import sys
import types
import unittest
import re

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

    def test_default_group_uses_theme_base_color(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['POPULATION'], 'GROUP_COLOR': [None]}))
        dialog.default_group_color = '#111111'
        dialog._ensure_group_color_integrity()
        self.assertEqual(dialog.df['GROUP_COLOR'].iloc[0], '#111111')

    def test_default_group_non_theme_color_is_corrected(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['POPULATION'], 'GROUP_COLOR': [None]}))
        dialog.default_group_color = '#222222'
        dialog._ensure_group_color_integrity()
        self.assertEqual(dialog.df['GROUP_COLOR'].iloc[0], '#222222')

    def test_default_group_overrides_non_theme_color(self):
        dialog = self._dialog_with_df(pd.DataFrame({'GROUP': ['POPULATION'], 'GROUP_COLOR': ['#CCCCCC']}))
        dialog.default_group_color = '#333333'
        dialog._ensure_group_color_integrity()
        self.assertEqual(dialog.df['GROUP_COLOR'].iloc[0], '#333333')
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


class _ColorCaptureItem:
    def __init__(self):
        self.background = None
        self.foreground = None

    def setBackground(self, value):
        self.background = value

    def setForeground(self, value):
        self.foreground = value


class _PaletteHighlightColor:
    def __init__(self, value):
        self._value = value

    def isValid(self):
        return True

    def name(self):
        return self._value


class _PaletteHighlightRole:
    def __init__(self, value):
        self._value = value

    def color(self):
        return _PaletteHighlightColor(self._value)


class _ListPalette:
    def __init__(self, value):
        self._value = value

    def highlight(self):
        return _PaletteHighlightRole(self._value)


class _ThemeListWidget:
    def __init__(self, highlight='#0A0B0C'):
        self._highlight = highlight
        self.stylesheet = ''

    def palette(self):
        return _ListPalette(self._highlight)

    def setStyleSheet(self, value):
        self.stylesheet = value


