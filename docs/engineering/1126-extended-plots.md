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
remaining groups to serial without duplicating writes. Cancellation and early
exit cancel queued futures and shut down the executor in a `finally` block.
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
