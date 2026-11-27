"""Pre-import metadata review (#1100): reading, merge rules, plan binding and import."""

from contextlib import closing
from dataclasses import replace
import hashlib
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
from metroliza.reports.report_curation import load_stored_report_context
from metroliza.reports.report_metadata_normalizers import is_missing_reference
from metroliza.reports.report_metadata_review import (
    CORE_FIELDS,
    FieldOverride,
    OcrSuggestionDecision,
    ReportMetadataOverride,
    ReviewRow,
    apply_metadata_override,
    apply_value_to_rows,
    build_overrides,
    normalize_review_value,
)
from metroliza.reports.report_repository import ReportRepository
from metroliza.shared.parse_contracts import ParseRequest
from tests.metadata_review_fakes import FILE_NAME, make_selection


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


def _prefilled_rows(tmp_path, names, *, metadata_parsing_mode="light"):
    source = _source(tmp_path, names=names)
    database = tmp_path / "reports.sqlite3"
    review = _review(source, database, metadata_parsing_mode)
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
    source, database, review, rows, reader = _prefilled_rows(tmp_path, (NAME,))
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
    choices = build_overrides(rows.values())
    candidate = next(item.ocr_candidate for item in choices[0].fields if item.field_name == "reference")
    assert candidate.region_name == "page1_header_band_ocr" and candidate.page_number == 1
    assert not database.exists()
    worker = ParseReportsThread(_plan(source, database, review, overrides=choices))
    worker.run()
    assert worker.last_parse_result.imported_files == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT reference FROM report_metadata").fetchone() == ("OCR-REF-9",)
        assert connection.execute(
            "SELECT normalized_value, region_name, page_number, confidence "
            "FROM report_metadata_candidates WHERE field_name = 'reference' AND is_selected = 1"
        ).fetchall() == [("OCR-REF-9", candidate.region_name, 1, candidate.confidence)]


def test_second_ocr_run_keeps_edits_made_after_the_first(tmp_path, fake_ocr):
    *_, rows, reader = _prefilled_rows(tmp_path, (NAME,))
    row = next(iter(rows.values()))
    _read(reader, rows, mode=MODE_OCR)
    row.set_user_value("revision", "Z")
    _read(reader, rows, mode=MODE_OCR)
    assert row.value("revision") == "Z"
    assert row.cells["revision"].ocr_suggestion == "D.01"


def test_deferred_ocr_can_be_resolved_and_rejection_is_specific_to_that_reading():
    row = ReviewRow("one.pdf", "sha256:one", "one.pdf", "cmm")
    row.set_user_value("reference", "MANUAL")
    first = make_selection({"reference": ("FIRST", "header_exact", 0.74)})
    latest = make_selection({"reference": ("SECOND", "header_exact", 0.92)})
    row.apply_ocr(first)
    assert row.defer_ocr_suggestion("reference")
    assert row.value("reference") == "MANUAL"
    assert row.has_deferred_ocr_suggestion("reference")
    assert not row.defer_ocr_suggestion("reference")

    row.apply_ocr(first)
    assert row.has_deferred_ocr_suggestion("reference")
    assert row.dismiss_ocr_suggestion("reference")
    row.apply_ocr(first)
    assert row.suggested_ocr_candidate("reference") is None
    assert row.value("reference") == "MANUAL"

    row.apply_ocr(latest)
    assert row.suggested_ocr_candidate("reference") == latest.candidates[0]
    assert not row.has_deferred_ocr_suggestion("reference")
    assert row.defer_ocr_suggestion("reference")
    row.mark_ocr_failed("No new OCR evidence")
    assert not row.defer_ocr_suggestion("reference")
    assert not row.dismiss_ocr_suggestion("reference")
    assert row.accept_ocr_suggestions(("reference",)) == ()
    row.apply_ocr(latest)
    assert row.accept_ocr_suggestions(("reference",)) == ("reference",)
    assert row.value("reference") == "SECOND"
    assert row.to_override().ocr_decisions == ()


def test_current_ocr_decision_audit_records_only_backed_conflicting_evidence():
    row = ReviewRow("one.pdf", "sha256:one", "one.pdf", "cmm")
    row.set_user_value("reference", "MANUAL")
    first = make_selection({"reference": ("FIRST", "header_exact", 0.74)})
    latest = make_selection({"reference": ("SECOND", "header_exact", 0.92)})
    row.apply_ocr(first)
    assert row.defer_ocr_suggestion("reference")
    row.apply_ocr(latest)
    assert not row.has_deferred_ocr_suggestion("reference")
    assert row.suggested_ocr_candidate("reference") == latest.candidates[0]
    decision, = row.to_override().ocr_decisions
    assert decision == OcrSuggestionDecision("deferred", first.candidates[0])
    audit = apply_metadata_override(latest, row.to_override())
    assert audit.metadata.reference == "MANUAL"
    assert replace(first.candidates[0], selected=False) in audit.candidates
    assert audit.metadata.metadata_json["metadata_review"]["ocr_decisions"]["reference"]["value"] == "FIRST"

    with pytest.raises(ValueError, match="matching OCR evidence"):
        OcrSuggestionDecision("deferred", replace(first.candidates[0], selected=False))
    with pytest.raises(ValueError, match="distinct confirmed value"):
        ReportMetadataOverride(row.occurrence_id, row.fingerprint, ocr_decisions=(decision,))

    # A fast reread can detect the same value as the manual override. Explicitly
    # reverting to that detection drops the anchor and the review decision.
    row.apply_fast(make_selection({"reference": "MANUAL"}))
    assert row.set_user_value("reference", "MANUAL") == (True, None)
    assert not row.conflict_fields
    assert row.to_override().ocr_decisions == ()


def test_explicit_acceptance_preserves_the_exact_ocr_candidate_after_another_read():
    row = ReviewRow("one.pdf", "sha256:one", "one.pdf", "cmm")
    row.set_user_value("reference", "MANUAL")
    row.set_user_value("revision", "MANUAL-REV")
    first = make_selection({
        "reference": ("FIRST", "header_exact", 0.74), "revision": "A",
    })
    accepted_candidate = replace(
        first.candidates[0], raw_value=" FIRST ", region_name="page1_header_band_ocr",
    )
    row.apply_ocr(replace(first, candidates=(accepted_candidate, first.candidates[1])))

    assert row.value("reference") == "MANUAL"
    assert row.accept_ocr_suggestions(("reference",)) == ("reference",)
    assert row.cells["reference"].source == accepted_candidate.source_type
    assert row.cells["reference"].confidence == accepted_candidate.confidence
    assert row.value("revision") == "MANUAL-REV"
    latest = make_selection({"reference": ("SECOND", "header_exact", 0.95), "revision": "B"})
    row.apply_ocr(latest)
    assert row.value("reference") == "FIRST"
    assert row.cells["reference"].ocr_suggestion == "SECOND"
    assert row.value("revision") == "MANUAL-REV"

    # A different reading can find the same normalized value with higher confidence
    # and the same candidate key. It must retain its own evidence as an alternative.
    fresh_candidate = replace(accepted_candidate, confidence=0.99, region_name="page1_header_band_words")
    fresh = replace(first, candidates=(fresh_candidate, first.candidates[1]))
    applied = apply_metadata_override(fresh, row.to_override(), applied_at="2026-01-01")
    assert applied.metadata.reference == "FIRST"
    assert [item for item in applied.candidates if item.field_name == "reference" and item.selected] == [
        accepted_candidate,
    ]
    assert replace(fresh_candidate, selected=False) in applied.candidates
    assert replace(latest.candidates[0], selected=False) in applied.candidates
    assert applied.metadata.revision == "MANUAL-REV"
    row.mark_ocr_failed("Synthetic failed reread")
    assert row.value("reference") == "FIRST"
    assert accepted_candidate in apply_metadata_override(fresh, row.to_override()).candidates

    assert row.set_user_value("reference", "CORRECTED") == (True, None)
    row.apply_ocr(latest)
    assert row.value("reference") == "CORRECTED"
    assert row.to_override().fields[0] == FieldOverride("reference", "CORRECTED", "user")


