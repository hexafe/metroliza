import unittest
from unittest.mock import patch

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from modules.ParsingDialog import ParsingDialog
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    QMessageBox = None
    ParsingDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


class _DummyParent:
    def set_directory(self, _directory):
        return None


class TestParsingDialogSelectionFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f'PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}')
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_directory_and_decline_archive_keeps_selection_empty(self):
        dialog = ParsingDialog(parent=None, directory=None, db_file=None)

        with patch('modules.ParsingDialog.QFileDialog.getExistingDirectory', return_value=''), \
                patch('modules.ParsingDialog.QMessageBox.question', return_value=QMessageBox.StandardButton.No), \
                patch('modules.ParsingDialog.QFileDialog.getOpenFileName') as get_open_file_name:
            dialog.select_directory()

        self.assertEqual(dialog.directory, None)
        self.assertEqual(dialog.directory_text_label.text(), 'None selected')
        get_open_file_name.assert_not_called()

    def test_cancel_directory_and_accept_archive_opens_archive_dialog(self):
        dialog = ParsingDialog(parent=_DummyParent(), directory=None, db_file=None)

        with patch('modules.ParsingDialog.QFileDialog.getExistingDirectory', return_value=''), \
                patch('modules.ParsingDialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
                patch('modules.ParsingDialog.QFileDialog.getOpenFileName', return_value=('/tmp/source.zip', '')) as get_open_file_name:
            dialog.select_directory()

        self.assertEqual(dialog.directory, '/tmp/source.zip')
        self.assertEqual(dialog.directory_text_label.text(), '/tmp/source.zip')
        get_open_file_name.assert_called_once()


if __name__ == '__main__':
    unittest.main()
