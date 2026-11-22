"""Real synthetic PDF → SQLite → workbook/dashboard, with a literal SQL oracle."""
import pymupdf
import shutil
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from metroliza.recipes.report_ports import ReportsRecipeService
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import (
    REPORTS_APPEND_EXCEL_MAIN, REPORTS_DASHBOARD_HTML, REPORTS_EXCEL_MAIN, builtin_binding,
)
from metroliza.recipes.contracts import ParameterKey, StepKind
from metroliza.recipes.ports import PreparationPhase, ResultCode
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
def test_real_microflow_numeric_and_output_contract(tmp_path, definition, suffix, qapplication_session):
    from metroliza.recipes.contracts import StepKind
    from metroliza.recipes.diagnostics import safe_run_projection

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
            html = next(step.result for step in record.steps if step.kind is StepKind.EXPORT_HTML)
            assets = Path(html.dashboard_assets_path)
            assert assets.is_dir() and assets.parent == output.parent
            assert assets.name + "/" in document
            assert assets.name not in str(safe_run_projection(record))
            assert not output.with_suffix(".xlsx").exists()
        assert app is QApplication.instance()
    finally:
        runner.cancel()


@pytest.mark.parametrize("mode,expected_ocr", [("light", 0), ("complete", 1)])
def test_reviewed_image_import_uses_one_recheck_and_keeps_metadata(
        tmp_path, qapplication_session, monkeypatch, mode, expected_ocr):
    from dataclasses import replace
    from metroliza.parsing.cmm_report_parser import CMMReportParser
    from metroliza.parsing.preflight import ParsePreflightService
    from tests.test_metadata_review_core import FAKE_OCR_ITEMS

    source = tmp_path / "reports"
    source.mkdir()
    fixture = Path(__file__).parent / "fixtures/windows_candidate_ocr/image-header-only.pdf"
    shutil.copyfile(fixture, source / "image.pdf")
    binding = builtin_binding(REPORTS_EXCEL_MAIN, str(source), str(tmp_path / "result.xlsx"))
    values = dict(binding.values)
    values[ParameterKey.METADATA_MODE] = mode
    plan = resolve_plan(REPORTS_EXCEL_MAIN, replace(binding, values=tuple(values.items())))

    ocr_calls, scans, events = [], [], []
    scanner = ParsePreflightService()
    scan_source = scanner.scan_source

    def ocr(_cls, _page, bbox, _backend):
        ocr_calls.append(bbox)
        return [dict(item) for item in FAKE_OCR_ITEMS], None

    def scan(**kwargs):
        scans.append(kwargs["metadata_parsing_mode"])
        return scan_source(**kwargs)

    monkeypatch.setattr(CMMReportParser, "_ocr_header_items_from_pixmap", classmethod(ocr))
    monkeypatch.setattr(scanner, "scan_source", scan)
    runner = RecipeRunner(ReportsRecipeService(
        RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export"), scanner=scanner,
    ), on_event=events.append)
    try:
        assert runner.start(plan).state is RunState.REQUIRES_DECISION
        assert scans == [mode] and len(ocr_calls) == expected_ocr
        assert not plan.database_file.exists()
        row, = runner.review.review.rows
        assert row.set_user_value("part_name", "Confirmed part") == (True, None)
        result = runner.resume("continue")
        assert result.state is RunState.COMPLETED
        assert scans == [mode, mode] and len(ocr_calls) == expected_ocr
        expected_phase = PreparationPhase.METADATA if mode == "light" else PreparationPhase.OCR
        assert any(event.phase is expected_phase for event in events)
        assert plan.output_file.is_file()
        with closing(sqlite3.connect(str(plan.database_file))) as connection:
            actual = connection.execute("SELECT part_name FROM report_metadata").fetchall()
            assert actual == [("Confirmed part",)]
            extraction, = connection.execute("SELECT header_extraction_mode FROM report_parse_state").fetchone()
            assert (extraction == "ocr") == bool(expected_ocr)
    finally:
        runner.cancel()


