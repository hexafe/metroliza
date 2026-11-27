from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3

from openpyxl import load_workbook
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog, QPushButton
import pytest

from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
from metroliza.exporting.export_data_thread import ExportDataThread
from metroliza.reports import report_grouping_rules as rules
from metroliza.reports.report_query_service import build_measurement_filter_query
from metroliza.reports.report_repository import ReportRepository
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.ui.report_grouping_rules_dialog import ReportGroupingRulesDialog
from tests.test_1089_acceptance_analytics import _persist_report
from tests.test_export_dialog_behavior import _build_dialog


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "reports.sqlite"
    ensure_report_schema(str(path))
    repository = ReportRepository(str(path))
    for number, reference, header in ((1, "001", "Width"), (2, "1", "Width"), (3, "001", "Height"),
                                      (4, "001", "Width"), (5, "001", "Width")):
        _persist_report(repository, tmp_path, number=number, reference=reference, header=header)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE report_metadata SET report_date = '2024-01-05' WHERE report_id = 4")
        connection.execute("DELETE FROM report_measurements WHERE report_id = 5")
    return path


@pytest.fixture
def selection():
    return build_measurement_filter_query(header_values=("Width",), date_to="2024-01-03")


def _rule(number, label, expression):
    return rules.ReportGroupRule(f"{number:032x}", label, "#DAE9F6", expression)


def test_preset_round_trip_retains_order_ids_text_and_style():
    original = rules.ReportGroupingPreset("Supplier drops", (
        _rule(3, "Case 001", 'Reference = "001"'),
        replace(_rule(4, "Date-based", "Date >= 2024-01-02"), color="#1AaF55"),
    ))
    raw = rules.dump_grouping_preset(original)
    assert rules.load_grouping_preset(raw) == original
    assert json.loads(raw)["groups"][0]["filter"]["expression"]["values"] == ["001"]
    assert {item["id"] for item in json.loads(raw)["groups"]} == {item.group_id for item in original.rules}


@pytest.mark.parametrize("damage", ["future", "field", "type", "drift", "id", "name", "color", "extra"])
def test_incompatible_files_fail_before_application(damage):
    original = rules.ReportGroupingPreset("Supplier", (_rule(1, "Case 001", 'Reference = "001"'),))
    document = json.loads(rules.dump_grouping_preset(original))
    item = document["groups"][0]
    predicate = item["filter"]["expression"]
    match damage:
        case "future":
            document["version"] = 101
        case "field":
            predicate["field"] = "removed"
        case "type":
            predicate["kind"] = "number"
        case "drift":
            item["expression"] = 'Reference = "1"'
        case "id":
            document["groups"].append({**item, "label": "Different"})
        case "name":
            document["groups"].append({**item, "id": "2" * 32, "label": "case 001"})
        case "color":
            item["color"] = "<b>unsafe</b>"
        case "extra":
            item["sql"] = "ignored?"
    with pytest.raises(ValueError, match="unsupported|incompatible|differ|duplicate|hexadecimal"):
        rules.load_grouping_preset(json.dumps(document).encode())


def test_invalid_json_and_oversized_file_have_actionable_errors():
    with pytest.raises(ValueError, match="duplicate"):
        rules.load_grouping_preset(b'{"version": 1, "version": 1}')
    with pytest.raises(ValueError, match="64 KiB"):
        rules.load_grouping_preset(b" " * (rules.MAX_PRESET_BYTES + 1))
    with pytest.raises(ValueError, match="valid UTF-8"):
        rules.load_grouping_preset(b"[" * 2_000)


