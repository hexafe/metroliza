from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest

from scripts import measure_windows_startup_routes as routes

needs_posix_exec = pytest.mark.skipif(
    os.name == "nt", reason="fake executables are POSIX scripts"
)

FAKE_TEMPLATE = """#!{python}
import json, os, sys, time
from pathlib import Path

EXIT = {exit_code}
EVENTS = {events!r}
SLEEP = {sleep}
ALWAYS = {always!r}

root = os.environ.get("METROLIZA_RUNTIME_ROOT")
if root:
    marker = Path(root) / "runtime" / ".complete"
    pending = marker.with_name(".pending")
    outcome = ALWAYS or ("warm" if marker.exists() else "verified" if pending.exists() else "cold")
    marker.parent.mkdir(parents=True, exist_ok=True)
    if outcome == "cold":
        pending.write_text("pending")
    elif outcome == "verified":
        marker.write_text("complete")
        pending.unlink()
    with open(os.environ["METROLIZA_LAUNCHER_LOG"], "a", encoding="utf-8") as handle:
        handle.write("cache=" + outcome + "\\n")
time.sleep(SLEEP)
profile = os.environ["METROLIZA_STARTUP_PROFILE_PATH"]
assert os.environ["METROLIZA_STARTUP_UI_SMOKE"] == "1"
assert os.environ["METROLIZA_LICENSE_VERIFICATION"] == "0"
assert os.environ["METROLIZA_STARTUP_PROFILE"] == "1"
with open(profile, "a", encoding="utf-8") as handle:
    for name, offset, stamped in EVENTS:
        event = {{"name": name, "elapsed_ms": offset}}
        if stamped:
            event["epoch_ms"] = time.time() * 1000
        handle.write(json.dumps(event) + "\\n")
sys.exit(EXIT)
"""

GOOD_EVENTS = (
    ("process_entry", 5, True),
    ("main_window_show_called", 30, True),
    ("first_event_loop_tick", 35, True),
)


