import re
from pathlib import Path


LEGACY_CAMELCASE_MODULES = {
    "AboutWindow.py",
    "Base64EncodedFiles.py",
    "CMMReportParser.py",
    "CSVSummaryDialog.py",
    "CustomLogger.py",
    "DataGrouping.py",
    "ExportDataThread.py",
    "ExportDialog.py",
    "FilterDialog.py",
    "LicenseKeyManager.py",
    "MainWindow.py",
    "ModifyDB.py",
    "ParseReportsThread.py",
    "ParsingDialog.py",
    "ReleaseNotesDialog.py",
}


SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.py$")


def test_modules_directory_filenames_follow_policy():
    module_dir = Path("modules")
    discovered = {path.name for path in module_dir.glob("*.py")}

    unexpected_camelcase = sorted(
        name
        for name in discovered
        if not SNAKE_CASE_PATTERN.match(name) and name not in LEGACY_CAMELCASE_MODULES
    )

    assert not unexpected_camelcase, (
        "Found non-snake-case module filenames not covered by the legacy migration allowlist: "
        f"{unexpected_camelcase}"
    )
