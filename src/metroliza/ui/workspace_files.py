"""File menu commands for saving and restoring the active Reports workspace."""

from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from metroliza.app.workspace_file import WORKSPACE_FILTER, read_workspace, write_workspace
from metroliza.reports.db import DatabaseSourceChanged, SQLiteFileBinding
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
        self.context_at_open = None

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
            snapshot = self.window.workspace_context.snapshot
            draft = self.window.report_grouping_draft
            if draft is not None and self.window.get_report_grouping_draft(snapshot.database_file) is None:
                self._error("Select the Reports database again before saving its grouping draft.")
                return
            self._start(write_workspace, self._saved, path, snapshot,
                        self.window.navigation_combo.currentData(), consents, draft)

    def _saved(self, path):
        self.window.statusBar().showMessage(f"Workspace saved to {path}", 8000)

    def open(self):
        if not self.window._report_context_change_allowed():
            return
        selected, _ = QFileDialog.getOpenFileName(self.window, "Open workspace", "", WORKSPACE_FILTER)
        if selected:
            self.context_at_open = self._report_context_token()
            self._start(_prepare_workspace, self._restore, selected)

    def _report_context_token(self):
        return self.window.workspace_context.snapshot.version, self.window.report_grouping_draft

    def _restore(self, prepared):
        state, missing, database_binding = prepared
        if not missing:
            self._apply(self._locations(state), state, database_binding)
            return
        chosen = self._locations(state)
        for field in missing:
            location = getattr(state, field)
            candidate = self._relink(field, location)
            if not candidate:
                return
            chosen[field] = candidate
        self._start(_verify_relinks, self._apply_verified, state, chosen)

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

    def _apply(self, selected, state, database_binding):
        version, draft = self._report_context_token()
        opening_version, opening_draft = self.context_at_open
        if version != opening_version or draft is not opening_draft:
            self._error("The current workspace changed while this file was opening. Open it again to apply it.")
            return
        if database_binding is not None:
            try:
                database_binding.require(selected["database"])
            except (DatabaseSourceChanged, OSError, ValueError) as exc:
                self._error(str(exc))
                return
        if self.window.restore_workspace_locations(
            selected["database"], selected["source"], state.page, report_grouping_draft=state.report_grouping_draft,
        ):
            self.window.statusBar().showMessage("Workspace restored", 6000)


def _match_location(state, field, path):
    location = getattr(state, field)
    if field != "database" or state.report_grouping_draft is None:
        return location.matches(path), None
    try:
        binding = SQLiteFileBinding.capture(path)
        if binding.identity is not None and location.matches(path):
            binding.require(path)
            return True, binding
    except (DatabaseSourceChanged, OSError, ValueError):
        pass
    return False, None


def _prepare_workspace(filename):
    state = read_workspace(filename)
    missing = []
    database_binding = None
    for field in ("source", "database"):
        location = getattr(state, field)
        if location:
            matched, binding = _match_location(state, field, location.path)
            if not matched:
                missing.append(field)
            if binding is not None:
                database_binding = binding
    return state, missing, database_binding


def _verify_relinks(state, selected):
    database_binding = None
    for field, path in selected.items():
        location = getattr(state, field)
        if location is not None:
            matched, binding = _match_location(state, field, path)
            if not matched:
                raise ValueError(f"The selected location did not match the saved {field}. Choose the original or an unchanged copy.")
            if binding is not None:
                database_binding = binding
    return selected, state, database_binding
