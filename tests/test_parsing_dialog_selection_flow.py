import unittest
from unittest.mock import patch

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget
    from modules.parsing_dialog import ParsingDialog
except ImportError as exc:  # pragma: no cover - environment-dependent import
    Qt = None
    QApplication = None
    QMessageBox = None
    QWidget = None
    ParsingDialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


class _DummyParent(QWidget if QWidget is not None else object):
    def set_directory(self, _directory):
        return None


class _Signal:
    def connect(self, _callback):
        return None


class _ProgressDialog:
    def show(self):
        return None

    def accept(self):
        return None


class _ProgressBar:
    def setValue(self, _value):
        return None


class _ProgressLabel:
    def setText(self, _value):
        return None


class TestParsingDialogSelectionFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f'PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}')
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_directory_and_decline_archive_keeps_selection_empty(self):
        dialog = ParsingDialog(parent=None, directory=None, db_file=None)

        with patch('modules.parsing_dialog.QFileDialog.getExistingDirectory', return_value=''), \
                patch('modules.parsing_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.No), \
                patch('modules.parsing_dialog.QFileDialog.getOpenFileName') as get_open_file_name:
            dialog.select_directory()

        self.assertEqual(dialog.directory, None)
        self.assertEqual(dialog.directory_text_label.text(), 'None selected')
        get_open_file_name.assert_not_called()

    def test_cancel_directory_and_accept_archive_opens_archive_dialog(self):
        parent = _DummyParent()
        dialog = ParsingDialog(parent=parent, directory=None, db_file=None)

        with patch('modules.parsing_dialog.QFileDialog.getExistingDirectory', return_value=''), \
                patch('modules.parsing_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
                patch('modules.parsing_dialog.QFileDialog.getOpenFileName', return_value=('/tmp/source.zip', '')) as get_open_file_name:
            dialog.select_directory()

        self.assertEqual(dialog.directory, '/tmp/source.zip')
        self.assertEqual(dialog.directory_text_label.text(), '/tmp/source.zip')
        get_open_file_name.assert_called_once()

    def test_default_metadata_mode_is_light_for_gui_parsing(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')

        self.assertEqual(dialog.metadata_mode_combo.currentData(), 'light')
        self.assertFalse(dialog.rich_metadata_checkbox.isChecked())

    def test_metadata_mode_tooltips_explain_speed_tradeoff(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')

        complete_index = dialog.metadata_mode_combo.findData('complete')
        light_index = dialog.metadata_mode_combo.findData('light')

        self.assertIn('OCR fallback', dialog.metadata_mode_combo.itemData(complete_index, Qt.ItemDataRole.ToolTipRole))
        self.assertIn('much faster', dialog.metadata_mode_combo.itemData(light_index, Qt.ItemDataRole.ToolTipRole))
        self.assertIn('much slower', dialog.metadata_mode_combo.toolTip())

    def test_complete_metadata_mode_disables_background_enrichment_checkbox(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        complete_index = dialog.metadata_mode_combo.findData('complete')
        light_index = dialog.metadata_mode_combo.findData('light')

        dialog.rich_metadata_checkbox.setChecked(True)
        dialog.metadata_mode_combo.setCurrentIndex(complete_index)

        self.assertFalse(dialog.rich_metadata_checkbox.isEnabled())
        self.assertFalse(dialog.rich_metadata_checkbox.isChecked())
        self.assertIn('redundant', dialog.rich_metadata_checkbox.toolTip())

        dialog.metadata_mode_combo.setCurrentIndex(light_index)

        self.assertTrue(dialog.rich_metadata_checkbox.isEnabled())
        self.assertIn('fast import', dialog.rich_metadata_checkbox.toolTip())

    def test_loading_screen_passes_selected_metadata_mode_to_parse_request(self):
        captured = {}

        class _FakeParseThread:
            def __init__(self, request):
                captured['request'] = request
                self.update_label = _Signal()
                self.update_progress = _Signal()
                self.error_occurred = _Signal()
                self.finished = _Signal()

            def start(self):
                captured['started'] = True

        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        light_index = dialog.metadata_mode_combo.findData('light')
        self.assertGreaterEqual(light_index, 0)
        dialog.metadata_mode_combo.setCurrentIndex(light_index)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'light')
        self.assertFalse(captured['request'].run_background_metadata_enrichment)

    def test_loading_screen_passes_user_enabled_background_metadata_enrichment(self):
        captured = {}

        class _FakeParseThread:
            def __init__(self, request):
                captured['request'] = request
                self.update_label = _Signal()
                self.update_progress = _Signal()
                self.error_occurred = _Signal()
                self.finished = _Signal()

            def start(self):
                captured['started'] = True

        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.rich_metadata_checkbox.setChecked(True)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'light')
        self.assertTrue(captured['request'].run_background_metadata_enrichment)


if __name__ == '__main__':
    unittest.main()
