import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get("parent")

    def setAlignment(self, *_args, **_kwargs):
        return None

    def setOpenExternalLinks(self, *_args, **_kwargs):
        return None

    def setCursor(self, *_args, **_kwargs):
        return None

    def setStyleSheet(self, *_args, **_kwargs):
        return None


class _FakeDialog(_FakeWidget):
    def setWindowTitle(self, *_args, **_kwargs):
        return None

    def setLayout(self, *_args, **_kwargs):
        return None

    def closeEvent(self, *_args, **_kwargs):
        return None


class _FakeLabel(_FakeWidget):
    def setMovie(self, movie):
        self.movie = movie


class _FakeVBoxLayout:
    def setAlignment(self, *_args, **_kwargs):
        return None

    def addWidget(self, *_args, **_kwargs):
        return None


class _FakeQTemporaryFile:
    def __init__(self):
        self._auto_remove = True
        self._path = tempfile.mkstemp(prefix="about_window_test_")[1]
        self._handle = None

    def setAutoRemove(self, enabled):
        self._auto_remove = enabled

    def open(self):
        self._handle = open(self._path, "wb")
        return True

    def write(self, data):
        self._handle.write(data)

    def close(self):
        if self._handle:
            self._handle.close()
            self._handle = None
        if self._auto_remove and os.path.exists(self._path):
            os.remove(self._path)

    def fileName(self):
        return self._path


class _FakeQMovie:
    def __init__(self, source_path):
        self.source_path = source_path

    def setScaledSize(self, *_args, **_kwargs):
        return None

    def start(self):
        return None

    def isValid(self):
        return bool(self.source_path) and os.path.exists(self.source_path)


def _install_qt_stubs():
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QSize = lambda *_args, **_kwargs: None
    qtcore.QTemporaryFile = _FakeQTemporaryFile
    qtcore.Qt = types.SimpleNamespace(
        AlignmentFlag=types.SimpleNamespace(AlignCenter=0, AlignHCenter=1),
        CursorShape=types.SimpleNamespace(PointingHandCursor=0),
    )
    qtcore.QUrl = lambda value: value

    qtgui = types.ModuleType("PyQt6.QtGui")
    qtgui.QMovie = _FakeQMovie
    qtgui.QDesktopServices = types.SimpleNamespace(openUrl=lambda *_args, **_kwargs: None)
    qtgui.QCursor = _FakeWidget

    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtwidgets.QDialog = _FakeDialog
    qtwidgets.QLabel = _FakeLabel
    qtwidgets.QVBoxLayout = _FakeVBoxLayout

    return qtcore, qtgui, qtwidgets


class TestAboutWindowGifLifetime(unittest.TestCase):
    def test_gif_file_persists_while_dialog_active_and_movie_is_valid(self):
        qtcore, qtgui, qtwidgets = _install_qt_stubs()
        with patch.dict(
            sys.modules,
            {
                "PyQt6.QtCore": qtcore,
                "PyQt6.QtGui": qtgui,
                "PyQt6.QtWidgets": qtwidgets,
            },
            clear=False,
        ):
            sys.modules.pop("modules.AboutWindow", None)
            about_module = importlib.import_module("modules.AboutWindow")
            dialog = about_module.AboutWindow()

            gif_path = dialog._gif_temp_file_path
            self.assertTrue(os.path.exists(gif_path))
            self.assertTrue(dialog.gif.isValid())

            dialog.closeEvent(None)
            self.assertFalse(os.path.exists(gif_path))


if __name__ == "__main__":
    unittest.main()
