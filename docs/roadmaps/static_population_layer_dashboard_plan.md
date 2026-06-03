# Static POPULATION Layer Dashboard Optimization Plan

Status: Active implementation plan
Date: 2026-06-01
Scope: CSV Summary dashboard first, shared dashboard renderer support for Export parity where the same chart payloads apply.

## Summary

Large CSV Summary datasets can currently exceed the practical Plotly marker limit for a
single saved HTML dashboard. The recent dashboard work made the 50,000-row interactive
sample more explicit and added metadata that identifies when a large `POPULATION`
marker layer could be optimized. It did not yet add a visible setting or an
option-driven static `POPULATION` render path.

This feature finishes that work. Users should be able to choose whether the large
`POPULATION` context layer stays interactive, is rendered as a static image, or is
handled automatically by Metroliza. Custom comparison groups remain interactive where
possible, and all statistics continue to use the full selected dataset.

## User Problem

When users generate a dashboard from hundreds of thousands of rows, the dashboard still
needs to answer the same quality questions:

- What is the full-process context?
- Which selected groups differ from the process background?
- Are the key limits, statistics, and summaries based on all rows?
- Can the file open quickly enough to be useful?

Pure Plotly markers are not the right representation for every row when the background
cohort is very large. The user needs a clear choice before generation, not a silent
failure or a dashboard where every interactive chart is dropped.

## Product Behavior

Add a second generation-time control in the CSV Summary `Dashboard interactivity`
dialog:

| Setting | Values | Default |
|---|---|---|
| `Mode` | `Auto`, `Interactive random sample`, `Snapshots only`, `All rows` | `Auto` |
| `POPULATION layer` | `Auto`, `Interactive`, `Static image` | `Auto` |

Behavior by `POPULATION layer` value:

| Value | Behavior |
|---|---|
| `Auto` | Use static image layers when the normalized `POPULATION` point count reaches the dashboard point threshold and the chart type supports static layers. Otherwise keep normal interactive traces. |
| `Interactive` | Keep `POPULATION` as Plotly traces, subject to the selected dashboard mode and global budget limits. This preserves hover/selection at the cost of larger dashboards. |
| `Static image` | Render supported `POPULATION` marker layers as static images even when below the automatic threshold. Keep non-POPULATION groups interactive. |

The dashboard should include concise copy in the overview/key takeaway area:

- Static `POPULATION` layers preserve the visible process context.
- Hover and selection are unavailable for that background layer.
- Group traces, limits, statistics, tables, and insights still use the full selected data unless the dashboard explicitly says otherwise.

The setting belongs in dashboard generation settings, not the saved HTML visual-theme
panel, because it changes exported chart payloads and file size. The in-dashboard
visual settings may still control colors and opacity for the static layer through the
proxy trace where practical.

## Contract Changes

Extend `DashboardInteractivityOptions` in `src/metroliza/shared/contracts.py`:

```python
@dataclass(frozen=True)
class DashboardInteractivityOptions:
    mode: str = "auto"
    sample_size: int = 50_000
    population_layer_mode: str = "auto"
```

Accepted `population_layer_mode` values:

- `auto`
- `interactive`
- `static`

Normalization rules:

- Missing values normalize to `auto` for backwards compatibility.
- Unknown values normalize to `auto`.
- Dict aliases should accept `population_layer_mode` and `populationLayerMode`.
- Existing serialized requests without the new field remain valid.

Update every request summary that displays dashboard interactivity so users can see the
chosen strategy before and after generation.

## Rendering Design

Use the existing raw-image-layer mechanics where possible:

- `layout.images` holds the rasterized `POPULATION` layer.
- A lightweight proxy trace owns the legend row and visibility toggle.
- The Plotly runtime preserves image visibility across visual setting updates.
- Proxy traces are excluded from normal series visual-control lists unless the control is intentionally mapped to the static layer.

Extend the renderer with a POPULATION-specific decision step:

