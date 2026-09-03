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
from metroliza.parsing.parse_reports_thread import ParseReportsThread, parse_new_reports
from metroliza.parsing.preflight import (
    ImportPlan,
    ParsePreflightService,
    ParsePreflightStatus,
    SelectedReportIdentity,
    validate_import_plan,
)
from metroliza.shared.parse_contracts import ParseRequest


FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"


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
    assert thread.last_parse_result.selected_files == 2
    assert thread.last_parse_result.imported_files == 2
    assert thread.last_parse_result.already_present_files == 0
    assert thread.last_parse_result.intentionally_excluded_files == 3
    assert thread.last_parse_result.preflight_changed_files == 0


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
    assert thread.last_parse_result.selected_files == 0
    assert thread.last_parse_result.imported_files == 0
    assert thread.last_parse_result.intentionally_excluded_files == 2


def test_explicit_all_ready_adapter_preserves_current_behavior(tmp_path):
    source = tmp_path / "reports"
    _write_unique_reports(source, 3)
    database = tmp_path / "all-ready.db"
    request = _request(source, database)
    preflight = _preflight(source, database)

    thread = ParseReportsThread.for_all_ready(request, preflight)
    thread.run()

    assert len(_stored_source_hashes(database)) == 3
    assert thread.last_parse_result.selected_files == 3
    assert thread.last_parse_result.imported_files == 3
    assert thread.last_parse_result.intentionally_excluded_files == 0


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
def test_selected_file_changed_or_deleted_after_review_is_rejected(tmp_path, change):
    source = tmp_path / "reports"
    report = _write_unique_reports(source, 1)[0]
    database = tmp_path / f"{change}.db"
    preflight = _preflight(source, database)
    plan = ImportPlan.all_ready(_request(source, database), preflight)
    if change == "changed":
        report.write_bytes(b"changed after review")
    else:
        report.unlink()

    thread = ParseReportsThread(plan)
    thread.run()

    assert not database.exists()
    assert thread.last_parse_result.imported_files == 0
    assert thread.last_parse_result.preflight_changed_files == 1


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
    assert thread.last_parse_result.imported_files == 1
    assert thread.last_parse_result.intentionally_excluded_files == 1
    assert thread.last_parse_result.preflight_changed_files == 1


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
    assert thread.last_parse_result.imported_files == 0
    assert thread.last_parse_result.preflight_changed_files == 1


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
    assert duplicate_recheck.last_parse_result.selected_files == 1
    assert duplicate_recheck.last_parse_result.imported_files == 0
    assert duplicate_recheck.last_parse_result.already_present_files == 1


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
    assert thread.last_parse_result.intentionally_excluded_files == 1


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
    assert result.selected_files == 3
    assert result.imported_files == 1
    assert result.cancelled_files == 2


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

    assert result.imported_files == 3
    assert stored_count == 3
    assert persistence_thread_ids == [caller_thread_id] * 3


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
