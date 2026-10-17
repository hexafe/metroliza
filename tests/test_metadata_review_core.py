"""Pre-import metadata review (#1100): reading, merge rules, plan binding and import."""

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.metadata_review import (
    MODE_FAST,
    MODE_OCR,
    MetadataReviewReader,
)
from metroliza.parsing.parse_reports_thread import ParseReportsThread
from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
from metroliza.reports.report_metadata_normalizers import is_missing_reference
from metroliza.reports.report_metadata_review import (
    CORE_FIELDS,
    FieldOverride,
    ReportMetadataOverride,
    ReviewRow,
    apply_value_to_rows,
    build_overrides,
    normalize_review_value,
)
from metroliza.shared.parse_contracts import ParseRequest


FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"
NAME = "ABCDE12345_Part_Name_2024-05-06_7.pdf"


def _item(text, x0, y0, x1, y1):
    return {
        "text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "page_number": 1, "region_name": "page1_header_band_ocr",
    }


FAKE_OCR_ITEMS = [
    _item("DRAWING No", 296.5, 44.8, 337.2, 50.6),
    _item("OCR-REF-9", 358.4, 45.1, 405.8, 50.6),
    _item("DRAWING REV", 167.4, 44.8, 213.0, 50.6),
    _item("D.01", 231.8, 44.8, 245.0, 51.1),
    _item("STATS COUNT", 423.5, 45.1, 469.4, 50.0),
    _item("12", 491.3, 45.6, 494.4, 49.5),
    _item("PART NAME", 150, 10, 178, 16),
    _item("Header Part", 182, 10, 220, 16),
]


@pytest.fixture
def fake_ocr(monkeypatch):
    calls = []

    def _fake(cls, page, bbox, pdf_backend):
        calls.append(bbox)
        return list(FAKE_OCR_ITEMS), None

    monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(_fake))
    return calls


def _source(tmp_path, names=(NAME,), tag="unique"):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    for index, name in enumerate(names):
        (source / name).write_bytes(FIXTURE.read_bytes() + f"\n% {tag}-{index}\n".encode())
    return source


def _review(source, database, metadata_parsing_mode="light"):
    return ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode=metadata_parsing_mode
    )


def _rows(review):
    return {
        item.stable_occurrence_id: ReviewRow(
            item.stable_occurrence_id, item.fingerprint, item.display_name, item.parser_id
        )
        for item in review.ready_files
    }


def _read(reader, rows, mode=MODE_FAST, **kwargs):
    readings = []
    reader.read(list(rows), mode=mode, on_reading=readings.append, **kwargs)
    for reading in readings:
        row = rows[reading.occurrence_id]
        if reading.status != "ok":
            row.mark_failed(reading.note, state=reading.status)
        elif mode == MODE_FAST:
            row.apply_fast(reading.selection)
        else:
            row.apply_ocr(reading.selection, note=reading.ocr_note)
    return readings


def _graph(database):
    with closing(sqlite3.connect(database)) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in (
                "parsed_reports", "report_metadata", "report_metadata_candidates",
                "report_metadata_warnings", "report_measurements",
            )
        }


# --- shared "missing reference" definition ---------------------------------


@pytest.mark.parametrize(
    ("value", "missing"),
    [(None, True), ("", True), ("   ", True), ("\t", True), (" ", True),
     (float("nan"), True), ("REF1", False), (" REF1 ", False), (0, False)],
)
def test_is_missing_reference_is_the_single_shared_definition(value, missing):
    assert is_missing_reference(value) is missing


# --- fast prefill (no database) ---------------------------------------------


def test_fast_prefill_reads_filename_metadata_without_touching_the_database(tmp_path):
    source = _source(tmp_path)
    database = tmp_path / "never-created.sqlite3"
    review = _review(source, database)
    rows = _rows(review)

    readings = _read(MetadataReviewReader(review), rows)

    assert [reading.status for reading in readings] == ["ok"]
    row = next(iter(rows.values()))
    assert row.value("reference") == "ABCDE12345"
    assert row.value("part_name") == "Part Name"
    assert row.value("sample_number") == "7"
    assert row.value("report_date") == "2024-05-06"
    assert row.cells["reference"].source == "filename_candidate"
    assert row.cells["reference"].confidence == pytest.approx(0.74)
    assert row.warnings and row.metadata_confidence > 0
    assert not row.missing_fields and not row.reference_missing
    # Part name (0.66) and sample number (0.63) are filename-only, hence low confidence.
    assert set(row.low_confidence_fields) == {"part_name", "sample_number"}
    assert not database.exists()


