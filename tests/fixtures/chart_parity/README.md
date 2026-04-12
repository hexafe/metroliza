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
- `matplotlib_oracle_geometry.json`: finalized matplotlib geometry extraction when a historical/reference oracle payload is still retained alongside the fixture.

Current runtime/parity split:

- Histogram, distribution, IQR, and trend build their resolved specs directly from the planner helpers and compare those live planner outputs against `planner_spec.json`.
- `matplotlib_oracle_geometry.json` is retained only as historical/reference parity evidence for fixture sets that still include it; runtime fast-path behavior now follows the planner-built resolved specs for all four chart types.

## Regeneration

Run from repository root:

```bash
python scripts/generate_chart_parity_fixtures.py --clean
```

The generator writes to `tests/fixtures/chart_parity/` and updates `manifest.json`.