@pytest.mark.parametrize("source,extraction_mode", [(FILE_NAME, "ocr"), ("header_exact", "words")])
def test_fallback_cannot_be_accepted_as_ocr(source, extraction_mode):
    row = ReviewRow("one.pdf", "sha256:one", "one.pdf", "cmm")
    row.set_user_value("reference", "MANUAL")
    result = make_selection({"reference": ("FALLBACK", source, 0.8)})
    row.apply_ocr(replace(result, metadata=replace(result.metadata, metadata_json={
        **result.metadata.metadata_json, "header_extraction_mode": extraction_mode,
    })))
    assert not row.conflict_fields
    assert row.accept_ocr_suggestions(("reference",)) == ()
    assert row.value("reference") == "MANUAL"


@pytest.mark.parametrize("state", ["pending", "changed", "unsupported", "failed"])
def test_review_cannot_resolve_a_previous_suggestion_on_an_unready_row(state):
    row = ReviewRow("one.pdf", "sha256:one", "one.pdf", "cmm")
    row.set_user_value("reference", "MANUAL")
    row.apply_ocr(make_selection({"reference": "OCR"}))
    assert row.conflict_fields == ("reference",)
    row.mark_failed("Synthetic unready row", state=state)
    assert row.accept_ocr_suggestions(("reference",)) == ()
    assert not row.dismiss_ocr_suggestion("reference")
    assert not row.defer_ocr_suggestion("reference")
    assert row.value("reference") == "MANUAL"


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
        report = connection.execute(
            "SELECT id, measurement_count, has_nok, nok_count, identity_hash, parse_status FROM parsed_reports"
        ).fetchone()
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


@pytest.mark.parametrize("field", ["reference", "part_name", "sample_number", "report_date", "revision"])
def test_user_cleared_value_survives_fast_import_and_enrichment(tmp_path, fake_ocr, monkeypatch, field):
    source, database, review, rows, reader = _prefilled_rows(tmp_path, (NAME,))
    _read(reader, rows, mode=MODE_OCR)
    row = next(iter(rows.values()))
    assert row.value(field)
    row.set_user_value(field, "")
    plan = replace(
        _plan(source, database, review, build_overrides(rows.values())),
        run_background_metadata_enrichment=True,
    )
    imported = []
    complete = ParseReportsThread._complete_requested_enrichment

    def capture_import(worker, paths, connection):
        imported.append(_single_report(database)[0][field])
        return complete(worker, paths, connection)

    monkeypatch.setattr(ParseReportsThread, "_complete_requested_enrichment", capture_import)
    worker = ParseReportsThread(plan)
    worker.run()

    assert imported == [None]
    assert worker.last_parse_result.imported_files == 1
    assert worker.last_enrichment_result.enriched_files == 1
    metadata, candidates, _report = _single_report(database)
    assert metadata[field] is None
    assert not [c for c in candidates if c["field_name"] == field and c["is_selected"]]
    provenance = json.loads(metadata["metadata_json"])
    assert provenance["manual_overrides"][field]["value"] is None
    assert provenance["field_sources"][field] == "user_manual"


@pytest.mark.parametrize("reference", ["REVIEWED-REF", "OCR-REF-9"])
def test_complete_enrichment_preserves_existing_manual_candidate_history(
    tmp_path, fake_ocr, monkeypatch, reference,
):
    source = _source(tmp_path)
    database = tmp_path / "db.sqlite3"
    plan = replace(_plan(source, database, _review(source, database)), run_background_metadata_enrichment=True)
    complete = ParseReportsThread._complete_requested_enrichment
    captured = {}

    def with_manual_edits(worker, paths, connection):
        metadata, _, _ = _single_report(database)
        ReportRepository(str(database)).update_report_metadata_fields(
            metadata["report_id"], {"reference": reference, "part_name": None},
        )
        captured["before"] = _graph(database)
        complete(worker, paths, connection)
        captured["first_result"] = worker.last_enrichment_result
        captured["enriched"] = _graph(database)
        complete(worker, paths, connection)
        captured["repeated_result"] = worker.last_enrichment_result
        captured["repeated"] = _graph(database)
        with closing(sqlite3.connect(database)) as blocker, blocker:
            blocker.execute(
                "CREATE TRIGGER reject_enrichment BEFORE UPDATE OF raw_report_json ON parsed_reports "
                "BEGIN SELECT RAISE(ABORT, 'synthetic enrichment rollback'); END"
            )

        def changed_ocr(cls, page, bbox, pdf_backend):
            return [dict(item, text="OCR-REF-ROLLBACK") if item["text"] == "OCR-REF-9" else item
                    for item in FAKE_OCR_ITEMS], None

        monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(changed_ocr))
        complete(worker, paths, connection)
        captured["rolled_back"] = _graph(database)

    monkeypatch.setattr(ParseReportsThread, "_complete_requested_enrichment", with_manual_edits)
    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == 1
    assert captured["first_result"].enriched_files == captured["repeated_result"].enriched_files == 1
    assert worker.last_enrichment_result.failed_files == 1
    metadata, candidates, _ = _single_report(database)
    assert (metadata["reference"], metadata["part_name"]) == (reference, None)
    reference_rows = [item for item in candidates if item["field_name"] == "reference"]
    assert [(item["source_type"], item["normalized_value"]) for item in reference_rows if item["is_selected"]] == [
        ("user_manual", reference)
    ]
    assert any(item["normalized_value"] == "OCR-REF-9" and item["source_type"] != "user_manual"
               and not item["is_selected"] for item in reference_rows)
    assert not any(item["is_selected"] for item in candidates if item["field_name"] == "part_name")
    provenance = json.loads(metadata["metadata_json"])
    assert provenance["field_sources"]["reference"] == provenance["field_sources"]["part_name"] == "manual"
    assert provenance["manual_overrides"]["reference"]["value"] == reference
    assert provenance["manual_overrides"]["part_name"]["value"] is None

    def manual_evidence(stage):
        return [row for row in captured[stage]["report_metadata_candidates"]
                if row[2] in {"reference", "part_name"}]

    assert all(row in manual_evidence("enriched") for row in manual_evidence("before"))
    assert manual_evidence("repeated") == manual_evidence("enriched")
    assert len(captured["repeated"]["report_metadata_candidates"]) == len(captured["enriched"]["report_metadata_candidates"])
    assert captured["rolled_back"] == captured["repeated"]


