"""Validate packaged PDF parser dependencies for build pipelines."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    return included


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True, help='Path to nuitka-build-report.xml')
    parser.add_argument(
        '--allow-broken-pdf-parser-build',
        action='store_true',
        help='Unsafe override: only use when intentionally bypassing the required packaged PDF parser gate.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    require_pdf_backend_available(allow_broken=args.allow_broken_pdf_parser_build)
    included = validate_nuitka_report_has_pdf_backend(args.report)
    print(f"Validated packaged PDF parser backends in report: {', '.join(included)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
