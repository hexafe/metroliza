import json
import sqlite3
from pathlib import Path

import pytest

from modules.cmm_native_parser import (
    native_backend_available,
    native_persistence_backend_available,
    normalize_measurement_rows,
    parse_blocks_with_backend,
    persist_measurement_rows_python,
    persist_measurement_rows_with_backend_and_telemetry,
)
from modules.cmm_schema import ensure_cmm_report_schema
from modules.cmm_parsing import add_tolerances_to_blocks, parse_raw_lines_to_blocks

FIXTURE_DIR = Path("tests/fixtures/cmm_parser")


def _load_fixtures():
    return [json.loads(path.read_text()) for path in sorted(FIXTURE_DIR.glob("*.json"))]


def _fixture_by_name(name):
    return next(fixture for fixture in _load_fixtures() if fixture["name"] == name)


@pytest.mark.parametrize("fixture", _load_fixtures(), ids=lambda f: f["name"])
def test_parser_interface_matches_fixture_snapshot(fixture):
    parsed = parse_raw_lines_to_blocks(fixture["raw_lines"])
    assert json.dumps(parsed, separators=(",", ":")) == json.dumps(
        fixture["expected_blocks"], separators=(",", ":")
    )


def test_cmm_report_parser_wired_to_interface_layer():
    parser_source = Path("modules/cmm_report_parser.py").read_text()
    assert "parse_blocks_with_backend_and_telemetry(self.pdf_raw_text)" in parser_source
    assert "parse_blocks_with_backend_and_telemetry(self.pdf_raw_text, use_native=False)" not in parser_source


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


def test_interrupted_multiline_fixture_keeps_single_block_intent_explicit():
    fixture = _fixture_by_name("interrupted multi-line token stream parses as one block")

    parsed = parse_raw_lines_to_blocks(fixture["raw_lines"])

    assert len(parsed) == 1
    assert [line[0] for line in parsed[0][1]] == ["X", "Y"]


def test_unusual_token_layout_fixture_preserves_semantic_tp_and_numeric_x_mapping():
    fixture = _fixture_by_name("unusual token/layout variants preserve parser semantics")

    parsed = parse_raw_lines_to_blocks(fixture["raw_lines"])

    assert len(parsed) == 1
    assert parsed[0][0] == [["TOKEN LABELS"]]
    assert parsed[0][1][0] == ["X", 10.0, 0.2, -0.2, "", 10.1, 0.1, 0.0]
    assert parsed[0][1][1] == ["TP", 0.0, 0.3, 0, 0.05, 0.12, 0.12, 0.0]


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


