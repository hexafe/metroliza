# Release Status — Active Operations

- Status: Active release status hub
- Owner: Release maintainer
- Last reviewed: 2026-08-22
- Current release identity: `2026.06 RC2 (build 260711)`

Use this page for the current release state. Exact decision evidence belongs in the linked
release-check documents. Historical run-by-run detail remains in those documents and in git history;
it is not repeated indefinitely in this active hub.

## Current decision

| Decision | State | Evidence / owner |
|---|---|---|
| Automatic candidate content | **Passed** | [`rc2_branch_transition_decision_2026-08-22.md`](./rc2_branch_transition_decision_2026-08-22.md), CI run `32585291955` |
| Development branch transition | **Go** | `develop` is the canonical development base |
| Frozen candidate branch | **Active** | `release/2026.06-rc2` |
| Stable promotion to `master` | **No-Go** | blocked by #901 manual packaged/Windows/Google/notices/legal evidence |
| Stable tag | **No-Go** | may be created only after the release-owner Go decision |
| Security exception review | **Open** | #906 before baseline expiry on 2026-10-31 |

## Candidate identity and branches

Release line metadata is canonical in `src/metroliza/app/version.py`:

- `RELEASE_VERSION` defines the release version;
- `VERSION_DATE` defines the release date;
- `CURRENT_RELEASE_HIGHLIGHT` defines the current release summary.

Validate those values and their synchronized consumers with:

```bash
python scripts/sync_release_metadata.py --check
```

Current branch roles:

- `develop` — normal Issue-driven development;
- `release/2026.06-rc2` — frozen candidate and promotion-evidence line;
- `rc2` — retained transition/reference branch, no new routine work;
- `master` — unchanged historical/default production branch pending promotion.

Validated branch-point content before the #900 decision documentation:

- final governance commit: `a03bbdacbd6c308acf46ca31c16d0dd2caeab304`;
- final tree: `dc10e028332cb311cb0b2c110deecee2841b9799`;
- parent product commit: `202690eb21087314a3c8000aa3ebdb58a1a09c1b`;
- CI-tested synthetic merge: `0a3f2b982f827466f214cede76995a5bf3effa14`;
- CI-tested tree: `dc10e028332cb311cb0b2c110deecee2841b9799`.

The tested synthetic merge and final governance merge have the same tree SHA, so the automatic
results apply to the exact selected repository content. The branch-transition PR itself is
documentation-only and must also complete normal exact-tree CI before #900 closes.

## Gate sources

- **PR-blocking CI gates** are defined in [`../ci-policy.md`](../ci-policy.md) and must be green for
  merge readiness on the exact pull-request content.
- **Release-blocking manual evidence gates** are defined in [`release_candidate_checklist.md`](./release_candidate_checklist.md)
  and must be complete before a candidate can be promoted.
- Google conversion smoke is intentionally local-only and remains release-blocking for promotion;
  a green hosted CI run does not satisfy that evidence gate.

## Current automatic evidence

Pull-request CI run `32585291955` completed successfully:

| Gate | Result |
|---|---|
| Compile check and parser-profile self-service smoke | Passed |
| Ruff full repository | Passed |
| Selected strict mypy boundaries | Passed |
| Release metadata consistency | Passed |
| Secret scan and release hygiene | Passed |
| Dependency/security audit, including pinned sibling packages | Passed |
| Main test suite | `3030 passed, 21 skipped, 8 warnings, 98 subtests passed` |
| Additional real-Qt append shards | Passed |
| Aggregate line coverage | `83.80%` |
| Canonical `src/metroliza` line coverage | `85.72%` |
| Blocking coverage threshold | `80%` — passed |
| Native wheel builds/imports and chart/parser/export parity smoke | Passed |
| Windows core path/SQLite/metadata smoke | Passed |
| CMM parser performance guardrail | Passed |
| Performance trend check | Passed |

Normal PR CI intentionally skipped the manual/opt-in packaged Windows startup and packaging lanes.
Live Google conversion is also a separate local/manual release gate. These skipped lanes do not
invalidate automatic CI, but they cannot be used as promotion evidence.

## Current promotion blockers — #901

Before a Go decision for `master` or a stable tag, the exact final candidate must have:

- approved PyInstaller and Nuitka builds;
- artifact hashes plus staged/verified third-party notices and dependency inventory;
- packaged parser/OCR, SQLite, dashboard, realtime, workbook, and export smoke;
- clean-machine Windows launch and startup/readiness evidence;
- secure live Google conversion smoke, validation, cleanup, cancellation/failure behavior, and
  preserved local `.xlsx` fallback;
