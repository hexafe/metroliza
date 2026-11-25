"""Browse local run receipts and package the previously published files."""

from datetime import datetime
from functools import partial
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker, QThread, Qt
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from metroliza.app.analysis_history import (
    analysis_is_stale, bundle_analysis, has_report_folder_revision, load_recent_analyses, result_still_matches,
)
from metroliza.exporting.output_publication import OutputConsent
from metroliza.ui.local_file_task import LocalFileTask
from metroliza.ui.result_actions import LastResultRow


def collect_output_consent(parent, path):
    """Bind explicit replacement consent to the file the user actually saw."""
    try:
        existing = OutputConsent.for_path(path)
    except FileNotFoundError:
        return ()
    answer = QMessageBox.question(
        parent, "Replace existing file?", f"Replace {Path(path).name}?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return (existing,) if answer == QMessageBox.StandardButton.Yes else None


def _load_history(_generation):
    return load_recent_analyses(cancelled=QThread.currentThread().isInterruptionRequested)


def _check_report_source(receipt, _generation):
    return analysis_is_stale(receipt, cancelled=QThread.currentThread().isInterruptionRequested)


def _source_status(stale):
    if stale is None:
        return "Published · report source freshness not verified"
    return "Source changed · run again to refresh" if stale else "Published"


class AnalysisHistoryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Analysis history")
        self.resize(690, 520)

        self.runs = QListWidget()
        self.runs.setAccessibleName("Saved analyses")
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Analysis settings")
        self.result = LastResultRow(self, "Saved result")
        self.pack = QPushButton("Create ZIP of results…")
        self.reload_button = QPushButton("Refresh list")
        self.close_button = QPushButton("Close")
        self.listing_notice = QLabel()
        self.listing_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.listing_notice.setWordWrap(True)
        self.listing_notice.setAccessibleName("Saved analyses listing status")
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(54)
        self.status.setAccessibleName("Analysis history status")

        layout = QVBoxLayout(self)
        layout.addWidget(self.runs)
        layout.addWidget(self.listing_notice)
        layout.addWidget(self.details)
        layout.addWidget(self.result)
        controls = QHBoxLayout()
        for button in (self.pack, self.reload_button, self.close_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        self.pack.clicked.connect(self._package)
        self.reload_button.clicked.connect(self.reload)
        self.close_button.clicked.connect(self.close)
        self.runs.currentItemChanged.connect(self._selection_changed)
        self._task = None
        self._listing_task = None
        self._listing_generation = 0
        self._listing_requested = False
        self._source_task = None
        self._source_pending = None
        self._source_generation = 0
        self.finished.connect(self._cancel_source_check)
        self.finished.connect(self._cancel_listing)
        self.reload()

    def reload(self):
        self._cancel_listing()
        self._listing_requested = True
        with QSignalBlocker(self.runs):
            self.runs.clear()
        self._selection_changed(None)
        self.listing_notice.setText("Reading saved analyses…")
        self.listing_notice.show()
        self._start_listing()

    def _cancel_listing(self):
        self._listing_generation += 1
        self._listing_requested = False
        if self._listing_task is not None:
            self._listing_task.requestInterruption()

    def _start_listing(self):
        if self._listing_task is not None or not self._listing_requested:
            return
        self._listing_requested = False
        self._listing_task = LocalFileTask(_load_history, self._listing_generation)
        self._listing_task.succeeded.connect(self._show_listing)
        self._listing_task.failed.connect(self._listing_failed)
        self._listing_task.start_owned(self, AnalysisHistoryDialog._listing_finished)

    def _listing_is_current(self, task):
        return task is not None and task is self._listing_task and task.args[0] == self._listing_generation

    def _show_listing(self, listing):
        if not self._listing_is_current(self.sender()):
            return
        with QSignalBlocker(self.runs):
            for run in listing.receipts:
                at = datetime.fromisoformat(run["at"]).astimezone().strftime("%Y-%m-%d %H:%M")
                label = {"recipe": "Recipe", "csv": "CSV Summary", "reports": "Reports", "industrial": "Industrial"}.get(
                    run["kind"], run["kind"],
                )
                item = QListWidgetItem(f"{at} · {label} · {Path(run['files'][0]).name}")
                item.setData(Qt.ItemDataRole.UserRole, run)
                self.runs.addItem(item)
            self.runs.setCurrentRow(0)
        self._selection_changed(self.runs.currentItem())
        if listing.partial:
            self.listing_notice.setText("Partial history list. Some recent analyses may be missing. Saved receipts are retained.")
        elif not listing.receipts:
            self.listing_notice.setText("Completed exports will appear here.")
        else:
            self.listing_notice.hide()

    def _listing_failed(self, _error):
        if self._listing_is_current(self.sender()):
            self.listing_notice.setText("Could not read the analysis history. Saved receipts are retained.")

    def _listing_finished(self, task):
        self._listing_task = None
        task.deleteLater()
        self._start_listing()

    def _selection_changed(self, current, _previous=None):
        self._cancel_source_check()
        self.pack.setEnabled(current is not None and self._task is None)
        if current is None:
            self.details.clear()
            self.result.clear()
            return
        run = current.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText(self._describe(run))
        validate = partial(result_still_matches, run)
        available = [path for path in run["files"] if validate(path)]
        if len(available) < len(run["files"]):
            outcome = "One or more output files were moved or replaced."
            self.pack.setEnabled(False)
        elif has_report_folder_revision(run):
            outcome = "Published · checking report sources…"
            self._source_pending = run
            self._start_source_check()
        else:
            outcome = _source_status(analysis_is_stale(run))
        self.result.set_result(outcome, available, validate=validate)

    def _cancel_source_check(self):
        self._source_generation += 1
        self._source_pending = None
        if self._source_task is not None:
            self._source_task.requestInterruption()

    def _start_source_check(self):
        if self._source_task is not None or self._source_pending is None:
            return
        run, self._source_pending = self._source_pending, None
        self._source_task = LocalFileTask(_check_report_source, run, self._source_generation)
        self._source_task.succeeded.connect(self._show_source_check)
        self._source_task.failed.connect(self._source_check_failed)
        self._source_task.start_owned(self, AnalysisHistoryDialog._source_check_finished)

    def _source_check_failed(self, _error):
        self._show_source_check(None)

    def _show_source_check(self, stale):
        task = self.sender()
        if task is not self._source_task or task.args[1] != self._source_generation:
            return
        run = task.args[0]
        validate = partial(result_still_matches, run)
        available = [path for path in run["files"] if validate(path)]
        outcome = _source_status(stale)
        if len(available) < len(run["files"]):
            outcome = "One or more output files were moved or replaced."
            self.pack.setEnabled(False)
        self.result.set_result(outcome, available, validate=validate)

    def _source_check_finished(self, task):
        self._source_task = None
        task.deleteLater()
        self._start_source_check()

    def _describe(self, run):
        source = run.get("source")
        lines = [f"Input: {source}"] if source else []
        for field, value in run["settings"].items():
            if isinstance(value, (tuple, list)):
                value = ", ".join(map(str, value))
            lines.append(f"{field}: {value}")
        return "\n".join(lines) or "No additional settings were recorded for this run."

    def _package(self):
        current = self.runs.currentItem()
        if current is None or self._task is not None:
            return
        run = current.data(Qt.ItemDataRole.UserRole)
        first_file = Path(run["files"][0])
        proposed = first_file.with_name(f"{first_file.stem}_results.zip")
        selected, _ = QFileDialog.getSaveFileName(
            self, "Create ZIP of published results", str(proposed), "ZIP archive (*.zip)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".zip":
            path = path.with_suffix(".zip")
        try:
            consents = collect_output_consent(self, path)
        except OSError as exc:
            self.status.setPlainText(str(exc))
            return
        if consents is not None:
            self.pack.setEnabled(False)
            self.status.setPlainText("Collecting the Excel and HTML output files and dashboard resources…")
            self._task = LocalFileTask(bundle_analysis, run, path, consents)
            self._task.succeeded.connect(self._packaged)
            self._task.failed.connect(self.status.setPlainText)
            self._task.start_owned(self, AnalysisHistoryDialog._task_finished)

    def _packaged(self, path):
        self.status.setPlainText(f"Verified ZIP saved to {path}")

    def _task_finished(self, task):
        self._task = None
        self._selection_changed(self.runs.currentItem())
        task.deleteLater()
