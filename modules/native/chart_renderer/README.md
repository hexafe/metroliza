# Chart renderer native module

This crate builds the Python extension module `_metroliza_chart_native`.

## Exported Python symbols

The extension exports:

- `_metroliza_chart_native.render_histogram_png(payload)`
- `_metroliza_chart_native.render_distribution_png(payload)`
- `_metroliza_chart_native.render_iqr_png(payload)`
- `_metroliza_chart_native.render_trend_png(payload)`

Histogram and distribution payloads are built from `modules/chart_renderer.py`.
IQR/trend payloads are assembled by the summary export path in `modules/export_data_thread.py`.

The current native backend uses a payload-driven Pillow compositor behind the
PyO3 extension surface. It is native in backend selection and packaging terms,
while the export runtime uses a split model:

- `runtime` decides whether a chart kind may use native rendering.
- `oracle` means the export path has already resolved matplotlib-derived
  geometry/spec payloads for parity-sensitive charts.
- `fast-path` means the compositor can draw from that resolved payload without
  re-running matplotlib layout.

Histogram currently reaches the native fast-path in the export runtime.
Distribution, IQR, and trend still use a matplotlib oracle pass before native
rendering, so their visual parity is strong but their end-to-end export path is
not yet fully matplotlib-free.

## Runtime behavior

`modules/chart_renderer.py` controls backend selection using `METROLIZA_CHART_RENDERER_BACKEND`
and `METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS`:

- `auto` (default): use native chart rendering only for chart kinds that are
  allowlisted in `METROLIZA_CHART_RENDERER_ROLLOUT_CHARTS` and available from
  this extension.
- `native`: prefer native chart rendering for allowlisted chart kinds; when a
  chart kind is unavailable or not allowlisted, Python warns and falls back to
  matplotlib.
- `matplotlib`: force matplotlib rendering for rollback and diagnostics.

This rollout policy applies to the runtime export path. The direct
`_metroliza_chart_native` compositor entrypoints are still designed to accept
legacy payloads and may synthesize missing geometry or metadata when invoked
outside the runtime gate.

## Build commands

```bash
# Install extension into the current interpreter (dev/editable workflow)
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 python -m maturin develop --manifest-path modules/native/chart_renderer/Cargo.toml

# Build wheel artifact(s)
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 python -m maturin build --manifest-path modules/native/chart_renderer/Cargo.toml --release
```
