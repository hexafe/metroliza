import importlib
import sys
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = args[0] if args else ""
        self.text_interaction_flags = None

    def setMovie(self, movie):
        self.movie = movie

    def setTextInteractionFlags(self, flags):
        self.text_interaction_flags = flags


class _FakeVBoxLayout:
    def __init__(self, *_args, **_kwargs):
        self.widgets = []

    def setAlignment(self, *_args, **_kwargs):
        return None

    def addWidget(self, widget, *_args, **_kwargs):
        self.widgets.append(widget)
        return None


class _FakeQBuffer:
    def __init__(self, *_args, **_kwargs):
        self.data = b""
        self.opened = False
        self.closed = False

    def setData(self, data):
        self.data = bytes(data)

    def open(self, *_args, **_kwargs):
        self.opened = True
        return True

    def close(self):
        self.closed = True


class _FakeQMovie:
    def __init__(self, source, *_args):
        self.source = source
        self.stopped = False

    def setScaledSize(self, *_args, **_kwargs):
        return None

    def start(self):
        return None

    def stop(self):
        self.stopped = True

    def isValid(self):
        return bool(getattr(self.source, "data", b"")) and getattr(self.source, "opened", False)


def _install_qt_stubs():
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QByteArray = bytes
    qtcore.QBuffer = _FakeQBuffer
    qtcore.QIODevice = types.SimpleNamespace(
        OpenModeFlag=types.SimpleNamespace(ReadOnly=0),
    )
    qtcore.QSize = lambda *_args, **_kwargs: None
    qtcore.Qt = types.SimpleNamespace(
        AlignmentFlag=types.SimpleNamespace(AlignCenter=0, AlignHCenter=1),
        CursorShape=types.SimpleNamespace(PointingHandCursor=0),
        TextInteractionFlag=types.SimpleNamespace(
            TextSelectableByMouse=1,
            TextSelectableByKeyboard=2,
        ),
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
    def test_gif_buffer_persists_while_dialog_active_and_movie_is_valid(self):
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
            sys.modules.pop("modules.about_window", None)
            about_module = importlib.import_module("modules.about_window")
            dialog = about_module.AboutWindow()

            self.assertIsNotNone(dialog._gif_buffer)
            self.assertTrue(dialog._gif_buffer.opened)
            self.assertTrue(dialog.gif.isValid())

            dialog.closeEvent(None)
            self.assertIsNone(dialog._gif_buffer)
            self.assertTrue(dialog.gif.stopped)

    def test_close_event_detaches_movie_from_label_before_closing_buffer(self):
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
            sys.modules.pop("modules.about_window", None)
            about_module = importlib.import_module("modules.about_window")
            dialog = about_module.AboutWindow()

            gif_buffer = dialog._gif_buffer
            dialog.closeEvent(None)

            self.assertTrue(gif_buffer.closed)
            self.assertIsNone(dialog._gif_label.movie)

    def test_about_window_keeps_compact_metadata_only(self):
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
            sys.modules.pop("modules.about_window", None)
            about_module = importlib.import_module("modules.about_window")
            dialog = about_module.AboutWindow(days_until_expiration=7)

            text = "\n".join(getattr(widget, "text", "") for widget in dialog.layout.widgets)
            self.assertIn(about_module.VersionDate.VERSION_LABEL, text)
            self.assertIn("Grzegorz Ozimek", text)
            self.assertIn(about_module.SUPPORT_URL, text)
            self.assertIn("GitHub:", text)
            self.assertNotIn("License expiration", text)
            self.assertNotIn("Support/build info", text)
            self.assertNotIn("Manual:", text)
            self.assertNotIn("Internal version:", text)
            self.assertFalse(hasattr(dialog, "support_info_label"))

if __name__ == "__main__":
    unittest.main()
