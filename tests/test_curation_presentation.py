"""Visible draft state, actual saved values and mapping-owned database boundaries."""
from contextlib import closing
from threading import Event
import sqlite3
import os
import time

import pytest
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QVBoxLayout, QPushButton

from metroliza.ui import characteristic_mapping_dialog as matching
from metroliza.ui.modify_db import ModifyDB
from metroliza.ui.modify_db_records import RecordRows, RecordTableModel
from tests.test_modifydb_record_updates import _wait_edit
from tests.test_report_workspace_shell import app, window, prepare_review, reports, wait_until  # noqa: F401, F811
from tests.test_wave0_modifydb_mapping import _database


def _native_ready(condition, timeout=2):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(5)
    return condition()


@pytest.fixture
def editor(qapplication_session):
    dialog = ModifyDB(modal=False)
    yield dialog
    dialog._changes_committed = True
    dialog.close()


def test_sparse_dirty_cells_filtered_identity_and_bounded_preview(qapplication_session):
    specs = [dict(field='report_id', label='REPORT_ID', key=True),
             dict(field='part_name', label='PART_NAME', editable=True)]
    model = RecordTableModel(specs, [(i, f'part-{i}') for i in range(1000)])
    for row in range(20):
        model.setData(model.index(row, 1), 'x' * 300)
    model.set_filter_text('part-999')
    assert model.rowCount() == 1 and model.pending_cell_count == 20
    preview = model.pending_preview()
    assert len(preview) == 12 and max(map(len, preview)) < 230
    assert 'Part name (ID 0)' in preview[0]
    model.set_filter_text('')
    index = model.index(0, 1)
    assert index.data(Qt.ItemDataRole.FontRole).bold()
    assert 'Pending:' in index.data(Qt.ItemDataRole.ToolTipRole)
    model.setData(index, 'part-0')
    assert model.pending_cell_count == 19 and index.data(Qt.ItemDataRole.FontRole) is None
    assert model.headerData(1, Qt.Orientation.Horizontal) == 'Part name'
    assert model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) == 'PART_NAME'
    assert model.headerData(99, Qt.Orientation.Horizontal) is None
    model.setData(index, '')
    assert '→ NULL' in model.pending_preview(20)[-1]


def test_normalization_count_bulk_and_unchanged_reversion(editor):
    editor.populate_table(editor.reference_table, [('A', 3), ('B', 2)])
    for row in range(2):
        editor.reference_table.item(row, 1).setText('C')
    assert '2 normalization values' in editor.pending_label.text()
    assert '(3 occurrences)' in editor.pending_preview()[0]
    editor.reference_filter_edit.setText('no match')
    assert len(editor.pending_preview()) == 2
    editor.reference_table.item(0, 1).setText('A')
    assert '1 normalization values' in editor.pending_label.text()
    editor.reference_table.item(1, 1).setText('B')
    assert not editor.has_pending_changes()
    assert '0 normalization values' in editor.pending_label.text()


