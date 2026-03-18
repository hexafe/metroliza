# Python module naming migration status (`modules/`)

This project has completed the migration to `snake_case.py` module names for first-party code.

## Current state

- **Canonical implementation location:** `snake_case.py` modules only.
- **Import style for app/test/script code:** `from modules.some_module import ...` or `import modules.some_module`.
- **CamelCase module policy:** first-party `modules/CamelCaseName.py` files are no longer part of the supported layout.
- **First-party import policy:** `modules.CamelCaseName` imports are prohibited everywhere in `modules/`, `scripts/`, and `tests/`.

## Parser migration status

The parser slice now uses only the canonical snake_case modules:

| Legacy module removed | Canonical module | Status |
| --- | --- | --- |
| `CMMReportParser.py` | `cmm_report_parser.py` | ✅ removed |
| `ParseReportsThread.py` | `parse_reports_thread.py` | ✅ removed |

## Validation status

- Parser-related tests import `modules.cmm_report_parser` and `modules.parse_reports_thread` directly.
- `tests/test_no_camelcase_module_imports.py` scans first-party Python files recursively and fails on any `modules.CamelCaseName` import.
- Naming policy tests also fail if any `modules/*.py` filename contains CamelCase characters.

## Migration outcome

The module naming migration is considered complete for the parser-related modules covered by this cleanup.
Any future modules under `modules/` must be added as snake_case filenames and imported via their snake_case paths from the start.
