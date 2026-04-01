# Native Plot Matplotlib Parity Audit And Execution Plan

## Goal

Make native-rendered export plots match the current matplotlib export output 1:1 wherever that is technically achievable, with matplotlib treated as the visual and layout oracle.

Scope:

- Histogram summary charts
- Distribution charts (`violin` and scatter fallback)
- IQR boxplots
- Trend plots

Out of scope for this pass:

- HTML dashboard styling beyond reusing the exported PNGs
- Interactive chart behavior
- A brand-new visual design system for native charts

## Audit Basis

This audit is based on:

- Python backend selection and payload contracts in `modules/chart_renderer.py`
- Native compositor implementation in `modules/native_chart_compositor.py`
- Matplotlib reference rendering flow in `modules/export_data_thread.py`
- Histogram layout planners in `modules/export_histogram_layout.py`
- Existing chart tests in `tests/test_chart_renderer.py`, `tests/test_export_histogram_layout.py`, and `tests/test_export_plot_helpers.py`
- Local side-by-side sample renders produced during this audit at `/tmp/metroliza_native_plot_audit/`

Important runtime note:

- In this environment `_metroliza_chart_native` is not installed, but the audit is still valid because the native extension is only a thin PyO3 wrapper around `modules.native_chart_compositor`.

## Current Architecture

The current system has two fundamentally different render paths:

1. Matplotlib path
- Python builds a real matplotlib figure.
- Layout is resolved with axes objects, figure legends, artist bounds, and final `subplots_adjust` / explicit axes rectangles.
- Histogram uses a dedicated right-side information column and figure-level title/annotation safety logic.

2. Native path
- Python builds a chart payload dictionary.
- The native extension calls `modules.native_chart_compositor`.
- The compositor redraws charts from scratch with Pillow using fixed pixel paddings and its own tick, legend, annotation, and table logic.

This is the root problem: the native path is not rendering the matplotlib result, it is rendering a second interpretation of the same data.

## Findings

### 1. The native renderer does not share final layout geometry with matplotlib

Severity: critical

Matplotlib resolves:

- final plot rectangle
- title band
- legend placement
- axis margins
- tick label rotation and thinning
- safe annotation bounds
- histogram right-column geometry

The native compositor recomputes all of those independently with fixed constants such as:

- histogram `plot_left = 86`, `plot_top = 72/104`, `table_width = width * 0.31`
- distribution/IQR/trend `plot_rect = (82, 88, width - 32, height - 92)`
- custom legend boxes drawn directly into top plot space

Result:

- different plot aspect ratio
- different whitespace distribution
- different title position
- different annotation headroom
- different legend collisions

### 2. Histogram parity is currently the farthest from matplotlib

Severity: critical

Observed and code-backed issues:

- Matplotlib histogram uses `compute_histogram_plot_with_right_info_layout(...)` and a dedicated right information column. Native histogram uses a hard-coded right table width.
- Matplotlib title is figure-level (`render_histogram_figure_title` / `render_histogram_title`). Native title is drawn directly at `(54, 22)` in image pixels.
- Matplotlib annotation placement uses `render_histogram_annotations(...)`, artist bounds, title collision avoidance, and candidate offsets. Native histogram uses fixed top rows (`base_y = 44 + row_index * 26`) with no title-aware collision solver.
- Matplotlib right-side table uses `render_panel_table_in_panel_axes(...)`, semantic row styling, explicit row heights, and section separators. Native histogram draws a simplified table with a different row-height model and no shared geometry contract.
- Matplotlib y-axis is locked from rendered bar heights via `lock_histogram_y_axis_to_bar_heights(...)`. Native histogram derives `max_count` separately and also expands it when overlays are present, which changes bar prominence and tick values.
- Matplotlib overlay note (`Dashed KDE: descriptive only`) is anchored in axes coordinates. Native histogram renders a custom boxed note in a different location and style.

Impact:

- histogram feels like a different chart family rather than a native copy of the matplotlib export
- annotations and side metadata do not read as part of the same composed figure

### 3. Distribution native rendering recomputes violin geometry and annotation layout

Severity: high

Matplotlib distribution charts use:

