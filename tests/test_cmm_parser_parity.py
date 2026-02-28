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
