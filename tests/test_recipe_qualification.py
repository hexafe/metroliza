"""Independent fixture, negative receipt, literal oracle and owned-exit controls."""
from collections import Counter
import json
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from contextlib import closing
from types import SimpleNamespace

import pytest

from metroliza.ui.recipe_qualification import GATE, install_recipe_qualification, write_reports
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
from metroliza.recipes.report_ports import ReportsRecipeService
from metroliza.recipes.ports import StepContext
from scripts import qualify_recipe_package as driver


def receipt():
    return {"schema_version": 1, "status": "passed", "reason": "none", "packaged": True,
        "native_windows": True, "source_sha": "a" * 40, "source_dirty": False,
        "qpa": "windows", "scale": 1.25, "cleanup": "complete", "stage": "complete", "cases": [
            {"case": case, "state": "completed", "prompt_fields": 4 if case == "larger" else 2,
             "start_clicks": 1} for case in driver.CASES]}


def test_authored_fixture_preflight_is_complete_without_decision(tmp_path):
    source = tmp_path / "reports"
    write_reports(source)
    plan = resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
        str(source), str(tmp_path / "main.xlsx")))
    context = StepContext(plan.flow_id, plan.run_id, "unused", lambda: False, lambda *_: None)
    service = ReportsRecipeService(lambda *_: None, lambda *_: None)
    result = service.preflight(plan, context)
    try:
        assert result.ready and not result.requires_decision
        assert len(result.review.rows) == 12
        assert Counter(row.value("reference") for row in result.review.rows) == {"ABCDE12345": 12}
        assert Counter(row.value("revision") for row in result.review.rows) == {"A": 6, "B": 6}
    finally:
        service.finish(plan)


@pytest.mark.parametrize("key,value", [("packaged", False), ("native_windows", False),
    ("source_dirty", True), ("source_sha", "b" * 40), ("scale", float("nan")),
    ("qpa", "offscreen"), ("schema_version", True), ("cleanup", "pending")])
def test_source_stale_offscreen_partial_and_wrong_scale_are_rejected(key, value):
    value_map = receipt()
    value_map[key] = value
    with pytest.raises(ValueError):
        driver.validate_receipt(value_map, "a" * 40, 1.25)


def test_receipt_has_no_extra_private_fields_and_requires_one_start():
    payload = receipt()
    driver.validate_receipt(payload, "a" * 40, 1.25)
    payload["private_path"] = "PRIVATE_SENTINEL"
    with pytest.raises(ValueError, match="receipt_schema"):
        driver.validate_receipt(payload, "a" * 40, 1.25)
    payload.pop("private_path")
    payload["cases"][0]["start_clicks"] = 2
    with pytest.raises(ValueError, match="one_start_required"):
        driver.validate_receipt(payload, "a" * 40, 1.25)


def test_literal_database_oracle_rejects_wrong_values_and_cardinality(tmp_path):
    database = tmp_path / "test.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript("CREATE TABLE parsed_reports(id INTEGER);"
                                 "CREATE TABLE report_metadata(report_id INTEGER, reference TEXT, revision TEXT, report_date TEXT);"
                                 "CREATE TABLE report_measurements(report_id INTEGER, meas REAL);")
        # Authored independently of both probe writer and driver implementation.
        samples = [("A", value) for value in (9.90, 9.92, 9.94, 9.96, 10.02, 9.92)]
        samples += [("B", value) for value in (10.02, 10.04, 10.06, 10.08, 10.10, 10.09)]
        connection.executemany("INSERT INTO parsed_reports VALUES (?)", [(i,) for i in range(1, 13)])
        connection.executemany("INSERT INTO report_metadata VALUES (?, ?, ?, ?)",
                               [(i, "ABCDE12345", revision, "2024-01-02" if i in (6, 12) else "2024-01-01")
                                for i, (revision, _) in enumerate(samples, start=1)])
        connection.executemany("INSERT INTO report_measurements VALUES (?, ?)",
                               [(i, value) for i, (_, value) in enumerate(samples, start=1)])
        connection.commit()
    driver.verify_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE report_measurements SET meas=10.03 WHERE rowid=1")
        connection.commit()
    with pytest.raises(ValueError, match="literal_measurement_oracle"):
        driver.verify_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM parsed_reports WHERE rowid=1")
        connection.commit()
    with pytest.raises(ValueError, match="report_count"):
        driver.verify_database(database)


def test_unrequested_probe_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv(GATE, raising=False)
    with pytest.raises(ValueError, match="qualification_gate_required"):
        install_recipe_qualification(None, tmp_path)
    assert not tuple(tmp_path.iterdir())


