# Full Module Audit - 2026-06-08

Branch: `codex/full-module-audit-20260608`  
Base: `rc2` at `44116433a8fcd5f55aff3653b4644240a04b15d6`  
Audit date: 2026-06-08

## Scope

This audit covered canonical application code under `src/metroliza/`, release
automation under `.github/workflows/`, `packaging/`, and `scripts/`, active
user/release docs under `docs/`, and focused tests under `tests/`.

Static inventory at audit start:

| Package area | Python files |
|---|---:|
| `analytics` | 7 |
| `app` | 8 |
| `charts` | 24 |
| `exporting` | 20 |
| `industrial` | 17 |
| `integrations` | 1 |
| `native_bridges` | 7 |
| `parsing` | 18 |
| `reports` | 17 |
| `resources` | 3 |
| `shared` | 20 |
| `tabular` | 5 |
| `ui` | 28 |
| `workers` | 1 |

Largest implementation files reviewed for risk concentration:

| File | Lines |
|---|---:|
| `src/metroliza/exporting/export_data_thread.py` | 6738 |
| `src/metroliza/industrial/industrial_analytics_dashboard.py` | 5519 |
| `src/metroliza/charts/export_html_dashboard.py` | 4411 |
| `src/metroliza/tabular/tabular_analytics_service.py` | 3812 |
| `src/metroliza/charts/hexafe_plotstats_adapter.py` | 2684 |
| `src/metroliza/charts/dashboard_html_controls.py` | 2677 |
| `src/metroliza/charts/dashboard_visual_options.py` | 2510 |
| `src/metroliza/ui/tabular_analytics_grouping_dialog.py` | 2349 |
| `src/metroliza/exporting/group_analysis_writer.py` | 2240 |
| `src/metroliza/ui/industrial_analytics_dialog.py` | 2144 |

## Subagent Split

| Agent | Scope | Outcome |
|---|---|---|
| Ohm | Parser, report repository, shared persistence contracts | Found parsed-report atomicity and CMM persistence propagation defects. |
| Anscombe | Export, charts, Google conversion, dashboard output contracts | Found HTML-only dashboard false success and native chart fallback parity gaps. |
| Herschel | CSV/Excel tabular analytics, industrial analytics, workflow performance | Found CSV/SQLite filter parity and multi-CSV header identity defects. |
| Hume | UI, generated dashboard UX, docs workflow parity, startup UX evidence | Found dashboard modal/error UX issues and stale export manual text. |
| Archimedes | CI, release/security hygiene, packaging, startup/perf gates, native paths | Found packaging OCR smoke gaps, native helper verification mismatch, startup evidence gaps, and perf-gate baseline gaps. |

## Implemented Fixes

| ID | Severity | Area | Fix |
|---|---:|---|---|
| PR-001 | P1 | Report persistence | `ReportRepository.persist_parsed_report()` now replaces parsed report rows, metadata, candidates, warnings, measurements, and duplicate warnings inside one transaction. Regression test injects measurement failure and verifies the previous report remains intact. |
| PR-002 | P1 | CMM parsing | `CMMReportParser.to_sqlite()` now re-raises after logging repository failures, so parse orchestration cannot count a failed DB write as success. |
| EX-001 | P1 | Export | HTML-only dashboard export failures are fatal and do not emit the completed signal. Workbook sidecar dashboard failures remain warnings. Dashboard output is verified as created and non-empty. |
| EX-003 | P2 | Charts | Native histogram, IQR, and trend renderer exceptions now fall back to matplotlib when a fallback figure exists, matching distribution behavior. |
| TI-001 | P1 | CSV/Excel analytics | Pandas and SQLite numeric/date `!=` filters now both exclude invalid or blank values. |
| TI-002 | P1 | CSV/Excel analytics | Multi-CSV SQLite loading now builds one global original-header-to-normalized-column map before chunk writes, preserving source column identity across files. |
| CR-001 | P1 | CI packaging smoke | Manual packaging smoke now installs `requirements-ocr.txt` and runs `scripts/validate_packaged_pdf_parser.py --require-header-ocr`. |
| CR-002 | P1 | Native packaging helper | `build_native_and_package.ps1` no longer requires unavailable native CMM persistence, installs OCR requirements, and runs the header-OCR validator after native backend verification. |
| CR-003 | P1 | Windows startup smoke | `measure_windows_startup.ps1` now fails on nonzero exit, missing profile JSONL, empty profile JSONL, or missing `first_event_loop_tick`. |
| CR-004 | P2 | Performance gate | `benchmark_trend_compare.py` supports `--require-baselines` and `--require-observed`; the blocking CMM trend gate uses both flags. |
| UX-005 | P2 | User docs | Export manual now documents the dashboard-only `.html` path and includes `HTML dashboard only` in the preset list. |

