# Chart Parity Fixtures

This fixture set captures deterministic chart parity inputs and references for:

- `histogram`
- `distribution_scatter`
- `distribution_violin`
- `iqr`
- `trend`

Each fixture directory contains:

- `payload.json`: chart payload input.
- `planner_spec.json`: spec built from `modules/chart_render_spec.py`.
- `matplotlib_reference.png`: canonical matplotlib image artifact.
- `matplotlib_oracle_geometry.json`: finalized matplotlib geometry extraction (present for distribution/IQR/trend).

## Regeneration

Run from repository root:

```bash
python scripts/generate_chart_parity_fixtures.py --clean
```

The generator writes to `tests/fixtures/chart_parity/` and updates `manifest.json`.
