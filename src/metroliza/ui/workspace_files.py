"""File menu commands for saving and restoring the active Reports workspace."""

from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from metroliza.app.workspace_file import WORKSPACE_FILTER, read_workspace, write_workspace
from metroliza.shared.sqlite_paths import SQLITE_FILE_FILTER
from metroliza.ui.analysis_history_dialog import collect_output_consent
from metroliza.ui.local_file_task import LocalFileTask


class WorkspaceFiles(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.task = None
        self.save_action = window.save_workspace_action
        self.open_action = window.open_workspace_action
        self.version_at_open = None

    def _start(self, operation, callback, *args):
        self.open_action.setEnabled(False)
        self.save_action.setEnabled(False)
        self.task = LocalFileTask(operation, *args)
        self.task.succeeded.connect(callback)
        self.task.failed.connect(self._error)
        self.task.start_owned(self, WorkspaceFiles._finished)

    def _error(self, message):
        QMessageBox.warning(self.window, "Workspace file", message)

    def _finished(self, task):
        if self.task is task:
            self.task = None
            self.open_action.setEnabled(True)
            self.save_action.setEnabled(True)
        task.deleteLater()

    def save(self):
        selected, _ = QFileDialog.getSaveFileName(
            self.window, "Save workspace", "", WORKSPACE_FILTER,
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".metroliza-workspace":
            path = path.with_suffix(".metroliza-workspace")
        try:
            consents = collect_output_consent(self.window, path)
        except OSError as exc:
            self._error(str(exc))
            return
        if consents is not None:
            self._start(write_workspace, self._saved, path, self.window.workspace_context.snapshot,
                        self.window.navigation_combo.currentData(), consents)

    def _saved(self, path):
        self.window.statusBar().showMessage(f"Workspace saved to {path}", 8000)

    def open(self):
        if not self.window._report_context_change_allowed():
            return
        selected, _ = QFileDialog.getOpenFileName(self.window, "Open workspace", "", WORKSPACE_FILTER)
        if selected:
            self.version_at_open = self.window.workspace_context.snapshot.version
            self._start(_prepare_workspace, self._restore, selected)

    def _restore(self, prepared):
        state, missing = prepared
        if not missing:
            self._apply(self._locations(state), state.page)
            return
        chosen = self._locations(state)
        for field in missing:
            location = getattr(state, field)
            candidate = self._relink(field, location)
            if not candidate:
                return
            chosen[field] = candidate
        self._start(_verify_relinks, self._apply_verified, state, tuple(missing), chosen)

    @staticmethod
    def _locations(state):
        return {name: getattr(state, name).path if getattr(state, name) else None for name in ("source", "database")}

    def _relink(self, field, location):
        name = Path(location.path).name
        if location.directory:
            return QFileDialog.getExistingDirectory(self.window, f"Locate report folder: {name}")
        file_filter = SQLITE_FILE_FILTER if field == "database" else "Report archives (*.zip *.7z *.tar *.gz);;All files (*)"
        selected, _ = QFileDialog.getOpenFileName(self.window, f"Locate {name}", "", file_filter)
        return selected

    def _apply_verified(self, result):
        self._apply(*result)

    def _apply(self, selected, page):
        if self.window.workspace_context.snapshot.version != self.version_at_open:
            self._error("The current workspace changed while this file was opening. Open it again to apply it.")
            return
        if self.window.restore_workspace_locations(selected["database"], selected["source"], page):
            self.window.statusBar().showMessage("Workspace restored", 6000)


def _prepare_workspace(filename):
    state = read_workspace(filename)
    missing = []
    for field in ("source", "database"):
        location = getattr(state, field)
        if location and not location.matches(location.path):
            missing.append(field)
    return state, missing


def _verify_relinks(state, missing, selected):
    for field in missing:
        location = getattr(state, field)
        if not location.matches(selected[field]):
            raise ValueError(f"The selected location did not match the saved {field}. Choose the original or an unchanged copy.")
    return selected, state.page