def test_complete_enrichment_preserves_manual_edit_after_snapshot(tmp_path, fake_ocr, monkeypatch):
    from metroliza.parsing import parse_reports_thread as worker_module

    source = _source(tmp_path)
    database = tmp_path / "db.sqlite3"
    plan = replace(_plan(source, database, _review(source, database)), run_background_metadata_enrichment=True)
    read_snapshot = worker_module.report_metadata_row_for_enrichment
    edited = []

    def edit_after_snapshot(db_file, report_id, *, connection=None):
        result = read_snapshot(db_file, report_id, connection=connection)
        ReportRepository(db_file).update_report_metadata_fields(report_id, {"reference": "NEW-MANUAL"})
        edited.append(_graph(database))
        return result

    monkeypatch.setattr(worker_module, "report_metadata_row_for_enrichment", edit_after_snapshot)
    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == 1
    assert worker.last_enrichment_result.failed_files == 1
    assert edited == [_graph(database)]
    assert _single_report(database)[0]["reference"] == "NEW-MANUAL"


def test_deferred_review_distinguishes_same_value_with_different_header_evidence(tmp_path, fake_ocr, monkeypatch):
    from metroliza.parsing.metadata_enrichment_thread import (
        MetadataEnrichmentWorkItem,
        enrich_existing_report_metadata,
    )

    source, database, review, rows, reader = _prefilled_rows(tmp_path, (NAME,), metadata_parsing_mode="complete")
    row = next(iter(rows.values()))
    row.set_user_value("reference", "MANUAL-REF")
    _read(reader, rows, mode=MODE_OCR)
    original = row.suggested_ocr_candidate("reference")
    assert original is not None and original.evidence_text
    assert row.defer_ocr_suggestion("reference")

    add_diagnostics = CMMReportParser._apply_header_extraction_diagnostics

    def changed_evidence(parser, selection):
        selection = add_diagnostics(parser, selection)
        return replace(selection, candidates=tuple(
            replace(item, evidence_text="Same OCR value with changed nearby text") if item == original else item
            for item in selection.candidates
        ))

    monkeypatch.setattr(CMMReportParser, "_apply_header_extraction_diagnostics", changed_evidence)
    worker = ParseReportsThread(_plan(source, database, review, build_overrides(rows.values())))
    worker.run()
    assert worker.last_parse_result.imported_files == 1
    metadata, _, report = _single_report(database)
    assert metadata["reference"] == "MANUAL-REF"

    def reference_evidence():
        with closing(sqlite3.connect(database)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM report_metadata_candidates WHERE report_id = ? AND field_name = 'reference'",
                (report["id"],),
            ).fetchall()

    identity_fields = ("field_name", "normalized_value", "source_type", "page_number", "region_name", "rule_id", "confidence")
    matching = [candidate for candidate in reference_evidence()
                if all(candidate[name] == getattr(original, name) for name in identity_fields)]
    assert len(matching) == 2
    original_row, = [item for item in matching if item["evidence_text"] == original.evidence_text]

    decision, = load_stored_report_context(str(database), report["id"]).ocr_decisions
    assert decision.approval is not None and decision.approval.candidate_id == original_row["id"]
    receipt = json.loads(metadata["metadata_json"])["metadata_review"]["ocr_decisions"]["reference"]
    assert original.evidence_text not in json.dumps(receipt)
    pdf = source / NAME
    work_item = MetadataEnrichmentWorkItem(report["id"], str(pdf), hashlib.sha256(pdf.read_bytes()).hexdigest())
    assert enrich_existing_report_metadata(str(database), work_item)
    refreshed, = load_stored_report_context(str(database), report["id"]).ocr_decisions
    assert refreshed.approval is not None and refreshed.approval.candidate_id == original_row["id"]
    ReportRepository(str(database)).accept_deferred_ocr(refreshed.approval)
    updated, _, _ = _single_report(database)
    assert updated["reference"] == original.normalized_value
    selected, = [item for item in reference_evidence() if item["is_selected"]]
    assert selected["id"] == original_row["id"]


@pytest.mark.parametrize("metadata_parsing_mode", ["light", "complete"])
def test_imported_deferred_sample_can_be_accepted_and_survives_real_enrichment(
    tmp_path, fake_ocr, monkeypatch, metadata_parsing_mode,
):
    from metroliza.parsing.metadata_enrichment_thread import (
        discover_metadata_enrichment_work,
        enrich_existing_report_metadata,
    )

    source, database, review, rows, reader = _prefilled_rows(tmp_path, (NAME,), metadata_parsing_mode=metadata_parsing_mode)

    def canonical_identity():
        with closing(sqlite3.connect(database)) as connection:
            identity = connection.execute(
                """SELECT pr.parser_id, pr.template_family, pr.template_variant, rm.reference, rm.report_date,
                          rm.report_time, rm.part_name, rm.revision, rm.sample_number, pr.page_count
                   FROM parsed_reports pr JOIN report_metadata rm ON rm.report_id = pr.id""",
            ).fetchone()
        payload = "\x1f".join("" if value is None else str(value).strip() for value in identity)
        return hashlib.sha256(payload.encode()).hexdigest()

    row = next(iter(rows.values()))
    row.set_user_value("sample_number", "19")
    row.set_user_value("reference", "MANUAL-REF")
    _read(reader, rows, mode=MODE_OCR)
    assert row.defer_ocr_suggestion("sample_number") and not database.exists()
    worker = ParseReportsThread(_plan(source, database, review, build_overrides(rows.values())))
    worker.run()
    assert worker.last_parse_result.imported_files == 1
    before, _, parsed_before = _single_report(database)
    assert before["sample_number"] == "19"
    graph_before = _graph(database)
    stored = load_stored_report_context(str(database), parsed_before["id"])
    suggestion, = stored.ocr_decisions
    assert suggestion.value == "12" and suggestion.approval is not None
    repository = ReportRepository(str(database))
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER reject_test_ocr BEFORE UPDATE OF identity_hash ON parsed_reports "
            "BEGIN SELECT RAISE(ABORT, 'synthetic OCR acceptance rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="synthetic OCR acceptance rollback"):
        repository.accept_deferred_ocr(suggestion.approval)
    assert _graph(database) == graph_before
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DROP TRIGGER reject_test_ocr")

    repository.accept_deferred_ocr(suggestion.approval)
    graph_chosen = _graph(database)
    chosen, _, parsed_chosen = _single_report(database)
    review_receipt = json.loads(chosen["metadata_json"])["metadata_review"]
    assert review_receipt["accepted_ocr_fields"] == ["sample_number"]
    assert review_receipt["ocr_decisions"]["sample_number"]["candidate_id"] == suggestion.approval.candidate_id
    assert review_receipt["ocr_decisions"]["sample_number"]["decision"] == "accepted"
    assert (chosen["sample_number"], chosen["sample_number_kind"]) == ("12", "stats_count")
    assert parsed_chosen["identity_hash"] != parsed_before["identity_hash"]
    assert parsed_chosen["identity_hash"] == canonical_identity()
    assert graph_chosen["report_measurements"] == graph_before["report_measurements"]
    with pytest.raises(ValueError, match="stored OCR suggestion changed"):
        repository.accept_deferred_ocr(suggestion.approval)
    assert _graph(database) == graph_chosen

    latest_items = [dict(item, text="13") if item["text"] == "12" else item for item in FAKE_OCR_ITEMS]
    monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap",
                        classmethod(lambda _cls, _page, _bbox, _backend: (latest_items, None)))
    work_item, = discover_metadata_enrichment_work(str(database))
    assert enrich_existing_report_metadata(str(database), work_item)
    after, candidates, parsed_after = _single_report(database)
    graph_after = _graph(database)
    assert (after["sample_number"], after["sample_number_kind"], after["reference"]) == ("12", "stats_count", "MANUAL-REF")
    assert json.loads(after["metadata_json"])["metadata_review"] == review_receipt
    assert parsed_after["identity_hash"] == canonical_identity()
    assert graph_after["report_measurements"] == graph_chosen["report_measurements"]
    assert any(item["field_name"] == "sample_number" and item["normalized_value"] == "13"
               and not item["is_selected"] for item in candidates)
    for graph in (graph_chosen, graph_after):
        selected, = [item for item in graph["report_metadata_candidates"] if item[2] == "sample_number" and item[12]]
        assert selected[0] == suggestion.approval.candidate_id
        assert [item[2] for item in graph["report_metadata_warnings"] if item[3] == "sample_number"
                and item[2].startswith("sample_number_")] == ["sample_number_projected_from_stats_count"]


