"""Qt worker adapter that reads reviewed-report metadata off the GUI thread (#1100)."""

from __future__ import annotations

from collections.abc import Iterable
from threading import Event

from PyQt6.QtCore import QThread, pyqtSignal

from metroliza.parsing.metadata_review import MODE_OCR, MetadataReviewReader
from metroliza.shared.progress_status import build_three_line_status
from metroliza.shared.safe_bugreport import BugReportAction, recorder as _bugreport_recorder


# Running workers stay referenced here until they finish, so a QThread is never
# destroyed while running even if its owner is garbage-collected first.
_RUNNING_THREADS: set = set()


def _record_metadata_review_action(
    action: BugReportAction, *, enabled: bool | None = None
) -> None:
    try:
        _bugreport_recorder.record(action, enabled=enabled)
    except Exception:
        # Copyable diagnostics must never change a metadata review result.
        return


class MetadataReviewThread(QThread):
    """Run ``MetadataReviewReader.read`` for a batch; never touches the database.

    Readings are emitted one by one so the table keeps everything that was read
    when the batch is cancelled.  Failure text is deliberately generic: raw
    exceptions from document parsing may contain confidential content.
    """

    update_progress = pyqtSignal(int)
    update_counts = pyqtSignal(int, int)
    update_label = pyqtSignal(str)
    reading_ready = pyqtSignal(object)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        reader: MetadataReviewReader,
        occurrence_ids: Iterable[str],
        *,
        mode: str,
    ) -> None:
        super().__init__()
        self._reader = reader
        self._occurrence_ids = tuple(occurrence_ids)
        self.mode = mode
        self._cancel_requested = Event()

    def start(self, *args, **kwargs) -> None:  # noqa: D102 - QThread.start
        _RUNNING_THREADS.add(self)
        self.finished.connect(lambda thread=self: _RUNNING_THREADS.discard(thread))
        super().start(*args, **kwargs)

    def stop_reading(self) -> None:
        self._cancel_requested.set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    def _on_progress(self, completed: int, total: int, display_name: str) -> None:
        self.update_progress.emit(round(100 * completed / total) if total else 100)
        self.update_counts.emit(completed, total)
        action = "Running OCR" if self.mode == MODE_OCR else "Reading metadata"
        self.update_label.emit(
            build_three_line_status(
                f"{action}...",
                f"Report {completed}/{total}: {display_name}",
                "No database changes are being made",
            )
        )

    def run(self) -> None:
        _record_metadata_review_action(BugReportAction.REPORT_METADATA_REVIEW_STARTED)
        _record_metadata_review_action(
            BugReportAction.OPTION_REPORT_REVIEW_OCR,
            enabled=self.mode == MODE_OCR,
        )
        try:
            summary = self._reader.read(
                self._occurrence_ids,
                mode=self.mode,
                should_cancel=self._cancel_requested.is_set,
                on_reading=self.reading_ready.emit,
                on_progress=self._on_progress,
            )
        except Exception:  # pragma: no cover - defensive worker boundary
            _record_metadata_review_action(BugReportAction.REPORT_METADATA_REVIEW_FAILED)
            self.failed.emit("Metadata could not be read.")
            return
        try:
            if summary.cancelled:
                action = BugReportAction.REPORT_METADATA_REVIEW_CANCELLED
            elif summary.failed and summary.read:
                action = BugReportAction.REPORT_METADATA_REVIEW_COMPLETED_WITH_WARNINGS
            elif summary.failed and summary.total:
                action = BugReportAction.REPORT_METADATA_REVIEW_FAILED
            else:
                action = BugReportAction.REPORT_METADATA_REVIEW_COMPLETED
        except Exception:
            # A diagnostic projection cannot suppress the worker's result signal.
            action = BugReportAction.REPORT_METADATA_REVIEW_RESULT_UNKNOWN
        _record_metadata_review_action(action)
        self.completed.emit(summary)
