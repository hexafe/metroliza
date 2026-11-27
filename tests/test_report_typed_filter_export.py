from contextlib import closing
from dataclasses import replace
import sqlite3

from openpyxl import load_workbook
import pytest

from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
from metroliza.exporting.export_data_thread import ExportDataThread
from metroliza.reports.db import QueryScope
from metroliza.reports.report_query_service import build_measurement_filter_query
from metroliza.reports.report_repository import ReportRepository
from metroliza.reports.report_schema import ensure_report_schema, is_report_schema_ready
from metroliza.reports.report_typed_filter import (
    ReportTypedViewError,
    prepare_report_typed_filter,
    preview_report_typed_filter,
)
from metroliza.shared.filter_state import FilterState
from metroliza.shared.typed_filter import FilterValidationError
from tests.test_1089_acceptance_analytics import _persist_report


@pytest.fixture
def report_database(tmp_path):
    database = tmp_path / "typed-report.sqlite"
    ensure_report_schema(str(database))
    repository = ReportRepository(str(database))
    for number, ref, header in (
        (1, "001", "Width"), (2, "1", "Width"), (3, "001", "Height"),
        (4, "001", "Width"), (5, "001", "Width"),
    ):
        _persist_report(repository, tmp_path, number=number, reference=ref, header=header)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE parsed_reports SET has_nok = 1 WHERE id IN (1, 2, 3, 4)")
        connection.execute("UPDATE report_metadata SET report_date = '2024-01-01' WHERE report_id = 5")
    return database


@pytest.fixture
def filter_state():
    return FilterState(
        header_values=("Width",), date_from="2024-01-01", date_to="2024-01-03",
        has_nok_only=True, expression_text='Ref IN ("001")',
    )


def _request(database, output, scope):
    return ExportRequest(
        AppPaths(str(database), str(output)), ExportOptions(chart_worker_count=1),
        typed_report_scope=scope,
    )


def test_report_typed_preview_and_real_xlsx_use_one_bound_scope(report_database, filter_state, tmp_path):
    snapshot = report_database.read_bytes()
    scope = prepare_report_typed_filter(report_database, filter_state)
    assert scope.query.params[:3] == ("Width", "2024-01-01", "2024-01-03")
    assert all(value not in scope.query.sql for value in ("Width", "2024-01-01", "001"))
    preview = preview_report_typed_filter(scope)
    assert preview.matching_count == 1
    assert [(row[0], row[1]) for row in preview.rows] == [(1, "001")]

    with closing(sqlite3.connect(report_database)) as connection:
        legacy = build_measurement_filter_query(
            header_values=filter_state.header_values, date_from=filter_state.date_from,
            date_to=filter_state.date_to, has_nok_only=True, expression_text=filter_state.expression_text,
        )
        assert [row[:3] for row in connection.execute(legacy)] == [(1, 1, "001"), (2, 2, "1")]

    output = tmp_path / "typed-export.xlsx"
    ExportDataThread(replace(_request(report_database, output, scope), filter_description="Wrong description")).run()
    workbook = load_workbook(output, read_only=True)
    try:
        headings, *rows = workbook["MEASUREMENTS"].values
        assert [(row[headings.index("MEASUREMENT_ID")], row[headings.index("REFERENCE")]) for row in rows] == [
            (1, "001")
        ]
        filters = [value for label, value in workbook["REPORT SCOPE"].values if label == "Filters"]
        assert filters[0] == "Typed filter"
        assert 'Expression: Ref IN ("001")' in filters and "Header: Width" in filters
    finally:
        workbook.close()
    assert report_database.read_bytes() == snapshot


def test_typed_report_unknown_field_and_operator_and_unavailable_schema(report_database, tmp_path):
    with pytest.raises(FilterValidationError, match="Nominal"):
        prepare_report_typed_filter(report_database, FilterState(expression_text="Nominal = 1"))
    with pytest.raises(FilterValidationError, match="unavailable"):
        prepare_report_typed_filter(report_database, FilterState(expression_text="Reference > 1"))
    database = tmp_path / "unavailable-schema.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE no_reports(id INTEGER)")
    scope = prepare_report_typed_filter(database, FilterState(expression_text="Ref = 001"))
    with pytest.raises(ReportTypedViewError, match="standard Reports measurement view"):
        preview_report_typed_filter(scope)


