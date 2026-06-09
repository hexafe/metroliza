# RC5 Dashboard And Industrial Cache Release Check - 2026-06-09

Release line: `2026.05 RC5`  
Build: `260609`  
Branch: `rc2`  
Implementation source: `codex/full-module-audit-20260608`

## Scope

This release check covers the RC5 dashboard and Industrial Data hardening slice.

Implemented release-relevant fixes:

- CSV Summary dashboard interactivity now treats any very large group layer like the
  previous dense POPULATION case: in Auto mode groups above 5,000 rows can be
  pre-rendered as static images, and supported group layers can be pre-rendered when the
  selected dashboard data is above 50,000 rows.
- Users can still override the large-group layer behavior and thresholds from Dashboard
  interactivity.
- CSV Summary and Export dashboard visual dialogs no longer expose one shared opacity
  control; opacity remains available for concrete chart elements and selected-element
  styling.
- Industrial Data sync supports reference filters, row limits, and explicit fetch-all
  confirmation before saving fetched rows into the local SQLite cache.
- Cached Industrial Data rows can be opened through the CSV Summary tabular workflow for
  filtering, grouping, dashboards, and optional workbook output.
- Cached industrial rows expose a `source` column plus fetched non-secret source columns
  so users can filter and group by production source and dataset fields.
- GitHub review-note hardening keeps dashboard/preview JSON safe inside inline scripts,
  preserves sync-run links during legacy cache migrations, removes stale dynamic values
  when cached production rows are refreshed, applies missing-field dynamic filters with
  null-aware semantics, refreshes credentials when switching source profiles, and rejects
  scalar `allowed_columns` config values.

## Local Evidence

Completed locally on 2026-06-09:

```bash
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
git diff --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q tests/test_contracts.py tests/test_industrial_analytics_dashboard.py tests/test_dashboard_visual_options.py tests/test_dashboard_visual_options_dialog.py tests/test_dashboard_html_controls.py tests/test_export_html_dashboard.py tests/test_hexafe_plotstats_adapter.py tests/test_industrial_tabular_bridge.py tests/test_industrial_sync_dialog.py tests/test_industrial_data_dialog.py tests/test_release_metadata_sync.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q tests/test_industrial_analytics_dialog.py tests/test_industrial_analytics_workflow.py tests/test_industrial_analytics_workers.py tests/test_industrial_workers_access_check.py tests/test_oznak_adapter.py tests/test_industrial_data_schema_repository.py tests/test_tabular_analytics_service.py tests/test_industrial_analytics_dashboard.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q tests/test_industrial_data_schema_repository.py tests/test_industrial_analytics_service.py tests/test_industrial_sync_dialog.py tests/test_industrial_source_config.py tests/test_dashboard_html_controls.py::test_dashboard_visual_runtime_escapes_script_closing_sequence_in_json tests/test_dashboard_visual_options.py::test_dashboard_visual_preview_html_escapes_script_closing_sequence_in_spec_json
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --cov=. --cov-report=term --cov-report=xml:coverage.xml
```

Results:

- Ruff: passed.
- Compileall: passed.
- Release metadata sync: passed.
- Whitespace diff check: passed.
- Release hygiene: passed.
- Security audit: passed after rerunning with normal network access for `pip-audit`;
  `pip-audit` reported no known vulnerabilities. Existing Bandit medium findings remain
  report-only baseline items tracked in [`implementation_item_triage.md`](./implementation_item_triage.md).
- Focused dashboard/Industrial Data suite: `297 passed, 3 subtests passed`.
- Adjacent industrial/tabular suite: `210 passed`.
- GitHub review-note focused suite: `60 passed`.
- Full headless pytest with coverage: `1901 passed, 264 skipped, 96 warnings, 71 subtests passed`; total coverage `75%`.

## Pending Release Owner Evidence

Manual/opt-in release evidence remains required before promotion:

- Packaging smoke on the final artifact.
- Windows packaged startup benchmark on the final artifact.
- Google conversion smoke on the final artifact.
- Release owner sign-off for remaining implementation/security triage items.