def test_missing_core_fields_are_flagged(tmp_path):
    source = _source(tmp_path, names=("noreference.pdf",))
    review = _review(source, tmp_path / "db.sqlite3")
    rows = _rows(review)
    _read(MetadataReviewReader(review), rows)

    row = next(iter(rows.values()))
    assert row.reference_missing
    assert {"reference", "sample_number", "report_date"} <= set(row.missing_fields)
    assert set(row.missing_fields) <= set(CORE_FIELDS)
    assert row.needs_attention


def test_reader_reports_changed_source_and_does_not_reapprove_it(tmp_path):
    source = _source(tmp_path)
    review = _review(source, tmp_path / "db.sqlite3")
    rows = _rows(review)
    (source / NAME).write_bytes((source / NAME).read_bytes() + b"changed after review")

    readings = _read(MetadataReviewReader(review), rows)

    assert [reading.status for reading in readings] == ["changed"]
    row = next(iter(rows.values()))
    assert row.state == "changed" and not row.editable
    assert row.to_override() is None


def test_reader_resolves_archive_members_by_occurrence_id(tmp_path):
    archive = tmp_path / "reports.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"sub/{NAME}", FIXTURE.read_bytes())
    review = _review(archive, tmp_path / "db.sqlite3")
    rows = _rows(review)
    assert list(rows) == [f"sub/{NAME}"]

    _read(MetadataReviewReader(review), rows)

    assert rows[f"sub/{NAME}"].value("reference") == "ABCDE12345"


def test_reader_cancel_keeps_completed_readings(tmp_path):
    source = _source(tmp_path, names=("AAAAA11111_a_2024-01-01_1.pdf", "BBBBB22222_b_2024-01-02_2.pdf"))
    review = _review(source, tmp_path / "db.sqlite3")
    rows = _rows(review)
    seen = []

    def stop_after_first():
        return len(seen) >= 1

    summary = MetadataReviewReader(review).read(
        list(rows), mode=MODE_FAST, should_cancel=stop_after_first, on_reading=seen.append
    )

    assert (summary.read, summary.cancelled) == (1, 1)
    assert len(seen) == 1


def test_parser_without_override_support_is_read_only(tmp_path):
    source = _source(tmp_path)
    review = _review(source, tmp_path / "db.sqlite3")
    rows = _rows(review)

    class _Plain:
        def __init__(self, *args, **kwargs):
            pass

    reader = MetadataReviewReader(review, parser_factory=lambda *a, **k: _Plain())
    readings = _read(reader, rows)

    assert readings[0].status == "unsupported"
    assert not next(iter(rows.values())).editable


# --- manual edit, bulk apply -------------------------------------------------


def _prefilled_rows(tmp_path, names):
    source = _source(tmp_path, names=names)
    database = tmp_path / "reports.sqlite3"
    review = _review(source, database)
    rows = _rows(review)
    reader = MetadataReviewReader(review)
    _read(reader, rows)
    return source, database, review, rows, reader


def test_manual_edit_normalizes_validates_and_tracks_origin(tmp_path):
    *_, rows, _reader = _prefilled_rows(tmp_path, (NAME,))
    row = next(iter(rows.values()))

    assert row.set_user_value("reference", "  NEW   REF ") == (True, None)
    assert row.value("reference") == "NEW REF"
    assert row.cells["reference"].origin == "user"
    assert row.edited_fields == ("reference",)

    accepted, error = row.set_user_value("report_date", "not a date")
    assert not accepted and error
    assert row.value("report_date") == "2024-05-06"

    assert row.set_user_value("report_date", "2024/07/09") == (True, None)
    assert row.value("report_date") == "2024-07-09"

    # Typing the detected value again returns the cell to "detected".
    assert row.set_user_value("reference", "ABCDE12345") == (True, None)
    assert row.cells["reference"].origin == "detected"
    assert row.edited_fields == ("report_date",)

    assert row.set_user_value("reference", "") == (True, None)
    assert row.reference_missing
    assert row.cells["reference"].user_set


def test_bulk_apply_sets_one_value_on_selected_rows_only(tmp_path):
    *_, rows, _reader = _prefilled_rows(
        tmp_path, ("AAAAA11111_a_2024-01-01_1.pdf", "BBBBB22222_b_2024-01-02_2.pdf", "c.pdf")
    )
    ordered = sorted(rows.values(), key=lambda row: row.display_name)

    changed, error = apply_value_to_rows(ordered[:2], "reference", "COMMON-REF")
    assert (changed, error) == (2, None)
    assert [row.value("reference") for row in ordered] == ["COMMON-REF", "COMMON-REF", None]
    assert apply_value_to_rows(ordered, "report_date", "31.02.2024")[1]  # invalid date, nothing applied
    assert ordered[2].value("report_date") is None


