import unittest
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import time

import pytest

from metroliza.parsing import report_parser_factory
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


def _attach_synthetic_review(dialog):
    from metroliza.parsing.preflight import ParsePreflightResult

    dialog._preflight_result = ParsePreflightResult(
        source_path=dialog.directory,
        database_path=dialog.db_file,
        metadata_parsing_mode=dialog._build_parse_request_fields()[0],
        files=(),
    )


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

    def _completion_feedback(self, **result_fields):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(**result_fields),
        )
        return dialog._build_parse_completion_feedback()

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
        _attach_synthetic_review(dialog)

        with patch(
            'metroliza.ui.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('metroliza.ui.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'light')
        self.assertFalse(captured['request'].run_background_metadata_enrichment)

    def test_loading_screen_binds_fast_then_enrich_to_import_plan(self):
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
        _attach_synthetic_review(dialog)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'light')
        self.assertTrue(captured['request'].run_background_metadata_enrichment)
        self.assertFalse(dialog._pending_modeless_metadata_enrichment)

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
        _attach_synthetic_review(dialog)

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
        _attach_synthetic_review(dialog)

        with patch(
            'modules.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('modules.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertEqual(captured['request'].metadata_parsing_mode, 'complete')
        self.assertFalse(captured['request'].run_background_metadata_enrichment)

    def test_reviewed_preflight_enables_import_and_is_attached_to_worker(self):
        from metroliza.parsing.preflight import (
            ParseFilePreflight,
            ParsePreflightResult,
            ParsePreflightStatus,
        )

        result = ParsePreflightResult(
            source_path='/tmp/reports',
            database_path='/tmp/reports.db',
            metadata_parsing_mode='light',
            files=(
                ParseFilePreflight(
                    display_name='report.pdf',
                    source_path='/tmp/reports/report.pdf',
                    status=ParsePreflightStatus.READY,
                    source_format='pdf',
                    fingerprint='sha256:abc',
                    parser_id='cmm',
                    confidence=90,
                    registry_generation_id=report_parser_factory.get_registry_snapshot().generation_id,
                ),
            ),
        )
        dialog = ParsingDialog(
            parent=None,
            directory='/tmp/reports',
            db_file='/tmp/reports.db',
        )
        dialog.on_preflight_completed(result)

        self.assertTrue(dialog.parse_button.isEnabled())
        self.assertTrue(dialog.review_scan_button.isEnabled())
        self.assertIn('1 ready', dialog.readiness_label.text())

        captured = {}

        class _FakeParseThread:
            def __init__(self, request):
                captured['thread'] = self
                self.preflight_result = request.preflight_result
                self.update_label = _Signal()
                self.update_progress = _Signal()
                self.error_occurred = _Signal()
                self.finished = _Signal()

            def start(self):
                captured['started'] = True

        with patch(
            'metroliza.ui.parsing_dialog.create_worker_progress_dialog',
            return_value=(_ProgressDialog(), _ProgressLabel(), _ProgressBar(), None),
        ), patch('metroliza.ui.parsing_dialog.ParseReportsThread', _FakeParseThread):
            dialog.show_loading_screen()

        self.assertTrue(captured['started'])
        self.assertIs(captured['thread'].preflight_result, result)

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
        message = warning_mock.call_args.args[2]
        self.assertIn("Completed and available in the destination: 2 report files", message)
        self.assertIn("1 report file could not be parsed", message)
        self.assertNotIn("2 of 3", message)

    def test_completion_keeps_historical_unsupported_with_changed_evidence(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=2,
                parsed_files=1,
                failed_files=0,
                preflight_unsupported_files=1,
                preflight_changed_files=1,
            ),
        )

        severity, title, message = dialog._build_parse_completion_feedback()

        self.assertIn("Import outcome:", message)
        self.assertIn("Completed and available in the destination: 1 report file", message)
        self.assertIn("Review snapshot:", message)
        self.assertIn("Unsupported during review: 1 report file", message)
        self.assertIn("Changed since review:", message)
        self.assertEqual((severity, title), ("warning", "Parsing completed with warnings"))
        self.assertLess(message.index("Import outcome:"), message.index("Review snapshot:"))
        self.assertLess(message.index("Review snapshot:"), message.index("Changed since review:"))

    def test_completion_keeps_historical_destination_match_with_changed_evidence(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=2,
                parsed_files=0,
                failed_files=0,
                preflight_duplicate_files=1,
                preflight_changed_files=1,
            ),
        )

        severity, title, message = dialog._build_parse_completion_feedback()

        self.assertIn("Review snapshot:", message)
        self.assertIn("Matched the destination during review: 1 report file", message)
        self.assertIn("Changed since review:", message)
        self.assertEqual((severity, title), ("warning", "No reports imported"))

    def test_completion_shows_repaired_destination_overlap_as_two_domains(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=1,
                parsed_files=1,
                imported_files=1,
                already_present_files=0,
                failed_files=0,
                preflight_duplicate_files=1,
                preflight_changed_files=0,
            ),
        )

        severity, title, message = dialog._build_parse_completion_feedback()

        self.assertIn("Saved: 1 report file", message)
        self.assertIn("Matched the destination during review: 1 report file", message)
        self.assertNotIn("omission", message.lower())
        self.assertNotIn("already imported", message.lower())
        self.assertNotIn("of 1", message.lower())
        self.assertEqual((severity, title), ("info", "Import successful"))

    def test_completion_shows_unchanged_destination_overlap_without_double_counting(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=1,
                parsed_files=1,
                imported_files=0,
                already_present_files=1,
                failed_files=0,
                preflight_duplicate_files=1,
            ),
        )

        severity, title, message = dialog._build_parse_completion_feedback()

        self.assertIn("Already present at import time: 1 report file", message)
        self.assertIn("Matched the destination during review: 1 report file", message)
        self.assertIn("Nothing new was saved", message)
        self.assertNotIn("of 1", message.lower())
        self.assertEqual((severity, title), ("info", "No new reports saved"))

    def test_completion_result_contract_matrix(self):
        cases = (
            (
                "legacy success",
                dict(total_files=1, parsed_files=1, failed_files=0),
                ("info", "Parsing successful"),
                ("Completed and available in the destination: 1 report file",),
                ("Saved:", "Already present at import time:"),
            ),
            (
                "typed success",
                dict(
                    total_files=1,
                    parsed_files=1,
                    imported_files=1,
                    already_present_files=0,
                ),
                ("info", "Import successful"),
                ("Saved: 1 report file",),
                ("Completed and available in the destination",),
            ),
            (
                "partial failure",
                dict(
                    total_files=2,
                    parsed_files=1,
                    imported_files=1,
                    already_present_files=0,
                    failed_files=1,
                ),
                ("warning", "Parsing completed with warnings"),
                ("Saved: 1 report file", "Failed: 1 report file could not be parsed"),
                (),
            ),
            (
                "partial changed",
                dict(
                    total_files=2,
                    parsed_files=1,
                    imported_files=1,
                    already_present_files=0,
                    preflight_changed_files=1,
                ),
                ("warning", "Parsing completed with warnings"),
                ("Saved: 1 report file", "Changed since review:"),
                (),
            ),
            (
                "all historical attention categories",
                dict(
                    total_files=4,
                    parsed_files=0,
                    preflight_duplicate_files=1,
                    preflight_unsupported_files=1,
                    preflight_ambiguous_files=1,
                    preflight_unreadable_files=1,
                ),
                ("warning", "No compatible reports parsed"),
                (
                    "Matched the destination during review: 1 report file",
                    "Unsupported during review: 1 report file",
                    "Ambiguous during review: 1 report file",
                    "Unreadable during review: 1 report file",
                ),
                ("Already imported",),
            ),
            (
                "all already present",
                dict(
                    total_files=2,
                    parsed_files=2,
                    imported_files=0,
                    already_present_files=2,
                ),
                ("info", "No new reports saved"),
                (
                    "Already present at import time: 2 report files",
                    "Nothing new was saved",
                ),
                ("Completed and available in the destination",),
            ),
            (
                "cancelled before completion",
                dict(
                    total_files=2,
                    parsed_files=0,
                    selected_files=2,
                    imported_files=0,
                    already_present_files=0,
                    cancelled_files=2,
                ),
                ("warning", "Import cancelled"),
                ("Cancelled: 2 report files", "Nothing new was saved"),
                (),
            ),
            (
                "partial cancellation",
                dict(
                    total_files=2,
                    parsed_files=1,
                    selected_files=2,
                    imported_files=1,
                    already_present_files=0,
                    cancelled_files=1,
                ),
                ("warning", "Parsing completed with warnings"),
                ("Saved: 1 report file", "Cancelled: 1 report file"),
                (),
            ),
            (
                "reviewed but none selected",
                dict(
                    total_files=2,
                    parsed_files=0,
                    selected_files=0,
                    imported_files=0,
                    already_present_files=0,
                ),
                ("info", "No reports selected"),
                ("none were selected or approved for import", "Nothing new was saved"),
                (),
            ),
            (
                "intentional empty plan",
                dict(
                    total_files=2,
                    parsed_files=0,
                    selected_files=0,
                    imported_files=0,
                    already_present_files=0,
                    intentionally_excluded_files=2,
                ),
                ("info", "No reports selected"),
                ("Intentionally not selected: 2 report files", "Nothing new was saved"),
                ("Failed",),
            ),
            (
                "mixed typed outcomes",
                dict(
                    total_files=3,
                    parsed_files=2,
                    selected_files=2,
                    imported_files=1,
                    already_present_files=1,
                    intentionally_excluded_files=1,
                ),
                ("info", "Import successful"),
                (
                    "Saved: 1 report file",
                    "Already present at import time: 1 report file",
                    "Intentionally not selected: 1 report file",
                ),
                (),
            ),
            (
                "all failed",
                dict(
                    total_files=2,
                    parsed_files=0,
                    selected_files=2,
                    imported_files=0,
                    already_present_files=0,
                    failed_files=2,
                ),
                ("warning", "No reports imported"),
                ("Failed: 2 report files could not be parsed", "Nothing new was saved"),
                (),
            ),
            (
                "typed zeros do not use legacy parsed count",
                dict(
                    total_files=2,
                    parsed_files=2,
                    selected_files=2,
                    imported_files=0,
                    already_present_files=0,
                ),
                ("info", "No new reports saved"),
                ("Nothing new was saved",),
                ("Completed and available in the destination", "Saved:"),
            ),
            (
                "runtime skip and historical unsupported stay separate",
                dict(
                    total_files=2,
                    parsed_files=0,
                    skipped_files=1,
                    preflight_unsupported_files=1,
                ),
                ("warning", "No compatible reports parsed"),
                (
                    "Runtime-skipped. Unsupported based on file contents and skipped: 1 report file",
                    "Unsupported during review: 1 report file",
                ),
                ("Unsupported during review: 2",),
            ),
            (
                "overlapping historical and changed evidence",
                dict(
                    total_files=2,
                    parsed_files=1,
                    imported_files=1,
                    already_present_files=0,
                    preflight_duplicate_files=1,
                    preflight_unsupported_files=1,
                    preflight_ambiguous_files=1,
                    preflight_unreadable_files=1,
                    preflight_changed_files=1,
                ),
                ("warning", "Parsing completed with warnings"),
                (
                    "Saved: 1 report file",
                    "Matched the destination during review: 1 report file",
                    "Unsupported during review: 1 report file",
                    "Ambiguous during review: 1 report file",
                    "Unreadable during review: 1 report file",
                    "Changed since review:",
                ),
                (),
            ),
        )

        for name, fields, expected_heading, expected, forbidden in cases:
            with self.subTest(name=name):
                severity, title, message = self._completion_feedback(**fields)
                self.assertEqual((severity, title), expected_heading)
                for fragment in expected:
                    self.assertIn(fragment, message)
                for fragment in forbidden:
                    self.assertNotIn(fragment, message)
                self.assertNotRegex(message, r"\b\d+ of \d+\b")

    def test_scan_summary_labels_destination_matches_as_review_snapshot(self):
        from metroliza.parsing.preflight import ParsePreflightStatus

        counts = {status: 0 for status in ParsePreflightStatus}
        counts[ParsePreflightStatus.READY] = 1
        counts[ParsePreflightStatus.DUPLICATE] = 1

        message = ParsingDialog._preflight_summary_text(
            SimpleNamespace(status_counts=counts),
        )

        self.assertIn("1 matched destination during review", message)
        self.assertNotIn("already imported", message.lower())

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

    def test_legacy_result_without_cancelled_count_keeps_cancellation_status(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.loading_dialog = _ProgressDialog()
        dialog.parsing_canceled = True
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=2,
                parsed_files=1,
                failed_files=0,
            ),
        )

        with patch('modules.parsing_dialog.QMessageBox.information') as information_mock:
            with patch('modules.parsing_dialog.QMessageBox.warning') as warning_mock:
                dialog.on_parse_finished()

        warning_mock.assert_not_called()
        information_mock.assert_called_once_with(
            dialog,
            "Parsing canceled",
            "Parsing has been canceled",
        )
        self.assertFalse(dialog.parsing_canceled)

    def test_partial_cancellation_uses_truthful_result_summary(self):
        dialog = ParsingDialog(parent=None, directory='/tmp/reports', db_file='/tmp/reports.db')
        dialog.loading_dialog = _ProgressDialog()
        dialog.parsing_canceled = True
        dialog.parse_thread = SimpleNamespace(
            last_parse_result=SimpleNamespace(
                total_files=2,
                parsed_files=1,
                selected_files=2,
                imported_files=1,
                already_present_files=0,
                cancelled_files=1,
            ),
        )

        with patch('modules.parsing_dialog.QMessageBox.information') as information_mock:
            with patch('modules.parsing_dialog.QMessageBox.warning') as warning_mock:
                dialog.on_parse_finished()

        information_mock.assert_not_called()
        warning_mock.assert_called_once()
        self.assertEqual(warning_mock.call_args.args[1], "Parsing completed with warnings")
        self.assertIn("Saved: 1 report file", warning_mock.call_args.args[2])
        self.assertIn("Cancelled: 1 report file", warning_mock.call_args.args[2])
        self.assertFalse(dialog.parsing_canceled)

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