def test_report_grain_preview_counts_overlap_and_unassigned_uses_export_scope(database, selection):
    before = database.read_bytes()
    overlap = rules.ReportGroupingPreset("Suppliers", (
        _rule(1, "First", 'Reference = "001"'),
        _rule(2, "Second", 'Reference IN ("001", "bad") AND Date <= 2024-01-03'),
    ))
    source = rules.ReportGroupingSource.capture(database, selection)
    preview = rules.preview_grouping_preset(overlap, source)
    assert preview.counts == (("First", 1), ("Second", 1))
    assert (preview.overlap_count, preview.overlap_sample) == (1, (1,))
    assert (preview.unassigned_count, preview.unassigned_sample) == (1, (2,))
    assert preview.assignments == ()
    assert sorted(row[0] for row in rules.ReportGroupingSource.capture(database, None).read_rows()) == [1, 2, 3, 4]
    assert database.read_bytes() == before


def test_preview_rejects_oversized_or_changed_reports_scope(database, selection, monkeypatch):
    preset = rules.ReportGroupingPreset("Suppliers", (_rule(1, "First", 'Reference = "001"'),))
    with monkeypatch.context() as patch:
        patch.setattr(rules, "MAX_REPORTS", 1)
        with pytest.raises(ValueError, match="up to 1 reports"):
            rules.preview_grouping_preset(preset, rules.ReportGroupingSource.capture(database, selection))
    with closing(sqlite3.connect(database)) as connection, connection:
        view = connection.execute("SELECT sql FROM sqlite_schema WHERE name = 'vw_measurement_export'").fetchone()[0]
        connection.execute("DROP VIEW vw_measurement_export")
        connection.execute(view.replace("rm.reference AS reference", "rm.part_name AS reference"))
    with pytest.raises(ValueError, match="standard Reports measurement view"):
        rules.preview_grouping_preset(preset, rules.ReportGroupingSource.capture(database, selection))


def test_foreground_rule_work_stops_when_budget_is_exhausted(database, selection, monkeypatch):
    preset = rules.ReportGroupingPreset("Suppliers", (_rule(1, "First", 'Reference = "001"'),))
    source = rules.ReportGroupingSource.capture(database, selection)
    rows = source.read_rows()
    monkeypatch.setattr(rules.ReportGroupingSource, "read_rows", lambda *_, **kwargs: rows)
    ticks = iter((0.0, rules.PREVIEW_SECONDS + 0.1))
    monkeypatch.setattr(rules, "monotonic", lambda: next(ticks))
    with pytest.raises(ValueError, match="took too long"):
        rules.preview_grouping_preset(preset, source)


def _click(editor, label):
    next(button for button in editor.findChildren(QPushButton) if button.text() == label).click()


