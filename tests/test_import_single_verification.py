"""Two import hashes (#1125), plus one pre-schema guard only for schema work."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3

import pytest

from metroliza.parsing.parse_reports_thread import ParseReportsThread
from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
from metroliza.parsing.source_inspection import (
    SourceChangedAfterInspectionError,
    SourceInspectionContext,
)
from metroliza.reports import report_repository
from metroliza.shared.parse_contracts import ParseRequest

FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"


def _write_reports(source: Path, count: int) -> list[Path]:
    source.mkdir()
    fixture_bytes = FIXTURE.read_bytes()
    reports = []
    for index in range(count):
        report = source / f"report-{index}.pdf"
        report.write_bytes(fixture_bytes + f"\n% synthetic-report-{index}\n".encode())
        reports.append(report)
    return reports


def _plan(source: Path, database: Path):
    request = ParseRequest(str(source), str(database), "light")
    preflight = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light"
    )
    return preflight, ImportPlan.all_ready(request, preflight)


def _count_hash_reads(monkeypatch):
    """Count full-content reads and flag any that happen while a write transaction is open."""

    state = {"reads": [], "cursor": None, "reads_in_transaction": 0}
    original_context_hash = SourceInspectionContext._compute_sha256
    original_repo_hash = report_repository.compute_sha256
    original_transaction = report_repository.run_transaction_with_retry

    def record_read(path):
        state["reads"].append(Path(path).name)
        cursor = state["cursor"]
        if cursor is not None:
            # The callback starts before BEGIN IMMEDIATE: prove the hash follows
            # successful lock acquisition, rather than just callback entry.
            assert cursor.connection.in_transaction
            state["reads_in_transaction"] += 1

    def counted_context_hash(self):
        record_read(self.source_path)
        return original_context_hash(self)

    def counted_repo_hash(path, **kwargs):
        record_read(path)
        return original_repo_hash(path, **kwargs)

    def tracked_transaction(*args, **kwargs):
        callback = args[1]

        def wrapped(cursor):
            state["cursor"] = cursor
            try:
                return callback(cursor)
            finally:
                state["cursor"] = None

        return original_transaction(args[0], wrapped, *args[2:], **kwargs)

    monkeypatch.setattr(SourceInspectionContext, "_compute_sha256", counted_context_hash)
    monkeypatch.setattr(report_repository, "compute_sha256", counted_repo_hash)
    monkeypatch.setattr(report_repository, "run_transaction_with_retry", tracked_transaction)
    return state


def _imported_hashes(database: Path) -> set[str]:
    with closing(sqlite3.connect(database)) as connection:
        return {row[0] for row in connection.execute("SELECT sha256 FROM source_files")}


def test_preflight_records_size_and_mtime_beside_the_fingerprint(tmp_path):
    reports = _write_reports(tmp_path / "reports", 2)
    preflight, _plan_unused = _plan(tmp_path / "reports", tmp_path / "db.sqlite3")

    by_name = {Path(item.source_path).name: item for item in preflight.files}
    for report in reports:
        stat_result = os.stat(report)
        assert by_name[report.name].stat_signature == (stat_result.st_size, stat_result.st_mtime_ns)


def test_adopt_reviewed_digest_needs_unchanged_stat_and_no_digest_yet(tmp_path):
    report = tmp_path / "report.bin"
    report.write_bytes(b"reviewed bytes")
    reviewed = SourceInspectionContext.from_path(report).sha256
    stat_result = os.stat(report)
    signature = (stat_result.st_size, stat_result.st_mtime_ns)

    fresh = SourceInspectionContext.from_path(report)
    assert fresh.adopt_reviewed_sha256(reviewed, signature) is True
    assert fresh.sha256 == reviewed

    assert SourceInspectionContext.from_path(report).adopt_reviewed_sha256(reviewed, None) is False
    moved = (signature[0], signature[1] + 1)
    assert SourceInspectionContext.from_path(report).adopt_reviewed_sha256(reviewed, moved) is False
    already_hashed = SourceInspectionContext.from_path(report)
    assert already_hashed.sha256 == reviewed
    assert already_hashed.adopt_reviewed_sha256("0" * 64, signature) is False
    assert already_hashed.sha256 == reviewed


def test_adopted_digest_never_replaces_the_verification_hash(tmp_path):
    report = tmp_path / "report.bin"
    report.write_bytes(b"reviewed bytes")
    reviewed = SourceInspectionContext.from_path(report).sha256
    before = os.stat(report)
    inspection = SourceInspectionContext.from_path(report)
    assert inspection.adopt_reviewed_sha256(reviewed, (before.st_size, before.st_mtime_ns))

    report.write_bytes(b"tampered bytes")  # same size, then restore the old mtime
    os.utime(report, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert (os.stat(report).st_size, os.stat(report).st_mtime_ns) == (
        before.st_size,
        before.st_mtime_ns,
    )

    with pytest.raises(SourceChangedAfterInspectionError):
        inspection.verified_sha256()


def test_final_verification_always_rehashes_even_when_stat_is_unchanged(tmp_path, monkeypatch):
    report = tmp_path / "report.bin"
    report.write_bytes(b"reviewed bytes")
    inspection = SourceInspectionContext.from_path(report)
    assert inspection.sha256
    reads = []
    original = SourceInspectionContext._compute_sha256
    monkeypatch.setattr(
        SourceInspectionContext,
        "_compute_sha256",
        lambda self: reads.append(1) or original(self),
    )

    assert inspection.verified_sha256() == inspection.sha256
    assert inspection.verified_sha256() == inspection.sha256
    assert len(reads) == 2

    report.write_bytes(b"reviewed bytes, now longer")
    with pytest.raises(SourceChangedAfterInspectionError):
        inspection.verified_sha256()
    assert len(reads) == 3


@pytest.mark.parametrize("workers", ["0", "2"])
@pytest.mark.parametrize("schema_state", ["ready", "absent", "outdated"])
def test_import_hashes_twice_plus_one_guard_only_for_required_schema_work(
    tmp_path, monkeypatch, workers, schema_state
):
    monkeypatch.setenv("METROLIZA_IMPORT_PREPARE_WORKERS", workers)
    monkeypatch.setenv("METROLIZA_IMPORT_PREPARE_MIN_REPORTS", "2")
    source = tmp_path / "reports"
    reports = _write_reports(source, 4)
    database = tmp_path / "db.sqlite3"
    _prepare_schema(database, schema_state)
    state = _count_hash_reads(monkeypatch)
    _preflight, plan = _plan(source, database)

    thread = ParseReportsThread(plan)
    thread.run()

    result = thread.last_parse_result
    assert (result.imported_files, result.failed_files, result.preflight_changed_files) == (4, 0, 0)
    expected_reads = [report.name for report in reports for _ in range(2)]
    if schema_state != "ready":
        expected_reads.append(reports[0].name)
    assert sorted(state["reads"]) == sorted(expected_reads)
    assert state["reads_in_transaction"] == 4


def test_same_size_same_mtime_change_after_review_is_rejected_and_not_persisted(tmp_path):
    source = tmp_path / "reports"
    reports = _write_reports(source, 3)
    database = tmp_path / "db.sqlite3"
    _preflight, plan = _plan(source, database)
    victim = reports[1]
    before = os.stat(victim)
    data = victim.read_bytes()
    victim.write_bytes(data.replace(b"synthetic-report-1", b"synthetic-report-7"))
    os.utime(victim, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert os.stat(victim).st_size == before.st_size

    thread = ParseReportsThread(plan)
    thread.run()

    result = thread.last_parse_result
    assert (result.imported_files, result.preflight_changed_files, result.failed_files) == (2, 1, 0)
    assert len(_imported_hashes(database)) == 2


def test_size_change_after_review_is_rejected_before_parsing(tmp_path):
    source = tmp_path / "reports"
    reports = _write_reports(source, 3)
    database = tmp_path / "db.sqlite3"
    _preflight, plan = _plan(source, database)
    reports[0].write_bytes(reports[0].read_bytes() + b"\n% appended after review\n")

    thread = ParseReportsThread(plan)
    thread.run()

    result = thread.last_parse_result
    assert (result.imported_files, result.preflight_changed_files) == (2, 1)
    assert len(_imported_hashes(database)) == 2


def test_touched_but_identical_file_is_still_imported(tmp_path):
    source = tmp_path / "reports"
    reports = _write_reports(source, 2)
    database = tmp_path / "db.sqlite3"
    _preflight, plan = _plan(source, database)
    stat_result = os.stat(reports[0])
    os.utime(reports[0], ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 5_000_000_000))

    thread = ParseReportsThread(plan)
    thread.run()

    result = thread.last_parse_result
    assert (result.imported_files, result.preflight_changed_files) == (2, 0)


def test_uninspected_repository_import_inspects_then_verifies_inside_the_transaction(tmp_path, monkeypatch):
    from tests.test_atomic_report_import import _payload

    source = tmp_path / "synthetic.report"
    source.write_bytes(b"reviewed")
    database = tmp_path / "reports.sqlite3"
    digest = report_repository.compute_sha256(source)
    state = _count_hash_reads(monkeypatch)

    outcome = report_repository.ReportRepository(str(database)).import_report_if_absent(
        source_path=source, source_sha256=digest, **_payload("once")
    )

    assert outcome is report_repository.ReportImportDisposition.IMPORTED
    assert state["reads"] == ["synthetic.report", "synthetic.report"]
    assert state["reads_in_transaction"] == 1


def _prepare_schema(database, schema_state):
    repository = report_repository.ReportRepository(str(database))
    if schema_state != "absent":
        repository.ensure_schema()
    if schema_state == "outdated":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("DELETE FROM app_schema WHERE key = 'source_location_ownership_version'")
            connection.commit()
    return repository


@pytest.mark.parametrize("schema_state, expected_reads", [("ready", 2), ("absent", 3), ("outdated", 3)])
def test_inspected_import_adds_a_pre_schema_guard_only_when_schema_work_is_required(
    tmp_path, monkeypatch, schema_state, expected_reads
):
    from tests.test_atomic_report_import import _payload

    source = tmp_path / "synthetic.report"
    source.write_bytes(b"reviewed")
    database = tmp_path / "reports.sqlite3"
    repository = _prepare_schema(database, schema_state)
    state = _count_hash_reads(monkeypatch)
    inspection = SourceInspectionContext.from_path(source)
    digest = inspection.sha256

    outcome = repository.import_report_if_absent(
        source_path=source,
        source_sha256=digest,
        source_digest_verifier=inspection.verified_sha256,
        **_payload("inspected"),
    )

    assert outcome is report_repository.ReportImportDisposition.IMPORTED
    assert state["reads"] == [source.name] * expected_reads
    assert state["reads_in_transaction"] == 1
    assert repository._import_schema_is_ready()


@pytest.mark.parametrize("schema_state", ["absent", "outdated"])
def test_pre_schema_guard_does_not_replace_final_content_verification(
    tmp_path, monkeypatch, schema_state
):
    from tests.test_atomic_report_import import _payload

    source = tmp_path / "synthetic.report"
    source.write_bytes(b"reviewed")
    before = source.stat()
    inspection = SourceInspectionContext.from_path(source)
    digest = inspection.sha256
    database = tmp_path / "reports.sqlite3"
    repository = _prepare_schema(database, schema_state)
    ensure_schema = repository._ensure_import_schema

    def migrate_then_replace_source():
        ensure_schema()
        source.write_bytes(b"tampered")
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

    monkeypatch.setattr(repository, "_ensure_import_schema", migrate_then_replace_source)

    with pytest.raises(SourceChangedAfterInspectionError):
        repository.import_report_if_absent(
            source_path=source,
            source_sha256=digest,
            source_digest_verifier=inspection.verified_sha256,
            **_payload("stale"),
        )

    assert _imported_hashes(database) == set()


@pytest.mark.parametrize("already_present", [False, True])
@pytest.mark.parametrize("change_content", [False, True])
@pytest.mark.parametrize("change_mtime", [False, True])
def test_content_hash_is_authoritative_when_mtime_changes_during_lock_wait(
    tmp_path, monkeypatch, already_present, change_content, change_mtime
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from tests.test_atomic_report_import import _payload

    source = tmp_path / "synthetic.report"
    source.write_bytes(b"reviewed")
    before = source.stat()
    inspection = SourceInspectionContext.from_path(source)
    digest = inspection.sha256
    database = tmp_path / "reports.sqlite3"
    repository = report_repository.ReportRepository(str(database))
    repository.ensure_schema()
    if already_present:
        repository.import_report_if_absent(source_path=source, **_payload("accepted"))
    state = _count_hash_reads(monkeypatch)
    waiting = Event()
    modified_ns = before.st_mtime_ns + (5_000_000_000 if change_mtime else 0)

    def import_contender():
        with closing(sqlite3.connect(database, timeout=5)) as connection:
            contender = report_repository.ReportRepository(str(database), connection=connection)
            contender.ensure_schema = lambda: None
            connection.set_trace_callback(
                lambda statement: waiting.set() if statement == "BEGIN IMMEDIATE" else None
            )
            return contender.import_report_if_absent(
                source_path=source,
                source_sha256=digest,
                source_digest_verifier=inspection.verified_sha256,
                **_payload("stale"),
            )

    with closing(sqlite3.connect(database)) as lock, ThreadPoolExecutor(max_workers=1) as pool:
        lock.execute("BEGIN IMMEDIATE")
        future = pool.submit(import_contender)
        try:
            assert waiting.wait(5), "contender never reached BEGIN IMMEDIATE"
            replacement = tmp_path / "replacement.report"
            replacement.write_bytes(b"tampered" if change_content else b"reviewed")
            os.utime(replacement, ns=(before.st_atime_ns, modified_ns))
            replacement.replace(source)
            assert (source.stat().st_size, source.stat().st_mtime_ns) == (
                before.st_size, modified_ns
            )
        finally:
            lock.rollback()
        if change_content:
            with pytest.raises(SourceChangedAfterInspectionError):
                future.result(timeout=10)
        else:
            expected = (
                report_repository.ReportImportDisposition.ALREADY_PRESENT if already_present
                else report_repository.ReportImportDisposition.IMPORTED
            )
            assert future.result(timeout=10) is expected
    assert len(_imported_hashes(database)) == (int(already_present) if change_content else 1)
    assert state["reads"] == [source.name]
    assert state["reads_in_transaction"] == 1


@pytest.mark.parametrize("change_content", [False, True])
def test_mtime_change_before_transaction_is_classified_without_a_dialog(
    tmp_path, monkeypatch, change_content
):
    from metroliza.parsing.cmm_report_parser import CMMReportParser

    source = tmp_path / "reports"
    report, = _write_reports(source, 1)
    database = tmp_path / "db.sqlite3"
    _prepare_schema(database, "ready")
    _preflight, plan = _plan(source, database)
    original = report_repository.run_transaction_with_retry
    dialogs = []

    def touch_before_begin(database_path, callback, *args, **kwargs):
        before = report.stat()
        data = report.read_bytes()
        if change_content:
            report.write_bytes(data.replace(b"synthetic-report-0", b"synthetic-report-9"))
        os.utime(report, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
        return original(database_path, callback, *args, **kwargs)

    monkeypatch.setattr(report_repository, "run_transaction_with_retry", touch_before_begin)
    monkeypatch.setattr(CMMReportParser, "log_and_exit", lambda _self, exc: dialogs.append(exc))
    thread = ParseReportsThread(plan)
    thread.run()
    result = thread.last_parse_result
    assert (result.imported_files, result.preflight_changed_files, result.failed_files) == (
        (0, 1, 0) if change_content else (1, 0, 0)
    )
    assert dialogs == []
