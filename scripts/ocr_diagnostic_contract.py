"""Small public OCR diagnostic contract and isolated, bounded process boundary.

Only stdlib is imported in the publishing process. Application/library work runs
in a child whose native stdout/stderr are bounded in memory and never published.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_IDS = ("runtime_config", "models", "runtime_import", "engine_smoke")
CHECK_IDS = (*RUNTIME_IDS, "pdf", "database", "alternatives", "diagnostic", "publication")
REASONS = {
    "ok",
    "not_selected",
    "not_requested",
    "ocr_disabled",
    "invalid_configuration",
    "missing_models",
    "invalid_models",
    "import_failed",
    "accelerator_unavailable",
    "smoke_failed",
    "input_unreadable",
    "invalid_pdf",
    "extraction_failed",
    "metadata_absent",
    "ocr_no_records",
    "database_missing",
    "schema_unsupported",
    "database_unreadable",
    "no_matching_rows",
    "timeout",
    "child_failed",
    "protocol_error",
    "output_limit",
    "interrupted",
    "not_completed",
    "output_failed",
    "output_alias",
    "invalid_arguments",
}
ENUM_FACTS = {
    "engine": {"onnxruntime", "openvino", "tensorrt"},
    "accelerator": {"cpu", "cuda", "dml", "coreml"},
    "extraction_mode": {"none", "words", "ocr"},
}
COUNT_FACTS = {
    "model_count",
    "missing_count",
    "matching_rows",
    "metadata_fields",
    "header_items",
    "filename_fields",
    "header_fields",
    "other_fields",
    "page_count",
}
VERSION_FACTS = {
    "python_version",
    "engine_version",
    "rapidocr_version",
    "numpy_version",
    "cv2_version",
}
MAX_OUTPUT = 65536


def row(check_id: str, status: str, reason: str, *, required: bool = True, **facts: Any) -> dict:
    return {
        "id": check_id,
        "requirement": "required" if required else "advisory",
        "status": status,
        "reason": reason,
        "facts": facts,
    }


def safe_version(value: Any) -> str | None:
    if type(value) is str and re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}", value):
        return value
    return None


def validate_row(value: Any, expected_id: str | None = None) -> dict:
    if type(value) is not dict or set(value) != {"id", "requirement", "status", "reason", "facts"}:
        raise ValueError
    check_id = value["id"]
    if (
        type(check_id) is not str
        or check_id not in CHECK_IDS
        or (expected_id and check_id != expected_id)
    ):
        raise ValueError
    for key, allowed in (
        ("requirement", {"required", "advisory"}),
        ("status", {"pass", "fail", "skipped"}),
        ("reason", REASONS),
    ):
        if type(value[key]) is not str or value[key] not in allowed:
            raise ValueError
    allowed_reasons = {
        "pass": {"ok", "metadata_absent", "ocr_no_records", "no_matching_rows", "ocr_disabled"},
        "skipped": {"not_selected", "not_requested", "ocr_disabled", "not_completed"},
        "fail": REASONS
        - {
            "ok",
            "not_selected",
            "not_requested",
            "metadata_absent",
            "ocr_no_records",
            "no_matching_rows",
            "ocr_disabled",
        },
    }
    if value["reason"] not in allowed_reasons[value["status"]]:
        raise ValueError
    if (
        value["status"] == "pass"
        and value["reason"] != "ok"
        and check_id not in {"pdf", "database"}
    ):
        raise ValueError
    _validate_facts(value["facts"])
    return {key: value[key] for key in ("id", "requirement", "status", "reason", "facts")}


def _validate_facts(facts: Any) -> None:
    if type(facts) is not dict or len(facts) > 16:
        raise ValueError
    for key, fact in facts.items():
        if key in ENUM_FACTS and type(fact) is str and fact in ENUM_FACTS[key]:
            continue
        if key in COUNT_FACTS and type(fact) is int and 0 <= fact <= 1000000:
            continue
        if key in VERSION_FACTS and safe_version(fact) is not None:
            continue
        raise ValueError


def payload(checks: list[dict]) -> dict:
    return {"schema_version": 1, "checks": checks}


def validated_payload(value: Any, required_ids: tuple[str, ...]) -> dict:
    try:
        if type(value) is not dict or set(value) != {"schema_version", "checks"}:
            raise ValueError
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError
        if type(value["checks"]) is not list or not 1 <= len(value["checks"]) <= len(CHECK_IDS):
            raise ValueError
        checks = [validate_row(check) for check in value["checks"]]
        ids = [check["id"] for check in checks]
        if len(set(ids)) != len(ids):
            raise ValueError
        by_id = {check["id"]: check for check in checks}
        for check_id in required_ids:
            if check_id not in by_id or by_id[check_id]["requirement"] != "required":
                raise ValueError
        return payload(checks)
    except (ValueError, TypeError, KeyError):
        return payload([row("diagnostic", "fail", "protocol_error")])


def succeeded(value: dict) -> bool:
    required = [check for check in value["checks"] if check["requirement"] == "required"]
    return bool(required) and all(check["status"] == "pass" for check in required)


class _WindowsJob:
    """Own the diagnostic child's descendants independently of parent lifetime."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("min_working", ctypes.c_size_t),
                ("max_working", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle:
            raise OSError("job_unavailable")
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise OSError("job_unavailable")

    def assign(self, process: subprocess.Popen) -> None:
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError("job_unavailable")

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _stop_child(process: subprocess.Popen, job: _WindowsJob | None = None) -> None:
    if job is not None:
        job.close()
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def _deliver_input(pipe: Any, data: bytes) -> None:
    try:
        pipe.write(data)
        pipe.close()
    except (OSError, ValueError):
        pass  # A dead child is classified by exit/protocol checks, never its text.


def _capture(pipe: Any, buffer: bytearray, exceeded: threading.Event, limit: int) -> None:
    try:
        while chunk := os.read(pipe.fileno(), 4096):
            remaining = limit - len(buffer)
            buffer.extend(chunk[: max(0, remaining)])
            if len(chunk) > remaining:
                exceeded.set()
                break
    except (OSError, ValueError):
        exceeded.set()


def run_child(
    command: list[str],
    check_id: str,
    *,
    request: dict | None = None,
    timeout_s: float = 180,
    output_limit: int = MAX_OUTPUT,
    env: dict[str, str] | None = None,
) -> dict:
    """Run a trusted worker; all received bytes are untrusted private data."""
    data = json.dumps(request or {}).encode("utf-8")
    if len(data) > MAX_OUTPUT:
        return row(check_id, "fail", "protocol_error")
    output, noise = bytearray(), bytearray()
    exceeded = threading.Event()
    process = None
    job = None
    readers: list[threading.Thread] = []
    reason = None
    try:
        deadline = time.monotonic() + timeout_s
        job = _WindowsJob() if os.name == "nt" else None
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
        )
        if job is not None:
            job.assign(process)
        for pipe, buffer in ((process.stdout, output), (process.stderr, noise)):
            thread = threading.Thread(
                target=_capture, args=(pipe, buffer, exceeded, output_limit), daemon=True
            )
            thread.start()
            readers.append(thread)
        writer = threading.Thread(target=_deliver_input, args=(process.stdin, data), daemon=True)
        writer.start()
        readers.append(writer)
        reason = _monitor_child(process, readers, exceeded, deadline)
    except KeyboardInterrupt:
        reason = "interrupted"
    except (OSError, subprocess.SubprocessError):
        reason = "child_failed"
    finally:
        try:
            _cleanup_child(process, job, readers)
        except (OSError, subprocess.SubprocessError):
            reason = "not_completed"
    if reason:
        return row(check_id, "fail", reason)
    try:
        return validate_row(json.loads(output.decode("utf-8")), check_id)
    except (ValueError, UnicodeError, TypeError, KeyError):
        return row(check_id, "fail", "protocol_error")