- `render_violin(...)`
- `annotate_violin_group_stats(...)`
- `add_violin_annotation_legend(...)`
- `move_legend_to_figure(...)`
- `finalize_extended_chart_layout(...)`

Native distribution charts:

- recompute violin density internally
- place legends inside a top inline badge row
- render annotation boxes with a different label grammar and placement model
- use fixed plot margins unrelated to the matplotlib figure adjustments

Impact:

- violin widths and shape feel different
- legend position differs from matplotlib
- annotation density and overlap behavior differ
- title and top-of-plot whitespace do not match

### 4. IQR native rendering does not follow matplotlib legend and layout behavior

Severity: high

Matplotlib IQR charts:

- use `render_iqr_boxplot(...)`
- add a compact legend with `add_iqr_boxplot_legend(...)`
- move the legend to figure space with `move_legend_to_figure(...)`
- finalize margins with `finalize_extended_chart_layout(...)`

Native IQR charts:

- draw a custom legend row inside the top canvas area
- use a fixed plot rectangle
- use its own stroke widths and spacing

Impact:

- the chart is readable, but still not visually aligned with the matplotlib export system
- the legend and title compete for top-row space differently than in matplotlib

### 5. Trend native rendering uses a simpler axis model than matplotlib

Severity: medium

Matplotlib trend charts:

- build a figure with axis-aware tick label placement
- use `apply_shared_x_axis_label_strategy(...)`
- use matplotlib marker sizing and final layout adjustment

Native trend charts:

- use fixed margins
- draw tick labels directly
- do not have a final artist-bounds layout pass

Impact:

- title vertical placement differs
- x tick angle and baseline spacing can differ
- marker and axis proportions feel off even when data is correct

### 6. The current payload contract is data-heavy but layout-light

Severity: critical

Current native payloads carry:

- values
- labels
- limits
- some visual metadata

They do not carry the final resolved render contract for:

- figure-space title placement
- plot rectangle
- legend rectangle
- final tick list after thinning and formatting
- final annotation offsets after collision resolution
- histogram right-panel geometry and row heights
- precomputed violin or boxplot drawing primitives

Without that, the native compositor is forced to re-implement matplotlib layout heuristics.

### 7. Existing tests are not strong enough to prevent parity regressions

Severity: high

Current tests mostly verify:

- backend selection
- payload validation
- PNG existence
- some coarse histogram metadata presence
- rectangle non-overlap for matplotlib-side planning helpers

They do not verify:

- chart-to-chart layout parity
- title position parity
- tick text parity
- legend placement parity
- annotation placement parity
- right-side histogram table parity
- perceptual or structural image similarity

## Decision

Do not keep growing `modules.native_chart_compositor.py` as an independent chart implementation.

Instead:

- treat matplotlib as the reference renderer
- extract a stable resolved render spec from the matplotlib planning path
- make the native renderer consume that resolved spec

In short: native should render a shared chart specification, not reinterpret raw chart payloads.

## Parity Specification

## 1. Shared Principles

The parity target is:

- same chart composition
- same data semantics
- same ordering and text for annotations and metadata
- same relative spacing and visual hierarchy
- same legend behavior
- same axis framing and tick labeling

Acceptable differences:

- minor font rasterization differences
- sub-pixel anti-aliasing differences
- tiny stroke-weight differences if needed by Pillow/native primitives

Target reading of "1:1":

- identical composition and metadata semantics
- identical resolved geometry within a tiny pixel tolerance
- native draws the matplotlib-decided layout, not a second approximation

Unacceptable differences:

- different title anchoring
- legend moving from figure space to plot space
- different annotation row assignment
- different histogram right-panel width or row ordering
- different tick text or thinning behavior
- different y-axis range logic
- recomputing a different violin/boxplot geometry from the same data

## 2. Shared Render Contract

Introduce a resolved chart render contract, for example `ResolvedChartSpec`, with these top-level sections:

- `canvas`
  - `width_px`
  - `height_px`
  - `dpi`
- `title`
  - `text`
  - `anchor`
  - `font`
  - `color`
- `plot_area`
  - normalized figure rectangle
- `axes`
  - `x_limits`
  - `y_limits`
  - `x_ticks`
  - `y_ticks`
  - `x_label`
  - `y_label`
  - grid visibility
  - visible spines
  - tick font/style
