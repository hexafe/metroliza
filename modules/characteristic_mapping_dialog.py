"""Dialog for maintaining characteristic name matching mappings."""

from __future__ import annotations

import csv

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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules.characteristic_alias_service import (
    CharacteristicAliasCsvSchemaError,
    CharacteristicAliasImportValidationError,
    delete_characteristic_alias,
    ensure_characteristic_alias_schema,
    export_characteristic_aliases_csv,
    fetch_all_characteristic_aliases,
    import_characteristic_aliases_csv,
    normalize_scope_type,
    upsert_characteristic_alias,
)
from modules.custom_logger import CustomLogger


ALL_REFERENCES_LABEL = 'All references'
ONE_REFERENCE_LABEL = 'One reference only'
REMEDIATION_REPORT_HEADERS = ('row_number', 'field', 'code', 'category', 'message', 'remediation_hint')


def _has_selected_db_file(db_file: str) -> bool:
    return bool(str(db_file or '').strip())


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


class CharacteristicAliasEditorDialog(QDialog):
    """Simple editor used by Add/Edit actions for characteristic mappings."""

    def __init__(self, parent=None, *, initial_values=None):
        super().__init__(parent)
        self.setWindowTitle('Edit report name mapping' if initial_values else 'Add new report name mapping')

        self.alias_input = QLineEdit()
        self.alias_input.setPlaceholderText('e.g. TP GAP')
        self.common_name_input = QLineEdit()
        self.common_name_input.setPlaceholderText('e.g. AA-C11 - TP')

        self.apply_to_combo = QComboBox()
        self.apply_to_combo.addItems([ALL_REFERENCES_LABEL, ONE_REFERENCE_LABEL])

        self.reference_input = QLineEdit()
        self.reference_input.setPlaceholderText('Select reference')

        if initial_values:
            self.alias_input.setText(str(initial_values.get('alias_name') or ''))
            self.common_name_input.setText(str(initial_values.get('canonical_name') or ''))
            scope_type = str(initial_values.get('scope_type') or 'global').strip().lower()
            if scope_type == 'reference':
                self.apply_to_combo.setCurrentText(ONE_REFERENCE_LABEL)
            else:
                self.apply_to_combo.setCurrentText(ALL_REFERENCES_LABEL)
            self.reference_input.setText(str(initial_values.get('scope_value') or ''))

        layout = QGridLayout(self)

        row = 0
        layout.addWidget(QLabel('Name found in report'), row, 0)
        layout.addWidget(self.alias_input, row, 1)
        row += 1
        alias_help = QLabel('Enter the name exactly as it appears in the report.')
        alias_help.setWordWrap(True)
        layout.addWidget(alias_help, row, 0, 1, 2)

        row += 1
        layout.addWidget(QLabel('Use this common name'), row, 0)
        layout.addWidget(self.common_name_input, row, 1)
        row += 1
        common_help = QLabel('This is the shared name the app will use when grouping and comparing characteristics.')
        common_help.setWordWrap(True)
        layout.addWidget(common_help, row, 0, 1, 2)

        row += 1
        layout.addWidget(QLabel('Where should this match apply?'), row, 0)
        layout.addWidget(self.apply_to_combo, row, 1)
        row += 1
        apply_help = QLabel(
            'Use “All references” when the same characteristic may appear under different names across reports, '
            'and this report name should always map to the same common name. '
            'Use “One reference only” when this report name should map only for a specific reference.'
        )
        apply_help.setWordWrap(True)
        layout.addWidget(apply_help, row, 0, 1, 2)

        row += 1
        self.reference_label = QLabel('Reference')
        layout.addWidget(self.reference_label, row, 0)
        layout.addWidget(self.reference_input, row, 1)
        row += 1
        self.reference_help = QLabel('This report name will only be used for the selected reference.')
        self.reference_help.setWordWrap(True)
        layout.addWidget(self.reference_help, row, 0, 1, 2)

        row += 1
        example_help = QLabel(
            'Example:\nThe same characteristic can appear under different names. '
            'If one report uses “TP GAP” and another uses “AA-C11 - TP”, '
            'map “TP GAP” to the common name “AA-C11 - TP”.'
        )
        example_help.setWordWrap(True)
        layout.addWidget(example_help, row, 0, 1, 2)

        row += 1
        self.button_box_layout = QHBoxLayout()
        self.save_button = QPushButton('Save mapping')
        self.clear_button = QPushButton('Clear')
        self.cancel_button = QPushButton('Cancel')
        self.button_box_layout.addWidget(self.save_button)
        self.button_box_layout.addWidget(self.clear_button)
        self.button_box_layout.addWidget(self.cancel_button)
        layout.addLayout(self.button_box_layout, row, 0, 1, 2)

        self.apply_to_combo.currentTextChanged.connect(self._sync_scope_value_state)
        self.save_button.clicked.connect(self._validate_and_accept)
        self.clear_button.clicked.connect(self._clear_fields)
        self.cancel_button.clicked.connect(self.reject)
        self._sync_scope_value_state(self.apply_to_combo.currentText())

    def _clear_fields(self):
        self.alias_input.clear()
        self.common_name_input.clear()
        self.apply_to_combo.setCurrentText(ALL_REFERENCES_LABEL)
        self.reference_input.clear()

    def _sync_scope_value_state(self, selected_scope):
        is_reference_scope = str(selected_scope or '').strip() == ONE_REFERENCE_LABEL
        self.reference_label.setVisible(is_reference_scope)
        self.reference_input.setVisible(is_reference_scope)
        self.reference_help.setVisible(is_reference_scope)
        if not is_reference_scope:
            self.reference_input.clear()

    def _validate_and_accept(self):
        alias_name = str(self.alias_input.text() or '').strip()
        common_name = str(self.common_name_input.text() or '').strip()
        selected_scope = str(self.apply_to_combo.currentText() or '').strip()

        scope_type = 'reference' if selected_scope == ONE_REFERENCE_LABEL else 'global'
        scope_value = str(self.reference_input.text() or '').strip() or None

        if not alias_name:
            QMessageBox.warning(self, 'Validation error', 'Please enter the name found in the report.')
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

        self._result_payload = {
            'alias_name': alias_name,
            'canonical_name': common_name,
            'scope_type': scope_type,
            'scope_value': scope_value,
        }
        self.accept()

    @property
    def result_payload(self):
        return getattr(self, '_result_payload', None)


