"""Qt worker adapter for dependency-neutral parser preflight scans."""

from __future__ import annotations

from threading import Event

from PyQt6.QtCore import QThread, pyqtSignal

from metroliza.parsing.preflight import ParsePreflightService
from metroliza.shared.progress_status import build_three_line_status


class ParsePreflightThread(QThread):
    """Run parser discovery and content recognition without blocking the UI."""

    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, source_path: str, database_path: str, metadata_parsing_mode: str):
        super().__init__()
        self.source_path = str(source_path)
        self.database_path = str(database_path)
        self.metadata_parsing_mode = str(metadata_parsing_mode)
        self._cancel_requested = Event()

    def stop_scan(self) -> None:
        self._cancel_requested.set()

    def _on_progress(self, completed: int, total: int, display_name: str) -> None:
        fraction = completed / total if total else 1.0
        self.update_progress.emit(round(fraction * 100))
        self.update_label.emit(
            build_three_line_status(
                "Scanning report contents...",
                f"Inspected {completed}/{total}: {display_name}",
                "No database changes are being made",
            )
        )

    def run(self) -> None:
        try:
            result = ParsePreflightService().scan_source(
                source_path=self.source_path,
                database_path=self.database_path,
                metadata_parsing_mode=self.metadata_parsing_mode,
                should_cancel=self._cancel_requested.is_set,
                on_progress=self._on_progress,
            )
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(result)
