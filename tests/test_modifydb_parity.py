"""Behaviour parity of the Modify Database record tables (#1118).

The golden file ``tests/fixtures/modifydb/parity_golden.json`` holds a fixed set of edits
(``ops``) per storage flavor and the observable results that the pre-#1118 ``QTableWidget``
implementation produced for them (``expected``): confirmation summary, collected updates,
generated UPDATE statements, selection and filter results, and the database state after the
apply flow. The model/view implementation must reproduce them exactly.

``run_scenario`` is driver-agnostic: only ``ScenarioDriver.set_record_cell``,
``apply_record_filter`` and ``record_visible_keys`` touch the record-table widget API, so the same
scenario can be replayed against the pre-change implementation to regenerate ``expected``.
"""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest


GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "modifydb" / "parity_golden.json"
NORMALIZE_TABLE_ATTRS = {
    "reference": "reference_table",
    "part_number": "part_number_table",
    "header": "header_table",
}
RECORD_TABLE_ATTRS = {
    "report_records": ("report_records_table", "report_id"),
    "measurement_records": ("measurement_records_table", "measurement_id"),
}


_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


# --------------------------------------------------------------------------------------
# Synthetic databases (no customer data)
# --------------------------------------------------------------------------------------

_CURRENT_REPORTS = (
    # id, reference, date, time, part, revision, sample, operator, comment
    (1, "REF-A", "2024-01-01", "08:00", "PART-1", "A", "001", "OP1", "first"),
    (2, "REF-A", "2024-01-02", None, "PART-1", "A", "002", "OP2", None),
    (3, "REF-B", "2024-02-01", "09:15", "PART-2", "B", "002", None, "review"),
    (4, "REF-C", "2024-03-05", None, None, None, "004", "OP1", None),
)

_CURRENT_MEASUREMENTS = (
    # id, report_id, header, section, feature, characteristic, family, description, ax,
    # nominal, tol+, tol-, bonus, meas, dev, outtol, status
    (101, 1, "WIDTH", "SEC1", "F1", "Width", "CH_A", "Slot width", "X", 10.0, 0.1, -0.1, 0.0, 10.05, 0.05, 0.0, "ok"),
    (102, 1, "HEIGHT", "SEC1", "F2", "Height", "CH_A", "Slot height", "Y", 20.0, 0.2, -0.2, 0.0, 20.05, 0.05, 0.0, "ok"),
    (103, 1, "DIAM", "SEC2", "F3", "Diameter", "CH_B", "Hole", "Z", 5.0, 0.05, -0.05, 0.0, 5.07, 0.02, 0.02, "ok"),
    (104, 2, "WIDTH", "SEC1", "F1", "Width", "CH_A", "Slot width", "X", 10.0, 0.1, -0.1, 0.0, 10.2, 0.2, 0.1, "nok"),
    (105, 2, "HEIGHT", "SEC1", "F2", "Height", "CH_A", "Slot height", "Y", 20.0, 0.2, -0.2, 0.0, 19.9, -0.1, 0.0, "ok"),
    (106, 3, "WIDTH", "SEC1", "F1", "Width", "CH_A", "Slot width", "X", 10.0, 0.1, -0.1, 0.0, 10.01, 0.01, 0.0, "ok"),
    (107, 3, None, "SEC3", "F4", "Flatness", "CH_C", None, "Z", None, 0.05, 0.0, 0.0, 0.03, 0.03, 0.0, "ok"),
    (108, 3, "DIAM", "SEC2", "F3", "Diameter", "CH_B", "Hole", "Z", 5.0, 0.05, -0.05, 0.0, 5.0, 0.0, 0.0, "ok"),
    (109, 4, "WIDTH", "SEC1", "F1", "Width", "CH_A", "Slot width", "X", 10.0, 0.1, -0.1, 0.0, 9.85, -0.15, 0.05, "nok"),
    (110, 4, "HEIGHT", "SEC1", "F2", "Height", "CH_A", "Slot height", "Y", 20.0, 0.2, -0.2, 0.0, 20.0, 0.0, 0.0, "ok"),
)

