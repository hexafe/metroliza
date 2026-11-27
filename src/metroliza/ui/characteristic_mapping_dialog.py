"""Dialog for maintaining characteristic name matching mappings."""

from __future__ import annotations

from contextlib import contextmanager
import csv
from functools import partial
from html import escape
import sqlite3
import threading
import time
import weakref
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
    QScrollArea,
    QWidget,
)

from metroliza.reports.characteristic_alias_service import (
    CharacteristicAliasCsvSchemaError,
    CharacteristicAliasImportValidationError,
    CHARACTERISTIC_ALIAS_TABLE,
    conflicting_alias_targets,
    delete_characteristic_alias,
    effective_alias_scope,
    ensure_characteristic_alias_schema,
    export_characteristic_aliases_csv,
    fetch_all_characteristic_aliases,
    import_characteristic_aliases_csv,
    preview_characteristic_aliases_csv,
    apply_characteristic_alias_import,
    normalize_scope_type,
    repair_characteristic_alias_conflict,
    save_manual_characteristic_alias,
)
from metroliza.reports.characteristic_mapping_service import (
    fetch_distinct_references,
    fetch_distinct_report_metric_names,
    fetch_mapping_impact_counts,
)
from metroliza.reports.db import (
    _is_transient_sqlite_error,
    sqlite_file_identity,
    sqlite_readonly_connection_scope,
)
from metroliza.shared.custom_logger import CustomLogger
from metroliza.shared.safe_bugreport import BugReportAction, recorder as _bugreport_recorder
from metroliza.ui import detached_threads
from metroliza.ui.curation_presentation import bind_button
from metroliza.ui.shortcuts import bind_search_shortcut, install_button_commands
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_table,
    configure_dialog_button_roles,
    configure_window_size,
    section_label,
    set_status_variant,
    status_chip,
)
from metroliza.ui.worker_progress_dialog import (
    create_delayed_worker_progress_dialog,
    dismiss_worker_progress_dialog,
)


ALL_REFERENCES_LABEL = 'All references'
ONE_REFERENCE_LABEL = 'One reference only'
REMEDIATION_REPORT_HEADERS = ('row_number', 'field', 'code', 'category', 'message', 'remediation_hint')
SOURCE_TABLE_HEADERS = ['Report/export name', 'References', 'Reports', 'Rows']
SOURCE_LOADING_TEXT = 'Loading report/export names...'
SOURCE_LOAD_CANCELED_TEXT = 'Loading report/export names was canceled. Use Browse DB to load them again.'
ALIAS_INFO_TEXT = 'Matches affect Group Analysis labels; raw parsed values stay unchanged.'
# Upper bound for the GUI thread to wait for an interrupted loader; a loader that has not stopped by
# then is detached (it keeps running to completion in the background and its result is dropped).
SOURCE_LOAD_STOP_WAIT_MS = 2000

_DEFAULT_ALIAS_SCHEMA = ensure_characteristic_alias_schema
_DEFAULT_ALIAS_IMPORT = import_characteristic_aliases_csv
_DEFAULT_ALIAS_EXPORT = export_characteristic_aliases_csv
_DEFAULT_ALIAS_FETCH = fetch_all_characteristic_aliases


@contextmanager
def _readonly_source_options_connection(db_file):
    scope = None
    connection = None
    for attempt in range(3):
        scope = sqlite_readonly_connection_scope(db_file, resolve_path=False)
        try:
            connection = scope.__enter__()
            break
        except sqlite3.OperationalError as exc:
            if attempt >= 2 or not _is_transient_sqlite_error(exc):
                raise
            time.sleep(0.05)
    if connection is None or scope is None:
        raise RuntimeError('Could not open the source database.')
    try:
        yield connection
    finally:
        scope.__exit__(None, None, None)
_ALIAS_CSV_CONTROLS = ('select_db_button', 'add_button', 'add_from_selected_button',
                       'edit_button', 'delete_button', 'import_button', 'export_button')


def _record_mapping_action(action: BugReportAction) -> None:
    try:
        _bugreport_recorder.record(action)
    except Exception:
        # A local diagnostic must never change mapping behavior.
        return


def _record_mapping_action_if(enabled: bool, action: BugReportAction) -> None:
    if enabled:
        _record_mapping_action(action)


def _record_alias_csv_outcome(operation, error, phase, result_confirmed) -> None:
    if error is not None:
        outcome = 'failed'
    elif phase == 'cancelled':
        outcome = 'cancelled'
    elif result_confirmed:
        outcome = 'completed'
    else:
        outcome = 'unknown'
    actions = {
        ('import', 'completed'): BugReportAction.WORKFLOW_MAPPING_IMPORT_COMPLETED,
        ('import', 'failed'): BugReportAction.WORKFLOW_MAPPING_IMPORT_FAILED,
        ('import', 'cancelled'): BugReportAction.WORKFLOW_MAPPING_IMPORT_CANCELLED,
        ('import', 'unknown'): BugReportAction.WORKFLOW_MAPPING_IMPORT_RESULT_UNKNOWN,
        ('export', 'completed'): BugReportAction.WORKFLOW_MAPPING_EXPORT_COMPLETED,
        ('export', 'failed'): BugReportAction.WORKFLOW_MAPPING_EXPORT_FAILED,
        ('export', 'cancelled'): BugReportAction.WORKFLOW_MAPPING_EXPORT_CANCELLED,
        ('export', 'unknown'): BugReportAction.WORKFLOW_MAPPING_EXPORT_RESULT_UNKNOWN,
    }
    action = actions.get((operation, outcome))
    if action is not None:
        _record_mapping_action(action)


def _alias_csv_busy(owner):
    return type(owner) is _NATIVE_MAPPING_DIALOG and any(
        type(key) is str and key == '_alias_csv_thread' and value is not None
        for key, value in vars(owner).items()
    )


def _native_alias_csv(owner):
    if type(owner) is not _NATIVE_MAPPING_DIALOG:
        return False
    state = vars(owner)
    if any(type(key) is not str for key in state):
        return False
    if type(state.get('db_file')) is not str or '_alias_csv_thread' not in state or state.get('_source_loading'):
        return False
    if any(name in state or vars(_NATIVE_MAPPING_DIALOG).get(name) is not method
           for name, method in _ALIAS_CSV_METHODS.items()):
        return False
    return (ensure_characteristic_alias_schema is _DEFAULT_ALIAS_SCHEMA
            and import_characteristic_aliases_csv is _DEFAULT_ALIAS_IMPORT
            and export_characteristic_aliases_csv is _DEFAULT_ALIAS_EXPORT
            and all(type(state.get(name)) is QPushButton for name in _ALIAS_CSV_CONTROLS))


class _AliasCsvThread(QThread):
    """Own one immutable path request; result/error delivery remains on the GUI."""

    preview_ready = pyqtSignal(object)

    def __init__(self, operation, db_file, filename):
        super().__init__()
        self.operation, self.db_file, self.filename = operation, db_file, filename
        self.producer = _DEFAULT_ALIAS_IMPORT if operation == 'import' else _DEFAULT_ALIAS_EXPORT
        self.count, self.error, self.discard_result = None, None, False
        self.reviewed = threading.Event()
        self.choice = None
        self._outcome_lock = threading.Lock()
        self._phase = 'preflight'
        self._result_confirmed = False

    def run(self):
        try:
            if self.operation == 'import':
                plan = preview_characteristic_aliases_csv(self.db_file, self.filename)
                self.preview_ready.emit(plan)
                while not self.reviewed.wait(0.1):
                    if self.isInterruptionRequested() or self.discard_result:
                        with self._outcome_lock:
                            self._phase = 'cancelled'
                        return
                with self._outcome_lock:
                    if self.error is not None:
                        return
                    if self.choice is None or self.discard_result or self.isInterruptionRequested():
                        self._phase = 'cancelled'
                        return
                    # Once apply starts, closing the dialog only discards UI delivery.
                    # The persistence operation itself remains authoritative.
                    self._phase = 'applying'
                self.count = apply_characteristic_alias_import(self.db_file, plan, replace=self.choice)
                self._result_confirmed = True
            else:
                with self._outcome_lock:
                    self._phase = 'applying'
                _DEFAULT_ALIAS_SCHEMA(self.db_file)
                self.count = self.producer(self.db_file, self.filename)
                self._result_confirmed = True
        except Exception as exc:
            self.error = exc
        finally:
            _record_alias_csv_outcome(
                self.operation, self.error, self._phase, self._result_confirmed
            )

    def result(self):
        if self.error is not None:
            raise self.error
        return self.count

    def cancel_review(self, *_args):
        with self._outcome_lock:
            self.discard_result = True
            self.requestInterruption()
            self.reviewed.set()


