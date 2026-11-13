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


@pytest.mark.parametrize('source_count', [1, 2], ids=['single-csv', 'multiple-csv'])
def test_busy_csv_commands_preserve_borrowed_sqlite_until_real_analytics_finishes(
    owner, qapplication_session, tmp_path, monkeypatch, source_count,
):
    from pathlib import Path
    import shutil
    from PyQt6.QtWidgets import QFileDialog
    from metroliza.industrial import industrial_workers
    from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_files

    window, dialog, source = owner
    sources = [source]
    if source_count == 2:
        second = tmp_path / 'second.csv'
        shutil.copyfile(source, second)
        sources.append(second)
    loaded = load_tabular_analytics_files(sources, force_sqlite=True)
    dialog.input_files = tuple(str(path) for path in sources)
    dialog._apply_tabular_load_result(loaded)
    store = loaded.sqlite_store
    assert store is not None
    store_path = Path(store.path)
    expected_rows = 8 * source_count
    assert store.row_ids() == list(range(1, expected_rows + 1))
    assert store.read_dataframe(columns=('value',))['value'].tolist() == list(range(10, 81, 10)) * source_count
    output = tmp_path / 'borrowed-store.html'
    dialog.output_dashboard_file = str(output)
    dialog.workbook_checkbox.setChecked(False)
    dialog._sync_ui_state()
    controls = (dialog.browse_input_button, dialog.load_metrics_button,
                dialog.sheet_name_combo, dialog.timestamp_column_combo, dialog.reference_column_combo)
    idle_enabled = [control.isEnabled() for control in controls]
    assert idle_enabled == [True, True, False, True, True]
    picker_attempts = []

    def unexpected_picker(*_args, **_kwargs):
        # Fail only on direct Python entry below; never fabricate a chosen source.
        picker_attempts.append(True)
        pytest.fail('Busy source command opened a picker')

    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', unexpected_picker)
    with (
        _owned_notifications(qapplication_session, dialog) as (notification_errors, notifications),
        _delegating_barrier(monkeypatch, industrial_workers, 'run_tabular_file_analytics') as (entered, release, errors),
    ):
        worker = None
        try:
            started = time.monotonic()
            dialog.start_button.click()
            worker = dialog.analytics_thread
            assert worker is not None
            result = QSignalSpy(worker.result_ready)
            request = worker.request
            _wait(qapplication_session, entered.is_set, 4)  # Before the original service materializes SQLite rows.
            _wait(qapplication_session, lambda: dialog.loading_dialog.isVisible() and time.monotonic() - started >= 1.05, 4)
            _navigate_while_busy(qapplication_session, window, dialog, worker, 'analytics_thread')
            assert all(not control.isEnabled() for control in controls)
            dialog.select_input_file()  # Direct entry must also guard before the chooser or cleanup.
            dialog._handle_tabular_source_changed()
            dialog._handle_tabular_column_changed()
            dialog.handle_load_metrics_clicked()
            dialog.load_metrics()
            dialog.show_tabular_load_screen()
            for sequence in ('Ctrl+D', 'Ctrl+R'):
                press_key(qapplication_session, dialog, sequence)
            dialog.browse_input_button.click()
            dialog.load_metrics_button.click()
            assert not picker_attempts and not output.exists()
            assert dialog.analytics_thread is worker and worker.isRunning()
            assert dialog.tabular_load_thread is None and worker.request is request
            assert request.tabular_load_result is loaded and dialog.tabular_load_result is loaded
            assert dialog.input_files == tuple(str(path) for path in sources)
            assert request.input_file == str(source) and request.output_dashboard_file == str(output)
            assert store_path.is_file() and store.row_ids() == list(range(1, expected_rows + 1))
            assert store.read_dataframe(columns=('value',))['value'].tolist() == list(range(10, 81, 10)) * source_count
            assert [metric.field_name for metric in dialog.metric_candidates] == ['value']
            release.set()
            _wait(qapplication_session, lambda: dialog.analytics_thread is None)
            assert len(result) == 1 and result[0][0].row_count == expected_rows
            assert result[0][0].html_dashboard_path == str(output)
            assert output.is_file() and '<!doctype html>' in output.read_text().lower()
            assert dialog.tabular_load_result is loaded and store_path.is_file()
            assert [control.isEnabled() for control in controls] == idle_enabled
            assert not errors and not notification_errors and len(notifications) == 1
        finally:
            release.set()
            _join_after_release(qapplication_session, dialog, worker, 'analytics_thread')
    assert dialog.close()
    assert not store_path.exists()  # Cleanup remains owned by the finished dialog.


@contextmanager
def _observe_and_cancel_owned_children(app, owner):
    from metroliza.ui.industrial_analytics_dialog import MetricLimitsDialog, MetricSelectionDialog
    from metroliza.ui.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
    from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog

    kinds = (MetricLimitsDialog, MetricSelectionDialog, TabularAnalyticsFilterDialog, TabularAnalyticsGroupingDialog)
    seen, errors = [], []
    timer = QTimer(owner)
    timer.setInterval(10)

    def observe():
        try:
            child = app.activeModalWidget()
            if isinstance(child, kinds) and child.parentWidget() is owner:
                if child not in seen:
                    seen.append(child)
                child.reject()  # Actual clean Cancel; never replace exec() or its outcome.
        except BaseException as error:
            errors.append(type(error).__name__)

    timer.timeout.connect(observe)
    timer.start()
    try:
        yield seen, errors, kinds
    finally:
        timer.stop()
        timer.deleteLater()


