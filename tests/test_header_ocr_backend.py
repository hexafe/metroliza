from __future__ import annotations

import importlib
import sys
import types
from enum import Enum

import pytest


def test_rapidocr_backend_is_lazy_and_normalizes_common_result_shapes(tmp_path, monkeypatch):
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
    monkeypatch.setitem(sys.modules, "onnxruntime", types.ModuleType("onnxruntime"))
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)

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


def test_rapidocr_backend_coerces_string_defaults_to_rapidocr_enums(tmp_path, monkeypatch):
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
    monkeypatch.setitem(sys.modules, "onnxruntime", types.ModuleType("onnxruntime"))
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)

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

    params = calls["params"]
    assert params["Det.engine_type"] is EngineType.ONNXRUNTIME
    assert params["Det.lang_type"] is LangDet.CH
    assert params["Det.model_type"] is ModelType.MOBILE
    assert params["Det.ocr_version"] is OCRVersion.PPOCRV4
    assert params["Cls.ocr_version"] is OCRVersion.PPOCRV4
    assert params["Rec.lang_type"] is LangRec.LATIN
    assert params["Rec.ocr_version"] is OCRVersion.PPOCRV4


def test_cached_rapidocr_backend_reuses_engine_within_thread(tmp_path, monkeypatch):
    backend_module = importlib.import_module("modules.header_ocr_backend")
    backend_module.clear_cached_rapidocr_latin_backends()
    calls = {"init_count": 0}

    class FakeRapidOCR:
        def __init__(self, *args, **kwargs):
            calls["init_count"] += 1

        def __call__(self, image_path):
            return types.SimpleNamespace(txts=[], scores=[], boxes=[])

    fake_module = types.ModuleType("rapidocr")
    fake_module.RapidOCR = FakeRapidOCR
    monkeypatch.setitem(sys.modules, "onnxruntime", types.ModuleType("onnxruntime"))
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    try:
        config = backend_module.RapidOcrLatinBackendConfig(
            model_paths=backend_module.RapidOcrLatinModelPaths(
                det_model_path="det.onnx",
                cls_model_path="cls.onnx",
                rec_model_path="rec.onnx",
            ),
            params={"EngineConfig.onnxruntime.intra_op_num_threads": 1},
        )
        backend_a = backend_module.get_cached_rapidocr_latin_backend(config)
        backend_b = backend_module.get_cached_rapidocr_latin_backend(config)

        image_path = tmp_path / "header.png"
        image_path.write_bytes(b"not-a-real-image")
        backend_a.recognize(image_path)
        backend_b.recognize(image_path)
    finally:
        backend_module.clear_cached_rapidocr_latin_backends()

    assert backend_a is backend_b
    assert calls["init_count"] == 1


def test_rapidocr_runtime_config_defaults_to_onnxruntime_cpu_threads():
    backend_module = importlib.import_module("modules.header_ocr_backend")

    config = backend_module.rapidocr_latin_runtime_config_from_env(
        env={},
        ocr_thread_count=4,
    )

    assert config.engine == "onnxruntime"
    assert config.accelerator == "cpu"
    assert config.params["Det.engine_type"] == "onnxruntime"
    assert config.params["Cls.engine_type"] == "onnxruntime"
    assert config.params["Rec.engine_type"] == "onnxruntime"
    assert config.params["EngineConfig.onnxruntime.intra_op_num_threads"] == 4
    assert config.params["EngineConfig.onnxruntime.inter_op_num_threads"] == 1
    assert "EngineConfig.onnxruntime.use_cuda" not in config.params
    assert "EngineConfig.onnxruntime.use_dml" not in config.params


def test_rapidocr_runtime_config_maps_directml_accelerator():
    backend_module = importlib.import_module("modules.header_ocr_backend")

    config = backend_module.rapidocr_latin_runtime_config_from_env(
        env={
            "METROLIZA_HEADER_OCR_ACCELERATOR": "DirectML",
            "METROLIZA_HEADER_OCR_DEVICE_ID": "1",
        },
        ocr_thread_count=2,
    )

    assert config.engine == "onnxruntime"
    assert config.accelerator == "dml"
    assert config.params["EngineConfig.onnxruntime.use_dml"] is True
    assert config.params["EngineConfig.onnxruntime.dm_ep_cfg"] == {"device_id": 1}


