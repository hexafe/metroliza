"""Opt-in, real tabular UI journeys. Importing this module never loads Qt/UI."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from threading import Event
import time

SCHEMA_VERSION = 1
FACETS = ('csv_single_owner', 'csv_busy_resume', 'csv_db_independence', 'csv_outputs',
          'filter_scope', 'grouping_identity', 'grouping_apply_cancel_reset', 'bounded_reads', 'cleanup', 'captures')
ERROR_CODES = ('tabular_gate_missing', 'tabular_fixture_invalid', 'tabular_application_missing',
               'tabular_invariant_failed', 'tabular_phase_deadline', 'tabular_callback_failed',
               'tabular_capture_failed', 'tabular_worker_join_deadline', 'tabular_cleanup_failed', 'unexpected_exception')
FIXTURE_HASHES = {
    'analysis.csv': '764c2776b85b24c373b094b5095c7e043dee3fa2f3af48fb063781f5f4bbaef0',
    'grouping.csv': 'b04ea4ba08ee70e6a12e5fd709467ebf3049f21cd252ceea77a738bb9b07fb4e',
    'saved-groups.csv': '02770298bcb61b07fbc9bee9f0c38b4a86e2a0d8be8815e09ebdf9b31be7e54d',
    'oracles.json': '0530ba3857abf24863fd4c6faadb5c0a325bbdddd1c4030b0856e68240de451f',
}
CAPTURE_STATES = {
    'csv-busy': {'worker_running': True, 'modal_blocker': False, 'source_rows': 8, 'selected_rows': 4},
    'csv-resumed': {'completed': True, 'rows': 4, 'formats': ['html', 'xlsx']},
    'grouping-members': {'source_rows': 3000, 'ids': [1, 13, 25], 'date_field': 'captured_at'},
    'filter-scope': {'column': 'line', 'selected': ['East'], 'hidden_selected': 1, 'rows': 4},
    'output-summary': {'rows': 4, 'formats': ['html', 'xlsx'], 'scope': 'Line=East'},
}
_RETAINED_WINDOWS: list[object] = []

class TabularChecksFailure(ValueError):
    """A closed, path-free acceptance failure."""

def _require(condition, code='tabular_invariant_failed'):
    if not condition:
        raise TabularChecksFailure(code)

def _sha(path):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32 * 1024 * 1024,
             'tabular_fixture_invalid')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs_sha(pairs):
    return hashlib.sha256(json.dumps(pairs, separators=(',', ':')).encode()).hexdigest()


class _Journey:
    def __init__(self, scratch, fixtures, expected_dpr, capture, observation):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        self.app, self.Qt = QApplication.instance(), Qt
        _require(self.app is not None, 'tabular_application_missing')
        _require(self.app.primaryScreen().devicePixelRatio() == expected_dpr)
        self.root, self.fixtures = scratch, fixtures
        self.child = scratch / 'tabular'
        self.child.mkdir(mode=0o700)
        self.capture, self.dpr, self.result = capture, expected_dpr, observation
        self.evidence = observation['evidence']
        self.oracle = json.loads((fixtures / 'oracles.json').read_text())
        self.deadline, self.phase = time.monotonic() + 75, 'admission'
        self.window, self.csv = None, None
        self.stores, self.modals, self.callback_errors = [], [], []
        self.release = Event()
        for name in ('analysis.csv', 'grouping.csv', 'saved-groups.csv'):
            shutil.copyfile(fixtures / name, self.child / name)
            _require(_sha(self.child / name) == FIXTURE_HASHES[name], 'tabular_fixture_invalid')

    def passed(self, *facets):
        for facet in facets:
            self.result['facets'][facet] = 'passed'

    def wait(self, predicate, seconds=20):
        end = min(self.deadline - (0 if self.phase == 'cleanup' else 20), time.monotonic() + seconds)
        while not predicate() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        _require(bool(predicate()), 'tabular_phase_deadline')
        _require(not self.callback_errors, 'tabular_callback_failed')

    def reveal(self, widget):
        from PyQt6.QtWidgets import QScrollArea
        ancestor = widget.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                ancestor.ensureWidgetVisible(widget)
            ancestor = ancestor.parentWidget()
        self.app.processEvents()

    def activate(self, target):
        from PyQt6.QtGui import QGuiApplication
        window = target.window()
        expected_modal = window
        while expected_modal is not None and not (expected_modal.isWindow() and expected_modal.isModal()):
            expected_modal = expected_modal.parentWidget()
        self.reveal(target)
        window.activateWindow()
        if target is not window:
            target.setFocus()
        def ready():
            focus = self.app.focusWidget()
            owned = focus is not None and focus.window() is window
            return (self.app.activeWindow() is window and window.isActiveWindow()
                    and self.app.activeModalWidget() is expected_modal
                    and ((owned or (focus is None and QGuiApplication.focusWindow() is window.windowHandle()))
                         if target is window else owned and (target.focusProxy() or target).hasFocus()))
        self.wait(ready)

    def key(self, target, sequence):
        from PyQt6.QtGui import QKeySequence
        from PyQt6.QtTest import QTest
        self.activate(target)
        combination = QKeySequence(sequence)[0]
        QTest.keyClick(target, combination.key(), combination.keyboardModifiers())
        self.app.processEvents()

    def select(self, listing, value):
        from PyQt6.QtTest import QTest
        item = next((listing.item(i) for i in range(listing.count())
                     if listing.item(i).data(self.Qt.ItemDataRole.UserRole) == value), None)
        _require(item is not None)
        self.activate(listing)
        listing.scrollToItem(item)
        QTest.mouseClick(listing.viewport(), self.Qt.MouseButton.LeftButton,
                         pos=listing.visualItemRect(item).center())
        self.app.processEvents()

    def modal(self, trigger, kind, action):
        from PyQt6.QtCore import QTimer
        visited, failures = [], []
        def drive():
            modal = None
            try:
                modal = self.app.activeModalWidget() or next((w for w in self.app.topLevelWidgets()
                    if isinstance(w, kind) and w.parentWidget() in (self.window, self.csv)), None)
                _require(isinstance(modal, kind))
                visited.append(True)
                self.modals.append(modal)
                action(modal)
            except BaseException as error:
                failures.append(type(error).__name__)
                try:
                    if modal is not None:
                        modal.hide()  # Failure-only cleanup; never a successful UI outcome.
                        modal.reject()
                except BaseException as cleanup_error:
                    failures.append(type(cleanup_error).__name__)
        def expire():
            failures.append('modal_deadline')
            try:
                modal = self.app.activeModalWidget()
                if modal is not None and modal in self.modals:
                    modal.hide()
                    modal.reject()
            except BaseException as error:
                failures.append(type(error).__name__)
        timer, watchdog = QTimer(self.app), QTimer(self.app)
        timer.setSingleShot(True)
        watchdog.setSingleShot(True)
        timer.timeout.connect(drive)
        watchdog.timeout.connect(expire)
        timer.start(0)
        watchdog.start(max(1, int(min(20, self.deadline - 20 - time.monotonic()) * 1000)))
        try:
            trigger()
        finally:
            timer.stop()
            watchdog.stop()
            timer.deleteLater()
            watchdog.deleteLater()
        self.callback_errors.extend(failures)
        _require(visited and not failures, 'tabular_callback_failed')

    def yes(self, trigger):
        from PyQt6.QtWidgets import QMessageBox
        self.modal(trigger, QMessageBox, lambda box: box.button(QMessageBox.StandardButton.Yes).click())

    def choose_path(self, trigger, path):
        from PyQt6.QtWidgets import QFileDialog
        def choose(dialog):
            dialog.selectFile(str(path))
            dialog.accept()
        self.modal(trigger, QFileDialog, choose)

    def take(self, name, widget):
        _require(name in CAPTURE_STATES and name not in self.evidence['captures'], 'tabular_capture_failed')
        metadata = self.capture(name, widget, json.loads(json.dumps(CAPTURE_STATES[name])))
        _require(type(metadata) is dict and set(metadata) == {'path', 'sha256', 'width', 'height', 'dpr'}, 'tabular_capture_failed')
        expected_path, expected_size = 'uiux-' + name + '.png', widget.size() * self.dpr
        _require(type(metadata['path']) is str and metadata['path'] == expected_path
                 and type(metadata['sha256']) is str and type(metadata['dpr']) in (float, int) and metadata['dpr'] == self.dpr
                 and all(type(metadata[k]) is int and 0 < metadata[k] <= 8192 for k in ('width', 'height'))
                 and metadata['width'] == expected_size.width()
                 and metadata['height'] == expected_size.height(), 'tabular_capture_failed')
        output = self.root / expected_path
        _require(output.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n' and _sha(output) == metadata['sha256'], 'tabular_capture_failed')
        self.evidence['captures'][name] = dict(metadata)

    def idle(self, dialog):
        self.wait(lambda: not getattr(dialog, '_scope_query_running', False)
                  and not any(t.isRunning() for t in getattr(dialog, '_selector_preview_threads', ()))
                  and not any(t.isRunning() for t in getattr(dialog, '_preview_threads', ()))
                  and getattr(dialog, '_selector_preview_loading_dialog', None) is None
                  and getattr(dialog, '_preview_loading_dialog', None) is None)

    @contextmanager
    def notifications(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QMessageBox
        timer = QTimer(self.csv)
        def acknowledge():
            try:
                box = self.app.activeModalWidget()
                if isinstance(box, QMessageBox) and box.parentWidget() is self.csv:
                    if box.windowTitle() not in ('Analytics successful', 'Analytics completed with warnings'):
                        self.callback_errors.append('unexpected_terminal_notification')
                    button = box.button(QMessageBox.StandardButton.Ok)
                    _require(button is not None)
                    button.click()
            except BaseException as error:
                self.callback_errors.append(type(error).__name__)
        timer.timeout.connect(acknowledge)
        timer.start(10)
        try:
            yield
        finally:
            timer.stop()
            timer.deleteLater()

    def filters(self):
        from metroliza.ui.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
        self.phase = 'filter'
        counts = [self.csv._tabular_filtered_row_count()]
        def east(dialog, capture=False):
            self.select(dialog.column_list, 'line')
            dialog.add_column_button.click()
            self.idle(dialog)
            self.select(dialog.matching_list, 'East')
            dialog.matching_search.setText('West')
            self.idle(dialog)
            _require('1 hidden selected' in dialog.value_scope_label.text()
                     and dialog.get_column_filters()[0].selected_values == ('East',))
            if capture:
                self.take('filter-scope', dialog)
            dialog.apply_button.click()
        self.modal(self.csv.filters_button.click, TabularAnalyticsFilterDialog, lambda d: east(d, True))
        counts.append(self.csv._tabular_filtered_row_count())
        saved = self.csv.tabular_column_filters
        def cancel(dialog):
            dialog.expression_input.setText('Value > 50')
            self.yes(dialog.cancel_button.click)
        self.modal(self.csv.filters_button.click, TabularAnalyticsFilterDialog, cancel)
        _require(self.csv.tabular_column_filters == saved)
        counts.append(self.csv._tabular_filtered_row_count())
        def reset(dialog):
            self.yes(dialog.clear_filter_button.click)
            _require(not dialog.get_column_filters() and not dialog.get_filter_expression())
            _require(self.csv.tabular_column_filters == saved)
            dialog.apply_button.click()
        self.modal(self.csv.filters_button.click, TabularAnalyticsFilterDialog, reset)
        counts.append(self.csv._tabular_filtered_row_count())
        self.modal(self.csv.filters_button.click, TabularAnalyticsFilterDialog, east)
        counts.append(self.csv._tabular_filtered_row_count())
        _require(counts == [8, 4, 4, 8, 4])
        self.evidence['filter'] = {'row_counts': counts, 'selected_values': ['East'], 'hidden_selected': 1,
                                   'cancel_preserved': True, 'reset_applied': True}
        self.passed('filter_scope')

    def csv_journey(self):
        from PyQt6.QtCore import QSettings
        from PyQt6.QtTest import QSignalSpy
        from metroliza.app.ui_entrypoint import load_main_window_factory
        from metroliza.ui.ui_preferences import UiPreferences
        from metroliza.industrial import industrial_workers as workers
        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
        from metroliza.app.windows_candidate_lifecycle_checks import _logical_sha256
        self.phase = 'csv'
        settings = QSettings(str(self.child / 'settings.ini'), QSettings.Format.IniFormat)
        self.window = load_main_window_factory()('UIUX tabular', None, ui_preferences=UiPreferences(settings))
        self.window.show()
        databases = [self.child / name for name in ('db-a.sqlite', 'db-b.sqlite')]
        for path in databases:
            IndustrialDataRepository(str(path))
        database_hashes = [_logical_sha256(path) for path in databases]
        _require(self.window.set_db_file(str(databases[0])))
        self.window._activate_workspace('reports')
        self.window.csv_summary_action.trigger()
        self.csv = self.window.csv_summary_dialog
        _require(self.csv is not None and self.csv.isVisible() and not self.csv.isModal())
        source = self.child / 'analysis.csv'
        self.csv.input_file, self.csv.input_files = str(source), (str(source),)  # Explicit fixture admission.
        self.csv._sync_ui_state()
        self.csv.load_metrics_button.click()
        self.wait(lambda: self.csv.tabular_load_thread is None and self.csv.tabular_load_result is not None)
        _require(self.csv.tabular_load_result.row_count == 8)
        self.csv.reference_column_combo.setCurrentIndex(self.csv.reference_column_combo.findData('operator_lot_code'))
        self.csv.timestamp_column_combo.setCurrentIndex(self.csv.timestamp_column_combo.findData('captured_at'))
        self.csv.load_metrics_button.click()  # Normal UI reload after changing the actual ID/time fields.
        self.wait(lambda: self.csv.tabular_load_thread is None and self.csv.tabular_load_result is not None)
        _require(self.csv.tabular_load_result.reference_column == 'operator_lot_code'
                 and self.csv.tabular_load_result.timestamp_column == 'captured_at')
        self.filters()
        self.phase = 'csv'
        self.csv.workbook_checkbox.click()
        html, xlsx = self.child / 'analysis.html', self.child / 'analysis.xlsx'
        self.choose_path(self.csv.dashboard_button.click, html)
        self.choose_path(self.csv.workbook_button.click, xlsx)
        _require(self.csv.workbook_checkbox.isChecked() and not self.csv.advanced_options_container.isVisible()
                 and self.csv.dashboard_path_field.isVisibleTo(self.csv) and self.csv.workbook_path_field.isVisibleTo(self.csv)
                 and self.csv.output_dashboard_file == str(html) and self.csv.output_workbook_file == str(xlsx))
        self.reveal(self.csv.workbook_path_field)
        self.take('output-summary', self.csv)
        existed = 'run_tabular_file_analytics' in vars(workers)
        original = workers.run_tabular_file_analytics
        entered = Event()
        def delegate(*args, **kwargs):
            entered.set()
            if not self.release.wait(5):
                raise TabularChecksFailure('tabular_phase_deadline')
            return original(*args, **kwargs)
        workers.run_tabular_file_analytics = delegate
        try:
            with self.notifications():
                started = time.monotonic()
                self.csv.start_button.click()
                worker = self.csv.analytics_thread
                _require(worker is not None)
                result_spy = QSignalSpy(worker.result_ready)
                request = worker.request
                self.wait(entered.is_set, 4)
                self.wait(lambda: self.csv.loading_dialog.isVisible() and time.monotonic() - started >= 1.05, 4)
                _require(self.app.activeModalWidget() is None and not self.csv.loading_dialog.isModal())
                self.take('csv-busy', self.csv)
                for sequence in ('Ctrl+2', 'Ctrl+1', 'Ctrl+3'):
                    self.key(self.window, sequence)
                    _require(self.window.csv_summary_dialog is self.csv and self.csv.analytics_thread is worker
                             and worker.isRunning() and worker.request is request and self.app.activeModalWidget() is None)
                self.choose_path(self.window._choose_database, databases[1])
                _require(Path(self.window.db_file).resolve() == databases[1].resolve() and self.window.csv_summary_dialog is self.csv
                         and worker.request is request and request.db_file == self.csv.db_file == ''
                         and request.input_file == str(source) and request.tabular_load_result is self.csv.tabular_load_result)
                _require(request.tabular_column_filters[0].selected_values == ('East',)
                         and request.output_dashboard_file == str(html) and request.output_workbook_file == str(xlsx)
                         and [metric.field_name for metric in request.metric_selection] == ['value']
                         and request.reference_column == 'operator_lot_code' and request.timestamp_column == 'captured_at'
                         and not request.grouping_df)
                self.release.set()
                self.wait(lambda: self.csv.analytics_thread is None)
                _require(len(result_spy) == 1)
                result = result_spy[0][0]
        finally:
            self.release.set()
            try:
                if self.csv.analytics_thread is not None:
                    with self.notifications():
                        self.csv.cancel_analytics()
                        self.join(self.csv.analytics_thread)
            finally:
                if existed:
                    workers.run_tabular_file_analytics = original
                else:
                    del workers.run_tabular_file_analytics
        _require(result.row_count == 4 and result.metric_count == 1 and html.is_file() and xlsx.is_file())
        _require('<!doctype html>' in html.read_text().lower() and 'Value' in html.read_text())
        from openpyxl import load_workbook
        book = load_workbook(xlsx, read_only=True, data_only=True)
        try:
            rows = list(book['Table Data'].values)
            value_index = list(rows[0]).index('value')
            values = [row[value_index] for row in rows[1:]]
            identifiers = [row[list(rows[0]).index('operator_lot_code')] for row in rows[1:]]
            _require(identifiers == ['LOT-1', 'LOT-3', 'LOT-5', 'LOT-7'])
            dates = [str(row[list(rows[0]).index('captured_at')])[:10] for row in rows[1:]]
            _require(dates == ['2026-01-01', '2026-01-03', '2026-01-05', '2026-01-07'])
            metrics = list(book['Metrics'].values)
            summary = dict(zip(metrics[0], metrics[1]))
            _require(values == [10, 30, 50, 70] and all(summary[key] == value for key, value in
                     {'n': 4, 'mean': 40, 'min': 10, 'max': 70}.items()))
        finally:
            book.close()
        _require([_logical_sha256(path) for path in databases] == database_hashes)
        self.window._activate_workspace('home')
        self.window.csv_summary_action.trigger()
        _require(self.window.csv_summary_dialog is self.csv and self.csv.analytics_thread is None
                 and 'Rows analyzed: 4' in self.csv.last_result_row.summary.text())
        self.take('csv-resumed', self.csv)
        self.evidence['csv'] = {'source_rows': 8, 'rows': 4, 'values': values, 'identifiers': identifiers, 'dates': dates, 'metric_summary':
                               {key: summary[key] for key in ('n', 'mean', 'min', 'max')},
                               'same_owner': True, 'same_worker': True, 'same_request': True,
                               'database_independent': True, 'database_hashes': database_hashes,
                               'request': {'source': Path(request.input_file).name,
                                           'reference_column': request.reference_column, 'timestamp_column': request.timestamp_column,
                                           'metrics': [metric.field_name for metric in request.metric_selection],
                                           'filter_column': request.tabular_column_filters[0].column,
                                           'selected_values': list(request.tabular_column_filters[0].selected_values),
                                           'filter_expression': request.tabular_filter_expression,
                                           'grouping_count': len(request.grouping_df or ())},
                               'outputs': {p.suffix[1:]: {'path': p.relative_to(self.root).as_posix(), 'sha256': _sha(p)} for p in (html, xlsx)}}
        self.passed('csv_single_owner', 'csv_busy_resume', 'csv_db_independence', 'csv_outputs')

    def members(self, dialog, group, first, count, *, date=True):
        self.select(dialog.groups_list, group)
        self.idle(dialog)
        items = [dialog.group_members_list.item(i) for i in range(dialog.group_members_list.count())]
        ids = [item.data(self.Qt.ItemDataRole.UserRole) for item in items]
        _require(ids[:5] == first and len(ids) == count and count <= 1000)
        _require(dialog.identity_column == 'operator_lot_code' and dialog.datetime_column == ('captured_at' if date else None))
        for item in items:
            row_id, label = item.data(self.Qt.ItemDataRole.UserRole), item.text()
            _require(label.endswith(f'[Row {row_id}]'))
            if row_id in (1, 13):
                _require('Operator lot code: DUP-1212' in label)
            if row_id == 25:
                _require('Missing identifier' in label)
            if date and row_id in (1, 13, 25):
                expected = {1: '2026-01-01', 13: 'Missing date', 25: '2026-01-03'}[row_id]
                _require('Captured at: ' + expected in label)
            if not date:
                _require('Captured at:' not in label and 'Missing date' not in label)
        return ids

    def pairs(self):
        frame = self.csv.df_for_grouping
        rows = frame.iter_rows(as_dict=True) if hasattr(frame, 'iter_rows') else frame.to_dict('records')
        return sorted([[int(row['REPORT_ID']), str(row['GROUP'])] for row in rows])

    def grouping(self):
        import pandas as pd
        from PyQt6.QtWidgets import QInputDialog, QLineEdit, QDialogButtonBox
        from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_file
        from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
        self.phase = 'grouping'
        self.csv.clear_filter_button.click()
        source = self.child / 'grouping.csv'
        loaded = load_tabular_analytics_file(source, force_sqlite=True,
                                            reference_column='operator_lot_code', timestamp_column='captured_at')
        _require(loaded.row_count == 3000 and loaded.sqlite_store is not None)
        self.stores.append(Path(loaded.sqlite_store.path))
        self.csv.input_file, self.csv.input_files = str(source), (str(source),)
        self.csv._apply_tabular_load_result(loaded)
        self.csv.reference_column_combo.setCurrentIndex(self.csv.reference_column_combo.findData('operator_lot_code'))
        self.csv.timestamp_column_combo.setCurrentIndex(self.csv.timestamp_column_combo.findData('captured_at'))
        self.csv.set_df_for_grouping(pd.read_csv(self.child / 'saved-groups.csv', keep_default_na=False))
        self.csv.set_grouping_applied(True)
        original_pairs = self.pairs()
        oracle = self.oracle['grouping']
        observed, reads, read_errors = {}, [], []
        kind, store = type(loaded.sqlite_store), loaded.sqlite_store
        owned_stores = [store]
        original_read = kind.read_row_table
        def observe(instance, **kwargs):
            result = original_read(instance, **kwargs)
            if any(instance is known for known in owned_stores):
                try:
                    reads.append({'columns': list(kwargs.get('columns') or ()), 'limit': kwargs.get('limit'),
                                  'filter_columns': list(kwargs.get('filter_columns') or ()), 'keys': len(kwargs.get('selected_filter_keys') or ()), 'rows': len(result)})
                except BaseException as error:
                    read_errors.append(type(error).__name__)
            return result
        kind.read_row_table = observe
        def edit(action):
            self.modal(self.csv.edit_groups_button.click, TabularAnalyticsGroupingDialog, action)
        def initial(dialog):
            _require(dialog._group_counts() == {f'G-{i:03d}': 250 for i in range(12)})
            self.members(dialog, 'G-000', oracle['g0'], 250)
            self.reveal(dialog.group_members_list)
            self.take('grouping-members', dialog)
            dialog.cancel_button.click()
        def apply(dialog):
            self.select(dialog.available_columns_list, 'operator_lot_code')
            self.key(dialog.column_search, 'Ctrl+E')
            self.select(dialog.available_columns_list, 'captured_at')
            self.key(dialog.column_search, 'Ctrl+E')
            _require(dialog.selector_columns == ['operator_lot_code', 'captured_at'])
            self.select(dialog.selected_columns_list, 'captured_at')
            self.key(dialog.selected_column_search, 'Ctrl+Shift+E')
            _require(dialog.selector_columns == ['operator_lot_code'])
            self.idle(dialog)
            _require(dialog.selector_list.count() <= 1000 and dialog.next_page_button.isEnabled())
            dialog.next_page_button.click()
            self.idle(dialog)
            _require(dialog._selector_page_offset == 1000 and dialog.selector_list.count() <= 1000)
            dialog.previous_page_button.click()
            self.idle(dialog)
            _require(dialog._selector_page_offset == 0)
            self.members(dialog, 'G-001', oracle['g1'], 250)
            self.members(dialog, 'G-000', oracle['g0'], 250)
            dialog.selector_search.setText('DUP-1212')
            self.key(dialog.selector_search, 'Return')
            _require(dialog.isVisible())
            self.select(dialog.group_members_list, 13)
            self.key(dialog.group_members_list, 'Ctrl+D')
            observed['removed'] = self.members(dialog, 'G-000', oracle['removed_g0'], 249)[:5]
            self.select(dialog.groups_list, 'POPULATION')
            _require('contains 1 unassigned' in dialog.group_members_list.item(0).text())
            records = dialog._sqlite_assignment_store.assignments(tuple(dialog._sqlite_assignment_operations), default_group=dialog.default_group)
            unassigned = sorted(set(range(1, 3001)) - {record.row_id for record in records})
            _require(unassigned == [13] and len(records) == 2999 and all(1 <= record.row_id <= 3000 for record in records))
            observed['unassigned'] = unassigned
            self.select(dialog.groups_list, 'G-000')
            self.select(dialog.selector_list, ('DUP-1212',))
            def name(prompt):
                edit = prompt.findChild(QLineEdit)
                edit.setText('G-001')
                prompt.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
            self.modal(dialog.create_group_button.click, QInputDialog, name)
            observed['assigned_g1'] = self.members(dialog, 'G-001', oracle['assigned_g1'], 252)[:5]
            observed['assigned_g0'] = self.members(dialog, 'G-000', oracle['assigned_g0'], 248)[:5]
            observed['counts'] = dialog._group_counts()
            _require(observed['counts'] == {f'G-{i:03d}': 248 if i == 0 else 252 if i == 1 else 250 for i in range(12)})
            self.key(dialog, 'Ctrl+S')
        def cancel(dialog):
            self.members(dialog, 'G-001', oracle['assigned_g1'], 252)
            self.select(dialog.group_members_list, 13)
            self.key(dialog.group_members_list, 'R')
            self.yes(dialog.cancel_button.click)
        def reset(dialog):
            self.members(dialog, 'G-000', oracle['assigned_g0'], 248)
            self.select(dialog.group_members_list, 25)
            dialog.remove_from_group_button.click()
            self.yes(dialog.dont_use_grouping_button.click)
            self.members(dialog, 'G-000', oracle['assigned_g0'], 248)
            self.members(dialog, 'G-001', oracle['assigned_g1'], 252)
            dialog.cancel_button.click()
        def no_date(dialog):
            self.members(dialog, 'G-000', oracle['g0'], 250, date=False)
            dialog.cancel_button.click()
        try:
            edit(initial)
            _require(self.pairs() == original_pairs)
            edit(apply)
            _require(self.csv.analytics_thread is None and self.csv.tabular_load_thread is None)
            applied = self.pairs()
            _require(len(applied) == 3000 and _pairs_sha(applied) == oracle['applied_assignment_sha256'])
            request = self.csv._build_analytics_request()
            _require(_pairs_sha(sorted([[row.report_id, row.group] for row in request.grouping_df])) == oracle['applied_assignment_sha256'])
            edit(cancel)
            _require(self.pairs() == applied)
            edit(reset)
            _require(self.pairs() == applied)
            _require(store.count_rows() == 3000)
            self.csv.timestamp_column_combo.setCurrentIndex(self.csv.timestamp_column_combo.findData(''))
            no_time = load_tabular_analytics_file(source, force_sqlite=True, reference_column='operator_lot_code', timestamp_column=None)
            _require(no_time.sqlite_store is not None and no_time.timestamp_column is None)
            owned_stores.append(no_time.sqlite_store)
            self.stores.append(Path(no_time.sqlite_store.path))
            self.csv._apply_tabular_load_result(no_time)  # Separate explicit no-date SQLite fixture admission.
            self.csv.set_df_for_grouping(pd.read_csv(self.child / 'saved-groups.csv', keep_default_na=False))
            self.csv.set_grouping_applied(True)
            _require(self.csv._selected_tabular_column(self.csv.timestamp_column_combo) is None)
            edit(no_date)
            _require(self.pairs() == original_pairs and no_time.sqlite_store.count_rows() == 3000)
        finally:
            kind.read_row_table = original_read
        _require(reads and not read_errors and len(reads) <= 64 and all(
            0 < row['keys'] <= 252 and row['limit'] == 1000 and row['rows'] <= row['keys'] and row['filter_columns'] == ['source_row_number']
            and row['columns'] in (['source_row_number', 'operator_lot_code', 'captured_at'], ['source_row_number', 'operator_lot_code']) for row in reads))
        observed.update(source_rows=3000, applied_assignment_sha256=_pairs_sha(applied),
                        cancel_preserved=True, reset_preserved=True, no_date=True, member_reads=reads)
        self.evidence['grouping'] = observed
        self.passed('grouping_identity', 'grouping_apply_cancel_reset', 'bounded_reads')

    def join(self, worker):
        from PyQt6 import sip
        from PyQt6.QtCore import QDeadlineTimer
        from metroliza.app.windows_candidate_native_check import abort_unavailable_after_join_failure
        if worker is not None and not sip.isdeleted(worker):
            if not worker.wait(QDeadlineTimer(max(0, int(min(20, self.deadline-time.monotonic())*1000)), self.Qt.TimerType.PreciseTimer)):
                _RETAINED_WINDOWS.append(self.window)
                abort_unavailable_after_join_failure(self.window)
                raise TabularChecksFailure('tabular_worker_join_deadline')
        self.app.processEvents()

    def cleanup(self):
        from metroliza.app.windows_candidate_native_check import close_report_owner
        self.phase = 'cleanup'
        self.release.set()
        if self.csv is not None:
            with self.notifications():
                for attribute, cancel in (('tabular_load_thread', self.csv.cancel_tabular_load), ('analytics_thread', self.csv.cancel_analytics)):
                    worker = getattr(self.csv, attribute)
                    if worker is not None:
                        cancel()
                        self.join(worker)
                self.wait(lambda: self.csv.tabular_load_thread is None and self.csv.analytics_thread is None)
        if self.window is not None:
            try:
                close_report_owner(self.window, self.app)
            except BaseException:
                _RETAINED_WINDOWS.append(self.window)
                raise
        _require(self.app.activeModalWidget() is None and not any(path.exists() for path in self.stores), 'tabular_cleanup_failed')
        _require(not self.callback_errors, 'tabular_callback_failed')
        _require(all(_sha(self.fixtures / name) == sha for name, sha in FIXTURE_HASHES.items())
                 and all(_sha(self.child / name) == FIXTURE_HASHES[name] for name in ('analysis.csv', 'grouping.csv', 'saved-groups.csv')))
        self.evidence['cleanup'] = {'joined': True, 'stores_removed': True, 'closed': True,
                                    'source_hashes_unchanged': True, 'observer_errors': []}
        self.passed('cleanup')


def run_tabular_checks(scratch, fixtures, *, expected_dpr, capture):
    """Run only inside the existing double opt-in, using its retained QApplication."""
    observation = {'schema_version': SCHEMA_VERSION, 'status': 'failed', 'facets': {name: 'failed' for name in FACETS},
                   'error_codes': [], 'evidence': {'fixture_hashes': {}, 'csv': None, 'filter': None, 'grouping': None,
                   'captures': {}, 'cleanup': None, 'failure': None}}
    journey = None
    try:
        _require(all(os.environ.get(name) == '1' for name in ('METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION')), 'tabular_gate_missing')
        _require(callable(capture), 'tabular_capture_failed')
        _require(type(expected_dpr) in (float, int) and math.isfinite(expected_dpr) and expected_dpr in (1, 1.25, 1.5))
        scratch, fixtures = Path(scratch).resolve(), Path(fixtures).resolve()
        _require(scratch.is_dir() and fixtures.is_dir() and set(p.name for p in fixtures.iterdir()) == set(FIXTURE_HASHES), 'tabular_fixture_invalid')
        _require({name: _sha(fixtures / name) for name in FIXTURE_HASHES} == FIXTURE_HASHES, 'tabular_fixture_invalid')
        observation['evidence']['fixture_hashes'] = dict(FIXTURE_HASHES)
        journey = _Journey(scratch, fixtures, expected_dpr, capture, observation)
        journey.csv_journey()
        journey.grouping()
        _require(set(observation['evidence']['captures']) == set(CAPTURE_STATES), 'tabular_capture_failed')
        journey.passed('captures')
    except Exception as error:
        code = str(error) if isinstance(error, TabularChecksFailure) and str(error) in ERROR_CODES else 'unexpected_exception'
        observation['error_codes'].append(code)
        observation['evidence']['failure'] = {'phase': journey.phase if journey else 'admission', 'type': type(error).__name__,
                                             'callback_errors': journey.callback_errors[:8] if journey else []}
    finally:
        if journey is not None:
            try:
                journey.cleanup()
            except Exception as error:
                observation['error_codes'].append('tabular_cleanup_failed')
                if observation['evidence']['failure'] is None:
                    observation['evidence']['failure'] = {'phase': 'cleanup', 'type': type(error).__name__, 'callback_errors': journey.callback_errors[:8]}
    if not observation['error_codes'] and all(value == 'passed' for value in observation['facets'].values()):
        observation['status'] = 'passed'
    return observation
