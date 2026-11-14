"""Bounded in-memory, content-free activity trace for copyable bug reports.

Only source-controlled action/category codes and an optional boolean state are
accepted. Do not add user values, paths, names, timestamps, exception text, or
diagnostic payloads to this module.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import queue
import re
import stat
import threading

from metroliza.shared import diagnostic_store as _diagnostic_store

MAX_EVENTS = 128
MAX_REPORT_BYTES = 16 * 1024
MAX_HISTORY_BYTES = 16 * 1024
MAX_WRITE_QUEUE = 128
BUG_REPORT_UNAVAILABLE = "Bug report could not be generated from safe diagnostic data."
_SAFE_RELEASE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:-(?:dev|rc)\.[0-9]{1,3})?\Z")
_COVERAGE_NOTE = (
    "Coverage: selected CSV workflow actions. "
    "Input data, paths, names, and configuration values are not included."
)
_HISTORY_NOTE = "Activity history: retained local activity may include earlier launches."
_SESSION_NOTE = "Session boundaries: unknown; prior activity is not evidence of a crash."
_ASYNC_NOTE = "Recent activity is queued asynchronously and may not survive forced exit."
_STAGE_NAME = re.compile(r"\.stage-[0-9a-f]{32}\.tmp\Z")


def _release_version(value: object) -> str:
    if type(value) is str and len(value) <= 40 and _SAFE_RELEASE.fullmatch(value):
        return value
    return "UNKNOWN"


class BugReportAction(str, Enum):
    APP_OPENED = "app_opened"
    CSV_OPENED = "csv_opened"
    CSV_LOAD_STARTED = "csv_load_started"
    CSV_LOAD_FINISHED = "csv_load_finished"
    CSV_LOAD_FAILED = "csv_load_failed"
    CSV_LOAD_CANCELLED = "csv_load_cancelled"
    FILTER_APPLIED = "filter_applied"
    GROUPING_APPLIED = "grouping_applied"
    OPTION_WORKBOOK = "option_workbook"
    OPTION_HTML = "option_html"
    OPTION_GROUPING = "option_grouping"
    OPTION_CHARTS = "option_charts"
    CHECK_CHARTS_PRESENT = "check_charts_present"
    CHECK_WORKBOOK_REQUEST_MATCH = "check_workbook_request_match"
    CHECK_FILTER_REQUEST_MATCH = "check_filter_request_match"
    CHECK_GROUPING_REQUEST_MATCH = "check_grouping_request_match"
    CHECK_CHART_REQUEST_MATCH = "check_chart_request_match"
    OUTPUT_WITHOUT_REQUESTED_CHARTS = "output_without_requested_charts"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_FINISHED = "analysis_finished"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_CANCELLED = "analysis_cancelled"
    EXPORT_STARTED = "export_started"
    EXPORT_FINISHED = "export_finished"
    EXPORT_FAILED = "export_failed"
    EXPORT_CANCELLED = "export_cancelled"
    PROBLEM_REPORTED = "problem_reported"


class BugReportCategory(str, Enum):
    WRONG_OUTPUT = "wrong_output"
    MISSING_OUTPUT = "missing_output"
    OPERATION_FAILED = "operation_failed"
    APP_UNRESPONSIVE = "app_unresponsive"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SafeBugReportEvent:
    action: BugReportAction
    enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class BugReportSnapshot:
    events: tuple[SafeBugReportEvent, ...]
    events_lost: bool
    previous_session_state: str = "unknown"
    clear_state: str | None = None


class PreviousSessionState(str, Enum):
    LOADING = "loading"
    AVAILABLE = "available"
    UNKNOWN = "unknown"
    NOT_AVAILABLE = "not_available"


class HistoryClearState(str, Enum):
    PENDING = "pending"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class _QueuedHistoryEvent:
    event: SafeBugReportEvent
    generation: int


@dataclass(frozen=True, slots=True)
class _ClearHistory:
    generation: int


class _StopHistoryWorker(Enum):
    STOP = "stop"


def _decode_history(data: bytes) -> tuple[tuple[SafeBugReportEvent, ...], bool]:
    """Parse only the exact bounded persisted schema; reject the whole file otherwise."""
    if type(data) is not bytes or len(data) > MAX_HISTORY_BYTES:
        raise ValueError("invalid_history")
    payload = json.loads(data.decode("ascii"))
    if type(payload) is not dict or set(payload) != {"schema", "events", "events_lost"}:
        raise ValueError("invalid_history")
    if type(payload["schema"]) is not int or payload["schema"] != 1:
        raise ValueError("invalid_history")
    if type(payload["events_lost"]) is not bool or type(payload["events"]) is not list:
        raise ValueError("invalid_history")
    if len(payload["events"]) > MAX_EVENTS:
        raise ValueError("invalid_history")
    result: list[SafeBugReportEvent] = []
    for raw in payload["events"]:
        if type(raw) is not dict or set(raw) != {"action", "enabled"}:
            raise ValueError("invalid_history")
        action, enabled = raw["action"], raw["enabled"]
        if type(action) is not str or enabled is not None and type(enabled) is not bool:
            raise ValueError("invalid_history")
        result.append(SafeBugReportEvent(BugReportAction(action), enabled))
    return tuple(result), payload["events_lost"]


class LocalBugReportHistoryStore:
    """Private, bounded history file. Its root must be explicitly injected."""

    _FILE_NAME = "activity.json"
    _LOCK_NAME = ".diagnostic-store.lock"

    def prepare_locked(self) -> bool:
        """Remove only owned, regular interrupted stage files; reject unknown entries."""
        try:
            with os.scandir(self.root) as entries:
                for index, entry in enumerate(entries):
                    if index >= 8:
                        return False
                    name = entry.name
                    if name == self._LOCK_NAME:
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if name == self._FILE_NAME:
                        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                                or _diagnostic_store._is_reparse_or_link(metadata)
                                or os.name != "nt" and metadata.st_uid != os.getuid()):
                            return False
                        continue
                    if _STAGE_NAME.fullmatch(name):
                        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                                or _diagnostic_store._is_reparse_or_link(metadata)
                                or os.name != "nt" and metadata.st_uid != os.getuid()):
                            return False
                        Path(entry.path).unlink()
                        continue
                    return False
            return True
        except OSError:
            return False

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def load_locked(self) -> tuple[tuple[SafeBugReportEvent, ...], bool]:
        path = self.root / self._FILE_NAME
        if not path.exists():
            return (), False
        return _decode_history(_diagnostic_store._safe_file_bytes(path, MAX_HISTORY_BYTES))

    def append_locked(
        self, event: SafeBugReportEvent, *, max_events: int, events_lost: bool = False
    ) -> bool:
        try:
            events, lost = self.load_locked()
            overflow = len(events) >= max_events
            events = (*events, event)[-max_events:]
            return self._replace_locked(events, lost or overflow or events_lost)
        except Exception:
            return False

    def clear_locked(self) -> bool:
        """Atomically replace only our controlled history file with an empty schema."""
        return self._replace_locked((), False)

    def _replace_locked(self, events: tuple[SafeBugReportEvent, ...], lost: bool) -> bool:
        stage = None
        try:
            path = self.root / self._FILE_NAME
            payload = {
                "schema": 1,
                "events": [
                    {"action": item.action.value, "enabled": item.enabled}
                    for item in events
                ],
                "events_lost": lost,
            }
            data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            if len(data) > MAX_HISTORY_BYTES:
                return False
            if path.exists():
                _diagnostic_store._safe_file_bytes(path, MAX_HISTORY_BYTES)
            stage = _diagnostic_store._write_stage(self.root, data)
            os.replace(stage, path)
            stage = None
            if os.name != "nt":
                descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return True
        except Exception:
            return False
        finally:
            if stage is not None:
                try:
                    stage.unlink(missing_ok=True)
                except OSError:
                    pass


class SafeBugReportRecorder:
    """Keep bounded activity in memory and optionally persist it off the caller thread."""

    def __init__(
        self,
        *,
        max_events: int = MAX_EVENTS,
        write_queue_size: int = MAX_WRITE_QUEUE,
    ) -> None:
        if type(max_events) is not int or not 1 <= max_events <= MAX_EVENTS:
            raise ValueError("invalid safe bug report limit")
        if type(write_queue_size) is not int or not 1 <= write_queue_size <= MAX_WRITE_QUEUE:
            raise ValueError("invalid safe bug report queue limit")
        self._events: deque[SafeBugReportEvent] = deque(maxlen=max_events)
        self._events_lost = False
        self._max_events = max_events
        self._history: LocalBugReportHistoryStore | None = None
        self._queue: queue.Queue[
            _QueuedHistoryEvent | _ClearHistory | _StopHistoryWorker
        ] | None = None
        self._worker: threading.Thread | None = None
        self._write_pending = threading.Condition()
        self._pending_writes = 0
        self._previous_session_state = PreviousSessionState.NOT_AVAILABLE.value
        self._write_queue_size = write_queue_size
        self._lock = threading.RLock()
        self._history_generation = 0
        self._loss_since_clear = False
        self._clear_state: HistoryClearState | None = None

    def configure_history(self, root: Path) -> bool:
        """Start asynchronous restore/persistence. Returns false if already configured."""
        with self._lock:
            if self._worker is not None or self._history is not None:
                return False
            self._history = LocalBugReportHistoryStore(root)
            self._queue = queue.Queue(maxsize=self._write_queue_size)
            self._previous_session_state = PreviousSessionState.LOADING.value
            initial = tuple(self._events)
            for event in initial:
                try:
                    self._queue.put_nowait(_QueuedHistoryEvent(event, self._history_generation))
                    self._pending_writes += 1
                except queue.Full:
                    self._events_lost = True
                    break
            with self._write_pending:
                self._pending_writes += 1  # includes asynchronous root/restore bootstrap
            self._worker = threading.Thread(target=self._write_loop, daemon=True,
                                            name="metroliza-safe-bugreport")
            self._worker.start()
            return True

    def _initialize_history(self):
        assert self._history is not None
        lock = None
        if _diagnostic_store._ensure_private_root(self._history.root):
            lock = _diagnostic_store._StoreLock(self._history.root)
            if not lock.acquire():
                lock = None
        if lock is None:
            with self._lock:
                self._events_lost = True
                self._previous_session_state = PreviousSessionState.UNKNOWN.value
        else:
            if not self._history.prepare_locked():
                with self._lock:
                    self._events_lost = True
                    self._previous_session_state = PreviousSessionState.UNKNOWN.value
                lock.release()
                lock = None
            else:
                try:
                    prior, prior_lost = self._history.load_locked()
                    previous_state = (
                        PreviousSessionState.AVAILABLE.value
                        if prior else PreviousSessionState.NOT_AVAILABLE.value
                    )
                except Exception:
                    prior, prior_lost = (), True
                    previous_state = PreviousSessionState.UNKNOWN.value
                with self._lock:
                    current = tuple(self._events)
                    if self._history_generation == 0:
                        self._events.clear()
                        self._events.extend((*prior, *current)[-self._max_events:])
                        self._events_lost = (
                            self._events_lost or prior_lost
                            or len(prior) + len(current) > self._max_events
                        )
                    self._previous_session_state = previous_state
        return lock

    def _write_loop(self) -> None:
        assert self._queue is not None and self._history is not None
        lock = self._initialize_history()
        with self._write_pending:
            self._pending_writes -= 1
            self._write_pending.notify_all()
        while True:
            command = self._queue.get()
            try:
                if command is _StopHistoryWorker.STOP:
                    if lock is not None:
                        lock.release()
                        lock = None
                    return
                if isinstance(command, _ClearHistory):
                    complete = lock is not None and self._history.clear_locked()
                    with self._lock:
                        if command.generation == self._history_generation:
                            if complete:
                                self._clear_state = HistoryClearState.COMPLETE
                                self._events_lost = self._loss_since_clear
                                self._previous_session_state = (
                                    PreviousSessionState.NOT_AVAILABLE.value
                                )
                            else:
                                self._clear_state = HistoryClearState.ERROR
                                self._events_lost = True
                                self._loss_since_clear = True
                    continue
                assert isinstance(command, _QueuedHistoryEvent)
                with self._lock:
                    lost = self._events_lost
                if lock is None or not self._history.append_locked(
                    command.event, max_events=self._max_events, events_lost=lost
                ):
                    self._mark_events_lost(command.generation)
            finally:
                self._queue.task_done()
                with self._write_pending:
                    self._pending_writes -= 1
                    self._write_pending.notify_all()
        if lock is not None:
            lock.release()

    def record(self, action: object, *, enabled: object = None) -> bool:
        """Best-effort product hook; reject anything outside the closed schema."""
        try:
            if type(action) is not BugReportAction:
                with self._lock:
                    self._events_lost = True
                    self._loss_since_clear = True
                return False
            if enabled is not None and type(enabled) is not bool:
                with self._lock:
                    self._events_lost = True
                    self._loss_since_clear = True
                return False
            with self._lock:
                if len(self._events) == self._events.maxlen:
                    self._events_lost = True
                    self._loss_since_clear = True
                event = SafeBugReportEvent(action, enabled)
                self._events.append(event)
                if self._queue is not None:
                    with self._write_pending:
                        self._pending_writes += 1
                    try:
                        self._queue.put_nowait(
                            _QueuedHistoryEvent(event, self._history_generation)
                        )
                    except queue.Full:
                        with self._write_pending:
                            self._pending_writes -= 1
                        self._events_lost = True
                        self._loss_since_clear = True
            return True
        except Exception:
            # Diagnostics must never interrupt application work.
            with self._lock:
                self._events_lost = True
                self._loss_since_clear = True
            return False

    def snapshot(self) -> BugReportSnapshot:
        with self._lock:
            return BugReportSnapshot(tuple(self._events), self._events_lost,
                                     self._previous_session_state,
                                     self._clear_state.value if self._clear_state else None)

    def _mark_events_lost(self, generation: int) -> None:
        with self._lock:
            self._events_lost = True
            if generation == self._history_generation:
                self._loss_since_clear = True

    def clear_history(self) -> bool:
        """Queue a FIFO reset; true means pending, never that durable clearing completed."""
        with self._lock:
            if self._queue is None:
                self._clear_state = HistoryClearState.ERROR
                self._events_lost = True
                self._loss_since_clear = True
                return False
            generation = self._history_generation + 1
            with self._write_pending:
                self._pending_writes += 1
            try:
                self._queue.put_nowait(_ClearHistory(generation))
            except queue.Full:
                with self._write_pending:
                    self._pending_writes -= 1
                self._clear_state = HistoryClearState.ERROR
                self._events_lost = True
                self._loss_since_clear = True
                return False
            self._history_generation = generation
            self._clear_state = HistoryClearState.PENDING
            self._events.clear()
            self._events_lost = True
            self._loss_since_clear = False
            return True

    def close_history(self, timeout: float = 2.0) -> bool:
        """Best-effort orderly drain; forced process exit can lose queued events."""
        if not self.flush(timeout):
            return False
        if self._queue is not None:
            try:
                with self._write_pending:
                    self._pending_writes += 1
                self._queue.put_nowait(_StopHistoryWorker.STOP)
            except queue.Full:
                with self._write_pending:
                    self._pending_writes -= 1
                return False
        if self._worker is not None:
            self._worker.join(timeout=min(max(float(timeout), 0.0), 30.0))
            return not self._worker.is_alive()
        return True

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait for queued writes, primarily for orderly teardown and tests."""
        if type(timeout) not in (int, float) or timeout < 0:
            return False
        import time

        end = time.monotonic() + min(float(timeout), 30.0)
        with self._write_pending:
            while self._pending_writes:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._write_pending.wait(remaining)
        return True