@pytest.mark.parametrize("source_copy", [False, True], ids=["singleton", "excluded-copy-first"])
@pytest.mark.parametrize("accepted", [False, True], ids=["incomplete", "accepted"])
def test_duplicate_only_real_click_dispatches_atomic_verification(tmp_path, monkeypatch, accepted, source_copy, request):
    # The complete suite shares Qt application/window state. Exercise the real
    # modal click/worker flow in a fresh Qt process, as in an application launch.
    import os
    import subprocess
    import sys

    if os.environ.get("METROLIZA_ATOMIC_UI_TEST_CHILD") != "1":
        environment = dict(os.environ, METROLIZA_ATOMIC_UI_TEST_CHILD="1", QT_QPA_PLATFORM="offscreen")
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", request.node.nodeid, "-q"],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return

    from PyQt6.QtTest import QTest
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ParsePreflightService, ParsePreflightStatus
    from metroliza.reports.report_repository import ReportImportDisposition, ReportRepository
    from metroliza.ui.parsing_dialog import ParsingDialog

    app = QApplication.instance() or QApplication([])
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "synthetic.pdf"
    shutil.copyfile(Path(__file__).parent / "fixtures/pdf/cmm_smoke_fixture.pdf", source)
    if source_copy:
        shutil.copyfile(source, source_dir / "z-copy.pdf")
    database = tmp_path / "reports.sqlite3"
    repository = ReportRepository(str(database))
    repository.replace_existing_report(
        source_path=source,
        parser_id="cmm_pdf_header_box", parser_version="1.1.0",
        template_family="synthetic", parse_status="parsed" if accepted else "failed",
        metadata={"reference": "accepted", "metadata_json": {}},
        candidates=(), warnings=(),
        measurements=({"row_order": 1, "header": "accepted", "status_code": "ok"},)
        if accepted else (),
        metadata_version="synthetic-v1",
    )

    def graph():
        with closing(sqlite3.connect(database)) as connection:
            tables = ("source_files", "source_file_locations", "parsed_reports", "report_metadata",
                      "report_measurements", "report_metadata_candidates", "report_metadata_warnings",
                      "report_parse_state")
            return {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}

    workers, outcomes, feedback = [], [], []
    original_import = ReportRepository.import_report_if_absent

    def record_import(self, **kwargs):
        result = original_import(self, **kwargs)
        outcomes.append(result)
        return result

    def create_thread(request):
        worker = ParseReportsThread(request)
        discover = worker.get_list_of_reports
        worker.get_list_of_reports = lambda: sorted(discover(), reverse=True)
        workers.append(worker)
        return worker

    monkeypatch.setattr(ReportRepository, "import_report_if_absent", record_import)
    monkeypatch.setattr("metroliza.ui.parsing_dialog.ParseReportsThread", create_thread)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: feedback.append(args[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: feedback.append(args[2]))
    dialog = ParsingDialog(directory=str(source_dir), db_file=str(database))
    dialog.show()
    snapshots = []
    try:
        for attempt in range(2):
            review = ParsePreflightService().scan_source(
                source_path=source_dir, database_path=database, metadata_parsing_mode="light"
            )
            assert len(review.files) == 1 + source_copy
            assert review.count(ParsePreflightStatus.READY) == 0
            assert review.count(ParsePreflightStatus.DUPLICATE) == 1 + source_copy
            dialog._preflight_result = review
            dialog._sync_readiness_state()
            before = graph()
            assert dialog.parse_button.isEnabled()
            QTest.mouseClick(dialog.parse_button, Qt.MouseButton.LeftButton)
            assert len(workers) == attempt + 1, feedback
            deadline = time.monotonic() + 15
            while (len(feedback) <= attempt or workers[-1].isRunning()) and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(5)
            assert len(workers) == attempt + 1
            assert not workers[-1].isRunning()
            assert len(feedback) == attempt + 1
            result = workers[-1].last_parse_result
            assert result.parsed_files == result.imported_files + result.already_present_files == 1
            assert result.preflight_duplicate_files == 1 + source_copy
            assert "Import outcome" in feedback[-1]
            assert "Review snapshot" in feedback[-1]
            if accepted or attempt:
                assert outcomes[-1] is ReportImportDisposition.ALREADY_PRESENT
                assert graph() == before
                assert "Already present" in feedback[-1]
            else:
                assert outcomes[-1] is ReportImportDisposition.IMPORTED
                assert graph()["parsed_reports"][0][6] in ("parsed", "parsed_with_warnings")
                assert graph()["report_measurements"]
                assert "Saved: 1 report file" in feedback[-1]
            assert {row[4] for row in graph()["source_file_locations"]} == {source.name}
            snapshots.append(graph())
        assert snapshots[0] == snapshots[1]
    finally:
        for worker in workers:
            worker.wait(15000)
        dialog.close()


@pytest.mark.parametrize("case,expected", [
    ("ready", True), ("destination", True), ("source-copy", False),
    ("unsupported", False), ("ambiguous", False), ("unreadable", False),
    ("cancelled", False), ("stale-source", False), ("stale-database", False),
    ("stale-mode", False), ("stale-generation", False), ("no-generation", False),
    ("no-parser", False), ("no-fingerprint", False),
    ("no-source", False), ("no-database", False),
])
def test_ui_worker_share_review_eligibility(tmp_path, monkeypatch, case, expected):
    from dataclasses import replace
    from metroliza.parsing.parse_reports_thread import ParseReportsThread
    from metroliza.parsing.preflight import ParsePreflightService, ParsePreflightStatus
    from metroliza.shared.parse_contracts import ParseRequest
    from metroliza.ui.parsing_dialog import ParsingDialog

    app = QApplication.instance() or QApplication([])
    source = tmp_path / "synthetic.pdf"
    shutil.copyfile(Path(__file__).parent / "fixtures/pdf/cmm_smoke_fixture.pdf", source)
    database = tmp_path / "new.sqlite3"
    review = ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light"
    )
    item = review.files[0]
    assert item.status is ParsePreflightStatus.READY
    item_changes = {
        "destination": {"status": ParsePreflightStatus.DUPLICATE},
        "source-copy": {"status": ParsePreflightStatus.DUPLICATE,
                        "reason_codes": ("duplicate_in_selected_source",)},
        "unsupported": {"status": ParsePreflightStatus.UNSUPPORTED},
        "ambiguous": {"status": ParsePreflightStatus.AMBIGUOUS},
        "unreadable": {"status": ParsePreflightStatus.UNREADABLE},
        "stale-generation": {"registry_generation_id": item.registry_generation_id - 1},
        "no-generation": {"registry_generation_id": None},
        "no-parser": {"parser_id": None}, "no-fingerprint": {"fingerprint": None},
    }
    item = replace(item, **item_changes.get(case, {}))
    review = replace(review, files=(item,))
    review_changes = {
        "cancelled": {"cancelled": True}, "stale-source": {"source_path": str(tmp_path / "other")},
        "stale-database": {"database_path": str(tmp_path / "other.db")},
        "stale-mode": {"metadata_parsing_mode": "complete"},
    }
    review = replace(review, **review_changes.get(case, {}))
    dialog = ParsingDialog(directory=str(source), db_file=str(database))
    worker = ParseReportsThread(ParseRequest(
        source_directory=str(source), db_file=str(database), metadata_parsing_mode="light"
    ))
    if case == "no-source":
        dialog.directory = worker.directory = ""
    if case == "no-database":
        dialog.db_file = worker.db_file = ""
    dialog._preflight_result = review
    try:
        dialog._sync_readiness_state()
        assert dialog.parse_button.isEnabled() is expected
        if case in {
            "cancelled", "stale-source", "stale-database", "stale-mode",
            "stale-generation", "no-generation", "no-parser", "no-fingerprint",
            "no-source", "no-database",
        }:
            with pytest.raises(ValueError):
                worker.preflight_result = review
                worker._filter_reports_for_preflight([source])
            approved = []
        else:
            worker.preflight_result = review
            approved, _changed = worker._filter_reports_for_preflight([source])
        assert approved == ([source] if expected else [])
        assert review.files == (item,)
        assert not database.exists()
        if not expected:
            starts = []
            monkeypatch.setattr("metroliza.ui.parsing_dialog.ParseReportsThread", starts.append)
            dialog.parse_button.click()
            dialog._import_reviewed_reports()  # Recheck the dispatch seam, too.
            app.processEvents()
            assert starts == []
            assert "No eligible reviewed reports" in dialog.parse_button.toolTip()
        else:
            assert "1 eligible for import / verification" in dialog.readiness_label.text()
    finally:
        dialog.close()
