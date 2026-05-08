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
