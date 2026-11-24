"""Lazy boundary between application startup and the concrete Qt main window."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Callable, Protocol, cast


MAIN_WINDOW_MODULE = "metroliza.ui.main_window"
RECIPE_QUALIFICATION_MODULE = "metroliza.ui.recipe_qualification"


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


def install_recipe_qualification(main_window: MainWindowHandle, root: Path) -> None:
    """Load the fixed GUI probe through the existing lazy application/UI boundary."""
    module = import_module(RECIPE_QUALIFICATION_MODULE)
    installer = getattr(module, "install_recipe_qualification", None)
    if not callable(installer):
        raise TypeError("Recipe qualification entry point is unavailable")
    installer(main_window, root)
