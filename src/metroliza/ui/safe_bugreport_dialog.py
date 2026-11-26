"""Preview, copy and save a local, fixed-schema bug report."""

from __future__ import annotations

from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from metroliza.app.version import RELEASE_VERSION
from metroliza.app.bugreport_provenance import collect_bugreport_build_facts
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus, export_safe_bug_report
from metroliza.shared.safe_bugreport import (
    BUG_REPORT_UNAVAILABLE,
    BugReportAction,
    BugReportCategory,
    PreviousSessionState,
    build_bug_report_markdown,
    recorder,
)
from metroliza.shared.safe_bugreport_context import (
    BugReportContextSelection, ContextBehavior, ContextModule, ContextSymptom,
    SafeBugReportProvenance,
)
from metroliza.ui.ui_foundation import apply_metroliza_theme, configure_window_size


_CATEGORY_CHOICES = (
    ("Wrong output", BugReportCategory.WRONG_OUTPUT),
    ("Missing output", BugReportCategory.MISSING_OUTPUT),
    ("Operation failed", BugReportCategory.OPERATION_FAILED),
    ("Application unresponsive", BugReportCategory.APP_UNRESPONSIVE),
    ("Other", BugReportCategory.OTHER),
)


class SafeBugReportDialog(QDialog):
    """Show the exact report that will be copied or saved."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Report a problem"))
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())

        self.category_combo = QComboBox(self)
        for label, category in _CATEGORY_CHOICES:
            self.category_combo.addItem(self.tr(label), category)

        self.module_combo = self._closed_choices(ContextModule)
        self.symptom_combo = self._closed_choices(ContextSymptom)
        self.expected_combo = self._closed_choices(ContextBehavior)
        self.observed_combo = self._closed_choices(ContextBehavior)
        self._captured_activity = None
        self._captured_context = None
        self._provenance = SafeBugReportProvenance(**collect_bugreport_build_facts())
        self._capture_activity()

        guidance = QLabel(
            self.tr(
                "Choose the affected module and describe the symptom using the choices below. "
                "The report includes technical build facts, fixed diagnostic codes and option states. "
                "It excludes files, names, paths, entered values and report data. "
                "This snapshot stays fixed while you review it. Use Refresh to capture later activity. "
                "A saved ZIP contains this preview (report.md) and its checksum (manifest.json)."
            ),
            self,
        )
        guidance.setWordWrap(True)
        guidance.setProperty("secondary", True)

        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("secondary", True)
        self._preview_report: str | None = None
        self._clear_polling = False

        self.copy_button = QPushButton(self.tr("Copy report"), self)
        self.save_button = QPushButton(self.tr("Save diagnostic ZIP…"), self)
        self.refresh_button = QPushButton(self.tr("Refresh snapshot"), self)
        self.clear_button = QPushButton(self.tr("Clear activity history"), self)
        close_button = QPushButton(self.tr("Close"), self)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(guidance)
        layout.addWidget(QLabel(self.tr("Problem category"), self))
        layout.addWidget(self.category_combo)
        for label, combo in (
            ("Affected module", self.module_combo), ("Symptom", self.symptom_combo),
            ("Expected behaviour", self.expected_combo), ("Observed behaviour", self.observed_combo),
        ):
            layout.addWidget(QLabel(self.tr(label), self))
            layout.addWidget(combo)
            combo.currentIndexChanged.connect(self._refresh_preview)
        layout.addWidget(QLabel(self.tr("Report preview"), self))
        layout.addWidget(self.preview, stretch=1)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

        self.category_combo.currentIndexChanged.connect(self._refresh_preview)
        self.copy_button.clicked.connect(self.copy_report)
        self.save_button.clicked.connect(self.save_report)
        self.refresh_button.clicked.connect(self.refresh_snapshot)
        self.clear_button.clicked.connect(self.clear_history)
        close_button.clicked.connect(self.close)
        self.finished.connect(self._stop_clear_polling)
        configure_window_size(self, minimum=(560, 580), initial=(800, 760))
        apply_metroliza_theme(self)
        self._refresh_preview()

    def _closed_choices(self, enum_type):
        combo = QComboBox(self)
        for value in enum_type:
            label = "Unspecified" if value.value == "unknown" else value.value.replace("_", " ").capitalize()
            combo.addItem(self.tr(label), value)
        return combo

    def _capture_activity(self) -> None:
        try:
            self._captured_activity, self._captured_context = recorder.report_snapshot()
        except Exception:
            self._captured_activity = self._captured_context = None

    def refresh_snapshot(self) -> None:
        self._capture_activity()
        self._refresh_preview()

    def _selected_category(self) -> BugReportCategory | None:
        value = self.category_combo.currentData()
        return value if type(value) is BugReportCategory else None

    def _report_text(self) -> str | None:
        category = self._selected_category()
        if category is None:
            return None
        try:
            if self._captured_activity is None or self._captured_context is None:
                return None
            context = BugReportContextSelection(
                snapshot=self._captured_context, provenance=self._provenance,
                module=self.module_combo.currentData(), symptom=self.symptom_combo.currentData(),
                expected=self.expected_combo.currentData(), observed=self.observed_combo.currentData(),
            )
            return build_bug_report_markdown(
                category, self._captured_activity, release_version=RELEASE_VERSION, context=context,
            )
        except Exception:
            return None

    def _refresh_preview(self, *_args) -> None:
        try:
            clear_state = getattr(recorder.snapshot(), "clear_state", None)
        except Exception:
            self._set_preview(None)
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return
        if clear_state == "pending":
            self._set_preview(None)
            self.clear_button.setEnabled(False)
            self.status_label.setText(self.tr("Clearing local history…"))
            if not self._clear_polling:
                self._clear_polling = True
                QTimer.singleShot(100, lambda: self._poll_history_clear(0))
            return
        report = self._report_text()
        if report is None or report == BUG_REPORT_UNAVAILABLE:
            self._set_preview(None)
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return
        self._set_preview(report)
        self.status_label.setText("")

    def _set_preview(self, report: str | None) -> None:
        self._preview_report = report
        self.preview.setPlainText(report or "")
        self.copy_button.setEnabled(report is not None)
        self.save_button.setEnabled(report is not None)

    def _checked_preview(self) -> str | None:
        report = self._preview_report
        if report is None or self._captured_context is None:
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return None
        try:
            clear_state = recorder.snapshot().clear_state
            current_generation = recorder.history_generation()
        except Exception:
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return None
        if clear_state == "pending":
            self._refresh_preview()
            return None
        if current_generation != self._captured_context.generation:
            self.refresh_snapshot()
            self.status_label.setText(self.tr("History was cleared. Review the new snapshot."))
            return None
        return report

    def copy_report(self) -> None:
        report = self._checked_preview()
        if report is None:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self.status_label.setText(self.tr("The clipboard is unavailable."))
            return
        clipboard.setText(report)
        self.status_label.setText(
            self.tr("Copied locally. Review the report before pasting it into an assistant.")
        )

    def save_report(self) -> None:
        report = self._checked_preview()
        if report is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save diagnostic ZIP"), "metroliza-diagnostic.zip",
            self.tr("ZIP archive (*.zip)"),
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not filename or sip.isdeleted(self):
            return
        current = self._checked_preview()
        if current is None:
            return
        if current != report:
            self.status_label.setText(self.tr("The preview changed. Review it before saving."))
            return
        target = Path(filename)
        if target.suffix.lower() != ".zip":
            target = target.with_name(target.name + ".zip")
        result = export_safe_bug_report(report, target)
        messages = {
            StoreStatus.EXPORTED: self.tr("Diagnostic ZIP saved."),
            StoreStatus.DESTINATION_EXISTS: self.tr("That file already exists. Choose a new filename."),
            StoreStatus.PUBLISH_INCOMPLETE: self.tr(
                "The ZIP could not be verified. Check the destination before sharing it."
            ),
        }
        self.status_label.setText(messages.get(result, self.tr("The diagnostic ZIP could not be saved.")))

    def clear_history(self) -> None:
        """Queue a clear; report success only after the local writer confirms it."""
        try:
            if recorder.snapshot().clear_state == "pending":
                self._refresh_preview()
                return
            accepted = recorder.clear_history()
        except Exception:
            accepted = False
        if not accepted:
            self.status_label.setText(self.tr("Local history could not be cleared."))
            return
        self.clear_button.setEnabled(False)
        self._clear_polling = True
        self._refresh_preview()
        QTimer.singleShot(100, lambda: self._poll_history_clear(0))

    def _poll_history_clear(self, attempts: int) -> None:
        try:
            if not self._clear_polling:
                return
            state = recorder.snapshot().clear_state
            if state == "pending":
                QTimer.singleShot(100, lambda: self._poll_history_clear(attempts + 1))
                return
            self._clear_polling = False
            self.clear_button.setEnabled(state != "pending")
            self._capture_activity()
            self._refresh_preview()
            if state == "complete":
                self.status_label.setText(self.tr("Local activity history cleared."))
            else:
                self.status_label.setText(self.tr("Local history could not be cleared."))
        except (AttributeError, RuntimeError):
            self._clear_polling = False
            return

    def closeEvent(self, event) -> None:
        self._stop_clear_polling()
        super().closeEvent(event)

    def _stop_clear_polling(self, *_args) -> None:
        self._clear_polling = False


def open_safe_bug_report_dialog(parent=None) -> SafeBugReportDialog:
    dialog = SafeBugReportDialog(parent)
    dialog.show()
    return dialog


def start_local_bugreport_history(parent, app) -> None:
    """Start private history in the normal UI, without disk I/O on the GUI thread."""
    try:
        root = IncidentStore().root
        if root is None:
            return
        history_root = root.parent / "safe-bugreport-activity"
        if recorder.configure_history(history_root):
            recorder.record(BugReportAction.APP_OPENED)
        elif not recorder.history_is_running(history_root):
            return
        # A short best-effort drain on orderly exit; abrupt exits can lose queued events.
        app.aboutToQuit.connect(lambda: recorder.close_history(timeout=0.2))
        QTimer.singleShot(250, lambda: _offer_previous_history(parent, 0))
    except Exception:
        # Diagnostics must not affect normal application startup.
        return


def _offer_previous_history(parent, attempts: int) -> None:
    try:
        state = recorder.snapshot().previous_session_state
        if state == PreviousSessionState.LOADING.value and attempts < 20:
            QTimer.singleShot(250, lambda: _offer_previous_history(parent, attempts + 1))
            return
        if state != PreviousSessionState.AVAILABLE.value or not parent.isVisible():
            return
        notice = QMessageBox(parent)
        notice.setWindowTitle("Previous diagnostic activity")
        notice.setText("Earlier local diagnostic activity is available. Open a report?")
        notice.setInformativeText("The presence of history does not indicate a crash.")
        notice.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        notice.setModal(False)
        notice.finished.connect(
            lambda result: open_safe_bug_report_dialog(parent)
            if result == QMessageBox.StandardButton.Yes else None
        )
        parent._safe_bugreport_history_notice = notice
        notice.show()
    except (AttributeError, RuntimeError):
        return