- `legend`
  - visibility
  - normalized figure rectangle or anchor
  - items with text and symbol style
- `annotations`
  - resolved text
  - anchor point
  - offset in points or final figure-space box rectangle
  - bbox style
  - arrow/leader style
  - z-order
- `primitives`
  - bars
  - lines
  - polygons
  - rectangles
  - markers
  - fills
- `side_panels`
  - optional panel rectangles
  - table title
  - rows
  - row height model
  - badge palette
  - separators

The native renderer should only draw from this resolved spec.

## 3. Histogram Specification

Histogram must match the current matplotlib export path built around:

- `render_histogram(...)`
- `compute_histogram_plot_with_right_info_layout(...)`
- `render_panel_table_in_panel_axes(...)`
- `style_histogram_stats_table(...)`
- `adjust_histogram_stats_table_geometry(...)`
- `render_histogram_annotations(...)`
- `render_histogram_figure_title(...)`

Required parity:

- same canvas size as current export
- same plot rectangle and right-column rectangle
- same title text, color, font size, and top-band anchor
- same bin count
- same x limits from `resolve_histogram_x_view(...)`
- same bar alpha, fill, edge color, and edge width
- same mean line style from `build_histogram_mean_line_style()`
- same spec limit line positions and clipping behavior
- same y-axis range logic as final matplotlib bars
- same annotation texts, order, row index, and final collision-resolved offsets
- same right-side table title, row order, row content, palette badges, and section separators
- same modeled overlay lines, tail shading, and KDE note placement

Implementation constraint:

- native histogram must stop computing its own table geometry and annotation layout from scratch
- Python must provide final layout rectangles and resolved annotation placements

## 4. Distribution Specification

Distribution must support both modes:

- violin
- scatter fallback

Required parity:

- same figure width recommendation as matplotlib path
- same tick thinning/rotation as the shared categorical axis strategy
- same tolerance band and spec line positions
- same title anchor and top whitespace
- same legend presence rules and legend placement
- same per-group annotation visibility rules
- same mean/min/max/sigma markers and label text

Implementation constraint:

- native renderer must not independently derive a different violin silhouette
- Python should provide resolved violin polygons or equivalent density samples already accepted by the matplotlib-side planning step

## 5. IQR Specification

Required parity:

- same boxplot statistics and positions
- same box, whisker, cap, median, and outlier styles
- same tolerance band and reference line behavior
- same legend presence and placement
- same title anchor and plot rectangle
- same categorical tick strategy

Implementation constraint:

- native renderer should consume precomputed boxplot statistics rather than recomputing layout-critical decisions late

## 6. Trend Specification

Required parity:

- same marker positions, size, and color
- same horizontal limit lines
- same x tick labels, thinning, and rotation
- same y-axis scaling
- same title anchor and whitespace

## 7. Metadata Specification

All metadata that is currently shown in matplotlib must remain available and visually intact in native output:

- histogram summary rows
- histogram distribution-fit rows
- histogram row badges and fit-quality emphasis
- histogram annotation rows
- modeled overlay notes
- distribution annotation legend items
- IQR legend items

No metadata may be silently dropped because the native compositor has no room for it. If the chart does not fit, layout must change or the backend must fall back to matplotlib.

## Acceptance Criteria

Each chart type must satisfy all of the following before native becomes the default parity path:

1. Structural parity
- canvas size matches matplotlib export
- plot rectangle delta <= 3 px on each edge
- title anchor delta <= 4 px
- legend anchor delta <= 4 px
- tick labels and tick count match exactly

2. Semantic parity
- same annotation texts and ordering
- same right-side histogram table row labels and values
- same visible overlays and reference lines
- same fallback mode decisions (`violin` vs scatter, native vs matplotlib)

3. Visual parity
- no overlaps between title, legend, annotations, and plot
- no clipped labels
- histogram table fully visible
- perceptual image diff stays below an agreed threshold for golden fixtures

4. Test parity
- automated golden-fixture tests exist for each chart type
- one failure in parity fixtures blocks native rollout for that chart type

## Current Status As Of 2026-04-01

Completed:

