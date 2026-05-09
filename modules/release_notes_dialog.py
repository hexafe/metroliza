import VersionDate
from PyQt6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout
from modules.ui_foundation import apply_metroliza_theme, configure_window_size

class ReleaseNotesDialog(QDialog):
    def __init__(self, parent, release_notes):
        super().__init__(parent)

        # Initialize the dialog window
        self.setWindowTitle(f"Release Notes - {VersionDate.VERSION_LABEL}")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        configure_window_size(self, minimum=(520, 320), initial=(680, 480))
        apply_metroliza_theme(self)

        # Create a QTextBrowser to display release notes
        self.release_notes_browser = QTextBrowser()
        self.release_notes_browser.setHtml(release_notes)

        # Create a layout for the dialog and add the QTextBrowser to it
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.release_notes_browser)
        self.setLayout(layout)
