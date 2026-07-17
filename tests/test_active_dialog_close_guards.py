from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QEvent, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QProgressBar

import metroliza.ui.export_dialog as export_dialog_module
import metroliza.ui.parsing_dialog as parsing_dialog_module
from metroliza.ui.window_coordinator import WindowCoordinator
from metroliza.ui.workspace_context import WorkspaceContext


_QT_APP = None


@pytest.fixture(scope="module")
def qapp():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


class _CancelableThread(QThread):
    def __init__(self, *args, cancel_calls: list[str] | None = None, **kwargs):
        super().__init__()
        self._release = Event()
        self._cancel_calls = cancel_calls if cancel_calls is not None else []

    def run(self):
        self._release.wait(timeout=5)

    def release(self):
        self._release.set()

    def _cancel(self, operation: str):
        self._cancel_calls.append(operation)
        self.release()


class _PreflightThread(_CancelableThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def stop_scan(self):
        self._cancel("preflight")


class _ParseThread(_CancelableThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def stop_parsing(self):
        self._cancel("parse")


class _ExportThread(_CancelableThread):
    update_progress = pyqtSignal(int)
    update_label = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    completed = pyqtSignal()
    canceled = pyqtSignal()

    def stop_exporting(self):
        self._cancel("export")


def _progress_dialog(parent, **_kwargs):
    dialog = QDialog(parent)
    return dialog, QLabel(dialog), QProgressBar(dialog), None


def _wait_until(qapp, predicate, *, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _track_deletion(dialog):
    deleted = []
    dialog.destroyed.connect(lambda *_args: deleted.append(True))
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dialog.show()
    return deleted


def _release_thread(thread):
    try:
        thread.release()
        thread.wait(1000)
    except RuntimeError:
        pass


def test_parsing_close_waits_for_active_preflight_worker(qapp, monkeypatch, tmp_path):
    cancel_calls = []

    class PreflightThread(_PreflightThread):
        def __init__(self, **kwargs):
            super().__init__(cancel_calls=cancel_calls, **kwargs)

    monkeypatch.setattr(parsing_dialog_module, "ParsePreflightThread", PreflightThread)
    monkeypatch.setattr(
        parsing_dialog_module,
        "create_worker_progress_dialog",
        _progress_dialog,
    )
    dialog = parsing_dialog_module.ParsingDialog(
        directory=str(tmp_path),
        db_file=str(tmp_path / "reports.db"),
    )
    deleted = _track_deletion(dialog)
    dialog.scan_reports()
    thread = dialog.preflight_thread
    try:
        assert _wait_until(qapp, thread.isRunning)

        assert dialog.close() is False
        assert cancel_calls == ["preflight"]
        assert deleted == []
        assert _wait_until(qapp, lambda: bool(deleted))
    finally:
        _release_thread(thread)


def test_parsing_reject_waits_for_active_parse_worker(qapp, monkeypatch, tmp_path):
    cancel_calls = []

    class ParseThread(_ParseThread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, cancel_calls=cancel_calls, **kwargs)

    monkeypatch.setattr(parsing_dialog_module, "ParseReportsThread", ParseThread)
    monkeypatch.setattr(
        parsing_dialog_module,
        "create_worker_progress_dialog",
        _progress_dialog,
    )
    monkeypatch.setattr(parsing_dialog_module.QMessageBox, "information", lambda *_args: None)
    dialog = parsing_dialog_module.ParsingDialog(
        directory=str(tmp_path),
        db_file=str(tmp_path / "reports.db"),
    )
    deleted = _track_deletion(dialog)
    dialog.show_loading_screen()
    thread = dialog.parse_thread
    try:
        assert _wait_until(qapp, thread.isRunning)

        dialog.reject()
        assert cancel_calls == ["parse"]
        assert deleted == []
        assert _wait_until(qapp, lambda: bool(deleted))
    finally:
        _release_thread(thread)


def _build_export_dialog(monkeypatch, tmp_path):
    monkeypatch.setattr(
        export_dialog_module.ExportDialog,
        "_load_dialog_config",
        lambda self: {"selected_preset": "fast_diagnostics"},
    )
    monkeypatch.setattr(export_dialog_module, "load_dashboard_visual_settings", lambda: {})
    monkeypatch.setattr(export_dialog_module, "save_export_dialog_config", lambda *_args: None)
    dialog = export_dialog_module.ExportDialog(db_file=str(tmp_path / "source.db"))
    dialog.config_path = tmp_path / "export-config.json"
    dialog.excel_file = Path(tmp_path / "output.xlsx")
    dialog._set_path_field_value(dialog.excel_file_text_label, dialog.excel_file)
    dialog._refresh_metadata_enrichment_notice = lambda: None
    return dialog


def test_export_close_waits_for_active_worker(qapp, monkeypatch, tmp_path):
    cancel_calls = []

    class ExportThread(_ExportThread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, cancel_calls=cancel_calls, **kwargs)

    request = SimpleNamespace(
        paths=SimpleNamespace(excel_file=str(tmp_path / "output.xlsx"), html_dashboard_file=None),
        options=SimpleNamespace(violin_plot_min_samplesize=6, summary_plot_scale=0),
    )
    monkeypatch.setattr(
        export_dialog_module,
        "build_validated_export_request",
        lambda **_kwargs: request,
    )
    monkeypatch.setattr(export_dialog_module, "create_export_data_thread", ExportThread)
    monkeypatch.setattr(
        export_dialog_module,
        "create_worker_progress_dialog",
        _progress_dialog,
    )
    dialog = _build_export_dialog(monkeypatch, tmp_path)
    deleted = _track_deletion(dialog)
    dialog.show_loading_screen()
    thread = dialog.export_thread
    try:
        assert _wait_until(qapp, thread.isRunning)

        assert dialog.close() is False
        assert cancel_calls == ["export"]
        assert deleted == []
        assert _wait_until(qapp, lambda: bool(deleted))
    finally:
        _release_thread(thread)


def test_coordinator_reports_active_dialog_blocked_then_observes_deferred_close(
    qapp,
    monkeypatch,
    tmp_path,
):
    cancel_calls = []

    class PreflightThread(_PreflightThread):
        def __init__(self, **kwargs):
            super().__init__(cancel_calls=cancel_calls, **kwargs)

    monkeypatch.setattr(parsing_dialog_module, "ParsePreflightThread", PreflightThread)
    monkeypatch.setattr(
        parsing_dialog_module,
        "create_worker_progress_dialog",
        _progress_dialog,
    )
    coordinator = WindowCoordinator(WorkspaceContext())
    dialog = coordinator.open_modeless(
        "parsing",
        lambda _snapshot: parsing_dialog_module.ParsingDialog(
            directory=str(tmp_path),
            db_file=str(tmp_path / "reports.db"),
        ),
    )
    dialog.scan_reports()
    thread = dialog.preflight_thread
    try:
        assert _wait_until(qapp, thread.isRunning)

        assert coordinator.close_all() == ("parsing",)
        assert coordinator.get("parsing") is dialog
        assert cancel_calls == ["preflight"]
        assert _wait_until(qapp, lambda: coordinator.get("parsing") is None)
    finally:
        _release_thread(thread)


def test_parse_completion_explains_parser_registry_drift(tmp_path):
    dialog = parsing_dialog_module.ParsingDialog(
        directory=str(tmp_path),
        db_file=str(tmp_path / "reports.db"),
    )
    try:
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=1,
                parsed_files=0,
                failed_files=0,
                skipped_files=0,
                preflight_changed_files=1,
            )
        )

        _level, _title, message = dialog._build_parse_completion_feedback()

        assert "Content or parser selection changed after scan" in message
        assert "Changed or added after scan" not in message
    finally:
        dialog.parse_thread = None
        dialog.close()
