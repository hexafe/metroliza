# #1126 — equivalent, bounded Extended plot rendering

## Execution packet

Authority: the supplied #1126 issue and external-orchestrator packet. Starting
branch `perf/1126-extended-plots`, base `82f8f57653964dd344fac7c01a84d9ab303cdaac`
(RC1, expressly selected by the packet). No branch/base changes or remote
operations are authorized. The external orchestrator owns review/integration.

Objective: reduce Extended plot rendering time while preserving PNG layout,
worksheet content, image anchors, group order and progress reporting.

Whole-change routing: CRITICAL / MILESTONE capability class for process lifecycle
and concurrency; actual model/reasoning: not visible. Coordinator-only execution;
the rendering seam and its evidence benefit from one context and one writer.
Scope: exporter, a bounded group-render helper, focused export tests and this
evidence record. Existing coverage rules assign exporting to #981, tests to #985
and documentation to #975. No native renderer, database schema, UI or packaging
entry-point changes are in scope.

## MUST

1. Capture baseline PNGs and layout decisions before changing production code.
   Compare every image, plus all workbook parts except document timestamps.
2. Measure tiny (4 groups) and a synthetic 40-group subset, median of three;
   record load averages and worker counts.
3. Use bounded, spawn-safe group rendering with deterministic collection, serial
   fallback for small exports/unavailable frozen multiprocessing, and parent-only
   workbook mutation/progress. Retain cancellation and deterministic cleanup.
4. Run related test files, complexity/coverage/security gates and Ruff using the
   supplied Python and crash-safe Qt test command. Never increase budgets or
   silently update the Bandit baseline.

## SHOULD

Reuse the Agg renderer and text extents for annotation candidates and table
layout, avoiding repeated full-figure draws.

## DEFERRED

Native chart rendering. Actual packaged Windows validation remains an external
acceptance gate, not a claim inferred from Linux tests.

## Equivalence harness

`tests/test_export_plot_equivalence.py` accepts `METROLIZA_PLOT_BASE` and
`METROLIZA_PLOT_CANDIDATE` XLSX paths. It compares all package members, worksheet
content/formulas/styles and drawing anchors. PNG dimensions must match; maximum
channel error is 1/255, mean channel error at most 0.0001/255, and at most 0.01%
of pixels may change. A one-pixel annotation shift is an explicit falsifier.
Synthetic reference exports and audit scripts stay in the task scratch directory
under `scratchpad/codex/1126/`, outside Git. Annotation text/position/alignment
and table bounds/font/fallback/row metadata are also captured there.

Stop/escalate if output diverges, the accepted base changes, or Windows support
would require unrelated startup/packaging changes. Rollback is a local revert
of this issue's implementation commits; no data migration is involved.

## Design and lifecycle

Histogram annotations draw once to resolve axes transforms, then measure each
Text/Annotation candidate against the same renderer. Candidate ordering,
collision/edge/title checks and leader-line bounds remain the original ones.
Panel tables and note panels use renderer metrics without drawing the figure;
standalone Text probes avoid adding/removing artists, with a bounded per-table
extent cache. Final chart layout and PNG saving retain their existing passes.

For workbook-only summaries with at least eight groups in one reference
partition, the first group stays serial. The remaining groups use an explicit
`spawn` context, at most four workers (also bounded by `chart_worker_count`), and
at most `min(chart_worker_queue_size, 2 * workers)` pending jobs. The parent
prepares SQL aggregates; children receive only options, the group, grouping
assignments, aggregates and the active chart settings. Children render through
the existing summary path against a recording worksheet. They open no database
or output files. PNG bytes, worksheet commands, warnings and telemetry return
to the parent, which replays them in input order. Progress remains in the
original per-group parent loop.

The first serial group establishes the existing adaptive density policy. If
active settings change after submission, stale results are discarded and that
group follows the original serial path. Startup/submission/task failures switch
remaining groups to serial without duplicating writes. A shared spawn event
connects parent cancellation to the workers' existing chart-boundary checks.
The parent polls futures every 100 ms and discards results after cancellation.
Cancellation, early exit and failures signal workers and cancel queued futures.
Cleanup allows two seconds for cooperative exit, then terminates remaining
workers, waits another 500 ms, kills survivors and waits another 500 ms. The
executor manager thread has a final 500 ms join. These deadlines are shared
across all workers in each phase, rather than multiplied by the worker count.
Worker initialization disables core dumps on POSIX; no QApplication is created
in workers.

