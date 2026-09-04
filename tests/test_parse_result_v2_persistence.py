import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

import metroliza.parsing.parse_result_v2_persistence as persistence_module
from metroliza.parsing.parse_result_v2_persistence import (
    EmptyParseResultError,
    ParseResultContractError,
    build_persistence_payload,
    import_parse_result_v2_if_absent,
    import_parse_result_v2_payload_if_absent,
    persist_parse_result_v2_payload,
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
from metroliza.parsing.source_inspection import (
    SourceChangedAfterInspectionError,
    SourceInspectionContext,
)
from metroliza.reports.report_repository import ReportImportDisposition


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


def _persistable_parse_result():
    return _parse_result(
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


def _forbid_repository_construction(monkeypatch):
    calls = []

    def forbidden_repository(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("repository must not be constructed")

    monkeypatch.setattr(persistence_module, "ReportRepository", forbidden_repository)
    return calls


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


def test_parse_result_v2_import_propagates_typed_dispositions(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text("synthetic", encoding="utf-8")
    database = tmp_path / "reports.sqlite3"
    parse_result = _persistable_parse_result()
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")

    first = import_parse_result_v2_if_absent(
        parse_result,
        source_path=source,
        database=str(database),
        source_inspection=source_inspection,
    )
    second = import_parse_result_v2_if_absent(
        parse_result,
        source_path=source,
        database=str(database),
        source_inspection=source_inspection,
    )

    assert first is ReportImportDisposition.IMPORTED
    assert second is ReportImportDisposition.ALREADY_PRESENT


def test_parse_result_v2_source_drift_fails_before_creating_database(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text("reviewed", encoding="utf-8")
    database = tmp_path / "reports.sqlite3"
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    assert source_inspection.sha256 is not None
    source.write_text("changed", encoding="utf-8")

    with pytest.raises(SourceChangedAfterInspectionError):
        import_parse_result_v2_if_absent(
            _persistable_parse_result(),
            source_path=source,
            database=str(database),
            source_inspection=source_inspection,
        )

    assert not database.exists()


def test_atomic_import_rejects_explicit_digest_from_older_source_before_repository(
    tmp_path, monkeypatch
):
    source = tmp_path / "sample.csv"
    content_a = b"synthetic source revision A"
    content_b = b"synthetic source revision B"
    source.write_bytes(content_a)
    digest_a = hashlib.sha256(content_a).hexdigest()
    source.write_bytes(content_b)
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    database = tmp_path / "reports.sqlite3"
    repository_calls = _forbid_repository_construction(monkeypatch)

    with pytest.raises(ValueError, match="does not match the inspected source digest"):
        import_parse_result_v2_if_absent(
            _persistable_parse_result(),
            source_path=source,
            database=str(database),
            source_sha256=digest_a,
            source_inspection=source_inspection,
        )

    assert repository_calls == []
    assert not database.exists()


def test_atomic_payload_rejects_digest_binding_before_repository(tmp_path, monkeypatch):
    source = tmp_path / "sample.csv"
    content_a = b"synthetic payload source revision A"
    content_b = b"synthetic payload source revision B"
    source.write_bytes(content_a)
    digest_a = hashlib.sha256(content_a).hexdigest()
    source.write_bytes(content_b)
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    database = tmp_path / "reports.sqlite3"
    parse_result = _persistable_parse_result()
    payload = build_persistence_payload(parse_result, source_path=source)
    repository_calls = _forbid_repository_construction(monkeypatch)

    with pytest.raises(ValueError, match="does not match the inspected source digest"):
        import_parse_result_v2_payload_if_absent(
            payload,
            parse_result=parse_result,
            source_path=source,
            database=str(database),
            source_sha256=digest_a,
            source_inspection=source_inspection,
        )

    assert repository_calls == []
    assert not database.exists()


def test_atomic_payload_rejects_explicit_digest_when_inspection_has_no_digest(
    tmp_path, monkeypatch
):
    source = tmp_path / "missing.csv"
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    assert source_inspection.sha256 is None
    database = tmp_path / "reports.sqlite3"
    parse_result = _persistable_parse_result()
    payload = build_persistence_payload(parse_result, source_path=source)
    repository_calls = _forbid_repository_construction(monkeypatch)

    with pytest.raises(ValueError, match="does not match the inspected source digest"):
        import_parse_result_v2_payload_if_absent(
            payload,
            parse_result=parse_result,
            source_path=source,
            database=str(database),
            source_sha256="0" * 64,
            source_inspection=source_inspection,
        )

    assert repository_calls == []
    assert not database.exists()


def test_atomic_import_matching_bound_digest_preserves_duplicate_graph(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_bytes(b"synthetic matching source")
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    assert source_inspection.sha256 is not None
    database = tmp_path / "reports.sqlite3"
    parse_result = _persistable_parse_result()

    first = import_parse_result_v2_if_absent(
        parse_result,
        source_path=source,
        database=str(database),
        source_sha256=source_inspection.sha256,
        source_inspection=source_inspection,
    )
    with closing(sqlite3.connect(database)) as connection:
        graph_after_first = tuple(connection.iterdump())
    second = import_parse_result_v2_if_absent(
        parse_result,
        source_path=source,
        database=str(database),
        source_sha256=source_inspection.sha256,
        source_inspection=source_inspection,
    )
    with closing(sqlite3.connect(database)) as connection:
        graph_after_second = tuple(connection.iterdump())

    assert first is ReportImportDisposition.IMPORTED
    assert second is ReportImportDisposition.ALREADY_PRESENT
    assert graph_after_second == graph_after_first


def test_atomic_payload_forwards_canonical_inspected_digest_for_case_only_match(
    tmp_path, monkeypatch
):
    source = tmp_path / "sample.csv"
    source.write_bytes(b"synthetic canonical digest source")
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    assert source_inspection.sha256 is not None
    parse_result = _persistable_parse_result()
    payload = build_persistence_payload(parse_result, source_path=source)
    forwarded = {}

    class RecordingRepository:
        def __init__(self, database, *, connection=None):
            forwarded["constructor"] = (database, connection)

        def import_report_if_absent(self, **kwargs):
            forwarded.update(kwargs)
            return ReportImportDisposition.IMPORTED

    monkeypatch.setattr(persistence_module, "ReportRepository", RecordingRepository)

    disposition = import_parse_result_v2_payload_if_absent(
        payload,
        parse_result=parse_result,
        source_path=source,
        database=str(tmp_path / "unused.sqlite3"),
        source_sha256=source_inspection.sha256.upper(),
        source_inspection=source_inspection,
    )

    assert disposition is ReportImportDisposition.IMPORTED
    assert forwarded["source_sha256"] == source_inspection.sha256
    assert forwarded["source_digest_verifier"]() == source_inspection.sha256


def test_atomic_import_explicit_only_verifies_current_source(tmp_path):
    source = tmp_path / "sample.csv"
    content = b"synthetic explicit-only source"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    database = tmp_path / "reports.sqlite3"

    imported = import_parse_result_v2_if_absent(
        _persistable_parse_result(),
        source_path=source,
        database=str(database),
        source_sha256=digest,
    )
    with closing(sqlite3.connect(database)) as connection:
        graph_before_drift = tuple(connection.iterdump())
    source.write_bytes(b"synthetic explicit-only changed source")

    with pytest.raises(ValueError, match="does not match the final source digest"):
        import_parse_result_v2_if_absent(
            _persistable_parse_result(),
            source_path=source,
            database=str(database),
            source_sha256=digest,
        )
    with closing(sqlite3.connect(database)) as connection:
        graph_after_drift = tuple(connection.iterdump())

    assert imported is ReportImportDisposition.IMPORTED
    assert graph_after_drift == graph_before_drift


def test_replacement_payload_rejects_digest_binding_before_repository(tmp_path, monkeypatch):
    source = tmp_path / "sample.csv"
    content_a = b"synthetic replacement source revision A"
    content_b = b"synthetic replacement source revision B"
    source.write_bytes(content_a)
    digest_a = hashlib.sha256(content_a).hexdigest()
    source.write_bytes(content_b)
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    database = tmp_path / "reports.sqlite3"
    parse_result = _persistable_parse_result()
    payload = build_persistence_payload(parse_result, source_path=source)
    repository_calls = _forbid_repository_construction(monkeypatch)

    with pytest.raises(ValueError, match="does not match the inspected source digest"):
        persist_parse_result_v2_payload(
            payload,
            parse_result=parse_result,
            source_path=source,
            database=str(database),
            source_sha256=digest_a,
            source_inspection=source_inspection,
        )

    assert repository_calls == []
    assert not database.exists()


def test_replacement_payload_rejects_source_drift_before_repository(tmp_path, monkeypatch):
    source = tmp_path / "sample.csv"
    source.write_bytes(b"synthetic inspected replacement source")
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    assert source_inspection.sha256 is not None
    source.write_bytes(b"synthetic changed replacement source")
    database = tmp_path / "reports.sqlite3"
    parse_result = _persistable_parse_result()
    payload = build_persistence_payload(parse_result, source_path=source)
    repository_calls = _forbid_repository_construction(monkeypatch)

    with pytest.raises(SourceChangedAfterInspectionError):
        persist_parse_result_v2_payload(
            payload,
            parse_result=parse_result,
            source_path=source,
            database=str(database),
            source_inspection=source_inspection,
        )

    assert repository_calls == []
    assert not database.exists()


def test_replacement_payload_persists_matching_inspected_digest(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_bytes(b"synthetic matching replacement source")
    source_inspection = SourceInspectionContext.from_path(source, source_format="csv")
    assert source_inspection.sha256 is not None
    database = tmp_path / "reports.sqlite3"
    parse_result = _persistable_parse_result()
    payload = build_persistence_payload(parse_result, source_path=source)

    report_id = persist_parse_result_v2_payload(
        payload,
        parse_result=parse_result,
        source_path=source,
        database=str(database),
        source_sha256=source_inspection.sha256.upper(),
        source_inspection=source_inspection,
    )
    with closing(sqlite3.connect(database)) as connection:
        persisted_digest = connection.execute("SELECT sha256 FROM source_files").fetchone()[0]

    assert report_id > 0
    assert persisted_digest == source_inspection.sha256
