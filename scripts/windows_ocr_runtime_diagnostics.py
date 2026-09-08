"""Safe OCR support JSON; required/requested failures return nonzero.

The selected runtime is tested in bounded children. No paths, environment values,
raw child output, document values or exception text are included in public output.
"""

from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

contract = importlib.import_module("scripts.ocr_diagnostic_contract")


def _selected_config():
    from metroliza.parsing.header_ocr_backend import rapidocr_latin_runtime_config_from_env

    return rapidocr_latin_runtime_config_from_env()


def _selected_models():
    from metroliza.parsing.header_ocr_backend import default_rapidocr_latin_model_paths

    return default_rapidocr_latin_model_paths(os.getenv("METROLIZA_HEADER_OCR_MODEL_DIR") or None)


def _configuration_check() -> dict:
    backend = os.getenv("METROLIZA_HEADER_OCR_BACKEND", "rapidocr_latin").strip().lower()
    if backend in {"", "none", "off", "disabled"}:
        return contract.row("runtime_config", "skipped", "ocr_disabled")
    if backend != "rapidocr_latin":
        return contract.row("runtime_config", "fail", "invalid_configuration")
    try:
        config = _selected_config()
    except (ValueError, TypeError):
        return contract.row("runtime_config", "fail", "invalid_configuration")
    return contract.row(
        "runtime_config",
        "pass",
        "ok",
        engine=config.engine,
        accelerator=config.accelerator,
        python_version=".".join(map(str, sys.version_info[:3])),
    )


def _models_check() -> dict:
    from metroliza.parsing.header_ocr_backend import RAPIDOCR_MODEL_ASSET_MANIFEST

    models = _selected_models()
    paths = [models.det_model_path, models.cls_model_path, models.rec_model_path]
    if models.rec_keys_path is not None:
        paths.append(models.rec_keys_path)
    missing = 0
    invalid = False
    for path in paths:
        try:
            with Path(path).open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                manifest = RAPIDOCR_MODEL_ASSET_MANIFEST.get(Path(path).name)
                if manifest and digest != manifest["sha256"]:
                    invalid = True
        except OSError:
            missing += 1
    if invalid and not missing:
        return contract.row(
            "models", "fail", "invalid_models", model_count=len(paths), missing_count=0
        )
    return contract.row(
        "models",
        "fail" if missing else "pass",
        "missing_models" if missing else "ok",
        model_count=len(paths),
        missing_count=missing,
    )


def _runtime_import_check() -> dict:
    config = _selected_config()
    try:
        # Match the application's Windows preload ordering for the chosen engine.
        engine = importlib.import_module(config.engine)
        cv2 = importlib.import_module("cv2")
        numpy = importlib.import_module("numpy")
        rapidocr = importlib.import_module("rapidocr")
    except Exception:
        return contract.row("runtime_import", "fail", "import_failed")
    if config.engine == "onnxruntime":
        provider = {
            "cpu": "CPUExecutionProvider",
            "cuda": "CUDAExecutionProvider",
            "dml": "DmlExecutionProvider",
            "coreml": "CoreMLExecutionProvider",
        }[config.accelerator]
        if provider not in engine.get_available_providers():
            return contract.row("runtime_import", "fail", "accelerator_unavailable")
    facts = {"engine": config.engine, "accelerator": config.accelerator}
    for name, module in (
        ("engine", engine),
        ("cv2", cv2),
        ("numpy", numpy),
        ("rapidocr", rapidocr),
    ):
        version = contract.safe_version(getattr(module, "__version__", None))
        if version is not None:
            facts[name + "_version"] = version
    return contract.row("runtime_import", "pass", "ok", **facts)


