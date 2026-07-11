import sys
import types
import unittest
from unittest.mock import patch


class TestDataGroupingErrorPaths(unittest.TestCase):
    def test_read_data_to_df_reraises_unexpected_errors(self):
        qtcore = types.ModuleType('PyQt6.QtCore')
        qtcore.Qt = types.SimpleNamespace(
            ItemDataRole=types.SimpleNamespace(UserRole=0),
        )
        qtwidgets = types.ModuleType('PyQt6.QtWidgets')
        qtwidgets.QDialog = type('QDialog', (), {})
        qtwidgets.QGridLayout = object
        qtwidgets.QLabel = object
        qtwidgets.QLineEdit = object
        qtwidgets.QListWidget = object
        qtwidgets.QListWidgetItem = object
        qtwidgets.QPushButton = object
        qtwidgets.QInputDialog = object
        qtwidgets.QMessageBox = object
        qtwidgets.QAbstractItemView = types.SimpleNamespace(SelectionMode=types.SimpleNamespace(MultiSelection=2))
        qtgui = types.ModuleType('PyQt6.QtGui')
        qtgui.QColor = object
        qtgui.QBrush = object

        pyqt6 = types.ModuleType('PyQt6')
        pyqt6.QtCore = qtcore
        pyqt6.QtWidgets = qtwidgets
        pyqt6.QtGui = qtgui

        original_modules = {
            name: sys.modules.get(name)
            for name in (
                'PyQt6',
                'PyQt6.QtCore',
                'PyQt6.QtWidgets',
                'PyQt6.QtGui',
                'modules.data_grouping',
                'metroliza.ui.data_grouping',
            )
        }
        package_attrs = []
        for package_name, attribute in (
            ('modules', 'data_grouping'),
            ('metroliza.ui', 'data_grouping'),
        ):
            package = __import__(package_name, fromlist=(attribute,))
            sentinel = object()
            package_attrs.append((package, attribute, vars(package).get(attribute, sentinel), sentinel))
        sys.modules['PyQt6'] = pyqt6
        sys.modules['PyQt6.QtCore'] = qtcore
        sys.modules['PyQt6.QtWidgets'] = qtwidgets
        sys.modules['PyQt6.QtGui'] = qtgui

        try:
            import importlib
            sys.modules.pop('modules.data_grouping', None)
            sys.modules.pop('metroliza.ui.data_grouping', None)
            data_grouping_module = importlib.import_module('modules.data_grouping')
            DataGrouping = data_grouping_module.DataGrouping

            dialog = types.SimpleNamespace()
            dialog.parent = lambda: None
            dialog.db_file = 'test.db'

            captured = {}

            def _log_and_exit(exc, *, reraise=False):
                captured['reraise'] = reraise
                if reraise:
                    raise exc

            dialog.log_and_exit = _log_and_exit

            with patch.object(data_grouping_module, 'load_grouping_dataframe', side_effect=RuntimeError('boom'), create=True):
                with self.assertRaises(RuntimeError):
                    DataGrouping.read_data_to_df(dialog)

            self.assertTrue(captured.get('reraise'))
        finally:
            for name, module in original_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            for package, attribute, previous, sentinel in package_attrs:
                if previous is sentinel:
                    vars(package).pop(attribute, None)
                else:
                    setattr(package, attribute, previous)


if __name__ == '__main__':
    unittest.main()
