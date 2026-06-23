import unittest
from types import SimpleNamespace
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
    def __init__(self):
        super().__init__()
        self.db_file = None
        self.enrichment_launches = 0

    def set_directory(self, _directory):
        return None

    def set_db_file(self, db_file):
        self.db_file = db_file

    def launch_metadata_enrichment(self):
        self.enrichment_launches += 1


class _Signal:
    def connect(self, _callback):
        return None


class _ProgressDialog:
    def __init__(self, events=None):
        self.events = events

    def show(self):
        return None

    def accept(self):
        if self.events is not None:
            self.events.append("progress_closed")
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

    def test_archive_source_has_direct_browse_action(self):
        parent = _DummyParent()
        dialog = ParsingDialog(parent=parent, directory=None, db_file=None)

        with patch(
            'modules.parsing_dialog.QFileDialog.getOpenFileName',
            return_value=('/tmp/source.zip', ''),
        ) as get_open_file_name:
            dialog.select_archive()

        self.assertEqual(dialog.directory_button.text(), 'Browse folder')
        self.assertEqual(dialog.archive_button.text(), 'Browse archive')
        self.assertEqual(dialog.archive_button.accessibleName(), 'Browse parse archive source')
        self.assertEqual(dialog.directory, '/tmp/source.zip')
        self.assertEqual(dialog.directory_text_label.text(), '/tmp/source.zip')
        get_open_file_name.assert_called_once()

    def test_default_metadata_mode_is_light_for_gui_parsing(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')

        self.assertEqual(dialog.metadata_mode_combo.currentData(), 'fast')
        self.assertEqual(dialog._selected_metadata_request_fields(), ('light', False))
        self.assertFalse(hasattr(dialog, 'rich_metadata_checkbox'))

    def test_metadata_mode_tooltips_explain_speed_tradeoff(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')

        complete_index = dialog.metadata_mode_combo.findData('complete')
        fast_index = dialog.metadata_mode_combo.findData('fast')
        enrich_index = dialog.metadata_mode_combo.findData('fast_then_enrich')

        self.assertIn('OCR fallback', dialog.metadata_mode_combo.itemData(complete_index, Qt.ItemDataRole.ToolTipRole))
        self.assertIn('fastest import', dialog.metadata_mode_combo.itemData(fast_index, Qt.ItemDataRole.ToolTipRole))
        self.assertIn('enrichment pass', dialog.metadata_mode_combo.itemData(enrich_index, Qt.ItemDataRole.ToolTipRole))
        self.assertIn('slower', dialog.metadata_mode_combo.toolTip())

    def test_metadata_mode_selector_maps_all_user_choices_to_request_fields(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        expected = {
            'fast': ('light', False),
            'fast_then_enrich': ('light', False),
            'complete': ('complete', False),
        }

        for combo_value, request_fields in expected.items():
            with self.subTest(combo_value=combo_value):
                index = dialog.metadata_mode_combo.findData(combo_value)
                self.assertGreaterEqual(index, 0)
                dialog.metadata_mode_combo.setCurrentIndex(index)
                self.assertEqual(dialog._selected_metadata_request_fields(), request_fields)

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
        fast_index = dialog.metadata_mode_combo.findData('fast')
        self.assertGreaterEqual(fast_index, 0)
        dialog.metadata_mode_combo.setCurrentIndex(fast_index)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'light')
        self.assertFalse(captured['request'].run_background_metadata_enrichment)

    def test_loading_screen_passes_fast_then_enrich_metadata_mode(self):
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
        enrich_index = dialog.metadata_mode_combo.findData('fast_then_enrich')
        self.assertGreaterEqual(enrich_index, 0)
        dialog.metadata_mode_combo.setCurrentIndex(enrich_index)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'light')
        self.assertFalse(captured['request'].run_background_metadata_enrichment)
        self.assertTrue(dialog._pending_modeless_metadata_enrichment)

    def test_fast_then_enrich_archive_uses_embedded_enrichment_fallback(self):
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

        dialog = ParsingDialog(parent=None, directory='/tmp/reports.zip', db_file='/tmp/reports.db')
        enrich_index = dialog.metadata_mode_combo.findData('fast_then_enrich')
        self.assertGreaterEqual(enrich_index, 0)
        dialog.metadata_mode_combo.setCurrentIndex(enrich_index)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'light')
        self.assertTrue(captured['request'].run_background_metadata_enrichment)
        self.assertFalse(dialog._pending_modeless_metadata_enrichment)

    def test_loading_screen_passes_complete_metadata_mode(self):
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
        complete_index = dialog.metadata_mode_combo.findData('complete')
        self.assertGreaterEqual(complete_index, 0)
        dialog.metadata_mode_combo.setCurrentIndex(complete_index)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'complete')
        self.assertFalse(captured['request'].run_background_metadata_enrichment)

    def test_successful_fast_then_enrich_requests_modeless_metadata_enrichment(self):
        parent = _DummyParent()
        dialog = ParsingDialog(parent=parent, directory='/tmp/reports', db_file='/tmp/reports.db')
        emitted = []
        dialog.metadata_enrichment_requested.connect(emitted.append)
        dialog.loading_dialog = _ProgressDialog()
        dialog._pending_modeless_metadata_enrichment = True

        with patch('modules.parsing_dialog.QMessageBox.information') as information_mock:
            dialog.on_parse_finished()

        information_mock.assert_not_called()
        self.assertEqual(emitted, ['/tmp/reports.db'])
        self.assertEqual(parent.db_file, '/tmp/reports.db')
        self.assertEqual(parent.enrichment_launches, 0)
        self.assertFalse(dialog._pending_modeless_metadata_enrichment)

    def test_zero_report_completion_summary_explains_nothing_was_written(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.loading_dialog = _ProgressDialog()
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(total_files=0, parsed_files=0, failed_files=0),
        )

        with patch('modules.parsing_dialog.QMessageBox.information') as information_mock:
            with patch('modules.parsing_dialog.QMessageBox.warning') as warning_mock:
                dialog.on_parse_finished()

        warning_mock.assert_not_called()
        information_mock.assert_called_once()
        self.assertEqual(information_mock.call_args.args[1], "No reports parsed")
        self.assertIn("No supported report files", information_mock.call_args.args[2])
        self.assertIn("Nothing was written to /tmp/reports.db", information_mock.call_args.args[2])

    def test_partial_parse_completion_summary_warns_about_skipped_reports(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.loading_dialog = _ProgressDialog()
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(total_files=3, parsed_files=2, failed_files=1),
        )

        with patch('modules.parsing_dialog.QMessageBox.information') as information_mock:
            with patch('modules.parsing_dialog.QMessageBox.warning') as warning_mock:
                dialog.on_parse_finished()

        information_mock.assert_not_called()
        warning_mock.assert_called_once()
        self.assertEqual(warning_mock.call_args.args[1], "Parsing completed with warnings")
        self.assertIn("2 of 3 report files completed successfully", warning_mock.call_args.args[2])
        self.assertIn("1 report file could not be parsed", warning_mock.call_args.args[2])

    def test_canceled_parse_does_not_request_modeless_metadata_enrichment(self):
        parent = _DummyParent()
        dialog = ParsingDialog(parent=parent, directory='/tmp/reports', db_file='/tmp/reports.db')
        emitted = []
        dialog.metadata_enrichment_requested.connect(emitted.append)
        dialog.loading_dialog = _ProgressDialog()
        dialog._pending_modeless_metadata_enrichment = True
        dialog.parsing_canceled = True

        with patch('modules.parsing_dialog.QMessageBox.information'):
            dialog.on_parse_finished()

        self.assertEqual(emitted, [])
        self.assertEqual(parent.enrichment_launches, 0)
        self.assertFalse(dialog._pending_modeless_metadata_enrichment)

    def test_failed_parse_does_not_request_modeless_metadata_enrichment(self):
        parent = _DummyParent()
        dialog = ParsingDialog(parent=parent, directory='/tmp/reports', db_file='/tmp/reports.db')
        emitted = []
        dialog.metadata_enrichment_requested.connect(emitted.append)
        dialog.loading_dialog = _ProgressDialog()
        dialog._pending_modeless_metadata_enrichment = True
        dialog.parse_error_message = 'synthetic failure'

        with patch('modules.parsing_dialog.QMessageBox.warning'):
            dialog.on_parse_finished()

        self.assertEqual(emitted, [])
        self.assertEqual(parent.enrichment_launches, 0)
        self.assertFalse(dialog._pending_modeless_metadata_enrichment)

    def test_failed_parse_closes_progress_dialog_before_warning(self):
        events = []
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.loading_dialog = _ProgressDialog(events)
        dialog.parse_error_message = 'synthetic failure'

        with patch(
            'modules.parsing_dialog.QMessageBox.warning',
            side_effect=lambda *_args: events.append("warning"),
        ):
            dialog.on_parse_finished()

        self.assertEqual(events, ["progress_closed", "warning"])


if __name__ == '__main__':
    unittest.main()