@pytest.mark.parametrize("legacy_review", [False, True])
def test_enrichment_protects_confirmed_ocr_value_and_original_selected_candidate(
    tmp_path, fake_ocr, monkeypatch, legacy_review,
):
    from metroliza.parsing.metadata_enrichment_thread import (
        discover_metadata_enrichment_work,
        enrich_existing_report_metadata,
    )

    source, database, review, rows, reader = _prefilled_rows(tmp_path, (NAME,))
    row = next(iter(rows.values()))
    row.set_user_value("revision", "MANUAL-REV")
    row.set_user_value("reference", "KEEP-REF")
    row.set_user_value("sample_number", "19")
    _read(reader, rows, mode=MODE_OCR)
    assert row.accept_ocr_suggestions(("revision",)) == ("revision",)
    assert row.dismiss_ocr_suggestion("reference")
    assert row.defer_ocr_suggestion("sample_number")
    assert row.value("revision") == "D.01"
    assert row.value("operator_name") is None
    assert not database.exists()
    plan = replace(_plan(source, database, review, build_overrides(rows.values())),
                   run_background_metadata_enrichment=True)
    stages = {}
    complete = ParseReportsThread._complete_requested_enrichment
    latest_items = [
        dict(item, text={"D.01": "D.02", "OCR-REF-9": "OCR-REF-10", "12": "13"}.get(item["text"], item["text"]))
        for item in FAKE_OCR_ITEMS
    ] + [
        _item("OPERATOR", 167.2, 74.5, 218, 80), _item("CMM OPERATOR A", 225, 74.5, 288, 80),
    ]

    def later_ocr(cls, page, bbox, pdf_backend):
        return latest_items, None

    def with_different_ocr(worker, paths, connection):
        if legacy_review:
            # A saved v1 review from the original planner has no explicit-choice list.
            metadata, _, _ = _single_report(database)
            stored = json.loads(metadata["metadata_json"])
            stored["metadata_review"].pop("accepted_ocr_fields", None)
            with closing(sqlite3.connect(database)) as snapshot, snapshot:
                snapshot.execute("UPDATE report_metadata SET metadata_json = ?", (json.dumps(stored),))
        stages["stored"] = _single_report(database)
        stages["before"] = _graph(database)
        monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(later_ocr))
        complete(worker, paths, connection)
        stages["first_result"] = worker.last_enrichment_result
        stages["first"] = _graph(database)
        stages["first_hash"] = _single_report(database)[2]["identity_hash"]
        complete(worker, paths, connection)
        stages["second"] = _graph(database)
        stages["refreshed"] = _single_report(database)

    monkeypatch.setattr(ParseReportsThread, "_complete_requested_enrichment", with_different_ocr)
    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == 1
    assert stages["first_result"].enriched_files == worker.last_enrichment_result.enriched_files == 1
    before, _, parsed_before = stages["stored"]
    refreshed, candidates, parsed_after = stages["refreshed"]
    assert before["revision"] == refreshed["revision"] == "D.01"
    assert before["reference"] == refreshed["reference"] == "KEEP-REF"
    assert before["sample_number"] == refreshed["sample_number"] == "19"
    assert refreshed["operator_name"] == "CMM_OPERATOR_A"
    old_provenance = json.loads(before["metadata_json"])
    new_provenance = json.loads(refreshed["metadata_json"])
    assert new_provenance["field_sources"]["revision"] == old_provenance["field_sources"]["revision"]
    assert new_provenance["metadata_review"] == old_provenance["metadata_review"]
    decisions = new_provenance["metadata_review"]["ocr_decisions"]
    assert {name: (item["decision"], item["value"], item["region_name"], item["page_number"])
            for name, item in decisions.items()} == {
        "reference": ("rejected", "OCR-REF-9", "page1_header_band_ocr", 1),
        "sample_number": ("deferred", "12", "page1_header_band_ocr", 1),
    }
    assert decisions["sample_number"]["source_type"] == "projected_from_stats_count"
    assert all("raw_value" not in item and "evidence_text" not in item for item in decisions.values())
    for name, decision in decisions.items():
        assert any(item["field_name"] == name and item["normalized_value"] == decision["value"]
                   and not item["is_selected"] for item in candidates)
    if not legacy_review:
        assert new_provenance["metadata_review"]["accepted_ocr_fields"] == ["revision"]
    assert "revision" in new_provenance["metadata_enrichment"]["preserved_fields"]
    assert "revision" not in new_provenance["metadata_enrichment"]["updated_fields"]
    for field_name in ("id", "measurement_count", "has_nok", "nok_count"):
        assert parsed_before[field_name] == parsed_after[field_name]
    from hashlib import sha256

    with closing(sqlite3.connect(database)) as connection:
        stored_identity = connection.execute(
            """SELECT pr.parser_id, pr.template_family, pr.template_variant, rm.reference, rm.report_date,
                      rm.report_time, rm.part_name, rm.revision, rm.sample_number, pr.page_count
               FROM parsed_reports pr JOIN report_metadata rm ON rm.report_id = pr.id""",
        ).fetchone()
    payload = "\x1f".join("" if value is None else str(value).strip() for value in stored_identity)
    assert parsed_after["identity_hash"] == sha256(payload.encode()).hexdigest()
    assert parsed_after["identity_hash"] == stages["first_hash"]
    assert before["stats_count_int"] == refreshed["stats_count_int"] == 7
    assert stages["before"]["report_measurements"] == stages["second"]["report_measurements"]

    def revision_rows(stage):
        return [record for record in stage["report_metadata_candidates"] if record[2] == "revision"]

    first_revision = revision_rows(stages["first"])
    assert all(record in first_revision for record in revision_rows(stages["before"]))
    assert first_revision == revision_rows(stages["second"])
    assert [(item["normalized_value"], item["is_selected"]) for item in candidates
            if item["field_name"] == "revision" and item["is_selected"]] == [("D.01", 1)]
    assert any(item["normalized_value"] == "D.02" and not item["is_selected"] for item in candidates
               if item["field_name"] == "revision")

    existing, = discover_metadata_enrichment_work(str(database))
    retry_snapshot = _graph(database)
    latest_items[:] = [dict(item, text="D.03") if item["text"] == "D.02" else item for item in latest_items]
    with closing(sqlite3.connect(database)) as blocker, blocker:
        blocker.execute(
            "CREATE TRIGGER reject_reviewed_enrichment BEFORE UPDATE OF raw_report_json ON parsed_reports "
            "BEGIN SELECT RAISE(ABORT, 'synthetic reviewed enrichment rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="synthetic reviewed enrichment rollback"):
        enrich_existing_report_metadata(str(database), existing)
    assert _graph(database) == retry_snapshot
    with closing(sqlite3.connect(database)) as blocker, blocker:
        blocker.execute("DROP TRIGGER reject_reviewed_enrichment")

    assert enrich_existing_report_metadata(str(database), existing)
    refreshed_again, candidates, _ = _single_report(database)
    assert refreshed_again["revision"] == "D.01"
    modeless_revision = revision_rows(_graph(database))
    assert all(record in modeless_revision for record in first_revision)
    assert any(item["normalized_value"] == "D.03" and not item["is_selected"] for item in candidates
               if item["field_name"] == "revision")

    ReportRepository(str(database)).update_report_metadata_fields(existing.report_id, {"revision": None})
    assert enrich_existing_report_metadata(str(database), existing)
    manually_cleared, candidates, _ = _single_report(database)
    assert manually_cleared["revision"] is None
    assert all(not item["is_selected"] for item in candidates if item["field_name"] == "revision")
    assert json.loads(manually_cleared["metadata_json"])["manual_overrides"]["revision"]["value"] is None
    assert stages["before"]["report_measurements"] == _graph(database)["report_measurements"]


def test_reviewed_enrichment_preserves_dependencies_but_refreshes_automatic_fields():
    from metroliza.parsing.parse_reports_thread import merge_enriched_metadata_for_persistence

    current = {
        "reference": "CHOSEN", "reference_raw": None,
        "sample_number": "S-7", "sample_number_kind": "explicit_sample_number",
        "revision": "OLD",
        "metadata_json": {
            "metadata_review": {
                "version": 1, "ocr_fields": ["reference", "revision", "sample_number"],
                "accepted_ocr_fields": ["reference", "sample_number"],
            },
            "field_sources": {"reference": "position_cell", "sample_number": "explicit_sample_number"},
            "field_corrections": {"sample_number": {"correction_rule": "chosen"}},
        },
    }
    fresh = make_selection({"reference": "FRESH", "sample_number": "9", "revision": "NEW"}).metadata
    fresh = replace(fresh, sample_number_kind="stats_count", metadata_json={
        **fresh.metadata_json,
        "field_corrections": {"sample_number": {"correction_rule": "fresh"}},
    })
    merged, summary = merge_enriched_metadata_for_persistence(current, fresh)
    assert (merged.reference, merged.reference_raw) == ("CHOSEN", None)
    assert (merged.sample_number, merged.sample_number_kind) == ("S-7", "explicit_sample_number")
    assert merged.revision == "NEW"
    assert merged.metadata_json["sample_number_provenance"] == "explicit_sample_number"
    assert merged.metadata_json["field_corrections"]["sample_number"] == {"correction_rule": "chosen"}
    assert summary["updated_fields"] == ["revision"]
    assert summary["preserved_fields"] == ["reference", "reference_raw", "sample_number", "sample_number_kind"]


@pytest.mark.parametrize("chosen_source,fresh_source", [
    ("explicit_sample_number", "projected_from_stats_count"),
    ("projected_from_stats_count", "comment_derived"),
    ("comment_derived", "projected_from_stats_count"),
])
def test_sample_number_warning_follows_accepted_candidate_in_import_and_enrichment(
    tmp_path, monkeypatch, chosen_source, fresh_source,
):
    from metroliza.parsing.metadata_enrichment_thread import (
        discover_metadata_enrichment_work,
        enrich_existing_report_metadata,
    )

    cases = {
        "explicit_sample_number": (FAKE_OCR_ITEMS + [
            _item("SAMPLE NUMBER", 100, 105, 175, 110), _item("8", 188, 105, 200, 110),
        ], "8", "explicit_sample_number", None),
        "projected_from_stats_count": (
            FAKE_OCR_ITEMS, "12", "stats_count", "sample_number_projected_from_stats_count",
        ),
        "comment_derived": ([
            item for item in FAKE_OCR_ITEMS if item["text"] not in ("STATS COUNT", "12")
        ] + [
            _item("COMMENT", 296.5, 74.2, 345, 80), _item("8", 353, 74.2, 360, 80),
        ], "8", "derived_counter", "sample_number_derived_from_comment"),
    }
    warning_codes = {case[3] for case in cases.values()} - {None}

    def read_ocr(source_type):
        items, *_ = cases[source_type]
        monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap",
                            classmethod(lambda cls, page, box, backend: (items, None)))

    def saved_sample_state():
        metadata, candidates, _ = _single_report(database)
        with closing(sqlite3.connect(database)) as connection:
            warnings = [
                (code, field, severity, text, json.loads(details or "{}"))
                for code, field, severity, text, details in connection.execute(
                    "SELECT code, field_name, severity, message, details_json FROM report_metadata_warnings"
                )
                if code in warning_codes
            ]
        selected = [
            (candidate["normalized_value"], candidate["source_type"])
            for candidate in candidates if candidate["field_name"] == "sample_number" and candidate["is_selected"]
        ]
        return (metadata["sample_number"], metadata["sample_number_kind"],
                json.loads(metadata["metadata_json"])["sample_number_provenance"], selected, warnings)

    source = _source(tmp_path)
    database = tmp_path / "samples.sqlite3"
    review = _review(source, database, metadata_parsing_mode="complete")
    rows = _rows(review)
    row = rows[NAME]
    row.set_user_value("sample_number", "MANUAL")
    read_ocr(chosen_source)
    chosen, = _read(MetadataReviewReader(review), rows, mode=MODE_OCR)
    _, chosen_value, chosen_kind, chosen_code = cases[chosen_source]
    assert chosen.selection.metadata.metadata_json["sample_number_provenance"] == chosen_source
    assert row.accept_ocr_suggestions(("sample_number",)) == ("sample_number",)
    expected_warnings = [
        (warning.code, warning.field_name, warning.severity, warning.message, warning.details)
        for warning in chosen.selection.metadata.warnings if warning.code == chosen_code
    ]
    assert len(expected_warnings) == int(chosen_code is not None)

    read_ocr(fresh_source)
    competing, = _read(MetadataReviewReader(review), rows, mode=MODE_OCR)
    assert competing.selection.metadata.metadata_json["sample_number_provenance"] == fresh_source
    assert cases[fresh_source][3] in {warning.code for warning in competing.selection.metadata.warnings}
    plan = ImportPlan.from_preflight(
        ParseRequest(source_directory=str(source), db_file=str(database), metadata_parsing_mode="complete"),
        review, selected_occurrence_ids=(NAME,), metadata_overrides=build_overrides(rows.values()),
    )
    worker = ParseReportsThread(plan)
    worker.run()
    assert worker.last_parse_result.imported_files == 1
    imported = saved_sample_state()
    work_item, = discover_metadata_enrichment_work(str(database))
    assert enrich_existing_report_metadata(str(database), work_item)
    refreshed = saved_sample_state()
    expected = (chosen_value, chosen_kind, chosen_source, [(chosen_value, chosen_source)], expected_warnings)
    assert (imported, refreshed) == (expected, expected)

    ReportRepository(str(database)).update_report_metadata_fields(work_item.report_id, {"sample_number": None})
    assert saved_sample_state() == (None, "unknown", "manual", [], [])
    assert enrich_existing_report_metadata(str(database), work_item)
    assert saved_sample_state() == (None, "unknown", "manual", [], [])