- histogram emits a resolved spec and the runtime native histogram path now requires that resolved spec rather than allowing heuristic workbook rendering through the export backend
- distribution captures finalized matplotlib geometry after `fig.canvas.draw()`, including plot area, axes, legend, reference lines/bands, scatter points, violin polygons, and annotation geometry
- IQR captures finalized matplotlib geometry, including boxplot statistics, legend placement, and reference geometry
- trend captures finalized matplotlib geometry, including final ticks, plot area, points, and horizontal limits
- export orchestration builds one matplotlib-oracle path for distribution, IQR, and trend before dispatching to backend rendering
- runtime native rendering is now gated per chart kind through `METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS`, so backend enablement is chart-by-chart instead of all-or-nothing
- histogram, distribution, IQR, and trend all fall back to matplotlib when finalized oracle/spec payload coverage is missing or incomplete
- checked-in parity fixtures now exist under `tests/fixtures/chart_parity/`, along with a deterministic regeneration script at `scripts/generate_chart_parity_fixtures.py`
- fixture-driven parity tests now gate native-vs-matplotlib image drift for histogram, distribution scatter, distribution violin, IQR, and trend
- histogram is the only summary-chart path that currently behaves like a true native fast-path in the export runtime; distribution, IQR, and trend still pay a matplotlib oracle pass before native rendering

Remaining non-blocking follow-up work:

- expand the fixture set with more pathological long-label / dense-annotation cases if future visual churn warrants it
- keep the direct compositor legacy fallback paths only for non-export callers; export/runtime rollout already enforces oracle-or-fallback behavior

## Active Workstreams

The original execution workstreams are complete enough for rollout:

1. Native oracle consumption
- completed in runtime/backend terms by requiring resolved oracle/spec payloads for native export rendering
- still relevant as a contract for any future fast-path work on trend or other charts: native rendering should remain a consumer of finalized geometry, not a second planner

2. Export oracle emission cleanup
- completed for the summary export path now that distribution/IQR/trend all attach finalized matplotlib geometry before render dispatch
- this is the current tradeoff point: parity is strong, but the export path still depends on matplotlib for oracle capture on those charts

3. Parity harness and rollout gate
- completed through checked-in parity fixtures, generator tooling, fixture-driven image tests, and per-chart rollout policy in `modules/chart_renderer.py`
- keep using the parity gate as the acceptance check for any future native fast-path work, especially trend

## Execution Plan

## Phase 0: Freeze The Oracle

1. Build representative golden fixtures from the current matplotlib path for:
- histogram with right-side table and fit overlays
- histogram with dense annotation collisions
- violin distribution with legend
- scatter fallback distribution
- IQR boxplot with legend
- trend plot with long labels

2. Save both:
- matplotlib PNG golden files
- resolved JSON metadata fixtures for text, ticks, limits, and annotations

3. Add a small fixture generator script so future layout changes are intentional.

## Phase 1: Introduce A Shared Render Spec

1. Add typed spec models for resolved chart rendering.
2. Refactor current matplotlib export code so each chart has:
- data preparation
- layout/spec planning
- renderer execution

3. Make matplotlib render from the same spec where practical, or at minimum emit the final resolved spec after planning and before `savefig`.

Definition of done:

- histogram, distribution, IQR, and trend all have a serializable resolved spec
- the spec contains final layout geometry, not just raw data

## Phase 2: Histogram First

1. Extract histogram layout output into the resolved spec:
- `plot_rect`
- `right_container_rect`
- title anchor
- annotation positions
- table row heights

2. Replace native histogram constants with spec-driven drawing.
3. Port histogram table rendering to use spec-provided row metrics and separator markers.
4. Port annotation rendering to use pre-resolved offsets instead of native row-only heuristics.
5. Add histogram parity tests against golden fixtures.

Definition of done:

- histogram native output matches matplotlib closely enough to pass structural and visual parity thresholds

## Phase 3: Distribution

1. Use finalized matplotlib artist geometry as the oracle, not planner-estimated geometry.
2. Precompute and serialize violin polygons from the matplotlib figure.
3. Move legend placement into spec instead of native inline badge logic.
4. Carry resolved annotation placements into native output.
5. Make native render directly from oracle polygons, scatter points, annotation geometry, and resolved title/legend layout whenever available.
6. Add violin and scatter parity fixtures.

