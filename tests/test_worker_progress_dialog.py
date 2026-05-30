from __future__ import annotations

import time

import pytest

try:
    from PyQt6.QtGui import QCloseEvent
    from PyQt6.QtWidgets import QApplication
    from modules.worker_progress_dialog import (
        create_delayed_worker_progress_dialog,
        create_worker_progress_dialog,
    )
except ImportError as exc:  # pragma: no cover - depends on optional PyQt availability
    QApplication = None
    QCloseEvent = None
    create_delayed_worker_progress_dialog = None
    create_worker_progress_dialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

_APP = None


def _app():
    if PYQT_IMPORT_ERROR is not None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def _process_events_for(milliseconds: int) -> None:
    app = _app()
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_delayed_worker_progress_dialog_waits_before_showing() -> None:
    _app()
    dialog, _label, _bar, _movie = create_delayed_worker_progress_dialog(
        None,
        window_title="Working",
        initial_status_text="Stage\nDetail\nETA --",
        on_cancel=lambda: None,
    )
    try:
        dialog.show()
        _process_events_for(150)

        assert not dialog.isVisible()

        _process_events_for(1000)

        assert dialog.isVisible()
    finally:
        dialog.close()


def test_delayed_worker_progress_dialog_does_not_show_after_quick_finish() -> None:
    _app()
    dialog, _label, _bar, _movie = create_delayed_worker_progress_dialog(
        None,
        window_title="Working",
        initial_status_text="Stage\nDetail\nETA --",
        on_cancel=lambda: None,
    )
    dialog.show()
    _process_events_for(100)
    dialog.accept()
    _process_events_for(1100)

    assert not dialog.isVisible()


def test_worker_progress_dialog_window_close_requests_cancel_without_closing() -> None:
    _app()
    cancel_calls = []
    dialog, _label, _bar, _movie = create_worker_progress_dialog(
        None,
        window_title="Working",
        initial_status_text="Stage\nDetail\nETA --",
        on_cancel=lambda: cancel_calls.append("cancel"),
    )
    try:
        dialog.show()
        _process_events_for(50)

        close_event = QCloseEvent()
        dialog.closeEvent(close_event)

        assert cancel_calls == ["cancel"]
        assert not close_event.isAccepted()
        assert dialog.isVisible()

        second_close_event = QCloseEvent()
        dialog.closeEvent(second_close_event)

        assert cancel_calls == ["cancel"]
        assert not second_close_event.isAccepted()
    finally:
        dialog.accept()


def test_worker_progress_dialog_reject_requests_cancel_without_closing() -> None:
    _app()
    cancel_calls = []
    dialog, _label, _bar, _movie = create_worker_progress_dialog(
        None,
        window_title="Working",
        initial_status_text="Stage\nDetail\nETA --",
        on_cancel=lambda: cancel_calls.append("cancel"),
    )
    try:
        dialog.show()
        _process_events_for(50)

        dialog.reject()

        assert cancel_calls == ["cancel"]
        assert dialog.isVisible()

        dialog.reject()

        assert cancel_calls == ["cancel"]
    finally:
        dialog.accept()


def test_worker_progress_dialog_programmatic_close_does_not_request_cancel() -> None:
    _app()
    cancel_calls = []
    dialog, _label, _bar, _movie = create_worker_progress_dialog(
        None,
        window_title="Working",
        initial_status_text="Stage\nDetail\nETA --",
        on_cancel=lambda: cancel_calls.append("cancel"),
    )
    dialog.show()
    _process_events_for(50)
    dialog.close()
    _process_events_for(50)

    assert cancel_calls == []
    assert not dialog.isVisible()


def test_worker_progress_dialog_terminal_reject_does_not_request_cancel() -> None:
    _app()
    cancel_calls = []
    dialog, _label, _bar, _movie = create_worker_progress_dialog(
        None,
        window_title="Working",
        initial_status_text="Stage\nDetail\nETA --",
        on_cancel=lambda: cancel_calls.append("cancel"),
    )
    dialog.show()
    _process_events_for(50)
    dialog.reject_as_terminal()
    _process_events_for(50)

    assert cancel_calls == []
    assert not dialog.isVisible()