Single-worker, fewer-than-eight-group and dashboard exports stay serial.
Current frozen entry points lack multiprocessing worker dispatch, so frozen
exports explicitly stay serial and never relaunch the desktop app as a worker.
`METROLIZA_EXPORT_GROUP_MP=0` disables the new pool. The existing opt-in fit/trend
executor is unchanged.

This remains one performance outcome: the additional test/evidence lines are
required to prove pre-change image parity, spawn behavior and failure cleanup;
they do not introduce another product feature.

## Security baseline drift

The baseline file was deliberately **not** regenerated. A focused Bandit scan
finds the same two B608 SQL statements, now at lines 3967/3987 rather than
3959/3979. Their code and security rationale are unchanged, but line-sensitive
fingerprints change from `63e7da8a6a1b...` / `b42ab68583b2...` to
`af5bfce05135...` / `bda540c8b3c6...`. The external orchestrator must review this
drift before a full security-baseline gate can pass. The existing low-severity
B112 also moves from 2536 to 2543. No SQL or exception-handling policy was
changed by this work.

## Measured evidence

Serial timing source: `fa557916`. Final parallel timing source: `14ca50cd`,
which restores the serial missing-identity guard in pool task preparation;
the serial renderer is unchanged between those commits. Baseline source:
`82f8f57653964dd344fac7c01a84d9ab303cdaac`. Baseline exports were captured in the
current worktree before production edits; no second worktree was created.

All numbers below are medians of three full `ExportDataThread.run()` audit
exports, using `full_report`. Times include workbook close and process startup/
shutdown. The audit script prints wall time to one decimal place.

| Synthetic fixture | Before, 1 worker | After, 1 worker | After, 2 workers |
| --- | ---: | ---: | ---: |
| tiny, 4 groups / 320 measurements | 7.6 s | 5.0 s | serial policy tested |
| groups40, 40 groups / 3,200 measurements | 77.6 s | 51.9 s | 30.7 s |

Recorded repetitions: tiny before `[7.0, 7.6, 7.9]`, after `[5.4, 5.0, 5.0]`;
groups40 before `[77.7, 74.0, 77.6]`, after serial `[48.0, 51.9, 61.2]`, after
parallel `[30.7, 30.2, 34.0]`. Median starting load averages (1/5/15 minutes):

| Run set | Load average |
| --- | --- |
| tiny before | 2.58 / 2.23 / 1.50 |
| tiny after | 3.79 / 4.52 / 3.27 |
| groups40 before | 4.10 / 2.80 / 1.79 |
| groups40 after serial | 6.26 / 5.03 / 3.53 |
| groups40 after parallel | 6.33 / 6.70 / 5.42 |

These are shared-machine observations, not a quiet-machine extrapolation. The
40-group histogram median fell from 1.201 to 0.491 seconds in the serial runs.
All three parallel runs recorded two workers, at most four pending groups and
39 completed worker jobs. The first group was serial. Sampled process-tree peak
RSS was 807–810 MB with two workers, versus roughly 300 MB serial. Worker
chart-time sums represent CPU work, not export wall time.

The 40-group fixture copies `perf_audit/data/sub_50.sqlite` and retains the first
40 distinct `(header, ax)` pairs ordered by `header, ax` in `report_measurements`.
This yields one reference partition with 40 groups. Every export uses a fresh
copy; original audit databases/tools remain unchanged.

All nine measured candidate XLSX packages match the reference package member
order and every member except `docProps/core.xml` (document timestamps).
**1,008 PNGs are byte-identical**, stronger than the declared pixel tolerance.
All six serial annotation/table trace sets match, including text, positions,
alignment, table bounds, fonts, rows and fallback metadata. The guarded spawn
probe also passed a decoded-pixel comparison of all 160 PNGs with zero error.
The collision/edge harness separately compares layout decisions and pixels
against the captured base module on three synthetic adversarial scenes.

