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


def test_native_unavailable_falls_back_to_python(monkeypatch):
    monkeypatch.setenv("METROLIZA_CMM_PARSER_BACKEND", "auto")
    parser = importlib.reload(cmm_native_parser)
    monkeypatch.setattr(parser, "_native_parse_blocks", None)

    parsed = parser.parse_blocks_with_backend(_sample_lines(), use_native=True)
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
