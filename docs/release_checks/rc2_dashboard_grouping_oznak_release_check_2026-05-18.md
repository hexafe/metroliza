# RC2 Dashboard, Grouping, and Oznak Release Check - 2026-05-18

Scope:

- Plotly dashboard semantics for histogram percent axes, numeric bins, reference legend labels, white annotation boxes, high-cardinality x labels, and raw/aggregate axis alignment.
- CSV Summary dashboard fast/full detail mode.
- CSV Summary grouping-scope numeric filters and page navigation.
- Shared Export and CSV Summary grouping filter syntax in the existing search/filter fields,
  including nested boolean expressions, aliases, text wildcards, and SQLite-backed assignment.
- Oznak access-only check and live production export without selecting a Metroliza database.
- Runtime dependency hygiene for the pinned `hexafe-plotstats` update.
- Large-data performance pass for 1M x 20 style CSV Summary workloads:
  SQLite-backed grouping search/count/row-id paths, cheaper assign-all enablement,
  reduced assignment-frame string materialization, cached group counts during refresh,
  single-column grouped key filters using chunked `IN`, one-pass metric coercion for
  production groupstats inputs, and sampled Plotly distribution/histogram payloads with
  full-data statistics preserved.

Validation:

- `python -m ruff check .` - passed.
- `python -m compileall -q -x '^\./\.git/' .` - passed.
- `QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/metroliza-mplconfig python -m pytest -q` - passed: 1530 passed, 143 skipped, 6 warnings, 60 subtests passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_grouping_filter_core.py tests/test_data_grouping_filter_query.py tests/test_tabular_analytics_grouping_dialog.py tests/test_tabular_analytics_service.py -q` - passed: 91 passed, 31 skipped.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_industrial_analytics_workflow.py tests/test_industrial_analytics_dialog.py tests/test_data_grouping_filter_query.py tests/test_tabular_analytics_service.py -q` - passed: 119 passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_tabular_analytics_service.py tests/test_tabular_analytics_grouping_dialog.py tests/test_industrial_analytics_service.py tests/test_industrial_analytics_dashboard.py -q` - passed: 101 passed.
- `python scripts/sync_release_metadata.py --check` - passed.
- `python scripts/check_release_hygiene.py` - passed.
- `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` - passed after rerun with network/tooling access for the pip-audit temporary environment. `pip-audit` reported no known vulnerabilities; remaining Bandit messages are report-only baseline warnings.
- `python -m pytest -q tests/test_requirements_hygiene.py` - passed.

Dependency note:

- `requirements.txt`, `.github/workflows/ci.yml`, and `tests/test_requirements_hygiene.py` already point to `hexafe-plotstats` commit `2c8c9718320ad743f3779900435ab032d616f240`, which matches `/home/hexaf/Projects/hexafe-plotstats` `main` at validation time.

Not covered in this Linux validation slice:

- Windows executable launch smoke.
- Google conversion smoke.
- Clean-machine install smoke.
