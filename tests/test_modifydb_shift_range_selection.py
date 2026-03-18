import sys
import types
import unittest


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


qtcore_stub = types.ModuleType("PyQt6.QtCore")
qtcore_stub.QItemSelection = _FakeQItemSelection
qtcore_stub.QItemSelectionModel = _FakeQItemSelectionModel
qtcore_stub.Qt = type(
    "Qt",
    (),
    {
        "KeyboardModifier": type("KeyboardModifier", (), {"ShiftModifier": 1}),
        "ItemDataRole": type("ItemDataRole", (), {"UserRole": 0}),
    },
)
sys.modules["PyQt6.QtCore"] = qtcore_stub

qtwidgets_stub = types.ModuleType("PyQt6.QtWidgets")
for name in [
    "QDialog",
    "QGridLayout",
    "QTableWidget",
    "QTableWidgetItem",
    "QPushButton",
    "QFileDialog",
    "QMessageBox",
]:
    setattr(qtwidgets_stub, name, type(name, (), {}))
sys.modules["PyQt6.QtWidgets"] = qtwidgets_stub

custom_logger_stub = types.ModuleType("modules.custom_logger")
custom_logger_stub.CustomLogger = type("CustomLogger", (), {"__init__": lambda self, *args, **kwargs: None})
sys.modules["modules.custom_logger"] = custom_logger_stub

from modules.modify_db import ModifyDB  # noqa: E402


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
        dialog = object.__new__(ModifyDB)
        dialog._last_clicked_row_by_table = {}
        dialog._keyboard_modifiers = lambda: 0

        table = _FakeTableWidget(columns=3)

        dialog._handle_table_cell_pressed(table, 2, 0)
        self.assertEqual(dialog._last_clicked_row_by_table[table], 2)

        dialog._keyboard_modifiers = lambda: qtcore_stub.Qt.KeyboardModifier.ShiftModifier
        dialog._handle_table_cell_pressed(table, 5, 0)

        self.assertEqual(table.selectionModel().selected_rows, {2, 3, 4, 5})
        self.assertIn(2, table.selectionModel().selected_rows)


if __name__ == "__main__":
    unittest.main()
