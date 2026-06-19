from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd

from modules.industrial_analytics_state import ProductionChartSelection, ProductionMetricSelection
from modules.industrial_analytics_workbook_charts import (
    _plot_groups,
    _time_series_groups,
    add_analytics_workbook_charts,
)

NS_MAIN = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_PACKAGE = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
NS_DRAWING = {"xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}
NS_A = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
_EMU_PER_PIXEL = 9525.0


def _load_package_xml(workbook_zip: zipfile.ZipFile, xml_path: str) -> ET.Element:
    return ET.fromstring(workbook_zip.read(xml_path))


def _worksheet_drawing_root(workbook_zip: zipfile.ZipFile, sheet_name: str) -> ET.Element:
    workbook_xml = _load_package_xml(workbook_zip, "xl/workbook.xml")
    workbook_rels = _load_package_xml(workbook_zip, "xl/_rels/workbook.xml.rels")
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in workbook_rels.findall("r:Relationship", NS_PACKAGE)
    }

    sheet_target = None
    for sheet in workbook_xml.findall("x:sheets/x:sheet", NS_MAIN):
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        sheet_target = rel_map[rel_id]
        break
    assert sheet_target is not None

    sheet_path = f"xl/{sheet_target}" if not sheet_target.startswith("xl/") else sheet_target
    sheet_rels_path = f"xl/worksheets/_rels/{Path(sheet_path).name}.rels"
    worksheet_rels = _load_package_xml(workbook_zip, sheet_rels_path)
    drawing_target = next(
        rel.attrib["Target"]
        for rel in worksheet_rels.findall("r:Relationship", NS_PACKAGE)
        if rel.attrib["Type"].endswith("/drawing")
    )
    drawing_path = f"xl/drawings/{Path(drawing_target).name}"
    return _load_package_xml(workbook_zip, drawing_path)


def _inserted_image_sizes_px(workbook_zip: zipfile.ZipFile, sheet_name: str) -> list[tuple[float, float]]:
    drawing_root = _worksheet_drawing_root(workbook_zip, sheet_name)
    sizes: list[tuple[float, float]] = []
    for anchor in drawing_root:
        ext = anchor.find("xdr:ext", NS_DRAWING)
        if ext is None:
            ext = anchor.find("xdr:pic/xdr:spPr/a:xfrm/a:ext", {**NS_DRAWING, **NS_A})
        if ext is None:
            continue
        width_px = float(ext.attrib["cx"]) / _EMU_PER_PIXEL
        height_px = float(ext.attrib["cy"]) / _EMU_PER_PIXEL
        sizes.append((width_px, height_px))
    return sizes


def test_workbook_distribution_groups_use_selected_group_field_before_defaults() -> None:
    dataframe = pd.DataFrame(
        {
            "station": ["S1", "S1", "S1", "S1"],
            "machine": ["M1", "M2", "M1", "M2"],
            "cycle_time_s": [35.0, 36.0, 34.8, 36.2],
        }
    )

    groups = _plot_groups(dataframe, "cycle_time_s", group_fields=("machine",))

    assert [label for label, _values in groups] == ["M1", "M2"]
    assert [values.tolist() for _label, values in groups] == [[35.0, 34.8], [36.0, 36.2]]


def test_workbook_time_series_groups_use_selected_group_field() -> None:
    dataframe = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "reference_cohort": [
                "Selected references",
                "Other references",
                "Selected references",
                "Other references",
            ],
            "cycle_time_s": [35.0, 36.0, 35.2, 36.1],
        }
    )

    groups = _time_series_groups(
        dataframe,
        "cycle_time_s",
        "process_datetime",
        group_fields=("reference_cohort",),
    )

    assert [label for label, _x_values, _y_values in groups] == [
        "Other references",
        "Selected references",
    ]
    assert [y_values for _label, _x_values, y_values in groups] == [[36.0, 36.1], [35.0, 35.2]]


def test_workbook_time_series_groups_combine_manual_group_and_highlight_cohort() -> None:
    dataframe = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "GROUP": ["POPULATION", "POPULATION", "Fixture A", "Fixture A"],
            "reference_cohort": [
                "Other references",
                "Selected references",
                "Other references",
                "Selected references",
            ],
            "cycle_time_s": [36.0, 35.0, 36.2, 35.2],
        }
    )

    groups = _time_series_groups(
        dataframe,
        "cycle_time_s",
        "process_datetime",
        group_fields=("GROUP",),
    )

    assert [label for label, _x_values, _y_values in groups] == [
        "Fixture A | Other references",
        "Fixture A | Selected references",
        "POPULATION | Other references",
        "POPULATION | Selected references",
    ]


