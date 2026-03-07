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


    def test_default_group_non_white_color_is_corrected(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['POPULATION'], 'GROUP_COLOR': ['#CCCCCC']}))
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


class _FakeListItem:
    def __init__(self, text='', user_role=None):
        self._text = text
        self._user_role = user_role
        self.hidden = False

    def text(self):
        return self._text

    def data(self, role):
        return self._user_role

    def setHidden(self, value):
        self.hidden = bool(value)


class _FakeListWidget:
    def __init__(self, items=None, current_index=0):
        self._items = items or []
        self._current_index = current_index

    def currentItem(self):
        if not self._items:
            return None
        return self._items[self._current_index]

    def count(self):
        return len(self._items)

    def item(self, row):
        return self._items[row]

    def selectedItems(self):
        return []

    def clearSelection(self):
        return None


class _FakeButton:
    def setDisabled(self, value):
        self.disabled = value


class TestDataGroupingGroupLabels(unittest.TestCase):
    def test_group_display_label_contains_count(self):
        self.assertEqual(DataGrouping._group_display_label('Group A', 3), 'Group A (n=3)')

    def test_selected_group_name_prefers_user_role(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog._group_display_to_name = {'Sales (n=2)': 'Sales'}
        dialog.groups_list = _FakeListWidget([_FakeListItem(text='Sales (n=2)', user_role='Sales')])

        self.assertEqual(dialog._selected_group_name(), 'Sales')

    def test_selected_group_name_falls_back_to_display_mapping(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog._group_display_to_name = {'Ops Team (n=1)': 'Ops Team'}
        dialog.groups_list = _FakeListWidget([_FakeListItem(text='Ops Team (n=1)', user_role=None)])

        self.assertEqual(dialog._selected_group_name(), 'Ops Team')

    def test_rename_group_uses_canonical_group_name(self):
        from unittest.mock import patch

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'GROUP': ['Ops Team', 'POPULATION'],
                'GROUP_COLOR': ['#ABCDEF', '#FFFFFF'],
            }
        )
        dialog._group_display_to_name = {'Ops Team (n=1)': 'Ops Team'}
        dialog.groups_list = _FakeListWidget([_FakeListItem(text='Ops Team (n=1)', user_role='Ops Team')])
        dialog._selected_group_name = lambda: 'Ops Team'
        dialog.populate_list_widgets = lambda: None
        dialog.remove_from_group_button = _FakeButton()

        input_dialog_cls = DataGrouping.rename_group.__globals__['QInputDialog']
        with patch.object(input_dialog_cls, 'getText', return_value=('Operations', True), create=True):
            dialog.rename_group()

        self.assertIn('Operations', dialog.df['GROUP'].tolist())
        self.assertNotIn('Ops Team', dialog.df['GROUP'].tolist())

    def test_group_search_matches_canonical_name(self):
        from modules.list_selection_utils import ListSelectionUtils

        dialog = DataGrouping.__new__(DataGrouping)
        dialog._list_selection_utils = ListSelectionUtils()
        dialog.groups_list = _FakeListWidget([_FakeListItem(text='Fancy Label (n=4)', user_role='CanonicalGroup')])

        dialog.search_list_widgets(dialog.groups_list, 'canonical')

        self.assertFalse(dialog.groups_list.item(0).hidden)

    def test_double_click_group_item_triggers_rename(self):
        from unittest.mock import Mock

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.rename_group = Mock()

        dialog.on_group_item_double_clicked(_FakeListItem(text='Any'))

        dialog.rename_group.assert_called_once_with()

    def test_double_click_ignores_none_item(self):
        from unittest.mock import Mock

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.rename_group = Mock()

        dialog.on_group_item_double_clicked(None)

        dialog.rename_group.assert_not_called()
