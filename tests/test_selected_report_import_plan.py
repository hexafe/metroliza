from contextlib import closing
from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import sqlite3
from threading import get_ident
from types import SimpleNamespace
import zipfile

import pytest

from metroliza.parsing import report_parser_factory
from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.parse_reports_thread import ParseReportsThread, parse_new_reports
from metroliza.parsing.source_inspection import SourceInspectionContext
from metroliza.parsing.preflight import (
    ImportPlan,
    ParsePreflightService,
    ParsePreflightStatus,
    SelectedReportIdentity,
    validate_import_plan,
)
from metroliza.shared.parse_contracts import ParseRequest


FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"


def test_one_to_one_rename_counts_one_changed_slot_and_writes_nothing(tmp_path):
    source = tmp_path / "reports"
    report, = _write_unique_reports(source, 1)
    database = tmp_path / "rename.db"
    plan = ImportPlan.all_ready(_request(source, database), _preflight(source, database))
    report.rename(source / "renamed.pdf")
    thread = ParseReportsThread(plan)
    thread.run()
    assert not database.exists()
    assert thread.last_parse_result.total_files == 1
    assert thread.last_parse_result.preflight_changed_files == 1


def test_missing_selected_remains_changed_after_complete_discovery_cancellation(tmp_path, monkeypatch):
    source = tmp_path / "reports"
    reports = _write_unique_reports(source, 2)
    database = tmp_path / "cancel-missing.db"
    plan = ImportPlan.all_ready(_request(source, database), _preflight(source, database))
    reports[1].unlink()
    thread = ParseReportsThread(plan)
    discover = thread.get_list_of_reports

    def discover_then_cancel():
        paths = discover()
        thread.parsing_canceled = True
        return paths

    monkeypatch.setattr(thread, "get_list_of_reports", discover_then_cancel)
    thread.run()
    assert not database.exists()
    assert thread.last_parse_result.preflight_changed_files == 1
    assert thread.last_parse_result.cancelled_files == 1


def _write_unique_reports(source: Path, count: int) -> list[Path]:
    source.mkdir()
    fixture_bytes = FIXTURE.read_bytes()
    reports = []
    for index in range(count):
        report = source / f"report-{index}.pdf"
        report.write_bytes(fixture_bytes + f"\n% synthetic-report-{index}\n".encode())
        reports.append(report)
    return reports


def _request(source: Path, database: Path) -> ParseRequest:
    return ParseRequest(
        source_directory=str(source),
        db_file=str(database),
        metadata_parsing_mode="light",
    )


def _preflight(source: Path, database: Path):
    return ParsePreflightService().scan_source(
        source_path=source,
        database_path=database,
        metadata_parsing_mode="light",
    )


def _stored_source_hashes(database: Path) -> set[str]:
    with closing(sqlite3.connect(database)) as connection:
        return {
            str(row[0])
            for row in connection.execute("SELECT sha256 FROM source_files").fetchall()
        }


def _track_completed_import_plan_filter(monkeypatch):
    state = {"completed": False}
    original_filter = ParseReportsThread._filter_reports_for_import_plan

    def tracked_filter(thread, report_paths, plan):
        result = original_filter(thread, report_paths, plan)
        state["completed"] = True
        return result

    monkeypatch.setattr(
        ParseReportsThread,
        "_filter_reports_for_import_plan",
        tracked_filter,
    )
    return state


def _assert_selected_result_counts(
    result,
    *,
    parsed,
    selected,
    imported,
    already_present,
    changed,
    failed,
    skipped,
    cancelled,
    excluded,
):
    assert result.parsed_files == parsed
    assert result.selected_files == selected
    assert result.imported_files == imported
    assert result.already_present_files == already_present
    assert result.preflight_changed_files == changed
    assert result.failed_files == failed
    assert result.skipped_files == skipped
    assert result.cancelled_files == cancelled
    assert result.intentionally_excluded_files == excluded


def _track_database_opens(monkeypatch):
    database_opens = []

    def unexpected_database_open(*args, **kwargs):
        database_opens.append((args, kwargs))
        raise AssertionError("filter-stage cancellation must not open SQLite")

    monkeypatch.setattr(
        "metroliza.parsing.parse_reports_thread.sqlite_connection_scope",
        unexpected_database_open,
    )
    return database_opens


def test_selected_two_of_five_persists_exactly_two_and_reports_exclusions(tmp_path):
    source = tmp_path / "reports"
    reports = _write_unique_reports(source, 5)
    database = tmp_path / "selected.db"
    preflight = _preflight(source, database)
    assert all(item.status is ParsePreflightStatus.READY for item in preflight.files)
    selected_names = {reports[1].name, reports[3].name}
    plan = ImportPlan.from_preflight(
        _request(source, database),
        preflight,
        selected_occurrence_ids=selected_names,
    )

    thread = ParseReportsThread(plan)
    thread.run()

    expected_hashes = {
        hashlib.sha256(report.read_bytes()).hexdigest()
        for report in reports
        if report.name in selected_names
    }
    assert _stored_source_hashes(database) == expected_hashes
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=2,
        selected=2,
        imported=2,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=3,
    )