def test_normalize_review_value_supports_all_review_fields():
    assert normalize_review_value("report_time", "9:5") == ("09:05", None)
    assert normalize_review_value("report_time", "25:99")[1]
    assert normalize_review_value("comment", "  ") == (None, None)
    with pytest.raises(ValueError):
        normalize_review_value("identity_hash", "x")


# --- OCR merge ---------------------------------------------------------------


def test_ocr_fills_unedited_fields_and_never_overwrites_manual_values(tmp_path, fake_ocr):
    *_, rows, reader = _prefilled_rows(tmp_path, (NAME,))
    row = next(iter(rows.values()))
    row.set_user_value("reference", "MY-MANUAL-REF")

    _read(reader, rows, mode=MODE_OCR)

    assert fake_ocr, "the injected OCR backend was used"
    assert row.value("reference") == "MY-MANUAL-REF"
    assert row.cells["reference"].origin == "user"
    assert row.cells["reference"].ocr_suggestion == "OCR-REF-9"
    assert row.conflict_fields == ("reference",)
    assert row.value("part_name") == "Header Part"
    assert row.cells["part_name"].origin == "ocr"
    assert row.value("revision") == "D.01"
    assert row.value("sample_number") == "12"
    assert row.value("report_date") == "2024-05-06"  # kept from fast detection
    assert row.ocr_state == "done"

    # The user can correct the table again after OCR.
    assert row.set_user_value("part_name", "Corrected Part") == (True, None)
    assert row.value("part_name") == "Corrected Part"

    # Only an explicit action replaces the manual value with the OCR one.
    assert row.accept_ocr_suggestions() == ("reference",)
    assert row.value("reference") == "OCR-REF-9" and row.cells["reference"].origin == "ocr"


def test_second_ocr_run_keeps_edits_made_after_the_first(tmp_path, fake_ocr):
    *_, rows, reader = _prefilled_rows(tmp_path, (NAME,))
    row = next(iter(rows.values()))
    _read(reader, rows, mode=MODE_OCR)
    row.set_user_value("revision", "Z")
    _read(reader, rows, mode=MODE_OCR)
    assert row.value("revision") == "Z"
    assert row.cells["revision"].ocr_suggestion == "D.01"


def test_unavailable_ocr_backend_is_reported_with_a_coarse_note(tmp_path, monkeypatch):
    monkeypatch.setattr(
        CMMReportParser,
        "_ocr_header_items_from_pixmap",
        classmethod(lambda cls, page, bbox, pdf: ([], "header_ocr_models_missing:/secret/path/x.onnx")),
    )
    *_, rows, reader = _prefilled_rows(tmp_path, (NAME,))

    readings = _read(reader, rows, mode=MODE_OCR)

    assert readings[0].ocr_note == "OCR models are not installed."
    assert "secret" not in readings[0].ocr_note
    assert next(iter(rows.values())).value("reference") == "ABCDE12345"


# --- import plan binding -----------------------------------------------------


def _plan(source, database, review, overrides=(), selected=None):
    request = ParseRequest(
        source_directory=str(source),
        db_file=str(database),
        metadata_parsing_mode=review.metadata_parsing_mode,
    )
    ids = selected if selected is not None else [item.stable_occurrence_id for item in review.ready_files]
    return ImportPlan.from_preflight(
        request, review, selected_occurrence_ids=ids, metadata_overrides=overrides
    )


def test_plan_rejects_overrides_for_unselected_duplicate_or_stale_reports(tmp_path):
    source, database, review, rows, _reader = _prefilled_rows(
        tmp_path, ("AAAAA11111_a_2024-01-01_1.pdf", "BBBBB22222_b_2024-01-02_2.pdf")
    )
    first, second = sorted(rows.values(), key=lambda row: row.display_name)
    good = ReportMetadataOverride(
        first.occurrence_id, first.fingerprint, (FieldOverride("reference", "X", "user"),)
    )

    assert _plan(source, database, review, [good]).metadata_overrides == (good,)
    with pytest.raises(ValueError, match="unselected"):
        _plan(source, database, review, [good], selected=[second.occurrence_id])
    with pytest.raises(ValueError, match="reviewed content"):
        _plan(source, database, review, [replace(good, fingerprint="sha256:" + "0" * 64)])
    with pytest.raises(ValueError, match="duplicate"):
        _plan(source, database, review, [good, good])


