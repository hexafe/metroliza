"""Startup splash-screen helpers.

The splash screen is deliberately isolated from bootstrap so tests and headless
startup smoke can disable it without importing Qt GUI classes.
"""

from __future__ import annotations

import base64
import os
from typing import Protocol

from metroliza.app.startup_profile import record_event
from metroliza.shared.env_utils import parse_bool

STARTUP_SPLASH_ENV = "METROLIZA_STARTUP_SPLASH"


class StartupSplash(Protocol):
    def show_message(self, message: str, *, phase: str) -> None: ...

    def finish(self, widget: object) -> None: ...

    def close(self) -> None: ...


class NullStartupSplash:
    """No-op splash implementation for tests, smoke runs, and disabled config."""

    def show_message(self, message: str, *, phase: str) -> None:
        record_event("splash_message_skipped", phase=phase)

    def finish(self, widget: object) -> None:
        record_event("splash_finish_skipped")

    def close(self) -> None:
        record_event("splash_close_skipped")


def _normalized_mode() -> str:
    raw_value = os.getenv(STARTUP_SPLASH_ENV)
    if raw_value is None:
        return "auto"

    normalized = raw_value.strip().lower()
    if normalized in {"auto", "default"}:
        return "auto"
    if parse_bool(normalized, default=False):
        return "1"
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return "0"
    return "auto"


def should_show_startup_splash(*, ui_smoke_mode: bool) -> bool:
    """Return whether a visual startup splash should be shown for this launch."""

    mode = _normalized_mode()
    if mode == "1":
        return True
    if mode == "0":
        return False

    platform_name = os.getenv("QT_QPA_PLATFORM", "").strip().lower()
    if ui_smoke_mode or platform_name in {"offscreen", "minimal"}:
        return False
    return True


class QtStartupSplash:
    """Animated startup splash with profile markers."""

    def __init__(self, app) -> None:
        record_event("splash_qt_import_start")
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
        from PyQt6.QtGui import QImageReader, QMovie
        from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

        record_event("splash_qt_import_done")
        self._app = app
        self._movie = None
        self._gif_buffer = None
        self._gif_reader_buffer = None

        window_flags = (
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._splash = QDialog(None, window_flags)
        self._splash.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._splash.setObjectName("metrolizaStartupSplash")
        self._splash.setStyleSheet(
            """
            QDialog#metrolizaStartupSplash {
                background: #15202b;
                border: 1px solid #2f4858;
                border-radius: 8px;
            }
            QLabel#metrolizaStartupTitle {
                color: #f8fafc;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#metrolizaStartupMessage {
                color: #cbd5e1;
                font-size: 13px;
            }
            """
        )

        self._gif_label = QLabel(self._splash)
        self._gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gif_label.setFixedSize(QSize(128, 128))
        self._gif_label.setText("Metroliza")
        self._gif_label.setStyleSheet("color: #f8fafc; font-weight: 700;")

        title_label = QLabel("Metroliza", self._splash)
        title_label.setObjectName("metrolizaStartupTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._message_label = QLabel("Metroliza is loading...", self._splash)
        self._message_label.setObjectName("metrolizaStartupMessage")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._message_label.setWordWrap(True)
        self._message_label.setMinimumWidth(280)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)
        text_layout.addStretch(1)
        text_layout.addWidget(title_label)
        text_layout.addWidget(self._message_label)
        text_layout.addStretch(1)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(16)
        content_layout.addWidget(self._gif_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        content_layout.addLayout(text_layout, stretch=1)

        self._splash.setLayout(content_layout)
        self._splash.setFixedSize(500, 190)
        self._install_loading_movie(QByteArray, QBuffer, QIODevice, QImageReader, QMovie, QSize)
        self._splash.show()
        self._center_on_screen()
        self.show_message("Metroliza is loading...", phase="splash")
        record_event("splash_shown")

    def _install_loading_movie(
        self,
        qbyte_array_type,
        qbuffer_type,
        qiodevice_type,
        qimage_reader_type,
        qmovie_type,
        qsize_type,
    ) -> None:
        try:
            from metroliza.resources import base64_encoded_files

            loading_gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)
            self._gif_reader_buffer = qbuffer_type(self._splash)
            self._gif_reader_buffer.setData(qbyte_array_type(loading_gif_decoded))
            self._gif_reader_buffer.open(qiodevice_type.OpenModeFlag.ReadOnly)
            source_size = qimage_reader_type(self._gif_reader_buffer, b"gif").size()

            self._gif_buffer = qbuffer_type(self._splash)
            self._gif_buffer.setData(qbyte_array_type(loading_gif_decoded))
            self._gif_buffer.open(qiodevice_type.OpenModeFlag.ReadOnly)

            self._movie = qmovie_type(self._gif_buffer, b"gif", self._splash)
            self._movie.setScaledSize(_scaled_splash_gif_size(source_size, qsize_type))
            self._gif_label.setMovie(self._movie)
            self._movie.start()
            record_event("splash_gif_loaded")
        except Exception as exc:  # pragma: no cover - defensive fallback for packaged assets.
            record_event("splash_gif_failed", error_type=type(exc).__name__)

    def _center_on_screen(self) -> None:
        screen = self._splash.screen() or self._app.primaryScreen()
        if screen is None:
            return

        available_geometry = screen.availableGeometry()
        frame_geometry = self._splash.frameGeometry()
        frame_geometry.moveCenter(available_geometry.center())
        self._splash.move(frame_geometry.topLeft())

    def show_message(self, message: str, *, phase: str) -> None:
        record_event("splash_message", phase=phase)
        self._message_label.setText(message or "Metroliza is loading...")
        self._app.processEvents()

    def finish(self, widget: object) -> None:
        record_event("splash_finish_start")
        if hasattr(widget, "raise_"):
            widget.raise_()
        if hasattr(widget, "activateWindow"):
            widget.activateWindow()
        self._splash.close()
        self._app.processEvents()
        record_event("splash_finish_done")

    def close(self) -> None:
        record_event("splash_close_start")
        self._splash.close()
        self._app.processEvents()
        record_event("splash_close_done")


def _scaled_splash_gif_size(source_size, qsize_type):
    target_max_dimension = 128
    if not source_size.isValid() or source_size.isEmpty():
        return qsize_type(target_max_dimension, target_max_dimension)

    width = source_size.width()
    height = source_size.height()
    if width >= height:
        scaled_width = target_max_dimension
        scaled_height = max(1, round((target_max_dimension * height) / width))
    else:
        scaled_height = target_max_dimension
        scaled_width = max(1, round((target_max_dimension * width) / height))
    return qsize_type(scaled_width, scaled_height)


def create_startup_splash(app, *, ui_smoke_mode: bool) -> StartupSplash:
    """Create a startup splash or a no-op replacement for this launch."""

    if not should_show_startup_splash(ui_smoke_mode=ui_smoke_mode):
        record_event("splash_disabled")
        return NullStartupSplash()

    try:
        return QtStartupSplash(app)
    except Exception as exc:
        record_event("splash_failed", error_type=type(exc).__name__)
        return NullStartupSplash()