def test_primary_apply_confirmation_is_bounded_and_child_isolated(editor, monkeypatch, qapplication_session):
    editor.db_file = 'selected.db'
    editor.apply_button.setEnabled(True)
    editor.populate_table(editor.reference_table, [(str(i), 1) for i in range(30)])
    for row in range(30):
        editor.reference_table.item(row, 1).setText('x' * 400)
    confirmations = []
    monkeypatch.setattr(QMessageBox, 'exec', lambda box: confirmations.append(box.text()) or QMessageBox.StandardButton.Cancel)
    editor.activateWindow()
    editor.reference_filter_edit.setFocus()
    QTest.qWait(10)
    QTest.keyClick(editor.reference_filter_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert len(confirmations) == 1 and len(confirmations[0]) < 2400
    assert '30 normalization values' in confirmations[0] and 'at most 12' in confirmations[0]
    child = QDialog(editor)
    child.setModal(True)
    layout = QVBoxLayout(child)
    button = QPushButton('Child', child)
    layout.addWidget(button)
    child.show()
    child.activateWindow()
    button.setFocus()
    QTest.qWait(10)
    QTest.keyClick(button, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert len(confirmations) == 1
    child.close()


def test_draft_apply_saves_exact_records_and_clears_ownership(tmp_path, qapplication_session, monkeypatch):
    path, _repository, report, _other, ids = _database(tmp_path)
    dialog = ModifyDB(db_file=path, modal=False)
    dialog.ensure_record_tables_loaded()
    try:
        model = dialog.report_records_table.model()
        row = next(row for row in range(model.rowCount()) if model.index(row, 0).data() == str(report))
        column = next(i for i, spec in enumerate(model.specs) if spec['field'] == 'part_name')
        model.setData(model.index(row, column), 'Corrected part')
        assert '1 record cells' in dialog.pending_label.text()
        assert any('Part name' in line and 'Corrected part' in line for line in dialog.pending_preview())
        monkeypatch.setattr(QMessageBox, 'information', lambda *_args: None)
        dialog.apply_changes()
        _wait_edit(dialog)
        assert dialog._changes_committed and not dialog.isVisible()
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute('SELECT part_name FROM report_metadata WHERE report_id=?', (report,)).fetchone() == ('Corrected part',)
    finally:
        dialog._changes_committed = True
        dialog.close()


def test_invalid_numeric_preview_keeps_draft_and_does_not_claim_saved(editor):
    specs = [dict(field='measurement_id', label='MEASUREMENT_ID', key=True),
             dict(field='meas', label='MEAS', editable=True, value_type='float')]
    model = RecordTableModel(specs, [(42, 10.0)])
    editor.measurement_records_table.set_record_model(model)
    model.setData(model.index(0, 1), 'NaN')
    with pytest.raises(ValueError, match='Invalid number'):
        editor.pending_preview()
    assert model.has_edits and 'Invalid number' in model.index(0, 1).data(Qt.ItemDataRole.ToolTipRole)


@pytest.mark.parametrize('decision', ['before', 'after', 'parent'])
def test_mapping_browse_retains_database_when_guard_rejects(qapplication_session, monkeypatch, decision):
    class Parent(QDialog):
        def set_db_file(self, _path):
            return False
    parent = Parent()
    dialog = matching.CharacteristicMappingDialog(parent, '', modal=False)
    dialog.db_file = 'old.db'
    dialog.db_path_input.setText('old.db')
    guards = iter([False] if decision == 'before' else [True, False] if decision == 'after' else [True, True])
    dialog.database_change_allowed = lambda: next(guards)
    chooser = []
    monkeypatch.setattr(matching.QFileDialog, 'getOpenFileName', lambda *_args: chooser.append(True) or ('new.db', ''))
    try:
        dialog.select_db_file()
        assert dialog.db_file == dialog.db_path_input.text() == 'old.db'
        assert bool(chooser) == (decision != 'before')
    finally:
        dialog.close()
        parent.close()


def test_mapping_resumes_keeps_actual_database_and_blocks_same_db_review(app, window, reports):  # noqa: F811
    host, _source, database = prepare_review(app, window, reports)
    window.launch_characteristic_mapping_dialog()
    dialog = window.characteristic_mapping_dialog
    wait_until(app, lambda: not dialog.is_loading_source_options())
    assert not dialog.isModal() and dialog.isVisible()
    window.launch_characteristic_mapping_dialog()
    assert window.characteristic_mapping_dialog is dialog
    assert not window._report_start_allowed()
    assert 'Name matching' in window.workspace_notice_label.text()
    other = database.with_name('other.db')
    assert window.set_db_file(str(other))
    assert dialog.db_file == dialog.db_path_input.text() == str(database)
    assert 'Name matching' in window._workflows_using_previous_database(str(other))
    assert window._report_start_allowed()
    assert 'save immediately' in dialog.persistence_label.text()
    dialog.close()
    app.processEvents()


@pytest.mark.parametrize('kind', ['modify', 'mapping'])
def test_curation_footer_and_status_fit_760x560(qapplication_session, kind):
    screen = qapplication_session.primaryScreen()
    print(f"curation-screen={screen.geometry().width()}x{screen.geometry().height()} DPR={screen.devicePixelRatio()}")
    assert screen.devicePixelRatio() == float(os.environ.get('METROLIZA_CURATION_EXPECT_DPR', '1'))
    dialog = ModifyDB(modal=False) if kind == 'modify' else matching.CharacteristicMappingDialog(modal=False)
    try:
        dialog.show()
        QTest.qWait(40)
        dialog.resize(760, 560)
        QTest.qWait(20)
        assert dialog.width() == 760 and dialog.height() == 560
        status = dialog.pending_label if kind == 'modify' else dialog.persistence_label
        buttons = (dialog.apply_button, dialog.cancel_button) if kind == 'modify' else (dialog.close_button, dialog.add_button, dialog.edit_button)
        for widget in (status, *buttons):
            assert widget.isVisibleTo(dialog)
            position = widget.mapTo(dialog, widget.rect().topLeft())
            assert position.x() >= 0 and position.y() >= 0
            assert position.x() + widget.width() <= dialog.width()
            assert position.y() + widget.height() <= dialog.height()
    finally:
        dialog.close()


@pytest.mark.parametrize('timing', ['before', 'during_chooser'])
def test_mapping_owned_context_rejects_actual_report_busy_transition(app, window, reports, monkeypatch, timing):  # noqa: F811
    from metroliza.parsing.preflight import ParsePreflightService

    host, _source, database = prepare_review(app, window, reports)
    window.launch_characteristic_mapping_dialog()
    dialog = window.characteristic_mapping_dialog
    wait_until(app, lambda: not dialog.is_loading_source_options())
    other = database.with_name('other.db')
    assert window.set_db_file(str(other))
    entered, release = Event(), Event()
    original = ParsePreflightService.scan_source

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(ParsePreflightService, 'scan_source', gated)
    choosers = []

    def choose(*_args):
        choosers.append(True)
        host.scan_button.click()
        wait_until(app, entered.is_set)
        return str(database.with_name('third.db')), ''

    monkeypatch.setattr(matching.QFileDialog, 'getOpenFileName', choose)
    try:
        if timing == 'before':
            host.scan_button.click()
            wait_until(app, entered.is_set)
        dialog.select_db_file()
        assert bool(choosers) == (timing == 'during_chooser')
        assert dialog.db_file == dialog.db_path_input.text() == str(database)
        assert window.db_file == str(other)
        window.launch_characteristic_mapping_dialog()
        assert window.characteristic_mapping_dialog is dialog
        assert not host.can_change_workspace()
    finally:
        release.set()
        wait_until(app, lambda: host.can_change_workspace() and host.metadata_thread is None)
        dialog.close()
        app.processEvents()


def test_ctrl_s_commits_active_record_delegate_before_confirmation(editor, monkeypatch):
    editor.db_file = 'selected.db'
    editor.apply_button.setEnabled(True)
    specs = [dict(field='report_id', label='REPORT_ID', key=True),
             dict(field='part_name', label='PART_NAME', editable=True)]
    editor._install_record_rows(editor._record_slots[0], specs,
                               RecordRows([(7, 'Old')], None))
    editor.tab_widget.setCurrentWidget(editor.report_records_tab)
    table = editor.report_records_table
    editor.activateWindow()
    table.setFocus()
    table.edit(table.model().index(0, 1))
    delegate = table.findChild(QLineEdit)
    assert delegate is not None
    delegate.selectAll()
    QTest.keyClicks(delegate, 'Typed part')
    assert _native_ready(lambda: editor.isActiveWindow() and delegate.hasFocus())
    confirmations = []
    monkeypatch.setattr(QMessageBox, 'exec', lambda box: confirmations.append(box.text()) or QMessageBox.StandardButton.Cancel)
    QTest.keyClick(delegate, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert len(confirmations) == 1 and 'Typed part' in confirmations[0]
    assert table.model().pending_cell_count == 1
    assert editor.collect_report_record_updates() == [(7, {'part_name': 'Typed part'})]


def test_mapping_actual_child_ctrl_s_saves_and_close_does_not_undo(tmp_path, qapplication_session):
    from metroliza.reports.characteristic_alias_service import ensure_characteristic_alias_schema, fetch_all_characteristic_aliases
    path = str(tmp_path / 'aliases.db')
    ensure_characteristic_alias_schema(path)
    dialog = matching.CharacteristicMappingDialog(db_file=path, modal=False)
    dialog.show()
    wait_until(qapplication_session, lambda: not dialog.is_loading_source_options())
    failures = []

    def save_editor():
        child = QApplication.activeModalWidget()
        if not isinstance(child, matching.CharacteristicAliasEditorDialog):
            failures.append('Expected the real mapping editor')
            return
        child.alias_input.setCurrentText('Original metric')
        child.common_name_input.setCurrentText('Common metric')
        child.common_name_input.setFocus()
        if not _native_ready(lambda: child.isActiveWindow() and
                             QApplication.activeModalWidget() is child and
                             (child.common_name_input.hasFocus() or child.common_name_input.lineEdit().hasFocus())):
            failures.append('The real modal editor never became active')
            child.reject()
            return
        QTest.keyClick(child.common_name_input, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        if child.isVisible():
            failures.append('Ctrl+S did not accept the editor')
            child.reject()

    try:
        QTimer.singleShot(0, save_editor)
        dialog.add_button.click()
        assert not failures
        assert len(fetch_all_characteristic_aliases(path)) == 1
        dialog.activateWindow()
        dialog.close_button.setFocus()
        QTest.qWait(10)
        QTest.keyClick(dialog.close_button, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
        assert not dialog.isVisible()
        reopened = matching.CharacteristicMappingDialog(db_file=path, modal=False)
        try:
            assert reopened.alias_table.rowCount() == 1
            assert reopened.alias_table.item(0, 1).text() == 'Common metric'
            assert len(fetch_all_characteristic_aliases(path)) == 1
        finally:
            reopened.close()
    finally:
        dialog.close()


def _mapping_browse_databases(app, window, tmp_path):  # noqa: F811
    from metroliza.reports.report_repository import ReportRepository
    source, _repository, _report, _other, _ids = _database(tmp_path)
    destination = str(tmp_path / 'other.db')
    ReportRepository(destination).ensure_schema()
    assert window.set_db_file(source)
    window.launch_characteristic_mapping_dialog()
    dialog = window.characteristic_mapping_dialog
    wait_until(app, lambda: not dialog.is_loading_source_options())
    return dialog, source, destination


@pytest.mark.parametrize('owners', [(), ('export',), ('modify',), ('realtime',), ('export', 'realtime')])
def test_successful_mapping_browse_reconciles_only_actual_context_owners(app, window, tmp_path, monkeypatch, owners):  # noqa: F811
    dialog, source, destination = _mapping_browse_databases(app, window, tmp_path)
    writers, rebinds = [], []
    attributes = {'export': 'export_dialog', 'modify': 'modifydb_dialog', 'realtime': 'realtime_monitoring_dialog'}
    try:
        for owner in owners:
            writer = QDialog(window)
            writer.db_file = source
            if owner == 'realtime':
                writer.rebind_database = lambda path: rebinds.append(path) or False
            setattr(window, attributes[owner], writer)
            writer.show()
            writers.append(writer)
        monkeypatch.setattr(matching.QFileDialog, 'getOpenFileName', lambda *_args: (destination, ''))
        dialog.select_db_file()
        wait_until(app, lambda: not dialog.is_loading_source_options())
        assert window.db_file == dialog.db_file == dialog.db_path_input.text() == destination
        notice = window.workspace_notice_label
        if not owners:
            assert notice.isHidden() and not notice.text()
        else:
            assert not notice.isHidden() and 'Name matching' not in notice.text()
            for owner, label in (('export', 'Export'), ('modify', 'Database editor'), ('realtime', 'Realtime Monitor')):
                assert (label in notice.text()) == (owner in owners)
            if 'realtime' in owners:
                assert rebinds == [destination]
                assert notice.property('statusVariant') == 'danger'
                assert 'temporary session data' in notice.text()
        # The accepted mapping session now blocks the new database, not its previous one.
        assert 'Name matching' in window._same_database_workflow_labels()
    finally:
        dialog.close()
        for writer in writers:
            writer.close()
        for attribute in attributes.values():
            setattr(window, attribute, None)
        app.processEvents()


def test_rejected_mapping_browse_preserves_database_and_unrelated_notice(app, window, tmp_path, monkeypatch):  # noqa: F811
    dialog, source, _destination = _mapping_browse_databases(app, window, tmp_path)
    invalid = tmp_path / 'not-a-database.db'
    invalid.write_text('invalid SQLite content', encoding='utf-8')
    notice = window.workspace_notice_label
    notice.setText('An unrelated operation needs attention.')
    notice.show()
    monkeypatch.setattr(matching.QFileDialog, 'getOpenFileName', lambda *_args: (str(invalid), ''))
    try:
        dialog.select_db_file()
        assert window.db_file == dialog.db_file == dialog.db_path_input.text() == source
        assert notice.text() == 'An unrelated operation needs attention.' and not notice.isHidden()
    finally:
        dialog.close()
        app.processEvents()


def test_accepted_mapping_browse_preserves_a_new_unrelated_host_warning(app, window, tmp_path, monkeypatch):  # noqa: F811
    dialog, _source, destination = _mapping_browse_databases(app, window, tmp_path)
    original = window.set_db_file

    def accept_and_warn(path):
        accepted = original(path)
        assert accepted
        window.workspace_notice_label.setText('A different operation now owns this warning.')
        window.workspace_notice_label.show()
        return accepted

    monkeypatch.setattr(window, 'set_db_file', accept_and_warn)
    monkeypatch.setattr(matching.QFileDialog, 'getOpenFileName', lambda *_args: (destination, ''))
    try:
        dialog.select_db_file()
        wait_until(app, lambda: not dialog.is_loading_source_options())
        assert window.db_file == dialog.db_file == destination
        assert window.workspace_notice_label.text() == 'A different operation now owns this warning.'
        assert not window.workspace_notice_label.isHidden()
    finally:
        dialog.close()
        app.processEvents()
