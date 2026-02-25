import sys
import types
import unittest


qtcore_stub = types.ModuleType('PyQt6.QtCore')
qtcore_stub.Qt = type('Qt', (), {'UserRole': 0})
sys.modules['PyQt6.QtCore'] = qtcore_stub

qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
for name in [
    'QMainWindow',
    'QLabel',
    'QWidget',
    'QVBoxLayout',
    'QLineEdit',
    'QPushButton',
    'QTableWidget',
    'QTableWidgetItem',
    'QComboBox',
]:
    setattr(qtwidgets_stub, name, type(name, (), {}))


class _MessageBox:
    class StandardButton:
        Yes = 1
        No = 2

    @staticmethod
    def warning(*args, **kwargs):
        return None

    @staticmethod
    def question(*args, **kwargs):
        return _MessageBox.StandardButton.Yes


qtwidgets_stub.QMessageBox = _MessageBox
sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub

from modules.bom_manager import BOMManager  # noqa: E402


class _FakeIndex:
    def __init__(self, row):
        self._row = row

    def row(self):
        return self._row


class _FakeSelectionModel:
    def __init__(self, rows):
        self._rows = rows

    def selectedRows(self):
        return [_FakeIndex(row) for row in self._rows]


class _FakeSelectedItem:
    def __init__(self, row):
        self._row = row

    def row(self):
        return self._row


class _FakeCell:
    def __init__(self, row_data):
        self._row_data = row_data

    def data(self, role):
        return self._row_data


class _FakeTable:
    def __init__(self, row_data, selected_item_rows, selected_rows_from_model):
        self._row_data = list(row_data)
        self._selected_item_rows = selected_item_rows
        self._selected_rows_from_model = selected_rows_from_model

    def selectionModel(self):
        return _FakeSelectionModel(self._selected_rows_from_model)

    def selectedItems(self):
        return [_FakeSelectedItem(row) for row in self._selected_item_rows]

    def item(self, row, column):
        return _FakeCell(self._row_data[row])

    def update_rows(self, row_data):
        self._row_data = list(row_data)

    def rowCount(self):
        return len(self._row_data)


class _FakeManager:
    def __init__(self):
        self.rows = [
            (1, 'PR-1', 'Desc 1', 'Part-1', 'Part Desc 1', None),
            (2, 'PR-2', 'Desc 2', 'Part-2', 'Part Desc 2', None),
        ]
        self.bom_table = _FakeTable(
            row_data=self.rows,
            selected_item_rows=[0, 0, 0, 0, 0],
            selected_rows_from_model=[0],
        )
        self.refresh_called = 0
        self.clear_called = 0
        self.delete_statements = []

    def _execute_write(self, query, params=()):
        if query.strip().upper().startswith('DELETE FROM BOM'):
            self.delete_statements.append(params)
            delete_id = params[0]
            self.rows = [row for row in self.rows if row[0] != delete_id]

    def refresh_table(self):
        self.refresh_called += 1
        self.bom_table.update_rows(self.rows)

    def clear_inputs(self):
        self.clear_called += 1


class TestBOMManagerDeleteEntry(unittest.TestCase):
    def test_delete_selected_row_with_multiple_cells_uses_one_delete_per_row_and_refreshes(self):
        manager = _FakeManager()

        BOMManager.delete_bom_entry(manager)

        self.assertEqual(manager.delete_statements, [(1,)])
        self.assertEqual(manager.refresh_called, 1)
        self.assertEqual(manager.clear_called, 1)
        self.assertEqual(manager.rows, [(2, 'PR-2', 'Desc 2', 'Part-2', 'Part Desc 2', None)])
        self.assertEqual(manager.bom_table.rowCount(), 1)


if __name__ == '__main__':
    unittest.main()
