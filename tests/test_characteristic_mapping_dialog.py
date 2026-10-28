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
        # Existing import scenarios deliberately accept the newly required review.
        review = patch.object(CharacteristicMappingDialog, '_confirm_alias_import', return_value=True)
        review.start()
        cls.addClassCleanup(review.stop)

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


class TestAliasCsvBaseline(unittest.TestCase):
    """Literal public CSV behavior shared by the synchronous reference versions."""

    @classmethod
    def setUpClass(cls):
        TestCharacteristicMappingDialog.setUpClass.__func__(cls)

    def setUp(self):
        import importlib
        from pathlib import Path
        self.native = importlib.import_module('metroliza.ui.characteristic_mapping_dialog')
        self.service = importlib.import_module('metroliza.reports.characteristic_alias_service')
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.db = self.root / 'synthetic.sqlite'
        self.owner = self.native.CharacteristicMappingDialog(db_file='')
        self.addCleanup(self.owner.close)
        self.owner.db_file = str(self.db)

    def snapshot(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.db)) as connection:
            return {
                'catalog': connection.execute(
                    'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'
                ).fetchall(),
                'rows': connection.execute('SELECT * FROM CHARACTERISTIC_ALIASES ORDER BY id').fetchall(),
                'dump': tuple(connection.iterdump()),
            }

    def test_alias_csv_baseline_literal_roundtrip_repeat_and_reopen(self):
        source, target = self.root / 'input.csv', self.root / 'output.csv'
        source.write_text('\ufeff alias_name ,canonical_name,scope_type,scope_value\n'
                          ' z , Zed , GLOBAL ,discarded\n'
                          '001,Numeric,reference, 007 \n'
                          '"a,b","Quoted ""name""",global,\n', encoding='utf-8')
        expected = [
            {'alias_name': '001', 'canonical_name': 'Numeric', 'scope_type': 'reference', 'scope_value': '007'},
            {'alias_name': 'a,b', 'canonical_name': 'Quoted "name"', 'scope_type': 'global', 'scope_value': None},
            {'alias_name': 'z', 'canonical_name': 'Zed', 'scope_type': 'global', 'scope_value': None},
        ]
        calls = []
        load = self.owner.load_aliases

        def reload():
            self.assertIs(QThread.currentThread(), self.app.thread())
            calls.append('load')
            load()

        with patch.object(self.native.QFileDialog, 'getOpenFileName', return_value=(str(source), '')), patch.object(
            self.owner, 'load_aliases', side_effect=reload,
        ), patch.object(self.native.QMessageBox, 'information', side_effect=lambda *args: calls.append(args[1:])):
            for _ in range(2):
                self.owner.import_mappings()
                self.assertEqual(self.service.fetch_all_characteristic_aliases(str(self.db)), expected)
                self.assertEqual(self.owner.alias_table.rowCount(), 3)
        self.assertEqual(calls, ['load', ('Import complete', 'Imported 3 mapping row(s).'),
                                 'load', ('Import complete', 'Imported 0 mapping row(s).')])
        before = self.snapshot()
        self.assertEqual(before['rows'], [
            (1, 'z', 'Zed', 'global', None, None, None),
            (2, '001', 'Numeric', 'reference', '007', None, None),
            (3, 'a,b', 'Quoted "name"', 'global', None, None, None),
        ])
        with patch.object(self.native.QFileDialog, 'getSaveFileName', return_value=(str(target), '')), patch.object(
            self.native.QMessageBox, 'information',
        ) as info:
            for _ in range(2):
                self.owner.export_mappings()
                thread = getattr(self.owner, '_alias_csv_thread', None)
                if thread is not None:
                    deadline = time.monotonic() + 10
                    while (self.owner._alias_csv_thread is not None or
                           self.native.detached_threads.is_registered(thread)) and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    self.assertIsNone(self.owner._alias_csv_thread)
                    self.assertFalse(self.native.detached_threads.is_registered(thread))
                self.assertEqual(target.read_bytes(), (
                    b'alias_name,canonical_name,scope_type,scope_value\r\n'
                    b'001,Numeric,reference,007\r\n'
                    b'"a,b","Quoted ""name""",global,\r\nz,Zed,global,\r\n'))
        self.assertEqual(info.call_args.args[1:], ('Export complete', 'Exported 3 mapping row(s).'))
        self.assertEqual(self.snapshot(), before)
        self.owner.close()
        reopened = self.native.CharacteristicMappingDialog(db_file='')
        try:
            reopened.db_file = str(self.db)
            reopened.load_aliases()
            self.assertEqual([[reopened.alias_table.item(r, c).text() for c in range(4)] for r in range(3)], [
                ['001', 'Numeric', ONE_REFERENCE_LABEL, '007'],
                ['a,b', 'Quoted "name"', ALL_REFERENCES_LABEL, '—'],
                ['z', 'Zed', ALL_REFERENCES_LABEL, '—'],
            ])
            self.assertEqual(self.snapshot(), before)
        finally:
            reopened.close()

    def test_alias_csv_baseline_real_validation_atomicity_and_remediation_choices(self):
        import csv
        source, report = self.root / 'invalid.csv', self.root / 'report.csv'
        self.service.ensure_characteristic_alias_schema(str(self.db))
        self.service.upsert_characteristic_alias(str(self.db), 'KEEP', 'Kept', 'global')
        before = self.snapshot()
        source.write_text('alias_name,canonical_name,scope_type,scope_value\n'
                          'A,C,global,\n A ,Other, GLOBAL ,ignored\nR,C,reference,\n'
                          'S,C,wat,\nQ,,global,\nVALID,C,global,\n', encoding='utf-8')
        issues = [
            (3, 'alias_name', 'duplicate_key_collision', 'duplicate_collision',
             'duplicate alias/scope key for "A" (global) at row 3; first seen at row 2',
             'Remove or merge duplicate alias rows with the same alias_name + scope.'),
            (4, 'scope_value', 'reference_scope_requires_scope_value', 'scope_requirements',
             'scope_value is required for reference scope at row 4', 'Set scope_value for reference-scoped aliases.'),
            (5, 'scope_type', 'invalid_scope_type', 'invalid_value',
             'scope_type must be one of: global, reference at row 5', "Use scope_type 'global' or 'reference'."),
            (6, 'canonical_name', 'missing_canonical_name', 'missing_required_field',
             'canonical_name is required at row 6', 'Provide the canonical_name to map this alias to.'),
        ]
        with self.assertRaises(self.service.CharacteristicAliasImportValidationError) as caught:
            self.service.import_characteristic_aliases_csv(str(self.db), str(source))
        fields = ('row_number', 'field', 'code', 'category', 'message', 'remediation_hint')
        self.assertEqual(caught.exception.row_error_details, [dict(zip(fields, issue)) for issue in issues])
        self.assertEqual((caught.exception.total_rows_processed, caught.exception.valid_rows, caught.exception.invalid_rows), (6, 2, 4))
        self.assertEqual(self.snapshot(), before)
        for accept, filename in [(False, ''), (True, ''), (True, str(report))]:
            with self.subTest(accept=accept, filename=bool(filename)), patch.object(
                self.native.QFileDialog, 'getOpenFileName', return_value=(str(source), ''),
            ), patch.object(self.native.QFileDialog, 'getSaveFileName', return_value=(filename, '')) as save, patch.object(
                self.native.QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Ok,
            ), patch.object(self.native.QMessageBox, 'question', return_value=(
                QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No
            )), patch.object(self.native.QMessageBox, 'information') as info, patch.object(
                self.native, 'CustomLogger',
            ), patch.object(self.owner, 'load_aliases') as load:
                self.owner.import_mappings()
                load.assert_not_called()
                self.assertEqual(save.call_count, int(accept))
                self.assertEqual(info.call_count, int(bool(filename)))
                box = self.owner.findChildren(QMessageBox)[-1]
                self.assertEqual(box.windowTitle(), 'Import error')
                for text in ('Total rows processed: 6', 'Valid rows: 2', 'Invalid rows: 4', 'duplicate_collision: 1'):
                    self.assertIn(text, box.text())
                for issue in issues:
                    self.assertIn(issue[4], box.detailedText())
                    self.assertIn(issue[5], box.detailedText())
                if filename:
                    self.assertEqual(info.call_args.args[1:], ('Report saved', 'Saved remediation report with 4 row issue(s).'))
            self.assertEqual(self.snapshot(), before)
        with report.open(newline='', encoding='utf-8') as stream:
            self.assertEqual(list(csv.reader(stream)), [list(fields)] + [[str(value) for value in issue] for issue in issues])

    def test_alias_csv_baseline_schema_and_missing_header_messages(self):
        source = self.root / 'schema.csv'
        self.service.ensure_characteristic_alias_schema(str(self.db))
        before = self.snapshot()
        for contents, detected in [('', '(none)'), ('canonical_name,alias_name\n', 'canonical_name, alias_name')]:
            source.write_text(contents, encoding='utf-8')
            with self.subTest(contents=contents), patch.object(
                self.native.QFileDialog, 'getOpenFileName', return_value=(str(source), ''),
            ), patch.object(self.native.QMessageBox, 'critical') as critical, patch.object(
                self.native, 'CustomLogger',
            ), patch.object(self.owner, 'load_aliases') as load:
                self.owner.import_mappings()
                critical.assert_called_once_with(self.owner, 'Import error',
                    'Could not import mappings because the CSV header row does not match the expected schema.\n\n'
                    'Required columns: alias_name, canonical_name, scope_type, scope_value\n'
                    f'Detected columns: {detected}\n\nUse this exact header line (same names and order):\n'
                    'alias_name,canonical_name,scope_type,scope_value')
                load.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_alias_csv_baseline_public_standin_dispatch_order_cancel_and_errors(self):
        from contextlib import ExitStack
        from types import SimpleNamespace
        comparisons = []

        class Key(str):
            __hash__ = str.__hash__

            def __eq__(self, other):
                comparisons.append(other)
                return False

        for operation in ('import', 'export'):
            for mode in ('success', 'cancel', 'error', 'schema_error'):
                events = []

                def record(name, result=None, error=None):
                    def callback(*args, **kwargs):
                        self.assertIs(QThread.currentThread(), self.app.thread())
                        events.append((name, args, kwargs))
                        if error:
                            raise RuntimeError(error)
                        return result
                    return callback

                standin = SimpleNamespace(
                    db_file='synthetic-hook.sqlite',
                    _ensure_db_file_selected=record('selected', True),
                    load_aliases=record('load'),
                )
                standin.__dict__[Key('_alias_csv_task')] = 'existing extension value'
                comparisons.clear()
                filename = '' if mode == 'cancel' else 'synthetic-hook.csv'
                with self.subTest(operation=operation, mode=mode), ExitStack() as stack:
                    dialog_method = 'getOpenFileName' if operation == 'import' else 'getSaveFileName'
                    stack.enter_context(patch.object(self.native.QFileDialog, dialog_method, side_effect=record('file', (filename, ''))))
                    stack.enter_context(patch.object(self.native, 'ensure_characteristic_alias_schema', side_effect=record(
                        'schema', error='schema failed' if mode == 'schema_error' else None)))
                    stack.enter_context(patch.object(self.native, f'{operation}_characteristic_aliases_csv', side_effect=record(
                        'producer', 17, 'producer failed' if mode == 'error' else None)))
                    for name in ('information', 'critical'):
                        stack.enter_context(patch.object(self.native.QMessageBox, name, side_effect=record(name)))
                    stack.enter_context(patch.object(self.native, 'CustomLogger', side_effect=record('log')))
                    getattr(self.native.CharacteristicMappingDialog, f'{operation}_mappings')(standin)
                expected = ['selected', 'file']
                if mode != 'cancel':
                    expected += ['schema']
                    if mode != 'schema_error':
                        expected += ['producer']
                    expected += (['load'] if operation == 'import' else []) + ['information'] if mode == 'success' else ['log', 'critical']
                self.assertEqual([event[0] for event in events], expected)
                self.assertEqual(comparisons, [])
                if mode in ('success', 'error'):
                    self.assertEqual(events[3][1:], (('synthetic-hook.sqlite', filename), {}))
                if mode == 'success':
                    verb = 'Imported' if operation == 'import' else 'Exported'
                    self.assertEqual(events[-1][1], (standin, f'{operation.title()} complete', f'{verb} 17 mapping row(s).'))
                elif mode in ('error', 'schema_error'):
                    message = 'producer failed' if mode == 'error' else 'schema failed'
                    self.assertEqual(events[-2][2], {'reraise': False})
                    self.assertEqual(events[-1][1], (standin, f'{operation.title()} error', f'Could not {operation} mappings: {message}'))


