"""Lazy boundary between application startup and the concrete Qt main window."""

from __future__ import annotations

from importlib import import_module
from typing import Callable, Protocol, cast


MAIN_WINDOW_MODULE = "metroliza.ui.main_window"


class MainWindowHandle(Protocol):
    """Startup-facing behavior exposed by the concrete main window."""

    def show(self) -> None: ...

    def schedule_feature_import_warmup(
        self,
        *,
        delay_ms: int = 100,
        on_finished: Callable[[], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None: ...


class MainWindowFactory(Protocol):
    """Constructor shape required by the application startup orchestrator."""

    def __call__(
        self,
        version_label: str,
        days_until_expiration: int | None,
    ) -> MainWindowHandle: ...


def load_main_window_factory() -> MainWindowFactory:
    """Resolve the Qt main window only after startup has created QApplication."""
    module = import_module(MAIN_WINDOW_MODULE)
    factory = getattr(module, "MainWindow", None)
    if not callable(factory):
        raise TypeError(f"{MAIN_WINDOW_MODULE}.MainWindow must be callable")
    return cast(MainWindowFactory, factory)
