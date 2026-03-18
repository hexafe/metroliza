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

### License verification mode

- License verification is **disabled by default** at startup.
- Configure with `METROLIZA_LICENSE_VERIFICATION`:
  - truthy values (`1`, `true`, `yes`, `on`) enforce license validation.
  - falsy values (`0`, `false`, `no`, `off`) bypass license validation.
  - missing/invalid values fall back to the default (`disabled`).
- When license verification is enabled and validation fails, the app shows the hardware-id dialog and exits instead of launching the main window.
- `METROLIZA_STARTUP_SMOKE` remains available for non-interactive startup smoke checks.

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

## Parser plugin resolver controls

- Default selection accepts parser probes with confidence `>=1` and resolves ties by confidence, plugin priority, then plugin id.
- Optional strict selection: set `PARSER_STRICT_MATCHING=true` to require confidence `>=80`.
- Probe results are cached per plugin/path during process runtime to reduce repeated probe work in batch parses.

## Group Comparison export sheet

Excel exports now include a **Group Comparison** worksheet that consolidates:

- Location / central-tendency summaries and pairwise tables for mean/median-focused comparisons.
- Distribution shape profile by group, so you can quickly see how each group behaves beyond mean/median shifts.
- Distribution shape summaries and pairwise tables, including adjusted p-values and Wasserstein distance for side-by-side shape comparisons.
- Shape-aware interpretation notes explaining that significant shape differences can exist even when location comparisons are not significant.

Interpretation guidance:

- Use **adjusted p-values** (not raw p-values) for both pairwise location and pairwise distribution-shape significance decisions.
- Heatmap significance colors are thresholded at 0.05 and 0.01.
- Effect-size magnitudes are shown as absolute values for ranking practical impact.
- Effect sizes can indicate practical importance even when p-values are non-significant (e.g., small or imbalanced samples), so read both together.
- Distribution-shape sections also report Wasserstein distance as a descriptive separation measure; if the sheet shows a low/moderate/high severity label, treat it as domain-neutral guidance rather than a specification-based acceptance limit.

Effect size caveats:

- Two-group parametric paths report Cohen's *d*; non-parametric paths report Cliff's delta.
- Multi-group rows use an omnibus effect (eta-squared by default), so pairwise practical interpretation should consider group imbalance and distribution shape.

## Capability metrics legend (summary report)

Histogram statistics tables now use capability terminology aligned with common SPC notation:

- **Two-sided specs**: `Cp` and `Cpk` are shown.
- **One-sided upper specs**: `Cp` is shown as not defined (`Cp (not defined for one-sided) ⓘ`), and capability is shown as **`Cpu`**.
- **One-sided lower specs**: `Cp` is shown as not defined (`Cp (not defined for one-sided) ⓘ`), and capability is shown as **`Cpl`**.

Examples of metric availability by spec type:

- `Spec type: two-sided` → `Cp`, `Cpk`.
- `Spec type: one-sided upper` → `Cp (not defined for one-sided) ⓘ`, `Cpu`.
- `Spec type: one-sided lower` → `Cp (not defined for one-sided) ⓘ`, `Cpl`.

## Documentation map

- Release highlights: [`CHANGELOG.md`](CHANGELOG.md)
- Contribution guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Docs policy and lifecycle: [`docs/documentation_policy.md`](docs/documentation_policy.md)
- Release runbooks/checklists: [`docs/release_checks/`](docs/release_checks/)
- Google conversion smoke runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md)
- Historical plans and retired docs: [`docs/archive/`](docs/archive/)

## Release metadata

Current release highlight (`2026.03rc1(260317)`): Major analytics update: histogram/chart readability improvements plus new capability confidence and safeguards for low-sample interpretation.

Canonical release metadata is in `VersionDate.py` (`RELEASE_VERSION`, `VERSION_DATE`, `CURRENT_RELEASE_HIGHLIGHT`).

### Changelog highlights (release `2026.03rc1(260317)`)

- See [`CHANGELOG.md`](CHANGELOG.md) for end-user release notes and version history.

Sync docs from release metadata:

```bash
python scripts/sync_release_metadata.py
```

Validate metadata consistency:

```bash
python scripts/sync_release_metadata.py --check
```