def _monitor_child(process, readers, exceeded, deadline) -> str | None:
    while process.poll() is None or any(thread.is_alive() for thread in readers):
        if exceeded.is_set():
            return "output_limit"
        if time.monotonic() >= deadline:
            return "timeout"
        time.sleep(0.01)
    if exceeded.is_set():
        return "output_limit"
    return "child_failed" if process.returncode != 0 else None


def _cleanup_child(process, job, readers) -> None:
    if process is not None:
        _stop_child(process, job)
        for thread in readers:
            thread.join(timeout=2)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
    elif job is not None:
        job.close()


def isolated_check(check_id: str, request: dict | None = None) -> dict:
    # The worker redirects native fd 1 to captured fd 2 before application imports.
    code = (
        "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; "
        "from scripts.ocr_diagnostic_contract import worker_main; worker_main()"
    )
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="metroliza_diagnostic_") as private:
        # Cache location is disposable; backend/accelerator/model selection is preserved.
        env["METROLIZA_HEADER_OCR_CACHE_DIR"] = private
        return run_child(
            [sys.executable, "-B", "-u", "-c", code, str(REPO_ROOT / "src"), str(REPO_ROOT)],
            check_id,
            request={"check_id": check_id, **(request or {})},
            env=env,
        )


class DiagnosticAssetMissing(RuntimeError):
    """A dependency tried to acquire an asset during read-only diagnosis."""


