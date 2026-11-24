"""Synthetic Help-to-clipboard qualification for the fixed-schema bug report."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

FACETS = ('help_action', 'preview', 'clipboard', 'history_restore', 'privacy_guards', 'cleanup')
ERROR_CODES = ('bugreport_gate_missing', 'bugreport_application_missing',
               'bugreport_route_missing', 'bugreport_preview_invalid',
               'bugreport_clipboard_invalid', 'bugreport_history_invalid',
               'bugreport_privacy_invalid', 'bugreport_cleanup_failed',
               'unexpected_exception')
SENTINELS = ('SYNTHETIC_CONFIDENTIAL_PATH_7F3A', 'SYNTHETIC_SHEET_NAME_91BC',
             'SYNTHETIC_INPUT_VALUE_62DE')
# Fixed synthetic trace spanning report import, database editing, industrial / realtime,
# parser profiles, and the original CSV export-choice regression. This is a qualification
# fixture, not telemetry harvested from a user session.
EXPECTED_ACTIONS = [
    'app_opened', 'workspace_reports_opened',
    'workflow_report_import_started', 'workflow_report_import_completed',
    'option_report_review_ocr', 'workspace_database_opened',
    'workflow_database_edit_opened', 'workflow_database_edit_completed',
    'workspace_industrial_opened', 'industrial_sync_started', 'industrial_sync_finished',
    'workspace_realtime_opened', 'realtime_source_config_apply_started',
    'realtime_source_config_apply_finished', 'workspace_parser_profiles_opened',
    'parser_profile_validation_started', 'parser_profile_validation_finished',
    'csv_opened', 'option_workbook', 'option_html', 'log_error_reports',
]


class BugReportChecksFailure(ValueError):
    """Closed, path-free failure code."""


def _require(ok: bool, code: str = 'unexpected_exception') -> None:
    if not ok:
        raise BugReportChecksFailure(code)


def _wait(app, predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(.005)
    return bool(predicate())


# Deliberately literal oracle framing: never import the product serializer/parser.
PREVIEW_PREFIX = (
    '# Metroliza bug report v2\n\n'
    'Privacy: fixed codes, boolean options, runtime tokens and vetted build facts only.\n'
    'Missing context: unknown. Option observations do not imply operation association.\n'
    'Recent activity is queued asynchronously and may not survive forced exit.\n'
    'Reproduction status: `NOT_RUN`\nExternal input data: `not included`\n\n```json\n'
)
PREVIEW_SUFFIX = (
    '\n```\n\n## Reproduction\nReproduction not performed. Input data was not captured.\n'
    "Use synthetic inputs only; a reference scenario cannot reproduce the user's issue.\n"
    '\n## Instructions for a coding agent\n'
    'Inspect the source for the recorded actions, results and options; investigate the reported category.\n'
    'Use synthetic inputs only. Do not request or infer confidential files, values, paths or names.\n'
    'Attempt a relevant reproduction where possible; distinguish evidence, hypotheses and unverified behavior.\n'
)
SELECTION = dict(module='tabular', symptom='wrong_output',
                 expected='all_requested_outputs', observed='wrong_output')
MAX_PREVIEW_BYTES = 128 * 1024


def _valid(condition):
    _require(condition, 'bugreport_preview_invalid')


def _closed(value, names):
    _valid(type(value) is dict and set(value) == set(names.split()))
    return value


def _literal(value, expected):
    _valid(type(value) is type(expected))
    if type(expected) is dict:
        _valid(set(value) == set(expected))
        for key in expected:
            _literal(value[key], expected[key])
    elif type(expected) is list:
        _valid(len(value) == len(expected))
        for actual, target in zip(value, expected):
            _literal(actual, target)
    else:
        _valid(value == expected)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        _valid(key not in result)
        result[key] = value
    return result


def _uuid4(value):
    _valid(type(value) is str and len(value) == 36)
    parsed = uuid.UUID(value)
    _valid(parsed.version == 4 and str(parsed) == value)


def _expected_activity():
    states = {'option_report_review_ocr': True, 'option_workbook': True, 'option_html': False}
    return [dict(action=action, enabled=states.get(action)) for action in EXPECTED_ACTIONS]


def _validate_context(raw, *, request_id, session_id, stamps):
    _closed(raw, 'events options events_lost snapshot_state snapshots_lost')
    _literal(raw['events_lost'], False)
    _literal(raw['snapshots_lost'], False)
    _literal(raw['snapshot_state'], 'available')
    events, options = raw['events'], raw['options']
    _valid(type(events) is list and len(events) == 25)
    _valid(type(options) is list and len(options) == 1)
    _uuid4(request_id)
    _uuid4(session_id)
    last_ms = 0
    for index, event in enumerate(events):
        sequence = index + 1 if index < 21 else index + 2  # option snapshot owns sequence 22
        detail_keys = ('action enabled' if index < 21 else
                       'request' if index < 23 else
                       'category site' if index == 23 else 'output_verification')
        _closed(event, 'session_id sequence relative_ms kind ' + detail_keys)
        _literal(event['session_id'], session_id)
        _literal(event['sequence'], sequence)
        relative_ms = event['relative_ms']
        _valid(type(relative_ms) is int and last_ms <= relative_ms <= (1 << 53) - 1)
        _literal(relative_ms, stamps[sequence])
        last_ms = relative_ms
        if index < 21:
            _literal(event['kind'], 'action')
            for key, value in _expected_activity()[index].items():
                _literal(event[key], value)
        elif index < 23:
            _literal(event['kind'], 'request')
            request = _closed(event['request'], 'operation_id kind outcome duration_ms')
            _literal(request['operation_id'], request_id)
            _literal(request['kind'], 'report_export')
            _literal(request['outcome'], 'started' if index == 21 else 'completed')
            duration = request['duration_ms']
            if index == 21:
                _literal(duration, None)
            else:
                _valid(type(duration) is int and 0 <= duration <= relative_ms - stamps[23] + 1)
        elif index == 23:
            _literal(event['kind'], 'exception')
            _literal(event['category'], 'permission')
            _literal(event['site'], 'report_export')
        else:
            _literal(event['kind'], 'output_verification')
            _literal(event['output_verification'], dict(
                kind='report_workbook', passed=True, operation_id=request_id))
    option = _closed(options[0], 'session_id sequence relative_ms kind options operation_id')
    _literal(option['session_id'], session_id)
    _literal(option['sequence'], 22)
    _literal(option['relative_ms'], stamps[22])
    _valid(stamps[21] <= stamps[22] <= stamps[23])
    _literal(option['operation_id'], request_id)
    _literal(option['kind'], 'report_export')
    _literal(option['options'], {'workbook': True, 'html': False})


def _validate_provenance(raw):
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    from metroliza.app.version import RELEASE_VERSION

    _closed(raw, 'platform arch python qt pyqt runtime packager git_sha dirty')
    frozen = bool(getattr(sys, 'frozen', False))
    _literal(raw['platform'], {'win32': 'windows', 'linux': 'linux', 'darwin': 'macos'}.get(sys.platform, 'unknown'))
    _literal(raw['arch'], {'AMD64': 'x86_64', 'amd64': 'x86_64', 'x86_64': 'x86_64',
                           'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine(), 'unknown'))
    for key, expected in (('python', '.'.join(map(str, sys.version_info[:3]))),
                          ('qt', QT_VERSION_STR), ('pyqt', PYQT_VERSION_STR)):
        _valid(type(raw[key]) is str and re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}', raw[key]) is not None)
        _literal(raw[key], expected)
    _literal(raw['runtime'], 'frozen' if frozen else 'source')
    if not frozen:
        _literal(raw['packager'], 'source')
        _literal(raw['git_sha'], 'unknown')
        _literal(raw['dirty'], None)
        return
    # Read bounded embedded primitives independently of the product provenance loader.
    path = Path(__file__).with_name('build_provenance.json')
    with path.open('rb') as stream:
        encoded = stream.read(16 * 1024 + 1)
    _valid(len(encoded) <= 16 * 1024)
    manifest = json.loads(encoded, object_pairs_hook=_unique_keys)
    _closed(manifest, 'schema_version release_label git_sha dirty built_at_utc packager python_version')
    _literal(manifest['schema_version'], 1)
    _literal(manifest['release_label'], RELEASE_VERSION)
    _valid(type(raw['git_sha']) is str and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', raw['git_sha']) is not None)
    _valid(type(raw['dirty']) is bool and type(raw['packager']) is str
           and raw['packager'] in ('pyinstaller', 'nuitka'))
    for key in ('packager', 'git_sha', 'dirty'):
        _literal(raw[key], manifest[key])


def _validate_preview(preview, *, request_id, session_id, stamps):
    """Independent bounded oracle; return no report text or product parse result."""
    from metroliza.app.version import RELEASE_VERSION

    try:
        _valid(type(preview) is str and len(preview.encode('utf-8')) <= MAX_PREVIEW_BYTES
               and preview.startswith(PREVIEW_PREFIX) and preview.endswith(PREVIEW_SUFFIX))
        raw = json.loads(preview[len(PREVIEW_PREFIX):-len(PREVIEW_SUFFIX)], object_pairs_hook=_unique_keys)
        _closed(raw, 'schema release_version category activity context provenance selection')
        _literal(raw['schema'], 2)
        _literal(raw['release_version'], RELEASE_VERSION)
        _literal(raw['category'], 'wrong_output')
        _literal(raw['activity'], dict(events=_expected_activity(), events_lost=False,
                                      previous_session_state='available'))
        _literal(raw['selection'], SELECTION)
        _validate_context(raw['context'], request_id=request_id, session_id=session_id, stamps=stamps)
        _validate_provenance(raw['provenance'])
        _valid(preview == PREVIEW_PREFIX + json.dumps(raw, ensure_ascii=True, sort_keys=True, indent=2) + PREVIEW_SUFFIX)
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        raise BugReportChecksFailure('bugreport_preview_invalid') from error


def _observation(app) -> dict:
    return dict(schema_version=1, status='failed', facets=dict.fromkeys(FACETS, 'failed'),
        error_codes=[], evidence=dict(execution='packaged' if getattr(sys, 'frozen', False) else 'source',
            platform=app.platformName(), history_state='unknown', actions=[], option_states={},
            category='wrong_output', reproduction_status='NOT_RUN', preview_sha256=None,
            clipboard_match=False, excluded_sentinels_absent=False, dialog_closed=False,
            report_schema=None, detailed_context_validated=False, frozen_preview=False))


def _restore_synthetic_history(app, history_root, observation, resources):
    from metroliza.shared.safe_bugreport import (
        BugReportAction, PreviousSessionState, SafeBugReportRecorder,
    )

    recorder = SafeBugReportRecorder(max_events=32)
    resources['recorder'] = recorder
    _require(recorder.configure_history(history_root), 'bugreport_history_invalid')
    _require(_wait(app, lambda: recorder.snapshot().previous_session_state != PreviousSessionState.LOADING.value),
             'bugreport_history_invalid')
    synthetic_events = (
        (BugReportAction.APP_OPENED, None),
        (BugReportAction.WORKSPACE_REPORTS_OPENED, None),
        (BugReportAction.WORKFLOW_REPORT_IMPORT_STARTED, None),
        (BugReportAction.WORKFLOW_REPORT_IMPORT_COMPLETED, None),
        (BugReportAction.OPTION_REPORT_REVIEW_OCR, True),
        (BugReportAction.WORKSPACE_DATABASE_OPENED, None),
        (BugReportAction.WORKFLOW_DATABASE_EDIT_OPENED, None),
        (BugReportAction.WORKFLOW_DATABASE_EDIT_COMPLETED, None),
        (BugReportAction.WORKSPACE_INDUSTRIAL_OPENED, None),
        (BugReportAction.INDUSTRIAL_SYNC_STARTED, None),
        (BugReportAction.INDUSTRIAL_SYNC_FINISHED, None),
        (BugReportAction.WORKSPACE_REALTIME_OPENED, None),
        (BugReportAction.REALTIME_SOURCE_CONFIG_APPLY_STARTED, None),
        (BugReportAction.REALTIME_SOURCE_CONFIG_APPLY_FINISHED, None),
        (BugReportAction.WORKSPACE_PARSER_PROFILES_OPENED, None),
        (BugReportAction.PARSER_PROFILE_VALIDATION_STARTED, None),
        (BugReportAction.PARSER_PROFILE_VALIDATION_FINISHED, None),
        (BugReportAction.CSV_OPENED, None),
        (BugReportAction.OPTION_WORKBOOK, True),
        (BugReportAction.OPTION_HTML, False),
        (BugReportAction.LOG_ERROR_REPORTS, None),
    )
    for action, enabled in synthetic_events:
        _require(recorder.record(action, enabled=enabled), 'bugreport_history_invalid')
    from metroliza.shared.safe_bugreport_context import (
        ContextOperationOutcome, ExceptionCategory, ExceptionSite,
        OptionSnapshotKind, OutputVerificationKind,
    )

    token = recorder.record_option_snapshot(OptionSnapshotKind.REPORT_EXPORT,
                                             {'workbook': True, 'html': False})
    _require(type(token) is uuid.UUID and token.version == 4, 'bugreport_history_invalid')
    _require(recorder.record_option_outcome(token, ContextOperationOutcome.COMPLETED)
             and recorder.record_exception_category(ExceptionCategory.PERMISSION, ExceptionSite.REPORT_EXPORT)
             and recorder.record_output_verification(OutputVerificationKind.REPORT_WORKBOOK, True, token),
             'bugreport_history_invalid')
    _require(recorder.flush(5.0), 'bugreport_history_invalid')
    seeded = recorder.context_snapshot()
    _require(len(seeded.events) == 25 and len(seeded.options) == 1
             and seeded.snapshot_state == 'available' and not seeded.events_lost
             and not seeded.snapshots_lost, 'bugreport_history_invalid')
    resources['seed'] = dict(request_id=str(token), session_id=str(seeded.events[0].session_id),
        stamps={item.sequence: item.relative_ms for item in (*seeded.events, *seeded.options)})
    _require(recorder.close_history(5.0), 'bugreport_history_invalid')
    resources['recorder_closed'] = True
    restored = SafeBugReportRecorder(max_events=32)
    resources['restored'] = restored
    _require(restored.configure_history(history_root), 'bugreport_history_invalid')
    ready = _wait(app, lambda: restored.snapshot().previous_session_state != PreviousSessionState.LOADING.value
                  and restored.context_snapshot().snapshot_state != 'loading')
    _require(ready, 'bugreport_history_invalid')
    snapshot = restored.snapshot()
    actions = [event.action.value for event in snapshot.events]
    _require(snapshot.previous_session_state == PreviousSessionState.AVAILABLE.value
             and actions == EXPECTED_ACTIONS
             and snapshot.events[4].enabled is True
             and snapshot.events[18].enabled is True
             and snapshot.events[19].enabled is False,
             'bugreport_history_invalid')
    # An actual disk close/restore in this process; this does not claim an EXE restart.
    detailed = restored.context_snapshot()
    _require(detailed.events == seeded.events and detailed.options == seeded.options
             and detailed.snapshot_state == 'available' and not detailed.events_lost
             and not detailed.snapshots_lost, 'bugreport_history_invalid')
    observation['evidence'].update(history_state=snapshot.previous_session_state, actions=actions,
        option_states={'report_review_ocr': snapshot.events[4].enabled,
                       'workbook': snapshot.events[18].enabled,
                       'html': snapshot.events[19].enabled})
    observation['facets']['history_restore'] = 'passed'
    return recorder, restored


def _open_bugreport_dialog(app, settings_path, restored, resources):
    from PyQt6.QtCore import QSettings

    dialog_module = __import__('metroliza.ui.safe_bugreport_dialog', fromlist=['recorder'])
    original_recorder = dialog_module.recorder
    resources['dialog_module'] = dialog_module
    resources['original_recorder'] = original_recorder
    dialog_module.recorder = restored
    main_module = __import__('metroliza.ui.main_window', fromlist=['MainWindow'])
    prefs_module = __import__('metroliza.ui.ui_preferences', fromlist=['UiPreferences'])
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    settings.setValue('syntheticSheetName', SENTINELS[1])
    settings.setValue('syntheticCellValue', SENTINELS[2])
    settings.sync()
    window = main_module.MainWindow('Synthetic qualification', None,
        ui_preferences=prefs_module.UiPreferences(settings))
    resources['window'] = window
    window.show()
    _require(_wait(app, lambda: window.isVisible()), 'bugreport_route_missing')
    action = window.report_problem_action
    _require(action.isVisible() and action.isEnabled() and action in window.help_menu.actions(),
             'bugreport_route_missing')
    action.trigger()
    _require(_wait(app, lambda: any(w.isVisible() and w.windowTitle() == 'Report a problem'
                                    for w in app.topLevelWidgets())), 'bugreport_route_missing')
    dialogs = [w for w in app.topLevelWidgets() if w.isVisible() and w.windowTitle() == 'Report a problem']
    _require(len(dialogs) == 1, 'bugreport_route_missing')
    resources['dialog'] = dialogs[0]


def _check_preview_and_clipboard(app, dialog, root, history_root, settings_path, observation, resources):
    from PyQt6.QtGui import QGuiApplication
    from metroliza.shared.safe_bugreport import BugReportAction, BugReportCategory
    from metroliza.shared.safe_bugreport_context import ContextBehavior, ContextModule, ContextSymptom

    category_index = dialog.category_combo.findData(BugReportCategory.WRONG_OUTPUT)
    _require(category_index >= 0, 'bugreport_preview_invalid')
    dialog.category_combo.setCurrentIndex(category_index)
    for combo, value in ((dialog.module_combo, ContextModule.TABULAR),
                         (dialog.symptom_combo, ContextSymptom.WRONG_OUTPUT),
                         (dialog.expected_combo, ContextBehavior.ALL_REQUESTED_OUTPUTS),
                         (dialog.observed_combo, ContextBehavior.WRONG_OUTPUT)):
        index = combo.findData(value)
        _require(index >= 0, 'bugreport_preview_invalid')
        combo.setCurrentIndex(index)
    _require(_wait(app, lambda: bool(dialog.preview.toPlainText())), 'bugreport_preview_invalid')
    preview = dialog.preview.toPlainText()
    _require(dialog._preview_report == preview, 'bugreport_preview_invalid')
    _validate_preview(preview, **resources['seed'])
    observation['evidence'].update(report_schema=2, detailed_context_validated=True)
    # Real later activity must not alter the reviewed snapshot or copied bytes.
    _require(resources['restored'].record(BugReportAction.APP_OPENED), 'bugreport_preview_invalid')
    app.processEvents()
    _require(dialog.preview.toPlainText() == preview and dialog._preview_report == preview,
             'bugreport_preview_invalid')
    observation['evidence']['preview_sha256'] = hashlib.sha256(preview.encode('utf-8')).hexdigest()
    observation['facets']['preview'] = 'passed'
    _require(dialog.copy_button.isEnabled(), 'bugreport_clipboard_invalid')
    dialog.copy_button.click()
    _require(_wait(app, lambda: QGuiApplication.clipboard().text() == preview),
             'bugreport_clipboard_invalid')
    _require(dialog.preview.toPlainText() == preview and dialog._preview_report == preview,
             'bugreport_clipboard_invalid')
    observation['evidence'].update(clipboard_match=True, frozen_preview=True)
    observation['facets']['clipboard'] = 'passed'
    excluded = (*SENTINELS, str(root), str(history_root), str(settings_path))
    observation['evidence']['excluded_sentinels_absent'] = not any(
        secret in preview or secret in QGuiApplication.clipboard().text() for secret in excluded)
    _require(observation['evidence']['excluded_sentinels_absent'], 'bugreport_privacy_invalid')
    observation['facets']['privacy_guards'] = 'passed'


def _close_widgets(dialog, window) -> bool:
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent

    closed = True
    for widget in (dialog, window):
        if widget is None:
            continue
        try:
            closed = bool(widget.close()) and closed
            if not sip.isdeleted(widget):
                widget.deleteLater()
                QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
            closed = sip.isdeleted(widget) and closed
        except Exception:
            closed = False
    return closed


def _cleanup_bugreport(resources, history_root, settings_path, observation) -> None:
    dialog, window = resources['dialog'], resources['window']
    dialog_closed = _close_widgets(dialog, window) if dialog is not None or window is not None else True
    dialog_module = resources['dialog_module']
    if dialog_module is not None:
        dialog_module.recorder = resources['original_recorder']
    history_closed = False
    try:
        restored = resources['restored']
        recorder = resources['recorder']
        history_closed = (restored.close_history(5.0) if restored is not None else
                          recorder.close_history(5.0) if recorder is not None and not resources['recorder_closed'] else True)
    except Exception:
        history_closed = False
    scratch_removed = True
    try:
        if history_root.exists():
            shutil.rmtree(history_root, ignore_errors=False)
        settings_path.unlink(missing_ok=True)
    except Exception:
        scratch_removed = False
    cleanup_ok = dialog_closed and history_closed and scratch_removed
    observation['evidence']['dialog_closed'] = dialog_closed
    observation['facets']['cleanup'] = 'passed' if cleanup_ok else 'failed'
    if not cleanup_ok and observation['status'] == 'passed':
        observation['status'] = 'failed'
        observation['error_codes'] = ['bugreport_cleanup_failed']


def run_bugreport_checks(root: Path) -> dict:
    """Exercise the real Help action and dialog using an isolated synthetic history."""
    _require(all(os.environ.get(key) == '1' for key in
                 ('METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION')),
              'bugreport_gate_missing')
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    _require(app is not None, 'bugreport_application_missing')
    root = Path(root).resolve()
    history_root, settings_path = root / 'bugreport-synthetic-history', root / 'bugreport-synthetic-settings.ini'
    observation = _observation(app)
    resources = dict.fromkeys(('recorder', 'restored', 'dialog_module', 'original_recorder', 'window', 'dialog'))
    resources['recorder_closed'] = False
    try:
        _restore_synthetic_history(app, history_root, observation, resources)
        _open_bugreport_dialog(app, settings_path, resources['restored'], resources)
        observation['facets']['help_action'] = 'passed'
        _check_preview_and_clipboard(app, resources['dialog'], root, history_root, settings_path, observation, resources)
        observation['status'] = 'passed'
    except Exception as error:
        code = str(error) if isinstance(error, BugReportChecksFailure) and str(error) in ERROR_CODES else 'unexpected_exception'
        observation['error_codes'] = [code]
    finally:
        _cleanup_bugreport(resources, history_root, settings_path, observation)
    if observation['status'] == 'passed':
        _require(all(value == 'passed' for value in observation['facets'].values()), 'unexpected_exception')
    return observation
