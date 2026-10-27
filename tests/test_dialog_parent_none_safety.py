import importlib
import sys
import types
import unittest
from contextlib import contextmanager, nullcontext

import pytest
from unittest.mock import patch


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get('parent')

    def parent(self):
        return self._parent

    def __getattr__(self, _name):
        def _method(*_args, **_kwargs):
            return None
        return _method


class _FakeDialog(_FakeWidget):
    pass


def _build_qt_stubs():
    qtcore = types.ModuleType('PyQt6.QtCore')
    qtcore.Qt = types.SimpleNamespace(
        ItemDataRole=types.SimpleNamespace(UserRole=0, DisplayRole=0, EditRole=2)
    )
    qtcore.QUrl = _FakeWidget
    qtcore.QDate = _FakeWidget

    qtgui = types.ModuleType('PyQt6.QtGui')
    qtgui.QDesktopServices = types.SimpleNamespace(openUrl=lambda *_args, **_kwargs: None)

    qtwidgets = types.ModuleType('PyQt6.QtWidgets')
    qtwidgets.QDialog = _FakeDialog
    qtwidgets.QApplication = type('QApplication', (), {'instance': staticmethod(lambda: None)})

    widget_names = [
        'QAbstractItemView', 'QGridLayout', 'QLabel', 'QLineEdit', 'QListWidget',
        'QListWidgetItem', 'QPushButton', 'QInputDialog', 'QMessageBox', 'QFileDialog',
        'QTableWidget', 'QTableWidgetItem', 'QTextBrowser', 'QVBoxLayout', 'QDateEdit',
        'QHBoxLayout', 'QWidget', 'QComboBox', 'QCheckBox'
    ]
    for name in widget_names:
        setattr(qtwidgets, name, _FakeWidget)

    def _module_getattr(_name):
        return _FakeWidget

    qtcore.__getattr__ = _module_getattr
    qtgui.__getattr__ = _module_getattr
    qtwidgets.__getattr__ = _module_getattr
    return qtcore, qtgui, qtwidgets


@contextmanager
def _qt_stubbed_imports():
    qtcore, qtgui, qtwidgets = _build_qt_stubs()
    fake_pandas = types.ModuleType('pandas')
    module_cache = sys.modules
    isolated_prefixes = ('metroliza.ui.', 'modules' + '.')
    preserved_modules = {
        name: module
        for name, module in module_cache.items()
        if name.startswith(isolated_prefixes)
    }
    package_attributes = {
        name: (module, tuple(vars(module).items()))
        for name, module in tuple(module_cache.items())
        if name in ('metroliza.ui', 'modules')
        or (name.startswith(isolated_prefixes) and '__path__' in vars(module))
    }
    missing = object()
    with patch.dict(
        sys.modules,
        {
            'PyQt6.QtCore': qtcore,
            'PyQt6.QtGui': qtgui,
            'PyQt6.QtWidgets': qtwidgets,
            'pandas': fake_pandas,
        },
        clear=False,
    ):
        try:
            yield
        finally:
            scoped_names = set(preserved_modules) | {
                name for name in module_cache if name.startswith(isolated_prefixes)
            }
            for package_name, (package, attributes) in package_attributes.items():
                children = {name.rpartition('.')[2] for name in scoped_names
                            if name.rpartition('.')[0] == package_name}
                children.update(name for name, value in tuple(vars(package).items())
                                if isinstance(value, types.ModuleType)
                                and value.__name__.startswith(isolated_prefixes))
                for child in children:
                    original = next((value for name, value in attributes if name == child), missing)
                    if original is missing:
                        vars(package).pop(child, None)
                    else:
                        setattr(package, child, original)
            for name in tuple(module_cache):
                if name.startswith(isolated_prefixes) and name not in preserved_modules:
                    module_cache.pop(name, None)
            module_cache.update(preserved_modules)


