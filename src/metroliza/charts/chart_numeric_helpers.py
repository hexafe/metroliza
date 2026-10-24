"""Small numeric helpers shared by chart spec builders and renderers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
import math
import sys

import numpy as np

from metroliza.shared.numeric_coercion import coerce_finite_float


def as_finite_float(value: Any) -> float | None:
    return coerce_finite_float(value)


def _is_scalar_chart_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes)):
        return True
    if isinstance(value, Mapping):
        return False
    if isinstance(value, np.ndarray):
        return value.ndim == 0
    try:
        iter(value)
    except TypeError:
        return True
    return False


def _raw_numeric_items(values: Any) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, Mapping):
        if "values" in values:
            return _raw_numeric_items(values.get("values"))
        return list(values.values())
    if isinstance(values, np.ndarray):
        if values.ndim == 0:
            return [values.item()]
        return values.reshape(-1).tolist()
    if isinstance(values, (str, bytes)):
        return [values]
    try:
        return list(values)
    except TypeError:
        return [values]


def _plain_numeric_state(value: Any, *, allowed: set[str] | None = None) -> dict[str, Any] | None:
    state = vars(value)
    # Validate keys before any lookup: even an exact dict can contain custom
    # keys whose equality/hash callbacks would be new work before fallback.
    if type(state) is not dict or any(type(key) is not str for key in state):
        return None
    if allowed is not None and any(key not in allowed for key in state):
        return None
    return state


def _native_numeric_axis(axis: Any) -> bool:
    pandas = sys.modules["pandas"]
    if type(axis) not in (pandas.RangeIndex, pandas.Index):
        return False
    state = _plain_numeric_state(axis)
    if state is None:
        return False
    # list(Series) also requests a length hint. Only bypass the original
    # axis length read when its native implementation has native storage.
    if type(axis) is pandas.RangeIndex:
        return type(dict.get(state, "_range")) is range
    return type(dict.get(state, "_data")) is np.ndarray


def _native_numeric_manager_array(manager: Any) -> np.ndarray | None:
    from pandas.core.internals.blocks import NumpyBlock
    from pandas.core.internals.managers import SingleBlockManager

    if type(manager) is not SingleBlockManager:
        return None
    state = _plain_numeric_state(manager, allowed={"axes", "blocks", "_block",
                                                  "_known_consolidated", "_is_consolidated"})
    if state is None:
        return None
    axes, blocks = dict.get(state, "axes"), dict.get(state, "blocks")
    if type(axes) is not list or type(blocks) is not tuple:
        return None
    if len(axes) != 1 or len(blocks) != 1:
        return None
    if not _native_numeric_axis(axes[0]):
        return None
    block = blocks[0]
    if type(block) is not NumpyBlock or dict.get(state, "_block", block) is not block:
        return None
    # Native block.values is a storage descriptor. Do not dispatch manager
    # dtype/internal_values or Series._values while establishing eligibility.
    array = block.values
    return array if type(array) is np.ndarray else None


def _native_numeric_series_array(values: Any) -> np.ndarray | None:
    pandas = sys.modules.get("pandas")
    if pandas is None or type(values) is not getattr(pandas, "Series", None):
        return None
    state = _plain_numeric_state(values)
    if state is None:
        return None
    return _native_numeric_manager_array(dict.get(state, "_mgr"))


def _finite_float64_array(values: Any) -> np.ndarray | None:
    # Unsupported raw storage declines before dtype/backing-array dispatch;
    # the original scalar path retains all of its reads, warnings and errors.
    array = values if type(values) is np.ndarray else _native_numeric_series_array(values)
    if array is None or array.dtype != np.dtype(float):
        return None
    flat = array.reshape(-1)
    return flat[np.isfinite(flat)]


def finite_float_list(values: Any) -> list[float]:
    array = _finite_float64_array(values)
    if array is not None:
        return array.tolist()
    output: list[float] = []
    for value in _raw_numeric_items(values):
        number = as_finite_float(value)
        if number is not None:
            output.append(float(number))
    return output


def finite_array(values: Iterable[Any] | Any) -> np.ndarray:
    array = _finite_float64_array(values)
    if array is not None:
        return array
    return np.asarray(finite_float_list(values), dtype=float)


def finite_series_list(values: Any, *, label_count: int | None = None) -> list[list[float]]:
    if values is None:
        return []

    if isinstance(values, Mapping):
        if "series" in values:
            return finite_series_list(values.get("series"), label_count=label_count)
        if "values" in values:
            numeric_values = finite_float_list(values.get("values"))
            return [numeric_values]
        numeric_values = finite_float_list(values)
        return [numeric_values]

    if isinstance(values, np.ndarray):
        if values.ndim == 0:
            raw_groups = [values.item()]
        elif values.ndim == 1:
            raw_values = values.tolist()
            raw_groups = [raw_values] if label_count == 1 else raw_values
        else:
            raw_groups = list(values.tolist())
    elif isinstance(values, (str, bytes)):
        raw_groups = [values]
    else:
        try:
            raw_values = list(values)
        except TypeError:
            raw_groups = [values]
        else:
            if raw_values and all(_is_scalar_chart_value(item) for item in raw_values):
                raw_groups = [raw_values] if label_count == 1 else raw_values
            else:
                raw_groups = raw_values

    normalized: list[list[float]] = []
    for group_values in raw_groups:
        numeric_values = finite_float_list(group_values)
        normalized.append(numeric_values)
    return normalized


def coerce_string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, np.ndarray):
        raw_values = values.reshape(-1).tolist()
    elif isinstance(values, (str, bytes)):
        raw_values = [values]
    else:
        try:
            raw_values = list(values)
        except TypeError:
            raw_values = [values]
    return [str(value) if value is not None else "" for value in raw_values]


def align_labels_to_series(labels: Any, series_count: int, *, default_prefix: str = "Group") -> list[str]:
    count = max(0, int(series_count or 0))
    normalized = coerce_string_list(labels)[:count]
    while len(normalized) < count:
        normalized.append(f"{default_prefix} {len(normalized) + 1}")
    return normalized


def line_ticks(min_value: float, max_value: float, *, count: int = 5) -> list[float]:
    if not math.isfinite(min_value) or not math.isfinite(max_value):
        return [0.0, 1.0]
    if math.isclose(min_value, max_value):
        return [min_value]
    return [min_value + ((max_value - min_value) * idx / max(1, count - 1)) for idx in range(count)]


def format_tick(value: float) -> str:
    numeric = float(value)
    if abs(numeric) >= 100 or math.isclose(numeric, round(numeric), abs_tol=1e-9):
        return f"{numeric:.0f}"
    if abs(numeric) >= 10:
        return f"{numeric:.1f}"
    return f"{numeric:.3f}".rstrip("0").rstrip(".")


def format_histogram_stat_value(value: Any, *, decimals: int = 3) -> str:
    numeric = as_finite_float(value)
    if numeric is None:
        return "N/A"
    if math.isclose(numeric, round(numeric), abs_tol=1e-9):
        return f"{numeric:.0f}"
    return f"{numeric:.{decimals}f}"
