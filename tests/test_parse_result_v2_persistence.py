import json

import pytest

from metroliza.parsing.parse_result_v2_persistence import (
    EmptyParseResultError,
    ParseResultContractError,
    build_persistence_payload,
)
from metroliza.parsing.parser_plugin_contracts import (
    MeasurementBlockV2,
    MeasurementV2,
    ParseError,
    ParseMetaV2,
    ParseResultV2,
    ParseWarning,
    ReportInfoV2,
)


def _parse_result(
    *,
    blocks=(),
    warnings=(),
    errors=(),
    template_id=None,
    confidence=120,
    plugin_id="supplier_alpha",
    plugin_version="0.1.0",
    source_format="csv",
):
    return ParseResultV2(
        meta=ParseMetaV2(
            source_file="sample.csv",
            source_format=source_format,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            template_id=template_id,
            parse_timestamp="2026-06-11T10:00:00Z",
            locale_detected="en-US",
            confidence=confidence,
        ),
        report=ReportInfoV2(
            reference="REF-123",
            report_date="2026-06-10",
            sample_number="S1",
            file_name="sample.csv",
            file_path="/tmp/sample.csv",
        ),
        blocks=tuple(blocks),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def test_parse_result_v2_payload_maps_warnings_and_measurement_statuses():
    parse_result = _parse_result(
        template_id="supplier_alpha_v2",
        warnings=(ParseWarning(code="ambiguous_header", message="Header matched weakly", field="header"),),
        blocks=(
            MeasurementBlockV2(
                header_raw=("Length",),
                header_normalized="Length",
                block_index=2,
                dimensions=(
                    MeasurementV2(
                        axis_code="X",
                        nominal=10.0,
                        tol_plus=0.1,
                        tol_minus=-0.1,
                        bonus=None,
                        measured=10.01,
                        deviation=0.01,
                        out_of_tolerance=0.0,
                        raw_tokens=("X", "10.01"),
                        raw_line_refs=(12,),
                        extensions={"characteristic_name": "Length X", "page_number": 1},
                    ),
                    MeasurementV2(
                        axis_code="Y",
                        nominal=20.0,
                        tol_plus=0.2,
                        tol_minus=-0.2,
                        bonus=None,
                        measured=20.5,
                        deviation=0.5,
                        out_of_tolerance=0.3,
                    ),
                    MeasurementV2(
                        axis_code="Z",
                        nominal=None,
                        tol_plus=None,
                        tol_minus=None,
                        bonus=None,
                        measured=None,
                        deviation=None,
                        out_of_tolerance=None,
                    ),
                ),
            ),
        ),
    )

    payload = build_persistence_payload(parse_result, source_path="/tmp/sample.csv")

    assert payload.parse_status == "parsed_with_warnings"
    assert payload.measurement_count == 3
    assert payload.has_nok is True
    assert payload.nok_count == 1
    assert payload.metadata.metadata_confidence == 1.0
    assert payload.metadata.template_family == "supplier_alpha_v2"
    assert payload.warnings[0].code == "ambiguous_header"
    assert payload.warnings[0].field_name == "header"
    assert [row["status_code"] for row in payload.measurements] == ["ok", "nok", "unknown"]
    assert payload.measurements[0]["characteristic_name"] == "Length X"
    assert payload.measurements[0]["raw_measurement_json"]["raw_tokens"] == ("X", "10.01")
    assert payload.raw_report_json["source"] == "ParseResultV2"


def test_parse_result_v2_payload_rejects_no_measurements_before_persistence():
    manifest = type(
        "Manifest",
        (),
        {
            "plugin_id": "supplier_alpha",
            "supported_formats": ("csv",),
            "template_ids": ("fallback_template",),
        },
    )()
    parse_result = _parse_result(blocks=(), confidence=-5)

    with pytest.raises(EmptyParseResultError, match="no persistable measurements"):
        build_persistence_payload(
            parse_result,
            source_path="/tmp/sample.csv",
            manifest=manifest,
        )


def test_parse_result_v2_payload_rejects_selected_plugin_identity_mismatch():
    manifest = type(
        "Manifest",
        (),
        {
            "plugin_id": "another_supplier",
            "supported_formats": ("csv",),
            "template_ids": (),
        },
    )()
    parse_result = _parse_result(
        blocks=(
            MeasurementBlockV2(
                header_raw=("Length",),
                header_normalized="Length",
                block_index=0,
                dimensions=(
                    MeasurementV2(
                        axis_code="X",
                        nominal=1.0,
                        tol_plus=0.1,
                        tol_minus=-0.1,
                        bonus=None,
                        measured=1.0,
                        deviation=0.0,
                        out_of_tolerance=0.0,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ParseResultContractError, match="plugin_id does not match"):
        build_persistence_payload(
            parse_result,
            source_path="/tmp/sample.csv",
            manifest=manifest,
        )


def test_parse_result_v2_payload_rejects_non_normalized_plugin_identity():
    manifest = type(
        "Manifest",
        (),
        {
            "plugin_id": "supplier_alpha",
            "version": "0.1.0",
            "supported_formats": ("csv",),
            "template_ids": (),
        },
    )()
    parse_result = _parse_result(
        plugin_id="supplier_alpha ",
        blocks=(
            MeasurementBlockV2(
                header_raw=("Length",),
                header_normalized="Length",
                block_index=0,
                dimensions=(
                    MeasurementV2(
                        axis_code="X",
                        nominal=1.0,
                        tol_plus=0.1,
                        tol_minus=-0.1,
                        bonus=None,
                        measured=1.0,
                        deviation=0.0,
                        out_of_tolerance=0.0,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ParseResultContractError, match="plugin_id must be normalized"):
        build_persistence_payload(
            parse_result,
            source_path="/tmp/sample.csv",
            manifest=manifest,
        )


@pytest.mark.parametrize("plugin_version", ["", "0.2.0", "0.1.0 "])
def test_parse_result_v2_payload_rejects_invalid_plugin_version(plugin_version):
    manifest = type(
        "Manifest",
        (),
        {
            "plugin_id": "supplier_alpha",
            "version": "0.1.0",
            "supported_formats": ("csv",),
            "template_ids": (),
        },
    )()
    parse_result = _parse_result(
        plugin_version=plugin_version,
        blocks=(
            MeasurementBlockV2(
                header_raw=("Length",),
                header_normalized="Length",
                block_index=0,
                dimensions=(
                    MeasurementV2(
                        axis_code="X",
                        nominal=1.0,
                        tol_plus=0.1,
                        tol_minus=-0.1,
                        bonus=None,
                        measured=1.0,
                        deviation=0.0,
                        out_of_tolerance=0.0,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ParseResultContractError, match="plugin_version"):
        build_persistence_payload(
            parse_result,
            source_path="/tmp/sample.csv",
            manifest=manifest,
        )


def test_parse_result_v2_payload_rejects_selected_source_format_mismatch():
    manifest = type(
        "Manifest",
        (),
        {
            "plugin_id": "supplier_alpha",
            "supported_formats": ("pdf",),
            "template_ids": (),
        },
    )()
    parse_result = _parse_result(
        blocks=(
            MeasurementBlockV2(
                header_raw=("Length",),
                header_normalized="Length",
                block_index=0,
                dimensions=(
                    MeasurementV2(
                        axis_code="X",
                        nominal=1.0,
                        tol_plus=0.1,
                        tol_minus=-0.1,
                        bonus=None,
                        measured=1.0,
                        deviation=0.0,
                        out_of_tolerance=0.0,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ParseResultContractError, match="source_format is not supported"):
        build_persistence_payload(
            parse_result,
            source_path="/tmp/sample.csv",
            manifest=manifest,
        )


def test_parse_result_v2_payload_rejects_inspected_source_format_mismatch():
    parse_result = _parse_result(
        blocks=(
            MeasurementBlockV2(
                header_raw=("Length",),
                header_normalized="Length",
                block_index=0,
                dimensions=(
                    MeasurementV2(
                        axis_code="X",
                        nominal=1.0,
                        tol_plus=0.1,
                        tol_minus=-0.1,
                        bonus=None,
                        measured=1.0,
                        deviation=0.0,
                        out_of_tolerance=0.0,
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ParseResultContractError, match="does not match the inspected source"):
        build_persistence_payload(
            parse_result,
            source_path="/tmp/sample.pdf",
            expected_source_format="pdf",
        )


def test_parse_result_v2_payload_rejects_blocking_parser_errors():
    parse_result = _parse_result(
        errors=(ParseError(code="missing_rows", message="No measurement table found"),),
    )

    with pytest.raises(ValueError, match="missing_rows: No measurement table found"):
        build_persistence_payload(parse_result, source_path="/tmp/sample.csv")


def test_parse_result_v2_raw_provenance_omits_measurement_tree_and_caps_diagnostics():
    warnings = tuple(
        ParseWarning(code=f"warning_{index}", message="x" * 2_000, field="header")
        for index in range(75)
    )
    dimensions = tuple(
        MeasurementV2(
            axis_code=f"AXIS-{index}",
            nominal=1.0,
            tol_plus=0.1,
            tol_minus=-0.1,
            bonus=None,
            measured=1.0,
            deviation=0.0,
            out_of_tolerance=0.0,
            raw_tokens=("raw" * 1_000,),
        )
        for index in range(100)
    )
    parse_result = _parse_result(
        warnings=warnings,
        blocks=(
            MeasurementBlockV2(
                header_raw=("Feature",),
                header_normalized="Feature",
                dimensions=dimensions,
                block_index=0,
            ),
        ),
    )

    payload = build_persistence_payload(parse_result, source_path="/tmp/sample.csv")
    summary = payload.raw_report_json["parse_result_summary"]

    assert "parse_result" not in payload.raw_report_json
    assert summary["measurement_count"] == 100
    assert summary["warning_count"] == 75
    assert len(summary["warnings"]) == 50
    assert summary["diagnostics_truncated"] is True
    assert len(summary["warnings"][0]["message"]) == 500
    assert len(json.dumps(payload.raw_report_json)) < 35_000
