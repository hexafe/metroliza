"""Synthetic Help-to-clipboard qualification for the fixed-schema bug report."""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path

FACETS = ('help_action', 'preview', 'clipboard', 'history_restore', 'privacy_guards', 'cleanup')
ERROR_CODES = ('bugreport_gate_missing', 'bugreport_application_missing',
               'bugreport_route_missing', 'bugreport_preview_invalid',
               'bugreport_clipboard_invalid', 'bugreport_history_invalid',
               'bugreport_privacy_invalid', 'bugreport_cleanup_failed',
               'unexpected_exception')
SENTINELS = ('SYNTHETIC_CONFIDENTIAL_PATH_7F3A', 'SYNTHETIC_SHEET_NAME_91BC',
             'SYNTHETIC_INPUT_VALUE_62DE')
EXPECTED_ACTIONS = ['app_opened', 'csv_opened', 'option_workbook', 'option_html']


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


def _expected_preview() -> str:
    """Independent expected public report; do not call the product serializer here."""
    from metroliza.app.version import RELEASE_VERSION

    lines = (
        '# Metroliza bug report',
        '',
        f'Application version: `{RELEASE_VERSION}`',
        'This report serializes only fixed action/category codes and boolean states.',
        'Coverage: selected CSV workflow actions. Input data, paths, names, and configuration values are not included.',
        'Activity history: retained local activity may include earlier launches.',
        'Session boundaries: unknown; prior activity is not evidence of a crash.',
        'Recent activity is queued asynchronously and may not survive forced exit.',
        'Previous activity restored: `available`',
        'Reproduction status: `NOT_RUN`',
        'External input data: `not included`',
        '',
        'Category: `wrong_output`',
        'Recorded events lost: `false`',
        '',
        '## Recent activity',
        '- `app_opened`',
        '- `csv_opened`',
        '- `option_workbook` (enabled: `true`)',
        '- `option_html` (enabled: `false`)',
        '',
        '## Reproduction',
        'Reproduction not performed. Input data was not captured.',
    )
    return '\n'.join(lines) + '\n'


def _observation(app) -> dict:
    import sys

    return dict(schema_version=1, status='failed', facets=dict.fromkeys(FACETS, 'failed'),
        error_codes=[], evidence=dict(execution='packaged' if getattr(sys, 'frozen', False) else 'source',
            platform=app.platformName(), history_state='unknown', actions=[], option_states={},
            category='wrong_output', reproduction_status='NOT_RUN', preview_sha256=None,
            clipboard_match=False, excluded_sentinels_absent=False, dialog_closed=False))


def _restore_synthetic_history(app, history_root, observation, resources):
    from metroliza.shared.safe_bugreport import (
        BugReportAction, PreviousSessionState, SafeBugReportRecorder,
    )

    recorder = SafeBugReportRecorder(max_events=16)
    resources['recorder'] = recorder
    _require(recorder.configure_history(history_root), 'bugreport_history_invalid')
    for action, enabled in ((BugReportAction.APP_OPENED, None), (BugReportAction.CSV_OPENED, None),
                            (BugReportAction.OPTION_WORKBOOK, True), (BugReportAction.OPTION_HTML, False)):
        _require(recorder.record(action, enabled=enabled), 'bugreport_history_invalid')
    _require(recorder.flush(5.0) and recorder.close_history(5.0), 'bugreport_history_invalid')
    resources['recorder_closed'] = True
    restored = SafeBugReportRecorder(max_events=16)
    resources['restored'] = restored
    _require(restored.configure_history(history_root), 'bugreport_history_invalid')
    ready = _wait(app, lambda: restored.snapshot().previous_session_state != PreviousSessionState.LOADING.value)
    _require(ready, 'bugreport_history_invalid')
    snapshot = restored.snapshot()
    actions = [event.action.value for event in snapshot.events]
    _require(snapshot.previous_session_state == PreviousSessionState.AVAILABLE.value
             and actions == EXPECTED_ACTIONS and snapshot.events[2].enabled is True
             and snapshot.events[3].enabled is False, 'bugreport_history_invalid')
    observation['evidence'].update(history_state=snapshot.previous_session_state, actions=actions,
        option_states={'workbook': snapshot.events[2].enabled, 'html': snapshot.events[3].enabled})
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


def _check_preview_and_clipboard(app, dialog, root, history_root, settings_path, observation):
    from PyQt6.QtGui import QGuiApplication
    from metroliza.shared.safe_bugreport import BugReportCategory

    category_index = dialog.category_combo.findData(BugReportCategory.WRONG_OUTPUT)
    _require(category_index >= 0, 'bugreport_preview_invalid')
    dialog.category_combo.setCurrentIndex(category_index)
    _require(_wait(app, lambda: bool(dialog.preview.toPlainText())), 'bugreport_preview_invalid')
    preview = dialog.preview.toPlainText()
    _require(dialog._preview_report == preview and len(preview.encode('utf-8')) <= 16 * 1024
             and preview == _expected_preview(), 'bugreport_preview_invalid')
    observation['evidence']['preview_sha256'] = hashlib.sha256(preview.encode('utf-8')).hexdigest()
    observation['facets']['preview'] = 'passed'
    _require(dialog.copy_button.isEnabled(), 'bugreport_clipboard_invalid')
    dialog.copy_button.click()
    _require(_wait(app, lambda: QGuiApplication.clipboard().text() == preview),
             'bugreport_clipboard_invalid')
    observation['evidence']['clipboard_match'] = True
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
        _check_preview_and_clipboard(app, resources['dialog'], root, history_root, settings_path, observation)
        observation['status'] = 'passed'
    except Exception as error:
        code = str(error) if isinstance(error, BugReportChecksFailure) and str(error) in ERROR_CODES else 'unexpected_exception'
        observation['error_codes'] = [code]
    finally:
        _cleanup_bugreport(resources, history_root, settings_path, observation)
    if observation['status'] == 'passed':
        _require(all(value == 'passed' for value in observation['facets'].values()), 'unexpected_exception')
    return observation

