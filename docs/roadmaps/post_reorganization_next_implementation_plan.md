# Post-Reorganization Next Implementation Plan

Created: 2026-05-31
Status: Active post-reorganization implementation plan

## Context

The directory reorganization is complete. `src/metroliza/` is the canonical
application package, and `modules.*` remains an intentional compatibility layer
for legacy imports, dynamic import paths, and packaging hidden imports. Do not
plan a shim removal as part of the next implementation wave.

This plan starts from the completed layout and focuses on the next work that
should raise release confidence and reduce remaining structural debt.

## Audit Snapshot

Current branch at audit time: `codex/directory-reorg-plan`

Current HEAD at audit time: `9d18b61f72292041fe8df3dcff58df8b604f38b9`

The reorganization itself is not the remaining blocker. The current blockers are
release-promotion evidence, stale active-plan references, and post-reorg
structural cleanup that should move in separate reviewable slices.

Verified locally during this audit:

```bash
PYTHONPATH=src:. python -m pytest tests/test_directory_reorganization_architecture.py -q
PYTHONPATH=src:. python -m pytest tests/test_docs_markdown_links.py tests/test_requirements_hygiene.py -q
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
git diff --check
```

Audit findings to carry into implementation:

- Runtime/source imports are clean: `src/metroliza/`, `scripts/`, and Python
  packaging helpers do not directly import `modules.*`.
- `modules.*` compatibility remains intentional in alias shims, legacy dynamic
  imports, and packaging hidden-import coverage.
- Test coverage still leans on legacy imports heavily; migrate tests by package
  slice and keep only explicit compatibility tests on `modules.*`.
- Active roadmaps and next-session docs still contain pre-reorganization
  `modules/*` write targets. Update them to `src/metroliza/*` paths or mark the
  sections as historical before assigning new implementation work from them.
- Release docs still mix two states: the directory reorganization is complete,
  but RC promotion remains blocked until manual evidence and security triage are
  recorded for the final candidate.
- New supplier report templates should be parser-plugin first. Built-in parser
  changes should be reserved for shared parser interfaces, factory behavior, or
  formats explicitly accepted as core Metroliza parsers.
- `scripts/security_audit.py --ci` passes after `pip-audit`; medium Bandit
  findings remain report-only warnings and still require release-owner review or
  waiver before Go.

## Scope Rules

- New implementation imports must use `metroliza.*`.
- `modules.*` files stay alias shims unless a dedicated compatibility-breaking
  cleanup is approved later.
- Release evidence updates belong in `docs/release_checks/`, but only when a
  release-closeout slice is actually executed.
- Archived docs are historical. Scan them for stale links during documentation
  cleanup, but edit them only in a dedicated docs cleanup with explicit approval.
- New report parsers should be created as external parser plugins under the
  documented plugin workflow unless maintainers approve a built-in parser.
- Keep slices small enough to review and validate independently.

## Workstreams

### 1. Release Evidence Closeout

Owner: release evidence subagent.

- Update release status docs so they say the reorganization is complete while
  RC promotion evidence is still open.
- Record final SHA, CI run, required job status, and skipped manual lanes for
  the current branch when verified.
- Run or explicitly waive packaging smoke, Windows executable clean-machine
  launch, Google conversion smoke, third-party notice artifact evidence, and
  clean-machine smoke evidence.
- Review or waive the medium Bandit baseline, especially SQL-construction B608
  reports, before any Go decision.
- Separate environment/tooling warnings from release blockers.

Primary validation:

```bash
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
```

### 2. Docs And Reference Cleanup

Owner: docs/reference subagent.

- Make active docs consistently describe `src/metroliza/` as canonical.
- Keep user manuals focused on user behavior, not internal import mechanics.
- Remove stale references to pre-reorganization paths from active docs.
- Confirm parser plugin docs, native build docs, packaging docs, and docs index
  all point at the current package/resource paths.
- Inventory every `docs/roadmaps/*.md` file as active, completed record, or
  archive candidate; update `docs/README.md` so active docs are indexed.
- Add a short archive-wide note that old `modules/*` implementation paths are
  historical after the `src/metroliza/` reorganization instead of rewriting every
  archived body line.
