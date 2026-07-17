from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

import metroliza.ui.industrial_sync_dialog as industrial_sync_dialog_module
from metroliza.ui.industrial_sync_dialog import IndustrialSyncDialog


_QT_APP = None


@pytest.fixture(scope="module")
def qapp():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


class _RunningThread:
    def __init__(self):
        self.running = True
        self.cancel_calls = 0

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_calls += 1


def _install_operation(dialog: IndustrialSyncDialog, operation: str):
    if operation == "fetch":
        thread = _RunningThread()
        dialog.oznak_sync_thread = thread
        return thread
    if operation == "queued_batch":
        dialog._batch_operations = [object()]
        return None
    if operation == "link_refresh":
        thread = _RunningThread()
        dialog.link_refresh_thread = thread
        return thread
    raise AssertionError(f"Unknown operation {operation!r}")


def _mark_operation_idle(dialog: IndustrialSyncDialog, operation: str, thread):
    if operation == "fetch":
        thread.running = False
        dialog.oznak_sync_thread = None
        dialog._set_action_buttons_enabled(True)
        return
    if operation == "queued_batch":
        dialog._batch_operations.clear()
        dialog._set_action_buttons_enabled(True)
        return
    thread.running = False
    dialog._clear_batch_link_refresh_thread()


@pytest.mark.parametrize("operation", ["fetch", "queued_batch", "link_refresh"])
@pytest.mark.parametrize("close_action", ["reject", "close"])
def test_native_close_paths_stay_blocked_until_all_sync_operations_are_idle(
    qapp,
    monkeypatch,
    tmp_path,
    operation,
    close_action,
):
    notices = []
    monkeypatch.setattr(
        industrial_sync_dialog_module.QMessageBox,
        "information",
        lambda *args: notices.append(args),
    )
    dialog = IndustrialSyncDialog(db_file=str(tmp_path / f"{operation}.db"))
    dialog.show()
    thread = _install_operation(dialog, operation)
    dialog._set_action_buttons_enabled(True)
    qapp.processEvents()
    try:
        assert not dialog.close_button.isEnabled()

        result = getattr(dialog, close_action)()
        qapp.processEvents()

        if close_action == "close":
            assert result is False
        assert dialog.isVisible()
        assert notices[-1][2] == (
            "Cancellation was requested where supported. Wait for the operation to finish."
        )
        if operation == "fetch":
            assert thread.cancel_calls == 1
            assert dialog._is_oznak_operation_running()
        elif operation == "queued_batch":
            assert dialog._batch_operations == []
        else:
            assert thread.cancel_calls == 0
            assert dialog._is_link_refresh_running()

        _mark_operation_idle(dialog, operation, thread)

        assert dialog.close_button.isEnabled()
    finally:
        _mark_operation_idle(dialog, operation, thread)
        dialog.close()
