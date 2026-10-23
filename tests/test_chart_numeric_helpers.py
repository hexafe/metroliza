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