def _import_fresh(module_name):
    sys.modules.pop(module_name, None)
    canonical_by_legacy = {
        'modules.data_grouping': 'metroliza.ui.data_grouping',
        'modules.export_dialog': 'metroliza.ui.export_dialog',
        'modules.filter_dialog': 'metroliza.ui.filter_dialog',
        'modules.modify_db': 'metroliza.ui.modify_db',
        'modules.release_notes_dialog': 'metroliza.ui.release_notes_dialog',
    }
    canonical_name = canonical_by_legacy.get(module_name)
    if canonical_name is not None:
        sys.modules.pop(canonical_name, None)
    return importlib.import_module(module_name)


class TestDialogParentNoneSafety(unittest.TestCase):
    def test_data_grouping_constructor_with_none_parent(self):
        with _qt_stubbed_imports():
            DataGrouping = _import_fresh('modules.data_grouping').DataGrouping
            with patch.object(DataGrouping, 'setup_ui', return_value=None), patch.object(
                DataGrouping, 'read_data_to_df', return_value=None
            ), patch.object(DataGrouping, 'add_default_group', return_value=None), patch.object(
                DataGrouping, 'populate_list_widgets', return_value=None
            ), patch.object(
                DataGrouping, '_restore_saved_grouping_state', return_value=None
            ):
                DataGrouping(parent=None, db_file='')

    def test_export_dialog_constructor_with_none_parent(self):
        with _qt_stubbed_imports():
            _import_fresh('modules.filter_dialog')
            _import_fresh('modules.data_grouping')
            ExportDialog = _import_fresh('modules.export_dialog').ExportDialog
            with patch.object(ExportDialog, 'init_widgets', return_value=None), patch.object(
                ExportDialog, 'init_layout', return_value=None
            ), patch.object(ExportDialog, '_load_dialog_config', return_value={'selected_preset': 'fast_diagnostics'}):
                ExportDialog(parent=None, db_file='')

    def test_filter_dialog_constructor_with_none_parent(self):
        with _qt_stubbed_imports():
            FilterDialog = _import_fresh('modules.filter_dialog').FilterDialog
            with patch.object(FilterDialog, 'setup_ui', return_value=None):
                FilterDialog(parent=None, db_file='')

    def test_modify_db_constructor_with_none_parent(self):
        with _qt_stubbed_imports():
            ModifyDB = _import_fresh('modules.modify_db').ModifyDB
            with patch.object(ModifyDB, 'setup_ui', return_value=None):
                ModifyDB(parent=None, db_file='')

    def test_release_notes_dialog_constructor_with_none_parent(self):
        with _qt_stubbed_imports():
            ReleaseNotesDialog = _import_fresh('modules.release_notes_dialog').ReleaseNotesDialog
            ReleaseNotesDialog(parent=None, release_notes='<p>Release notes</p>')


if __name__ == '__main__':
    unittest.main()


@pytest.mark.parametrize('raises', [False, True])
@pytest.mark.parametrize('attribute_present', [False, True])
def test_stub_scope_restores_native_module_and_parent_identity(raises, attribute_present):
    from PyQt6.QtWidgets import QMessageBox

    package = importlib.import_module('metroliza.ui')
    canonical = importlib.import_module('metroliza.ui.modify_db')
    legacy_package = importlib.import_module('modules')
    legacy = importlib.import_module('modules.modify_db')
    assert canonical.QMessageBox is QMessageBox
    if not attribute_present:
        vars(package).pop('modify_db', None)
    added_name = 'metroliza.ui.__stub_scope_added__'
    assert '__stub_scope_added__' not in vars(package)
    try:
        with pytest.raises(RuntimeError, match='scope failure') if raises else nullcontext():
            with _qt_stubbed_imports():
                reloaded = _import_fresh('modules.modify_db')
                assert package.modify_db is reloaded
                added = types.ModuleType(added_name)
                sys.modules[added_name] = added
                package.__stub_scope_added__ = added
                if raises:
                    raise RuntimeError('scope failure')
        assert sys.modules['metroliza.ui.modify_db'] is canonical
        assert sys.modules['modules.modify_db'] is legacy
        assert legacy_package.modify_db is legacy
        assert canonical.QMessageBox is QMessageBox
        if attribute_present:
            assert package.modify_db is canonical
        else:
            assert 'modify_db' not in vars(package)
        assert '__stub_scope_added__' not in vars(package)
        assert added_name not in sys.modules
    finally:
        package.modify_db = canonical
