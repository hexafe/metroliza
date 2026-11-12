"""FULL1 regressions: active config ownership and truthful cache outcome guidance."""
from contextlib import closing
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_source_config import build_source_profile, upsert_source_profile_in_config
from metroliza.reports import db as report_db
from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result
from metroliza.ui import industrial_data_dialog as data, industrial_sync_dialog as sync
from metroliza.ui import industrial_source_profiles_dialog as sources
from tests.test_industrial_onboarding_presentation import ui  # noqa: F401
from tests.test_report_planner_integration import wait_until


def profile(repository, key, name):
    return repository.upsert_source_profile(profile_key=key, profile_name=name,
        source_db_alias=key, database_type='sqlite', source_object_name='events')


@pytest.mark.parametrize('flow', ['success', 'error', 'batch'])
def test_modal_config_b_survives_callback_refresh_and_actual_cached_handoff(ui, tmp_path, monkeypatch, qapplication_session, flow):  # noqa: F811
    paths = (tmp_path / 'sources.yaml', tmp_path / 'chosen-b.yaml')
    for path, name, table in ((paths[0], 'Synthetic A', 'events_a'), (paths[1], 'Synthetic B', 'events_b')):
        upsert_source_profile_in_config(path, build_source_profile(profile_key='uiux_same',
            profile_name=name, source_db_alias='uiux_same', database_type='mssql',
            host=f'{table}.invalid', port=1433, database_name='synthetic', source_object_name=table,
            allowed_columns=('id', 'value')))
    parent = ui(database=tmp_path / 'cache # próba.db')
    repository = IndustrialDataRepository(parent.db_file)
    selected = repository.list_source_profiles()[0]
    repository.upsert_industrial_records_from_rows(source_profile_id=selected.id,
        source_db_alias=selected.source_db_alias, rows=({'source_record_key': 'one', 'value': 3},))
    profile(repository, 'uiux_other', 'Other synthetic')
    parent.refresh_status()
    failures, handed_off, observed = [], [], []
    monkeypatch.setattr(sources.QFileDialog, 'getSaveFileName', lambda *_args: (str(paths[1]), ''))
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)

    class Analytics:
        def __init__(self, _parent, **kwargs):
            self.loaded = kwargs['tabular_load_result']
        def exec(self):
            frame = self.loaded.sqlite_store.read_dataframe(columns=('source', 'source_profile_id'))
            handed_off.append((set(frame.source), set(frame.source_profile_id)))
            cleanup_tabular_load_result(self.loaded)

    monkeypatch.setattr(data, 'IndustrialAnalyticsDialog', Analytics)
    native_exec = sync.IndustrialSyncDialog.exec

    def choose_b():
        child = QApplication.activeModalWidget()
        try:
            assert isinstance(child, sources.IndustrialSourceProfilesDialog)
            child.browse_config_file()
            child.save_source()  # immediate-save controller, not a staged profile substitute
        except Exception as exc:
            failures.append(exc)
        finally:
            if isinstance(child, sources.IndustrialSourceProfilesDialog):
                child.reject()

    def operate(dialog):
        try:
            QTimer.singleShot(0, choose_b)
            dialog.configure_sources_button.click()  # nested real modal editor; no activation pump before its timer
            assert not failures
            assert dialog.isVisible() and QApplication.activeModalWidget() is dialog
            assert parent.config_path == dialog.config_path == paths[1]
            result = {'status': 'succeeded', 'test_only': False, 'row_count': 0,
                      'cache_summary': {'records': 0}, 'upsert_summary': {'processed': 0}}
            if flow == 'error':
                dialog.on_oznak_error('Synthetic source denied')
                parent.open_analytics_dialog()
            else:
                dialog._open_csv_summary_after_fetch = True
                if flow == 'batch':
                    dialog._active_batch_total = 2
                    dialog.on_oznak_result({**result, 'profile_key': 'uiux_same'})
                dialog.on_oznak_result({**result, 'profile_key': 'uiux_other' if flow == 'batch' else 'uiux_same'})
            wait_until(qapplication_session, lambda: bool(handed_off))
            stored = next(item for item in repository.list_source_profiles() if item.profile_key == 'uiux_same')
            observed.append((parent.config_path, stored.profile_name, stored.source_object_name, stored.host,
                             dialog.isVisible(), QApplication.activeModalWidget() is dialog))
        except Exception as exc:
            failures.append(exc)
        finally:
            dialog.reject()

    def execute(dialog):
        QTimer.singleShot(0, lambda: operate(dialog))
        return native_exec(dialog)

    monkeypatch.setattr(sync.IndustrialSyncDialog, 'exec', execute)
    parent.open_sync_dialog()
    assert not failures, failures
    assert observed == [(paths[1], 'Synthetic B', 'events_b', 'events_b.invalid', True, True)]
    assert handed_off == [({'Synthetic B'}, {selected.id})]
    assert parent.config_path == paths[1]


