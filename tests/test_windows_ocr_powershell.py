"""Native Windows wrapper/process evidence with disposable simulated diagnostics.

No OCR-engine acceptance: these tests execute both PowerShell scripts with a
stdlib-only fake diagnostic child. Setup's installation command boundary is
replaced in its disposable copy before execution; all machine-changing commands
are trapped. The production diagnostic validation/completion flow is unchanged.
"""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

import pytest

from scripts import ocr_diagnostic_contract as contract
from tests import windows_ocr_process as process

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Requires native Windows PowerShell"
)
CANARY = "SYNTHETIC_PRIVATE_1002"
_INVOKE_REASONS = {
    "completed", "timeout", "cancelled", "containment_unavailable", "startup_failed",
    "assignment_failed", "resume_failed", "not_completed", "output_limit",
}


@dataclass(frozen=True)
class InvokeResult:
    """Bounded public result from one owned PowerShell process tree."""

    returncode: int
    stdout: bytes
    stderr: bytes
    reason: process.Reason
    process_returncode: int | None
    cleanup_complete: bool
    tree_empty: bool
    output_limited: bool
    elapsed_s: float


@pytest.fixture(params=["powershell", "pwsh"])
def powershell(request):
    executable = shutil.which(request.param)
    if executable is None:
        pytest.fail(f"Required native Windows shell unavailable: {request.param}")
    return executable


@pytest.fixture
def fixture_repo(tmp_path):
    root = tmp_path / (CANARY + " spaced ź")
    root.mkdir()
    (root / "scripts").mkdir()
    shutil.copyfile(ROOT / "diagnose_windows_ocr.ps1", root / "diagnose_windows_ocr.ps1")
    setup = (ROOT / "setup_windows_runtime.ps1").read_text()
    boundary = """
# Disposable test boundary: never enter installation, elevation or cleanup.
function Invoke-Step {
    param([string]$Title, [scriptblock]$Action)
    if ($Title -eq 'Validating OCR runtime and model files') { & $Action }
}
function Invoke-Checked { throw 'TEST_FORBIDDEN_INSTALL_COMMAND' }
function New-ProjectVenv { throw 'TEST_FORBIDDEN_VENV_COMMAND' }
function Invoke-WebRequest { throw 'TEST_FORBIDDEN_DOWNLOAD_COMMAND' }
function Start-Process { throw 'TEST_FORBIDDEN_INSTALLER_COMMAND' }
function Remove-Item { throw 'TEST_FORBIDDEN_CLEANUP_COMMAND' }
"""
    marker = "Push-Location $repoRoot"
    assert setup.count(marker) == 1
    (root / "setup_windows_runtime.ps1").write_text(
        setup.replace(marker, boundary + "\n" + marker), encoding="utf-8-sig"
    )
    return root


def write_child(root, mode):
    checks = [contract.row(check_id, "pass", "ok") for check_id in contract.RUNTIME_IDS]
    if mode == "fail":
        checks[-1] = contract.row("engine_smoke", "fail", "smoke_failed")
    source = """import json, os, pathlib, sys, time
args = sys.argv[1:]
"""
    if mode == "noise":
        source += f"os.write(1, {CANARY.encode()!r}); os.write(2, {CANARY.encode()!r})\n"
    elif mode == "flood":
        source += "os.write(2, b'x'*100000)\n"
    elif mode == "timeout":
        source += "time.sleep(30)\n"
    elif mode == "malformed":
        source += f"os.write(1, b'{{invalid:' + {CANARY.encode()!r}); raise SystemExit(0)\n"
    elif mode == "partial":
        source += f"os.write(1, b'{{\"private\":' + {CANARY.encode()!r}); raise SystemExit(0)\n"
    source += f"value = {contract.payload(checks)!r}\n"
    source += """for flag, check_id in [('--pdf','pdf'),('--db-file','database')]:
 if flag in args:
  value['checks'].append({'id':check_id,'requirement':'required','status':'pass','reason':'ok','facts':{}})
text = json.dumps(value)
if '--output' in args:
 pathlib.Path(args[args.index('--output')+1]).write_text(text, encoding='utf-8')
else: print(text)
"""
    source += f"raise SystemExit({17 if mode == 'fail' else 0})\n"
    (root / "scripts/windows_ocr_runtime_diagnostics.py").write_text(source)


