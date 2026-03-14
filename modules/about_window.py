"""About dialog and clickable label helpers for application metadata display."""

import os

from PyQt6.QtCore import QSize, QTemporaryFile, Qt, QUrl
from PyQt6.QtGui import QMovie, QDesktopServices, QCursor
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from modules import base64_encoded_files
import base64
import VersionDate


class ClickableLabel(QLabel):
    """Label that behaves like a hyperlink and opens a fixed URL when clicked."""

    def __init__(self, text, link):
        super().__init__(text)
        self.link = link
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def enterEvent(self, event):
        self.setStyleSheet("QLabel { color: blue; text-decoration: underline; }")

    def leaveEvent(self, event):
        self.setStyleSheet("QLabel { color: black; text-decoration: none; }")

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl(self.link))


class AboutWindow(QDialog):
    """Display version, license, and project attribution information.

    The dialog renders an embedded GIF from in-memory base64 content and keeps
    the movie instance alive for the dialog lifetime.
    """

    def __init__(self, parent=None, days_until_expiration=0):
        super().__init__(parent)
        self._gif_temp_file_path = ""
        self._gif_label = None

        # Set the window title and layout
        self.setWindowTitle("About")
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create a QLabel to display the loading GIF
        gif_label = QLabel()
        self._gif_label = gif_label
        # gif_label.setFixedSize(200, 200)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)

        # Create temporary file and save encoded gif to it
        temp_file = QTemporaryFile()
        temp_file.setAutoRemove(False)
        temp_file_name = ""
        if temp_file.open():
            temp_file.write(gif_decoded)
            temp_file.close()
            temp_file_name = temp_file.fileName()
            self._gif_temp_file_path = temp_file_name

        # Create the QMovie using the temporary file name
        self.gif = QMovie(temp_file_name)
        self.gif.setScaledSize(QSize(200, 200))
        gif_label.setMovie(self.gif)
        gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gif.start()
        self.layout.addWidget(gif_label)

        # Add the title label
        title_label = QLabel(f"Metroliza version <b>{VersionDate.VERSION_LABEL}</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(title_label)
        
        if days_until_expiration is not None:
            # Add the license expiration label
            license_expiration_label = QLabel(f"License expiration in <b>{days_until_expiration+1}</b> day{'s' if days_until_expiration+1 > 1 else ''}")
            license_expiration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(license_expiration_label)
        
        # Add the clickable label with email
        # author_label = ClickableLabel(f"Grzegorz Ozimek (grzegorz.ozimek@valeo.com)", "mailto:grzegorz.ozimek@valeo.com")
        author_label = QLabel("Grzegorz Ozimek")
        author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author_label.setOpenExternalLinks(True)
        self.layout.addWidget(author_label)
        
        # Add the text with a link to www.github.com
        link_label = ClickableLabel("Github: https://www.github.com/hexafe/", "https://www.github.com/hexafe/")
        link_label.setOpenExternalLinks(True)
        link_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.layout.addWidget(link_label)

    def closeEvent(self, event):
        """Remove the temporary GIF file created for QMovie during teardown."""
        if getattr(self, "gif", None) is not None:
            if hasattr(self.gif, "stop"):
                self.gif.stop()

            if self._gif_label is not None:
                self._gif_label.setMovie(None)

            if hasattr(self.gif, "setFileName"):
                self.gif.setFileName("")

        if self._gif_temp_file_path and os.path.exists(self._gif_temp_file_path):
            try:
                os.remove(self._gif_temp_file_path)
                self._gif_temp_file_path = ""
            except PermissionError:
                # On Windows, delayed movie teardown can transiently keep the file handle open.
                pass
        super().closeEvent(event)
