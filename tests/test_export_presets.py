import sys
import tempfile
import types
import unittest
from pathlib import Path

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
        sys.modules['PyQt6.QtCore'] = qtcore_stub

        qtgui_stub = types.ModuleType('PyQt6.QtGui')
        qtgui_stub.QMovie = object
        sys.modules['PyQt6.QtGui'] = qtgui_stub

        qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
        for name in [
            'QDialog', 'QFileDialog', 'QGridLayout', 'QLabel', 'QLineEdit',
            'QMessageBox', 'QProgressBar', 'QPushButton', 'QVBoxLayout',
            'QComboBox', 'QCheckBox',
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
            )
        )

        self.assertEqual(fast_payload.preset, EXPORT_PRESET_FAST_DIAGNOSTICS)
        self.assertEqual(full_payload.preset, EXPORT_PRESET_FULL_REPORT)
        self.assertFalse(fast_payload.generate_summary_sheet)
        self.assertTrue(full_payload.generate_summary_sheet)


class TestExportCompletionMessaging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestExportPresetFlowIntegration.setUpClass()

    def test_google_success_includes_converted_link(self):
        from modules.ExportDialog import build_export_completion_message

        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata={'converted_url': 'https://docs.google.com/spreadsheets/d/abc/edit'},
        )

        self.assertEqual(level, 'info')
        self.assertEqual(title, 'Export successful')
        self.assertIn('Google Sheet:', message)

    def test_google_fallback_promotes_warning_dialog(self):
        from modules.ExportDialog import build_export_completion_message

        level, title, message = build_export_completion_message(
            excel_file='out.xlsx',
            export_target='google_sheets_drive_convert',
            completion_metadata={
                'fallback_message': 'Google export failed; using local .xlsx fallback: out.xlsx',
                'conversion_warnings': ['Missing token.json for Google Drive export. Please complete OAuth authorization first.'],
            },
        )

        self.assertEqual(level, 'warning')
        self.assertEqual(title, 'Export completed with Google fallback')
        self.assertIn('Google Sheets conversion was not fully completed.', message)
        self.assertIn('Missing token.json', message)


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


if __name__ == '__main__':
    unittest.main()
