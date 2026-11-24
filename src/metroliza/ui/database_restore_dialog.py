"""Restore a verified Reports backup to a separate file."""

from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QFileDialog, QFormLayout, QLabel, QPushButton, QVBoxLayout

from metroliza.industrial.industrial_cache_target import publish_verified_database_copy
from metroliza.reports.db import sqlite_readonly_connection_scope
from metroliza.reports.report_schema import validate_report_snapshot
from metroliza.shared.sqlite_paths import SQLITE_FILE_FILTER
from metroliza.ui import detached_threads


def _validate_report_snapshot(path: Path):
    with sqlite_readonly_connection_scope(str(path)) as connection:
        validate_report_snapshot(connection)


class _RestoreThread(QThread):
    restored = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source, destination, active):
        super().__init__()
        self.source, self.destination, self.active = source, destination, active

    def run(self):
        try:
            result = publish_verified_database_copy(
                self.source, self.destination, forbidden_destinations=(self.active,),
                validate=_validate_report_snapshot,
            )
        except (ValueError, FileExistsError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Could not verify and restore this database. Check the source and destination.")
        else:
            self.restored.emit(str(result))


class DatabaseRestoreDialog(QDialog):
    def __init__(self, parent, active_database):
        super().__init__(parent)
        self.active_database = active_database or ""
        self._worker = None
        self.source = ""
        self.destination = ""
        self.setWindowTitle("Restore database copy")
        self.source_button = QPushButton("Choose backup…")
        self.destination_button = QPushButton("Choose new database…")
        self.restore_button = QPushButton("Verify and restore")
        self.restore_button.setEnabled(False)
        self.status = QLabel("Choose a backup and a new file. The current database stays open.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        paths = QFormLayout()
        paths.addRow("Backup", self.source_button)
        paths.addRow("Restored database", self.destination_button)
        layout = QVBoxLayout(self)
        layout.addLayout(paths)
        layout.addWidget(self.status)
        layout.addWidget(self.restore_button)
        self.source_button.clicked.connect(self._choose_backup)
        self.destination_button.clicked.connect(self._choose_destination)
        self.restore_button.clicked.connect(self._restore)

    def _choose_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose backup", self.source, SQLITE_FILE_FILTER)
        if path:
            self.source = path
            self.source_button.setToolTip(path)
            self.source_button.setText(Path(path).name)
            self._sync_controls()

    def _choose_destination(self):
        proposed = self.destination
        if not proposed and self.source:
            source = Path(self.source)
            proposed = str(source.with_name(f"{source.stem} (restored).sqlite"))
        path, _ = QFileDialog.getSaveFileName(self, "Choose new database", proposed, SQLITE_FILE_FILTER)
        if path:
            self.destination = path
            self.destination_button.setToolTip(path)
            self.destination_button.setText(Path(path).name)
            self._sync_controls()

    def _sync_controls(self):
        idle = self._worker is None
        self.source_button.setEnabled(idle)
        self.destination_button.setEnabled(idle)
        self.restore_button.setEnabled(idle and bool(self.source and self.destination))

    def _restore(self):
        if not self.restore_button.isEnabled():
            return
        self._worker = worker = _RestoreThread(self.source, self.destination, self.active_database)
        self.status.setText("Verifying and restoring a separate copy…")
        self._sync_controls()
        worker.restored.connect(self._restored)
        worker.failed.connect(self.status.setText)
        detached_threads.register(worker, defer_quit=True, owner=self, on_finished=DatabaseRestoreDialog._finished)
        worker.start()

    def _restored(self, path):
        self.status.setText(f"Restored and verified: {path}")
        self.destination = ""
        self.destination_button.setText("Choose new database…")
        self.destination_button.setToolTip("")

    def _finished(self, worker):
        self._worker = None
        self._sync_controls()
        worker.deleteLater()

    def done(self, result):
        if self._worker is None:
            super().done(result)

    def closeEvent(self, event):
        if self._worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)
