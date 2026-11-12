"""Observed onboarding state, cache-first handoffs and guarded native controls."""
from contextlib import closing
import os
import sqlite3
from threading import Event

import pytest
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QVBoxLayout

from metroliza.app.windows_candidate_ui_checks import _geometry_dialog
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_workflow_state import IndustrialFilterState
from metroliza.industrial.oznak_adapter import OznakAdapterFetchResult, OznakAdapterStatus
from metroliza.industrial import industrial_workers as workers
from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result
from metroliza.ui import detached_threads, industrial_data_dialog as data, industrial_sync_dialog as sync
from tests.qt_key_input import activate_for_key, observe_key, press_key
from tests.test_report_planner_integration import wait_until


@pytest.fixture
def ui(qapplication_session, tmp_path, monkeypatch):
    monkeypatch.setattr(data, 'default_industrial_source_config_path', lambda: tmp_path / 'sources.yaml')
    monkeypatch.setattr(data, 'get_oznak_adapter_status', lambda: OznakAdapterStatus(available=False, error='Synthetic connector offline'))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, 'information', lambda *_args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Discard)
    created = []

    def create(kind='data', database=None, **kwargs):
        if kind == 'data':
            dialog = data.IndustrialDataDialog(db_file=str(database or tmp_path / 'empty.db'))
        else:
            dialog = sync.IndustrialSyncDialog(db_file=str(database or tmp_path / 'empty.db'),
                                               config_path=tmp_path / 'sources.yaml', **kwargs)
        created.append(dialog)
        dialog.show()
        return dialog

    yield create
    for dialog in reversed(created):
        if isinstance(dialog, data.IndustrialDataDialog):
            dialog._stop_background_threads()
        assert dialog.close()
    wait_until(qapplication_session, lambda: not detached_threads.running_threads())


def press(app, widget, sequence):
    press_key(app, widget, sequence)


def cached_sources(tmp_path):
    path = str(tmp_path / 'cache.db')
    repository = IndustrialDataRepository(path)
    profiles = []
    for key, name, count in (('uiux_a', 'Synthetic A', 1200), ('uiux_b', 'Synthetic B', 800)):
        profile = repository.upsert_source_profile(profile_key=key, profile_name=name,
                    source_db_alias=key, database_type='sqlite', source_object_name='events')
        repository.upsert_industrial_records_from_rows(source_profile_id=profile.id,
            source_db_alias=key, rows=({'source_record_key': f'{key}-{i}', 'reference': f'REF-{i % 4}',
                                       'value': i} for i in range(count)))
        profiles.append(profile)
    failed = repository.create_sync_run(source_profile_id=profiles[0].id)
    repository.finish_sync_run(sync_run_id=failed, status='failed', row_count=0,
                               error_summary='Synthetic remote access denied')
    return path, repository, profiles


def test_no_source_and_disabled_source_lead_to_configuration(ui, tmp_path):
    dialog = ui()
    assert 'Next: Configure' in dialog.next_action_label.text()
    assert dialog.sources_button.property('buttonRole') == 'primary'
    assert dialog.sync_button.isEnabled()  # existing Windows qualification focuses this launcher
    repository = IndustrialDataRepository(dialog.db_file)
    repository.upsert_source_profile(profile_key='uiux_disabled', profile_name='Disabled synthetic',
        source_db_alias='uiux_disabled', database_type='sqlite', source_object_name='events', is_enabled=False)
    dialog.refresh_status()
    assert '0 enabled' in dialog.sources_label.text()
    assert 'Next: Configure' in dialog.next_action_label.text()
    repository.upsert_source_profile(profile_key='uiux_disabled', profile_name='Enabled synthetic',
        source_db_alias='uiux_disabled', database_type='sqlite', source_object_name='events', is_enabled=True)
    dialog.refresh_status()
    assert 'Local cache empty' in dialog.next_action_label.text()
    assert dialog.sync_button.property('buttonRole') == 'primary'


