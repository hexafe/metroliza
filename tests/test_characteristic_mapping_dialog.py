import tempfile
import unittest
from unittest.mock import patch

from modules.characteristic_alias_service import (
    CharacteristicAliasImportValidationError,
    ensure_characteristic_alias_schema,
    upsert_characteristic_alias,
)

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from modules.characteristic_mapping_dialog import CharacteristicMappingDialog
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    QMessageBox = None
    CharacteristicMappingDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


class TestCharacteristicMappingDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f'PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}')
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_constructs_and_loads_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='DIAMETER - X',
                scope_type='reference',
                scope_value='REF-1',
            )

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)

            self.assertEqual(dialog.windowTitle(), 'Characteristic Mapping')
            self.assertEqual(dialog.db_path_input.text(), db_path)
            self.assertEqual(dialog.alias_table.rowCount(), 1)
            self.assertEqual(dialog.alias_table.item(0, 0).text(), 'DIA - X')
            self.assertEqual(dialog.alias_table.item(0, 1).text(), 'DIAMETER - X')
            self.assertEqual(dialog.alias_table.item(0, 2).text(), 'reference')
            self.assertEqual(dialog.alias_table.item(0, 3).text(), 'REF-1')
            dialog.close()

    def test_import_export_require_selected_db_file(self):
        dialog = CharacteristicMappingDialog(parent=None, db_file='')
        try:
            with patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok) as warn_mock:
                dialog.import_mappings()
                self.assertTrue(warn_mock.called)

            with patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok) as warn_mock:
                dialog.export_mappings()
                self.assertTrue(warn_mock.called)
        finally:
            dialog.close()

    def test_import_mappings_success_refreshes_table_and_shows_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            csv_path = f'{tmpdir}/import_aliases.csv'
            ensure_characteristic_alias_schema(db_path)

            with open(csv_path, 'w', encoding='utf-8', newline='') as csv_file:
                csv_file.write('alias_name,canonical_name,scope_type,scope_value\n')
                csv_file.write('LEN,LENGTH,global,\n')
                csv_file.write('DIA,DIAMETER,reference,REF-42\n')

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                self.assertEqual(dialog.alias_table.rowCount(), 0)

                with patch('modules.characteristic_mapping_dialog.QFileDialog.getOpenFileName', return_value=(csv_path, 'CSV files (*.csv)')):
                    with patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok) as info_mock:
                        dialog.import_mappings()

                info_mock.assert_called_once_with(dialog, 'Import complete', 'Imported 2 mapping row(s).')
                self.assertEqual(dialog.alias_table.rowCount(), 2)
            finally:
                dialog.close()

    def test_export_mappings_success_creates_csv_and_shows_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            output_path = f'{tmpdir}/export_aliases.csv'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA',
                canonical_name='DIAMETER',
                scope_type='global',
                scope_value=None,
            )

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                with patch('modules.characteristic_mapping_dialog.QFileDialog.getSaveFileName', return_value=(output_path, 'CSV files (*.csv)')):
                    with patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok) as info_mock:
                        dialog.export_mappings()

                info_mock.assert_called_once_with(dialog, 'Export complete', 'Exported 1 mapping row(s).')
                with open(output_path, 'r', encoding='utf-8') as exported_file:
                    lines = exported_file.read().splitlines()

                self.assertGreaterEqual(len(lines), 2)
                self.assertEqual(lines[0], 'alias_name,canonical_name,scope_type,scope_value')
                self.assertIn('DIA,DIAMETER,global,', lines)
            finally:
                dialog.close()


    def test_import_mappings_shows_summary_and_detailed_remediation_for_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            csv_path = f'{tmpdir}/import_aliases.csv'
            ensure_characteristic_alias_schema(db_path)
            with open(csv_path, 'w', encoding='utf-8', newline='') as csv_file:
                csv_file.write('alias_name,canonical_name,scope_type,scope_value\n')

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                validation_error = CharacteristicAliasImportValidationError(
                    [
                        'alias_name is required at row 2',
                        'scope_value is required for reference scope at row 3',
                    ],
                    summary='CSV import failed validation. Fix the row issues below and retry.',
                    row_error_details=[
                        {
                            'row_number': 2,
                            'field': 'alias_name',
                            'code': 'missing_alias_name',
                            'category': 'missing_required_field',
                            'remediation_hint': 'Provide a non-empty alias_name value.',
                            'message': 'alias_name is required at row 2',
                        },
                        {
                            'row_number': 3,
                            'field': 'scope_value',
                            'code': 'reference_scope_requires_scope_value',
                            'category': 'scope_requirements',
                            'remediation_hint': 'Set scope_value for reference-scoped aliases.',
                            'message': 'scope_value is required for reference scope at row 3',
                        },
                    ],
                    total_rows_processed=4,
                )
                with patch('modules.characteristic_mapping_dialog.QFileDialog.getOpenFileName', return_value=(csv_path, 'CSV files (*.csv)')):
                    with patch('modules.characteristic_mapping_dialog.import_characteristic_aliases_csv', side_effect=validation_error):
                        with patch('modules.characteristic_mapping_dialog.QMessageBox.exec', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                            dialog.import_mappings()

                self.assertTrue(critical_mock.called)
                active_box = dialog.findChild(QMessageBox)
                self.assertIsNotNone(active_box)
                self.assertEqual(active_box.windowTitle(), 'Import error')
                message = active_box.text()
                self.assertIn('Total rows processed: 4', message)
                self.assertIn('Valid rows: 2', message)
                self.assertIn('Invalid rows: 2', message)
                self.assertIn('Error categories:', message)
                self.assertIn('missing_required_field: 1', message)
                self.assertIn('scope_requirements: 1', message)
                self.assertIn('Fix: Provide a non-empty alias_name value.', message)
                self.assertIn('Fix: Set scope_value for reference-scoped aliases.', message)
                detailed = active_box.detailedText()
                self.assertIn('CSV Validation Report', detailed)
                self.assertIn('code=missing_alias_name', detailed)
                self.assertIn('code=reference_scope_requires_scope_value', detailed)
            finally:
                dialog.close()

    def test_import_mappings_shows_critical_message_on_exception(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            csv_path = f'{tmpdir}/import_aliases.csv'
            ensure_characteristic_alias_schema(db_path)
            with open(csv_path, 'w', encoding='utf-8', newline='') as csv_file:
                csv_file.write('alias_name,canonical_name,scope_type,scope_value\n')

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                with patch('modules.characteristic_mapping_dialog.QFileDialog.getOpenFileName', return_value=(csv_path, 'CSV files (*.csv)')):
                    with patch('modules.characteristic_mapping_dialog.import_characteristic_aliases_csv', side_effect=RuntimeError('boom')):
                        with patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                            dialog.import_mappings()

                self.assertTrue(critical_mock.called)
                self.assertEqual(critical_mock.call_args[0][1], 'Import error')
            finally:
                dialog.close()

    def test_export_mappings_shows_critical_message_on_exception(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            output_path = f'{tmpdir}/export_aliases.csv'
            ensure_characteristic_alias_schema(db_path)

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                with patch('modules.characteristic_mapping_dialog.QFileDialog.getSaveFileName', return_value=(output_path, 'CSV files (*.csv)')):
                    with patch('modules.characteristic_mapping_dialog.export_characteristic_aliases_csv', side_effect=RuntimeError('boom')):
                        with patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                            dialog.export_mappings()

                self.assertTrue(critical_mock.called)
                self.assertEqual(critical_mock.call_args[0][1], 'Export error')
            finally:
                dialog.close()


if __name__ == '__main__':
    unittest.main()
