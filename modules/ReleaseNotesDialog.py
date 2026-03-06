from PyQt6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

class ReleaseNotesDialog(QDialog):
    def __init__(self, parent, release_notes):
        super().__init__(parent)

        # Initialize the dialog window
        self.setWindowTitle("Release Notes")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 600, 400)

        # Create a QTextBrowser to display release notes
        self.release_notes_browser = QTextBrowser()
        self.release_notes_browser.setHtml(release_notes)

        # Create a layout for the dialog and add the QTextBrowser to it
        layout = QVBoxLayout()
        layout.addWidget(self.release_notes_browser)
        self.setLayout(layout)