The preliminary `probe` benchmark is excluded: its wrapper temporarily used
`runpy` with `__main__`, causing children to re-run the audit entry point. The
corrected wrapper runs that unmodified script as `audit_benchmark`, preserving
the guarded wrapper as the spawn entry point. Both receipts are retained.
The earlier valid pre-guard parallel series `[40.3, 38.6, 40.1]` is also retained;
the table uses the final pool source. Differences between those series reflect
shared-machine variability, not a speed claim for the identity guard.

## Reproduction commands and remaining gates

All scripts, raw logs, DB copies, workbook references, layout traces and
`results.json` are under this task's scratch directory:

```bash
S=/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1126
P=/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python
bash "$S/baseline.sh"   # executed before production edits
bash "$S/candidate.sh"  # three tiny, three serial40, three parallel40 runs
bash "$S/guard-benchmark.sh"  # repeat parallel40 three times on final source
"$P" "$S/report.py"
```

The wrapper executes the read-only audit `bench_export.py` with
`<copied-db> <out.xlsx> --preset full_report --workers 1` (or `2` for parallel).
Each shell script uses `ulimit -c 0`, offscreen Qt, removes
`QT_QPA_PLATFORMTHEME`, and sets `PYTHONPATH=src:.`.

Final regression command (also saved verbatim in `verification.sh`):

```bash
ulimit -c 0
export METROLIZA_PLOT_REFERENCE_MODULE="$S/base_export_data_thread.py"
export METROLIZA_PLOT_BASE="$S/base1-groups40.xlsx"
export METROLIZA_PLOT_CANDIDATE="$S/guard1-groups40.xlsx"
env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_export*.py tests/test_thread_flow_helpers.py tests/test_chart_renderer.py tests/test_chart_render_service.py tests/test_summary_plot_palette_accessibility.py tests/test_analytics_exporting_boundary.py tests/test_contracts.py tests/test_complexity_ratchet.py tests/test_bug_sweep_coverage.py tests/test_security_audit.py
"$P" -m ruff check .
git diff --check
```

Earlier integrated validation exposed an unclassified test-helper import
(`902 passed, 1 failed, 2 skipped`); the import was corrected to `tests.*`.
The affected tests plus complexity, coverage and security then passed
(`132 passed, 1 skipped`). The adverse log is retained as
`integration-tests.log`. The first complete gate passed `910 passed, 1 skipped,
35 subtests passed` (`final-tests.log`); the post-guard focused gate passed all
141 tests (`guard-tests.log`). The final-source integrated gate is saved
separately as `final-head-tests.log`: **914 passed, 1 skipped, 35 subtests passed**
in 143.42 seconds, with six expected deprecation/native-rollout warnings.
`python -m ruff check .` and `git diff --check` both passed. No complexity budget
or coverage ownership rule was weakened. The final gate exercised production
source `14ca50cdebe7cb8dd9bc1b38abff862920343a0f`; subsequent changes are this
evidence record only.

Not verified here: actual Windows source execution, frozen/clean-machine
exports, CI, independent exact-head review and remote integration. Frozen
fallback policy and POSIX spawn rendering are automated evidence only. Dashboard
exports intentionally retain the serial path. Parallelism is within each
reference partition, with an eight-group threshold. The Windows packaged gate
and the reviewed Bandit fingerprint drift remain external acceptance work.
No remote operations were performed. No PR was opened or merged.

## Internal readiness audit

| Requirement | Observed evidence | Remaining boundary |
| --- | --- | --- |
| Same charts/layout/workbook | Strict PNG/package harness, serial traces, base-source collision scenes | Same-machine synthetic proof |
| Before/after performance | Three repetitions per fixture/mode, raw logs and load averages | Shared-machine timings only |
| Bounded deterministic pool | Real spawn exports; bounded queue, order, partial failure, cancellation and worker-cap tests | Real Windows/frozen execution unverified |
| Required local checks | Related export files plus complexity/coverage/security tests and Ruff | Full Bandit baseline drift requires review |

