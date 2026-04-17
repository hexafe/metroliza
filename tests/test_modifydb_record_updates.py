import sys
import types
import unittest

qtcore_stub = types.ModuleType("PyQt6.QtCore")
qtcore_stub.Qt = type("Qt", (), {"ItemDataRole": type("ItemDataRole", (), {"UserRole": 0})})
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
sys.modules["PyQt6.QtGui"] = types.ModuleType("PyQt6.QtGui")

custom_logger_stub = types.ModuleType("modules.custom_logger")
custom_logger_stub.CustomLogger = type("CustomLogger", (), {"__init__": lambda self, *args, **kwargs: None})
sys.modules["modules.custom_logger"] = custom_logger_stub

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
        return self._rows[row][col]


class _FakeRepository:
    def __init__(self):
        self.report_updates = []
        self.measurement_updates = []

    def update_report_metadata_fields(self, report_id, fields):
        self.report_updates.append((report_id, fields))

    def update_measurement_fields(self, measurement_id, fields):
        self.measurement_updates.append((measurement_id, fields))


class TestModifyDbRecordUpdates(unittest.TestCase):
    def test_collect_report_record_updates_ignores_readonly_and_unchanged_cells(self):
        dialog = object.__new__(ModifyDB)
        specs = [
            {"label": "REPORT_ID", "field": "report_id", "editable": False},
            {"label": "REFERENCE", "field": "reference", "editable": True},
            {"label": "COMMENT", "field": "comment", "editable": True},
            {"label": "FILENAME", "field": "file_name", "editable": False},
        ]
        table = _FakeTable(
            [
                [
                    _FakeItem(42, "42"),
                    _FakeItem("REF_A", "REF_B"),
                    _FakeItem("old comment", ""),
                    _FakeItem("source.pdf", "renamed.pdf"),
                ],
                [
                    _FakeItem(43, "43"),
                    _FakeItem("REF_C", "REF_C"),
                    _FakeItem(None, ""),
                    _FakeItem("source2.pdf", "source2.pdf"),
                ],
            ]
        )
        dialog._record_specs_by_table = {table: specs}

        updates = dialog.collect_record_table_updates(table, "report_id")

        self.assertEqual(updates, [(42, {"reference": "REF_B", "comment": None})])

    def test_collect_measurement_record_updates_coerces_float_cells(self):
        dialog = object.__new__(ModifyDB)
        specs = [
            {"label": "MEASUREMENT_ID", "field": "measurement_id", "editable": False},
            {"label": "REPORT_ID", "field": "report_id", "editable": False},
            {"label": "NOM", "field": "nominal", "editable": True, "value_type": "float"},
            {"label": "OUTTOL", "field": "outtol", "editable": True, "value_type": "float"},
            {"label": "STATUS_CODE", "field": "status_code", "editable": True},
        ]
        table = _FakeTable(
            [
                [
                    _FakeItem(7, "7"),
                    _FakeItem(42, "42"),
                    _FakeItem(10.0, "10.25"),
                    _FakeItem(0.1, ""),
                    _FakeItem("nok", "ok"),
                ]
            ]
        )
        dialog._record_specs_by_table = {table: specs}

        updates = dialog.collect_record_table_updates(table, "measurement_id")

        self.assertEqual(updates, [(7, {"nominal": 10.25, "outtol": None, "status_code": "ok"})])

    def test_apply_record_updates_dispatches_to_repository_methods(self):
        dialog = object.__new__(ModifyDB)
        repository = _FakeRepository()

        dialog.apply_record_updates(
            repository,
            [(42, {"reference": "REF_B"})],
            [(7, {"header": "H2"})],
        )

        self.assertEqual(repository.report_updates, [(42, {"reference": "REF_B"})])
        self.assertEqual(repository.measurement_updates, [(7, {"header": "H2"})])

    def test_apply_record_updates_requires_repository_api(self):
        dialog = object.__new__(ModifyDB)

        with self.assertRaisesRegex(RuntimeError, "update_report_metadata_fields"):
            dialog.apply_record_updates(object(), [(42, {"reference": "REF_B"})], [])


if __name__ == "__main__":
    unittest.main()
