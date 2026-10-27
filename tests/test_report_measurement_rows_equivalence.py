"""Measurement row building stays byte-identical to the reference implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from metroliza.reports import report_repository as repo
from metroliza.reports.report_metadata_models import CanonicalReportMetadata, MetadataWarning
from metroliza.reports.report_repository import (
    ReportRepository,
    _as_mapping,
    _coerce_float,
    _coerce_int,
    _get_value,
    _measurement_status_values,
    _metadata_persistence_values,
    _to_json,
)


def _reference_rows(report_id, measurements):
    """The row builder as it was before the import fast path (frozen copy)."""

    report_id = int(report_id)
    rows = []
    for row_order, measurement in enumerate(measurements, start=1):
        if isinstance(measurement, dict):
            rows.append(_frozen_mapping_row(report_id, row_order, measurement))
            continue
        explicit_order = _get_value(measurement, "row_order")
        outtol = _coerce_float(_get_value(measurement, "outtol"))
        is_nok, status_code = _measurement_status_values(measurement, outtol)
        rows.append(
            (
                int(report_id),
                _coerce_int(_get_value(measurement, "page_number")),
                int(explicit_order if explicit_order is not None else row_order),
                _get_value(measurement, "header"),
                _get_value(measurement, "section_name"),
                _get_value(measurement, "feature_label"),
                _get_value(measurement, "characteristic_name"),
                _get_value(measurement, "characteristic_family"),
                _get_value(measurement, "description"),
                _get_value(measurement, "ax"),
                _coerce_float(_get_value(measurement, "nominal", _get_value(measurement, "nom"))),
                _coerce_float(_get_value(measurement, "tol_plus")),
                _coerce_float(_get_value(measurement, "tol_minus")),
                _coerce_float(_get_value(measurement, "bonus")),
                _coerce_float(_get_value(measurement, "meas")),
                _coerce_float(_get_value(measurement, "dev")),
                outtol,
                is_nok,
                status_code,
                _to_json(_get_value(measurement, "raw_measurement_json", _as_mapping(measurement))),
            )
        )
    return rows


@dataclass
class _Inner:
    unit: str = "mm"
    values: list = field(default_factory=lambda: [1, 2.5, None])


@dataclass
class _DataclassMeasurement:
    header: str = "FEAT_ü"
    ax: str = "X"
    nominal: float = 10.0
    tol_plus: float = 0.1
    tol_minus: float = -0.1
    meas: float = 10.02
    dev: float = 0.02
    outtol: float = 0.0
    extra: _Inner = field(default_factory=_Inner)


class _ObjectMeasurement:
    header = "OBJ"
    ax = "Y"
    nom = "5.5"
    meas = "5.6"
    status_code = " NOK "

    def method(self):
        return 1

    @property
    def broken(self):
        raise RuntimeError("skipped by _as_mapping")


def _parser_shaped(index):
    return {
        "page_number": None,
        "row_order": index,
        "header": f"H{index}",
        "section_name": f"H{index}",
        "feature_label": f"H{index}",
        "characteristic_name": "POS",
        "characteristic_family": "POS",
        "description": f"H{index}",
        "ax": "X",
        "nominal": 1.5 * index,
        "tol_plus": 0.1,
        "tol_minus": -0.1,
        "bonus": 0.0,
        "meas": 1.5 * index + 0.01,
        "dev": 0.01,
        "outtol": 0.0 if index % 3 else 0.05,
        "is_nok": 0 if index % 3 else 1,
        "status_code": "ok" if index % 3 else "nok",
        "raw_measurement_json": {"tokens": ["X", "1", "ž"], "header": f"H{index}", "n": index},
    }


CASES = {
    "parser_shaped": [_parser_shaped(i) for i in range(1, 40)],
    "missing_keys_and_alias": [
        {"nom": "3.25", "meas": "", "tol_plus": "abc", "outtol": "0.2"},
        {"nominal": None, "nom": 7, "bonus": "1e-3"},
        {},
    ],
    "raw_json_variants": [
        {"raw_measurement_json": None},
        {"raw_measurement_json": {}},
        {"raw_measurement_json": {"b": 2, "a": [1, {"z": 1, "y": "é"}]}},
        {"raw_measurement_json": [1, 2]},
        {"raw_measurement_json": "text"},
        {"header": "no raw", "meas": 1.0},
    ],
    "status_variants": [
        {"status_code": "OK"},
        {"status_code": " nok ", "outtol": 0},
        {"status_code": "", "is_nok": 1},
        {"status_code": None, "is_nok": 0, "outtol": 5},
        {"is_nok": "yes"},
        {"outtol": -1},
        {"outtol": 0.0001},
        {"status_code": "unknown"},
    ],
    "explicit_order": [{"row_order": 0}, {"row_order": "7"}, {"row_order": None}, {}],
    "page_and_ints": [{"page_number": "3"}, {"page_number": 2.0}, {"page_number": ""}],
    "objects": [
        _DataclassMeasurement(),
        _ObjectMeasurement(),
        _DataclassMeasurement(header="second", outtol=0.4),
    ],
    "mixed": [_parser_shaped(1), _DataclassMeasurement(), {"header": "x"}, _ObjectMeasurement()],
    "empty": [],
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_rows_are_identical_to_the_reference_implementation(name):
    measurements = CASES[name]
    expected = _reference_rows(41, list(measurements))
    actual = ReportRepository("unused.sqlite")._measurement_rows(41, iter(list(measurements)))
    assert actual == expected
    assert [type(value) for row in actual for value in row] == [
        type(value) for row in expected for value in row
    ]


def test_invalid_status_code_still_raises_the_same_error():
    measurements = [{"status_code": "maybe"}]
    with pytest.raises(ValueError, match="status_code must be one of") as reference:
        _reference_rows(1, measurements)
    with pytest.raises(ValueError, match="status_code must be one of") as actual:
        ReportRepository("unused.sqlite")._measurement_rows(1, measurements)
    assert str(actual.value) == str(reference.value)


def test_to_json_output_is_unchanged_for_scalars_dicts_and_dataclasses():
    import json

    values = [None, {"b": 1, "a": "é"}, [1, 2], "x", 3, _Inner(), {"nested": _Inner().__dict__}]
    for value in values:
        if value is None:
            assert _to_json(value) is None
        else:
            from dataclasses import asdict, is_dataclass

            plain = asdict(value) if is_dataclass(value) else value
            assert _to_json(value) == json.dumps(plain, ensure_ascii=False, sort_keys=True)
    assert repo._to_json({"x": float("inf")}) == json.dumps({"x": float("inf")}, ensure_ascii=False, sort_keys=True)


# --- metadata row values ---------------------------------------------------------------

def _reference_metadata_values(metadata):
    """Frozen copy of the metadata handling before the field-by-field fast path."""

    metadata_map = _as_mapping(metadata)
    metadata_json = metadata_map.get("metadata_json")
    if metadata_json is None:
        metadata_json = {
            key: value
            for key, value in metadata_map.items()
            if key not in {"warnings"}
            and isinstance(value, (str, int, float, bool, type(None), list, tuple, dict))
        }
    return metadata_map, metadata_json, _to_json(metadata_json)


_SCALARS = (
    "reference", "reference_raw", "report_date", "report_time", "part_name", "revision",
    "sample_number", "sample_number_kind", "stats_count_raw", "stats_count_int",
    "operator_name", "comment",
)


def _canonical(metadata_json, warnings=()):
    return CanonicalReportMetadata(
        parser_id="cmm",
        template_family="family",
        template_variant=None,
        metadata_confidence=0.9,
        reference="R-ž",
        reference_raw="r",
        report_date="2026-01-02",
        report_time=None,
        part_name="P",
        revision="A",
        sample_number="3",
        sample_number_kind="explicit_sample_number",
        stats_count_raw="7",
        stats_count_int=7,
        operator_name=None,
        comment="c",
        page_count=2,
        metadata_json=metadata_json,
        warnings=warnings,
    )


@dataclass
class _Detail:
    code: str = "d"


_WARNING = MetadataWarning(field_name="reference", code="w", severity="warning", message="m", details={"k": [1, {"z": 2}]})

METADATA_CASES = {
    "canonical": _canonical(
        {
            "metadata_parsing_mode": "complete",
            "field_sources": {"reference": "header", "report_date": "x"},
            "nested": {"b": 1, "a": (1, 2)},
            "unicode": "é",
        },
        (_WARNING,),
    ),
    "canonical_empty_json": _canonical({}),
    "canonical_json_none": _canonical(None, (_WARNING,)),
    "nested_dataclass_in_json": _canonical({"detail": _Detail(), "field_sources": {"reference": "r"}}),
    "plain_dict": {"reference": "dict", "metadata_json": {"field_sources": {"reference": "d"}}},
    "plain_dict_no_json": {"reference": "dict", "page_count": 3, "warnings": [1], "extra": {"a": 1}},
    "object": _ObjectMeasurement(),
}


@pytest.mark.parametrize("name", sorted(METADATA_CASES))
def test_metadata_row_values_match_the_generic_path(name):
    from copy import deepcopy

    metadata = METADATA_CASES[name]
    expected_map, expected_json, expected_text = _reference_metadata_values(deepcopy(metadata))
    actual_map, actual_json, actual_text = _metadata_persistence_values(metadata)
    assert actual_text == expected_text
    assert actual_json == expected_json
    for key in _SCALARS:
        assert actual_map.get(key) == expected_map.get(key)
    from metroliza.reports.report_schema import report_parse_state_values_from_metadata_json

    assert report_parse_state_values_from_metadata_json(actual_json) == (
        report_parse_state_values_from_metadata_json(expected_json)
    )


def test_metadata_with_a_circular_json_reference_fails_like_the_generic_path():
    circular = {}
    circular["self"] = circular
    metadata = _canonical(circular)
    with pytest.raises(RecursionError):
        _reference_metadata_values(metadata)
    with pytest.raises(RecursionError):
        _metadata_persistence_values(metadata)


_FROZEN_UNSET = repo._UNSET

def _frozen_mapping_row(report_id: int, row_order: int, measurement: dict) -> tuple[Any, ...]:
    """Row tuple for a dict measurement; same values as the generic attribute path."""

    get = measurement.get
    explicit_order = get("row_order")
    outtol = _coerce_float(get("outtol"))
    status_code = get("status_code")
    if status_code not in (None, ""):
        status_code = repo._coerce_status_code(status_code)
        is_nok = 1 if status_code == "nok" else 0
    else:
        raw_is_nok = get("is_nok")
        if raw_is_nok is not None:
            is_nok = 1 if raw_is_nok else 0
            status_code = "nok" if is_nok else "ok"
        else:
            is_nok, status_code = repo._status_from_outtol(outtol)
    raw = get("raw_measurement_json", _FROZEN_UNSET)
    return (
        report_id,
        _coerce_int(get("page_number")),
        int(explicit_order if explicit_order is not None else row_order),
        get("header"),
        get("section_name"),
        get("feature_label"),
        get("characteristic_name"),
        get("characteristic_family"),
        get("description"),
        get("ax"),
        _coerce_float(get("nominal", get("nom"))),
        _coerce_float(get("tol_plus")),
        _coerce_float(get("tol_minus")),
        _coerce_float(get("bonus")),
        _coerce_float(get("meas")),
        _coerce_float(get("dev")),
        outtol,
        is_nok,
        status_code,
        _to_json(_as_mapping(measurement) if raw is _FROZEN_UNSET else raw),
    )


@pytest.mark.parametrize("raw", [None, {"x": [None, float("inf"), -0.0, "ž"]}, "raw"])
def test_prepared_public_rows_remain_mutable_and_repeatable(raw):
    from metroliza.parsing.cmm_report_parser import CMMReportParser

    parser = CMMReportParser("synthetic.pdf", "unused.sqlite")
    parser.blocks_text = [["#SYNTHETIC", [["X", "1", ".1", "-.1", "0", "1", "0", "0", "OK"]]]]
    rows = parser.parse_measurements()
    assert type(rows) is list and type(rows[0]) is dict
    rows[0]["raw_measurement_json"] = raw
    repository = ReportRepository("unused.sqlite")
    for report_id in (3, "7", 3):
        supplied = parser._normalized_rows_for_persistence()
        assert repository._measurement_rows(report_id, supplied) == _reference_rows(report_id, rows)
    rows[0]["nominal"] = "3.75"
    assert repository._measurement_rows(8, parser._normalized_rows_for_persistence()) == _reference_rows(8, rows)


def test_report_id_error_precedes_iteration_and_row_callbacks():
    class ObservingRows:
        def __iter__(self):
            pytest.fail("report id conversion must precede iteration")

    for build in (_reference_rows, ReportRepository("unused.sqlite")._measurement_rows):
        with pytest.raises(ValueError):
            build("invalid-id", ObservingRows())


def test_dict_subclass_keeps_get_callback_order():
    calls = []

    class ObservingDict(dict):
        def get(self, *args):
            calls.append(args)
            return super().get(*args)

    row = ObservingDict(_parser_shaped(1))
    expected = _reference_rows(9, [row])
    expected_calls = list(calls)
    calls.clear()
    assert ReportRepository("unused.sqlite")._measurement_rows(9, [row]) == expected
    assert calls == expected_calls


def _legacy_prepared_rows(rows):
    # A deliberately unusable cache proves compatibility consumes only the source.
    return repo._PreparedMeasurementRows(1, rows, b"legacy", (("STALE",) * 19,))


def _prepare_normalized_rows(rows):
    from metroliza.parsing.cmm_report_parser import CMMReportParser

    parser = CMMReportParser("synthetic.pdf", "unused.sqlite")
    parser.raw_text = "synthetic"
    parser.blocks_text = [["synthetic"]]
    parser._metadata_selection_result = object()
    parser.parse_measurements = lambda: rows
    parser.prepare_for_two_stage_pipeline()
    assert parser._prepared_measurement_rows is rows
    assert "_prepared_persistence_rows" not in parser.export_prepared_state()
    return parser._prepared_persistence_rows


def test_legacy_prepared_rows_rebuild_and_bind_only_the_owning_report_id(monkeypatch):
    from copy import deepcopy

    rows = [_parser_shaped(1), _parser_shaped(2)]
    prepared = _legacy_prepared_rows(rows)
    expected = {number: _reference_rows(number, deepcopy(rows)) for number in (4, 8)}
    calls = []
    original = repo._mapping_measurement_row

    def observe(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(repo, "_mapping_measurement_row", observe)
    repository = ReportRepository("unused.sqlite")
    for number in (4, 8):
        assert repository._measurement_rows(number, prepared) == expected[number]
    assert len(calls) == 4
    rows[0]["raw_measurement_json"]["tokens"].append("mutated")
    assert repository._measurement_rows(4, prepared) == _reference_rows(4, rows)
    assert len(calls) == 6


@pytest.mark.parametrize("change", ["version", "shape", "key", "custom"])
def test_unsupported_prepared_rows_use_the_original_path(monkeypatch, change):
    from dataclasses import replace

    rows = [_parser_shaped(1)]
    prepared = _legacy_prepared_rows(rows)
    if change == "version":
        prepared = replace(prepared, version=2)
    elif change == "shape":
        prepared = replace(prepared, rows=((1,),))
    elif change == "key":
        prepared = replace(prepared, source_key=object())
    else:
        class Custom(dict):
            pass
        rows[0] = Custom(rows[0])
        assert _prepare_normalized_rows(rows) is None
    calls = []
    original = repo._mapping_measurement_row
    monkeypatch.setattr(repo, "_mapping_measurement_row", lambda *args: calls.append(1) or original(*args))
    assert ReportRepository("unused.sqlite")._measurement_rows(1, prepared) == _reference_rows(1, rows)
    assert calls == [1]


def test_prepared_row_snapshot_freezes_outer_membership_at_repository_entry():
    rows = [_parser_shaped(1)]
    prepared = repo._freeze_measurements(_legacy_prepared_rows(rows))
    rows.append(_parser_shaped(2))
    assert ReportRepository("unused.sqlite")._measurement_rows(1, prepared) == _reference_rows(1, rows[:1])
    rows[0]["meas"] = 99
    assert ReportRepository("unused.sqlite")._measurement_rows(1, prepared) == _reference_rows(1, rows[:1])


@pytest.mark.parametrize("value", [None, -0.0, float("nan"), float("inf"), float("-inf")])
def test_prepared_rows_keep_nonfinite_signed_zero_and_exact_json(value):
    import struct

    rows = [_parser_shaped(1)]
    rows[0].update(nominal=value, outtol=value, status_code="unknown", raw_measurement_json={"value": value, "unicode": "ž"})
    prepared = _legacy_prepared_rows(rows)
    assert prepared is not None
    expected = _reference_rows(11, rows)
    actual = ReportRepository("unused.sqlite")._measurement_rows(11, prepared)
    def typed(values):
        return [(type(item), struct.pack("!d", item) if type(item) is float else item) for row in values for item in row]
    assert typed(actual) == typed(expected)
    assert actual[0][-1] == _to_json(rows[0]["raw_measurement_json"])


def test_preparation_declines_callbacks_and_preserves_writer_errors():
    calls = []
    class Number:
        def __eq__(self, other):
            calls.append(("eq", other))
            return False
        def __float__(self):
            calls.append(("float",))
            return 1.25
    rows = [{"nominal": Number(), "raw_measurement_json": None}]
    assert _prepare_normalized_rows(rows) is None
    assert calls == []
    expected = _reference_rows(1, rows)
    original_calls = list(calls)
    calls.clear()
    assert ReportRepository("unused.sqlite")._measurement_rows(1, rows) == expected
    assert calls == original_calls
    rows = [{"row_order": "invalid", "status_code": "bad"}]
    assert _prepare_normalized_rows(rows) is None
    with pytest.raises(ValueError, match="status_code must be"):
        ReportRepository("unused.sqlite")._measurement_rows(1, rows)



def test_preparation_uses_identity_checks_before_custom_metaclass_callbacks():
    class ObservingMeta(type):
        def __eq__(cls, other):
            pytest.fail("eligibility called custom metaclass equality")
        def __hash__(cls):
            pytest.fail("eligibility called custom metaclass hashing")
    class Number(metaclass=ObservingMeta):
        def __float__(self):
            return 1.25
    rows = [{"nominal": Number(), "raw_measurement_json": None}]
    assert _prepare_normalized_rows(rows) is None
    assert ReportRepository("unused.sqlite")._measurement_rows(1, rows) == _reference_rows(1, rows)


@pytest.mark.parametrize("shape", ["string", "dictionary"])
def test_prepared_decline_preserves_custom_string_and_dictionary_observations(shape):
    calls = []
    class Text(str):
        def __eq__(self, other):
            calls.append(("eq", other))
            return super().__eq__(other)
    class Mapping(dict):
        def items(self):
            calls.append(("items",))
            return super().items()
    rows = ([{"nominal": Text("1.25"), "raw_measurement_json": None}] if shape == "string"
            else [{"raw_measurement_json": Mapping(value=1)}])
    assert _prepare_normalized_rows(rows) is None
    assert calls == []
    expected = _reference_rows(1, rows)
    expected_calls = list(calls)
    calls.clear()
    assert ReportRepository("unused.sqlite")._measurement_rows(1, rows) == expected
    assert calls == expected_calls


@pytest.fixture
def native_bigint_repr_limit():
    import sys

    if not hasattr(sys, "set_int_max_str_digits"):
        pytest.skip("interpreter has no native integer repr limit")
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    try:
        yield 10 ** 5000
    finally:
        sys.set_int_max_str_digits(previous)


def test_ignored_bigint_after_preparation_falls_back_without_cached_emission(monkeypatch, native_bigint_repr_limit):
    from dataclasses import replace

    rows = [{"header": "GENERIC", "raw_measurement_json": {}}]
    prepared = _legacy_prepared_rows(rows)
    poison = list(prepared.rows[0])
    poison[2] = "CACHED_MUST_NOT_BE_EMITTED"
    prepared = replace(prepared, rows=(tuple(poison),))
    rows[0]["ignored_native_bigint"] = native_bigint_repr_limit
    expected = _reference_rows(17, rows)
    calls, emissions = [], []
    original = repo._mapping_measurement_row

    def writer(*args):
        calls.append(1)
        row = original(*args)
        emissions.append(row)
        return row

    monkeypatch.setattr(repo, "_mapping_measurement_row", writer)
    actual = ReportRepository("unused.sqlite")._measurement_rows(17, prepared)
    assert actual == expected == emissions
    assert calls == [1]
    assert actual[0][3] == "GENERIC" and actual[0][-1] == "{}"


@pytest.mark.parametrize("field", ["nominal", "raw_measurement_json"])
def test_used_bigint_keeps_original_writer_failure(monkeypatch, native_bigint_repr_limit, field):
    rows = [{"raw_measurement_json": {}}]
    prepared = _legacy_prepared_rows(rows)
    rows[0][field] = ({"used": native_bigint_repr_limit} if field == "raw_measurement_json" else native_bigint_repr_limit)
    with pytest.raises((ValueError, OverflowError)) as baseline:
        _reference_rows(17, rows)
    calls = []
    original = repo._mapping_measurement_row
    monkeypatch.setattr(repo, "_mapping_measurement_row", lambda *args: calls.append(1) or original(*args))
    with pytest.raises(type(baseline.value)) as actual:
        ReportRepository("unused.sqlite")._measurement_rows(17, prepared)
    assert str(actual.value) == str(baseline.value)
    assert calls == [1]


@pytest.mark.parametrize("error_type", [ValueError, OverflowError, RuntimeError])
def test_key_decline_does_not_catch_or_retry_generic_writer_error(monkeypatch, native_bigint_repr_limit, error_type):
    rows = [{"raw_measurement_json": {}}]
    prepared = _legacy_prepared_rows(rows)
    rows[0]["ignored_native_bigint"] = native_bigint_repr_limit
    calls = []
    error = error_type("generic writer sentinel")

    def writer(*args):
        calls.append(1)
        raise error

    monkeypatch.setattr(repo, "_mapping_measurement_row", writer)
    with pytest.raises(error_type) as actual:
        ReportRepository("unused.sqlite")._measurement_rows(17, prepared)
    assert actual.value is error
    assert calls == [1]


def test_prepared_decline_keeps_real_status_callback_error(monkeypatch, native_bigint_repr_limit):
    rows = [{"raw_measurement_json": {}}]
    prepared = _legacy_prepared_rows(rows)
    calls, callbacks = [], []
    error = ValueError("status callback sentinel")

    class Status:
        def __str__(self):
            callbacks.append(1)
            raise error

    rows[0].update(status_code=Status(), ignored_native_bigint=native_bigint_repr_limit)
    original = repo._mapping_measurement_row
    monkeypatch.setattr(repo, "_mapping_measurement_row", lambda *args: calls.append(1) or original(*args))
    with pytest.raises(ValueError) as actual:
        ReportRepository("unused.sqlite")._measurement_rows(17, prepared)
    assert actual.value is error
    assert calls == callbacks == [1]


@pytest.mark.parametrize("stage", ["producer", "consumer"])
def test_native_dict_resize_needs_no_unused_source_traversal(monkeypatch, stage):
    rows = [{"header": "GENERIC", "raw_measurement_json": {}}]
    prepared = _legacy_prepared_rows(rows)
    calls = []
    original = repo._mapping_measurement_row

    def writer(*args):
        rows[0]["ignored_resize"] = 1
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(repo, "_mapping_measurement_row", writer)
    if stage == "producer":
        assert _prepare_normalized_rows(rows) is None
        assert calls == []
    actual = ReportRepository("unused.sqlite")._measurement_rows(17, prepared)
    assert calls == [1] and rows[0]["ignored_resize"] == 1
    assert actual == _reference_rows(17, rows)


def test_preparation_skips_writer_and_consumer_preserves_mapping_runtime_error(monkeypatch):
    calls = []
    error = RuntimeError("writer sentinel")

    def writer(*args):
        calls.append(1)
        raise error

    monkeypatch.setattr(repo, "_mapping_measurement_row", writer)
    rows = [{"raw_measurement_json": {}}]
    assert _prepare_normalized_rows(rows) is None and calls == []
    with pytest.raises(RuntimeError) as actual:
        ReportRepository("unused.sqlite")._measurement_rows(17, _legacy_prepared_rows(rows))
    assert actual.value is error and calls == [1]


@pytest.mark.parametrize("custom", [False, True])
def test_repository_entry_freeze_keeps_current_nested_values_and_callbacks(custom):
    calls = []

    class Row(dict):
        def get(self, *args):
            calls.append(args)
            return super().get(*args)

    rows = [_parser_shaped(1)]
    prepared = _legacy_prepared_rows(rows)
    if custom:
        rows[0] = Row(rows[0])
    frozen = repo._freeze_measurements(prepared)
    retained = rows[0]
    rows[:] = [_parser_shaped(2), _parser_shaped(3)]
    retained["nominal"] = "0.30000000000000004"
    retained["raw_measurement_json"]["tokens"].append([None, -0.0, "é"])
    expected = _reference_rows(27, [retained])
    expected_calls = list(calls)
    calls.clear()
    actual = ReportRepository("unused.sqlite")._measurement_rows(27, frozen)
    assert actual == expected
    assert [type(value) for value in actual[0]] == [type(value) for value in expected[0]]
    assert calls == expected_calls
    retained.update(status_code="invalid", row_order="also-invalid")
    with pytest.raises(ValueError) as reference:
        _reference_rows(27, [retained])
    with pytest.raises(type(reference.value)) as current:
        ReportRepository("unused.sqlite")._measurement_rows(27, frozen)
    assert str(current.value) == str(reference.value)


def test_legacy_prepared_rows_skip_cache_validation_and_use_current_source(monkeypatch):
    rows = [_parser_shaped(1)]
    prepared = repo._PreparedMeasurementRows(1, rows, b"legacy", (("STALE",) * 19,))

    def unused(*args):
        pytest.fail("withdrawn persistence cache must not be hashed or validated")

    monkeypatch.setattr(repo, "_measurement_rows_key", unused, raising=False)
    assert ReportRepository("unused.sqlite")._measurement_rows(5, prepared) == _reference_rows(5, rows)
