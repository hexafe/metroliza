#!/usr/bin/env python3
"""Measure real-application startup through the shipped Windows delivery routes.

The same non-interactive startup smoke is run through each route:

* ``portable_envelope``: the PyInstaller envelope (``metroliza_<label>.exe``), which extracts the
  whole supervised onedir to ``%TEMP%`` on every launch;
* ``launcher_cold``: the native launcher EXE (``metroliza_<label>_launcher.exe``) with an empty
  runtime cache (a fresh ``METROLIZA_RUNTIME_ROOT`` for every run);
* ``launcher_warm``: the same launcher EXE again on an already populated cache. The first warm
  sample is the second launch of that cache, the next the third, and so on.

The smoke is ``METROLIZA_STARTUP_UI_SMOKE=1`` (see ``metroliza.app.bootstrap.launch_ui``): the
application constructs and shows the real main window and exits after the first Qt event-loop
tick. ``METROLIZA_LICENSE_VERIFICATION=0`` keeps the license dialog away. The supervisor
(``metroliza.exe``) passes its environment on to ``metroliza_application.exe`` unchanged, so the
same variables work through the supervised chain. Nothing here can open an interactive dialog;
every run is bounded by a timeout and its process tree is killed when it expires.

Each run reports the wall time of the whole launch (process creation to exit) and, from the
startup profile (``METROLIZA_STARTUP_PROFILE``), the time from the moment this script started the
EXE to the application's ``main_window_show_called`` and ``first_event_loop_tick`` events. Those
events carry a wall-clock ``epoch_ms``, so the numbers include the bootloader or launcher, cache
extraction and the supervisor, which the in-process ``elapsed_ms`` cannot see.

``first_paint_ms`` is the first event-loop tick after ``QWidget.show()``: the first moment at
which the event loop has had the chance to deliver the initial paint of the main window. It is
not a GPU frame time. With ``--offscreen`` the Qt platform is ``offscreen`` and nothing is shown
on a desktop; the default uses the real Windows platform plugin.

Writes ``startup-benchmark.json`` and ``startup-benchmark.md`` (plus the raw profiles and launcher
logs) into ``--output-dir``, prints the table, and appends it to ``$GITHUB_STEP_SUMMARY`` when set.
The exit status is 1 if any run failed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

SCHEMA = "metroliza.startup_routes.v1"
REQUIRED_EVENT = "first_event_loop_tick"
WINDOW_EVENT = "main_window_show_called"
CACHE_PREFIX = "cache="

#: Variables copied from the parent environment. The rest is rebuilt so the result does not depend
#: on whatever Python or Qt installation the runner happens to expose.
WINDOWS_KEEP = (
    "SystemRoot", "WINDIR", "SystemDrive", "COMSPEC", "PATHEXT", "USERNAME", "USERDOMAIN",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "ProgramData", "ProgramFiles", "ProgramFiles(x86)",
    "ALLUSERSPROFILE", "PUBLIC", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    "COMPUTERNAME",
)


class RunFailure(RuntimeError):
    """One launch did not produce valid evidence."""


# ---------------------------------------------------------------- pure helpers


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _first(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matching = [event for event in events if event.get("name") == name]
    if not matching:
        return None
    return min(matching, key=lambda event: float(event.get("epoch_ms") or float("inf")))


def profile_metrics(events: list[dict[str, Any]], launched_epoch_ms: float) -> dict[str, float]:
    """Time offsets from the launch to the profile events, all in milliseconds."""
    tick = _first(events, REQUIRED_EVENT)
    if tick is None:
        raise RunFailure(f"startup profile is missing the required event '{REQUIRED_EVENT}'")
    stamped = [e for e in events if isinstance(e.get("epoch_ms"), (int, float))]
    if not stamped or not isinstance(tick.get("epoch_ms"), (int, float)):
        raise RunFailure("startup profile events carry no epoch_ms (build predates the stamp)")
    shown = _first(events, WINDOW_EVENT)
    metrics = {
        "pre_python_ms": min(float(e["epoch_ms"]) for e in stamped) - launched_epoch_ms,
        "first_paint_ms": float(tick["epoch_ms"]) - launched_epoch_ms,
        "python_first_paint_ms": float(tick.get("elapsed_ms") or 0.0),
    }
    if shown is not None and isinstance(shown.get("epoch_ms"), (int, float)):
        metrics["window_shown_ms"] = float(shown["epoch_ms"]) - launched_epoch_ms
    return {key: round(value, 1) for key, value in metrics.items()}


def launcher_cache_outcome(log_path: Path) -> str | None:
    """Last ``cache=...`` value the launcher logged (``cold``, ``warm`` or ``repair``)."""
    outcome = None
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(CACHE_PREFIX):
                outcome = line[len(CACHE_PREFIX):].strip()
    return outcome


def summarize(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "min": None, "max": None}
    return {
        "median": round(statistics.median(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def summarize_scenario(runs: list[dict[str, Any]]) -> dict[str, Any]:
    good = [run for run in runs if run["status"] == "ok"]
    summary: dict[str, Any] = {
        "runs": len(runs),
        "ok": len(good),
        "wall_ms": summarize([run["wall_ms"] for run in good]),
    }
    for key in ("first_paint_ms", "window_shown_ms", "pre_python_ms", "python_first_paint_ms"):
        summary[key] = summarize([run[key] for run in good if key in run])
    return summary


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "## Windows startup by delivery route",
        "",
        "Real application, `METROLIZA_STARTUP_UI_SMOKE=1` (main window shown, exit after the first "
        "event-loop tick). Times in ms, medians of the samples; the launch is timed from process "
        "creation.",
        "",
        "| Route | OK/runs | Median wall | Median to first paint | Median to window shown "
        "| Median before Python | Wall min-max |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for name, scenario in report["scenarios"].items():
        summary = scenario["summary"]
        wall = summary["wall_ms"]
        span = "n/a" if wall["min"] is None else f"{_ms(wall['min'])}-{_ms(wall['max'])}"
        lines.append(
            f"| {scenario['label']} | {summary['ok']}/{summary['runs']} | {_ms(wall['median'])} "
            f"| {_ms(summary['first_paint_ms']['median'])} "
            f"| {_ms(summary['window_shown_ms']['median'])} "
            f"| {_ms(summary['pre_python_ms']['median'])} | {span} |"
        )
    comparison = report.get("comparison", {})
    if comparison:
        lines += ["", "Median first paint relative to the portable envelope:", ""]
        for name, ratio in comparison.items():
            lines.append(f"* {name}: {ratio:.2f}x of the envelope")
    sizes = report.get("sizes", {})
    if sizes:
        lines += ["", "Sizes: " + ", ".join(f"{key} {value:,} bytes" for key, value in sizes.items())]
    failed = [
        f"{run['scenario']} #{run['index']}: {run['error']}"
        for scenario in report["scenarios"].values()
        for run in scenario["runs"]
        if run["status"] != "ok"
    ]
    if failed:
        lines += ["", "Failed runs:", ""] + [f"* {item}" for item in failed]
    lines += [
        "",
        "`first paint` = first Qt event-loop tick after the main window `show()`; "
        "`before Python` = launch to the first profile event of the application "
        "(bootloader, extraction or launcher, supervisor). Hosted-runner numbers are "
        "indicative only: they are not a clean-machine measurement.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- running one launch


def build_environment(
    state: Path, temp: Path, profile: Path, *, offscreen: bool, base: dict[str, str] | None = None
) -> dict[str, str]:
    base = dict(os.environ if base is None else base)
    if os.name == "nt":
        env = {key: base[key] for key in WINDOWS_KEEP if key in base}
        windows = base.get("SystemRoot") or base.get("WINDIR") or r"C:\Windows"
        env["PATH"] = str(Path(windows) / "System32") + ";" + windows
    else:
        env = {key: base[key] for key in ("PATH", "HOME", "LANG") if key in base}
    env.update(
        TEMP=str(temp),
        TMP=str(temp),
        TMPDIR=str(temp),
        LOCALAPPDATA=str(state),
        APPDATA=str(state / "Roaming"),
        METROLIZA_STARTUP_PROFILE="1",
        METROLIZA_STARTUP_PROFILE_PATH=str(profile),
        METROLIZA_STARTUP_UI_SMOKE="1",
        METROLIZA_LICENSE_VERIFICATION="0",
        METROLIZA_LAUNCHER_NO_UI="1",
    )
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def _kill_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        process.kill()


def launch_once(exe: Path, env: dict[str, str], cwd: Path, timeout: float) -> tuple[int, float, float]:
    """Run ``exe``; returns (exit code, wall ms, wall-clock epoch ms at launch)."""
    launched_epoch_ms = time.time() * 1000
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(exe)], env=env, cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        process.wait(timeout=60)
        raise RunFailure(f"timed out after {timeout:.0f} s") from None
    return code, (time.perf_counter() - started) * 1000, launched_epoch_ms


def directory_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


class Benchmark:
    def __init__(self, out: Path, *, runs: int, timeout: float, offscreen: bool) -> None:
        self.out = out
        self.runs = runs
        self.timeout = timeout
        self.offscreen = offscreen
        self.work = Path(tempfile.mkdtemp(prefix="metroliza-startup-"))
        self.state = self.work / "state"
        self.temp = self.work / "temp"
        self.cwd = self.work / "cwd"
        for directory in (self.state / "Roaming", self.temp, self.cwd, out / "profiles", out / "logs"):
            directory.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def run(
        self, scenario: str, index: int, exe: Path, *, root: Path | None, expect_cache: str | None
    ) -> dict[str, Any]:
        """One launch, validated; never raises, a failure is recorded in the run."""
        profile = self.out / "profiles" / f"{scenario}-{index}.jsonl"
        log = self.out / "logs" / f"{scenario}-{index}.launcher.log"
        for stale in (profile, log):
            stale.unlink(missing_ok=True)
        env = build_environment(self.state, self.temp, profile, offscreen=self.offscreen)
        if root is not None:
            env["METROLIZA_RUNTIME_ROOT"] = str(root)
            env["METROLIZA_LAUNCHER_LOG"] = str(log)
        record: dict[str, Any] = {
            "scenario": scenario, "index": index, "status": "ok",
            "profile": profile.relative_to(self.out).as_posix(),
        }
        try:
            code, wall_ms, launched = launch_once(exe, env, self.cwd, self.timeout)
            record.update(exit_code=code, wall_ms=round(wall_ms, 1))
            if code != 0:
                raise RunFailure(f"exit code {code}")
            record.update(profile_metrics(load_events(profile), launched))
            if root is not None:
                outcome = launcher_cache_outcome(log)
                record["cache"] = outcome
                record["launcher_log"] = log.relative_to(self.out).as_posix()
                if expect_cache is not None and outcome != expect_cache:
                    raise RunFailure(f"expected cache={expect_cache}, launcher logged {outcome}")
            leftovers = sorted(p.name for p in self.temp.iterdir())
            record["temp_leftovers"] = leftovers
        except RunFailure as error:
            record.update(status="failed", error=str(error))
        except OSError as error:
            record.update(status="failed", error=f"{type(error).__name__}: {error}")
        shown = record.get("first_paint_ms")
        print(
            f"  {scenario} #{index}: {record['status']} wall={record.get('wall_ms')} ms "
            f"first_paint={shown} ms" + (f" ({record['error']})" if "error" in record else ""),
            flush=True,
        )
        return record


def measure_portable(bench: Benchmark, exe: Path, runs: int) -> dict[str, Any]:
    print("portable envelope", flush=True)
    samples = [
        bench.run("portable_envelope", i, exe, root=None, expect_cache=None)
        for i in range(1, runs + 1)
    ]
    return {"label": "Portable envelope (extracts every launch)", "runs": samples}


def measure_launcher_cold(
    bench: Benchmark, exe: Path, runs: int, sizes: dict[str, int]
) -> tuple[dict[str, Any], Path | None]:
    """Cold runs, each on a fresh cache; the first valid cache is kept for the warm runs."""
    print("launcher cold", flush=True)
    roots = bench.work / "roots"
    warm_root = None
    samples = []
    for i in range(1, runs + 1):
        root = roots / f"cold-{i}"
        samples.append(bench.run("launcher_cold", i, exe, root=root, expect_cache="cold"))
        if i == 1 and samples[0]["status"] == "ok":
            warm_root = root
            sizes["launcher_runtime_cache_bytes"] = directory_bytes(root)
        else:
            shutil.rmtree(root, ignore_errors=True)
    return {"label": "Launcher, cold cache (first launch)", "runs": samples}, warm_root


def measure_launcher_warm(
    bench: Benchmark, exe: Path, runs: int, warm_root: Path | None
) -> dict[str, Any]:
    print("launcher warm", flush=True)
    samples = []
    for i in range(1, runs + 1):
        if warm_root is None:
            samples.append({
                "scenario": "launcher_warm", "index": i, "status": "failed",
                "error": "no valid cold run to warm up",
            })
            continue
        run = bench.run("launcher_warm", i, exe, root=warm_root, expect_cache="warm")
        run["launch_number_in_cache"] = i + 1
        samples.append(run)
    return {"label": "Launcher, warm cache (launches 2..N of one cache)", "runs": samples}


def compare_with_envelope(scenarios: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Median first paint of each launcher scenario relative to the portable envelope."""

    def median(name: str) -> float | None:
        return scenarios.get(name, {}).get("summary", {}).get("first_paint_ms", {}).get("median")

    base = median("portable_envelope")
    comparison: dict[str, float] = {}
    for name in ("launcher_cold", "launcher_warm"):
        value = median(name)
        if base and value:
            comparison[scenarios[name]["label"]] = value / base
    return comparison


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bench = Benchmark(out, runs=args.runs, timeout=args.timeout, offscreen=args.offscreen)
    scenarios: dict[str, dict[str, Any]] = {}
    sizes: dict[str, int] = {}
    try:
        if args.portable:
            exe = Path(args.portable).resolve()
            sizes["portable_envelope_exe"] = exe.stat().st_size
            scenarios["portable_envelope"] = measure_portable(bench, exe, args.runs)
        if args.launcher:
            exe = Path(args.launcher).resolve()
            sizes["launcher_exe"] = exe.stat().st_size
            scenarios["launcher_cold"], warm_root = measure_launcher_cold(
                bench, exe, args.runs, sizes
            )
            scenarios["launcher_warm"] = measure_launcher_warm(bench, exe, args.runs, warm_root)
    finally:
        bench.close()

    for scenario in scenarios.values():
        scenario["summary"] = summarize_scenario(scenario["runs"])
    return {
        "schema": SCHEMA,
        "runs_per_scenario": args.runs,
        "smoke": "METROLIZA_STARTUP_UI_SMOKE=1",
        "qt_platform": "offscreen" if args.offscreen else "default (windows)",
        "platform": platform.platform(),
        "git_sha": os.environ.get("GITHUB_SHA"),
        "sizes": sizes,
        "scenarios": scenarios,
        "comparison": compare_with_envelope(scenarios),
        "passed": bool(scenarios)
        and all(run["status"] == "ok" for s in scenarios.values() for run in s["runs"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--portable", help="portable envelope EXE (metroliza_<label>.exe)")
    parser.add_argument("--launcher", help="native launcher EXE (metroliza_<label>_launcher.exe)")
    parser.add_argument("--runs", type=int, default=3, help="samples per scenario (default 3)")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds per launch")
    parser.add_argument("--offscreen", action="store_true", help="QT_QPA_PLATFORM=offscreen")
    parser.add_argument("--output-dir", default="startup-artifacts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.portable or args.launcher):
        print("give --portable and/or --launcher", file=sys.stderr)
        return 2
    if args.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2
    for name in ("portable", "launcher"):
        path = getattr(args, name)
        if path and not Path(path).is_file():
            print(f"--{name}: not a file: {path}", file=sys.stderr)
            return 2
    report = run_benchmark(args)
    out = Path(args.output_dir)
    (out / "startup-benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    (out / "startup-benchmark.md").write_text(markdown, encoding="utf-8")
    print()
    print(markdown)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    print("PASSED" if report["passed"] else "FAILED")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