def test_empty_plan_is_immutable_and_performs_zero_writes(tmp_path):
    source = tmp_path / "reports"
    _write_unique_reports(source, 2)
    database = tmp_path / "empty.db"
    preflight = _preflight(source, database)
    plan = ImportPlan.from_preflight(
        _request(source, database),
        preflight,
        selected_occurrence_ids=(),
    )

    with pytest.raises(FrozenInstanceError):
        plan.database_path = "other.db"

    thread = ParseReportsThread(plan)
    thread.run()

    assert not database.exists()
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=0,
        selected=0,
        imported=0,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=2,
    )


def test_explicit_all_ready_adapter_preserves_current_behavior(tmp_path):
    source = tmp_path / "reports"
    _write_unique_reports(source, 3)
    database = tmp_path / "all-ready.db"
    request = _request(source, database)
    preflight = _preflight(source, database)

    thread = ParseReportsThread.for_all_ready(request, preflight)
    thread.run()

    assert len(_stored_source_hashes(database)) == 3
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=3,
        selected=3,
        imported=3,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_core_executor_rejects_a_missing_plan_before_database_write(tmp_path):
    source = tmp_path / "reports"
    _write_unique_reports(source, 1)
    database = tmp_path / "must-not-exist.db"
    thread = ParseReportsThread(_request(source, database))
    errors = []
    thread.error_occurred.connect(errors.append)

    thread.run()

    assert not database.exists()
    assert errors
    assert "Import plan must be provided" in errors[0]


def test_executor_rejects_context_drift_from_the_immutable_plan(tmp_path):
    source = tmp_path / "reports"
    _write_unique_reports(source, 1)
    reviewed_database = tmp_path / "reviewed.db"
    other_database = tmp_path / "other.db"
    preflight = _preflight(source, reviewed_database)
    thread = ParseReportsThread(
        ImportPlan.all_ready(_request(source, reviewed_database), preflight)
    )
    thread.db_file = str(other_database)
    errors = []
    thread.error_occurred.connect(errors.append)

    thread.run()

    assert not reviewed_database.exists()
    assert not other_database.exists()
    assert "executor inputs do not match" in errors[0]


@pytest.mark.parametrize("drift", ("source", "database", "metadata"))
def test_plan_rejects_request_context_not_reviewed_by_preflight(tmp_path, drift):
    source = tmp_path / "reports"
    _write_unique_reports(source, 1)
    database = tmp_path / "reviewed.db"
    preflight = _preflight(source, database)
    request = _request(source, database)
    if drift == "source":
        request = replace(request, source_directory=str(tmp_path / "other-reports"))
    elif drift == "database":
        request = replace(request, db_file=str(tmp_path / "other.db"))
    else:
        request = replace(request, metadata_parsing_mode="complete")

    with pytest.raises(ValueError, match="do not match the reviewed preflight"):
        ImportPlan.all_ready(request, preflight)

    assert not database.exists()


def test_non_ready_missing_or_tampered_identity_cannot_enter_a_valid_plan(tmp_path):
    source = tmp_path / "reports"
    reports = _write_unique_reports(source, 2)
    reports[1].write_bytes(reports[0].read_bytes())
    database = tmp_path / "invalid.db"
    preflight = _preflight(source, database)
    duplicate = preflight.files_with_status(ParsePreflightStatus.DUPLICATE)[0]

    with pytest.raises(ValueError, match="not READY"):
        ImportPlan.from_preflight(
            _request(source, database),
            preflight,
            selected_occurrence_ids=(duplicate.stable_occurrence_id,),
        )
    with pytest.raises(ValueError, match="missing from preflight"):
        ImportPlan.from_preflight(
            _request(source, database),
            preflight,
            selected_occurrence_ids=("missing.pdf",),
        )

    ready = preflight.ready_files[0]
    valid = ImportPlan.from_preflight(
        _request(source, database),
        preflight,
        selected_occurrence_ids=(ready.stable_occurrence_id,),
    )
    tampered = replace(
        valid,
        selected_reports=(
            replace(valid.selected_reports[0], fingerprint="sha256:tampered"),
        ),
    )
    with pytest.raises(ValueError, match="exact READY approval"):
        validate_import_plan(tampered)