def test_cached_rows_remain_analyzable_and_scoped_after_remote_failure(ui, tmp_path, monkeypatch, qapplication_session):
    path, repository, profiles = cached_sources(tmp_path)
    dialog = ui(database=path)
    assert '2,000 rows' in dialog.next_action_label.text() and 'Last fetch failed' in dialog.next_action_label.text()
    assert dialog.analyze_button.isEnabled() and dialog.export_button.isEnabled()
    assert dialog.analyze_button.property('buttonRole') == 'primary'
    assert 'not a live connection check' in dialog.workflow_label.text()
    assert dialog.connector_details.isHidden()
    dialog.connector_details_action.setChecked(True)
    assert not dialog.connector_details.isHidden()
    wait_until(qapplication_session, lambda: dialog._oznak_status_thread is None)
    assert 'Synthetic connector offline' in dialog.oznak_label.text()
    dialog.connector_details_action.setChecked(False)
    seen = []

    class Analytics:
        def __init__(self, _parent, **kwargs):
            self.loaded = kwargs['tabular_load_result']
        def exec(self):
            frame = self.loaded.sqlite_store.read_dataframe(columns=('source_profile_id',))
            seen.append((self.loaded.row_count, set(frame.source_profile_id)))
            cleanup_tabular_load_result(self.loaded)

    exported = []
    class Export:
        def __init__(self, _parent, **kwargs):
            exported.append(kwargs)
        def exec(self):
            pass

    monkeypatch.setattr(data, 'IndustrialAnalyticsDialog', Analytics)
    monkeypatch.setattr(data, 'IndustrialExportDialog', Export)
    dialog.analysis_source_combo.setCurrentIndex(dialog.analysis_source_combo.findData(profiles[1].id))
    press(qapplication_session, dialog.analyze_button, 'Ctrl+S')
    wait_until(qapplication_session, lambda: bool(seen))
    assert seen == [(800, {profiles[1].id})]
    scope = IndustrialFilterState(reference_column='reference', references=('REF-3',))
    dialog.export_filter_state = scope
    press(qapplication_session, dialog.export_button, 'Ctrl+E')
    assert exported[0]['db_file'] == path and exported[0]['filter_state'] is scope
    assert repository.summarize_counts().records == 2000


def test_access_denial_is_observed_and_does_not_hide_cached_actions(ui, tmp_path, monkeypatch, qapplication_session):
    path, repository, _profiles = cached_sources(tmp_path)
    parent = ui(database=path)
    status = OznakAdapterStatus(available=True, fetch_available=True)
    monkeypatch.setattr(workers, 'get_oznak_adapter_status', lambda: status)
    monkeypatch.setattr(workers, 'create_oznak_cancellation_token', lambda: None)
    attempts = []

    def denied_fetch(*_args, **_kwargs):
        attempts.append(True)
        return OznakAdapterFetchResult(status=status, records=(), row_count=0, implemented=True,
                                      error='Access denied password=synthetic-value')

    monkeypatch.setattr(workers, 'fetch_oznak_records_for_source_profile', denied_fetch)
    dialog = sync.IndustrialSyncDialog(parent, db_file=path, report_db_file=None, config_path=tmp_path / 'sources.yaml')
    dialog.show()
    dialog.username_edit.setText('synthetic_operator')
    dialog.password_edit.setText('synthetic_session_password')
    try:
        press(qapplication_session, dialog.test_connection_button, 'Ctrl+R')
        wait_until(qapplication_session, lambda: bool(attempts))
        wait_until(qapplication_session, lambda: dialog.oznak_sync_thread is None)
        assert 'failed' in dialog.stage_label.text() and 'Check credentials' in dialog.stage_label.text()
        assert dialog.test_connection_button.property('buttonRole') == 'primary'
        assert 'synthetic-value' not in dialog.status_label.text()
        assert repository.summarize_counts().records == 2000
        assert parent.analyze_button.isEnabled() and parent.export_button.isEnabled()
        assert parent.analyze_button.property('buttonRole') == 'primary'
    finally:
        assert dialog.close()


def test_actual_stop_key_keeps_last_complete_cache_and_native_owner(ui, tmp_path, monkeypatch, qapplication_session):
    path, repository, _profiles = cached_sources(tmp_path)
    status = OznakAdapterStatus(available=True, fetch_available=True)
    entered, release = Event(), Event()
    forwarded = []
    monkeypatch.setattr(workers, 'get_oznak_adapter_status', lambda: status)
    monkeypatch.setattr(workers, 'create_oznak_cancellation_token', lambda: None)

    def fetch(_profile, **kwargs):
        forwarded.append(kwargs['reference_values'])
        kwargs['record_batch_callback'](({'source_record_key': 'uiux-new-pending', 'value': 999},))
        entered.set()
        assert release.wait(10)
        return OznakAdapterFetchResult(status=status, records=(), row_count=1, implemented=True)

    monkeypatch.setattr(workers, 'fetch_oznak_records_for_source_profile', fetch)
    scope = IndustrialFilterState(reference_column='reference', references=('REF-1',))
    dialog = ui('sync', path, report_db_file=None, filter_state=scope)
    dialog.username_edit.setText('synthetic_operator')
    dialog.password_edit.setText('synthetic_session_password')
    worker = None
    try:
        press(qapplication_session, dialog.sync_now_button, 'Ctrl+S')
        wait_until(qapplication_session, entered.is_set)
        worker = dialog.oznak_sync_thread
        assert worker is not None and worker.isRunning()
        assert not dialog.close_button.isEnabled() and not dialog.configure_sources_button.isEnabled()
        press(qapplication_session, dialog, 'Ctrl+W')
        assert dialog.isVisible() and dialog.oznak_sync_thread is worker and not worker._cancel_requested
        press(qapplication_session, dialog.cancel_sync_button, 'Ctrl+Shift+S')
        assert worker._cancel_requested and worker.isRunning() and dialog.oznak_sync_thread is worker
        assert 'Stop requested' in dialog.stage_label.text()
        assert repository.summarize_counts().records == 2000
        release.set()
        wait_until(qapplication_session, lambda: dialog.oznak_sync_thread is None)
        assert worker.wait(2000)
        assert forwarded == [('REF-1',)]
        assert repository.latest_sync_run().status == 'cancelled'
        assert repository.summarize_counts().records == 2000
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM industrial_records WHERE source_record_key='uiux-new-pending'").fetchone() == (0,)
        assert dialog.close_button.isEnabled() and not dialog.cancel_sync_button.isEnabled()
    finally:
        release.set()
        if worker is not None:
            assert worker.wait(10000)
            wait_until(qapplication_session, lambda: dialog.oznak_sync_thread is None)