def test_typed_report_preview_caps_the_ordered_prefix(report_database):
    with closing(sqlite3.connect(report_database)) as connection, connection:
        connection.execute("UPDATE report_metadata SET report_date = '2026-01-01' WHERE report_id = 1")
        connection.executemany(
            "INSERT INTO report_measurements (id, report_id, row_order, status_code) VALUES (?, 1, ?, 'ok')",
            ((index, index) for index in range(29, 5, -1)),
        )
    scope = prepare_report_typed_filter(report_database, FilterState(expression_text="Date = 2026-01-01"))
    preview = preview_report_typed_filter(scope)
    assert preview.matching_count == 25
    assert [row[0] for row in preview.rows] == [1, *range(6, 25)]


def test_typed_report_counts_and_samples_in_the_same_read_snapshot(report_database, filter_state, monkeypatch):
    from metroliza.reports import report_typed_filter

    read_sample = report_typed_filter.read_query_scope_result

    def assert_snapshot_started(*args, connection, **kwargs):
        assert connection.in_transaction
        return read_sample(*args, connection=connection, **kwargs)

    monkeypatch.setattr(report_typed_filter, "read_query_scope_result", assert_snapshot_started)
    scope = prepare_report_typed_filter(report_database, filter_state)
    assert preview_report_typed_filter(scope).matching_count == 1


@pytest.mark.parametrize("failure", ["changed_database", "snapshot", "changed_view"])
def test_typed_report_snapshot_failure_retains_existing_xlsx(report_database, filter_state, tmp_path, failure,
                                                             monkeypatch):
    if failure == "changed_view":
        with closing(sqlite3.connect(report_database)) as connection, connection:
            canonical = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE name = 'vw_measurement_export'",
            ).fetchone()[0]
            altered = canonical.replace("rm.reference AS reference,", "rm.part_name AS reference,")
            assert altered != canonical
            connection.execute("DROP VIEW vw_measurement_export")
            connection.execute(altered)
            assert is_report_schema_ready(connection)
            assert connection.execute(
                "SELECT reference, typeof(reference) FROM vw_measurement_export WHERE measurement_id = 1",
            ).fetchone() == ("Part 1", "text")
    scope = prepare_report_typed_filter(report_database, filter_state)
    if failure == "changed_view":
        with pytest.raises(ReportTypedViewError, match="Restore an intact Reports database"):
            preview_report_typed_filter(scope)
    output = tmp_path / "existing.xlsx"
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active["A1"] = "Existing workbook"
    workbook.save(output)
    workbook.close()
    before = output.read_bytes()
    worker = ExportDataThread(_request(report_database, output, scope))
    if failure == "snapshot":
        def fail_snapshot_index(_table_name):
            worker.export_canceled = True
            raise sqlite3.OperationalError("Synthetic failure preparing the snapshot index")

        monkeypatch.setattr(worker, "_index_export_snapshot", fail_snapshot_index)
    backend_calls = []
    backend = worker.get_export_backend
    monkeypatch.setattr(worker, "get_export_backend", lambda: backend_calls.append(True) or backend())
    if failure == "changed_database":
        with closing(sqlite3.connect(report_database)) as connection, connection:
            connection.execute("UPDATE report_metadata SET reference = 'changed' WHERE report_id = 1")
    errors = []
    worker.error_occurred.connect(errors.append)
    worker.run()
    assert errors
    if failure == "changed_view":
        assert "Restore an intact Reports database" in errors[0]
    assert backend_calls == []
    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".xlsx-package-*"))


def test_typed_report_contract_rejects_conflicting_or_unsupported_paths(report_database, filter_state, tmp_path):
    scope = prepare_report_typed_filter(report_database, filter_state)
    with pytest.raises(ValueError, match="init=False"):
        replace(scope, query=QueryScope("SELECT 1"))
    request = _request(report_database, tmp_path / "typed.xlsx", scope)
    for unsupported in (
        replace(request, filter_query="SELECT 1"),
        replace(request, options=replace(request.options, generate_html_dashboard=True)),
        replace(request, options=replace(request.options, include_industrial_context=True)),
        replace(request, options=replace(request.options, preset="full_report")),
    ):
        with pytest.raises(ValueError, match="Main plots"):
            ExportDataThread(unsupported)


