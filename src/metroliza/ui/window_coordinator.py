"""Lifecycle and workspace-context ownership for modeless PyQt windows."""

from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget

from metroliza.ui.workspace_context import (
    WorkspaceContext,
    WorkspaceField,
    WorkspaceSnapshot,
)


logger = logging.getLogger(__name__)
WindowFactory = Callable[[WorkspaceSnapshot], QWidget]
ContextUpdater = Callable[[QWidget, WorkspaceSnapshot], None]
_ALL_WORKSPACE_FIELDS = frozenset(
    {WorkspaceField.SOURCE_DIRECTORY, WorkspaceField.DATABASE_FILE}
)


class WindowContextPolicy(str, Enum):
    """Action applied when a relevant workspace field changes."""

    KEEP = "keep"
    CLOSE = "close"
    UPDATE = "update"


@dataclass(frozen=True, slots=True)
class ModelessWindowSpec:
    """Registration contract for one stable modeless window identity."""

    window_id: str
    factory: WindowFactory
    context_policy: WindowContextPolicy = WindowContextPolicy.KEEP
    context_fields: frozenset[WorkspaceField] = _ALL_WORKSPACE_FIELDS
    context_updater: ContextUpdater | None = None

    def __post_init__(self) -> None:
        if not self.window_id.strip():
            raise ValueError("Modeless window ID must not be empty.")
        if not callable(self.factory):
            raise TypeError("Modeless window factory must be callable.")
        normalized_policy = WindowContextPolicy(self.context_policy)
        normalized_fields = frozenset(WorkspaceField(field) for field in self.context_fields)
        object.__setattr__(self, "context_policy", normalized_policy)
        object.__setattr__(self, "context_fields", normalized_fields)
        if normalized_policy is WindowContextPolicy.UPDATE and not callable(
            self.context_updater
        ):
            raise ValueError("UPDATE context policy requires a context_updater callback.")


@dataclass(slots=True)
class _OpenWindow:
    widget: QWidget
    generation: int
    context_version: int


