# RC4 Static Scatter Annotation Backgrounds Release Check - 2026-05-23

## Scope

- Updated the pinned `hexafe-plotstats[pandas]` dependency to commit
  `2a15c1c799902831f64b95a53de30547885cdcc8`.
- The pinned plotstats commit adds semi-opaque white backgrounds behind static
  Matplotlib scatter reference annotations so LSL, Nominal, and USL labels stay
  readable over their reference lines.
- Codex review comments on Metroliza PR #895 were audited. The sampling-budget
  thread is resolved. The reference-cohort groupstats and trend-vs-scatter chart
  classification comments are already covered by current code and regression
  tests, but their GitHub thread state may remain unresolved until explicitly
  resolved on the PR.

## Validation

### hexafe-plotstats

- `python -m pytest tests/test_renderer_backends.py -q` - passed, 46 tests.
- `env RUFF_CACHE_DIR=/tmp/metroliza-plotstats-ruff-cache python -m ruff check src/hexafe_plotstats/renderers/matplotlib/scatter.py tests/test_renderer_backends.py` - passed.
- `env PYTHONPYCACHEPREFIX=/tmp/metroliza-plotstats-pycache python -m compileall -q src tests` - passed.
- `env PYTHONPYCACHEPREFIX=/tmp/metroliza-plotstats-pycache python -m pytest -q -p no:cacheprovider` - passed, 77 tests, 10 skipped.
- GitHub Actions CI run `26326553748` passed for the initial code-fix commit
  `736ed35048a7c76c3a9b236ed8151b5358286414`.

Note: full-repo plotstats Ruff still reports existing `E402` findings in benchmark scripts outside this fix.

### Metroliza

- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_requirements_hygiene.py tests/test_hexafe_plotstats_adapter.py tests/test_chart_renderer.py -q` - passed, 77 tests.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_dashboard_html_controls.py tests/test_industrial_analytics_workflow.py -q` - passed, 19 tests.
- `python -m ruff check .` - passed.
- `python -m compileall -q -x '^\\./\\.git/' .` - passed.
- `python scripts/sync_release_metadata.py --check` - passed.
- `python scripts/check_release_hygiene.py` - passed.
- `QT_QPA_PLATFORM=offscreen python -m pytest tests -q` - passed, 1645 tests, 174 skipped, 60 subtests.
- `python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects` - passed after rerun with network access for `pip-audit`.

Security audit retained the existing report-only Bandit warning baseline.

Manual release-promotion gates remain separate from this PR CI check: packaging
smoke, Windows clean-machine launch, Google conversion smoke, and third-party
notice evidence still require release-owner/QA evidence before promotion.
