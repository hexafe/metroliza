import tempfile
import unittest
from unittest.mock import patch

from modules.characteristic_alias_service import (
    CharacteristicAliasCsvSchemaError,
    CharacteristicAliasImportValidationError,
    ensure_characteristic_alias_schema,
    upsert_characteristic_alias,
)

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from modules.characteristic_mapping_dialog import (
        CharacteristicMappingDialog,
        build_remediation_report_rows,
    )
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

            self.assertEqual(dialog.windowTitle(), 'Characteristic Name Matching')
            self.assertEqual(dialog.db_path_input.text(), db_path)
            self.assertEqual(dialog.alias_table.rowCount(), 1)
            self.assertEqual(dialog.alias_table.item(0, 0).text(), 'DIA - X')
            self.assertEqual(dialog.alias_table.item(0, 1).text(), 'DIAMETER - X')
            self.assertEqual(dialog.alias_table.item(0, 2).text(), 'One reference only')
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

                info_mock.assert_called_once_with(dialog, 'Import complete', 'Imported 2 name match row(s).')
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

                info_mock.assert_called_once_with(dialog, 'Export complete', 'Exported 1 name match row(s).')
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
                        'duplicate name match/apply to key for "AX" (global) at row 2; first seen at row 1',
                        'alias_name is required at row 2',
                        'Reference is required when apply to is reference at row 3',
                    ],
                    summary='CSV import failed validation. Fix the row issues below and retry.',
                    row_error_details=[
                        {
                            'row_number': 2,
                            'field': 'alias_name',
                            'code': 'duplicate_key_collision',
                            'category': 'duplicate_collision',
                            'remediation_hint': 'Remove or merge duplicate name match rows with the same alias_name + apply to key.',
                            'message': 'duplicate name match/apply to key for "AX" (global) at row 2; first seen at row 1',
                        },
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
                            'remediation_hint': 'Set the reference value when apply to is reference.',
                            'message': 'Reference is required when apply to is reference at row 3',
                        },
                    ],
                    total_rows_processed=5,
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
                self.assertIn('What to fix first:', message)
                self.assertIn('Remove duplicate name match/apply to key rows', message)
                self.assertIn('Total rows processed: 5', message)
                self.assertIn('Valid rows: 3', message)
                self.assertIn('Invalid rows: 2', message)
                self.assertIn('Error categories:', message)
                self.assertIn('duplicate_collision: 1', message)
                self.assertIn('missing_required_field: 1', message)
                self.assertIn('scope_requirements: 1', message)
                self.assertIn('Fix: Provide a non-empty alias_name value.', message)
                self.assertIn('Fix: Set the reference value when apply to is reference.', message)
                detailed = active_box.detailedText()
                self.assertIn('CSV Validation Report', detailed)
                self.assertIn('Conflict-first sections:', detailed)
                self.assertIn('duplicate_collision:', detailed)
                self.assertIn('other_validation_issues:', detailed)
                self.assertIn('code=duplicate_key_collision', detailed)
                self.assertIn('code=missing_alias_name', detailed)
                self.assertIn('code=reference_scope_requires_scope_value', detailed)
            finally:
                dialog.close()

    def test_build_remediation_report_rows_sorts_by_row_then_category(self):
        rows = build_remediation_report_rows(
            [
                {
                    'row_number': 8,
                    'field': 'scope_value',
                    'code': 'reference_scope_requires_scope_value',
                    'category': 'scope_requirements',
                    'message': 'Reference is required when apply to is reference at row 8',
                    'remediation_hint': 'Set the reference value when apply to is reference.',
                },
                {
                    'row_number': 5,
                    'field': 'alias_name',
                    'code': 'duplicate_key_collision',
                    'category': 'duplicate_collision',
                    'message': 'duplicate name match/apply to key for "AX" (global) at row 5; first seen at row 4',
                    'remediation_hint': 'Remove or merge duplicate name match rows with the same alias_name + apply to key.',
                },
                {
                    'row_number': 5,
                    'field': 'canonical_name',
                    'code': 'missing_canonical_name',
                    'category': 'missing_required_field',
                    'message': 'Common name is required at row 5',
                    'remediation_hint': 'Provide the common name for this name match.',
                },
            ]
        )

        self.assertEqual(rows[0]['code'], 'duplicate_key_collision')
        self.assertEqual(rows[1]['code'], 'missing_canonical_name')
        self.assertEqual(rows[2]['code'], 'reference_scope_requires_scope_value')

    def test_import_mappings_offers_and_saves_remediation_report_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            csv_path = f'{tmpdir}/import_aliases.csv'
            report_path = f'{tmpdir}/remediation_report.csv'
            ensure_characteristic_alias_schema(db_path)
            with open(csv_path, 'w', encoding='utf-8', newline='') as csv_file:
                csv_file.write('alias_name,canonical_name,scope_type,scope_value\n')

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                validation_error = CharacteristicAliasImportValidationError(
                    ['duplicate name match/apply to key for "AX" (global) at row 3; first seen at row 2'],
                    summary='CSV import failed validation. Fix the row issues below and retry.',
                    row_error_details=[
                        {
                            'row_number': 3,
                            'field': 'alias_name',
                            'code': 'duplicate_key_collision',
                            'category': 'duplicate_collision',
                            'remediation_hint': 'Remove or merge duplicate name match rows with the same alias_name + apply to key.',
                            'message': 'duplicate name match/apply to key for "AX" (global) at row 3; first seen at row 2',
                        }
                    ],
                    total_rows_processed=2,
                )

                with patch('modules.characteristic_mapping_dialog.QFileDialog.getOpenFileName', return_value=(csv_path, 'CSV files (*.csv)')):
                    with patch('modules.characteristic_mapping_dialog.import_characteristic_aliases_csv', side_effect=validation_error):
                        with patch('modules.characteristic_mapping_dialog.QMessageBox.exec', return_value=QMessageBox.StandardButton.Ok):
                            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                                with patch('modules.characteristic_mapping_dialog.QFileDialog.getSaveFileName', return_value=(report_path, 'CSV files (*.csv)')):
                                    with patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok) as info_mock:
                                        dialog.import_mappings()

                info_mock.assert_called_once_with(dialog, 'Report saved', 'Saved remediation report with 1 name match row issue(s).')
                with open(report_path, 'r', encoding='utf-8') as report_file:
                    lines = report_file.read().splitlines()
                self.assertEqual(lines[0], 'row_number,field,code,category,message,remediation_hint')
                self.assertIn('3,alias_name,duplicate_key_collision,duplicate_collision,"duplicate name match/apply to key for ""AX"" (global) at row 3; first seen at row 2",Remove or merge duplicate name match rows with the same alias_name + apply to key.', lines)
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

    def test_import_mappings_shows_schema_specific_remediation_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            csv_path = f'{tmpdir}/import_aliases.csv'
            ensure_characteristic_alias_schema(db_path)
            with open(csv_path, 'w', encoding='utf-8', newline='') as csv_file:
                csv_file.write('alias_name,canonical_name\n')

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                schema_error = CharacteristicAliasCsvSchemaError(
                    required_columns=('alias_name', 'canonical_name', 'scope_type', 'scope_value'),
                    detected_columns=('alias_name', 'canonical_name'),
                    expected_header_example='alias_name,canonical_name,scope_type,scope_value',
                )
                with patch('modules.characteristic_mapping_dialog.QFileDialog.getOpenFileName', return_value=(csv_path, 'CSV files (*.csv)')):
                    with patch('modules.characteristic_mapping_dialog.import_characteristic_aliases_csv', side_effect=schema_error):
                        with patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                            dialog.import_mappings()

                self.assertTrue(critical_mock.called)
                message = critical_mock.call_args[0][2]
                self.assertIn('header row does not match the expected schema', message)
                self.assertIn('Required columns: alias_name, canonical_name, scope_type, scope_value', message)
                self.assertIn('Detected columns: alias_name, canonical_name', message)
                self.assertIn('alias_name,canonical_name,scope_type,scope_value', message)
                self.assertNotIn('Could not import name match entries: ', message)
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
