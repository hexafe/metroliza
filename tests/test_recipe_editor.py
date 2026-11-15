"""Typed capture and editor roundtrip controls, independent of widget history."""
from dataclasses import asdict, replace
import json
import sqlite3

import pytest

from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest, validate_export_request
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
from metroliza.recipes.contracts import ParameterKey, ParameterMode, RecipeError, StepKind
from metroliza.recipes.editor_service import RecipeEditorService
from metroliza.recipes.storage import RecipeStore, copy_recipe
from metroliza.recipes.report_configuration_adapter import (
    build_export_request, capture_export_configuration,
)
from metroliza.reports.report_query_service import build_measurement_filter_query
from metroliza.shared.filter_state import FilterState
from metroliza.tabular.contracts import GroupingAssignment


def manual_request(tmp_path, *, state=None, grouping=None):
    options = ExportOptions(preset="full_report", violin_plot_min_samplesize=12,
                            generate_summary_sheet=True, chart_worker_count=2)
    request = ExportRequest(AppPaths(str(tmp_path / "source.db"), str(tmp_path / "result.xlsx")),
        options, build_measurement_filter_query(**asdict(state)) if state else None, grouping)
    return validate_export_request(request)


def test_capture_reopen_keeps_all_actual_export_options_and_filter_semantics(tmp_path):
    state = FilterState(reference_values=("PRIVATE_REFERENCE",), date_from="2020-01-01",
                        date_to="2020-12-31", has_nok_only=True)
    manual = manual_request(tmp_path, state=state)
    captured = capture_export_configuration(manual, filter_state=state)
    store = RecipeStore(tmp_path / "private")
    saved = store.save(captured.definition, captured.binding, expected_revision=None)
    reopened = store.load(saved.definition.recipe_id)
    plan = resolve_plan(reopened.definition, reopened.binding)
    actual = build_export_request(plan, StepKind.EXPORT_MAIN)
    assert actual.options == manual.options
    assert actual.filter_query == manual.filter_query
    assert actual.replace_outputs == ()
    assert "PRIVATE_REFERENCE" not in repr(captured.definition)


def test_raw_sql_and_manual_membership_never_silently_dropped(tmp_path):
    with pytest.raises(RecipeError, match="filter_capture_requires_typed_state"):
        capture_export_configuration(replace(manual_request(tmp_path), filter_query="SELECT 1"))
    with pytest.raises(RecipeError, match="manual_membership_not_portable"):
        capture_export_configuration(manual_request(tmp_path,
            grouping=(GroupingAssignment("Private", report_id=3),)))


def test_builtin_copy_extended_flow_and_runtime_modes_survive_save(tmp_path):
    copied = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(tmp_path / "input"), str(tmp_path / "result.xlsx")), name="Local")
    editor = RecipeEditorService(copied)
    editor.configure_reports(dates=True, grouping_columns=("REFERENCE",), additional_html=True)
    editor.set_value(ParameterKey.DATE_FROM, "2020-01-01")
    editor.set_value(ParameterKey.DATE_TO, "2020-12-31")
    editor.set_mode(ParameterKey.DATE_FROM, ParameterMode.PROMPT)
    snapshot = editor.preview()
    editor.rename("Changed during execution")
    editor.set_value(ParameterKey.DATE_FROM, "2021-01-01")
    assert snapshot.value(ParameterKey.DATE_FROM) == "2020-01-01"
    assert snapshot.binding.name == "Local"
    store = RecipeStore(tmp_path / "private")
    saved = editor.save(store)
    reopened = RecipeEditorService(store.load(saved.definition.recipe_id))
    assert reopened.current == saved
    assert [s.kind for s in saved.definition.steps] == [StepKind.PREPARE_DATABASE,
        StepKind.IMPORT_REPORTS, StepKind.FILTER, StepKind.GROUP, StepKind.EXPORT_MAIN,
        StepKind.EXPORT_HTML, StepKind.VERIFY_OUTPUT]
    assert REPORTS_EXCEL_MAIN.steps[-2].kind is StepKind.EXPORT_MAIN


def test_unknown_group_column_blocks_without_partial_editor_mutation(tmp_path):
    copied = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN), name="Local")
    editor = RecipeEditorService(copied)
    previous = editor.current
    with pytest.raises(RecipeError, match="unsupported_grouping_rule"):
        editor.configure_reports(dates=True, grouping_columns=("RAW_REPORT_ID",), additional_html=True)
    assert editor.current == previous


def test_configured_filter_matches_independent_sql_oracle(tmp_path):
    state = FilterState(reference_values=("A",), date_from="2020-01-01", date_to="2020-12-31")
    captured = capture_export_configuration(manual_request(tmp_path, state=state), filter_state=state)
    actual = build_export_request(resolve_plan(captured.definition, captured.binding), StepKind.EXPORT_MAIN)
    # Inspect the shared query's WHERE against independent row-wise truth, rather
    # than comparing capture and execution via the same helper as sole oracle.
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE candidate(reference TEXT, report_date TEXT)")
        fixtures = [("A", "2020-06-01"), ("B", "2020-06-01"), ("A", "2021-01-01")]
        connection.executemany("INSERT INTO candidate VALUES (?, ?)", fixtures)
        where = actual.filter_query.split(" WHERE ", 1)[1]
        result = connection.execute("SELECT reference, report_date FROM candidate WHERE " + where).fetchall()
        expected = [row for row in fixtures if row[0] == "A" and "2020-01-01" <= row[1] <= "2020-12-31"]
        assert result == expected
    finally:
        connection.close()


def test_configuration_json_unknown_field_is_rejected(tmp_path):
    captured = capture_export_configuration(manual_request(tmp_path))
    plan = resolve_plan(captured.definition, captured.binding)
    values = dict(plan.binding.values)
    raw = json.loads(values[ParameterKey.EXPORT_OPTIONS])
    raw["arbitrary_sql"] = "SELECT 1"
    values[ParameterKey.EXPORT_OPTIONS] = json.dumps(raw)
    malformed = replace(plan, binding=replace(plan.binding, values=tuple(values.items())))
    with pytest.raises(RecipeError, match="unsupported_configuration_fields"):
        build_export_request(malformed, StepKind.EXPORT_MAIN)


def test_editor_dirty_close_cancel_then_discard_emits_finished(qapplication_session, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from metroliza.ui.recipe_editor import RecipeEditor
    copied = copy_recipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN), name="Private")
    dialog = RecipeEditor(copied, RecipeStore(tmp_path / "private"))
    finished = []
    dialog.finished.connect(finished.append)
    dialog.show()
    dialog.name.setText("Unsaved")
    dialog._mark_modified()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel)
    assert not dialog.close()
    assert dialog.isVisible() and not finished
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Discard)
    assert dialog.close()
    assert not dialog.isVisible() and len(finished) == 1
    assert not dialog._widgets_dirty and not dialog.service.modified
