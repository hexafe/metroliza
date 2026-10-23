"""Independent controls for numeric chart normalization and its fallback."""
from collections.abc import Mapping
from decimal import Decimal
import math
import warnings

import numpy as np
import pandas as pd
import pytest

from metroliza.charts import chart_numeric_helpers as helpers


def _scalar_reference(values):
    # Frozen scalar contract from the pre-optimization implementation.
    if values is None:
        raw = []
    elif isinstance(values, Mapping):
        return _scalar_reference(values.get("values")) if "values" in values else _scalar_reference(list(values.values()))
    elif isinstance(values, np.ndarray):
        raw = [values.item()] if values.ndim == 0 else values.reshape(-1).tolist()
    elif isinstance(values, (str, bytes)):
        raw = [values]
    else:
        try:
            raw = list(values)
        except TypeError:
            raw = [values]
    result = []
    for value in raw:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def _observation(function, values):
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        try:
            output = function(values)
        except Exception as exc:
            result = ("error", type(exc), str(exc))
        else:
            array = np.asarray(output)
            result = ("values", type(output), array.dtype.str, array.shape, array.tobytes())
    return result, [(type(item.message), str(item.message)) for item in emitted]


def _inputs():
    floats = np.array([-0.0, 0.0, 1.5, np.nan, np.inf, -np.inf, -2.5])
    for dtype, bits in ((np.float16, np.uint16(0x7C01)), (np.float32, np.uint32(0x7F800001)),
                        (np.float64, np.uint64(0x7FF0000000000001))):
        signaling = np.array([bits]).view(dtype)
        yield signaling
        yield pd.Series(signaling)
    yield from (None, " 2.5 ", b"-0", 4, 10 ** 1000, np.array(-0.0), floats, floats[::-2],
                floats.reshape(1, -1), np.empty((0, 2)), floats.astype(">f8"),
                np.array([1, 2], dtype=np.int64), np.array([1 + 2j]),
                np.array([1, "2", None], dtype=object), np.array([1, 2], dtype=np.longdouble),
                [Decimal("1.25"), Decimal("NaN"), Decimal("sNaN"), "-0", "bad", None, float("inf")],
                {"values": floats}, {"a": 1, "b": "2"}, pd.Series(floats), pd.Series(floats[::-2]),
                pd.Series(floats, index=list("gfedcba"), name="Measurement"),
                pd.Series([1, None], dtype="Float64"), pd.Series(["2", "bad"]),
                np.ma.array([1.0, 2.0], mask=[False, True]))


@pytest.mark.parametrize("values", list(_inputs()))
@pytest.mark.parametrize("array_output", [False, True])
def test_numeric_normalization_matches_independent_scalar_contract(values, array_output):
    reference = (lambda value: np.asarray(_scalar_reference(value), dtype=float)) if array_output else _scalar_reference
    actual = helpers.finite_array if array_output else helpers.finite_float_list
    assert _observation(actual, values) == _observation(reference, values)


@pytest.mark.parametrize("values", [np.array([-0.0, 2.0]), pd.Series([-0.0, 2.0])])
def test_numeric_array_result_never_aliases_caller(values):
    result = helpers.finite_array(values)
    result[0] = 9.0
    assert math.copysign(1.0, values[0]) == -1.0
    values[1] = 11.0
    assert result[1] == 2.0
    assert result.dtype == np.dtype(float)
    assert result.ndim == 1


def test_numeric_fallback_preserves_conversion_order_warnings_and_errors():
    events = []

    class Number:
        def __init__(self, label, error=None):
            self.label, self.error = label, error

        def __float__(self):
            events.append(self.label)
            warnings.warn(self.label, UserWarning)
            if self.error:
                raise self.error(self.label)
            return -0.0

    for error in (None, ValueError, OverflowError, RuntimeError):
        values = [Number("first"), Number("second", error), Number("last")]
        expected = _observation(_scalar_reference, values)
        expected_events = events[:]
        events.clear()
        assert _observation(helpers.finite_float_list, values) == expected
        assert events == expected_events
        events.clear()


def test_numeric_array_subclass_keeps_tolist_dispatch():
    events = []

    class Array(np.ndarray):
        def tolist(self):
            events.append("tolist")
            return [3.0, -0.0]

    values = np.array([1.0, 2.0]).view(Array)
    assert helpers.finite_float_list(values) == [3.0, -0.0]
    assert events == ["tolist"]


def test_numeric_series_subclass_keeps_iteration_dispatch():
    class Series(pd.Series):
        def __iter__(self):
            return iter([3.0, -0.0])

    assert helpers.finite_float_list(Series([1.0, 2.0])) == [3.0, -0.0]


def test_numeric_series_does_not_newly_call_shadowed_conversion_methods():
    values = pd.Series([-0.0, 2.0])

    def fail(*args, **kwargs):
        raise AssertionError("new Series conversion callback")

    values.to_numpy = fail
    values.__array__ = fail
    assert _observation(helpers.finite_float_list, values) == _observation(_scalar_reference, values)
    assert _observation(helpers.finite_array, values) == _observation(
        lambda value: np.asarray(_scalar_reference(value), dtype=float), values,
    )


