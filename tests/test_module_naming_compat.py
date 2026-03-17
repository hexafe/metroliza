import importlib
import sys
import types
from pathlib import Path


LEGACY_TO_SNAKE = {
    "AboutWindow": "about_window",
    "Base64EncodedFiles": "base64_encoded_files",
    "CMMReportParser": "cmm_report_parser",
    "CSVSummaryDialog": "csv_summary_dialog",
    "CustomLogger": "custom_logger",
    "DataGrouping": "data_grouping",
    "ExportDataThread": "export_data_thread",
    "ExportDialog": "export_dialog",
    "FilterDialog": "filter_dialog",
    "LicenseKeyManager": "license_key_manager",
    "MainWindow": "main_window",
    "ModifyDB": "modify_db",
    "ParseReportsThread": "parse_reports_thread",
    "ParsingDialog": "parsing_dialog",
    "ReleaseNotesDialog": "release_notes_dialog",
}


def test_legacy_modules_are_shims_to_snake_case():
    modules_dir = Path(__file__).resolve().parents[1] / "modules"

    for legacy, snake in LEGACY_TO_SNAKE.items():
        source = (modules_dir / f"{legacy}.py").read_text(encoding="utf-8")
        assert "Compatibility shim for legacy CamelCase module imports." in source
        assert f"from modules.{snake} import *" in source


def test_snake_case_and_legacy_imports_work_for_core_pairs():
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtwidgets.QMessageBox = type("QMessageBox", (), {})
    sys.modules.setdefault("PyQt6", types.ModuleType("PyQt6"))
    sys.modules["PyQt6.QtWidgets"] = qtwidgets

    for snake, legacy in [
        ("modules.custom_logger", "modules.CustomLogger"),
        ("modules.base64_encoded_files", "modules.Base64EncodedFiles"),
    ]:
        snake_module = importlib.import_module(snake)
        legacy_module = importlib.import_module(legacy)
        assert snake_module is not None
        assert legacy_module is not None