- Add docs guard tests for active-roadmap indexing and active-doc `modules/`
  write-scope drift once the inventory is complete.

Primary validation:

```bash
PYTHONPATH=src:. python -m pytest tests/test_docs_markdown_links.py tests/test_ci_policy_sync.py -q
python scripts/check_release_hygiene.py
```

2026-05-31 implementation note:

- Active production-analytics, OCR, and UI reference docs now point new work at
  canonical `src/metroliza/*` paths or carry pre-reorganization historical notes.
- `docs/README.md` now inventories every `docs/roadmaps/*.md` file by status.
- `docs/archive/README.md` carries the archive-wide `modules/*` historical-path
  disclaimer.
- `tests/test_docs_markdown_links.py` guards that every roadmap remains listed
  in the docs index.

### 3. Canonical Import Guardrail Hardening

Owner: architecture guardrail subagent.

- Tighten architecture tests around new `modules.*` imports in implementation code
  and active implementation docs.
- Keep packaging hidden-import exceptions explicit and documented.
- Add focused checks for future `src/metroliza/` package boundary regressions:
  shared-package feature imports, UI dependencies outside UI/app/workers, and native
  Rust imports.
- Add a decreasing-budget test for legacy imports in behavior tests, then burn
  the budget down by package slice until only explicit compatibility tests import
  `modules.*`.
- Update stale source docstrings/comments that still describe canonical modules
  with old `modules.*` names.
- If legacy packaging imports stay for another compatibility release, add an
  explicit allowlist test for `.ps1` packaging scripts so new legacy contracts
  are intentional.
- Do not weaken legacy shim tests; shims are compatibility assets.

Primary validation:

```bash
PYTHONPATH=src:. python -m pytest tests/test_directory_reorganization_architecture.py tests/test_packaging_spec_hiddenimports.py -q
PYTHONPATH=src:. python -m ruff check tests/test_directory_reorganization_architecture.py tests/test_packaging_spec_hiddenimports.py
```

### 4. Parser Plugin Productionization

Owner: parser-plugin subagent.

- Treat new supplier report templates as external parser plugins by default.
- Keep the active plugin contract stable: `BaseReportParser`,
  `BaseReportParserPlugin`, `PluginManifest`, `probe(...)`, `parse_to_v2(...)`,
  and `to_legacy_blocks(...)`.
- Audit plugin runtime discovery after the reorganization:
  `~/.metroliza/parser_plugins/` and `PARSER_EXTERNAL_PLUGIN_PATHS`.
- Add or refresh fixture coverage for a generated plugin that exercises probing,
  V2 parsing, expected-results CSV validation, and resolver diagnostics without
  committing real supplier reports.
- Keep plugin docs and rollout runbook aligned with canonical `metroliza.*`
  paths and the compatibility-only `modules.*` policy.
- Do not add new parser dependencies, global registry mechanisms, network access,
  or subprocess-based parsing in this slice.

Primary validation:

```bash
PYTHONPATH=src:. python -m pytest \
  tests/test_parser_plugin_validation.py \
  tests/test_parser_plugin_repair_loop.py \
  tests/test_directory_reorganization_architecture.py \
  tests/test_docs_markdown_links.py -q
PYTHONPATH=src:. python scripts/create_parser_plugin_workspace.py \
  --plugin-id supplier_alpha \
  --source-format pdf \
  --output-dir /tmp/metroliza_parser_plugin_workspace
PYTHONPATH=src:. python scripts/validate_parser_plugins.py \
  --paths /tmp/metroliza_parser_plugin_workspace/generated_plugin.py \
  --plugin-id supplier_alpha
```

### 5. Exporter Phase-B Structural Decomposition

Owner: exporter decomposition subagent.

- Continue Phase-B decomposition from `docs/roadmaps/exporter_audit_2026_03.md`.
- Keep `src/metroliza/exporting/export_data_thread.py` as orchestration, not a
  formatting and worksheet-detail sink.
- Extract behavior-preserving services around remaining hotspots before changing
  user-visible export behavior.
- Preserve dashboard-first routine output; workbook generation remains opt-in.

Initial targets:

- Summary sheet write orchestration.
- Group analysis rendering and annotation coordination.
- Horizontal measurement-sheet layout details.
- `run()` stage bodies and cancellation-safe state transitions.

Primary validation:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest \
  tests/test_export_summary_composition_service.py \
  tests/test_export_group_analysis_annotation_service.py \
  tests/test_export_workbook_output.py \
  tests/test_export_data_thread_group_analysis.py \
  tests/test_export_html_dashboard.py -q
PYTHONPATH=src:. python -m ruff check src/metroliza/exporting src/metroliza/charts tests
```

### 6. Industrial And Tabular Analytics Follow-Up

Owner: industrial/tabular analytics subagent.

- Align industrial analytics and tabular analytics around shared filtering,
  grouping, aggregation, and dashboard contracts.
- Preserve production-only analytics as cache-first; do not require CMM reports
  for production data analysis.
- Keep CSV/Excel analytics dashboard-first for routine output.
- Add only narrow UI changes after the service contracts are stable.

Primary validation:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest \
  tests/test_industrial_analytics_service.py \
  tests/test_industrial_analytics_dashboard.py \
  tests/test_industrial_analytics_workflow.py \
  tests/test_tabular_analytics_service.py \
  tests/test_tabular_analytics_filter_dialog.py \
  tests/test_tabular_analytics_grouping_dialog.py -q
PYTHONPATH=src:. python -m ruff check src/metroliza/industrial src/metroliza/tabular tests
```

### 7. Dependency Pin Follow-Up

Owner: dependency hygiene subagent.

- Re-check whether `hexafe-groupstats`, `hexafe-plotstats`, and `oznak` have formal
  release tags that should replace current full-SHA Git pins.
- Keep runtime pins, CI security-audit checkout refs, and hygiene tests synchronized
  in the same change.
- Do not replace full-SHA Git pins with local paths or branch refs for release work.
- Re-run security and packaging checks after any dependency move.

Primary validation:

```bash
PYTHONPATH=src:. python -m pytest tests/test_requirements_hygiene.py tests/test_security_audit.py -q
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
python scripts/check_release_hygiene.py
```

## Implementation Subagent Split

Use subagents for parallel audit/research and for bounded implementation slices.
Keep write ownership disjoint, and integrate through the main agent.

| Subagent | Type | Ownership | Output |
| --- | --- | --- | --- |
| Release evidence | Explorer or worker | `docs/release_checks/`, CI/manual evidence notes only | Current SHA/CI/manual gate status and release-doc patch |
| Docs/reference cleanup | Explorer then worker | `docs/README.md`, active `docs/roadmaps/*.md`, archive disclaimer | Active-doc inventory, canonical path updates, docs guard tests |
| Architecture guardrails | Worker | `tests/test_directory_reorganization_architecture.py`, optional focused docs guard test | Import-budget guard, packaging allowlist, stale docstring cleanup |
| Parser plugins | Explorer then worker | `src/metroliza/parsing/`, `src/metroliza/reports/report_parser_factory.py`, parser-plugin docs/tests | Plugin-first parser path, fixture validation, resolver diagnostics |
| Exporter Phase-B | Worker | One exporter seam at a time under `src/metroliza/exporting/` plus focused tests | Behavior-preserving extraction with parity validation |
| Industrial/tabular analytics | Explorer then worker | `src/metroliza/industrial/`, `src/metroliza/tabular/`, related UI tests | Shared service/UI follow-up plan or narrow implementation patch |
| Dependency hygiene | Explorer | `requirements.txt`, `.github/workflows/ci.yml`, dependency-hygiene tests | Tag availability and exact pin/update recommendation |

## Suggested Sequence

1. Close release evidence for the completed reorganization.
2. Clean active references and docs index entries that describe the new layout.
3. Harden import and packaging guardrails before the next broad implementation wave.
4. Productionize the parser-plugin path for new supplier report templates.
5. Run exporter Phase-B extractions behind focused parity tests.
6. Advance industrial/tabular analytics after exporter contracts are stable.
7. Refresh dependency pins only when upstream packages have formal release tags.

## Integration Rule

Each workstream can be audited by a separate subagent, but the main integrator
should apply patches, resolve overlaps, run the agreed validation, and keep the
final change set scoped to one slice at a time.
