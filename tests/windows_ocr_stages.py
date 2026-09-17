"""Closed, test-only observations in disposable copies of the OCR wrapper.

The probe adds small file writes and can change scheduling. A missing stage is
an observation boundary, not proof of the historical timeout's cause. No
process handle, stream, callback or extra child is retained by this observer.
"""

from __future__ import annotations

import json
from pathlib import Path


WRAPPER_STAGES = (
    "shell_entered", "type_entered", "type_ready", "start_entered", "start_returned",
    "input_released", "reads_entered", "reads_ready", "loop_entered",
    "child_exited", "stdout_eof", "stderr_eof", "output_complete",
    "result_validated", "result_published", "cleanup_entered", "job_stopped",
    "cleanup_returned",
)
CHILD_STAGES = ("child_entered", "result_generated", "result_write_returned")
OBSERVATION_FAILURES = ("unobserved", "fixture_mismatch")


def _ordered(values: list[str], domain: tuple[str, ...]) -> bool:
    if domain == CHILD_STAGES:
        return values == list(domain[:len(values)])
    before = {stage: {WRAPPER_STAGES[index - 1]} for index, stage in enumerate(WRAPPER_STAGES) if index}
    before["shell_entered"] = set()
    for stage in ("child_exited", "stdout_eof", "stderr_eof"):
        before[stage] = {"loop_entered"}
    before["output_complete"] = {"child_exited", "stdout_eof", "stderr_eof"}
    # Failed initialization/start/read/validation can enter finally early.
    before["cleanup_entered"] = {"type_entered"}
    before["cleanup_returned"] = {"cleanup_entered"}
    seen: set[str] = set()
    for stage in values:
        if not before[stage] <= seen:
            return False
        if "cleanup_entered" in seen and stage not in {"job_stopped", "cleanup_returned"}:
            return False
        if "cleanup_returned" in seen:
            return False
        seen.add(stage)
    return True


def _replace_once(source: str, anchor: str, replacement: str) -> str:
    # Git's Windows checkout can use CRLF. Preserve its existing bytes instead
    # of normalizing the whole disposable file as a side effect of observation.
    if "\r\n" in source:
        anchor = anchor.replace("\n", "\r\n")
        replacement = replacement.replace("\n", "\r\n")
    if source.count(anchor) != 1:
        raise ValueError("fixture_anchor_mismatch")
    return source.replace(anchor, replacement)


