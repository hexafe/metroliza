import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from modules.contracts import validate_export_options
from modules.export_preset_utils import (
    EXPORT_PRESET_DEFAULT,
    EXPORT_PRESET_FAST_DIAGNOSTICS,
    EXPORT_PRESET_FULL_REPORT,
    build_export_options_for_preset,
    get_export_preset_id_for_label,
    load_export_dialog_config,
    migrate_export_dialog_config,
    save_export_dialog_config,
)


class TestExportPresetSerialization(unittest.TestCase):
    def test_load_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / '.metroliza' / '.export_dialog_config.json'
            payload = {'selected_preset': EXPORT_PRESET_FULL_REPORT}
            save_export_dialog_config(config_path, payload)

            loaded = load_export_dialog_config(config_path)
            self.assertEqual(loaded, payload)

    def test_migrate_defaults_for_existing_users(self):
        migrated, changed = migrate_export_dialog_config({})
        self.assertTrue(changed)
        self.assertEqual(migrated['selected_preset'], EXPORT_PRESET_DEFAULT)

        migrated_invalid, changed_invalid = migrate_export_dialog_config({'selected_preset': 'legacy'})
        self.assertTrue(changed_invalid)
        self.assertEqual(migrated_invalid['selected_preset'], EXPORT_PRESET_DEFAULT)

    def test_load_export_dialog_config_malformed_json_logs_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / '.metroliza' / '.export_dialog_config.json'
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text('{"selected_preset":', encoding='utf-8')

            with patch('modules.export_preset_utils.logger.warning') as warning_mock:
                loaded = load_export_dialog_config(config_path)

            self.assertEqual({}, loaded)
            warning_mock.assert_called_once()
            args = warning_mock.call_args.args
            self.assertEqual(config_path, args[1])
            self.assertEqual('JSONDecodeError', args[2])

    def test_load_export_dialog_config_unreadable_logs_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / '.metroliza' / '.export_dialog_config.json'
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text('{}', encoding='utf-8')

            with patch('pathlib.Path.open', side_effect=OSError('permission denied')):
                with patch('modules.export_preset_utils.logger.warning') as warning_mock:
                    loaded = load_export_dialog_config(config_path)

            self.assertEqual({}, loaded)
            warning_mock.assert_called_once()
            args = warning_mock.call_args.args
            self.assertEqual(config_path, args[1])
            self.assertEqual('OSError', args[2])


class TestExportPresetOptionMapping(unittest.TestCase):
    def test_preset_option_baselines(self):
        fast = build_export_options_for_preset(EXPORT_PRESET_FAST_DIAGNOSTICS)
        full = build_export_options_for_preset(EXPORT_PRESET_FULL_REPORT)

        self.assertFalse(fast['generate_summary_sheet'])
        self.assertTrue(full['generate_summary_sheet'])
        self.assertGreaterEqual(fast['violin_plot_min_samplesize'], full['violin_plot_min_samplesize'])


    def test_preset_labels_match_export_dialog_copy(self):
        from modules.export_preset_utils import get_export_preset_label

        self.assertEqual(get_export_preset_label(EXPORT_PRESET_FAST_DIAGNOSTICS), 'Main plots')
        self.assertEqual(get_export_preset_label(EXPORT_PRESET_FULL_REPORT), 'Extended plots')

    def test_validate_export_options_keeps_preset(self):
        full = build_export_options_for_preset(EXPORT_PRESET_FULL_REPORT)
        options = validate_export_options(
            type('Obj', (), {'preset': EXPORT_PRESET_FULL_REPORT, **full})()
        )
        self.assertEqual(options.preset, EXPORT_PRESET_FULL_REPORT)
        self.assertTrue(options.generate_summary_sheet)


class TestExportPresetFlowIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._missing = object()
        cls._saved_modules = {
            module_name: sys.modules.get(module_name)
            for module_name in [
                'PyQt6.QtCore',
                'PyQt6.QtGui',
                'PyQt6.QtWidgets',
                'modules.base64_encoded_files',
                'modules.export_data_thread',
                'modules.filter_dialog',
                'modules.data_grouping',
                'modules.custom_logger',
                'modules.export_dialog',
            ]
        }
        cls._saved_module_attrs = {
            ('modules.export_data_thread', 'ExportDataThread'): getattr(sys.modules.get('modules.export_data_thread'), 'ExportDataThread', cls._missing),
            ('modules.filter_dialog', 'FilterDialog'): getattr(sys.modules.get('modules.filter_dialog'), 'FilterDialog', cls._missing),
            ('modules.data_grouping', 'DataGrouping'): getattr(sys.modules.get('modules.data_grouping'), 'DataGrouping', cls._missing),
            ('modules.custom_logger', 'CustomLogger'): getattr(sys.modules.get('modules.custom_logger'), 'CustomLogger', cls._missing),
        }

        # Minimal stubs for Qt and dependencies so we can import payload builder.
        qtcore_stub = types.ModuleType('PyQt6.QtCore')
        qtcore_stub.QSize = object
        qtcore_stub.QTemporaryFile = object
        qtcore_stub.Qt = object

        class _FakeQUrl:
            def __init__(self, value=''):
                self._value = str(value or '')

            def isValid(self):
                return '://' in self._value

            def scheme(self):
                return self._value.split('://', 1)[0] if self.isValid() else ''

            def toLocalFile(self):
                if self._value.startswith('file://'):
                    return self._value[len('file://'):]
                return ''

            def __str__(self):
                return self._value

        qtcore_stub.QUrl = _FakeQUrl
        sys.modules['PyQt6.QtCore'] = qtcore_stub

        qtgui_stub = types.ModuleType('PyQt6.QtGui')
        qtgui_stub.QMovie = object

        class _FakeDesktopServices:
            @staticmethod
            def openUrl(_url):
                return True

        qtgui_stub.QDesktopServices = _FakeDesktopServices
        sys.modules['PyQt6.QtGui'] = qtgui_stub

        qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
        for name in [
            'QApplication', 'QDialog', 'QFileDialog', 'QGridLayout', 'QLabel', 'QLineEdit',
            'QMessageBox', 'QProgressBar', 'QPushButton', 'QVBoxLayout',
            'QComboBox', 'QCheckBox', 'QHBoxLayout', 'QWidget', 'QScrollArea',
            'QSizePolicy', 'QToolButton',
        ]:
            setattr(qtwidgets_stub, name, object)
        sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub

        for module_name in ['modules.base64_encoded_files', 'modules.export_data_thread', 'modules.filter_dialog', 'modules.data_grouping', 'modules.custom_logger']:
            if module_name not in sys.modules:
                sys.modules[module_name] = types.ModuleType(module_name)

        sys.modules['modules.export_data_thread'].ExportDataThread = object
        sys.modules['modules.filter_dialog'].FilterDialog = object
        sys.modules['modules.data_grouping'].DataGrouping = object
        sys.modules['modules.custom_logger'].CustomLogger = object
        sys.modules.pop('modules.export_dialog', None)

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop('modules.export_dialog', None)
        for (module_name, attr_name), original_value in cls._saved_module_attrs.items():
            module = sys.modules.get(module_name)
            if module is None:
                continue
            if original_value is cls._missing:
                if hasattr(module, attr_name):
                    delattr(module, attr_name)
            else:
                setattr(module, attr_name, original_value)
        for module_name, original_module in cls._saved_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module

    def test_selected_preset_changes_payload_deterministically(self):
        from modules.export_dialog import build_export_options_payload

        fast_payload = validate_export_options(
            build_export_options_payload(
                selected_preset=EXPORT_PRESET_FAST_DIAGNOSTICS,
                export_type='Line',
                export_target='excel_xlsx',
                sorting_parameter='Date',
                violin_input='8',
                summary_scale_input='0',
                hide_ok_results=False,
            )
        )
        full_payload = validate_export_options(
            build_export_options_payload(
                selected_preset=EXPORT_PRESET_FULL_REPORT,
                export_type='Line',
                export_target='excel_xlsx',
                sorting_parameter='Date',
                violin_input='6',
                summary_scale_input='0',
                hide_ok_results=False,
            )
        )

        self.assertEqual(fast_payload.preset, EXPORT_PRESET_FAST_DIAGNOSTICS)
        self.assertEqual(full_payload.preset, EXPORT_PRESET_FULL_REPORT)
        self.assertFalse(fast_payload.generate_summary_sheet)
        self.assertTrue(full_payload.generate_summary_sheet)


class TestExportDialogPresetApplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_apply_selected_preset_updates_only_preset_owned_controls(self):
        from modules.export_dialog import ExportDialog

        class _FakeCombo:
            def __init__(self, value):
                self._value = value

            def currentText(self):
                return self._value

            def setCurrentText(self, value):
                self._value = value

        class _FakeLineEdit:
            def __init__(self, value=""):
                self._value = value

            def text(self):
                return self._value

            def setText(self, value):
                self._value = value

        class _FakeCheckbox:
            def __init__(self, checked):
                self._checked = checked

            def isChecked(self):
                return self._checked

            def setChecked(self, checked):
                self._checked = checked

        dialog = ExportDialog.__new__(ExportDialog)
        dialog.preset_combobox = _FakeCombo("Extended plots")
        dialog.export_type_combobox = _FakeCombo("Scatter")
        dialog.sort_measurements_combobox = _FakeCombo("Sample #")
        dialog.violin_plot_min_samplesize = _FakeLineEdit("99")
        dialog.summary_plot_scale = _FakeLineEdit("42")
        dialog.hide_ok_results_checkbox = _FakeCheckbox(True)
        dialog.include_google_sheets_checkbox = _FakeCheckbox(False)
        dialog.group_analysis_level_combobox = _FakeCombo("Off")
        dialog.group_analysis_scope_combobox = _FakeCombo("Auto")
        dialog._save_dialog_config = lambda: None

        dialog.apply_selected_preset()

        self.assertEqual(dialog.export_type_combobox.currentText(), "Line")
        self.assertEqual(dialog.sort_measurements_combobox.currentText(), "Date")
        self.assertEqual(dialog.violin_plot_min_samplesize.text(), "6")
        self.assertEqual(dialog.summary_plot_scale.text(), "0")
        self.assertFalse(dialog.hide_ok_results_checkbox.isChecked())
        self.assertEqual(get_export_preset_id_for_label(dialog.preset_combobox.currentText()), EXPORT_PRESET_FULL_REPORT)
        self.assertEqual(dialog._selected_group_analysis_level(), "off")
        self.assertEqual(dialog._selected_group_analysis_scope(), "auto")
        self.assertFalse(dialog.include_google_sheets_checkbox.isChecked())


