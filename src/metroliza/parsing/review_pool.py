"""Process pool for "Review reports": file inspection and the quick metadata read (#1148 C2).

The workers run the same per-file code as the in-process path
(``ParsePreflightService._inspect_file`` and ``metadata_review.read_metadata_one``) on
chunks of files; the owner consumes the chunks in input order, so every rule that depends
on order (duplicates in the selected source, progress, cancellation between files) is
still applied serially by the caller.

Registry consistency: parser-registry generation ids are per-process counters, so a
worker's ids mean nothing to the parent.  The parent sends the deterministic
configuration fingerprint of its registry
(``report_parser_factory.registry_configuration_fingerprint``) with every chunk; the
worker checks it before working, checks it again afterwards and returns it.  The parent
accepts a chunk only when the returned fingerprint matches and its own registry is still
at the generation the fingerprint was taken from, and then stamps its own generation id.
Any mismatch, worker error or dead pool sends the affected chunk through the in-process
path instead, so generations are never mixed and a stale generation is never approved.

Packaged Windows: off unless ``METROLIZA_REVIEW_WORKERS`` enables it (see
``metroliza.shared.compute_budget.review_workers``).

This module must stay Qt-free: workers are spawned (never forked) and import it fresh.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
import logging
import os
from pathlib import Path
from typing import Callable, Iterator, Sequence

from metroliza.parsing import report_parser_factory
from metroliza.shared.compute_budget import review_workers
from metroliza.shared.compute_worker import compute_workers_available, spawn_context

logger = logging.getLogger(__name__)

CHUNK_SIZE = 24
INFLIGHT_PER_WORKER = 2
_RESULT_POLL_SECONDS = 0.05

_WORKER_EXISTING_FINGERPRINTS: frozenset[str] = frozenset()


def resolve_review_worker_count(file_count: int) -> int:
    """Worker processes for ``file_count`` files; 0 means in-process (compute budget rules)."""

    return review_workers(file_count, available=compute_workers_available)


def registry_state() -> tuple[int, str]:
    """Return this process's current registry generation and configuration fingerprint."""

    snapshot = report_parser_factory.get_registry_snapshot()
    return (
        snapshot.generation_id,
        report_parser_factory.registry_configuration_fingerprint(snapshot),
    )


def initialize_review_worker(existing_fingerprints: frozenset[str] = frozenset()) -> None:
    """Quiet, low-priority, core-dump-free worker start-up with a warm parser registry."""

    global _WORKER_EXISTING_FINGERPRINTS

    from metroliza.shared.compute_worker import initialize_compute_runtime

    initialize_compute_runtime()
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
    _WORKER_EXISTING_FINGERPRINTS = frozenset(existing_fingerprints)
    report_parser_factory.get_registry_snapshot()


def inspect_chunk_in_worker(task):
    """Inspect ``(path, display_name)`` entries; returns ``(fingerprint, generation, items, probes)``.

    ``items`` is ``None`` when the worker's registry does not match the expected
    fingerprint or changed while the chunk ran.
    """

    from metroliza.parsing.preflight import ParsePreflightService

    expected_fingerprint, entries = task
    generation, fingerprint = registry_state()
    if fingerprint != expected_fingerprint:
        return fingerprint, generation, None, ()
    items = tuple(
        ParsePreflightService._inspect_file(
            Path(path),
            display_name=display_name,
            existing_fingerprints=_WORKER_EXISTING_FINGERPRINTS,
        )
        for path, display_name in entries
    )
    if registry_state() != (generation, fingerprint):
        return "", generation, None, ()
    return fingerprint, generation, items, report_parser_factory.export_probe_cache_entries(
        tuple(path for path, _name in entries), generation_id=generation,
    )


def read_metadata_chunk_in_worker(task):
    """Read quick metadata for ``(item, path)`` entries; returns ``(fingerprint, generation, readings, probes)``.

    The parent sends only items approved at its own generation; they are re-bound to this
    worker's generation (same fingerprint, so the same registry) before parser resolution.
    """

    from metroliza.parsing.metadata_review import read_metadata_one

    expected_fingerprint, database_path, mode, entries = task
    generation, fingerprint = registry_state()
    if fingerprint != expected_fingerprint:
        return fingerprint, generation, None, ()
    readings = tuple(
        read_metadata_one(
            replace(item, registry_generation_id=generation),
            None if path is None else Path(path),
            mode,
            database_path=database_path,
        )
        for item, path in entries
    )
    if registry_state() != (generation, fingerprint):
        return "", generation, None, ()
    return fingerprint, generation, readings, report_parser_factory.export_probe_cache_entries(
        tuple(path for _item, path in entries if path is not None), generation_id=generation,
    )