def test_typed_snapshot_interrupt_cancels_without_replacing_workbook(
    report_database, filter_state, tmp_path, monkeypatch,
):
    from contextlib import contextmanager

    from metroliza.reports import db

    scope = prepare_report_typed_filter(report_database, filter_state)
    output = tmp_path / "previous.xlsx"
    output.write_bytes(b"previous workbook bytes")
    worker = ExportDataThread(_request(report_database, output, scope))
    error_codes, failures, cancelled = [], [], []

    class InterruptProbe(sqlite3.Connection):
        def set_progress_handler(self, handler, operations):
            if handler is not None:
                worker.export_canceled = True
                operations = 1
            return super().set_progress_handler(handler, operations)

        def execute(self, *args, **kwargs):
            try:
                return super().execute(*args, **kwargs)
            except sqlite3.OperationalError as error:
                error_codes.append(error.sqlite_errorcode)
                raise

    @contextmanager
    def read_only_scope(_database, **_options):
        uri = report_database.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, factory=InterruptProbe)) as connection:
            yield connection

    monkeypatch.setattr(db, "sqlite_readonly_connection_scope", read_only_scope)
    worker.error_occurred.connect(failures.append)
    worker.canceled.connect(lambda: cancelled.append(True))
    worker.run()
    assert error_codes == [sqlite3.SQLITE_INTERRUPT]
    assert cancelled == [True] and failures == []
    assert output.read_bytes() == b"previous workbook bytes"


def test_normal_export_dialog_applies_the_previewed_scope(report_database, tmp_path, monkeypatch):
    from PyQt6.QtTest import QTest
    from metroliza.ui.filter_dialog import FilterDialog
    from tests.test_export_dialog_behavior import _build_dialog

    monkeypatch.setattr(FilterDialog, "populate_list_widgets", lambda self: None)
    results = []
    native_sender_lookups = []
    monkeypatch.setattr(FilterDialog, "sender", lambda self: native_sender_lookups.append(True))
    monkeypatch.setattr(FilterDialog, "_show_typed_preview", lambda self, preview: results.append(preview))
    dialog = _build_dialog(monkeypatch, tmp_path, db_file=str(report_database))
    dialog.excel_file = tmp_path / "ui-export.xlsx"
    try:
        dialog.open_filter_window()
        editor = dialog.filter_window
        assert editor.typed_mode_button.isEnabled()
        editor.typed_mode_button.click()
        editor.expression_input.setText("Reference > 1")
        editor.typed_preview_button.click()
        assert "Operator" in editor.filter_summary_label.text()
        assert not editor.apply_button.isEnabled()
        expression = 'Ref = "001"'
        editor.expression_input.setText(expression)
        editor.typed_preview_button.click()
        editor.typed_preview_button.click()
        QTest.qWait(20)
        assert not results and editor._typed_preview_loader is None
        assert "canceled" in editor.filter_summary_label.text()
        editor.typed_preview_button.click()
        for _ in range(200):
            if results:
                break
            QTest.qWait(10)
        assert results and all(row[1] == "001" for row in results[0].rows)
        QTest.qWait(20)
        preview_status = editor.filter_summary_label.text()
        previewed = editor._typed_preview_scope
        editor.expression_input.setText('Ref = "1"')
        assert not editor.apply_button.isEnabled()
        assert editor.apply_filters() is False
        editor.expression_input.setText(expression)
        assert editor.apply_filters()
        request = dialog._build_export_request()
        assert request.typed_report_scope is previewed and request.filter_query is None
        assert "Typed" in dialog.select_filter_label.text()
        ExportDataThread(request).run()
        workbook = load_workbook(request.paths.excel_file, read_only=True)
        try:
            headings, *rows = workbook["MEASUREMENTS"].values
            assert [row[headings.index("MEASUREMENT_ID")] for row in rows] == [row[0] for row in results[0].rows]
        finally:
            workbook.close()
        with pytest.raises(ValueError, match="before saving a recipe"):
            dialog._build_recipe_export_request()
        dialog.generate_html_dashboard_checkbox.setChecked(True)
        with pytest.raises(ValueError, match="Main plots"):
            dialog._build_export_request()
    finally:
        dialog.close()
    assert native_sender_lookups == []
    assert "matching measurements" in preview_status