def test_source_change_after_recipe_review_still_stops_before_any_write(
        tmp_path, qapplication_session, monkeypatch):
    from metroliza.parsing.preflight import ParsePreflightService

    source = tmp_path / "reports"
    _write_complete_reports(source)
    output = tmp_path / "result.xlsx"
    output.write_bytes(b"previous complete result")
    plan = resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN, str(source), str(output)))
    scanner = ParsePreflightService()
    scans, scan_source = [], scanner.scan_source

    def scan(**kwargs):
        scans.append(True)
        return scan_source(**kwargs)

    def unexpected_write(*_args):
        pytest.fail("The approval was stale before the import step.")

    monkeypatch.setattr(scanner, "scan_source", scan)
    runner = RecipeRunner(ReportsRecipeService(unexpected_write, unexpected_write, scanner=scanner))
    try:
        assert runner.start(plan).state is RunState.REQUIRES_DECISION
        with next(source.glob("*.pdf")).open("ab") as handle:
            handle.write(b"\n% changed after approval was offered\n")
        result = runner.resume("continue")
        assert result.state is RunState.FAILED and result.code is ResultCode.SOURCE_CHANGED
        assert len(scans) == 2
        assert not plan.database_file.exists() and output.read_bytes() == b"previous complete result"
    finally:
        runner.cancel()


def _seed_append_report(database, source, reference, measured):
    from metroliza.reports.report_repository import ReportRepository

    ReportRepository(str(database)).persist_parsed_report(
        source_path=source, parser_id="cmm_pdf", parser_version="old-version",
        template_family="cmm_pdf_header_box", parse_status="parsed",
        metadata={"reference": reference, "part_name": "Previously saved",
                  "report_date": "2024-01-01", "sample_number": "0"},
        candidates=(), warnings=(), metadata_version="report_metadata_v1",
        measurements=({"header": "KEPT_FEATURE", "ax": "X", "nominal": 10.0,
                       "tol_plus": 0.5, "tol_minus": -0.5, "meas": measured,
                       "dev": measured - 10.0, "outtol": 0, "status_code": "ok"},),
        identity_hash=reference, metadata_confidence=1.0,
    )


