"""Opt-in, owner-context persistence timings; no paths or report content in receipts."""

from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
from time import perf_counter


_ACTIVE = ContextVar("import_persist_profile", default=None)


class ImportPersistProfile:
    """Aggregate bounded stage totals, including failed/retried attempts.

    Stages are inclusive. ``checkpoint`` measures explicit passive checkpoints
    after import commits. ``checkpoint_close`` times connection close, including
    SQLite's last-connection WAL checkpoint. Automatic checkpoints cannot be
    separated from commit using Python's SQLite API and remain in ``commit``.
    Neither profiling nor connection reuse changes the checkpoint PRAGMAs.
    """

    def __init__(self):
        self.seconds = defaultdict(float)
        self.calls = Counter()
        self.sqlite_settings = Counter()
        self.checkpoint_results = Counter()

    @contextmanager
    def activate(self):
        token = _ACTIVE.set(self)
        try:
            yield self
        finally:
            _ACTIVE.reset(token)

    @contextmanager
    def measure(self, stage):
        started = perf_counter()
        try:
            yield
        finally:
            self.seconds[stage] += perf_counter() - started
            self.calls[stage] += 1

    def observe_connection(self, connection):
        settings = tuple(connection.execute(f"PRAGMA {name}").fetchone()[0] for name in (
            "journal_mode", "synchronous", "wal_autocheckpoint",
        ))
        self.sqlite_settings[settings] += 1

    def receipt(self):
        return {
            "seconds": dict(self.seconds),
            "calls": dict(self.calls),
            "sqlite_settings": [
                dict(journal_mode=mode, synchronous=sync, wal_autocheckpoint=pages, connections=count)
                for (mode, sync, pages), count in sorted(self.sqlite_settings.items())
            ],
            "checkpoint_accounting": "close includes final checkpoint; auto-checkpoint included in commit",
            "passive_checkpoints": [
                dict(busy=busy, wal_frames=frames, checkpointed_frames=written, calls=count)
                for (busy, frames, written), count in sorted(self.checkpoint_results.items())
            ],
        }


def persist_stage(stage):
    """Time a stage only when a benchmark explicitly activates a profile."""
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            with measure_persist_stage(stage):
                return function(*args, **kwargs)
        return measured
    return decorate


def measure_persist_stage(stage):
    profile = _ACTIVE.get()
    return profile.measure(stage) if profile is not None else nullcontext()


def observe_persist_connection(connection):
    profile = _ACTIVE.get()
    if profile is not None:
        profile.observe_connection(connection)


def observe_persist_checkpoint(result):
    profile = _ACTIVE.get()
    if profile is not None:
        profile.checkpoint_results[tuple(result)] += 1


class _ProfiledCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def executemany(self, *args, **kwargs):
        with measure_persist_stage("executemany"):
            return self._cursor.executemany(*args, **kwargs)


def profile_persist_cursor(cursor):
    return _ProfiledCursor(cursor) if _ACTIVE.get() is not None else cursor


def close_persist_connection(connection):
    with measure_persist_stage("checkpoint_close"):
        connection.close()
