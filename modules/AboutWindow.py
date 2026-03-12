"""About dialog and clickable label helpers for application metadata display."""

import os
import base64

import VersionDate
from PyQt6.QtCore import QSize, QTemporaryFile, Qt, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices, QMovie
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from modules import Base64EncodedFiles, ui_theme_tokens


class ClickableLabel(QLabel):
    """Label that behaves like a hyperlink and opens a fixed URL when clicked."""

    def __init__(self, text, link, default_style=None, hover_style=None):
        super().__init__(text)
        self.link = link
        self._default_style = default_style or "QLabel { color: #2563EB; text-decoration: underline; }"
        self._hover_style = hover_style or "QLabel { color: #1D4ED8; text-decoration: underline; }"
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(self._default_style)

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._default_style)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl(self.link))
        super().mousePressEvent(event)


class AboutWindow(QDialog):
    """Display version, license, and project attribution information.

    The dialog renders an embedded GIF from in-memory base64 content and keeps
    the movie instance alive for the dialog lifetime.
    """

    def __init__(self, parent=None, days_until_expiration=0):
        super().__init__(parent)
        self._gif_temp_file_path = ""
        self._gif_label = None

        self.setWindowTitle("About")
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.layout.setContentsMargins(
            ui_theme_tokens.SPACE_24,
            ui_theme_tokens.SPACE_20,
            ui_theme_tokens.SPACE_24,
            ui_theme_tokens.SPACE_20,
        )
        self.layout.setSpacing(ui_theme_tokens.SPACE_8)

        gif_label = QLabel()
        self._gif_label = gif_label

        gif_decoded = base64.b64decode(Base64EncodedFiles.encoded_loading_gif)

        temp_file = QTemporaryFile()
        temp_file.setAutoRemove(False)
        temp_file_name = ""
        if temp_file.open():
            temp_file.write(gif_decoded)
            temp_file.close()
            temp_file_name = temp_file.fileName()
            self._gif_temp_file_path = temp_file_name

        self.gif = QMovie(temp_file_name)
        self.gif.setScaledSize(QSize(184, 184))
        gif_label.setMovie(self.gif)
        gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gif_label.setContentsMargins(0, 0, 0, ui_theme_tokens.SPACE_8)
        self.gif.start()
        self.layout.addWidget(gif_label)

        title_label = QLabel(f"Metroliza version <b>{VersionDate.VERSION_LABEL}</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(ui_theme_tokens.typography_style("section", ui_theme_tokens.COLOR_TEXT_PRIMARY))
        self.layout.addWidget(title_label)

        if days_until_expiration is not None:
            license_expiration_label = QLabel(
                f"License expiration in <b>{days_until_expiration + 1}</b> "
                f"day{'s' if days_until_expiration + 1 > 1 else ''}"
            )
            license_expiration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            license_expiration_label.setStyleSheet(
                ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_SECONDARY)
            )
            self.layout.addWidget(license_expiration_label)

        author_label = QLabel("By Grzegorz Ozimek")
        author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author_label.setStyleSheet(ui_theme_tokens.typography_style("body", ui_theme_tokens.COLOR_TEXT_SECONDARY))
        author_label.setContentsMargins(0, ui_theme_tokens.SPACE_8, 0, 0)
        self.layout.addWidget(author_label)

        repository_row = QHBoxLayout()
        repository_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        repository_row.setSpacing(ui_theme_tokens.SPACE_8)

        repository_label = QLabel("Repository")
        repository_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_SECONDARY))

        repository_link = ClickableLabel(
            "Open on GitHub",
            "https://www.github.com/hexafe/",
            default_style=(
                "QLabel {"
                f" color: {ui_theme_tokens.COLOR_ACCENT};"
                " text-decoration: none;"
                f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_DEFAULT};"
                f" border-radius: {ui_theme_tokens.RADIUS_10}px;"
                f" padding: {ui_theme_tokens.SPACE_4}px {ui_theme_tokens.SPACE_12}px;"
                f" background-color: {ui_theme_tokens.COLOR_ACCENT_SUBTLE};"
                " font-weight: 600;"
                "}"
            ),
            hover_style=(
                "QLabel {"
                f" color: {ui_theme_tokens.COLOR_ACCENT_HOVER};"
                " text-decoration: none;"
                f" border: 1px solid {ui_theme_tokens.COLOR_ACCENT};"
                f" border-radius: {ui_theme_tokens.RADIUS_10}px;"
                f" padding: {ui_theme_tokens.SPACE_4}px {ui_theme_tokens.SPACE_12}px;"
                " background-color: #DBEAFE;"
                " font-weight: 600;"
                "}"
            ),
        )
        repository_row.addWidget(repository_label)
        repository_row.addWidget(repository_link)
        self.layout.addLayout(repository_row)

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
