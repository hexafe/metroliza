# Python module naming migration status (`modules/`)

This project is standardizing Python modules on `snake_case.py`.

## Current state

- **Canonical implementation location:** `snake_case.py` modules.
- **Import style for app/test code:** `from modules.some_module import ...`.
- **Compatibility direction:** legacy `CamelCase.py` modules are temporary shims that re-export from snake_case modules.

## Shimmed modules (temporary)

| Legacy module | Canonical snake_case module | Status |
| --- | --- | --- |
| `AboutWindow.py` | `about_window.py` | ✅ canonical flipped |
| `Base64EncodedFiles.py` | `base64_encoded_files.py` | ✅ canonical flipped |
| `CMMReportParser.py` | `cmm_report_parser.py` | ✅ canonical flipped |
| `CSVSummaryDialog.py` | `csv_summary_dialog.py` | ✅ canonical flipped |
| `CustomLogger.py` | `custom_logger.py` | ✅ canonical flipped |
| `DataGrouping.py` | `data_grouping.py` | ✅ canonical flipped |
| `ExportDataThread.py` | `export_data_thread.py` | ✅ canonical flipped |
| `ExportDialog.py` | `export_dialog.py` | ✅ canonical flipped |
| `FilterDialog.py` | `filter_dialog.py` | ✅ canonical flipped |
| `LicenseKeyManager.py` | `license_key_manager.py` | ✅ canonical flipped |
| `MainWindow.py` | `main_window.py` | ✅ canonical flipped |
| `ModifyDB.py` | `modify_db.py` | ✅ canonical flipped |
| `ParseReportsThread.py` | `parse_reports_thread.py` | ✅ canonical flipped |
| `ParsingDialog.py` | `parsing_dialog.py` | ✅ canonical flipped |
| `ReleaseNotesDialog.py` | `release_notes_dialog.py` | ✅ canonical flipped |

## Compatibility shim pattern

Legacy files now use this pattern:

```python
from modules.snake_case_name import *  # noqa: F401,F403
```

## Final removal criteria for legacy shims

Remove legacy `CamelCase.py` shim files only when **all** criteria are met:

1. A full-repo search shows no remaining imports of `modules.CamelCaseName` in first-party code (including scripts/tests/docs examples).
2. Compatibility tests prove snake_case imports are in use and no runtime paths depend on legacy module paths.
3. Release notes communicate the deprecation window and the shim removal release version.
4. One cleanup PR removes all legacy shims in a single change set and updates migration docs accordingly.
