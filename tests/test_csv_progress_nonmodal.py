"""Real delayed CSV workers permit Reports navigation; cache modality is retained."""
from contextlib import contextmanager
import csv
from threading import Event
import time

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QMessageBox

from tests.qt_key_input import press_key


def _wait(app, predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate(), 'Bounded real-worker state deadline'


@contextmanager
def _delegating_barrier(monkeypatch, module, name):
    original = getattr(module, name)
    entered, release = Event(), Event()
    errors = []

    def gated(*args, **kwargs):
        entered.set()
        if not release.wait(5):
            errors.append('real-worker barrier expired')
            raise RuntimeError(errors[-1])
        return original(*args, **kwargs)

    # The original service always runs after release; no worker/result is fabricated.
    with monkeypatch.context() as patch:
        patch.setattr(module, name, gated)
        try:
            yield entered, release, errors
        finally:
            release.set()


@contextmanager
def _owned_notifications(app, owner):
    errors, seen = [], []
    timer = QTimer(owner)
    timer.setInterval(10)

    def acknowledge():
        try:
            message = app.activeModalWidget()
            if isinstance(message, QMessageBox) and message.parentWidget() is owner:
                seen.append(message.windowTitle())
                if message.windowTitle() not in ('Analytics successful', 'Analytics completed with warnings'):
                    errors.append('unexpected owned terminal notification')
                button = message.button(QMessageBox.StandardButton.Ok)
                if button is None:
                    errors.append('owned notification has no OK button')
                else:
                    button.click()  # Dismiss the actual owned result; never open an external viewer.
        except BaseException as error:
            errors.append(type(error).__name__)  # Never escape a Qt callback.

    timer.timeout.connect(acknowledge)
    timer.start()
    try:
        yield errors, seen
    finally:
        timer.stop()
        timer.deleteLater()


@pytest.fixture
def owner(qapplication_session, tmp_path):
    from metroliza.app.ui_entrypoint import load_main_window_factory
    from metroliza.app.windows_candidate_native_check import close_report_owner
    from metroliza.ui.ui_preferences import UiPreferences

    source = tmp_path / 'real.csv'
    with source.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('Part', 'Date', 'Value'))
        writer.writerows((f'LOT-{i}', f'2026-01-{i:02d}', i * 10) for i in range(1, 9))
    settings = QSettings(str(tmp_path / 'preferences.ini'), QSettings.Format.IniFormat)
    window = load_main_window_factory()('F13 real CSV', None, ui_preferences=UiPreferences(settings))
    window.show()
    window._activate_workspace('reports')  # Build the real Reports page before the finite barrier.
    window.csv_summary_action.trigger()
    dialog = window.csv_summary_dialog
    assert dialog is not None and dialog.isVisible() and not dialog.isModal()
    dialog.input_file = str(source)  # Explicit private fixture admission, not a picker claim.
    dialog.input_files = (str(source),)
    dialog._sync_ui_state()
    try:
        yield window, dialog, source
    finally:
        close_report_owner(window, qapplication_session)


def _navigate_while_busy(app, window, dialog, worker, attribute):
    assert dialog.loading_dialog.isVisible()
    assert dialog.loading_dialog.windowModality() == Qt.WindowModality.NonModal
    assert app.activeModalWidget() is None
    for sequence, page in (('Ctrl+2', 'reports'), ('Ctrl+1', 'home'), ('Ctrl+3', 'csv_summary')):
        press_key(app, window, sequence)
        assert window.navigation_combo.currentData() == page
        assert window.csv_summary_dialog is dialog
        assert getattr(dialog, attribute) is worker and worker.isRunning()
        assert app.activeModalWidget() is None
    assert dialog.isVisible() and not dialog.isModal()


def _join_after_release(app, owner, worker, attribute):
    if worker is not None and not sip.isdeleted(worker):
        from metroliza.app.windows_candidate_lifecycle_checks import _join_owned_worker
        _join_owned_worker(worker, owner, 'F13_real_worker_join_deadline')
    _wait(app, lambda: getattr(owner, attribute) is None)