class CharacteristicMappingDialog(QDialog):
    """Manage report-name-to-common-name mappings."""

    TABLE_HEADERS = ['Name found in report', 'Use this common name', 'Apply to', 'Reference']

    def __init__(self, parent=None, db_file=''):
        super().__init__(parent)
        self.setWindowTitle('Characteristic Name Matching')
        if parent is not None and hasattr(parent, 'windowIcon'):
            self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        self.resize(900, 600)

        self.db_file = db_file

        self.subtitle_label = QLabel(
            'Use this tool when the same characteristic appears under different names in reports. '
            'Map each report name to a common name, then choose whether the mapping applies to all references or one reference only.'
        )
        self.subtitle_label.setWordWrap(True)

        self.db_label = QLabel('Database file:')
        self.db_path_input = QLineEdit(str(db_file or ''))
        self.db_path_input.setReadOnly(True)
        self.select_db_button = QPushButton('Browse DB')

        self.table_title_label = QLabel('Saved report name mappings')
        self.empty_state_label = QLabel(
            'No report name mappings have been added yet.\n'
            'Add a name found in report and a common name, then choose Apply to and Reference as needed.'
        )
        self.empty_state_label.setWordWrap(True)

        self.alias_table = QTableWidget(0, len(self.TABLE_HEADERS), self)
        self.alias_table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.alias_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.alias_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.alias_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.alias_table.itemSelectionChanged.connect(self._sync_selection_actions)

        self.add_button = QPushButton('Add match')
        self.edit_button = QPushButton('Edit selected')
        self.delete_button = QPushButton('Delete selected')
        self.import_button = QPushButton('Import CSV')
        self.export_button = QPushButton('Export CSV')
        self.close_button = QPushButton('Close')

        button_row = QHBoxLayout()
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.delete_button)
        button_row.addWidget(self.import_button)
        button_row.addWidget(self.export_button)
        button_row.addStretch()
        button_row.addWidget(self.close_button)

        db_row = QHBoxLayout()
        db_row.addWidget(self.db_label)
        db_row.addWidget(self.db_path_input, 1)
        db_row.addWidget(self.select_db_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.subtitle_label)
        layout.addLayout(db_row)
        layout.addWidget(self.table_title_label)
        layout.addWidget(self.empty_state_label)
        layout.addWidget(self.alias_table)
        layout.addLayout(button_row)

        self.add_button.clicked.connect(self.add_mapping)
        self.edit_button.clicked.connect(self.edit_mapping)
        self.delete_button.clicked.connect(self.delete_mapping)
        self.import_button.clicked.connect(self.import_mappings)
        self.export_button.clicked.connect(self.export_mappings)
        self.close_button.clicked.connect(self.accept)
        self.select_db_button.clicked.connect(self.select_db_file)

        self.load_aliases()
        self._sync_selection_actions()

    def _scope_display_values(self, scope_type, scope_value):
        if str(scope_type or '').strip().lower() == 'reference':
            return ONE_REFERENCE_LABEL, str(scope_value or '')
        return ALL_REFERENCES_LABEL, '—'

    def _scope_from_display(self, apply_to, reference_value):
        if str(apply_to or '').strip() == ONE_REFERENCE_LABEL:
            return 'reference', str(reference_value or '').strip() or None
        return 'global', None

    def _sync_selection_actions(self):
        has_selection = self._selected_mapping() is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    def select_db_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Select a database file',
            str(self.db_file or ''),
            'SQLite database (*.db *.sqlite *.sqlite3);;All files (*)',
        )
        if not filename:
            return

        self.db_file = filename
        self.db_path_input.setText(filename)
        if self.parent() is not None and hasattr(self.parent(), 'set_db_file'):
            self.parent().set_db_file(filename)
        self.load_aliases()

    def load_aliases(self):
        if not self.db_file:
            self.alias_table.setRowCount(0)
            self.empty_state_label.setVisible(True)
            self._sync_selection_actions()
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            alias_rows = fetch_all_characteristic_aliases(self.db_file)
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Load error', f'Could not load report name mappings: {exc}')
            return

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

        self.empty_state_label.setVisible(len(alias_rows) == 0)
        self.alias_table.resizeColumnsToContents()
        self._sync_selection_actions()

    def _selected_mapping(self):
        selected_rows = self.alias_table.selectionModel().selectedRows()
        if not selected_rows:
            return None

        row = selected_rows[0].row()
        apply_to = self.alias_table.item(row, 2).text()
        reference_display = self.alias_table.item(row, 3).text()
        scope_type, scope_value = self._scope_from_display(apply_to, reference_display)

        return {
            'alias_name': self.alias_table.item(row, 0).text(),
            'canonical_name': self.alias_table.item(row, 1).text(),
            'scope_type': scope_type,
            'scope_value': scope_value,
        }

    def add_mapping(self):
        editor = CharacteristicAliasEditorDialog(self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return

        payload = editor.result_payload
        if payload is None:
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            existing = fetch_all_characteristic_aliases(self.db_file)
            if any(
                row['alias_name'] == payload['alias_name']
                and row['scope_type'] == payload['scope_type']
                and (row.get('scope_value') or None) == (payload.get('scope_value') or None)
                for row in existing
            ):
                QMessageBox.warning(
                    self,
                    'Validation error',
                    'This name found in the report already exists for the selected Apply to/Reference combination.',
                )
                return

            upsert_characteristic_alias(
                self.db_file,
                alias_name=payload['alias_name'],
                canonical_name=payload['canonical_name'],
                scope_type=payload['scope_type'],
                scope_value=payload['scope_value'],
            )
            self.load_aliases()
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Save error', f'Could not save report name mapping: {exc}')

    def edit_mapping(self):
        selected = self._selected_mapping()
        if selected is None:
            return

        editor = CharacteristicAliasEditorDialog(self, initial_values=selected)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return

        payload = editor.result_payload
        if payload is None:
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            existing = fetch_all_characteristic_aliases(self.db_file)
            if any(
                row['alias_name'] == payload['alias_name']
                and row['scope_type'] == payload['scope_type']
                and (row.get('scope_value') or None) == (payload.get('scope_value') or None)
                and not (
                    row['alias_name'] == selected['alias_name']
                    and row['scope_type'] == selected['scope_type']
                    and (row.get('scope_value') or None) == (selected.get('scope_value') or None)
                )
                for row in existing
            ):
                QMessageBox.warning(
                    self,
                    'Validation error',
                    'This name found in the report already exists for the selected Apply to/Reference combination.',
                )
                return

            upsert_characteristic_alias(
                self.db_file,
                alias_name=payload['alias_name'],
                canonical_name=payload['canonical_name'],
                scope_type=payload['scope_type'],
                scope_value=payload['scope_value'],
            )
            if (
                selected['alias_name'] != payload['alias_name']
                or selected['scope_type'] != payload['scope_type']
                or (selected['scope_value'] or None) != (payload['scope_value'] or None)
            ):
                delete_characteristic_alias(
                    self.db_file,
                    alias_name=selected['alias_name'],
                    scope_type=selected['scope_type'],
                    scope_value=selected['scope_value'],
                )
            self.load_aliases()
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Save error', f'Could not update report name mapping: {exc}')

    def delete_mapping(self):
        selected = self._selected_mapping()
        if selected is None:
            return

        confirmation = QMessageBox.question(
            self,
            'Delete report name mapping',
            'Are you sure you want to delete this report name mapping?\n\n'
            'This will stop treating the selected report name as the chosen common name.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        try:
            delete_characteristic_alias(
                self.db_file,
                alias_name=selected['alias_name'],
                scope_type=selected['scope_type'],
                scope_value=selected['scope_value'],
            )
            self.load_aliases()
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Delete error', f'Could not delete report name mapping: {exc}')

    def _ensure_db_file_selected(self) -> bool:
        if _has_selected_db_file(self.db_file):
            return True
        QMessageBox.warning(self, 'Database required', 'Please select a database file first.')
        return False

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
            'Could not import report name mappings due to CSV validation errors.',
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
            summary_lines.append('  1) Remove duplicate report name/apply to key rows to keep imports atomic and deterministic.')
            summary_lines.append('  2) For each duplicate key, choose one apply to strategy: all references or one reference only.')
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
        if not self._ensure_db_file_selected():
            return

        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Import report name mappings',
            str(self.db_file or ''),
            'CSV files (*.csv);;All files (*)',
        )
        if not filename:
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            imported_count = import_characteristic_aliases_csv(self.db_file, filename)
            self.load_aliases()
            QMessageBox.information(self, 'Import complete', f'Imported {imported_count} report name mapping row(s).')
        except CharacteristicAliasImportValidationError as exc:
            CustomLogger(exc, reraise=False)
            message, full_report = self._build_import_validation_summary(exc, preview_limit=10)
            details_box = QMessageBox(self)
            details_box.setIcon(QMessageBox.Icon.Critical)
            details_box.setWindowTitle('Import error')
            details_box.setText(message)
            details_box.setDetailedText(full_report)
            details_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            details_box.exec()

            if exc.row_error_details:
                save_response = QMessageBox.question(
                    self,
                    'Save remediation report',
                    'Save a remediation CSV report for these report name mapping row issues?',
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
                            f'Saved remediation report with {exported_rows} report name mapping row issue(s).',
                        )
        except CharacteristicAliasCsvSchemaError as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(
                self,
                'Import error',
                'Could not import report name mappings because the CSV header row does not match the expected schema.\n\n'
                f"Required columns: {', '.join(exc.required_columns)}\n"
                f"Detected columns: {', '.join(exc.detected_columns) if exc.detected_columns else '(none)'}\n\n"
                'Use this exact header line (same names and order):\n'
                'alias_name,canonical_name,scope_type,scope_value',
            )
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Import error', f'Could not import report name mappings: {exc}')

    def export_mappings(self):
        if not self._ensure_db_file_selected():
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Export report name mappings',
            'characteristic_aliases.csv',
            'CSV files (*.csv);;All files (*)',
        )
        if not filename:
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            exported_count = export_characteristic_aliases_csv(self.db_file, filename)
            QMessageBox.information(self, 'Export complete', f'Exported {exported_count} report name mapping row(s).')
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Export error', f'Could not export report name mappings: {exc}')
