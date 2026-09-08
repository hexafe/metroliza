"""Public-channel and real-process regressions for #1002 / #1000."""

import json
import subprocess

import pytest

from scripts import windows_ocr_runtime_diagnostics as runtime


CANARIES = (
    "SYNTHETIC_CHILD_OUT_1002", "SYNTHETIC_CHILD_ERR_1002",
    "SYNTHETIC_ENV_PATH_1002", "SYNTHETIC_DB_SOURCE_1002", "SYNTHETIC_METADATA_1002",
)


def test_fail_first_raw_payload_cannot_escape(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runtime, "build_payload", lambda *args: {
        "environment": dict(zip(CANARIES, CANARIES)),
        "smoke_tests": [{"name": "required", "returncode": 17, "ok": False}],
    })
    output = tmp_path / "safe.json"
    result = runtime.main(["--output", str(output)])
    captured = capsys.readouterr()
    public = output.read_text() + captured.out + captured.err
    assert all(marker not in public for marker in CANARIES)
    assert result != 0
    assert json.loads(output.read_text())["checks"]


def test_fail_first_required_smoke_failure_is_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "build_payload", lambda *args: {
        "smoke_tests": [{"name": "rapidocr_engine_load", "returncode": 17, "ok": False}],
    })
    output = tmp_path / "safe.json"
    assert runtime.main(["--output", str(output)]) != 0
    assert json.loads(output.read_text())["checks"]


def test_fail_first_timeout_retains_safe_json(tmp_path, monkeypatch, capsys):
    def timeout(*args):
        raise subprocess.TimeoutExpired(CANARIES[0], 1, output=CANARIES[1])
    monkeypatch.setattr(runtime, "build_payload", timeout)
    output = tmp_path / "safe.json"
    assert runtime.main(["--output", str(output)]) != 0
    public = output.read_text() + capsys.readouterr().err
    assert all(marker not in public for marker in CANARIES)
    assert json.loads(output.read_text())["checks"]