def test_overrides_are_keyed_by_occurrence_not_display_name(tmp_path):
    source = tmp_path / "source"
    (source / "a").mkdir(parents=True)
    (source / "b").mkdir()
    (source / "a" / NAME).write_bytes(FIXTURE.read_bytes() + b"\n% a\n")
    (source / "b" / NAME).write_bytes(FIXTURE.read_bytes() + b"\n% b\n")
    database = tmp_path / "db.sqlite3"
    review = _review(source, database)
    rows = _rows(review)
    assert sorted(rows) == [f"a/{NAME}", f"b/{NAME}"]  # same file name, distinct identities
    _read(MetadataReviewReader(review), rows)
    rows[f"b/{NAME}"].set_user_value("reference", "ONLY-B")

    plan = _plan(source, database, review, build_overrides(rows.values()))
    ParseReportsThread(plan).run()

    with closing(sqlite3.connect(database)) as connection:
        stored = {
            Path(directory).name: reference
            for directory, reference in connection.execute(
                "SELECT sfl.directory_path, rm.reference FROM report_metadata rm "
                "JOIN parsed_reports pr ON pr.id = rm.report_id "
                "JOIN source_file_locations sfl ON sfl.source_file_id = pr.source_file_id"
            )
        }
    assert stored == {"a": "ABCDE12345", "b": "ONLY-B"}


# --- import: values equal the table, provenance is auditable ------------------


def _single_report(database):
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        metadata = connection.execute("SELECT * FROM report_metadata").fetchone()
        candidates = connection.execute(
            "SELECT field_name, raw_value, normalized_value, source_type, is_selected, confidence "
            "FROM report_metadata_candidates ORDER BY id"
        ).fetchall()
        report = connection.execute("SELECT identity_hash, parse_status FROM parsed_reports").fetchone()
    return dict(metadata), [dict(row) for row in candidates], dict(report)


def test_import_writes_the_confirmed_values_and_records_provenance(tmp_path, fake_ocr):
    source, database, review, rows, reader = _prefilled_rows(tmp_path, (NAME,))
    row = next(iter(rows.values()))
    _read(reader, rows, mode=MODE_OCR)
    row.set_user_value("reference", "USER-REF")
    row.set_user_value("report_date", "2025-01-02")
    shown = {name: row.value(name) for name in ("reference", "part_name", "sample_number",
                                                 "report_date", "revision")}
    assert not database.exists()  # nothing written while reviewing

    plan = _plan(source, database, review, build_overrides(rows.values()))
    worker = ParseReportsThread(plan)
    worker.run()
    assert worker.last_parse_result.imported_files == 1

    metadata, candidates, report = _single_report(database)
    # Imported values equal what the table showed at import time.
    assert {name: metadata[name] for name in shown} == shown
    # The detected raw reference is preserved next to the confirmed value.
    assert metadata["reference_raw"] == "ABCDE12345"
    metadata_json = json.loads(metadata["metadata_json"])
    assert metadata_json["field_sources"]["reference"] == "user_manual"
    assert metadata_json["manual_overrides"]["reference"]["value"] == "USER-REF"
    assert metadata_json["manual_overrides"]["reference"]["source"] == "metadata_review"
    assert "part_name" not in metadata_json["manual_overrides"]  # OCR value is not a manual edit
    review_json = metadata_json["metadata_review"]
    assert review_json["edited_fields"] == ["reference", "report_date"]
    assert "part_name" in review_json["ocr_fields"] and review_json["ocr_run"] is True
    assert review_json["detected_values"]["reference"] == "ABCDE12345"
    # Detected candidates stay (unselected); exactly one selected candidate per overridden field.
    user = [c for c in candidates if c["source_type"] == "user_manual"]
    assert {c["field_name"]: c["normalized_value"] for c in user} == {
        "reference": "USER-REF", "report_date": "2025-01-02"}
    assert all(c["is_selected"] == 1 and c["confidence"] == 1.0 for c in user)
    reference_rows = [c for c in candidates if c["field_name"] == "reference"]
    assert sorted((c["source_type"], c["normalized_value"], c["is_selected"]) for c in reference_rows) == [
        ("filename_candidate", "ABCDE12345", 0),
        ("header_alias", "OCR-REF-9", 0),
        ("position_cell", "OCR-REF-9", 0),
        ("user_manual", "USER-REF", 1),
    ]
    part_rows = [c for c in candidates if c["field_name"] == "part_name" and c["is_selected"]]
    assert [c["normalized_value"] for c in part_rows] == ["Header Part"]
    assert part_rows[0]["source_type"] != "filename_candidate"
    # Identity reflects the confirmed values (semantic duplicate detection uses it).
    assert report["identity_hash"]


