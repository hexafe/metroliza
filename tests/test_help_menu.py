import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class _FakeAction:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.triggered = types.SimpleNamespace(connect=lambda *_args, **_kwargs: None)


class _FakeMenu:
    def __init__(self):
        self.actions = []

    def addAction(self, action):
        self.actions.append(action)


class _FakeMenuBar:
    def __init__(self, *_args, **_kwargs):
        self.menus = []

    def addMenu(self, _title):
        menu = _FakeMenu()
        self.menus.append(menu)
        return menu


class _FakeQUrl:
    def __init__(self, url=''):
        self._url = url

    @classmethod
    def fromLocalFile(cls, path):
        return cls(path)

    def toLocalFile(self):
        return self._url

    def toString(self):
        return self._url


class _FakeMessageBox:
    @staticmethod
    def warning(*_args, **_kwargs):
        return None


def _import_help_menu_with_stubs():
    sys.modules.pop('modules.help_menu', None)
    qtcore = types.ModuleType('PyQt6.QtCore')
    qtcore.QUrl = _FakeQUrl
    qtgui = types.ModuleType('PyQt6.QtGui')
    qtgui.QAction = _FakeAction
    qtgui.QDesktopServices = types.SimpleNamespace(openUrl=lambda *_args, **_kwargs: True)
    qtwidgets = types.ModuleType('PyQt6.QtWidgets')
    qtwidgets.QMenuBar = _FakeMenuBar
    qtwidgets.QMessageBox = _FakeMessageBox
    with patch.dict(sys.modules, {'PyQt6.QtCore': qtcore, 'PyQt6.QtGui': qtgui, 'PyQt6.QtWidgets': qtwidgets}):
        return importlib.import_module('modules.help_menu')


class TestHelpMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_menu = _import_help_menu_with_stubs()

    def test_manual_path_keys_point_to_existing_manuals(self):
        for key, path in self.help_menu.MANUAL_PATHS.items():
            with self.subTest(key=key):
                self.assertEqual(self.help_menu.manual_path(key), path)
                self.assertTrue(Path(path).exists(), f'Manual for {key} should exist: {path}')

    def test_manual_url_keys_point_to_github_markdown(self):
        for key, path in self.help_menu.MANUAL_PATHS.items():
            with self.subTest(key=key):
                expected = (
                    'https://github.com/hexafe/metroliza/blob/main/'
                    f'{path.relative_to(self.help_menu.REPO_ROOT).as_posix()}'
                )
                self.assertEqual(self.help_menu.manual_url(key), expected)

    def test_open_manual_opens_github_manual_url(self):
        with patch.object(self.help_menu.QDesktopServices, 'openUrl', return_value=True) as open_url_mock:
            result = self.help_menu.open_manual(None, 'parsing')

        self.assertTrue(result)
        open_url_mock.assert_called_once()
        opened_url = open_url_mock.call_args.args[0]
        self.assertEqual(opened_url.toString(), self.help_menu.manual_url('parsing'))

    def test_open_manual_warns_when_manual_missing(self):
        with patch.object(self.help_menu, 'manual_path', return_value=Path('/tmp/definitely-missing-manual.md')):
            with patch.object(self.help_menu.QMessageBox, 'warning') as warning_mock:
                result = self.help_menu.open_manual(None, 'parsing')

        self.assertFalse(result)
        warning_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
