"""Dialog for maintaining characteristic alias mappings."""

from __future__ import annotations

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
    CharacteristicAliasImportValidationError,
    delete_characteristic_alias,
    ensure_characteristic_alias_schema,
    export_characteristic_aliases_csv,
    fetch_all_characteristic_aliases,
    import_characteristic_aliases_csv,
    normalize_alias_scope,
    upsert_characteristic_alias,
)
from modules.custom_logger import CustomLogger


def _has_selected_db_file(db_file: str) -> bool:
    return bool(str(db_file or '').strip())


class CharacteristicAliasEditorDialog(QDialog):
    """Simple editor used by Add/Edit actions for characteristic aliases."""

    def __init__(self, parent=None, *, initial_values=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Mapping" if initial_values else "Add Mapping")

        self.alias_input = QLineEdit()
        self.canonical_input = QLineEdit()
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["global", "reference"])
        self.scope_value_input = QLineEdit()

        if initial_values:
            self.alias_input.setText(str(initial_values.get('alias_name') or ''))
            self.canonical_input.setText(str(initial_values.get('canonical_name') or ''))
            scope_type = str(initial_values.get('scope_type') or 'global').strip().lower()
            self.scope_combo.setCurrentText(scope_type if scope_type in {'global', 'reference'} else 'global')
            self.scope_value_input.setText(str(initial_values.get('scope_value') or ''))

        layout = QGridLayout(self)
        layout.addWidget(QLabel("Alias"), 0, 0)
        layout.addWidget(self.alias_input, 0, 1)
        layout.addWidget(QLabel("Canonical name"), 1, 0)
        layout.addWidget(self.canonical_input, 1, 1)
        layout.addWidget(QLabel("Scope"), 2, 0)
        layout.addWidget(self.scope_combo, 2, 1)
        layout.addWidget(QLabel("Scope value"), 3, 0)
        layout.addWidget(self.scope_value_input, 3, 1)

        self.button_box_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")
        self.button_box_layout.addWidget(self.save_button)
        self.button_box_layout.addWidget(self.cancel_button)
        layout.addLayout(self.button_box_layout, 4, 0, 1, 2)

        self.scope_combo.currentTextChanged.connect(self._sync_scope_value_state)
        self.save_button.clicked.connect(self._validate_and_accept)
        self.cancel_button.clicked.connect(self.reject)
        self._sync_scope_value_state(self.scope_combo.currentText())

    def _sync_scope_value_state(self, selected_scope):
        is_reference_scope = str(selected_scope or '').strip().lower() == 'reference'
        self.scope_value_input.setEnabled(is_reference_scope)
        if not is_reference_scope:
            self.scope_value_input.clear()
            self.scope_value_input.setPlaceholderText('Not used for global scope')
        else:
            self.scope_value_input.setPlaceholderText('Required for reference scope')

    def _validate_and_accept(self):
        alias_name = str(self.alias_input.text() or '').strip()
        canonical_name = str(self.canonical_input.text() or '').strip()
        scope_type = str(self.scope_combo.currentText() or '').strip().lower()
        scope_value = str(self.scope_value_input.text() or '').strip() or None

        if not alias_name:
            QMessageBox.warning(self, 'Validation error', 'Alias is required.')
            return

        if not canonical_name:
            QMessageBox.warning(self, 'Validation error', 'Canonical name is required.')
            return

        try:
            normalize_alias_scope(scope_type, scope_value)
        except ValueError as exc:
            QMessageBox.warning(self, 'Validation error', str(exc))
            return

        self._result_payload = {
            'alias_name': alias_name,
            'canonical_name': canonical_name,
            'scope_type': scope_type,
            'scope_value': scope_value,
        }
        self.accept()

    @property
    def result_payload(self):
        return getattr(self, '_result_payload', None)


