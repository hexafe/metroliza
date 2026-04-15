import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class TestExportDialogLayout(unittest.TestCase):
    def _run_probe(self, script):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_STYLE_OVERRIDE"] = "Fusion"

        try:
            result = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(script)],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            headless_runtime_markers = (
                "libGL.so.1",
                "libEGL.so.1",
                "Could not load the Qt platform plugin",
                "no Qt platform plugin could be initialized",
                "qt.qpa.plugin",
            )
            if any(marker in stderr for marker in headless_runtime_markers):
                self.skipTest(f"PyQt runtime dependency missing in test environment: {stderr}")
            self.fail(
                "ExportDialog probe subprocess failed unexpectedly.\n"
                f"Return code: {exc.returncode}\n"
                f"STDOUT:\n{(exc.stdout or '').strip()}\n"
                f"STDERR:\n{stderr}"
            )

        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_default_layout_fits_screen_and_starts_compact(self):
        payload = self._run_probe(
            """
            import json
            from PyQt6.QtWidgets import QApplication
            from modules.export_dialog import ExportDialog

            ExportDialog._load_dialog_config = lambda self: {'selected_preset': 'fast_diagnostics'}

            app = QApplication.instance() or QApplication([])
            dialog = ExportDialog(parent=None, db_file="")
            dialog.show()
            app.processEvents()

            available = app.primaryScreen().availableGeometry()
            print(json.dumps({
                "dialog_size": [dialog.width(), dialog.height()],
                "available": [available.width(), available.height()],
                "advanced_visible": dialog.advanced_options_container.isVisible(),
                "scope_visible": dialog.group_analysis_scope_combobox.isVisible(),
                "scope_enabled": dialog.group_analysis_scope_combobox.isEnabled(),
                "toggle_text": dialog.advanced_toggle_button.text(),
                "google_label": dialog.include_google_sheets_checkbox.text(),
                "html_label": dialog.generate_html_dashboard_checkbox.text(),
                "close_label": dialog.close_button.text(),
                "db_text": dialog.database_text_label.text(),
                "excel_text": dialog.excel_file_text_label.text(),
            }, sort_keys=True))
            dialog.close()
            app.processEvents()
            """
        )

        self.assertLessEqual(payload["dialog_size"][0], payload["available"][0])
        self.assertLessEqual(payload["dialog_size"][1], payload["available"][1])
        self.assertFalse(payload["advanced_visible"])
        self.assertFalse(payload["scope_visible"])
        self.assertFalse(payload["scope_enabled"])
        self.assertEqual(payload["toggle_text"], "Show advanced options")
        self.assertEqual(payload["google_label"], "Google Sheets version")
        self.assertEqual(payload["html_label"], "HTML dashboard")
        self.assertEqual(payload["close_label"], "Close")
        self.assertEqual(payload["db_text"], "None selected")
        self.assertEqual(payload["excel_text"], "None selected")

    def test_long_paths_do_not_expand_dialog_width(self):
        payload = self._run_probe(
            """
            import json
            from PyQt6.QtWidgets import QApplication
            from modules.export_dialog import ExportDialog

            ExportDialog._load_dialog_config = lambda self: {'selected_preset': 'fast_diagnostics'}

            app = QApplication.instance() or QApplication([])
            long_db = '/home/hexaf/Projects/metroliza/very/' + '/'.join(['deeply_nested_directory_name'] * 6) + '/measurement_database_name_with_really_long_identifier.db'
            long_xlsx = long_db.replace('.db', '.xlsx')

            dialog = ExportDialog(parent=None, db_file=long_db)
            dialog.excel_file = long_xlsx
            dialog._set_path_field_value(dialog.excel_file_text_label, long_xlsx)
            dialog._update_export_button_enabled_state()
            dialog.show()
            app.processEvents()

            available = app.primaryScreen().availableGeometry()
            print(json.dumps({
                "dialog_size": [dialog.width(), dialog.height()],
                "available": [available.width(), available.height()],
                "db_size_hint_width": dialog.database_text_label.sizeHint().width(),
                "excel_size_hint_width": dialog.excel_file_text_label.sizeHint().width(),
                "db_tooltip": dialog.database_text_label.toolTip(),
                "excel_tooltip": dialog.excel_file_text_label.toolTip(),
                "export_enabled": dialog.export_button.isEnabled(),
            }, sort_keys=True))
            dialog.close()
            app.processEvents()
            """
        )

        self.assertLessEqual(payload["dialog_size"][0], payload["available"][0])
        self.assertLessEqual(payload["dialog_size"][1], payload["available"][1])
        self.assertLess(payload["db_size_hint_width"], 200)
        self.assertLess(payload["excel_size_hint_width"], 200)
        self.assertIn("measurement_database_name_with_really_long_identifier.db", payload["db_tooltip"])
        self.assertIn("measurement_database_name_with_really_long_identifier.xlsx", payload["excel_tooltip"])
        self.assertTrue(payload["export_enabled"])


if __name__ == "__main__":
    unittest.main()
