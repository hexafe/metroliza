# Metroliza Directory Reorganization Record

This record documents the completed package-layout migration. Metroliza now uses
`src/metroliza/` as the canonical source tree while retaining `modules.*`
compatibility shims for legacy imports and packaging compatibility.

## Canonical Layout

```text
src/metroliza/
  app/
  shared/
  ui/
  reports/
  parsing/
  exporting/
  charts/
  analytics/
  industrial/
  tabular/
  integrations/
  native/
  native_bridges/
  resources/
  workers/
```

Native Rust crates live under `src/metroliza/native/`. Python native bridge
modules live under `src/metroliza/native_bridges/`. Bundled runtime resources
live under `src/metroliza/resources/`, including dashboard assets and OCR model
assets.

## Compatibility Policy

The old flat `modules/` namespace is retained as explicit alias shims. Each shim
imports the canonical module and binds the legacy module name to the same module
object through `modules.compat.alias_module`.

New implementation code must import canonical package paths, for example:

```python
from metroliza.shared.contracts import ExportRequest
from metroliza.reports.db import run_transaction_with_retry
from metroliza.exporting.export_query_service import execute_export_query
```

Legacy imports remain valid for external callers, older scripts, and packaging
hidden-import compatibility:

```python
from modules.contracts import ExportRequest
from modules.db import run_transaction_with_retry
```

## Guardrails

- `tests/test_directory_reorganization_architecture.py` verifies the canonical
  package layout.
- Legacy `modules/**/*.py` files must remain alias shims.
- Selected legacy imports must resolve to the exact same module objects as their
  canonical `metroliza.*` modules.
- Implementation code under `src/metroliza/`, `scripts/`, and `packaging/` must
  not introduce new `modules.*` imports. Packaging hidden-import strings and
  explicit compatibility-shim verification are allowed.
- `pyproject.toml` sets `pythonpath = ["src", "."]` for pytest discovery.

## Packaging Notes

PyInstaller and Nuitka include `src` on their import paths and collect the
canonical `metroliza` package. Freezing uses
`packaging/metroliza_package_entry.py` instead of the root `metroliza.py`
launcher so the entry script does not shadow the package during hidden-import
analysis. The packagers also retain explicit legacy hidden imports for selected
`modules.*` shims so older dynamic import paths remain packaged.

Relevant resource paths:

```text
src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js
src/metroliza/resources/ocr_models/rapidocr/
```

Relevant native crate paths:

```text
src/metroliza/native/cmm_parser/Cargo.toml
src/metroliza/native/group_stats_coercion/Cargo.toml
src/metroliza/native/comparison_stats_bootstrap/Cargo.toml
src/metroliza/native/distribution_fit_ad/Cargo.toml
src/metroliza/native/chart_renderer/Cargo.toml
```

## Validation Expectations

Baseline validation for package-layout changes:

```bash
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
PYTHONPATH=src:. python -m ruff check .
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q
```

Packaging-sensitive changes should additionally run the relevant packaging smoke
checks, including:

```bash
PYTHONPATH=src:. python scripts/validate_packaged_pdf_parser.py --require-header-ocr
pyinstaller packaging/metroliza_onefile.spec
pyinstaller packaging/metroliza_onedir.spec
```

Windows release validation remains mandatory before promotion:

```powershell
.\build_windows_exe.ps1 -Mode both
.\scripts\measure_windows_startup.ps1 -ArtifactPath <onefile.exe>,<onedir\metroliza.exe>
```

## Remaining Cleanup

Compatibility shims are intentionally retained. Remove them only in a dedicated
future cleanup after external compatibility, packaging hidden imports, release
notes, and downstream scripts are explicitly approved for the break.
