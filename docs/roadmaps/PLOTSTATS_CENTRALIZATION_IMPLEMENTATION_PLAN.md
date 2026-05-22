# hexafe-plotstats Centralization Implementation Plan

Date: 2026-05-21
Status: future implementation plan

## Goal

Centralize all reusable plotting behavior in `hexafe-plotstats` so Metroliza no
longer owns chart definitions, renderer-specific styling, Plotly trace logic, or
static image drawing rules.

Target architecture:

- `hexafe-plotstats` owns reusable chart definitions, templates, statistics
  overlays, Plotly specs, PNG rendering, resolved specs, and workbook chart data.
- Metroliza extracts domain data, passes basic settings, and embeds returned
  artifacts in dashboards, worksheets, or files.
- Metroliza keeps UI, export orchestration, workbook sheet placement, dashboard
  shell rendering, cancellation, logging, and release diagnostics.

## Current Gap

Metroliza still contains several custom plotting systems:

- HTML dashboard Plotly builders for histogram, violin/distribution, IQR, trend,
  grouped histograms, and group-analysis charts.
- Workbook/static image Matplotlib and seaborn chart generation.
- Metroliza-specific resolved chart specs and native compositor paths.
- XlsxWriter chart data and chart insertion helpers.
- Industrial analytics dashboard and workbook chart definitions.
- Normalization and post-processing around plotstats output, including legend
  names, reference line behavior, histogram y-axis scaling, overlay scaling, and
  dashboard theme handling.

`hexafe-plotstats` already has the right package boundary for histogram, violin,
IQR, and scatter payloads, with Matplotlib, Plotly, and optional Rust/native
renderers. The migration should expand that boundary into a complete reusable
artifact API instead of keeping Metroliza-specific chart logic in the consumer.

## Target Public API

Add a generic preset artifact API to `hexafe-plotstats`.

Primary request:

```python
ChartArtifactRequest(
    chart_kind="histogram" | "violin" | "iqr" | "scatter" | "trend" | "grouped_histogram" | "time_series",
    values=...,
    groups=...,
    x=...,
    y=...,
    labels=...,
    limits=SpecLimits(...),
    title="...",
    template="metroliza.dashboard",
    targets=("plotly", "png", "resolved_spec", "workbook_chart_data"),
    settings={...},
)
```

Primary result:

```python
ChartArtifact(
    plotly_spec=dict | None,
    png_bytes=bytes | None,
    resolved_spec=dict | None,
    workbook_chart_data=dict | None,
    stats_tables=list[dict],
    metadata=dict,
    diagnostics=list[str],
)
```

Required entry points:

- `build_chart_artifact(request)` for new reusable callers.
- `build_chart_artifact_from_mapping(mapping)` for simple dict-based callers.
- A temporary compatibility adapter for current Metroliza payloads until
  Metroliza has migrated to the generic request shape.

## Templates

Move the current Metroliza fine tuning into reusable plotstats templates:

- `metroliza.dashboard`
- `metroliza.workbook`
- `metroliza.group_analysis`
- `metroliza.industrial`

Templates must own:

- Color palettes, dark/light tokens, line widths, marker sizes, and opacity.
- Legend names and legend grouping.
- Reference-line behavior for LSL, USL, nominal, mean, min, quartiles, and max.
- Histogram frequency scaling and y-axis range rules.
- Selected model and KDE curve scaling.
- Mean precision: one decimal place more than source data, capped at 4 decimals.
- Plotly interaction defaults, including legend toggles that can hide all traces.
- Static image layout, table rows, and annotation placement.

## Migration Phases

### Phase 1 - Stabilize plotstats artifact API

Implement the generic `ChartArtifactRequest` and `ChartArtifact` contracts in
`hexafe-plotstats`.

Keep the existing Metroliza adapter working, but make it delegate to the generic
artifact builder internally. Do not remove the adapter yet.

Acceptance criteria:

- Histogram, violin, IQR, scatter/trend, grouped histogram, and time-series
  requests can produce Plotly specs.
- Histogram, violin, IQR, and scatter/trend requests can produce PNG artifacts.
- Result metadata identifies template, backend, chart kind, and target outputs.
- `hexafe-plotstats` tests pass without importing Metroliza.

### Phase 2 - Port dashboard Plotly behavior

Move Metroliza dashboard Plotly behavior into `hexafe-plotstats` templates.

Start with the recently tuned charts because they define the product contract:

- Distribution/violin.
- IQR box plots.
- Histograms.
- Trend/scatter.
- Group Analysis violin and grouped histogram.

Acceptance criteria:

- LSL, USL, nominal, and stats traces are real legend-controlled Plotly traces,
  not layout-only shapes when the legend needs to control them.
- Reference lines span the full visible plot extent.
- Disabling all legend items leaves the plot visually empty.
- Histogram y-axis range is based only on histogram bin heights, not reference
  line or overlay heights.
- Selected model and KDE curves match the static histogram scaling.
- Group stat legends use compact labels such as `(A) Min=6.469`.
- Group stat colors make the group clear, with stat-specific accents/dashes.

### Phase 3 - Port static and native/resolved rendering

Move Metroliza static PNG behavior and reusable resolved-spec logic into
`hexafe-plotstats`.

The resolved-spec boundary should remain the package-level contract. Native/Rust
and Matplotlib renderers should consume the same resolved chart specification.

Acceptance criteria:

- Metroliza no longer needs its own reusable chart compositor/spec logic for
  histogram, distribution, IQR, or trend.
- PNG artifacts generated by plotstats are visually equivalent to the current
  accepted Metroliza output within existing image-diff tolerances.
- Static histogram tables, fit overlays, capability rows, annotations, and
  reference lines survive the migration.

### Phase 4 - Port workbook chart data

Move reusable workbook chart definitions into plotstats as serializable data.

Metroliza should still use XlsxWriter to place charts on sheets, but the series,
chart kind, axis labels, styles, and reference-line data should come from
plotstats artifacts.

Acceptance criteria:

- Plotstats returns workbook chart data for measurement scatter/trend, grouped
  histograms, ranked effects, and effect-vs-adjusted-p charts where they are
  reusable outside Metroliza.
- Metroliza owns only sheet layout, anchor cells, and insertion mechanics.
- XlsxWriter does not become a required core dependency of plotstats unless a
  later implementation explicitly chooses that.

### Phase 5 - Shrink Metroliza to data adapters

Replace Metroliza plot-building code with plotstats artifact calls.

Metroliza should construct requests from export data and attach returned
artifacts to:

- Export HTML dashboard.
- Export workbook summary charts.
- Group Analysis worksheets and dashboard sections.
- Industrial analytics dashboards and workbooks.

Keep a feature flag during migration:

- Default path remains plotstats-first.
- A temporary fallback may call legacy Metroliza plotting during rollout.
- Remove fallback code only after parity tests and release checks are green.

Acceptance criteria:

- Metroliza no longer contains reusable Plotly trace builders.
- Metroliza no longer contains reusable Matplotlib chart drawing functions.
- Metroliza no longer post-processes plotstats output for core semantics such as
  legend names, reference line extents, y-axis scaling, or curve scaling.
- Metroliza tests prove artifact requests are passed to plotstats and returned
  artifacts are embedded correctly.

## Testing Plan

### hexafe-plotstats

- Unit tests for `ChartArtifactRequest` validation and artifact generation.
- Plotly spec golden tests for histogram, violin, IQR, scatter/trend, grouped
  histogram, group-analysis, and industrial time-series templates.
- Static PNG smoke tests for Matplotlib and optional Rust/native backends.
- Image parity tests for migrated Metroliza chart fixtures.
- Tests proving templates do not import Metroliza.
- Tests for histogram model/KDE scaling and y-axis range behavior.
- Tests for legend behavior, including the all-traces-hidden state.

### Metroliza

- Integration tests for export dashboard artifact embedding.
- Integration tests for workbook/static chart artifact embedding.
- Regression tests for histogram, violin, IQR, scatter, and Group Analysis
  dashboard behavior.
- Code-search hygiene tests preventing reintroduction of reusable Plotly or
  Matplotlib chart definitions in Metroliza.
- Existing release gates:
  - `python -m ruff check .`
  - `python -m compileall -q -x '^\\./\\.git/' .`
  - `QT_QPA_PLATFORM=offscreen python -m pytest -q`
  - `python scripts/sync_release_metadata.py --check`
  - `python scripts/check_release_hygiene.py`
  - `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects`

## Implementation Notes

- Do not move Qt, workbook file writing, dashboard HTML shell rendering, export
  threading, cancellation, or Google export behavior into plotstats.
- Keep plotstats library-first: no dependency on Metroliza, no import of
  Metroliza modules, and no assumption that the caller is a PyQt app.
- Prefer serializable requests and artifacts so other projects and notebooks can
  reuse the same plotting behavior.
- Keep Metroliza compatibility wrappers during rollout, but make them thin and
  removable.
- Update Metroliza's `requirements.txt` plotstats SHA only after the package
  changes are committed and CI is green in `hexafe-plotstats`.

