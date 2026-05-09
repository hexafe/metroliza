import sys
import types
import unittest

qtcore_stub = types.ModuleType('PyQt6.QtCore')
qtcore_stub.Qt = type('Qt', (), {'ItemDataRole': type('ItemDataRole', (), {'UserRole': 0})})
sys.modules['PyQt6.QtCore'] = qtcore_stub

qtwidgets_stub = types.ModuleType('PyQt6.QtWidgets')
qtwidgets_stub.QSizePolicy = type(
    'QSizePolicy',
    (),
    {'Policy': type('Policy', (), {'Expanding': 1, 'Fixed': 2})},
)
qtwidgets_stub.QHeaderView = type(
    'QHeaderView',
    (),
    {'ResizeMode': type('ResizeMode', (), {'Interactive': 0, 'Stretch': 1, 'ResizeToContents': 2})},
)
qtwidgets_stub.QApplication = type('QApplication', (), {'instance': staticmethod(lambda: None)})
for name in [
    'QDialog',
    'QGridLayout',
    'QHBoxLayout',
    'QTableWidget',
    'QTableWidgetItem',
    'QPushButton',
    'QFileDialog',
    'QMessageBox',
    'QFrame',
    'QLabel',
    'QLineEdit',
    'QWidget',
]:
    setattr(qtwidgets_stub, name, type(name, (), {}))
sys.modules['PyQt6.QtWidgets'] = qtwidgets_stub
sys.modules['PyQt6.QtGui'] = types.ModuleType('PyQt6.QtGui')

custom_logger_stub = types.ModuleType('modules.custom_logger')
custom_logger_stub.CustomLogger = type('CustomLogger', (), {'__init__': lambda self, *args, **kwargs: None})
sys.modules['modules.custom_logger'] = custom_logger_stub
sys.modules.pop('modules.ui_foundation', None)
sys.modules.pop('modules.modify_db', None)

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


class _FakeHeader:
    def __init__(self):
        self.stretch_last_section = None
        self.resize_modes = {}

    def setStretchLastSection(self, value):
        self.stretch_last_section = value

    def setSectionResizeMode(self, column, mode):
        self.resize_modes[column] = mode


class _FakeResizeTable:
    def __init__(self, columns):
        self._columns = columns
        self.minimum_height = None
        self.alternating_rows = None
        self.size_policy = None
        self.header = _FakeHeader()

    def setMinimumHeight(self, value):
        self.minimum_height = value

    def setAlternatingRowColors(self, value):
        self.alternating_rows = value

    def setSizePolicy(self, horizontal, vertical):
        self.size_policy = (horizontal, vertical)

    def horizontalHeader(self):
        return self.header

    def columnCount(self):
        return self._columns


class TestModifyDbUpdateStatements(unittest.TestCase):
    @staticmethod
    def _mode_value(mode):
        return getattr(mode, "value", mode)

    @staticmethod
    def _mode_name(mode):
        return getattr(mode, "name", None)

    def _assert_resize_mode(self, actual, *, expected_name, expected_stub):
        actual_name = self._mode_name(actual)
        if actual_name is not None:
            self.assertEqual(actual_name, expected_name)
            return
        self.assertEqual(actual, expected_stub)

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

    def test_configure_normalize_table_sets_stretch_and_occurrence_resize(self):
        table = _FakeResizeTable(columns=3)

        ModifyDB._configure_normalize_table(table)

        resize_mode = qtwidgets_stub.QHeaderView.ResizeMode
        self._assert_resize_mode(
            table.header.resize_modes[0],
            expected_name="Stretch",
            expected_stub=resize_mode.Stretch,
        )
        self._assert_resize_mode(
            table.header.resize_modes[1],
            expected_name="Stretch",
            expected_stub=resize_mode.Stretch,
        )
        self._assert_resize_mode(
            table.header.resize_modes[2],
            expected_name="ResizeToContents",
            expected_stub=resize_mode.ResizeToContents,
        )


if __name__ == '__main__':
    unittest.main()
