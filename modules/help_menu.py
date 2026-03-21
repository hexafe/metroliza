"""Helpers for attaching dialog/main-window Help menus to local user manuals."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtWidgets import QMenuBar, QMessageBox


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


__all__ = ['MANUAL_PATHS', 'USER_MANUAL_ROOT', 'build_help_menu', 'manual_path', 'open_manual']