def test_manual_value_wins_over_ocr_repeated_during_complete_import(tmp_path, fake_ocr):
    # "Complete" imports run header OCR again while parsing; the reviewed value must survive it.
    source = _source(tmp_path)
    database = tmp_path / "db.sqlite3"
    review = _review(source, database, metadata_parsing_mode="complete")
    rows = _rows(review)
    _read(MetadataReviewReader(review), rows)
    row = next(iter(rows.values()))
    row.set_user_value("reference", "USER-REF")

    plan = _plan(source, database, review, build_overrides(rows.values()))
    ParseReportsThread(plan).run()

    metadata, candidates, _report = _single_report(database)
    assert fake_ocr, "complete import should have run header OCR"
    assert metadata["reference"] == "USER-REF"
    assert any(c["source_type"] == "user_manual" and c["is_selected"] == 1 for c in candidates)


def test_import_without_overrides_is_unchanged(tmp_path):
    source, database, review, _rows_, _reader = _prefilled_rows(tmp_path, (NAME,))

    ParseReportsThread(_plan(source, database, review)).run()

    metadata, candidates, _report = _single_report(database)
    assert metadata["reference"] == "ABCDE12345"
    assert "metadata_review" not in json.loads(metadata["metadata_json"])
    assert {c["source_type"] for c in candidates} == {"filename_candidate"}


def test_user_cleared_value_is_imported_as_empty(tmp_path):
    source, database, review, rows, _reader = _prefilled_rows(tmp_path, (NAME,))
    row = next(iter(rows.values()))
    row.set_user_value("part_name", "")

    ParseReportsThread(_plan(source, database, review, build_overrides(rows.values()))).run()

    metadata, candidates, _report = _single_report(database)
    assert metadata["part_name"] is None
    assert not [c for c in candidates if c["field_name"] == "part_name" and c["is_selected"]]


# --- cancel / invalidation: no database write ---------------------------------


def test_cancelled_review_never_creates_or_changes_the_database(tmp_path, fake_ocr):
    source, database, review, rows, reader = _prefilled_rows(tmp_path, (NAME,))
    next(iter(rows.values())).set_user_value("reference", "DISCARDED")
    _read(reader, rows, mode=MODE_OCR, should_cancel=lambda: True)  # cancelled before any report
    assert not database.exists()

    # With an existing database the full graph is byte-for-byte unchanged.
    other = _source(tmp_path / "second", ("ZZZZZ99999_z_2024-02-02_3.pdf",), tag="other")
    ParseReportsThread(_plan(other, database, _review(other, database))).run()
    before = _graph(database)
    review2 = _review(source, database)
    rows2 = _rows(review2)
    reader2 = MetadataReviewReader(review2)
    _read(reader2, rows2)
    _read(reader2, rows2, mode=MODE_OCR)
    next(iter(rows2.values())).set_user_value("reference", "NOT-IMPORTED")
    assert _graph(database) == before


def test_source_change_after_review_invalidates_the_plan_and_writes_nothing(tmp_path):
    source, database, review, rows, _reader = _prefilled_rows(tmp_path, (NAME,))
    next(iter(rows.values())).set_user_value("reference", "WONT-BE-IMPORTED")
    plan = _plan(source, database, review, build_overrides(rows.values()))
    (source / NAME).write_bytes((source / NAME).read_bytes() + b"tampered")

    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == 0
    assert worker.last_parse_result.preflight_changed_files == 1
    assert not database.exists() or _graph(database)["parsed_reports"] == []


def test_override_for_a_parser_without_support_fails_closed(tmp_path, monkeypatch):
    source, database, review, rows, _reader = _prefilled_rows(tmp_path, (NAME,))
    next(iter(rows.values())).set_user_value("reference", "X")
    plan = _plan(source, database, review, build_overrides(rows.values()))
    monkeypatch.setattr(CMMReportParser, "supports_metadata_review_override", False)

    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == 0
    assert worker.last_parse_result.failed_files == 1
    assert not database.exists() or _graph(database)["parsed_reports"] == []