- release-owner/legal review for PyQt/Qt, PyMuPDF, Rust crates, and generated notices;
- any release-line fix rerun through the applicable exact-head automatic and manual gates.

Issue #901 is the executable work item and evidence checklist for these blockers. None is silently
waived by the branch transition.

## Active release documents

- [`rc2_branch_transition_decision_2026-08-22.md`](./rc2_branch_transition_decision_2026-08-22.md)
  — exact automatic evidence, branch decision, and promotion no-go.
- [`release_candidate_checklist.md`](./release_candidate_checklist.md)
  — primary release-candidate gate and sign-offs.
- [`implementation_item_triage.md`](./implementation_item_triage.md)
  — must-fix/defer/late-scope decisions.
- [`google_conversion_smoke.md`](./google_conversion_smoke.md)
  — required live Google conversion evidence log.
- [`open_testing_runbook.md`](./open_testing_runbook.md)
  — manual/open-testing execution guidance.
- [`branching_strategy.md`](./branching_strategy.md)
  — active branch roles and merge directions.
- [`rc2_audit_pass2_release_check_2026-07-11.md`](./rc2_audit_pass2_release_check_2026-07-11.md)
  — build `260711` implementation audit and pre-transition local evidence.
- [`cmm_parser_perf_guardrail.md`](./cmm_parser_perf_guardrail.md)
  — parser performance policy and failure triage.

## Release-line operating rules

- Normal work starts from and targets `develop`.
- Candidate fixes/evidence start from and target `release/2026.06-rc2`.
- Every accepted candidate fix is reconciled into `develop`.
- No new feature, broad refactor, visual redesign, or convenience dependency upgrade enters the
  frozen candidate.
- A late-scope exception requires an explicit triage record, release-owner approval, test evidence,
  and rollback/deferral option; it does not waive manual release gates.
- `master` and stable tags remain untouched until the final Go decision.
- GitHub still presents `master` as the default branch; choose PR bases explicitly.

## Historical evidence index

The following documents remain the durable source for earlier implementation and release evidence:

- [`rc2_full_repo_hardening_2026-07-09.md`](./rc2_full_repo_hardening_2026-07-09.md)
- [`rc2_pandas_free_sqlite_performance_2026-06-23.md`](./rc2_pandas_free_sqlite_performance_2026-06-23.md)
- [`ui_overlap_layout_audit_2026-06-19.md`](./ui_overlap_layout_audit_2026-06-19.md)
- [`realtime_industrial_performance_check_2026-06-17.md`](./realtime_industrial_performance_check_2026-06-17.md)
- [`realtime_industrial_optimization_check_2026-06-16.md`](./realtime_industrial_optimization_check_2026-06-16.md)
- [`realtime_monitor_ui_ux_audit_2026-06-15.md`](./realtime_monitor_ui_ux_audit_2026-06-15.md)
- [`rc5_rc_audit_evidence_2026-06-12.md`](./rc5_rc_audit_evidence_2026-06-12.md)
- [`rc5_parser_ux_release_closeout_2026-06-11.md`](./rc5_parser_ux_release_closeout_2026-06-11.md)
- [`rc5_industrial_data_csv_summary_followup_2026-06-10.md`](./rc5_industrial_data_csv_summary_followup_2026-06-10.md)
- [`rc5_dashboard_industrial_cache_check_2026-06-09.md`](./rc5_dashboard_industrial_cache_check_2026-06-09.md)
- [`full_module_audit_2026-06-08.md`](./full_module_audit_2026-06-08.md)
- [`rc2_performance_optimization_check_2026-05-20.md`](./rc2_performance_optimization_check_2026-05-20.md)
- [`rc2_release_audit_2026-05-17.md`](./rc2_release_audit_2026-05-17.md)

Older exact run IDs and counts are historical evidence, not the current candidate decision. Use the
linked documents and git history when investigating them.

## Status update rule

Update this page whenever one of these changes:

- final candidate branch/commit/tree;
- automatic CI conclusion or coverage threshold;
- manual promotion blocker status;
- release-owner Go/No-Go;
- branch role or release identity.

Keep the hub concise. Put full logs, artifact hashes, screenshots, environment descriptions, and
sign-offs in the dedicated evidence document or Issue.