@pytest.mark.parametrize("change", ("changed", "deleted"))
def test_selected_file_changed_or_deleted_after_review_is_rejected(
    tmp_path,
    monkeypatch,
    change,
):
    source = tmp_path / "reports"
    report = _write_unique_reports(source, 1)[0]
    database = tmp_path / f"{change}.db"
    preflight = _preflight(source, database)
    plan = ImportPlan.all_ready(_request(source, database), preflight)
    if change == "changed":
        report.write_bytes(b"changed after review")
    else:
        report.unlink()
    original_filter = ParseReportsThread._filter_reports_for_import_plan
    filter_results = []

    def capture_filter_result(thread, report_paths, import_plan):
        result = original_filter(thread, report_paths, import_plan)
        filter_results.append(result)
        return result

    monkeypatch.setattr(
        ParseReportsThread,
        "_filter_reports_for_import_plan",
        capture_filter_result,
    )

    thread = ParseReportsThread(plan)
    thread.run()

    assert not database.exists()
    assert filter_results[0].selected_changed_files == 1
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=0,
        selected=1,
        imported=0,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_filter_stage_cancellation_keeps_changed_selected_report_out_of_cancelled(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "reports"
    reports = _write_unique_reports(source, 3)
    database = tmp_path / "filter-cancel-changed.db"
    plan = ImportPlan.all_ready(_request(source, database), _preflight(source, database))
    reports[1].write_bytes(b"changed after review")
    thread = ParseReportsThread(plan)
    original_from_path = SourceInspectionContext.from_path
    original_filter = ParseReportsThread._filter_reports_for_import_plan
    inspected_reports = []
    filter_results = []

    def inspect_and_cancel_on_changed_report(cls, source_path, *, source_format=None):
        inspection = original_from_path(source_path, source_format=source_format)
        inspected_reports.append(Path(source_path).name)
        if Path(source_path) == reports[1]:
            assert inspection.sha256 is not None
            thread.stop_parsing()
        return inspection

    def capture_filter_result(thread, report_paths, import_plan):
        result = original_filter(thread, report_paths, import_plan)
        filter_results.append(result)
        return result

    monkeypatch.setattr(
        SourceInspectionContext,
        "from_path",
        classmethod(inspect_and_cancel_on_changed_report),
    )
    monkeypatch.setattr(
        ParseReportsThread,
        "_filter_reports_for_import_plan",
        capture_filter_result,
    )
    database_opens = _track_database_opens(monkeypatch)

    thread.run()

    assert inspected_reports == [reports[0].name, reports[1].name]
    assert filter_results[0].selected_changed_files == 1
    assert database_opens == []
    assert not database.exists()
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=0,
        selected=3,
        imported=0,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=2,
        excluded=0,
    )


def test_filter_stage_cancellation_before_classification_cancels_every_selected_report(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "reports"
    _write_unique_reports(source, 3)
    database = tmp_path / "filter-cancel-before-classification.db"
    plan = ImportPlan.all_ready(_request(source, database), _preflight(source, database))
    thread = ParseReportsThread(plan)
    original_filter = ParseReportsThread._filter_reports_for_import_plan
    inspection_calls = []

    def cancel_before_filtering(thread, report_paths, import_plan):
        thread.stop_parsing()
        result = original_filter(thread, report_paths, import_plan)
        filter_results.append(result)
        return result

    original_from_path = SourceInspectionContext.from_path
    filter_results = []

    def track_inspection(cls, source_path, *, source_format=None):
        inspection_calls.append(Path(source_path))
        return original_from_path(source_path, source_format=source_format)

    monkeypatch.setattr(
        ParseReportsThread,
        "_filter_reports_for_import_plan",
        cancel_before_filtering,
    )
    monkeypatch.setattr(
        SourceInspectionContext,
        "from_path",
        classmethod(track_inspection),
    )
    database_opens = _track_database_opens(monkeypatch)

    thread.run()

    assert inspection_calls == []
    assert filter_results[0].selected_changed_files == 0
    assert database_opens == []
    assert not database.exists()
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=0,
        selected=3,
        imported=0,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=3,
        excluded=0,
    )


