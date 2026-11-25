"""Create or restore a verified Reports database copy."""

from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QDialog, QFileDialog, QFormLayout, QLabel, QPushButton, QVBoxLayout

from metroliza.industrial.industrial_cache_target import (
    publish_verified_database_copy,
    resolve_industrial_cache_destination,
)
from metroliza.recipes.bindings import paths_alias
from metroliza.reports.db import DatabaseSourceChanged, SQLiteFileBinding, sqlite_readonly_connection_scope
from metroliza.reports.report_schema import publish_upgraded_report_copy, validate_report_snapshot
from metroliza.shared.sqlite_paths import SQLITE_FILE_FILTER
from metroliza.ui import detached_threads


def _validate_report_snapshot(path: Path):
    with sqlite_readonly_connection_scope(str(path)) as connection:
        validate_report_snapshot(connection)


class _DatabaseCopyThread(QThread):
    copied = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source, destination, active, *, upgrade=False, source_binding=None):
        super().__init__()
        self.source, self.destination, self.active = source, destination, active
        self.upgrade = upgrade
        self.source_binding = source_binding
        self.succeeded = False

    def run(self):
        try:
            binding = self.source_binding or SQLiteFileBinding.capture(self.source)
            binding.require(self.source)
            if self.upgrade:
                result = publish_upgraded_report_copy(
                    self.source, self.destination, forbidden_destinations=(self.active,),
                    source_binding=binding,
                )
            else:
                def validate(path):
                    _validate_report_snapshot(path)
                    binding.require(self.source)

                result = publish_verified_database_copy(
                    self.source, self.destination, forbidden_destinations=(self.active,),
                    validate=validate, source_binding=binding,
                )
        except (DatabaseSourceChanged, ValueError, FileExistsError) as exc:
            message = str(exc)
            if message == "Choose a destination outside the temporary cache":
                message = "Choose a new file different from the source database."
            elif message.endswith("an active Metroliza database cannot be replaced"):
                message = "Choose a new file different from the active Reports database."
            self.failed.emit(message)
        except Exception:
            self.failed.emit("Could not verify and copy this database. Check the source and destination.")
        else:
            self.succeeded = True
            self.copied.emit(str(result))


