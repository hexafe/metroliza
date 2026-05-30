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
            import modules.export_dialog as export_dialog_module
            from modules.export_dialog import ExportDialog

            ExportDialog._load_dialog_config = lambda self: {'selected_preset': 'fast_diagnostics'}
            ExportDialog._save_dialog_config = lambda self: None
            export_dialog_module.load_dashboard_visual_settings = lambda: {"preset": "auto"}

            app = QApplication.instance() or QApplication([])
            dialog = ExportDialog(parent=None, db_file="")
            dialog.violin_plot_min_samplesize.setText("1")
            dialog.summary_plot_scale.setText("-5")
            pre_finished_values = [
                dialog.violin_plot_min_samplesize.text(),
                dialog.summary_plot_scale.text(),
            ]
            dialog.violin_plot_min_samplesize.editingFinished.emit()
            dialog.summary_plot_scale.editingFinished.emit()
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
                "dashboard_visuals_text": dialog.dashboard_visuals_button.text(),
                "dashboard_visuals_visible": dialog.dashboard_visuals_button.isVisible(),
                "dashboard_visuals_enabled": dialog.dashboard_visuals_button.isEnabled(),
                "dashboard_visuals_summary": dialog.dashboard_visuals_summary_label.text(),
                "dashboard_visuals_tooltip": dialog.dashboard_visuals_button.toolTip(),
                "has_html_only_checkbox": hasattr(dialog, "html_dashboard_only_checkbox"),
                "preset_labels": [
                    dialog.preset_combobox.itemText(index)
                    for index in range(dialog.preset_combobox.count())
                ],
                "close_label": dialog.close_button.text(),
                "db_text": dialog.database_text_label.text(),
                "excel_text": dialog.excel_file_text_label.text(),
                "pre_finished_values": pre_finished_values,
                "post_finished_values": [
                    dialog.violin_plot_min_samplesize.text(),
                    dialog.summary_plot_scale.text(),
                ],
                "hide_ok_tooltip": dialog.hide_ok_results_checkbox.toolTip(),
                "info_button_size": [
                    dialog.google_sheets_info_button.width(),
                    dialog.google_sheets_info_button.height(),
                ],
                "export_accessible_name": dialog.export_button.accessibleName(),
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
        self.assertEqual(payload["google_label"], "Google Sheets")
        self.assertEqual(payload["html_label"], "HTML dashboard")
        self.assertEqual(payload["dashboard_visuals_text"], "Change...")
        self.assertFalse(payload["dashboard_visuals_visible"])
        self.assertFalse(payload["dashboard_visuals_enabled"])
        self.assertEqual(payload["dashboard_visuals_summary"], "Metroliza default")
        self.assertIn("Enable HTML dashboard output", payload["dashboard_visuals_tooltip"])
        self.assertFalse(payload["has_html_only_checkbox"])
        self.assertIn("HTML dashboard only", payload["preset_labels"])
        self.assertEqual(payload["close_label"], "Close")
        self.assertEqual(payload["db_text"], "None selected")
        self.assertEqual(payload["excel_text"], "None selected")
        self.assertEqual(payload["pre_finished_values"], ["1", "-5"])
        self.assertEqual(payload["post_finished_values"], ["2", "0"])
        self.assertIn("OK results are hidden", payload["hide_ok_tooltip"])
        self.assertGreaterEqual(payload["info_button_size"][0], 24)
        self.assertGreaterEqual(payload["info_button_size"][1], 24)
        self.assertEqual(payload["export_accessible_name"], "Start export")

    def test_long_paths_do_not_expand_dialog_width(self):
        payload = self._run_probe(
            """
            import json
            from PyQt6.QtWidgets import QApplication
            import modules.export_dialog as export_dialog_module
            from modules.export_dialog import ExportDialog

            ExportDialog._load_dialog_config = lambda self: {'selected_preset': 'fast_diagnostics'}
            ExportDialog._save_dialog_config = lambda self: None
            export_dialog_module.load_dashboard_visual_settings = lambda: {"preset": "auto"}

            app = QApplication.instance() or QApplication([])
            long_db = '/synthetic/metroliza/very/' + '/'.join(['deeply_nested_directory_name'] * 6) + '/measurement_database_name_with_really_long_identifier.db'
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

    def test_html_dashboard_only_preset_owns_dashboard_output_mode(self):
        payload = self._run_probe(
            """
            import json
            from PyQt6.QtWidgets import QApplication
            import modules.export_dialog as export_dialog_module
            from modules.export_dialog import ExportDialog

            ExportDialog._load_dialog_config = lambda self: {'selected_preset': 'html_dashboard_only'}
            ExportDialog._save_dialog_config = lambda self: None
            export_dialog_module.load_dashboard_visual_settings = lambda: {"preset": "auto"}

            app = QApplication.instance() or QApplication([])
            dialog = ExportDialog(parent=None, db_file='/tmp/source.db')
            dialog.excel_file = '/tmp/source.xlsx'
            dialog._sync_html_dashboard_only_state()
            dialog.show()
            app.processEvents()

            print(json.dumps({
                "selected_preset": dialog.preset_combobox.currentText(),
                "output_label": dialog.select_excel_label.text(),
                "output_path": str(dialog.excel_file),
                "html_checked": dialog.generate_html_dashboard_checkbox.isChecked(),
                "html_enabled": dialog.generate_html_dashboard_checkbox.isEnabled(),
                "dashboard_visuals_visible": dialog.dashboard_visuals_button.isVisible(),
                "dashboard_visuals_enabled": dialog.dashboard_visuals_button.isEnabled(),
                "dashboard_visuals_tooltip": dialog.dashboard_visuals_button.toolTip(),
                "google_checked": dialog.include_google_sheets_checkbox.isChecked(),
                "google_enabled": dialog.include_google_sheets_checkbox.isEnabled(),
                "export_target": dialog._selected_export_target(),
            }, sort_keys=True))
            dialog.close()
            app.processEvents()
            """
        )

        self.assertEqual(payload["selected_preset"], "HTML dashboard only")
        self.assertEqual(payload["output_label"], "Dashboard file:")
        self.assertTrue(payload["output_path"].endswith("_dashboard.html"))
        self.assertTrue(payload["html_checked"])
        self.assertFalse(payload["html_enabled"])
        self.assertTrue(payload["dashboard_visuals_visible"])
        self.assertTrue(payload["dashboard_visuals_enabled"])
        self.assertIn("Adjust HTML dashboard", payload["dashboard_visuals_tooltip"])
        self.assertFalse(payload["google_checked"])
        self.assertFalse(payload["google_enabled"])
        self.assertEqual(payload["export_target"], "html_dashboard")

    def test_dashboard_visuals_button_launches_dialog_after_html_dashboard_is_checked(self):
        payload = self._run_probe(
            """
            import json
            import sys
            import types
            from PyQt6.QtWidgets import QApplication, QDialog
            import modules.export_dialog as export_dialog_module
            from modules.export_dialog import ExportDialog

            ExportDialog._load_dialog_config = lambda self: {'selected_preset': 'fast_diagnostics'}
            ExportDialog._save_dialog_config = lambda self: None
            export_dialog_module.load_dashboard_visual_settings = lambda: {"preset": "auto"}

            calls = {}

            class FakeDashboardVisualOptionsDialog:
                def __init__(self, parent=None, *, settings=None, preview_group_names=None):
                    calls["parent_is_dialog"] = isinstance(parent, ExportDialog)
                    calls["settings"] = settings
                    calls["preview_group_names"] = preview_group_names

                def exec(self):
                    calls["exec_called"] = True
                    return QDialog.DialogCode.Accepted

                def visual_settings(self):
                    return {"preset": "distinct"}

            fake_module = types.SimpleNamespace(
                DashboardVisualOptionsDialog=FakeDashboardVisualOptionsDialog
            )
            sys.modules["modules.dashboard_visual_options_dialog"] = fake_module
            sys.modules["metroliza.ui.dashboard_visual_options_dialog"] = fake_module

            app = QApplication.instance() or QApplication([])
            dialog = ExportDialog(parent=None, db_file="")
            dialog.generate_html_dashboard_checkbox.setChecked(True)
            dialog.show()
            app.processEvents()
            dialog.open_dashboard_visual_options()

            print(json.dumps({
                "button_visible": dialog.dashboard_visuals_button.isVisible(),
                "button_enabled": dialog.dashboard_visuals_button.isEnabled(),
                "html_checked": dialog.generate_html_dashboard_checkbox.isChecked(),
                "exec_called": calls.get("exec_called", False),
                "parent_is_dialog": calls.get("parent_is_dialog", False),
                "preview_group_names": calls.get("preview_group_names"),
                "settings_preset": dialog.dashboard_visual_settings["preset"],
            }, sort_keys=True))
            dialog.close()
            app.processEvents()
            """
        )

        self.assertTrue(payload["button_visible"])
        self.assertTrue(payload["button_enabled"])
        self.assertTrue(payload["html_checked"])
        self.assertTrue(payload["exec_called"])
        self.assertTrue(payload["parent_is_dialog"])
        self.assertEqual(payload["preview_group_names"], [])
        self.assertEqual(payload["settings_preset"], "distinct")


if __name__ == "__main__":
    unittest.main()
