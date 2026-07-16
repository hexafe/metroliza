import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from metroliza.parsing.pdf_backend import require_pdf_backend

try:
    from PyQt6.QtWidgets import QApplication

    from metroliza.ui.parser_plugin_wizard import (
        ParserPluginWizardDialog,
        create_llm_handoff_workspace,
        safe_profile_id,
        summarize_profile_store,
    )
    from modules.main_window import MainWindow
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    ParserPluginWizardDialog = None
    create_llm_handoff_workspace = None
    safe_profile_id = None
    summarize_profile_store = None
    MainWindow = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


def _write_pdf_text(path: Path, text: str) -> None:
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()


class TestParserPluginWizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_safe_profile_id_creates_parser_slug(self):
        self.assertEqual(safe_profile_id("Supplier Alpha v2"), "supplier_alpha_v2")
        self.assertEqual(safe_profile_id("123"), "supplier_123")
        self.assertEqual(safe_profile_id("a"), "a_profile")
        self.assertEqual(safe_profile_id(""), "supplier_profile")

    def test_create_handoff_workspace_writes_data_only_template(self):
        with tempfile.TemporaryDirectory() as home_dir:
            workspace = create_llm_handoff_workspace(
                plugin_id="Supplier Alpha",
                display_name="Supplier Alpha",
                source_format="pdf",
                home=Path(home_dir),
            )

            self.assertTrue(workspace.root.is_dir())
            self.assertTrue((workspace.root / "samples").is_dir())
            self.assertTrue(workspace.profile_path.is_file())
            self.assertTrue(workspace.handoff_path.is_file())
            self.assertTrue(workspace.expected_results_path.is_file())
            self.assertTrue((workspace.root / "handoff_manifest.json").is_file())
            self.assertTrue((workspace.root / "NON_TECHNICAL_STEPS.md").is_file())
            self.assertTrue((workspace.root / "contracts" / "01_parser_api_contract.md").is_file())
            self.assertTrue((workspace.root / "reference" / "contract_snippets.md").is_file())
            self.assertTrue((workspace.root / "prompts" / "01_identify_template_markers.md").is_file())
            self.assertTrue((workspace.root / "prompts" / "06_fix_validation_failures.md").is_file())

            profile_text = workspace.profile_path.read_text(encoding="utf-8")
            handoff_text = workspace.handoff_path.read_text(encoding="utf-8")
            manifest = json.loads((workspace.root / "handoff_manifest.json").read_text(encoding="utf-8"))
            snippets = (workspace.root / "reference" / "contract_snippets.md").read_text(encoding="utf-8")
            profile = yaml.safe_load(profile_text)
            self.assertEqual(profile["plugin"]["plugin_id"], "supplier_alpha")
            self.assertIn("source_format: pdf", profile_text)
            self.assertIn("Do not ask for Python code", handoff_text)
            self.assertIn("database writes", handoff_text)
            self.assertIn("measurement row capture names", handoff_text)
            self.assertIn("parser_plugin_self_service.py validate", handoff_text)
            self.assertIn("approval evidence records", handoff_text)
            self.assertEqual(manifest["package_type"], "declarative_profile")
            self.assertEqual(manifest["allowed_outputs"], ["profile.yaml"])
            self.assertIn("PluginManifest", snippets)
            self.assertIn("ParseResultV2", snippets)
            self.assertIn("Do not write SQLite", snippets)
            self.assertIn("sample_file,reference,report_date", workspace.expected_results_path.read_text(encoding="utf-8"))

    def test_store_summary_initializes_empty_store(self):
        with tempfile.TemporaryDirectory() as home_dir:
            summary = summarize_profile_store(home=Path(home_dir))

            self.assertEqual(summary.total, 0)
            self.assertEqual(summary.enabled, 0)
            self.assertTrue((summary.root / "approved").is_dir())
            self.assertTrue((summary.root / "incoming").is_dir())

    def test_dialog_can_create_handoff_workspace_without_llm_calls(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Beta")
                dialog.display_name_edit.setText("Supplier Beta")
                dialog.source_format_combo.setCurrentText("csv")

                dialog.create_handoff_workspace()

                expected_root = Path(home_dir) / ".metroliza" / "parser_plugins" / "profiles" / "incoming" / "supplier_beta"
                self.assertTrue(expected_root.is_dir())
                self.assertIn("Handoff folder ready", dialog.result_label.text())
                self.assertEqual(dialog.plugin_id_edit.text(), "supplier_beta")
                self.assertTrue(dialog.open_folder_button.isEnabled())
                self.assertTrue(dialog.copy_path_button.isEnabled())
                self.assertTrue(dialog.check_package_button.isEnabled())
                self.assertTrue(dialog.validate_button.isEnabled())
                self.assertTrue(dialog.repair_button.isEnabled())
            finally:
                dialog.close()

    def test_dialog_writes_integrity_validation_and_repair_artifacts(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Epsilon")
                dialog.create_handoff_workspace()

                dialog.check_handoff_package()
                self.assertIn("Package check passed", dialog.result_label.text())
                self.assertTrue(
                    (dialog.last_handoff_workspace.root / "artifacts" / "handoff_integrity.txt").is_file()
                )
                sample = dialog.last_handoff_workspace.root / "samples" / "sample_report_01.pdf"
                _write_pdf_text(
                    sample,
                    "\n".join(
                        (
                            "SUPPLIER TEMPLATE MARKER",
                            "Reference: REF123",
                            "Date: 2026-01-05",
                            "Sample: 0001",
                            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0",
                            "",
                        )
                    ),
                )
                dialog.last_handoff_workspace.expected_results_path.write_text(
                    "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
                    "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
                    "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,Y,10.0,0.1,-0.1,,10.02,0.02,0\n",
                    encoding="utf-8",
                )

                dialog.validate_handoff_profile()
                self.assertIn("Validation failed", dialog.result_label.text())
                self.assertTrue(
                    (dialog.last_handoff_workspace.root / "artifacts" / "profile_validation.txt").is_file()
                )

                dialog.create_repair_prompt()
                self.assertIn("Repair prompt written", dialog.result_label.text())
                self.assertTrue(
                    (dialog.last_handoff_workspace.root / "artifacts" / "profile_repair_prompt.md").is_file()
                )
            finally:
                dialog.close()

    def test_dialog_open_and_copy_handoff_folder_actions(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Gamma")
                dialog.create_handoff_workspace()

                with patch("metroliza.ui.parser_plugin_wizard.QDesktopServices.openUrl", return_value=True) as open_url:
                    dialog.open_handoff_folder()
                open_url.assert_called_once()

                dialog.copy_handoff_path()
                self.assertEqual(QApplication.clipboard().text(), str(dialog.last_handoff_workspace.root))
                self.assertIn("Copied handoff folder path", dialog.result_label.text())
            finally:
                dialog.close()

    def test_dialog_open_and_copy_are_noops_without_workspace(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                with patch("metroliza.ui.parser_plugin_wizard.QDesktopServices.openUrl") as open_url:
                    dialog.open_handoff_folder()
                dialog.copy_handoff_path()

                open_url.assert_not_called()
                self.assertIn("No handoff folder created yet", dialog.result_label.text())
            finally:
                dialog.close()

    def test_dialog_open_handoff_folder_reports_failed_desktop_open(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Delta")
                dialog.create_handoff_workspace()

                with patch("metroliza.ui.parser_plugin_wizard.QDesktopServices.openUrl", return_value=False):
                    dialog.open_handoff_folder()

                self.assertIn("Could not open folder", dialog.result_label.text())
                self.assertIn(str(dialog.last_handoff_workspace.root), dialog.result_label.text())
            finally:
                dialog.close()

    def test_main_window_tools_menu_opens_parser_profile_dialog(self):
        window = MainWindow(version_label="test", days_until_expiration=None)

        class FakeDialog:
            def __init__(self, parent):
                self.parent = parent
                self.show_calls = 0
                self.raise_calls = 0
                self.activate_calls = 0

            def isVisible(self):
                return self.show_calls > 0

            def show(self):
                self.show_calls += 1

            def raise_(self):
                self.raise_calls += 1

            def activateWindow(self):
                self.activate_calls += 1

        try:
            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Parser profiles...", action_texts)

            with patch("metroliza.ui.parser_plugin_wizard.ParserPluginWizardDialog", FakeDialog):
                window.launch_parser_plugin_wizard()

            self.assertIsInstance(window.parser_plugin_wizard_dialog, FakeDialog)
            self.assertEqual(window.parser_plugin_wizard_dialog.show_calls, 1)
            self.assertEqual(window.parser_plugin_wizard_dialog.raise_calls, 1)
            self.assertEqual(window.parser_plugin_wizard_dialog.activate_calls, 1)
        finally:
            window.close()
