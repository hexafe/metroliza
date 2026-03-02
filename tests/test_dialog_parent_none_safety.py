import sys
import types
import unittest
from unittest.mock import patch


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._parent = args[0] if args else kwargs.get('parent')

    def parent(self):
        return self._parent

    def __getattr__(self, _name):
        def _method(*args, **kwargs):
            return None
        return _method


class _FakeDialog(_FakeWidget):
    pass


def _install_qt_stubs():
    qtcore = types.ModuleType('PyQt6.QtCore')
    qtcore.Qt = types.SimpleNamespace(ItemDataRole=types.SimpleNamespace(UserRole=0))
    qtcore.QUrl = object
    qtcore.QDate = object

    qtgui = types.ModuleType('PyQt6.QtGui')
    qtgui.QDesktopServices = types.SimpleNamespace(openUrl=lambda *args, **kwargs: None)

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
    sys.modules.setdefault('PyQt6.QtCore', qtcore)
    sys.modules.setdefault('PyQt6.QtGui', qtgui)
    sys.modules.setdefault('PyQt6.QtWidgets', qtwidgets)


_install_qt_stubs()


class TestDialogParentNoneSafety(unittest.TestCase):
    def test_data_grouping_constructor_with_none_parent(self):
        from modules.DataGrouping import DataGrouping

        with patch.object(DataGrouping, 'setup_ui', return_value=None), patch.object(
            DataGrouping, 'read_data_to_df', return_value=None
        ), patch.object(DataGrouping, 'add_default_group', return_value=None), patch.object(
            DataGrouping, 'populate_list_widgets', return_value=None
        ):
            DataGrouping(parent=None, db_file='')

    def test_export_dialog_constructor_with_none_parent(self):
        from modules.ExportDialog import ExportDialog

        with patch.object(ExportDialog, 'init_widgets', return_value=None), patch.object(
            ExportDialog, 'init_layout', return_value=None
        ), patch.object(ExportDialog, '_load_dialog_config', return_value={'selected_preset': 'fast_diagnostics'}):
            ExportDialog(parent=None, db_file='')

    def test_filter_dialog_constructor_with_none_parent(self):
        from modules.FilterDialog import FilterDialog

        with patch.object(FilterDialog, 'setup_ui', return_value=None):
            FilterDialog(parent=None, db_file='')

    def test_modify_db_constructor_with_none_parent(self):
        from modules.ModifyDB import ModifyDB

        with patch.object(ModifyDB, 'setup_ui', return_value=None):
            ModifyDB(parent=None, db_file='')

    def test_release_notes_dialog_constructor_with_none_parent(self):
        from modules.ReleaseNotesDialog import ReleaseNotesDialog

        ReleaseNotesDialog(parent=None, release_notes='<p>Release notes</p>')


if __name__ == '__main__':
    unittest.main()