def test_actual_csv_load_progress_stays_nonmodal_after_delay_and_resumes_same_worker(
    owner, qapplication_session, monkeypatch,
):
    from metroliza.industrial import industrial_workers

    window, dialog, source = owner
    with (
        _owned_notifications(qapplication_session, dialog) as (notification_errors, notifications),
        _delegating_barrier(monkeypatch, industrial_workers, 'load_tabular_analytics_files') as (entered, release, errors),
    ):
        worker = None
        try:
            started = time.monotonic()
            dialog.load_metrics_button.click()
            worker = dialog.tabular_load_thread
            assert worker is not None
            result = QSignalSpy(worker.result_ready)
            _wait(qapplication_session, entered.is_set, 4)
            _wait(qapplication_session, lambda: dialog.loading_dialog.isVisible() and time.monotonic() - started >= 1.05, 4)
            _navigate_while_busy(qapplication_session, window, dialog, worker, 'tabular_load_thread')
            assert dialog.input_file == str(source)
            release.set()
            _wait(qapplication_session, lambda: dialog.tabular_load_thread is None)
            assert len(result) == 1 and result[0][0] is dialog.tabular_load_result
            assert dialog.tabular_load_result.row_count == 8
            assert [metric.field_name for metric in dialog.metric_candidates] == ['value']
            assert not errors and not notification_errors and not notifications
        finally:
            release.set()
            _join_after_release(qapplication_session, dialog, worker, 'tabular_load_thread')


@pytest.mark.parametrize('cache', [False, True], ids=['csv', 'industrial-cache'])
def test_actual_analytics_progress_preserves_csv_navigation_and_cache_modality(
    owner, qapplication_session, tmp_path, monkeypatch, cache,
):
    from metroliza.industrial import industrial_workers
    from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_file
    from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog, SOURCE_TABULAR_FILE

    window, csv_dialog, source = owner
    loaded = load_tabular_analytics_file(source)
    if cache:
        dialog = IndustrialAnalyticsDialog(window, source_kind=SOURCE_TABULAR_FILE, input_file=str(source),
                                           tabular_load_result=loaded, presentation_mode='industrial_cache')
        dialog.show()
    else:
        dialog = csv_dialog
        dialog._apply_tabular_load_result(loaded)  # Real public load result, not an analysis outcome.
    assert dialog.is_industrial_cache_presentation is cache
    output = tmp_path / ('cache.html' if cache else 'csv.html')
    dialog.output_dashboard_file = str(output)
    dialog.workbook_checkbox.setChecked(False)
    dialog._sync_ui_state()
    assert dialog.start_button.isEnabled()
    with _owned_notifications(qapplication_session, dialog) as (notification_errors, notifications):
        with _delegating_barrier(monkeypatch, industrial_workers, 'run_tabular_file_analytics') as (entered, release, errors):
            worker = None
            try:
                started = time.monotonic()
                dialog.start_button.click()
                worker = dialog.analytics_thread
                assert worker is not None
                result = QSignalSpy(worker.result_ready)
                request = worker.request
                _wait(qapplication_session, entered.is_set, 4)
                _wait(qapplication_session, lambda: dialog.loading_dialog.isVisible() and time.monotonic() - started >= 1.05, 4)
                if cache:
                    assert dialog.loading_dialog.windowModality() == Qt.WindowModality.ApplicationModal
                    assert qapplication_session.activeModalWidget() is dialog.loading_dialog
                    assert worker.isRunning()
                else:
                    _navigate_while_busy(qapplication_session, window, dialog, worker, 'analytics_thread')
                assert worker.request is request and request.input_file == str(source)
                assert request.output_dashboard_file == str(output)
                release.set()
                _wait(qapplication_session, lambda: dialog.analytics_thread is None)
                assert len(result) == 1 and result[0][0].row_count == 8
                assert result[0][0].html_dashboard_path == str(output)
                assert output.is_file() and '<!doctype html>' in output.read_text().lower()
                assert not errors and not notification_errors
                assert len(notifications) == 1
            finally:
                release.set()
                _join_after_release(qapplication_session, dialog, worker, 'analytics_thread')
                if cache:
                    assert dialog.close()