class WindowCoordinator(QObject):
    """Keep one live widget per ID and apply explicit context-change policies."""

    window_opened = pyqtSignal(str, object)
    window_reused = pyqtSignal(str, object)
    window_closed = pyqtSignal(str)
    window_close_deferral_cancelled = pyqtSignal(str)
    context_update_failed = pyqtSignal(str, object)

    def __init__(
        self,
        workspace_context: WorkspaceContext,
        *,
        parent: QObject | None = None,
    ) -> None:
        if not isinstance(workspace_context, WorkspaceContext):
            raise TypeError("WindowCoordinator requires a WorkspaceContext.")
        super().__init__(parent)
        self._workspace_context = workspace_context
        self._specs: dict[str, ModelessWindowSpec] = {}
        self._open_windows: dict[str, _OpenWindow] = {}
        self._generation = 0
        workspace_context.snapshot_changed.connect(self._on_workspace_snapshot_changed)

    @property
    def registered_window_ids(self) -> tuple[str, ...]:
        return tuple(self._specs)

    @property
    def open_window_ids(self) -> tuple[str, ...]:
        return tuple(self._open_windows)

    def register_modeless(
        self,
        spec_or_id: ModelessWindowSpec | str,
        factory: WindowFactory | None = None,
        *,
        context_policy: WindowContextPolicy = WindowContextPolicy.KEEP,
        context_fields: frozenset[WorkspaceField] = _ALL_WORKSPACE_FIELDS,
        context_updater: ContextUpdater | None = None,
    ) -> ModelessWindowSpec:
        """Register one stable modeless window contract."""

        if isinstance(spec_or_id, ModelessWindowSpec):
            if factory is not None:
                raise ValueError("Factory must not be supplied with a ModelessWindowSpec.")
            spec = spec_or_id
        else:
            if factory is None:
                raise ValueError("A modeless window factory is required.")
            spec = ModelessWindowSpec(
                window_id=str(spec_or_id),
                factory=factory,
                context_policy=context_policy,
                context_fields=context_fields,
                context_updater=context_updater,
            )
        if spec.window_id in self._specs:
            raise ValueError(f"Modeless window {spec.window_id!r} is already registered.")
        self._specs[spec.window_id] = spec
        return spec

    def open_modeless(
        self,
        window_id: str,
        factory: WindowFactory | None = None,
        *,
        context_policy: WindowContextPolicy = WindowContextPolicy.KEEP,
        context_fields: frozenset[WorkspaceField] = _ALL_WORKSPACE_FIELDS,
        context_updater: ContextUpdater | None = None,
    ) -> QWidget:
        """Open or reuse a registered window.

        Passing ``factory`` provides a convenience registration path for callers
        that do not need a separate composition phase.
        """

        normalized_id = str(window_id or "").strip()
        if factory is not None:
            self._register_inline_factory(
                normalized_id,
                factory,
                context_policy=context_policy,
                context_fields=context_fields,
                context_updater=context_updater,
            )
        spec = self._specs.get(normalized_id)
        if spec is None:
            raise KeyError(f"Unknown modeless window {normalized_id!r}.")

        existing_widget = self._reuse_open_window(normalized_id)
        if existing_widget is not None:
            return existing_widget
        widget = spec.factory(self._workspace_context.snapshot)
        if not isinstance(widget, QWidget):
            raise TypeError("Modeless window factories must return a QWidget.")
        return self._track_and_show_window(normalized_id, widget)

    def _register_inline_factory(
        self,
        window_id: str,
        factory: WindowFactory,
        *,
        context_policy: WindowContextPolicy,
        context_fields: frozenset[WorkspaceField],
        context_updater: ContextUpdater | None,
    ) -> None:
        if window_id in self._specs:
            raise ValueError(f"Modeless window {window_id!r} is already registered.")
        self.register_modeless(
            window_id,
            factory,
            context_policy=context_policy,
            context_fields=context_fields,
            context_updater=context_updater,
        )

    def _reuse_open_window(self, window_id: str) -> QWidget | None:
        existing = self._open_windows.get(window_id)
        if existing is None:
            return None
        try:
            existing.widget.show()
            existing.widget.raise_()
            existing.widget.activateWindow()
        except RuntimeError:
            self._open_windows.pop(window_id, None)
            return None
        self.window_reused.emit(window_id, existing.widget)
        return existing.widget

    def _track_and_show_window(self, window_id: str, widget: QWidget) -> QWidget:
        widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._generation += 1
        generation = self._generation
        self._open_windows[window_id] = _OpenWindow(
            widget=widget,
            generation=generation,
            context_version=self._workspace_context.snapshot.version,
        )
        widget.destroyed.connect(self._destroyed_callback(window_id, generation))
        deferral_cancelled = getattr(widget, "close_deferral_cancelled", None)
        connect_cancelled = getattr(deferral_cancelled, "connect", None)
        if callable(connect_cancelled):
            connect_cancelled(
                lambda: self._on_close_deferral_cancelled(window_id, generation)
            )
        widget.show()
        widget.raise_()
        widget.activateWindow()
        self.window_opened.emit(window_id, widget)
        return widget

    def _destroyed_callback(self, window_id: str, generation: int):
        coordinator_ref = weakref.ref(self)

        def _window_destroyed(_object=None):
            coordinator = coordinator_ref()
            if coordinator is None:
                return
            try:
                coordinator._on_window_destroyed(window_id, generation)
            except RuntimeError:
                # QApplication teardown may delete the coordinator before its
                # top-level windows emit their final destroyed signals.
                return

        return _window_destroyed

    def get(self, window_id: str) -> QWidget | None:
        opened = self._open_windows.get(str(window_id or "").strip())
        return None if opened is None else opened.widget

    def close(self, window_id: str) -> bool:
        widget = self.get(window_id)
        if widget is None:
            return True
        try:
            return bool(widget.close())
        except RuntimeError:
            self._open_windows.pop(str(window_id or "").strip(), None)
            return True

    def close_all(self) -> tuple[str, ...]:
        """Close all managed windows and return IDs whose close was rejected."""

        blocked: list[str] = []
        for window_id in tuple(self._open_windows):
            if not self.close(window_id):
                blocked.append(window_id)
        return tuple(blocked)

    def is_close_deferred(self, window_id: str) -> bool:
        """Return whether a rejected close is a cooperative, self-finishing shutdown."""

        widget = self.get(window_id)
        if widget is None:
            return False
        deferred_check = getattr(widget, "is_close_deferred", None)
        if not callable(deferred_check):
            return False
        try:
            return bool(deferred_check())
        except (AttributeError, RuntimeError):
            return False

    def unregister(self, window_id: str) -> bool:
        normalized_id = str(window_id or "").strip()
        if normalized_id in self._open_windows:
            return False
        return self._specs.pop(normalized_id, None) is not None

    def _on_workspace_snapshot_changed(
        self,
        current: WorkspaceSnapshot,
        previous: WorkspaceSnapshot,
    ) -> None:
        changed_fields = current.changed_fields(previous)
        for window_id, opened in tuple(self._open_windows.items()):
            spec = self._specs.get(window_id)
            if spec is None or not changed_fields.intersection(spec.context_fields):
                continue
            if spec.context_policy is WindowContextPolicy.KEEP:
                continue
            if spec.context_policy is WindowContextPolicy.CLOSE:
                self.close(window_id)
                continue
            updater = spec.context_updater
            if updater is None:  # Defensive; ModelessWindowSpec validates this.
                continue
            try:
                updater(opened.widget, current)
            except Exception as exc:
                logger.exception("Failed to update modeless window %s context", window_id)
                self.context_update_failed.emit(window_id, exc)
                continue
            opened.context_version = current.version

    def _on_window_destroyed(self, window_id: str, generation: int) -> None:
        opened = self._open_windows.get(window_id)
        if opened is None or opened.generation != generation:
            return
        self._open_windows.pop(window_id, None)
        self.window_closed.emit(window_id)

    def _on_close_deferral_cancelled(self, window_id: str, generation: int) -> None:
        opened = self._open_windows.get(window_id)
        if opened is None or opened.generation != generation:
            return
        self.window_close_deferral_cancelled.emit(window_id)


__all__ = [
    "ContextUpdater",
    "ModelessWindowSpec",
    "WindowContextPolicy",
    "WindowCoordinator",
    "WindowFactory",
]