def _cancel_alias_review(thread_ref, *_args):
    thread = thread_ref()
    if thread is not None and not sip.isdeleted(thread):
        thread.cancel_review()


def _delete_alias_csv_thread(owner_ref, thread_ref):
    thread, owner = thread_ref(), owner_ref()
    if thread is None or sip.isdeleted(thread):
        return
    cancel = vars(thread).pop('_cancel_review_callback', None)
    if cancel is not None:
        QCoreApplication.instance().aboutToQuit.disconnect(cancel)
        if owner is not None and not sip.isdeleted(owner):
            owner.destroyed.disconnect(cancel)
    thread.error = None
    detached_threads.delete_on_owner_thread(thread)


def _has_selected_db_file(db_file: str) -> bool:
    return bool(str(db_file or '').strip())


def _alias_database_binding(db_file: str) -> tuple[str, tuple[int, int]]:
    path = Path(db_file).expanduser().resolve(strict=True)
    identity = sqlite_file_identity(path)
    if identity is None:
        raise ValueError('The selected database is unavailable. Choose it again and reload name matches.')
    return str(path), identity


def _format_count(value) -> str:
    try:
        return f'{int(value or 0):,}'
    except (TypeError, ValueError):
        return '0'


def _metric_option_name(row: dict[str, object]) -> str:
    return str(row.get('metric_name') or '').strip()


def _reference_option_name(row: dict[str, object]) -> str:
    return str(row.get('reference') or '').strip()


def _build_editable_combo(values: list[str], *, placeholder: str) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    line_edit = combo.lineEdit()
    if line_edit is not None:
        line_edit.setPlaceholderText(placeholder)
    combo.addItems(values)
    completer = combo.completer()
    if completer is not None:
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
    return combo


def _issue_sort_key(issue: dict[str, str | int | None]) -> tuple[int, int, str, str, str]:
    category = str(issue.get('category') or 'validation_error')
    severity_rank = 0 if category == 'duplicate_collision' else 1
    row_number = issue.get('row_number')
    if row_number is None:
        normalized_row = 10**9
    else:
        normalized_row = int(row_number)
    return (
        normalized_row,
        severity_rank,
        category,
        str(issue.get('code') or ''),
        str(issue.get('field') or ''),
    )


def build_remediation_report_rows(
    row_error_details: list[dict[str, str | int | None]],
) -> list[dict[str, str | int | None]]:
    """Convert validation issues to deterministic remediation CSV rows."""
    rows = []
    for entry in sorted(list(row_error_details or []), key=_issue_sort_key):
        rows.append(
            {
                'row_number': entry.get('row_number'),
                'field': entry.get('field'),
                'code': entry.get('code'),
                'category': entry.get('category'),
                'message': entry.get('message'),
                'remediation_hint': entry.get('remediation_hint'),
            }
        )
    return rows


def export_remediation_report_csv(
    destination_path: str,
    row_error_details: list[dict[str, str | int | None]],
) -> int:
    """Write remediation rows to CSV and return number of data rows exported."""
    rows = build_remediation_report_rows(row_error_details)
    with open(destination_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(REMEDIATION_REPORT_HEADERS))
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header) or '' for header in REMEDIATION_REPORT_HEADERS})
    return len(rows)


class _SourceOptionsLoadThread(QThread):
    """Read the report/export names and references of a database off the GUI thread."""

    loaded = pyqtSignal(int, list, list)
    failed = pyqtSignal(int, object)

    def __init__(self, *, request_id: int, db_file: str):
        super().__init__()
        self.request_id = request_id
        self.db_file = db_file
        self._connection_lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None

    def release(self) -> None:
        """Drop the registry reference once the thread has finished."""
        detached_threads.discard(self)

    def interrupt_query(self) -> None:
        """Ask the loader to stop; abort the running SQLite statement, if any."""
        self.requestInterruption()
        with self._connection_lock:
            connection = self._connection
            if connection is not None:
                try:
                    connection.interrupt()
                except sqlite3.Error:
                    pass

    def run(self) -> None:
        try:
            if not Path(self.db_file).is_file():
                metric_options, reference_options = [], []
            else:
                with _readonly_source_options_connection(self.db_file) as connection:
                    with self._connection_lock:
                        self._connection = connection
                    try:
                        if self.isInterruptionRequested():
                            return
                        metric_options = fetch_distinct_report_metric_names(self.db_file, connection=connection)
                        if self.isInterruptionRequested():
                            return
                        reference_options = fetch_distinct_references(self.db_file, connection=connection)
                    finally:
                        with self._connection_lock:
                            self._connection = None
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.request_id, exc)
            return
        if not self.isInterruptionRequested():
            self.loaded.emit(self.request_id, metric_options, reference_options)


