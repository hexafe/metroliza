"""Public-channel and real-process regressions for #1002 / #1000."""

from contextlib import closing
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
    (modules / "tensorrt.py").write_text("__version__='10.0.0'\n")
    rapidocr = modules / "rapidocr"
    rapidocr.mkdir()
    (rapidocr / "utils").mkdir()
    (rapidocr / "utils/__init__.py").write_text("")
    (rapidocr / "utils/download_file.py").write_text(
        "import os\nfrom pathlib import Path\nclass DownloadFile:\n"
        " @staticmethod\n def run(*args): Path(os.environ['SYNTHETIC_ASSET_TARGET']).write_text('forbidden')\n"
    )
    (rapidocr / "__init__.py").write_text(
        "import os,sys\n__version__='3.8.0'\n"
        "if os.environ.get('METROLIZA_HEADER_OCR_ENGINE','onnxruntime')=='onnxruntime':\n"
        " assert 'onnxruntime' in sys.modules, 'required preload order'\n"
        "from types import SimpleNamespace\n"
        "class Stage:\n"
        " def __init__(self): self.session=self\n"
        " def get_providers(self):\n"
        "  selected=os.environ.get('METROLIZA_HEADER_OCR_ACCELERATOR','cpu')\n"
        "  return ['CUDAExecutionProvider' if selected=='cuda' and not os.environ.get('SYNTHETIC_FALLBACK') else 'CPUExecutionProvider']\n"
        " def __call__(self,image):\n"
        "  assert image.ndim==4, 'RapidOCR sessions accept one bare batched tensor'\n"
        "  if os.environ.get('SYNTHETIC_STAGE_FAIL'): raise RuntimeError('SYNTHETIC_METADATA_1002')\n"
        "class RapidOCR:\n"
        " def __init__(self,params):\n"
        "  self.text_det=self.text_cls=self.text_rec=SimpleNamespace(session=Stage())\n"
        "  assert params['Det.engine_type']==os.environ.get('METROLIZA_HEADER_OCR_ENGINE','onnxruntime')\n"
        "  assert params['Rec.model_path'].startswith(os.environ['METROLIZA_HEADER_OCR_MODEL_DIR'])\n"
        "  if os.environ.get('SYNTHETIC_ENGINE_FAIL'): raise RuntimeError('SYNTHETIC_METADATA_1002')\n"
        "  if os.environ.get('SYNTHETIC_DOWNLOAD'):\n"
        "   from rapidocr.utils.download_file import DownloadFile\n"
        "   DownloadFile.run(None)\n"
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


def test_available_cuda_but_cpu_sessions_cannot_pass(simulated_runtime, monkeypatch):
    monkeypatch.setenv("METROLIZA_HEADER_OCR_ACCELERATOR", "cuda")
    monkeypatch.setenv("SYNTHETIC_FALLBACK", "1")
    result = run_cli("--compact")
    data = assert_public_safe(result)
    assert result.returncode != 0
    assert data["checks"][2]["status"] == "pass"
    assert data["checks"][3]["reason"] == "accelerator_unavailable"


def test_every_model_session_must_execute(simulated_runtime, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_STAGE_FAIL", "1")
    result = run_cli("--compact")
    assert result.returncode != 0
    assert assert_public_safe(result)["checks"][3]["reason"] == "smoke_failed"


def test_request_delivery_has_timeout_and_size_bound():
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    start = time.monotonic()
    result = contract.run_child(
        command, "database", request={"database": "x" * 60000}, timeout_s=0.2
    )
    assert result["reason"] == "timeout"
    assert time.monotonic() - start < 5
    result = contract.run_child(
        command, "database", request={"database": "x" * 100000}, timeout_s=0.2
    )
    assert result["reason"] == "protocol_error"


def test_interrupt_starts_no_further_requested_work(monkeypatch):
    called = []

    def check(check_id, request=None):
        called.append(check_id)
        return (
            contract.row(check_id, "pass", "ok")
            if len(called) == 1
            else contract.row(check_id, "fail", "interrupted")
        )

    monkeypatch.setattr(contract, "isolated_check", check)
    result = runtime.build_payload(Path("synthetic.pdf"), "synthetic.sqlite")
    assert called == ["runtime_config", "models"]
    assert result["checks"][0]["status"] == "pass"
    assert result["checks"][-1]["status"] == "skipped"


def test_real_interrupt_kills_and_reaps_child(tmp_path, monkeypatch):
    pid_file = tmp_path / "pid"
    command = [
        sys.executable,
        "-c",
        "import os,pathlib,time; pathlib.Path("
        + repr(str(pid_file))
        + ").write_text(str(os.getpid())); time.sleep(10)",
    ]
    real_sleep = time.sleep
    interrupted = False

    def interrupt(seconds):
        nonlocal interrupted
        if pid_file.exists() and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        real_sleep(seconds)

    monkeypatch.setattr(contract.time, "sleep", interrupt)
    result = contract.run_child(command, "engine_smoke", timeout_s=5)
    assert result["reason"] == "interrupted"
    assert not _process_alive(int(pid_file.read_text()))


def test_real_parent_exit_does_not_leave_descendant(tmp_path):
    pid_file = tmp_path / "descendant.pid"
    child_code = "import time; time.sleep(30)"
    code = (
        "import sys,subprocess,pathlib; sys.stdin.read(); "
        "child=subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "]); "
        "pathlib.Path(" + repr(str(pid_file)) + ").write_text(str(child.pid))"
    )
    result = contract.run_child([sys.executable, "-c", code], "engine_smoke", timeout_s=0.5)
    assert result["reason"] == "timeout"
    assert not _process_alive(int(pid_file.read_text()))


