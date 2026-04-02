# Chart Parity Fixtures

This fixture set captures deterministic parity inputs and references for:

- `histogram`
- `distribution_scatter`
- `distribution_violin`
- `iqr`
- `trend`

Each fixture directory contains:

- `payload.json`: chart payload input.
- `planner_spec.json`: checked-in resolved spec built from the live planner in `modules/chart_render_spec.py`.
- `matplotlib_reference.png`: canonical matplotlib image artifact.
- `matplotlib_oracle_geometry.json`: finalized matplotlib geometry extraction when that oracle payload is still retained for runtime/reference use.

Current runtime/parity split:

- Histogram, distribution, and IQR build their resolved specs directly from the planner helpers and compare those live planner outputs against `planner_spec.json`.
- Trend still retains a checked-in matplotlib-oracle geometry payload for runtime parity while also keeping `planner_spec.json` under fixture control.

## Regeneration

Run from repository root:

```bash
python scripts/generate_chart_parity_fixtures.py --clean
```

The generator writes to `tests/fixtures/chart_parity/` and updates `manifest.json`.
