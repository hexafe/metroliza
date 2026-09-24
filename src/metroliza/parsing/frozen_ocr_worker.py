"""Private onedir OCR boundary: Qt stays in the application, ONNX in a worker.

Only fixed-schema files in a newly owned temporary directory cross the process
boundary. No recognized text, native output, path, or exception is logged.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REQUEST_LIMIT = 65536
RESULT_LIMIT = 262144
IMAGE_LIMIT = 32 * 1024 * 1024
WORKER_SECONDS = 90
_NONCE = re.compile(r"[0-9a-f]{32}\Z")


class OcrWorkerFailure(RuntimeError):
    """Fixed, path-free failure at the isolated OCR boundary."""


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate_field")
        result[name] = value
    return result


def _read_json(path: Path, limit: int) -> dict[str, Any]:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not 0 < info.st_size <= limit):
        raise ValueError("unsafe_ocr_protocol_file")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("oversized_ocr_protocol_file")
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_fields)
    if type(value) is not dict:
        raise ValueError("invalid_ocr_protocol")
    return value


def _write_json(path: Path, value: dict[str, Any], limit: int) -> None:
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > limit:
        raise ValueError("oversized_ocr_protocol_file")
    with path.open("xb") as stream:
        stream.write(payload)


def _regular_image(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not 0 < info.st_size <= IMAGE_LIMIT):
        raise ValueError("unsafe_ocr_image")


def _config_payload(config) -> dict[str, Any]:
    paths = config.model_paths
    return {
        "model_paths": {
            "det": str(paths.det_model_path), "cls": str(paths.cls_model_path),
            "rec": str(paths.rec_model_path),
            "keys": None if paths.rec_keys_path is None else str(paths.rec_keys_path),
        },
        "params": config.params,
        "source": config.source_name,
    }


def _valid_config(value: Any) -> bool:
    if type(value) is not dict or set(value) != {"model_paths", "params", "source"}:
        return False
    paths = value["model_paths"]
    return (
        type(paths) is dict and set(paths) == {"det", "cls", "rec", "keys"}
        and all(type(paths[name]) is str and 0 < len(paths[name]) <= 32768
                and Path(paths[name]).is_absolute() for name in ("det", "cls", "rec"))
        and (paths["keys"] is None or type(paths["keys"]) is str
             and 0 < len(paths["keys"]) <= 32768 and Path(paths["keys"]).is_absolute())
        and type(value["params"]) is dict and len(value["params"]) <= 64
        and value["source"] == "rapidocr_latin"
    )


def _record_payload(record) -> dict[str, Any]:
    return {
        "text": record.text,
        "confidence": record.confidence,
        "box": record.box,
        "source": record.source,
    }


def _validated_records(value: Any, source: str):
    from metroliza.parsing.header_ocr_backend import HeaderOcrRecord

    if type(value) is not list or len(value) > 256:
        raise ValueError("invalid_ocr_records")
    records = []
    for index, item in enumerate(value):
        if type(item) is not dict or set(item) != {"text", "confidence", "box", "source"}:
            raise ValueError("invalid_ocr_record")
        text = item["text"]
        confidence = item["confidence"]
        box = item["box"]
        if (type(text) is not str or len(text) > 4096 or item["source"] != source
                or confidence is not None and (type(confidence) not in (int, float)
                                                or not math.isfinite(confidence)
                                                or not 0 <= confidence <= 1)):
            raise ValueError("invalid_ocr_record")
        if box is not None:
            if (type(box) not in (list, tuple) or len(box) != 4
                    or any(type(point) not in (list, tuple) or len(point) != 2
                           or any(type(axis) not in (int, float) or not math.isfinite(axis)
                                  for axis in point) for point in box)):
                raise ValueError("invalid_ocr_record")
            box = tuple((float(x), float(y)) for x, y in box)
        records.append(HeaderOcrRecord(
            text=text, confidence=confidence, box=box, source=source,
            diagnostics={"raw_index": index, "raw_shape": "isolated_worker"},
        ))
    return tuple(records)


def _worker_executable() -> Path:
    from metroliza.shared.diagnostic_package import inspect_package

    app = Path(sys.executable)
    worker = app.with_name("metroliza_ocr_worker.exe")
    if app.name.lower() != "metroliza_application.exe" or not inspect_package(app.parent).valid:
        raise OcrWorkerFailure("ocr_package_identity_failed")
    return worker


def _private_work_directory():
    if os.name == "nt":
        # Reuse the product's pinned, owner-only Windows directory primitive.
        from metroliza.ui.private_dashboard_directory import create_private_dashboard_directory

        return create_private_dashboard_directory()
    return tempfile.TemporaryDirectory(prefix="metroliza_ocr_worker_")


def _run_owned_worker(executable: Path, root: Path) -> None:
    from metroliza.shared.windows_owned_job import WindowsOwnedJob

    job = WindowsOwnedJob()
    process = None
    clean = False
    cleanup_failed = False
    try:
        environment = dict(os.environ)
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        for key in tuple(environment):
            if (key.startswith("METROLIZA_WINDOWS_RUNTIME_AUDIT")
                    or key in {"METROLIZA_STARTUP_SMOKE", "METROLIZA_DIAGNOSTIC_QUALIFICATION",
                               "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "PYTHONPATH", "PYTHONHOME"}):
                environment.pop(key, None)
        process = subprocess.Popen(
            [str(executable), str(root)], cwd=root, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=0x4 | 0x08000000,  # SUSPENDED | NO_WINDOW
        )
        job.assign(process)
        job.resume(process)
        if process.wait(timeout=WORKER_SECONDS) != 0:
            raise OcrWorkerFailure("ocr_worker_failed")
        job.drain(deadline=time.monotonic() + 10)
        clean = True
    finally:
        if not clean:
            try:
                job.terminate(deadline=time.monotonic() + 10)
            except Exception:
                cleanup_failed = True
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                except Exception:
                    cleanup_failed = True
        job.close()
        if cleanup_failed:
            raise OcrWorkerFailure("ocr_worker_cleanup_failed") from None


def recognize_in_frozen_worker(config, image_path: Path):
    """Run unchanged RapidOCR models in a separate owned Windows executable."""

    from metroliza.parsing.header_ocr_backend import HeaderOcrRun

    try:
        _regular_image(image_path)
        executable = _worker_executable()
        owner = _private_work_directory()
        try:
            root = Path(owner.name)
            shutil.copyfile(image_path, root / "header.png")
            _regular_image(root / "header.png")
            nonce = os.urandom(16).hex()
            _write_json(root / "request.json", {
                "schema_version": 1, "nonce": nonce, "config": _config_payload(config),
            }, REQUEST_LIMIT)
            _run_owned_worker(executable, root)
            result = _read_json(root / "result.json", RESULT_LIMIT)
            if (set(result) != {"schema_version", "nonce", "records"}
                    or result["schema_version"] != 1 or result["nonce"] != nonce):
                raise ValueError("invalid_ocr_result")
            records = _validated_records(result["records"], config.source_name)
        finally:
            try:
                owner.cleanup()
            except Exception:
                raise OcrWorkerFailure("ocr_worker_cleanup_failed") from None
        return HeaderOcrRun(records=records, diagnostics={
            "backend": config.source_name, "isolated_worker": True,
        })
    except OcrWorkerFailure:
        raise
    except Exception:
        raise OcrWorkerFailure("ocr_worker_boundary_failed") from None


def worker_main(argv: list[str] | None = None) -> int:
    """Consume only a private request; never print OCR text or errors."""

    from metroliza.parsing.header_ocr_backend import (
        RapidOcrLatinBackend, RapidOcrLatinBackendConfig, RapidOcrLatinModelPaths,
    )

    values = sys.argv[1:] if argv is None else argv
    try:
        if len(values) != 1:
            return 1
        root = Path(values[0])
        info = root.lstat()
        if (not root.is_absolute() or not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400):
            return 1
        request = _read_json(root / "request.json", REQUEST_LIMIT)
        if (set(request) != {"schema_version", "nonce", "config"}
                or request["schema_version"] != 1
                or type(request["nonce"]) is not str or _NONCE.fullmatch(request["nonce"]) is None
                or not _valid_config(request["config"])):
            return 1
        _regular_image(root / "header.png")
        config = request["config"]
        paths = config["model_paths"]
        backend = RapidOcrLatinBackend(RapidOcrLatinBackendConfig(
            model_paths=RapidOcrLatinModelPaths(
                paths["det"], paths["cls"], paths["rec"], paths["keys"],
            ),
            params=config["params"], source_name=config["source"],
        ))
        run = backend.recognize(root / "header.png", _in_process=True)
        _write_json(root / "result.json", {
            "schema_version": 1, "nonce": request["nonce"],
            "records": [_record_payload(record) for record in run.records],
        }, RESULT_LIMIT)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(worker_main())