def _format_report_event(event: object) -> str:
    if type(event) is not SafeBugReportEvent or type(event.action) is not BugReportAction:
        raise ValueError("invalid_event")
    if event.enabled is not None and type(event.enabled) is not bool:
        raise ValueError("invalid_event")
    suffix = ""
    if event.enabled is not None:
        suffix = f" (enabled: `{str(event.enabled).lower()}`)"
    return f"- `{event.action.value}`{suffix}"


def build_bug_report_markdown(
    category: object,
    snapshot: object,
    *,
    release_version: object = None,
) -> str:
    """Serialize only fixed enum literals and bools; fail closed on bad input."""
    try:
        if type(category) is not BugReportCategory or type(snapshot) is not BugReportSnapshot:
            return BUG_REPORT_UNAVAILABLE
        if type(snapshot.events_lost) is not bool or type(snapshot.events) is not tuple:
            return BUG_REPORT_UNAVAILABLE
        if type(snapshot.previous_session_state) is not str or snapshot.previous_session_state not in {
            state.value for state in PreviousSessionState
        }:
            return BUG_REPORT_UNAVAILABLE
        if len(snapshot.events) > MAX_EVENTS:
            return BUG_REPORT_UNAVAILABLE
        lines = [
            "# Metroliza bug report",
            "",
            f"Application version: `{_release_version(release_version)}`",
            "This report serializes only fixed action/category codes and boolean states.",
            _COVERAGE_NOTE,
            _HISTORY_NOTE,
            _SESSION_NOTE,
            _ASYNC_NOTE,
            f"Previous activity restored: `{snapshot.previous_session_state}`",
            "Reproduction status: `NOT_RUN`",
            "External input data: `not included`",
            "",
            f"Category: `{category.value}`",
            f"Recorded events lost: `{str(snapshot.events_lost).lower()}`",
            "",
            "## Recent activity",
        ]
        lines.extend(_format_report_event(event) for event in snapshot.events)
        lines.extend(("", "## Reproduction", "Reproduction not performed. Input data was not captured."))
        report = "\n".join(lines) + "\n"
        if len(report.encode("utf-8")) > MAX_REPORT_BYTES:
            return BUG_REPORT_UNAVAILABLE
        return report
    except Exception:
        return BUG_REPORT_UNAVAILABLE


recorder = SafeBugReportRecorder()
