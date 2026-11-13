import os
import types
import unittest
from unittest.mock import patch

import pytest

from PyQt6.QtCore import Qt
from metroliza.ui.modify_db import ModifyDB
from metroliza.ui.modify_db_records import RecordTableModel


def _wait_edit(dialog):
    from PyQt6.QtTest import QTest
    for _ in range(1000):
        if vars(dialog).get('_edit_thread') is None:
            return
        QTest.qWait(10)
    pytest.fail('save worker did not complete')


def _record_table(specs, rows):
    """Build a record-table stand-in from ``(original, current)`` cell pairs per row.

    Record tables are model/view based since #1118: originals live in the model and every
    differing ``current`` value is applied through ``setData`` like an in-cell edit. Cells the
    model refuses (read-only columns) are returned so tests can assert they were rejected.
    """

    model = RecordTableModel(specs, [tuple(original for original, _current in row) for row in rows])
    rejected = []
    for row_index, row in enumerate(rows):
        for column_index, (original, current) in enumerate(row):
            accepted = model.setData(model.index(row_index, column_index), current, Qt.ItemDataRole.EditRole)
            if not accepted and current != ("" if original is None else str(original)):
                rejected.append((row_index, column_index))
    return types.SimpleNamespace(model=lambda: model), rejected


class _FakeRepository:
    def __init__(self):
        self.report_updates = []
        self.measurement_updates = []

    def update_report_metadata_fields(self, report_id, fields):
        self.report_updates.append((report_id, fields))

    def update_measurement_fields(self, measurement_id, fields):
        self.measurement_updates.append((measurement_id, fields))