def instrument_wrapper(root: Path) -> None:
    """Instrument only a disposable fixture, with exact source anchors."""
    path = root / "diagnose_windows_ocr.ps1"
    source = path.read_bytes().decode("utf-8")
    writer = r'''
function Write-TestStage([string]$Stage) {
    try {
        [System.IO.File]::AppendAllText((Join-Path $PSScriptRoot 'wrapper.stages'),
            ($Stage + "`n"), [System.Text.Encoding]::ASCII)
    } catch { } # Missing evidence must not change production control flow.
}
Write-TestStage 'shell_entered'
'''
    anchors = {
        "Set-StrictMode -Version Latest": "Set-StrictMode -Version Latest\n" + writer,
        "    Initialize-DiagnosticJobType\n": (
            "    Write-TestStage 'type_entered'\n    Initialize-DiagnosticJobType\n"
            "    Write-TestStage 'type_ready'\n"
        ),
        "    $process = $job.Start($python, $nativeArguments, $repoRoot)": (
            "    Write-TestStage 'start_entered'\n"
            "    $process = $job.Start($python, $nativeArguments, $repoRoot)\n"
            "    Write-TestStage 'start_returned'"
        ),
        "    $job.Input.Close()": (
            "    $job.Input.Close()\n    Write-TestStage 'input_released'"
        ),
        "    $tasks = @($streams[0].ReadAsync": (
            "    Write-TestStage 'reads_entered'\n    $tasks = @($streams[0].ReadAsync"
        ),
        "    $closed = @($false, $false)": (
            "    Write-TestStage 'reads_ready'\n    $observedExit = $false\n"
            "    $observedLoop = $false\n    $closed = @($false, $false)"
        ),
        "    while (-not ($closed[0] -and $closed[1] -and $process.HasExited)) {": (
            "    while (-not ($closed[0] -and $closed[1] -and $process.HasExited)) {\n"
            "        if (-not $observedLoop) { Write-TestStage 'loop_entered'; $observedLoop = $true }\n"
            "        if (-not $observedExit -and $process.HasExited) {\n"
            "            Write-TestStage 'child_exited'; $observedExit = $true\n        }"
        ),
        "if ($count -eq 0) { $closed[$index] = $true }": (
            "if ($count -eq 0) {\n                    $closed[$index] = $true\n"
            "                    if ($index -eq 0) { Write-TestStage 'stdout_eof' }\n"
            "                    else { Write-TestStage 'stderr_eof' }\n                }"
        ),
        "    $diagnosticExit = if ($process.ExitCode": (
            "    if (-not $observedExit) { Write-TestStage 'child_exited' }\n"
            "    Write-TestStage 'output_complete'\n    $diagnosticExit = if ($process.ExitCode"
        ),
        "    $result = ConvertTo-SafeDiagnostic $text": (
            "    $result = ConvertTo-SafeDiagnostic $text\n    Write-TestStage 'result_validated'"
        ),
        "    if ($diagnosticExit -ne 0) { [Console]": (
            "    Write-TestStage 'result_published'\n    if ($diagnosticExit -ne 0) { [Console]"
        ),
        "finally {\n    try {\n        if ($null -ne $job) { $job.Stop() }": (
            "finally {\n    Write-TestStage 'cleanup_entered'\n    try {\n"
            "        if ($null -ne $job) { $job.Stop(); Write-TestStage 'job_stopped' }"
        ),
        "exit $diagnosticExit": "Write-TestStage 'cleanup_returned'\nexit $diagnosticExit",
    }
    for anchor, replacement in anchors.items():
        source = _replace_once(source, anchor, replacement)
    path.write_bytes(source.encode("utf-8"))

    child = root / "scripts/windows_ocr_runtime_diagnostics.py"
    source = child.read_bytes().decode("utf-8")
    writer = '''def stage(value):
 try:
  with pathlib.Path(__file__).with_name('child.stages').open('a', encoding='ascii') as stream:
   stream.write(value + '\\n')
 except OSError: pass
stage('child_entered')
'''
    source = _replace_once(source, "args = sys.argv[1:]\n", writer + "args = sys.argv[1:]\n")
    source = _replace_once(source, "text = json.dumps(value)\n", "text = json.dumps(value)\nstage('result_generated')\n")
    # This records return from print/write, not a flush or OS process exit.
    source = _replace_once(source, "raise SystemExit(", "stage('result_write_returned')\nraise SystemExit(")
    child.write_bytes(source.encode("utf-8"))


def read_stages(path: Path, allowed: tuple[str, ...]) -> list[str]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(1025)
    except OSError:
        return ["unobserved"]
    if len(raw) > 1024 or not raw.endswith(b"\n"):
        return ["fixture_mismatch"]
    try:
        values = raw.decode("ascii").splitlines()
    except UnicodeError:
        return ["fixture_mismatch"]
    if not values or len(values) != len(set(values)) or any(value not in allowed for value in values):
        return ["fixture_mismatch"]
    if not _ordered(values, allowed):
        return ["fixture_mismatch"]
    return values


def validate_observation(text: str) -> dict:
    """Revalidate before publishing a private JUnit property in the native lane."""
    if len(text) > 4096:
        raise ValueError("stage_receipt_limit")
    value = json.loads(text)
    if type(value) is not dict or set(value) != {"shell", "mode", "wrapper", "child"}:
        raise ValueError("stage_receipt_schema")
    if value["shell"] not in ("powershell", "pwsh") or value["mode"] not in ("pass", "fail"):
        raise ValueError("stage_receipt_domain")
    for key, domain in (("wrapper", WRAPPER_STAGES), ("child", CHILD_STAGES)):
        stages = value[key]
        if type(stages) is not list or not 1 <= len(stages) <= len(domain):
            raise ValueError("stage_receipt_domain")
        if any(type(stage) is not str or stage not in domain + OBSERVATION_FAILURES for stage in stages):
            raise ValueError("stage_receipt_domain")
        if len(stages) != len(set(stages)):
            raise ValueError("stage_receipt_domain")
        if any(stage in OBSERVATION_FAILURES for stage in stages) and len(stages) != 1:
            raise ValueError("stage_receipt_domain")
        if stages[0] not in OBSERVATION_FAILURES and not _ordered(stages, domain):
            raise ValueError("stage_receipt_order")
    return value