def _engine_smoke_check() -> dict:
    from metroliza.parsing.header_ocr_backend import (
        RapidOcrLatinBackend,
        RapidOcrLatinBackendConfig,
    )

    config = _selected_config()
    try:
        contract.prevent_rapidocr_downloads(config.engine)
        backend = RapidOcrLatinBackend(
            RapidOcrLatinBackendConfig(model_paths=_selected_models(), params=config.params)
        )
        engine = backend.load_engine()
        import numpy as np

        stages = (engine.text_det.session, engine.text_cls.session, engine.text_rec.session)
        if config.engine == "onnxruntime":
            expected = {
                "cpu": "CPUExecutionProvider",
                "cuda": "CUDAExecutionProvider",
                "dml": "DmlExecutionProvider",
                "coreml": "CoreMLExecutionProvider",
            }[config.accelerator]
            for stage in stages:
                providers = stage.session.get_providers()
                if not providers or providers[0] != expected:
                    return contract.row("engine_smoke", "fail", "accelerator_unavailable")
        # Exercise every selected model directly. RapidOCR's outer image pipeline
        # may swallow stage errors or skip classification/recognition on blank input.
        for stage, shape in zip(stages, ((1, 3, 64, 256), (1, 3, 48, 192), (1, 3, 48, 320))):
            stage(np.zeros(shape, dtype=np.float32))
    except contract.DiagnosticAssetMissing:
        return contract.row("engine_smoke", "fail", "missing_models")
    except Exception:
        return contract.row("engine_smoke", "fail", "smoke_failed")
    return contract.row(
        "engine_smoke", "pass", "ok", engine=config.engine, accelerator=config.accelerator
    )


def run_runtime_check(check_id: str) -> dict:
    checks = {
        "runtime_config": _configuration_check,
        "models": _models_check,
        "runtime_import": _runtime_import_check,
        "engine_smoke": _engine_smoke_check,
    }
    return checks[check_id]()


def build_payload(pdf_path: Path | None = None, db_file: str | None = None) -> dict:
    checks = []
    for check_id in contract.RUNTIME_IDS:
        if checks and any(check["status"] != "pass" for check in checks):
            checks.append(contract.row(check_id, "skipped", "not_completed"))
        else:
            checks.append(contract.isolated_check(check_id))
    checks.append(contract.row("alternatives", "skipped", "not_selected", required=False))
    request = {"pdf": str(pdf_path) if pdf_path is not None else None, "database": db_file}
    for check_id, requested in (("pdf", pdf_path is not None), ("database", db_file is not None)):
        if requested and any(check["reason"] == "interrupted" for check in checks):
            checks.append(contract.row(check_id, "skipped", "not_completed"))
        elif requested:
            checks.append(contract.isolated_check(check_id, request))
        else:
            checks.append(contract.row(check_id, "skipped", "not_requested", required=False))
    return contract.payload(checks)


def build_arg_parser() -> contract.SafeArgumentParser:
    parser = contract.SafeArgumentParser(description=__doc__)
    parser.add_argument("--pdf", help="Optional PDF; inspection must complete when requested.")
    parser.add_argument(
        "--db-file", help="Optional existing SQLite DB; inspect read-only, never create."
    )
    parser.add_argument(
        "--output", help="Atomic safe JSON output file; default stdout. Cannot alias input."
    )
    parser.add_argument("--compact", action="store_true", help="Write compact safe JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_arg_parser().parse_args(argv)
    except ValueError:
        return contract.publish(
            contract.payload([contract.row("diagnostic", "fail", "invalid_arguments")]),
            None,
            True,
            [],
        )
    if args.output == "":
        return contract.publish(
            contract.payload([contract.row("publication", "fail", "invalid_arguments")]),
            None,
            args.compact,
            [],
        )
    inputs = [Path(value) for value in (args.pdf, args.db_file) if value is not None]
    required = (
        contract.RUNTIME_IDS
        + (("pdf",) if args.pdf is not None else ())
        + (("database",) if args.db_file is not None else ())
    )
    try:
        if args.output:
            contract.reject_output_alias(Path(args.output), inputs)
        result = build_payload(Path(args.pdf) if args.pdf is not None else None, args.db_file)
        result = contract.validated_payload(result, required)
    except KeyboardInterrupt:
        result = contract.payload([contract.row("diagnostic", "fail", "interrupted")])
    except Exception:
        result = contract.payload([contract.row("diagnostic", "fail", "not_completed")])
    return contract.publish(result, args.output, args.compact, inputs)


if __name__ == "__main__":
    raise SystemExit(main())
