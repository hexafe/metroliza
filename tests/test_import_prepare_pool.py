"""Parallel import preparation (#1125): same database as the serial path, same semantics."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import random
import sqlite3
import sys

import pytest


from metroliza.parsing import import_prepare_pool
from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.import_prepare_pool import (
    MIN_REPORTS_ENV,
    WORKERS_ENV,
    ImportPreparePool,
    accepted_worker_state,
    resolve_prepare_worker_count,
)
from metroliza.parsing.parse_reports_thread import ParseReportsThread
from metroliza.parsing.pdf_backend import require_pdf_backend
from metroliza.parsing.preflight import ImportPlan, ParsePreflightService
from metroliza.reports.report_repository import ReportRepository
from metroliza.shared.parse_contracts import ParseRequest

# The only columns excluded from the serial-vs-pool comparison: wall-clock values written
# when a row is persisted. Everything else (ids, hashes, metadata, candidates, measurements,
# parse state, source mtimes) must be byte-identical.
WALL_CLOCK_COLUMNS = {
    "parsed_reports": {"parse_started_at", "parse_finished_at", "created_at", "updated_at"},
    "report_metadata_candidates": {"created_at"},
    "report_metadata_warnings": {"created_at"},
    "report_parse_state": {"updated_at"},
    "source_files": {"discovered_at", "ingested_at"},
    "source_file_locations": {"discovered_at"},
}


def _write_synthetic_reports(source: Path, count: int, seed: int = 11) -> list[Path]:
    # The repo's own backend handle: other tests leave a stub module in sys.modules["pymupdf"].
    pymupdf = require_pdf_backend()

    rnd = random.Random(seed)
    source.mkdir()
    reports = []
    for index in range(count):
        ref = f"ABC{index % 4:02d}{(index % 4) * 7 + 100:03d}"
        lines = [
            "SYNTHETIC CMM MEASUREMENT REPORT",
            "CMM REPORT",
            f"REFERENCE: {ref}",
            f"DATE: 2024-02-{1 + index % 27:02d}",
            f"SAMPLE: {index + 1:04d}",
        ]
        for feature in range(1 + index % 3):
            lines += [f"#FEATURE_{feature:02d}", "DIM"]
            for axis in "XYZD":
                nominal, tol = rnd.uniform(5, 200), rnd.choice([0.1, 0.2, 0.3])
                measured = nominal + rnd.gauss(0, tol / 2)
                lines.append(
                    f"{axis} {nominal:.4f} {tol:.4f} {-tol:.4f} {measured:.4f} "
                    f"{measured - nominal:.4f} {max(0.0, abs(measured - nominal) - tol):.4f}"
                )
        lines.append("#END")
        report = source / f"{ref}_{index:03d}.pdf"
        document = pymupdf.open()
        for start in range(0, len(lines), 40):  # several pages for the longer ones
            page = document.new_page()
            page.insert_text((40, 40), "\n".join(lines[start:start + 40]), fontsize=8)
        document.save(str(report))
        document.close()
        reports.append(report)
    return reports


def _plan(source: Path, database: Path) -> ImportPlan:
    request = ParseRequest(str(source), str(database), "light")
    preflight = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light"
    )
    return ImportPlan.all_ready(request, preflight)


def _pool_env(monkeypatch, workers: str) -> None:
    monkeypatch.setenv(WORKERS_ENV, workers)
    monkeypatch.setenv(MIN_REPORTS_ENV, "2")


def _run_import(source: Path, database: Path) -> ParseReportsThread:
    thread = ParseReportsThread(_plan(source, database))
    thread.run()
    return thread


def _dump_database(database: Path) -> dict[str, list[tuple]]:
    with closing(sqlite3.connect(database)) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        dump = {}
        for table in tables:
            skipped = WALL_CLOCK_COLUMNS.get(table, set())
            columns = [
                row[1] for row in connection.execute(f"PRAGMA table_info({table})") if row[1] not in skipped
            ]
            dump[table] = connection.execute(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid"
            ).fetchall()
        return dump


def _count_in_process_work(monkeypatch):
    counts = {"hydrated": 0, "prepared_in_process": 0}
    original_apply = CMMReportParser.apply_prepared_state
    original_prepare = CMMReportParser.prepare_for_two_stage_pipeline

    def apply_state(self, state):
        counts["hydrated"] += 1
        return original_apply(self, state)

    def prepare(self):
        counts["prepared_in_process"] += 1
        return original_prepare(self)

    monkeypatch.setattr(CMMReportParser, "apply_prepared_state", apply_state)
    monkeypatch.setattr(CMMReportParser, "prepare_for_two_stage_pipeline", prepare)
    return counts


def test_pooled_import_database_is_identical_to_the_serial_database(tmp_path, monkeypatch):
    source = tmp_path / "reports"
    _write_synthetic_reports(source, 24)

    _pool_env(monkeypatch, "0")
    serial_counts = _count_in_process_work(monkeypatch)
    serial = _run_import(source, tmp_path / "serial.sqlite3")
    assert serial_counts == {"hydrated": 0, "prepared_in_process": 24}

    _pool_env(monkeypatch, "2")
    pooled_counts = _count_in_process_work(monkeypatch)
    pooled = _run_import(source, tmp_path / "pooled.sqlite3")
    assert pooled_counts == {"hydrated": 24, "prepared_in_process": 0}

    assert serial.last_parse_result == pooled.last_parse_result
    assert pooled.last_parse_result.imported_files == 24
    serial_dump = _dump_database(tmp_path / "serial.sqlite3")
    pooled_dump = _dump_database(tmp_path / "pooled.sqlite3")
    assert serial_dump == pooled_dump
    assert len(serial_dump["parsed_reports"]) == 24
    assert len(serial_dump["report_measurements"]) > 24 * 4
    assert serial_dump["report_metadata_candidates"] and serial_dump["report_parse_state"]


def test_cold_probe_cache_serial_and_pooled_imports_match_the_warm_serial_database(tmp_path, monkeypatch):
    """A probe-cache miss lets open_report reuse the inspected text; the result must not change."""

    from metroliza.parsing import report_parser_factory

    source = tmp_path / "reports"
    _write_synthetic_reports(source, 12)
    dumps = {}
    for label, workers, cold in (("warm", "0", False), ("cold", "0", True), ("cold_pool", "2", True)):
        _pool_env(monkeypatch, workers)
        database = tmp_path / f"{label}.sqlite3"
        plan = _plan(source, database)
        if cold:
            report_parser_factory.reset_probe_cache()
        ParseReportsThread(plan).run()
        dumps[label] = _dump_database(database)

    assert dumps["warm"] == dumps["cold"] == dumps["cold_pool"]
    assert len(dumps["warm"]["parsed_reports"]) == 12


def test_only_declared_wall_clock_columns_are_excluded_from_the_comparison(tmp_path, monkeypatch):
    _write_synthetic_reports(tmp_path / "reports", 3)
    _pool_env(monkeypatch, "0")
    _run_import(tmp_path / "reports", tmp_path / "db.sqlite3")

    with closing(sqlite3.connect(tmp_path / "db.sqlite3")) as connection:
        for table, skipped in WALL_CLOCK_COLUMNS.items():
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert skipped <= columns
        timestamp_like = {
            table: {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table})")
                if row[1].endswith("_at")
            }
            for (table,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
    populated = {"parsed_reports", "report_metadata_candidates", "report_metadata_warnings",
                 "report_parse_state", "source_files", "source_file_locations"}
    for table in populated:
        assert timestamp_like[table] <= WALL_CLOCK_COLUMNS[table] | {"file_modified_at"}


def test_cancellation_commits_the_same_ordered_prefix_as_the_serial_import(tmp_path, monkeypatch):
    source = tmp_path / "reports"
    _write_synthetic_reports(source, 20)
    outcomes = {}
    for label, workers in (("serial", "0"), ("pooled", "2")):
        _pool_env(monkeypatch, workers)
        database = tmp_path / f"{label}.sqlite3"
        thread = ParseReportsThread(_plan(source, database))
        original = ReportRepository.import_report_if_absent
        imported = []

        def cancel_after_five(self, *args, _thread=thread, _imported=imported, _original=original, **kwargs):
            outcome = _original(self, *args, **kwargs)
            _imported.append(outcome)
            if len(_imported) == 5:
                _thread.stop_parsing()
            return outcome

        monkeypatch.setattr(ReportRepository, "import_report_if_absent", cancel_after_five)
        thread.run()
        monkeypatch.setattr(ReportRepository, "import_report_if_absent", original)
        outcomes[label] = (thread.last_parse_result, _dump_database(database))

    assert outcomes["serial"] == outcomes["pooled"]
    result, dump = outcomes["pooled"]
    assert result.imported_files == 5 and result.cancelled_files == 15
    names = [row[0] for row in dump["source_file_locations"]]
    assert len(dump["parsed_reports"]) == 5 and len(names) == 5


def test_same_size_same_mtime_change_after_review_is_rejected_in_the_pooled_import(tmp_path, monkeypatch):
    source = tmp_path / "reports"
    reports = _write_synthetic_reports(source, 6)
    plan = _plan(source, tmp_path / "db.sqlite3")
    victim = reports[2]
    before = os.stat(victim)
    data = victim.read_bytes()
    index = data.index(b"/Producer")  # same-length edit inside the file body
    victim.write_bytes(data[:index] + b"/Producex" + data[index + 9:])
    os.utime(victim, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert os.stat(victim).st_size == before.st_size

    _pool_env(monkeypatch, "2")
    thread = ParseReportsThread(plan)
    thread.run()

    result = thread.last_parse_result
    assert (result.imported_files, result.preflight_changed_files, result.failed_files) == (5, 1, 0)
    dump = _dump_database(tmp_path / "db.sqlite3")
    assert len(dump["source_files"]) == 5


def test_failing_workers_fall_back_to_the_serial_result(tmp_path, monkeypatch):
    source = tmp_path / "reports"
    _write_synthetic_reports(source, 12)
    _pool_env(monkeypatch, "0")
    serial = _run_import(source, tmp_path / "serial.sqlite3")

    _pool_env(monkeypatch, "2")
    monkeypatch.setattr(import_prepare_pool, "prepare_cmm_report_in_worker", os._exit)  # raises TypeError
    counts = _count_in_process_work(monkeypatch)
    pooled = _run_import(source, tmp_path / "pooled.sqlite3")

    assert counts == {"hydrated": 0, "prepared_in_process": 12}
    assert serial.last_parse_result == pooled.last_parse_result
    assert _dump_database(tmp_path / "serial.sqlite3") == _dump_database(tmp_path / "pooled.sqlite3")


def test_a_dying_worker_breaks_the_pool_without_restart_and_the_import_still_matches(tmp_path, monkeypatch):
    source = tmp_path / "reports"
    _write_synthetic_reports(source, 12)
    _pool_env(monkeypatch, "0")
    serial = _run_import(source, tmp_path / "serial.sqlite3")

    _pool_env(monkeypatch, "2")
    original_submit = ProcessPoolExecutor.submit
    submitted = []

    def killing_submit(self, function, *args, **kwargs):
        submitted.append(function)
        if len(submitted) == 3:
            return original_submit(self, os._exit, 1)
        return original_submit(self, function, *args, **kwargs)

    monkeypatch.setattr(ProcessPoolExecutor, "submit", killing_submit)
    counts = _count_in_process_work(monkeypatch)
    pooled = _run_import(source, tmp_path / "pooled.sqlite3")

    assert counts["prepared_in_process"] > 0  # the dead pool's reports were prepared in-process
    assert counts["hydrated"] + counts["prepared_in_process"] == 12
    assert serial.last_parse_result == pooled.last_parse_result
    assert _dump_database(tmp_path / "serial.sqlite3") == _dump_database(tmp_path / "pooled.sqlite3")
    assert len(submitted) <= 12  # never re-submitted to a replacement pool


def test_worker_result_is_discarded_when_the_file_moved_while_it_was_parsed():
    class Inspection:
        file_size_bytes, file_modified_ns = 10, 20

    steady = {"state": {"k": 1}, "stat_before": (10, 20), "stat_after": (10, 20)}
    assert accepted_worker_state(steady, Inspection()) == {"k": 1}
    for moved in (
        {**steady, "stat_after": (10, 21)},  # touched during the parse
        {**steady, "stat_before": (11, 20), "stat_after": (11, 20)},  # differs from the reviewed file
        {**steady, "stat_before": None, "stat_after": None},  # could not be observed
    ):
        assert accepted_worker_state(moved, Inspection()) is None


def test_worker_count_policy(monkeypatch):
    monkeypatch.delenv(WORKERS_ENV, raising=False)
    monkeypatch.delenv(MIN_REPORTS_ENV, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    monkeypatch.setattr(sys, "platform", "linux")

    assert resolve_prepare_worker_count(10) == 0  # tiny batch: start-up would dominate
    assert resolve_prepare_worker_count(500) == import_prepare_pool.MAX_AUTO_WORKERS
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert resolve_prepare_worker_count(500) == 0  # one spare core is not enough to pay off
    monkeypatch.setattr(os, "cpu_count", lambda: 12)

    monkeypatch.setenv(WORKERS_ENV, "0")
    assert resolve_prepare_worker_count(500) == 0
    monkeypatch.setenv(WORKERS_ENV, "3")
    assert resolve_prepare_worker_count(500) == 3
    assert resolve_prepare_worker_count(10) == 0
    monkeypatch.setenv(WORKERS_ENV, "garbage")
    assert resolve_prepare_worker_count(500) == 0


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("configured", ["auto", "3", "16"])
def test_frozen_build_stays_serial_even_with_explicit_workers(monkeypatch, platform, configured):
    monkeypatch.delenv(WORKERS_ENV, raising=False)
    monkeypatch.delenv(MIN_REPORTS_ENV, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert resolve_prepare_worker_count(5000) == 0
    monkeypatch.setenv(WORKERS_ENV, configured)
    assert resolve_prepare_worker_count(5000) == 0


def test_complete_mode_and_small_batches_never_start_a_pool(tmp_path, monkeypatch):
    source = tmp_path / "reports"
    _write_synthetic_reports(source, 4)
    started = []
    monkeypatch.setattr(
        ImportPreparePool, "__init__", lambda self, *args, **kwargs: started.append(1)
    )
    monkeypatch.setenv(WORKERS_ENV, "2")
    monkeypatch.delenv(MIN_REPORTS_ENV, raising=False)  # default minimum is larger than 4
    _run_import(source, tmp_path / "small.sqlite3")
    assert started == []

    monkeypatch.setenv(MIN_REPORTS_ENV, "2")
    thread = ParseReportsThread(_plan(source, tmp_path / "complete.sqlite3"))
    thread.metadata_parsing_mode = "complete"
    assert thread._open_prepare_pool([]) is None
    assert started == []


def test_only_reports_approved_for_the_builtin_cmm_parser_are_sent_to_workers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from metroliza.parsing import parse_reports_thread

    captured = {}

    class RecordingPool:
        def __init__(self, paths, **kwargs):
            captured["paths"] = list(paths)
            captured["workers"] = kwargs["workers"]

    monkeypatch.setattr(parse_reports_thread, "ImportPreparePool", RecordingPool)
    _pool_env(monkeypatch, "2")
    _write_synthetic_reports(tmp_path / "reports", 3)
    thread = ParseReportsThread(_plan(tmp_path / "reports", tmp_path / "db.sqlite3"))
    plugin_id = CMMReportParser.manifest.plugin_id
    items = [
        SimpleNamespace(report_path="a.pdf", selected_identity=SimpleNamespace(parser_id=plugin_id)),
        SimpleNamespace(report_path="b.pdf", selected_identity=SimpleNamespace(parser_id="external_plugin")),
        SimpleNamespace(report_path="c.pdf", selected_identity=None),
        SimpleNamespace(report_path="d.pdf", selected_identity=SimpleNamespace(parser_id=plugin_id)),
    ]

    assert thread._open_prepare_pool(items) is not None
    assert captured == {"paths": ["a.pdf", "d.pdf"], "workers": 2}
    thread._prepare_pool = None


def test_worker_state_is_never_applied_to_a_parser_that_is_not_the_builtin_cmm_parser(tmp_path):
    from types import SimpleNamespace

    class OtherParser:
        metadata_parsing_mode = "light"

    pool = SimpleNamespace(_parser_plugin_id=CMMReportParser.manifest.plugin_id, _mode="light")
    prepared = SimpleNamespace(
        parser=OtherParser(),
        resolution_evidence=SimpleNamespace(plugin_id=CMMReportParser.manifest.plugin_id),
    )
    assert ImportPreparePool._eligible(pool, prepared) is False


def test_cancel_during_unresolved_future_never_prepares_serially(tmp_path, monkeypatch):
    from concurrent.futures import Future

    _write_synthetic_reports(tmp_path / "reports", 2)
    _pool_env(monkeypatch, "2")
    thread = ParseReportsThread(_plan(tmp_path / "reports", tmp_path / "db.sqlite3"))
    counts = _count_in_process_work(monkeypatch)
    shutdown = []

    class CancellingFuture(Future):
        def result(self, timeout=None):
            thread.stop_parsing()
            return super().result(timeout=0.001)

    class UnresolvedExecutor:
        def __init__(self, **kwargs):
            pass

        def submit(self, *args):
            return CancellingFuture()

        def shutdown(self, **kwargs):
            shutdown.append(kwargs)

    monkeypatch.setattr(import_prepare_pool, "ProcessPoolExecutor", UnresolvedExecutor)
    thread.run()

    assert counts == {"hydrated": 0, "prepared_in_process": 0}
    result = thread.last_parse_result
    assert (result.imported_files, result.failed_files, result.cancelled_files) == (0, 0, 2)
    assert shutdown and shutdown[0]["cancel_futures"] is True


def _blocked_prepare_worker(task):
    """A deliberately stuck, core-dump-free worker for the shutdown regression."""
    import signal
    import time

    marker, _database, mode = task
    if mode == "ignore_terminate" and sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(marker).write_text(str(os.getpid()))
    while True:
        time.sleep(60)


@pytest.mark.parametrize("mode", ["light", "ignore_terminate"])
def test_cancel_reaps_blocked_workers_and_manager_with_bounded_shutdown(tmp_path, monkeypatch, mode):
    import time

    monkeypatch.setattr(import_prepare_pool, "prepare_cmm_report_in_worker", _blocked_prepare_worker)
    for cycle in range(2):
        markers = [tmp_path / f"{mode}-{cycle}-{index}.started" for index in range(2)]
        pool = ImportPreparePool(
            [str(marker) for marker in markers], database_path=str(tmp_path / "unused.sqlite3"),
            metadata_parsing_mode=mode, workers=2,
            parser_plugin_id=CMMReportParser.manifest.plugin_id,
        )
        executor = pool._executor
        children = list(executor._processes.values())
        manager = executor._executor_manager_thread
        try:
            deadline = time.monotonic() + 10
            while not all(marker.exists() for marker in markers) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert all(marker.exists() for marker in markers), "both blocked workers must be running"
            started = time.monotonic()
            pool.close(cancel=True)
            assert time.monotonic() - started < 5
            assert all(not child.is_alive() and child.exitcode is not None for child in children)
            assert not manager.is_alive()
            assert not pool._futures
        finally:
            # Also reap on the deliberately failing pre-fix run; never leak test children.
            for child in children:
                if child.is_alive():
                    child.kill()
                child.join(timeout=5)
            executor.shutdown(wait=True, cancel_futures=True)


def test_owner_retains_pool_if_bounded_shutdown_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace

    _write_synthetic_reports(tmp_path / "reports", 2)
    thread = ParseReportsThread(_plan(tmp_path / "reports", tmp_path / "db.sqlite3"))

    def failed_close(**kwargs):
        raise RuntimeError("shutdown deadline")

    pool = SimpleNamespace(close=failed_close)
    thread._prepare_pool = pool
    thread.stop_parsing()
    with pytest.raises(RuntimeError, match="shutdown deadline"):
        thread._close_prepare_pool()
    assert thread._prepare_pool is pool
    thread._prepare_pool = None


def test_packaged_windows_build_uses_separate_defaults_and_explicit_override(monkeypatch):
    monkeypatch.setattr(import_prepare_pool, "compute_workers_available", lambda: True)
    monkeypatch.delenv(WORKERS_ENV, raising=False)
    monkeypatch.delenv(MIN_REPORTS_ENV, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    # Import workers are opt-in in the packaged Windows app (#1136 evidence, run 39151254630).
    assert resolve_prepare_worker_count(199) == 0
    assert resolve_prepare_worker_count(200) == 0
    assert resolve_prepare_worker_count(5000) == 0
    monkeypatch.setenv(WORKERS_ENV, "3")
    assert resolve_prepare_worker_count(199) == 0
    assert resolve_prepare_worker_count(5000) == 3


def test_prepare_executor_uses_shared_compute_context(monkeypatch):
    context, calls = object(), []
    monkeypatch.setattr(import_prepare_pool, 'spawn_context', lambda: context)

    class Executor:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def shutdown(self, **kwargs):
            pass

    monkeypatch.setattr(import_prepare_pool, 'ProcessPoolExecutor', Executor)
    pool = ImportPreparePool([], database_path='unused', metadata_parsing_mode='light',
                             workers=2, parser_plugin_id='builtin')
    pool.close()
    assert calls[0]['mp_context'] is context


def _partially_transmitted_prepare_worker(task):
    """Write a real result frame header and prefix, then block mid-transmission."""
    import multiprocessing.connection
    import struct
    import time

    marker = Path(task[0]).with_suffix(".sending")

    def partial_send(connection, buffer):
        connection._send(struct.pack("!i", len(buffer)))
        connection._send(buffer[:128])
        marker.write_text("partial result sent")
        while True:
            time.sleep(60)

    multiprocessing.connection.Connection._send_bytes = partial_send
    return {"state": {"large": bytes(4 * 1024 * 1024)}}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX framed result-pipe regression")
def test_run_cancel_during_partial_result_reaps_manager_and_cleans_inputs(tmp_path, monkeypatch):
    from threading import Event
    import time
    from types import SimpleNamespace

    _write_synthetic_reports(tmp_path / "reports", 2)
    _pool_env(monkeypatch, "2")
    thread = ParseReportsThread(_plan(tmp_path / "reports", tmp_path / "db.sqlite3"))
    receiving = Event()
    owned = {}
    cleaned = []
    errors = []
    monkeypatch.setattr(thread, "log_and_exit", errors.append)
    monkeypatch.setattr(
        import_prepare_pool, "prepare_cmm_report_in_worker", _partially_transmitted_prepare_worker
    )
    original_executor = import_prepare_pool.ProcessPoolExecutor

    def make_executor(**kwargs):
        executor = original_executor(**kwargs)
        reader = executor._result_queue._reader
        original_recv = reader._recv

        def receiving_body(size, *args):
            if size > 1024 * 1024:
                receiving.set()
            return original_recv(size, *args)

        reader._recv = receiving_body
        owned["executor"] = executor
        owned["result_writer"] = executor._result_queue._writer
        return executor

    monkeypatch.setattr(import_prepare_pool, "ProcessPoolExecutor", make_executor)
    original_open = thread._open_prepare_pool

    def open_and_cancel(items):
        pool = original_open(items)
        executor = pool._executor
        owned["children"] = list(executor._processes.values())
        owned["manager"] = executor._executor_manager_thread
        assert receiving.wait(15), "manager must enter reception of the large frame body"
        deadline = time.monotonic() + 5
        while not list((tmp_path / "reports").glob("*.sending")) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert list((tmp_path / "reports").glob("*.sending")), "worker must send a partial body"
        thread._extracted_archive_dir = SimpleNamespace(cleanup=lambda: cleaned.append(True))
        thread.stop_parsing()
        return pool

    monkeypatch.setattr(thread, "_open_prepare_pool", open_and_cancel)
    try:
        thread.run()
        assert not errors
        assert not owned["manager"].is_alive()
        assert all(not child.is_alive() and child.exitcode is not None for child in owned["children"])
        assert thread._prepare_pool is None
        assert thread._extracted_archive_dir is None and cleaned == [True]
        assert thread._resolved_report_root is None
        result = thread.last_parse_result
        assert (result.imported_files, result.failed_files, result.cancelled_files) == (0, 0, 2)
    finally:
        # Rescue the pre-fix failure without leaving a blocked manager at interpreter exit.
        for child in owned.get("children", ()):
            if child.is_alive():
                child.kill()
            child.join(timeout=5)
        executor = owned.get("executor")
        if executor is not None:
            owned["result_writer"].close()
            executor.shutdown(wait=True, cancel_futures=True)
        thread._prepare_pool = None


def test_run_handles_shutdown_failure_and_retains_inputs_until_retry(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from metroliza.parsing import parse_reports_thread

    _write_synthetic_reports(tmp_path / "reports", 2)
    thread = ParseReportsThread(_plan(tmp_path / "reports", tmp_path / "db.sqlite3"))
    errors, cleaned, finished, failed = [], [], [], []
    diagnostic = SimpleNamespace(
        stage=lambda *args, **kwargs: None,
        fail=failed.append,
        finish_import=lambda *args: finished.append(True),
    )
    monkeypatch.setattr(parse_reports_thread, "start_workflow_trace", lambda *args: diagnostic)
    monkeypatch.setattr(thread, "log_and_exit", errors.append)

    def failed_close(**kwargs):
        raise RuntimeError("shutdown deadline")

    pool = SimpleNamespace(close=failed_close)
    archive = SimpleNamespace(cleanup=lambda: cleaned.append(True))
    thread._prepare_pool = pool
    thread._extracted_archive_dir = archive
    thread.stop_parsing()
    thread.run()

    assert len(errors) == 1 and str(errors[0]) == "shutdown deadline"
    assert failed and finished == [True]
    assert thread._prepare_pool is pool and thread._extracted_archive_dir is archive
    assert not cleaned
    pool.close = lambda **kwargs: None
    thread._finish_import_resources(diagnostic)
    assert thread._prepare_pool is None and thread._extracted_archive_dir is None
    assert cleaned == [True]
