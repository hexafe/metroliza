"""Qt worker adapter that reads reviewed-report metadata off the GUI thread (#1100)."""

from __future__ import annotations

from collections.abc import Iterable
from threading import Event

from PyQt6.QtCore import QThread, pyqtSignal

from metroliza.parsing.metadata_review import MODE_OCR, MetadataReviewReader
from metroliza.shared.progress_status import build_three_line_status


class MetadataReviewThread(QThread):
    """Run ``MetadataReviewReader.read`` for a batch; never touches the database.

    Readings are emitted one by one so the table keeps everything that was read
    when the batch is cancelled.  Failure text is deliberately generic: raw
    exceptions from document parsing may contain confidential content.
    """

    update_progress = pyqtSignal(int)
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

    def stop_reading(self) -> None:
        self._cancel_requested.set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    def _on_progress(self, completed: int, total: int, display_name: str) -> None:
        self.update_progress.emit(round(100 * completed / total) if total else 100)
        action = "Running OCR" if self.mode == MODE_OCR else "Reading metadata"
        self.update_label.emit(
            build_three_line_status(
                f"{action}...",
                f"Report {completed}/{total}: {display_name}",
                "No database changes are being made",
            )
        )

    def run(self) -> None:
        try:
            summary = self._reader.read(
                self._occurrence_ids,
                mode=self.mode,
                should_cancel=self._cancel_requested.is_set,
                on_reading=self.reading_ready.emit,
                on_progress=self._on_progress,
            )
        except Exception:  # pragma: no cover - defensive worker boundary
            self.failed.emit("Metadata could not be read.")
            return
        self.completed.emit(summary)