def _reject_asset_download(*args, **kwargs):
    raise DiagnosticAssetMissing("missing_models")


def prevent_rapidocr_downloads() -> None:
    # Worker-local boundary for the pinned RapidOCR downloader. Intercept before
    # it creates a directory, contacts the network, or overwrites a cached file.
    # Existing dictionaries are read without invoking this path in RapidOCR 3.8.1.
    if importlib.util.find_spec("rapidocr") is not None:
        module = importlib.import_module("rapidocr.utils.download_file")
        module.DownloadFile.run = staticmethod(_reject_asset_download)


def worker_main() -> None:
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    request = json.loads(sys.stdin.buffer.read(MAX_OUTPUT))
    check_id = request["check_id"]
    try:
        if check_id in {"pdf", "database"}:
            from scripts.diagnose_header_ocr_metadata import run_input_check

            result = run_input_check(check_id, request)
        else:
            from scripts.windows_ocr_runtime_diagnostics import run_runtime_check

            result = run_runtime_check(check_id)
        result = validate_row(result, check_id)
    except BaseException:
        result = row(check_id, "fail", "child_failed")
    with os.fdopen(protocol_fd, "w", encoding="utf-8") as protocol:
        protocol.write(json.dumps(result, allow_nan=False))


def reject_output_alias(output: Path, inputs: list[Path]) -> None:
    target = output.expanduser().resolve()
    for source in inputs:
        source = source.expanduser().resolve()
        for protected in (
            source,
            *(Path(str(source) + suffix) for suffix in ("-wal", "-shm", "-journal")),
        ):
            if target == protected or (
                target.exists() and protected.exists() and target.samefile(protected)
            ):
                raise ValueError("output_alias")


def publish(value: dict, output: str | None, compact: bool, inputs: list[Path]) -> int:
    stage = None
    try:
        text = json.dumps(value, indent=None if compact else 2, allow_nan=False) + "\n"
        if output:
            target = Path(output).expanduser().resolve()
            reject_output_alias(target, inputs)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=".ocr-diagnostic-",
                delete=False,
            ) as stream:
                stage = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            reject_output_alias(target, inputs)
            os.replace(stage, target)
        else:
            sys.stdout.write(text)
            sys.stdout.flush()
    except (OSError, ValueError, UnicodeError, KeyboardInterrupt):
        try:
            sys.stderr.write("OCR diagnostic: publication failed (output_failed).\n")
        except (OSError, UnicodeError):
            pass
        return 2
    finally:
        if stage is not None:
            try:
                stage.unlink(missing_ok=True)
            except OSError:
                pass
    return 0 if succeeded(value) else 1


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("invalid_arguments")
