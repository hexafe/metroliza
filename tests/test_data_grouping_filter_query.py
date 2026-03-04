import sys
import types
import unittest

from collections import namedtuple

import pandas as pd


qtcore_stub = types.ModuleType('PyQt6.QtCore')
qtcore_stub.Qt = type('Qt', (), {'ItemDataRole': type('ItemDataRole', (), {'UserRole': 0})})
sys.modules['PyQt6.QtCore'] = qtcore_stub


qtgui_stub = types.ModuleType('PyQt6.QtGui')


class _DummyQColor:
    def __init__(self, value=None):
        self._value = str(value or '#000000')

    def isValid(self):
        return isinstance(self._value, str) and self._value.startswith('#') and len(self._value) in {7}

    def red(self):
        return int(self._value[1:3], 16) if self.isValid() else 0

    def green(self):
        return int(self._value[3:5], 16) if self.isValid() else 0

    def blue(self):
        return int(self._value[5:7], 16) if self.isValid() else 0

    def name(self):
        return self._value.upper() if self.isValid() else '#000000'

    @classmethod
    def fromHsl(cls, h, s, lightness):
        return cls(f'#{(h % 256):02X}{(s % 256):02X}{(lightness % 256):02X}')


class _DummyQBrush:
    def __init__(self, *args, **kwargs):
        pass


qtgui_stub.QColor = _DummyQColor
qtgui_stub.QBrush = _DummyQBrush
sys.modules['PyQt6.QtGui'] = qtgui_stub

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


class TestDataGroupingPartDisplayLabel(unittest.TestCase):
    def test_part_display_label_accepts_namedtuple_row(self):
        dialog = DataGrouping.__new__(DataGrouping)
        Row = namedtuple('Row', ['SAMPLE_NUMBER', 'DATE', 'FILENAME'])
        row = Row(SAMPLE_NUMBER=42, DATE='2024-01-15', FILENAME='part.csv')

        label = dialog._part_display_label(row)

        self.assertEqual(label, '42 | 2024-01-15 | part.csv')

    def test_part_display_label_handles_missing_values(self):
        dialog = DataGrouping.__new__(DataGrouping)
        row = {'SAMPLE_NUMBER': 7, 'DATE': pd.NA, 'FILENAME': None}

        label = dialog._part_display_label(row)

        self.assertEqual(label, '7 |  | ')


class TestDataGroupingColorAssignments(unittest.TestCase):
    def _dialog_with_df(self, df):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.default_group_color = '#FFFFFF'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.group_palette = ['#FDE2E4', '#E2ECE9']
        dialog.df = df.copy()
        return dialog

    def test_default_group_remains_white(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['POPULATION'], 'GROUP_COLOR': [None]}))
        dialog._ensure_group_color_integrity()
        self.assertEqual(dialog.df['GROUP_COLOR'].iloc[0], '#FFFFFF')

    def test_new_groups_receive_distinct_colors(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['POPULATION', 'A', 'B'], 'GROUP_COLOR': ['#FFFFFF', None, None]}))
        dialog._ensure_group_color_integrity()
        assigned = dialog.df.loc[dialog.df['GROUP'].isin(['A', 'B']), 'GROUP_COLOR'].tolist()
        self.assertEqual(len(set(assigned)), 2)

    def test_palette_exhaustion_generates_additional_color(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['A', 'B', 'C'], 'GROUP_COLOR': [None, None, None]}))
        dialog._ensure_group_color_integrity()
        colors = dialog.df['GROUP_COLOR'].tolist()
        self.assertEqual(colors[0], '#FDE2E4')
        self.assertEqual(colors[1], '#E2ECE9')
        self.assertTrue(colors[2].startswith('#'))

    def test_deleted_group_color_can_be_reused(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['A'], 'GROUP_COLOR': ['#FDE2E4']}))
        dialog.df = pd.DataFrame({'GROUP': ['B'], 'GROUP_COLOR': [None]})
        dialog._ensure_group_color_integrity()
        self.assertEqual(dialog.df['GROUP_COLOR'].iloc[0], '#FDE2E4')


if __name__ == '__main__':
    unittest.main()
