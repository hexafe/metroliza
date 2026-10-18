"""Bounded process pool for the CPU-bound preparation of a large report import (#1125).

Only the parse work (PDF open, tokenising, tolerances, metadata selection, row
normalisation) runs in worker processes. Parser resolution, source approval, the single
content verification and all SQLite persistence stay on the importing thread, which still
visits the reports in their original deterministic order. A worker that fails, times out
or dies never decides anything: that report is simply prepared in-process by the existing
code path, so error, cancellation and progress semantics are unchanged.

This module must stay Qt-free: workers are spawned (never forked) and import it fresh.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
import logging
from multiprocessing import get_context
import os
import sys
from typing import Callable, Sequence

from metroliza.shared.env_utils import env_int, env_value

logger = logging.getLogger(__name__)

WORKERS_ENV = "METROLIZA_IMPORT_PREPARE_WORKERS"
MIN_REPORTS_ENV = "METROLIZA_IMPORT_PREPARE_MIN_REPORTS"
DEFAULT_MIN_REPORTS = 64
MAX_AUTO_WORKERS = 3
MAX_EXPLICIT_WORKERS = 16
INFLIGHT_PER_WORKER = 3
_RESULT_POLL_SECONDS = 0.2


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resolve_prepare_worker_count(report_count: int) -> int:
    """Return the worker-process count for a batch; 0 means prepare in-process.

    ``METROLIZA_IMPORT_PREPARE_WORKERS`` is ``auto`` (default), ``0`` (disabled) or an
    explicit count. Small batches stay serial because process start-up would dominate.
    Frozen builds always stay serial until a supported worker executable has
    supervised packaged-startup qualification evidence (#1134).
    """

    if _is_frozen():
        return 0
    configured = (env_value(WORKERS_ENV) or "auto").lower()
    try:
        minimum = max(2, env_int(MIN_REPORTS_ENV, default=DEFAULT_MIN_REPORTS) or DEFAULT_MIN_REPORTS)
    except ValueError:
        minimum = DEFAULT_MIN_REPORTS
    if report_count < minimum:
        return 0
    if configured != "auto":
        try:
            return max(0, min(int(configured), MAX_EXPLICIT_WORKERS, report_count))
        except ValueError:
            return 0
    workers = min(MAX_AUTO_WORKERS, (os.cpu_count() or 1) - 1)
    return workers if workers >= 2 else 0


_WORKER_PARSER_CLASS = None


def _worker_parser_class():
    """Return the CMM parser variant used in workers; failures are logged by the owner."""

    global _WORKER_PARSER_CLASS
    if _WORKER_PARSER_CLASS is None:
        from metroliza.parsing.cmm_report_parser import CMMReportParser

        class _WorkerCMMReportParser(CMMReportParser):
            def log_and_exit(self, exception):
                raise exception

        _WORKER_PARSER_CLASS = _WorkerCMMReportParser
    return _WORKER_PARSER_CLASS


def initialize_prepare_worker() -> None:
    """Quiet, low-priority, core-dump-free worker start-up (the owner logs failures)."""

    logging.disable(logging.CRITICAL)
    try:
        os.nice(5)
    except (AttributeError, OSError):
        pass
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass
    _worker_parser_class()


def prepare_cmm_report_in_worker(task: tuple[str, str, str]) -> dict[str, object]:
    """Run the CPU-bound CMM report preparation for one source and return its state."""

    from metroliza.parsing.source_inspection import source_stat_signature

    source_path, database_path, metadata_parsing_mode = task
    stat_before = source_stat_signature(source_path)
    parser = _worker_parser_class()(
        source_path,
        database_path,
        connection=None,
        metadata_parsing_mode=metadata_parsing_mode,
    )
    parser.prepare_for_two_stage_pipeline()
    return {
        "state": parser.export_prepared_state(),
        "stat_before": stat_before,
        "stat_after": source_stat_signature(source_path),
    }


def accepted_worker_state(result, inspection) -> dict[str, object] | None:
    """Return a worker's prepared state only if the file stayed untouched while it was parsed.

    The worker's ``(size, mtime_ns)`` before and after parsing must equal each other and the
    signature of the importer's own inspection; otherwise the report is parsed again
    in-process. (The content hash verified right before persistence is the final authority.)
    """

    reviewed = (inspection.file_size_bytes, inspection.file_modified_ns)
    if not (result["stat_before"] == result["stat_after"] == reviewed):
        return None
    return result["state"]


class ImportPreparePool:
    """Prefetch report preparation in worker processes, consumed in submission order."""

    def __init__(
        self,
        report_paths: Sequence[str],
        *,
        database_path: str,
        metadata_parsing_mode: str,
        workers: int,
        parser_plugin_id: str,
        should_cancel: Callable[[], bool] = lambda: False,
    ) -> None:
        self._paths = [str(path) for path in report_paths]
        self._index = {path: position for position, path in enumerate(self._paths)}
        self._database_path = str(database_path)
        self._mode = str(metadata_parsing_mode)
        self._parser_plugin_id = parser_plugin_id
        self._should_cancel = should_cancel
        self._window = max(2, int(workers)) * INFLIGHT_PER_WORKER
        self._futures: dict[int, object] = {}
        self._next_to_submit = 0
        self._broken = False
        self._executor = ProcessPoolExecutor(
            max_workers=int(workers),
            mp_context=get_context("spawn"),
            initializer=initialize_prepare_worker,
        )
        self._refill(0)

    def _refill(self, position: int) -> None:
        while (
            not self._broken
            and self._next_to_submit < len(self._paths)
            and self._next_to_submit < position + self._window
            and not self._should_cancel()
        ):
            index = self._next_to_submit
            self._next_to_submit += 1
            try:
                self._futures[index] = self._executor.submit(
                    prepare_cmm_report_in_worker,
                    (self._paths[index], self._database_path, self._mode),
                )
            except Exception:  # pool is broken or shut down: stay in-process
                self._broken = True

    def _drop_before(self, position: int) -> None:
        for index in [i for i in self._futures if i < position]:
            self._futures.pop(index).cancel()

    def _result(self, future):
        while True:
            try:
                return future.result(timeout=_RESULT_POLL_SECONDS)
            except FutureTimeoutError:
                if self._should_cancel():
                    return None
            except Exception as exc:
                self._broken = self._broken or isinstance(exc, BrokenProcessPool)
                logger.debug("Import prepare worker failed: %s", type(exc).__name__)
                return None

    def _eligible(self, prepared) -> bool:
        from metroliza.parsing.cmm_report_parser import CMMReportParser

        evidence = getattr(prepared, "resolution_evidence", None)
        parser = prepared.parser
        return (
            type(parser) is CMMReportParser
            and evidence is not None
            and evidence.plugin_id == self._parser_plugin_id
            and getattr(parser, "metadata_parsing_mode", None) == self._mode
        )

    def apply_to(self, work_item, prepared) -> bool:
        """Hydrate ``prepared.parser`` from its worker result; False means prepare in-process."""

        position = self._index.get(str(work_item.report_path))
        if position is None:
            return False
        self._drop_before(position)
        self._refill(position)
        future = self._futures.pop(position, None)
        if future is None or not self._eligible(prepared):
            if future is not None:
                future.cancel()
            return False
        result = self._result(future)
        if result is None:
            return False
        state = accepted_worker_state(result, prepared.source_inspection)
        if state is None:
            return False
        try:
            prepared.parser.apply_prepared_state(state)
        except (KeyError, TypeError, ValueError):
            return False
        return True

    def close(self, *, cancel: bool = False) -> None:
        for future in self._futures.values():
            future.cancel()
        self._futures.clear()
        self._executor.shutdown(wait=not cancel, cancel_futures=True)