class CharacteristicAliasEditorDialog(QDialog):
    """Simple editor used by Add/Edit actions for characteristic mappings."""

    def __init__(
        self,
        parent=None,
        *,
        initial_values=None,
        metric_options=None,
        reference_options=None,
        impact_resolver=None,
    ):
        super().__init__(parent)
        self.setWindowTitle('Edit name match' if initial_values else 'Add new name match')
        configure_window_size(self, minimum=(620, 360), initial=(760, 440))

        self.metric_options = list(metric_options or [])
        self.reference_options = list(reference_options or [])
        self.impact_resolver = impact_resolver
        self.save_match = None
        self._known_metric_names = {
            _metric_option_name(row)
            for row in self.metric_options
            if _metric_option_name(row)
        }
        self._known_references = {
            _reference_option_name(row)
            for row in self.reference_options
            if _reference_option_name(row)
        }

        if initial_values:
            initial_alias = str(initial_values.get('alias_name') or '').strip()
            initial_common = str(initial_values.get('canonical_name') or '').strip()
            initial_reference = str(initial_values.get('scope_value') or '').strip()
        else:
            initial_alias = ''
            initial_common = ''
            initial_reference = ''

        metric_values = sorted(self._known_metric_names, key=str.casefold)
        common_values = list(metric_values)
        for value in (initial_alias, initial_common):
            if value and value not in common_values:
                common_values.insert(0, value)
            if value and value not in metric_values:
                metric_values.insert(0, value)

        reference_values = sorted(self._known_references, key=str.casefold)
        if initial_reference and initial_reference not in reference_values:
            reference_values.insert(0, initial_reference)

        self.alias_input = _build_editable_combo(
            metric_values,
            placeholder='Select or type report/export name',
        )
        self.common_name_input = _build_editable_combo(
            common_values,
            placeholder='Select or type common name',
        )

        self.apply_to_combo = QComboBox()
        self.apply_to_combo.addItems([ALL_REFERENCES_LABEL, ONE_REFERENCE_LABEL])

        self.reference_input = _build_editable_combo(reference_values, placeholder='Select reference')
        self.impact_label = status_chip('Select a report/export name to preview affected rows.', 'neutral')

        if initial_values:
            self.alias_input.setCurrentText(initial_alias)
            self.common_name_input.setCurrentText(initial_common)
            scope_type = str(initial_values.get('scope_type') or 'global').strip().lower()
            if scope_type == 'reference':
                self.apply_to_combo.setCurrentText(ONE_REFERENCE_LABEL)
            else:
                self.apply_to_combo.setCurrentText(ALL_REFERENCES_LABEL)
            self.reference_input.setCurrentText(initial_reference)
        else:
            self.alias_input.setCurrentText('')
            self.common_name_input.setCurrentText('')
            self.reference_input.setCurrentText('')

        layout = QGridLayout(self)
        attach_help_menu_to_layout(layout, self, [("Characteristic matching manual", 'characteristic_name_matching')])

        row = 0
        layout.addWidget(QLabel('Original report/export name'), row, 0)
        layout.addWidget(self.alias_input, row, 1)
        row += 1
        alias_help = QLabel('Pick the name exactly as Metroliza uses it in Group Analysis.')
        alias_help.setWordWrap(True)
        layout.addWidget(alias_help, row, 0, 1, 2)

        row += 1
        layout.addWidget(QLabel('Use this common name'), row, 0)
        layout.addWidget(self.common_name_input, row, 1)
        row += 1
        common_help = QLabel('Group Analysis will use this common name; raw parsed values stay unchanged.')
        common_help.setWordWrap(True)
        layout.addWidget(common_help, row, 0, 1, 2)

        row += 1
        layout.addWidget(QLabel('Apply to'), row, 0)
        layout.addWidget(self.apply_to_combo, row, 1)

        row += 1
        self.reference_label = QLabel('Reference')
        layout.addWidget(self.reference_label, row, 0)
        layout.addWidget(self.reference_input, row, 1)

        row += 1
        layout.addWidget(self.impact_label, row, 0, 1, 2)
        row += 1
        self.save_error_label = status_chip('', 'danger')
        self.save_error_label.setWordWrap(True)
        self.save_error_label.hide()
        layout.addWidget(self.save_error_label, row, 0, 1, 2)

        row += 1
        self.button_box_layout = QHBoxLayout()
        self.save_button = QPushButton('Save match')
        self.clear_button = QPushButton('Clear')
        self.cancel_button = QPushButton('Cancel')
        self.button_box_layout.addWidget(self.save_button)
        self.button_box_layout.addWidget(self.clear_button)
        self.button_box_layout.addWidget(self.cancel_button)
        layout.addLayout(self.button_box_layout, row, 0, 1, 2)

        self.apply_to_combo.currentTextChanged.connect(self._sync_scope_value_state)
        self.apply_to_combo.currentTextChanged.connect(lambda _value: self._refresh_impact_preview())
        self.alias_input.currentTextChanged.connect(lambda _value: self._refresh_impact_preview())
        self.reference_input.currentTextChanged.connect(lambda _value: self._refresh_impact_preview())
        for field in (self.alias_input, self.common_name_input, self.apply_to_combo, self.reference_input):
            field.currentTextChanged.connect(self.save_error_label.hide)
        self.save_button.clicked.connect(self._validate_and_accept)
        self.clear_button.clicked.connect(self._clear_fields)
        self.cancel_button.clicked.connect(self.reject)
        self.save_action = bind_button(self, self.save_button, 'Ctrl+S')
        self.close_action = bind_button(self, self.cancel_button, 'Ctrl+W')
        self._sync_scope_value_state(self.apply_to_combo.currentText())
        self._refresh_impact_preview()
        apply_metroliza_theme(self)

    def _clear_fields(self):
        self.alias_input.setCurrentText('')
        self.common_name_input.setCurrentText('')
        self.apply_to_combo.setCurrentText(ALL_REFERENCES_LABEL)
        self.reference_input.setCurrentText('')
        self._refresh_impact_preview()

    def _sync_scope_value_state(self, selected_scope):
        is_reference_scope = str(selected_scope or '').strip() == ONE_REFERENCE_LABEL
        self.reference_label.setVisible(is_reference_scope)
        self.reference_input.setVisible(is_reference_scope)
        if not is_reference_scope:
            self.reference_input.setCurrentText('')

    def _current_scope_payload(self):
        selected_scope = str(self.apply_to_combo.currentText() or '').strip()
        scope_type = 'reference' if selected_scope == ONE_REFERENCE_LABEL else 'global'
        scope_value = str(self.reference_input.currentText() or '').strip() or None
        return scope_type, scope_value

    def _refresh_impact_preview(self):
        alias_name = str(self.alias_input.currentText() or '').strip()
        scope_type, scope_value = self._current_scope_payload()

        if not alias_name:
            self.impact_label.setText('Select a report/export name to preview affected rows.')
            set_status_variant(self.impact_label, 'neutral')
            return

        if scope_type == 'reference' and not scope_value:
            self.impact_label.setText('Select a reference to preview this reference-only match.')
            set_status_variant(self.impact_label, 'warning')
            return

        if not callable(self.impact_resolver):
            self.impact_label.setText('Impact preview is unavailable for this database.')
            set_status_variant(self.impact_label, 'neutral')
            return

        try:
            impact = self.impact_resolver(alias_name, scope_type, scope_value)
        except Exception as exc:
            CustomLogger(exc, reraise=False, logger_name=__name__)
            self.impact_label.setText('Impact preview could not be loaded.')
            set_status_variant(self.impact_label, 'warning')
            return

        measurements = int(impact.get('measurement_count') or 0)
        reports = int(impact.get('report_count') or 0)
        references = int(impact.get('reference_count') or 0)
        self.impact_label.setText(
            f'Affects {_format_count(measurements)} rows in {_format_count(reports)} reports '
            f'across {_format_count(references)} references.'
        )
        set_status_variant(self.impact_label, 'success' if measurements else 'warning')

    def _validate_and_accept(self):
        alias_name = str(self.alias_input.currentText() or '').strip()
        common_name = str(self.common_name_input.currentText() or '').strip()
        scope_type, scope_value = self._current_scope_payload()

        if not alias_name:
            QMessageBox.warning(self, 'Validation error', 'Please select the original report/export name.')
            return

        if not common_name:
            QMessageBox.warning(self, 'Validation error', 'Please enter the common name to use.')
            return

        if scope_type == 'reference' and not scope_value:
            QMessageBox.warning(self, 'Validation error', 'Please select a reference.')
            return

        try:
            normalize_scope_type(scope_type, scope_value)
        except ValueError as exc:
            QMessageBox.warning(self, 'Validation error', str(exc))
            return

        payload = {
            'alias_name': alias_name,
            'canonical_name': common_name,
            'scope_type': scope_type,
            'scope_value': scope_value,
        }
        if self._commit_match(payload):
            self._result_payload = payload
            self.accept()

    def _commit_match(self, payload):
        if self.save_match is None:
            return True
        try:
            self.save_match(payload)
        except ValueError as exc:
            self.save_error_label.setText(str(exc))
            self.alias_input.setFocus()
        except (OSError, sqlite3.Error):
            self.save_error_label.setText('Could not save the match. Check the database and retry.')
        else:
            return True
        self.save_error_label.show()
        return False

    @property
    def result_payload(self):
        return getattr(self, '_result_payload', None)


