# #1128 — CSV Summary export performance

## Durable authority and objective

Issue: https://github.com/hexafe/metroliza/issues/1128 (read with `gh issue view 1128`).
Execution packet: external orchestrator's task in this session; no Issue comment.
Base: current RC1 worktree, `perf/1128-csv-summary`, commit
`82f8f57653964dd344fac7c01a84d9ab303cdaac`. The explicit packet requires staying
on this branch; no integration target or remote action is authorized.

Reduce chart/manifest and workbook export overhead while retaining workbook cells,
sheets, chart data, images and dashboard content, including full-data statistics.
Sources read: `AGENTS.md`, project README/architecture/development workflow,
branching strategy, model routing, task packet and routing report templates.

## Routing and ownership

Whole-PR class: BOUNDED INTEGRATION; numerical and artifact equivalence span the
CSV dashboard and workbook boundaries. Requested coordinator: Codex, with commit
attribution GPT-6.1 Sol; requested reasoning unspecified. Actual runtime model and
reasoning: not visible. No downgrade or worker-model claim.
Coordinator-only implementation: workers skipped to keep numerical equivalence
and artifact ownership in one context. External Claude Code owns independent
exact-head review and any integration decisions.

Owned scope: tabular workbook writing, industrial analytics chart/manifest
construction and their directly related chart helpers/tests; this evidence note
and coverage ownership for any new source/test paths. `scripts/benchmark_paths.py`
is the representative measurement driver. Audit scripts/outputs live outside the
repository under the assigned `scratchpad/codex/1128/` directory.

## MUST

1. Capture base artifacts before implementation. Compare all workbook cells,
   sheets, chart definitions and embedded images, plus complete dashboard data.
2. Preserve full-data statistics, existing sampling behavior and offline assets.
   Any new decimation would require min/max-shape preservation and separate proof.
3. Measure 10,000 and 100,000 rows × 8 columns, median of three fresh-process
   benchmark runs; report load averages and peak RSS.
4. Run all related test files and the complexity, ownership and security checks,
   plus Ruff. Never increase the complexity budget or silently rebaseline Bandit.
5. Commit locally with #1128 and the required co-author trailer. Preserve atomic
   publication, deterministic cleanup, Python fallback and packaged compatibility.

## SHOULD

1. Reuse direct XlsxWriter techniques from #1124 where output equivalence permits.
2. Render independent charts in parallel if bounded execution and deterministic
   output can be demonstrated within the existing packaging/runtime contract.

## DEFERRED / forbidden

Remote writes, push/PR/merge, rebasing, destructive Git operations, real data,
release/promotion, database migrations and broader analytics changes are excluded
by the execution packet. Windows/frozen-build execution and hosted CI require the
external orchestrator's environment; source/Linux proof must remain distinct.
No approved product-requirement deferral is inferred.

## Validation and readiness

Pending implementation and measurements. Acceptance requires the MUST-to-evidence
record below; the coordinator does not claim independent review, CI, mergeability
or release readiness. Rollback is a local revert of the bounded implementation;
no persisted source-data format change is planned.