def _read_captures(stdout_file, stderr_file):
    """Return both bounded streams, or one closed failure reason and no bytes."""
    try:
        sizes = (
            os.fstat(stdout_file.fileno()).st_size,
            os.fstat(stderr_file.fileno()).st_size,
        )
        if any(size > contract.MAX_OUTPUT for size in sizes):
            return "output_limit", b"", b""
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(contract.MAX_OUTPUT + 1)
        stderr = stderr_file.read(contract.MAX_OUTPUT + 1)
        if len(stdout) > contract.MAX_OUTPUT or len(stderr) > contract.MAX_OUTPUT:
            return "output_limit", b"", b""
        return None, stdout, stderr
    except (OSError, ValueError):
        return "not_completed", b"", b""


def invoke(shell, root, script, *args, timeout_s=45, cancel_event=None):
    started = time.monotonic()
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        return InvokeResult(
            1, b"", b"startup_failed", "startup_failed", None, True, True, False, 0.0
        )

    deadline = started + timeout_s
    cleanup_s = min(5.0, timeout_s / 3.0)
    read_margin_s = min(0.25, timeout_s / 20.0)
    env = os.environ.copy()
    # Select the CI interpreter, not another user's venv or launcher.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    command = [
        shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / script), *args,
    ]
    owned = None
    reason: process.Reason = "startup_failed"
    stdout = stderr = b""
    output_limited = False
    private_cleanup_complete = False
    try:
        with tempfile.TemporaryDirectory(prefix="metroliza-invoke-") as private:
            capture_root = Path(private)
            with (
                tempfile.TemporaryFile(mode="w+b", dir=capture_root) as stdout_file,
                tempfile.TemporaryFile(mode="w+b", dir=capture_root) as stderr_file,
            ):
                execution_s = deadline - time.monotonic() - cleanup_s - read_margin_s
                if execution_s <= 0:
                    reason = "timeout"
                else:
                    owned = process.run_owned(
                        command,
                        cwd=root,
                        env=env,
                        timeout_s=execution_s,
                        cleanup_timeout_s=cleanup_s,
                        cancel_event=cancel_event,
                        stdout_target=stdout_file,
                        stderr_target=stderr_file,
                        output_limit=contract.MAX_OUTPUT,
                    )
                    reason = (
                        owned.reason
                        if type(owned.reason) is str and owned.reason in _INVOKE_REASONS
                        else "not_completed"
                    )
                    output_limited = owned.output_limited is True
                    if output_limited:
                        reason = "output_limit"
                    publishable = (
                        reason == "completed"
                        and owned.cleanup_complete is True
                        and owned.tree_empty is True
                        and not output_limited
                        and type(owned.returncode) is int
                    )
                    if publishable:
                        capture_reason, stdout, stderr = _read_captures(
                            stdout_file, stderr_file
                        )
                        if capture_reason is not None:
                            reason = capture_reason
                            output_limited = capture_reason == "output_limit"
                    elif reason == "completed":
                        reason = "not_completed"
        private_cleanup_complete = True
    except (OSError, ValueError):
        reason = "startup_failed" if owned is None else "not_completed"

    finished = time.monotonic()
    if finished > deadline:
        reason = "timeout"
    process_returncode = owned.returncode if owned is not None else None
    cleanup_complete = (
        (owned.cleanup_complete is True if owned is not None else True)
        and private_cleanup_complete
    )
    tree_empty = owned.tree_empty is True if owned is not None else True
    publishable = (
        reason == "completed"
        and cleanup_complete
        and tree_empty
        and type(process_returncode) is int
    )
    if not publishable:
        stdout, stderr = b"", reason.encode("ascii")
    returncode = (
        process_returncode
        if publishable or (type(process_returncode) is int and process_returncode != 0)
        else 1
    )
    return InvokeResult(
        returncode,
        stdout,
        stderr,
        reason,
        process_returncode,
        cleanup_complete,
        tree_empty,
        output_limited or reason == "output_limit",
        max(0.0, finished - started),
    )


def assert_owned_completion(result):
    assert result.reason == "completed"
    assert result.cleanup_complete and result.tree_empty
    assert not result.output_limited
    assert result.process_returncode == result.returncode
    assert len(result.stdout) <= contract.MAX_OUTPUT
    assert len(result.stderr) <= contract.MAX_OUTPUT