def test_rapidocr_runtime_config_maps_cuda_accelerator():
    backend_module = importlib.import_module("modules.header_ocr_backend")

    config = backend_module.rapidocr_latin_runtime_config_from_env(
        env={
            "METROLIZA_HEADER_OCR_ACCELERATOR": "cuda",
            "METROLIZA_HEADER_OCR_DEVICE_ID": "2",
        },
    )

    assert config.engine == "onnxruntime"
    assert config.accelerator == "cuda"
    assert config.params["EngineConfig.onnxruntime.use_cuda"] is True
    assert config.params["EngineConfig.onnxruntime.cuda_ep_cfg.device_id"] == 2


def test_rapidocr_runtime_config_maps_openvino_cpu():
    backend_module = importlib.import_module("modules.header_ocr_backend")

    config = backend_module.rapidocr_latin_runtime_config_from_env(
        env={
            "METROLIZA_HEADER_OCR_ENGINE": "openvino",
            "METROLIZA_HEADER_OCR_OPENVINO_PERFORMANCE_HINT": "LATENCY",
            "METROLIZA_HEADER_OCR_OPENVINO_NUM_STREAMS": "2",
        },
        ocr_thread_count=3,
    )

    assert config.engine == "openvino"
    assert config.accelerator == "cpu"
    assert config.params["Det.engine_type"] == "openvino"
    assert config.params["Cls.engine_type"] == "openvino"
    assert config.params["Rec.engine_type"] == "openvino"
    assert config.params["EngineConfig.openvino.inference_num_threads"] == 3
    assert config.params["EngineConfig.openvino.performance_hint"] == "LATENCY"
    assert config.params["EngineConfig.openvino.num_streams"] == 2


def test_rapidocr_runtime_config_rejects_openvino_gpu_until_wrapper_exists():
    backend_module = importlib.import_module("modules.header_ocr_backend")

    with pytest.raises(ValueError, match="custom OpenVINO session wrapper"):
        backend_module.rapidocr_latin_runtime_config_from_env(
            env={
                "METROLIZA_HEADER_OCR_ENGINE": "openvino",
                "METROLIZA_HEADER_OCR_ACCELERATOR": "gpu",
            }
        )


def test_rapidocr_runtime_config_maps_tensorrt_options():
    backend_module = importlib.import_module("modules.header_ocr_backend")

    config = backend_module.rapidocr_latin_runtime_config_from_env(
        env={
            "METROLIZA_HEADER_OCR_ENGINE": "trt",
            "METROLIZA_HEADER_OCR_DEVICE_ID": "2",
            "METROLIZA_HEADER_OCR_CACHE_DIR": "/tmp/metroliza-trt",
            "METROLIZA_HEADER_OCR_TENSORRT_FP16": "false",
            "METROLIZA_HEADER_OCR_TENSORRT_INT8": "true",
            "METROLIZA_HEADER_OCR_TENSORRT_FORCE_REBUILD": "true",
        }
    )

    assert config.engine == "tensorrt"
    assert config.params["Det.engine_type"] == "tensorrt"
    assert config.params["EngineConfig.tensorrt.device_id"] == 2
    assert config.params["EngineConfig.tensorrt.cache_dir"] == "/tmp/metroliza-trt"
    assert config.params["EngineConfig.tensorrt.use_fp16"] is False
    assert config.params["EngineConfig.tensorrt.use_int8"] is True
    assert config.params["EngineConfig.tensorrt.force_rebuild"] is True


def test_non_onnxruntime_runtime_does_not_preload_onnxruntime(tmp_path, monkeypatch):
    backend_module = importlib.import_module("modules.header_ocr_backend")

    class _OnnxRuntimeGuardFinder:
        def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
            if fullname == "onnxruntime":
                raise AssertionError("onnxruntime should not be preloaded for OpenVINO")
            return None

    class FakeRapidOCR:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, image_path):
            return types.SimpleNamespace(txts=[], scores=[], boxes=[])

    fake_module = types.ModuleType("rapidocr")
    fake_module.RapidOCR = FakeRapidOCR
    monkeypatch.delitem(sys.modules, "onnxruntime", raising=False)
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)

    runtime_config = backend_module.rapidocr_latin_runtime_config_from_env(
        env={"METROLIZA_HEADER_OCR_ENGINE": "openvino"}
    )
    backend = backend_module.RapidOcrLatinBackend(
        backend_module.RapidOcrLatinBackendConfig(
            model_paths=backend_module.RapidOcrLatinModelPaths(
                det_model_path="det.onnx",
                cls_model_path="cls.onnx",
                rec_model_path="rec.onnx",
            ),
            params=runtime_config.params,
        )
    )

    guard = _OnnxRuntimeGuardFinder()
    sys.meta_path.insert(0, guard)
    try:
        image_path = tmp_path / "header.png"
        image_path.write_bytes(b"not-a-real-image")
        backend.recognize(image_path)
    finally:
        sys.meta_path.remove(guard)