1. Normalize group labels with the same logic used for `population_baseline` visual styling.
2. Detect exactly one `POPULATION` cohort for a chart. If detection is ambiguous, keep the chart interactive and add no static conversion.
3. Decide whether to convert:
   - `population_layer_mode == "static"` converts supported charts.
   - `population_layer_mode == "auto"` converts when source points reach `DASHBOARD_RAW_POINT_LIMIT`.
   - `population_layer_mode == "interactive"` does not convert.
4. Rasterize only the `POPULATION` marker/background layer.
5. Remove the heavy Plotly marker trace for that layer.
6. Add a proxy trace with stable metadata such as `metroliza_static_population_layer_index`.
7. Keep custom groups, selected cohorts, limit lines, statistics, and aggregate traces interactive.

The first supported chart family should be point-based time-series/scatter-style charts
where axis mapping is direct and the static image can be anchored to data coordinates.
Distribution, histogram, violin, and box-style charts should only be converted after a
chart-specific renderer proves that the static image preserves the same interpretation.

Unsupported chart types must not silently pretend to be optimized. They should keep the
interactive or sampled behavior and may add a short note:

> Static POPULATION image layers are not available for this chart type yet.

## File Size And Performance Strategy

Static `POPULATION` layers are one optimization among several:

| Strategy | Best Use | Tradeoff |
|---|---|---|
| Reproducible random sample | Fast interactive detail for broad inspection | Individual unsampled points are not hoverable. |
| Static `POPULATION` image layer | Dense process background behind smaller interactive groups | Background layer has no hover/selection. |
| Aggregation or binning | Trends and distributions at very large scale | Shows shape/counts rather than individual points. |
| Full Plotly rows | Small or explicitly requested datasets | Large files can be slow or fail browser rendering. |
| Snapshot-only dashboard | Lowest browser load when interactivity is unnecessary | No Plotly hover, zoom, or legend interaction. |

The `Auto` path should prefer the least destructive optimization:

1. Keep interactive charts when under budget.
2. Static-render only oversized `POPULATION` background layers when custom groups are
   still useful interactively.
3. Fall back to reproducible random sampling or chart snapshots only when the full
   dashboard payload remains over budget.

## UI Work

Update `src/metroliza/ui/industrial_analytics_dialog.py`:

- Add a `POPULATION layer` combo under the existing dashboard interactivity mode.
- Keep labels short:
  - `Auto`
  - `Interactive`
  - `Static image`
- Add one concise chip:
  - `Static POPULATION layers keep the background visible without adding every background point to Plotly.`
- Include the setting in `dashboard_interactivity_options_summary`.
- Preserve accessibility names for the new combo.
- Keep the setting visible even for smaller inputs so users can intentionally choose
  static rendering before loading a very large file.

## Renderer Work

Update `src/metroliza/industrial/industrial_analytics_dashboard.py`:

- Normalize and carry `population_layer_mode` through `_normalize_dashboard_interactivity_options`.
- Add the selected mode to `summary["dashboard_interactivity"]`.
- Replace the current availability-only `STATIC_POPULATION_LAYER_OPTIMIZATION` metadata
  with option-aware conversion state:
  - available
  - selected mode
  - applied or skipped
  - source point count
  - rendered point count or raster dimensions
  - skipped reason, when applicable
- Add a helper that converts supported `POPULATION` traces into static image layers.
- Use stable metadata for proxy traces and images so legend toggles and visual updates
  survive `Plotly.react`.
- Keep the existing raw-layer path compatible for high-density time-series charts.

Update `src/metroliza/charts/dashboard_html_controls.py`:

- Generalize raw-layer visibility preservation so it recognizes both existing
  `metroliza_raw_layer_index` and new `metroliza_static_population_layer_index`.
- Exclude static-layer proxy traces from series controls unless the visual target is
  specifically the population baseline.
- Ensure theme changes do not make the static image visible after the user hides it.

Update shared dashboard shell/copy only where needed:

- Overview cards should say when static `POPULATION` layers were applied.
- Key takeaways should explain the interactivity tradeoff in one short sentence.
- No diagnostic/debug comments should be exposed to end users.

## Export Dashboard Parity

Do not add a hidden Export setting as part of the first slice unless the Export flow
already exposes the same generation-time dashboard interactivity contract. Instead:

- Keep helper functions shared and reusable.
- Audit Export chart payloads for `POPULATION` marker layers.
- If the Export dashboard uses compatible point-layer payloads, wire the same renderer
  behavior through a default `auto` mode and document the behavior in release notes.
- If Export needs a separate user setting, plan it as a follow-up with matching UI copy
  and tests.

## Parallel Workstreams

| Workstream | Scope | Output |
|---|---|---|
| Contract and UI | `DashboardInteractivityOptions`, dialog controls, summaries, request validation | New visible setting with backwards-compatible defaults. |
| Renderer | POPULATION detection, static conversion, metadata, budget interaction | Static layer applied only when requested or safe in `Auto`. |
| Runtime controls | Legend/image visibility, visual-theme updates, proxy trace handling | Static layers behave predictably in saved HTML. |
| Dashboard copy and UX | Overview cards, key takeaways, clear user-facing descriptions | Non-technical users understand the tradeoff. |
| Tests and release gate | Contract, UI, renderer, HTML runtime, docs, full local gate | Green local QA and CI-ready changes. |

## Test Plan

Add or update focused tests:

- `tests/test_contracts.py`
  - default `population_layer_mode` is `auto`
  - dict aliases normalize correctly
  - unknown values normalize to `auto`
- `tests/test_industrial_analytics_workers.py`
  - request objects carry the new field from UI to workflow
- `tests/test_tabular_analytics_grouping_dialog.py` or dialog-specific tests
  - the new combo is visible and produces `DashboardInteractivityOptions`
- `tests/test_industrial_analytics_dashboard.py` or existing dashboard tests
  - large `POPULATION` point layer converts in `static` mode
  - `interactive` mode keeps Plotly traces
  - `auto` applies only above threshold
  - unsupported chart types keep truthful notes
- `tests/test_dashboard_html_controls.py`
  - static POPULATION proxy traces preserve legend visibility across `Plotly.react`
  - static proxy traces do not pollute normal series style controls
- `tests/test_industrial_analytics_workflow.py`
  - dashboard summary reports the selected population-layer mode
  - stats and row summaries still use all rows
- `tests/test_docs_markdown_links.py`
  - roadmap/index links stay valid

Manual QA with a synthetic 350,000-row CSV:

- Open the dashboard interactivity dialog and confirm the `POPULATION layer` setting is visible.
- Generate with `Auto`; confirm oversized `POPULATION` context renders as a static layer where supported.
- Generate with `Interactive`; confirm no static conversion is applied unless another budget rule forces snapshots.
- Generate with `Static image`; confirm supported `POPULATION` layers convert even below the automatic threshold.
- Toggle legend visibility, theme, lightbox, and visual controls.
- Confirm key takeaways and overview cards explain the active strategy.

## Acceptance Criteria

- Users can select `Auto`, `Interactive`, or `Static image` for the `POPULATION`
  layer before dashboard generation.
- Large `POPULATION` background layers can be statically rendered while custom groups
  remain interactive.
- The saved dashboard clearly states when a static `POPULATION` layer is used and what
  interaction is unavailable.
- Full-scope statistics, metric summaries, and group comparison remain based on all
  selected rows unless another visible option explicitly says otherwise.
- Unsupported chart types fall back honestly and do not claim static optimization.
- Existing dashboards and request objects without the new field still load/generate.
- Local validation passes:

```bash
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
```

## Release Notes And Docs

When implemented, update:

- `docs/user_manual/csv_summary.md` with the new setting and tradeoff.
- `README.md` or `CHANGELOG.md` if the release branch requires visible feature notes.
- `docs/release_checks/release_status.md` only when this becomes release evidence, not
  while it is still an implementation plan.