class CharacteristicMappingDialog(QDialog):
    """Manage alias-to-canonical mappings via the characteristic alias service."""

    TABLE_HEADERS = ['Alias', 'Canonical name', 'Scope', 'Scope value']

    def __init__(self, parent=None, db_file=''):
        super().__init__(parent)
        self.setWindowTitle('Characteristic Mapping')
        if parent is not None and hasattr(parent, 'windowIcon'):
            self.setWindowIcon(parent.windowIcon())
        self.setModal(True)
        self.resize(760, 520)

        self.db_file = db_file

        self.db_label = QLabel('Database file:')
        self.db_path_input = QLineEdit(str(db_file or ''))
        self.db_path_input.setReadOnly(True)
        self.select_db_button = QPushButton('Browse DB')

        self.alias_table = QTableWidget(0, len(self.TABLE_HEADERS), self)
        self.alias_table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.alias_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.alias_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.alias_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.add_button = QPushButton('Add')
        self.edit_button = QPushButton('Edit')
        self.delete_button = QPushButton('Delete')
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
        layout.addLayout(db_row)
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
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            alias_rows = fetch_all_characteristic_aliases(self.db_file)
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Load error', f'Could not load mappings: {exc}')
            return

        self.alias_table.setRowCount(len(alias_rows))
        for row_index, row in enumerate(alias_rows):
            values = [
                str(row.get('alias_name') or ''),
                str(row.get('canonical_name') or ''),
                str(row.get('scope_type') or ''),
                str(row.get('scope_value') or ''),
            ]
            for column_index, value in enumerate(values):
                self.alias_table.setItem(row_index, column_index, QTableWidgetItem(value))

        self.alias_table.resizeColumnsToContents()

    def _selected_mapping(self):
        selected_rows = self.alias_table.selectionModel().selectedRows()
        if not selected_rows:
            return None

        row = selected_rows[0].row()
        return {
            'alias_name': self.alias_table.item(row, 0).text(),
            'canonical_name': self.alias_table.item(row, 1).text(),
            'scope_type': self.alias_table.item(row, 2).text(),
            'scope_value': self.alias_table.item(row, 3).text() or None,
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
            QMessageBox.critical(self, 'Save error', f'Could not save mapping: {exc}')

    def edit_mapping(self):
        selected = self._selected_mapping()
        if selected is None:
            QMessageBox.information(self, 'Edit mapping', 'Please select one mapping to edit.')
            return

        editor = CharacteristicAliasEditorDialog(self, initial_values=selected)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return

        payload = editor.result_payload
        if payload is None:
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
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
            QMessageBox.critical(self, 'Save error', f'Could not update mapping: {exc}')

    def delete_mapping(self):
        selected = self._selected_mapping()
        if selected is None:
            QMessageBox.information(self, 'Delete mapping', 'Please select one mapping to delete.')
            return

        confirmation = QMessageBox.question(
            self,
            'Delete mapping',
            f"Delete mapping for alias '{selected['alias_name']}'?",
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
            QMessageBox.critical(self, 'Delete error', f'Could not delete mapping: {exc}')

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
        summary_lines.append(f'First {min(preview_limit, len(details))} row issue(s):')
        for entry in details[:preview_limit]:
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
        for index, entry in enumerate(details, start=1):
            detail_lines.append(
                f"{index}. row={entry.get('row_number')} field={entry.get('field')} code={entry.get('code')} "
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
            'Import characteristic mappings',
            str(self.db_file or ''),
            'CSV files (*.csv);;All files (*)',
        )
        if not filename:
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            imported_count = import_characteristic_aliases_csv(self.db_file, filename)
            self.load_aliases()
            QMessageBox.information(self, 'Import complete', f'Imported {imported_count} mapping row(s).')
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
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Import error', f'Could not import mappings: {exc}')

    def export_mappings(self):
        if not self._ensure_db_file_selected():
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Export characteristic mappings',
            'characteristic_aliases.csv',
            'CSV files (*.csv);;All files (*)',
        )
        if not filename:
            return

        try:
            ensure_characteristic_alias_schema(self.db_file)
            exported_count = export_characteristic_aliases_csv(self.db_file, filename)
            QMessageBox.information(self, 'Export complete', f'Exported {exported_count} mapping row(s).')
        except Exception as exc:
            CustomLogger(exc, reraise=False)
            QMessageBox.critical(self, 'Export error', f'Could not export mappings: {exc}')