def test_scalar_oracle_rejects_known_bad_filter():
    original = np.array([-0.0, np.nan, np.inf, 2.0])
    assert _observation(_scalar_reference, original) != _observation(lambda value: value.tolist(), original)
    assert _observation(_scalar_reference, original) != _observation(lambda _value: [0.0, 2.0], original)


def test_scalar_oracle_rejects_narrow_signaling_nan_cast():
    values = np.array([0x7F800001], dtype=np.uint32).view(np.float32)

    def bad_cast(items):
        converted = items.astype(float)
        return converted[np.isfinite(converted)].tolist()

    assert _observation(_scalar_reference, values) != _observation(bad_cast, values)


def _raw_series_observation(function, mode, behavior):
    series = pd.Series([-0.0, 2.0, np.nan])
    manager = series._mgr
    events = []
    armed = False

    def record(operation):
        if not armed:
            return
        events.append(operation)
        warnings.warn(operation, UserWarning)
        if behavior == "raising" and len(events) > 1:
            raise RuntimeError("manager-second-read")

    def observed(read):
        record("internal_values")
        if behavior == "changing":
            return np.array([float(len(events)), -0.0, np.nan])
        return read()

    if mode == "manager_instance":
        read = manager.internal_values
        manager.internal_values = lambda: observed(read)
    elif mode == "manager_subclass":
        class Manager(type(manager)):
            def internal_values(self):
                return observed(super().internal_values)

        object.__setattr__(series, "_mgr", Manager(manager.blocks[0], manager.axes[0]))
    else:
        class State(dict):
            def get(self, *args):
                record("get")
                return super().get(*args)

            def keys(self):
                record("keys")
                return super().keys()

            def __contains__(self, key):
                record("contains")
                return super().__contains__(key)

            def __getitem__(self, key):
                record("getitem")
                return super().__getitem__(key)

            def values(self):
                record("values")
                return super().values()

        class Key(str):
            def __hash__(self):
                record("hash")
                return super().__hash__()

            def __eq__(self, other):
                record("eq")
                return super().__eq__(other)

        class Axes(list):
            def __len__(self):
                record("axes-length")
                return super().__len__()

        class Blocks(tuple):
            def __getitem__(self, key):
                record("blocks-lookup")
                return super().__getitem__(key)

        class Axis:
            def __len__(self):
                record("axis-length")
                if behavior == "raising":
                    raise RuntimeError("axis-length")
                return 3

        owner = series if mode.startswith("series") else manager
        if mode.startswith("axis_"):
            owner = manager.axes[0]
        if mode.endswith("state"):
            object.__setattr__(owner, "__dict__", State(owner.__dict__))
        elif mode.endswith("key"):
            owner.__dict__[Key("raw_metadata")] = True
        elif mode == "axes":
            manager.axes = Axes(manager.axes)
        elif mode == "blocks":
            manager.blocks = Blocks(manager.blocks)
        elif mode == "cached_block":
            manager.__dict__["_block"] = pd.Series([9.0, -0.0, np.nan])._mgr.blocks[0]
        elif mode == "axis_object":
            manager.axes = [Axis()]
        elif mode == "axis_range":
            owner.__dict__["_range"] = Axis()
        events.clear()
    armed = True
    observation = _observation(function, series)
    return observation, events


@pytest.mark.parametrize("name", ["finite_float_list", "finite_array"])
@pytest.mark.parametrize("mode", ["manager_instance", "manager_subclass", "series_state", "manager_state",
                                  "series_key", "manager_key", "axes", "blocks", "cached_block",
                                  "axis_object", "axis_range", "axis_state", "axis_key"])
@pytest.mark.parametrize("behavior", ["observe", "changing", "raising"])
def test_raw_series_preserves_original_observation(name, mode, behavior):
    def reference(value):
        result = _scalar_reference(value)
        return np.asarray(result, dtype=float) if name == "finite_array" else result

    expected = _raw_series_observation(reference, mode, behavior)
    assert _raw_series_observation(getattr(helpers, name), mode, behavior) == expected


@pytest.mark.parametrize("name", ["finite_float_list", "finite_array"])
@pytest.mark.parametrize("series", [False, True, "native_index"])
def test_native_numeric_storage_activates_without_scalar_fallback(monkeypatch, name, series):
    values = np.array([-0.0, 2.0, np.nan, np.inf])
    if series:
        index = pd.Index([4, 3, 2, 1]) if series == "native_index" else None
        values = pd.Series(values, index=index)

    def fail(_values):
        raise AssertionError("native storage unexpectedly declined")

    monkeypatch.setattr(helpers, "_raw_numeric_items", fail)
    result = getattr(helpers, name)(values)
    assert np.asarray(result).tobytes() == np.array([-0.0, 2.0]).tobytes()