def test_real_reload_blocks_stale_children_and_start_then_restores_analytics_children(
    owner, qapplication_session, tmp_path, monkeypatch,
):
    from pathlib import Path
    from metroliza.industrial import industrial_workers
    from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_file

    window, dialog, source = owner
    old = load_tabular_analytics_file(source, force_sqlite=True)
    dialog._apply_tabular_load_result(old)
    old_path = Path(old.sqlite_store.path)
    output = tmp_path / 'after-reload.html'
    dialog.output_dashboard_file = str(output)
    dialog.workbook_checkbox.setChecked(False)
    dialog._sync_ui_state()
    controls = (dialog.filters_button, dialog.edit_groups_button,
                dialog.choose_metrics_button, dialog.edit_limits_button, dialog.start_button)
    assert all(control.isEnabled() for control in controls)
    with source.open('a', newline='') as stream:
        csv.writer(stream).writerow(('LOT-9', '2026-01-09', 90))
    application, audit_errors = [], []
    original_apply = dialog._apply_tabular_load_result

    def observe_application(loaded, **kwargs):
        try:
            application.append((dialog.tabular_load_result is old, old_path.is_file(),
                                old.sqlite_store.row_ids(), loaded is not old))
        except BaseException as error:
            audit_errors.append(type(error).__name__)
        return original_apply(loaded, **kwargs)

    monkeypatch.setattr(dialog, '_apply_tabular_load_result', observe_application)
    with _observe_and_cancel_owned_children(qapplication_session, dialog) as (children, child_errors, kinds):
        with _delegating_barrier(monkeypatch, industrial_workers, 'load_tabular_analytics_files') as (entered, release, errors):
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
                assert all(not control.isEnabled() for control in controls)
                assert 'Loading CSV/Excel data' in dialog.readiness_label.text()
                for open_child in (dialog.open_filters_dialog, dialog.open_tabular_filter_dialog,
                                   dialog.open_grouping_dialog, dialog.open_metrics_dialog, dialog.open_limits_dialog):
                    open_child()
                for button in controls:
                    button.click()
                for sequence in ('Ctrl+Shift+F', 'Ctrl+G', 'Ctrl+F', 'Ctrl+Shift+G', 'Ctrl+S'):
                    press_key(qapplication_session, dialog, sequence)
                assert not children and not child_errors
                assert dialog.tabular_load_result is old and old_path.is_file()
                assert old.sqlite_store.row_ids() == list(range(1, 9))
                assert dialog.tabular_load_thread is worker and worker.isRunning()
                assert dialog.analytics_thread is None and not output.exists()
                release.set()
                _wait(qapplication_session, lambda: dialog.tabular_load_thread is None)
                new = dialog.tabular_load_result
                assert len(result) == 1 and result[0][0] is new and new is not old
                assert application == [(True, True, list(range(1, 9)), True)] and not audit_errors
                assert not old_path.exists() and new.sqlite_store is not None
                assert new.sqlite_store.row_ids() == list(range(1, 10))
                assert new.sqlite_store.read_dataframe(columns=('value',))['value'].tolist() == list(range(10, 91, 10))
                assert all(control.isEnabled() for control in controls) and not errors
            finally:
                release.set()
                _join_after_release(qapplication_session, dialog, worker, 'tabular_load_thread')
        monkeypatch.setattr(dialog, '_apply_tabular_load_result', original_apply)
        with (
            _owned_notifications(qapplication_session, dialog) as (notification_errors, notifications),
            _delegating_barrier(monkeypatch, industrial_workers, 'run_tabular_file_analytics') as (entered, release, errors),
        ):
            worker = None
            try:
                dialog.start_button.click()
                worker = dialog.analytics_thread
                assert worker is not None
                result = QSignalSpy(worker.result_ready)
                request = worker.request
                _wait(qapplication_session, entered.is_set, 4)
                assert all(control.isEnabled() for control in controls[:-1])
                for button in controls[:-1]:
                    button.click()  # Four real children remain reachable while analytics borrows a stable source.
                assert {type(child) for child in children} == set(kinds) and len(children) == 4
                assert not child_errors and qapplication_session.activeModalWidget() is None
                assert worker.isRunning() and worker.request is request and request.tabular_load_result is new
                assert Path(new.sqlite_store.path).is_file()
                release.set()
                _wait(qapplication_session, lambda: dialog.analytics_thread is None)
                assert len(result) == 1 and result[0][0].row_count == 9
                assert output.is_file() and result[0][0].html_dashboard_path == str(output)
                assert not errors and not notification_errors and len(notifications) == 1
            finally:
                release.set()
                _join_after_release(qapplication_session, dialog, worker, 'analytics_thread')
    new_path = Path(new.sqlite_store.path)
    assert dialog.close() and not old_path.exists() and not new_path.exists()