def test_append_reports_exports_only_folder_and_refreshes_all_duplicate_run(tmp_path, qapplication_session):
    from dataclasses import replace
    from metroliza.reports.db import sqlite_file_identity, sqlite_readonly_connection_scope

    source = tmp_path / "incoming"
    _write_complete_reports(source)
    database, output = tmp_path / "Baza pomiarów.db", tmp_path / "result.xlsx"
    known = sorted(source.glob("*.pdf"))[0]
    unrelated = tmp_path / "unrelated.pdf"
    unrelated.write_bytes(b"existing source outside selected folder")
    _seed_append_report(database, known, "ABCDE12345", 10.07)
    _seed_append_report(database, unrelated, "OUT_OF_SCOPE", 9876.5)
    original_identity = sqlite_file_identity(database)
    args = (REPORTS_APPEND_EXCEL_MAIN, str(source), str(output))
    binding = builtin_binding(*args, existing_database=str(database))
    plan = resolve_plan(REPORTS_APPEND_EXCEL_MAIN, binding)
    runner = RecipeRunner(ReportsRecipeService(
        RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export")), active_database=database)
    try:
        first = runner.start(plan)
        assert first.state is RunState.COMPLETED, first
        receipt = next(step.result for step in first.steps if step.kind is StepKind.IMPORT_REPORTS)
        assert (receipt.imported_count, receipt.duplicate_count) == (4, 1)
        assert sqlite_file_identity(database) == original_identity

        with sqlite_readonly_connection_scope(str(database)) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone() == (6,)
            assert connection.execute(
                "SELECT m.meas FROM report_measurements m JOIN parsed_reports pr ON pr.id=m.report_id "
                "WHERE pr.parser_version='old-version' ORDER BY m.meas"
            ).fetchall() == [(10.07,), (9876.5,)]
        with zipfile.ZipFile(output) as workbook:
            xml = b"".join(workbook.read(name) for name in workbook.namelist() if name.startswith("xl/"))
            assert b"KEPT_FEATURE" in xml and b"10.07" in xml and b"10.02" in xml
            assert b"OUT_OF_SCOPE" not in xml and b"9876.5" not in xml

        def unexpected_parse(*_args):
            pytest.fail("A duplicate-only refresh must not start the parser.")

        runner.ports.import_executor = unexpected_parse
        values = dict(binding.values)
        values[ParameterKey.METADATA_MODE] = "complete"
        binding = replace(binding, values=tuple(values.items()))
        pending = runner.start(resolve_plan(REPORTS_APPEND_EXCEL_MAIN, binding))
        assert pending.state is RunState.REQUIRES_DECISION and pending.decision == "review"
        assert runner.review.review.conflicts == (output,)
        repeat = runner.resume("continue")
        assert repeat.state is RunState.COMPLETED, repeat
        receipt = next(step.result for step in repeat.steps if step.kind is StepKind.IMPORT_REPORTS)
        assert (receipt.imported_count, receipt.duplicate_count) == (0, 5)
        assert runner.plan.database_file == database and not output.with_suffix(".db").exists()

        assert runner.start(resolve_plan(REPORTS_APPEND_EXCEL_MAIN, binding)).state is RunState.REQUIRES_DECISION
        output.write_bytes(b"another completed result before consent")
        stale = runner.resume("continue")
        assert stale.state is RunState.FAILED
        assert output.read_bytes() == b"another completed result before consent"
    finally:
        runner.cancel()


def test_append_cannot_recreate_database_lost_after_preflight(tmp_path, qapplication_session):
    from metroliza.reports.report_schema import ensure_report_schema

    source = tmp_path / "incoming"
    _write_complete_reports(source)
    database, output = tmp_path / "selected.db", tmp_path / "result.xlsx"
    ensure_report_schema(str(database))
    moved = database.with_name("saved-original.db")
    importer = RecipeExecutionAdapter("import")

    def remove_destination_before_open(plan, context):
        database.rename(moved)
        return importer(plan, context)

    runner = RecipeRunner(ReportsRecipeService(remove_destination_before_open, RecipeExecutionAdapter("export")))
    plan = resolve_plan(REPORTS_APPEND_EXCEL_MAIN, builtin_binding(
        REPORTS_APPEND_EXCEL_MAIN, str(source), str(output), existing_database=str(database)))
    try:
        result = runner.start(plan)
        assert result.state is RunState.FAILED and result.code is ResultCode.DATABASE_UNAVAILABLE
        assert not database.exists() and not output.exists()
        with closing(sqlite3.connect(str(moved))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone() == (0,)
    finally:
        runner.cancel()


def _seed_export_scope(database):
    """Authored measurements independent of product query/statistics helpers."""
    from metroliza.reports.report_repository import ReportRepository
    groups = {"A": (9.90, 9.92, 9.94, 9.96, 10.02),
              "B": (10.02, 10.04, 10.06, 10.08, 10.10),
              "EXCLUDED": (1234.5, 9876.5)}
    repository = ReportRepository(str(database))
    index = 0
    for group, values in groups.items():
        for value in values:
            index += 1
            source = database.with_name(f"synthetic-{index}.pdf")
            source.write_bytes(f"synthetic authored measurement {index}".encode())
            repository.persist_parsed_report(
                source_path=source, parser_id="cmm", parser_version="1.0",
                template_family="cmm_pdf_header_box", parse_status="parsed",
                metadata={"reference": "REF-1", "part_name": "Synthetic part", "revision": group,
                          "report_date": "2024-01-02" if group == "EXCLUDED" else "2024-01-01",
                          "sample_number": str(index), "sample_number_kind": "explicit_sample_number"},
                candidates=(), warnings=(), metadata_version="report_metadata_v1",
                measurements=({"header": "FEATURE_1", "ax": "X", "nominal": 10.0,
                               "tol_plus": 0.5, "tol_minus": -0.5, "meas": value,
                               "dev": value - 10.0, "outtol": 0, "status_code": "ok"},),
                identity_hash=f"synthetic-{index}", metadata_confidence=1.0)
    return groups


def _xlsx_cells(path, sheet_name):
    """Read the emitted OOXML, using no application export/analysis helpers."""
    import xml.etree.ElementTree as ET
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relations}
        sheet = next(sheet for sheet in workbook.findall("x:sheets/x:sheet", ns)
                     if sheet.attrib["name"] == sheet_name)
        key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        target = targets[sheet.attrib[key]].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        result = {}
        for cell in ET.fromstring(archive.read(target)).findall(".//x:c", ns):
            value = cell.find("x:v", ns)
            if cell.attrib.get("t") == "s" and value is not None:
                result[cell.attrib["r"]] = shared[int(value.text)]
            elif cell.attrib.get("t") == "inlineStr":
                result[cell.attrib["r"]] = "".join(cell.find("x:is", ns).itertext())
            elif value is not None and value.text:
                result[cell.attrib["r"]] = (value.text if cell.attrib.get("t") in {"e", "str"}
                                             else float(value.text))
        return result


def test_larger_saved_flow_uses_same_snapshot_and_real_outputs(tmp_path):
    from statistics import mean
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest, validate_export_request
    from metroliza.recipes.contracts import ParameterKey
    from metroliza.recipes.editor_service import RecipeEditorService
    from metroliza.recipes.report_configuration_adapter import capture_export_configuration
    from metroliza.recipes.storage import RecipeStore

    app = QApplication.instance() or QApplication([])
    database = tmp_path / "authored.db"
    groups = _seed_export_scope(database)
    captured = capture_export_configuration(validate_export_request(ExportRequest(
        AppPaths(str(database), excel_file=str(tmp_path / "Larger.xlsx")),
        ExportOptions(preset="full_report", generate_summary_sheet=True, chart_worker_count=1))))
    editor = RecipeEditorService(captured)
    editor.configure_reports(dates=True, grouping_columns=("REVISION",), additional_html=False)
    editor.set_value(ParameterKey.DATE_FROM, "2024-01-01")
    editor.set_value(ParameterKey.DATE_TO, "2024-01-01")
    saved = editor.save(RecipeStore(tmp_path / "private"))
    reopened = RecipeStore(tmp_path / "private").load(saved.definition.recipe_id)
    plan = resolve_plan(reopened.definition, reopened.binding)
    editor.set_value(ParameterKey.OUTPUT_FILE, str(tmp_path / "Future.xlsx"))
    assert plan.output_file == tmp_path / "Larger.xlsx"
    runner = RecipeRunner(ReportsRecipeService(
        RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export")))
    try:
        record = runner.start(plan)
        assert record.state in (RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS), record
        assert not (tmp_path / "Future.xlsx").exists()
        with closing(sqlite3.connect(str(database))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM report_measurements").fetchone() == (12,)
        # The manual Main export names measurement sheets by reference.
        # This fixture has exactly the authored REF-1 family.
        main = _xlsx_cells(plan.output_file, "REF-1")
        assert main["C21"] == "FEATURE_1 - X"
        expected = [*groups["A"], *groups["B"]]
        assert sorted(main[f"C{row}"] for row in range(22, 32)) == pytest.approx(sorted(expected))
        assert "C32" not in main  # Date exclusion removed both later measurements.
        raw = _xlsx_cells(plan.output_file, "MEASUREMENTS")
        assert raw["AD1"] == "MEAS" and raw["D1"] == "DATE"
        assert sorted(raw[f"AD{row}"] for row in range(2, 12)) == pytest.approx(sorted(expected))
        assert {raw[f"D{row}"] for row in range(2, 12)} == {"2024-01-01"}
        assert [raw[f"G{row}"] for row in range(2, 12)].count("A") == 5
        assert [raw[f"G{row}"] for row in range(2, 12)].count("B") == 5
        assert "AD12" not in raw
        analysis = _xlsx_cells(plan.output_file, "Group Analysis")
        _xlsx_cells(plan.output_file, "Group Analysis Plots")
        for group in ("A", "B"):
            rows = [int(cell[1:]) for cell, value in analysis.items() if cell.startswith("A") and value == group]
            assert any(analysis.get(f"B{row}") == 5 and
                       analysis.get(f"C{row}") == pytest.approx(mean(groups[group])) for row in rows)
        assert "EXCLUDED" not in analysis.values()
        html = plan.output_file.with_suffix(".html").read_text(encoding="utf-8")
        assert "<html" in html.lower()
        assert "9876.5" not in html and "1234.5" not in html
        assert app is QApplication.instance()
    finally:
        runner.cancel()


def test_multi_column_delimiter_collision_keeps_distinct_native_group_counts_and_means(tmp_path):
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest, validate_export_request
    from metroliza.recipes.editor_service import RecipeEditorService
    from metroliza.recipes.report_configuration_adapter import capture_export_configuration
    from metroliza.reports.report_repository import ReportRepository

    app = QApplication.instance() or QApplication([])
    database = tmp_path / "group-collision.db"
    repository = ReportRepository(str(database))
    authored = [("A | B", "C", (9.90, 9.92, 9.94, 9.96, 10.02)),
                ("A", "B | C", (10.02, 10.04, 10.06, 10.08, 10.10))]
    index = 0
    for revision, part, values in authored:
        for measured in values:
            index += 1
            source = tmp_path / f"group-fixture-{index}.pdf"
            source.write_bytes(f"synthetic group measurement {index}".encode())
            repository.persist_parsed_report(
                source_path=source, parser_id="cmm", parser_version="1.0",
                template_family="cmm_pdf_header_box", parse_status="parsed",
                metadata={"reference": "REF-1", "part_name": part, "revision": revision,
                          "report_date": "2024-01-01", "sample_number": str(index),
                          "sample_number_kind": "explicit_sample_number"},
                candidates=(), warnings=(), metadata_version="report_metadata_v1",
                measurements=({"header": "FEATURE_1", "ax": "X", "nominal": 10.0,
                               "tol_plus": 0.5, "tol_minus": -0.5, "meas": measured,
                               "dev": measured - 10.0, "outtol": 0, "status_code": "ok"},),
                identity_hash=f"synthetic-group-{index}", metadata_confidence=1.0)
    captured = capture_export_configuration(validate_export_request(ExportRequest(
        AppPaths(str(database), excel_file=str(tmp_path / "Distinct.xlsx")),
        ExportOptions(preset="full_report", generate_summary_sheet=True, chart_worker_count=1))))
    editor = RecipeEditorService(captured)
    editor.configure_reports(dates=False, grouping_columns=("REVISION", "PART_NAME"), additional_html=False)
    plan = editor.preview()
    runner = RecipeRunner(ReportsRecipeService(
        RecipeExecutionAdapter("import"), RecipeExecutionAdapter("export")))
    try:
        record = runner.start(plan)
        assert record.state in (RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS), record
        # Read actual native statistics from OOXML; literal populations/means
        # are independent of recipe key normalization and analytics helpers.
        analysis = _xlsx_cells(plan.output_file, "Group Analysis")
        for label, expected_mean in (('["A | B", "C"]', 9.948), ('["A", "B | C"]', 10.06)):
            rows = [int(cell[1:]) for cell, value in analysis.items()
                    if cell[0] == "A" and cell[1:].isdigit() and value == label]
            assert any(analysis.get(f"B{row}") == 5 and
                       analysis.get(f"C{row}") == pytest.approx(expected_mean) for row in rows)
        assert "A | B | C" not in analysis.values()
        assert app is QApplication.instance()
    finally:
        runner.cancel()


@pytest.mark.parametrize("damage", ["deleted", "corrupted"])
def test_real_import_database_lost_after_successful_export_cannot_complete(tmp_path, damage):
    from metroliza.exporting.export_outcomes import ExportRunStatus
    from metroliza.recipes.contracts import StepKind
    from metroliza.recipes.ports import StepStatus

    app = QApplication.instance() or QApplication([])
    source = tmp_path / "reports"
    _write_complete_reports(source)
    plan = resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(source), str(tmp_path / "Retained.xlsx")))
    actual_export = RecipeExecutionAdapter("export")
    completed_exports = []
    def export_then_lose_database(request, context):
        result = actual_export(request, context)
        assert result.status is ExportRunStatus.COMPLETE
        completed_exports.append(plan.output_file.read_bytes())
        if damage == "deleted":
            plan.database_file.unlink()
        else:
            plan.database_file.write_bytes(b"not a SQLite database")
        return result
    runner = RecipeRunner(ReportsRecipeService(RecipeExecutionAdapter("import"), export_then_lose_database))
    try:
        record = runner.start(plan)
        assert record.state is RunState.FAILED
        imported = next(step.result for step in record.steps if step.kind is StepKind.IMPORT_REPORTS)
        assert imported.status is StepStatus.COMPLETED and imported.imported_count == 5
        assert record.steps[-1].kind is StepKind.VERIFY_OUTPUT
        assert record.steps[-1].result.status is StepStatus.FAILED
        assert completed_exports and plan.output_file.read_bytes() == completed_exports[0]
        with zipfile.ZipFile(plan.output_file) as archive:
            assert archive.testzip() is None and "xl/workbook.xml" in archive.namelist()
        if damage == "deleted":
            assert not plan.database_file.exists()
        else:
            assert plan.database_file.read_bytes() == b"not a SQLite database"
        assert app is QApplication.instance()
    finally:
        runner.cancel()
