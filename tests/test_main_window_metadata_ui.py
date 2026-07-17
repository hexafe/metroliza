from contextlib import closing
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, pyqtSignal
    from PyQt6.QtGui import QCloseEvent
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton
    from modules.main_window import FEATURE_IMPORT_WARMUP_MODULES, MainWindow, warm_feature_imports
    from metroliza.ui.ui_preferences import UiPreferences
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    QPushButton = None
    QDialog = None
    QMessageBox = None
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

    def setUp(self):
        self._settings_directory = tempfile.TemporaryDirectory()
        settings_path = Path(self._settings_directory.name) / "metroliza-test.ini"
        self._ui_preferences = UiPreferences(
            QSettings(str(settings_path), QSettings.Format.IniFormat)
        )

    def tearDown(self):
        self._settings_directory.cleanup()

    def _main_window(self):
        return MainWindow(
            version_label="test",
            days_until_expiration=None,
            ui_preferences=self._ui_preferences,
        )

    def test_main_window_schedules_feature_imports_after_init(self):
        imported_modules = []
        callback_calls = []
        status_messages = []

        def fake_importer(module_name):
            imported_modules.append(module_name)
            return object()

        window = self._main_window()
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
        window = self._main_window()
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
        window = self._main_window()
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
        window = self._main_window()
        try:
            button_texts = [button.text() for button in window.findChildren(QPushButton)]
            self.assertNotIn("Industrial Data", button_texts)

            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Industrial data...", action_texts)
        finally:
            window.close()

    def test_realtime_monitoring_is_tools_action_without_launcher_button(self):
        window = self._main_window()
        try:
            button_texts = [button.text() for button in window.findChildren(QPushButton)]
            self.assertNotIn("Real-time Industrial Monitoring", button_texts)

            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Real-time Industrial Monitoring...", action_texts)
        finally:
            window.close()

    def test_realtime_monitoring_dialog_uses_temporary_session_database_when_none_selected(self):
        window = self._main_window()
        session_db_path = None
        try:
            window.launch_realtime_industrial_monitoring_dialog()

            self.assertIsNotNone(window.realtime_monitoring_dialog)
            self.assertTrue(window.realtime_monitoring_dialog.isVisible())
            self.assertIsNotNone(window.last_realtime_dashboard_db_path)
            session_db_path = Path(window.last_realtime_dashboard_db_path)
            self.assertTrue(session_db_path.exists())
            self.assertEqual(session_db_path.suffix, ".sqlite")
            self.assertEqual(window.realtime_monitoring_dialog.db_file, str(session_db_path))
            self.assertIn(
                "Temporary session storage",
                window.realtime_monitoring_dialog.storage_lifecycle_label.text(),
            )
            self.assertIn("temporary session DB", window.statusBar().currentMessage())

            window.close()
            self.assertFalse(session_db_path.exists())
        finally:
            window.close()

    def test_realtime_temp_session_rebind_cancel_keeps_operator_data(self):
        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

        window = self._main_window()
        with tempfile.TemporaryDirectory() as temp_dir:
            window.launch_realtime_industrial_monitoring_dialog()
            dialog = window.realtime_monitoring_dialog
            session_db = Path(dialog.db_file)
            IndustrialDataRepository(str(session_db)).upsert_source_profile(
                profile_key="line-a",
                profile_name="Line A",
                source_db_alias="line-a",
                database_type="sqlite",
                source_object_name="events",
            )
            durable_db = str(Path(temp_dir) / "durable.db")

            with patch(
                "metroliza.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Cancel,
            ):
                window.set_db_file(durable_db)

            self.assertTrue(session_db.exists())
            self.assertEqual(dialog.db_file, str(session_db))
            self.assertEqual(
                len(
                    IndustrialDataRepository(str(session_db)).list_source_profiles(
                        include_disabled=True
                    )
                ),
                1,
            )
            self.assertIn("previous database", window.workspace_notice_label.text())

            with patch(
                "metroliza.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Discard,
            ):
                window.close()

    def test_realtime_temp_session_save_preserves_copy_before_rebind(self):
        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

        window = self._main_window()
        with tempfile.TemporaryDirectory() as temp_dir:
            window.launch_realtime_industrial_monitoring_dialog()
            dialog = window.realtime_monitoring_dialog
            session_db = Path(dialog.db_file)
            IndustrialDataRepository(str(session_db)).upsert_source_profile(
                profile_key="line-a",
                profile_name="Line A",
                source_db_alias="line-a",
                database_type="sqlite",
                source_object_name="events",
            )
            durable_db = str(Path(temp_dir) / "durable.db")
            saved_copy = Path(temp_dir) / "saved-session.sqlite"

            with (
                patch(
                    "metroliza.ui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Save,
                ),
                patch(
                    "metroliza.ui.main_window.QFileDialog.getSaveFileName",
                    return_value=(str(saved_copy), "SQLite database"),
                ),
            ):
                window.set_db_file(durable_db)

            self.assertFalse(session_db.exists())
            self.assertTrue(saved_copy.exists())
            self.assertEqual(dialog.db_file, durable_db)
            self.assertEqual(
                len(
                    IndustrialDataRepository(str(saved_copy)).list_source_profiles(
                        include_disabled=True
                    )
                ),
                1,
            )
            self.assertIn("Durable storage", dialog.storage_lifecycle_label.text())
        window.close()

    def test_realtime_temp_session_archive_cannot_replace_active_database(self):
        import sqlite3

        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

        window = self._main_window()
        with tempfile.TemporaryDirectory() as temp_dir:
            window.launch_realtime_industrial_monitoring_dialog()
            dialog = window.realtime_monitoring_dialog
            session_db = Path(dialog.db_file)
            IndustrialDataRepository(str(session_db)).upsert_source_profile(
                profile_key="line-a",
                profile_name="Line A",
                source_db_alias="line-a",
                database_type="sqlite",
                source_object_name="events",
            )
            active_db = Path(temp_dir) / "active.db"
            with closing(sqlite3.connect(active_db)) as connection, connection:
                connection.execute("CREATE TABLE report_marker (value TEXT NOT NULL)")
                connection.execute("INSERT INTO report_marker VALUES ('keep-me')")

            with (
                patch(
                    "metroliza.ui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Save,
                ),
                patch(
                    "metroliza.ui.main_window.QFileDialog.getSaveFileName",
                    return_value=(str(active_db), "SQLite database"),
                ),
                patch("metroliza.ui.main_window.QMessageBox.warning") as warning,
            ):
                window.set_db_file(str(active_db))

            self.assertTrue(session_db.exists())
            self.assertEqual(dialog.db_file, str(session_db))
            with closing(sqlite3.connect(active_db)) as connection:
                marker = connection.execute("SELECT value FROM report_marker").fetchone()[0]
            self.assertEqual(marker, "keep-me")
            self.assertTrue(warning.called)

            close_event = QCloseEvent()
            with (
                patch(
                    "metroliza.ui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Save,
                ),
                patch(
                    "metroliza.ui.main_window.QFileDialog.getSaveFileName",
                    return_value=(str(active_db), "SQLite database"),
                ),
                patch("metroliza.ui.main_window.QMessageBox.warning") as close_warning,
            ):
                window.closeEvent(close_event)

            self.assertFalse(close_event.isAccepted())
            self.assertTrue(session_db.exists())
            with closing(sqlite3.connect(active_db)) as connection:
                marker = connection.execute("SELECT value FROM report_marker").fetchone()[0]
            self.assertEqual(marker, "keep-me")
            self.assertTrue(close_warning.called)

            with patch(
                "metroliza.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Discard,
            ):
                window.close()

    def test_realtime_pending_database_rebind_retries_after_monitor_stops(self):
        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

        window = self._main_window()
        with tempfile.TemporaryDirectory() as temp_dir:
            window.launch_realtime_industrial_monitoring_dialog()
            dialog = window.realtime_monitoring_dialog
            session_db = Path(dialog.db_file)
            IndustrialDataRepository(str(session_db)).upsert_source_profile(
                profile_key="line-a",
                profile_name="Line A",
                source_db_alias="line-a",
                database_type="sqlite",
                source_object_name="events",
            )
            durable_db = str(Path(temp_dir) / "durable.db")
            dialog.poll_timer.start(60_000)

            window.set_db_file(durable_db)

            self.assertEqual(dialog.db_file, str(session_db))
            self.assertEqual(window._pending_realtime_database, durable_db)

            with patch(
                "metroliza.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Discard,
            ):
                dialog.stop_monitoring()

            self.assertEqual(dialog.db_file, durable_db)
            self.assertIsNone(window._pending_realtime_database)
            self.assertFalse(session_db.exists())
        window.close()

    def test_realtime_pending_database_rebind_waits_for_dashboard_writer(self):
        window = self._main_window()

        class _RunningDashboardThread:
            running = True

            def isRunning(self):
                return self.running

        with tempfile.TemporaryDirectory() as temp_dir:
            original_db = str(Path(temp_dir) / "original.db")
            replacement_db = str(Path(temp_dir) / "replacement.db")
            window.set_db_file(original_db)
            window.launch_realtime_industrial_monitoring_dialog()
            dialog = window.realtime_monitoring_dialog
            dashboard_thread = _RunningDashboardThread()
            dialog.dashboard_thread = dashboard_thread
            dialog.poll_timer.start(60_000)

            window.set_db_file(replacement_db)

            self.assertEqual(dialog.db_file, original_db)
            self.assertEqual(window._pending_realtime_database, replacement_db)

            dialog.stop_monitoring()

            self.assertEqual(dialog.db_file, original_db)
            self.assertEqual(window._pending_realtime_database, replacement_db)

            dashboard_thread.running = False
            dialog._on_dashboard_writer_finished()

            self.assertEqual(dialog.db_file, replacement_db)
            self.assertIsNone(window._pending_realtime_database)
        window.close()

    def test_realtime_pending_rebind_waits_for_queued_poll_callbacks(self):
        window = self._main_window()

        class _FinishedButOwnedPollThread:
            def isRunning(self):
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            original_db = str(Path(temp_dir) / "original.db")
            replacement_db = str(Path(temp_dir) / "replacement.db")
            window.set_db_file(original_db)
            window.launch_realtime_industrial_monitoring_dialog()
            dialog = window.realtime_monitoring_dialog
            owned_thread = _FinishedButOwnedPollThread()
            dialog.poll_thread = owned_thread
            dialog.poll_timer.start(60_000)

            window.set_db_file(replacement_db)
            dialog.stop_monitoring()

            self.assertIs(dialog.poll_thread, owned_thread)
            self.assertTrue(dialog.is_monitoring_active())
            self.assertEqual(dialog.db_file, original_db)
            self.assertEqual(window._pending_realtime_database, replacement_db)

            dialog._clear_poll_thread()

            self.assertIsNone(dialog.poll_thread)
            self.assertEqual(dialog.db_file, replacement_db)
            self.assertIsNone(window._pending_realtime_database)
        window.close()

    def test_realtime_monitoring_dialog_uses_selected_database(self):
        window = self._main_window()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                db_path = str(Path(temp_dir) / "monitoring.db")
                window.set_db_file(db_path)

                window.launch_realtime_industrial_monitoring_dashboard()

                self.assertIsNotNone(window.realtime_monitoring_dialog)
                self.assertTrue(window.realtime_monitoring_dialog.isVisible())
                self.assertEqual(window.last_realtime_dashboard_db_path, db_path)
                self.assertEqual(window.realtime_monitoring_dialog.db_file, db_path)
                self.assertIn("monitoring opened", window.statusBar().currentMessage())
                self.assertNotIn("temporary", window.statusBar().currentMessage().lower())
        finally:
            window.close()

    def test_realtime_monitoring_dialog_rebinds_in_place_after_database_change(self):
        window = self._main_window()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                first_db = str(Path(temp_dir) / "first.db")
                second_db = str(Path(temp_dir) / "second.db")
                window.set_db_file(first_db)
                window.launch_realtime_industrial_monitoring_dialog()
                first_dialog = window.realtime_monitoring_dialog

                window.set_db_file(second_db)
                window.launch_realtime_industrial_monitoring_dialog()

                self.assertIs(window.realtime_monitoring_dialog, first_dialog)
                self.assertEqual(window.realtime_monitoring_dialog.db_file, second_db)
                self.assertTrue(first_dialog.isVisible())
                self.assertIn("moved to the active database", window.workspace_notice_label.text())
        finally:
            window.close()

    def test_open_industrial_dialog_tracks_database_selection_changes(self):
        window = self._main_window()
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

    def test_database_selection_recovers_abandoned_staging_once(self):
        window = self._main_window()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                db_path = Path(temp_dir) / "monitoring.db"
                db_path.touch()
                with patch(
                    "metroliza.industrial.industrial_data_repository.IndustrialDataRepository"
                ) as repository_type:
                    repository_type.return_value.recover_abandoned_sync_staging_at_startup.return_value = {
                        "runs_failed": 1,
                        "rows_discarded": 7,
                    }

                    window.set_db_file(str(db_path))
                    window.set_db_file(str(db_path))

                repository_type.assert_called_once_with(str(db_path.resolve()))
                repository_type.return_value.recover_abandoned_sync_staging_at_startup.assert_called_once_with()
                self.assertIn("1 run(s), 7 row(s)", window.statusBar().currentMessage())
        finally:
            window.close()

    def test_set_directory_updates_context_label_state(self):
        window = self._main_window()
        try:
            window.set_directory("/tmp/metroliza-reports")

            self.assertEqual(window.directory, "/tmp/metroliza-reports")
            self.assertEqual(window.source_status_label.text(), "Source: /tmp/metroliza-reports")
            self.assertEqual(window.database_status_label.text(), "Database: not selected")
        finally:
            window.close()

    def test_workflow_next_step_tracks_source_and_database_context(self):
        window = self._main_window()
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

    def test_launch_modifydb_preserves_other_workflows_and_reuses_visible_dialog(self):
        window = self._main_window()

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

            self.assertEqual(window.export_dialog.close_calls, 0)
            self.assertEqual(window.parsing_dialog.close_calls, 0)
            self.assertEqual(len(FakeModifyDialog.created), 1)
            self.assertEqual(FakeModifyDialog.created[0].db_file, "/tmp/metroliza.db")
            self.assertEqual(FakeModifyDialog.created[0].show_calls, 1)
            self.assertEqual(FakeModifyDialog.created[0].raise_calls, 2)
            self.assertEqual(FakeModifyDialog.created[0].activate_calls, 2)
        finally:
            window.close()

    def test_database_context_change_identifies_workflows_kept_on_previous_database(self):
        window = self._main_window()

        class OpenWorkflow:
            db_file = "/tmp/previous.db"

            @staticmethod
            def isVisible():
                return True

        try:
            window.parsing_dialog = OpenWorkflow()
            window.export_dialog = OpenWorkflow()

            window.set_db_file("/tmp/current.db")

            self.assertFalse(window.workspace_notice_label.isHidden())
            self.assertIn("Report import", window.workspace_notice_label.text())
            self.assertIn("Export", window.workspace_notice_label.text())
            self.assertIn("previously selected database", window.workspace_notice_label.text())
        finally:
            window.parsing_dialog = None
            window.export_dialog = None
            window.close()

    def test_workspace_shell_exposes_guided_navigation_without_launcher_button_sprawl(self):
        window = self._main_window()
        try:
            navigation = [
                window.navigation_list.item(index).text()
                for index in range(window.navigation_list.count())
            ]

            self.assertEqual(
                navigation,
                [
                    "Home",
                    "Reports",
                    "CSV Analytics",
                    "Industrial Data",
                    "Realtime Monitor",
                    "Parser Profiles",
                ],
            )
            self.assertEqual(window.workspace_stack.count(), len(navigation))
            window.navigation_list.setCurrentRow(3)
            self.assertEqual(window.workspace_stack.currentIndex(), 3)
            self.assertEqual(
                window.navigation_list.accessibleName(),
                "Metroliza workspace navigation",
            )
        finally:
            window.close()

    def test_workspace_navigation_restores_before_default_state_can_overwrite_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = str(Path(temp_dir) / "ui.ini")
            preferences = UiPreferences(
                QSettings(settings_file, QSettings.Format.IniFormat)
            )
            preferences.set("presentation/navigation/current", 4)

            window = MainWindow(
                version_label="test",
                days_until_expiration=None,
                ui_preferences=preferences,
            )
            try:
                self.assertEqual(window.navigation_list.currentRow(), 4)
                self.assertEqual(window.workspace_stack.currentIndex(), 4)
                window.navigation_list.setCurrentRow(2)
                self.assertEqual(
                    preferences.get(
                        "presentation/navigation/current",
                        -1,
                        expected_type=int,
                    ),
                    2,
                )
            finally:
                window.close()

    def test_workspace_context_versions_real_source_and_database_changes(self):
        window = self._main_window()
        try:
            window.set_directory("/tmp/reports")
            window.set_db_file("/tmp/metroliza.db")
            snapshot = window.workspace_context.snapshot

            self.assertEqual(snapshot.version, 2)
            self.assertEqual(snapshot.source_directory, "/tmp/reports")
            self.assertEqual(snapshot.database_file, "/tmp/metroliza.db")
            self.assertEqual(window.directory, snapshot.source_directory)
            self.assertEqual(window.db_file, snapshot.database_file)

            window.set_db_file("/tmp/metroliza.db")
            self.assertEqual(window.workspace_context.snapshot.version, 2)
        finally:
            window.close()

    def test_metadata_enrichment_finished_reports_result_and_hides_cancel(self):
        window = self._main_window()

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
        window = self._main_window()
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
        window = self._main_window()
        calls = []
        try:
            window.launch_metadata_enrichment = lambda: calls.append(window.db_file)

            window.start_metadata_enrichment_from_parsing("/tmp/metroliza.db")

            self.assertEqual(window.db_file, "/tmp/metroliza.db")
            self.assertEqual(calls, ["/tmp/metroliza.db"])
        finally:
            window.close()

    def test_metadata_enrichment_without_database_shows_clear_message(self):
        window = self._main_window()
        try:
            window.launch_metadata_enrichment()

            self.assertFalse(window.metadata_enrichment_status_label.isHidden())
            self.assertIn("Select a database", window.metadata_enrichment_status_label.text())
        finally:
            window.close()

    def test_close_event_cancels_active_metadata_enrichment_and_stays_open(self):
        window = self._main_window()

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

    def test_close_event_keeps_realtime_session_db_until_dialog_shutdown_completes(self):
        window = self._main_window()

        class FakeRealtimeDialog:
            def __init__(self):
                self.ready = False
                self.shutdown_calls = 0
                self.close_calls = 0

            def request_shutdown(self):
                self.shutdown_calls += 1
                return self.ready

            def is_close_deferred(self):
                return not self.ready

            def close(self):
                self.close_calls += 1

        with tempfile.TemporaryDirectory() as temp_dir:
            session_db = Path(temp_dir) / "session.sqlite"
            session_db.write_bytes(b"")
            fake_dialog = FakeRealtimeDialog()
            window._realtime_session_db_path = session_db
            window.realtime_monitoring_dialog = fake_dialog

            first_event = QCloseEvent()
            window.closeEvent(first_event)

            self.assertFalse(first_event.isAccepted())
            self.assertTrue(session_db.exists())
            self.assertEqual(fake_dialog.shutdown_calls, 1)
            self.assertEqual(fake_dialog.close_calls, 0)

            fake_dialog.ready = True
            second_event = QCloseEvent()
            window.closeEvent(second_event)

            self.assertTrue(second_event.isAccepted())
            self.assertFalse(session_db.exists())
            self.assertEqual(fake_dialog.close_calls, 1)
        window.realtime_monitoring_dialog = None
        window.close()

    def test_close_event_stays_open_when_managed_dialog_rejects_close(self):
        window = self._main_window()

        class BlockingDialog(QDialog):
            def __init__(self):
                super().__init__()
                self.allow_close = False
                self.setWindowTitle("Unsaved editor")

            def closeEvent(self, event):
                if self.allow_close:
                    event.accept()
                else:
                    event.ignore()

        child = window.window_coordinator.open_modeless("blocking_editor", lambda _snapshot: BlockingDialog())
        try:
            first_event = QCloseEvent()

            window.closeEvent(first_event)

            self.assertFalse(first_event.isAccepted())
            self.assertIs(window.window_coordinator.get("blocking_editor"), child)
            self.assertTrue(child.isVisible())
            self.assertIn("Unsaved editor", window.workspace_notice_label.text())

            child.allow_close = True
            second_event = QCloseEvent()
            window.closeEvent(second_event)

            self.assertTrue(second_event.isAccepted())
        finally:
            child.allow_close = True
            try:
                child.close()
            except RuntimeError:
                pass
            window.close()

    def test_root_close_retries_after_deferred_managed_dialog_finishes(self):
        window = self._main_window()

        class DeferredDialog(QDialog):
            def __init__(self):
                super().__init__()
                self.allow_close = False

            def closeEvent(self, event):
                if self.allow_close:
                    event.accept()
                else:
                    event.ignore()

            def is_close_deferred(self):
                return not self.allow_close

        child = window.window_coordinator.open_modeless(
            "deferred_worker",
            lambda _snapshot: DeferredDialog(),
        )
        window.show()
        try:
            first_event = QCloseEvent()
            window.closeEvent(first_event)
            self.assertFalse(first_event.isAccepted())
            self.assertTrue(window._close_deferred_for_children)
            self.assertTrue(window.isVisible())

            child.allow_close = True
            self.assertTrue(child.close())
            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            self.assertFalse(window._close_deferred_for_children)
            self.assertFalse(window.isVisible())
        finally:
            child.allow_close = True
            try:
                child.close()
            except RuntimeError:
                pass
            window.close()

    def test_root_close_requires_fresh_request_after_non_deferred_blocker_closes(self):
        window = self._main_window()

        class BlockingDialog(QDialog):
            def __init__(self):
                super().__init__()
                self.allow_close = False
                self.close_attempts = 0

            def closeEvent(self, event):
                self.close_attempts += 1
                if self.allow_close:
                    event.accept()
                else:
                    event.ignore()

        window.window_coordinator.open_modeless("clean_child", lambda _snapshot: QDialog())
        blocker = window.window_coordinator.open_modeless(
            "persistent_blocker",
            lambda _snapshot: BlockingDialog(),
        )
        window.show()
        try:
            close_event = QCloseEvent()
            window.closeEvent(close_event)
            self.assertFalse(close_event.isAccepted())
            self.assertEqual(window._deferred_close_blockers, set())
            self.assertFalse(window._close_deferred_for_children)
            self.assertEqual(blocker.close_attempts, 1)

            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            self.assertTrue(window.isVisible())
            self.assertEqual(blocker.close_attempts, 1)

            blocker.allow_close = True
            blocker.close()
            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
            self.assertTrue(window.isVisible())

            window.close()
            self.assertFalse(window.isVisible())
        finally:
            try:
                blocker.allow_close = True
                blocker.close()
            except RuntimeError:
                pass
            window.close()

    def test_dirty_modifydb_cancel_never_arms_automatic_root_close(self):
        window = self._main_window()
        window.show()
        with tempfile.TemporaryDirectory() as temp_dir:
            window.set_db_file(str(Path(temp_dir) / "report.db"))
            window.launch_modifydb_dialog()
            dialog = window.modifydb_dialog
            dialog.populate_table(dialog.reference_table, [("REF-A", 3)])
            dialog.reference_table.item(0, 1).setText("REF-B")

            with patch(
                "metroliza.ui.modify_db.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Cancel,
            ):
                close_event = QCloseEvent()
                window.closeEvent(close_event)

            self.assertFalse(close_event.isAccepted())
            self.assertTrue(window.isVisible())
            self.assertFalse(window._close_deferred_for_children)
            self.assertEqual(window._deferred_close_blockers, set())

            dialog._changes_committed = True
            dialog.close()
            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            self.assertTrue(window.isVisible())
        window.close()

    def test_child_deferral_cancel_requires_fresh_root_close_request(self):
        window = self._main_window()

        class DeferredDialog(QDialog):
            close_deferral_cancelled = pyqtSignal()

            def __init__(self):
                super().__init__()
                self.allow_close = False

            def closeEvent(self, event):
                if self.allow_close:
                    event.accept()
                else:
                    event.ignore()

            def is_close_deferred(self):
                return not self.allow_close

        child = window.window_coordinator.open_modeless(
            "cancelled_deferral",
            lambda _snapshot: DeferredDialog(),
        )
        window.show()
        try:
            close_event = QCloseEvent()
            window.closeEvent(close_event)
            self.assertFalse(close_event.isAccepted())
            self.assertTrue(window._close_deferred_for_children)

            child.close_deferral_cancelled.emit()
            self.assertFalse(window._close_deferred_for_children)
            self.assertEqual(window._deferred_close_blockers, set())

            child.allow_close = True
            child.close()
            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            self.assertTrue(window.isVisible())
        finally:
            child.allow_close = True
            try:
                child.close()
            except RuntimeError:
                pass
            window.close()

    def test_realtime_retention_cancel_clears_deferred_root_close_intent(self):
        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

        window = self._main_window()

        class DeferredRealtimeDialog:
            def __init__(self):
                self.ready = False
                self.close_calls = 0

            def request_shutdown(self):
                return self.ready

            def is_close_deferred(self):
                return not self.ready

            def close(self):
                self.close_calls += 1

        with tempfile.TemporaryDirectory() as temp_dir:
            session_db = Path(temp_dir) / "session.sqlite"
            IndustrialDataRepository(str(session_db)).upsert_source_profile(
                profile_key="line-a",
                profile_name="Line A",
                source_db_alias="line-a",
                database_type="sqlite",
                source_object_name="events",
            )
            dialog = DeferredRealtimeDialog()
            window._realtime_session_db_path = session_db
            window.realtime_monitoring_dialog = dialog
            window.show()

            first_event = QCloseEvent()
            window.closeEvent(first_event)
            self.assertFalse(first_event.isAccepted())
            self.assertTrue(window._close_deferred_for_realtime)

            dialog.ready = True
            with patch(
                "metroliza.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Cancel,
            ) as question:
                window._on_realtime_monitoring_shutdown_complete()
                self.app.processEvents()

                self.assertTrue(window.isVisible())
                self.assertTrue(session_db.exists())
                self.assertFalse(window._close_deferred_for_realtime)
                self.assertEqual(question.call_count, 1)

                window._on_realtime_monitoring_shutdown_complete()
                self.app.processEvents()
                self.assertEqual(question.call_count, 1)

            with patch(
                "metroliza.ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Discard,
            ):
                window.close()

    def test_metadata_enrichment_thread_is_cleared_after_thread_lifecycle_finishes(self):
        window = self._main_window()
        try:
            marker = object()
            window.metadata_enrichment_thread = marker

            window._clear_metadata_enrichment_thread()

            self.assertIsNone(window.metadata_enrichment_thread)
        finally:
            window.close()

    def test_dirty_realtime_source_cancel_never_arms_automatic_root_close(self):
        window = self._main_window()
        window.show()
        with tempfile.TemporaryDirectory() as temp_dir:
            window.set_db_file(str(Path(temp_dir) / "realtime.db"))
            window.launch_realtime_industrial_monitoring_dialog()
            realtime = window.realtime_monitoring_dialog
            realtime.open_source_profiles_dialog()
            self.app.processEvents()
            source_editor = realtime.source_window
            source_editor.source_name_edit.setText("Unsaved line source")

            with patch(
                "metroliza.ui.industrial_source_profiles_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ):
                close_event = QCloseEvent()
                window.closeEvent(close_event)

            self.assertFalse(close_event.isAccepted())
            self.assertTrue(window.isVisible())
            self.assertFalse(window._close_deferred_for_realtime)
            self.assertTrue(source_editor.isVisible())

            with patch(
                "metroliza.ui.industrial_source_profiles_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                source_editor.close()
            self.app.processEvents()

            realtime.shutdown_complete.emit()
            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            self.assertTrue(window.isVisible())
            self.assertFalse(window._close_deferred_for_realtime)
        window.close()

    def test_realtime_shutdown_retry_intent_is_consumed_before_other_blocker(self):
        window = self._main_window()

        class _ReadyRealtime:
            def request_shutdown(self):
                return True

            def close(self):
                return True

        class _DirtyChild(QDialog):
            def __init__(self):
                super().__init__()
                self.allow_close = False

            def closeEvent(self, event):
                if self.allow_close:
                    event.accept()
                else:
                    event.ignore()

        blocker = window.window_coordinator.open_modeless(
            "dirty_child_after_realtime",
            lambda _snapshot: _DirtyChild(),
        )
        window.realtime_monitoring_dialog = _ReadyRealtime()
        window._close_deferred_for_realtime = True
        window.show()
        try:
            window._on_realtime_monitoring_shutdown_complete()
            self.app.processEvents()

            self.assertTrue(window.isVisible())
            self.assertFalse(window._close_deferred_for_realtime)

            blocker.allow_close = True
            blocker.close()
            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            window.realtime_monitoring_dialog = _ReadyRealtime()
            window._on_realtime_monitoring_shutdown_complete()
            self.app.processEvents()

            self.assertTrue(window.isVisible())
            self.assertFalse(window._close_deferred_for_realtime)
        finally:
            window.realtime_monitoring_dialog = None
            blocker.allow_close = True
            try:
                blocker.close()
            except RuntimeError:
                pass
            window.close()

    def test_realtime_relaunch_rebinds_after_dirty_source_draft_is_resolved(self):
        window = self._main_window()
        window.show()
        with tempfile.TemporaryDirectory() as temp_dir:
            first_db = str(Path(temp_dir) / "first.db")
            second_db = str(Path(temp_dir) / "second.db")
            window.set_db_file(first_db)
            window.launch_realtime_industrial_monitoring_dialog()
            realtime = window.realtime_monitoring_dialog
            realtime.open_source_profiles_dialog()
            self.app.processEvents()
            source_editor = realtime.source_window
            source_editor.source_name_edit.setText("Unsaved line source")

            with patch(
                "metroliza.ui.industrial_source_profiles_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ):
                window.set_db_file(second_db)

            self.assertEqual(window.db_file, second_db)
            self.assertEqual(realtime.db_file, first_db)
            self.assertIs(window.realtime_monitoring_dialog, realtime)

            with patch(
                "metroliza.ui.industrial_source_profiles_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                source_editor.close()
            self.app.processEvents()

            window.launch_realtime_industrial_monitoring_dialog()

            self.assertIs(window.realtime_monitoring_dialog, realtime)
            self.assertIs(window.window_coordinator.get("realtime_monitor"), realtime)
            self.assertEqual(realtime.db_file, second_db)
            self.assertTrue(realtime.isVisible())
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
