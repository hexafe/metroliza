import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        return None


class _FakeDialog:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")

    def parent(self):
        return self._parent

    def setWindowTitle(self, *_args, **_kwargs):
        return None

    def setGeometry(self, *_args, **_kwargs):
        return None

    def setLayout(self, *_args, **_kwargs):
        return None

    def accept(self):
        return None


class _FakeLabel:
    def __init__(self, text=""):
        self._text = text

    def setToolTip(self, *_args, **_kwargs):
        return None

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text


class _FakeButton:
    def __init__(self, *_args, **_kwargs):
        self.clicked = _FakeSignal()
        self._enabled = True

    def setToolTip(self, *_args, **_kwargs):
        return None

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled


class _FakeGridLayout:
    def addWidget(self, *_args, **_kwargs):
        return None


def _install_qt_stubs():
    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    qtcore.pyqtSlot = lambda *args, **kwargs: (lambda fn: fn)
    qtwidgets.QDialog = _FakeDialog
    qtwidgets.QFileDialog = type(
        "QFileDialog",
        (),
        {
            "getExistingDirectory": staticmethod(lambda *_args, **_kwargs: ""),
            "getOpenFileName": staticmethod(lambda *_args, **_kwargs: ("", "")),
            "getSaveFileName": staticmethod(lambda *_args, **_kwargs: ("", "")),
        },
    )
    qtwidgets.QGridLayout = _FakeGridLayout
    qtwidgets.QLabel = _FakeLabel
    qtwidgets.QMessageBox = type(
        "QMessageBox",
        (),
        {
            "StandardButton": types.SimpleNamespace(Yes=1, No=2),
            "question": staticmethod(lambda *_args, **_kwargs: 2),
            "warning": staticmethod(lambda *_args, **_kwargs: None),
            "information": staticmethod(lambda *_args, **_kwargs: None),
        },
    )
    qtwidgets.QPushButton = _FakeButton
    pyqt6.QtCore = qtcore
    pyqt6.QtWidgets = qtwidgets
    return pyqt6, qtcore, qtwidgets


class TestParsingDialogParentNoneSafety(unittest.TestCase):
    def _import_module(self):
        pyqt6, qtcore, qtwidgets = _install_qt_stubs()
        parse_reports_thread = types.ModuleType("modules.parse_reports_thread")
        parse_reports_thread.ParseReportsThread = type("ParseReportsThread", (), {})
        worker_progress_dialog = types.ModuleType("modules.worker_progress_dialog")
        worker_progress_dialog.create_worker_progress_dialog = lambda *_args, **_kwargs: (None, None, None, None)
        with patch.dict(
            sys.modules,
            {
                "PyQt6": pyqt6,
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtWidgets": qtwidgets,
                "modules.parse_reports_thread": parse_reports_thread,
                "modules.worker_progress_dialog": worker_progress_dialog,
            },
            clear=False,
        ):
            sys.modules.pop("modules.parsing_dialog", None)
            return importlib.import_module("modules.parsing_dialog")

    def test_select_directory_updates_state_without_parent(self):
        module = self._import_module()
        dialog = module.ParsingDialog(parent=None, directory=None, db_file=None)

        with patch.object(module.QFileDialog, "getExistingDirectory", return_value="/tmp/reports"), \
                patch.object(dialog, "log_and_exit") as log_and_exit_mock:
            dialog.select_directory()

        self.assertEqual(dialog.directory, "/tmp/reports")
        self.assertEqual(dialog.directory_text_label.text(), "/tmp/reports")
        self.assertTrue(dialog.database_button.isEnabled())
        self.assertFalse(dialog.parse_button.isEnabled())
        log_and_exit_mock.assert_not_called()

    def test_select_database_updates_state_without_parent(self):
        module = self._import_module()
        dialog = module.ParsingDialog(parent=None, directory="/tmp/reports", db_file=None)

        with patch.object(module.QFileDialog, "getSaveFileName", return_value=("/tmp/output", "")), \
                patch.object(dialog, "log_and_exit") as log_and_exit_mock:
            dialog.select_database()

        self.assertEqual(dialog.db_file, "/tmp/output.db")
        self.assertEqual(dialog.database_text_label.text(), "/tmp/output.db")
        self.assertTrue(dialog.parse_button.isEnabled())
        log_and_exit_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
