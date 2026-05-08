import sys
import types
import unittest

qtcore_stub = types.ModuleType('PyQt6.QtCore')
qtcore_stub.Qt = type('Qt', (), {'ItemDataRole': type('ItemDataRole', (), {'UserRole': 0})})
sys.modules['PyQt6.QtCore'] = qtcore_stub

qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
for name in [
    'QDialog',
    'QGridLayout',
    'QTableWidget',
    'QTableWidgetItem',
    'QPushButton',
    'QFileDialog',
    'QMessageBox',
]:
    setattr(qtwidgets_stub, name, type(name, (), {}))
sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub
sys.modules['PyQt6.QtGui'] = types.ModuleType('PyQt6.QtGui')

custom_logger_stub = types.ModuleType('modules.custom_logger')
custom_logger_stub.CustomLogger = type('CustomLogger', (), {'__init__': lambda self, *args, **kwargs: None})
sys.modules['modules.custom_logger'] = custom_logger_stub

from modules.modify_db import ModifyDB  # noqa: E402


class _FakeItem:
    def __init__(self, original, current):
        self._original = original
        self._current = current

    def data(self, role):
        if role == 0:
            return self._original
        return None

    def text(self):
        return self._current


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def rowCount(self):
        return len(self._rows)

    def columnCount(self):
        return 1

    def item(self, row, col):
        return self._rows[row]


class _FakeMatrixTable:
    def __init__(self, rows):
        self._rows = rows

    def rowCount(self):
        return len(self._rows)

    def columnCount(self):
        return len(self._rows[0]) if self._rows else 0

    def item(self, row, col):
        return self._rows[row][col]


class TestModifyDbUpdateStatements(unittest.TestCase):
    def test_build_update_statements_returns_only_changed_rows(self):
        table = _FakeTable(
            [
                _FakeItem('A', 'A'),
                _FakeItem('B', 'B2'),
                _FakeItem('C', 'C2'),
            ]
        )

        statements = ModifyDB.build_update_statements(
            None,
            table,
            'report_metadata',
            'reference',
        )

        self.assertEqual(
            statements,
            [
                ('UPDATE report_metadata SET reference = ? WHERE reference = ?', ('B2', 'B')),
                ('UPDATE report_metadata SET reference = ? WHERE reference = ?', ('C2', 'C')),
            ],
        )

    def test_build_update_statements_uses_new_value_column_for_normalize_layout(self):
        table = _FakeMatrixTable(
            [
                [_FakeItem('A', 'A'), _FakeItem('A', 'A'), _FakeItem(3, '3')],
                [_FakeItem('B', 'B'), _FakeItem('B', 'B2'), _FakeItem(2, '2')],
            ]
        )

        statements = ModifyDB.build_update_statements(
            None,
            table,
            'report_metadata',
            'reference',
        )

        self.assertEqual(
            statements,
            [('UPDATE report_metadata SET reference = ? WHERE reference = ?', ('B2', 'B'))],
        )


if __name__ == '__main__':
    unittest.main()
