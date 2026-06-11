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
    sys.modules.pop('metroliza.ui.help_menu', None)
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
        self.assertIn('help_startup_and_license', self.help_menu.MANUAL_RELATIVE_PATHS)
        for key, path in self.help_menu.MANUAL_PATHS.items():
            with self.subTest(key=key):
                self.assertEqual(self.help_menu.manual_path(key), path)
                self.assertTrue(Path(path).exists(), f'Manual for {key} should exist: {path}')

    def test_manual_url_keys_point_to_github_markdown(self):
        for key, relative_path in self.help_menu.MANUAL_RELATIVE_PATHS.items():
            with self.subTest(key=key):
                expected = self.help_menu.github_blob_url(relative_path)
                self.assertEqual(self.help_menu.manual_url(key), expected)
                self.assertTrue(expected.startswith('https://github.com/hexafe/metroliza/blob/'))
                self.assertNotIn('file://', expected)
                self.assertNotIn(str(self.help_menu.REPO_ROOT), expected)

    def test_help_menu_manuals_are_discoverable_from_user_manual_hub(self):
        hub_text = Path("docs/user_manual/README.md").read_text(encoding="utf-8")

        for key, relative_path in self.help_menu.MANUAL_RELATIVE_PATHS.items():
            with self.subTest(key=key):
                manual_name = Path(relative_path).name
                self.assertIn(manual_name, hub_text)

    def test_docs_ref_defaults_to_release_constant(self):
        self.assertEqual(
            self.help_menu.GITHUB_RENDERED_DOCS_REF,
            self.help_menu.DEFAULT_RELEASE_DOCS_REF,
        )

    def test_docs_ref_can_be_overridden_by_environment(self):
        sys.modules.pop('modules.help_menu', None)
        sys.modules.pop('metroliza.ui.help_menu', None)
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
        sys.modules.pop('metroliza.ui.help_menu', None)
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

    def test_open_manual_opens_github_even_when_packaged_local_manual_is_missing(self):
        with patch.dict(
            self.help_menu.MANUAL_PATHS,
            {'parsing': Path('/tmp/definitely-missing-manual.md')},
            clear=False,
        ):
            with patch.object(self.help_menu.QMessageBox, 'warning') as warning_mock:
                with patch.object(self.help_menu.QDesktopServices, 'openUrl', return_value=True) as open_url_mock:
                    result = self.help_menu.open_manual(None, 'parsing')

        self.assertTrue(result)
        warning_mock.assert_not_called()
        opened_url = open_url_mock.call_args.args[0].toString()
        self.assertEqual(opened_url, self.help_menu.manual_url('parsing'))
        self.assertTrue(opened_url.startswith('https://github.com/hexafe/metroliza/blob/'))

    def test_open_manual_warns_when_browser_open_fails(self):
        with patch.object(self.help_menu.QMessageBox, 'warning') as warning_mock:
            with patch.object(self.help_menu.QDesktopServices, 'openUrl', return_value=False):
                result = self.help_menu.open_manual(None, 'help_startup_and_license')

        self.assertFalse(result)
        warning_mock.assert_called_once()
        self.assertEqual(warning_mock.call_args.args[1], 'Could not open manual')
        self.assertIn(
            self.help_menu.manual_url('help_startup_and_license'),
            warning_mock.call_args.args[2],
        )

    def test_open_manual_warns_for_unknown_manual_key(self):
        with patch.object(self.help_menu.QMessageBox, 'warning') as warning_mock:
            result = self.help_menu.open_manual(None, 'not-a-manual')

        self.assertFalse(result)
        warning_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