def test_new_unreviewed_file_does_not_reduce_selected_cancellation_count(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "reports"
    _write_unique_reports(source, 2)
    database = tmp_path / "filter-cancel-new-file.db"
    plan = ImportPlan.all_ready(_request(source, database), _preflight(source, database))
    new_report = source / "000-new-unreviewed.pdf"
    new_report.write_bytes(FIXTURE.read_bytes() + b"\n% new-unreviewed\n")
    thread = ParseReportsThread(plan)
    original_filter = ParseReportsThread._filter_reports_for_import_plan
    original_occurrence_id = ParseReportsThread._occurrence_id_for_report
    state = {"filtering": False}

    def track_filtering(thread, report_paths, import_plan):
        state["filtering"] = True
        try:
            result = original_filter(thread, report_paths, import_plan)
            state["result"] = result
            return result
        finally:
            state["filtering"] = False

    def cancel_while_classifying_new_report(thread, report):
        occurrence_id = original_occurrence_id(thread, report)
        if state["filtering"] and Path(report) == new_report:
            thread.stop_parsing()
        return occurrence_id

    monkeypatch.setattr(
        ParseReportsThread,
        "_filter_reports_for_import_plan",
        track_filtering,
    )
    monkeypatch.setattr(
        ParseReportsThread,
        "_occurrence_id_for_report",
        cancel_while_classifying_new_report,
    )
    database_opens = _track_database_opens(monkeypatch)

    thread.run()

    assert state["result"].selected_changed_files == 0
    assert database_opens == []
    assert not database.exists()
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=0,
        selected=2,
        imported=0,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=2,
        excluded=0,
    )


def test_new_file_is_rejected_and_unselected_ready_is_an_intentional_exclusion(tmp_path):
    source = tmp_path / "reports"
    reports = _write_unique_reports(source, 2)
    database = tmp_path / "new-and-excluded.db"
    preflight = _preflight(source, database)
    plan = ImportPlan.from_preflight(
        _request(source, database),
        preflight,
        selected_occurrence_ids=(reports[0].name,),
    )
    reports[1].write_bytes(b"changed but deliberately unselected")
    fixture_bytes = FIXTURE.read_bytes()
    (source / "new-report.pdf").write_bytes(fixture_bytes + b"\n% new-after-review\n")

    thread = ParseReportsThread(plan)
    thread.run()

    assert len(_stored_source_hashes(database)) == 1
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=1,
        selected=1,
        imported=1,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=1,
    )


