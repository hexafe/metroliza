# Python module naming migration plan (`modules/`)

This project is standardizing Python modules on `snake_case.py`.

## Target convention

- **Preferred module filename format:** `snake_case.py`
- **Import style for new/updated code:** `from modules.some_module import ...`
- **Temporary transition support:** legacy `CamelCase.py` modules remain importable while call sites are migrated.

## Staged migration map

| Stage | Legacy module | Canonical snake_case module | Transition strategy |
| --- | --- | --- | --- |
| 1 (now) | `ParseReportsThread.py` | `parse_reports_thread.py` | Add shim module and migrate imports opportunistically. |
| 1 (now) | `ExportDataThread.py` | `export_data_thread.py` | Add shim module and migrate imports opportunistically. |
| 1 (now) | `ModifyDB.py` | `modify_db.py` | Add shim module and migrate imports opportunistically. |
| 1 (now) | `CMMReportParser.py` | `cmm_report_parser.py` | Add shim module and migrate imports opportunistically. |
| 1 (now) | `MainWindow.py` | `main_window.py` | Add shim module and migrate imports in entrypoints first. |
| 1 (now) | `CustomLogger.py` | `custom_logger.py` | Add shim module and migrate imports opportunistically. |
| 2 (dialogs) | `ParsingDialog.py` | `parsing_dialog.py` | Keep dialog aliases; migrate UI call sites incrementally. |
| 2 (dialogs) | `ExportDialog.py` | `export_dialog.py` | Keep dialog aliases; migrate UI call sites incrementally. |
| 2 (dialogs) | `FilterDialog.py` | `filter_dialog.py` | Keep dialog aliases; migrate UI call sites incrementally. |
| 2 (dialogs) | `AboutWindow.py` | `about_window.py` | Keep dialog/window aliases; migrate UI call sites incrementally. |
| 2 (dialogs) | `ReleaseNotesDialog.py` | `release_notes_dialog.py` | Keep dialog aliases; migrate UI call sites incrementally. |
| 2 (dialogs) | `CSVSummaryDialog.py` | `csv_summary_dialog.py` | Keep dialog aliases; migrate UI call sites incrementally. |
| 3 (remaining utilities) | `DataGrouping.py` | `data_grouping.py` | Keep compatibility alias until all imports are updated. |
| 3 (remaining utilities) | `LicenseKeyManager.py` | `license_key_manager.py` | Keep compatibility alias until all imports are updated. |
| 3 (remaining utilities) | `Base64EncodedFiles.py` | `base64_encoded_files.py` | Keep compatibility alias until all imports are updated. |

## Compatibility shim pattern

During migration, snake_case modules can be lightweight wrappers that re-export legacy symbols:

```python
from modules.LegacyName import *  # noqa: F401,F403
```

Once all imports use snake_case names, we can invert this (legacy module imports from snake_case) and remove legacy modules in a later major cleanup.
