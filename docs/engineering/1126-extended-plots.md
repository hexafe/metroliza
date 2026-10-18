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
