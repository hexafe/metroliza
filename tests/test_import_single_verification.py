"""Import integrity (#1125): one preflight hash plus one full verification inside the write lock."""

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

    state = {"reads": [], "in_transaction": False, "reads_in_transaction": 0}
    original_context_hash = SourceInspectionContext._compute_sha256
    original_repo_hash = report_repository.compute_sha256
    original_transaction = report_repository.run_transaction_with_retry

    def counted_context_hash(self):
        state["reads"].append(Path(self.source_path).name)
        state["reads_in_transaction"] += int(state["in_transaction"])
        return original_context_hash(self)

    def counted_repo_hash(path, **kwargs):
        state["reads"].append(Path(path).name)
        state["reads_in_transaction"] += int(state["in_transaction"])
        return original_repo_hash(path, **kwargs)

    def tracked_transaction(*args, **kwargs):
        callback = args[1]

        def wrapped(cursor):
            state["in_transaction"] = True
            try:
                return callback(cursor)
            finally:
                state["in_transaction"] = False

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
def test_import_hashes_each_file_twice_with_final_read_inside_the_write_transaction(
    tmp_path, monkeypatch, workers
):
    monkeypatch.setenv("METROLIZA_IMPORT_PREPARE_WORKERS", workers)
    monkeypatch.setenv("METROLIZA_IMPORT_PREPARE_MIN_REPORTS", "2")
    source = tmp_path / "reports"
    reports = _write_reports(source, 4)
    database = tmp_path / "db.sqlite3"
    state = _count_hash_reads(monkeypatch)
    _preflight, plan = _plan(source, database)

    thread = ParseReportsThread(plan)
    thread.run()

    result = thread.last_parse_result
    assert (result.imported_files, result.failed_files, result.preflight_changed_files) == (4, 0, 0)
    assert sorted(state["reads"]) == sorted(report.name for report in reports for _ in range(2))
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


@pytest.mark.parametrize("already_present", [False, True])
def test_same_size_same_mtime_replacement_during_lock_wait_is_rejected(
    tmp_path, already_present
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
    waiting = Event()

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
            replacement.write_bytes(b"tampered")
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            replacement.replace(source)
            assert (source.stat().st_size, source.stat().st_mtime_ns) == (
                before.st_size, before.st_mtime_ns
            )
        finally:
            lock.rollback()
        with pytest.raises((ValueError, SourceChangedAfterInspectionError)):
            future.result(timeout=10)
    assert len(_imported_hashes(database)) == int(already_present)
