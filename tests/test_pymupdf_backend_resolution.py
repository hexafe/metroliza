import importlib


pdf_backend = importlib.import_module("modules.pdf_backend")


def test_resolve_prefers_pymupdf_when_backend_available(monkeypatch):
    pymupdf_stub = type("PyMuPDFStub", (), {"open": staticmethod(lambda *_args, **_kwargs: None)})()
    fitz_stub = type("FitzStub", (), {"open": staticmethod(lambda *_args, **_kwargs: None)})()

    monkeypatch.setattr(pdf_backend, "_PYMUPDF_BACKEND", pymupdf_stub)
    monkeypatch.setattr(pdf_backend, "_FITZ_BACKEND", fitz_stub)

    assert pdf_backend.resolve_pdf_backend_module_name() == "pymupdf"


def test_resolve_falls_back_to_fitz_when_pymupdf_backend_missing(monkeypatch):
    fitz_stub = type("FitzStub", (), {"open": staticmethod(lambda *_args, **_kwargs: None)})()

    monkeypatch.setattr(pdf_backend, "_PYMUPDF_BACKEND", None)
    monkeypatch.setattr(pdf_backend, "_FITZ_BACKEND", fitz_stub)

    assert pdf_backend.resolve_pdf_backend_module_name() == "fitz"


def test_resolve_rejects_backend_without_open(monkeypatch):
    monkeypatch.setattr(pdf_backend, "_PYMUPDF_BACKEND", object())
    monkeypatch.setattr(pdf_backend, "_FITZ_BACKEND", object())

    assert pdf_backend.resolve_pdf_backend_module_name() is None