@pytest.mark.parametrize("typed_count", [6, None])
@pytest.mark.parametrize("fresh_raw_count", [None, "077"])
@pytest.mark.parametrize("has_previous_evidence", [True, False])
def test_complete_enrichment_retains_raw_count_with_manual_integer(
    tmp_path, monkeypatch, typed_count, fresh_raw_count, has_previous_evidence,
):
    from metroliza.parsing import parse_reports_thread as worker_module

    source = _source(tmp_path, names=("noreference.pdf",))
    database = tmp_path / "db.sqlite3"
    plan = replace(_plan(source, database, _review(source, database)), run_background_metadata_enrichment=True)
    complete = ParseReportsThread._complete_requested_enrichment
    read_snapshot = worker_module.report_metadata_row_for_enrichment
    ocr_items = [dict(item, text="004") if item["text"] == "12" else item for item in FAKE_OCR_ITEMS]
    captured = {}

    def read_header(cls, page, bbox, pdf_backend):
        return ocr_items, None

    def edit_after_snapshot(db_file, report_id, *, connection=None):
        row = read_snapshot(db_file, report_id, connection=connection)
        ReportRepository(db_file).update_report_metadata_fields(report_id, {"stats_count_int": 7})
        captured["new_edit"] = _graph(database)
        return row

    def after_light_import(worker, paths, connection):
        complete(worker, paths, connection)
        captured["initial_result"] = worker.last_enrichment_result
        metadata, _, _ = _single_report(database)
        ReportRepository(str(database)).update_report_metadata_fields(
            metadata["report_id"], {"stats_count_int": typed_count},
        )
        if not has_previous_evidence:
            with closing(sqlite3.connect(database)) as old_database, old_database:
                old_database.execute("DELETE FROM report_metadata_candidates WHERE field_name = 'stats_count_raw'")
        captured["before"] = _single_report(database)
        if fresh_raw_count is None:
            ocr_items[:] = [item for item in ocr_items if item["text"] not in {"STATS COUNT", "004"}]
        else:
            ocr_items[:] = [dict(item, text=fresh_raw_count) if item["text"] == "004" else item for item in ocr_items]
        complete(worker, paths, connection)
        captured["updated_result"] = worker.last_enrichment_result
        captured["updated"] = _single_report(database)
        complete(worker, paths, connection)
        captured["repeated_result"] = worker.last_enrichment_result
        captured["repeated"] = _single_report(database)
        monkeypatch.setattr(worker_module, "report_metadata_row_for_enrichment", edit_after_snapshot)
        complete(worker, paths, connection)

    monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(read_header))
    monkeypatch.setattr(ParseReportsThread, "_complete_requested_enrichment", after_light_import)
    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == 1
    assert captured["initial_result"].enriched_files == captured["updated_result"].enriched_files == 1
    assert captured["repeated_result"].enriched_files == 1
    before, before_candidates, _ = captured["before"]
    updated, updated_candidates, _ = captured["updated"]
    assert (before["stats_count_raw"], before["stats_count_int"]) == ("004", typed_count)
    assert (updated["stats_count_raw"], updated["stats_count_int"]) == ("004", typed_count)
    count_fields = {"stats_count_raw", "stats_count_int"}
    original_count_candidates = [row for row in before_candidates if row["field_name"] in count_fields]
    assert any(row["field_name"] == "stats_count_raw" and row["source_type"] != "user_manual"
               and row["is_selected"] and row["raw_value"] == "004"
               for row in original_count_candidates) is has_previous_evidence
    retained_count_candidates = [row for row in updated_candidates if row["field_name"] in count_fields]
    assert all(row in retained_count_candidates for row in original_count_candidates)
    new_candidates = [row for row in retained_count_candidates if row not in original_count_candidates]
    assert {row["raw_value"] for row in new_candidates} == ({fresh_raw_count} if fresh_raw_count else set())
    assert all(row["field_name"] == "stats_count_raw" and not row["is_selected"] for row in new_candidates)
    assert [row for row in captured["repeated"][1] if row["field_name"] in count_fields] == retained_count_candidates
    metadata_json = json.loads(updated["metadata_json"])
    assert metadata_json["field_sources"]["stats_count_raw"] == json.loads(before["metadata_json"])[
        "field_sources"
    ]["stats_count_raw"]
    assert "stats_count_raw" not in metadata_json["manual_overrides"]
    assert worker.last_enrichment_result.failed_files == 1
    assert _graph(database) == captured["new_edit"]


