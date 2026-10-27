"""Opt-in owner-thread persistence timings, without paths, parameters or report content."""

from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import lru_cache, wraps
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
from time import perf_counter


_ACTIVE = ContextVar("import_persist_profile", default=None)
# Normalize literals/comments before aggregation. Never use SQLite's expanded
# trace_callback SQL: it contains bound report data, and cannot measure duration.
_SQL_LITERALS = re.compile(r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\b\d+(?:\.\d+)?\b", re.S)
_FS_NAMES = frozenset((
    "stat", "lstat", "fstat", "open", "read", "write", "close", "access",
    "listdir", "scandir", "readlink", "fsync", "fdatasync", "unlink", "rename",
    "replace", "mkdir", "rmdir", "getcwd", "_getfullpathname", "_getfinalpathname",
))
_IO_NAMES = frozenset(("read", "readinto", "readline", "write", "flush", "close", "seek", "__exit__"))

_PYTHON_ACTIVITIES = {
    Path.resolve.__code__: ("filesystem", "Path.resolve"),
    json.dumps.__code__: ("python", "json.dumps"),
}


@lru_cache(maxsize=512)
def _sql_template(sql):
    return " ".join(_SQL_LITERALS.sub("?", sql).split()).upper()


def _native_activity(function):
    """Names only; never retain arguments, filenames, buffers or exceptions."""
    name = getattr(function, "__name__", "")
    module = getattr(function, "__module__", "")
    if module in ("posix", "nt", "io", "_io") and name in _FS_NAMES:
        return "filesystem", name
    if name in _IO_NAMES and isinstance(getattr(function, "__self__", None), io.IOBase):
        return "filesystem", f"file.{name}"
    if module == "_sqlite3" and name == "connect":
        return "sqlite", "connection_open"
    if module == "time" and name == "sleep":
        return "sleep", "time.sleep"
    return None


class ImportPersistProfile:
    """Inclusive stages plus a non-overlapping wall-clock partition of persist.

    Python gaps include interpreter/instrumentation overhead and scheduling time;
    they are not a CPU-time claim. Python filesystem calls are observed using an
    owner-thread sys profiler, with no global monkeypatches. SQLite's internal
    filesystem I/O and busy-handler waits remain within the SQL/commit/checkpoint
    call that performs them. BEGIN IMMEDIATE is reported separately. Automatic
    checkpoints remain in commit; explicit passive and final close are separate.
    """

    def __init__(self):
        self.seconds = defaultdict(float)
        self.calls = Counter()
        self.sqlite_settings = Counter()
        self.checkpoint_results = Counter()
        self.activities = defaultdict(float)
        self.activity_calls = Counter()
        self.sql_seconds = defaultdict(float)
        self.sql_calls = Counter()
        self.sql_errors = Counter()
        self.sqlite_errors = Counter()
        self._stack = []
        self._last = 0.0
        self._traced = []

    @contextmanager
    def activate(self):
        token = _ACTIVE.set(self)
        previous = sys.getprofile()
        sys.setprofile(self._trace)
        try:
            yield self
        finally:
            sys.setprofile(previous)
            _ACTIVE.reset(token)

    def _switch(self, now):
        if self._stack:
            self.activities[self._stack[-1]] += now - self._last
        self._last = now

    def _enter(self, key, now):
        self._switch(now)
        self._stack.append(key)
        self.activity_calls[key] += 1

    def _leave(self, now):
        self._switch(now)
        self._stack.pop()

    def _trace(self, frame, event, argument):
        if not self._stack:
            return
        if event == "call":
            key = _PYTHON_ACTIVITIES.get(frame.f_code)
            if key is not None:
                self._enter(key, perf_counter())
                self._traced.append((id(frame), None))
        elif event == "return":
            if self._traced and self._traced[-1] == (id(frame), None):
                self._leave(perf_counter())
                self._traced.pop()
        elif event == "c_call":
            key = _native_activity(argument)
            if key is not None:
                self._enter(key, perf_counter())
                self._traced.append((id(frame), argument))
        elif event in ("c_return", "c_exception"):
            if self._traced and self._traced[-1] == (id(frame), argument):
                self._leave(perf_counter())
                self._traced.pop()

    @contextmanager
    def activity(self, category, name):
        active = bool(self._stack)
        if active:
            self._enter((category, name), perf_counter())
        try:
            yield
        finally:
            if active:
                self._leave(perf_counter())

    @contextmanager
    def measure(self, stage):
        started = perf_counter()
        root = stage == "persist" and not self._stack
        if root:
            self._enter(("python", "between_operations"), started)
        try:
            # Stages are inclusive; nested I/O/SQL is subtracted in activities.
            with (nullcontext() if root else self.activity("python", stage)):
                yield
        finally:
            ended = perf_counter()
            if root:
                self._leave(ended)
            self.seconds[stage] += ended - started
            self.calls[stage] += 1

    @contextmanager
    def sql(self, method, statement):
        template = _sql_template(statement)
        key = (method, template)
        category = "begin_immediate" if template.rstrip(";") == "BEGIN IMMEDIATE" else "sql"
        started = perf_counter()
        try:
            with self.activity(category, f"{method}: {template}"):
                yield
        except BaseException as exc:
            self.sql_errors[key] += 1
            if isinstance(exc, sqlite3.Error):
                self.sqlite_errors[getattr(exc, "sqlite_errorname", "unknown")] += 1
            raise
        finally:
            self.sql_seconds[key] += perf_counter() - started
            self.sql_calls[key] += 1

    def observe_connection(self, connection):
        settings = tuple(connection.execute(f"PRAGMA {name}").fetchone()[0] for name in (
            "journal_mode", "synchronous", "wal_autocheckpoint",
        ))
        self.sqlite_settings[settings] += 1

    def receipt(self):
        persist = self.seconds.get("persist", 0.0)
        attributed = sum(self.activities.values())
        return {
            "seconds": dict(self.seconds), "calls": dict(self.calls),
            "attribution": {
                "persist_s": persist, "attributed_s": attributed,
                "unattributed_s": persist - attributed,
                "activities": [
                    dict(category=category, operation=name, seconds=seconds, calls=self.activity_calls[key])
                    for key, seconds in sorted(self.activities.items())
                    for category, name in (key,)
                ],
                "scope": "exclusive wall time inside persist; Python includes observer overhead and scheduling; "
                         "SQLite internal I/O/busy waits included in enclosing call",
            },
            "sqlite_errors": dict(self.sqlite_errors),
            "sql_scope": "all profiled calls, including setup/close outside persist; inclusive durations",
            "sql": [
                dict(method=method, template=template, seconds=seconds,
                     calls=self.sql_calls[key], errors=self.sql_errors[key])
                for key, seconds in sorted(self.sql_seconds.items())
                for method, template in (key,)
            ],
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


def _activity(category, name):
    profile = _ACTIVE.get()
    return profile.activity(category, name) if profile is not None else nullcontext()


def observe_persist_connection(connection):
    profile = _ACTIVE.get()
    if profile is not None:
        profile.observe_connection(connection)


def observe_persist_checkpoint(result):
    profile = _ACTIVE.get()
    if profile is not None:
        profile.checkpoint_results[tuple(result)] += 1


class _ProfiledCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        with _sql_scope("execute", sql):
            return super().execute(sql, parameters)

    def executemany(self, sql, parameters):
        with measure_persist_stage("executemany"), _sql_scope("executemany", sql):
            return super().executemany(sql, parameters)

    def executescript(self, sql):
        with _sql_scope("executescript", sql):
            return super().executescript(sql)

    def fetchone(self):
        with _activity("sqlite", "fetchone"):
            return super().fetchone()

    def fetchall(self):
        with _activity("sqlite", "fetchall"):
            return super().fetchall()

    def fetchmany(self, *args):
        with _activity("sqlite", "fetchmany"):
            return super().fetchmany(*args)

    def __next__(self):
        with _activity("sqlite", "cursor_next"):
            return super().__next__()

    def close(self):
        with _activity("sqlite", "cursor_close"):
            return super().close()


def _sql_scope(method, sql):
    profile = _ACTIVE.get()
    return profile.sql(method, sql) if profile is not None else nullcontext()


class _ProfiledConnection(sqlite3.Connection):
    def cursor(self, factory=_ProfiledCursor):
        with _activity("sqlite", "cursor_create"):
            return super().cursor(factory)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters):
        return self.cursor().executemany(sql, parameters)

    def executescript(self, sql):
        return self.cursor().executescript(sql)

    def commit(self):
        with _activity("sqlite", "commit"):
            return super().commit()

    def rollback(self):
        with _activity("sqlite", "rollback"):
            return super().rollback()

    def close(self):
        with _activity("sqlite", "checkpoint_close"):
            return super().close()


def persist_sqlite_options(*, cursor=False):
    """Keep normal connections/cursors untouched unless explicitly profiling."""
    factory = _ProfiledCursor if cursor else _ProfiledConnection
    return {"factory": factory} if _ACTIVE.get() is not None else {}


def close_persist_connection(connection):
    with measure_persist_stage("checkpoint_close"):
        connection.close()
