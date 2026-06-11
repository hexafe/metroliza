"""About dialog and clickable label helpers for application metadata display."""

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt, QUrl
from PyQt6.QtGui import QMovie, QDesktopServices, QCursor
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from metroliza.resources import base64_encoded_files
from metroliza.app import version as VersionDate
import base64


SUPPORT_URL = "https://www.github.com/hexafe/"


def build_support_build_info() -> str:
    """Return compact support metadata that users can copy from the About dialog."""
    public_version = getattr(VersionDate, "PUBLIC_VERSION_LABEL", VersionDate.VERSION_LABEL)
    return "\n".join(
        [
            "Support/build info",
            f"Version: {public_version}",
            f"Internal version: {VersionDate.VERSION_LABEL}",
            f"Build: {VersionDate.VERSION_DATE}",
            "Manual: Help > Startup, license, and support",
            f"Support URL: {SUPPORT_URL}",
        ]
    )


def _make_selectable(label):
    if hasattr(label, "setTextInteractionFlags") and hasattr(Qt, "TextInteractionFlag"):
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
    return label


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

    The dialog renders an embedded GIF from in-memory base64 content and keeps the
    backing buffer and movie instance alive for the dialog lifetime.
    """

    def __init__(self, parent=None, days_until_expiration=0):
        super().__init__(parent)
        self._gif_buffer = None
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

        gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)
        self._gif_buffer = QBuffer(self)
        self._gif_buffer.setData(QByteArray(gif_decoded))
        self._gif_buffer.open(QIODevice.OpenModeFlag.ReadOnly)

        self.gif = QMovie(self._gif_buffer, b"gif", self)
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

        support_info_label = _make_selectable(QLabel(build_support_build_info()))
        support_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.support_info_label = support_info_label
        self.layout.addWidget(support_info_label)

        # Add the text with a link to www.github.com
        link_label = ClickableLabel(f"Github: {SUPPORT_URL}", SUPPORT_URL)
        link_label.setOpenExternalLinks(True)
        link_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.layout.addWidget(link_label)

    def closeEvent(self, event):
        """Stop GIF playback and release the in-memory backing buffer."""
        if getattr(self, "gif", None) is not None:
            if hasattr(self.gif, "stop"):
                self.gif.stop()

            if self._gif_label is not None:
                self._gif_label.setMovie(None)

        if self._gif_buffer is not None and hasattr(self._gif_buffer, "close"):
            self._gif_buffer.close()
            self._gif_buffer = None
        super().closeEvent(event)