class _FakeEditService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def apply_changes(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


class TestModifyDbRecordUpdates(unittest.TestCase):
    def test_collect_report_record_updates_ignores_readonly_and_unchanged_cells(self):
        dialog = ModifyDB.__new__(ModifyDB)
        specs = [
            {"label": "REPORT_ID", "field": "report_id", "editable": False},
            {"label": "REFERENCE", "field": "reference", "editable": True},
            {"label": "COMMENT", "field": "comment", "editable": True},
            {"label": "FILENAME", "field": "file_name", "editable": False},
        ]
        table, rejected = _record_table(
            specs,
            [
                [(42, "42"), ("REF_A", "REF_B"), ("old comment", ""), ("source.pdf", "renamed.pdf")],
                [(43, "43"), ("REF_C", "REF_C"), (None, ""), ("source2.pdf", "source2.pdf")],
            ],
        )

        updates = dialog.collect_record_table_updates(table, "report_id")

        self.assertEqual(updates, [(42, {"reference": "REF_B", "comment": None})])
        self.assertEqual(rejected, [(0, 3)])

    def test_collect_measurement_record_updates_coerces_float_cells(self):
        dialog = ModifyDB.__new__(ModifyDB)
        specs = [
            {"label": "MEASUREMENT_ID", "field": "measurement_id", "editable": False},
            {"label": "REPORT_ID", "field": "report_id", "editable": False},
            {"label": "NOM", "field": "nominal", "editable": True, "value_type": "float"},
            {"label": "OUTTOL", "field": "outtol", "editable": True, "value_type": "float"},
            {"label": "STATUS_CODE", "field": "status_code", "editable": True},
        ]
        table, _rejected = _record_table(
            specs,
            [[(7, "7"), (42, "42"), (10.0, "10.25"), (0.1, ""), ("nok", "ok")]],
        )

        updates = dialog.collect_record_table_updates(table, "measurement_id")

        self.assertEqual(updates, [(7, {"nominal": 10.25, "outtol": None, "status_code": "ok"})])

    def test_apply_record_updates_dispatches_to_repository_methods(self):
        dialog = ModifyDB.__new__(ModifyDB)
        repository = _FakeRepository()

        dialog.apply_record_updates(
            repository,
            [(42, {"reference": "REF_B"})],
            [(7, {"header": "H2"})],
        )

        self.assertEqual(repository.report_updates, [(42, {"reference": "REF_B"})])
        self.assertEqual(repository.measurement_updates, [(7, {"header": "H2"})])

    def test_apply_record_updates_requires_repository_api(self):
        dialog = ModifyDB.__new__(ModifyDB)

        with self.assertRaisesRegex(RuntimeError, "update_report_metadata_fields"):
            dialog.apply_record_updates(object(), [(42, {"reference": "REF_B"})], [])

    def test_collect_record_table_modifications_reports_original_values(self):
        dialog = ModifyDB.__new__(ModifyDB)
        specs = [
            {"label": "REPORT_ID", "field": "report_id", "editable": False},
            {"label": "REFERENCE", "field": "reference", "editable": True},
            {"label": "COMMENT", "field": "comment", "editable": True},
        ]
        table, _rejected = _record_table(
            specs,
            [[(42, "42"), ("REF_A", "REF_B"), ("old comment", "")]],
        )

        summary = dialog.collect_record_table_modifications(table, "Report records", "report_id")

        self.assertEqual(
            summary,
            'Report records.REFERENCE: "REF_A" -> "REF_B" (REPORT_ID=42)\n'
            'Report records.COMMENT: "old comment" -> NULL (REPORT_ID=42)',
        )

    def test_record_value_coercion_rejects_invalid_float_text(self):
        self.assertIsNone(ModifyDB._coerce_record_value("", "float"))
        self.assertEqual(ModifyDB._coerce_record_value("10.5", "float"), 10.5)
        with self.assertRaises(ValueError):
            ModifyDB._coerce_record_value("not-a-number", "float")
        self.assertEqual(ModifyDB._coerce_record_id("bad-id"), None)

    def test_apply_changes_delegates_collected_payload_to_report_edit_service(self):
        dialog = ModifyDB.__new__(ModifyDB)
        reference_table = object()
        sample_table = object()
        header_table = object()
        service = _FakeEditService()
        changes_by_table = {
            reference_table: [("REF-B", "REF-A")],
            sample_table: [],
            header_table: [("WIDTH", "OLD WIDTH")],
        }
        dialog.reference_table = reference_table
        dialog.part_number_table = sample_table
        dialog.header_table = header_table
        dialog._storage_flavor = "current"
        dialog.collect_normalization_value_changes = lambda table: changes_by_table[table]
        dialog.collect_report_record_updates = lambda: [(42, {"comment": "reviewed"})]
        dialog.collect_measurement_record_updates = lambda: [(7, {"header": "WIDTH"})]
        dialog._create_report_edit_service = lambda: service
        dialog.close = lambda: None

        with patch("metroliza.ui.modify_db.QMessageBox.information"):
            dialog.apply_changes()

        self.assertEqual(
            service.calls,
            [
                {
                    "storage_flavor": "current",
                    "normalization_changes": {
                        "reference": [("REF-B", "REF-A")],
                        "sample_number": [],
                        "header": [("WIDTH", "OLD WIDTH")],
                    },
                    "report_updates": [(42, {"comment": "reviewed"})],
                    "measurement_updates": [(7, {"header": "WIDTH"})],
                }
            ],
        )

    def test_apply_changes_forwards_service_error_to_dialog_error_handler(self):
        dialog = ModifyDB.__new__(ModifyDB)
        dialog.reference_table = object()
        dialog.part_number_table = object()
        dialog.header_table = object()
        dialog._storage_flavor = "current"
        dialog.collect_normalization_value_changes = lambda _table: [("new", "old")]
        dialog.collect_report_record_updates = lambda: []
        dialog.collect_measurement_record_updates = lambda: []
        failure = ValueError("unsupported report edit")
        dialog._create_report_edit_service = lambda: _FakeEditService(failure)
        captured = []
        dialog.log_and_exit = captured.append

        dialog.apply_changes()

        self.assertEqual(captured, [failure])


if __name__ == "__main__":
    unittest.main()


@pytest.mark.parametrize('factory_hook', ['method', 'global'])
def test_literal_custom_repository_factory_and_callbacks_stay_on_gui(tmp_path, qapplication_session, monkeypatch, factory_hook):
    import threading
    from metroliza.ui import modify_db
    from tests.test_modifydb_parity import _build_current_database

    database = tmp_path / 'custom.db'
    _build_current_database(database)
    dialog = ModifyDB(db_file=str(database), modal=False)
    dialog.ensure_record_tables_loaded()
    model = dialog.report_records_table.model()
    column = next(i for i, s in enumerate(model.specs) if s['field'] == 'comment')
    model.setData(model.index(0, column), 'literal edit', Qt.ItemDataRole.EditRole)
    events = []
    gui = threading.get_ident()

    class Repository:
        def update_report_metadata_fields(self, record_id, fields):
            events.append(('report', record_id, fields, threading.get_ident()))

    def factory():
        events.append(('factory', dialog.db_file, threading.get_ident()))
        return Repository()

    if factory_hook == 'method':
        dialog._create_report_repository = factory
    else:
        monkeypatch.setattr(modify_db, 'ReportRepository', lambda _database: factory())
    monkeypatch.setattr(modify_db.QMessageBox, 'information',
                        lambda _parent, title, _text: events.append(('message', title, threading.get_ident())))
    dialog.apply_changes()
    assert events == [('factory', str(database), gui),
                      ('report', 1, {'comment': 'literal edit'}, gui),
                      ('message', 'Changes applied', gui)]
    assert dialog._changes_committed
    dialog.close()


def _editable_dialog(tmp_path, monkeypatch, flavor='current'):
    from metroliza.ui import modify_db
    from tests.test_modifydb_parity import DATABASE_BUILDERS

    database = tmp_path / (flavor + '.db')
    DATABASE_BUILDERS[flavor](database)
    dialog = ModifyDB(db_file=str(database), modal=False)
    dialog.ensure_record_tables_loaded()
    model = dialog.report_records_table.model()
    column = next(i for i, spec in enumerate(model.specs) if spec['field'] == 'reference')
    model.setData(model.index(0, column), 'SNAPSHOT', Qt.ItemDataRole.EditRole)
    messages, errors = [], []
    monkeypatch.setattr(modify_db.QMessageBox, 'information', lambda *args: messages.append(args[1:]))
    dialog.log_and_exit = errors.append
    return dialog, database, model, column, messages, errors


def test_default_apply_uses_worker_and_closes_with_identical_saved_rows(tmp_path, qapplication_session, monkeypatch):
    from contextlib import closing
    import sqlite3
    import threading
    from metroliza.reports import db

    dialog, database, _model, _column, messages, errors = _editable_dialog(tmp_path, monkeypatch)
    owner_threads = []
    original_connect = db.connect_sqlite
    def connect(*args, **kwargs):
        owner_threads.append(threading.get_ident())
        return original_connect(*args, **kwargs)
    monkeypatch.setattr(db, 'connect_sqlite', connect)
    dialog.apply_changes()
    _wait_edit(dialog)
    assert owner_threads and threading.get_ident() not in owner_threads
    assert errors == [] and messages == [('Changes applied', 'Changes have been applied successfully.')]
    assert dialog._changes_committed and not dialog.isVisible()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT reference FROM report_metadata WHERE report_id=1').fetchone() == ('SNAPSHOT',)


def test_default_legacy_apply_and_noop_keep_exact_messages(tmp_path, qapplication_session, monkeypatch):
    from contextlib import closing
    import sqlite3

    dialog, database, _model, _column, messages, errors = _editable_dialog(tmp_path, monkeypatch, 'legacy')
    dialog.apply_changes()
    _wait_edit(dialog)
    assert not errors and dialog._changes_committed
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT REFERENCE FROM REPORTS WHERE ID=1').fetchone() == ('SNAPSHOT',)
    clean = ModifyDB(db_file=str(database), modal=False)
    clean.apply_changes()
    assert not clean._changes_committed
    assert messages == [('Changes applied', 'Changes have been applied successfully.'),
                        ('No changes', 'No changes were detected.')]
    clean.close()


def test_save_error_rolls_back_batch_and_ui_error_callback_runs_on_gui(tmp_path, qapplication_session, monkeypatch):
    from contextlib import closing
    import sqlite3
    import threading

    dialog, database, _model, _column, messages, errors = _editable_dialog(tmp_path, monkeypatch)
    dialog.collect_measurement_record_updates = lambda: [(999999, {'header': 'missing'})]
    callbacks = []
    dialog.log_and_exit = lambda error: callbacks.append((str(error), threading.get_ident()))
    gui = threading.get_ident()
    dialog.apply_changes()
    _wait_edit(dialog)
    assert callbacks == [('Measurement 999999 does not exist', gui)]
    assert errors == [] and messages == [] and not dialog._changes_committed
    assert dialog.isVisible() and dialog.apply_button.isEnabled() and dialog.tab_widget.isEnabled()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT reference FROM report_metadata WHERE report_id=1').fetchone() == ('REF-A',)
    dialog._discard_confirmed = True
    dialog.close()


def test_custom_service_method_is_not_run_on_worker(tmp_path, qapplication_session, monkeypatch):
    import threading
    from metroliza.ui import modify_db

    dialog, _database, _model, _column, messages, errors = _editable_dialog(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(modify_db.ReportEditService, 'apply_changes',
                        lambda service, **payload: calls.append((threading.get_ident(), payload)))
    dialog.apply_changes()
    assert calls[0][0] == threading.get_ident()
    assert calls[0][1]['report_updates'] == [(1, {'reference': 'SNAPSHOT'})]
    assert not errors and len(messages) == 1


@pytest.mark.parametrize("partial_error", [False, True])
def test_public_synchronous_apply_normal_close_native_process(tmp_path, partial_error):
    import subprocess
    import sys
    script = """
from contextlib import closing
import sqlite3, sys
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from metroliza.app.bootstrap import get_or_create_qapplication
from metroliza.ui import modify_db
from tests.test_modifydb_parity import _build_current_database
app = get_or_create_qapplication()
app.setQuitOnLastWindowClosed(False)
path, partial_error = sys.argv[1], sys.argv[2] == 'True'
_build_current_database(path)
dialog = modify_db.ModifyDB(db_file=path, modal=False)
dialog.reference_table.item(0, 1).setText('SHUTDOWN')
if partial_error:
    dialog.collect_measurement_record_updates = lambda: [(999999, {'header': 'missing'})]
QMessageBox.information = lambda *args: None
QMessageBox.question = lambda *args: QMessageBox.StandardButton.Discard
errors = []
dialog.log_and_exit = lambda error: errors.append(str(error))
def apply_and_quit():
    dialog.apply_changes()
    app.quit()
QTimer.singleShot(0, apply_and_quit)
QTimer.singleShot(10000, lambda: app.exit(99))
assert app.exec() == 0
if partial_error:
    dialog._discard_confirmed = True
    dialog.close()
assert errors == (['Measurement 999999 does not exist'] if partial_error else [])
assert dialog._changes_committed == (not partial_error)
assert not dialog.isVisible()
with closing(sqlite3.connect(path)) as connection:
    assert connection.execute('SELECT DISTINCT reference FROM report_metadata WHERE reference=?',
                              ('SHUTDOWN',)).fetchall() == ([] if partial_error else [('SHUTDOWN',)])
print('public synchronous normal close; saved-reopen identical', partial_error, flush=True)
"""
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'shutdown.db'), str(partial_error)],
                            env={**os.environ, "PYTHONFAULTHANDLER": "1"}, capture_output=True, text=True, timeout=20)
    print('ModifyDB actual child exit', result.returncode, result.stdout, result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'public synchronous normal close; saved-reopen identical' in result.stdout
    assert 'QWaitCondition' not in result.stderr


def test_c2_repeated_saves_with_retained_editors_native_process(tmp_path):
    import subprocess
    import sys

    script = '''
from pathlib import Path
import sys
from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from metroliza.app.bootstrap import get_or_create_qapplication
from metroliza.ui import modify_db
from tests.test_modifydb_parity import _build_current_database
app = get_or_create_qapplication()
app.setQuitOnLastWindowClosed(False)
root = Path(sys.argv[1])
dialogs = []
index = 0
QMessageBox.information = lambda *args: None
def begin():
    database = str(root / f'{index}.sqlite')
    _build_current_database(database)
    owner = modify_db.ModifyDB(db_file=database, modal=False)
    dialogs.append(owner)
    owner.reference_table.item(0, 1).setText('REPEATED-SAVE')
    owner.apply_changes()
    QTimer.singleShot(1, poll)
def poll():
    global index
    owner = dialogs[-1]
    if owner._edit_thread is not None:
        QTimer.singleShot(1, poll)
        return
    assert owner._changes_committed
    index += 1
    if index == 50:
        app.quit()
    else:
        QTimer.singleShot(0, begin)
QTimer.singleShot(0, begin)
QTimer.singleShot(20000, lambda: app.exit(99))
assert app.exec() == 0
assert not modify_db.detached_threads.running_threads()
assert not modify_db.detached_threads._DEFERRED
assert all(not sip.isdeleted(owner) and owner._changes_committed for owner in dialogs)
print('REPEATED SAVES PASS', index, modify_db.__file__, flush=True)
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)],
                            env={**os.environ, "PYTHONFAULTHANDLER": "1"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'REPEATED SAVES PASS 50' in result.stdout


def test_c2_save_cleanup_after_event_loop_stops_native_process(tmp_path):
    import subprocess
    import sys

    script = '''
import sys
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PyQt6.QtWidgets import QMessageBox
from metroliza.app.bootstrap import get_or_create_qapplication
from metroliza.ui import detached_threads, modify_db
from tests.test_modifydb_parity import _build_current_database
app = get_or_create_qapplication()
app.setQuitOnLastWindowClosed(False)
QTimer.singleShot(0, app.quit)
assert app.exec() == 0
_build_current_database(sys.argv[1])
owner = modify_db.ModifyDB(db_file=sys.argv[1], modal=False)
owner.reference_table.item(0, 1).setText('AFTER-LOOP')
QMessageBox.information = lambda *args: None
owner.apply_changes()
worker, progress = owner._edit_thread, owner._edit_progress
destroyed = []
worker.destroyed.connect(lambda: destroyed.append(('worker', QThread.currentThread() == app.thread())))
progress.destroyed.connect(lambda: destroyed.append(('progress', QThread.currentThread() == app.thread())))
assert worker.wait(5000)
# Deliver finished callbacks without giving Qt a DeferredDelete turn.
QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
assert sip.isdeleted(progress), 'progress retained after stopped-loop completion'
assert sip.isdeleted(worker), 'save QThread retained after native completion'
assert sorted(destroyed) == [('progress', True), ('worker', True)], destroyed
assert owner._edit_thread is None and owner._edit_progress is None
assert not detached_threads.running_threads()
assert not detached_threads._DEFERRED
owner.close()
print('SAVE GUI CLEANUP AFTER LOOP PASS', destroyed, flush=True)
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'after-loop.sqlite')],
                            env={**os.environ, "PYTHONFAULTHANDLER": "1"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_uninitialized_standin_with_database_keeps_synchronous_service(tmp_path, monkeypatch):
    from contextlib import closing
    import sqlite3
    from metroliza.ui import modify_db

    database = tmp_path / 'standin.db'
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('CREATE TABLE REPORTS (REFERENCE TEXT)')
        connection.execute("INSERT INTO REPORTS VALUES ('A')")
    dialog = ModifyDB.__new__(ModifyDB)
    dialog.db_file, dialog._storage_flavor = str(database), 'legacy'
    dialog.reference_table, dialog.part_number_table, dialog.header_table = object(), object(), object()
    dialog.collect_normalization_value_changes = lambda table: [('A2', 'A')] if table is dialog.reference_table else []
    dialog.collect_report_record_updates = lambda: []
    dialog.collect_measurement_record_updates = lambda: []
    dialog.close = lambda: None
    errors = []
    dialog.log_and_exit = errors.append
    monkeypatch.setattr(modify_db.QMessageBox, 'information', lambda *args: None)
    dialog.apply_changes()
    assert not errors and dialog._changes_committed
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT REFERENCE FROM REPORTS').fetchall() == [('A2',)]


def test_c2_validation_error_has_one_clear_dialog(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui import modify_db
    from tests.test_modifydb_parity import _build_current_database

    database = tmp_path / 'validation.db'
    _build_current_database(database)
    dialog = ModifyDB(db_file=str(database), modal=False)
    dialog.ensure_record_tables_loaded()
    model = dialog.measurement_records_table.model()
    column = next(i for i, spec in enumerate(model.specs) if spec['field'] == 'meas')
    model.setData(model.index(0, column), 'bad')
    messages = []
    monkeypatch.setattr(modify_db.QMessageBox, 'information', lambda *args: messages.append(args[1:]))
    monkeypatch.setattr(modify_db.QMessageBox, 'critical', lambda *args: messages.append(args[1:]))
    try:
        dialog.apply_changes()
        assert len(messages) == 1
        assert messages[0][0] == 'Nothing was saved'
        assert 'Nothing was saved. Pending edits were kept.' in messages[0][1]
        assert 'MEASUREMENT_ID=101, MEAS: Invalid number' in messages[0][1]
        assert model.has_edits and not dialog._changes_committed
    finally:
        dialog._discard_confirmed = True
        dialog.close()


def test_c2_save_disables_database_switch_before_progress_creation(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui import modify_db

    dialog, _database, _model, _column, _messages, errors = _editable_dialog(tmp_path, monkeypatch)
    real_create = modify_db.create_delayed_worker_progress_dialog
    observed = []

    def create(*args, **kwargs):
        observed.append((dialog.select_db_button.isEnabled(), vars(dialog).get('_save_in_progress', False)))
        dialog.select_db_file()
        return real_create(*args, **kwargs)

    monkeypatch.setattr(modify_db, 'create_delayed_worker_progress_dialog', create)
    monkeypatch.setattr(modify_db.QMessageBox, 'question',
                        lambda *args: modify_db.QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(modify_db.QFileDialog, 'getOpenFileName',
                        lambda *args, **kwargs: pytest.fail('database picker opened during save'))
    dialog.apply_changes()
    _wait_edit(dialog)
    assert not errors
    assert observed == [(False, True)]
    assert dialog.select_db_button.isEnabled()


@pytest.mark.parametrize('error_type', [TypeError, ValueError])
def test_c2_unexpected_worker_error_keeps_traceback_and_one_dialog(tmp_path, qapplication_session, monkeypatch, error_type):
    from metroliza.ui import modify_db
    from metroliza.ui.modify_db_records import RecordSaveThread

    dialog, database, _model, _column, _messages, _errors = _editable_dialog(tmp_path, monkeypatch)
    del dialog.log_and_exit
    messages, logged = [], []
    monkeypatch.setattr(modify_db.QMessageBox, 'information', lambda *args: messages.append(args[1:]))
    monkeypatch.setattr(modify_db.QMessageBox, 'critical', lambda *args: messages.append(args[1:]))
    monkeypatch.setattr(modify_db, 'CustomLogger', lambda error, **kwargs: logged.append((error, kwargs)))
    if error_type is ValueError:
        def unexpected_value_error(*args, **kwargs):
            raise ValueError('unexpected service failure')
        monkeypatch.setattr(modify_db.ReportEditService, 'apply_changes', unexpected_value_error)
    worker = RecordSaveThread(str(database), {'unexpected_payload_argument': True})
    worker.start()
    assert worker.wait(5000)
    try:
        assert isinstance(worker.error, error_type)
        assert worker.error.__traceback__ is not None
        dialog._report_save_error(worker.error)
        assert len(logged) == 1 and logged[0][0].__traceback__ is not None
        assert logged[0][1]['behavior'] == 'log_only'
        assert len(messages) == 1 and messages[0][0] == 'Nothing was saved'
    finally:
        worker.error = None
        worker.deleteLater()
        dialog._discard_confirmed = True
        dialog.close()
