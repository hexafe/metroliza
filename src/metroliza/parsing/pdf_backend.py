"""Shared PyMuPDF backend detection helpers for runtime and packaging validation."""

from __future__ import annotations

import importlib.util

try:
    import pymupdf as _PYMUPDF_BACKEND
except Exception:  # pragma: no cover - depends on optional runtime dependency
    _PYMUPDF_BACKEND = None

try:
    import fitz as _FITZ_BACKEND
except Exception:  # pragma: no cover - depends on optional runtime dependency
    _FITZ_BACKEND = None


PDF_BACKEND_CANDIDATES = ("pymupdf", "fitz")


def backend_required_error_message() -> str:
    return (
        "PyMuPDF is required to parse PDF reports. Install `PyMuPDF` (which "
        "provides either the `pymupdf` or `fitz` module) and remove any "
        "conflicting standalone `fitz` package."
    )


def _import_candidate_backend(module_name: str):
    module = {
        "pymupdf": _PYMUPDF_BACKEND,
        "fitz": _FITZ_BACKEND,
    }.get(module_name)

    if callable(getattr(module, "open", None)):
        return module
    return None


def resolve_pdf_backend_module_name() -> str | None:
    """Return the preferred import name for an available PyMuPDF backend."""
    for module_name in PDF_BACKEND_CANDIDATES:
        if importlib.util.find_spec(module_name) is None:
            continue

        module = _import_candidate_backend(module_name)
        if module is not None:
            return module_name

    return None


def load_pdf_backend():
    """Import and return the usable PyMuPDF backend module, if available."""
    backend_name = resolve_pdf_backend_module_name()
    if backend_name is None:
        return None

    return _import_candidate_backend(backend_name)


def require_pdf_backend():
    """Return the usable PyMuPDF backend module or raise a clear runtime error."""
    backend = load_pdf_backend()
    if backend is None:
        raise ImportError(backend_required_error_message())
    return backend