def test_missing_source_configure_key_uses_existing_saved_profile_controller(ui, tmp_path, qapplication_session):
    from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
    dialog = ui('sync')
    assert 'Configure sources' in dialog.stage_label.text() and not dialog.sync_now_button.isEnabled()
    failures = []
    seen_children = []

    def save_source():
        child = QApplication.activeModalWidget()
        if not isinstance(child, IndustrialSourceProfilesDialog):
            failures.append('Expected the actual source configuration dialog')
            return
        seen_children.append(True)
        child.source_name_edit.setText('Synthetic configured source')
        child.alias_edit.setText('uiux_new')
        child.host_edit.setText('synthetic.invalid')
        child.database_edit.setText('synthetic')
        child.table_edit.setText('events')
        child.columns_edit.setText('event_id, event_at, reference')
        child.record_key_edit.setText('event_id')
        child.timestamp_column_edit.setText('event_at')
        child.save_source()
        child.reject()

    activate_for_key(qapplication_session, dialog.configure_sources_button)
    assert dialog.configure_sources_button.hasFocus()
    with observe_key(qapplication_session, dialog.configure_sources_button, 'Ctrl+D'):
        QTimer.singleShot(0, save_source)
        # No activation/event pumping may run this timer before the real command opens its child.
        QTest.keyClick(dialog.configure_sources_button, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert not failures
    assert seen_children == [True]
    assert dialog.current_profile() is not None and dialog.current_profile().profile_key == 'uiux_new'
    assert 'Next: Check access' in dialog.stage_label.text() and dialog.test_connection_button.isEnabled()


@pytest.mark.parametrize('kind', ['data', 'sync'])
def test_industrial_keys_remain_button_guarded_and_child_isolated(ui, qapplication_session, kind):
    dialog = ui(kind)
    button = dialog.sync_button if kind == 'data' else dialog.test_connection_button
    button.clicked.disconnect()
    hits = []
    button.clicked.connect(lambda: hits.append(True))
    sequence = 'Ctrl+R'
    button.setEnabled(False)
    press(qapplication_session, dialog, sequence)
    assert not hits
    button.setEnabled(True)
    press(qapplication_session, button, sequence)
    assert hits == [True]
    child = QDialog(dialog)
    child.setModal(True)
    text = QLineEdit(child)
    layout = QVBoxLayout(child)
    layout.addWidget(text)
    child.show()
    try:
        press(qapplication_session, text, sequence)
        assert hits == [True]
        text.setText('ordinary text')
        press(qapplication_session, text, 'Ctrl+A')
        assert text.selectedText() == 'ordinary text'
    finally:
        child.close()


@pytest.mark.parametrize('kind', ['data', 'sync'])
def test_existing_native_geometry_consumer_remains_satisfied(ui, qapplication_session, kind):
    dialog = ui(kind)
    if kind == 'data':
        controls, focus = (dialog.status_label, dialog.sync_button), (dialog.sync_button,)
        pinned = (dialog.next_action_label, dialog.sync_button, dialog.analyze_button, dialog.export_button, dialog.close_button)
    else:
        controls = (dialog.select_all_sources_button, dialog.current_source_only_button, dialog.close_button,
                    dialog.test_connection_button, dialog.sync_now_button, dialog.fetch_csv_summary_button, dialog.cancel_sync_button)
        focus = (dialog.select_all_sources_button, dialog.current_source_only_button, dialog.close_button)
        pinned = (dialog.stage_label, dialog.close_button, dialog.test_connection_button, dialog.sync_now_button,
                  dialog.fetch_csv_summary_button, dialog.cancel_sync_button)
    actual = _geometry_dialog(dialog, qapplication_session, controls, focus_controls=focus, scroll=dialog.content_scroll)
    assert actual['client'] == [760, 480]
    screen = qapplication_session.primaryScreen()
    print(f'industrial-screen={screen.geometry().width()}x{screen.geometry().height()} DPR={screen.devicePixelRatio()}')
    assert screen.devicePixelRatio() == float(os.environ.get('METROLIZA_INDUSTRIAL_TEST_DPR', '1'))
    for widget in pinned:
        assert dialog.rect().contains(widget.geometry())
        assert widget.isVisibleTo(dialog)
