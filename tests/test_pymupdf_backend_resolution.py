import importlib
import sys
import types


class _DummyCustomLogger:
    def __init__(self, *_args, **_kwargs):
        pass


def _load_cmm_report_parser_module():
    custom_logger_stub = types.ModuleType("modules.custom_logger")
    custom_logger_stub.CustomLogger = _DummyCustomLogger
    sys.modules.setdefault("modules.custom_logger", custom_logger_stub)
    return importlib.import_module("modules.cmm_report_parser")


class _FakeSpec:  # simple non-None sentinel
    pass


def test_resolve_prefers_pymupdf_when_backend_available(monkeypatch):
    cmm_report_parser = _load_cmm_report_parser_module()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: _FakeSpec() if name in {"pymupdf", "fitz"} else None)

    pymupdf_stub = types.SimpleNamespace(open=lambda *_args, **_kwargs: None)
    fitz_stub = types.SimpleNamespace(open=lambda *_args, **_kwargs: None)

    def fake_import(name):
        return {"pymupdf": pymupdf_stub, "fitz": fitz_stub}[name]

    monkeypatch.setattr(importlib, "import_module", fake_import)

    assert cmm_report_parser._resolve_pymupdf_backend_module() == "pymupdf"


def test_resolve_falls_back_to_fitz_when_pymupdf_import_fails(monkeypatch):
    cmm_report_parser = _load_cmm_report_parser_module()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: _FakeSpec() if name in {"pymupdf", "fitz"} else None)

    fitz_stub = types.SimpleNamespace(open=lambda *_args, **_kwargs: None)

    def fake_import(name):
        if name == "pymupdf":
            raise ImportError("pymupdf unavailable")
        return fitz_stub

    monkeypatch.setattr(importlib, "import_module", fake_import)

    assert cmm_report_parser._resolve_pymupdf_backend_module() == "fitz"


def test_resolve_rejects_fitz_without_open(monkeypatch):
    cmm_report_parser = _load_cmm_report_parser_module()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: _FakeSpec() if name == "fitz" else None)
    monkeypatch.setattr(importlib, "import_module", lambda _name: types.SimpleNamespace())

    assert cmm_report_parser._resolve_pymupdf_backend_module() is None
