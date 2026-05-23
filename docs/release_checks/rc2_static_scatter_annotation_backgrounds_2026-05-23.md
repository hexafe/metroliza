# RC2 Static Scatter Annotation Backgrounds Release Check - 2026-05-23

## Scope

- Updated the pinned `hexafe-plotstats[pandas]` dependency to commit
  `736ed35048a7c76c3a9b236ed8151b5358286414`.
- The pinned plotstats commit adds semi-opaque white backgrounds behind static
  Matplotlib scatter reference annotations so LSL, Nominal, and USL labels stay
  readable over their reference lines.

## Validation

### hexafe-plotstats

- `python -m pytest tests/test_renderer_backends.py -q` - passed, 46 tests.
- `env RUFF_CACHE_DIR=/tmp/metroliza-plotstats-ruff-cache python -m ruff check src/hexafe_plotstats/renderers/matplotlib/scatter.py tests/test_renderer_backends.py` - passed.
- `env PYTHONPYCACHEPREFIX=/tmp/metroliza-plotstats-pycache python -m compileall -q src tests` - passed.
- `env PYTHONPYCACHEPREFIX=/tmp/metroliza-plotstats-pycache python -m pytest -q -p no:cacheprovider` - passed, 77 tests, 10 skipped.

Note: full-repo plotstats Ruff still reports existing `E402` findings in benchmark scripts outside this fix.

### Metroliza

- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_requirements_hygiene.py tests/test_hexafe_plotstats_adapter.py tests/test_chart_renderer.py -q` - passed, 77 tests.
- `python -m ruff check .` - passed.
- `python -m compileall -q -x '^\\./\\.git/' .` - passed.
- `python scripts/sync_release_metadata.py --check` - passed.
- `python scripts/check_release_hygiene.py` - passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests -q` - passed, 1645 tests, 174 skipped, 60 subtests.
- `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` - passed after rerun with network access for `pip-audit`.

Security audit retained the existing report-only Bandit warning baseline.