class DatabaseRestoreDialog(QDialog):
    copy_failed_on_close = pyqtSignal()

    def __init__(self, parent, active_database, *, create_backup=False, source_binding=None):
        super().__init__(parent)
        self.active_database = active_database or ""
        self.create_backup = create_backup
        self._worker = None
        self._close_after_copy = False
        self._copy_failed = False
        self.source = self.active_database if create_backup else ""
        self._source_binding = source_binding or (SQLiteFileBinding.capture(self.source) if self.source else None)
        self.destination = ""
        self.setWindowTitle("Back up Reports database" if create_backup else "Restore database copy")
        self.source_button = None
        self.upgrade_checkbox = None
        if create_backup:
            source_widget = QLabel(Path(self.source).name or "No database open")
            source_widget.setTextFormat(Qt.TextFormat.PlainText)
            source_widget.setToolTip(self.source)
        else:
            self.source_button = source_widget = QPushButton("Choose database or backup…")
            self.source_button.clicked.connect(self._choose_backup)
            self.upgrade_checkbox = QCheckBox("Upgrade to the current Reports schema")
        self.destination_prompt = "Choose backup file…" if create_backup else "Choose new database…"
        self.destination_button = QPushButton(self.destination_prompt)
        self.restore_button = QPushButton("Verify and back up" if create_backup else "Verify and restore")
        self.restore_button.setEnabled(False)
        self.status = QLabel(
            "Choose a new file for a verified backup. The current database stays open."
            if create_backup else "Choose a Reports database or backup and a new file. The current database stays open."
        )
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        paths = QFormLayout()
        paths.addRow("Active Reports database" if create_backup else "Source database", source_widget)
        paths.addRow("Backup file" if create_backup else "Restored database", self.destination_button)
        if self.upgrade_checkbox is not None:
            paths.addRow(self.upgrade_checkbox)
        layout = QVBoxLayout(self)
        layout.addLayout(paths)
        layout.addWidget(self.status)
        layout.addWidget(self.restore_button)
        self.destination_button.clicked.connect(self._choose_destination)
        self.restore_button.clicked.connect(self._copy_database)

    def _choose_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose database or backup", self.source, SQLITE_FILE_FILTER)
        if path:
            try:
                binding = SQLiteFileBinding.capture(path)
            except (OSError, ValueError):
                self.status.setText("Could not identify the selected database. Choose another file.")
                return
            self.source = path
            self._source_binding = binding
            self.source_button.setToolTip(path)
            self.source_button.setText(Path(path).name)
            self._sync_controls()

    def _choose_destination(self):
        proposed = self.destination
        if not proposed and self.source:
            source = Path(self.source)
            suffix = "backup" if self.create_backup else "restored"
            proposed = str(source.with_name(f"{source.stem} ({suffix}).sqlite"))
        options = QFileDialog.Option.DontConfirmOverwrite if self.create_backup else QFileDialog.Option(0)
        path, _ = QFileDialog.getSaveFileName(
            self, self.destination_prompt.removesuffix("…"), proposed, SQLITE_FILE_FILTER, options,
        )
        if path:
            self.destination = path
            self.destination_button.setToolTip(path)
            self.destination_button.setText(Path(path).name)
            self._sync_controls()

    def _sync_controls(self):
        idle = self._worker is None
        if self.source_button is not None:
            self.source_button.setEnabled(idle)
        if self.upgrade_checkbox is not None:
            self.upgrade_checkbox.setEnabled(idle)
        self.destination_button.setEnabled(idle)
        self.restore_button.setEnabled(idle and bool(self.source and self.destination))

    def _copy_database(self):
        if not self.restore_button.isEnabled():
            return
        try:
            destination = resolve_industrial_cache_destination(self.destination)
        except (OSError, RuntimeError, ValueError):
            self.status.setText("Could not resolve the destination. Choose a new file and try again.")
            return
        upgrade = self.upgrade_checkbox is not None and self.upgrade_checkbox.isChecked()
        self._worker = worker = _DatabaseCopyThread(
            self.source, destination, self.active_database, upgrade=upgrade,
            source_binding=self._source_binding,
        )
        if self.create_backup:
            self.status.setText("Creating and verifying a backup…")
        elif upgrade:
            self.status.setText("Verifying and upgrading a separate copy…")
        else:
            self.status.setText("Verifying and restoring a separate copy…")
        self._sync_controls()
        worker.copied.connect(self._copied)
        worker.failed.connect(self.status.setText)
        detached_threads.register(worker, defer_quit=True, owner=self, on_finished=DatabaseRestoreDialog._finished)
        worker.start()

    def _copied(self, path):
        if self.create_backup:
            result = "Backup created and verified"
        elif self._worker is not None and self._worker.upgrade:
            result = "Upgraded copy created and verified"
        else:
            result = "Restored and verified"
        self.status.setText(f"{result}: {path}")
        self.destination = ""
        self.destination_button.setText(self.destination_prompt)
        self.destination_button.setToolTip("")

    def _finished(self, worker):
        self._worker = None
        self._copy_failed = not worker.succeeded
        worker.deleteLater()
        if self._close_after_copy:
            self.close()
        else:
            self._sync_controls()

    def owns_destination(self, database):
        if self._worker is None or not database:
            return False
        try:
            candidate = Path(database).expanduser()
            destination = self._worker.destination
            if paths_alias(candidate, destination):
                return True
            # A missing leaf has no inode yet. Both names can still reach the same directory.
            resolved = candidate.resolve(strict=False)
            return (
                resolved.name.casefold() == destination.name.casefold()
                and resolved.parent.samefile(destination.parent)
            )
        except (FileNotFoundError, NotADirectoryError):
            return False
        except (OSError, RuntimeError, ValueError):
            return True

    def is_close_deferred(self):
        return self._worker is not None and self._close_after_copy

    def done(self, result):
        if self._worker is not None:
            return
        if self._copy_failed:
            self._copy_failed = False
            self.setEnabled(False)
            self.copy_failed_on_close.emit()
        super().done(result)

    def closeEvent(self, event):
        if self._worker is not None:
            self._close_after_copy = True
            event.ignore()
        else:
            super().closeEvent(event)
