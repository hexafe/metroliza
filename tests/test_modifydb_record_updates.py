import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from metroliza.ui.modify_db import ModifyDB


class _FakeItem:
    def __init__(self, original, current):
        self._original = original
        self._current = current

    def data(self, role):
        if role == Qt.ItemDataRole.UserRole:
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


class _FakeEditService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def apply_changes(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


class TestModifyDbRecordUpdates(unittest.TestCase):
    def test_collect_report_record_updates_ignores_readonly_and_unchanged_cells(self):
        dialog = ModifyDB.__new__(ModifyDB)
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
        dialog = ModifyDB.__new__(ModifyDB)
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
        dialog = ModifyDB.__new__(ModifyDB)
        repository = _FakeRepository()

        dialog.apply_record_updates(
            repository,
            [(42, {"reference": "REF_B"})],
            [(7, {"header": "H2"})],
        )

        self.assertEqual(repository.report_updates, [(42, {"reference": "REF_B"})])
        self.assertEqual(repository.measurement_updates, [(7, {"header": "H2"})])

    def test_apply_record_updates_requires_repository_api(self):
        dialog = ModifyDB.__new__(ModifyDB)

        with self.assertRaisesRegex(RuntimeError, "update_report_metadata_fields"):
            dialog.apply_record_updates(object(), [(42, {"reference": "REF_B"})], [])

    def test_collect_record_table_modifications_reports_original_values(self):
        dialog = ModifyDB.__new__(ModifyDB)
        specs = [
            {"label": "REPORT_ID", "field": "report_id", "editable": False},
            {"label": "REFERENCE", "field": "reference", "editable": True},
            {"label": "COMMENT", "field": "comment", "editable": True},
        ]
        table = _FakeTable(
            [
                [
                    _FakeItem(42, "42"),
                    _FakeItem("REF_A", "REF_B"),
                    _FakeItem("old comment", ""),
                ]
            ]
        )
        dialog._record_specs_by_table = {table: specs}

        summary = dialog.collect_record_table_modifications(table, "Report records", "report_id")

        self.assertEqual(
            summary,
            'Report records.REFERENCE: "REF_A" -> "REF_B" (REPORT_ID=42)\n'
            'Report records.COMMENT: "old comment" -> NULL (REPORT_ID=42)',
        )

    def test_record_value_coercion_preserves_invalid_float_text(self):
        self.assertIsNone(ModifyDB._coerce_record_value("", "float"))
        self.assertEqual(ModifyDB._coerce_record_value("10.5", "float"), 10.5)
        self.assertEqual(ModifyDB._coerce_record_value("not-a-number", "float"), "not-a-number")
        self.assertEqual(ModifyDB._coerce_record_id("bad-id"), None)

    def test_apply_changes_delegates_collected_payload_to_report_edit_service(self):
        dialog = ModifyDB.__new__(ModifyDB)
        reference_table = object()
        sample_table = object()
        header_table = object()
        service = _FakeEditService()
        changes_by_table = {
            reference_table: [("REF-B", "REF-A")],
            sample_table: [],
            header_table: [("WIDTH", "OLD WIDTH")],
        }
        dialog.reference_table = reference_table
        dialog.part_number_table = sample_table
        dialog.header_table = header_table
        dialog._storage_flavor = "current"
        dialog.collect_normalization_value_changes = lambda table: changes_by_table[table]
        dialog.collect_report_record_updates = lambda: [(42, {"comment": "reviewed"})]
        dialog.collect_measurement_record_updates = lambda: [(7, {"header": "WIDTH"})]
        dialog._create_report_edit_service = lambda: service
        dialog.close = lambda: None

        with patch("metroliza.ui.modify_db.QMessageBox.information"):
            dialog.apply_changes()

        self.assertEqual(
            service.calls,
            [
                {
                    "storage_flavor": "current",
                    "normalization_changes": {
                        "reference": [("REF-B", "REF-A")],
                        "sample_number": [],
                        "header": [("WIDTH", "OLD WIDTH")],
                    },
                    "report_updates": [(42, {"comment": "reviewed"})],
                    "measurement_updates": [(7, {"header": "WIDTH"})],
                }
            ],
        )

    def test_apply_changes_forwards_service_error_to_dialog_error_handler(self):
        dialog = ModifyDB.__new__(ModifyDB)
        dialog.reference_table = object()
        dialog.part_number_table = object()
        dialog.header_table = object()
        dialog._storage_flavor = "current"
        dialog.collect_normalization_value_changes = lambda _table: [("new", "old")]
        dialog.collect_report_record_updates = lambda: []
        dialog.collect_measurement_record_updates = lambda: []
        failure = ValueError("unsupported report edit")
        dialog._create_report_edit_service = lambda: _FakeEditService(failure)
        captured = []
        dialog.log_and_exit = captured.append

        dialog.apply_changes()

        self.assertEqual(captured, [failure])


if __name__ == "__main__":
    unittest.main()
