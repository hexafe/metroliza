# Group Analysis standard-plot interface decision

## Goal
Define the minimal interface needed to move from placeholder **Standard plot slots** to real plot insertion, using existing Group Analysis payload surfaces when possible.

## Findings from current code

### 1) Service payload already carries per-metric eligibility contract
`build_group_analysis_payload()` sets `metric_rows[*].plot_eligibility` with:
- `violin.eligible` (bool)
- `violin.skip_reason` (string)
- `histogram.eligible` (bool)
- `histogram.skip_reason` (string)

The helper `_build_metric_plot_eligibility()` computes these from analysis level, comparability policy inclusion, number of groups, and sample-count thresholds.

### 2) Writer already has a stable slot surface
`_write_metric_section()` in `group_analysis_writer.py` writes the **Standard plot slots** table from:
- `metric_row.plot_eligibility`
- optional `plot_assets['metrics'][metric]['violin'|'histogram']`

When `plot_assets` is absent, writer falls back to explicit reserved text.

### 3) Export flow currently injects placeholders, not rendered chart assets
`ExportDataThread._write_group_analysis_outputs()`:
- builds payload via `build_group_analysis_payload(...)`
- constructs `plot_assets` as a per-metric placeholder dictionary
- passes payload + plot_assets to `write_group_analysis_sheet(...)`

No per-metric Group Analysis chart bytes/paths are produced yet. Existing plotting pipelines in `ExportDataThread` (summary sheet violin/histogram/trend/IQR payload builders and renderers) are available as reusable data/render sources but are not wired to Group Analysis sheet insertion today.

## Interface decision (minimal)

## ✅ Reuse current payload only
Do **not** add a payload extension at this stage.

### Why
- Current payload already provides all gating logic needed to decide whether each Standard slot should be rendered (`plot_eligibility`).
- Writer interface already supports external chart asset injection via `plot_assets` without payload-schema changes.
- Export thread is the correct orchestration layer to map each metric to chart assets; this can be added incrementally by replacing placeholder strings with generated image references.
- Avoids payload bloat (for example, embedding raw grouped arrays under every metric row).

### Backward compatibility
- No schema change required.
- Existing consumers of `metric_rows[*]` and diagnostics remain untouched.

## Follow-up (implementation hint)
When implementing real chart insertion, keep payload unchanged and only evolve `plot_assets` producer in `ExportDataThread`:
- key by metric identity exactly as written in payload
- provide `plot_assets['metrics'][metric]['violin'|'histogram']` entries as rendered image handles/anchors instead of placeholder text.