class TestDataGroupingSelectionStyling(unittest.TestCase):
    def test_apply_item_color_only_sets_background_for_non_selected_theme_blending(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group_color = '#FFFFFF'
        item = _ColorCaptureItem()

        dialog._apply_item_color(item, '#AABBCC')

        self.assertIsNotNone(item.background)
        self.assertIsNotNone(item.foreground)

    def test_apply_list_theme_styles_sets_selection_rules_for_all_lists(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog.reference_list = _ThemeListWidget('#112233')
        dialog.part_list = _ThemeListWidget('#112233')
        dialog.groups_list = _ThemeListWidget('#112233')
        dialog.part_group_list = _ThemeListWidget('#112233')

        dialog._apply_list_theme_styles()

        for list_widget in (dialog.reference_list, dialog.part_list, dialog.groups_list, dialog.part_group_list):
            self.assertIn('QListWidget::item:selected', list_widget.stylesheet)
            self.assertIn('background-color: #112233', list_widget.stylesheet)
            self.assertNotRegex(
                list_widget.stylesheet,
                re.compile(r'QListWidget::item(?!:selected)[^{]*\{[^}]*background-color', re.IGNORECASE),
            )


class TestDataGroupingThemeColorResolution(unittest.TestCase):
    def test_resolve_default_group_color_prefers_base(self):
        resolved = DataGrouping._resolve_default_group_color_from_base('#0D0D0D')
        self.assertEqual(resolved, '#0D0D0D')

    def test_resolve_default_group_color_fallback_is_white(self):
        resolved = DataGrouping._resolve_default_group_color_from_base(None)
        self.assertEqual(resolved, '#FFFFFF')

    def test_dark_mode_detection(self):
        self.assertTrue(DataGrouping._is_dark_mode_base('#111111'))
        self.assertFalse(DataGrouping._is_dark_mode_base('#F2F2F2'))

    def test_clamp_group_color_preserves_light_theme_palette(self):
        source = '#FDE2E4'
        self.assertEqual(DataGrouping._clamp_group_color_for_theme(source, dark_mode=False), source)

    def test_clamp_group_color_adjusts_dark_theme_palette(self):
        source = '#FDE2E4'
        clamped = DataGrouping._clamp_group_color_for_theme(source, dark_mode=True)
        self.assertTrue(clamped.startswith('#'))
        self.assertNotEqual(clamped, source)


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
    def __init__(self):
        self.disabled = None

    def setDisabled(self, value):
        self.disabled = value

    def setEnabled(self, value):
        self.disabled = not bool(value)


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
        dialog.default_group = 'POPULATION'
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

    def test_rename_group_allows_default_population_group(self):
        from unittest.mock import patch

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'GROUP': ['POPULATION', 'Ops Team'],
                'GROUP_COLOR': ['#FFFFFF', '#ABCDEF'],
            }
        )
        dialog._selected_group_name = lambda: 'POPULATION'
        dialog.populate_list_widgets = lambda: None
        dialog.remove_from_group_button = _FakeButton()

        input_dialog_cls = DataGrouping.rename_group.__globals__['QInputDialog']
        with patch.object(input_dialog_cls, 'getText', return_value=('All Samples', True), create=True) as mocked_get_text:
            dialog.rename_group()

        mocked_get_text.assert_called_once()
        self.assertIn('All Samples', dialog.df['GROUP'].tolist())
        self.assertNotIn('POPULATION', dialog.df['GROUP'].tolist())

    def test_delete_group_ignores_default_population_group(self):
        from unittest.mock import patch

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.default_group_color = '#FFFFFF'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'GROUP': ['POPULATION', 'Ops Team'],
                'GROUP_COLOR': ['#FFFFFF', '#ABCDEF'],
            }
        )
        dialog._selected_group_name = lambda: 'POPULATION'
        dialog.populate_list_widgets = lambda: None
        dialog.remove_from_group_button = _FakeButton()

        message_box_cls = DataGrouping.delete_group.__globals__['QMessageBox']
        with patch.object(message_box_cls, '__init__', return_value=None, create=True), \
             patch.object(message_box_cls, 'setStandardButtons', return_value=None, create=True), \
             patch.object(message_box_cls, 'exec', return_value=1, create=True) as mocked_exec:
            dialog.delete_group()

        mocked_exec.assert_not_called()
        self.assertEqual(dialog.df['GROUP'].tolist(), ['POPULATION', 'Ops Team'])

    def test_delete_group_reassigns_non_default_group_to_population(self):
        from unittest.mock import patch

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.default_group_color = '#FFFFFF'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'GROUP': ['Ops Team', 'Ops Team', 'POPULATION'],
                'GROUP_COLOR': ['#ABCDEF', '#ABCDEF', '#FFFFFF'],
            }
        )
        dialog._selected_group_name = lambda: 'Ops Team'
        dialog.populate_list_widgets = lambda: None
        dialog.remove_from_group_button = _FakeButton()

        message_box_cls = DataGrouping.delete_group.__globals__['QMessageBox']
        with patch.object(message_box_cls, 'Icon', type('Icon', (), {'Question': object()}), create=True), \
             patch.object(message_box_cls, 'StandardButton', type('StandardButton', (), {'Yes': 1, 'No': 2}), create=True), \
             patch.object(message_box_cls, '__init__', return_value=None, create=True), \
             patch.object(message_box_cls, 'setStandardButtons', return_value=None, create=True), \
             patch.object(message_box_cls, 'exec', return_value=1, create=True):
            dialog.delete_group()

        self.assertTrue((dialog.df['GROUP'] == 'POPULATION').all())

    def test_delete_group_allows_legacy_empty_group_name(self):
        from unittest.mock import patch

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.default_group_color = '#FFFFFF'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'GROUP': ['', '', 'POPULATION'],
                'GROUP_COLOR': ['#ABCDEF', '#ABCDEF', '#FFFFFF'],
            }
        )
        dialog._selected_group_name = lambda: ''
        dialog.populate_list_widgets = lambda: None
        dialog.remove_from_group_button = _FakeButton()

        message_box_cls = DataGrouping.delete_group.__globals__['QMessageBox']
        with patch.object(message_box_cls, 'Icon', type('Icon', (), {'Question': object()}), create=True), \
             patch.object(message_box_cls, 'StandardButton', type('StandardButton', (), {'Yes': 1, 'No': 2}), create=True), \
             patch.object(message_box_cls, '__init__', return_value=None, create=True), \
             patch.object(message_box_cls, 'setStandardButtons', return_value=None, create=True), \
             patch.object(message_box_cls, 'exec', return_value=1, create=True):
            dialog.delete_group()

        self.assertTrue((dialog.df['GROUP'] == 'POPULATION').all())

    def test_on_group_selection_changed_disables_delete_but_keeps_rename_for_default_group(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.groups_list = _FakeListWidget([_FakeListItem(text='POPULATION (n=2)', user_role='POPULATION')])
        dialog.part_group_list = _FakeListWidget([_FakeListItem(text='P1')])
        dialog.rename_group_button = _FakeButton()
        dialog.delete_group_button = _FakeButton()
        dialog.remove_from_group_button = _FakeButton()
        dialog._selected_group_name = lambda: 'POPULATION'
        dialog._populate_part_group_list = lambda selected_group: None

        dialog.on_group_selection_changed()

        self.assertFalse(dialog.rename_group_button.disabled)
        self.assertTrue(dialog.delete_group_button.disabled)
        self.assertTrue(dialog.remove_from_group_button.disabled)

    def test_on_group_selection_changed_enables_rename_and_delete_for_non_default_group(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.groups_list = _FakeListWidget([_FakeListItem(text='Ops Team (n=1)', user_role='Ops Team')])
        dialog.part_group_list = _FakeListWidget([_FakeListItem(text='P1')])
        dialog.rename_group_button = _FakeButton()
        dialog.delete_group_button = _FakeButton()
        dialog.remove_from_group_button = _FakeButton()
        dialog._selected_group_name = lambda: 'Ops Team'
        dialog._populate_part_group_list = lambda selected_group: None

        dialog.on_group_selection_changed()

        self.assertFalse(dialog.rename_group_button.disabled)
        self.assertFalse(dialog.delete_group_button.disabled)
        self.assertFalse(dialog.remove_from_group_button.disabled)

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


class _PopulateListItem:
    def __init__(self, text=''):
        self._text = text
        self._user_role = None

    def setData(self, role, value):
        self._user_role = value

    def data(self, role):
        return self._user_role

    def text(self):
        return self._text


class _PopulateListWidget:
    def __init__(self):
        self._items = []
        self._current_index = -1

    def clear(self):
        self._items = []
        self._current_index = -1

    def addItems(self, values):
        for value in values:
            self._items.append(_PopulateListItem(str(value)))

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def setCurrentRow(self, row):
        self._current_index = row

    def currentItem(self):
        if self._current_index < 0 or self._current_index >= len(self._items):
            return None
        return self._items[self._current_index]




class TestDataGroupingCreateGroupSelectionPriority(unittest.TestCase):
    def _base_dialog(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1', 'REF-1', 'REF-2'],
                'GROUP_KEY': ['k1', 'k2', 'k3'],
                'GROUP': ['POPULATION', 'POPULATION', 'POPULATION'],
                'GROUP_COLOR': ['#FFFFFF', '#FFFFFF', '#FFFFFF'],
            }
        )
        dialog._selected_reference_name = lambda: 'REF-1'
        dialog._next_group_color = lambda: '#ABC123'
        dialog.populate_list_widgets = lambda: None
        dialog.remove_from_group_button = _FakeButton()
        return dialog

    def test_create_group_uses_selected_reference_when_no_parts_selected(self):
        from unittest.mock import patch

        dialog = self._base_dialog()
        dialog.part_list = _FakeListWidget([])
        dialog.part_list.selectedItems = lambda: []

        input_dialog_cls = DataGrouping.create_group.__globals__['QInputDialog']
        with patch.object(input_dialog_cls, 'getText', return_value=('Ref Group', True), create=True):
            dialog.create_group()

        ref1_groups = dialog.df.loc[dialog.df['REFERENCE'] == 'REF-1', 'GROUP'].tolist()
        ref2_group = dialog.df.loc[dialog.df['REFERENCE'] == 'REF-2', 'GROUP'].iloc[0]
        self.assertEqual(ref1_groups, ['Ref Group', 'Ref Group'])
        self.assertEqual(ref2_group, 'POPULATION')

    def test_create_group_prefers_explicit_part_selection_over_reference(self):
        from unittest.mock import patch

        dialog = self._base_dialog()
        dialog.part_list = _FakeListWidget([_FakeListItem(user_role='k2')])
        dialog.part_list.selectedItems = lambda: [_FakeListItem(user_role='k2')]

        input_dialog_cls = DataGrouping.create_group.__globals__['QInputDialog']
        with patch.object(input_dialog_cls, 'getText', return_value=('Single Part Group', True), create=True):
            dialog.create_group()

        selected_part_group = dialog.df.loc[dialog.df['GROUP_KEY'] == 'k2', 'GROUP'].iloc[0]
        sibling_part_group = dialog.df.loc[dialog.df['GROUP_KEY'] == 'k1', 'GROUP'].iloc[0]
        self.assertEqual(selected_part_group, 'Single Part Group')
        self.assertEqual(sibling_part_group, 'POPULATION')

    def test_create_group_ignores_blank_group_name(self):
        from unittest.mock import patch

        dialog = self._base_dialog()
        dialog.part_list = _FakeListWidget([_FakeListItem(user_role='k1')])
        dialog.part_list.selectedItems = lambda: [_FakeListItem(user_role='k1')]

        input_dialog_cls = DataGrouping.create_group.__globals__['QInputDialog']
        with patch.object(input_dialog_cls, 'getText', return_value=('   ', True), create=True):
            dialog.create_group()

        self.assertTrue((dialog.df['GROUP'] == 'POPULATION').all())

    def test_create_group_prefills_dialog_with_initial_group_name(self):
        from unittest.mock import patch

        dialog = self._base_dialog()
        dialog.part_list = _FakeListWidget([])
        dialog.part_list.selectedItems = lambda: []

        input_dialog_cls = DataGrouping.create_group.__globals__['QInputDialog']
        with patch.object(input_dialog_cls, 'getText', return_value=('REF-1', False), create=True) as mocked_get_text:
            dialog.create_group(initial_group_name='REF-1')

        self.assertEqual(mocked_get_text.call_args.kwargs.get('text'), 'REF-1')


class TestDataGroupingReferenceDoubleClick(unittest.TestCase):
    def test_reference_double_click_opens_create_group_with_reference_name(self):
        dialog = DataGrouping.__new__(DataGrouping)
        captured = {'initial_group_name': None}

        def _capture_create_group(initial_group_name=''):
            captured['initial_group_name'] = initial_group_name

        dialog.create_group = _capture_create_group

        dialog.on_reference_item_double_clicked(_FakeListItem(text='REF-42'))

        self.assertEqual(captured['initial_group_name'], 'REF-42')


class TestDataGroupingSelectionRetention(unittest.TestCase):
    def test_populate_list_widgets_prefers_existing_group_name(self):
        from unittest.mock import patch

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.default_group_color = '#FFFFFF'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R2'],
                'GROUP': ['POPULATION', 'Ops Team', 'Ops Team'],
                'GROUP_KEY': ['k1', 'k2', 'k3'],
                'SAMPLE_NUMBER': [1, 2, 3],
                'DATE': ['2024-01-01', '2024-01-02', '2024-01-03'],
                'FILENAME': ['a.csv', 'b.csv', 'c.csv'],
                'GROUP_COLOR': ['#FFFFFF', '#ABCDEF', '#ABCDEF'],
            }
        )
        dialog._group_display_to_name = {}
        dialog.reference_list = _PopulateListWidget()
        dialog.part_list = _PopulateListWidget()
        dialog.all_parts_list = _PopulateListWidget()
        dialog.groups_list = _PopulateListWidget()
        dialog.part_group_list = _PopulateListWidget()
        dialog._ensure_group_color_integrity = lambda: None
        dialog._apply_item_color = lambda item, color: None
        dialog._populate_part_list = lambda selected_reference: None

        captured_group = {'value': None}
        dialog._populate_part_group_list = lambda selected_group: captured_group.update(value=selected_group)

        with patch.dict(DataGrouping.populate_list_widgets.__globals__, {'QListWidgetItem': _PopulateListItem}):
            dialog.populate_list_widgets(preferred_group_name='Ops Team')

        self.assertEqual(dialog._selected_group_name(), 'Ops Team')
        self.assertEqual(captured_group['value'], 'Ops Team')

    def test_populate_list_widgets_falls_back_to_first_when_group_missing(self):
        from unittest.mock import patch

        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.default_group_color = '#FFFFFF'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R2'],
                'GROUP': ['POPULATION', 'Other Group'],
                'GROUP_KEY': ['k1', 'k2'],
                'SAMPLE_NUMBER': [1, 2],
                'DATE': ['2024-01-01', '2024-01-02'],
                'FILENAME': ['a.csv', 'b.csv'],
                'GROUP_COLOR': ['#FFFFFF', '#ABCDEF'],
            }
        )
        dialog._group_display_to_name = {}
        dialog.reference_list = _PopulateListWidget()
        dialog.part_list = _PopulateListWidget()
        dialog.all_parts_list = _PopulateListWidget()
        dialog.groups_list = _PopulateListWidget()
        dialog.part_group_list = _PopulateListWidget()
        dialog._ensure_group_color_integrity = lambda: None
        dialog._apply_item_color = lambda item, color: None
        dialog._populate_part_list = lambda selected_reference: None
        dialog._populate_part_group_list = lambda selected_group: None

        with patch.dict(DataGrouping.populate_list_widgets.__globals__, {'QListWidgetItem': _PopulateListItem}):
            dialog.populate_list_widgets(preferred_group_name='Removed Group')

        self.assertEqual(dialog._selected_group_name(), 'POPULATION')

    def test_delete_selected_parts_requests_preferred_group_reselection(self):
        dialog = DataGrouping.__new__(DataGrouping)
        dialog.default_group = 'POPULATION'
        dialog.default_group_color = '#FFFFFF'
        dialog.group_color_column = 'GROUP_COLOR'
        dialog.df = pd.DataFrame(
            {
                'GROUP': ['Ops Team', 'Ops Team', 'POPULATION'],
                'GROUP_KEY': ['k1', 'k2', 'k3'],
                'GROUP_COLOR': ['#ABCDEF', '#ABCDEF', '#FFFFFF'],
            }
        )
        dialog.part_group_list = _FakeListWidget([_FakeListItem(user_role='k1')])
        dialog.part_group_list.selectedItems = lambda: [_FakeListItem(user_role='k1')]
        dialog._selected_group_name = lambda: 'Ops Team'
        dialog.remove_from_group_button = _FakeButton()

        call_args = {'preferred_group_name': None}
        dialog.populate_list_widgets = lambda preferred_group_name=None: call_args.update(preferred_group_name=preferred_group_name)

        result = dialog._delete_selected_parts_from_group()

        self.assertTrue(result)
        self.assertEqual(call_args['preferred_group_name'], 'Ops Team')
        reassigned_group = dialog.df.loc[dialog.df['GROUP_KEY'] == 'k1', 'GROUP'].iloc[0]
        self.assertEqual(reassigned_group, 'POPULATION')