class TestExportCompletionMessaging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_google_success_uses_standard_success_message(self):
        from modules.export_dialog import build_export_completion_message

        metadata = {
            'converted_url': 'https://docs.google.com/spreadsheets/d/abc/edit',
            'converted_file_id': 'abc',
            'fallback_message': '',
            'conversion_warnings': [],
            'converted_tab_titles': ['MEASUREMENTS'],
        }
        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata=metadata,
        )

        self.assertEqual(level, 'info')
        self.assertEqual(title, 'Export successful')
        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        self.assertEqual(
            message,
            'Data exported successfully!\n'
            '\n'
            f'Export file: {expected_file_uri}',
        )

    def test_google_fallback_promotes_warning_dialog(self):
        from modules.export_dialog import build_export_completion_message

        metadata = {
            'fallback_message': 'Google export failed; using local .xlsx fallback: out.xlsx',
            'conversion_warnings': ['Missing token.json for Google Drive export. Please complete OAuth authorization first.'],
            'converted_url': '',
            'converted_tab_titles': [],
        }
        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata=metadata,
        )

        self.assertEqual(level, 'warning')
        self.assertEqual(title, 'Export completed with Google fallback')
        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        self.assertEqual(
            message,
            'Data exported locally to out.xlsx.\n'
            f'Export file: {expected_file_uri}\n'
            '\n'
            'Google Sheets conversion was not fully completed.\n'
            'Warnings/Errors:\n'
            '- Missing token.json for Google Drive export. Please complete OAuth authorization first.',
        )

    def test_google_fallback_only_shows_conversion_partial_message(self):
        from modules.export_dialog import build_export_completion_message

        metadata = {
            'fallback_message': 'Google export failed; using local .xlsx fallback: out.xlsx',
            'conversion_warnings': [],
            'converted_url': '',
            'converted_tab_titles': [],
        }
        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata=metadata,
        )

        self.assertEqual(level, 'warning')
        self.assertEqual(title, 'Export completed with Google fallback')
        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        self.assertEqual(
            message,
            'Data exported locally to out.xlsx.\n'
            f'Export file: {expected_file_uri}\n'
            '\n'
            'Google Sheets conversion was not fully completed.',
        )

    def test_google_empty_metadata_defaults_to_standard_success_message(self):
        from modules.export_dialog import build_export_completion_message

        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata={},
        )

        self.assertEqual(level, 'info')
        self.assertEqual(title, 'Export successful')
        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        self.assertEqual(
            message,
            'Data exported successfully!\n'
            '\n'
            f'Export file: {expected_file_uri}'
        )


    def test_link_formatting_converts_google_urls_to_anchors(self):
        from modules.export_dialog import format_message_with_clickable_links

        formatted = format_message_with_clickable_links(
            'Google Sheet: https://docs.google.com/spreadsheets/d/abc/edit'
        )

        self.assertIn('<a href="https://docs.google.com/spreadsheets/d/abc/edit">https://docs.google.com/spreadsheets/d/abc/edit</a>', formatted)
        self.assertNotIn('drive.google.com/file/d/abc/view', formatted)

    def test_link_formatting_escapes_html_before_linking(self):
        from modules.export_dialog import format_message_with_clickable_links

        formatted = format_message_with_clickable_links('Result <ok> https://example.com')

        self.assertIn('Result &lt;ok&gt;', formatted)
        self.assertIn('<a href="https://example.com">https://example.com</a>', formatted)

    def test_link_formatting_also_converts_file_urls_to_anchors(self):
        from modules.export_dialog import format_message_with_clickable_links

        formatted = format_message_with_clickable_links('Export file: file:///tmp/out.xlsx')

        self.assertIn('<a href="file:///tmp/out.xlsx">file:///tmp/out.xlsx</a>', formatted)

    def test_build_export_directory_link_line_points_to_file(self):
        from modules.export_dialog import build_export_directory_link_line

        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        self.assertEqual(build_export_directory_link_line('out.xlsx'), f'Export file: {expected_file_uri}')


    def test_build_export_folder_link_line_points_to_parent_directory(self):
        from modules.export_dialog import build_export_folder_link_line

        expected_folder_uri = Path('out.xlsx').resolve().parent.as_uri()
        self.assertEqual(build_export_folder_link_line('out.xlsx'), f'Export folder: {expected_folder_uri}')

    def test_google_fallback_still_includes_google_url_when_available(self):
        from modules.export_dialog import build_export_completion_message

        metadata = {
            'fallback_message': 'Google conversion completed with warnings; local xlsx remains fallback.',
            'conversion_warnings': ['Trendline patch skipped'],
            'converted_url': 'https://docs.google.com/spreadsheets/d/abc/edit',
            'converted_tab_titles': ['MEASUREMENTS'],
        }

        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata=metadata,
        )

        self.assertEqual(level, 'warning')
        self.assertEqual(title, 'Export completed with Google fallback')
        self.assertIn('Google Sheet: https://docs.google.com/spreadsheets/d/abc/edit', message)

    def test_excel_target_message_uses_standard_success_copy_even_with_google_metadata(self):
        from modules.export_dialog import build_export_completion_message

        metadata = {
            'converted_url': 'https://docs.google.com/spreadsheets/d/abc/edit',
            'fallback_message': 'Google export failed; using local .xlsx fallback: out.xlsx',
            'conversion_warnings': ['warning one'],
            'converted_tab_titles': ['MEASUREMENTS'],
        }
        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='excel_xlsx',
            completion_metadata=metadata,
        )

        self.assertEqual(level, 'info')
        self.assertEqual(title, 'Export successful')
        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        self.assertEqual(
            message,
            'Data exported successfully!\n'
            '\n'
            f'Export file: {expected_file_uri}'
        )

    def test_completion_message_ignores_backend_diagnostics_when_present(self):
        from modules.export_dialog import build_export_completion_message

        metadata = {
            'backend_diagnostics_lines': [
                'chart_renderer: status=native_available, available=True, selected=auto, effective=native',
                'cmm_parser: status=native_unavailable_fallback, available=False, selected=auto, effective=python',
            ],
        }
        _level, _title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='excel_xlsx',
            completion_metadata=metadata,
        )

        self.assertEqual(
            message,
            'Data exported successfully!\n'
            '\n'
            f'Export file: {Path("out.xlsx").resolve().as_uri()}'
        )

    def test_completion_message_includes_html_dashboard_link_without_assets(self):
        from modules.export_dialog import build_export_completion_message

        metadata = {
            'html_dashboard_path': 'out_dashboard.html',
            'html_dashboard_assets_path': 'out_dashboard_assets',
        }
        _level, _title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='excel_xlsx',
            completion_metadata=metadata,
        )

        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        expected_dashboard_uri = Path('out_dashboard.html').resolve().as_uri()
        self.assertEqual(
            message,
            'Data exported successfully!\n'
            '\n'
            f'Export file: {expected_file_uri}\n'
            '\n'
            f'HTML dashboard: {expected_dashboard_uri}'
        )


class TestExportTargetSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_selected_export_target_defaults_to_excel(self):
        from modules.export_dialog import ExportDialog

        dialog = ExportDialog.__new__(ExportDialog)

        class _Box:
            def __init__(self, checked):
                self._checked = checked

            def isChecked(self):
                return self._checked

        dialog.include_google_sheets_checkbox = _Box(False)
        self.assertEqual(dialog._selected_export_target(), 'excel_xlsx')

        dialog.include_google_sheets_checkbox = _Box(True)
        self.assertEqual(dialog._selected_export_target(), 'google_sheets_drive_convert')


class TestRevealFileInExplorer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_reveal_file_in_explorer_raises_for_missing_file(self):
        from modules.export_dialog import reveal_file_in_explorer

        with self.assertRaises(FileNotFoundError):
            reveal_file_in_explorer('does-not-exist.xlsx')

    def test_reveal_file_in_explorer_windows_uses_select(self):
        from modules.export_dialog import reveal_file_in_explorer

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / 'out.xlsx'
            file_path.write_text('content', encoding='utf-8')
            with patch('modules.export_dialog.sys.platform', 'win32'), patch('modules.export_dialog.subprocess.run') as run_mock:
                run_mock.return_value.returncode = 1
                reveal_file_in_explorer(file_path)
            run_mock.assert_called_once_with(['explorer', '/select,', str(file_path)], check=False)


class TestShowExportResultMessage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_handle_export_result_link_reveals_file_for_export_link(self):
        from modules.export_dialog import handle_export_result_link

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / 'out.xlsx'
            file_path.write_text('content', encoding='utf-8')

            with patch('modules.export_dialog.reveal_file_in_explorer') as reveal_mock, patch('modules.export_dialog.QDesktopServices.openUrl') as open_url_mock:
                handle_export_result_link(parent=None, url=file_path.resolve().as_uri(), excel_file=str(file_path))

        reveal_mock.assert_called_once_with(str(file_path))
        open_url_mock.assert_not_called()

    def test_handle_export_result_link_opens_non_matching_urls_normally(self):
        from modules.export_dialog import handle_export_result_link

        with patch('modules.export_dialog.QDesktopServices.openUrl') as open_url_mock:
            handle_export_result_link(parent=None, url='https://example.com', excel_file='out.xlsx')

        open_url_mock.assert_called_once()

    def test_open_export_result_link_surfaces_failure_warning(self):
        from modules.export_dialog import _open_export_result_link

        class FakeMessageBox:
            warning_calls = []

            @staticmethod
            def warning(parent, title, text):
                FakeMessageBox.warning_calls.append((parent, title, text))

        with patch('modules.export_dialog.QMessageBox', FakeMessageBox), patch('modules.export_dialog.handle_export_result_link', side_effect=RuntimeError('boom')):
            _open_export_result_link(parent=None, link='file:///tmp/out.xlsx', excel_file='out.xlsx')

        self.assertEqual(len(FakeMessageBox.warning_calls), 1)
        _, warning_title, warning_text = FakeMessageBox.warning_calls[0]
        self.assertEqual(warning_title, 'Unable to open file location')
        self.assertIn('Could not open the export location for out.xlsx.', warning_text)
        self.assertIn('boom', warning_text)

    def test_open_export_result_link_reraises_unexpected_exception_after_logging(self):
        from modules.export_dialog import _open_export_result_link

        with patch('modules.export_dialog._log_exception') as log_exception_mock, \
             patch('modules.export_dialog.handle_export_result_link', side_effect=KeyError('unexpected')):
            with self.assertRaises(KeyError):
                _open_export_result_link(parent=None, link='file:///tmp/out.xlsx', excel_file='out.xlsx')

        log_exception_mock.assert_called_once()


class TestExportDialogCompletionFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_on_export_finished_success_keeps_dialog_open_and_closes_progress(self):
        from modules.export_dialog import ExportDialog

        class _LoadingDialog:
            def __init__(self):
                self.accept_calls = 0

            def accept(self):
                self.accept_calls += 1

        class _Button:
            def __init__(self):
                self.enabled_states = []

            def setEnabled(self, enabled):
                self.enabled_states.append(enabled)

        class _Thread:
            export_target = 'excel_xlsx'
            completion_metadata = {}

        dialog = ExportDialog.__new__(ExportDialog)
        dialog.export_error_message = None
        dialog.excel_file = 'out.xlsx'
        dialog.export_thread = _Thread()
        dialog.loading_dialog = _LoadingDialog()
        dialog.export_button = _Button()
        dialog.accept_called = False
        dialog.accept = lambda: setattr(dialog, 'accept_called', True)

        with patch('modules.export_dialog.build_export_completion_message', return_value=('info', 'Export successful', 'ok')) as build_mock, \
             patch('modules.export_dialog.show_export_result_message') as show_mock:
            dialog.on_export_finished()

        build_mock.assert_called_once()
        show_mock.assert_called_once_with(dialog, 'info', 'Export successful', 'ok', excel_file='out.xlsx')
        self.assertEqual(dialog.loading_dialog.accept_calls, 1)
        self.assertFalse(dialog.accept_called)
        self.assertEqual(dialog.export_button.enabled_states, [True])
        self.assertIsNone(dialog.export_error_message)

    def test_on_export_finished_falls_back_to_plain_message_when_rich_message_fails(self):
        from modules.export_dialog import ExportDialog

        class _LoadingDialog:
            def __init__(self):
                self.accept_calls = 0

            def accept(self):
                self.accept_calls += 1

        class _Button:
            def __init__(self):
                self.enabled_states = []

            def setEnabled(self, enabled):
                self.enabled_states.append(enabled)

        class _Thread:
            export_target = 'excel_xlsx'
            completion_metadata = {}

        dialog = ExportDialog.__new__(ExportDialog)
        dialog.export_error_message = None
        dialog.excel_file = 'out.xlsx'
        dialog.export_thread = _Thread()
        dialog.loading_dialog = _LoadingDialog()
        dialog.export_button = _Button()
        dialog.accept_called = False
        dialog.accept = lambda: setattr(dialog, 'accept_called', True)

        class _InfoMessageBox:
            information_calls = []

            @staticmethod
            def information(parent, title, text):
                _InfoMessageBox.information_calls.append((parent, title, text))

        with patch('modules.export_dialog.build_export_completion_message', return_value=('info', 'Export successful', 'ok')) as build_mock, \
             patch('modules.export_dialog.show_export_result_message', side_effect=RuntimeError('boom')) as show_mock, \
             patch('modules.export_dialog.QMessageBox', _InfoMessageBox):
            dialog.on_export_finished()

        build_mock.assert_called_once()
        show_mock.assert_called_once()
        self.assertEqual(_InfoMessageBox.information_calls, [(dialog, 'Export successful', 'ok')])
        self.assertEqual(dialog.loading_dialog.accept_calls, 1)
        self.assertFalse(dialog.accept_called)
        self.assertEqual(dialog.export_button.enabled_states, [True])
        self.assertIsNone(dialog.export_error_message)


class TestExportDialogServiceRequestAssembly(unittest.TestCase):
    def test_build_validated_export_request_matches_existing_coercion_contract(self):
        from modules.export_dialog_service import build_export_options_payload, build_validated_export_request

        request = build_validated_export_request(
            db_file='input.db',
            excel_file=Path('out.xlsx'),
            selected_preset=EXPORT_PRESET_FAST_DIAGNOSTICS,
            export_type='Line',
            export_target='excel_xlsx',
            sorting_parameter='Sample #',
            violin_input='1',
            summary_scale_input='-4',
            hide_ok_results=True,
            generate_html_dashboard=True,
            filter_query='SELECT * FROM T',
            grouping_df=None,
            group_analysis_level='Standard',
            group_analysis_scope='Multi-reference',
        )

        expected_options = validate_export_options(
            build_export_options_payload(
                selected_preset=EXPORT_PRESET_FAST_DIAGNOSTICS,
                export_type='Line',
                export_target='excel_xlsx',
                sorting_parameter='Sample #',
                violin_input='1',
                summary_scale_input='-4',
                hide_ok_results=True,
                generate_html_dashboard=True,
                group_analysis_level='Standard',
                group_analysis_scope='Multi-reference',
            )
        )

        self.assertEqual(request.paths.db_file, 'input.db')
        self.assertEqual(request.paths.excel_file, 'out.xlsx')
        self.assertEqual(request.options, expected_options)
        self.assertEqual(request.options.violin_plot_min_samplesize, 2)
        self.assertEqual(request.options.summary_plot_scale, 0)
        self.assertEqual(request.filter_query, 'SELECT * FROM T')
        self.assertIsNone(request.grouping_df)
        self.assertTrue(request.options.generate_html_dashboard)
        self.assertEqual(request.options.group_analysis_level, 'standard')
        self.assertEqual(request.options.group_analysis_scope, 'multi_reference')


class TestExportDialogThreadStartupContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_show_loading_screen_starts_thread_with_validated_export_request_keyword(self):
        from modules.export_dialog import ExportDialog

        class _Signal:
            def __init__(self):
                self.connected = []

            def connect(self, slot):
                self.connected.append(slot)

        class _FakeThread:
            init_kwargs = None

            def __init__(self, *args, **kwargs):
                _FakeThread.init_kwargs = kwargs
                self.update_label = _Signal()
                self.update_progress = _Signal()
                self.error_occurred = _Signal()
                self.finished = _Signal()
                self.canceled = _Signal()
                self.started = False

            def start(self):
                self.started = True

        class _FakeButton:
            def __init__(self):
                self.disabled_states = []

            def setDisabled(self, value):
                self.disabled_states.append(value)

        class _FakeDialog:
            def __init__(self):
                self.show_calls = 0

            def show(self):
                self.show_calls += 1

        class _FakeLabel:
            def setText(self, _text):
                return None

        class _FakeBar:
            def setValue(self, _value):
                return None

        class _FakeLineEdit:
            def __init__(self, value):
                self._value = value

            def text(self):
                return self._value

            def setText(self, value):
                self._value = value

        class _FakeCombo:
            def __init__(self, value):
                self._value = value

            def currentText(self):
                return self._value

        class _FakeCheckbox:
            def __init__(self, checked):
                self._checked = checked

            def isChecked(self):
                return self._checked

        dialog = ExportDialog.__new__(ExportDialog)
        dialog.export_button = _FakeButton()
        dialog.violin_plot_min_samplesize = _FakeLineEdit('1')
        dialog.summary_plot_scale = _FakeLineEdit('-5')
        dialog.preset_combobox = _FakeCombo('Main plots')
        dialog.export_type_combobox = _FakeCombo('Line')
        dialog.sort_measurements_combobox = _FakeCombo('Sample #')
        dialog.include_google_sheets_checkbox = _FakeCheckbox(False)
        dialog.generate_html_dashboard_checkbox = _FakeCheckbox(True)
        dialog.hide_ok_results_checkbox = _FakeCheckbox(False)
        dialog.filter_query = 'SELECT 1'
        dialog.df_for_grouping = None
        dialog.db_file = 'input.db'
        dialog.excel_file = Path('out.xlsx')
        dialog.config = {}
        dialog.config_path = Path('/tmp/nonexistent-export-config.json')
        dialog.stop_exporting = lambda: None
        dialog.on_export_error = lambda *_: None
        dialog.on_export_finished = lambda: None
        dialog.on_export_canceled = lambda: None

        with patch('modules.export_dialog.create_worker_progress_dialog', return_value=(_FakeDialog(), _FakeLabel(), _FakeBar(), object())), \
             patch('modules.export_dialog.save_export_dialog_config'), \
             patch('modules.export_dialog.ExportDataThread', _FakeThread):
            dialog.show_loading_screen()

        self.assertIsNotNone(_FakeThread.init_kwargs)
        self.assertEqual(set(_FakeThread.init_kwargs.keys()), {'export_request'})
        request = _FakeThread.init_kwargs['export_request']
        self.assertEqual(request.paths.db_file, 'input.db')
        self.assertEqual(request.paths.excel_file, 'out.xlsx')
        self.assertEqual(request.options.export_target, 'excel_xlsx')
        self.assertEqual(request.options.violin_plot_min_samplesize, 2)
        self.assertEqual(request.options.summary_plot_scale, 0)
        self.assertTrue(request.options.generate_html_dashboard)


class TestExportDialogDatabaseSwitchContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_select_db_file_resets_filter_and_grouping_context(self):
        from modules.export_dialog import DEFAULT_FILTER_QUERY, ExportDialog

        class _FakeButton:
            def __init__(self):
                self.enabled = []

            def setEnabled(self, value):
                self.enabled.append(bool(value))

        class _FakeLabel:
            def __init__(self):
                self.value = None

            def setText(self, value):
                self.value = value

        class _FakeParent:
            def __init__(self):
                self.db_file = None

            def set_db_file(self, filename):
                self.db_file = filename

        class _FakeChildDialog:
            def __init__(self):
                self.closed = False
                self.deleted = False

            def close(self):
                self.closed = True

            def deleteLater(self):
                self.deleted = True

        dialog = ExportDialog.__new__(ExportDialog)
        parent = _FakeParent()
        dialog.parent = lambda: parent
        dialog.select_excel_button = _FakeButton()
        dialog.filter_button = _FakeButton()
        dialog.group_button = _FakeButton()
        dialog.database_text_label = _FakeLabel()
        dialog.select_filter_label = _FakeLabel()
        dialog.filter_query = "SELECT * FROM REPORTS WHERE REFERENCE='stale'"
        dialog.df_for_grouping = object()
        dialog.filter_window = _FakeChildDialog()
        dialog.grouping_window = _FakeChildDialog()
        dialog.set_grouping_applied = lambda applied: setattr(dialog, '_grouping_applied', applied)

        fake_file_dialog = type('FakeFileDialog', (), {'getOpenFileName': staticmethod(lambda *_args, **_kwargs: ('/tmp/next.db', 'SQLite database (*.db)'))})
        with patch('modules.export_dialog.QFileDialog', fake_file_dialog):
            dialog.select_db_file()

        self.assertEqual(dialog.db_file, '/tmp/next.db')
        self.assertEqual(parent.db_file, '/tmp/next.db')
        self.assertEqual(dialog.database_text_label.value, '/tmp/next.db')
        self.assertEqual(dialog.filter_query, DEFAULT_FILTER_QUERY)
        self.assertIsNone(dialog.df_for_grouping)
        self.assertEqual(dialog.select_filter_label.value, 'Not applied')
        self.assertFalse(dialog._grouping_applied)
        self.assertIsNone(dialog.filter_window)
        self.assertIsNone(dialog.grouping_window)


class TestExportDialogGroupingAnalysisDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_grouping_applied_promotes_off_level_to_standard(self):
        from modules.export_dialog import ExportDialog

        class _FakeLabel:
            def __init__(self):
                self.value = None

            def setText(self, value):
                self.value = value

        class _FakeCombo:
            def __init__(self, value):
                self._value = value

            def currentText(self):
                return self._value

            def setCurrentText(self, value):
                self._value = value

        dialog = ExportDialog.__new__(ExportDialog)
        dialog.select_group_label = _FakeLabel()
        dialog.group_analysis_level_combobox = _FakeCombo('Off')

        dialog.set_grouping_applied(True)

        self.assertEqual(dialog.select_group_label.value, 'Applied')
        self.assertEqual(dialog.group_analysis_level_combobox.currentText(), 'Standard')

    def test_grouping_applied_keeps_non_off_level(self):
        from modules.export_dialog import ExportDialog

        class _FakeLabel:
            def __init__(self):
                self.value = None

            def setText(self, value):
                self.value = value

        class _FakeCombo:
            def __init__(self, value):
                self._value = value

            def currentText(self):
                return self._value

            def setCurrentText(self, value):
                self._value = value

        dialog = ExportDialog.__new__(ExportDialog)
        dialog.select_group_label = _FakeLabel()
        dialog.group_analysis_level_combobox = _FakeCombo('Light')

        dialog.set_grouping_applied(True)

        self.assertEqual(dialog.group_analysis_level_combobox.currentText(), 'Light')

    def test_grouping_disabled_sets_level_off(self):
        from modules.export_dialog import ExportDialog

        class _FakeLabel:
            def __init__(self):
                self.value = None

            def setText(self, value):
                self.value = value

        class _FakeCombo:
            def __init__(self, value):
                self._value = value

            def currentText(self):
                return self._value

            def setCurrentText(self, value):
                self._value = value

        dialog = ExportDialog.__new__(ExportDialog)
        dialog.select_group_label = _FakeLabel()
        dialog.group_analysis_level_combobox = _FakeCombo('Standard')

        dialog.set_grouping_applied(False)

        self.assertEqual(dialog.select_group_label.value, 'Not applied')
        self.assertEqual(dialog.group_analysis_level_combobox.currentText(), 'Off')



if __name__ == '__main__':
    unittest.main()
