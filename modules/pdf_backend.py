"""Shared PyMuPDF backend detection helpers for runtime and packaging validation."""

from __future__ import annotations

import importlib
import importlib.util


PDF_BACKEND_CANDIDATES = ("pymupdf", "fitz")


def backend_required_error_message() -> str:
    return (
        "PyMuPDF is required to parse PDF reports. Install `PyMuPDF` (which "
        "provides either the `pymupdf` or `fitz` module) and remove any "
        "conflicting standalone `fitz` package."
    )


def resolve_pdf_backend_module_name() -> str | None:
    """Return the preferred import name for an available PyMuPDF backend."""
    for module_name in PDF_BACKEND_CANDIDATES:
        if importlib.util.find_spec(module_name) is None:
            continue

        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue

        open_method = getattr(module, "open", None)
        if callable(open_method):
            return module_name

    return None


def load_pdf_backend():
    """Import and return the usable PyMuPDF backend module, if available."""
    backend_name = resolve_pdf_backend_module_name()
    if backend_name is None:
        return None

    try:
        return importlib.import_module(backend_name)
    except Exception:
        return None


def require_pdf_backend():
    """Return the usable PyMuPDF backend module or raise a clear runtime error."""
    backend = load_pdf_backend()
    if backend is None:
        raise ImportError(backend_required_error_message())
    return backend
