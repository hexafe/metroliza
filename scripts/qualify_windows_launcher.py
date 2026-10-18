#!/usr/bin/env python3
"""Qualify the native Metroliza launcher (packaging/launcher) against a built EXE.

Two modes:

* ``--synthetic``: builds a small synthetic onedir around ``launcher-test-entry`` and packs
  several versions of it with the real launcher stub and packer. Fast, deterministic, and the
  only mode that can exercise every scenario (second instance, version upgrade, kill during
  extraction).
* ``--exe PATH``: qualifies one real packed EXE (the Metroliza onedir) with
  ``METROLIZA_STARTUP_SMOKE=1``. Scenarios that need a long-running app or several versions are
  reported as skipped with a reason.

The launcher is always run with ``METROLIZA_RUNTIME_ROOT`` pointing at a temporary directory and
``METROLIZA_LAUNCHER_LOG`` set; its ``cache=...`` / ``instance=second`` log lines are the
evidence for cold/warm/repair/second-instance decisions. Results are printed and optionally
written as JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

IS_WINDOWS = os.name == "nt"
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""
MARKER = ".complete"
PENDING_MARKER = ".pending"
ENTRY_NAME = f"launcher-test-entry{EXE_SUFFIX}"
SHA_A, SHA_B, SHA_C, SHA_D = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)


class QualificationError(AssertionError):
    """A scenario assertion failed."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    """Relative POSIX path -> SHA-256 for every file below ``root`` except the marker."""
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {MARKER, PENDING_MARKER}
    }


class Harness:
    """Runs a packed launcher EXE against one cache root and reads its log."""

    def __init__(self, work: Path, extra_env: dict[str, str] | None = None) -> None:
        self.work = work
        self.root = work / "runtime-root"
        self.temp = work / "temp"
        self.temp.mkdir(parents=True, exist_ok=True)
        self.extra_env = extra_env or {}
        self._runs = 0

    def _env(self, log: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            METROLIZA_RUNTIME_ROOT=str(self.root),
            METROLIZA_LAUNCHER_LOG=str(log),
            METROLIZA_LAUNCHER_NO_UI="1",
            TEMP=str(self.temp),
            TMP=str(self.temp),
            TMPDIR=str(self.temp),
        )
        env.update(self.extra_env)
        return env

    def _next_log(self) -> Path:
        self._runs += 1
        return self.work / f"launcher-{self._runs:02d}.log"

    def start(self, exe: Path, *args: str) -> tuple[subprocess.Popen, Path]:
        log = self._next_log()
        proc = subprocess.Popen([str(exe), *args], env=self._env(log))
        return proc, log

    def run(self, exe: Path, *args: str, timeout: float = 300.0) -> dict:
        log = self._next_log()
        started = time.perf_counter()
        completed = subprocess.run([str(exe), *args], env=self._env(log), timeout=timeout)
        return {
            "returncode": completed.returncode,
            "seconds": time.perf_counter() - started,
            "log": read_log(log),
        }

    def version_dirs(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and ".staging-" not in p.name
        )

    def staging_dirs(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return [p for p in self.root.iterdir() if p.is_dir() and ".staging-" in p.name]


def read_log(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def wait_for(predicate, timeout: float, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def snapshot_mtimes(directory: Path) -> dict[str, int]:
    return {
        p.relative_to(directory).as_posix(): p.stat().st_mtime_ns
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------- synthetic payloads


def write_synthetic_onedir(directory: Path, test_entry: Path, filler_mb: int) -> None:
    """Entry binary, many small compressible files and incompressible filler blobs."""
    if directory.exists():
        shutil.rmtree(directory)
    (directory / "data").mkdir(parents=True)
    (directory / "blobs").mkdir()
    shutil.copy2(test_entry, directory / ENTRY_NAME)
    for index in range(150):
        text = f"synthetic data file {index}\n" * (50 + index)
        (directory / "data" / f"file_{index:03d}.txt").write_text(text, encoding="utf-8")
    (directory / "data" / "empty.dat").write_bytes(b"")
    blob_count = 16
    for index in range(blob_count):
        size = max(1, filler_mb) * 1024 * 1024 // blob_count
        (directory / "blobs" / f"blob_{index:02d}.bin").write_bytes(os.urandom(size))


def pack_exe(
    packer: Path,
    launcher: Path,
    onedir: Path,
    entry: str,
    version: str,
    sha: str,
    output: Path,
) -> dict:
    """Run the real packer; returns its JSON summary."""
    result = subprocess.run(
        [
            str(packer),
            "--input", str(onedir),
            "--entry", entry,
            "--version", version,
            "--git-sha", sha,
            "--stub", str(launcher),
            "--output", str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    check(result.returncode == 0, f"packer failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def dir_name(version: str, sha: str) -> str:
    return f"{version}_{sha[:8]}"


# ---------------------------------------------------------------- scenarios


def scenario_first_run(h: Harness, exe: Path, summary: dict, onedir: Path | None, args) -> dict:
    result = h.run(exe, *args)
    target = h.root / summary["dir_name"]
    check(result["returncode"] == args_exit_code(args), f"exit code {result['returncode']}")
    check("cache=cold" in result["log"], f"expected cache=cold, log: {result['log']}")
    check(target.is_dir(), "version directory was not created")
    check(not (target / MARKER).exists(), "cold cache was completed without verification")
    marker = (target / PENDING_MARKER).read_text(encoding="utf-8").strip()
    check(marker == summary["manifest_sha256"], "marker does not hold the manifest hash")
    check(not h.staging_dirs(), "staging directory left behind")
    if onedir is not None:
        check(tree_hashes(target) == tree_hashes(onedir), "extracted tree differs from source")
    return {"seconds": round(result["seconds"], 3)}


def scenario_verify_pending(h: Harness, exe: Path, summary: dict, args) -> dict:
    target = h.root / summary["dir_name"]
    check((target / PENDING_MARKER).is_file(), "pending marker missing")
    before = {k: v for k, v in snapshot_mtimes(target).items() if k != PENDING_MARKER}
    result = h.run(exe, *args)
    check(result["returncode"] == args_exit_code(args), f"exit code {result['returncode']}")
    check("cache=verified" in result["log"], f"expected verification: {result['log']}")
    check(not (target / PENDING_MARKER).exists(), "pending marker survived promotion")
    check((target / MARKER).read_text().strip() == summary["manifest_sha256"], "complete marker mismatch")
    after = {k: v for k, v in snapshot_mtimes(target).items() if k != MARKER}
    check(before == after, "verification rewrote payload files")
    return {"seconds": round(result["seconds"], 3)}


def scenario_warm_run(
    h: Harness, exe: Path, summary: dict, cold_seconds: float, args, onedir: Path | None
) -> dict:
    target = h.root / summary["dir_name"]
    before = snapshot_mtimes(target)
    result = h.run(exe, *args)
    check(result["returncode"] == args_exit_code(args), f"exit code {result['returncode']}")
    check("cache=warm" in result["log"], f"expected cache=warm, log: {result['log']}")
    check(snapshot_mtimes(target) == before, "warm run modified the cache")
    check(not h.staging_dirs(), "warm run created a staging directory")
    if onedir is not None:
        check(
            result["seconds"] <= cold_seconds,
            f"warm {result['seconds']:.2f}s is slower than cold {cold_seconds:.2f}s",
        )
    return {"seconds": round(result["seconds"], 3), "cold_seconds": round(cold_seconds, 3)}


def args_exit_code(args) -> int:
    """Expected exit code for synthetic runs (``--exit-code N``); 0 otherwise."""
    if "--exit-code" in args:
        return int(args[args.index("--exit-code") + 1])
    return 0


def scenario_second_instance(h: Harness, exe: Path, summary: dict) -> dict:
    stop = h.work / "stop-first"
    record = h.work / "record-second-instance.txt"
    for leftover in (stop, record):
        leftover.unlink(missing_ok=True)
    first, first_log = h.start(
        exe, "--record", str(record), "--stop-file", str(stop), "--sleep-ms", "60000"
    )
    try:
        check(
            wait_for(lambda: record.exists() and record.read_text().count("started") == 1, 60),
            "first instance did not start its entry process",
        )
        staging_before = len(h.staging_dirs())
        second = h.run(exe, "--record", str(record), "--sleep-ms", "0", timeout=60)
        check("instance=second" in second["log"], f"second log: {second['log']}")
        check("cache=" not in "\n".join(second["log"]), "second instance touched the cache")
        check(record.read_text().count("started") == 1, "second instance started the entry")
        check(len(h.staging_dirs()) == staging_before, "second instance extracted")
    finally:
        stop.write_text("stop", encoding="utf-8")
        try:
            first.wait(timeout=60)
        except subprocess.TimeoutExpired:
            first.kill()
            raise
    check(first.returncode == 0, f"first instance exit code {first.returncode}")
    check("exit=0" in read_log(first_log), "first instance did not finish normally")
    return {"second_seconds": round(second["seconds"], 3)}


def scenario_corrupted_cache(
    h: Harness, exe: Path, summary: dict, onedir: Path | None, args, victims: list[str]
) -> dict:
    target = h.root / summary["dir_name"]
    check(len(victims) >= 2, "need two files to damage")
    (target / victims[0]).write_bytes(b"x")  # truncated
    (target / victims[1]).unlink()  # deleted
    result = h.run(exe, *args)
    check(result["returncode"] == args_exit_code(args), f"exit code {result['returncode']}")
    check("cache=repair" in result["log"], f"expected cache=repair, log: {result['log']}")
    check((target / victims[0]).stat().st_size > 1, "truncated file was not restored")
    check((target / victims[1]).is_file(), "deleted file was not restored")
    if onedir is not None:
        check(tree_hashes(target) == tree_hashes(onedir), "repaired tree differs from source")
    return {"seconds": round(result["seconds"], 3)}


def scenario_upgrade(h: Harness, exes: dict[str, tuple[Path, dict]], args) -> dict:
    (exe2, sum2), (exe3, sum3) = exes["v2"], exes["v3"]
    first_dir = exes["v1"][1]["dir_name"]
    for exe in (exe2, exe3):
        result = h.run(exe, *args)
        check(result["returncode"] == args_exit_code(args), f"exit code {result['returncode']}")
        check("cache=cold" in result["log"], f"expected cache=cold, log: {result['log']}")
    expected = sorted([sum2["dir_name"], sum3["dir_name"]])
    check(h.version_dirs() == expected, f"expected {expected}, found {h.version_dirs()}")
    check(first_dir not in h.version_dirs(), "oldest version was not removed")
    check(not (h.root / f"{first_dir}.use").exists(), "oldest version's lock file left behind")
    return {"kept": expected, "removed": first_dir}


def scenario_kill_during_extraction(h: Harness, exe: Path, summary: dict, onedir: Path) -> dict:
    target = h.root / summary["dir_name"]
    record = h.work / "record-kill.txt"
    record.unlink(missing_ok=True)

    def staging_has_files() -> bool:
        return any(any(p.rglob("*")) for p in h.staging_dirs())

    proc, _ = h.start(exe, "--record", str(record))
    try:
        seen = wait_for(lambda: staging_has_files() or proc.poll() is not None, 120, 0.002)
        check(seen and proc.poll() is None, "extraction finished before it could be interrupted")
        proc.kill()
    finally:
        proc.wait(timeout=60)
    check(not record.exists(), "entry process started although extraction was interrupted")
    check(not (target / MARKER).exists(), "interrupted extraction produced a usable cache")
    result = h.run(exe, "--record", str(record))
    check(result["returncode"] == 0, f"repair run exit code {result['returncode']}")
    check(
        any(line in ("cache=cold", "cache=repair") for line in result["log"]),
        f"expected a fresh extraction, log: {result['log']}",
    )
    check(not h.staging_dirs(), "stale staging directory survived the next run")
    check(tree_hashes(target) == tree_hashes(onedir), "repaired tree differs from source")
    return {"seconds": round(result["seconds"], 3)}


def repair_variable_per_start(record: Path) -> list[str]:
    """Value of METROLIZA_RUNTIME_REPAIR_AVAILABLE the test entry saw at each start."""
    return [
        line.rsplit("repair_available=", 1)[1]
        for line in record.read_text(encoding="utf-8").splitlines()
        if line.startswith("started ")
    ]


def scenario_self_repair(h: Harness, exe: Path, summary: dict) -> dict:
    """Exit code 75 re-extracts the runtime and restarts the entry once, without the variable."""
    target = h.root / summary["dir_name"]
    victim = target / "data" / "file_000.txt"
    original = victim.read_bytes()
    # The preceding repair left pending: complete it before testing the size-only warm path.
    verified = h.run(exe, "--exit-code", "0")
    check("cache=verified" in verified["log"], "repaired runtime was not verified")
    # Same size, different content: the size-only warm check cannot see this.
    victim.write_bytes(bytes([original[0] ^ 0xFF]) + original[1:])
    record = h.work / "record-self-repair.txt"
    record.unlink(missing_ok=True)

    repaired = h.run(
        exe, "--record", str(record), "--request-repair", "--exit-code", "0", timeout=300.0
    )
    check(repaired["returncode"] == 0, f"exit code {repaired['returncode']} after repair")
    check("repair=requested" in repaired["log"], f"no repair request: {repaired['log']}")
    check("cache=repair" in repaired["log"], f"no re-extraction: {repaired['log']}")
    check(
        repair_variable_per_start(record) == ["1", "unset"],
        f"starts/variable: {repair_variable_per_start(record)}",
    )
    check(victim.read_bytes() == original, "damaged file was not restored")
    check(not h.staging_dirs(), "staging directory left behind")

    # A second 75 is final: no loop, the second run's exit code is returned.
    record.unlink()
    twice = h.run(exe, "--record", str(record), "--exit-code", "75", timeout=300.0)
    check(twice["returncode"] == 75, f"exit code {twice['returncode']} after two requests")
    check(repair_variable_per_start(record) == ["1", "unset"], "second 75 must not loop")
    check(
        sum(line == "repair=requested" for line in twice["log"]) == 1,
        f"repair requested more than once: {twice['log']}",
    )

    # Ordinary exit codes pass through unchanged and are never restarted.
    record.unlink()
    plain = h.run(exe, "--record", str(record), "--exit-code", "9", timeout=300.0)
    check(plain["returncode"] == 9, f"exit code {plain['returncode']} was altered")
    check(repair_variable_per_start(record) == ["1"], "ordinary exit code restarted the entry")
    return {"seconds": round(repaired["seconds"], 3)}


def scenario_no_temp_use(h: Harness) -> dict:
    leftovers = sorted(p.name for p in h.temp.iterdir())
    check(not leftovers, f"launcher runs left files in TEMP: {leftovers}")
    return {}


# ---------------------------------------------------------------- drivers


class Report:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def run(self, name: str, func, *func_args, **func_kwargs):
        started = time.perf_counter()
        entry = {"name": name}
        try:
            detail = func(*func_args, **func_kwargs) or {}
            entry.update(status="passed", **detail)
        except (QualificationError, subprocess.SubprocessError, OSError) as exc:
            entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        entry["total_seconds"] = round(time.perf_counter() - started, 3)
        self.entries.append(entry)
        print(f"[{entry['status']:>7}] {name}" + (f" - {entry['error']}" if "error" in entry else ""))
        return entry

    def skip(self, name: str, reason: str) -> None:
        self.entries.append({"name": name, "status": "skipped", "reason": reason})
        print(f"[skipped] {name} - {reason}")

    @property
    def passed(self) -> bool:
        return all(e["status"] != "failed" for e in self.entries)


def qualify_synthetic(args, work: Path, report: Report) -> None:
    launcher, packer, test_entry = (Path(p).resolve() for p in (args.launcher, args.packer, args.test_entry))
    onedir = work / "onedir"
    write_synthetic_onedir(onedir, test_entry, args.filler_mb)
    exes: dict[str, tuple[Path, dict]] = {}
    for key, version, sha in (
        ("v1", "1.0.0", SHA_A),
        ("v2", "2.0.0", SHA_B),
        ("v3", "3.0.0", SHA_C),
        ("v4", "4.0.0", SHA_D),
    ):
        output = work / f"metroliza_synthetic_{key}{EXE_SUFFIX}"
        exes[key] = (output, pack_exe(packer, launcher, onedir, ENTRY_NAME, version, sha, output))

    h = Harness(work)
    exe1, sum1 = exes["v1"]
    run_args = ("--exit-code", "5")
    cold = report.run("first_run_cold", scenario_first_run, h, exe1, sum1, onedir, run_args)
    cold_seconds = cold.get("seconds", 0.0)
    report.run("pending_verified", scenario_verify_pending, h, exe1, sum1, run_args)
    report.run("warm_run", scenario_warm_run, h, exe1, sum1, cold_seconds, run_args, onedir)
    if IS_WINDOWS:
        report.run("second_instance", scenario_second_instance, h, exe1, sum1)
    else:
        report.skip("second_instance", "single-instance guard exists only in the Windows build")
    report.run(
        "corrupted_cache_repaired",
        scenario_corrupted_cache,
        h, exe1, sum1, onedir, run_args,
        ["blobs/blob_00.bin", "data/file_000.txt"],
    )
    report.run("self_repair_exit_75", scenario_self_repair, h, exe1, sum1)
    report.run("version_upgrade_cleanup", scenario_upgrade, h, exes, ("--exit-code", "0"))
    exe4, sum4 = exes["v4"]
    report.run("kill_during_extraction", scenario_kill_during_extraction, h, exe4, sum4, onedir)
    report.run("no_temp_use", scenario_no_temp_use, h)


def qualify_real_app(args, work: Path, report: Report) -> None:
    exe = Path(args.exe).resolve()
    check(exe.is_file(), f"EXE not found: {exe}")
    h = Harness(work, extra_env={"METROLIZA_STARTUP_SMOKE": "1"})
    # No packer summary exists for an already built EXE: the version directory is whatever
    # single directory the first run creates.
    state: dict = {}

    def first_run() -> dict:
        result = h.run(exe)
        check(result["returncode"] == 0, f"smoke exit code {result['returncode']}")
        check("cache=cold" in result["log"], f"expected cache=cold, log: {result['log']}")
        dirs = h.version_dirs()
        check(len(dirs) == 1, f"expected one version directory, found {dirs}")
        check((h.root / dirs[0] / PENDING_MARKER).is_file(), "pending marker missing")
        state.update(dir=h.root / dirs[0], cold=result["seconds"])
        return {"seconds": round(result["seconds"], 3), "dir": dirs[0]}

    def verify_pending() -> dict:
        result = h.run(exe)
        check(result["returncode"] == 0, f"smoke exit code {result['returncode']}")
        check("cache=verified" in result["log"], f"expected cache=verified: {result['log']}")
        check((state["dir"] / MARKER).is_file(), "completion marker missing")
        check(not (state["dir"] / PENDING_MARKER).exists(), "pending marker remained")
        return {"seconds": round(result["seconds"], 3)}

    def warm_run() -> dict:
        before = snapshot_mtimes(state["dir"])
        result = h.run(exe)
        check(result["returncode"] == 0, f"smoke exit code {result['returncode']}")
        check("cache=warm" in result["log"], f"expected cache=warm, log: {result['log']}")
        check(snapshot_mtimes(state["dir"]) == before, "warm run modified the cache")
        return {"seconds": round(result["seconds"], 3), "cold_seconds": round(state["cold"], 3)}

    def corrupted() -> dict:
        files = sorted(
            (p for p in state["dir"].rglob("*") if p.is_file() and p.name != MARKER),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        check(len(files) >= 2, "unexpectedly small runtime")
        size = files[0].stat().st_size
        files[0].write_bytes(b"x")
        files[1].unlink()
        result = h.run(exe)
        check(result["returncode"] == 0, f"smoke exit code {result['returncode']}")
        check("cache=repair" in result["log"], f"expected cache=repair, log: {result['log']}")
        check(files[0].stat().st_size == size and files[1].is_file(), "files not restored")
        return {"seconds": round(result["seconds"], 3)}

    def no_mei() -> dict:
        found = sorted(p.name for p in h.temp.glob("_MEI*"))
        check(not found, f"PyInstaller extraction directories found in TEMP: {found}")
        return {}

    if report.run("first_run_cold", first_run)["status"] != "passed":
        return
    report.run("pending_verified", verify_pending)
    report.run("warm_run", warm_run)
    report.skip("second_instance", "startup smoke exits immediately; use --synthetic")
    report.run("corrupted_cache_repaired", corrupted)
    report.skip("version_upgrade_cleanup", "needs several packed versions; use --synthetic")
    report.skip("kill_during_extraction", "needs a controllable payload; use --synthetic")
    report.run("no_pyinstaller_extraction_in_temp", no_mei)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic", action="store_true", help="build and qualify synthetic EXEs")
    mode.add_argument("--exe", help="qualify this real packed Metroliza EXE")
    mode.add_argument(
        "--write-synthetic-onedir",
        metavar="DIR",
        help="only write the synthetic onedir (for exercising the packaging script)",
    )
    parser.add_argument("--launcher", help="unsigned launcher stub (metroliza-launcher[.exe])")
    parser.add_argument("--packer", help="metroliza-packer[.exe]")
    parser.add_argument("--test-entry", help="launcher-test-entry[.exe]")
    parser.add_argument("--filler-mb", type=int, default=128, help="incompressible payload size")
    parser.add_argument("--work-dir", help="working directory (default: a new temp directory)")
    parser.add_argument("--output", help="write the JSON report here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.write_synthetic_onedir:
        if not args.test_entry:
            print("--test-entry is required", file=sys.stderr)
            return 2
        write_synthetic_onedir(
            Path(args.write_synthetic_onedir), Path(args.test_entry), args.filler_mb
        )
        return 0
    if args.synthetic and not (args.launcher and args.packer and args.test_entry):
        print("--synthetic needs --launcher, --packer and --test-entry", file=sys.stderr)
        return 2

    own_work = args.work_dir is None
    work = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="qualify-launcher-"))
    work.mkdir(parents=True, exist_ok=True)
    report = Report()
    try:
        if args.synthetic:
            qualify_synthetic(args, work, report)
        else:
            qualify_real_app(args, work, report)
    finally:
        payload = {
            "schema": "metroliza.launcher_qualification.v1",
            "mode": "synthetic" if args.synthetic else "real-app",
            "platform": sys.platform,
            "passed": report.passed,
            "scenarios": report.entries,
        }
        if args.output:
            Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if own_work:
            shutil.rmtree(work, ignore_errors=True)
    print("PASSED" if report.passed else "FAILED")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
