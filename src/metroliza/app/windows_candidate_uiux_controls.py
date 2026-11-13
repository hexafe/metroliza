"""Inert controls journeys and strict actual-widget capture for the existing opt-in."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
from threading import Event
import time

FACETS = ('workspace_routes', 'launcher_single_owner', 'reports_tab_initial_ready',
          'reports_tab_review_result', 'reports_tab_busy', 'text_modifier_guards',
          'modal_shared_key_owner', 'reports_filter_geometry', 'parser_profiles_geometry',
          'active_child_capture', 'controls_cleanup')
ERROR_CODES = ('controls_gate_missing', 'controls_fixture_invalid', 'controls_application_missing',
               'controls_invariant_failed', 'controls_phase_deadline', 'controls_callback_failed',
               'controls_geometry_clipped', 'controls_worker_join_deadline', 'controls_cleanup_failed',
               'capture_name_invalid', 'capture_owner_invalid', 'capture_pixels_failed',
               'capture_state_failed', 'unexpected_exception')
CAPTURE_STATES = {
    'reports-saved-top': dict(rows=12, saved=12, failed=0, unknown=0, attention=0, viewport='top'),
    'reports-saved-bottom': dict(rows=12, saved=12, failed=0, unknown=0, attention=0, viewport='bottom'),
    'reports-partial-error': dict(rows=12, saved=11, failed=1, unknown=0, attention=1, viewport='top'),
    'reports-partial-cancel': dict(rows=12, saved=1, failed=0, unknown=11, attention=11, viewport='top'),
    'csv-busy': dict(worker_running=True, modal_blocker=False, source_rows=8, selected_rows=4),
    'csv-resumed': dict(completed=True, rows=4, formats=['html', 'xlsx']),
    'grouping-members': dict(source_rows=3000, ids=[1, 13, 25], date_field='captured_at'),
    'filter-scope': dict(column='line', selected=['East'], hidden_selected=1, rows=4),
    'output-summary': dict(rows=4, formats=['html', 'xlsx'], scope='Line=East'),
    'active-child-modal': dict(surface='csv-metrics', owner='csv-summary', selected_metrics=1,
                               parent_no_start=True, modal=True),
}
TAB_IDS = ('directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
           'review', 'search', 'status', 'parser', 'attention', 'select_ready', 'clear', 'table',
           'details_button', 'details', 'ocr', 'metadata', 'import', 'outcome_button', 'outcome',
           'modify', 'mapping', 'export')
TAB_CHAINS = {
    'initial': ('directory_path', 'directory', 'archive', 'database_path', 'metadata_mode',
                'search', 'status', 'parser', 'attention', 'table', 'details_button'),
    'ready': ('directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
              'review', 'search', 'status', 'parser', 'attention', 'table', 'details_button', 'modify', 'mapping', 'export'),
    'busy': ('directory_path', 'database_path', 'search', 'status', 'parser', 'attention', 'details_button'),
    'review': ('directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
               'review', 'search', 'status', 'parser', 'attention', 'select_ready', 'clear', 'table',
               'details_button', 'ocr', 'metadata', 'import', 'modify', 'mapping', 'export'),
    'result': ('directory_path', 'directory', 'archive', 'database_path', 'database', 'metadata_mode',
               'review', 'search', 'status', 'parser', 'attention', 'table', 'details_button',
               'outcome_button', 'outcome', 'modify', 'mapping', 'export'),
}


class ControlsChecksFailure(ValueError):
    """Closed, path-free observation code."""


def _require(condition, code='controls_invariant_failed'):
    if not condition:
        raise ControlsChecksFailure(code)


def _admit(expected_dpr):
    _require(all(os.environ.get(key) == '1' for key in ('METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION')), 'controls_gate_missing')
    _require(type(expected_dpr) in (int, float) and math.isfinite(expected_dpr) and expected_dpr in (1, 1.25, 1.5))
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    _require(app is not None, 'controls_application_missing')
    _require(app.primaryScreen().devicePixelRatio() == expected_dpr)
    return app


def _sha(path):
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024 * 1024, 'controls_fixture_invalid')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _control(identifier, widget, window, rect=None):
    from PyQt6.QtCore import QPoint
    bounds = widget.rect() if rect is None else rect
    current, inside = widget, widget.rect().contains(bounds)
    while current is not window and current.parentWidget() is not None:
        bounds = bounds.translated(current.mapToParent(QPoint()))
        current = current.parentWidget()
        inside = inside and current.rect().contains(bounds)
    return dict(id=identifier, bounds=[bounds.x(), bounds.y(), bounds.width(), bounds.height()],
                visible=widget.isVisibleTo(window), enabled=widget.isEnabled(),
                focusable=bool(widget.focusPolicy().value), in_window=window.rect().contains(bounds),
                in_viewport=bool(inside and current is window))


class CaptureSession:
    def __init__(self, scratch, expected_dpr):
        self.app = _admit(expected_dpr)
        self.root, self.dpr = Path(scratch).resolve(), expected_dpr
        _require(self.root.is_dir(), 'capture_owner_invalid')
        self._metadata, self._observations, self._errors = {}, {}, []

    @property
    def metadata(self):
        return json.loads(json.dumps(self._metadata))

    @property
    def observations(self):
        return json.loads(json.dumps(self._observations))

    def snapshot(self, *, require_complete=True):
        complete = (set(self._metadata) == set(self._observations) == set(CAPTURE_STATES)
                    and all(row['status'] == 'passed' for row in self._observations.values()) and not self._errors)
        if require_complete:
            _require(complete, 'capture_state_failed')
        return dict(status='passed' if complete else 'failed', metadata=self.metadata,
                    observations=self.observations, error_codes=list(self._errors))

    def __call__(self, name, widget, expected_state):
        from PyQt6.QtWidgets import QWidget
        try:
            _require(type(name) is str and name in CAPTURE_STATES and name not in self._observations
                     and type(expected_state) is dict
                     and json.dumps(expected_state, sort_keys=True) == json.dumps(CAPTURE_STATES[name], sort_keys=True), 'capture_name_invalid')
            _require(isinstance(widget, QWidget) and widget.isWindow() and widget.isVisible()
                     and widget.devicePixelRatioF() == self.dpr, 'capture_owner_invalid')
            owner = widget
            while owner is not None and not hasattr(owner, 'ui_preferences'):
                owner = owner.parentWidget()
            _require(owner is not None
                     and Path(owner.ui_preferences._settings.fileName()).resolve().is_relative_to(self.root), 'capture_owner_invalid')
            path, pixels = self.root / f'uiux-{name}.png', widget.grab()
            _require(not path.exists() and not path.is_symlink() and pixels.size() == widget.size() * self.dpr
                     and pixels.devicePixelRatio() == self.dpr and pixels.save(str(path), 'PNG'), 'capture_pixels_failed')
            _require(8 <= path.stat().st_size <= 8 * 1024 * 1024 and path.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
                     and all(64 <= value <= 8192 for value in (pixels.width(), pixels.height())), 'capture_pixels_failed')
            metadata = dict(path=path.name, sha256=_sha(path), width=pixels.width(), height=pixels.height(), dpr=self.dpr)
            self._metadata[name] = metadata
            row = dict(status='failed', expected_state=json.loads(json.dumps(expected_state)), observed_state=None,
                       window=dict(logical_rect=[0, 0, widget.width(), widget.height()],
                                   physical_size=[pixels.width(), pixels.height()], dpr=self.dpr), controls=[], error_codes=[])
            self._observations[name] = row
            state, controls, pinned = self._surface(name, widget)
            row.update(observed_state=state, controls=controls)
            _require(state == expected_state, 'capture_state_failed')
            _require(all(c['visible'] and c['in_window'] and c['in_viewport'] for c in controls if c['id'] in pinned), 'controls_geometry_clipped')
            row['status'] = 'passed'
            return dict(metadata)
        except Exception as error:
            code = str(error) if isinstance(error, ControlsChecksFailure) and str(error) in ERROR_CODES else 'capture_state_failed'
            if len(self._errors) < 16:
                self._errors.append(code)
            if type(name) is str and name in self._observations:
                self._observations[name]['error_codes'].append(code)
            raise ControlsChecksFailure(code) from error

    def _surface(self, name, window):
        if name.startswith('reports-'):
            planner = window.reports_workspace.report_planner
            rows, bar = planner.model.execution_rows, planner.table.verticalScrollBar()
            counts = Counter(row.status.value for row in rows)
            viewport = 'bottom' if name == 'reports-saved-bottom' else 'top'
            _require(bar.value() == (bar.maximum() if viewport == 'bottom' else bar.minimum()), 'capture_state_failed')
            state = dict(rows=len(rows), saved=counts['saved'], failed=counts['failed'], unknown=counts['unknown'],
                         attention=sum(row.needs_attention for row in rows), viewport=viewport)
            pairs = [('navigation', window.navigation_list), ('summary', planner.counts), ('table', planner.table), ('outcome', planner.outcome)]
            pinned = {'summary', 'table'}
        elif name == 'grouping-members':
            listing = window.group_members_list
            from PyQt6.QtCore import Qt
            ids = [listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)]
            state = dict(source_rows=window.sqlite_store.row_count, ids=ids, date_field=window.datetime_column)
            controls = [_control('apply', window.use_grouping_button, window), _control('cancel', window.cancel_button, window)]
            controls += [_control(f'member-row-{value}', listing.viewport(), window, listing.visualItemRect(listing.item(i))) for i, value in enumerate(ids)]
            return state, controls, {c['id'] for c in controls}
        elif name == 'filter-scope':
            selected = sorted(window.value_filters.get('line', set()))
            state = dict(column=window._current_filter_column(), selected=selected,
                         hidden_selected=int('1 hidden selected' in window.value_scope_label.text()),
                         rows=window._filtered_row_count(window._active_column_filters()))
            pairs = [('apply', window.apply_button), ('cancel', window.cancel_button), ('matching', window.matching_list), ('selection_summary', window.value_scope_label)]
            pinned = {'apply', 'cancel', 'selection_summary'}
        elif name == 'active-child-modal':
            parent = window.parentWidget()
            state = dict(surface='csv-metrics', owner='csv-summary', selected_metrics=len(window.selected_metrics()),
                         parent_no_start=parent.analytics_thread is None, modal=self.app.activeModalWidget() is window)
            _require(parent.source_kind == 'tabular_file', 'capture_state_failed')
            pairs = [('apply', window.apply_button), ('cancel', window.cancel_button), ('search', window.search_field), ('metrics', window.metrics_list)]
            pinned = {'apply', 'cancel', 'search'}
        else:
            rows = window._tabular_filtered_row_count()
            formats = ['html'] + (['xlsx'] if window.workbook_checkbox.isChecked() else [])
            if name == 'csv-busy':
                state = dict(worker_running=window.analytics_thread is not None and window.analytics_thread.isRunning(),
                             modal_blocker=self.app.activeModalWidget() is not None, source_rows=window.tabular_load_result.row_count, selected_rows=rows)
            elif name == 'csv-resumed':
                state = dict(completed=window.analytics_thread is None and 'Rows analyzed: 4' in window.last_result_row.summary.text(), rows=rows, formats=formats)
            else:
                filters = window.tabular_column_filters
                _require(len(filters) == 1 and filters[0].column == 'line' and filters[0].selected_values == ('East',), 'capture_state_failed')
                state = dict(rows=rows, formats=formats, scope='Line=East')
            pairs = [('start', window.start_button), ('close', window.close_button), ('metrics', window.choose_metrics_button),
                     ('dashboard_path', window.dashboard_path_field), ('workbook_path', window.workbook_path_field)]
            pinned = {'start', 'close'} | ({'dashboard_path', 'workbook_path'} if name == 'output-summary' else set())
        return state, [_control(key, control, window) for key, control in pairs], pinned


def make_capture(scratch, *, expected_dpr):
    return CaptureSession(scratch, expected_dpr)


class _Journey:
    def __init__(self, scratch, fixtures, dpr, capture, result):
        from PyQt6.QtCore import Qt, QSettings
        from metroliza.app.windows_candidate_uiux_tabular import _Journey as Delivery, FIXTURE_HASHES
        from metroliza.app.windows_candidate_uiux_reports import _stage
        from metroliza.app.ui_entrypoint import load_main_window_factory
        from metroliza.ui.ui_preferences import UiPreferences
        self.app, self.Qt, self.delivery = _admit(dpr), Qt, Delivery
        self.root, self.child, self.capture = scratch, scratch / 'controls-uiux', capture
        self.child.mkdir(mode=0o700)
        self.result, self.evidence = result, result['evidence']
        self.deadline, self.phase, self.csv = time.monotonic() + 45, 'admission', None
        self.loaded, self.filter_workers = None, []
        self.callback_errors, self.modals, self.release = [], [], Event()
        self.oracle = _stage(fixtures / 'uiux/reports', self.child / 'pdf')
        self.analysis = fixtures / 'uiux/tabular/analysis.csv'
        _require(_sha(self.analysis) == FIXTURE_HASHES['analysis.csv'], 'controls_fixture_invalid')
        self.source_hashes = {p.name: _sha(p) for p in (self.child / 'pdf').iterdir()}
        settings = QSettings(str(self.child / 'settings.ini'), QSettings.Format.IniFormat)
        self.window = load_main_window_factory()('UIUX controls', None, ui_preferences=UiPreferences(settings))
        self.window.show()
        self.workspace = self.window.launch_parsing_dialog()
        _require(not self.workspace._ocr_unavailable_reason(), 'controls_fixture_invalid')
        screen = self.app.primaryScreen()
        self.evidence['context'] = dict(execution='packaged' if getattr(sys, 'frozen', False) else 'source', qpa=self.app.platformName(),
                                       dpr=dpr, screen=[screen.geometry().width(), screen.geometry().height()],
                                       available_screen=[screen.availableGeometry().width(), screen.availableGeometry().height()])

    def wait(self, predicate, seconds=20):
        return self.delivery.wait(self, predicate, seconds)

    def reveal(self, target):
        return self.delivery.reveal(self, target)

    def activate(self, target):
        return self.delivery.activate(self, target)

    def key(self, target, sequence):
        from PyQt6.QtCore import QObject, QEvent
        owner = self
        class Observer(QObject):
            def eventFilter(self, watched, event):
                try:
                    if event.type() == QEvent.Type.Shortcut and event.isAmbiguous():
                        owner.callback_errors.append('controls_callback_failed')
                except BaseException:
                    owner.callback_errors.append('controls_callback_failed')
                return False
        observer = Observer(self.app)
        self.app.installEventFilter(observer)
        try:
            return self.delivery.key(self, target, sequence)
        finally:
            self.app.removeEventFilter(observer)
            observer.deleteLater()

    def modal(self, trigger, kind, action):
        return self.delivery.modal(self, trigger, kind, action)

    def passed(self, *facets):
        for facet in facets:
            self.result['facets'][facet] = 'passed'

    def tab(self, stage):
        from PyQt6.QtTest import QTest
        host, window = self.workspace, self.window
        planner = host.report_planner
        controls = (host.directory_text_label, host.directory_button, host.archive_button, host.database_text_label,
                    host.database_button, host.metadata_mode_combo, host.scan_button, planner.search, planner.status_filter,
                    planner.parser_filter, planner.attention_filter, planner.select_ready, planner.clear, planner.table,
                    planner.details_button, planner.details, planner.ocr_button, planner.metadata_button, host.parse_button,
                    planner.outcome_button, planner.outcome, window.modifydb_button, window.map_characteristics_button, window.export_button)
        busy = stage == 'busy'
        _require(host.scan_button.isEnabled() == (stage not in ('initial', 'busy'))
                 and host.parse_button.isEnabled() == (stage == 'review')
                 and host.database_button.isEnabled() == (stage not in ('initial', 'busy')))
        if busy:
            _require(host.preflight_thread is not None and host.preflight_thread.isRunning()
                     and not host.directory_button.isEnabled() and not host.archive_button.isEnabled())
        navigation = window.navigation_list if window.navigation_list.isVisible() else window.navigation_combo
        self.activate(navigation)
        expected = TAB_CHAINS[stage]
        hidden = {'details'} | ({'outcome', 'outcome_button'} if stage != 'result' else set())
        for name, control in zip(TAB_IDS, controls, strict=True):
            _require(control.isVisibleTo(window) == (name not in hidden)
                     and control.isEnabled() == (name in expected or name in hidden))
        lookup = dict(zip(TAB_IDS, controls, strict=True))
        active = [(name, lookup[name]) for name in expected]
        for _, control in active:
            QTest.keyClick(self.app.focusWidget(), self.Qt.Key.Key_Tab)
            _require(self.app.focusWidget() is control)
        previous = [('navigation', navigation)] + active[:-1]
        for _, control in reversed(previous):
            QTest.keyClick(self.app.focusWidget(), self.Qt.Key.Key_Backtab)
            _require(self.app.focusWidget() is control)
        return dict(forward=[name for name, _ in active], reverse=[name for name, _ in reversed(previous)],
                    controls=[dict(id=name, visible=control.isVisibleTo(window), enabled=control.isEnabled())
                              for name, control in zip(TAB_IDS, controls, strict=True)], worker_running=busy)

    def reports(self):
        from unittest.mock import patch
        from metroliza.parsing.preflight import ParsePreflightService
        from metroliza.app.windows_candidate_import_sync import click_import, wait_import_started, wait_import_finished
        from metroliza.app.windows_candidate_uiux_reports import _snapshot
        self.phase, observed = 'reports', {}
        observed['initial'] = self.tab('initial')
        database = self.child / 'controls.sqlite'
        _require(self.window.set_directory(str(self.child / 'pdf')) and self.window.set_db_file(str(database)))
        observed['ready'] = self.tab('ready')
        original, entered = ParsePreflightService.scan_source, Event()
        def delegate(service, **kwargs):
            entered.set()
            if not self.release.wait(5):
                raise ControlsChecksFailure('controls_phase_deadline')
            return original(service, **kwargs)
        with patch.object(ParsePreflightService, 'scan_source', delegate):
            try:
                self.workspace.scan_button.click()
                self.wait(entered.is_set, 4)
                observed['busy'] = self.tab('busy')
            finally:
                self.release.set()
            self.wait(lambda: self.workspace.preflight_thread is None and not self.workspace._metadata_threads and not self.workspace._after_metadata_idle)
        _require(self.workspace.report_planner.model.selected_count == 12)
        observed['review'] = self.tab('review')
        planner = self.workspace.report_planner
        planner.clear.click()
        planner.table.setCurrentIndex(planner.proxy.index(0, 0))
        self.key(planner.table, 'Space')
        _require(planner.model.selected_ids == ('REF001_0001.pdf',))
        operation = click_import(self.workspace)
        wait_import_started(self.app, operation, seconds=max(0, self.deadline - 20 - time.monotonic()))
        imported = wait_import_finished(self.app, operation, seconds=max(0, self.deadline - 20 - time.monotonic()))
        self.wait(lambda: self.workspace.parse_thread is None)
        _require(imported.imported_files == 1 and self.workspace.import_succeeded)
        counts, digests = _snapshot(database, self.oracle, {'REF001_0001.pdf'})
        observed['result'] = self.tab('result')
        observed['import'] = dict(name='REF001_0001.pdf', reports=counts['parsed_reports'], measurements=counts['report_measurements'],
                                  measurements_sha256=digests['REF001_0001.pdf'])
        self.evidence['report_tab'] = observed
        self.passed('reports_tab_initial_ready', 'reports_tab_review_result', 'reports_tab_busy')

    def routes(self):
        self.phase, pages = 'routes', []
        owners = dict.fromkeys(('csv', 'industrial', 'realtime', 'profiles'), False)
        for index, page in enumerate(('home', 'reports', 'csv_summary', 'industrial_data', 'realtime_monitor'), 1):
            self.key(self.window, f'Ctrl+{index}')
            _require(self.window.navigation_combo.currentData() == page)
            pages.append(page)
            attribute = {'csv_summary': 'csv_summary_dialog', 'industrial_data': 'industrial_data_dialog', 'realtime_monitor': 'realtime_monitoring_dialog'}.get(page)
            if attribute:
                owner = getattr(self.window, attribute)
                _require(owner is not None and owner.isVisible())
                self.key(self.window, f'Ctrl+{index}')
                _require(getattr(self.window, attribute) is owner)
                owners[{'csv_summary': 'csv', 'industrial_data': 'industrial', 'realtime_monitor': 'realtime'}[page]] = True
        self.csv = self.window.csv_summary_dialog
        self.evidence['routes'] = dict(pages=pages, same_csv=True)
        self.evidence['owners'] = owners
        self.passed('workspace_routes')

    def geometry(self, window, size, tabs, pinned, body, wrapped, scroll):
        from PyQt6.QtWidgets import QScrollArea, QAbstractButton
        from PyQt6.QtCore import QRect
        window.resize(*size)
        self.app.processEvents()
        _require([window.width(), window.height()] == size, 'controls_geometry_clipped')
        records = []
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            self.app.processEvents()
            area = scroll(index) if scroll else tabs.currentWidget().findChild(QScrollArea)
            before = area.verticalScrollBar().value()
            for _ in range(4):
                self.key(area, 'PgDown')
            pinned_records = [_control(name, getattr(window, name), window) for name in pinned(index)]
            _require(all(row['visible'] and row['in_window'] and row['in_viewport'] for row in pinned_records), 'controls_geometry_clipped')
            _require(all(getattr(window, name).height() >= 36 for name in pinned(index)
                         if isinstance(getattr(window, name), QAbstractButton)), 'controls_geometry_clipped')
            labels = [dict(id=name, height=getattr(window, name).height(), required=max(0, getattr(window, name).heightForWidth(getattr(window, name).width()))) for name in wrapped(index)]
            _require(all(row['height'] >= row['required'] for row in labels) and area.horizontalScrollBar().maximum() == 0, 'controls_geometry_clipped')
            bar = area.verticalScrollBar()
            body_records = [_control(name, getattr(window, name), window) for name in body(index)]
            _require(all(not QRect(*first['bounds']).intersects(QRect(*second['bounds']))
                         for i, first in enumerate(body_records) for second in body_records[i + 1:]), 'controls_geometry_clipped')
            records.append(dict(index=index, pinned=pinned_records,
                                body=body_records,
                                vertical=dict(minimum=bar.minimum(), maximum=bar.maximum(), before=before, after=bar.value()),
                                horizontal_max=area.horizontalScrollBar().maximum(), wrapped=labels))
        return dict(size=size, tabs=records)

    def dialogs(self):
        self.phase = 'dialogs'
        self.window._activate_workspace('reports')
        self.activate(self.window.export_button)
        self.window.export_button.click()
        export = self.window.export_dialog
        _require(export is not None and export.db_file == self.workspace.db_file)
        export.filter_button.click()
        editor = export.filter_window
        if editor._value_loader is not None:
            self.filter_workers.append(editor._value_loader)
        self.wait(lambda: not editor._values_loading and editor._value_loader is None)
        reports = self.geometry(editor, [720, 480], editor.filter_tabs,
                                lambda _: ('apply_button', 'cancel_button', 'reset_button', 'select_today_button', 'select_beginning_button', 'has_nok_button'),
                                lambda index: tuple(field for _, search, listing in editor.FILTER_SECTIONS[index][1] for field in (search, listing) if field),
                                lambda _: ('draft_status_label', 'filter_summary_label'), None)
        editor.cancel_button.click()
        export.close()
        self.key(self.window, 'Ctrl+Shift+F')
        profiles = self.window.parser_plugin_wizard_dialog
        self.window.parser_profiles_action.trigger()
        _require(self.window.parser_plugin_wizard_dialog is profiles and profiles.isVisible())
        profiles_result = self.geometry(profiles, [620, 560], profiles.task_tabs,
            lambda i: ('close_button', 'manage_status_label', 'refresh_button') if i == 0 else ('close_button', 'stage_label', 'validation_status_label', 'next_action_label', 'result_label', 'next_button'),
            lambda i: ('profile_list',) if i == 0 else ('plugin_id_edit', 'display_name_edit', 'source_format_combo', 'create_button'),
            lambda i: ('manage_status_label',) if i == 0 else ('next_action_label', 'result_label'),
            lambda i: profiles.add_scroll_area if i else profiles.profile_list)
        profiles.close_button.click()
        self.evidence['owners']['profiles'] = True
        self.evidence['compact_dialogs'] = dict(reports_filter=reports, parser_profiles=profiles_result)
        self.passed('reports_filter_geometry', 'parser_profiles_geometry', 'launcher_single_owner')

    def keys(self):
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtGui import QKeyEvent, QInputMethodEvent
        from PyQt6.QtTest import QTest, QSignalSpy
        from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_file
        from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog
        from metroliza.ui.industrial_analytics_dialog import MetricSelectionDialog
        self.phase = 'keys'
        loaded = load_tabular_analytics_file(self.analysis, force_sqlite=True, reference_column='operator_lot_code', timestamp_column='captured_at')
        self.loaded = loaded
        self.csv.input_file, self.csv.input_files = str(self.analysis), (str(self.analysis),)
        self.csv._apply_tabular_load_result(loaded)
        self.csv.output_dashboard_file = str(self.child / 'unused.html')  # Owned path admission; P2 proves real picker controls.
        self.csv._sync_ui_state()
        editing, columns = {}, [[]]
        def group(dialog):
            field = dialog.column_search
            field.setText('er')
            self.key(field, 'Ctrl+A')
            editing['select_all'] = field.selectedText()
            for sequence, name in [('Ctrl+C', 'after_copy'), ('Ctrl+X', 'after_cut'), ('Ctrl+V', 'after_paste'), ('Ctrl+Z', 'after_undo_paste'), ('Ctrl+Z', 'after_undo_cut')]:
                self.key(field, sequence)
                editing[name] = field.text()
            field.clear()
            QTest.keyClicks(field, 'er')
            editing['literal'] = field.text()
            _require(not dialog.selector_columns)
            field.clear()
            listing = dialog.available_columns_list
            item = next(listing.item(i) for i in range(listing.count()) if listing.item(i).data(self.Qt.ItemDataRole.UserRole) == 'line')
            listing.setCurrentItem(item)
            self.activate(listing)
            for modifiers in (self.Qt.KeyboardModifier.ShiftModifier, self.Qt.KeyboardModifier.AltModifier, self.Qt.KeyboardModifier.ControlModifier | self.Qt.KeyboardModifier.AltModifier):
                QCoreApplication.sendEvent(listing, QKeyEvent(QEvent.Type.KeyPress, self.Qt.Key.Key_E, modifiers, 'e'))
                _require(not dialog.selector_columns)
            QCoreApplication.sendEvent(listing, QKeyEvent(QEvent.Type.KeyPress, self.Qt.Key.Key_E, self.Qt.KeyboardModifier.NoModifier, 'e', True))
            _require(not dialog.selector_columns)
            QCoreApplication.sendEvent(listing, QInputMethodEvent('e', []))
            _require(not dialog.selector_columns)
            for target, sequence in ((listing, 'Ctrl+E'), (dialog.selected_columns_list, 'R'), (listing, 'E'), (dialog.selected_columns_list, 'Ctrl+Shift+E')):
                if target is listing:
                    listing.setCurrentItem(next(listing.item(i) for i in range(listing.count()) if listing.item(i).data(self.Qt.ItemDataRole.UserRole) == 'line'))
                self.key(target, sequence)
                columns.append(list(dialog.selector_columns))
            dialog.cancel_button.click()
        self.activate(self.csv.edit_groups_button)
        self.modal(self.csv.edit_groups_button.click, TabularAnalyticsGroupingDialog, group)
        _require(editing == dict(select_all='er', after_copy='er', after_cut='', after_paste='er', after_undo_paste='', after_undo_cut='er', literal='er')
                 and columns == [[], ['line'], [], ['line'], []] and self.csv.df_for_grouping is None and not self.csv.grouping_applied)
        self.evidence['text_guards'] = dict(editing=editing, columns=columns, modifier_unchanged=True, repeat_unchanged=True, composition_unchanged=True, parent_unchanged=True)
        self.passed('text_modifier_guards')
        starts, closes = QSignalSpy(self.csv.start_button.clicked), QSignalSpy(self.csv.close_button.clicked)
        outcomes = []
        for sequence in ('Ctrl+S', 'Ctrl+W'):
            _require(self.csv.start_button.isEnabled() and self.csv.close_button.isEnabled())
            self.activate(self.csv.choose_metrics_button)
            def child(dialog):
                if sequence == 'Ctrl+S':
                    metadata = self.capture('active-child-modal', dialog, dict(CAPTURE_STATES['active-child-modal']))
                    path = self.root / 'uiux-active-child-modal.png'
                    size = dialog.size() * self.evidence['context']['dpr']
                    _require(type(metadata) is dict and set(metadata) == {'path', 'sha256', 'width', 'height', 'dpr'}
                             and metadata['path'] == path.name and metadata['sha256'] == _sha(path)
                             and all(type(metadata[key]) is int for key in ('width', 'height'))
                             and [metadata['width'], metadata['height']] == [size.width(), size.height()]
                             and type(metadata['dpr']) in (int, float) and metadata['dpr'] == self.evidence['context']['dpr'], 'capture_pixels_failed')
                    self.evidence['captures']['active-child-modal'] = metadata
                self.key(dialog.search_field, sequence)
                _require(not dialog.isVisible())
                outcomes.append('accepted' if dialog.result() == dialog.DialogCode.Accepted else 'rejected')
            self.modal(self.csv.choose_metrics_button.click, MetricSelectionDialog, child)
            self.wait(lambda: self.app.activeWindow() is self.csv and self.app.activeModalWidget() is None
                      and self.app.focusWidget() is not None and self.app.focusWidget().window() is self.csv)
            _require(len(starts) == len(closes) == 0 and self.csv.analytics_thread is None and self.csv.isVisible())
        selected = [metric.field_name for metric in self.csv._selected_metrics()]
        _require(outcomes == ['accepted', 'rejected'] and selected == ['value'] and not (self.child / 'unused.html').exists())
        self.evidence['modal_keys'] = dict(parent_enabled_before=True, save=outcomes[0], close=outcomes[1], parent_starts=0, parent_closes=0, return_focus=True, selected_metrics=selected)
        self.passed('modal_shared_key_owner', 'active_child_capture')

    def cleanup(self):
        from metroliza.app.windows_candidate_native_check import close_report_owner
        from metroliza.app.windows_candidate_uiux_tabular import FIXTURE_HASHES
        from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result
        self.phase = 'cleanup'
        self.release.set()
        if self.csv is not None:
            for name, cancel in (('analytics_thread', self.csv.cancel_analytics), ('tabular_load_thread', self.csv.cancel_tabular_load)):
                worker = getattr(self.csv, name)
                if worker is not None:
                    cancel()
                    self.delivery.join(self, worker)
        owners = (self.window.industrial_data_dialog, self.window.realtime_monitoring_dialog,
                  self.window.parser_plugin_wizard_dialog)
        workers = [getattr(owner, name, None) for owner in owners if owner is not None
                   for name in ('_oznak_status_thread', '_analytics_load_thread', 'link_refresh_thread',
                                'poll_thread', 'dashboard_thread', '_validation_thread')]
        for owner in owners:
            if owner is not None:
                owner.close()
        for worker in workers + self.filter_workers:
            self.delivery.join(self, worker)
        self.wait(lambda: all(owner is None or not owner.isVisible() for owner in owners))
        close_report_owner(self.window, self.app)
        _require(not self.window.isVisible() and self.app.activeModalWidget() is None, 'controls_cleanup_failed')
        store = Path(self.loaded.sqlite_store.path) if self.loaded is not None else None
        cleanup_tabular_load_result(self.loaded)
        _require(store is None or not store.exists(), 'controls_cleanup_failed')
        _require({p.name: _sha(p) for p in (self.child / 'pdf').iterdir()} == self.source_hashes
                 and _sha(self.analysis) == FIXTURE_HASHES['analysis.csv'], 'controls_cleanup_failed')
        shutil.rmtree(self.child)
        _require(not self.child.exists() and not self.callback_errors, 'controls_cleanup_failed')
        self.evidence['cleanup'] = dict(joined=True, closed=True, temporary_data_removed=True, sources_unchanged=True, observer_errors=[])
        self.passed('controls_cleanup')


def run_controls_checks(scratch, fixtures, *, expected_dpr, capture):
    evidence = dict.fromkeys(('context', 'routes', 'owners', 'report_tab', 'text_guards', 'modal_keys', 'compact_dialogs', 'cleanup', 'failure'))
    evidence['captures'] = {}
    result = dict(schema_version=1, status='failed', facets=dict.fromkeys(FACETS, 'failed'), error_codes=[], evidence=evidence)
    journey = None
    try:
        _admit(expected_dpr)
        _require(callable(capture))
        scratch, fixtures = Path(scratch).resolve(), Path(fixtures).resolve()
        _require(scratch.is_dir() and fixtures.is_dir(), 'controls_fixture_invalid')
        journey = _Journey(scratch, fixtures, expected_dpr, capture, result)
        journey.reports()
        journey.routes()
        journey.dialogs()
        journey.keys()
    except Exception as error:
        code = str(error) if isinstance(error, ControlsChecksFailure) and str(error) in ERROR_CODES else 'unexpected_exception'
        result['error_codes'].append(code)
        evidence['failure'] = dict(phase=journey.phase if journey else 'admission', code=code,
                                   callback_errors=['controls_callback_failed'] * min(8, len(journey.callback_errors) if journey else 0))
    finally:
        if journey is not None:
            try:
                journey.cleanup()
            except Exception:
                result['error_codes'].append('controls_cleanup_failed')
                if evidence['failure'] is None:
                    evidence['failure'] = dict(phase='cleanup', code='controls_cleanup_failed',
                                               callback_errors=['controls_callback_failed'] * min(8, len(journey.callback_errors)))
    if not result['error_codes'] and all(value == 'passed' for value in result['facets'].values()):
        result['status'] = 'passed'
    _require(len(json.dumps(result).encode()) <= 48 * 1024)
    return result
