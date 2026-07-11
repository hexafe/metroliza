import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt


class _FakeIndex:
    def __init__(self, row, column):
        self._row = row
        self._column = column

    def row(self):
        return self._row

    def column(self):
        return self._column


class _FakeQItemSelection:
    def __init__(self, top_left, bottom_right):
        self.top_left = top_left
        self.bottom_right = bottom_right


class _FakeSelectionFlags:
    Select = 1
    Rows = 2


class _FakeQItemSelectionModel:
    SelectionFlag = _FakeSelectionFlags


from modules.modify_db import ModifyDB  # noqa: E402
import modules.modify_db as modify_db_module  # noqa: E402


class _FakeSelectionModel:
    def __init__(self):
        self.selected_rows = set()

    def select(self, target, flags):
        del flags
        if isinstance(target, _FakeQItemSelection):
            for row in range(target.top_left.row(), target.bottom_right.row() + 1):
                self.selected_rows.add(row)
            return

        self.selected_rows.add(target.row())


class _FakeTableModel:
    @staticmethod
    def index(row, column):
        return _FakeIndex(row, column)


class _FakeTableWidget:
    def __init__(self, columns):
        self._columns = columns
        self._selection_model = _FakeSelectionModel()
        self._model = _FakeTableModel()
        self.current_cell = None

    def selectionModel(self):
        return self._selection_model

    def model(self):
        return self._model

    def columnCount(self):
        return self._columns

    def setCurrentCell(self, row, column):
        self.current_cell = (row, column)


class TestModifyDbShiftRangeSelection(unittest.TestCase):
    def test_shift_click_selects_whole_range_and_keeps_anchor_row_selected(self):
        with (
            patch.object(modify_db_module, "QItemSelection", _FakeQItemSelection),
            patch.object(modify_db_module, "QItemSelectionModel", _FakeQItemSelectionModel),
        ):
            dialog = ModifyDB.__new__(ModifyDB)
            dialog._last_clicked_row_by_table = {}
            dialog._keyboard_modifiers = lambda: Qt.KeyboardModifier.NoModifier

            table = _FakeTableWidget(columns=3)

            dialog._handle_table_cell_pressed(table, 2, 0)
            self.assertEqual(dialog._last_clicked_row_by_table[table], 2)

            dialog._keyboard_modifiers = lambda: Qt.KeyboardModifier.ShiftModifier
            dialog._handle_table_cell_pressed(table, 5, 0)

            self.assertEqual(table.selectionModel().selected_rows, {2, 3, 4, 5})
            self.assertIn(2, table.selectionModel().selected_rows)


if __name__ == "__main__":
    unittest.main()