@pytest.mark.parametrize('batch', [False, True])
@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('status', ['succeeded', 'completed_with_warnings', 'failed', 'cancelled'])
def test_zero_row_single_and_batch_guidance_uses_actual_whole_cache(ui, tmp_path, batch, cached, status):  # noqa: F811
    path = str(tmp_path / 'outcome.db')
    repository = IndustrialDataRepository(path)
    profile(repository, 'uiux_current', 'Current empty source')
    other = profile(repository, 'uiux_other', 'Another source')
    if cached:
        repository.upsert_industrial_records_from_rows(source_profile_id=other.id,
            source_db_alias=other.source_db_alias, rows=({'source_record_key': 'existing', 'value': 1},))
    dialog = ui('sync', path, report_db_file=None)
    result = {'status': status, 'test_only': False, 'row_count': 0, 'cache_summary': {'records': 0},
              'upsert_summary': {'processed': 0}, 'diagnostics': {}, 'error': 'Synthetic failure' if status == 'failed' else None}
    if batch:
        dialog._active_batch_total = 2
        dialog.on_oznak_result({**result, 'profile_key': 'uiux_current'})
        dialog.on_oznak_result({**result, 'profile_key': 'uiux_other'})
    else:
        dialog.on_oznak_result(result)
    text = dialog.stage_label.text()
    if cached:
        assert 'Cached rows are available' in text and 'Analyze or Export' in text
        assert dialog.close_button.property('buttonRole') == 'primary'
    else:
        assert 'local cache is empty' in text and 'Analyze or Export' not in text
        assert 'source/scope' in text and dialog.test_connection_button.property('buttonRole') == 'primary'
    assert (dialog.stage_label.property('statusVariant') == 'success') == (status == 'succeeded' and cached)
    assert repository.summarize_counts().records == int(cached)


def test_outcome_read_is_bounded_readonly_closed_and_missing_stays_unknown(ui, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / 'read # próba %25.db'
    repository = IndustrialDataRepository(str(path))
    profile(repository, 'uiux_current', 'Current')
    dialog = ui('sync', str(path), report_db_file=None)
    original_connect = sqlite3.connect
    connections, statements, parameters, closed = [], [], [], []
    before = path.read_bytes()

    class ObservedCursor(sqlite3.Cursor):
        def close(self):
            closed.append('cursor')
            super().close()

    class ObservedConnection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            return self.cursor(factory=ObservedCursor).execute(*args, **kwargs)

        def close(self):
            closed.append('connection')
            super().close()

    def connect(filename, **kwargs):
        parameters.append((filename, kwargs))
        connection = original_connect(filename, factory=ObservedConnection, **kwargs)
        connection.set_trace_callback(statements.append)
        connections.append(connection)
        return connection

    monkeypatch.setattr(report_db.sqlite3, 'connect', connect)
    assert dialog._cache_has_rows() is False
    assert len(connections) == 1 and statements == ['SELECT 1 FROM industrial_records LIMIT 1']
    uri = urlsplit(parameters[0][0])
    assert Path(unquote(uri.path)) == path.resolve()
    assert parse_qs(uri.query) == {'mode': ['ro']}  # A live cache must not use immutable=1.
    assert parameters[0][1] == {'uri': True, 'timeout': 0.1}
    assert closed == ['cursor', 'connection'] and path.read_bytes() == before
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')
    path.unlink()
    dialog._present_result_stage({'status': 'succeeded', 'test_only': False, 'row_count': 0})
    assert not path.exists()
    assert 'could not be confirmed' in dialog.stage_label.text()
    assert 'Analyze or Export' not in dialog.stage_label.text()
    assert dialog.stage_label.property('statusVariant') == 'warning'


def test_unavailable_read_and_error_keep_unknown_not_empty(ui, tmp_path, monkeypatch):  # noqa: F811
    dialog = ui('sync', str(tmp_path / 'unavailable.db'), report_db_file=None)
    with closing(sqlite3.connect(dialog.db_file)) as blocker:
        # WAL permits readers during EXCLUSIVE; use a private rollback-journal fixture.
        with closing(blocker.execute('PRAGMA journal_mode=DELETE')) as mode:
            assert mode.fetchone() == ('delete',)
        with closing(blocker.execute('BEGIN EXCLUSIVE')):
            try:
                assert dialog._cache_has_rows() is None
            finally:
                blocker.rollback()
    calls = []

    def locked(_uri, **kwargs):
        calls.append(kwargs)
        raise sqlite3.OperationalError('synthetic locked cache')

    monkeypatch.setattr(report_db.sqlite3, 'connect', locked)
    dialog.on_oznak_error('Synthetic unavailable cache')
    assert calls == [{'uri': True, 'timeout': 0.1}]
    assert 'could not be confirmed' in dialog.stage_label.text() and 'cache is empty' not in dialog.stage_label.text()


def test_access_only_and_active_check_exceptions_never_probe_cache(ui, tmp_path, monkeypatch):  # noqa: F811
    config = tmp_path / 'access-sources.yaml'
    upsert_source_profile_in_config(config, build_source_profile(profile_key='uiux_check',
        profile_name='Synthetic access check', source_db_alias='uiux_check', database_type='mssql',
        host='synthetic.invalid', port=1433, database_name='synthetic', source_object_name='events',
        allowed_columns=('id',)))
    path = str(tmp_path / 'check-cache.db')
    profile(IndustrialDataRepository(path), 'uiux_check', 'Cached check source')
    for access_only in (True, False):
        dialog = sync.IndustrialSyncDialog(db_file=None if access_only else path, access_only=access_only,
                                           report_db_file=None, config_path=config)
        if not access_only:
            dialog._active_operation = sync._OznakOperation(profile=dialog.current_profile(),
                username='synthetic_operator', password='example-password', fetch_state=None,
                test_only=True, access_only=False, pending_credential_save=None)
        monkeypatch.setattr(dialog, '_cache_has_rows', lambda: pytest.fail('access checks must not probe the cache'))
        try:
            dialog.on_oznak_error('Synthetic access failure')
            assert 'Check credentials' in dialog.stage_label.text() and 'Check access' in dialog.stage_label.text()
            assert 'Cache readiness' not in dialog.stage_label.text()
            assert dialog.test_connection_button.isEnabled()
            assert dialog.test_connection_button.property('buttonRole') == 'primary'
        finally:
            assert dialog.close()