## Deferred Findings

These are real findings but were left as follow-up work to keep this branch
reviewable and avoid broad behavior changes without runtime/browser evidence.

| ID | Severity | Area | Finding | Recommended next step |
|---|---:|---|---|---|
| PR-003 | P2 | Parser plugins | External file/entry-point parser plugin IDs can remain registered after config removal. | Track loaded external plugin IDs/modules and unregister them on external config signature changes. |
| PR-004 | P2 | Declarative parser profiles | `install_profile()` can move the approved profile before replacement copy/approval is fully verified. | Stage new profile and approval in temp storage, verify checksum, then promote atomically. |
| EX-002 | P2 | Google conversion | Cancellation or validation failure after Drive upload can leave orphaned converted files. | Track created file IDs and best-effort trash/delete on post-upload cancellation/failure. |
| EX-004 | P3 | Google upload performance | Workbook upload path materializes full multipart bytes in memory. | Use resumable/chunked upload above a size threshold. |
| TI-003 | P2 | Industrial export | Cached industrial export filters dynamic values but workbook output only includes fixed columns. | Include dynamic cached fields in cached export output. |
| TI-004 | P2 | Industrial sync | Link materialization failure after cache upsert records sync failure with `row_count=0` while rows may exist. | Separate cache-write status from link-refresh diagnostics or make the operation explicitly all-or-nothing. |
| TI-005 | P3 | Industrial performance | Dynamic filters are applied after broad fixed-row loads and dynamic pivots. | Push selective dynamic filters into SQL before frame load. |
| UX-001 | P2 | Generated dashboard layout | Visuals dialog can overflow short viewports. | Add modal max-height, internal scrolling, and footer-safe actions, then verify with browser captures. |
| UX-002 | P2 | Generated dashboard behavior | Plotly runtime failures can leave blank panels with no visible recovery message. | Add visible per-chart fallback/status messages and browser tests with Plotly blocked. |
| UX-003 | P3 | Validation UX | Some export/dashboard controls silently clamp invalid numeric settings. | Add visible inline correction/status text and accessibility state. |
| UX-004 | P3 | Accessibility | Visual element selection copy and tests emphasize pointer use. | Support and prove keyboard-only visual element selection. |
| UX-006 | P2 | Startup readiness evidence | Tests still mostly mock startup readiness; packaged ready-to-click evidence is separate. | Add packaged/offscreen smoke that proves actionable UI readiness beyond first event-loop tick. |
| CR-005 | P2 | Release evidence | Active release evidence still includes older build identifiers in some logs. | Refresh release evidence for the exact promoted artifact before release owner sign-off. |
| CR-006 | P1 | Security/release triage | Bandit medium findings are still non-failing while triage marks baseline burn-down as release work. | Resolve, narrowly waive, or promote selected medium findings after triage owner review. |

## Validation Evidence

Focused validation run during implementation:

```bash
PYTHONPATH=src:. python -m pytest tests/test_ci_policy_sync.py tests/test_startup_performance_guards.py tests/test_benchmark_trend_compare.py tests/test_export_presets.py tests/test_build_native_and_package_helper.py -q
PYTHONPATH=src:. python -m pytest tests/test_tabular_analytics_service.py tests/test_cmm_parser_parity.py tests/test_report_schema_repository.py tests/test_thread_flow_helpers.py tests/test_chart_renderer.py -q
PYTHONPATH=src:. python -m ruff check src/metroliza/parsing/cmm_report_parser.py src/metroliza/tabular/tabular_analytics_service.py src/metroliza/exporting/export_data_thread.py src/metroliza/charts/chart_renderer.py src/metroliza/reports/report_repository.py tests/test_cmm_parser_parity.py tests/test_tabular_analytics_service.py tests/test_thread_flow_helpers.py tests/test_chart_renderer.py tests/test_report_schema_repository.py
git diff --check
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q
```

Results:

- `74 passed, 3 subtests passed`
- `245 passed, 3 skipped, 5 warnings, 2 subtests passed`
- Ruff changed-file check passed.
- `git diff --check` passed.
- Full Ruff check passed.
- Compileall passed.
- Release metadata sync passed.
- Release hygiene passed.
- Security audit passed after rerunning with normal network access for
  `pip-audit`; `pip-audit` reported no known vulnerabilities.
- Full headless pytest passed:
  `1889 passed, 263 skipped, 6 warnings, 71 subtests passed`.

Full release validation and terminal CI evidence are tracked separately in the
release-check docs and final branch/CI status.
