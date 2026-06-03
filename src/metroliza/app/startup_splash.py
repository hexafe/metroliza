"""Startup splash-screen helpers.

The splash screen is deliberately isolated from bootstrap so tests and headless
startup smoke can disable it without importing Qt GUI classes.
"""

from __future__ import annotations

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
    """Thin wrapper around QSplashScreen with profile markers."""

    def __init__(self, app) -> None:
        record_event("splash_qt_import_start")
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor, QPixmap
        from PyQt6.QtWidgets import QSplashScreen

        record_event("splash_qt_import_done")
        pixmap = QPixmap(520, 240)
        pixmap.fill(QColor("#15202b"))
        self._alignment = (
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignBottom
            | Qt.TextFlag.TextWordWrap
        )
        self._text_color = QColor("#f8fafc")
        self._app = app
        self._splash = QSplashScreen(pixmap)
        self._splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._splash.show()
        self.show_message("Starting Metroliza...", phase="splash")
        record_event("splash_shown")

    def show_message(self, message: str, *, phase: str) -> None:
        record_event("splash_message", phase=phase)
        self._splash.showMessage(message, self._alignment, self._text_color)
        self._app.processEvents()

    def finish(self, widget: object) -> None:
        record_event("splash_finish_start")
        self._splash.finish(widget)
        self._app.processEvents()
        record_event("splash_finish_done")

    def close(self) -> None:
        record_event("splash_close_start")
        self._splash.close()
        self._app.processEvents()
        record_event("splash_close_done")


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
