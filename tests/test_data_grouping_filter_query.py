import sys
import types
import unittest


qtcore_stub = types.ModuleType('PyQt6.QtCore')
qtcore_stub.Qt = type('Qt', (), {'ItemDataRole': type('ItemDataRole', (), {'UserRole': 0})})
sys.modules['PyQt6.QtCore'] = qtcore_stub

qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
for name in [
    'QAbstractItemView',
    'QDialog',
    'QGridLayout',
    'QLabel',
    'QLineEdit',
    'QListWidget',
    'QListWidgetItem',
    'QPushButton',
    'QInputDialog',
    'QMessageBox',
]:
    setattr(qtwidgets_stub, name, type(name, (), {}))
sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub

custom_logger_stub = types.ModuleType('modules.CustomLogger')
custom_logger_stub.CustomLogger = type('CustomLogger', (), {'__init__': lambda self, *a, **k: None})
sys.modules['modules.CustomLogger'] = custom_logger_stub

from modules.DataGrouping import DataGrouping  # noqa: E402


class TestDataGroupingFilterQuery(unittest.TestCase):
    def test_build_grouping_query_uses_default_without_filter(self):
        query = DataGrouping._build_grouping_query(None)
        self.assertIn('FROM REPORTS', query)

    def test_build_grouping_query_wraps_filter_query(self):
        filter_query = 'SELECT REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER FROM X WHERE 1=1'
        query = DataGrouping._build_grouping_query(filter_query)
        self.assertIn('FROM (', query)
        self.assertIn(filter_query, query)
        self.assertIn('SELECT DISTINCT REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER', query)


if __name__ == '__main__':
    unittest.main()
