"""Bounded native smoke of the single visible supervised Windows executable."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _extraction_clean(root: Path) -> None:
    if any(path.name.startswith("_MEI") for path in root.iterdir()):
        raise RuntimeError("portable_extraction_remained")


def _run(exe: Path, work: Path, state: Path, temp: Path, scenario: str, expected: int) -> None:
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
    started = time.monotonic()
    result = subprocess.run([str(exe)], cwd=work, env=environment,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=240, check=False)
    if result.returncode != expected:
        raise RuntimeError(f"portable_{scenario}_exit_{result.returncode}")
    if scenario != "hard_exit":
        _receipt(work, scenario)
    else:
        startup = json.loads((work / "startup.json").read_text(encoding="utf-8"))
        if startup.get("stage") != "startup_ready":
            raise RuntimeError("portable_hard_exit_not_started")
    _extraction_clean(temp)
    print(f"{scenario}: exit {result.returncode}, elapsed {round(time.monotonic()-started, 2)}s, extraction clean")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "win32" or not args.artifact.is_file():
        raise RuntimeError("native_portable_artifact_required")
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError("public_fixture_mismatch")
    with tempfile.TemporaryDirectory(prefix="metroliza-portable-qualification-") as private:
        root = Path(private)
        state, temp = root / "state", root / "extract"
        (state / "Roaming").mkdir(parents=True)
        temp.mkdir()
        exe = args.artifact.resolve()
        _run(exe, root / "normal-first", state, temp, "normal", 0)
        if not (root / "normal-first/scratch.sqlite").is_file() or not (root / "normal-first/scratch.xlsx").is_file():
            raise RuntimeError("portable_core_outputs_missing")
        _run(exe, root / "normal-reopen", state, temp, "normal", 0)
        _run(exe, root / "hard-exit", state, temp, "hard_exit", 9)
        _run(exe, root / "preview", state, temp, "preview", 0)
        if not (root / "preview/selected.zip").is_file():
            raise RuntimeError("portable_incident_export_missing")
    print("portable supervised onefile smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
