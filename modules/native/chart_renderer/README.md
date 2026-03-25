# Chart renderer native histogram module

This crate builds the Python extension module `_metroliza_chart_native`.

## Exported Python symbols

The extension exports:

- `_metroliza_chart_native.render_histogram_png(payload)`

`payload` is the JSON-like mapping produced by `modules/chart_renderer.py::build_histogram_native_payload`.

## Runtime behavior

`modules/chart_renderer.py` controls backend selection using `METROLIZA_CHART_RENDERER_BACKEND`:

- `auto` (default): use native histogram rendering when this extension is importable.
- `native`: require native histogram rendering; when unavailable, Python warns and falls back to matplotlib.
- `matplotlib`: force matplotlib rendering for rollback and diagnostics.

## Build commands

```bash
# Install extension into the current interpreter (dev/editable workflow)
python -m maturin develop --manifest-path modules/native/chart_renderer/Cargo.toml

# Build wheel artifact(s)
python -m maturin build --manifest-path modules/native/chart_renderer/Cargo.toml --release
```