class CharacteristicMappingDialog(QDialog):
    """Manage report-name-to-common-name mappings."""

    TABLE_HEADERS = ['Original export name', 'Use this common name', 'Apply to', 'Reference']

    def __init__(self, parent=None, db_file='', *, modal=True):
        super().__init__(parent)
        self.setWindowTitle('Characteristic Name Matching')
        if parent is not None and hasattr(parent, 'windowIcon'):
            self.setWindowIcon(parent.windowIcon())
        self.setModal(modal)
        configure_window_size(self, minimum=(680, 480), initial=(1180, 740))

        self.db_file = db_file
        self._loaded_alias_database_path: str | None = None
        self._loaded_alias_database_identity: tuple[int, int] | None = None
        self._loaded_alias_scope_rows = {}
        self._conflicting_alias_scopes = set()
        self.database_change_allowed = None
        self.report_database_is_current = None
        self.metric_options: list[dict[str, object]] = []
        self.reference_options: list[dict[str, object]] = []
        self._source_request_id = 0
        self._source_loading = False
        self._source_load_canceled = False
        self._source_thread: _SourceOptionsLoadThread | None = None
        self._source_progress_dialog = None
        if type(self) is CharacteristicMappingDialog:
            self._alias_csv_thread = None
            self._alias_csv_progress = None
            self._alias_csv_controls = ()
            self._alias_csv_selection_controls = ()
            self._alias_csv_close_result = None

        self.subtitle_label = QLabel(
            'Map report/export names so Group Analysis treats equivalent characteristics as one metric.'
        )
        self.subtitle_label.setWordWrap(True)
        self.matching_section_label = section_label('Name matches')

        self.db_label = QLabel('Database file:')
        self.db_path_input = QLineEdit(str(db_file or ''))
        self.db_path_input.setReadOnly(True)
        self.select_db_button = QPushButton('Browse DB')
        self.db_warning_label = status_chip('Select a database file to manage name matches.', 'warning')

        self.available_section_label = section_label('Report/export names in this database')
        self.metric_search_input = QLineEdit()
        self.metric_search_input.setPlaceholderText('Search report/export names or references')
        self.metric_table = QTableWidget(0, len(SOURCE_TABLE_HEADERS), self)
        self.metric_table.setHorizontalHeaderLabels(SOURCE_TABLE_HEADERS)
        self.metric_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.metric_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.metric_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.metric_table.itemSelectionChanged.connect(self._sync_selection_actions)
        self.metric_empty_label = status_chip('Select a database to load report/export names.', 'neutral')

        self.table_title_label = section_label('Saved name matches')
        self.alias_search_input = QLineEdit()
        self.alias_search_input.setPlaceholderText('Search saved matches [Ctrl+F]')
        self.alias_search_input.setAccessibleName('Search saved name matches')
        self.alias_match_count = QLabel()

        self.empty_state_label = QLabel(
            'No name matches have been added yet.\n'
            'Select a report/export name on the left, then add a match.'
        )
        self.empty_state_label.setWordWrap(True)
        self.empty_warning_label = status_chip(
            'No mappings are currently stored in this database.',
            'warning',
        )
        self.collision_warning_label = status_chip(
            ALIAS_INFO_TEXT,
            'info',
        )

        self.alias_table = QTableWidget(0, len(self.TABLE_HEADERS), self)
        self.alias_table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.alias_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.alias_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.alias_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.alias_table.itemSelectionChanged.connect(self._sync_selection_actions)

        self.add_from_selected_button = QPushButton('Add from selected')
        self.add_button = QPushButton('Add manually')
        self.edit_button = QPushButton('Edit selected')
        self.delete_button = QPushButton('Delete selected')
        self.import_button = QPushButton('Import CSV')
        self.export_button = QPushButton('Export CSV')
        self.close_button = QPushButton('Close')

        table_actions_row = QHBoxLayout()
        table_actions_row.addWidget(self.add_from_selected_button)
        table_actions_row.addWidget(self.add_button)
        table_actions_row.addWidget(self.edit_button)
        table_actions_row.addWidget(self.delete_button)
        table_actions_row.addStretch()

        io_actions_row = QHBoxLayout()
        io_actions_row.addWidget(self.import_button)
        io_actions_row.addWidget(self.export_button)
        io_actions_row.addStretch()

        footer_row = QVBoxLayout()
        footer_row.addLayout(table_actions_row)
        io_actions_row.addWidget(self.close_button)
        footer_row.addLayout(io_actions_row)
        self.persistence_label = QLabel(
            'Successful changes save immediately to the database shown above. Close does not undo saved matches.')
        self.persistence_label.setWordWrap(True)

        db_row = QHBoxLayout()
        db_row.addWidget(self.db_label)
        db_row.addWidget(self.db_path_input, 1)
        db_row.addWidget(self.select_db_button)

        layout = QVBoxLayout(self)
        attach_help_menu_to_layout(layout, self, [("Characteristic matching manual", 'characteristic_name_matching')])
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.matching_section_label)
        layout.addLayout(db_row)
        layout.addWidget(self.db_warning_label)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        available_layout = QVBoxLayout()
        available_layout.addWidget(self.available_section_label)
        available_layout.addWidget(self.metric_search_input)
        available_layout.addWidget(self.metric_empty_label)
        available_layout.addWidget(self.metric_table)

        saved_layout = QVBoxLayout()
        saved_layout.addWidget(self.table_title_label)
        saved_layout.addWidget(self.alias_search_input)
        saved_layout.addWidget(self.alias_match_count)
        saved_layout.addWidget(self.empty_state_label)
        saved_layout.addWidget(self.empty_warning_label)
        saved_layout.addWidget(self.collision_warning_label)
        saved_layout.addWidget(self.alias_table)

        content_row.addLayout(available_layout, 3)
        content_row.addLayout(saved_layout, 4)
        body = QWidget()
        body.setLayout(content_row)
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setWidget(body)
        self.content_scroll.setMinimumSize(0, 0)
        layout.addWidget(self.content_scroll, 1)
        layout.addWidget(self.persistence_label)
        layout.addLayout(footer_row)

        self.metric_search_input.textChanged.connect(lambda _text: self._populate_metric_table())
        self.alias_search_input.textChanged.connect(self._filter_alias_table)
        self.add_from_selected_button.clicked.connect(self.add_selected_mapping)
        self.add_button.clicked.connect(lambda: self.add_mapping())
        self.edit_button.clicked.connect(self.edit_mapping)
        self.delete_button.clicked.connect(self.delete_mapping)
        self.import_button.clicked.connect(self.import_mappings)
        self.export_button.clicked.connect(self.export_mappings)
        self.close_button.clicked.connect(self.accept)
        self.select_db_button.clicked.connect(self.select_db_file)
        configure_dialog_button_roles(quiet=(self.close_button,), secondary=(
            self.add_from_selected_button, self.add_button, self.edit_button, self.delete_button,
            self.import_button, self.export_button, self.select_db_button))
        self.add_action = bind_button(self, self.add_button, 'Ctrl+E')
        self.edit_action = bind_button(self, self.edit_button, 'Ctrl+Shift+E')
        self.close_action = bind_button(self, self.close_button, 'Ctrl+W')
        self.search_action = bind_search_shortcut(self, [(self.metric_search_input, self.metric_table),
                                                         (self.alias_search_input, self.alias_table)])
        self.metric_search_input.setPlaceholderText('Search names or references [Ctrl+F]')
        install_button_commands(self, "mapping")

        configure_table(self.metric_table, stretch_column=0, resize_to_contents=(1, 2, 3), min_height=280)
        metric_header = self.metric_table.horizontalHeader()
        metric_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metric_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        configure_table(self.alias_table, stretch_column=1, resize_to_contents=(2, 3), min_height=280)
        header = self.alias_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.alias_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        set_status_variant(self.collision_warning_label, 'info')
        self.load_aliases()
        self.load_source_options()
        self._sync_selection_actions()
        self._sync_warning_labels()
        apply_metroliza_theme(self)

    def _scope_display_values(self, scope_type, scope_value):
        if str(scope_type or '').strip().lower() == 'reference':
            return ONE_REFERENCE_LABEL, str(scope_value or '')
        return ALL_REFERENCES_LABEL, '—'

    def _scope_from_display(self, apply_to, reference_value):
        if str(apply_to or '').strip() == ONE_REFERENCE_LABEL:
            return 'reference', str(reference_value or '').strip() or None
        return 'global', None

    def _selected_metric_option(self):
        selected_rows = self.metric_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        item = self.metric_table.item(row, 0)
        if item is None:
            return None
        option = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(option, dict):
            return option
        metric_name = str(item.text() or '').strip()
        return {'metric_name': metric_name} if metric_name else None

    def _sync_selection_actions(self):
        if _alias_csv_busy(self):
            return
        has_db = _has_selected_db_file(self.db_file)
        has_metric_selection = self._selected_metric_option() is not None
        has_selection = self._selected_mapping() is not None
        key, row = self._selected_alias_storage()
        conflicting = key in self._conflicting_alias_scopes
        multiple = len(self._loaded_alias_scope_rows.get(key, ())) > 1
        options_ready = not self._source_loading
        self.add_button.setEnabled(has_db and options_ready)
        self.add_from_selected_button.setEnabled(has_db and options_ready and has_metric_selection)
        self.import_button.setEnabled(has_db and options_ready)
        self.export_button.setEnabled(has_db)
        self.edit_button.setText('Resolve conflict' if conflicting else 'Edit selected')
        can_select_target = not conflicting or (row[0] is not None and bool(str(row[2] or '').strip()))
        self.edit_button.setEnabled(has_db and options_ready and has_selection and can_select_target)
        self.delete_button.setEnabled(has_db and options_ready and has_selection and not multiple)

    def _selected_alias_storage(self):
        selected = self.alias_table.selectionModel().selectedRows()
        if not selected or self.alias_table.isRowHidden(selected[0].row()):
            return None, None
        item = self.alias_table.item(selected[0].row(), 0)
        row = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(row, tuple) or len(row) != 5:
            return None, None
        return effective_alias_scope(row[1], row[3], row[4]), row

    def _sync_warning_labels(self):
        has_db = bool(str(self.db_file or '').strip())
        has_aliases = self.alias_table.rowCount() > 0
        self.db_warning_label.setVisible(not has_db)
        self.empty_warning_label.setVisible(has_db and not has_aliases)
        if not has_db:
            self.metric_empty_label.setText('Select a database to load report/export names.')
            set_status_variant(self.metric_empty_label, 'neutral')
            self.metric_empty_label.setVisible(True)
        elif self._source_loading:
            self.metric_empty_label.setText(SOURCE_LOADING_TEXT)
            set_status_variant(self.metric_empty_label, 'neutral')
            self.metric_empty_label.setVisible(True)
        elif self._source_load_canceled:
            self.metric_empty_label.setText(SOURCE_LOAD_CANCELED_TEXT)
            set_status_variant(self.metric_empty_label, 'warning')
            self.metric_empty_label.setVisible(True)
        elif not self.metric_options:
            self.metric_empty_label.setText('No report/export names were found in this database.')
            set_status_variant(self.metric_empty_label, 'warning')
            self.metric_empty_label.setVisible(True)
        elif self.metric_table.rowCount() == 0:
            self.metric_empty_label.setText('No report/export names match the current search.')
            set_status_variant(self.metric_empty_label, 'warning')
            self.metric_empty_label.setVisible(True)
        else:
            self.metric_empty_label.setVisible(False)

    def select_db_file(self):
        from metroliza.shared.sqlite_paths import SQLITE_FILE_FILTER, sqlite_database_path

        if _alias_csv_busy(self):
            return
        if self.database_change_allowed is not None and not self.database_change_allowed():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Select a database file',
            str(self.db_file or ''),
            SQLITE_FILE_FILTER,
        )
        if not filename or _alias_csv_busy(self):
            return
        if self.database_change_allowed is not None and not self.database_change_allowed():
            return
        filename = sqlite_database_path(filename)
        parent = self.parent()
        if parent is not None and hasattr(parent, 'set_db_file'):
            if parent.set_db_file(filename) is False:
                return
        self.db_file = filename
        self.db_path_input.setText(filename)
        refresh_notice = getattr(parent, 'refresh_characteristic_mapping_database_notice', None)
        if callable(refresh_notice):
            refresh_notice()
        self.load_aliases()
        self.load_source_options()

    def is_loading_source_options(self) -> bool:
        """Return True while the report/export names are being read in the background."""
        return self._source_loading

    def load_source_options(self):
        self._stop_source_loading()
        self._source_load_canceled = False
        self.metric_options = []
        self.reference_options = []
        if not self.db_file:
            self._populate_metric_table()
            return

        self._source_loading = True
        (
            self._source_progress_dialog,
            _loading_label,
            loading_bar,
            _loading_gif,
        ) = create_delayed_worker_progress_dialog(
            self,
            window_title=SOURCE_LOADING_TEXT,
            initial_status_text=f'{SOURCE_LOADING_TEXT}\nReading the database\nETA --',
            on_cancel=self._cancel_source_loading,
        )
        loading_bar.setRange(0, 0)

        thread = _SourceOptionsLoadThread(request_id=self._source_request_id, db_file=str(self.db_file))
        self._source_thread = thread
        detached_threads.register(thread)
        thread.loaded.connect(self._on_source_options_loaded)
        thread.failed.connect(self._on_source_options_failed)
        thread.finished.connect(thread.release)
        self._populate_metric_table()
        thread.start()
        self._source_progress_dialog.show()

    def _dismiss_source_progress_dialog(self) -> None:
        progress_dialog = self._source_progress_dialog
        self._source_progress_dialog = None
        if progress_dialog is not None:
            dismiss_worker_progress_dialog(progress_dialog)
            progress_dialog.deleteLater()

    def _stop_source_loading(self, *, wait_ms: int | None = None) -> None:
        """Invalidate any pending load; interrupt its thread and wait a bounded time for it."""
        self._source_request_id += 1
        self._source_loading = False
        self._dismiss_source_progress_dialog()
        thread = self._source_thread
        self._source_thread = None
        if thread is None:
            return
        for signal, slot in (
            (thread.loaded, self._on_source_options_loaded),
            (thread.failed, self._on_source_options_failed),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        thread.interrupt_query()
        if thread.wait(SOURCE_LOAD_STOP_WAIT_MS if wait_ms is None else wait_ms):
            thread.release()

    def _cancel_source_loading(self) -> None:
        self._stop_source_loading()
        self._source_load_canceled = True
        self._populate_metric_table()

    def _on_source_options_loaded(self, request_id, metric_options, reference_options):
        if request_id != self._source_request_id or not self._source_loading:
            return
        self._source_loading = False
        self._dismiss_source_progress_dialog()
        self.metric_options = list(metric_options)
        self.reference_options = list(reference_options)
        self._populate_metric_table()

    def _on_source_options_failed(self, request_id, exc):
        if request_id != self._source_request_id or not self._source_loading:
            return
        self._source_loading = False
        self._dismiss_source_progress_dialog()
        CustomLogger(exc, reraise=False, logger_name=__name__)
        self.metric_options = []
        self.reference_options = []
        self._populate_metric_table()
        QMessageBox.critical(self, 'Load error', f'Could not load report/export names: {exc}')

    def done(self, result):
        if CharacteristicMappingDialog._abandon_alias_csv(self, result):
            return
        self._stop_source_loading()
        super().done(result)

    def closeEvent(self, event):
        if CharacteristicMappingDialog._abandon_alias_csv(self, QDialog.DialogCode.Rejected):
            event.ignore()
            return
        self._stop_source_loading()
        super().closeEvent(event)

    def _metric_option_matches_filter(self, option, search_text):
        if not search_text:
            return True
        haystack = ' '.join(
            str(value or '')
            for value in (
                option.get('metric_name'),
                option.get('sample_references'),
                option.get('measurement_count'),
                option.get('report_count'),
                option.get('reference_count'),
            )
        ).lower()
        return search_text.lower() in haystack

    def _populate_metric_table(self):
        search_text = str(self.metric_search_input.text() or '').strip()
        filtered_options = [
            option
            for option in self.metric_options
            if self._metric_option_matches_filter(option, search_text)
        ]
        self.metric_table.setRowCount(len(filtered_options))
        for row_index, option in enumerate(filtered_options):
            values = [
                _metric_option_name(option),
                _format_count(option.get('reference_count')),
                _format_count(option.get('report_count')),
                _format_count(option.get('measurement_count')),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index in {1, 2, 3}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, option)
                    sample_references_value = option.get('sample_references') or ''
                    if isinstance(sample_references_value, (list, tuple)):
                        sample_references = ', '.join(str(value) for value in sample_references_value if str(value).strip())
                    else:
                        sample_references = str(sample_references_value).strip()
                    if sample_references:
                        item.setToolTip(f'References: {sample_references}')
                self.metric_table.setItem(row_index, column_index, item)
        self._sync_selection_actions()
        self._sync_warning_labels()

    def load_aliases(self):
        native_read = (
            ensure_characteristic_alias_schema is _DEFAULT_ALIAS_SCHEMA
            and fetch_all_characteristic_aliases is _DEFAULT_ALIAS_FETCH
        )
        if not self.db_file or (native_read and not Path(self.db_file).is_file()):
            self._clear_alias_rows()
            return

        try:
            loaded_path, loaded_identity, alias_rows = self._load_alias_rows()
        except Exception as exc:
            self._invalidate_loaded_aliases()
            self.alias_table.setRowCount(0)
            self._sync_alias_scope_warning()
            CustomLogger(exc, reraise=False, logger_name=__name__)
            QMessageBox.critical(self, 'Load error', f'Could not load name matches: {exc}')
            return

        self._loaded_alias_database_path = loaded_path
        self._loaded_alias_database_identity = loaded_identity

        identities = [tuple(row.get(name) for name in ('id', 'alias_name', 'canonical_name', 'scope_type', 'scope_value'))
                      for row in alias_rows]
        scopes = {}
        for row in identities:
            scopes.setdefault(effective_alias_scope(row[1], row[3], row[4]), []).append(row)
        self._loaded_alias_scope_rows = {
            key: tuple(sorted(rows, key=lambda row: row[0] or 0)) for key, rows in scopes.items()
        }
        self._conflicting_alias_scopes = {
            key for key, rows in scopes.items()
            if key[1] in ('global', 'reference') and conflicting_alias_targets(key[0], (row[2] for row in rows))
        }

        self.alias_table.setRowCount(len(alias_rows))
        for row_index, row in enumerate(alias_rows):
            apply_to, reference_display = self._scope_display_values(row.get('scope_type'), row.get('scope_value'))
            values = [
                str(row.get('alias_name') or ''),
                str(row.get('canonical_name') or ''),
                apply_to,
                reference_display,
            ]
            for column_index, value in enumerate(values):
                self.alias_table.setItem(row_index, column_index, QTableWidgetItem(value))
            identity = identities[row_index]
            alias_item = self.alias_table.item(row_index, 0)
            alias_item.setData(Qt.ItemDataRole.UserRole, identity)
            if effective_alias_scope(identity[1], identity[3], identity[4]) in self._conflicting_alias_scopes:
                alias_item.setToolTip('Conflicting common names for this scope. Select the name to keep and resolve the conflict.')

        self.empty_state_label.setVisible(len(alias_rows) == 0)
        self._sync_alias_scope_warning()
        self._filter_alias_table()
        self._sync_warning_labels()

    def _load_alias_rows(self):
        if (
            ensure_characteristic_alias_schema is _DEFAULT_ALIAS_SCHEMA
            and fetch_all_characteristic_aliases is _DEFAULT_ALIAS_FETCH
        ):
            selected_path = Path(self.db_file).expanduser().resolve(strict=True)
            selected_identity = sqlite_file_identity(selected_path, include_empty=True)
            if selected_identity is None:
                raise ValueError('The selected database is unavailable. Reload the name matches.')
            with sqlite_readonly_connection_scope(str(selected_path), resolve_path=False) as connection:
                if sqlite_file_identity(selected_path, include_empty=True) != selected_identity:
                    raise ValueError('The selected database changed while name matches were loading.')
                alias_table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND lower(name) = lower(?) LIMIT 1",
                    (CHARACTERISTIC_ALIAS_TABLE,),
                ).fetchone()
                if alias_table_exists is None:
                    alias_rows = []
                else:
                    alias_rows = fetch_all_characteristic_aliases(self.db_file, connection=connection, include_identity=True)
                if sqlite_file_identity(selected_path, include_empty=True) != selected_identity:
                    raise ValueError('The selected database changed while name matches were loading. Reload the list.')
            return str(selected_path), selected_identity, alias_rows

        ensure_characteristic_alias_schema(self.db_file)
        loaded_path, loaded_identity = _alias_database_binding(self.db_file)
        if fetch_all_characteristic_aliases is _DEFAULT_ALIAS_FETCH:
            with sqlite_readonly_connection_scope(self.db_file) as connection:
                alias_rows = fetch_all_characteristic_aliases(self.db_file, connection=connection, include_identity=True)
        else:
            alias_rows = fetch_all_characteristic_aliases(self.db_file)
        if _alias_database_binding(self.db_file) != (loaded_path, loaded_identity):
            raise ValueError('The selected database changed while name matches were loading. Reload the list.')
        return loaded_path, loaded_identity, alias_rows

    def _clear_alias_rows(self):
        self._invalidate_loaded_aliases()
        self.alias_table.setRowCount(0)
        self.empty_state_label.setVisible(True)
        self._sync_alias_scope_warning()
        self._sync_selection_actions()
        self._sync_warning_labels()

    def _invalidate_loaded_aliases(self):
        self._loaded_alias_database_path = None
        self._loaded_alias_database_identity = None
        self._loaded_alias_scope_rows = {}
        self._conflicting_alias_scopes = set()

    def _sync_alias_scope_warning(self):
        count = len(self._conflicting_alias_scopes)
        self.collision_warning_label.setText(
            f'{count} conflicting name match scope(s). Select the common name to keep, then choose Resolve conflict.'
            if count else ALIAS_INFO_TEXT
        )
        set_status_variant(self.collision_warning_label, 'warning' if count else 'info')

    def _loaded_alias_database_matches_current(self):
        if self._loaded_alias_database_path is None or self._loaded_alias_database_identity is None:
            return False
        try:
            return _alias_database_binding(self.db_file) == (
                self._loaded_alias_database_path, self._loaded_alias_database_identity,
            )
        except (OSError, RuntimeError, ValueError):
            return False

    def _filter_alias_table(self):
        needle = self.alias_search_input.text().strip().casefold()
        visible = 0
        for row in range(self.alias_table.rowCount()):
            matches = any(needle in self.alias_table.item(row, column).text().casefold()
                          for column in (0, 1, 3) if self.alias_table.item(row, column) is not None)
            self.alias_table.setRowHidden(row, not matches)
            visible += matches
        self.alias_match_count.setText(
            f"{visible} saved matches shown" if visible else "No saved matches found",
        )
        self._sync_selection_actions()

    def _resolve_impact_preview(self, alias_name, scope_type, scope_value):
        if not self.db_file:
            return {'measurement_count': 0, 'report_count': 0, 'reference_count': 0}
        return fetch_mapping_impact_counts(
            self.db_file,
            alias_name=alias_name,
            scope_type=scope_type,
            scope_value=scope_value,
        )

    def _selected_mapping(self):
        if not self._loaded_alias_database_matches_current():
            return None
        selected_rows = self.alias_table.selectionModel().selectedRows()
        if not selected_rows:
            return None

        row = selected_rows[0].row()
        if self.alias_table.isRowHidden(row):
            return None
        apply_to = self.alias_table.item(row, 2).text()
        reference_display = self.alias_table.item(row, 3).text()
        scope_type, scope_value = self._scope_from_display(apply_to, reference_display)

        return {
            'alias_name': self.alias_table.item(row, 0).text(),
            'canonical_name': self.alias_table.item(row, 1).text(),
            'scope_type': scope_type,
            'scope_value': scope_value,
        }

    def _build_editor(self, *, initial_values=None):
        return CharacteristicAliasEditorDialog(
            self,
            initial_values=initial_values,
            metric_options=self.metric_options,
            reference_options=self.reference_options,
            impact_resolver=self._resolve_impact_preview,
        )

    def add_selected_mapping(self):
        if _alias_csv_busy(self):
            return
        selected_metric = self._selected_metric_option()
        if selected_metric is None:
            return
        metric_name = _metric_option_name(selected_metric)
        self.add_mapping(
            {
                'alias_name': metric_name,
                'canonical_name': metric_name,
                'scope_type': 'global',
                'scope_value': None,
            }
        )

    def add_mapping(self, initial_values=None):
        self._open_mapping_editor(initial_values)

    def edit_mapping(self):
        selected = self._selected_mapping()
        if selected is not None:
            key, row = self._selected_alias_storage()
            if key in self._conflicting_alias_scopes:
                self._resolve_alias_conflict(key, row)
            else:
                self._open_mapping_editor(selected, previous=selected)

    def _resolve_alias_conflict(self, key, row):
        if _alias_csv_busy(self) or self._source_loading or row[0] is None or not str(row[2] or '').strip():
            return
        expected = self._loaded_alias_scope_rows[key]
        path, identity = self._loaded_alias_database_path, self._loaded_alias_database_identity
        scope = escape(str(key[2])) if key[1] == 'reference' else ALL_REFERENCES_LABEL
        text = (
            f'Use {escape(row[2])} for {escape(row[1])} in this scope?\n\n'
            f'Scope: {scope}\n{len(expected)} saved rows will use the selected common name.'
        )
        if QMessageBox.question(
            self, 'Resolve name match conflict', text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if _alias_csv_busy(self) or self._source_loading:
            return
        _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EDIT_STARTED)
        try:
            repair_characteristic_alias_conflict(
                self.db_file, key, expected, row[0], expected_database_path=path, expected_database_identity=identity,
            )
        except (OSError, sqlite3.Error, ValueError):
            _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EDIT_FAILED)
            QMessageBox.warning(self, 'Name match conflict', 'Could not resolve the conflict. Reload the name matches and try again.')
            return
        self.load_aliases()
        _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EDIT_COMPLETED)

    def _open_mapping_editor(self, initial_values, previous=None):
        if _alias_csv_busy(self) or not CharacteristicMappingDialog._ensure_existing_database_for_write(self):
            return
        editor = self._build_editor(initial_values=initial_values)
        database = self.db_file
        if previous is None:
            started = BugReportAction.WORKFLOW_MAPPING_ADD_STARTED
            failed = BugReportAction.WORKFLOW_MAPPING_ADD_FAILED
            completed = BugReportAction.WORKFLOW_MAPPING_ADD_COMPLETED
        else:
            started = BugReportAction.WORKFLOW_MAPPING_EDIT_STARTED
            failed = BugReportAction.WORKFLOW_MAPPING_EDIT_FAILED
            completed = BugReportAction.WORKFLOW_MAPPING_EDIT_COMPLETED

        def save_match(payload):
            _record_mapping_action(started)
            try:
                save_manual_characteristic_alias(database, payload, previous)
            except Exception:
                _record_mapping_action(failed)
                raise
            _record_mapping_action(completed)

        editor.save_match = save_match
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.load_aliases()

    def delete_mapping(self):
        if _alias_csv_busy(self):
            return
        selected = self._selected_mapping()
        if selected is None:
            if self.alias_table.selectionModel().selectedRows() and not self._loaded_alias_database_matches_current():
                QMessageBox.warning(
                    self, 'Database changed',
                    'The selected database changed after this list was loaded. Reload the name matches and review the rule again.',
                )
                self.load_aliases()
            return
        key, _row = self._selected_alias_storage()
        if len(self._loaded_alias_scope_rows.get(key, ())) > 1:
            QMessageBox.warning(self, 'Multiple name matches', 'This scope has more than one saved row. Delete is unavailable.')
            return

        loaded_database_path = self._loaded_alias_database_path
        loaded_database_identity = self._loaded_alias_database_identity
        alias_name = escape(selected['alias_name'])
        canonical_name = escape(selected['canonical_name'])
        scope_value = escape(selected['scope_value'] or '')
        scope_detail = f" ({scope_value})" if scope_value else ''
        try:
            impact = self._resolve_impact_preview(
                selected['alias_name'], selected['scope_type'], selected['scope_value'],
            )
            impact_detail = (
                f"Affects {int(impact.get('measurement_count', 0))} measurement rows in "
                f"{int(impact.get('report_count', 0))} reports."
            )
        except Exception:
            impact_detail = 'The affected report and measurement count is unavailable.'
        confirmation_text = (
            f"Delete this saved rule?\n\n"
            f"{alias_name} → {canonical_name}\n"
            f"Scope: {escape(selected['scope_type'])}{scope_detail}\n\n"
            f"{impact_detail}\n\n"
            'Export name matches to CSV before deleting if you may need to restore the rule.\n'
            'It will no longer be applied to future work.'
        )
        if QMessageBox.question(
            self, 'Delete name match', confirmation_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        if (
            not self._loaded_alias_database_matches_current()
            or (self._loaded_alias_database_path, self._loaded_alias_database_identity)
            != (loaded_database_path, loaded_database_identity)
        ):
            QMessageBox.warning(
                self, 'Database changed',
                'The selected database changed while deletion was being confirmed. Reload the name matches and review the rule again.',
            )
            self.load_aliases()
            return

        _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_DELETE_STARTED)
        try:
            delete_characteristic_alias(
                loaded_database_path,
                alias_name=selected['alias_name'],
                scope_type=selected['scope_type'],
                scope_value=selected['scope_value'],
                expected_mapping=selected,
                expected_database_path=loaded_database_path,
                expected_database_identity=loaded_database_identity,
            )
            self.load_aliases()
            _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_DELETE_COMPLETED)
        except ValueError as exc:
            _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_DELETE_FAILED)
            QMessageBox.warning(self, 'Name match changed', str(exc))
        except Exception as exc:
            _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_DELETE_FAILED)
            CustomLogger(exc, reraise=False, logger_name=__name__)
            QMessageBox.critical(self, 'Delete error', f'Could not delete name match: {exc}')

    def _ensure_db_file_selected(self) -> bool:
        if _has_selected_db_file(self.db_file):
            return True
        QMessageBox.warning(self, 'Database required', 'Please select a database file first.')
        return False

    def _ensure_existing_database_for_write(self) -> bool:
        if not self._ensure_db_file_selected():
            return False
        guard = getattr(self, 'report_database_is_current', None)
        if guard is None:
            return True
        if not Path(self.db_file).is_file():
            QMessageBox.warning(
                self,
                'Database required',
                'The selected database has not been created yet. Open or create it in Reports before editing, importing, or exporting name matches.',
            )
            return False
        return guard(self.db_file)

    def _build_import_validation_summary(self, error: CharacteristicAliasImportValidationError, *, preview_limit: int = 10):
        details = list(error.row_error_details or [])
        if not details:
            details = [
                {
                    'row_number': None,
                    'field': 'unknown',
                    'code': 'validation_error',
                    'category': 'validation_error',
                    'remediation_hint': 'Review the CSV row and correct invalid values.',
                    'message': row_error,
                }
                for row_error in error.row_errors
            ]

        details = sorted(details, key=_issue_sort_key)
        duplicate_conflicts = [entry for entry in details if str(entry.get('category') or '') == 'duplicate_collision']
        other_issues = [entry for entry in details if str(entry.get('category') or '') != 'duplicate_collision']

        grouped_categories: dict[str, int] = {}
        for entry in details:
            category = str(entry.get('category') or 'validation_error')
            grouped_categories[category] = grouped_categories.get(category, 0) + 1

        processed = error.total_rows_processed
        if processed <= 0:
            processed = len({entry.get('row_number') for entry in details if entry.get('row_number') is not None})
        invalid_rows = len({entry.get('row_number') for entry in details if entry.get('row_number') is not None}) or len(details)
        valid_rows = max(0, processed - invalid_rows)

        summary_lines = [
            'Could not import mappings due to CSV validation errors.',
            f'Total rows processed: {processed}',
            f'Valid rows: {valid_rows}',
            f'Invalid rows: {invalid_rows}',
            'Error categories:',
        ]
        for category in sorted(grouped_categories):
            summary_lines.append(f'  - {category}: {grouped_categories[category]}')

        summary_lines.append('')
        summary_lines.append('What to fix first:')
        if duplicate_conflicts:
            summary_lines.append('  1) Remove duplicate alias/scope key rows to keep imports atomic and deterministic.')
            summary_lines.append('  2) For each duplicate key, choose one scope strategy: global or reference-only.')
        summary_lines.append('  3) Fix missing/invalid field values listed below and retry import.')

        summary_lines.append('')
        summary_lines.append(f'First {min(preview_limit, len(details))} row issue(s) (conflicts first):')
        for entry in (duplicate_conflicts + other_issues)[:preview_limit]:
            summary_lines.append(
                f"- Row {entry.get('row_number')} [{entry.get('field')}] ({entry.get('code')}): "
                f"{entry.get('message')} Fix: {entry.get('remediation_hint')}"
            )

        detail_lines = [
            'CSV Validation Report',
            f'Total rows processed: {processed}',
            f'Valid rows: {valid_rows}',
            f'Invalid rows: {invalid_rows}',
            '',
        ]
        detail_lines.append('Conflict-first sections:')
        if duplicate_conflicts:
            detail_lines.append('duplicate_collision:')
            for index, entry in enumerate(duplicate_conflicts, start=1):
                detail_lines.append(
                    f"  {index}. row={entry.get('row_number')} field={entry.get('field')} code={entry.get('code')} "
                    f"category={entry.get('category')} message={entry.get('message')} remediation={entry.get('remediation_hint')}"
                )
            detail_lines.append('')

        detail_lines.append('other_validation_issues:')
        for index, entry in enumerate(other_issues, start=1):
            detail_lines.append(
                f"  {index}. row={entry.get('row_number')} field={entry.get('field')} code={entry.get('code')} "
                f"category={entry.get('category')} message={entry.get('message')} remediation={entry.get('remediation_hint')}"
            )

        summary_lines.append('')
        summary_lines.append('Open Details to copy the full validation report.')
        return '\n'.join(summary_lines), '\n'.join(detail_lines)

    def import_mappings(self):
        started_at = time.monotonic()
        if _alias_csv_busy(self):
            return
        if not CharacteristicMappingDialog._ensure_existing_database_for_write(self):
            return

        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Import name matches',
            str(self.db_file or ''),
            'CSV files (*.csv);;All files (*)',
        )
        if not filename:
            return

        _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_IMPORT_STARTED)

        if type(filename) is str and _native_alias_csv(self):
            CharacteristicMappingDialog._start_alias_csv(self, 'import', filename, started_at)
            return

        def produce():
            if import_characteristic_aliases_csv is not _DEFAULT_ALIAS_IMPORT:
                ensure_characteristic_alias_schema(self.db_file)
                return import_characteristic_aliases_csv(self.db_file, filename)
            plan = preview_characteristic_aliases_csv(self.db_file, filename)
            choice = self._confirm_alias_import(plan)
            if choice is not None:
                try:
                    _bugreport_recorder.record(
                        BugReportAction.OPTION_MAPPING_REPLACE_EXISTING, enabled=bool(choice)
                    )
                except Exception:
                    pass
            return None if choice is None else apply_characteristic_alias_import(self.db_file, plan, replace=choice)

        CharacteristicMappingDialog._apply_alias_import(self, produce)

    def _apply_alias_import(self, producer, *, record_outcome=True):
        try:
            imported_count = producer()
            if imported_count is None:
                _record_mapping_action_if(
                    record_outcome, BugReportAction.WORKFLOW_MAPPING_IMPORT_CANCELLED
                )
                return
            self.load_aliases()
            _record_mapping_action_if(
                record_outcome, BugReportAction.WORKFLOW_MAPPING_IMPORT_COMPLETED
            )
            QMessageBox.information(self, 'Import complete', f'Imported {imported_count} mapping row(s).')
        except CharacteristicAliasImportValidationError as exc:
            _record_mapping_action_if(
                record_outcome, BugReportAction.WORKFLOW_MAPPING_IMPORT_FAILED
            )
            CustomLogger(exc, reraise=False, logger_name=__name__)
            message, full_report = self._build_import_validation_summary(exc, preview_limit=10)
            details_box = QMessageBox(self)
            details_box.setIcon(QMessageBox.Icon.Critical)
            details_box.setWindowTitle('Import error')
            details_box.setText(message)
            details_box.setDetailedText(full_report)
            details_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            try:
                details_box.exec()
            finally:
                detached_threads.delete_on_owner_thread(details_box)

            if _alias_csv_busy(self) and sip.isdeleted(self):
                return
            if exc.row_error_details:
                save_response = QMessageBox.question(
                    self,
                    'Save remediation report',
                    'Save a remediation CSV report for these row issues?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if save_response == QMessageBox.StandardButton.Yes:
                    suggested_name = 'characteristic_alias_import_remediation.csv'
                    report_path, _ = QFileDialog.getSaveFileName(
                        self,
                        'Save remediation report',
                        suggested_name,
                        'CSV files (*.csv);;All files (*)',
                    )
                    if report_path:
                        exported_rows = export_remediation_report_csv(report_path, exc.row_error_details)
                        QMessageBox.information(
                            self,
                            'Report saved',
                            f'Saved remediation report with {exported_rows} row issue(s).',
                        )
        except CharacteristicAliasCsvSchemaError as exc:
            _record_mapping_action_if(
                record_outcome, BugReportAction.WORKFLOW_MAPPING_IMPORT_FAILED
            )
            CustomLogger(exc, reraise=False, logger_name=__name__)
            QMessageBox.critical(
                self,
                'Import error',
                'Could not import mappings because the CSV header row does not match the expected schema.\n\n'
                f"Required columns: {', '.join(exc.required_columns)}\n"
                f"Detected columns: {', '.join(exc.detected_columns) if exc.detected_columns else '(none)'}\n\n"
                'Use this exact header line (same names and order):\n'
                'alias_name,canonical_name,scope_type,scope_value',
            )
        except Exception as exc:
            _record_mapping_action_if(
                record_outcome, BugReportAction.WORKFLOW_MAPPING_IMPORT_FAILED
            )
            CustomLogger(exc, reraise=False, logger_name=__name__)
            QMessageBox.critical(self, 'Import error', f'Could not import mappings: {exc}')

    def export_mappings(self):
        started_at = time.monotonic()
        if _alias_csv_busy(self):
            return
        if not CharacteristicMappingDialog._ensure_existing_database_for_write(self):
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Export name matches',
            'characteristic_aliases.csv',
            'CSV files (*.csv);;All files (*)',
        )
        if not filename:
            return

        _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EXPORT_STARTED)

        if type(filename) is str and _native_alias_csv(self):
            CharacteristicMappingDialog._start_alias_csv(self, 'export', filename, started_at)
            return

        def produce():
            ensure_characteristic_alias_schema(self.db_file)
            return export_characteristic_aliases_csv(self.db_file, filename)

        CharacteristicMappingDialog._apply_alias_export(self, produce)

    def _apply_alias_export(self, producer, *, record_outcome=True):
        try:
            exported_count = producer()
            if record_outcome:
                _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EXPORT_COMPLETED)
            QMessageBox.information(self, 'Export complete', f'Exported {exported_count} mapping row(s).')
        except Exception as exc:
            if record_outcome:
                _record_mapping_action(BugReportAction.WORKFLOW_MAPPING_EXPORT_FAILED)
            CustomLogger(exc, reraise=False, logger_name=__name__)
            QMessageBox.critical(self, 'Export error', f'Could not export mappings: {exc}')

    def _start_alias_csv(self, operation, filename, started_at):
        thread, cleanup_registered = None, False
        try:
            thread = _AliasCsvThread(operation, self.db_file, filename)
            self._alias_csv_thread = thread
            if operation == 'import':
                thread.preview_ready.connect(self._review_alias_import)
                thread._cancel_review_callback = partial(_cancel_alias_review, weakref.ref(thread))
                self.destroyed.connect(thread._cancel_review_callback)
                QCoreApplication.instance().aboutToQuit.connect(thread._cancel_review_callback)
            self._alias_csv_controls = tuple((getattr(self, name), getattr(self, name).isEnabled())
                                             for name in _ALIAS_CSV_CONTROLS)
            # A disabled action with an existing selection is an intentional restriction.
            self._alias_csv_selection_controls = tuple(
                (control, control.isEnabled() or not selected)
                for control, selected in (
                    (self.add_from_selected_button, self._selected_metric_option() is not None),
                    (self.edit_button, self._selected_mapping() is not None),
                    (self.delete_button, self._selected_mapping() is not None),
                )
            )
            for control, _enabled in self._alias_csv_controls:
                control.setEnabled(False)
            detached_threads.register(thread, defer_quit=True, owner=self,
                                      on_finished=CharacteristicMappingDialog._finish_alias_csv)
            detached_threads.run_when_finished(
                [thread], partial(_delete_alias_csv_thread, weakref.ref(self), weakref.ref(thread)))
            cleanup_registered = True
            self._alias_csv_progress, _, bar, _ = create_delayed_worker_progress_dialog(
                self, window_title=f'{operation.title()} name matches',
                initial_status_text=f'{operation.title()}ing name matches…',
                on_cancel=lambda: None, action_started_at=started_at, cancellable=False,
            )
            bar.setRange(0, 0)
            self._alias_csv_progress.show()
            thread.start()
        except Exception as exc:
            if thread is None or not thread.isRunning():
                if thread is not None:
                    detached_threads.discard(thread)
                    if not cleanup_registered:
                        _delete_alias_csv_thread(weakref.ref(self), weakref.ref(thread))
                CharacteristicMappingDialog._release_alias_csv(self)
            else:
                thread.discard_result = True
            def failed(error=exc):
                raise error
            apply = CharacteristicMappingDialog._apply_alias_import if operation == 'import' else CharacteristicMappingDialog._apply_alias_export
            apply(self, failed)

    def _confirm_alias_import(self, plan):
        box = QMessageBox(self)
        box.setWindowTitle('Review mapping import')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f'Added: {plan.added} / Replaced: {plan.replaced} / Unchanged: {plan.unchanged}\n\n'
                    + '\n'.join(plan.replacement_lines()))
        only_new = box.addButton('Import only new', QMessageBox.ButtonRole.AcceptRole)
        replace = box.addButton(f'Import and replace {plan.replaced}', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(only_new)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        try:
            box.exec()
            if sip.isdeleted(box):
                return None
            if box.clickedButton() is only_new:
                return False
            return True if box.clickedButton() is replace else None
        finally:
            detached_threads.delete_on_owner_thread(box)

    def _review_alias_import(self, plan):
        thread = self.sender()
        if not isinstance(thread, _AliasCsvThread):
            thread = self._alias_csv_thread
        try:
            if thread is None or thread is not self._alias_csv_thread:
                if thread is not None:
                    thread.choice = None
                return
            progress = self._alias_csv_progress
            dismiss_worker_progress_dialog(progress)
            self._alias_csv_progress = None
            detached_threads.delete_on_owner_thread(progress)
            if not thread.discard_result and self.db_file == thread.db_file:
                thread.choice = self._confirm_alias_import(plan)
                if thread.choice is not None:
                    try:
                        _bugreport_recorder.record(
                            BugReportAction.OPTION_MAPPING_REPLACE_EXISTING,
                            enabled=bool(thread.choice),
                        )
                    except Exception:
                        pass
            if thread.choice is not None and not sip.isdeleted(self):
                self._alias_csv_progress, _, bar, _ = create_delayed_worker_progress_dialog(
                    self, window_title='Import name matches', initial_status_text='Applying reviewed mappings atomically…',
                    on_cancel=lambda: None, cancellable=False,
                )
                bar.setRange(0, 0)
                self._alias_csv_progress.show()
        except Exception as exc:
            thread.choice = None
            thread.error = exc.with_traceback(None)
        finally:
            if thread is not None:
                thread.reviewed.set()

    def _release_alias_csv(self):
        self._alias_csv_thread = None
        progress, self._alias_csv_progress = self._alias_csv_progress, None
        controls, self._alias_csv_controls = self._alias_csv_controls, ()
        selection, self._alias_csv_selection_controls = self._alias_csv_selection_controls, ()
        # A result message runs a nested event loop and can destroy the whole owner.
        if progress is not None and not sip.isdeleted(progress):
            dismiss_worker_progress_dialog(progress)
            detached_threads.delete_on_owner_thread(progress)
        if sip.isdeleted(self):
            return
        for control, enabled in controls:
            control.setEnabled(enabled)
        for control, unrestricted in selection:
            selected = (self._selected_metric_option() if control is self.add_from_selected_button
                        else self._selected_mapping())
            if unrestricted:
                control.setEnabled(_has_selected_db_file(self.db_file) and not self._source_loading
                                   and selected is not None)

    def _finish_alias_csv(self, thread):
        if thread is not self._alias_csv_thread:
            return
        try:
            if thread.discard_result:
                return
            if type(self.db_file) is not str or self.db_file != thread.db_file:
                # A stale result from a changed DB context is dropped, but that is
                # not evidence that the user cancelled the operation.
                return
            apply = CharacteristicMappingDialog._apply_alias_import if thread.operation == 'import' else CharacteristicMappingDialog._apply_alias_export
            apply(self, thread.result, record_outcome=False)
        finally:
            CharacteristicMappingDialog._release_alias_csv(self)
            if not sip.isdeleted(self):
                if type(self.db_file) is not str or self.db_file != thread.db_file:
                    self._sync_selection_actions()
                    self._sync_warning_labels()
                if self._alias_csv_close_result is not None:
                    result, self._alias_csv_close_result = self._alias_csv_close_result, None
                    self.done(result)

    def _abandon_alias_csv(self, result):
        if _alias_csv_busy(self):
            # Retain the modal database admission until this earlier request is durable.
            self._alias_csv_close_result = result
            self._alias_csv_thread.cancel_review()
            return True
        return False


_NATIVE_MAPPING_DIALOG = CharacteristicMappingDialog
_ALIAS_CSV_METHODS = {name: vars(CharacteristicMappingDialog)[name] for name in
                      ('_ensure_db_file_selected', 'load_aliases', '_build_import_validation_summary',
                       '_selected_metric_option', '_selected_mapping')}
