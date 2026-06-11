# RC5 Parser And UX Release Closeout - 2026-06-11

Release line: `2026.05 RC5`  
Build: `260611`  
Branch: `rc2`

## Scope

This release check covers the final QA, release, and coverage audit closeout for the
current RC5 worktree.

Implemented release-relevant fixes:

- Industrial Data now keeps the launcher cache-first: users configure production
  sources, select a Metroliza report database, fetch rows into the local SQLite
  cache, then use CSV Summary or cached-row workbook export. The launcher no longer
  presents routine direct live Oznak workbook export without a local cache target.
- Parser handoff manifests now list the actual generated prompt files in exact order.
  Handoff integrity checks fail when prompt entries are stale, missing, invalid, or
  disconnected from generated files.
- Parser plugin persistence has direct tests for `ParseResultV2` warning propagation,
  blocking parser errors, no-measurement results, template fallback, confidence
  clamping, and OK/NOK/unknown status mapping.
- Industrial sync-run repository tests now cover latest-run ordering, source-profile
  filtering, sensitive error redaction, and malformed diagnostics JSON fallback.
- Release identity and user-facing release notes were refreshed to
  `2026.05 RC5 (build 260611)`.

## Local Evidence

Completed locally on 2026-06-11:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_parser_plugin_contracts.py tests/test_parser_plugin_scripts.py tests/test_parser_plugin_self_service_cli.py tests/test_parser_plugin_wizard.py tests/test_parse_result_v2_persistence.py -q
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_industrial_data_schema_repository.py tests/test_industrial_data_dialog.py tests/test_industrial_sync_dialog.py -q
PYTHONPATH=src:. python -m pytest tests/test_release_metadata_sync.py -q
git diff --check
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/validate_packaged_pdf_parser.py --require-header-ocr
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
python -m coverage erase
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --cov=src/metroliza --cov=modules --cov=scripts --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_dashboard_visual_options_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_industrial_analytics_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_tabular_analytics_grouping_dialog.py tests/test_tabular_analytics_filter_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_export_dialog_behavior.py tests/test_export_dialog_layout.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_industrial_data_dialog.py tests/test_industrial_export_dialog.py tests/test_industrial_filter_dialog.py tests/test_industrial_linking_dialog.py tests/test_industrial_sync_dialog.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_data_grouping_filter_query.py tests/test_modifydb_record_updates.py tests/test_modifydb_update_statements.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_worker_progress_dialog.py tests/test_parser_plugin_wizard.py tests/test_main_window_metadata_ui.py -q --cov=src/metroliza --cov=modules --cov=scripts --cov-append --cov-report= --cov-fail-under=0
python -m coverage report --fail-under=80
python -m coverage xml -o coverage.xml
```

Results:

- Focused parser plugin and persistence suite: `36 passed`.
- Focused Industrial Data repository, launcher, and sync suite: `45 passed`.
- Release metadata sync tests: `5 passed`.
- `git diff --check`: passed.
- Ruff: `All checks passed!`
- Compileall: passed.
- Release metadata sync: `Release metadata is already in sync.`
- Release hygiene: passed.
- Packaged PDF parser dependency validation: passed; 3 vendored OCR model files found.
- Security audit: passed after rerunning with network access for the temporary
  `pip-audit` environment; `pip-audit` reported no known vulnerabilities. Existing
  Bandit findings remain report-only baseline warnings.
- Full CI-shaped coverage run:
  - main suite: `1922 passed, 273 skipped, 97 warnings, 74 subtests passed`
  - isolated UI append shards: `24 passed`, `40 passed`, `77 passed`, `12 passed`,
    `56 passed`, `82 passed`, and `33 passed`
  - total coverage: `82%` against the blocking `80%` threshold
  - `coverage.xml` written locally as generated evidence and remains untracked.

## GitHub Evidence

Commit `9a9310604604077b26fc5b2a4523459a4e14c5de` (`Finalize RC5 parser and UX
release`) passed default GitHub Actions CI in run
[`27327220468`](https://github.com/hexafe/metroliza/actions/runs/27327220468)
on 2026-06-11.

Green automatic jobs were Static checks, Unit tests with combined coverage
artifact upload, Native wheel build and smoke checks, CMM parser perf guardrail,
and the non-blocking Performance benchmark trend check. Manual/opt-in Packaging
smoke, Windows startup benchmark, and Google conversion smoke were skipped as
expected for default push CI and remain separate release-promotion evidence
gates.

## Pending Release Owner Evidence

Manual/opt-in release evidence remains required before promotion:

- Packaging smoke on the final artifact.
- Windows packaged startup benchmark on the final artifact.
- Google conversion smoke on the final artifact.
- Third-party notice artifact evidence.
- Release owner sign-off for remaining implementation/security triage items.