@pytest.mark.parametrize("ocr_agrees_with_filename", [False, True])
def test_complete_enrichment_reconciles_raw_selection_without_losing_history(
    tmp_path, fake_ocr, monkeypatch, ocr_agrees_with_filename,
):
    source = _source(tmp_path)
    database = tmp_path / "db.sqlite3"
    plan = replace(_plan(source, database, _review(source, database)), run_background_metadata_enrichment=True)
    complete = ParseReportsThread._complete_requested_enrichment
    captured = {}

    def after_light_import(worker, paths, connection):
        captured["light"] = _single_report(database)
        complete(worker, paths, connection)
        captured["first"] = _single_report(database)
        ReportRepository(str(database)).update_report_metadata_fields(
            captured["first"][0]["report_id"], {"stats_count_int": 6},
        )
        if ocr_agrees_with_filename:
            def read_agreeing_header(cls, page, bbox, pdf_backend):
                return [dict(item, text="7") if item["text"] == "12" else item for item in FAKE_OCR_ITEMS], None

            monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(read_agreeing_header))
        complete(worker, paths, connection)
        captured["edited"] = _single_report(database)
        complete(worker, paths, connection)

    monkeypatch.setattr(ParseReportsThread, "_complete_requested_enrichment", after_light_import)
    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == 1
    assert worker.last_enrichment_result.enriched_files == 1

    def raw_evidence(snapshot):
        return [row for row in snapshot[1] if row["field_name"] == "stats_count_raw"]

    assert captured["light"][0]["stats_count_raw"] == captured["first"][0]["stats_count_raw"] == "7"
    assert any(row["normalized_value"] == "12" and row["is_selected"] for row in raw_evidence(captured["first"]))
    final = _single_report(database)
    assert (final[0]["stats_count_raw"], final[0]["stats_count_int"]) == ("7", 6)
    metadata_json = json.loads(final[0]["metadata_json"])
    accepted_source = "position_cell" if ocr_agrees_with_filename else "filename_candidate"
    assert metadata_json["field_sources"]["stats_count_raw"] == accepted_source
    assert "stats_count_raw" not in metadata_json["manual_overrides"]
    assert [(row["normalized_value"], row["source_type"]) for row in raw_evidence(final) if row["is_selected"]] == [
        ("7", accepted_source),
    ]
    saved_evidence = [dict(row, is_selected=0) for row in raw_evidence(final)]
    assert all(dict(row, is_selected=0) in saved_evidence for row in raw_evidence(captured["first"]))
    assert raw_evidence(final) == raw_evidence(captured["edited"])