def test_workbook_grouped_histogram_uses_normalized_group_shares() -> None:
    dataframe = pd.DataFrame(
        {
            "source_row_number": list(range(1, 9)),
            "GROUP": ["POPULATION"] * 6 + ["Selected"] * 2,
            "cycle_time_s": [34.8, 35.0, 35.1, 35.2, 35.4, 35.6, 36.0, 36.2],
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "charts.xlsx"
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name="Data", index=False)
            chart_count = add_analytics_workbook_charts(
                writer=writer,
                dataframe=dataframe,
                metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
                chart_selection=ProductionChartSelection(
                    time_series=False,
                    histogram=True,
                    violin=False,
                    box=False,
                ),
                data_sheet_name="Data",
                used_names={"Data"},
                sheet_names=["Data"],
                group_fields=("GROUP",),
            )

        assert chart_count == 1
        with zipfile.ZipFile(output_file, "r") as workbook_zip:
            text_payload = "\n".join(
                workbook_zip.read(name).decode("utf-8", errors="ignore")
                for name in workbook_zip.namelist()
                if name.endswith(".xml")
            )

    assert "Share of group" in text_payload
    assert "POPULATION" in text_payload
    assert "Selected" in text_payload
    assert "0%" in text_payload
    assert "Stats: POPULATION" in text_payload
    assert "Samples" in text_payload


def test_workbook_single_histogram_uses_rendered_plot_with_stats_table() -> None:
    dataframe = pd.DataFrame(
        {
            "source_row_number": list(range(1, 5)),
            "cycle_time_s": [34.8, 35.0, 35.1, 35.2],
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "charts.xlsx"
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name="Data", index=False)
            chart_count = add_analytics_workbook_charts(
                writer=writer,
                dataframe=dataframe,
                metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
                chart_selection=ProductionChartSelection(
                    time_series=False,
                    histogram=True,
                    violin=False,
                    box=False,
                ),
                data_sheet_name="Data",
                used_names={"Data"},
                sheet_names=["Data"],
            )

        assert chart_count == 1
        with zipfile.ZipFile(output_file, "r") as workbook_zip:
            names = workbook_zip.namelist()
            text_payload = "\n".join(
                workbook_zip.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith(".xml")
            )

    assert any(name.startswith("xl/media/") and name.endswith(".png") for name in names)
    assert "Histogram rendered by" in text_payload


def test_workbook_single_histogram_image_stays_within_reserved_chart_slot() -> None:
    dataframe = pd.DataFrame(
        {
            "source_row_number": list(range(1, 7)),
            "cycle_time_s": [34.8, 35.0, 35.1, 35.2, 35.4, 35.6],
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "histogram-slot.xlsx"
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name="Data", index=False)
            chart_count = add_analytics_workbook_charts(
                writer=writer,
                dataframe=dataframe,
                metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
                chart_selection=ProductionChartSelection(
                    time_series=False,
                    histogram=True,
                    violin=False,
                    box=False,
                ),
                data_sheet_name="Data",
                used_names={"Data"},
                sheet_names=["Data"],
            )

        assert chart_count == 1
        with zipfile.ZipFile(output_file, "r") as workbook_zip:
            image_sizes = _inserted_image_sizes_px(workbook_zip, "Charts")

    assert len(image_sizes) == 1
    width_px, height_px = image_sizes[0]
    assert width_px <= 8 * 64.0 * 0.96
    assert height_px <= 18 * 20.0 * 0.96


def test_workbook_distribution_image_stays_within_reserved_chart_slot() -> None:
    dataframe = pd.DataFrame(
        {
            "station": ["S1", "S1", "S1", "S2", "S2", "S2"],
            "cycle_time_s": [34.8, 35.0, 35.1, 35.5, 35.6, 35.7],
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "distribution-slot.xlsx"
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name="Data", index=False)
            chart_count = add_analytics_workbook_charts(
                writer=writer,
                dataframe=dataframe,
                metric_selection=(ProductionMetricSelection("cycle_time_s", "Cycle Time S"),),
                chart_selection=ProductionChartSelection(
                    time_series=False,
                    histogram=False,
                    violin=True,
                    box=False,
                ),
                data_sheet_name="Data",
                used_names={"Data"},
                sheet_names=["Data"],
                group_fields=("station",),
            )

        assert chart_count == 1
        with zipfile.ZipFile(output_file, "r") as workbook_zip:
            image_sizes = _inserted_image_sizes_px(workbook_zip, "Charts")

    assert len(image_sizes) == 1
    width_px, height_px = image_sizes[0]
    assert width_px <= 8 * 64.0 * 0.96
    assert height_px <= 20 * 20.0 * 0.96
