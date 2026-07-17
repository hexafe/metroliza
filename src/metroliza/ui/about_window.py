"""About dialog and clickable label helpers for application metadata display."""

import base64
import html

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QMovie
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

from metroliza.app import version as VersionDate
from metroliza.resources import base64_encoded_files


SUPPORT_URL = "https://github.com/hexafe/metroliza"


class ClickableLabel(QLabel):
    """Keyboard-focusable rich-text link retained for compatibility."""

    def __init__(self, text, link):
        self.link = str(link)
        safe_link = html.escape(self.link, quote=True)
        safe_text = html.escape(str(text))
        super().__init__(f'<a href="{safe_link}">{safe_text}</a>')
        if hasattr(self, "setProperty"):
            self.setProperty("linkLabel", True)
        text_browser_interaction = getattr(
            getattr(Qt, "TextInteractionFlag", object()),
            "TextBrowserInteraction",
            None,
        )
        if text_browser_interaction is not None and hasattr(self, "setTextInteractionFlags"):
            self.setTextInteractionFlags(text_browser_interaction)
        strong_focus = getattr(getattr(Qt, "FocusPolicy", object()), "StrongFocus", None)
        if strong_focus is not None and hasattr(self, "setFocusPolicy"):
            self.setFocusPolicy(strong_focus)
        if hasattr(self, "setOpenExternalLinks"):
            self.setOpenExternalLinks(True)
        if hasattr(self, "setAccessibleName"):
            self.setAccessibleName(str(text))
        if hasattr(self, "setAccessibleDescription"):
            self.setAccessibleDescription(f"Opens {self.link} in the default browser")
        if hasattr(self, "setToolTip"):
            self.setToolTip(self.link)

    def keyPressEvent(self, event):
        activation_keys = {
            getattr(Qt.Key, "Key_Return", None),
            getattr(Qt.Key, "Key_Enter", None),
            getattr(Qt.Key, "Key_Space", None),
        }
        if event.key() in activation_keys:
            QDesktopServices.openUrl(QUrl(self.link))
            event.accept()
            return
        super().keyPressEvent(event)


class AboutWindow(QDialog):
    """Display compact version and project attribution information.

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

        # Add the clickable label with email
        # author_label = ClickableLabel(f"Grzegorz Ozimek (grzegorz.ozimek@valeo.com)", "mailto:grzegorz.ozimek@valeo.com")
        author_label = QLabel("Grzegorz Ozimek")
        author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author_label.setOpenExternalLinks(True)
        self.layout.addWidget(author_label)

        # Add the text with a link to www.github.com
        self.support_link_label = ClickableLabel(f"GitHub: {SUPPORT_URL}", SUPPORT_URL)
        self.support_link_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.layout.addWidget(self.support_link_label)

        # Import lazily so lightweight metadata tests can continue to use Qt stubs.
        try:
            from metroliza.ui.ui_foundation import (
                apply_metroliza_theme,
                configure_window_size,
                finalize_window_size,
            )

            configure_window_size(self, minimum=(300, 320), initial=(360, 380))
            apply_metroliza_theme(self)
            finalize_window_size(self)
        except (AttributeError, ImportError):  # pragma: no cover - lightweight Qt stubs
            pass

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
