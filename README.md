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

## Configuration essentials

- Google Sheets export is optional. Most users can run local Excel exports only; use Google export only if you need cloud sharing/sync.
- Google export needs local OAuth setup (Google Cloud project + OAuth client) before first use.
- Keep Google OAuth secrets local only: `credentials.json` and generated `token.json` should stay on your machine and must never be committed.
- For complete setup, validation, and troubleshooting, use the dedicated runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md).

Dependency files:
- `requirements.txt` - runtime
- `requirements-dev.txt` - development/testing
- `requirements-build.txt` - packaging


## Core workflow

1. Parse metrology PDFs/ZIPs and CSV data.
2. Store normalized records in SQLite.
3. Apply grouping labels where needed (default POPULATION rows stay white; user-created groups are auto color-coded with persistent pastel backgrounds).
4. Export Excel reports with summaries and plots.
5. Optionally generate a Google Sheets version while always keeping a local `.xlsx` fallback.
   - OAuth uses the minimal Drive scope: `https://www.googleapis.com/auth/drive.file`.


## CMM parser backend policy

- Default (`METROLIZA_CMM_PARSER_BACKEND=auto`): native parser when extension is available.
- Automatic fallback to pure Python only when extension is missing.
- Controlled rollback: set `METROLIZA_CMM_PARSER_BACKEND=python`.
- Strict native mode: set `METROLIZA_CMM_PARSER_BACKEND=native` to fail fast if native extension is unavailable.

Parity between native and Python backends is enforced through fixture-based tests in `tests/test_cmm_parser_parity.py`.

## Group Comparison export sheet

Excel exports now include a **Group Comparison** worksheet that consolidates:

- Metadata and overall test summary counts.
- Recommended per-metric omnibus test selection (assumption-driven).
- Pairwise comparison table with multiple-comparison correction (default: **Holm**).
- Adjusted p-value significance heatmaps and absolute effect-size heatmaps.
- Deterministic text insights for central tendency, significant/non-significant pairs, and sample-size warnings.

Interpretation guidance:

- Use **adjusted p-values** (not raw p-values) for pairwise significance decisions.
- Heatmap significance colors are thresholded at 0.05 and 0.01.
- Effect-size magnitudes are shown as absolute values for ranking practical impact.
- Effect sizes can indicate practical importance even when p-values are non-significant (e.g., small or imbalanced samples), so read both together.

Effect size caveats:

- Two-group parametric paths report Cohen's *d*; non-parametric paths report Cliff's delta.
- Multi-group rows use an omnibus effect (eta-squared by default), so pairwise practical interpretation should consider group imbalance and distribution shape.

## Documentation map

- Release highlights: [`CHANGELOG.md`](CHANGELOG.md)
- Contribution guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Docs policy and lifecycle: [`docs/documentation_policy.md`](docs/documentation_policy.md)
- Release runbooks/checklists: [`docs/release_checks/`](docs/release_checks/)
- Google conversion smoke runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md)
- Historical plans and retired docs: [`docs/archive/`](docs/archive/)

## Release metadata

Current release highlight (`2026.03rc1(260307)`): UX improvements: faster group renaming, clearer extended-chart visuals, and cleaner workflow readability.

Canonical release metadata is in `VersionDate.py` (`RELEASE_VERSION`, `VERSION_DATE`, `CURRENT_RELEASE_HIGHLIGHT`).

### Changelog highlights (release `2026.03rc1(260307)`)

- See [`CHANGELOG.md`](CHANGELOG.md) for end-user release notes and version history.

Sync docs from release metadata:

```bash
python scripts/sync_release_metadata.py
```

Validate metadata consistency:

```bash
python scripts/sync_release_metadata.py --check
```