def test_trailing_comment_does_not_leave_terminal_empty_block():
    raw_lines = [
        "#RUNTIME",
        "DIM",
        "X 10 0.2 -0.2 10.03 0.03 0",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed == [[[["RUNTIME"]], [["X", 10.0, 0.2, -0.2, 0, 10.03, 0.03, 0.0]]]]


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


def test_multiline_tp_rows_preserve_semantic_tokens_and_tolerance_propagation():
    raw_lines = [
        "#TP MULTILINE",
        "DIM",
        "X 10 0.1 -0.1 10.0 0 0",
        "TP",
        "MMC",
        "+TOL",
        "0.4",
        "BONUS",
        "0.1",
        "MEAS",
        "0.25",
        "DEV",
        "0.25",
        "OUTTOL",
        "0",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed[0][1][1] == ["TP", 0.0, 0.4, 0, 0.1, 0.25, 0.25, 0.0]
    assert parsed[0][1][0] == ["X", 10.0, 0.1, -0.1, "", 10.0, 0.0, 0.0]


def test_interrupted_block_starts_new_header_after_measurement_gap():
    raw_lines = [
        "#BLOCK ONE",
        "DIM",
        "X 1 0.1 -0.1 1.0 0 0",
        "#BLOCK TWO",
        "DIM",
        "Y 2 0.2 -0.2 2.0 0 0",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert [block[0] for block in parsed] == [[["BLOCK ONE"]], [["BLOCK TWO"]]]
    assert parsed[0][1] == [["X", 1.0, 0.1, -0.1, 0.0, 1.0, 0.0, 0.0]]
    assert parsed[1][1] == []


def test_malformed_numeric_tokens_are_dropped_without_breaking_following_rows():
    raw_lines = [
        "#MALFORMED",
        "DIM",
        "X 10 BAD -0.2 10.1 0.1 0",
        "Y 5 0.1 -0.1 5.05 0.05 0",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed == [[[ ["MALFORMED"] ], []]]


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
    assert pdf_blocks_text[0][1][1][2:5] == [0, 0, 0]
    assert pdf_blocks_text[0][1][2][2:5] == [0, 0, 0]


def test_add_tolerances_non_tp_propagates_all_missing_fields_from_explicit_row():
    pdf_blocks_text = [
        [
            [["NON TP PROPAGATION"]],
            [
                ["X", 10.0, 0.2, -0.2, 0.1, 10.0, 0.0, 0.0],
                ["Y", 5.0, "", "", "", 5.0, 0.0, 0.0],
            ],
        ]
    ]

    add_tolerances_to_blocks(pdf_blocks_text)

    assert pdf_blocks_text[0][1][1][2:5] == [0.2, -0.2, 0.1]


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



@pytest.mark.parametrize("qualifier", ["RFS", "MMC", "LMC", "MMB", "LMB", "TANGENT", "PROJECTED"])
def test_tp_parser_defaults_nom_to_zero_for_qualified_numeric_only_rows(qualifier):
    raw_lines = [
        "#TP QUALIFIED NUMERIC",
        "DIM",
        f"TP {qualifier} 0.600 0.000 0.237 0.237 0.000",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed[0][1][0] == ["TP", 0.0, 0.6, 0, 0.0, 0.237, 0.237, 0.0]


def test_tp_parser_keeps_explicit_nom_for_qualified_rows_with_nom_label():
    raw_lines = [
        "#TP QUALIFIED EXPLICIT NOM",
        "DIM",
        "TP RFS NOM 0.600 +TOL 0.200 BONUS 0.000 MEAS 0.237 DEV 0.237 OUTTOL 0.000",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed[0][1][0] == ["TP", 0.6, 0.2, 0, 0.0, 0.237, 0.237, 0.0]


def test_native_parser_matches_python_for_non_tp_token_normalization_edge_when_available():
    if not native_backend_available():
        pytest.skip("Native CMM parser prototype module is not built in this environment")

    raw_lines = [
        "#TOKEN NORMALIZATION",
        "DIM",
        "M NOM 5 +TOL 0.1 -TOL -0.1 BONUS 0.0 MEAS 5.02 DEV 0.02 OUTTOL 0",
        "#END",
    ]

    native = parse_blocks_with_backend(raw_lines, use_native=True)
    python = parse_blocks_with_backend(raw_lines, use_native=False)

    assert native == python


def test_native_parser_matches_python_for_tolerance_propagation_edge_when_available():
    if not native_backend_available():
        pytest.skip("Native CMM parser prototype module is not built in this environment")

    raw_lines = [
        "#TOL PROPAGATION",
        "DIM",
        "X 10 0.2 -0.2 10.03 0.03 0",
        "Y 5",
        "5.0",
        "0",
        "#END",
    ]

    native = parse_blocks_with_backend(raw_lines, use_native=True)
    python = parse_blocks_with_backend(raw_lines, use_native=False)

    assert native == python


def test_native_parser_matches_python_for_mixed_tp_and_non_tp_semantic_tokens_when_available():
    if not native_backend_available():
        pytest.skip("Native CMM parser prototype module is not built in this environment")

    raw_lines = [
        "#MIXED TOKENS",
        "DIM",
        "X NOM 10 +TOL 0.2 -TOL -0.2 MEAS 10.1 DEV 0.1 OUTTOL 0",
        "TP MMC +TOL 0.4 BONUS 0.1 MEAS 0.25 DEV 0.25 OUTTOL 0",
        "#END",
    ]

    native = parse_blocks_with_backend(raw_lines, use_native=True)
    python = parse_blocks_with_backend(raw_lines, use_native=False)

    assert native == python

def test_non_tp_x_parser_ignores_semantic_labels_without_shifting_values():
    raw_lines = [
        "#X LABELED",
        "DIM",
        "X NOM 10 +TOL 0.2 -TOL -0.2 MEAS 10.1 DEV 0.1 OUTTOL 0",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed[0][1][0] == ["X", 10.0, 0.2, -0.2, 0, 10.1, 0.1, 0.0]


def test_non_tp_m_parser_ignores_semantic_labels_without_shifting_values():
    raw_lines = [
        "#M LABELED",
        "DIM",
        "M NOM 5 +TOL 0.1 -TOL -0.1 BONUS 0.0 MEAS 5.02 DEV 0.02 OUTTOL 0",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert parsed[0][1][0] == ["M", 5.0, 0.1, -0.1, 0.0, 5.02, 0.02, 0.0]



def test_dim_ax_subrows_d1_d2_d3_parse_with_eight_column_shape():
    raw_lines = [
        "#AX SUBROWS",
        "DIM",
        "D1 10 0.2 -0.2 10.03",
        "D2 20 0.2 -0.2 20.01",
        "D3 30 0.2 -0.2 29.98",
        "#END",
    ]

    parsed = parse_raw_lines_to_blocks(raw_lines)

    assert [line[0] for line in parsed[0][1]] == ["D1", "D2", "D3"]
    assert parsed[0][1][0] == ["D1", 10.0, 0.2, -0.2, 0, 10.03, "", ""]
    assert parsed[0][1][1] == ["D2", 20.0, 0.2, -0.2, 0, 20.01, "", ""]
    assert parsed[0][1][2] == ["D3", 30.0, 0.2, -0.2, 0, 29.98, "", ""]


def test_dim_ax_subrows_d1_d2_d3_rows_reach_sqlite_via_to_sqlite(tmp_path):
    import importlib.machinery
    import importlib.util
    import sys
    import types
    from pathlib import Path

    custom_logger_stub = types.ModuleType("modules.custom_logger")
    custom_logger_stub.CustomLogger = type("CustomLogger", (), {"__init__": lambda self, *args, **kwargs: None})
    sys.modules["modules.custom_logger"] = custom_logger_stub

    fitz_stub = types.ModuleType("fitz")
    fitz_stub.__spec__ = importlib.machinery.ModuleSpec("fitz", loader=None)
    sys.modules["fitz"] = fitz_stub
    pymupdf_stub = types.ModuleType("pymupdf")
    pymupdf_stub.__spec__ = importlib.machinery.ModuleSpec("pymupdf", loader=None)
    sys.modules["pymupdf"] = pymupdf_stub

    parser_spec = importlib.util.spec_from_file_location(
        "_cmm_report_parser_real_for_test", Path("modules/cmm_report_parser.py")
    )
    assert parser_spec is not None and parser_spec.loader is not None
    parser_module = importlib.util.module_from_spec(parser_spec)
    parser_spec.loader.exec_module(parser_module)
    CMMReportParser = parser_module.CMMReportParser

    from modules.db import execute_with_retry

    db_path = str(tmp_path / "cmm.db")
    ensure_cmm_report_schema(db_path)
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", db_path)
    parser.pdf_reference = "REF01"
    parser.pdf_file_path = "/tmp/reports"
    parser.pdf_file_name = "REF01_2024-01-02_123.pdf"
    parser.pdf_date = "2024-01-02"
    parser.pdf_sample_number = "123"
    parser.pdf_blocks_text = parse_raw_lines_to_blocks(
        [
            "#AX SUBROWS",
            "DIM",
            "D1 10 0.2 -0.2 10.03",
            "D2 20 0.2 -0.2 20.01",
            "D3 30 0.2 -0.2 29.98",
            "#END",
        ]
    )

    parser.to_sqlite()

    rows = execute_with_retry(
        db_path,
        'SELECT AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL FROM MEASUREMENTS ORDER BY AX',
    )

    assert rows == [
        ("D1", 10.0, 0.2, -0.2, 0.0, 10.03, "", ""),
        ("D2", 20.0, 0.2, -0.2, 0.0, 20.01, "", ""),
        ("D3", 30.0, 0.2, -0.2, 0.0, 29.98, "", ""),
    ]


def _load_cmm_report_parser_with_test_stubs():
    import importlib.machinery
    import importlib.util
    import sys
    import types

    custom_logger_stub = types.ModuleType("modules.custom_logger")
    custom_logger_stub.CustomLogger = type("CustomLogger", (), {"__init__": lambda self, *args, **kwargs: None})
    sys.modules["modules.custom_logger"] = custom_logger_stub

    fitz_stub = types.ModuleType("fitz")
    fitz_stub.__spec__ = importlib.machinery.ModuleSpec("fitz", loader=None)
    sys.modules["fitz"] = fitz_stub
    pymupdf_stub = types.ModuleType("pymupdf")
    pymupdf_stub.__spec__ = importlib.machinery.ModuleSpec("pymupdf", loader=None)
    sys.modules["pymupdf"] = pymupdf_stub

    parser_spec = importlib.util.spec_from_file_location(
        "_cmm_report_parser_real_for_pipeline_test", Path("modules/cmm_report_parser.py")
    )
    assert parser_spec is not None and parser_spec.loader is not None
    parser_module = importlib.util.module_from_spec(parser_spec)
    parser_spec.loader.exec_module(parser_module)
    return parser_module.CMMReportParser


def _assert_tp_pipeline_roundtrip(parsed_blocks, tmp_path):
    from modules.db import execute_with_retry

    CMMReportParser = _load_cmm_report_parser_with_test_stubs()

    assert parsed_blocks[0][1][0] == ["TP", 0.0, 0.2, 0, 0.0, 0.344, 0.344, 0.144]

    db_path = str(tmp_path / "tp_pipeline.db")
    ensure_cmm_report_schema(db_path)
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", db_path)
    parser.pdf_reference = "REF01"
    parser.pdf_file_path = "/tmp/reports"
    parser.pdf_file_name = "REF01_2024-01-02_123.pdf"
    parser.pdf_date = "2024-01-02"
    parser.pdf_sample_number = "123"
    parser.pdf_blocks_text = parsed_blocks
    parser.to_sqlite()

    measurement_rows = execute_with_retry(
        db_path,
        'SELECT NOM, "+TOL", BONUS, MEAS, DEV, OUTTOL FROM MEASUREMENTS WHERE AX = "TP"',
    )
    assert measurement_rows == [(0.0, 0.2, 0.0, 0.344, 0.344, 0.144)]

    with sqlite3.connect(db_path) as conn:
        export_rows = conn.execute(
            """
            SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL",
                MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS,
                MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE,
                REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
            WHERE 1=1
            """
        ).fetchall()

    assert export_rows == [
        (
            "TP",
            0.0,
            0.2,
            0.0,
            0.0,
            0.344,
            0.344,
            0.144,
            "TP QUALIFIER PIPELINE",
            "REF01",
            "/tmp/reports",
            "REF01_2024-01-02_123.pdf",
            "2024-01-02",
            "123",
        )
    ]


def test_tp_qualifier_pipeline_roundtrip_python_backend(tmp_path):
    raw_lines = [
        "#TP QUALIFIER PIPELINE",
        "DIM",
        "TP RFS 0.200 0.000 0.344 0.344 0.144",
        "#END",
    ]

    parsed = parse_blocks_with_backend(raw_lines, use_native=False)
    _assert_tp_pipeline_roundtrip(parsed, tmp_path)


def test_tp_qualifier_pipeline_roundtrip_native_backend_when_available(tmp_path):
    if not native_backend_available():
        pytest.skip("Native CMM parser prototype module is not built in this environment")

    raw_lines = [
        "#TP QUALIFIER PIPELINE",
        "DIM",
        "TP RFS 0.200 0.000 0.344 0.344 0.144",
        "#END",
    ]

    parsed = parse_blocks_with_backend(raw_lines, use_native=True)
    _assert_tp_pipeline_roundtrip(parsed, tmp_path)


def test_measurement_row_normalization_parity_python_vs_native_when_available():
    if not native_persistence_backend_available():
        pytest.skip("Native CMM persistence module is not built in this environment")

    blocks = parse_blocks_with_backend(
        [
            "#ROW PARITY",
            "DIM",
            "D1 10 0.2 -0.2 10.03",
            "TP RFS 0.200 0.000 0.344 0.344 0.144",
            "#END",
        ],
        use_native=False,
    )
    meta = dict(
        reference="REF01",
        fileloc="/tmp/reports",
        filename="REF01_2024-01-02_123.pdf",
        date="2024-01-02",
        sample_number="123",
    )

    rows_python = normalize_measurement_rows(blocks, **meta, use_native=False)
    rows_native = normalize_measurement_rows(blocks, **meta, use_native=True)

    assert rows_python == rows_native
    assert len(rows_python) == len(rows_native)


def test_measurement_row_persistence_parity_python_vs_native_when_available(tmp_path):
    if not native_persistence_backend_available():
        pytest.skip("Native CMM persistence module is not built in this environment")

    blocks = parse_blocks_with_backend(
        [
            "#PERSIST PARITY",
            "DIM",
            "D1 10 0.2 -0.2 10.03",
            "D2 20 0.2 -0.2 20.01",
            "#END",
        ],
        use_native=False,
    )
    rows = normalize_measurement_rows(
        blocks,
        reference="REF01",
        fileloc="/tmp/reports",
        filename="REF01_2024-01-02_123.pdf",
        date="2024-01-02",
        sample_number="123",
        use_native=False,
    )

    py_db = str(tmp_path / "py_insert.db")
    native_db = str(tmp_path / "native_insert.db")
    ensure_cmm_report_schema(py_db)
    ensure_cmm_report_schema(native_db)
    assert persist_measurement_rows_python(py_db, rows) is True
    assert persist_measurement_rows_python(py_db, rows) is False
    native_result = persist_measurement_rows_with_backend_and_telemetry(native_db, rows, use_native=True)
    assert native_result.backend == "native"
    assert native_result.inserted is True
    native_duplicate_result = persist_measurement_rows_with_backend_and_telemetry(
        native_db, rows, use_native=True
    )
    assert native_duplicate_result.backend == "native"
    assert native_duplicate_result.inserted is False

    with sqlite3.connect(py_db) as py_conn, sqlite3.connect(native_db) as native_conn:
        py_rows = py_conn.execute(
            """
            SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL",
                MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS,
                MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE,
                REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
            ORDER BY MEASUREMENTS.ID
            """
        ).fetchall()
        native_rows = native_conn.execute(
            """
            SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL",
                MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS,
                MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE,
                REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER
            FROM MEASUREMENTS
            JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
            ORDER BY MEASUREMENTS.ID
            """
        ).fetchall()

    assert py_rows == native_rows


@pytest.fixture
def large_measurement_rows():
    row_count = 20_000
    header = "LARGE ROW PARITY"
    return [
        (
            f"D{idx}",
            10.0 + idx,
            0.2,
            -0.2,
            0.0,
            10.01 + idx,
            0.01,
            0.0,
            header,
            "REF_LARGE",
            "/tmp/reports",
            "REF_LARGE_2024-01-02_999.pdf",
            "2024-01-02",
            "999",
        )
        for idx in range(row_count)
    ]


def test_measurement_row_persistence_duplicate_detection_python_backend(tmp_path):
    rows = [
        (
            "D1",
            10.0,
            0.2,
            -0.2,
            0.0,
            10.03,
            0.03,
            0.0,
            "PERSIST PARITY",
            "REF01",
            "/tmp/reports",
            "REF01_2024-01-02_123.pdf",
            "2024-01-02",
            "123",
        )
    ]
    py_db = str(tmp_path / "py_duplicate.db")
    ensure_cmm_report_schema(py_db)

    assert persist_measurement_rows_python(py_db, rows) is True
    assert persist_measurement_rows_python(py_db, rows) is False

    with sqlite3.connect(py_db) as conn:
        report_count = conn.execute("SELECT COUNT(*) FROM REPORTS").fetchone()
        measurement_count = conn.execute("SELECT COUNT(*) FROM MEASUREMENTS").fetchone()

    assert report_count == (1,)
    assert measurement_count == (1,)


def test_large_row_persistence_python_backend(tmp_path, large_measurement_rows):
    py_db = str(tmp_path / "py_large_insert.db")
    ensure_cmm_report_schema(py_db)

    assert persist_measurement_rows_python(py_db, large_measurement_rows) is True
    assert persist_measurement_rows_python(py_db, large_measurement_rows) is False

    with sqlite3.connect(py_db) as conn:
        report_count = conn.execute("SELECT COUNT(*) FROM REPORTS").fetchone()
        measurement_count = conn.execute("SELECT COUNT(*) FROM MEASUREMENTS").fetchone()

    assert report_count == (1,)
    assert measurement_count == (len(large_measurement_rows),)


def test_large_row_persistence_parity_python_vs_native_when_available(tmp_path, large_measurement_rows):
    if not native_persistence_backend_available():
        pytest.skip("Native CMM persistence module is not built in this environment")

    py_db = str(tmp_path / "py_large_insert.db")
    native_db = str(tmp_path / "native_large_insert.db")
    ensure_cmm_report_schema(py_db)
    ensure_cmm_report_schema(native_db)

    assert persist_measurement_rows_python(py_db, large_measurement_rows) is True
    native_result = persist_measurement_rows_with_backend_and_telemetry(
        native_db, large_measurement_rows, use_native=True
    )
    assert native_result.backend == "native"
    assert native_result.inserted is True

    with sqlite3.connect(py_db) as py_conn, sqlite3.connect(native_db) as native_conn:
        py_counts = py_conn.execute(
            "SELECT COUNT(*) FROM REPORTS, MEASUREMENTS WHERE REPORTS.ID = MEASUREMENTS.REPORT_ID"
        ).fetchone()
        native_counts = native_conn.execute(
            "SELECT COUNT(*) FROM REPORTS, MEASUREMENTS WHERE REPORTS.ID = MEASUREMENTS.REPORT_ID"
        ).fetchone()
        py_edges = py_conn.execute(
            """
            SELECT AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER
            FROM MEASUREMENTS
            ORDER BY ID
            LIMIT 1
            """
        ).fetchone(), py_conn.execute(
            """
            SELECT AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER
            FROM MEASUREMENTS
            ORDER BY ID DESC
            LIMIT 1
            """
        ).fetchone()
        native_edges = native_conn.execute(
            """
            SELECT AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER
            FROM MEASUREMENTS
            ORDER BY ID
            LIMIT 1
            """
        ).fetchone(), native_conn.execute(
            """
            SELECT AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER
            FROM MEASUREMENTS
            ORDER BY ID DESC
            LIMIT 1
            """
        ).fetchone()

    assert py_counts == native_counts == (len(large_measurement_rows),)
    assert py_edges == native_edges


def test_cmm_report_parser_records_parse_and_db_stage_timings(tmp_path):
    CMMReportParser = _load_cmm_report_parser_with_test_stubs()

    db_path = str(tmp_path / "timing.db")
    ensure_cmm_report_schema(db_path)
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", db_path)
    parser.pdf_raw_text = [
        "#TIMING",
        "DIM",
        "X 10 0.2 -0.2 10.03 0.03 0",
        "#END",
    ]
    parser.split_text_to_blocks()
    parser.add_tolerances()
    parser.to_sqlite()

    assert parser.stage_timings_s["parse_batch_runtime"] >= 0.0
    assert parser.stage_timings_s["db_write_runtime"] >= 0.0


def test_cmm_report_parser_split_text_to_blocks_uses_runtime_backend_result():
    CMMReportParser = _load_cmm_report_parser_with_test_stubs()

    parser = CMMReportParser("REF01_2024-01-02_123.pdf", database=":memory:")
    parser.pdf_raw_text = [
        "#RUNTIME BACKEND",
        "DIM",
        "X 10 0.2 -0.2 10.03 0.03 0",
        "#END",
    ]

    fake_calls = {"count": 0}

    def _fake_parse_blocks(raw_lines):
        fake_calls["count"] += 1
        assert raw_lines == parser.pdf_raw_text
        return type(
            "ParseResult",
            (),
            {"blocks": [[["RUNTIME BACKEND"], [["X", 10.0, 0.2, -0.2, "", 10.03, 0.03, 0.0]]]], "backend": "native"},
        )()

    split_globals = CMMReportParser.split_text_to_blocks.__globals__
    original_parse_blocks = split_globals["parse_blocks_with_backend_and_telemetry"]
    split_globals["parse_blocks_with_backend_and_telemetry"] = _fake_parse_blocks
    try:
        parser.split_text_to_blocks()
    finally:
        split_globals["parse_blocks_with_backend_and_telemetry"] = original_parse_blocks

    assert fake_calls["count"] == 1
    assert parser.parse_backend_used == "native"
    assert parser.blocks_text == [[["RUNTIME BACKEND"], [["X", 10.0, 0.2, -0.2, "", 10.03, 0.03, 0.0]]]]
