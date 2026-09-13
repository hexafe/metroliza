"""The compatibility Parsing dialog works without a main-window parent."""

from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

from metroliza.ui.parsing_dialog import ParsingDialog


@pytest.fixture
def dialog():
    app = QApplication.instance() or QApplication([])
    widget = ParsingDialog(parent=None)
    yield widget
    widget.close()
    app.processEvents()


def test_select_directory_updates_state_without_parent(dialog):
    with patch('metroliza.ui.parsing_dialog.QFileDialog.getExistingDirectory', return_value='/tmp/reports'), \
            patch.object(dialog, 'log_and_exit') as errors:
        dialog.select_directory()
    assert dialog.directory == '/tmp/reports'
    assert dialog.directory_text_label.text() == '/tmp/reports'
    assert dialog.database_button.isEnabled()
    assert not dialog.parse_button.isEnabled()
    errors.assert_not_called()


def test_select_database_updates_state_without_parent(dialog):
    dialog._set_parse_source('/tmp/reports')
    with patch('metroliza.ui.parsing_dialog.QFileDialog.getSaveFileName', return_value=('/tmp/output', '')), \
            patch.object(dialog, 'log_and_exit') as errors:
        dialog.select_database()
    assert dialog.db_file == '/tmp/output.db'
    assert dialog.database_text_label.text() == '/tmp/output.db'
    assert dialog.scan_button.isEnabled()
    assert not dialog.parse_button.isEnabled()
    assert 'review' in dialog.readiness_label.text().lower()
    errors.assert_not_called()