def _process_alive(pid):
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            assert ctypes.get_last_error() == 87, "unexpected process inspection failure"
            return False
        try:
            # A job's descendants terminate asynchronously. Retain this handle
            # through a bounded native wait; unknown errors never mean stopped.
            initial = kernel.WaitForSingleObject(handle, 0)
            final = kernel.WaitForSingleObject(handle, 5000) if initial == 258 else initial
            assert final in {0, 258}, "unexpected process wait failure"
            print(f"native process cleanup: initial_wait={initial}, final_wait={final}")
            return final == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


@pytest.mark.parametrize(
    "script", ["windows_ocr_runtime_diagnostics.py", "diagnose_header_ocr_metadata.py"]
)
def test_real_requested_pdf_db_markers_absent(simulated_runtime, tmp_path, script):
    import hashlib
    import sqlite3

    pdf = tmp_path / (CANARIES[2] + ".pdf")
    _write_synthetic_pdf(pdf, "Reference: " + CANARIES[4] + "\nOperator: " + CANARIES[0])
    database = tmp_path / (CANARIES[3] + ".sqlite")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(
            "CREATE TABLE source_files(id INTEGER, sha256 TEXT, absolute_path TEXT); CREATE TABLE parsed_reports(id INTEGER, source_file_id INTEGER); CREATE TABLE report_metadata(report_id INTEGER, metadata_json TEXT)"
        )
        connection.execute(
            "INSERT INTO source_files VALUES(1,?,?)",
            (hashlib.sha256(pdf.read_bytes()).hexdigest(), CANARIES[3]),
        )
        connection.execute("INSERT INTO parsed_reports VALUES(1,1)")
        connection.execute("INSERT INTO report_metadata VALUES(1,?)", (CANARIES[4],))
    before = pdf.read_bytes(), database.read_bytes()
    output = tmp_path / "safe.json"
    args = [str(pdf)] if script.startswith("diagnose_header") else ["--pdf", str(pdf)]
    completed = run_cli(*args, "--db-file", str(database), "--output", str(output), script=script)
    data = assert_public_safe(completed, output)
    checks = {row["id"]: row for row in data["checks"]}
    assert checks["database"]["facts"]["matching_rows"] == 1
    assert checks["pdf"]["status"] == "pass", checks["pdf"]
    assert checks["pdf"]["facts"]["page_count"] == 1
    assert (pdf.read_bytes(), database.read_bytes()) == before
    assert not Path(str(database) + "-wal").exists()


