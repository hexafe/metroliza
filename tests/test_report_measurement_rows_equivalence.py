"""Measurement row building stays byte-identical to the reference implementation."""

from __future__ import annotations

from dataclasses import dataclass, field

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

    rows = []
    for row_order, measurement in enumerate(measurements, start=1):
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
