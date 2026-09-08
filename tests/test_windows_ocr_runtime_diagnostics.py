"""Public-channel and real-process regressions for #1002 / #1000."""

from pathlib import Path
import os
import sys
import time

from scripts import ocr_diagnostic_contract as contract

import json
import subprocess

import pytest

from scripts import windows_ocr_runtime_diagnostics as runtime


CANARIES = (
    "SYNTHETIC_CHILD_OUT_1002",
    "SYNTHETIC_CHILD_ERR_1002",
    "SYNTHETIC_ENV_PATH_1002",
    "SYNTHETIC_DB_SOURCE_1002",
    "SYNTHETIC_METADATA_1002",
)


def test_fail_first_raw_payload_cannot_escape(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        runtime,
        "build_payload",
        lambda *args: {
            "environment": dict(zip(CANARIES, CANARIES)),
            "smoke_tests": [{"name": "required", "returncode": 17, "ok": False}],
        },
    )
    output = tmp_path / "safe.json"
    result = runtime.main(["--output", str(output)])
    captured = capsys.readouterr()
    public = output.read_text() + captured.out + captured.err
    assert all(marker not in public for marker in CANARIES)
    assert result != 0
    assert json.loads(output.read_text())["checks"]


def test_fail_first_required_smoke_failure_is_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "build_payload",
        lambda *args: {
            "smoke_tests": [{"name": "rapidocr_engine_load", "returncode": 17, "ok": False}],
        },
    )
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


@pytest.fixture
def simulated_runtime(tmp_path, monkeypatch):
    """Trusted disposable Python engine doubles; never actual OCR evidence."""
    modules = tmp_path / "SYNTHETIC_ENV_PATH_1002"
    modules.mkdir()
    (modules / "onnxruntime.py").write_text(
        "import os\nos.write(1,b'SYNTHETIC_CHILD_OUT_1002\\xff')\n"
        "os.write(2,b'SYNTHETIC_CHILD_ERR_1002')\n"
        "__version__='1.2.3+SYNTHETIC_METADATA_1002'\n"
        "def get_available_providers(): return ['CPUExecutionProvider','CUDAExecutionProvider']\n"
    )
    (modules / "openvino.py").write_text("__version__='1.2.3'\n")
    (modules / "cv2.py").write_text("__version__='4.0.0'\n")
    (modules / "rapidocr.py").write_text(
        "import os\n__version__='3.8.0'\n"
        "class RapidOCR:\n"
        " def __init__(self,params):\n"
        "  assert params['Det.engine_type']==os.environ.get('METROLIZA_HEADER_OCR_ENGINE','onnxruntime')\n"
        "  assert params['Rec.model_path'].startswith(os.environ['METROLIZA_HEADER_OCR_MODEL_DIR'])\n"
        "  if os.environ.get('SYNTHETIC_ENGINE_FAIL'): raise RuntimeError('SYNTHETIC_METADATA_1002')\n"
        " def __call__(self,image): return None\n"
    )
    for name in list(os.environ):
        if name.startswith("METROLIZA_HEADER_OCR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv(
        "METROLIZA_HEADER_OCR_MODEL_DIR",
        str(runtime.REPO_ROOT / "src/metroliza/resources/ocr_models/rapidocr"),
    )
    monkeypatch.setenv("PYTHONPATH", str(modules))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return modules


def run_cli(*args, script="windows_ocr_runtime_diagnostics.py", env=None):
    return subprocess.run(
        [sys.executable, "-B", str(runtime.REPO_ROOT / "scripts" / script), *args],
        capture_output=True,
        timeout=45,
        env=env,
    )


def assert_public_safe(completed, output=None):
    public = completed.stdout + completed.stderr
    if output is not None:
        public += output.read_bytes()
    for marker in CANARIES:
        assert marker.encode() not in public
    assert b"Traceback" not in public
    return json.loads(output.read_text() if output is not None else completed.stdout)


def test_real_cli_selected_default_pass_with_simulated_engine(simulated_runtime):
    completed = run_cli("--compact")
    value = assert_public_safe(completed)
    assert completed.returncode == 0, value
    checks = {check["id"]: check for check in value["checks"]}
    assert checks["runtime_config"]["facts"]["engine"] == "onnxruntime"
    assert checks["engine_smoke"]["status"] == "pass"
    assert "engine_version" not in checks["runtime_import"]["facts"]
    assert checks["alternatives"]["status"] == "skipped"


def test_real_cli_selected_alternative(simulated_runtime, monkeypatch):
    monkeypatch.setenv("METROLIZA_HEADER_OCR_ENGINE", "openvino")
    completed = run_cli("--compact")
    value = assert_public_safe(completed)
    assert completed.returncode == 0, value
    assert value["checks"][3]["facts"]["engine"] == "openvino"


