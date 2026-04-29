"""Validate packaged PDF parser dependencies for build pipelines."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PYMUPDF_MODULES = (
    'pymupdf',
    'pymupdf._mupdf',
    'pymupdf._extra',
    'pymupdf.extra',
    'pymupdf.mupdf',
)
REQUIRED_HEADER_OCR_MODULES = (
    'rapidocr',
    'onnxruntime',
    'openvino',
    'cv2',
    'numpy',
)
REQUIRED_HEADER_OCR_REPORT_MODULES = (
    'modules.header_ocr_backend',
    'modules.header_ocr_geometry',
    'modules.header_ocr_corrections',
    *REQUIRED_HEADER_OCR_MODULES,
)
REQUIRED_THIRD_PARTY_NOTICE = ROOT / 'THIRD_PARTY_NOTICES.md'


def _load_pdf_backend_helpers():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from modules.pdf_backend import PDF_BACKEND_CANDIDATES, resolve_pdf_backend_module_name

    return PDF_BACKEND_CANDIDATES, resolve_pdf_backend_module_name


class PackagingValidationError(RuntimeError):
    """Raised when packaged PDF parser validation fails."""


def require_pdf_backend_available(*, allow_broken: bool = False) -> str:
    _, resolve_pdf_backend_module_name = _load_pdf_backend_helpers()
    backend_name = resolve_pdf_backend_module_name()
    if backend_name is not None:
        return backend_name
    if allow_broken:
        return ""
    raise PackagingValidationError(
        "PyMuPDF backend detection failed: neither `pymupdf` nor `fitz` is importable with a usable `open()` method."
    )


def _flatten_report_strings(root: ET.Element) -> list[str]:
    values: list[str] = []
    for element in root.iter():
        if element.text and element.text.strip():
            values.append(element.text.strip())
        values.extend(str(value).strip() for value in element.attrib.values() if str(value).strip())
    return values


def validate_nuitka_report_has_pdf_backend(report_path: str | Path) -> tuple[str, ...]:
    report = Path(report_path)
    if not report.is_file():
        raise PackagingValidationError(f"Nuitka build report not found: {report}")

    root = ET.parse(report).getroot()
    haystack = "\n".join(_flatten_report_strings(root))
    PDF_BACKEND_CANDIDATES, _ = _load_pdf_backend_helpers()
    included = tuple(name for name in PDF_BACKEND_CANDIDATES if name in haystack)
    if not included:
        raise PackagingValidationError(
            f"Nuitka build report {report} does not reference bundled PyMuPDF backends ({', '.join(PDF_BACKEND_CANDIDATES)})."
        )

    missing_required_modules = tuple(module_name for module_name in REQUIRED_PYMUPDF_MODULES if module_name not in haystack)
    if missing_required_modules:
        raise PackagingValidationError(
            f"Nuitka build report {report} is missing required PyMuPDF runtime modules: {', '.join(missing_required_modules)}."
        )
    return included


def require_header_ocr_available(*, allow_missing: bool = False) -> tuple[str, ...]:
    missing = []
    broken = []
    for name in REQUIRED_HEADER_OCR_MODULES:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
            continue
        try:
            importlib.import_module(name)
        except Exception as exc:
            broken.append(f"{name} ({type(exc).__name__}: {exc})")

    if not missing and not broken:
        return REQUIRED_HEADER_OCR_MODULES
    if allow_missing:
        return tuple(name for name in REQUIRED_HEADER_OCR_MODULES if name not in missing and not any(item.startswith(f"{name} ") for item in broken))

    details = []
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if broken:
        details.append(f"import failed: {'; '.join(broken)}")
    raise PackagingValidationError(
        "Header OCR dependencies are missing or not usable in the build environment: "
        f"{'; '.join(details)}. Install them with `python -m pip install -r requirements-ocr.txt`; "
        "on Windows also verify native DLL prerequisites such as the Microsoft Visual C++ Redistributable."
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_vendored_header_ocr_models(model_dir: str | Path | None = None) -> tuple[Path, ...]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from modules.header_ocr_backend import RAPIDOCR_MODEL_ASSET_MANIFEST, default_rapidocr_model_dir

    root = Path(model_dir).expanduser() if model_dir is not None else default_rapidocr_model_dir()
    root = root.resolve()
    verified: list[Path] = []
    missing: list[str] = []
    mismatched: list[str] = []
    for filename, asset in RAPIDOCR_MODEL_ASSET_MANIFEST.items():
        path = root / filename
        if not path.is_file():
            missing.append(filename)
            continue
        actual_sha256 = _sha256(path)
        expected_sha256 = str(asset['sha256'])
        if actual_sha256 != expected_sha256:
            mismatched.append(f"{filename} expected {expected_sha256} got {actual_sha256}")
            continue
        verified.append(path)

    if missing or mismatched:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if mismatched:
            details.append(f"sha256 mismatch: {'; '.join(mismatched)}")
        raise PackagingValidationError(
            f"Vendored RapidOCR model validation failed in {root}: {'; '.join(details)}. "
            "Run `python scripts/fetch_rapidocr_models.py` and rebuild."
        )
    return tuple(verified)


def validate_third_party_notice(notice_path: str | Path | None = None) -> Path:
    notice = Path(notice_path) if notice_path is not None else REQUIRED_THIRD_PARTY_NOTICE
    notice = notice.resolve()
    if not notice.is_file():
        raise PackagingValidationError(f"Third-party notice file not found: {notice}")

    text = notice.read_text(encoding='utf-8')
    required_terms = (
        'RapidOCR',
        'Apache-2.0',
        'Baidu',
        'ONNX Runtime',
        'MIT',
        'OpenVINO',
        'OpenCV',
        'NumPy',
        'BSD-3-Clause',
    )
    missing_terms = tuple(term for term in required_terms if term not in text)
    if missing_terms:
        raise PackagingValidationError(
            f"Third-party notice file {notice} is missing required OCR license terms: {', '.join(missing_terms)}."
        )
    return notice


def validate_nuitka_report_has_header_ocr(report_path: str | Path) -> tuple[str, ...]:
    report = Path(report_path)
    if not report.is_file():
        raise PackagingValidationError(f"Nuitka build report not found: {report}")

    root = ET.parse(report).getroot()
    haystack = "\n".join(_flatten_report_strings(root))
    missing_modules = tuple(module_name for module_name in REQUIRED_HEADER_OCR_REPORT_MODULES if module_name not in haystack)
    if missing_modules:
        raise PackagingValidationError(
            f"Nuitka build report {report} is missing required header OCR modules: {', '.join(missing_modules)}."
        )

    from modules.header_ocr_backend import RAPIDOCR_MODEL_ASSET_MANIFEST

    missing_models = tuple(filename for filename in RAPIDOCR_MODEL_ASSET_MANIFEST if filename not in haystack)
    if missing_models:
        raise PackagingValidationError(
            f"Nuitka build report {report} is missing vendored RapidOCR model data files: {', '.join(missing_models)}."
        )
    if 'THIRD_PARTY_NOTICES.md' not in haystack:
        raise PackagingValidationError(
            f"Nuitka build report {report} is missing bundled third-party notices: THIRD_PARTY_NOTICES.md."
        )
    return REQUIRED_HEADER_OCR_REPORT_MODULES


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', help='Path to nuitka-build-report.xml')
    parser.add_argument(
        '--allow-broken-pdf-parser-build',
        action='store_true',
        help='Unsafe override: only use when intentionally bypassing the required packaged PDF parser gate.',
    )
    parser.add_argument(
        '--require-header-ocr',
        action='store_true',
        help='Validate RapidOCR runtime dependencies, vendored model files, and Nuitka report entries.',
    )
    parser.add_argument(
        '--allow-missing-header-ocr-build',
        action='store_true',
        help='Unsafe override: skip strict header OCR validation.',
    )
    parser.add_argument(
        '--header-ocr-model-dir',
        help='Optional model directory override for vendored RapidOCR model validation.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.report and not args.require_header_ocr:
        raise PackagingValidationError("Nothing to validate: pass --report and/or --require-header-ocr.")

    if args.report:
        require_pdf_backend_available(allow_broken=args.allow_broken_pdf_parser_build)
        included = validate_nuitka_report_has_pdf_backend(args.report)
        print(f"Validated packaged PDF parser backends in report: {', '.join(included)}")

    if args.require_header_ocr and not args.allow_missing_header_ocr_build:
        require_header_ocr_available(allow_missing=False)
        models = validate_vendored_header_ocr_models(args.header_ocr_model_dir)
        validate_third_party_notice()
        if args.report:
            validate_nuitka_report_has_header_ocr(args.report)
        print(f"Validated packaged header OCR dependencies and {len(models)} vendored model files.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
