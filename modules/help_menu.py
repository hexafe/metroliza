"""Helpers for attaching dialog/main-window Help menus to GitHub-rendered manuals."""

from __future__ import annotations

import os
from pathlib import Path
import types

try:
    import PyQt6.QtCore as QtCore
    import PyQt6.QtGui as QtGui
    import PyQt6.QtWidgets as QtWidgets
except (ImportError, OSError, RuntimeError):
    QtCore = types.SimpleNamespace()
    QtGui = types.SimpleNamespace()
    QtWidgets = types.SimpleNamespace()


REPO_ROOT = Path(__file__).resolve().parent.parent
USER_MANUAL_ROOT = REPO_ROOT / 'docs' / 'user_manual'
GITHUB_REPOSITORY_BASE_URL = 'https://github.com/hexafe/metroliza'
DEFAULT_RELEASE_DOCS_REF = 'master'
GITHUB_RENDERED_DOCS_REF = os.environ.get('METROLIZA_RELEASE_DOCS_REF', DEFAULT_RELEASE_DOCS_REF)

MANUAL_RELATIVE_PATHS = {
    'main_window': 'docs/user_manual/main_window.md',
    'parsing': 'docs/user_manual/parsing.md',
    'modify_database': 'docs/user_manual/modify_database.md',
    'export_overview': 'docs/user_manual/export_overview.md',
    'export_filtering': 'docs/user_manual/export_filtering.md',
    'export_grouping': 'docs/user_manual/export_grouping.md',
    'csv_summary': 'docs/user_manual/csv_summary.md',
    'characteristic_name_matching': 'docs/user_manual/characteristic_name_matching.md',
}
MANUAL_PATHS = {key: REPO_ROOT / relative_path for key, relative_path in MANUAL_RELATIVE_PATHS.items()}

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
    def __init__(self, url=''):
        self._url = str(url or '')

    @classmethod
    def fromLocalFile(cls, local_file):
        return cls(local_file)

    def toLocalFile(self):
        return self._url

    def toString(self):
        return self._url


QAction = getattr(QtGui, 'QAction', _FallbackAction)
QDesktopServices = getattr(QtGui, 'QDesktopServices', _FallbackDesktopServices)
QMenuBar = getattr(QtWidgets, 'QMenuBar', _FallbackMenuBar)
QMessageBox = getattr(QtWidgets, 'QMessageBox', _FallbackMessageBox)
QUrl = getattr(QtCore, 'QUrl', _FallbackUrl)


def manual_path(manual_key: str) -> Path:
    """Return the local manual path for a known manual key."""
    return MANUAL_PATHS[manual_key]


def github_blob_url(path: str | Path) -> str:
    """Return the GitHub-rendered repository URL for a repo-relative path."""
    relative_path = Path(path).as_posix().lstrip('/')
    return f'{GITHUB_REPOSITORY_BASE_URL}/blob/{GITHUB_RENDERED_DOCS_REF}/{relative_path}'


def manual_url(manual_key: str) -> str:
    """Return the GitHub rendered-file URL for a known manual key.

    GitHub's normal HTML page for a repository file uses a ``/blob/<ref>/...``
    path segment. That page is what gives the browser-friendly rendered Markdown
    view instead of downloading raw file contents.
    """
    return github_blob_url(MANUAL_RELATIVE_PATHS[manual_key])



def open_manual(parent, manual_key: str) -> bool:
    """Open a user manual in the default browser via GitHub."""
    try:
        url = manual_url(manual_key)
    except KeyError:
        QMessageBox.warning(parent, 'Manual not found', f'Unknown user manual key: {manual_key}')
        return False
    return bool(QDesktopServices.openUrl(QUrl(url)))



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


__all__ = [
    'DEFAULT_RELEASE_DOCS_REF',
    'GITHUB_RENDERED_DOCS_REF',
    'MANUAL_PATHS',
    'MANUAL_RELATIVE_PATHS',
    'USER_MANUAL_ROOT',
    'attach_help_menu_to_layout',
    'build_help_menu',
    'github_blob_url',
    'manual_path',
    'manual_url',
    'open_manual',
]
