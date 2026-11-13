"""Inert, double-opt-in Reports acceptance through real UI workers and SQL."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import asdict
import hashlib
from importlib import import_module
import json
import math
import os
from pathlib import Path
import stat
import sys
from threading import Event
import time
from unittest.mock import patch
import zipfile

SCHEMA_VERSION = 1
FACETS = ('reports_twelve_import', 'reports_duplicate_rereview', 'reports_database_switch',
          'reports_partial_persistence_failure', 'reports_cancel_after_first_acceptance',
          'reports_historical_identity_readonly', 'reports_summary_layout',
          'reports_source_preservation', 'reports_captures', 'reports_cleanup')
ERROR_CODES = ('reports_gate_missing', 'reports_fixture_invalid', 'reports_application_missing',
               'reports_invariant_failed', 'reports_phase_deadline', 'reports_callback_failed',
               'reports_capture_failed', 'reports_summary_clipped',
               'reports_worker_join_deadline', 'reports_cleanup_failed', 'unexpected_exception')
FIXTURE_HASHES = {'reports-12.zip': '99f2a0af7269e52e82ac60a784e29aa82153a37b72357dc3844019d487c22041',
                  'oracles.json': '2ebad1ab90578f926f608e40652c516f36aaa5c55de918228ffd0b735551e1d4'}
CAPTURE_STATES = {
    'reports-saved-top': {'rows': 12, 'saved': 12, 'failed': 0, 'unknown': 0, 'attention': 0, 'viewport': 'top'},
    'reports-saved-bottom': {'rows': 12, 'saved': 12, 'failed': 0, 'unknown': 0, 'attention': 0, 'viewport': 'bottom'},
    'reports-partial-error': {'rows': 12, 'saved': 11, 'failed': 1, 'unknown': 0, 'attention': 1, 'viewport': 'top'},
    'reports-partial-cancel': {'rows': 12, 'saved': 1, 'failed': 0, 'unknown': 11, 'attention': 11, 'viewport': 'top'},
}
CASE_KEYS = ('review_counts', 'batch_counts', 'row_facts', 'receipt_states', 'database_counts',
             'numeric_digests', 'rereview_counts', 'context', 'preservation')
CONTEXT_KEYS = ('same_owner', 'same_result', 'approval_invalidated', 'worker_running_at_cancel',
                'first_accepted', 'cancel_clicked', 'cancel_flag', 'released', 'terminal', 'barrier_expired')
_RETAINED_WINDOWS: list[object] = []


class ReportsChecksFailure(ValueError):
    """Only closed, path-free codes enter the observation."""


def _require(condition, code='reports_invariant_failed'):
    if not condition:
        raise ReportsChecksFailure(code)


def _sha(path, maximum=128 * 1024):
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum,
             'reports_fixture_invalid')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage(fixtures, destination):
    _require(fixtures.is_dir() and not fixtures.is_symlink()
             and {p.name for p in fixtures.iterdir()} == set(FIXTURE_HASHES), 'reports_fixture_invalid')
    _require({n: _sha(fixtures / n) for n in FIXTURE_HASHES} == FIXTURE_HASHES, 'reports_fixture_invalid')
    oracle = json.loads((fixtures / 'oracles.json').read_text())
    expected_names = [f'REF{i:03d}_{i:04d}.pdf' for i in range(1, 13)]
    members = oracle['members']
    _require(oracle['schema_version'] == 1 and [m['name'] for m in members] == expected_names
             and oracle['archive_sha256'] == FIXTURE_HASHES['reports-12.zip'], 'reports_fixture_invalid')
    with zipfile.ZipFile(fixtures / 'reports-12.zip') as archive:
        items = archive.infolist()
        _require([m.filename for m in items] == expected_names and len(items) == 12
                 and sum(m.file_size for m in items) <= 256 * 1024, 'reports_fixture_invalid')
        payloads = []
        for item, expected in zip(items, members, strict=True):
            _require(not item.is_dir() and item.compress_type == zipfile.ZIP_STORED
                     and item.flag_bits & 1 == 0 and stat.S_ISREG(item.external_attr >> 16)
                     and 0 < item.file_size == expected['size'] <= 64 * 1024, 'reports_fixture_invalid')
            data = archive.read(item)
            _require(len(data) == expected['size'] and hashlib.sha256(data).hexdigest() == expected['sha256']
                     and oracle['expected']['reports'][expected['sha256']]['name'] == item.filename,
                     'reports_fixture_invalid')
            payloads.append((item.filename, data))
    destination.mkdir(mode=0o700)
    for name, data in payloads:
        with (destination / name).open('xb') as stream:
            stream.write(data)
    return oracle


def _snapshot(database, oracle, saved):
    from metroliza.reports.db import sqlite_readonly_connection_scope
    reports, counts = {}, {}
    with sqlite_readonly_connection_scope(str(database), timeout_s=0.1) as connection:
        with closing(connection.cursor()) as cursor:
            for table in ('parsed_reports', 'report_measurements', 'report_metadata'):
                counts[table] = cursor.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            rows = cursor.execute('''SELECT pr.id,sf.sha256,sfl.file_name,pr.measurement_count,pr.has_nok,
                rm.reference,rm.report_date,rm.sample_number,rm.sample_number_kind
                FROM parsed_reports pr JOIN source_files sf ON sf.id=pr.source_file_id
                JOIN source_file_locations sfl ON sfl.source_file_id=sf.id AND sfl.is_active=1
                JOIN report_metadata rm ON rm.report_id=pr.id ORDER BY sf.sha256''').fetchall()
            _require(len(rows) <= 12)
            for report_id, sha, name, declared, nok, *metadata in rows:
                values = cursor.execute('SELECT ' + ','.join(oracle['measurement_fields'])
                                        + ' FROM report_measurements WHERE report_id=? ORDER BY row_order,id',
                                        (report_id,)).fetchall()
                _require(sha not in reports and len(values) == 144)
                reports[sha] = dict(name=name, declared=declared, actual=len(values), has_nok=nok,
                                    metadata=metadata, measurements_sha256=hashlib.sha256(json.dumps(
                                        values, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest())
    expected = {sha: value for sha, value in oracle['expected']['reports'].items() if value['name'] in saved}
    _require(reports == expected and counts == dict(parsed_reports=len(saved),
             report_measurements=144 * len(saved), report_metadata=len(saved)))
    return counts, {value['name']: value['measurements_sha256'] for value in reports.values()}


def _summary_snapshot(planner):
    label, table = planner.counts, planner.table
    parent = label.parentWidget()
    position, table_position = label.mapTo(parent, label.rect().topLeft()), table.mapTo(parent, table.rect().topLeft())
    rect = label.geometry()
    return {'width': label.width(), 'height': label.height(), 'hfw': label.heightForWidth(label.width()),
            'minimum_hint': label.minimumSizeHint().height(), 'word_wrap': label.wordWrap(),
            'contained': parent.rect().contains(rect),
            'overlap': position.y() + label.height() > table_position.y(),
            'visible': label.isVisibleTo(planner),
            'window_size': [label.window().width(), label.window().height()]}


def _check_summary(facts):
    _require(facts['visible'] and facts['contained'] and facts['word_wrap'] and not facts['overlap']
             and facts['height'] >= facts['hfw'], 'reports_summary_clipped')


class _Journey:
    def __init__(self, scratch, fixtures, expected_dpr, capture, observation):
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance()
        _require(self.app is not None, 'reports_application_missing')
        screen = self.app.primaryScreen()
        _require(screen is not None and screen.devicePixelRatio() == expected_dpr)
        self.root, self.child, self.fixtures = scratch, scratch / 'reports-uiux', fixtures
        self.child.mkdir(mode=0o700)
        self.result, self.evidence, self.capture, self.dpr = observation, observation['evidence'], capture, expected_dpr
        self.oracle = _stage(fixtures, self.child / 'pdf')
        self.names = [member['name'] for member in self.oracle['members']]
        self.evidence['fixture_hashes'] = dict(FIXTURE_HASHES)
        self.evidence['context'] = {'execution': 'packaged' if getattr(sys, 'frozen', False) else 'source',
                                    'platform': self.app.platformName(), 'dpr': expected_dpr,
                                    'screen': [screen.geometry().width(), screen.geometry().height()],
                                    'available_screen': [screen.availableGeometry().width(), screen.availableGeometry().height()]}
        self.deadline, self.phase, self.window, self.workspace = time.monotonic() + 180, 'admission', None, None
        self.case_deadline = self.deadline
        self.release, self.callback_errors, self.close_failed = Event(), [], False

    def passed(self, *names):
        for name in names:
            self.result['facets']['reports_' + name] = 'passed'

    def wait(self, predicate, seconds=20):
        end = min(self.deadline, self.case_deadline, time.monotonic() + seconds)
        while not predicate() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        _require(bool(predicate()), 'reports_phase_deadline')
        _require(not self.callback_errors, 'reports_callback_failed')

    def remaining(self, seconds):
        remaining = min(seconds, self.deadline - time.monotonic(), self.case_deadline - time.monotonic())
        _require(remaining > 0, 'reports_phase_deadline')
        return remaining

    def choose(self, database):
        from PyQt6.QtWidgets import QFileDialog
        _require(self.workspace.database_button.isEnabled())
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(database), '')):
            self.workspace.database_button.click()
        _require(Path(self.workspace.db_file).resolve() == database.resolve())

    def review(self, ready, duplicate):
        workspace = self.workspace
        _require(workspace.scan_button.isEnabled())
        workspace.scan_button.click()
        self.wait(lambda: workspace.preflight_thread is None and workspace.metadata_thread is None
                  and not workspace._metadata_threads and not workspace._after_metadata_idle)
        reviewed = workspace._preflight_result
        _require(reviewed is not None and not reviewed.cancelled and len(reviewed.files) == 12)
        counts = dict(Counter(item.status.value for item in reviewed.files))
        _require(counts == {key: count for key, count in [('ready', ready), ('duplicate', duplicate)] if count})
        _require(workspace.report_planner.model.selected_count == ready and workspace.parse_button.isEnabled() == bool(ready))
        _require(Path(reviewed.database_path).resolve() == Path(workspace.db_file).resolve())
        return {'ready': ready, 'duplicate': duplicate, 'selected': ready}

    def import_reports(self, case, context):
        from PyQt6.QtWidgets import QPushButton
        from metroliza.app.windows_candidate_import_sync import click_import, wait_import_started, wait_import_finished
        module = import_module('metroliza.parsing.parse_reports_thread')
        original, entered = module.parse_new_reports, Event()
        self.release.clear()
        def producer(*args, **kwargs):
            callback = kwargs['on_file_accepted']
            def accepted(item, parser, outcome):
                value = callback(item, parser, outcome)
                try:
                    _require(context['first_accepted'] is None)
                    context['first_accepted'] = Path(item.report_path).name
                    entered.set()
                    if not self.release.wait(5):
                        context['barrier_expired'] = True
                except Exception:
                    self.callback_errors.append('reports_callback_failed')
                return value
            return original(*args, **dict(kwargs, on_file_accepted=accepted))
        with patch.object(module, 'parse_new_reports', producer if case == 'C' else original):
            try:
                operation = click_import(self.workspace)
                worker = wait_import_started(self.app, operation, seconds=self.remaining(20))
                _require({item.occurrence_id for item in worker.import_plan.selected_reports} == set(self.names)
                         and worker.import_plan.database_path == self.workspace.db_file)
                if case == 'C':
                    self.wait(entered.is_set)
                    progress = self.workspace.loading_dialog
                    _require(progress is not None)
                    self.wait(lambda: self.workspace.loading_dialog is progress and progress.isVisible(), 3)
                    _require(worker.isRunning())
                    buttons = [b for b in progress.findChildren(QPushButton) if b.text() == 'Cancel' and b.isVisibleTo(progress)]
                    _require(len(buttons) == 1 and buttons[0].isEnabled())
                    context['worker_running_at_cancel'] = True
                    buttons[0].click()
                    context['cancel_clicked'] = True
                    context['cancel_flag'] = bool(self.workspace.parsing_canceled and worker.parsing_canceled)
                    _require(context['cancel_flag'])
            finally:
                self.release.set()
                context['released'] = True
            wait_import_finished(self.app, operation, seconds=self.remaining(35), require_success=False)
            self.wait(lambda: self.workspace.parse_thread is None and operation.terminal)
        _require(not self.callback_errors, 'reports_callback_failed')
        context['terminal'] = operation.terminal
        _require(not context['barrier_expired'])
        if case == 'C':
            _require(context['first_accepted'] == self.names[0])
        result = asdict(worker.last_parse_result)
        expected = self.oracle['scenarios'][case]
        _require(result['total_files'] == result['selected_files'] == 12
                 and result['imported_files'] == result['parsed_files'] == expected['saved']
                 and result['failed_files'] == expected['failed'] and result['cancelled_files'] == expected['cancelled']
                 and all(result[name] == 0 for name in ('already_present_files', 'skipped_files',
                          'intentionally_excluded_files', 'preflight_changed_files')))
        return {'saved': result['imported_files'], 'failed': result['failed_files'],
                'cancelled': result['cancelled_files'], 'total': 12}, worker.last_report_outcomes

    def rows(self, case, receipts):
        from PyQt6.QtCore import Qt
        planner = self.workspace.report_planner
        model, proxy = planner.model, planner.proxy
        rows = list(model.execution_rows)
        expected = {name: 'failed' if case == 'B' and name == self.names[5] else
                    'unknown' if case == 'C' and name != self.names[0] else 'saved' for name in self.names}
        _require({row.stable_occurrence_id for row in rows} == set(self.names))
        _require(len(rows) == model.rowCount() == proxy.rowCount() == 12
                 and len({row.stable_occurrence_id for row in rows}) == 12)
        _require({row.display_name: row.status.value for row in rows} == expected)
        _require(model.selected_ids == () and not model.valid and self.workspace._preflight_result is None
                 and not self.workspace.parse_button.isEnabled())
        facts = []
        for index, row in enumerate(rows):
            cells = [model.data(model.index(index, col), Qt.ItemDataRole.DisplayRole) for col in range(model.columnCount())]
            _require(row.display_name in cells and row.status.value.title() in cells)
            readonly = all(not model.flags(model.index(index, col)) & (Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
                           for col in range(model.columnCount()))
            _require(readonly and row.needs_attention == (row.status.value != 'saved'))
            if row.status.value == 'unknown':
                _require(row.detail == 'No per-report completion evidence. Review the destination before retrying.')
            facts.append(dict(name=row.display_name, occurrence_id=row.stable_occurrence_id,
                              state=row.status.value, readonly=readonly, attention=row.needs_attention))
        states = {receipt.occurrence_id: receipt.state for receipt in receipts}
        _require(len(states) == len(receipts) and states == {row['occurrence_id']: row['state'] for row in facts if row['state'] != 'unknown'})
        attention = sum(row['attention'] for row in facts)
        planner.attention_filter.setChecked(True)
        _require(proxy.rowCount() == attention)
        planner.attention_filter.setChecked(False)
        _require(proxy.rowCount() == 12)
        expected_counts = Counter(expected.values())
        _require(all(model.execution_counts.get(key, 0) == count for key, count in expected_counts.items()))
        outcome = planner.outcome.toPlainText()
        for status, word in [('saved', 'Saved'), ('failed', 'Failed'), ('unknown', 'Cancelled')]:
            if expected_counts[status]:
                _require(f'{word}: {expected_counts[status]} report file' in outcome)
        _require(self.workspace.import_succeeded == (attention == 0))
        _require((self.workspace.readiness_label.property('statusVariant') == 'success') == (attention == 0))
        ordered = sorted(facts, key=lambda row: row['name'])
        return ordered, states

    def summary(self, case):
        from PyQt6.QtCore import QTimer
        planner = self.workspace.report_planner
        snapshots = {'immediate': _summary_snapshot(planner), 'queued': None}
        def delivered():
            try:
                snapshots['queued'] = _summary_snapshot(planner)
            except Exception:
                self.callback_errors.append('reports_callback_failed')
        QTimer.singleShot(0, delivered)
        self.wait(lambda: snapshots['queued'] is not None or self.callback_errors)
        self.evidence['summaries'][case] = snapshots
        expected = self.oracle['scenarios'][case]
        for fragment in ('Last import: 12 visible / 12 report results', f"{expected['saved']} saved",
                         f"{expected['failed']} failed", f"{expected['unknown']} unknown"):
            _require(fragment in planner.counts.accessibleDescription())
        for name in (('reports-saved-top', 'reports-saved-bottom') if case == 'A' else
                     ('reports-partial-error' if case == 'B' else 'reports-partial-cancel',)):
            self.take(name)
        _check_summary(snapshots['queued'])

    def take(self, name):
        from PyQt6.QtGui import QImage
        expected = CAPTURE_STATES[name]
        table = self.workspace.report_planner.table
        table.scrollToBottom() if expected['viewport'] == 'bottom' else table.scrollToTop()
        try:
            metadata = self.capture(name, self.window, dict(expected))
        except Exception as error:
            raise ReportsChecksFailure('reports_capture_failed') from error
        _require(type(metadata) is dict and set(metadata) == {'path', 'sha256', 'width', 'height', 'dpr'}, 'reports_capture_failed')
        path = self.root / f'uiux-{name}.png'
        _require(path.resolve().parent == self.root and metadata['path'] == path.name
                 and not path.is_symlink() and path.is_file(), 'reports_capture_failed')
        image = QImage(str(path))
        _require(not image.isNull() and image.width() == metadata['width'] and image.height() == metadata['height']
                 and metadata['dpr'] == self.dpr and metadata['sha256'] == _sha(path, 8 * 1024 * 1024)
                 and image.width() == round(self.window.width() * self.dpr)
                 and image.height() == round(self.window.height() * self.dpr), 'reports_capture_failed')
        self.evidence['captures'][name] = metadata

    def trigger(self, database, *, remove=False):
        from metroliza.reports.db import sqlite_connection_scope
        with sqlite_connection_scope(str(database)) as connection:
            with closing(connection.cursor()) as cursor:
                if remove:
                    cursor.execute('DROP TRIGGER acceptance_ref006_failure')
                else:
                    cursor.execute('''CREATE TRIGGER acceptance_ref006_failure BEFORE INSERT ON parsed_reports
                        WHEN (SELECT sha256 FROM source_files WHERE id=NEW.source_file_id)
                        = '6ed81cae46fe0111ee251f9dc2a7bfe817735e650e3d213cc84f0f1a03ddbd87'
                        BEGIN SELECT RAISE(ABORT, 'synthetic acceptance error'); END''')
                connection.commit()

    def run_case(self, case):
        from PyQt6.QtCore import QSettings
        from PyQt6.QtWidgets import QFileDialog
        from metroliza.app.ui_entrypoint import load_main_window_factory
        from metroliza.app.windows_candidate_import_guards import _database_state, _committed_unchanged
        from metroliza.reports.report_schema import ensure_report_schema
        self.phase = case
        started = time.monotonic()
        self.case_deadline = min(self.deadline, started + (90 if case == 'A' else 45))
        preferences = import_module('metroliza.ui.ui_preferences').UiPreferences
        settings = QSettings(str(self.child / (case + '.ini')), QSettings.Format.IniFormat)
        self.close_failed = False
        self.window = load_main_window_factory()('candidate-reports-uiux', None, ui_preferences=preferences(settings))
        self.window.show()
        self.workspace = self.window.launch_parsing_dialog()
        self.app.processEvents()
        with patch.object(QFileDialog, 'getExistingDirectory', return_value=str(self.child / 'pdf')):
            self.workspace.directory_button.click()
        _require(Path(self.workspace.directory).resolve() == (self.child / 'pdf').resolve())
        database = self.child / (case + '.sqlite')
        context = dict.fromkeys(CONTEXT_KEYS, False)
        context['first_accepted'] = None
        if case == 'A':
            first = self.child / 'seed.sqlite'
            self.choose(first)
            self.review(12, 0)
            self.import_reports('A', dict(context))
            _snapshot(first, self.oracle, set(self.names))
            baseline = _database_state(first)
            self.review(0, 12)
            _require(_committed_unchanged(first, baseline))
        else:
            ensure_report_schema(str(database))
            if case == 'B':
                self.trigger(database)
        self.choose(database)
        if case == 'A':
            _require(self.workspace._preflight_result is None and not self.workspace.parse_button.isEnabled()
                     and self.workspace.report_planner.model.selected_ids == () and not self.workspace.import_succeeded)
            context['approval_invalidated'] = True
        result = dict.fromkeys(CASE_KEYS)
        self.evidence[case] = result
        result['context'] = context
        result['review_counts'] = self.review(12, 0)
        result['batch_counts'], receipts = self.import_reports(case, context)
        result['row_facts'], result['receipt_states'] = self.rows(case, receipts)
        saved = {row['name'] for row in result['row_facts'] if row['state'] == 'saved'}
        result['database_counts'], result['numeric_digests'] = _snapshot(database, self.oracle, saved)
        self.summary(case)
        if case == 'A':
            plain_text = import_module('metroliza.ui.shortcuts').plain_text
            _require(self.window.export_button.isEnabled() and self.window.export_button.property('buttonRole') == 'primary'
                     and plain_text(self.window.home_next_action.text()) == 'Export Workbook [Ctrl+E]'
                     and self.window.home_next_action.accessibleName() == 'Export Workbook')
            frozen = tuple(self.workspace.report_planner.model.execution_rows)
            self.window.navigation_combo.setCurrentIndex(self.window.navigation_combo.findData('home'))
            _require(self.window.launch_parsing_dialog() is self.workspace)
            context['same_owner'] = True
            context['same_result'] = tuple(self.workspace.report_planner.model.execution_rows) == frozen
            _require(context['same_result'] and _committed_unchanged(first, baseline))
        if case == 'B':
            self.trigger(database, remove=True)
        committed = _database_state(database)
        result['rereview_counts'] = self.review(12 - len(saved), len(saved))
        _require(_committed_unchanged(database, committed))
        _snapshot(database, self.oracle, saved)
        result['preservation'] = {'destination_logical_sha256': committed['logical_sha256'], 'rereview_unchanged': True,
                                  'seed_unchanged': case != 'A' or _committed_unchanged(first, baseline),
                                  'sources_unchanged': self.source_unchanged()}
        _require(result['preservation']['sources_unchanged'])
        _require(time.monotonic() - started <= (90 if case == 'A' else 45), 'reports_phase_deadline')
        self.close()

    def source_unchanged(self):
        return all(_sha(self.fixtures / name) == sha for name, sha in FIXTURE_HASHES.items()) and all(
            _sha(self.child / 'pdf' / item['name']) == item['sha256'] for item in self.oracle['members'])

    def close(self):
        from metroliza.app.windows_candidate_native_check import close_report_owner
        self.release.set()
        _require(not self.close_failed, 'reports_cleanup_failed')
        if self.window is not None:
            try:
                close_report_owner(self.window, self.app)
            except BaseException:
                self.close_failed = True
                _RETAINED_WINDOWS.append(self.window)
                raise
            self.window, self.workspace = None, None

    def cleanup(self):
        self.phase = 'cleanup'
        self.close()
        _require(self.source_unchanged() and not self.callback_errors, 'reports_cleanup_failed')
        _require(self.app.activeModalWidget() is None, 'reports_cleanup_failed')
        self.evidence['cleanup'] = {'joined': True, 'closed': True, 'sources_unchanged': True, 'callback_errors': []}
        self.passed('cleanup')


def run_reports_checks(scratch, fixtures, *, expected_dpr, capture):
    """Run within existing qualification; source capture does not prove P3 integration."""
    result = {'schema_version': 1, 'status': 'failed', 'facets': dict.fromkeys(FACETS, 'failed'), 'error_codes': [],
              'evidence': {'fixture_hashes': {}, 'context': None, 'A': None, 'B': None, 'C': None,
                           'summaries': {}, 'captures': {}, 'cleanup': None, 'failure': None}}
    journey = None
    try:
        _require(all(os.environ.get(name) == '1' for name in ('METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION')),
                 'reports_gate_missing')
        _require(callable(capture), 'reports_capture_failed')
        _require(type(expected_dpr) in (int, float) and math.isfinite(expected_dpr) and expected_dpr in (1, 1.25, 1.5))
        scratch, fixtures = Path(scratch).resolve(), Path(fixtures).resolve()
        _require(scratch.is_dir() and not (scratch / 'reports-uiux').exists(), 'reports_fixture_invalid')
        journey = _Journey(scratch, fixtures, expected_dpr, capture, result)
        for case in 'ABC':
            journey.run_case(case)
        journey.passed('twelve_import', 'duplicate_rereview', 'database_switch', 'partial_persistence_failure',
                       'cancel_after_first_acceptance', 'historical_identity_readonly', 'summary_layout', 'source_preservation')
        _require(set(result['evidence']['captures']) == set(CAPTURE_STATES), 'reports_capture_failed')
        journey.passed('captures')
    except Exception as error:
        code = str(error) if isinstance(error, ReportsChecksFailure) and str(error) in ERROR_CODES else 'unexpected_exception'
        if type(error).__name__ in {'ImportSyncFailure', 'ScenarioFailure'} and str(error).endswith('_deadline'):
            code = 'reports_worker_join_deadline' if str(error) == 'import_worker_join_deadline' else 'reports_phase_deadline'
        result['error_codes'].append(code)
        result['evidence']['failure'] = {'phase': journey.phase if journey else 'admission', 'type': code}
    finally:
        if journey is not None:
            try:
                journey.cleanup()
            except Exception:
                result['error_codes'].append('reports_cleanup_failed')
    if not result['error_codes'] and all(value == 'passed' for value in result['facets'].values()):
        result['status'] = 'passed'
    _require(len(json.dumps(result, allow_nan=False).encode()) <= 24 * 1024)
    return result