def _stop_executor(executor) -> None:
    from metroliza.parsing.import_prepare_pool import _cancel_prepare_executor

    try:
        _cancel_prepare_executor(executor)
    except Exception:  # noqa: BLE001 - shutdown must not mask the caller's result
        logger.warning("Review pool did not stop cleanly.")


class OrderedChunkPool:
    """Run ``function(task)`` for each task in worker processes; results in task order.

    ``results()`` yields ``(index, value)`` where ``value`` is ``None`` when the chunk must
    be processed in-process (worker error, dead pool, abandoned pool).  It stops early when
    ``should_cancel`` turns true; the owner then sees the cancellation itself.
    """

    def __init__(
        self,
        function: Callable,
        tasks: Sequence[object],
        *,
        workers: int,
        should_cancel: Callable[[], bool],
        initializer: Callable | None = None,
        initargs: tuple = (),
    ) -> None:
        self.completion_metadata = {"review_pool": {
            "mode": "spawn", "workers": int(workers), "fallback_reason": None,
        }}
        self.telemetry = self.completion_metadata["review_pool"]
        self._function = function
        self._tasks = list(tasks)
        self._should_cancel = should_cancel
        self._window = max(1, int(workers)) * INFLIGHT_PER_WORKER
        self._futures: dict[int, object] = {}
        self._next_to_submit = 0
        self._usable = True
        self._closed = False
        self._executor = ProcessPoolExecutor(
            max_workers=int(workers),
            mp_context=spawn_context(),
            initializer=initializer,
            initargs=initargs,
        )

    def _refill(self, position: int) -> None:
        while (
            self._usable
            and self._next_to_submit < len(self._tasks)
            and self._next_to_submit < position + self._window
        ):
            index = self._next_to_submit
            self._next_to_submit += 1
            try:
                self._futures[index] = self._executor.submit(self._function, self._tasks[index])
            except Exception as exc:  # noqa: BLE001 - the rest runs in-process
                self._record_fallback("submit_failure", exc)
                self._usable = False

    def _wait(self, future):
        while True:
            if self._should_cancel():
                raise _Cancelled()
            try:
                return future.result(timeout=_RESULT_POLL_SECONDS)
            except FutureTimeoutError:
                continue
            except BrokenProcessPool as exc:
                self._record_fallback("broken_process_pool", exc)
                self._usable = False
                return None
            except Exception as exc:  # noqa: BLE001 - a failed chunk is redone in-process
                self._record_fallback("worker_failure", exc)
                return None

    def _record_fallback(self, reason: str, exc: Exception | None = None) -> None:
        self.telemetry["mode"] = "serial_fallback"
        if self.telemetry["fallback_reason"] is None:
            self.telemetry["fallback_reason"] = reason
            if exc is not None:
                self.telemetry["exception_class"] = type(exc).__name__

    def abandon(self) -> None:
        """Stop using the workers; every later chunk runs in-process."""

        self._usable = False
        self.close(cancel=True)

    def results(self) -> Iterator[tuple[int, object]]:
        for index in range(len(self._tasks)):
            self._refill(index)
            future = self._futures.pop(index, None)
            if future is None:
                yield index, None
                continue
            try:
                value = self._wait(future)
            except _Cancelled:
                self.close(cancel=True)
                return
            yield index, value

    def close(self, *, cancel: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        for future in self._futures.values():
            future.cancel()
        self._futures.clear()
        try:
            if cancel:
                _stop_executor(self._executor)
            else:
                self._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            logger.info("Review pool completed: %s", self.telemetry,
                        extra={"completion_metadata": self.completion_metadata})


class _Cancelled(Exception):
    pass


def _chunks(values: Sequence) -> list[Sequence]:
    size = max(1, int(CHUNK_SIZE))
    return [values[start:start + size] for start in range(0, len(values), size)]


def inspect_in_order(
    discovered: Sequence[tuple[Path, str]],
    *,
    existing_fingerprints: frozenset[str],
    workers: int,
    should_cancel: Callable[[], bool],
    inspect_serial: Callable,
) -> Iterator:
    """Yield the inspection of every discovered file in input order.

    Chunks that the workers cannot deliver under the parent's registry configuration are
    inspected by ``inspect_serial`` (the in-process path) in the parent.  The generator
    ends early only when ``should_cancel`` turned true while it waited for a worker; the
    caller checks cancellation between files itself.
    """

    generation, fingerprint = registry_state()
    chunks = _chunks(list(discovered))
    pool = OrderedChunkPool(
        inspect_chunk_in_worker,
        [(fingerprint, tuple((str(path), name) for path, name in chunk)) for chunk in chunks],
        workers=workers,
        should_cancel=should_cancel,
        initializer=initialize_review_worker,
        initargs=(frozenset(existing_fingerprints),),
    )
    finished = False
    try:
        for index, value in pool.results():
            items = _accepted(value, fingerprint, generation, pool)
            if items is None:
                for path, display_name in chunks[index]:
                    yield inspect_serial(path, display_name)
                continue
            yield from (
                item if item.registry_generation_id is None
                else replace(item, registry_generation_id=generation)
                for item in items
            )
        finished = True
    finally:
        # Anything but a complete run (cancel, early close, error) reaps the workers.
        pool.close(cancel=not finished)


def _accepted(value, fingerprint: str, generation: int, pool: OrderedChunkPool):
    """Return a worker chunk's items when they may carry the parent's generation, else ``None``."""

    if value is None:
        return None
    worker_fingerprint, worker_generation, items, probes = value
    if items is None or worker_fingerprint != fingerprint:
        pool._record_fallback("registry_fingerprint_mismatch")
        pool.abandon()
        return None
    if report_parser_factory.get_registry_snapshot().generation_id != generation:
        # The parent's registry moved on: the in-process path stamps the new generation.
        pool._record_fallback("parent_registry_generation_changed")
        pool.abandon()
        return None
    if any(
        getattr(item, "registry_generation_id", None) not in (None, worker_generation)
        for item in items
    ):
        pool._record_fallback("worker_registry_generation_mismatch")
        return None
    report_parser_factory.seed_probe_cache_entries(
        probes, generation_id=generation, fingerprint=fingerprint,
    )
    return items


def read_metadata_in_order(
    entries: Sequence[tuple[object, Path | None]],
    *,
    mode: str,
    database_path: str,
    workers: int,
    should_cancel: Callable[[], bool],
    read_serial: Callable,
) -> Iterator:
    """Yield one metadata reading per ``(item, path)`` entry in input order.

    Only chunks whose items were all approved at the parent's current generation go to the
    workers; any other chunk, and every chunk a worker cannot deliver, is read by
    ``read_serial`` in the parent.
    """

    generation, fingerprint = registry_state()
    chunks = _chunks(list(entries))
    eligible = [
        all(getattr(item, "registry_generation_id", None) == generation for item, _path in chunk)
        for chunk in chunks
    ]
    pool_chunks = [index for index, ok in enumerate(eligible) if ok]
    pool = OrderedChunkPool(
        read_metadata_chunk_in_worker,
        [
            (
                fingerprint,
                str(database_path),
                mode,
                tuple((item, None if path is None else str(path)) for item, path in chunks[index]),
            )
            for index in pool_chunks
        ],
        workers=workers,
        should_cancel=should_cancel,
        initializer=initialize_review_worker,
    )
    pooled = iter(pool.results())
    finished = False
    try:
        for index, chunk in enumerate(chunks):
            readings = None
            if eligible[index]:
                try:
                    _position, value = next(pooled)
                except StopIteration:  # cancelled while waiting
                    return
                readings = _accepted(value, fingerprint, generation, pool)
            if readings is None:
                for item, path in chunk:
                    yield read_serial(item, path)
                continue
            yield from readings
        finished = True
    finally:
        pool.close(cancel=not finished)


__all__ = [
    "CHUNK_SIZE",
    "OrderedChunkPool",
    "initialize_review_worker",
    "inspect_chunk_in_worker",
    "inspect_in_order",
    "read_metadata_chunk_in_worker",
    "read_metadata_in_order",
    "registry_state",
    "resolve_review_worker_count",
]
