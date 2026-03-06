import json
from pathlib import Path

import pytest

from modules.cmm_native_parser import native_backend_available, parse_blocks_with_backend
from modules.cmm_parsing import add_tolerances_to_blocks, parse_raw_lines_to_blocks

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
    assert "parse_blocks_with_backend_and_telemetry(self.pdf_raw_text, use_native=False)" in parser_source


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


def test_measurement_rows_parse_for_single_token_start_format():
    raw_lines = [
        "#SINGLE TOKEN",
        "DIM",
        "X",
        "10",
        "0.2",
        "-0.2",
        "10.1",
        "0.1",
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

    assert any([line[0] for line in block[1]] == ["X", "Y"] for block in parsed)


def test_measurement_rows_parse_for_inline_code_and_numbers_format():
    raw_lines = [
        "#INLINE TOKENS",
        "DIM",
        "X 10 0.2 -0.2 10.1 0.1 0",
        "Y 5 0.1 -0.1 5.05 0.05 0",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert any([line[0] for line in block[1]] == ["X", "Y"] for block in parsed)


def test_add_tolerances_keeps_explicit_zero_values_for_tp_blocks():
    pdf_blocks_text = [
        [
            [["ZERO TP"]],
            [
                ["X", 10.0, 0.0, 0.0, 0.0, 10.1, 0.1, 0.0],
                ["Y", 5.0, None, None, None, 5.0, 0.0, 0.0],
                ["TP", 0.0, 0.2, "", 0.0, 0.01, 0.01, 0.0],
            ],
        ]
    ]

    add_tolerances_to_blocks(pdf_blocks_text)

    assert pdf_blocks_text[0][1][0] == ["X", 10.0, 0.0, 0.0, 0.0, 10.1, 0.1, 0.0]
    assert pdf_blocks_text[0][1][1][2:5] == [0.1, -0.1, 0.0]


def test_add_tolerances_keeps_explicit_zero_values_for_non_tp_blocks():
    pdf_blocks_text = [
        [
            [["ZERO NON TP"]],
            [
                ["X", 10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0],
                ["Y", 5.0, "", "", "", 5.0, 0.0, 0.0],
                ["Z", 7.0, None, None, None, 7.0, 0.0, 0.0],
            ],
        ]
    ]

    add_tolerances_to_blocks(pdf_blocks_text)

    assert pdf_blocks_text[0][1][0] == ["X", 10.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0]
    assert pdf_blocks_text[0][1][1][2:5] == [0, "", ""]
    assert pdf_blocks_text[0][1][2][2:5] == [0, None, None]


def test_tp_parser_supports_optional_qualifiers_and_semantic_labels():
    raw_lines = [
        "#TP QUALIFIED",
        "DIM",
        "TP RFS NOM 0 +TOL 0.4 BONUS 0.1 MEAS 0.25 DEV 0.25 OUTTOL 0",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed[0][1][0] == ["TP", 0.0, 0.4, 0, 0.1, 0.25, 0.25, 0.0]


def test_tp_parser_defaults_nom_to_zero_when_absent():
    raw_lines = [
        "#TP NOM DEFAULT",
        "DIM",
        "TP MMC +TOL 0.4 BONUS 0.1 MEAS 0.25 DEV 0.25 OUTTOL 0",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed[0][1][0] == ["TP", 0.0, 0.4, 0, 0.1, 0.25, 0.25, 0.0]