def test_timeout_closes_only_the_owned_job(tmp_path, monkeypatch):
    from scripts import qualify_windows_diagnostics as ownership
    calls = []
    process = SimpleNamespace(poll=lambda: None, active_processes=lambda: 1,
                              close=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(ownership, "_WindowsApi", lambda: SimpleNamespace(launch=lambda *_: process))
    times = iter((0.0, 1000.0))
    monkeypatch.setattr(driver.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="owned_job_timeout"):
        driver._launch(tmp_path / "exact.exe", tmp_path, {})
    assert calls == [{"terminate": True}]


def test_linux_driver_never_labels_package_acceptance_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(driver.sys, "platform", "linux")
    output = tmp_path / "evidence"
    status = driver.main(["--exe", str(tmp_path / "unused.exe"), "--output", str(output),
                          "--expected-sha", "a" * 40, "--scale", "1"])
    assert status == 1
    result = json.loads((output / "qualification.json").read_text())
    assert result["status"] == "failed" and result["native_windows"] is False


def test_html_asset_oracle_rejects_missing_or_remote_dependencies(tmp_path):
    document = tmp_path / "dashboard.html"
    document.write_text('<html><script src="plotly.js"></script></html>')
    with pytest.raises(ValueError, match="html_assets_invalid"):
        driver.verify_html(document)
    (tmp_path / "plotly.js").write_text("synthetic offline plotly")
    driver.verify_html(document)
    document.write_text('<html><script src="https://example.invalid/plotly.js"></script></html>')
    with pytest.raises(ValueError, match="html_assets_invalid"):
        driver.verify_html(document)


def test_png_oracle_decodes_complete_screenshot_and_rejects_truncation(tmp_path):
    from PIL import Image
    path = tmp_path / "screenshot.png"
    Image.new("RGB", (640, 480), "white").save(path)
    driver.verify_png(path)
    path.write_bytes(path.read_bytes()[:30])
    with pytest.raises((OSError, ValueError, SyntaxError)):
        driver.verify_png(path)


def _literal_workbook(path, *, fault=None):
    """Small authored OOXML, with no product export/statistics implementation."""
    raw = {"C1": "REFERENCE", "G1": "REVISION", "D1": "DATE", "AD1": "MEAS"}
    samples = [("A", value) for value in (9.90, 9.92, 9.94, 9.96, 10.02)]
    samples += [("B", value) for value in (10.02, 10.04, 10.06, 10.08, 10.10)]
    for row, (revision, value) in enumerate(samples, start=2):
        raw.update({f"C{row}": "ABCDE12345", f"G{row}": revision,
                    f"D{row}": "2024-01-01", f"AD{row}": value})
    analysis = {"A2": "A", "B2": 5, "C2": 9.948,
                "A3": "B", "B3": 5, "C3": 10.06}
    if fault == "date":
        raw["D2"] = "2024-01-02"
    elif fault == "extra":
        raw["AD12"] = 9.92
    elif fault == "count":
        analysis["B2"] = 6
    elif fault == "mean":
        analysis["C2"] = 10.00
    elif fault == "value":
        raw["AD2"] = 9.93
    sheets = {"MEASUREMENTS": raw, "Group Analysis": analysis, "Group Analysis Plots": {"A1": "Plots"}}
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as archive:
        workbook = ET.Element("workbook", xmlns=ns)
        entries = ET.SubElement(workbook, "sheets")
        relationships = ET.Element("Relationships")
        for index, (name, cells) in enumerate(sheets.items(), start=1):
            ET.SubElement(entries, "sheet", {"name": name, "sheetId": str(index), f"{{{rel}}}id": f"r{index}"})
            ET.SubElement(relationships, "Relationship", Id=f"r{index}", Target=f"worksheets/sheet{index}.xml")
            document = ET.Element("worksheet", xmlns=ns)
            data = ET.SubElement(document, "sheetData")
            for address, value in cells.items():
                cell = ET.SubElement(data, "c", r=address)
                if type(value) is str:
                    cell.set("t", "inlineStr")
                    ET.SubElement(ET.SubElement(cell, "is"), "t").text = value
                else:
                    ET.SubElement(cell, "v").text = str(value)
            cached = ET.SubElement(data, "c", r="Z99", t="str")
            ET.SubElement(cached, "f").text = 'HYPERLINK("#A1", "Go to metric")'
            ET.SubElement(cached, "v").text = "Go to metric"
            archive.writestr(f"xl/worksheets/sheet{index}.xml", ET.tostring(document))
        archive.writestr("xl/workbook.xml", ET.tostring(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(relationships))


def test_larger_xlsx_literal_scope_and_group_statistics_include_formula_strings(tmp_path):
    path = tmp_path / "larger.xlsx"
    _literal_workbook(path)
    driver.verify_larger_workbook(path)
    assert driver.workbook_cells(path, "Group Analysis")["Z99"] == "Go to metric"


@pytest.mark.parametrize("part", ["xl/workbook.xml", "xl/_rels/workbook.xml.rels",
    "xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"])
def test_workbook_oracle_rejects_xml_entities_in_every_parsed_part(tmp_path, part):
    from defusedxml.common import DefusedXmlException
    path = tmp_path / "untrusted.xlsx"
    _literal_workbook(path)
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries[part] = (b'<!DOCTYPE root [<!ENTITY expanded "PRIVATE_XML_SENTINEL">]>'
                     b'<root>&expanded;</root>')
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    with pytest.raises(DefusedXmlException):
        driver.workbook_cells(path, "MEASUREMENTS")


@pytest.mark.parametrize("fault,reason", [("date", "larger_export_scope"),
    ("extra", "larger_export_scope"), ("value", "larger_export_scope"),
    ("count", "larger_group_statistics"), ("mean", "larger_group_statistics")])
def test_larger_xlsx_oracle_rejects_scope_and_statistic_regressions(tmp_path, fault, reason):
    path = tmp_path / "larger.xlsx"
    _literal_workbook(path, fault=fault)
    with pytest.raises(ValueError, match=reason):
        driver.verify_larger_workbook(path)