@pytest.mark.parametrize("option", ["--pdf", "--db-file"])
def test_requested_missing_input_is_nonzero(simulated_runtime, option):
    completed = run_cli(option, CANARIES[2])
    assert completed.returncode != 0
    data = assert_public_safe(completed)
    assert data["checks"][-2 if option == "--pdf" else -1]["status"] == "fail"


def test_selected_tensorrt_never_downloads_missing_dictionary(
    simulated_runtime, monkeypatch, tmp_path
):
    target = tmp_path / "user-model-cache" / "dictionary.txt"
    monkeypatch.setenv("METROLIZA_HEADER_OCR_ENGINE", "tensorrt")
    monkeypatch.setenv("SYNTHETIC_DOWNLOAD", "1")
    monkeypatch.setenv("SYNTHETIC_ASSET_TARGET", str(target))
    result = run_cli("--compact")
    assert result.returncode != 0
    assert assert_public_safe(result)["checks"][3]["reason"] == "missing_models"
    assert not target.parent.exists()


def test_pdf_worker_blocks_dependency_download(simulated_runtime, monkeypatch, tmp_path):
    target = tmp_path / "dictionary.txt"
    monkeypatch.setenv("SYNTHETIC_DOWNLOAD", "1")
    monkeypatch.setenv("SYNTHETIC_ASSET_TARGET", str(target))
    pdf = tmp_path / "synthetic.pdf"
    _write_synthetic_pdf(pdf)
    result = contract.isolated_check("pdf", {"pdf": str(pdf)})
    assert result["reason"] == "missing_models", result
    assert not target.exists()


def _write_synthetic_pdf(path, text=""):
    # Other suites intentionally replace PDF modules in sys.modules. Generate
    # this real disposable fixture in a fresh interpreter without those stubs.
    result = subprocess.run(
        [
            sys.executable, "-B", "-c",
            "import sys,pymupdf; doc=pymupdf.open(); page=doc.new_page(); "
            "page.insert_text((72,72),sys.argv[2]); doc.save(sys.argv[1]); doc.close()",
            str(path), text,
        ],
        capture_output=True, timeout=20,
    )
    assert result.returncode == 0, "synthetic PDF creation failed"


def test_interrupted_publication_preserves_output_without_traceback(tmp_path, monkeypatch, capsys):
    output = tmp_path / "safe.json"
    output.write_text("previous complete")

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(contract.os, "replace", interrupt)
    assert (
        contract.publish(
            contract.payload([contract.row("models", "pass", "ok")]), str(output), True, []
        )
        != 0
    )
    assert output.read_text() == "previous complete"
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("pdf_state", ["missing", "invalid"])
@pytest.mark.parametrize("db_state", ["missing", "unsupported", "valid"])
def test_requested_database_inspection_survives_pdf_failure(
    simulated_runtime, tmp_path, pdf_state, db_state
):
    from contextlib import closing
    import sqlite3

    pdf = tmp_path / "SYNTHETIC_DOCUMENT_1002.pdf"
    if pdf_state == "invalid":
        pdf.write_bytes(b"SYNTHETIC_METADATA_1002")
    database = tmp_path / "SYNTHETIC_DB_1002.sqlite"
    if db_state != "missing":
        with closing(sqlite3.connect(database)) as connection, connection:
            if db_state == "valid":
                connection.executescript(
                    "CREATE TABLE source_files(id, sha256);"
                    "CREATE TABLE parsed_reports(id, source_file_id);"
                    "CREATE TABLE report_metadata(report_id, metadata_json);"
                )
    original = database.read_bytes() if database.exists() else None
    result = run_cli("--pdf", str(pdf), "--db-file", str(database), "--compact")
    assert result.returncode != 0
    checks = {check["id"]: check for check in assert_public_safe(result)["checks"]}
    assert checks["pdf"]["reason"] == (
        "input_unreadable" if pdf_state == "missing" else "invalid_pdf"
    )
    assert checks["database"]["reason"] == {
        "missing": "database_missing", "unsupported": "schema_unsupported", "valid": "ok"
    }[db_state]
    assert checks["database"]["status"] == ("pass" if db_state == "valid" else "fail")
    assert checks["database"]["facts"] == {}
    assert (database.read_bytes() if database.exists() else None) == original
