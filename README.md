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
6. Optionally generate an HTML dashboard sidecar with offline Plotly interactions, an Auto/Light/Dark theme switch, and workbook-matching PNG snapshots.


## CMM parser backend policy

- Default (`METROLIZA_CMM_PARSER_BACKEND=auto`): native parser when extension is available.
- Automatic fallback to pure Python only when extension is missing.
- Controlled rollback: set `METROLIZA_CMM_PARSER_BACKEND=python`.
- Strict native mode: set `METROLIZA_CMM_PARSER_BACKEND=native` to fail fast if native extension is unavailable.

Parity between native and Python backends is enforced through fixture-based tests in `tests/test_cmm_parser_parity.py`.

## Chart renderer backend policy

- `METROLIZA_CHART_RENDERER_BACKEND` accepts `matplotlib` (default), `auto`, or `native`.
- Native chart rendering via `_metroliza_chart_native` is included when the native extension is built/installed in the packaging environment.
- `METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS` accepts a comma-separated allowlist such as `histogram,distribution,iqr,trend`; when unset, all supported chart kinds are enabled whenever native mode is opted in via `auto` or `native`.
- Matplotlib is the current default export path while native chart parity is still being tuned.
- In `auto`, the runtime export path re-enables native selection for enabled chart kinds whose native extension symbols are available.
- If `native` is forced while the native module is unavailable, Metroliza warns and falls back to matplotlib rendering.
- If `native` is forced for a chart kind that is not allowlisted for rollout, Metroliza warns and falls back to matplotlib rendering for that chart kind.
- Runtime export rendering is split into three layers:
  - `runtime` decides whether a chart kind may use the native backend.
  - `oracle` means the export path has already resolved matplotlib-derived geometry/spec data for parity-sensitive charts.
  - `fast-path` means the native compositor can render from that resolved payload without re-running matplotlib layout.
- Histogram, distribution, IQR, and trend use planner-driven native fast-path payloads in the export runtime only when native mode is opted in, the chart kind is allowlisted, and the native backend is available.
- The lower-level `_metroliza_chart_native` compositor entrypoints remain backward-compatible and can still synthesize fallback geometry/metadata for legacy payloads when called directly.
- For deterministic rollback behavior, either leave `METROLIZA_CHART_RENDERER_BACKEND` unset or set it explicitly to `matplotlib`.

## Additional native backend controls

- `METROLIZA_CMM_PERSIST_BACKEND`: controls CMM persistence backend (`auto`/`native`/`python`).
- `METROLIZA_COMPARISON_STATS_CI_BACKEND`: controls comparison bootstrap CI backend (`auto`/`native`/`python`).
- `METROLIZA_COMPARISON_STATS_BACKEND`: controls comparison pairwise backend (`auto`/`native`/`python`).
- `METROLIZA_DISTRIBUTION_FIT_KERNEL`: controls distribution-fit candidate kernel backend (`auto`/`native`/`python`).
- `METROLIZA_GROUP_STATS_BACKEND`: controls group-stats coercion backend (`auto`/`native`/`python`).
- See [`docs/native_build_distribution.md`](docs/native_build_distribution.md) for full backend semantics and packaging requirements.

### Local native chart extension build (optional)

```bash
python -m maturin develop --manifest-path modules/native/chart_renderer/Cargo.toml
# or build wheel artifacts
python -m maturin build --manifest-path modules/native/chart_renderer/Cargo.toml --release
```

## Parser plugin resolver controls

- End-user drop-in folder: Metroliza automatically discovers parser plugins placed in `~/.metroliza/parser_plugins/`.
- Default selection is strict and accepts parser probes only with confidence `>=80`; ties are resolved by confidence, plugin priority, then plugin id.
- To relax selection temporarily, set `PARSER_STRICT_MATCHING=false`.
- Probe results are cached per plugin/path during process runtime to reduce repeated probe work in batch parses.
- Advanced override: `PARSER_EXTERNAL_PLUGIN_PATHS` can point to extra plugin files or directories.
- Active parser plugin onboarding docs live under [`docs/parser_plugins/README.md`](docs/parser_plugins/README.md).

## Group Analysis

Excel exports now present grouped statistical results in a canonical **Group Analysis** worksheet. In **Standard** mode, the workbook also adds a separate **Group Analysis Plots** sheet.

For a plain-English guide to the exported Group Analysis worksheet, see [`docs/user_manual/group_analysis/user_manual.md`](docs/user_manual/group_analysis/user_manual.md). Printable companion: [`docs/user_manual/group_analysis/user_manual.pdf`](docs/user_manual/group_analysis/user_manual.pdf).

### What is on the sheet

The worksheet is designed to be read top-to-bottom on one main sheet so users can review conclusions first and only open extra visual detail when needed:

- **Title and context at the top** so users can confirm they are reading the grouped analysis output.
- A **compact summary** near the top that shows status, effective scope, metric count, and any short export warning.
- A **metric index with jump links** near the top so users can move directly to a metric block without leaving the single worksheet.
- Repeated **per-metric blocks** so each metric keeps its descriptive statistics, significance results, effect-size context, and nearby notes together.
- **Pairwise comparison tables** inside each metric block so users can compare one group against another without leaving the sheet.
- Short **interpretation and action notes** in plain language to explain what changed, what is statistically meaningful, and what to review next.
- A separate **Group Analysis Plots** sheet in **Standard** mode so the main results sheet stays cleaner while the visual detail remains one click away.
- A **light visual style**: no user-facing freeze panes, hidden gridlines, selective borders, and explicit widths/heights tuned for readability.

### Light vs Standard

Both export levels use the same core Group Analysis reading order, but they differ in how much supporting detail is shown:

- **Light** is the faster, more compact read. Start here when you want the worksheet title, the summary, the key per-metric comparison blocks, and concise interpretation notes without extra visual density.
- **Standard** keeps the same reading order and adds a separate plots sheet plus extra detail that helps users inspect how the distributions differ.

A simple rule for users: **read the top summary first, then move into the metric block for the measurement you care about, and only then use the pairwise table and plot for deeper inspection**.

Metroliza chooses the comparison method automatically based on the data, so most users should focus on the final label, adjusted p-value, effect size, and caution notes before worrying about the test name.

### How to read pairwise results

For each metric, the pairwise section answers a practical question: **which specific groups differ from which other groups?**

- Start with the **adjusted p-value**, because that is the version intended for the final yes/no significance decision after multiple comparisons.
- Then check the **effect size** to judge whether the observed difference looks small or large in practical terms.
- Read the text **status label** next to the metric or pair first:
  - **DIFFERENCE** = the corrected evidence supports a difference.
  - **NO DIFFERENCE** = the export did not find enough corrected evidence for a difference.
  - **APPROXIMATE** = the gap may matter, but evidence is not yet firm.
  - **USE CAUTION** = sample or comparability limits mean the result needs extra care.
- If the worksheet also shows a **distribution-shape comparison** or Wasserstein distance, treat that as a sign of how differently the full distributions behave, not just whether the averages move.
- If two groups do **not** show statistical significance, that does not automatically mean they are equivalent; it can also mean the sample is small, noisy, or imbalanced.

### What users should read first

For most users, the recommended order is:

1. The sheet title and top summary.
2. The metric block for the characteristic you are evaluating.
3. The pairwise table for the exact groups you need to compare.
4. The nearby interpretation note.
5. The plot, if present, to visually confirm whether the numeric result matches the distribution pattern.

### What cautions mean in user-facing language

Cautions are there to slow down overconfident conclusions, not to hide results.

- A caution about **small samples** means the result may swing more than usual if you collect a little more data.
- A caution about **imbalanced groups** means one group has much more data than another, so comparisons may be less stable.
- A caution about **non-significant p-values with visible effect size** means the worksheet sees a meaningful-looking difference, but the data is not strong enough yet for a confident significance claim.
- A caution about **distribution shape** means the groups may differ in spread, skew, or tails even if the centers look similar.
- Severity labels or descriptive distance cues should be read as **general interpretation help**, not as automatic pass/fail limits.

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

### User manuals

- User manual hub: [`docs/user_manual/README.md`](docs/user_manual/README.md)
- Main window guide: [`docs/user_manual/main_window.md`](docs/user_manual/main_window.md)
- Parsing guide: [`docs/user_manual/parsing.md`](docs/user_manual/parsing.md)
- Modify Database guide: [`docs/user_manual/modify_database.md`](docs/user_manual/modify_database.md)
- Export overview: [`docs/user_manual/export_overview.md`](docs/user_manual/export_overview.md)
- Group Analysis worksheet manual: [`docs/user_manual/group_analysis/user_manual.md`](docs/user_manual/group_analysis/user_manual.md)
- Group Analysis printable companion: [`docs/user_manual/group_analysis/user_manual.pdf`](docs/user_manual/group_analysis/user_manual.pdf)

### Other repository docs

- Release highlights: [`CHANGELOG.md`](CHANGELOG.md)
- Contribution guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Docs policy and lifecycle: [`docs/documentation_policy.md`](docs/documentation_policy.md)
- Release runbooks/checklists: [`docs/release_checks/`](docs/release_checks/)
- Google conversion smoke runbook: [`docs/google_conversion_smoke_runbook.md`](docs/google_conversion_smoke_runbook.md)
- Parser plugin generation and onboarding: [`docs/parser_plugins/README.md`](docs/parser_plugins/README.md)
- Historical plans and retired docs: [`docs/archive/`](docs/archive/)

## Release metadata

Current release highlight (`2026.04rc5(260418)`): HTML dashboards now match workbook histogram bin ranges, keep scatter plots as points, and add metric return controls.

Canonical release metadata is in `VersionDate.py` (`RELEASE_VERSION`, `VERSION_DATE`, `CURRENT_RELEASE_HIGHLIGHT`).

### Changelog highlights (release `2026.04rc5(260418)`)

- See [`CHANGELOG.md`](CHANGELOG.md) for end-user release notes and version history.

Sync docs from release metadata:

```bash
python scripts/sync_release_metadata.py
```

Validate metadata consistency:

```bash
python scripts/sync_release_metadata.py --check
```