def public_text(result):
    assert_owned_completion(result)
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert CANARY not in text
    assert "TEST_FORBIDDEN" not in text
    return text


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("pass", 0), ("fail", 1), ("noise", 1), ("flood", 1),
        ("malformed", 1), ("partial", 1),
    ],
)
def test_native_wrapper_output_and_exit(powershell, fixture_repo, mode, expected):
    write_child(fixture_repo, mode)
    result = invoke(
        powershell,
        fixture_repo,
        "diagnose_windows_ocr.ps1",
        "-Compact",
        "-PdfPath",
        CANARY + " document.pdf",
        "-DbFile",
        CANARY + " database.sqlite",
    )
    text = public_text(result)
    assert (result.returncode != 0) == bool(expected), text
    if mode in {"pass", "fail"}:
        data = json.loads(result.stdout)
        assert data["schema_version"] == 1
        assert any(check["id"] == "engine_smoke" for check in data["checks"])


def test_native_wrapper_safe_file(powershell, fixture_repo):
    write_child(fixture_repo, "fail")
    output = fixture_repo / "safe output.json"
    result = invoke(
        powershell, fixture_repo, "diagnose_windows_ocr.ps1", "-OutputPath", str(output)
    )
    public_text(result)
    assert result.returncode != 0
    assert json.loads(output.read_text())["checks"][-1]["reason"] == "smoke_failed"


def test_native_wrapper_timeout_and_start_failure(powershell, fixture_repo):
    write_child(fixture_repo, "timeout")
    script = fixture_repo / "diagnose_windows_ocr.ps1"
    script.write_text(script.read_text().replace("AddMinutes(20)", "AddSeconds(5)"))
    result = invoke(powershell, fixture_repo, script.name)
    public_text(result)
    assert result.returncode != 0
    venv = fixture_repo / "fake-venv" / "Scripts"
    venv.mkdir(parents=True)
    (venv / "python.exe").write_bytes(b"invalid synthetic executable")
    result = invoke(powershell, fixture_repo, script.name, "-VenvDir", str(venv.parent))
    public_text(result)
    assert result.returncode != 0


@pytest.mark.parametrize(
    "mode,flags,success",
    [
        ("pass", [], True),
        ("fail", [], False),
        ("fail", ["-SkipOcr"], True),
        ("fail", ["-SkipValidation"], True),
    ],
)
def test_native_required_setup_propagation(powershell, fixture_repo, mode, flags, success):
    write_child(fixture_repo, mode)
    result = invoke(powershell, fixture_repo, "setup_windows_runtime.ps1", *flags)
    assert_owned_completion(result)
    # Generic setup activation guidance is outside the diagnostic seam and may
    # include its disposable venv path. Only the actual diagnostic flow is public-safe.
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert "TEST_FORBIDDEN" not in text
    assert (result.returncode == 0) == success, text
    assert ("Windows runtime setup completed." in text) == success
    if flags:
        assert "skipped" in text and "OCR was not tested" in text
    else:
        assert "engine_smoke" in text
        if not success:
            assert CANARY not in text


def test_native_relative_output_uses_one_location(powershell, fixture_repo):
    write_child(fixture_repo, "pass")
    result = invoke(
        powershell, fixture_repo, "diagnose_windows_ocr.ps1", "-OutputPath", "relative result.json"
    )
    public_text(result)
    assert result.returncode == 0
    assert json.loads((fixture_repo / "relative result.json").read_text())["checks"]


def test_native_parent_exit_cleans_descendant(powershell, fixture_repo):
    from tests.test_windows_ocr_runtime_diagnostics import _process_alive

    pid_file = fixture_repo / "descendant.pid"
    child = "import time; time.sleep(30)"
    script = fixture_repo / "scripts/windows_ocr_runtime_diagnostics.py"
    script.write_text(
        "import sys,subprocess,pathlib; child=subprocess.Popen([sys.executable,'-c',"
        + repr(child)
        + "]); pathlib.Path("
        + repr(str(pid_file))
        + ").write_text(str(child.pid))",
        encoding="utf-8",
    )
    wrapper = fixture_repo / "diagnose_windows_ocr.ps1"
    wrapper.write_text(wrapper.read_text().replace("AddMinutes(20)", "AddSeconds(5)"))
    result = invoke(powershell, fixture_repo, wrapper.name)
    public_text(result)
    assert result.returncode != 0
    assert not _process_alive(int(pid_file.read_text()))


