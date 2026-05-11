import unittest

try:
    from PyQt6.QtWidgets import QApplication, QPushButton
    from modules.main_window import MainWindow
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    QPushButton = None
    MainWindow = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


class TestMainWindowMetadataUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

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
            self.assertIn("Legacy CSV Summary...", action_texts)
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


if __name__ == "__main__":
    unittest.main()