@pytest.mark.parametrize("manual_sample", ["MANUAL-5", None])
def test_complete_enrichment_keeps_manual_sample_classification(tmp_path, fake_ocr, monkeypatch, manual_sample):
    source = _source(tmp_path, names=("noreference.pdf",))
    database = tmp_path / "db.sqlite3"
    plan = replace(_plan(source, database, _review(source, database)), run_background_metadata_enrichment=True)
    complete = ParseReportsThread._complete_requested_enrichment
    captured = {}

    def warning_codes():
        with closing(sqlite3.connect(database)) as connection:
            return {code for (code,) in connection.execute("SELECT code FROM report_metadata_warnings")}

    def after_light_import(worker, paths, connection):
        complete(worker, paths, connection)
        initial, _, _ = _single_report(database)
        captured["initial_provenance"] = json.loads(initial["metadata_json"])["sample_number_provenance"]
        captured["initial_warnings"] = warning_codes()
        ReportRepository(str(database)).update_report_metadata_fields(
            initial["report_id"], {"sample_number": manual_sample},
        )
        complete(worker, paths, connection)

    monkeypatch.setattr(ParseReportsThread, "_complete_requested_enrichment", after_light_import)
    worker = ParseReportsThread(plan)
    worker.run()

    assert worker.last_parse_result.imported_files == worker.last_enrichment_result.enriched_files == 1
    assert captured["initial_provenance"] == "projected_from_stats_count"
    projected_warning = "sample_number_projected_from_stats_count"
    assert projected_warning in captured["initial_warnings"]
    metadata, candidates, _ = _single_report(database)
    assert (metadata["sample_number"], metadata["sample_number_kind"]) == (manual_sample, "unknown")
    assert json.loads(metadata["metadata_json"])["sample_number_provenance"] == "manual"
    assert projected_warning not in warning_codes()
    selected = [row["normalized_value"] for row in candidates if row["field_name"] == "sample_number" and row["is_selected"]]
    assert selected == ([manual_sample] if manual_sample is not None else [])


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


def _t21_original_full_open(parser):
    """Literal pre-T21 full-open ordering, independent of candidate open dispatch."""
    backend = parser._require_pdf_backend()
    cached = parser._cached_embedded_lines_for_open_report()
    with backend.open(str(Path(parser.file_path) / parser.file_name)) as document:
        parser._page_count = parser._resolve_page_count(document)
        if cached is not None:
            if parser._page_count:
                page = document[0]
                parser._first_page_width, parser._first_page_height = parser._page_size(page)
                (parser._first_page_header_items,
                 parser._header_extraction_diagnostics) = parser._extract_first_page_header_items(
                     page, backend, metadata_parsing_mode=parser.metadata_parsing_mode)
            parser.raw_text.extend(cached)
            return
        count = 0
        for page in document:
            count += 1
            if count == 1:
                parser._first_page_width, parser._first_page_height = parser._page_size(page)
            text = page.get_text().splitlines()
            if count == 1:
                (parser._first_page_header_items,
                 parser._header_extraction_diagnostics) = parser._extract_first_page_header_items(
                     page, backend, metadata_parsing_mode=parser.metadata_parsing_mode)
            parser.raw_text.extend(text)
        if parser._page_count is None:
            parser._page_count = count


@pytest.mark.parametrize("mode", [MODE_FAST, MODE_OCR])
@pytest.mark.parametrize("cached", [False, True])
def test_metadata_open_matches_original_complete_selection_and_geometry(tmp_path, fake_ocr, mode, cached):
    from metroliza.parsing.source_inspection import SourceInspectionContext

    path = _source(tmp_path) / NAME
    parsers = [CMMReportParser(str(path), "unused.sqlite", metadata_parsing_mode=mode)
               for _ in range(2)]
    if cached:
        for parser in parsers:
            parser.source_inspection_context = SourceInspectionContext.from_path(path)
            parser.source_inspection_context.get_pdf_text(max_chars=1000000)
    _t21_original_full_open(parsers[0])
    getattr(parsers[1], "open_metadata_report", parsers[1].open_report)()
    expected, actual = [parser.extract_metadata() for parser in parsers]
    assert actual == expected
    assert actual.metadata.reference == ("ABCDE12345" if mode == MODE_FAST else "OCR-REF-9")
    assert actual.metadata.report_date == "2024-05-06"
    assert parsers[0]._page_count == parsers[1]._page_count == 1
    assert parsers[0]._first_page_header_items == parsers[1]._first_page_header_items
    assert parsers[0]._header_extraction_diagnostics == parsers[1]._header_extraction_diagnostics
    assert parsers[0].raw_text  # the oracle is a successful full open