def test_native_output_failure_is_safe(powershell, fixture_repo):
    write_child(fixture_repo, "pass")
    result = invoke(
        powershell,
        fixture_repo,
        "diagnose_windows_ocr.ps1",
        "-OutputPath",
        str(fixture_repo / "missing" / "safe.json"),
    )
    public_text(result)
    assert result.returncode != 0


def test_native_venv_startup_hook_descendant_is_owned(powershell, fixture_repo, monkeypatch):
    from tests.test_windows_ocr_runtime_diagnostics import _process_alive, _startup_hook_fixture

    _, assigned, observed = _startup_hook_fixture(fixture_repo, monkeypatch)
    write_child(fixture_repo, "pass")
    wrapper = fixture_repo / "diagnose_windows_ocr.ps1"
    source = wrapper.read_text()
    source = source.replace(
        "public void Assign(IntPtr process) {",
        "public void Assign(IntPtr process) { System.Threading.Thread.Sleep(500);",
    )
    source = source.replace(
        "Assign(info.process);",
        "Assign(info.process); System.IO.File.WriteAllText("
        + json.dumps(str(assigned)) + ", info.pid.ToString());",
    )
    wrapper.write_text(source, encoding="utf-8-sig")
    result = invoke(powershell, fixture_repo, wrapper.name)
    public_text(result)
    observation = json.loads(observed.read_text())
    assert result.returncode == 0
    assert observation["assigned"]
    assert observation["pid"] != int(assigned.read_text())
    assert not _process_alive(observation["child"])


@pytest.mark.parametrize("mode", ["delay", "query_failed", "timeout"])
def test_native_job_completion_is_required(powershell, fixture_repo, mode):
    write_child(fixture_repo, "pass")
    wrapper = fixture_repo / "diagnose_windows_ocr.ps1"
    source = wrapper.read_text()
    if mode == "query_failed":
        source = source.replace(
            "if (!QueryInformationJobObject(handle, 1, out info,",
            "if (!QueryInformationJobObject(new IntPtr(-1), 1, out info,",
        )
    else:
        count = fixture_repo / "query-count"
        source = source.replace("void TerminateAndAccount(Stopwatch timer) {",
                                "void TerminateAndAccount(Stopwatch timer) { int queries = 0;")
        injected = "queries++; System.IO.File.WriteAllText(" + json.dumps(str(count)) + ", queries.ToString()); "
        injected += "if (queries < 3) info.active = 1; " if mode == "delay" else "info.active = 1; "
        source = source.replace("if (info.active == 0) return;", injected + "if (info.active == 0) return;")
        source = source.replace("timer.ElapsedMilliseconds >= 10000", "timer.ElapsedMilliseconds >= 100")
    wrapper.write_text(source, encoding="utf-8-sig")
    result = invoke(powershell, fixture_repo, wrapper.name)
    public_text(result)
    assert json.loads(result.stdout)["checks"], "fixture must execute before cleanup injection"
    if mode == "delay":
        assert result.returncode == 0
        assert int(count.read_text()) >= 3
    else:
        assert result.returncode != 0
        assert b"not_completed" in result.stderr
        if mode == "timeout":
            assert int(count.read_text()) >= 1


def test_native_job_overflow_still_terminates_and_checks_accounting(powershell, fixture_repo):
    write_child(fixture_repo, "pass")
    wrapper = fixture_repo / "diagnose_windows_ocr.ps1"
    marker = fixture_repo / "accounting-complete"
    source = wrapper.read_text()
    source = source.replace("static extern bool QueryMembers(", "static extern bool NativeQueryMembers(")
    source = source.replace("List<IntPtr> MemberHandles() {", """
    static bool QueryMembers(IntPtr job, int type, ref Members info, uint length, IntPtr returned) {
        if (!NativeQueryMembers(job, type, ref info, length, returned)) return false;
        info.assigned = 257; info.count = 256; return false;
    }
    List<IntPtr> MemberHandles() {""")
    source = source.replace("if (info.active == 0) return;",
                            "if (info.active == 0) { System.IO.File.WriteAllText("
                            + json.dumps(str(marker)) + ", \"zero\"); return; }")
    wrapper.write_text(source, encoding="utf-8-sig")
    result = invoke(powershell, fixture_repo, wrapper.name)
    public_text(result)
    assert result.returncode != 0
    assert b"not_completed" in result.stderr
    assert marker.read_text() == "zero"