The final diff is confined to the exporter rendering seam, its helper, two test
files and this record. Internal negative-path review found and corrected a
missing-identity discrepancy: task preparation must skip SQL statistics for a
missing/blank reference or missing header/axis, exactly like the serial path.
Four regression cases now enforce that guard. Workers retain Python statistics
for those groups. No migration, output publication, native rollout or external
service boundary changed.

Representative falsifiers include rejection of a one-pixel label shift, a
changed worksheet/drawing member, unexpected pool startup in frozen/small mode,
unbounded submission, and lost/duplicated entries after partial failure. Core
dumps were disabled for every test/benchmark; no crash was intentionally induced.
Primary tradeoff: bounded extra process memory and spawn startup cost. Rollback:
disable `METROLIZA_EXPORT_GROUP_MP`, or revert the implementation commits for
the original serial layout path.

Correction cycles after readiness: zero (no readiness declaration preceded
these corrections). Actual model/reasoning remains not visible. The same
concurrency/lifecycle acceptance burden merits CRITICAL / MILESTONE capability
coordination on a similar task. Independent exact-head review, CI and merge
readiness belong to the external orchestrator and remain pending; this local
handoff does not assert READY FOR MERGE.

## PR #1130 review correction — cancellation (#1126)

Authority: the supplied external-orchestrator finding and repair packet; current
worktree only, branch `perf/1126-extended-plots`, review base
`22547dee5938f08339bed8441874a6b4c24d5d05`. PR comparison base remains
`origin/integrate/2026.09-rc1-into-develop`. No remote actions are authorized.
Whole-change class remains CRITICAL / MILESTONE; coordinator-only execution,
actual runtime model/reasoning: not visible. Owned files: the existing render
pool, its existing test file and this record. No added repository files.

### MUST

Reproduce cancellation during an active spawn render before fixing production
code; stop subsequent charts, discard canceled results and reap workers within
a bounded shutdown. Preserve ordered, bounded submission, serial fallback and
strict PNG/workbook equivalence. Repeat three-run synthetic benchmarks with
load averages, related tests, complexity/coverage/security gates and Ruff.
Commit locally; leave external review, CI and integration to the orchestrator.

### SHOULD

Use the existing chart-boundary cancellation checks and avoid a manager process
or a new per-chart IPC protocol. Keep core dumps disabled.

### DEFERRED

Actual Windows/frozen-build execution remains the existing external acceptance
gate. No packaging/entry-point, UI, database or native-renderer changes.

The P2 finding is valid. Before production edits, real spawn tests failed in
both cooperative chart-release and stuck-chart cases. The former yielded a
canceled result and rendered distribution/IQR/histogram/trend in both workers;
the latter remained blocked beyond five seconds. The old completed-future
tests did not prove active cancellation; this receipt supersedes that part of
the earlier readiness table. Baseline pool/exporter sources and six full
synthetic exports were captured from the review base in
`scratchpad/codex/1130-cancel/` before production edits, without another worktree.

Worker initialization receives the shared event through spawn `initargs`.
Workers observe it without emitting parent-owned Qt cancellation signals.
Already-canceled jobs skip summary rendering. Pool errors stop workers before
replaying remaining groups serially; cancellation prevents that replay.
Worker-raised `TimeoutError` remains a failure eligible for serial fallback.

Python 3.11 lacks public executor worker termination. Cleanup snapshots this
executor's private process/manager references before nonblocking shutdown;
joins and termination touch only those processes. This narrow compatibility
dependency requires attention when changing supported Python versions. The
current chart can finish cooperatively; an unresponsive chart can be forcibly
stopped after the grace period. As with any process timeout, kernel scheduling
and uninterruptible OS waits are outside a strict wall-clock guarantee.

The real spawn regression checks both release-at-chart-boundary and a chart
that stays blocked: no later chart types, no results replayed after cancel,
collector return within five seconds, all child exit codes collected and the
executor manager thread stopped. Cooperative workers must exit with code zero.
Two intermediate test runs were interrupted because test teardown tried to
notify a multiprocessing Event after killing its waiters. The trace identified
the test's release event, not production cleanup. A filesystem release marker
removed that harness deadlock; no crash was induced.
