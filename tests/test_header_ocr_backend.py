from __future__ import annotations

import importlib
import sys
import types
from enum import Enum

import pytest


def test_rapidocr_backend_is_lazy_and_normalizes_common_result_shapes(tmp_path):
    class _RapidocrGuardFinder:
        def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
            if fullname == "rapidocr":
                raise AssertionError("rapidocr was imported during module import")
            return None

    guard = _RapidocrGuardFinder()
    sys.meta_path.insert(0, guard)
    try:
        backend_module = importlib.import_module("modules.header_ocr_backend")
    finally:
        sys.meta_path.remove(guard)

    calls: dict[str, object] = {}

    class FakeRapidOCR:
        def __init__(self, *args, **kwargs):
            calls["init_args"] = args
            calls["init_kwargs"] = kwargs

        def __call__(self, image_path):
            calls["image_path"] = image_path
            return types.SimpleNamespace(
                txts=["HEADER"],
                scores=[0.91],
                boxes=[[[1.0, 2.0], [3.0, 2.0], [3.0, 4.0], [1.0, 4.0]]],
            )

    fake_module = types.ModuleType("rapidocr")
    fake_module.RapidOCR = FakeRapidOCR
    sys.modules["rapidocr"] = fake_module
    try:
        config = backend_module.RapidOcrLatinBackendConfig(
            model_paths=backend_module.RapidOcrLatinModelPaths(
                det_model_path="det.onnx",
                cls_model_path="cls.onnx",
                rec_model_path="rec.onnx",
                rec_keys_path="latin.txt",
            )
        )
        backend = backend_module.RapidOcrLatinBackend(config)

        image_path = tmp_path / "header.png"
        image_path.write_bytes(b"not-a-real-image")

        run = backend.recognize(image_path)
    finally:
        sys.modules.pop("rapidocr", None)

    assert calls["init_kwargs"]["params"]["Det.model_path"] == "det.onnx"
    assert calls["init_kwargs"]["params"]["Cls.model_path"] == "cls.onnx"
    assert calls["init_kwargs"]["params"]["Rec.model_path"] == "rec.onnx"
    assert calls["init_kwargs"]["params"]["Rec.rec_keys_path"] == "latin.txt"
    assert calls["image_path"] == str(image_path)

    assert len(run.records) == 1
    record = run.records[0]
    assert record.text == "HEADER"
    assert record.confidence == pytest.approx(0.91)
    assert record.source == "rapidocr_latin"
    assert record.box == ((1.0, 2.0), (3.0, 2.0), (3.0, 4.0), (1.0, 4.0))
    assert run.diagnostics["backend"] == "rapidocr_latin"
    assert run.diagnostics["raw_result_type"] == "SimpleNamespace"


def test_rapidocr_backend_coerces_string_defaults_to_rapidocr_enums(tmp_path):
    backend_module = importlib.import_module("modules.header_ocr_backend")
    calls: dict[str, object] = {}

    class EngineType(Enum):
        ONNXRUNTIME = "onnxruntime"

    class LangDet(Enum):
        CH = "ch"

    class LangRec(Enum):
        LATIN = "latin"

    class ModelType(Enum):
        MOBILE = "mobile"

    class OCRVersion(Enum):
        PPOCRV4 = "PP-OCRv4"

    class FakeRapidOCR:
        def __init__(self, *args, **kwargs):
            calls["params"] = kwargs["params"]

        def __call__(self, image_path):
            return types.SimpleNamespace(txts=[], scores=[], boxes=[])

    fake_module = types.ModuleType("rapidocr")
    fake_module.RapidOCR = FakeRapidOCR
    fake_module.EngineType = EngineType
    fake_module.LangDet = LangDet
    fake_module.LangRec = LangRec
    fake_module.ModelType = ModelType
    fake_module.OCRVersion = OCRVersion
    sys.modules["rapidocr"] = fake_module
    try:
        config = backend_module.RapidOcrLatinBackendConfig(
            model_paths=backend_module.RapidOcrLatinModelPaths(
                det_model_path="det.onnx",
                cls_model_path="cls.onnx",
                rec_model_path="rec.onnx",
            )
        )
        backend = backend_module.RapidOcrLatinBackend(config)

        image_path = tmp_path / "header.png"
        image_path.write_bytes(b"not-a-real-image")

        backend.recognize(image_path)
    finally:
        sys.modules.pop("rapidocr", None)

    params = calls["params"]
    assert params["Det.engine_type"] is EngineType.ONNXRUNTIME
    assert params["Det.lang_type"] is LangDet.CH
    assert params["Det.model_type"] is ModelType.MOBILE
    assert params["Det.ocr_version"] is OCRVersion.PPOCRV4
    assert params["Cls.ocr_version"] is OCRVersion.PPOCRV4
    assert params["Rec.lang_type"] is LangRec.LATIN
    assert params["Rec.ocr_version"] is OCRVersion.PPOCRV4
