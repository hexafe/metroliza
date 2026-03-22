"""Helpers for attaching dialog/main-window Help menus to local user manuals."""

from __future__ import annotations

from pathlib import Path
import types

import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui
import PyQt6.QtWidgets as QtWidgets


REPO_ROOT = Path(__file__).resolve().parent.parent
USER_MANUAL_ROOT = REPO_ROOT / 'docs' / 'user_manual'

MANUAL_PATHS = {
    'main_window': USER_MANUAL_ROOT / 'main_window.md',
    'parsing': USER_MANUAL_ROOT / 'parsing.md',
    'modify_database': USER_MANUAL_ROOT / 'modify_database.md',
    'export_overview': USER_MANUAL_ROOT / 'export_overview.md',
    'export_filtering': USER_MANUAL_ROOT / 'export_filtering.md',
    'export_grouping': USER_MANUAL_ROOT / 'export_grouping.md',
    'csv_summary': USER_MANUAL_ROOT / 'csv_summary.md',
    'characteristic_name_matching': USER_MANUAL_ROOT / 'characteristic_name_matching.md',
}


class _FallbackAction:
    def __init__(self, *_args, **_kwargs):
        self.triggered = types.SimpleNamespace(connect=lambda *_a, **_k: None)


class _FallbackMenu:
    def __init__(self):
        self.actions = []

    def addAction(self, action):
        self.actions.append(action)


class _FallbackMenuBar:
    def __init__(self, *_args, **_kwargs):
        self.menus = []

    def addMenu(self, _title):
        menu = _FallbackMenu()
        self.menus.append(menu)
        return menu


class _FallbackMessageBox:
    @staticmethod
    def warning(*_args, **_kwargs):
        return None


class _FallbackDesktopServices:
    @staticmethod
    def openUrl(*_args, **_kwargs):
        return False


class _FallbackUrl:
    def __init__(self, local_file=''):
        self._local_file = str(local_file or '')

    @classmethod
    def fromLocalFile(cls, local_file):
        return cls(local_file)

    def toLocalFile(self):
        return self._local_file


QAction = getattr(QtGui, 'QAction', _FallbackAction)
QDesktopServices = getattr(QtGui, 'QDesktopServices', _FallbackDesktopServices)
QMenuBar = getattr(QtWidgets, 'QMenuBar', _FallbackMenuBar)
QMessageBox = getattr(QtWidgets, 'QMessageBox', _FallbackMessageBox)
QUrl = getattr(QtCore, 'QUrl', _FallbackUrl)


def manual_path(manual_key: str) -> Path:
    """Return the local manual path for a known manual key."""
    return MANUAL_PATHS[manual_key]



def open_manual(parent, manual_key: str) -> bool:
    """Open a local user manual and warn if it is unavailable."""
    path = manual_path(manual_key)
    if not path.exists():
        QMessageBox.warning(parent, 'Manual not found', f'Could not find the user manual at:\n{path}')
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))))



def build_help_menu(parent, entries, *, menu_bar=None):
    """Create a Help menu with one action per manual entry.

    Args:
        parent: Dialog or window owning the menu.
        entries: Iterable of ``(label, manual_key)`` tuples.
        menu_bar: Existing menu bar to attach to. When omitted, a new ``QMenuBar``
            is created for layout-based dialogs.
    """
    resolved_menu_bar = menu_bar or QMenuBar(parent)
    help_menu = resolved_menu_bar.addMenu('Help')
    for label, manual_key in entries:
        action = QAction(label, parent)
        action.triggered.connect(lambda _checked=False, key=manual_key, owner=parent: open_manual(owner, key))
        help_menu.addAction(action)
    return resolved_menu_bar, help_menu




def attach_help_menu_to_layout(layout, parent, entries):
    """Attach a Help menu to a dialog layout when the layout supports menu bars."""
    dialog_menu_bar, help_menu = build_help_menu(parent, entries)
    if hasattr(layout, 'setMenuBar'):
        layout.setMenuBar(dialog_menu_bar)
    return dialog_menu_bar, help_menu


__all__ = ['MANUAL_PATHS', 'USER_MANUAL_ROOT', 'attach_help_menu_to_layout', 'build_help_menu', 'manual_path', 'open_manual']
