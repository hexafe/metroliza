"""Windows-focused OCR runtime diagnostics.

This script checks the native import path that header OCR needs on Windows and,
optionally, runs the real CMM parser metadata diagnostic against one PDF.
It writes UTF-8 JSON directly so PowerShell redirection encoding does not hide
diagnostic details.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _module_spec_summary(module_name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return {"available": False, "origin": None}
    return {"available": True, "origin": spec.origin}


def _run_python_smoke(name: str, code: str, *, timeout_s: int = 180) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return {
        "name": name,
        "returncode": completed.returncode,
        "ok": completed.returncode == 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _vc_redist_registry_status() -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {"checked": False, "reason": "not_windows"}

    try:
        import winreg
    except ImportError as exc:
        return {"checked": False, "reason": f"winreg_unavailable:{exc}"}

    key_paths = (
        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
    )
    rows = []
    installed = False
    for key_path in key_paths:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                values = {}
                for name in ("Installed", "Version", "Major", "Minor", "Bld", "Rbld"):
                    try:
                        values[name] = winreg.QueryValueEx(key, name)[0]
                    except OSError:
                        values[name] = None
                row_installed = values.get("Installed") == 1
                installed = installed or row_installed
                rows.append({"key": key_path, "present": True, "installed": row_installed, "values": values})
        except OSError as exc:
            rows.append({"key": key_path, "present": False, "installed": False, "error": str(exc)})

    return {
        "checked": True,
        "installed": installed,
        "registry_rows": rows,
        "download_url": "https://aka.ms/vs/17/release/vc_redist.x64.exe",
    }


def _build_smoke_tests() -> list[tuple[str, str]]:
    return [
        (
            "onnxruntime_basic",
            "import onnxruntime as ort; print(ort.__version__, ort.__file__, ort.get_available_providers())",
        ),
        (
            "cv2_then_onnxruntime",
            "import cv2; from onnxruntime import GraphOptimizationLevel, InferenceSession, SessionOptions; "
            "print('cv2_then_onnxruntime_ok')",
        ),
        (
            "rapidocr_engine_load",
            "from modules.header_ocr_backend import default_rapidocr_latin_model_paths, "
            "RapidOcrLatinBackendConfig, RapidOcrLatinBackend; "
            "backend = RapidOcrLatinBackend(RapidOcrLatinBackendConfig(model_paths=default_rapidocr_latin_model_paths())); "
            "backend.load_engine(); print('rapidocr_engine_ok')",
        ),
        (
            "packaged_header_ocr_validator",
            "from scripts.validate_packaged_pdf_parser import require_header_ocr_available, "
            "validate_vendored_header_ocr_models; "
            "require_header_ocr_available(); validate_vendored_header_ocr_models(); "
            "print('packaged_header_ocr_validator_ok')",
        ),
    ]


def build_payload(pdf_path: Path | None = None, db_file: str | None = None) -> dict[str, Any]:
    from modules.header_ocr_backend import default_rapidocr_model_dir, missing_rapidocr_latin_model_paths
    from modules.header_ocr_backend import default_rapidocr_latin_model_paths

    model_paths = default_rapidocr_latin_model_paths(os.getenv("METROLIZA_HEADER_OCR_MODEL_DIR") or None)
    payload: dict[str, Any] = {
        "environment": {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
            "repo_root": str(REPO_ROOT),
            "path_head": os.environ.get("PATH", "").split(os.pathsep)[:12],
            "env": {
                "METROLIZA_HEADER_OCR_BACKEND": os.getenv("METROLIZA_HEADER_OCR_BACKEND"),
                "METROLIZA_HEADER_OCR_MODEL_DIR": os.getenv("METROLIZA_HEADER_OCR_MODEL_DIR"),
                "METROLIZA_HEADER_OCR_ZOOM": os.getenv("METROLIZA_HEADER_OCR_ZOOM"),
                "METROLIZA_HEADER_OCR_THREADS": os.getenv("METROLIZA_HEADER_OCR_THREADS"),
            },
            "modules": {
                name: _module_spec_summary(name)
                for name in ("rapidocr", "onnxruntime", "cv2", "numpy", "fitz", "pymupdf")
            },
            "vc_redist_x64": _vc_redist_registry_status(),
            "default_rapidocr_model_dir": str(default_rapidocr_model_dir()),
            "missing_rapidocr_model_files": [
                str(path) for path in missing_rapidocr_latin_model_paths(model_paths)
            ],
        },
        "smoke_tests": [_run_python_smoke(name, code) for name, code in _build_smoke_tests()],
    }

    if pdf_path is not None:
        from scripts.diagnose_header_ocr_metadata import build_diagnostic_payload

        payload["parser_diagnostic"] = build_diagnostic_payload(pdf_path, db_file)

    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="Optional PDF to run through the real CMM parser OCR metadata path.")
    parser.add_argument("--db-file", help="Optional SQLite database for existing-row diagnostics.")
    parser.add_argument("--output", help="Optional UTF-8 JSON output path. Defaults to stdout.")
    parser.add_argument("--compact", action="store_true", help="Write compact JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    pdf_path = Path(args.pdf).expanduser().resolve() if args.pdf else None
    payload = build_payload(pdf_path, args.db_file)
    indent = None if args.compact else 2
    output_text = json.dumps(payload, ensure_ascii=False, indent=indent, default=str)
    if args.output:
        Path(args.output).expanduser().resolve().write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