@pytest.mark.parametrize("drift", ("parser", "generation"))
def test_parser_identity_or_registry_generation_drift_rejects_selected_item(
    tmp_path,
    monkeypatch,
    drift,
):
    source = tmp_path / "reports"
    _write_unique_reports(source, 1)
    database = tmp_path / "parser-drift.db"
    preflight = _preflight(source, database)
    approved = preflight.ready_files[0]
    plan = ImportPlan.all_ready(_request(source, database), preflight)
    monkeypatch.setattr(
        report_parser_factory,
        "resolve_parser_with_diagnostics",
        lambda *_args, **_kwargs: SimpleNamespace(
            selected=SimpleNamespace(
                plugin_id=(
                    f"{approved.parser_id}-changed"
                    if drift == "parser"
                    else approved.parser_id
                )
            ),
            registry_generation_id=(
                approved.registry_generation_id + 1
                if drift == "generation"
                else approved.registry_generation_id
            ),
        ),
    )

    thread = ParseReportsThread(plan)
    thread.run()

    assert not database.exists()
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=0,
        selected=1,
        imported=0,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_destination_becoming_duplicate_before_import_remains_safe(tmp_path):
    source = tmp_path / "reports"
    _write_unique_reports(source, 1)
    database = tmp_path / "duplicate-race.db"
    request = _request(source, database)
    preflight = _preflight(source, database)
    plan = ImportPlan.all_ready(request, preflight)
    first_import = ParseReportsThread(plan)
    first_import.run()
    source_hashes_after_first_import = _stored_source_hashes(database)

    duplicate_recheck = ParseReportsThread(plan)
    duplicate_recheck.run()

    assert _stored_source_hashes(database) == source_hashes_after_first_import
    _assert_selected_result_counts(
        duplicate_recheck.last_parse_result,
        parsed=1,
        selected=1,
        imported=0,
        already_present=1,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_sequential_source_drift_after_filter_rejects_only_late_report(
    tmp_path,
    monkeypatch,
):
    reports = _write_unique_reports(tmp_path / "reports", 2)
    database = tmp_path / "sequential-source-drift.db"
    plan = ImportPlan.all_ready(
        _request(reports[0].parent, database), _preflight(reports[0].parent, database)
    )
    filter_state = _track_completed_import_plan_filter(monkeypatch)
    original_persist = CMMReportParser.open_database_and_check_filename
    report_a_hash = hashlib.sha256(reports[0].read_bytes()).hexdigest()

    def persist_a_then_change_b(parser):
        result = original_persist(parser)
        if parser.file_name == reports[0].name:
            assert filter_state["completed"]
            reports[1].write_bytes(reports[1].read_bytes() + b"\n% changed-after-a\n")
        return result

    monkeypatch.delenv("METROLIZA_PARSE_TWO_STAGE_PIPELINE", raising=False)
    monkeypatch.setattr(
        CMMReportParser,
        "open_database_and_check_filename",
        persist_a_then_change_b,
    )

    thread = ParseReportsThread(plan)
    thread.run()

    assert _stored_source_hashes(database) == {report_a_hash}
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=1,
        selected=2,
        imported=1,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


@pytest.mark.parametrize("drift", ("parser", "generation"))
def test_sequential_parser_approval_drift_after_filter_is_changed_not_failed(
    tmp_path,
    monkeypatch,
    drift,
):
    reports = _write_unique_reports(tmp_path / "reports", 2)
    database = tmp_path / f"sequential-{drift}-drift.db"
    plan = ImportPlan.all_ready(
        _request(reports[0].parent, database), _preflight(reports[0].parent, database)
    )
    filter_state = _track_completed_import_plan_filter(monkeypatch)
    original_resolver = report_parser_factory._resolve_parser_with_registration
    original_persist = CMMReportParser.open_database_and_check_filename
    drift_state = {"active": False}
    report_a_hash = hashlib.sha256(reports[0].read_bytes()).hexdigest()

    def drifting_resolver(*args, **kwargs):
        diagnostics, registration = original_resolver(*args, **kwargs)
        if not drift_state["active"]:
            return diagnostics, registration
        if drift == "parser":
            diagnostics = replace(
                diagnostics,
                selected=replace(diagnostics.selected, plugin_id="drifted-parser"),
            )
        else:
            diagnostics = replace(
                diagnostics,
                registry_generation_id=diagnostics.registry_generation_id + 1,
            )
        return diagnostics, registration

    def persist_a_then_enable_drift(parser):
        result = original_persist(parser)
        if parser.file_name == reports[0].name:
            assert filter_state["completed"]
            drift_state["active"] = True
        return result

    monkeypatch.delenv("METROLIZA_PARSE_TWO_STAGE_PIPELINE", raising=False)
    monkeypatch.setattr(
        report_parser_factory,
        "_resolve_parser_with_registration",
        drifting_resolver,
    )
    monkeypatch.setattr(
        CMMReportParser,
        "open_database_and_check_filename",
        persist_a_then_enable_drift,
    )

    thread = ParseReportsThread(plan)
    thread.run()

    assert _stored_source_hashes(database) == {report_a_hash}
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=1,
        selected=2,
        imported=1,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_get_parser_validates_the_single_resolution_used_for_construction(
    tmp_path,
    monkeypatch,
):
    report = tmp_path / "single-resolution.pdf"
    report.write_bytes(b"synthetic")
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")
    calls = []

    class ApprovedParser:
        def __init__(self, file_path, database, connection=None):
            self.file_path = file_path
            self.database = database
            self.connection = connection

    registration = SimpleNamespace(plugin_id="approved", parser_cls=ApprovedParser)
    diagnostics = SimpleNamespace(
        selected=SimpleNamespace(plugin_id="approved"),
        registry_generation_id=17,
        source_inspection=inspection,
    )

    def resolve_once(*args, **kwargs):
        calls.append((args, kwargs))
        return diagnostics, registration

    monkeypatch.setattr(
        report_parser_factory,
        "_resolve_parser_with_registration",
        resolve_once,
    )

    parser = report_parser_factory.get_parser(
        report,
        database=":memory:",
        source_inspection=inspection,
        expected_plugin_id="approved",
        expected_registry_generation_id=17,
    )

    assert len(calls) == 1
    assert type(parser) is ApprovedParser
    assert parser.source_inspection_context is inspection
    assert parser.parser_resolution_evidence.plugin_id == "approved"
    assert parser.parser_resolution_evidence.registry_generation_id == 17
    assert parser.parser_resolution_evidence.registration is registration


def test_get_parser_rejects_identity_drift_from_the_same_resolution(
    tmp_path,
    monkeypatch,
):
    report = tmp_path / "identity-drift.pdf"
    report.write_bytes(b"synthetic")
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")

    class DriftedParser:
        def __init__(self, file_path, database, connection=None):
            pytest.fail("approval drift must reject before parser construction")

    registration = SimpleNamespace(plugin_id="drifted", parser_cls=DriftedParser)
    diagnostics = SimpleNamespace(
        selected=SimpleNamespace(plugin_id="drifted"),
        registry_generation_id=23,
        source_inspection=inspection,
    )
    monkeypatch.setattr(
        report_parser_factory,
        "_resolve_parser_with_registration",
        lambda *_args, **_kwargs: (diagnostics, registration),
    )

    with pytest.raises(report_parser_factory.ParserApprovalMismatchError):
        report_parser_factory.get_parser(
            report,
            database=":memory:",
            source_inspection=inspection,
            expected_plugin_id="approved",
            expected_registry_generation_id=23,
        )


def test_get_parser_translates_late_ambiguity_with_exact_approval_evidence(
    tmp_path,
    monkeypatch,
):
    report = tmp_path / "late-ambiguity.pdf"
    report.write_bytes(b"synthetic")
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")
    diagnostics = SimpleNamespace(
        source_path=str(report),
        selected=None,
        registry_generation_id=31,
        source_inspection=inspection,
    )
    ambiguity = report_parser_factory.ParserAmbiguityError(
        diagnostics,
        ("approved", "new-parser"),
    )
    resolver_calls = []

    def raise_ambiguity(*args, **kwargs):
        resolver_calls.append((args, kwargs))
        raise ambiguity

    monkeypatch.setattr(
        report_parser_factory,
        "_resolve_parser_with_registration",
        raise_ambiguity,
    )
    monkeypatch.setattr(
        report_parser_factory.inspect,
        "signature",
        lambda *_args, **_kwargs: pytest.fail(
            "parser construction must not be reached after late ambiguity"
        ),
    )

    with pytest.raises(report_parser_factory.ParserApprovalMismatchError) as exc_info:
        report_parser_factory.get_parser(
            report,
            database=":memory:",
            source_inspection=inspection,
            expected_plugin_id="approved",
            expected_registry_generation_id=31,
        )

    mismatch = exc_info.value
    assert resolver_calls == [
        ((str(report),), {"source_inspection": inspection})
    ]
    assert mismatch.__cause__ is ambiguity
    assert mismatch.diagnostics is diagnostics
    assert mismatch.expected_plugin_id == "approved"
    assert mismatch.expected_registry_generation_id == 31
    assert mismatch.resolved_plugin_id is None
    assert mismatch.resolved_registry_generation_id == 31


def test_get_parser_without_expected_approval_preserves_ambiguity(
    tmp_path,
    monkeypatch,
):
    report = tmp_path / "first-time-ambiguity.pdf"
    report.write_bytes(b"synthetic")
    inspection = SourceInspectionContext.from_path(report, source_format="pdf")
    diagnostics = SimpleNamespace(
        source_path=str(report),
        selected=None,
        registry_generation_id=37,
        source_inspection=inspection,
    )
    ambiguity = report_parser_factory.ParserAmbiguityError(
        diagnostics,
        ("parser-a", "parser-b"),
    )
    resolver_calls = 0

    def raise_ambiguity(*_args, **_kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        raise ambiguity

    monkeypatch.setattr(
        report_parser_factory,
        "_resolve_parser_with_registration",
        raise_ambiguity,
    )

    with pytest.raises(report_parser_factory.ParserAmbiguityError) as exc_info:
        report_parser_factory.get_parser(
            report,
            database=":memory:",
            source_inspection=inspection,
        )

    assert resolver_calls == 1
    assert exc_info.value is ambiguity
    assert exc_info.value.diagnostics is diagnostics


def test_sequential_late_ambiguity_is_changed_not_failed(
    tmp_path,
    monkeypatch,
):
    reports = _write_unique_reports(tmp_path / "reports", 2)
    database = tmp_path / "sequential-late-ambiguity.db"
    plan = ImportPlan.all_ready(
        _request(reports[0].parent, database), _preflight(reports[0].parent, database)
    )
    filter_state = _track_completed_import_plan_filter(monkeypatch)
    original_resolver = report_parser_factory._resolve_parser_with_registration
    original_persist = CMMReportParser.open_database_and_check_filename
    state = {"report_a_persisted": False}
    report_a_hash = hashlib.sha256(reports[0].read_bytes()).hexdigest()

    def late_ambiguity_resolver(file_path, **kwargs):
        diagnostics, registration = original_resolver(file_path, **kwargs)
        if Path(file_path) == reports[1] and filter_state["completed"]:
            assert state["report_a_persisted"]
            ambiguous_diagnostics = replace(
                diagnostics,
                selected=None,
                rejected_reason="ambiguous_parser_match",
                ambiguous_plugin_ids=("cmm", "new-parser"),
            )
            raise report_parser_factory.ParserAmbiguityError(
                ambiguous_diagnostics,
                ambiguous_diagnostics.ambiguous_plugin_ids,
            )
        return diagnostics, registration

    def persist_a(parser):
        result = original_persist(parser)
        if parser.file_name == reports[0].name:
            state["report_a_persisted"] = True
        return result

    monkeypatch.delenv("METROLIZA_PARSE_TWO_STAGE_PIPELINE", raising=False)
    monkeypatch.setattr(
        report_parser_factory,
        "_resolve_parser_with_registration",
        late_ambiguity_resolver,
    )
    monkeypatch.setattr(
        CMMReportParser,
        "open_database_and_check_filename",
        persist_a,
    )

    thread = ParseReportsThread(plan)
    thread.run()

    assert state["report_a_persisted"]
    assert _stored_source_hashes(database) == {report_a_hash}
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=1,
        selected=2,
        imported=1,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_two_stage_late_ambiguity_is_changed_not_failed(
    tmp_path,
    monkeypatch,
):
    reports = _write_unique_reports(tmp_path / "reports", 2)
    database = tmp_path / "two-stage-late-ambiguity.db"
    plan = ImportPlan.all_ready(
        _request(reports[0].parent, database), _preflight(reports[0].parent, database)
    )
    filter_state = _track_completed_import_plan_filter(monkeypatch)
    original_resolver = report_parser_factory._resolve_parser_with_registration
    report_a_hash = hashlib.sha256(reports[0].read_bytes()).hexdigest()

    def late_ambiguity_resolver(file_path, **kwargs):
        diagnostics, registration = original_resolver(file_path, **kwargs)
        if Path(file_path) == reports[1] and filter_state["completed"]:
            ambiguous_diagnostics = replace(
                diagnostics,
                selected=None,
                rejected_reason="ambiguous_parser_match",
                ambiguous_plugin_ids=("cmm", "new-parser"),
            )
            raise report_parser_factory.ParserAmbiguityError(
                ambiguous_diagnostics,
                ambiguous_diagnostics.ambiguous_plugin_ids,
            )
        return diagnostics, registration

    monkeypatch.setenv("METROLIZA_PARSE_TWO_STAGE_PIPELINE", "1")
    monkeypatch.setenv("METROLIZA_PARSE_TWO_STAGE_WORKERS", "2")
    monkeypatch.setattr(
        report_parser_factory,
        "_resolve_parser_with_registration",
        late_ambiguity_resolver,
    )

    thread = ParseReportsThread(plan)
    thread.run()

    assert _stored_source_hashes(database) == {report_a_hash}
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=1,
        selected=2,
        imported=1,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_two_stage_late_source_drift_is_changed_and_keeps_identity_pairing(
    tmp_path,
    monkeypatch,
):
    reports = _write_unique_reports(tmp_path / "reports", 2)
    database = tmp_path / "two-stage-source-drift.db"
    plan = ImportPlan.all_ready(
        _request(reports[0].parent, database), _preflight(reports[0].parent, database)
    )
    filter_state = _track_completed_import_plan_filter(monkeypatch)
    original_prepare = CMMReportParser.prepare_for_two_stage_pipeline
    report_a_hash = hashlib.sha256(reports[0].read_bytes()).hexdigest()

    def prepare_then_change_selected_source(parser):
        result = original_prepare(parser)
        if parser.file_name == reports[1].name:
            assert filter_state["completed"]
            reports[1].write_bytes(reports[1].read_bytes() + b"\n% late-two-stage-change\n")
        return result

    monkeypatch.setenv("METROLIZA_PARSE_TWO_STAGE_PIPELINE", "1")
    monkeypatch.setenv("METROLIZA_PARSE_TWO_STAGE_WORKERS", "2")
    monkeypatch.setattr(
        CMMReportParser,
        "prepare_for_two_stage_pipeline",
        prepare_then_change_selected_source,
    )

    thread = ParseReportsThread(plan)
    thread.run()

    assert _stored_source_hashes(database) == {report_a_hash}
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=1,
        selected=2,
        imported=1,
        already_present=0,
        changed=1,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_identical_content_has_deterministic_occurrence_identity(tmp_path):
    source = tmp_path / "reports"
    reports = _write_unique_reports(source, 2)
    reports[1].write_bytes(reports[0].read_bytes())
    database = tmp_path / "occurrences.db"

    first_scan = _preflight(source, database)
    second_scan = _preflight(source, database)

    assert [item.stable_occurrence_id for item in first_scan.files] == [
        reports[0].name,
        reports[1].name,
    ]
    assert first_scan.result_id == second_scan.result_id
    assert first_scan.files[0].status is ParsePreflightStatus.READY
    assert first_scan.files[1].status is ParsePreflightStatus.DUPLICATE
    assert ImportPlan.all_ready(
        _request(source, database),
        first_scan,
    ).selected_reports[0].occurrence_id == reports[0].name


def test_archive_selection_survives_reextraction_without_temporary_path_identity(tmp_path):
    fixture_bytes = FIXTURE.read_bytes()
    selected_bytes = fixture_bytes + b"\n% selected-archive-member\n"
    archive = tmp_path / "reports.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nested/excluded.pdf", fixture_bytes + b"\n% excluded\n")
        bundle.writestr("nested/selected.pdf", selected_bytes)
    database = tmp_path / "archive.db"
    preflight = _preflight(archive, database)
    selected_item = next(
        item for item in preflight.ready_files if item.display_name == "nested/selected.pdf"
    )
    plan = ImportPlan.from_preflight(
        _request(archive, database),
        preflight,
        selected_occurrence_ids=(selected_item.stable_occurrence_id,),
    )

    assert selected_item.source_path not in repr(plan.selected_reports)
    assert plan.selected_reports[0].occurrence_id == "nested/selected.pdf"
    thread = ParseReportsThread(plan)
    thread.run()

    assert _stored_source_hashes(database) == {hashlib.sha256(selected_bytes).hexdigest()}
    _assert_selected_result_counts(
        thread.last_parse_result,
        parsed=1,
        selected=1,
        imported=1,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=1,
    )


def test_cancellation_keeps_completed_atomic_report_and_truthful_counts(tmp_path):
    reports = _write_unique_reports(tmp_path / "reports", 3)
    database = tmp_path / "cancelled.db"
    cancel_requested = False

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE completed (name TEXT PRIMARY KEY)")

        def persist_report(parser):
            nonlocal cancel_requested
            with connection:
                connection.execute("INSERT INTO completed (name) VALUES (?)", (parser.name,))
            cancel_requested = True

        result = parse_new_reports(
            reports,
            set(),
            parser_factory=lambda report, **_kwargs: SimpleNamespace(name=report.name),
            persist_report=persist_report,
            should_cancel=lambda: cancel_requested,
        )
        completed = connection.execute("SELECT name FROM completed").fetchall()

    assert completed == [(reports[0].name,)]
    _assert_selected_result_counts(
        result,
        parsed=1,
        selected=3,
        imported=1,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=2,
        excluded=0,
    )


def test_two_stage_cancellation_keeps_completed_atomic_report_and_exact_counts(
    tmp_path,
    monkeypatch,
):
    reports = _write_unique_reports(tmp_path / "reports", 3)
    database = tmp_path / "two-stage-cancelled.db"
    cancel_requested = False
    caller_thread_id = get_ident()
    persistence_thread_ids = []

    monkeypatch.setattr(
        "metroliza.parsing.parse_reports_thread.as_completed",
        lambda futures: iter(futures),
    )

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE completed (name TEXT PRIMARY KEY)")

        def persist_report(parser):
            nonlocal cancel_requested
            persistence_thread_ids.append(get_ident())
            with connection:
                connection.execute("INSERT INTO completed (name) VALUES (?)", (parser.name,))
            cancel_requested = True

        result = parse_new_reports(
            reports,
            set(),
            parser_factory=lambda report, **_kwargs: SimpleNamespace(name=report.name),
            persist_report=persist_report,
            should_cancel=lambda: cancel_requested,
            enable_two_stage_pipeline=True,
            worker_count=1,
        )
        completed = connection.execute("SELECT name FROM completed").fetchall()

    assert completed == [(reports[0].name,)]
    assert persistence_thread_ids == [caller_thread_id]
    _assert_selected_result_counts(
        result,
        parsed=1,
        selected=3,
        imported=1,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=2,
        excluded=0,
    )


def test_two_stage_parsing_keeps_all_sqlite_writes_on_the_caller_thread(tmp_path):
    reports = _write_unique_reports(tmp_path / "reports", 3)
    database = tmp_path / "single-writer.db"
    caller_thread_id = get_ident()
    persistence_thread_ids = []

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE completed (name TEXT PRIMARY KEY)")

        def persist_report(parser):
            persistence_thread_ids.append(get_ident())
            with connection:
                connection.execute("INSERT INTO completed (name) VALUES (?)", (parser.name,))

        result = parse_new_reports(
            reports,
            set(),
            parser_factory=lambda report, **_kwargs: SimpleNamespace(name=report.name),
            persist_report=persist_report,
            enable_two_stage_pipeline=True,
            worker_count=2,
        )
        stored_count = connection.execute("SELECT COUNT(*) FROM completed").fetchone()[0]

    assert stored_count == 3
    assert persistence_thread_ids == [caller_thread_id] * 3
    _assert_selected_result_counts(
        result,
        parsed=3,
        selected=3,
        imported=3,
        already_present=0,
        changed=0,
        failed=0,
        skipped=0,
        cancelled=0,
        excluded=0,
    )


def test_cancelled_preflight_cannot_build_a_plan(tmp_path):
    source = tmp_path / "reports"
    _write_unique_reports(source, 1)
    database = tmp_path / "cancelled-preflight.db"
    cancelled = replace(_preflight(source, database), cancelled=True)

    with pytest.raises(ValueError, match="cancelled preflight"):
        ImportPlan.all_ready(_request(source, database), cancelled)

    assert not database.exists()


def test_selected_identity_is_a_frozen_typed_value():
    identity = SelectedReportIdentity("report.pdf", "sha256:abc", "cmm", 1)

    with pytest.raises(FrozenInstanceError):
        identity.parser_id = "other"