def test_report_grouping_rules_save_reopen_and_export_real_outputs(database, selection, tmp_path, monkeypatch):
    # Use the normal Grouping button and opened rule editor with offscreen file choosers.
    export = _build_dialog(monkeypatch, tmp_path, db_file=str(database))
    export.excel_file = str(tmp_path / "report-with-groups.xlsx")
    export.set_filter_query(selection)
    preset_file = tmp_path / "suppliers.json"
    edit_results = []

    def edit(dialog):
        dialog.name_input.setText("Suppliers")
        dialog.rules_table.item(0, 0).setText("Reference 001")
        dialog.rules_table.item(0, 2).setText('Reference = "001"')
        initial_id = dialog.rules_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        _click(dialog, "Save preset…")
        assert preset_file.is_file()
        _click(dialog, "Preview")
        assert not dialog.apply_button.isEnabled()
        dialog.default_checkbox.setChecked(True)
        assert dialog.apply_button.isEnabled()
        dialog.rules_table.item(0, 2).setText('Reference = "1"')
        assert not dialog.apply_button.isEnabled()
        _click(dialog, "Open preset…")
        assert dialog.rules_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == initial_id
        assert not dialog.default_checkbox.isChecked()
        assert not dialog.apply_button.isEnabled()
        _click(dialog, "Preview")
        assert "Unassigned · 1" in dialog.preview_output.toPlainText()
        dialog.default_checkbox.setChecked(True)
        _click(dialog, "Use rule grouping")
        edit_results.append(dialog.accepted_preview)
        return dialog.result()

    monkeypatch.setattr(ReportGroupingRulesDialog, "exec", edit)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(preset_file), ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: (str(preset_file), ""))
    try:
        export.open_grouping_window()
        grouping = export.grouping_window
        for _ in range(200):
            if not grouping.is_loading_grouping():
                break
            QTest.qWait(10)
        assert grouping.grouping_rules_button.isEnabled()
        grouping.grouping_rules_button.click()
        preview, = edit_results
        assert [(assignment.report_id, assignment.group) for assignment in preview.assignments] == [
            (1, "Reference 001"), (2, "POPULATION"),
        ]
        request = export._build_export_request()
        assert request.grouping_df == preview.assignments
        assert request.filter_query == selection
        assert request.grouping_rule_source is preview.source
        with pytest.raises(ValueError, match="grouping preset"):
            export._build_recipe_export_request()

        export.open_grouping_window()
        assert export.grouping_window.df.loc[export.grouping_window.df["REPORT_ID"] == 1, "GROUP"].tolist() == [
            "Reference 001"
        ]
        export.grouping_window.use_grouping()
        assert export._build_export_request().grouping_rule_source is preview.source

        worker = ExportDataThread(request)
        original_join = worker._apply_group_assignments
        consumed = set()

        def capture(*args, **kwargs):
            merged, applied = original_join(*args, **kwargs)
            if applied:
                consumed.update(zip(merged["REPORT_ID"], merged["GROUP"]))
            return merged, applied

        monkeypatch.setattr(worker, "_apply_group_assignments", capture)
        failures = []
        worker.error_occurred.connect(failures.append)
        source_bytes = database.read_bytes()
        worker.run()
        assert not failures
        assert database.read_bytes() == source_bytes
        assert consumed == {(1, "Reference 001"), (2, "POPULATION")}
        workbook = load_workbook(export.excel_file, read_only=True)
        try:
            headings, *rows = workbook["MEASUREMENTS"].values
            assert {row[headings.index("REPORT_ID")] for row in rows} == {1, 2}
            assert any("Reference 001" in str(value) for label, value in workbook["REPORT SCOPE"].values
                       if label == "Grouping")
        finally:
            workbook.close()
        html = Path(worker.html_dashboard_file)
        assert html.is_file()
        assert "Reference 001" in html.read_text(encoding="utf-8")
        export.set_filter_query(build_measurement_filter_query(header_values=("Height",)))
        with pytest.raises(ValueError, match="Preview grouping rules again"):
            export._build_export_request()
    finally:
        export.close()


@pytest.mark.parametrize("change", ["report", "same_stat", "view"])
def test_rule_snapshot_stale_before_worker_preserves_old_workbook(database, selection, tmp_path, change):
    preset = rules.ReportGroupingPreset("Suppliers", (_rule(1, "First", 'Reference = "001"'),))
    preview = rules.preview_grouping_preset(preset, rules.ReportGroupingSource.capture(database, selection))
    output = tmp_path / "existing.xlsx"
    output.write_bytes(b"past workbook")
    worker = ExportDataThread(ExportRequest(
        AppPaths(str(database), str(output)), ExportOptions(chart_worker_count=1),
        filter_query=selection, grouping_df=preview.assignments, grouping_rule_source=preview.source,
    ))
    prior_stat = database.stat()
    with closing(sqlite3.connect(database)) as connection, connection:
        if change == "view":
            connection.execute("DROP VIEW vw_measurement_export")
            connection.execute("CREATE VIEW vw_measurement_export AS SELECT 1 AS wrong_column")
        else:
            connection.execute("UPDATE report_metadata SET reference = '1' WHERE report_id = 1")
    if change == "same_stat":
        assert database.stat().st_size == prior_stat.st_size
        os.utime(database, ns=(prior_stat.st_atime_ns, prior_stat.st_mtime_ns))
        preview.source.require_current(database, selection, exact_stamp=True)
    errors = []
    worker.error_occurred.connect(errors.append)
    worker.run()
    assert errors and "Preview grouping rules again" in str(errors[0])
    assert output.read_bytes() == b"past workbook"
