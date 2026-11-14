"""Local, fixed-schema bug report for copying into a coding assistant."""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from metroliza.app.version import RELEASE_VERSION
from metroliza.shared.diagnostic_store import IncidentStore
from metroliza.shared.safe_bugreport import (
    BUG_REPORT_UNAVAILABLE,
    BugReportAction,
    BugReportCategory,
    PreviousSessionState,
    build_bug_report_markdown,
    recorder,
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
    """Preview and copy only the versioned, allowlisted local report."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Report a problem"))
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())

        self.category_combo = QComboBox(self)
        for label, category in _CATEGORY_CHOICES:
            self.category_combo.addItem(self.tr(label), category)

        guidance = QLabel(
            self.tr(
                "The report contains fixed diagnostic codes only. It excludes files, "
                "names, paths, entered values, and report data. Activity is captured only "
                "while the application responds, so a freeze may not appear in the report. "
                "Review it before pasting."
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
        self.clear_button = QPushButton(self.tr("Clear activity history"), self)
        close_button = QPushButton(self.tr("Close"), self)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status_label, stretch=1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(guidance)
        layout.addWidget(QLabel(self.tr("Problem category"), self))
        layout.addWidget(self.category_combo)
        layout.addWidget(QLabel(self.tr("Report preview"), self))
        layout.addWidget(self.preview, stretch=1)
        layout.addLayout(buttons)

        self.category_combo.currentIndexChanged.connect(self._refresh_preview)
        self.copy_button.clicked.connect(self.copy_report)
        self.clear_button.clicked.connect(self.clear_history)
        close_button.clicked.connect(self.close)
        self.finished.connect(self._stop_clear_polling)
        configure_window_size(self, minimum=(560, 420), initial=(760, 560))
        apply_metroliza_theme(self)
        self._refresh_preview()

    def _selected_category(self) -> BugReportCategory | None:
        value = self.category_combo.currentData()
        return value if type(value) is BugReportCategory else None

    def _report_text(self) -> str | None:
        category = self._selected_category()
        if category is None:
            return None
        try:
            return build_bug_report_markdown(category, recorder.snapshot(), release_version=RELEASE_VERSION)
        except Exception:
            return None

    def _refresh_preview(self, *_args) -> None:
        try:
            clear_state = getattr(recorder.snapshot(), "clear_state", None)
        except Exception:
            self._preview_report = None
            self.preview.clear()
            self.copy_button.setEnabled(False)
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return
        if clear_state == "pending":
            self._preview_report = None
            self.preview.clear()
            self.copy_button.setEnabled(False)
            self.clear_button.setEnabled(False)
            self.status_label.setText(self.tr("Clearing local history…"))
            if not self._clear_polling:
                self._clear_polling = True
                QTimer.singleShot(100, lambda: self._poll_history_clear(0))
            return
        report = self._report_text()
        if report is None or report == BUG_REPORT_UNAVAILABLE:
            self._preview_report = None
            self.preview.clear()
            self.copy_button.setEnabled(False)
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return
        self.preview.setPlainText(report)
        self._preview_report = report
        self.copy_button.setEnabled(True)
        self.status_label.setText("")

    def copy_report(self) -> None:
        report = self._preview_report
        if report is None or report == BUG_REPORT_UNAVAILABLE:
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return
        try:
            clear_state = recorder.snapshot().clear_state
        except Exception:
            self.status_label.setText(self.tr("A safe report is unavailable."))
            return
        if clear_state == "pending":
            self._refresh_preview()
            return
        if self._report_text() != report:
            self._refresh_preview()
            self.status_label.setText(self.tr("History changed. Review the updated report before copying."))
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self.status_label.setText(self.tr("The clipboard is unavailable."))
            return
        clipboard.setText(report)
        self.status_label.setText(
            self.tr("Copied locally. Review the report before pasting it into an assistant.")
        )

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
        if root is None or not recorder.configure_history(root.parent / "safe-bugreport-activity"):
            return
        recorder.record(BugReportAction.APP_OPENED)
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
