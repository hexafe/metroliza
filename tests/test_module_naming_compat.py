from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = REPO_ROOT / "modules"


PARSER_CAMELCASE_SHIMS = {
    "CMMReportParser.py",
    "ParseReportsThread.py",
}


def test_parser_module_cleanup_removed_camelcase_shims():
    remaining = sorted(path.name for path in MODULES_DIR.glob("*.py") if path.name in PARSER_CAMELCASE_SHIMS)

    assert remaining == [], f"Parser CamelCase shim files must stay removed: {remaining}"
