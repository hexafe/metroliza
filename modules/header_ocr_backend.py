"""Lazy RapidOCR backend for header-band OCR.

This module keeps ``rapidocr`` import-time free until a caller actually asks for
OCR. It also normalizes the RapidOCR result into a small record set that carries
text, confidence, box, and diagnostics for downstream header geometry handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_HEADER_OCR_BACKEND = "rapidocr_latin"
RAPIDOCR_MODEL_FILENAMES = {
    "det_model_path": "ch_PP-OCRv4_det_mobile.onnx",
    "cls_model_path": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "rec_model_path": "latin_PP-OCRv3_rec_mobile.onnx",
}
RAPIDOCR_MODEL_ASSET_MANIFEST = {
    "ch_PP-OCRv4_det_mobile.onnx": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/onnx/PP-OCRv4/det/ch_PP-OCRv4_det_mobile.onnx",
        "sha256": "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9",
    },
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    },
    "latin_PP-OCRv3_rec_mobile.onnx": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/onnx/PP-OCRv4/rec/latin_PP-OCRv3_rec_mobile.onnx",
        "sha256": "e9d7a33667e8aaa702862975186adf2012e3f390cc0f9422865957125f8071cf",
    },
}
DEFAULT_LATIN_PARAMS = {
    "Det.engine_type": "onnxruntime",
    "Det.lang_type": "ch",
    "Det.model_type": "mobile",
    "Det.ocr_version": "PP-OCRv4",
    "Cls.engine_type": "onnxruntime",
    "Cls.lang_type": "ch",
    "Cls.model_type": "mobile",
    "Cls.ocr_version": "PP-OCRv4",
    "Rec.engine_type": "onnxruntime",
    "Rec.lang_type": "latin",
    "Rec.model_type": "mobile",
    "Rec.ocr_version": "PP-OCRv4",
}
RAPIDOCR_ENUM_PARAM_TYPES = {
    "Det.engine_type": "EngineType",
    "Det.lang_type": "LangDet",
    "Det.model_type": "ModelType",
    "Det.ocr_version": "OCRVersion",
    "Cls.engine_type": "EngineType",
    "Cls.lang_type": "LangDet",
    "Cls.model_type": "ModelType",
    "Cls.ocr_version": "OCRVersion",
    "Rec.engine_type": "EngineType",
    "Rec.lang_type": "LangRec",
    "Rec.model_type": "ModelType",
    "Rec.ocr_version": "OCRVersion",
}


@dataclass(frozen=True)
class RapidOcrLatinModelPaths:
    """Explicit model file paths for the RapidOCR Latin backend."""

    det_model_path: str | Path
    cls_model_path: str | Path
    rec_model_path: str | Path
    rec_keys_path: str | Path | None = None


@dataclass(frozen=True)
class RapidOcrLatinBackendConfig:
    """Configuration for the lazy RapidOCR Latin backend."""

    model_paths: RapidOcrLatinModelPaths
    params: dict[str, Any] = field(default_factory=dict)
    source_name: str = "rapidocr_latin"


@dataclass(frozen=True)
class HeaderOcrRecord:
    """Normalized OCR record emitted by the backend."""

    text: str
    confidence: float | None
    box: tuple[tuple[float, float], ...] | None
    source: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HeaderOcrRun:
    """Backend OCR response with normalized records and diagnostics."""

    records: tuple[HeaderOcrRecord, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _runtime_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def default_rapidocr_model_dir() -> Path:
    return _runtime_root() / "modules" / "ocr_models" / "rapidocr"


def default_rapidocr_latin_model_paths(
    model_dir: str | Path | None = None,
) -> RapidOcrLatinModelPaths:
    root = Path(model_dir) if model_dir is not None else default_rapidocr_model_dir()
    return RapidOcrLatinModelPaths(
        det_model_path=root / RAPIDOCR_MODEL_FILENAMES["det_model_path"],
        cls_model_path=root / RAPIDOCR_MODEL_FILENAMES["cls_model_path"],
        rec_model_path=root / RAPIDOCR_MODEL_FILENAMES["rec_model_path"],
    )


def missing_rapidocr_latin_model_paths(model_paths: RapidOcrLatinModelPaths) -> tuple[Path, ...]:
    paths = (
        model_paths.det_model_path,
        model_paths.cls_model_path,
        model_paths.rec_model_path,
        model_paths.rec_keys_path,
    )
    return tuple(Path(path) for path in paths if path is not None and not Path(path).exists())


def _rapidocr_enum_member_name(value: Any) -> str:
    return "".join(char for char in str(value).upper() if char.isalnum())


def _coerce_rapidocr_param_enums(params: Mapping[str, Any], rapidocr_module: Any) -> dict[str, Any]:
    coerced = dict(params)
    for key, enum_type_name in RAPIDOCR_ENUM_PARAM_TYPES.items():
        enum_type = getattr(rapidocr_module, enum_type_name, None)
        if enum_type is None or key not in coerced:
            continue

        value = coerced[key]
        if isinstance(value, enum_type):
            continue

        member_name = _rapidocr_enum_member_name(value)
        try:
            coerced[key] = enum_type[member_name]
        except (KeyError, TypeError):
            pass
    return coerced


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _json_safe(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _box_points(box: Any) -> tuple[tuple[float, float], ...] | None:
    if box is None:
        return None
    if isinstance(box, Mapping):
        if all(key in box for key in ("x0", "y0", "x1", "y1")):
            x0 = float(box["x0"])
            y0 = float(box["y0"])
            x1 = float(box["x1"])
            y1 = float(box["y1"])
            return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        nested_box = box.get("box")
        if nested_box is not None:
            return _box_points(nested_box)
        nested_box = box.get("dt_box")
        if nested_box is not None:
            return _box_points(nested_box)
        return None
    if isinstance(box, Sequence) and len(box) == 4 and all(
        isinstance(item, (int, float)) for item in box
    ):
        x0, y0, x1, y1 = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    if isinstance(box, Sequence):
        points: list[tuple[float, float]] = []
        for item in box:
            if not isinstance(item, Sequence) or len(item) < 2:
                continue
            try:
                points.append((float(item[0]), float(item[1])))
            except (TypeError, ValueError):
                continue
        return tuple(points) if points else None
    return None


def _coerce_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_from_parts(
    *,
    text: Any,
    confidence: Any,
    box: Any,
    source: str,
    diagnostics: Mapping[str, Any] | None,
) -> HeaderOcrRecord:
    return HeaderOcrRecord(
        text=str(text).strip(),
        confidence=_coerce_confidence(confidence),
        box=_box_points(box),
        source=source,
        diagnostics=dict(diagnostics or {}),
    )


def _records_from_attribute_arrays(result: Any, *, source: str) -> list[HeaderOcrRecord]:
    txts = _as_list(getattr(result, "txts", None))
    scores = _as_list(getattr(result, "scores", None))
    boxes = _as_list(getattr(result, "boxes", None))
    records: list[HeaderOcrRecord] = []
    for index, text in enumerate(txts):
        score = scores[index] if index < len(scores) else None
        box = boxes[index] if index < len(boxes) else None
        records.append(
            _record_from_parts(
                text=text,
                confidence=score,
                box=box,
                source=source,
                diagnostics={
                    "raw_index": index,
                    "raw_shape": "attribute_arrays",
                },
            )
        )
    return records


def _records_from_list(result: Sequence[Any], *, source: str) -> list[HeaderOcrRecord]:
    records: list[HeaderOcrRecord] = []
    for index, item in enumerate(result):
        if isinstance(item, Mapping):
            text = item.get("text") or item.get("txt") or item.get("rec_text") or ""
            confidence = (
                item.get("confidence")
                if item.get("confidence") is not None
                else item.get("score")
            )
            if confidence is None:
                confidence = item.get("rec_score")
            box = item.get("box") or item.get("dt_box") or item.get("points")
            records.append(
                _record_from_parts(
                    text=text,
                    confidence=confidence,
                    box=box,
                    source=source,
                    diagnostics={
                        "raw_index": index,
                        "raw_shape": "mapping",
                        "raw_keys": tuple(sorted(item.keys())),
                    },
                )
            )
            continue

        if isinstance(item, Sequence) and len(item) >= 2:
            if (
                isinstance(item[1], Sequence)
                and not isinstance(item[1], (str, bytes))
                and len(item[1]) >= 2
            ):
                box = item[0]
                text = item[1][0]
                confidence = item[1][1]
            else:
                box = item[0]
                text = item[1]
                confidence = item[2] if len(item) >= 3 else None
            records.append(
                _record_from_parts(
                    text=text,
                    confidence=confidence,
                    box=box,
                    source=source,
                    diagnostics={
                        "raw_index": index,
                        "raw_shape": "sequence",
                    },
                )
            )
    return records


def normalize_rapidocr_result(
    result: Any,
    *,
    source: str = "rapidocr_latin",
    diagnostics: Mapping[str, Any] | None = None,
) -> HeaderOcrRun:
    """Normalize a RapidOCR response into stable record objects."""

    merged_diagnostics = dict(diagnostics or {})
    merged_diagnostics["raw_result_type"] = type(result).__name__

    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], (int, float)):
        merged_diagnostics["elapsed"] = float(result[1])
        return normalize_rapidocr_result(result[0], source=source, diagnostics=merged_diagnostics)

    if hasattr(result, "txts"):
        records = _records_from_attribute_arrays(result, source=source)
        return HeaderOcrRun(records=tuple(records), diagnostics=merged_diagnostics)

    if isinstance(result, Mapping):
        records = _records_from_list([result], source=source)
        return HeaderOcrRun(records=tuple(records), diagnostics=merged_diagnostics)

    if isinstance(result, tuple):
        records = _records_from_list(result, source=source)
        if records:
            return HeaderOcrRun(records=tuple(records), diagnostics=merged_diagnostics)
        return normalize_rapidocr_result(result[0], source=source, diagnostics=merged_diagnostics)

    if isinstance(result, list):
        records = _records_from_list(result, source=source)
        return HeaderOcrRun(records=tuple(records), diagnostics=merged_diagnostics)

    text = str(result).strip()
    record = _record_from_parts(
        text=text,
        confidence=None,
        box=None,
        source=source,
        diagnostics={"raw_shape": "scalar"},
    )
    return HeaderOcrRun(records=(record,), diagnostics=merged_diagnostics)


class RapidOcrLatinBackend:
    """Lazy RapidOCR wrapper configured for explicit Latin model paths."""

    def __init__(self, config: RapidOcrLatinBackendConfig) -> None:
        """Store the backend config without importing RapidOCR."""

        self.config = config
        self._engine: Any | None = None

    def _build_params(self) -> dict[str, Any]:
        params = dict(DEFAULT_LATIN_PARAMS)
        params.update(
            {
                "Det.model_path": str(self.config.model_paths.det_model_path),
                "Cls.model_path": str(self.config.model_paths.cls_model_path),
                "Rec.model_path": str(self.config.model_paths.rec_model_path),
            }
        )
        if self.config.model_paths.rec_keys_path is not None:
            params["Rec.rec_keys_path"] = str(self.config.model_paths.rec_keys_path)
        params.update(self.config.params)
        return params

    def _build_engine_params(self, rapidocr_module: Any) -> dict[str, Any]:
        return _coerce_rapidocr_param_enums(self._build_params(), rapidocr_module)

    def load_engine(self) -> Any:
        """Import RapidOCR on demand and cache the instantiated engine."""

        if self._engine is not None:
            return self._engine

        rapidocr_module = importlib.import_module("rapidocr")
        rapidocr_class = getattr(rapidocr_module, "RapidOCR", None)
        if rapidocr_class is None:
            raise ImportError("rapidocr.RapidOCR is not available in the installed package.")

        self._engine = rapidocr_class(params=self._build_engine_params(rapidocr_module))
        return self._engine

    def recognize(self, image_path: str | Path) -> HeaderOcrRun:
        """Run OCR against a rendered crop and normalize the result."""

        image = Path(image_path).expanduser()
        if not image.exists():
            raise FileNotFoundError(str(image))

        engine = self.load_engine()
        result = engine(str(image))
        run = normalize_rapidocr_result(
            result,
            source=self.config.source_name,
            diagnostics={
                "backend": self.config.source_name,
                "image_path": str(image),
                "model_paths": {
                    "det_model_path": str(self.config.model_paths.det_model_path),
                    "cls_model_path": str(self.config.model_paths.cls_model_path),
                    "rec_model_path": str(self.config.model_paths.rec_model_path),
                    "rec_keys_path": str(self.config.model_paths.rec_keys_path)
                    if self.config.model_paths.rec_keys_path is not None
                    else None,
                },
                "params": self._build_params(),
            },
        )
        return run
