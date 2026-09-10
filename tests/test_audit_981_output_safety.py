"""Falsify #981's structural assertions with inert, task-private bad artifacts."""

from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

import pytest

from tests.audit_981_output_safety import (
    BREAKOUT,
    FORBIDDEN,
    NS,
    assert_chart_names_literal,
    assert_no_marker,
    assert_preserved,
    inspect_html,
    inspect_xlsx,
    parse_html,
    run,
    snapshot,
)


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    directory = tmp_path_factory.mktemp("audit981") / "generated żółć"
    # Select the existing supported in-repository Plotly builder in this process.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("METROLIZA_PLOTSTATS_EXPORT_CHARTS", "0")
        result = run(directory)
    return directory, result


def test_real_serializers_and_publication_seams(artifacts):
    _, result = artifacts
    assert len(result["cases"]) == 22
    assert sum(case["mode"] == "success" for case in result["cases"]) == 4


def altered_workbook(source: Path, target: Path, member: str, transform):
    with ZipFile(source) as original, ZipFile(target, "w") as altered:
        for name in original.namelist():
            data = original.read(name)
            altered.writestr(name, transform(data) if name == member else data)


def test_inert_imported_formula_is_detected(artifacts, tmp_path):
    """Deliberately bad artifact, not product execution or an Excel payload run."""
    directory, _ = artifacts
    source = directory / "xlsx False success" / "wynik żółć.xlsx"
    target = tmp_path / "bad formula.xlsx"

    def add_formula(data):
        sheet = ET.fromstring(data)
        cell = sheet.find('.//s:c[@r="A2"]', NS)
        cell.attrib.pop("t")
        ET.SubElement(cell, f"{{{NS['s']}}}f").text = "1+1"
        return ET.tostring(sheet)

    altered_workbook(source, target, "xl/worksheets/sheet1.xml", add_formula)
    with pytest.raises(AssertionError, match="imported text became active cell"):
        inspect_xlsx(target)


def test_forbidden_hidden_property_is_detected(artifacts, tmp_path):
    directory, _ = artifacts
    source = directory / "xlsx False success" / "wynik żółć.xlsx"
    target = tmp_path / "bad property.xlsx"

    def add_marker(data):
        root = ET.fromstring(data)
        root.set("audit", FORBIDDEN)
        return ET.tostring(root)

    altered_workbook(source, target, "docProps/core.xml", add_marker)
    with pytest.raises(AssertionError, match="non-export marker escaped"):
        inspect_xlsx(target)


def test_truncated_workbook_is_detected(artifacts, tmp_path):
    directory, _ = artifacts
    target = tmp_path / "truncated.xlsx"
    target.write_bytes((directory / "xlsx False success" / "wynik żółć.xlsx").read_bytes()[:100])
    with pytest.raises(BadZipFile):
        inspect_xlsx(target)


def test_inert_script_boundary_breakout_is_detected():
    # Only application/json script blocks; never executable JS, shell, or network.
    bad = '<html><script type="application/json">{"label":"' + BREAKOUT + '"}</script></html>'
    with pytest.raises(AssertionError, match="script boundary escaped"):
        parse_html(bad)


def test_forbidden_html_comment_is_detected():
    with pytest.raises(AssertionError, match="non-export marker escaped"):
        parse_html(f"<html><!--{FORBIDDEN}--></html>")


def test_truncated_html_is_detected():
    with pytest.raises(AssertionError, match="incomplete HTML document"):
        parse_html("<html><body>partial")


def test_missing_asset_is_detected(artifacts, tmp_path):
    directory, _ = artifacts
    target = tmp_path / "copied without assets.html"
    target.write_bytes((directory / "html False success" / "dashboard żółć.html").read_bytes())
    with pytest.raises(AssertionError, match="missing offline asset"):
        inspect_html(target)


def test_changed_last_good_hash_is_detected():
    with pytest.raises(AssertionError, match="last-complete artifact changed"):
        assert_preserved({"artifact": "old-hash"}, {"artifact": "different-hash"})


def test_raw_nonexport_error_marker_is_detected():
    with pytest.raises(AssertionError, match="non-export marker escaped"):
        assert_no_marker([f"synthetic error: {FORBIDDEN}".encode()])


@pytest.mark.parametrize("name_context", ["title", "series"])
def test_chart_name_formula_control(name_context):
    # This hand-built XML is an assertion control, not a generated product artifact.
    wrapper = "<c:title>{}</c:title>" if name_context == "title" else "<c:ser><c:tx>{}</c:tx></c:ser>"
    name = wrapper.format("<c:strRef><c:f>Data!A1</c:f></c:strRef>")
    root = ET.fromstring('<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">' + name + "</c:chart>")
    with pytest.raises(AssertionError, match="became formula"):
        assert_chart_names_literal(root)


def test_chart_name_control_preserves_authored_data_ranges():
    root = ET.fromstring('<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
                         '<c:title><c:tx><c:rich>literal</c:rich></c:tx></c:title>'
                         '<c:ser><c:tx><c:v>literal</c:v></c:tx><c:val><c:numRef><c:f>Data!B2:B3</c:f>'
                         '</c:numRef></c:val></c:ser></c:chart>')
    assert_chart_names_literal(root, "literal")


def test_chart_name_control_rejects_missing_labels():
    root = ET.fromstring('<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"/>')
    with pytest.raises(AssertionError, match="literal title missing"):
        assert_chart_names_literal(root, "literal")


def test_empty_generation_directory_is_detected(tmp_path):
    before = snapshot(tmp_path)
    (tmp_path / "dashboard_assets.generation-inert").mkdir()
    with pytest.raises(AssertionError, match="last-complete artifact changed"):
        assert_preserved(before, snapshot(tmp_path))
