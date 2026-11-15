"""Real synthetic PDF → SQLite → workbook/dashboard, with a literal SQL oracle."""
import pymupdf
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from metroliza.recipes.report_ports import ReportsRecipeService
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import (
    REPORTS_DASHBOARD_HTML, REPORTS_EXCEL_MAIN, builtin_binding,
)
from metroliza.recipes.run_state import RunState
from metroliza.recipes.runner import RecipeRunner
from metroliza.ui.recipe_execution_adapter import RecipeExecutionAdapter


def _write_complete_reports(source):
    source.mkdir()
    fixtures = Path(__file__).parent / "fixtures/windows_candidate/reports"
    for index in range(5):
        # Authored structured metadata makes this a complete positive fixture;
        # the minimal parser-smoke PDFs intentionally require metadata review.
        with pymupdf.open(fixtures / f"report-{index}.pdf") as document:
            page = document[0]
            for text, x, y in (("PART NAME", 150, 16), ("Recipe Part", 208, 16),
                               ("DRAWING No", 296, 46), ("ABCDE12345", 358, 46),
                               ("DRAWING REV", 167, 46), ("D.01", 232, 46)):
                page.insert_text((x, y), text, fontsize=6)
            page.insert_text((20, 62), f"SAMPLE NUMBER: {index}", fontsize=6)
            document.save(source / f"ABCDE12345_Recipe_Part_2024-01-01_{index}.pdf")


@pytest.mark.parametrize("definition,suffix", [
    (REPORTS_EXCEL_MAIN, ".xlsx"), (REPORTS_DASHBOARD_HTML, ".html"),
])
def test_real_microflow_numeric_and_output_contract(tmp_path, definition, suffix):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "reports"
    _write_complete_reports(source)
    output = tmp_path / ("Pomiar" + suffix)
    plan = resolve_plan(definition, builtin_binding(definition, str(source), str(output)))
    runner = RecipeRunner(ReportsRecipeService(
        RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export"),
    ))
    try:
        record = runner.start(plan)
        assert record.state in (RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS), record
        assert plan.database_file == tmp_path / "Pomiar.db"
        with closing(sqlite3.connect(str(plan.database_file))) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone() == (5,)
            measurements = connection.execute("SELECT meas FROM report_measurements").fetchall()
            assert len(measurements) == 5
            assert [row[0] for row in measurements] == pytest.approx([10.02] * 5)
        if suffix == ".xlsx":
            with zipfile.ZipFile(output) as archive:
                assert archive.testzip() is None
                assert "xl/workbook.xml" in archive.namelist()
                assert any(name.startswith("xl/charts/chart") for name in archive.namelist())
        else:
            document = output.read_text(encoding="utf-8")
            assert "<html" in document.lower()
            assert "plotly" in document.lower()
            assert not output.with_suffix(".xlsx").exists()
        assert app is QApplication.instance()
    finally:
        runner.cancel()


def test_larger_saved_flow_uses_same_snapshot_and_real_outputs(tmp_path):
    from metroliza.recipes.contracts import ParameterKey
    from metroliza.recipes.editor_service import RecipeEditorService
    from metroliza.recipes.storage import RecipeStore, StoredRecipe

    app = QApplication.instance() or QApplication([])
    source = tmp_path / "reports"
    _write_complete_reports(source)
    editor = RecipeEditorService(StoredRecipe(REPORTS_EXCEL_MAIN,
        builtin_binding(REPORTS_EXCEL_MAIN, str(source), str(tmp_path / "Larger.xlsx"))))
    editor.duplicate("Synthetic larger flow")
    editor.configure_reports(dates=True, grouping_columns=("REFERENCE",), additional_html=True)
    editor.set_value(ParameterKey.DATE_FROM, "2024-01-01")
    editor.set_value(ParameterKey.DATE_TO, "2024-01-01")
    store = RecipeStore(tmp_path / "private")
    saved = editor.save(store)
    reopened = RecipeStore(tmp_path / "private").load(saved.definition.recipe_id)
    plan = resolve_plan(reopened.definition, reopened.binding)
    editor.set_value(ParameterKey.OUTPUT_FILE, str(tmp_path / "Future.xlsx"))
    assert plan.output_file == tmp_path / "Larger.xlsx"
    runner = RecipeRunner(ReportsRecipeService(
        RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export")))
    try:
        record = runner.start(plan)
        assert record.state in (RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS), record
        assert (tmp_path / "Larger.xlsx").is_file()
        assert (tmp_path / "Larger.html").is_file()
        assert not (tmp_path / "Future.xlsx").exists()
        with closing(sqlite3.connect(str(plan.database_file))) as connection:
            # Independent literal fixture range, rather than the product query builder.
            rows = connection.execute("SELECT meas FROM report_measurements").fetchall()
            assert [row[0] for row in rows] == pytest.approx([10.02] * 5)
        assert app is QApplication.instance()
    finally:
        runner.cancel()