@pytest.mark.parametrize(
    "setting,value,check,reason",
    [
        ("METROLIZA_HEADER_OCR_ENGINE", CANARIES[0], "runtime_config", "invalid_configuration"),
        ("METROLIZA_HEADER_OCR_BACKEND", "off", "runtime_config", "ocr_disabled"),
        ("METROLIZA_HEADER_OCR_MODEL_DIR", CANARIES[2], "models", "missing_models"),
        ("SYNTHETIC_ENGINE_FAIL", "1", "engine_smoke", "smoke_failed"),
        ("METROLIZA_HEADER_OCR_ACCELERATOR", "dml", "runtime_import", "accelerator_unavailable"),
    ],
)
def test_real_required_failure_safe_file(
    simulated_runtime, monkeypatch, tmp_path, setting, value, check, reason
):
    monkeypatch.setenv(setting, value)
    output = tmp_path / "safe.json"
    completed = run_cli("--output", str(output))
    result = assert_public_safe(completed, output)
    assert completed.returncode != 0
    assert {row["id"]: row for row in result["checks"]}[check]["reason"] == reason
    assert completed.stdout == b""


@pytest.mark.parametrize(
    "code,reason",
    [
        (
            "import os; os.write(1,b'SYNTHETIC_CHILD_OUT_1002'); os.write(2,b'SYNTHETIC_CHILD_ERR_1002'); raise SystemExit(17)",
            "child_failed",
        ),
        ("import time; time.sleep(10)", "timeout"),
        ("import os; os.write(1,b'\\xff\\xfe')", "protocol_error"),
        ("print('x'*100000)", "output_limit"),
        ("import os; os.write(2,b'x'*100000)", "output_limit"),
        ("print('{}')", "protocol_error"),
    ],
)
def test_real_child_failure_and_bounds(code, reason):
    start = time.monotonic()
    result = contract.run_child([sys.executable, "-B", "-c", code], "engine_smoke", timeout_s=0.3)
    assert result == contract.row("engine_smoke", "fail", reason)
    assert time.monotonic() - start < 5


def test_real_child_can_return_only_useful_allowlisted_result():
    result = contract.row("models", "pass", "ok", model_count=3, missing_count=0)
    code = (
        "import os; os.write(2,b'SYNTHETIC_CHILD_ERR_1002\\xff'); print("
        + repr(json.dumps(result))
        + ")"
    )
    assert contract.run_child([sys.executable, "-c", code], "models") == result


@pytest.mark.parametrize(
    "checks",
    [
        [],
        [contract.row("models", "pass", "ok")],
        [contract.row(check, "pass", "ok", required=False) for check in contract.RUNTIME_IDS],
        [contract.row(check, "unknown", "ok") for check in contract.RUNTIME_IDS],
        [contract.row(check, "pass", "ok") for check in contract.RUNTIME_IDS]
        + [contract.row("models", "fail", "missing_models")],
    ],
)
def test_invalid_required_sets_never_pass(checks):
    value = contract.validated_payload(contract.payload(checks), contract.RUNTIME_IDS)
    assert not contract.succeeded(value)


@pytest.mark.parametrize(
    "fact", [True, -1, 1000001, float("nan"), CANARIES[0], {"raw": CANARIES[1]}]
)
def test_invalid_facts_fail_closed(fact):
    with pytest.raises(ValueError):
        contract.validate_row(contract.row("models", "pass", "ok", model_count=fact))


def test_atomic_output_preserves_complete_file_on_replace_failure(tmp_path, monkeypatch, capsys):
    output = tmp_path / "safe.json"
    previous = b'{"previous":"complete"}\n'
    output.write_bytes(previous)

    def fail(*args):
        raise OSError(CANARIES[0])

    monkeypatch.setattr(contract.os, "replace", fail)
    assert (
        contract.publish(
            contract.payload([contract.row("models", "pass", "ok")]), str(output), True, []
        )
        != 0
    )
    assert output.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [output]
    assert CANARIES[0] not in capsys.readouterr().err


@pytest.mark.parametrize("alias", ["direct", "hardlink", "symlink", "-wal", "-shm", "-journal"])
def test_output_cannot_overwrite_input_or_sidecars(tmp_path, alias):
    source = tmp_path / "input.db"
    source.write_bytes(b"source")
    output = source
    if alias == "hardlink":
        output = tmp_path / "hardlink.json"
        os.link(source, output)
    elif alias == "symlink":
        output = tmp_path / "symlink.json"
        try:
            output.symlink_to(source)
        except OSError:
            pytest.skip("Creating symlinks requires Windows developer mode")
    elif alias.startswith("-"):
        output = Path(str(source) + alias)
    assert (
        contract.publish(
            contract.payload([contract.row("models", "pass", "ok")]), str(output), True, [source]
        )
        != 0
    )
    assert source.read_bytes() == b"source"
    if alias.startswith("-"):
        assert not output.exists()


def test_cli_invalid_arguments_are_safe():
    result = run_cli("--" + CANARIES[0])
    assert result.returncode != 0
    assert assert_public_safe(result)["checks"][0]["reason"] == "invalid_arguments"
