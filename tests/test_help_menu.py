import importlib
import os
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
                expected = self.help_menu.github_blob_url(path.relative_to(self.help_menu.REPO_ROOT))
                self.assertEqual(self.help_menu.manual_url(key), expected)
                self.assertTrue(expected.startswith('https://github.com/hexafe/metroliza/blob/'))
                self.assertNotIn('file://', expected)
                self.assertNotIn(str(self.help_menu.REPO_ROOT), expected)

    def test_docs_ref_defaults_to_release_constant(self):
        self.assertEqual(
            self.help_menu.GITHUB_RENDERED_DOCS_REF,
            self.help_menu.DEFAULT_RELEASE_DOCS_REF,
        )

    def test_docs_ref_can_be_overridden_by_environment(self):
        sys.modules.pop('modules.help_menu', None)
        qtcore = types.ModuleType('PyQt6.QtCore')
        qtcore.QUrl = _FakeQUrl
        qtgui = types.ModuleType('PyQt6.QtGui')
        qtgui.QAction = _FakeAction
        qtgui.QDesktopServices = types.SimpleNamespace(openUrl=lambda *_args, **_kwargs: True)
        qtwidgets = types.ModuleType('PyQt6.QtWidgets')
        qtwidgets.QMenuBar = _FakeMenuBar
        qtwidgets.QMessageBox = _FakeMessageBox

        with patch.dict(os.environ, {'METROLIZA_RELEASE_DOCS_REF': 'release/2026.05-rc1'}, clear=False):
            with patch.dict(sys.modules, {'PyQt6.QtCore': qtcore, 'PyQt6.QtGui': qtgui, 'PyQt6.QtWidgets': qtwidgets}):
                overridden_module = importlib.import_module('modules.help_menu')

        self.assertEqual(overridden_module.GITHUB_RENDERED_DOCS_REF, 'release/2026.05-rc1')
        self.assertIn('/blob/release/2026.05-rc1/', overridden_module.manual_url('parsing'))

    def test_github_url_helper_imports_without_pyqt_runtime(self):
        sys.modules.pop('modules.help_menu', None)
        real_import = __import__

        def _raise_for_pyqt(name, *args, **kwargs):
            if name.startswith('PyQt6'):
                raise ImportError('simulated missing Qt runtime')
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=_raise_for_pyqt):
            fallback_module = importlib.import_module('modules.help_menu')

        self.assertEqual(
            fallback_module.github_blob_url('docs/user_manual/main_window.md'),
            (
                'https://github.com/hexafe/metroliza/blob/'
                f'{fallback_module.DEFAULT_RELEASE_DOCS_REF}/docs/user_manual/main_window.md'
            ),
        )
        self.assertFalse(fallback_module.open_manual(None, 'main_window'))

    def test_open_manual_opens_github_manual_url(self):
        with patch.object(self.help_menu.QDesktopServices, 'openUrl', return_value=True) as open_url_mock:
            result = self.help_menu.open_manual(None, 'parsing')

        self.assertTrue(result)
        open_url_mock.assert_called_once()
        opened_url = open_url_mock.call_args.args[0]
        self.assertEqual(opened_url.toString(), self.help_menu.manual_url('parsing'))
        self.assertTrue(opened_url.toString().startswith('https://github.com/hexafe/metroliza/blob/'))
        self.assertNotIn('file://', opened_url.toString())

    def test_open_manual_warns_when_manual_missing(self):
        with patch.object(self.help_menu, 'manual_path', return_value=Path('/tmp/definitely-missing-manual.md')):
            with patch.object(self.help_menu.QMessageBox, 'warning') as warning_mock:
                result = self.help_menu.open_manual(None, 'parsing')

        self.assertFalse(result)
        warning_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
