"""Native Windows wrapper/process evidence with disposable simulated diagnostics.

No OCR-engine acceptance: these tests execute both PowerShell scripts with a
stdlib-only fake diagnostic child. Setup's installation command boundary is
replaced in its disposable copy before execution; all machine-changing commands
are trapped. The production diagnostic validation/completion flow is unchanged.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import ocr_diagnostic_contract as contract

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Requires native Windows PowerShell"
)
CANARY = "SYNTHETIC_PRIVATE_1002"


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


def invoke(shell, root, script, *args):
    env = os.environ.copy()
    # Select the CI interpreter, not another user's venv or launcher.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / script), *args],
        capture_output=True,
        env=env,
        timeout=45,
    )


def public_text(result):
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert CANARY not in text
    assert "TEST_FORBIDDEN" not in text
    return text


@pytest.mark.parametrize("mode,expected", [("pass", 0), ("fail", 1), ("noise", 1), ("flood", 1)])
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
    script.write_text(script.read_text().replace("AddMinutes(20)", "AddSeconds(1)"))
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
    wrapper.write_text(wrapper.read_text().replace("AddMinutes(20)", "AddSeconds(1)"))
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
