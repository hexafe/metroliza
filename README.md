# Metroliza

[![CI](https://github.com/hexafe/metroliza/actions/workflows/ci.yml/badge.svg)](https://github.com/hexafe/metroliza/actions/workflows/ci.yml)

Metroliza is a Python desktop app for industrial metrology workflows: parsing measurement reports, organizing data in SQLite, and exporting analysis-ready Excel summaries.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python metroliza.py
```

Dependency files:
- `requirements.txt` — runtime
- `requirements-dev.txt` — development/testing
- `requirements-build.txt` — packaging

## Core workflow

1. Parse metrology PDFs/ZIPs and CSV data.
2. Store normalized records in SQLite.
3. Apply grouping labels where needed.
4. Export Excel reports with summaries and plots.
5. Optionally generate a Google Sheets version while always keeping a local `.xlsx` fallback.

## Documentation map

- Release highlights: [`CHANGELOG.md`](CHANGELOG.md)
- Contribution guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Docs policy and lifecycle: [`docs/documentation_policy.md`](docs/documentation_policy.md)
- Release runbooks/checklists: [`docs/release_checks/`](docs/release_checks/)
- Google conversion smoke runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md)
- Historical plans and retired docs: [`docs/archive/`](docs/archive/)

## Release metadata

Current release highlight (`2026.02`, build `260228`): Google Sheets export messaging is clearer, `.xlsx` fallback is explicit, and chart-heavy exports remain faster for daily use.

Canonical release metadata is in `VersionDate.py` (`RELEASE_VERSION`, `VERSION_DATE`, `CURRENT_RELEASE_HIGHLIGHT`).

### Changelog highlights (release `2026.02`, build `260228`)

- See [`CHANGELOG.md`](CHANGELOG.md) for end-user release notes and version history.

Sync docs from release metadata:

```bash
python scripts/sync_release_metadata.py
```

Validate metadata consistency:

```bash
python scripts/sync_release_metadata.py --check
```