_LEGACY_REPORTS = (
    # ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER
    (1, "REF-A", "/reports", "a.pdf", "2024-01-01", "001"),
    (2, "REF-B", "/reports", "b.pdf", "2024-01-02", "002"),
    (3, "REF-B", "/reports", "c.pdf", "2024-01-03", "002"),
    (4, "REF-C", "/archive", "d.pdf", None, "004"),
)

_LEGACY_MEASUREMENTS = (
    # ID, REPORT_ID, AX, NOM, +TOL, -TOL, BONUS, MEAS, DEV, OUTTOL, HEADER
    (10, 1, "X", 10.0, 0.1, -0.1, 0.0, 10.05, 0.05, 0.0, "WIDTH"),
    (11, 2, "Y", 20.0, 0.2, -0.2, 0.0, 20.05, 0.05, 0.0, "HEIGHT"),
    (12, 2, "Z", None, 0.05, -0.05, 0.0, 5.07, 0.02, 0.02, "DIAM"),
    (13, 3, "X", 10.0, 0.1, -0.1, 0.0, 10.2, 0.2, 0.1, "WIDTH"),
    (14, 4, "Y", 20.0, 0.2, -0.2, 0.0, 19.9, -0.1, 0.0, None),
)


def _build_current_database(path):
    from metroliza.reports.report_schema import ensure_report_schema

    ensure_report_schema(str(path))
    with closing(sqlite3.connect(path)) as connection, connection:
        for report in _CURRENT_REPORTS:
            report_id, reference, date, time, part, revision, sample, operator, comment = report
            connection.execute(
                "INSERT INTO source_files (id, sha256, source_format, discovered_at) VALUES (?, ?, 'pdf', '2024-01-01')",
                (report_id, f"sha-{report_id}"),
            )
            connection.execute(
                """
                INSERT INTO source_file_locations
                    (source_file_id, absolute_path, directory_path, file_name, file_extension, discovered_at)
                VALUES (?, ?, '/synthetic', ?, '.pdf', '2024-01-01')
                """,
                (report_id, f"/synthetic/r{report_id}.pdf", f"r{report_id}.pdf"),
            )
            connection.execute(
                """
                INSERT INTO parsed_reports
                    (id, source_file_id, parser_id, template_family, parse_status, created_at, updated_at)
                VALUES (?, ?, 'synthetic', 'synthetic', 'parsed', '2024-01-01', '2024-01-01')
                """,
                (report_id, report_id),
            )
            connection.execute(
                """
                INSERT INTO report_metadata
                    (report_id, reference, report_date, report_time, part_name, revision,
                     sample_number, operator_name, comment, metadata_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'v1')
                """,
                (report_id, reference, date, time, part, revision, sample, operator, comment),
            )
        for row_order, measurement in enumerate(_CURRENT_MEASUREMENTS):
            connection.execute(
                """
                INSERT INTO report_measurements
                    (id, report_id, row_order, header, section_name, feature_label, characteristic_name,
                     characteristic_family, description, ax, nominal, tol_plus, tol_minus, bonus, meas,
                     dev, outtol, status_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (measurement[0], measurement[1], row_order, *measurement[2:]),
            )


def _build_legacy_database(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT, SAMPLE_NUMBER TEXT)"
        )
        connection.execute(
            """
            CREATE TABLE MEASUREMENTS (
                ID INTEGER PRIMARY KEY, REPORT_ID INTEGER, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL,
                BONUS REAL, MEAS REAL, DEV REAL, OUTTOL REAL, HEADER TEXT
            )
            """
        )
        connection.executemany("INSERT INTO REPORTS VALUES (?, ?, ?, ?, ?, ?)", _LEGACY_REPORTS)
        connection.executemany(
            'INSERT INTO MEASUREMENTS (ID, REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _LEGACY_MEASUREMENTS,
        )


DATABASE_BUILDERS = {"current": _build_current_database, "legacy": _build_legacy_database}

DUMP_QUERIES = {
    "current": {
        "report_metadata": (
            "SELECT report_id, reference, report_date, report_time, part_name, revision, sample_number, "
            "operator_name, comment FROM report_metadata ORDER BY report_id"
        ),
        "report_measurements": (
            "SELECT id, report_id, header, section_name, feature_label, characteristic_name, "
            "characteristic_family, description, ax, nominal, tol_plus, tol_minus, bonus, meas, dev, "
            "outtol, status_code FROM report_measurements ORDER BY id"
        ),
    },
    "legacy": {
        "REPORTS": "SELECT * FROM REPORTS ORDER BY ID",
        "MEASUREMENTS": "SELECT * FROM MEASUREMENTS ORDER BY ID",
    },
}


# --------------------------------------------------------------------------------------
# Scenario runner
# --------------------------------------------------------------------------------------


class ScenarioDriver:
    """Widget access used by the scenario runner (record tables are implementation-specific)."""

    def open_dialog(self, database_path):
        from metroliza.ui.modify_db import ModifyDB

        _app()
        dialog = ModifyDB(parent=None, db_file=str(database_path), modal=False)
        dialog.ensure_record_tables_loaded()
        return dialog

    # -- record tables: model/view implementation ------------------------------------
    @staticmethod
    def _column_for_label(model, label):
        for index, spec in enumerate(model.specs):
            if spec["label"] == label:
                return index
        raise KeyError(label)

    def set_record_cell(self, dialog, table_key, row, label, text):
        from PyQt6.QtCore import Qt

        model = getattr(dialog, RECORD_TABLE_ATTRS[table_key][0]).model()
        column = self._column_for_label(model, label)
        model.setData(model.index(row, column), text, Qt.ItemDataRole.EditRole)

    def apply_record_filter(self, dialog, table_key, text):
        getattr(dialog, RECORD_TABLE_ATTRS[table_key][0]).model().set_filter_text(text)

    def record_visible_keys(self, dialog, table_key):
        from PyQt6.QtCore import Qt

        attr, key_field = RECORD_TABLE_ATTRS[table_key]
        model = getattr(dialog, attr).model()
        key_column = self._column_for_label(model, key_field.upper())
        return [
            model.index(row, key_column).data(Qt.ItemDataRole.DisplayRole) for row in range(model.rowCount())
        ]

    # -- normalization tables: QTableWidget implementation (unchanged by #1118) ---------
    @staticmethod
    def set_normalize_cell(dialog, table_key, row, text):
        getattr(dialog, NORMALIZE_TABLE_ATTRS[table_key]).item(row, 1).setText(text)


def _table_widget(dialog, table_key):
    if table_key in NORMALIZE_TABLE_ATTRS:
        return getattr(dialog, NORMALIZE_TABLE_ATTRS[table_key])
    return getattr(dialog, RECORD_TABLE_ATTRS[table_key][0])


def _selected_rows(table):
    return sorted({index.row() for index in table.selectionModel().selectedRows()})


def _click_rows(dialog, table, anchor, target):
    from PyQt6.QtCore import Qt

    dialog._keyboard_modifiers = lambda: Qt.KeyboardModifier.NoModifier
    dialog._handle_table_cell_pressed(table, anchor, 0)
    dialog._keyboard_modifiers = lambda: Qt.KeyboardModifier.ShiftModifier
    dialog._handle_table_cell_pressed(table, target, 0)
    del dialog._keyboard_modifiers


def _run_op(dialog, driver, op, result):
    kind = op["op"]
    table_key = op.get("table")
    if kind == "set_cell":
        if table_key in NORMALIZE_TABLE_ATTRS:
            driver.set_normalize_cell(dialog, table_key, op["row"], op["text"])
        else:
            driver.set_record_cell(dialog, table_key, op["row"], op["column"], op["text"])
    elif kind == "select_range":
        table = _table_widget(dialog, table_key)
        _click_rows(dialog, table, op["anchor"], op["target"])
        result["selections"].append({"table": table_key, "rows": _selected_rows(table)})
    elif kind == "bulk_rename":
        table = _table_widget(dialog, table_key)
        _click_rows(dialog, table, op["anchor"], op["target"])
        dialog._focused_table_widget = lambda: table
        try:
            with patch(
                "metroliza.ui.modify_db.QtWidgets.QInputDialog.getText",
                return_value=(op["text"], True),
            ):
                dialog._handle_bulk_rename_shortcut()
        finally:
            del dialog._focused_table_widget
        result["selections"].append({"table": table_key, "rows": _selected_rows(table)})
    elif kind == "filter":
        driver.apply_record_filter(dialog, table_key, op["text"])
        result["filters"].append(
            {"table": table_key, "text": op["text"], "visible_keys": driver.record_visible_keys(dialog, table_key)}
        )
    elif kind == "checkpoint":
        result["checkpoints"][op["name"]] = bool(dialog.has_pending_changes())
    else:  # pragma: no cover - guards the golden data
        raise ValueError(f"unknown scenario op: {kind}")


def _json_normalized(value):
    return json.loads(json.dumps(value))


def _capture_confirmation_text(dialog):
    from PyQt6.QtWidgets import QMessageBox

    captured = []

    def fake_exec(message_box):
        captured.append(message_box.text())
        return QMessageBox.StandardButton.Cancel

    with patch.object(QMessageBox, "exec", fake_exec):
        dialog.confirm_and_apply_changes()
    return captured[0] if captured else None


def _dump_database(path, flavor):
    with closing(sqlite3.connect(path)) as connection:
        return {name: connection.execute(query).fetchall() for name, query in DUMP_QUERIES[flavor].items()}


def run_scenario(flavor, ops, driver, tmp_path):
    """Replay ``ops`` against a fresh synthetic database and return every observable result."""

    from PyQt6.QtWidgets import QMessageBox

    from metroliza.reports.report_edit_service import ReportEditService

    database_path = tmp_path / f"{flavor}.db"
    DATABASE_BUILDERS[flavor](database_path)
    dialog = driver.open_dialog(database_path)
    result = {"selections": [], "filters": [], "checkpoints": {}}
    try:
        for op in ops:
            _run_op(dialog, driver, op, result)

        normalization = {
            "reference": dialog.collect_normalization_value_changes(dialog.reference_table),
            "sample_number": dialog.collect_normalization_value_changes(dialog.part_number_table),
            "header": dialog.collect_normalization_value_changes(dialog.header_table),
        }
        report_updates = dialog.collect_report_record_updates()
        measurement_updates = dialog.collect_measurement_record_updates()
        statements = ReportEditService.build_normalization_update_statements(flavor, normalization)
        if flavor == "legacy":
            statements += ReportEditService.build_legacy_record_update_statements(
                report_updates, measurement_updates
            )

        result.update(
            {
                "pending": bool(dialog.has_pending_changes()),
                "summary": dialog.collect_modifications(),
                "confirmation_text": _capture_confirmation_text(dialog),
                "normalization_changes": normalization,
                "report_updates": report_updates,
                "measurement_updates": measurement_updates,
                "statements": statements,
            }
        )

        captured_payloads = []
        real_service = dialog._create_report_edit_service()

        class _RecordingService:
            def apply_changes(self, **payload):
                captured_payloads.append(payload)
                real_service.apply_changes(**payload)

        dialog._create_report_edit_service = lambda: _RecordingService()
        with patch.object(QMessageBox, "information", lambda *_args, **_kwargs: None):
            dialog.apply_changes()
        result["apply_payload"] = captured_payloads
        result["database_after_apply"] = _dump_database(database_path, flavor)
    finally:
        dialog._changes_committed = True
        dialog.close()
    return _json_normalized(result)


def load_golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _valid_legacy_scenario(scenario):
    """Retain the golden journey, changing only the forbidden MEAS edit and its search."""
    scenario = deepcopy(scenario)
    for op in scenario['ops']:
        if op.get('text') == 'bad':
            op['text'] = '10.3'
        elif op.get('text') == 'BAD':
            op['text'] = '10.3'
    expected = scenario['expected']
    for key in ('summary', 'confirmation_text'):
        expected[key] = expected[key].replace('"bad"', '"10.3"')
    for payload in (expected, expected['apply_payload'][0]):
        fields = next(fields for key, fields in payload['measurement_updates'] if key == 13)
        assert fields['meas'] == 'bad'
        fields['meas'] = 10.3
    for _statement, params in expected['statements']:
        if params == [None, 'bad', 13]:
            params[1] = 10.3
    measurement = next(row for row in expected['database_after_apply']['MEASUREMENTS'] if row[0] == 13)
    assert measurement[7] == 'bad'
    measurement[7] = 10.3
    for filtered in expected['filters']:
        if filtered['text'] == 'BAD':
            filtered['text'] = '10.3'
    return scenario


def _without_equivalent_numeric_edits(scenario):
    scenario = deepcopy(scenario)
    expected = scenario['expected']
    for label, record_id, field, value in (('NOM', 104, 'nominal', 10.0), ('DEV', 109, 'dev', -0.15)):
        redundant = f'Measurement rows.{label}: "{value}" -> "{value}" (MEASUREMENT_ID={record_id})\n'
        for key in ('summary', 'confirmation_text'):
            assert redundant in expected[key]
            expected[key] = expected[key].replace(redundant, '')
        for payload in (expected, expected['apply_payload'][0]):
            updates = payload['measurement_updates']
            assert [record_id, {field: value}] in updates
            updates.remove([record_id, {field: value}])
    return scenario


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["current", "current_reverted", "legacy"])
def test_record_edits_reproduce_pre_model_view_behaviour(name, tmp_path):
    pytest.importorskip("PyQt6")
    scenario = load_golden()["scenarios"][name]
    assert scenario["expected"], "golden file has no captured expectations"

    if name == "legacy":
        scenario = _valid_legacy_scenario(scenario)
    elif name == "current":
        scenario = _without_equivalent_numeric_edits(scenario)

    actual = run_scenario(scenario["flavor"], scenario["ops"], ScenarioDriver(), tmp_path)

    assert actual == scenario["expected"]


def test_legacy_invalid_measurement_rejects_entire_scenario(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui.modify_db import ModifyDB

    scenario = load_golden()['scenarios']['legacy']
    database = tmp_path / 'invalid-legacy.db'
    DATABASE_BUILDERS['legacy'](database)
    before = _dump_database(database, 'legacy')
    dialog = ModifyDB(db_file=str(database), modal=False)
    dialog.ensure_record_tables_loaded()
    errors = []
    monkeypatch.setattr(dialog, '_report_save_error', errors.append)
    try:
        for op in scenario['ops']:
            _run_op(dialog, ScenarioDriver(), op, {"selections": [], "filters": [], "checkpoints": {}})
        dialog.apply_changes()
        assert len(errors) == 1
        assert 'MEASUREMENT_ID=13, MEAS: Invalid number' in str(errors[0])
        assert _dump_database(database, 'legacy') == before
        assert dialog.has_pending_changes()
    finally:
        dialog._discard_confirmed = True
        dialog.close()


def test_golden_scenarios_exercise_every_edit_kind():
    golden = load_golden()
    seen = {(s["flavor"], op["op"], op.get("table")) for s in golden["scenarios"].values() for op in s["ops"]}
    for flavor in ("current", "legacy"):
        assert (flavor, "set_cell", "report_records") in seen
        assert (flavor, "set_cell", "measurement_records") in seen
        assert (flavor, "bulk_rename", "reference") in seen or (flavor, "bulk_rename", "header") in seen
        assert (flavor, "select_range", "measurement_records") in seen
        assert (flavor, "filter", "measurement_records") in seen