class TestAliasCsvBackground(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestCharacteristicMappingDialog.setUpClass.__func__(cls)

    def setUp(self):
        TestAliasCsvBaseline.setUp(self)
        self._cleanups.pop()  # replace close with a cleanup safe after explicit native deletion
        self.addCleanup(self.close_owner)
        self.source = self.root / 'native.csv'
        self.source.write_text('alias_name,canonical_name,scope_type,scope_value\nDIA,Diameter,global,\n')

    def close_owner(self):
        from PyQt6 import sip
        if not sip.isdeleted(self.owner):
            self.owner.close()

    def wait(self, predicate):
        deadline = time.monotonic() + 10
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertTrue(predicate())

    def test_native_csv_actual_services_controls_and_gui_delivery(self):
        native = self.native
        real_run = native._AliasCsvThread.run
        for operation in ('import', 'export'):
            gate, started, events = threading.Event(), threading.Event(), []
            def held(thread):
                events.append(('worker', QThread.currentThread() is self.app.thread()))
                started.set()
                if not gate.wait(8):
                    thread.error = RuntimeError('test gate expired')
                    return
                real_run(thread)
            target = self.root / 'native-export.csv'
            def info(*_args):
                events.append(('info', QThread.currentThread() is self.app.thread()))
            self.owner.export_button.setEnabled(False)
            states = [getattr(self.owner, name).isEnabled() for name in native._ALIAS_CSV_CONTROLS]
            with patch.object(native._AliasCsvThread, 'run', held), patch.object(
                native.QFileDialog, 'getOpenFileName', return_value=(str(self.source), ''),
            ) as opening, patch.object(native.QFileDialog, 'getSaveFileName', return_value=(str(target), '')) as saving, patch.object(
                native.QMessageBox, 'information', side_effect=info,
            ):
                getattr(self.owner, operation + '_mappings')()
                thread = self.owner._alias_csv_thread
                self.wait(started.is_set)
                self.assertTrue(native.detached_threads.is_registered(thread))
                self.assertTrue(all(not getattr(self.owner, name).isEnabled() for name in native._ALIAS_CSV_CONTROLS))
                getattr(self.owner, operation + '_mappings')()
                self.assertEqual((opening if operation == 'import' else saving).call_count, 1)
                self.assertEqual(events, [('worker', False)])
                gate.set()
                self.wait(lambda: self.owner._alias_csv_thread is None)
                self.wait(lambda: not native.detached_threads.is_registered(thread))
            self.assertEqual(events, [('worker', False), ('info', True)])
            self.assertEqual([getattr(self.owner, name).isEnabled() for name in native._ALIAS_CSV_CONTROLS], states)
        self.assertEqual(target.read_bytes(), b'alias_name,canonical_name,scope_type,scope_value\r\nDIA,Diameter,global,\r\n')
        self.assertEqual(self.owner.alias_table.item(0, 1).text(), 'Diameter')

    def test_native_csv_raw_keys_custom_producer_and_class_hook_keep_gui_fallback(self):
        comparisons, calls = [], []
        native, original_load = self.native, self.native.CharacteristicMappingDialog.load_aliases
        class Key(str):
            __hash__ = str.__hash__
            def __eq__(self, other):
                comparisons.append(other)
                return False
        class Filename(str):
            pass
        def load(owner):
            calls.append(('load', QThread.currentThread() is self.app.thread()))
            original_load(owner)
        def produce(db, filename):
            calls.append(('producer', QThread.currentThread() is self.app.thread()))
            return self.service.import_characteristic_aliases_csv(db, filename)
        from contextlib import ExitStack
        for mode in ('raw-key', 'producer', 'class-hook', 'filename'):
            with self.subTest(mode=mode), ExitStack() as stack:
                comparisons.clear()
                if mode == 'raw-key':
                    self.owner.__dict__[Key('_alias_csv_thread')] = 'legacy extension'
                    comparisons.clear()
                elif mode == 'producer':
                    stack.enter_context(patch.object(native, 'import_characteristic_aliases_csv', side_effect=produce))
                elif mode == 'class-hook':
                    stack.enter_context(patch.object(native.CharacteristicMappingDialog, 'load_aliases', load))
                filename = Filename(str(self.source)) if mode == 'filename' else str(self.source)
                stack.enter_context(patch.object(native.QFileDialog, 'getOpenFileName', return_value=(filename, '')))
                info = stack.enter_context(patch.object(native.QMessageBox, 'information'))
                worker = stack.enter_context(patch.object(native, '_AliasCsvThread'))
                self.owner.import_mappings()
                worker.assert_not_called()
                count = 0 if mode in ('class-hook', 'filename') else 1
                info.assert_called_once_with(self.owner, 'Import complete', f'Imported {count} mapping row(s).')
                self.assertEqual(comparisons, [])
                for key in tuple(vars(self.owner)):
                    if type(key) is Key:
                        del vars(self.owner)[key]
        self.assertEqual(calls, [('producer', True), ('load', True)])

    def test_native_csv_close_stale_database_delete_and_late_error_drop_delivery(self):
        from PyQt6 import sip
        for action in ('close', 'database', 'delete'):
            owner = self.native.CharacteristicMappingDialog(db_file='')
            owner.db_file = str(self.root / (action + '.sqlite'))
            owner.show()
            gate, started = threading.Event(), threading.Event()
            def held(thread):
                started.set()
                gate.wait(8)
                thread.error = RuntimeError('literal late error')
            with patch.object(self.native._AliasCsvThread, 'run', held), patch.object(
                self.native.QFileDialog, 'getOpenFileName', return_value=(str(self.source), ''),
            ), patch.object(self.native.QMessageBox, 'critical') as critical, patch.object(
                self.native.QMessageBox, 'information',
            ) as info:
                owner.import_mappings()
                thread = owner._alias_csv_thread
                self.wait(started.is_set)
                if action == 'close':
                    owner.close()
                    owner.show()
                elif action == 'database':
                    owner.db_file = str(self.root / 'new.sqlite')
                else:
                    sip.delete(owner)
                gate.set()
                self.wait(lambda: not self.native.detached_threads.is_registered(thread))
                critical.assert_not_called()
                info.assert_not_called()
            if not sip.isdeleted(owner):
                self.assertIsNone(owner._alias_csv_thread)
                owner.close()

    def test_native_csv_validation_start_failure_and_reentrant_delivery(self):
        self.source.write_text('alias_name,canonical_name,scope_type,scope_value\nDIA,,global,\n')
        with patch.object(self.native.QFileDialog, 'getOpenFileName', return_value=(str(self.source), '')), patch.object(
            self.native.QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Ok,
        ), patch.object(self.native.QMessageBox, 'question', return_value=QMessageBox.StandardButton.No), patch.object(
            self.native, 'CustomLogger',
        ) as logger:
            self.owner.import_mappings()
            self.wait(lambda: self.owner._alias_csv_thread is None)
        self.assertIsInstance(logger.call_args.args[0], self.service.CharacteristicAliasImportValidationError)
        self.assertIn('canonical_name is required at row 2', self.owner.findChildren(QMessageBox)[-1].detailedText())
        self.assertFalse(self.db.exists())  # Validation/preview must not create a database.
        before = self.native.detached_threads.running_threads()
        with patch.object(self.native._AliasCsvThread, 'start', side_effect=RuntimeError('start failed')), patch.object(
            self.native.QFileDialog, 'getOpenFileName', return_value=(str(self.source), ''),
        ), patch.object(self.native, 'CustomLogger'), patch.object(self.native.QMessageBox, 'critical') as critical:
            self.owner.import_mappings()
        self.assertEqual(critical.call_args.args[1:], ('Import error', 'Could not import mappings: start failed'))
        self.assertIsNone(self.owner._alias_csv_thread)
        self.assertEqual(self.native.detached_threads.running_threads(), before)
        self.source.write_text('alias_name,canonical_name,scope_type,scope_value\nDIA,Diameter,global,\n')
        observed = []
        def information(*_args):
            observed.append(self.owner._alias_csv_thread is not None)
            self.owner.import_mappings()
            self.app.processEvents()
            observed.append(self.native.detached_threads.is_registered(self.owner._alias_csv_thread))
        with patch.object(self.native.QFileDialog, 'getOpenFileName', return_value=(str(self.source), '')) as opening, patch.object(
            self.native.QMessageBox, 'information', side_effect=information,
        ):
            self.owner.import_mappings()
            self.wait(lambda: self.owner._alias_csv_thread is None)
        self.assertEqual(observed, [True, True])
        self.assertEqual(opening.call_count, 1)


def test_csv_completion_uses_current_selection_and_keeps_restrictions(tmp_path, qapplication_session):
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QTableWidgetItem
    from metroliza.ui import characteristic_mapping_dialog as native
    from metroliza.reports import characteristic_alias_service as service

    for mode in ('select', 'deselect', 'restricted'):
        db = str(tmp_path / (mode + '.sqlite'))
        service.ensure_characteristic_alias_schema(db)
        service.upsert_characteristic_alias(db, 'A', 'Common', 'global')
        owner = native.CharacteristicMappingDialog(db_file='')
        owner.db_file = db
        owner.load_aliases()
        owner.metric_table.setRowCount(1)
        owner.metric_table.setItem(0, 0, QTableWidgetItem('A'))
        if mode != 'select':
            owner.alias_table.selectRow(0)
            owner.metric_table.selectRow(0)
        if mode == 'restricted':
            owner.edit_button.setEnabled(False)
        owner.export_button.setEnabled(False)
        entered, release = threading.Event(), threading.Event()
        real_fetch = service.fetch_all_characteristic_aliases

        def interact():
            if mode == 'select':
                owner.alias_table.selectRow(0)
                owner.metric_table.selectRow(0)
            elif mode == 'deselect':
                owner.alias_table.clearSelection()
                owner.metric_table.clearSelection()

        def held(*args, **kwargs):
            entered.set()
            if QThread.currentThread() is qapplication_session.thread():
                interact()  # original synchronous reference has no admitted event-loop gap
            elif not release.wait(8):
                raise TimeoutError('selection gate expired')
            return real_fetch(*args, **kwargs)

        thread = None
        try:
            with patch.object(service, 'fetch_all_characteristic_aliases', held), patch.object(
                native.QFileDialog, 'getSaveFileName', return_value=(str(tmp_path / (mode + '.csv')), ''),
            ), patch.object(native.QMessageBox, 'information'):
                owner.export_mappings()
                thread = getattr(owner, '_alias_csv_thread', None)
                if thread is not None:
                    deadline = time.monotonic() + 8
                    while not entered.is_set() and time.monotonic() < deadline:
                        QTest.qWait(5)
                    assert entered.is_set()
                    interact()
                release.set()
                deadline = time.monotonic() + 10
                while thread is not None and detached_threads.is_registered(thread) and time.monotonic() < deadline:
                    QTest.qWait(5)
                assert thread is None or not detached_threads.is_registered(thread)
            assert owner.add_from_selected_button.isEnabled() == (mode != 'deselect')
            assert owner.edit_button.isEnabled() == (mode == 'select')
            assert owner.delete_button.isEnabled() == (mode != 'deselect')
            if mode == 'restricted':
                assert not owner.export_button.isEnabled()
        finally:
            release.set()
            if thread is not None:
                deadline = time.monotonic() + 10
                while detached_threads.is_registered(thread) and time.monotonic() < deadline:
                    QTest.qWait(5)
                assert not detached_threads.is_registered(thread)
            owner.close()


def test_csv_selection_getter_hooks_keep_original_export_callbacks(tmp_path, qapplication_session):
    from contextlib import ExitStack
    from PyQt6.QtTest import QTest
    from metroliza.ui import characteristic_mapping_dialog as native
    from metroliza.reports import characteristic_alias_service as service

    for mode in ('instance', 'class'):
        db = str(tmp_path / (mode + '.sqlite'))
        output = tmp_path / (mode + '.csv')
        service.ensure_characteristic_alias_schema(db)
        service.upsert_characteristic_alias(db, 'A', 'Common', 'global')
        owner = native.CharacteristicMappingDialog(db_file='')
        owner.db_file = db
        events = []
        try:
            with ExitStack() as stack:
                for name in ('_selected_metric_option', '_selected_mapping'):
                    def selected(*args, name=name):
                        events.append(name)
                        return None
                    stack.enter_context(patch.object(owner if mode == 'instance' else type(owner), name, selected))
                def filename(*args):
                    events.append('filename')
                    return str(output), ''
                stack.enter_context(patch.object(native.QFileDialog, 'getSaveFileName', side_effect=filename))
                stack.enter_context(patch.object(native.QMessageBox, 'information',
                                                side_effect=lambda *args: events.append('information')))
                owner.export_mappings()
                thread = getattr(owner, '_alias_csv_thread', None)
                deadline = time.monotonic() + 10
                while thread is not None and detached_threads.is_registered(thread) and time.monotonic() < deadline:
                    QTest.qWait(5)
                assert thread is None or not detached_threads.is_registered(thread)
                assert events == ['filename', 'information']
                assert output.read_bytes() == (b'alias_name,canonical_name,scope_type,scope_value\r\n'
                                               b'A,Common,global,\r\n')
        finally:
            owner.close()


def test_csv_close_preserves_durable_import_order(tmp_path, qapplication_session):
    from PyQt6.QtTest import QTest
    from metroliza.ui import characteristic_mapping_dialog as native
    from metroliza.reports import characteristic_alias_service as service

    for action in ('close', 'done', 'reject'):
        db = str(tmp_path / (action + '.sqlite'))
        source = tmp_path / (action + '.csv')
        source.write_text('alias_name,canonical_name,scope_type,scope_value\nA,Old,global,\n')
        owner = native.CharacteristicMappingDialog(db_file='')
        owner.db_file = db
        owner.show()
        entered, release, events = threading.Event(), threading.Event(), []
        real_upsert = service.upsert_characteristic_aliases_bulk

        def held(*args, **kwargs):
            entered.set()
            if QThread.currentThread() is not qapplication_session.thread() and not release.wait(8):
                raise TimeoutError('import gate expired')
            result = real_upsert(*args, **kwargs)
            events.append('old-durable')
            return result

        def next_action():
            service.upsert_characteristic_alias(db, 'A', 'New', 'global')
            events.append('new-durable')

        thread = None
        try:
            with patch.object(service, 'upsert_characteristic_aliases_bulk', held), patch.object(
                native.QFileDialog, 'getOpenFileName', return_value=(str(source), ''),
            ), patch.object(native.QMessageBox, 'information'), patch.object(
                native.CharacteristicMappingDialog, '_confirm_alias_import', return_value=True,
            ):
                owner.import_mappings()
                thread = getattr(owner, '_alias_csv_thread', None)
                deadline = time.monotonic() + 8
                while not entered.is_set() and time.monotonic() < deadline:
                    QTest.qWait(5)
                assert entered.is_set()
                if action == 'done':
                    owner.done(1)
                else:
                    getattr(owner, action)()
                if not owner.isVisible():
                    next_action()  # only a returned modal owner admits the next same-DB action
                release.set()
                deadline = time.monotonic() + 10
                while thread is not None and detached_threads.is_registered(thread) and time.monotonic() < deadline:
                    QTest.qWait(5)
                assert thread is None or not detached_threads.is_registered(thread)
                assert not owner.isVisible()
                assert owner.result() == (1 if action == 'done' else 0)
                if 'new-durable' not in events:
                    next_action()
            assert events == ['old-durable', 'new-durable']
            assert service.fetch_all_characteristic_aliases(db)[0]['canonical_name'] == 'New'
        finally:
            release.set()
            if thread is not None:
                deadline = time.monotonic() + 10
                while detached_threads.is_registered(thread) and time.monotonic() < deadline:
                    QTest.qWait(5)
                assert not detached_threads.is_registered(thread)
            owner.close()


def test_csv_native_owner_destroyed_inside_result_modal(tmp_path):
    import subprocess
    import sys
    script = r'''
import sys,time
from pathlib import Path
from unittest.mock import patch
from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication,QMessageBox
from metroliza.app.gc_policy import install
from metroliza.ui import characteristic_mapping_dialog as native
from metroliza.reports import characteristic_alias_service as service
root=Path(sys.argv[1]);mode=sys.argv[2];root.mkdir()
operation='export' if mode=='export' else 'import'
app=QApplication([]);install(app);app.setQuitOnLastWindowClosed(False)
db=str(root/'data.sqlite');source=root/'data.csv'
source.write_text('alias_name,canonical_name,scope_type,scope_value\nA,Common,global,\n')
if mode=='validation':source.write_text('alias_name,canonical_name,scope_type,scope_value\nA,,global,\n')
if mode=='error':source.unlink()
service.ensure_characteristic_alias_schema(db);service.upsert_characteristic_alias(db,'A','Common','global')
owner=native.CharacteristicMappingDialog(db_file='');owner.db_file=db
events=[]
real_exec=QMessageBox.exec
def modal(box):
    def destroy():
        events.append('destroyed-in-modal');sip.delete(owner)
    QTimer.singleShot(0,destroy)
    return real_exec(box)
def information(*args):
    box=QMessageBox(owner);box.setText(args[2])
    box.exec()
with patch.object(native.QFileDialog,'getOpenFileName',return_value=(str(source),'')),patch.object(native.QFileDialog,'getSaveFileName',return_value=(str(root/'export.csv'),'')),patch.object(native.QMessageBox,'information',side_effect=information),patch.object(native.QMessageBox,'critical',side_effect=information),patch.object(native.QMessageBox,'exec',modal),patch.object(native,'CustomLogger'):
    getattr(owner,operation+'_mappings')()
    thread=vars(owner).get('_alias_csv_thread')
    deadline=time.monotonic()+10
    while (not sip.isdeleted(owner) or native.detached_threads.running_threads()) and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
assert sip.isdeleted(owner)
assert events==['destroyed-in-modal'],events
assert not native.detached_threads.running_threads()
if thread is not None:
    deadline=time.monotonic()+10
    while not sip.isdeleted(thread) and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    assert sip.isdeleted(thread)
assert service.fetch_all_characteristic_aliases(db)[0]['canonical_name']=='Common'
print('NATIVE RESULT DELETE PASS',mode,events,flush=True)
'''
    for operation in ('import', 'export', 'validation', 'error'):
        result = subprocess.run([sys.executable, '-c', script, str(tmp_path / operation), operation],
                                capture_output=True, text=True, timeout=20)
        (tmp_path / (operation + '.log')).write_text(result.stdout + result.stderr)
        print('native deletion child exit', operation, result.returncode, result.stdout, result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr


def test_alias_csv_native_normal_quit_and_owner_close_process(tmp_path):
    import subprocess
    import sys
    import textwrap
    code = textwrap.dedent('''
        from pathlib import Path
        from threading import Event
        from unittest.mock import patch
        import sys,time
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from metroliza.app.gc_policy import install
        from metroliza.ui import characteristic_mapping_dialog as native
        from metroliza.reports import characteristic_alias_service as service
        operation,mode,root=sys.argv[1],sys.argv[2],Path(sys.argv[3]);root.mkdir()
        db=str(root/'synthetic.sqlite');source=root/'input.csv';target=root/'export.csv'
        source.write_text('alias_name,canonical_name,scope_type,scope_value\\nDIA,Diameter,global,\\n')
        service.ensure_characteristic_alias_schema(db)
        if operation=='export':service.upsert_characteristic_alias(db,'DIA','Diameter','global')
        app=QApplication([]);install(app);owner=native.CharacteristicMappingDialog(db_file='');owner.db_file=db;owner.show()
        native.CharacteristicMappingDialog._confirm_alias_import=lambda self,plan:True
        started=Event();real_run=native._AliasCsvThread.run;events=[];beats=[]
        def held(thread):
            started.set();time.sleep(5.2);real_run(thread)
        def request():
            if not started.is_set():return
            timer.stop();events.append(('started-visible',owner.isVisible()))
            if mode=='close':owner.close()
            else:app.quit()
        timer=QTimer();timer.setInterval(5);timer.timeout.connect(request)
        heartbeat=QTimer();heartbeat.setInterval(20);heartbeat.timeout.connect(lambda:beats.append(1));heartbeat.start()
        with patch.object(native._AliasCsvThread,'run',held),patch.object(native.QFileDialog,'getOpenFileName',return_value=(str(source),'')),patch.object(native.QFileDialog,'getSaveFileName',return_value=(str(target),'')),patch.object(native.QMessageBox,'information',side_effect=lambda *args:events.append(('information',args[1],args[2]))):
            getattr(owner,operation+'_mappings')();timer.start();assert app.exec()==0
        assert events[0]==('started-visible',True),events
        assert len(beats)>100,len(beats)
        assert not native.detached_threads.running_threads()
        expected=[] if operation=='import' and mode=='close' else [{'alias_name':'DIA','canonical_name':'Diameter','scope_type':'global','scope_value':None}]
        assert service.fetch_all_characteristic_aliases(db)==expected
        if operation=='export':assert target.read_bytes()==b'alias_name,canonical_name,scope_type,scope_value\\r\\nDIA,Diameter,global,\\r\\n'
        assert len(events)==(1 if mode=='close' else 2),events
        owner.close();print('NATIVE PASS',operation,mode,events,len(beats),flush=True)
    ''')
    for operation in ('import', 'export'):
        for mode in ('quit', 'close'):
            result = subprocess.run([sys.executable, '-c', code, operation, mode, str(tmp_path / (operation + '-' + mode))],
                                    capture_output=True, text=True, timeout=20)
            (tmp_path / (operation + '-' + mode + '.log')).write_text(result.stdout + result.stderr)
            print(result.stdout + result.stderr)
            assert result.returncode == 0, result.stdout + result.stderr
