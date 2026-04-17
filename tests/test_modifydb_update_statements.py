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

    def item(self, row, col):
        return self._rows[row]


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


if __name__ == '__main__':
    unittest.main()
