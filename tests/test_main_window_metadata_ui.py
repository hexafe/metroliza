from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    from PyQt6.QtWidgets import QApplication, QPushButton
    from modules.main_window import FEATURE_IMPORT_WARMUP_MODULES, MainWindow, warm_feature_imports
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    QPushButton = None
    MainWindow = None
    FEATURE_IMPORT_WARMUP_MODULES = ()
    warm_feature_imports = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


class TestMainWindowMetadataUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_schedules_feature_imports_after_init(self):
        imported_modules = []
        callback_calls = []
        status_messages = []

        def fake_importer(module_name):
            imported_modules.append(module_name)
            return object()

        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            window._feature_import_warmup_importer = fake_importer
            self.assertEqual(imported_modules, [])
            self.assertFalse(window._feature_import_warmup_completed)
            window.schedule_feature_import_warmup(
                delay_ms=0,
                on_finished=lambda: callback_calls.append("finished"),
                status_callback=status_messages.append,
            )
            for _ in range(len(FEATURE_IMPORT_WARMUP_MODULES) + 2):
                self.app.processEvents()
            expected_modules = [module_name for _label, module_name in FEATURE_IMPORT_WARMUP_MODULES]
            self.assertEqual(imported_modules, expected_modules)
            self.assertTrue(window._feature_import_warmup_completed)
            self.assertEqual(window._feature_import_warmup_failures, [])
            self.assertEqual(callback_calls, ["finished"])
            self.assertEqual(status_messages[0], "Loading tools...")
            self.assertTrue(status_messages[-1].startswith("Loading "))
        finally:
            window.close()

    def test_metadata_enrichment_is_tools_action_without_launcher_button(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            button_texts = [button.text() for button in window.findChildren(QPushButton)]
            self.assertNotIn("Enrich Metadata", button_texts)
            self.assertFalse(hasattr(window, "enrich_metadata_button"))

            self.assertEqual(window.tools_menu.title(), "Tools")
            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Enrich existing database metadata...", action_texts)
        finally:
            window.close()

    def test_csv_summary_is_tools_action_without_launcher_button(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            button_texts = [button.text() for button in window.findChildren(QPushButton)]
            self.assertNotIn("CSV Summary", button_texts)
            self.assertFalse(hasattr(window, "csv_summary_button"))

            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("CSV Summary...", action_texts)
            self.assertNotIn("Legacy CSV Summary...", action_texts)
            self.assertFalse(hasattr(window, "legacy_csv_summary_action"))
        finally:
            window.close()

    def test_industrial_data_is_tools_action_without_launcher_button(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            button_texts = [button.text() for button in window.findChildren(QPushButton)]
            self.assertNotIn("Industrial Data", button_texts)

            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Industrial data...", action_texts)
        finally:
            window.close()

    def test_realtime_monitoring_is_tools_action_without_launcher_button(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            button_texts = [button.text() for button in window.findChildren(QPushButton)]
            self.assertNotIn("Real-time Industrial Monitoring", button_texts)

            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Real-time Industrial Monitoring...", action_texts)
        finally:
            window.close()

    def test_realtime_monitoring_dashboard_uses_temporary_database_when_none_selected(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            with patch("metroliza.ui.main_window.QDesktopServices.openUrl", return_value=True) as open_url:
                window.launch_realtime_industrial_monitoring_dashboard()

            open_url.assert_called_once()
            self.assertIsNotNone(window.last_realtime_dashboard_path)
            self.assertIsNotNone(window._realtime_monitoring_temp_db_file)
            self.assertTrue(Path(window._realtime_monitoring_temp_db_file).exists())
            html = Path(window.last_realtime_dashboard_path).read_text(encoding="utf-8")
            self.assertIn("Real-time Industrial Monitoring", html)
            self.assertIn("temporary session database", window.statusBar().currentMessage())
        finally:
            window.close()

    def test_realtime_monitoring_dashboard_generates_static_html_from_selected_database(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                db_path = str(Path(temp_dir) / "monitoring.db")
                window.set_db_file(db_path)

                with patch(
                    "metroliza.ui.main_window.QDesktopServices.openUrl",
                    return_value=True,
                ) as open_url:
                    window.launch_realtime_industrial_monitoring_dashboard()

                open_url.assert_called_once()
                self.assertIsNotNone(window.last_realtime_dashboard_path)
                html = Path(window.last_realtime_dashboard_path).read_text(encoding="utf-8")
                self.assertIn("Real-time Industrial Monitoring", html)
                self.assertIn('data-section="summary-cards"', html)
        finally:
            window.close()

    def test_open_industrial_dialog_tracks_database_selection_changes(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            class FakeIndustrialDialog:
                def __init__(self):
                    self.updated_paths = []

                def isVisible(self):
                    return True

                def update_db_file(self, db_file):
                    self.updated_paths.append(db_file)

            fake_dialog = FakeIndustrialDialog()
            window.industrial_data_dialog = fake_dialog

            window.set_db_file("/tmp/metroliza-a.db")
            window.set_db_file("/tmp/metroliza-b.db")

            self.assertEqual(
                fake_dialog.updated_paths,
                ["/tmp/metroliza-a.db", "/tmp/metroliza-b.db"],
            )
            self.assertEqual(window.db_file, "/tmp/metroliza-b.db")
        finally:
            window.close()

    def test_set_directory_updates_context_label_state(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            window.set_directory("/tmp/metroliza-reports")

            self.assertEqual(window.directory, "/tmp/metroliza-reports")
            self.assertEqual(window.source_status_label.text(), "Source: /tmp/metroliza-reports")
            self.assertEqual(window.database_status_label.text(), "Database: not selected")
        finally:
            window.close()

    def test_workflow_next_step_tracks_source_and_database_context(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            self.assertIn("choose reports", window.workflow_next_step_label.text())
            self.assertEqual(window.workflow_next_step_label.property("statusVariant"), "warning")

            window.set_directory("/tmp/metroliza-reports")
            self.assertIn("select or create a database", window.workflow_next_step_label.text())
            self.assertEqual(window.workflow_next_step_label.property("statusVariant"), "warning")

            window.set_db_file("/tmp/metroliza.db")
            self.assertIn("parse reports", window.workflow_next_step_label.text())
            self.assertEqual(window.workflow_next_step_label.property("statusVariant"), "success")

            window.set_directory("")
            self.assertIn("export this database", window.workflow_next_step_label.text())
            self.assertEqual(window.workflow_next_step_label.property("statusVariant"), "info")
        finally:
            window.close()

    def test_launch_modifydb_closes_other_transient_dialogs_and_reuses_visible_dialog(self):
        window = MainWindow(version_label="test", days_until_expiration=None)

        class VisibleDialog:
            def __init__(self):
                self.close_calls = 0
                self.visible = True

            def isVisible(self):
                return self.visible

            def close(self):
                self.close_calls += 1
                self.visible = False

        class FakeModifyDialog:
            created = []

            def __init__(self, parent, db_file):
                self.parent = parent
                self.db_file = db_file
                self.show_calls = 0
                self.raise_calls = 0
                self.activate_calls = 0
                FakeModifyDialog.created.append(self)

            def isVisible(self):
                return self.show_calls > 0

            def show(self):
                self.show_calls += 1

            def raise_(self):
                self.raise_calls += 1

            def activateWindow(self):
                self.activate_calls += 1

        try:
            window.db_file = "/tmp/metroliza.db"
            window.export_dialog = VisibleDialog()
            window.parsing_dialog = VisibleDialog()
            fake_module = types.SimpleNamespace(ModifyDB=FakeModifyDialog)

            with patch.dict(sys.modules, {"metroliza.ui.modify_db": fake_module}):
                window.launch_modifydb_dialog()
                window.launch_modifydb_dialog()

            self.assertEqual(window.export_dialog.close_calls, 1)
            self.assertEqual(window.parsing_dialog.close_calls, 1)
            self.assertEqual(len(FakeModifyDialog.created), 1)
            self.assertEqual(FakeModifyDialog.created[0].db_file, "/tmp/metroliza.db")
            self.assertEqual(FakeModifyDialog.created[0].show_calls, 1)
            self.assertEqual(FakeModifyDialog.created[0].raise_calls, 2)
            self.assertEqual(FakeModifyDialog.created[0].activate_calls, 2)
        finally:
            window.close()

    def test_metadata_enrichment_finished_reports_result_and_hides_cancel(self):
        window = MainWindow(version_label="test", days_until_expiration=None)

        class FakeResult:
            enriched_files = 2
            total_files = 3

        class FakeThread:
            result = FakeResult()

        try:
            window.metadata_enrichment_thread = FakeThread()
            window.metadata_enrichment_error_message = None
            window.cancel_metadata_enrichment_button.setVisible(True)
            window.cancel_metadata_enrichment_button.setEnabled(True)
            window.enrich_metadata_action.setEnabled(False)

            window.on_metadata_enrichment_finished()

            self.assertTrue(window.enrich_metadata_action.isEnabled())
            self.assertFalse(window.cancel_metadata_enrichment_button.isEnabled())
            self.assertTrue(window.cancel_metadata_enrichment_button.isHidden())
            self.assertEqual(window.metadata_enrichment_progress_bar.value(), 100)
            self.assertIn("2/3 reports updated", window.metadata_enrichment_status_label.text())
        finally:
            window.metadata_enrichment_thread = None
            window.close()

    def test_release_and_about_are_under_help_menu(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            top_level_action_texts = [action.text() for action in window.menuBar().actions()]
            self.assertIn("Tools", top_level_action_texts)
            self.assertIn("Help", top_level_action_texts)
            self.assertNotIn("About", top_level_action_texts)
            self.assertNotIn("Release notes", top_level_action_texts)

            help_action_texts = [action.text() for action in window.help_menu.actions()]
            self.assertIn("Main window manual", help_action_texts)
            self.assertIn("Startup, license, and support", help_action_texts)
            self.assertIn("Release notes", help_action_texts)
            self.assertIn("About", help_action_texts)
        finally:
            window.close()

    def test_parsing_enrichment_request_starts_modeless_enrichment(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        calls = []
        try:
            window.launch_metadata_enrichment = lambda: calls.append(window.db_file)

            window.start_metadata_enrichment_from_parsing("/tmp/metroliza.db")

            self.assertEqual(window.db_file, "/tmp/metroliza.db")
            self.assertEqual(calls, ["/tmp/metroliza.db"])
        finally:
            window.close()

    def test_metadata_enrichment_without_database_shows_clear_message(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            window.launch_metadata_enrichment()

            self.assertFalse(window.metadata_enrichment_status_label.isHidden())
            self.assertIn("Select a database", window.metadata_enrichment_status_label.text())
        finally:
            window.close()

    def test_close_event_cancels_active_metadata_enrichment_and_stays_open(self):
        window = MainWindow(version_label="test", days_until_expiration=None)

        class FakeThread:
            def __init__(self):
                self.stop_calls = 0

            def isRunning(self):
                return True

            def stop_enrichment(self):
                self.stop_calls += 1

        class FakeCloseEvent:
            def __init__(self):
                self.ignored = False

            def ignore(self):
                self.ignored = True

        try:
            fake_thread = FakeThread()
            window.metadata_enrichment_thread = fake_thread
            event = FakeCloseEvent()

            window.closeEvent(event)

            self.assertTrue(event.ignored)
            self.assertEqual(fake_thread.stop_calls, 1)
            self.assertIs(window.metadata_enrichment_thread, fake_thread)
            self.assertIn("Canceling metadata enrichment", window.metadata_enrichment_status_label.text())
        finally:
            window.metadata_enrichment_thread = None
            window.close()

    def test_metadata_enrichment_thread_is_cleared_after_thread_lifecycle_finishes(self):
        window = MainWindow(version_label="test", days_until_expiration=None)
        try:
            marker = object()
            window.metadata_enrichment_thread = marker

            window._clear_metadata_enrichment_thread()

            self.assertIsNone(window.metadata_enrichment_thread)
        finally:
            window.close()

    def test_feature_import_warmup_imports_deferred_modules(self):
        imported_modules = []

        def fake_importer(module_name):
            imported_modules.append(module_name)
            return object()

        loaded_modules, failed_modules = warm_feature_imports(importer=fake_importer)

        expected_modules = [module_name for _label, module_name in FEATURE_IMPORT_WARMUP_MODULES]
        self.assertEqual(imported_modules, expected_modules)
        self.assertEqual(loaded_modules, expected_modules)
        self.assertEqual(failed_modules, [])

    def test_feature_import_warmup_keeps_failures_non_fatal(self):
        expected_modules = [module_name for _label, module_name in FEATURE_IMPORT_WARMUP_MODULES]
        failing_module = expected_modules[1]

        def fake_importer(module_name):
            if module_name == failing_module:
                raise RuntimeError("boom")
            return object()

        loaded_modules, failed_modules = warm_feature_imports(importer=fake_importer)

        self.assertNotIn(failing_module, loaded_modules)
        self.assertEqual(len(failed_modules), 1)
        self.assertEqual(failed_modules[0]["module"], failing_module)
        self.assertEqual(failed_modules[0]["error_type"], "RuntimeError")
        self.assertEqual(failed_modules[0]["message"], "boom")


if __name__ == "__main__":
    unittest.main()
