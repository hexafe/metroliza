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
while intentionally avoiding matplotlib on the export path.

## Runtime behavior

`modules/chart_renderer.py` controls backend selection using `METROLIZA_CHART_RENDERER_BACKEND`:

- `auto` (default): use native chart rendering when this extension is importable.
- `native`: require native chart rendering; when unavailable, Python warns and falls back to matplotlib.
- `matplotlib`: force matplotlib rendering for rollback and diagnostics.

## Build commands

```bash
# Install extension into the current interpreter (dev/editable workflow)
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 python -m maturin develop --manifest-path modules/native/chart_renderer/Cargo.toml

# Build wheel artifact(s)
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 python -m maturin build --manifest-path modules/native/chart_renderer/Cargo.toml --release
```