def test_metadata_full_open_retains_later_page_error_and_close(tmp_path, monkeypatch):
    from types import SimpleNamespace

    events = []

    class Page:
        rect = SimpleNamespace(width=600, height=800)

        def __init__(self, broken=False):
            self.broken = broken

        def get_text(self):
            events.append("text")
            if self.broken:
                raise ValueError("later page failed")
            return "first line"

    class Document:
        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, *args):
            events.append("close")

        def __len__(self):
            return 2

        def __iter__(self):
            return iter([Page(), Page(True)])

    parser = CMMReportParser(str(tmp_path / NAME), "unused.sqlite")
    monkeypatch.setattr(parser, "_require_pdf_backend", lambda: SimpleNamespace(open=lambda path: Document()))
    monkeypatch.setattr(parser, "_extract_first_page_header_items", lambda *a, **kw: ([], {}))
    monkeypatch.setattr(parser, "log_and_exit", lambda error: events.append((type(error).__name__, str(error))))
    getattr(parser, "open_metadata_report", parser.open_report)()
    assert events == ["enter", "text", "text", "close", ("ValueError", "later page failed")]
    assert parser.raw_text == ["first line"]


def test_native_cached_metadata_activation_keeps_default_full_open(tmp_path, monkeypatch):
    from metroliza.parsing import report_parser_factory as factory

    source = _source(tmp_path)
    review = _review(source, tmp_path / "unused.sqlite")
    factory.reset_probe_cache()  # successful probe must populate canonical all-page text
    observed = []
    original = CMMReportParser._open_report

    def open_report(parser, *, metadata_only=False):
        original(parser, metadata_only=metadata_only)
        observed.append((metadata_only, list(parser.raw_text)))

    monkeypatch.setattr(CMMReportParser, "_open_report", open_report)
    readings = _read(MetadataReviewReader(review), _rows(review))
    assert readings[0].status == "ok" and readings[0].selection.metadata.reference == "ABCDE12345"
    assert observed == [(True, [])]
    parser = CMMReportParser(str(source / NAME), "unused.sqlite", metadata_parsing_mode=MODE_FAST)
    parser.open_report()
    assert observed[-1][0] is False and observed[-1][1]


@pytest.mark.parametrize("customization", ["factory", "instance_open", "class_open", "class_extract", "cache_hook"])
def test_custom_metadata_dispatch_keeps_public_full_open(tmp_path, monkeypatch, customization):
    from metroliza.parsing import metadata_review as review_module
    from metroliza.parsing import report_parser_factory as factory

    source = _source(tmp_path)
    review = _review(source, tmp_path / "unused.sqlite")
    calls = []
    original_open = CMMReportParser.open_report
    original_extract = CMMReportParser.extract_metadata

    def full_open(parser):
        calls.append("open")
        return original_open(parser)

    def extract(parser):
        calls.append("extract")
        return original_extract(parser)

    def custom_factory(*args, **kwargs):
        parser = factory.get_parser(*args, **kwargs)
        if customization == "instance_open":
            parser.open_report = lambda: full_open(parser)
        elif customization == "cache_hook":
            parser._cached_embedded_lines_for_open_report = lambda: None
        return parser

    def metadata_open(parser):
        pytest.fail("custom parser dispatch must use full open")

    monkeypatch.setattr(CMMReportParser, "open_metadata_report", metadata_open)
    if customization == "class_open":
        monkeypatch.setattr(CMMReportParser, "open_report", full_open)
    elif customization == "class_extract":
        monkeypatch.setattr(CMMReportParser, "extract_metadata", extract)
    item = review.ready_files[0]
    parser_factory = custom_factory if customization in {"factory", "instance_open", "cache_hook"} else None
    reading = review_module.read_metadata_one(item, source / NAME, MODE_FAST,
                                              database_path=str(tmp_path / "unused.sqlite"),
                                              parser_factory=parser_factory)
    assert reading.status == "ok" and reading.selection.metadata.reference == "ABCDE12345"
    if customization in {"instance_open", "class_open", "class_extract"}:
        assert calls


def test_metadata_native_guards_do_not_observe_custom_dictionary_membership(tmp_path):
    from metroliza.parsing import metadata_review as review_module

    class TrapDict(dict):
        def __contains__(self, key):
            pytest.fail("native guard must not invoke custom dictionary membership")

    parser = CMMReportParser(str(tmp_path / NAME), "unused.sqlite")
    parser.__dict__ = TrapDict(parser.__dict__)
    assert not review_module._metadata_open_supported(parser, None)


@pytest.mark.parametrize("cache_result", [None, "custom_text"])
def test_metadata_cached_text_reader_preserves_single_getter_and_raw_callbacks(tmp_path, cache_result):
    from metroliza.parsing.source_inspection import SourceInspectionContext

    events = []

    class Text(str):
        def splitlines(self):
            events.append("split")
            return ["custom cached line"]

    path = _source(tmp_path) / NAME
    parser = CMMReportParser(str(path), "unused.sqlite", metadata_parsing_mode=MODE_FAST)
    inspection = SourceInspectionContext.from_path(path)

    def get_cached(**kwargs):
        events.append("get")
        return None if cache_result is None else (Text("custom"),)

    object.__setattr__(inspection, "get_cached_pdf_page_texts", get_cached)
    parser.source_inspection_context = inspection
    parser.open_metadata_report()
    assert events == (["get"] if cache_result is None else ["get", "split"])
    assert parser.raw_text
    if cache_result is not None:
        assert parser.raw_text == ["custom cached line"]


@pytest.mark.parametrize("stateful", [False, True])
def test_native_raw_extract_key_keeps_single_lookup_and_success(tmp_path, monkeypatch, stateful):
    from metroliza.parsing import metadata_review, report_parser_factory

    source = _source(tmp_path)
    review = _review(source, tmp_path / "unused.sqlite")
    parser = CMMReportParser(str(source / NAME), "unused.sqlite", metadata_parsing_mode=MODE_FAST)
    events = []
    lookup_baseline = []
    baseline_value = []
    events_before_lookup = []

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            result = stateful and bool(events)
            events.append((other, result))
            return result

    object.__getattribute__(parser, "__dict__")[Key("extract_metadata")] = None

    def invoke(*args, source_inspection=None, **kwargs):
        parser.source_inspection_context = source_inspection
        return parser

    original_open_report = CMMReportParser.open_report

    def calibrate_one_attribute_lookup(self):
        result = original_open_report(self)
        prefix = list(events)
        # A second target lookup before this point would already violate the
        # one-lookup contract. Other key probes are retained as the state from
        # which the baseline lookup and actual lookup both start.
        assert not any(other == "extract_metadata" for other, _ in prefix)
        events_before_lookup.extend(prefix)
        try:
            baseline_value.append(object.__getattribute__(self, "extract_metadata"))
            lookup_baseline.extend(events[len(prefix):])
        finally:
            events[:] = prefix
        return result

    monkeypatch.setattr(report_parser_factory, "invoke_parser_factory", invoke)
    monkeypatch.setattr(CMMReportParser, "open_report", calibrate_one_attribute_lookup)
    reading = metadata_review.read_metadata_one(review.ready_files[0], source / NAME, MODE_FAST,
                                                database_path="unused.sqlite")
    assert events == events_before_lookup + lookup_baseline
    direct_result = baseline_value[0]
    if direct_result is None:
        assert reading.status == metadata_review.ROW_FAILED
    else:
        assert callable(direct_result)
        assert reading.status == "ok"
        assert reading.selection.metadata.reference == "ABCDE12345"
