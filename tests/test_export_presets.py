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


class TestExportPresetOptionMapping(unittest.TestCase):
    def test_preset_option_baselines(self):
        fast = build_export_options_for_preset(EXPORT_PRESET_FAST_DIAGNOSTICS)
        full = build_export_options_for_preset(EXPORT_PRESET_FULL_REPORT)

        self.assertFalse(fast['generate_summary_sheet'])
        self.assertTrue(full['generate_summary_sheet'])
        self.assertGreaterEqual(fast['violin_plot_min_samplesize'], full['violin_plot_min_samplesize'])

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
            'QDialog', 'QFileDialog', 'QGridLayout', 'QLabel', 'QLineEdit',
            'QMessageBox', 'QProgressBar', 'QPushButton', 'QVBoxLayout',
            'QComboBox', 'QCheckBox', 'QHBoxLayout', 'QWidget',
        ]:
            setattr(qtwidgets_stub, name, object)
        sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub

        for module_name in ['modules.Base64EncodedFiles', 'modules.ExportDataThread', 'modules.FilterDialog', 'modules.DataGrouping', 'modules.CustomLogger']:
            if module_name not in sys.modules:
                sys.modules[module_name] = types.ModuleType(module_name)

        sys.modules['modules.ExportDataThread'].ExportDataThread = object
        sys.modules['modules.FilterDialog'].FilterDialog = object
        sys.modules['modules.DataGrouping'].DataGrouping = object
        sys.modules['modules.CustomLogger'].CustomLogger = object

    def test_selected_preset_changes_payload_deterministically(self):
        from modules.ExportDialog import build_export_options_payload

        fast_payload = validate_export_options(
            build_export_options_payload(
                selected_preset=EXPORT_PRESET_FAST_DIAGNOSTICS,
                export_type='Line',
                export_target='excel_xlsx',
                sorting_parameter='Date',
                violin_input='8',
                summary_scale_input='0',
                hide_ok_results=False,
                generate_summary_sheet=False,
                generate_summary_sheet_overridden=False,
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
                generate_summary_sheet=True,
                generate_summary_sheet_overridden=False,
            )
        )

        self.assertEqual(fast_payload.preset, EXPORT_PRESET_FAST_DIAGNOSTICS)
        self.assertEqual(full_payload.preset, EXPORT_PRESET_FULL_REPORT)
        self.assertFalse(fast_payload.generate_summary_sheet)
        self.assertTrue(full_payload.generate_summary_sheet)

    def test_override_state_is_explicit(self):
        from modules.ExportDialog import is_generate_summary_sheet_overridden

        self.assertFalse(is_generate_summary_sheet_overridden(EXPORT_PRESET_FAST_DIAGNOSTICS, False))
        self.assertTrue(is_generate_summary_sheet_overridden(EXPORT_PRESET_FAST_DIAGNOSTICS, True))
        self.assertFalse(is_generate_summary_sheet_overridden(EXPORT_PRESET_FULL_REPORT, True))
        self.assertTrue(is_generate_summary_sheet_overridden(EXPORT_PRESET_FULL_REPORT, False))


    def test_effective_summary_sheet_state_helper(self):
        from modules.ExportDialog import is_summary_sheet_effectively_enabled

        self.assertFalse(is_summary_sheet_effectively_enabled(
            EXPORT_PRESET_FAST_DIAGNOSTICS,
            generate_summary_sheet=True,
            generate_summary_sheet_overridden=False,
        ))
        self.assertTrue(is_summary_sheet_effectively_enabled(
            EXPORT_PRESET_FAST_DIAGNOSTICS,
            generate_summary_sheet=True,
            generate_summary_sheet_overridden=True,
        ))
        self.assertTrue(is_summary_sheet_effectively_enabled(
            EXPORT_PRESET_FULL_REPORT,
            generate_summary_sheet=False,
            generate_summary_sheet_overridden=False,
        ))
        self.assertFalse(is_summary_sheet_effectively_enabled(
            EXPORT_PRESET_FULL_REPORT,
            generate_summary_sheet=False,
            generate_summary_sheet_overridden=True,
        ))

    def test_payload_uses_advanced_override_only_when_explicitly_changed(self):
        from modules.ExportDialog import build_export_options_payload

        no_override = validate_export_options(
            build_export_options_payload(
                selected_preset=EXPORT_PRESET_FAST_DIAGNOSTICS,
                export_type='Line',
                export_target='excel_xlsx',
                sorting_parameter='Date',
                violin_input='8',
                summary_scale_input='0',
                hide_ok_results=False,
                generate_summary_sheet=True,
                generate_summary_sheet_overridden=False,
            )
        )
        explicit_override = validate_export_options(
            build_export_options_payload(
                selected_preset=EXPORT_PRESET_FAST_DIAGNOSTICS,
                export_type='Line',
                export_target='excel_xlsx',
                sorting_parameter='Date',
                violin_input='8',
                summary_scale_input='0',
                hide_ok_results=False,
                generate_summary_sheet=True,
                generate_summary_sheet_overridden=True,
            )
        )

        self.assertFalse(no_override.generate_summary_sheet)
        self.assertTrue(explicit_override.generate_summary_sheet)


