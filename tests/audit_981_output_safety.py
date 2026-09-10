"""Explicit #981 structural audit; synthetic artifacts, no GUI or network use.

Run with PYTHONPATH=src:. python tests/audit_981_output_safety.py --output-dir DIR.
The output directory must not exist. Assertion failures are evidence, never skips.
This is a bounded reproducer, not a validator for arbitrary untrusted files.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from PIL import Image
import xlsxwriter
from xlsxwriter.exceptions import FileCreateError

from metroliza.charts import export_html_dashboard as dashboard
from metroliza.charts.export_chart_writer import insert_measurement_chart
from metroliza.exporting.export_backends import ExcelExportBackend, HtmlDashboardExportBackend
from metroliza.exporting.execution import ExportStageOutcome
from metroliza.exporting.export_query_service import build_export_dataframe, build_measurement_export_dataframe
from metroliza.exporting.export_sheet_writer import write_measurement_summary_rows


TEXT = 'Żółć "quotes" & <audit-literal> =1+1'
BREAKOUT = '</script><script type="application/json" id="audit-inert-breakout">{}</script>'
FORBIDDEN = "AUDIT981_NONEXPORT_SYNTHETIC_MARKER"
PRIVATE_PARENT = "AUDIT981_PRIVATE_PARENT"
URL_TEXT = "https://example.invalid/audit-literal"
VALUES = ["=1+1", "+2", "-3", "@name", URL_TEXT, TEXT, BREAKOUT]
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CHART_NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}


def assert_chart_names_literal(chart: ET.Element, expected_label: str | None = None) -> None:
    """Data-series range formulas are legitimate; imported name formulas are not."""
    assert not chart.findall(".//c:title//c:strRef/c:f", CHART_NS), "imported title became formula"
    assert not chart.findall(".//c:ser/c:tx/c:strRef/c:f", CHART_NS), "imported series name became formula"
    if expected_label is not None:
        title = chart.find(".//c:title", CHART_NS)
        series = chart.find(".//c:ser/c:tx", CHART_NS)
        assert title is not None and expected_label in list(title.itertext()), "literal title missing"
        assert series is not None and expected_label in list(series.itertext()), "literal series name missing"


def chart_label_probe(output_dir: Path) -> dict:
    """Minimal corroboration of the supported measurement-chart finding.

    Only a benign local reference. No formula is evaluated, and neither Excel
    nor Qt is started. CLI exits 1 for the observed defect.
    """
    output_dir.mkdir(parents=True, exist_ok=False)
    target = output_dir / "local-only.xlsx"
    backend = ExcelExportBackend()
    source = build_export_dataframe([("=Data!A1", "X", 1.0), ("=Data!A1", "X", 2.0)], ["HEADER", "AX", "MEAS"])
    table = build_measurement_export_dataframe(source)
    header = table["HEADER - AX"][0]

    def populate(writer):
        backend.write_dataframe(writer, table, "Data")
        insert_measurement_chart(
            backend.get_workbook(writer), backend.get_worksheet(writer, "Data"),
            chart_type="line", header=header, sheet_name="Data",
            measurement_plan={"data_start_row": 1, "last_data_row": 2, "summary_column": 3,
                              "y_column": 2, "usl_column": 2, "lsl_column": 2}, chart_anchor_col=0,
        )
        return ExportStageOutcome.completed()

    context = SimpleNamespace(excel_file=str(target), run_export_pipeline=populate,
                              begin_workbook_close=lambda: None, complete_workbook_close=lambda _elapsed: None)
    stderr = StringIO()
    with redirect_stderr(stderr):
        outcome = backend.run(context)
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        chart = ET.fromstring(archive.read("xl/charts/chart1.xml"))
    title = [node.text for node in chart.findall(".//c:title//c:strRef/c:f", CHART_NS)]
    series = [node.text for node in chart.findall(".//c:ser/c:tx/c:strRef/c:f", CHART_NS)]
    title_cache = [node.text for node in chart.findall(".//c:title//c:strCache/c:pt/c:v", CHART_NS)]
    series_cache = [node.text for node in chart.findall(".//c:ser/c:tx/c:strRef/c:strCache/c:pt/c:v", CHART_NS)]
    try:
        assert_chart_names_literal(chart, header)
    except AssertionError:
        disposition = "CONFIRMED DEFECT"
    else:
        disposition = "ACCEPTED CONTRACT"
    facts = {"disposition": disposition, "outcome": outcome.kind.value, "zip_valid": True,
             "imported_header_became_title_formula": title == [header.lstrip("=")],
             "imported_header_became_series_formula": series == [header.lstrip("=")],
             "total_chart_formula_nodes": len(chart.findall(".//c:f", CHART_NS)),
             "title_formula_count": len(title), "series_name_formula_count": len(series),
             "title_cached_values": title_cache, "series_cached_values": series_cache,
             "title_cache_matches_imported_label": title_cache == [header],
             "series_cache_matches_imported_label": series_cache == [header],
             "stderr_chars": len(stderr.getvalue()), "excel_execution": "NOT TESTED"}
    (output_dir / "facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    return facts


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assert_no_marker(parts: list[bytes]) -> None:
    assert all(FORBIDDEN.encode() not in part for part in parts), "non-export marker escaped"
    assert all(PRIVATE_PARENT.encode() not in part for part in parts), "private parent path escaped"


def assert_preserved(before: dict[str, str], after: dict[str, str]) -> None:
    assert before == after, "last-complete artifact changed"


def inspect_xlsx(path: Path, offset: int = 0) -> dict:
    """Read actual package cells and relationships, including nonvisible XML."""
    with ZipFile(path) as archive:
        assert archive.testzip() is None, "corrupt ZIP member"
        parts = {name: archive.read(name) for name in archive.namelist()}
    assert_no_marker(list(parts.values()))
    for name, data in parts.items():
        if name.endswith((".xml", ".rels")):
            ET.fromstring(data)
    strings = ["".join(node.itertext()) for node in ET.fromstring(parts["xl/sharedStrings.xml"])]
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    cells = {}
    formulas = {}
    for cell in sheet.findall(".//s:c", NS):
        value = cell.findtext("s:v", namespaces=NS)
        formula = cell.findtext("s:f", namespaces=NS)
        cells[cell.attrib["r"]] = strings[int(value)] if cell.get("t") == "s" else value
        if formula is not None:
            formulas[cell.attrib["r"]] = formula
    assert cells["A1"] == "=HEADER", "header changed"
    for row, value in enumerate(VALUES, start=2):
        cell = sheet.find(f'.//s:c[@r="A{row}"]', NS)
        assert cell is not None and cell.get("t") == "s", "imported text became active cell"
        assert cells[f"A{row}"] == value, "imported text changed"
        assert cells[f"B{row}"] == str(row - 2 + offset), "synthetic numeric cell changed"
    assert formulas == {"D2": "SUM(B2:B8)"}, "unexpected or missing formula"
    links = sheet.findall(".//s:hyperlink", NS)
    assert len(links) == 1 and links[0].get("ref") == "E2", "unexpected hyperlink"
    assert links[0].get("location") == "'Data'!A1", "navigation link changed"
    relationships = []
    for name, data in parts.items():
        if name.endswith(".rels"):
            relationships.extend(ET.fromstring(data))
    assert not any(rel.get("TargetMode") == "External" for rel in relationships)
    sheets = ET.fromstring(parts["xl/workbook.xml"]).findall("s:sheets/s:sheet", NS)
    assert len(sheets) == 1 and sheets[0].get("state", "visible") == "visible"
    assert not any("comments" in name.lower() for name in parts)
    return {"literal_cells": len(VALUES) + 1, "formulas": formulas, "links": 1,
            "external_relationships": 0, "hidden_sheets": 0,
            "parts": sorted(parts), "cells": cells}


class HtmlFacts(HTMLParser):
    """Independent HTML tokenizer: distinguish text, attributes and script data."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.scripts = []
        self.text = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "script":
            self.in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts[-1] += data
        else:
            self.text.append(data)


