import importlib.util
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from modules.characteristic_alias_service import (
    CharacteristicAliasCsvSchemaError,
    CharacteristicAliasImportValidationError,
    ensure_characteristic_alias_schema,
    upsert_characteristic_alias,
)

if importlib.util.find_spec("PyQt6") is None:  # pragma: no cover - optional local test runtime.
    QApplication = None
    QThread = None
    QMessageBox = None
    CharacteristicMappingDialog = None
    PYQT_IMPORT_ERROR = ModuleNotFoundError("PyQt6 is not installed")
else:
    from PyQt6.QtCore import QThread
    from metroliza.ui import detached_threads
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from modules.characteristic_mapping_dialog import (
        ALL_REFERENCES_LABEL,
        CharacteristicMappingDialog,
        CharacteristicAliasEditorDialog,
        ONE_REFERENCE_LABEL,
        build_remediation_report_rows,
    )
    PYQT_IMPORT_ERROR = None


class TestCharacteristicMappingDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f'PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}')
        cls.app = QApplication.instance() or QApplication([])

    def _wait_for_source_load(self, dialog, timeout_s=10.0):
        deadline = time.monotonic() + timeout_s
        while dialog.is_loading_source_options() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertFalse(dialog.is_loading_source_options(), 'source options did not finish loading')

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
            available = self.app.primaryScreen().availableGeometry()
            self.assertGreaterEqual(dialog.minimumWidth(), min(980, available.width() - 40))
            self.assertGreaterEqual(dialog.minimumHeight(), min(620, available.height() - 40))
            self.assertEqual(dialog.alias_table.rowCount(), 1)
            self.assertEqual(dialog.alias_table.item(0, 0).text(), 'DIA - X')
            self.assertEqual(dialog.alias_table.item(0, 1).text(), 'DIAMETER - X')
            self.assertEqual(dialog.alias_table.item(0, 2).text(), 'One reference only')
            self.assertEqual(dialog.alias_table.item(0, 3).text(), 'REF-1')
            self.assertTrue(dialog.db_warning_label.isHidden())
            self.assertTrue(dialog.empty_warning_label.isHidden())
            self.assertFalse(dialog.collision_warning_label.isHidden())
            dialog.close()

    def test_dialog_without_db_shows_db_warning(self):
        dialog = CharacteristicMappingDialog(parent=None, db_file='')
        try:
            self.assertFalse(dialog.db_warning_label.isHidden())
            self.assertTrue(dialog.empty_warning_label.isHidden())
            self.assertEqual(dialog.alias_table.rowCount(), 0)
            self.assertFalse(dialog.add_button.isEnabled())
            self.assertFalse(dialog.add_from_selected_button.isEnabled())
            self.assertFalse(dialog.import_button.isEnabled())
            self.assertFalse(dialog.export_button.isEnabled())
        finally:
            dialog.close()

    def test_import_export_require_selected_db_file_when_called_directly(self):
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

    def test_source_metric_options_load_filter_and_enable_add_from_selected(self):
        metric_rows = [
            {
                'metric_name': 'DIA - X',
                'measurement_count': 8,
                'report_count': 2,
                'reference_count': 1,
                'sample_references': 'REF-1',
            },
            {
                'metric_name': 'TP GAP',
                'measurement_count': 3,
                'report_count': 1,
                'reference_count': 1,
                'sample_references': 'REF-2',
            },
        ]
        reference_rows = [{'reference': 'REF-1'}, {'reference': 'REF-2'}]
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)

            with patch('modules.characteristic_mapping_dialog.fetch_distinct_report_metric_names', return_value=metric_rows):
                with patch('modules.characteristic_mapping_dialog.fetch_distinct_references', return_value=reference_rows):
                    dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
                    self._wait_for_source_load(dialog)

            try:
                self.assertEqual(dialog.metric_table.rowCount(), 2)
                self.assertEqual(dialog.metric_table.item(0, 0).text(), 'DIA - X')
                self.assertEqual(dialog.metric_table.item(0, 3).text(), '8')
                self.assertFalse(dialog.add_from_selected_button.isEnabled())

                dialog.metric_table.selectRow(1)
                self.assertTrue(dialog.add_from_selected_button.isEnabled())

                dialog.metric_search_input.setText('dia')
                self.assertEqual(dialog.metric_table.rowCount(), 1)
                self.assertEqual(dialog.metric_table.item(0, 0).text(), 'DIA - X')
            finally:
                dialog.close()

    def test_editor_uses_db_backed_combos_and_impact_preview(self):
        metric_rows = [{'metric_name': 'DIA - X'}, {'metric_name': 'TP GAP'}]
        reference_rows = [{'reference': 'REF-1'}, {'reference': 'REF-2'}]

        impact_calls = []

        def impact_resolver(alias_name, scope_type, scope_value):
            impact_calls.append((alias_name, scope_type, scope_value))
            return {'measurement_count': 8, 'report_count': 2, 'reference_count': 1}

        dialog = CharacteristicAliasEditorDialog(
            parent=None,
            metric_options=metric_rows,
            reference_options=reference_rows,
            impact_resolver=impact_resolver,
        )
        try:
            dialog.show()
            self.app.processEvents()
            dialog.alias_input.setCurrentText('DIA - X')
            dialog.common_name_input.setCurrentText('DIAMETER - X')
            dialog.apply_to_combo.setCurrentText(ONE_REFERENCE_LABEL)
            dialog.reference_input.setCurrentText('REF-1')
            self.app.processEvents()

            self.assertTrue(dialog.reference_input.isVisible())
            self.assertIn(('DIA - X', 'reference', 'REF-1'), impact_calls)
            self.assertIn('Affects 8 rows in 2 reports across 1 references.', dialog.impact_label.text())
            dialog._validate_and_accept()
            self.assertEqual(
                dialog.result_payload,
                {
                    'alias_name': 'DIA - X',
                    'canonical_name': 'DIAMETER - X',
                    'scope_type': 'reference',
                    'scope_value': 'REF-1',
                },
            )
        finally:
            dialog.close()

    def test_editor_hides_reference_for_global_scope(self):
        dialog = CharacteristicAliasEditorDialog(
            parent=None,
            initial_values={
                'alias_name': 'DIA - X',
                'canonical_name': 'DIAMETER - X',
                'scope_type': 'global',
                'scope_value': None,
            },
        )
        try:
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.apply_to_combo.currentText(), ALL_REFERENCES_LABEL)
            self.assertTrue(dialog.reference_input.isHidden())
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
                        'duplicate alias/scope key for "AX" (global) at row 2; first seen at row 1',
                        'alias_name is required at row 2',
                        'scope_value is required for reference scope at row 3',
                    ],
                    summary='CSV import failed validation. Fix the row issues below and retry.',
                    row_error_details=[
                        {
                            'row_number': 2,
                            'field': 'alias_name',
                            'code': 'duplicate_key_collision',
                            'category': 'duplicate_collision',
                            'remediation_hint': 'Remove or merge duplicate alias rows with the same alias_name + scope.',
                            'message': 'duplicate alias/scope key for "AX" (global) at row 2; first seen at row 1',
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
                            'remediation_hint': 'Set scope_value for reference-scoped aliases.',
                            'message': 'scope_value is required for reference scope at row 3',
                        },
                    ],
                    total_rows_processed=5,
                )
                with patch('modules.characteristic_mapping_dialog.QFileDialog.getOpenFileName', return_value=(csv_path, 'CSV files (*.csv)')):
                    with patch('modules.characteristic_mapping_dialog.import_characteristic_aliases_csv', side_effect=validation_error):
                        with patch('modules.characteristic_mapping_dialog.CustomLogger', return_value=None):
                            with patch('modules.characteristic_mapping_dialog.QMessageBox.exec', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
                                    dialog.import_mappings()

                self.assertTrue(critical_mock.called)
                active_box = dialog.findChild(QMessageBox)
                self.assertIsNotNone(active_box)
                self.assertEqual(active_box.windowTitle(), 'Import error')
                message = active_box.text()
                self.assertIn('What to fix first:', message)
                self.assertIn('Remove duplicate alias/scope key rows', message)
                self.assertIn('Total rows processed: 5', message)
                self.assertIn('Valid rows: 3', message)
                self.assertIn('Invalid rows: 2', message)
                self.assertIn('Error categories:', message)
                self.assertIn('duplicate_collision: 1', message)
                self.assertIn('missing_required_field: 1', message)
                self.assertIn('scope_requirements: 1', message)
                self.assertIn('Fix: Provide a non-empty alias_name value.', message)
                self.assertIn('Fix: Set scope_value for reference-scoped aliases.', message)
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
                    'message': 'scope_value is required for reference scope at row 8',
                    'remediation_hint': 'Set scope_value for reference-scoped aliases.',
                },
                {
                    'row_number': 5,
                    'field': 'alias_name',
                    'code': 'duplicate_key_collision',
                    'category': 'duplicate_collision',
                    'message': 'duplicate alias/scope key for "AX" (global) at row 5; first seen at row 4',
                    'remediation_hint': 'Remove or merge duplicate alias rows with the same alias_name + scope.',
                },
                {
                    'row_number': 5,
                    'field': 'canonical_name',
                    'code': 'missing_canonical_name',
                    'category': 'missing_required_field',
                    'message': 'canonical_name is required at row 5',
                    'remediation_hint': 'Provide the canonical_name to map this alias to.',
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
                    ['duplicate alias/scope key for "AX" (global) at row 3; first seen at row 2'],
                    summary='CSV import failed validation. Fix the row issues below and retry.',
                    row_error_details=[
                        {
                            'row_number': 3,
                            'field': 'alias_name',
                            'code': 'duplicate_key_collision',
                            'category': 'duplicate_collision',
                            'remediation_hint': 'Remove or merge duplicate alias rows with the same alias_name + scope.',
                            'message': 'duplicate alias/scope key for "AX" (global) at row 3; first seen at row 2',
                        }
                    ],
                    total_rows_processed=2,
                )

                with patch('modules.characteristic_mapping_dialog.QFileDialog.getOpenFileName', return_value=(csv_path, 'CSV files (*.csv)')):
                    with patch('modules.characteristic_mapping_dialog.import_characteristic_aliases_csv', side_effect=validation_error):
                        with patch('modules.characteristic_mapping_dialog.CustomLogger', return_value=None):
                            with patch('modules.characteristic_mapping_dialog.QMessageBox.exec', return_value=QMessageBox.StandardButton.Ok):
                                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                                    with patch('modules.characteristic_mapping_dialog.QFileDialog.getSaveFileName', return_value=(report_path, 'CSV files (*.csv)')):
                                        with patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok) as info_mock:
                                            dialog.import_mappings()

                info_mock.assert_called_once_with(dialog, 'Report saved', 'Saved remediation report with 1 row issue(s).')
                with open(report_path, 'r', encoding='utf-8') as report_file:
                    lines = report_file.read().splitlines()
                self.assertEqual(lines[0], 'row_number,field,code,category,message,remediation_hint')
                self.assertIn('3,alias_name,duplicate_key_collision,duplicate_collision,"duplicate alias/scope key for ""AX"" (global) at row 3; first seen at row 2",Remove or merge duplicate alias rows with the same alias_name + scope.', lines)
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
                        with patch('modules.characteristic_mapping_dialog.CustomLogger', return_value=None):
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
                        with patch('modules.characteristic_mapping_dialog.CustomLogger', return_value=None):
                            with patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                                dialog.import_mappings()

                self.assertTrue(critical_mock.called)
                message = critical_mock.call_args[0][2]
                self.assertIn('header row does not match the expected schema', message)
                self.assertIn('Required columns: alias_name, canonical_name, scope_type, scope_value', message)
                self.assertIn('Detected columns: alias_name, canonical_name', message)
                self.assertIn('alias_name,canonical_name,scope_type,scope_value', message)
                self.assertNotIn('Could not import mappings: ', message)
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
                        with patch('modules.characteristic_mapping_dialog.CustomLogger', return_value=None):
                            with patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                                dialog.export_mappings()

                self.assertTrue(critical_mock.called)
                self.assertEqual(critical_mock.call_args[0][1], 'Export error')
            finally:
                dialog.close()


    def _interruptible_fetch(self, result, seen_threads=None):
        def fetch(*_args, **_kwargs):
            if seen_threads is not None:
                seen_threads.append(QThread.currentThread())
            deadline = time.monotonic() + 10.0
            while not QThread.currentThread().isInterruptionRequested() and time.monotonic() < deadline:
                time.sleep(0.005)
            return result

        return fetch

    def _gated_fetch(self, gate, result, seen_threads=None):
        def fetch(*_args, **_kwargs):
            if seen_threads is not None:
                seen_threads.append(QThread.currentThread())
            gate.wait(10.0)
            return result

        return fetch

    def test_source_options_load_in_worker_thread_and_populate_on_gui_thread(self):
        metric_rows = [
            {'metric_name': 'DIA - X', 'measurement_count': 8, 'report_count': 2, 'reference_count': 1,
             'sample_references': ['REF-1']},
        ]
        gate = threading.Event()
        seen_threads = []
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            with patch(
                'modules.characteristic_mapping_dialog.fetch_distinct_report_metric_names',
                side_effect=self._gated_fetch(gate, metric_rows, seen_threads),
            ), patch(
                'modules.characteristic_mapping_dialog.fetch_distinct_references',
                side_effect=self._gated_fetch(gate, [{'reference': 'REF-1'}], seen_threads),
            ):
                dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
                try:
                    # The constructor returned while the worker is still blocked: nothing froze the GUI thread.
                    self.assertTrue(dialog.is_loading_source_options())
                    self.assertEqual(dialog.metric_table.rowCount(), 0)
                    self.assertFalse(dialog.metric_empty_label.isHidden())
                    self.assertEqual(dialog.metric_empty_label.text(), 'Loading report/export names...')
                    self.assertFalse(dialog.add_button.isEnabled())
                    self.assertIsNotNone(dialog._source_progress_dialog)
                    self.assertFalse(dialog._source_progress_dialog.isVisible())  # delayed indicator

                    gate.set()
                    self._wait_for_source_load(dialog)

                    self.assertEqual(dialog.metric_table.rowCount(), 1)
                    self.assertEqual(dialog.metric_table.item(0, 0).text(), 'DIA - X')
                    self.assertTrue(dialog.metric_empty_label.isHidden())
                    self.assertTrue(dialog.add_button.isEnabled())
                    self.assertIsNone(dialog._source_progress_dialog)
                    self.assertEqual(dialog.reference_options, [{'reference': 'REF-1'}])
                    self.assertEqual(len(seen_threads), 2)
                    self.assertTrue(all(thread is not self.app.thread() for thread in seen_threads))
                finally:
                    gate.set()
                    dialog.close()

    def test_source_options_load_error_keeps_message_and_empty_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            with patch('modules.characteristic_mapping_dialog.fetch_distinct_report_metric_names', side_effect=RuntimeError('boom')):
                with patch('modules.characteristic_mapping_dialog.CustomLogger') as logger_mock:
                    with patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok) as critical_mock:
                        dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
                        try:
                            self._wait_for_source_load(dialog)
                        finally:
                            dialog.close()

            critical_mock.assert_called_once_with(dialog, 'Load error', 'Could not load report/export names: boom')
            self.assertEqual(logger_mock.call_count, 1)
            self.assertIsInstance(logger_mock.call_args[0][0], RuntimeError)
            self.assertEqual(dialog.metric_options, [])
            self.assertEqual(dialog.reference_options, [])
            self.assertEqual(dialog.metric_table.rowCount(), 0)

    def test_closing_dialog_while_loading_interrupts_and_joins_worker(self):
        seen_threads = []
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            with patch(
                'modules.characteristic_mapping_dialog.fetch_distinct_report_metric_names',
                side_effect=self._interruptible_fetch([{'metric_name': 'LATE'}], seen_threads),
            ), patch('modules.characteristic_mapping_dialog.fetch_distinct_references', return_value=[]):
                dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
                thread = dialog._source_thread
                self.assertTrue(dialog.is_loading_source_options())
                deadline = time.monotonic() + 5.0
                while not seen_threads and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(thread.isRunning())

                started = time.monotonic()
                dialog.close()

                self.assertLess(time.monotonic() - started, 5.0)
                self.assertTrue(thread.isFinished())
                self.assertIsNone(dialog._source_thread)
                self.assertFalse(dialog.is_loading_source_options())
                self.assertIsNone(dialog._source_progress_dialog)
                self.app.processEvents()
                self.assertEqual(dialog.metric_options, [])  # late result is dropped

    def test_closing_dialog_with_uninterruptible_loader_detaches_thread_without_crash(self):
        gate = threading.Event()
        seen_threads = []
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            with patch(
                'modules.characteristic_mapping_dialog.fetch_distinct_report_metric_names',
                side_effect=self._gated_fetch(gate, [{'metric_name': 'LATE'}], seen_threads),
            ), patch('modules.characteristic_mapping_dialog.fetch_distinct_references', return_value=[]), patch(
                'modules.characteristic_mapping_dialog.SOURCE_LOAD_STOP_WAIT_MS', 50
            ):
                dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
                thread = dialog._source_thread
                deadline = time.monotonic() + 5.0
                while not seen_threads and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(seen_threads)
                started = time.monotonic()
                dialog.close()
                self.assertLess(time.monotonic() - started, 2.0)  # bounded wait, never the 10 s gate
                self.assertTrue(thread.isRunning())
                self.assertTrue(detached_threads.is_registered(thread))

                gate.set()
                self.assertTrue(thread.wait(5000))
                deadline = time.monotonic() + 5.0
                while detached_threads.is_registered(thread) and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertFalse(detached_threads.is_registered(thread))
                self.assertEqual(dialog.metric_options, [])

    def test_cancel_loading_discards_result_and_explains_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            with patch(
                'modules.characteristic_mapping_dialog.fetch_distinct_report_metric_names',
                side_effect=self._interruptible_fetch([{'metric_name': 'LATE'}]),
            ), patch('modules.characteristic_mapping_dialog.fetch_distinct_references', return_value=[]):
                dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
                try:
                    progress_dialog = dialog._source_progress_dialog
                    progress_dialog.reject()  # the Cancel / window-close path of the indicator
                    self.assertFalse(dialog.is_loading_source_options())
                    self.assertIsNone(dialog._source_progress_dialog)
                    self.assertFalse(dialog.metric_empty_label.isHidden())
                    self.assertIn('canceled', dialog.metric_empty_label.text())
                    self.app.processEvents()
                    self.assertEqual(dialog.metric_table.rowCount(), 0)
                    self.assertTrue(dialog.add_button.isEnabled())
                finally:
                    dialog.close()

    def test_stale_load_results_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                self._wait_for_source_load(dialog)
                stale_id = dialog._source_request_id - 1
                dialog._on_source_options_loaded(stale_id, [{'metric_name': 'STALE'}], [])
                self.assertEqual(dialog.metric_options, [])
                with patch.object(QMessageBox, 'critical') as critical_mock:
                    dialog._on_source_options_failed(stale_id, RuntimeError('stale'))
                critical_mock.assert_not_called()
            finally:
                dialog.close()

    def test_source_options_load_real_measurement_database_matches_service(self):
        import sqlite3
        from contextlib import closing
        from modules.characteristic_mapping_service import (
            fetch_distinct_references,
            fetch_distinct_report_metric_names,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/reports.sqlite'
            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.execute(
                    'CREATE TABLE vw_measurement_export '
                    '(report_id INTEGER, measurement_id INTEGER, reference TEXT, header TEXT, ax TEXT)'
                )
                connection.executemany(
                    'INSERT INTO vw_measurement_export VALUES (?, ?, ?, ?, ?)',
                    [
                        (1, 1, 'REF-1', 'DIA', 'X'),
                        (2, 2, 'ref-2', 'DIA', 'X'),
                        (2, 3, 'REF-2', 'LEN', ''),
                        (3, 4, None, 'LEN', ''),
                    ],
                )

            dialog = CharacteristicMappingDialog(parent=None, db_file=db_path)
            try:
                self._wait_for_source_load(dialog)
                self.assertEqual(dialog.metric_options, fetch_distinct_report_metric_names(db_path))
                self.assertEqual(dialog.reference_options, fetch_distinct_references(db_path))
                self.assertEqual(dialog.metric_table.rowCount(), 2)
                self.assertEqual(dialog.metric_table.item(0, 0).text(), 'DIA - X')
                self.assertEqual(dialog.metric_table.item(0, 0).toolTip(), 'References: REF-1, ref-2')
            finally:
                dialog.close()


if __name__ == '__main__':
    unittest.main()


def test_editor_literal_callback_and_error_contract(qapplication_session):
    import importlib
    from PyQt6.QtCore import QThread
    native = importlib.import_module('metroliza.ui.characteristic_mapping_dialog')
    widgets = importlib.import_module('PyQt6.QtWidgets')
    assert native.QDialog is widgets.QDialog
    assert native.CharacteristicAliasEditorDialog is CharacteristicAliasEditorDialog
    calls = []

    def resolver(alias, scope, value):
        assert QThread.currentThread() is qapplication_session.thread()
        calls.append((alias, scope, value))
        if alias == 'ERROR':
            raise RuntimeError('literal preview error')
        return {'measurement_count': 1234, 'report_count': 12, 'reference_count': 3}

    editor = native.CharacteristicAliasEditorDialog(impact_resolver=resolver)
    try:
        assert editor.impact_label.text() == 'Select a report/export name to preview affected rows.'
        editor.alias_input.setCurrentText(' DIA - X ')
        assert editor.impact_label.text() == 'Affects 1,234 rows in 12 reports across 3 references.'
        editor.apply_to_combo.setCurrentText(ONE_REFERENCE_LABEL)
        assert editor.impact_label.text() == 'Select a reference to preview this reference-only match.'
        editor.reference_input.setCurrentText(' REF-1 ')
        assert calls == [('DIA - X', 'global', None), ('DIA - X', 'reference', 'REF-1')]
        with patch.object(native, 'CustomLogger') as logger:
            editor.alias_input.setCurrentText('ERROR')
        assert editor.impact_label.text() == 'Impact preview could not be loaded.'
        assert str(logger.call_args.args[0]) == 'literal preview error'
        editor.impact_resolver = None
        editor._refresh_impact_preview()
        assert editor.impact_label.text() == 'Impact preview is unavailable for this database.'
    finally:
        editor.close()


def _impact_native_dialog(tmp_path):
    import importlib
    native = importlib.import_module('metroliza.ui.characteristic_mapping_dialog')
    widgets = importlib.import_module('PyQt6.QtWidgets')
    assert native.QDialog is widgets.QDialog
    return native, native.CharacteristicMappingDialog(db_file=str(tmp_path / 'impact.sqlite'))


def _wait_impact(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def test_default_impact_refresh_close_and_reopen_stay_synchronous(tmp_path, qapplication_session):
    native, owner = _impact_native_dialog(tmp_path)
    _wait_impact(qapplication_session, lambda: not owner.is_loading_source_options())
    calls = []

    def fetch(db, **kwargs):
        assert QThread.currentThread() is qapplication_session.thread()
        calls.append((db, kwargs))
        return {'measurement_count': 9, 'report_count': 3, 'reference_count': 2}

    # The withdrawn background feature must not register an impact worker or
    # retain pending/debounced work. Existing source-option loading is separate.
    with patch.object(native, 'fetch_mapping_impact_counts', side_effect=fetch), patch.object(
        native.detached_threads, 'register', wraps=native.detached_threads.register,
    ) as register:
        editor = owner._build_editor()
        try:
            editor.alias_input.setCurrentText('DIA - X')
            editor.apply_to_combo.setCurrentText(ONE_REFERENCE_LABEL)
            editor.reference_input.setCurrentText('REF-1')
            assert editor.impact_label.text() == 'Affects 9 rows in 3 reports across 2 references.'
            assert calls[-1] == (owner.db_file, {'alias_name': 'DIA - X', 'scope_type': 'reference', 'scope_value': 'REF-1'})
            owner.db_file = str(tmp_path / 'changed.sqlite')
            editor.alias_input.setCurrentText('LATEST')
            assert calls[-1][0] == owner.db_file
            assert calls[-1][1]['alias_name'] == 'LATEST'
            editor.reject()
            editor.show()
            editor._refresh_impact_preview()
            assert editor.impact_label.text() == 'Affects 9 rows in 3 reports across 2 references.'
            assert not any(name.startswith('_impact_') for name in vars(editor))
            register.assert_not_called()
        finally:
            editor.close()
            owner.close()


def test_default_impact_current_error_and_zero_keep_public_dispatch(tmp_path, qapplication_session):
    native, owner = _impact_native_dialog(tmp_path)
    _wait_impact(qapplication_session, lambda: not owner.is_loading_source_options())
    editor = owner._build_editor()
    try:
        # Patch after construction: the saved built-in resolver must perform a
        # live public fetch lookup, including GUI callback/error semantics.
        with patch.object(native, 'fetch_mapping_impact_counts', side_effect=RuntimeError('public error')), patch.object(native, 'CustomLogger') as logger:
            editor.alias_input.setCurrentText('FAIL')
            assert editor.impact_label.text() == 'Impact preview could not be loaded.'
            assert str(logger.call_args.args[0]) == 'public error'
        with patch.object(native, 'fetch_mapping_impact_counts', return_value={}) as fetch:
            editor.alias_input.setCurrentText('ZERO')
            assert editor.impact_label.text() == 'Affects 0 rows in 0 reports across 0 references.'
            assert fetch.call_args.kwargs == {'alias_name': 'ZERO', 'scope_type': 'global', 'scope_value': None}
        assert not any(name.startswith('_impact_') for name in vars(editor))
    finally:
        editor.close()
        owner.close()


def test_mapping_instance_and_class_resolver_hooks_stay_on_gui(tmp_path, qapplication_session):
    native, owner = _impact_native_dialog(tmp_path)
    _wait_impact(qapplication_session, lambda: not owner.is_loading_source_options())
    calls = []

    def resolve(*args):
        assert QThread.currentThread() is qapplication_session.thread()
        calls.append(args)
        return {'measurement_count': 4, 'report_count': 2, 'reference_count': 1}

    try:
        for context in (patch.object(owner, '_resolve_impact_preview', resolve),
                        patch.object(native.CharacteristicMappingDialog, '_resolve_impact_preview', resolve)):
            with context:
                editor = owner._build_editor()
                try:
                    editor.alias_input.setCurrentText('CUSTOM')
                    assert editor.impact_label.text() == 'Affects 4 rows in 2 reports across 1 references.'
                    assert not any(name.startswith('_impact_') for name in vars(editor))
                finally:
                    editor.close()
        assert len(calls) == 2
    finally:
        owner.close()


def test_editor_legacy_standin_keeps_original_dispatch(qapplication_session):
    import importlib
    from types import SimpleNamespace
    native = importlib.import_module('metroliza.ui.characteristic_mapping_dialog')
    widgets = importlib.import_module('PyQt6.QtWidgets')
    assert native.QDialog is widgets.QDialog
    label = widgets.QLabel()
    calls = []
    standin = SimpleNamespace(
        alias_input=SimpleNamespace(currentText=lambda: ' DIA '), impact_label=label,
        _current_scope_payload=lambda: ('global', None),
        impact_resolver=lambda *args: calls.append(args) or {'measurement_count': 2})
    native.CharacteristicAliasEditorDialog._refresh_impact_preview(standin)
    assert calls == [('DIA', 'global', None)]
    assert label.text() == 'Affects 2 rows in 0 reports across 0 references.'


def test_editor_raw_keys_do_not_add_equality_callbacks(qapplication_session):
    import importlib
    native = importlib.import_module('metroliza.ui.characteristic_mapping_dialog')
    comparisons = []

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            comparisons.append(other)
            return False

    editor = native.CharacteristicAliasEditorDialog(impact_resolver=lambda *_args: {'measurement_count': 3})
    try:
        # Collides with a new async field; original refresh never looks this name up.
        editor.__dict__[Key('_impact_timer')] = 'observing key'
        comparisons.clear()
        editor.alias_input.setCurrentText('DIA')
        assert comparisons == []
        assert editor.impact_label.text() == 'Affects 3 rows in 0 reports across 0 references.'
    finally:
        # Remove via object identity so teardown still uses its actual timer.
        for key in tuple(editor.__dict__):
            if type(key) is Key:
                del editor.__dict__[key]
        editor.close()


def test_mapping_public_fetch_override_retains_gui_dispatch(tmp_path, qapplication_session):
    native, owner = _impact_native_dialog(tmp_path)
    _wait_impact(qapplication_session, lambda: not owner.is_loading_source_options())

    def fetch(db, **kwargs):
        assert QThread.currentThread() is qapplication_session.thread()
        assert db == owner.db_file
        assert kwargs == {'alias_name': 'CUSTOM', 'scope_type': 'global', 'scope_value': None}
        return {'measurement_count': 7}

    try:
        with patch.object(native, 'fetch_mapping_impact_counts', side_effect=fetch):
            editor = owner._build_editor()
            try:
                editor.alias_input.setCurrentText('CUSTOM')
                assert editor.impact_label.text() == 'Affects 7 rows in 0 reports across 0 references.'
                assert not any(name.startswith('_impact_') for name in vars(editor))
            finally:
                editor.close()
    finally:
        owner.close()


def test_impact_deleted_editor_leaves_no_new_worker(tmp_path, qapplication_session):
    import importlib
    core = importlib.import_module('PyQt6.QtCore')
    native, owner = _impact_native_dialog(tmp_path)
    _wait_impact(qapplication_session, lambda: not owner.is_loading_source_options())
    before = native.detached_threads.running_threads()
    editor = owner._build_editor()
    with patch.object(native, 'fetch_mapping_impact_counts', return_value={'measurement_count': 5}):
        editor.alias_input.setCurrentText('DIA')
        assert editor.impact_label.text() == 'Affects 5 rows in 0 reports across 0 references.'
    assert not any(name.startswith('_impact_') for name in vars(editor))
    editor.deleteLater()
    core.QCoreApplication.sendPostedEvents(None, core.QEvent.Type.DeferredDelete)
    assert native.detached_threads.running_threads() == before
    owner.close()


def test_editor_keeps_option_and_resolver_evaluation_order(tmp_path, qapplication_session):
    native, owner = _impact_native_dialog(tmp_path)
    _wait_impact(qapplication_session, lambda: not owner.is_loading_source_options())
    metrics, references, calls = owner.metric_options, owner.reference_options, []

    def resolve(*args):
        calls.append(args)
        return {'measurement_count': 6}

    def read_metrics(_owner):
        calls.append('metrics')
        owner._resolve_impact_preview = resolve
        return metrics

    def read_references(_owner):
        calls.append('references')
        return references

    try:
        with patch.object(native.CharacteristicMappingDialog, 'metric_options', property(read_metrics), create=True), patch.object(
            native.CharacteristicMappingDialog, 'reference_options', property(read_references), create=True,
        ):
            editor = owner._build_editor()
        try:
            editor.alias_input.setCurrentText('ORDER')
            assert calls == ['metrics', 'references', ('ORDER', 'global', None)]
            assert editor.impact_label.text() == 'Affects 6 rows in 0 reports across 0 references.'
        finally:
            editor.close()
    finally:
        owner.close()


def test_mapping_live_fetch_and_raw_key_transitions_keep_latest_output(tmp_path, qapplication_session):
    native, owner = _impact_native_dialog(tmp_path)
    _wait_impact(qapplication_session, lambda: not owner.is_loading_source_options())
    editor = owner._build_editor()
    comparisons, calls = [], []

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            comparisons.append(other)
            return False

    def fetch(_db, **kwargs):
        assert QThread.currentThread() is qapplication_session.thread()
        calls.append(kwargs['alias_name'])
        return {'measurement_count': 7 if kwargs['alias_name'] == 'B' else 3}

    try:
        editor.alias_input.setCurrentText('A')
        with patch.object(native, 'fetch_mapping_impact_counts', side_effect=fetch):
            editor.__dict__[Key('_impact_timer')] = 'unsupported key'
            comparisons.clear()
            editor.alias_input.setCurrentText('B')
            assert editor.impact_label.text() == 'Affects 7 rows in 0 reports across 0 references.'
            assert comparisons == []
            for key in tuple(editor.__dict__):
                if type(key) is Key:
                    del editor.__dict__[key]
            editor.alias_input.setCurrentText('C')
            assert editor.impact_label.text() == 'Affects 3 rows in 0 reports across 0 references.'
            qapplication_session.processEvents()
            assert calls == ['B', 'C']
            assert not any(name.startswith('_impact_') for name in vars(editor))
    finally:
        editor.close()
        owner.close()


def test_impact_application_quit_creates_no_preview_worker():
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent('''
        from unittest.mock import patch
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from metroliza.app.gc_policy import install
        from metroliza.ui import characteristic_mapping_dialog as native
        app = QApplication([])
        install(app)
        app.setQuitOnLastWindowClosed(False)
        owner = native.CharacteristicMappingDialog(db_file='')
        owner.db_file = 'unused.sqlite'
        with patch.object(native.detached_threads, 'register') as register:
            editor = owner._build_editor()
            with patch.object(native, 'fetch_mapping_impact_counts', return_value={'measurement_count': 7}):
                editor.alias_input.setCurrentText('DIA')
                assert editor.impact_label.text() == 'Affects 7 rows in 0 reports across 0 references.'
            QTimer.singleShot(0, app.quit)
            assert app.exec() == 0
            assert not any(name.startswith('_impact_') for name in vars(editor))
            register.assert_not_called()
            editor.close()
        owner.close()
    ''')
    completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr
