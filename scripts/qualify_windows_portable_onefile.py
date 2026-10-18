"""Bounded native smoke of the single visible supervised Windows executable.

Two delivery routes carry the same supervised onedir and are qualified with the same scenarios
(first launch, reopen, hard exit, incident export, extraction cleanup):

* ``--kind envelope`` (default): the PyInstaller envelope, ``metroliza_<label>.exe``.
* ``--kind launcher``: the native launcher, ``metroliza_<label>_launcher.exe``. The runtime cache
  is the production default (``%LOCALAPPDATA%\\Metroliza\\runtime`` below the private state
  directory), so the first launch must be ``cache=cold`` and every later one ``cache=warm``, and
  exactly one complete runtime directory must exist at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/pdf/cmm_smoke_fixture.pdf"
FIXTURE_SHA256 = "ca500bd52afc2551560e7c0009851906a0d3bec6b35282e20703c1e298da608b"


def _receipt(root: Path, scenario: str) -> None:
    path = root / "qualification-complete.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("schema_version") != 1 or payload.get("scenario") != scenario
            or payload.get("stage") != "complete" or payload.get("packaged") is not True
            or payload.get("console_none") is not True):
        raise RuntimeError("portable_receipt_invalid")
    if (root / "qualification-failed.json").exists() or (root / "failure.json").exists():
        raise RuntimeError("portable_child_failed")


RUNTIME_DIR_PATTERN = re.compile(
    r"^[0-9]{4}\.[0-9]{2}[a-z0-9]+_[0-9]{6}-[0-9a-f]{12}_[0-9a-f]{8}$"
)


def _expect_cache(log: Path, expected: str) -> None:
    """The launcher logs ``cache=cold|warm|repair``; the last such line must equal ``expected``."""
    outcomes = []
    if log.is_file():
        outcomes = [
            line.split("=", 1)[1].strip()
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("cache=")
        ]
    if not outcomes or outcomes[-1] != expected:
        raise RuntimeError(f"launcher_cache_{expected}_expected_got_{outcomes[-1:] or 'none'}")


def _runtime_layout(runtime_root: Path) -> str:
    """Exactly one complete, content-keyed runtime directory and no leftovers; returns its name."""
    if not runtime_root.is_dir():
        raise RuntimeError("launcher_runtime_root_missing")
    names = sorted(path.name for path in runtime_root.iterdir())
    versions = [name for name in names if RUNTIME_DIR_PATTERN.match(name)]
    if len(versions) != 1:
        raise RuntimeError(f"launcher_expected_one_runtime_directory_found_{versions}")
    leftovers = [name for name in names if ".staging-" in name]
    if leftovers:
        raise RuntimeError("launcher_staging_directory_remained")
    marker = runtime_root / versions[0] / ".complete"
    if not marker.is_file() or not marker.read_text(encoding="utf-8").strip():
        raise RuntimeError("launcher_completion_marker_missing")
    return versions[0]


def _failure_detail(work: Path, launcher_log: Path | None = None) -> str:
    """Bounded facts of a failed child for the CI log: the fixed-schema failure receipt
    (stage, reason, cleanup) and, for the launcher, its cache/instance/repair/exit lines."""
    detail = []
    try:
        with (work / "failure.json").open(encoding="ascii") as stream:
            payload = json.loads(stream.read(513))
        detail += [
            f"{key}={payload[key]}" for key in ("stage", "reason", "cleanup")
            if isinstance(payload.get(key), str) and re.fullmatch(r"[a-z_]{1,64}", payload[key])
        ]
    except (OSError, ValueError, UnicodeError):
        detail.append("no_failure_receipt")
    if launcher_log is not None and launcher_log.is_file():
        lines = launcher_log.read_text(encoding="utf-8", errors="replace").splitlines()
        detail += [
            line for line in lines[:50]
            if re.fullmatch(r"(cache|repair|instance|entry|exit)=[a-z0-9_-]{1,16}", line)
        ]
    return ";".join(detail)


def _extraction_clean(root: Path) -> None:
    if any(path.name.startswith("_MEI") for path in root.iterdir()):
        raise RuntimeError("portable_extraction_remained")


def _run(
    exe: Path, work: Path, state: Path, temp: Path, scenario: str, expected: int,
    cache: str | None = None,
) -> None:
    work.mkdir()
    if scenario in {"normal", "hard_exit"}:
        shutil.copyfile(FIXTURE, work / "fixture.pdf")
    windows = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not windows:
        raise RuntimeError("windows_root_unavailable")
    environment = {key: os.environ[key] for key in (
        "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"
    ) if os.environ.get(key)}
    environment.update({
        "PATH": str(Path(windows) / "System32") + ";" + windows,
        "TEMP": str(temp), "TMP": str(temp),
        "LOCALAPPDATA": str(state), "APPDATA": str(state / "Roaming"),
        "METROLIZA_STARTUP_SMOKE": "1",
        "METROLIZA_DIAGNOSTIC_QUALIFICATION": scenario,
        "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT": str(work),
        "METROLIZA_LICENSE_VERIFICATION": "0",
        "QT_QPA_PLATFORM": "offscreen",
    })
    launcher_log = work / "launcher.log"
    if cache is not None:
        # Launcher route: no dialogs from the launcher itself; its log is the cache evidence.
        # METROLIZA_RUNTIME_ROOT stays unset so the production default location is used.
        environment.update({
            "METROLIZA_LAUNCHER_NO_UI": "1",
            "METROLIZA_LAUNCHER_LOG": str(launcher_log),
        })
    started = time.monotonic()
    result = subprocess.run([str(exe)], cwd=work, env=environment,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=240, check=False)
    if result.returncode != expected:
        detail = _failure_detail(work, launcher_log if cache is not None else None)
        raise RuntimeError(f"portable_{scenario}_exit_{result.returncode} [{detail}]")
    if scenario != "hard_exit":
        _receipt(work, scenario)
    else:
        startup = json.loads((work / "startup.json").read_text(encoding="utf-8"))
        if startup.get("stage") != "startup_ready":
            raise RuntimeError("portable_hard_exit_not_started")
    if cache is not None:
        _expect_cache(launcher_log, cache)
    _extraction_clean(temp)
    note = f", cache={cache}" if cache is not None else ""
    print(f"{scenario}: exit {result.returncode}, elapsed {round(time.monotonic()-started, 2)}s{note}, extraction clean")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--kind", choices=("envelope", "launcher"), default="envelope")
    args = parser.parse_args(argv)
    if sys.platform != "win32" or not args.artifact.is_file():
        raise RuntimeError("native_portable_artifact_required")
    is_launcher = args.kind == "launcher"
    if is_launcher != args.artifact.name.endswith("_launcher.exe"):
        # The two deliveries must never be mistaken for each other.
        raise RuntimeError("artifact_name_does_not_match_kind")
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError("public_fixture_mismatch")
    with tempfile.TemporaryDirectory(prefix="metroliza-portable-qualification-") as private:
        root = Path(private)
        state, temp = root / "state", root / "extract"
        (state / "Roaming").mkdir(parents=True)
        temp.mkdir()
        exe = args.artifact.resolve()
        # Launcher route: the first launch fills the cache, every later one reuses it.
        first = "cold" if is_launcher else None
        later = "warm" if is_launcher else None
        _run(exe, root / "normal-first", state, temp, "normal", 0, first)
        if not (root / "normal-first/scratch.sqlite").is_file() or not (root / "normal-first/scratch.xlsx").is_file():
            raise RuntimeError("portable_core_outputs_missing")
        _run(exe, root / "normal-reopen", state, temp, "normal", 0, later)
        _run(exe, root / "hard-exit", state, temp, "hard_exit", 9, later)
        _run(exe, root / "preview", state, temp, "preview", 0, later)
        if not (root / "preview/selected.zip").is_file():
            raise RuntimeError("portable_incident_export_missing")
        if is_launcher:
            runtime = _runtime_layout(state / "Metroliza" / "runtime")
            print(f"launcher runtime cache: {runtime}")
    print(f"{'launcher' if is_launcher else 'portable supervised onefile'} smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
