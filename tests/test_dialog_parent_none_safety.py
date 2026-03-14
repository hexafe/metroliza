import importlib
import sys
import types
import unittest
from contextlib import contextmanager
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
    qtcore.Qt = types.SimpleNamespace(ItemDataRole=types.SimpleNamespace(UserRole=0))
    qtcore.QUrl = _FakeWidget
    qtcore.QDate = _FakeWidget

    qtgui = types.ModuleType('PyQt6.QtGui')
    qtgui.QDesktopServices = types.SimpleNamespace(openUrl=lambda *_args, **_kwargs: None)

    qtwidgets = types.ModuleType('PyQt6.QtWidgets')
    qtwidgets.QDialog = _FakeDialog

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
    with patch.dict(
        sys.modules,
        {
            'PyQt6.QtCore': qtcore,
            'PyQt6.QtGui': qtgui,
            'PyQt6.QtWidgets': qtwidgets,
        },
        clear=False,
    ):
        yield


def _import_fresh(module_name):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


class TestDialogParentNoneSafety(unittest.TestCase):
    def test_data_grouping_constructor_with_none_parent(self):
        with _qt_stubbed_imports():
            DataGrouping = _import_fresh('modules.data_grouping').DataGrouping
            with patch.object(DataGrouping, 'setup_ui', return_value=None), patch.object(
                DataGrouping, 'read_data_to_df', return_value=None
            ), patch.object(DataGrouping, 'add_default_group', return_value=None), patch.object(
                DataGrouping, 'populate_list_widgets', return_value=None
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
