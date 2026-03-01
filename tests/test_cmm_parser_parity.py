import json
from pathlib import Path

import pytest

from modules.cmm_native_parser import native_backend_available, parse_blocks_with_backend
from modules.cmm_parsing import parse_raw_lines_to_blocks

FIXTURE_DIR = Path("tests/fixtures/cmm_parser")


def _load_fixtures():
    return [json.loads(path.read_text()) for path in sorted(FIXTURE_DIR.glob("*.json"))]


@pytest.mark.parametrize("fixture", _load_fixtures(), ids=lambda f: f["name"])
def test_parser_interface_matches_fixture_snapshot(fixture):
    parsed = parse_raw_lines_to_blocks(fixture["raw_lines"])
    assert json.dumps(parsed, separators=(",", ":")) == json.dumps(
        fixture["expected_blocks"], separators=(",", ":")
    )


def test_cmm_report_parser_wired_to_interface_layer():
    parser_source = Path("modules/CMMReportParser.py").read_text()
    assert "parse_blocks_with_backend(self.pdf_raw_text, use_native=False)" in parser_source


@pytest.mark.parametrize("fixture", _load_fixtures(), ids=lambda f: f["name"])
def test_native_parser_parity_with_python_backend(fixture):
    if not native_backend_available():
        pytest.skip("Native CMM parser prototype module is not built in this environment")

    native = parse_blocks_with_backend(fixture["raw_lines"], use_native=True)
    python = parse_blocks_with_backend(fixture["raw_lines"], use_native=False)

    assert json.dumps(native, separators=(",", ":")) == json.dumps(
        python, separators=(",", ":")
    )


def test_measurement_tokens_can_span_lines_with_interruptions_without_block_duplication():
    raw_lines = [
        "#INTERRUPTED",
        "DIM",
        "X",
        "10",
        "NOMINAL",
        "0.2",
        "TOL",
        "-0.2",
        "ACT",
        "10.1",
        "DEV",
        "0.1",
        "OUT",
        "0",
        "Y",
        "5",
        "0.1",
        "-0.1",
        "5.05",
        "0.05",
        "0",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert len(parsed) == 1
    assert parsed[0][0] == [["INTERRUPTED"]]
    assert [line[0] for line in parsed[0][1]] == ["X", "Y"]
    assert parsed[0][1][0] == ["X", 10.0, 0.2, -0.2, 0, 10.1, 0.1, 0.0]
    assert parsed[0][1][1] == ["Y", 5.0, 0.1, -0.1, 0, 5.05, 0.05, 0.0]


@pytest.fixture
def first_line_comment_regression_inputs():
    base_lines = [
        "#FIRST HEADER",
        "DIM",
        "X",
        "1",
        "0.1",
        "-0.1",
        "1.0",
        "0.0",
        "0",
    ]
    return (
        base_lines + ["#TRAILING COMMENT"],
        base_lines + ["123 456 789"],
    )


def test_first_line_comment_parsing_is_independent_of_last_line(first_line_comment_regression_inputs):
    trailing_comment_lines, trailing_numeric_triplet_lines = first_line_comment_regression_inputs

    parsed_with_trailing_comment = parse_raw_lines_to_blocks(trailing_comment_lines)
    parsed_with_trailing_numeric_triplet = parse_raw_lines_to_blocks(trailing_numeric_triplet_lines)

    assert parsed_with_trailing_comment[0][0] == [["FIRST HEADER"]]
    assert parsed_with_trailing_numeric_triplet[0][0] == [["FIRST HEADER"]]
