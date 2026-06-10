# RC5 Industrial Data CSV Summary Follow-Up - 2026-06-10

Release line: `2026.05 RC5`  
Build: `260609`  
Branch: `rc2`

## Scope

This follow-up tightens the Industrial Data workflow after the RC5 cache-to-CSV Summary
implementation.

Implemented release-relevant fixes:

- Oznak reference fetches no longer send the same pasted reference list as both a generic
  query filter and a batched reference filter.
- Industrial Data now presents Oznak as a fetch-to-cache workflow: configure sources,
  check access, fetch rows into the local SQLite cache, then open cached rows in CSV
  Summary.
- Access-only connection checks hide cache-write controls when no Metroliza report
  database is selected.
- Cached Industrial Data can be opened in CSV Summary for all cached sources or one
  selected cached source.
- The preloaded Industrial Data CSV Summary view hides CSV/Excel file-picking controls
  while keeping row filters, groups, dashboard settings, and optional workbook output.
- Industrial cache metadata now carries cache count summaries into the tabular workflow.

## Local Evidence

Completed locally on 2026-06-10:

```bash
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_oznak_adapter.py tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_analytics_dialog.py tests/test_industrial_tabular_bridge.py -q
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_oznak_adapter.py tests/test_industrial_workers_access_check.py tests/test_industrial_data_schema_repository.py tests/test_industrial_tabular_bridge.py tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py tests/test_industrial_analytics_dialog.py tests/test_industrial_analytics_workers.py tests/test_industrial_analytics_workflow.py tests/test_industrial_analytics_service.py tests/test_industrial_source_config.py -q
PYTHONPATH=src:. python -m pytest tests/test_release_metadata_sync.py -q
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml
```

Results:

- Ruff: `All checks passed!`
- Compileall: passed.
- Release metadata sync: `Release metadata is already in sync.`
- Release hygiene: passed.
- Security audit: passed; `pip-audit` reported no known vulnerabilities, with existing
  Bandit findings remaining report-only baseline warnings.
- Focused adapter, launcher, sync, analytics, and tabular bridge suite: `94 passed`.
- Broader Industrial Data and analytics suite: `169 passed`.
- Release metadata sync tests: `5 passed`.
- Full offscreen pytest suite with coverage: `1903 passed, 265 skipped, 96 warnings,
  71 subtests passed`; total coverage `75%`; `coverage.xml` written.

## Pending Release Owner Evidence

Manual/opt-in release evidence remains required before promotion:

- Packaging smoke on the final artifact.
- Windows packaged startup benchmark on the final artifact.
- Google conversion smoke on the final artifact.
- Release owner sign-off for remaining implementation/security triage items.
