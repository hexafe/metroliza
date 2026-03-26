import importlib

from modules import cmm_native_parser


def _sample_lines():
    return ["Characteristic", "AX 1 1.0 +0.1 -0.1 0 1.0 0 OK", "" ]


def test_force_python_backend_via_env(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "python")
    parser = importlib.reload(cmm_native_parser)

    parsed = parser.parse_blocks_with_backend(_sample_lines(), use_native=True)
    assert parsed == parser.parse_raw_lines_to_blocks(_sample_lines())


def test_invalid_backend_value_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "invalid")
    parser = importlib.reload(cmm_native_parser)

    parsed = parser.parse_blocks_with_backend(_sample_lines())
    assert parsed == parser.parse_raw_lines_to_blocks(_sample_lines())


def test_auto_mode_falls_back_to_python_when_native_is_unavailable(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "auto")
    parser = importlib.reload(cmm_native_parser)
    monkeypatch.setattr(parser, "_native_parse_blocks", None)

    parsed = parser.parse_blocks_with_backend(_sample_lines())
    assert parsed == parser.parse_raw_lines_to_blocks(_sample_lines())


def test_native_mode_raises_when_native_is_unavailable(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "native")
    parser = importlib.reload(cmm_native_parser)
    monkeypatch.setattr(parser, "_native_parse_blocks", None)

    try:
        parser.parse_blocks_with_backend(_sample_lines())
    except Exception:
        return
    raise AssertionError("native backend mode must raise when native parser is unavailable")


def test_parse_blocks_with_backend_and_telemetry_reports_python_backend(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "python")
    parser = importlib.reload(cmm_native_parser)

    result = parser.parse_blocks_with_backend_and_telemetry(_sample_lines(), use_native=False)

    assert result.backend == "python"
    assert result.blocks == parser.parse_raw_lines_to_blocks(_sample_lines())


def test_parse_blocks_with_backend_and_telemetry_reports_native_backend(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "native")
    parser = importlib.reload(cmm_native_parser)

    if parser._native_parse_blocks is None:
        try:
            parser.parse_blocks_with_backend_and_telemetry(_sample_lines())
        except RuntimeError:
            return
        raise AssertionError("native backend mode must raise when native parser is unavailable")

    result = parser.parse_blocks_with_backend_and_telemetry(
        [
            "#TP MULTILINE",
            "DIM",
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
    )

    assert result.backend == "native"
    assert result.blocks == parser.parse_raw_lines_to_blocks(
        [
            "#TP MULTILINE",
            "DIM",
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
    )


def test_backend_telemetry_snapshot_counts_and_rates_for_python_parse(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "python")
    parser = importlib.reload(cmm_native_parser)

    parser.reset_backend_telemetry()
    parser.parse_blocks_with_backend_and_telemetry(_sample_lines(), use_native=False)
    parser.parse_blocks_with_backend_and_telemetry(_sample_lines(), use_native=False)
    snapshot = parser.get_backend_telemetry_snapshot()

    assert snapshot["parse"]["python"] == 2
    assert snapshot["parse"]["native"] == 0
    assert snapshot["parse"]["total"] == 2
    assert snapshot["parse"]["python_rate"] == 1.0
    assert snapshot["parse"]["native_rate"] == 0.0


def test_backend_telemetry_snapshot_includes_persistence_counts(monkeypatch, tmp_path):
    monkeypatch.setenv("METROLIZA_CMM_PERSIST_BACKEND", "python")
    parser = importlib.reload(cmm_native_parser)
    parser.reset_backend_telemetry()

    rows = [
        ("X", 10.0, 0.2, -0.2, 0.0, 10.1, 0.1, 0.0, "HEADER", "REF", "/tmp", "f.pdf", "2024-01-01", "001"),
    ]
    result = parser.persist_measurement_rows_with_backend_and_telemetry(str(tmp_path / "telemetry.db"), rows)
    snapshot = parser.get_backend_telemetry_snapshot()

    assert result.backend == "python"
    assert snapshot["persistence"]["python"] == 1
    assert snapshot["persistence"]["native"] == 0
    assert snapshot["persistence"]["python_rate"] == 1.0
    assert snapshot["persistence_rows"]["python"] == 1
    assert snapshot["persistence_rows"]["inserted_python"] == 1


def test_backend_telemetry_snapshot_includes_normalization_counts(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PERSIST_BACKEND", "python")
    parser = importlib.reload(cmm_native_parser)
    parser.reset_backend_telemetry()

    blocks = parser.parse_raw_lines_to_blocks(
        [
            "#ROW PARITY",
            "DIM",
            "D1 10 0.2 -0.2 10.03",
            "#END",
        ]
    )
    rows = parser.normalize_measurement_rows(
        blocks,
        reference="REF01",
        fileloc="/tmp/reports",
        filename="REF01_2024-01-02_123.pdf",
        date="2024-01-02",
        sample_number="123",
        use_native=False,
    )
    snapshot = parser.get_backend_telemetry_snapshot()

    assert len(rows) == 1
    assert snapshot["normalize"]["python"] == 1
    assert snapshot["normalize"]["native"] == 0
    assert snapshot["normalize"]["rows_python"] == 1
    assert snapshot["normalize"]["latency_python_s"] >= 0.0


def test_parse_blocks_with_backend_keeps_tp_non_tp_mixed_semantic_token_parity(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "auto")
    parser = importlib.reload(cmm_native_parser)

    raw_lines = [
        "#MIXED TOKENS",
        "DIM",
        "X NOM 10 +TOL 0.2 -TOL -0.2 MEAS 10.1 DEV 0.1 OUTTOL 0",
        "TP MMC +TOL 0.4 BONUS 0.1 MEAS 0.25 DEV 0.25 OUTTOL 0",
        "#END",
    ]

    python = parser.parse_blocks_with_backend(raw_lines, use_native=False)

    if parser._native_parse_blocks is None:
        try:
            parser.parse_blocks_with_backend(raw_lines, use_native=True)
        except RuntimeError:
            assert parser.parse_blocks_with_backend(raw_lines) == python
            return
        raise AssertionError("native backend mode must raise when native parser is unavailable")
        return

    native = parser.parse_blocks_with_backend(raw_lines, use_native=True)
    assert native == python