class TestExportCompletionMessaging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_google_success_includes_converted_link(self):
        from modules.ExportDialog import build_export_completion_message

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
            'Data exported successfully to out.xlsx.\n'
            f'Export file: {expected_file_uri}\n'
            '\n'
            'Google Sheet: https://docs.google.com/spreadsheets/d/abc/edit',
        )

    def test_google_fallback_promotes_warning_dialog(self):
        from modules.ExportDialog import build_export_completion_message

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
        from modules.ExportDialog import build_export_completion_message

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
        from modules.ExportDialog import build_export_completion_message

        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata={},
        )

        self.assertEqual(level, 'info')
        self.assertEqual(title, 'Export successful')
        self.assertEqual(message, 'Data exported successfully to out.xlsx!')


    def test_link_formatting_converts_google_urls_to_anchors(self):
        from modules.ExportDialog import format_message_with_clickable_links

        formatted = format_message_with_clickable_links(
            'Google Sheet: https://docs.google.com/spreadsheets/d/abc/edit'
        )

        self.assertIn('<a href="https://docs.google.com/spreadsheets/d/abc/edit">https://docs.google.com/spreadsheets/d/abc/edit</a>', formatted)
        self.assertNotIn('drive.google.com/file/d/abc/view', formatted)

    def test_link_formatting_escapes_html_before_linking(self):
        from modules.ExportDialog import format_message_with_clickable_links

        formatted = format_message_with_clickable_links('Result <ok> https://example.com')

        self.assertIn('Result &lt;ok&gt;', formatted)
        self.assertIn('<a href="https://example.com">https://example.com</a>', formatted)

    def test_link_formatting_also_converts_file_urls_to_anchors(self):
        from modules.ExportDialog import format_message_with_clickable_links

        formatted = format_message_with_clickable_links('Export file: file:///tmp/out.xlsx')

        self.assertIn('<a href="file:///tmp/out.xlsx">file:///tmp/out.xlsx</a>', formatted)

    def test_build_export_directory_link_line_points_to_file(self):
        from modules.ExportDialog import build_export_directory_link_line

        expected_file_uri = Path('out.xlsx').resolve().as_uri()
        self.assertEqual(build_export_directory_link_line('out.xlsx'), f'Export file: {expected_file_uri}')

    def test_excel_target_message_is_unchanged_even_with_google_metadata(self):
        from modules.ExportDialog import build_export_completion_message

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
        self.assertEqual(message, 'Data exported successfully to out.xlsx!')


class TestExportTargetSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_selected_export_target_defaults_to_excel(self):
        from modules.ExportDialog import ExportDialog

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
        from modules.ExportDialog import reveal_file_in_explorer

        with self.assertRaises(FileNotFoundError):
            reveal_file_in_explorer('does-not-exist.xlsx')

    def test_reveal_file_in_explorer_windows_uses_select(self):
        from modules.ExportDialog import reveal_file_in_explorer

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / 'out.xlsx'
            file_path.write_text('content', encoding='utf-8')
            with patch('modules.ExportDialog.sys.platform', 'win32'), patch('modules.ExportDialog.subprocess.run') as run_mock:
                run_mock.return_value.returncode = 1
                reveal_file_in_explorer(file_path)
            run_mock.assert_called_once_with(['explorer', '/select,', str(file_path)], check=False)


class TestShowExportResultMessage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_handle_export_result_link_reveals_file_for_export_link(self):
        from modules.ExportDialog import handle_export_result_link

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / 'out.xlsx'
            file_path.write_text('content', encoding='utf-8')

            with patch('modules.ExportDialog.reveal_file_in_explorer') as reveal_mock, patch('modules.ExportDialog.QDesktopServices.openUrl') as open_url_mock:
                handle_export_result_link(parent=None, url=file_path.resolve().as_uri(), excel_file=str(file_path))

        reveal_mock.assert_called_once_with(str(file_path))
        open_url_mock.assert_not_called()

    def test_handle_export_result_link_opens_non_matching_urls_normally(self):
        from modules.ExportDialog import handle_export_result_link

        with patch('modules.ExportDialog.QDesktopServices.openUrl') as open_url_mock:
            handle_export_result_link(parent=None, url='https://example.com', excel_file='out.xlsx')

        open_url_mock.assert_called_once()

    def test_open_export_result_link_surfaces_failure_warning(self):
        from modules.ExportDialog import _open_export_result_link

        class FakeMessageBox:
            warning_calls = []

            @staticmethod
            def warning(parent, title, text):
                FakeMessageBox.warning_calls.append((parent, title, text))

        with patch('modules.ExportDialog.QMessageBox', FakeMessageBox), patch('modules.ExportDialog.handle_export_result_link', side_effect=RuntimeError('boom')):
            _open_export_result_link(parent=None, link='file:///tmp/out.xlsx', excel_file='out.xlsx')

        self.assertEqual(len(FakeMessageBox.warning_calls), 1)
        _, warning_title, warning_text = FakeMessageBox.warning_calls[0]
        self.assertEqual(warning_title, 'Unable to open file location')
        self.assertIn('Could not open the export location for out.xlsx.', warning_text)
        self.assertIn('boom', warning_text)


if __name__ == '__main__':
    unittest.main()
