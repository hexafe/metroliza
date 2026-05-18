# RC2 Dashboard, Grouping, and Oznak Release Check - 2026-05-18

Scope:

- Plotly dashboard semantics for histogram percent axes, numeric bins, reference legend labels, white annotation boxes, high-cardinality x labels, and raw/aggregate axis alignment.
- CSV Summary dashboard fast/full detail mode.
- CSV Summary grouping-scope numeric filters and page navigation.
- Oznak access-only check without selecting a Metroliza database.
- Runtime dependency hygiene for the pinned `hexafe-plotstats` update.

Validation:

- `python -m ruff check .` - passed.
- `python -m compileall -q -x '^\./\.git/' .` - passed.
- `QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/matplotlib-cache python -m pytest -q` - passed: 1496 passed, 140 skipped, 6 warnings, 60 subtests passed.
- `python scripts/sync_release_metadata.py --check` - passed.
- `python scripts/check_release_hygiene.py` - passed.
- `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` - passed after rerun with network/tooling access for the pip-audit temporary environment. Remaining Bandit messages are report-only baseline warnings.
- `python -m pytest -q tests/test_requirements_hygiene.py` - passed.

Dependency note:

- `requirements.txt`, `.github/workflows/ci.yml`, and `tests/test_requirements_hygiene.py` already point to `hexafe-plotstats` commit `2c8c9718320ad743f3779900435ab032d616f240`, which matches `/home/hexaf/Projects/hexafe-plotstats` `main` at validation time.

Not covered in this Linux validation slice:

- Windows executable launch smoke.
- Google conversion smoke.
- Clean-machine install smoke.