Definition of done:

- native violin/scatter no longer invent their own layout behavior

## Phase 4: IQR

1. Extract boxplot stats and legend placement into the spec.
2. Drive native box, whisker, cap, and outlier drawing from the resolved spec.
3. Add IQR parity fixtures.

## Phase 5: Trend

1. Extract resolved tick list and final plot rectangle into the spec.
2. Match marker sizing and title placement.
3. Add trend parity fixtures.
4. If a future trend fast-path lands, remove the matplotlib oracle pass only after it reuses the same resolved geometry contract and passes the existing parity gate.

## Phase 6: Rollout Controls

1. Gate native enablement per chart type.
2. If a chart type lacks complete parity spec coverage, force matplotlib for that chart type.
3. Treat parity-fixture failures as rollout blockers for the affected chart type.
4. Keep `METROLIZA_CHART_RENDERER_BACKEND=matplotlib` as immediate rollback.
5. Treat extracted matplotlib geometry as the contractual payload for parity charts; if that payload is missing or incomplete, fall back to matplotlib rather than allowing heuristic native layout.

## Historical Execution Sequence

The implementation proceeded in this order:

1. Remove remaining native-side recomputation for distribution when oracle geometry is available.
2. Convert the parity harness into an explicit backend-enable gate.
3. Enable native backend chart-by-chart, not globally.
4. Keep matplotlib as the fallback for any chart type that fails parity thresholds.

## Current takeaway

The parity target is mostly achieved for the covered charts, but the speed target is still chart-dependent:

- histogram already benefits from a native fast-path in the export runtime
- distribution, IQR, and trend are parity-first and still pay matplotlib oracle extraction before native rendering
- the next meaningful fast-path candidate is trend, but only if it can reuse the existing resolved spec contract without regressing the fixture gate

## Historical Implementation Tasks

Concrete tasks that drove the rollout:

1. Create the parity fixture set and fixture generator.
2. Add `ResolvedChartSpec` models and serializers.
3. Refactor histogram planning to emit a spec.
4. Rework native histogram drawing to consume the spec.
5. Add histogram parity tests.
6. Refactor distribution planning to emit a spec.
7. Rework native distribution drawing to consume the spec.
8. Add distribution parity tests.
9. Refactor IQR planning to emit a spec.
10. Rework native IQR drawing to consume the spec.
11. Add IQR parity tests.
12. Refactor trend planning to emit a spec.
13. Rework native trend drawing to consume the spec.
14. Add trend parity tests.
15. Switch `auto` backend policy only after all chart types clear parity gates.

## Test Plan

Add tests in three layers:

1. Spec tests
- ensure resolved spec matches expected text, tick labels, limits, and rectangles

2. Renderer tests
- ensure native renderer consumes the spec without dropping primitives or metadata

3. Parity tests
- render matplotlib and native from the same fixture
- compare dimensions, extracted metadata, and perceptual image differences

Recommended fixture assertions:

- exact title text
- exact x/y tick text
- exact annotation text list
- exact histogram table row labels and values
- exact legend item labels
- plot and panel rectangle tolerance

## Risks

### Risk 1: Trying to keep chart-type-specific native heuristics

If native keeps recomputing layout independently, parity work will stay fragile and regress repeatedly.

Mitigation:

- move to a shared resolved spec

### Risk 2: Overfitting to one developer environment

Font rasterization can differ across platforms.

Mitigation:

- assert structural parity and metadata parity first
- use tolerant perceptual image thresholds second

### Risk 3: Large refactor without rollout control

Mitigation:

- gate by chart type
- keep matplotlib fallback live

## Recommended Working Order

If this work starts immediately, the safest order is:

1. Freeze golden matplotlib fixtures
2. Implement shared resolved spec
3. Fix histogram end to end
4. Fix distribution
5. Fix IQR
6. Fix trend
7. Enable native per chart type only after each parity gate passes

## Bottom Line

The current native plot renderer is not failing because of one bad spacing constant. It fails because it is an independent plotting system with only partial metadata parity.

The correct fix is to make native rendering consume the same resolved layout and visual contract that the matplotlib export path already uses.
