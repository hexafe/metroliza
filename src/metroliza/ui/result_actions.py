"""In-session result access shared by Export and CSV Summary."""

from datetime import datetime
from functools import partial
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QHBoxLayout, QVBoxLayout, QWidget


def existing_result_files(paths):
    """Accept only explicitly produced local workbook/dashboard files."""
    return tuple(dict.fromkeys(
        Path(path) for path in paths if path and Path(path).suffix.lower() in {".xlsx", ".html", ".htm"}
        and Path(path).is_file()
    ))


def export_result_files(result):
    return existing_result_files(
        artifact.location for artifact in result.artifacts
        if artifact.artifact_id in {"workbook", "html_dashboard"}
        and artifact.status.value in {"complete", "partial"}
    )


def activate_result_file(parent, path, _checked=False, *, reveal=None):
    """Revalidate at every click; never substitute a different output."""
    path = Path(path)
    try:
        if not path.is_file():
            QMessageBox.warning(parent, "Output unavailable", f"{path}\nThis file was moved or deleted. Locate it or run again.")
            return
        if reveal is not None:
            reveal(path)
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            QMessageBox.warning(parent, "Unable to open output", f"Could not open {path}. Check its associated application and try again.")
    except (OSError, ValueError, RuntimeError) as exc:
        # A nested native dialog may have destroyed the owner.
        if parent is None or not sip.isdeleted(parent):
            QMessageBox.warning(parent, "Unable to open output", f"Could not open {path}. Check that it exists and try again.\n{type(exc).__name__}")


def _reveal(path):
    from metroliza.ui.export_dialog import reveal_file_in_explorer

    reveal_file_in_explorer(path)


def add_result_actions(parent, paths, add_button):
    """Use the same labels, URLs and safety checks in messages and retained rows."""
    paths = existing_result_files(paths)
    for suffixes, label in (({".xlsx"}, "Open workbook"), ({".html", ".htm"}, "Open dashboard")):
        for path in paths:
            if path.suffix.lower() in suffixes:
                button = add_button(label)
                button.setAccessibleName(label)
                button.setToolTip(str(path))
                button.clicked.connect(partial(activate_result_file, parent, path))
    if paths:
        button = add_button("Show in folder")
        button.setAccessibleName("Show in folder")
        button.setToolTip(str(paths[0]))
        button.clicked.connect(partial(activate_result_file, parent, paths[0], reveal=_reveal))


class LastResultRow(QWidget):
    """Compact, window-local result summary; cleared only when a new run starts."""

    def __init__(self, parent, label):
        super().__init__(parent)
        self.label = label
        self.setAccessibleName(label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.summary = QLabel(self)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setAccessibleName(f"{label} summary")
        layout.addWidget(self.summary)
        self.actions = QHBoxLayout()
        layout.addLayout(self.actions)
        self.clear()

    def clear(self):
        while self.actions.count():
            item = self.actions.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.summary.clear()
        self.hide()

    def set_result(self, outcome, paths=(), *, counts=""):
        self.clear()
        paths = existing_result_files(paths)
        parts = [self.label, outcome, datetime.now().strftime("%H:%M")]
        parts.extend(path.name for path in paths)
        if counts:
            parts.append(counts)
        self.summary.setText(" · ".join(parts))
        self.summary.setToolTip("\n".join(str(path) for path in paths))

        def add_button(label):
            button = QPushButton(label, self)
            button.setAutoDefault(False)
            self.actions.addWidget(button)
            return button

        add_result_actions(self.window(), paths, add_button)
        self.actions.addStretch(1)
        self.show()
