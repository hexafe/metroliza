"""Browse local run receipts and package the previously published files."""

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from metroliza.app.analysis_history import analysis_is_stale, bundle_analysis, recent_analyses
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
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(54)
        self.status.setAccessibleName("Analysis history status")

        layout = QVBoxLayout(self)
        layout.addWidget(self.runs)
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
        self.reload()

    def reload(self):
        self.runs.clear()
        for run in recent_analyses():
            at = datetime.fromisoformat(run["at"]).astimezone().strftime("%Y-%m-%d %H:%M")
            label = {"recipe": "Recipe", "csv": "CSV Summary", "reports": "Reports", "industrial": "Industrial"}.get(
                run["kind"], run["kind"],
            )
            item = QListWidgetItem(f"{at} · {label} · {Path(run['files'][0]).name}")
            item.setData(Qt.ItemDataRole.UserRole, run)
            self.runs.addItem(item)
        self.runs.setCurrentRow(0)
        self._selection_changed(self.runs.currentItem())
        if not self.runs.count():
            self.status.setPlainText("Completed exports will appear here.")

    def _selection_changed(self, current, _previous=None):
        self.pack.setEnabled(current is not None and self._task is None)
        if current is None:
            self.details.clear()
            self.result.clear()
            return
        run = current.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText(self._describe(run))
        outcome = "Source changed · run again to refresh" if analysis_is_stale(run) else "Published"
        self.result.set_result(outcome, run["files"])

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
        self.pack.setEnabled(self.runs.currentItem() is not None)
        task.deleteLater()