def parse_html(text: str) -> HtmlFacts:
    parsed = HtmlFacts()
    parsed.feed(text)
    parsed.close()
    assert any(tag == "html" for tag, _ in parsed.tags), "missing HTML document"
    assert "</html>" in text.lower(), "incomplete HTML document"
    assert not any(attrs.get("id") == "audit-inert-breakout" for _, attrs in parsed.tags), "script boundary escaped"
    assert not any(tag == "audit-literal" for tag, _ in parsed.tags), "text became element"
    assert not any(key.lower().startswith("on") for _, attrs in parsed.tags for key in attrs), "event handler appeared"
    assert_no_marker([text.encode()])
    return parsed


def inspect_html(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parsed = parse_html(text)
    assert TEXT in "".join(parsed.text) and BREAKOUT in "".join(parsed.text)
    specs = [json.loads(attrs["data-plotly-spec-light"]) for _, attrs in parsed.tags
             if "data-plotly-spec-light" in attrs]
    assert len(specs) == 2, "interactive specs missing"
    encoded_specs = json.dumps(specs, ensure_ascii=False)
    assert TEXT in encoded_specs.replace('\\"', '"') and BREAKOUT in encoded_specs.replace('\\"', '"')
    # Decode the actual JSON assignment embedded in the generated inline script.
    config_script = next(script for script in parsed.scripts if "const dashboardVisualConfig = " in script)
    config_text = config_script.split("const dashboardVisualConfig = ", 1)[1]
    config, _ = json.JSONDecoder().raw_decode(config_text)
    assert any(BREAKOUT in label for label in config["previewLabels"]), "preview boundary not exercised"
    assets = []
    links = []
    for tag, attrs in parsed.tags:
        for key in ("src", "href"):
            value = attrs.get(key)
            if not value or value.startswith("#"):
                continue
            if tag == "a":
                links.append(value)
                continue
            split = urlsplit(value)
            assert not split.scheme and not split.netloc, "automatic external resource"
            asset = path.parent / value
            assert asset.is_file(), "missing offline asset"
            assert_no_marker([asset.read_bytes()])
            if asset.suffix == ".png":
                with Image.open(asset) as png:
                    png.verify()
            assets.append(asset.name)
    assert any(name.endswith(".js") for name in assets), "local Plotly runtime missing"
    return {"spec_count": len(specs), "script_elements": len(parsed.scripts),
            "preview_labels": config["previewLabels"], "assets": sorted(assets),
            "links": links, "automatic_external_resources": 0}


def sections() -> list[dict]:
    image = BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    common = {"image_buffer": image.getvalue(), "title": TEXT, "backend": "audit-synthetic"}
    return [{"header": TEXT, "subtitle": BREAKOUT, "reference": URL_TEXT,
             "axis": TEXT, "sample_size": 3, "grouping_applied": True,
             "credentials": {"password": FORBIDDEN},
             "metadata_rows": [{"label": TEXT, "value": URL_TEXT}],
             "summary_rows": [{"label": TEXT, "value": "3"}],
             "charts": [
                 {**common, "chart_type": "distribution", "payload": {
                     "type": "distribution", "render_mode": "box", "labels": [BREAKOUT],
                     "series": [[1.0, 2.0, 3.0]], "x_label": TEXT, "y_label": TEXT,
                     "credentials": {"password": FORBIDDEN}}},
                 {**common, "chart_type": "histogram", "payload": {
                     "type": "histogram", "values": [1.0, 2.0, 3.0],
                     "annotation_rows": [{"label": TEXT, "text": BREAKOUT}],
                     "style": {"axis_label_x": TEXT}, "credentials": FORBIDDEN}},
             ]}]


class WorkbookContext:
    """No Qt: supply table data at the production backend callback boundary."""

    def __init__(self, path: Path, backend, mode="success", offset=0):
        self.excel_file = str(path)
        self.backend = backend
        self.mode = mode
        self.credentials = FORBIDDEN
        self.closed = False
        self.offset = offset

    def begin_workbook_close(self):
        pass

    def complete_workbook_close(self, elapsed):
        self.closed = True

    def run_export_pipeline(self, writer):
        rows = [(value, i + self.offset) for i, value in enumerate(VALUES)]
        table = build_export_dataframe(rows, ["=HEADER", "Value"])
        self.backend.write_dataframe(writer, table, "Data")
        assert list(table.iter_rows()) == rows, "source rows mutated"
        sheet = self.backend.get_worksheet(writer, "Data")
        # Exercise a real production formula-writing helper and navigation adapter.
        write_measurement_summary_rows(sheet, [{"row": 1, "label_col": 2, "value_col": 3,
                                               "label": TEXT, "formula": "=SUM(B2:B8)", "style": "number"}], {})
        sheet.write_url(1, 4, "internal:'Data'!A1", string="Back to data")
        if self.mode == "writer":
            raise RuntimeError(FORBIDDEN)
        return ExportStageOutcome.canceled() if self.mode == "cancel" else ExportStageOutcome.completed()


def snapshot(directory: Path) -> dict[str, str]:
    # Persistent publication lock is coordination metadata, not output content.
    entries = {}
    for path in directory.rglob("*"):
        relative = str(path.relative_to(directory))
        if path.is_dir():
            entries[relative + "/"] = "directory"
        elif path.is_file() and not path.name.endswith(".lock"):
            entries[relative] = digest(path.read_bytes())
    return entries


def workbook_case(directory: Path, mode: str, existing: bool) -> dict:
    directory.mkdir(parents=True)
    target = directory / "wynik żółć.xlsx"
    backend = ExcelExportBackend()
    if existing:
        backend.run(WorkbookContext(target, backend, offset=100))
        inspect_xlsx(target, offset=100)
    before = snapshot(directory)
    close = backend.close_writer

    def close_failure(writer):
        close(writer)
        raise OSError(FORBIDDEN)

    seam = (patch.object(xlsxwriter.Workbook, "_store_workbook", side_effect=OSError(FORBIDDEN)) if mode == "flush" else
            patch.object(backend, "close_writer", close_failure) if mode == "close" else
            patch.object(backend, "replace_workbook", side_effect=OSError(FORBIDDEN)) if mode == "promote" else nullcontext())
    context = WorkbookContext(target, backend, mode)
    outcome = None
    error = None
    exception_marker_propagated = False
    with seam:
        try:
            outcome = backend.run(context).kind.value
        except (OSError, RuntimeError, FileCreateError) as exc:
            error = type(exc).__name__
            exception_marker_propagated = FORBIDDEN in str(exc)
    assert context.closed
    after = snapshot(directory)
    assert len(list(directory.iterdir())) == int(target.exists()), "staging left behind"
    if mode == "success":
        assert outcome == "completed" and error is None
        facts = inspect_xlsx(target)
        assert before != after
    else:
        assert_preserved(before, after)
        assert (outcome == "canceled" and error is None) if mode == "cancel" else (outcome is None and error is not None)
        facts = None
    return {"format": "xlsx", "mode": mode, "existing": existing, "outcome": outcome,
            "error_class": error, "preserved": before == after, "target_exists": target.exists(),
            "injected_exception_marker_propagated_to_caller": exception_marker_propagated,
            "temporary_files": 0, "facts": facts}


def html_case(directory: Path, mode: str, existing: bool) -> dict:
    directory.mkdir(parents=True)
    target = directory / "dashboard żółć.html"
    fixture = sections()
    original_fixture = deepcopy(fixture)

    def publish():
        return dashboard.write_export_html_dashboard(output_path=target, assets_dir=dashboard.resolve_html_dashboard_assets_dir(target),
                                                     excel_file=directory / PRIVATE_PARENT / "source.xlsx",
                                                     sections=fixture, source_label=TEXT, dashboard_mode="html_only")

    if existing:
        publish()
        inspect_html(target)
    before = snapshot(directory)
    render = dashboard._render_dashboard_html
    write_text = Path.write_text

    def render_failure(*args, **kwargs):
        render(*args, **kwargs)
        raise RuntimeError(FORBIDDEN)

    def write_failure(path, text, *args, **kwargs):
        result = write_text(path, text, *args, **kwargs)
        if path.suffix == ".tmp":
            raise OSError(FORBIDDEN)
        return result

    seam = (patch.object(dashboard, "_render_dashboard_html", render_failure) if mode == "renderer" else
            patch.object(Path, "write_text", write_failure) if mode == "finalize" else
            patch.object(dashboard.os, "replace", side_effect=OSError(FORBIDDEN)) if mode == "promote" else nullcontext())
    result = None
    error = None
    exception_marker_propagated = False
    # Production publishes after backend planning; no generator cancellation token.
    context = SimpleNamespace(html_dashboard_file=str(target), run_html_dashboard_pipeline=lambda _writer:
                              ExportStageOutcome.canceled() if mode == "cancel" else ExportStageOutcome.completed())
    outcome = HtmlDashboardExportBackend().run(context)
    with seam:
        try:
            if outcome:
                result = publish()
        except (OSError, RuntimeError) as exc:
            error = type(exc).__name__
            exception_marker_propagated = FORBIDDEN in str(exc)
    after = snapshot(directory)
    assert fixture == original_fixture, "input fixture mutated"
    if mode == "success":
        assert result and result["html_dashboard_path"] == str(target) and error is None
        facts = inspect_html(target)
        assert len(list(directory.glob("*.generation-*"))) == 1
        assert before != after
    else:
        assert_preserved(before, after)
        assert result is None
        assert (not outcome and error is None) if mode == "cancel" else error is not None
        facts = None
    assert not list(directory.glob("*.tmp"))
    return {"format": "html", "mode": mode, "existing": existing,
            "planning_outcome": outcome.kind.value, "published": result is not None,
            "error_class": error, "preserved": before == after, "target_exists": target.exists(),
            "injected_exception_marker_propagated_to_caller": exception_marker_propagated,
            "temporary_files": 0, "facts": facts}


def run(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    cases = []
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        for existing in (False, True):
            for mode in ("success", "cancel", "writer", "flush", "close", "promote"):
                cases.append(workbook_case(output_dir / f"xlsx {existing} {mode}", mode, existing))
            for mode in ("success", "cancel", "renderer", "finalize", "promote"):
                cases.append(html_case(output_dir / f"html {existing} {mode}", mode, existing))
    assert_no_marker([stdout.getvalue().encode(), stderr.getvalue().encode()])
    result = {"evidence_level": "Linux real serialization; structural inspection; injected failure seams",
              "captured_stdout_chars": len(stdout.getvalue()), "captured_stderr_chars": len(stderr.getvalue()),
              "cases": cases, "browser_execution": "NOT TESTED", "excel_execution": "NOT TESTED"}
    (output_dir / "facts.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--chart-label-probe", action="store_true", help="Minimal stopped finding; exits 1 when confirmed")
    args = parser.parse_args()
    if args.chart_label_probe:
        result = chart_label_probe(args.output_dir)
        print(json.dumps(result))
        sys.exit(1 if result["disposition"] == "CONFIRMED DEFECT" else 0)
    else:
        result = run(args.output_dir)
        print(json.dumps({"cases": len(result["cases"]), "assertions": "passed", "runtime_execution": "NOT TESTED"}))