def fake_exe(
    tmp_path: Path, name: str, *, exit_code: int = 0, events=GOOD_EVENTS, sleep: float = 0.02,
    always: str | None = None,
) -> Path:
    path = tmp_path / name
    path.write_text(
        FAKE_TEMPLATE.format(
            python=sys.executable, exit_code=exit_code, events=tuple(events), sleep=sleep,
            always=always,
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def read_report(out: Path) -> dict:
    return json.loads((out / "startup-benchmark.json").read_text(encoding="utf-8"))


def test_profile_metrics_are_offsets_from_the_launch() -> None:
    events = [
        {"name": "process_entry", "elapsed_ms": 1, "epoch_ms": 1_000.0},
        {"name": "main_window_show_called", "elapsed_ms": 40, "epoch_ms": 1_400.0},
        {"name": "first_event_loop_tick", "elapsed_ms": 45, "epoch_ms": 1_450.0},
    ]
    metrics = routes.profile_metrics(events, launched_epoch_ms=900.0)
    assert metrics == {
        "pre_python_ms": 100.0,
        "first_paint_ms": 550.0,
        "python_first_paint_ms": 45.0,
        "window_shown_ms": 500.0,
    }


@pytest.mark.parametrize(
    "events,fragment",
    [
        ([], "first_event_loop_tick"),
        ([{"name": "process_entry", "elapsed_ms": 1, "epoch_ms": 5.0}], "first_event_loop_tick"),
        ([{"name": "first_event_loop_tick", "elapsed_ms": 1}], "epoch_ms"),
    ],
)
def test_profile_metrics_reject_missing_evidence(events, fragment) -> None:
    with pytest.raises(routes.RunFailure, match=fragment):
        routes.profile_metrics(events, 0.0)


def test_summary_uses_medians_of_successful_runs_only() -> None:
    runs = [
        {"status": "ok", "wall_ms": 100.0, "first_paint_ms": 80.0},
        {"status": "ok", "wall_ms": 300.0, "first_paint_ms": 280.0},
        {"status": "ok", "wall_ms": 200.0, "first_paint_ms": 180.0},
        {"status": "failed", "error": "x"},
    ]
    summary = routes.summarize_scenario(runs)
    assert summary["runs"] == 4 and summary["ok"] == 3
    assert summary["wall_ms"] == {"median": 200.0, "min": 100.0, "max": 300.0}
    assert summary["first_paint_ms"]["median"] == 180.0
    assert summary["window_shown_ms"]["median"] is None


def test_environment_runs_the_smoke_without_dialogs_or_inherited_python(tmp_path: Path) -> None:
    base = {
        "PATH": "/usr/bin", "HOME": "/home/x", "PYTHONPATH": "/leak", "PYTHONHOME": "/leak",
        "QT_QPA_PLATFORM": "xcb", "METROLIZA_STARTUP_SMOKE": "1",
        "METROLIZA_RUNTIME_REPAIR_AVAILABLE": "1", "VIRTUAL_ENV": "/venv",
    }
    env = routes.build_environment(
        tmp_path / "state", tmp_path / "temp", tmp_path / "p.jsonl", offscreen=False, base=base
    )
    assert env["METROLIZA_STARTUP_UI_SMOKE"] == "1"
    assert env["METROLIZA_STARTUP_PROFILE"] == "1"
    assert env["METROLIZA_STARTUP_PROFILE_PATH"] == str(tmp_path / "p.jsonl")
    assert env["METROLIZA_LICENSE_VERIFICATION"] == "0"
    assert env["METROLIZA_LAUNCHER_NO_UI"] == "1"
    for leaked in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM", "METROLIZA_STARTUP_SMOKE",
                   "METROLIZA_RUNTIME_REPAIR_AVAILABLE", "VIRTUAL_ENV"):
        assert leaked not in env
    offscreen = routes.build_environment(
        tmp_path / "state", tmp_path / "temp", tmp_path / "p.jsonl", offscreen=True, base=base
    )
    assert offscreen["QT_QPA_PLATFORM"] == "offscreen"


@needs_posix_exec
def test_all_routes_are_measured_with_fresh_cold_caches_and_one_warm_cache(tmp_path: Path) -> None:
    out = tmp_path / "out"
    portable = fake_exe(tmp_path, "portable")
    launcher = fake_exe(tmp_path, "launcher")

    code = routes.main([
        "--portable", str(portable), "--launcher", str(launcher),
        "--runs", "3", "--output-dir", str(out),
    ])

    assert code == 0
    report = read_report(out)
    assert report["passed"] is True
    assert list(report["scenarios"]) == ["portable_envelope", "launcher_cold", "launcher_verified", "launcher_warm"]
    for scenario in report["scenarios"].values():
        assert len(scenario["runs"]) == 3
        assert scenario["summary"]["ok"] == 3
        assert scenario["summary"]["wall_ms"]["median"] > 0
    # Every cold run saw an empty cache, every warm run the cache the first cold run filled.
    assert [r["cache"] for r in report["scenarios"]["launcher_cold"]["runs"]] == ["cold"] * 3
    verified = report["scenarios"]["launcher_verified"]["runs"]
    assert [r["cache"] for r in verified] == ["verified"] * 3
    assert [r["launch_number_in_cache"] for r in verified] == [2] * 3
    warm = report["scenarios"]["launcher_warm"]["runs"]
    assert [r["cache"] for r in warm] == ["warm"] * 3
    assert [r["launch_number_in_cache"] for r in warm] == [3, 4, 5]
    run = report["scenarios"]["portable_envelope"]["runs"][0]
    assert run["pre_python_ms"] >= 0
    assert run["first_paint_ms"] >= run["window_shown_ms"] >= run["pre_python_ms"]
    assert "cache" not in run
    assert set(report["comparison"]) == {
        "Launcher, cold cache (first launch)",
        "Launcher, verification (second launch)",
        "Launcher, warm cache (launches 3..N of one cache)",
    }
    assert report["sizes"]["launcher_runtime_cache_bytes"] > 0
    # Raw evidence is kept next to the summary.
    assert (out / "profiles" / "launcher_warm-3.jsonl").is_file()
    assert (out / "logs" / "launcher_cold-2.launcher.log").read_text().strip() == "cache=cold"
    markdown = (out / "startup-benchmark.md").read_text(encoding="utf-8")
    assert "| Portable envelope" in markdown and "| Launcher, warm cache" in markdown
    assert "Median to first paint" in markdown


@needs_posix_exec
def test_a_failed_run_still_writes_the_evidence_and_fails_the_job(tmp_path: Path) -> None:
    out = tmp_path / "out"
    broken = fake_exe(tmp_path, "broken", exit_code=3)

    code = routes.main(["--portable", str(broken), "--runs", "2", "--output-dir", str(out)])

    assert code == 1
    report = read_report(out)
    assert report["passed"] is False
    runs = report["scenarios"]["portable_envelope"]["runs"]
    assert [r["status"] for r in runs] == ["failed", "failed"]
    assert runs[0]["error"] == "exit code 3"
    assert "Failed runs" in (out / "startup-benchmark.md").read_text(encoding="utf-8")


@needs_posix_exec
def test_missing_profile_event_or_timestamp_is_a_failure_not_a_zero(tmp_path: Path) -> None:
    no_tick = fake_exe(tmp_path, "no_tick", events=(("process_entry", 1, True),))
    unstamped = fake_exe(tmp_path, "unstamped", events=(("first_event_loop_tick", 1, False),))
    for exe, fragment in ((no_tick, "first_event_loop_tick"), (unstamped, "epoch_ms")):
        out = tmp_path / f"out-{exe.name}"
        assert routes.main(["--portable", str(exe), "--runs", "1", "--output-dir", str(out)]) == 1
        error = read_report(out)["scenarios"]["portable_envelope"]["runs"][0]["error"]
        assert fragment in error


@needs_posix_exec
def test_launcher_runs_must_report_the_expected_cache_state(tmp_path: Path) -> None:
    out = tmp_path / "out"
    always_warm = fake_exe(tmp_path, "always_warm", always="warm")

    assert routes.main(["--launcher", str(always_warm), "--runs", "2", "--output-dir", str(out)]) == 1

    report = read_report(out)
    cold = report["scenarios"]["launcher_cold"]["runs"]
    assert all(r["status"] == "failed" and "expected cache=cold" in r["error"] for r in cold)
    # No valid cold run, so there is nothing to warm up and nothing is reported as measured.
    assert [r["status"] for r in report["scenarios"]["launcher_warm"]["runs"]] == ["failed"] * 2


@needs_posix_exec
def test_a_hanging_launch_is_killed_after_the_timeout(tmp_path: Path) -> None:
    out = tmp_path / "out"
    hanging = fake_exe(tmp_path, "hanging", sleep=30)

    code = routes.main([
        "--portable", str(hanging), "--runs", "1", "--timeout", "0.5", "--output-dir", str(out),
    ])

    assert code == 1
    assert "timed out" in read_report(out)["scenarios"]["portable_envelope"]["runs"][0]["error"]


def test_arguments_are_validated(tmp_path: Path, capsys) -> None:
    assert routes.main(["--output-dir", str(tmp_path)]) == 2
    assert routes.main(["--portable", str(tmp_path / "missing.exe")]) == 2
    capsys.readouterr()
