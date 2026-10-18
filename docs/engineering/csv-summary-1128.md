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

Implementation and local equivalence checks pass. Acceptance requires the
MUST-to-evidence record below; the coordinator does not claim independent review, CI, mergeability
or release readiness. Rollback is a local revert of the bounded implementation;
no persisted source-data format change is planned.

## Implementation and preserved contracts

Implementation commits: `042071ea` and `f45ccd19` (the final evidence-only
commit retains the production source bytes from `f45ccd19`). No remote mutation, additional Git worktree, rebase or reset was
performed. The base source was archived from the exact base commit into scratch;
it is an immutable measurement reference, without a Git checkout or native build.

- `tabular_xlsx_writer.write_tabular_dataframe` bulk-writes ordinary columns with
  XlsxWriter. pandas supplies the installed header policy; complex dtypes and
  lightweight Diagnostics payloads retain their original writers. Missing values,
  infinity strings, datetime formats, column order and literal formula/URL safety
  remain unchanged. No `constant_memory` change was introduced: workbook chart
  data can be written out of row order, so cells still remain in memory.
- `build_histogram_stats_tables` computes full-data tables in input order using
  at most three joined threads and three pending jobs for grouped inputs of at least 5,000 values.
  Context propagation retains request-local reuse across dashboard and workbook;
  locking preserves the cache's existing 64-entry/8 MiB accounting. Submission
  failure falls back to serial computation after joining started workers. Failures
  and request exit release cache state; no Qt worker process is introduced.
- `full_data_violin` uses Matplotlib's covariance, Scott bandwidth, 100 density
  coordinates and reduction order. A one-dimensional covariance dot product
  becomes scalar multiplication. Every finite observation remains in the KDE.
- Matplotlib/pyplot image generation remains serial because it shares global
  renderer state. The SHOULD for parallel work is applied to independent numeric
  statistics, without adding process-spawn/frozen-application behavior.
- No new sampling or decimation was added. Existing dashboard sampling and its
  full-data statistics are preserved exactly, including existing chart notes.
- Benchmark instrumentation measures the complete bulk writer without counting
  its pandas header twice. It now observes actual pandas XlsxWriter `_save`;
  the old lazy-pandas proxy patch never observed close and reported zero. Overall
  `workbook_write` remains comparable; the old close substage is unavailable.

## Equivalence evidence

Base exports were captured from the pre-change source at 10,000 and 100,000
rows × 8 columns using the benchmark's synthetic RNG seed 7 and three manual groups.
Artifacts and scripts are under:

`/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1128/`

At **both sizes**, `compare.py base-proof-N after-proof-N` returned exit 0:

- Every XLSX package member is identical, including sheet order, cells, types,
  number formats, formulas/text, chart data and chart ranges. All 20 chart/image
  members are byte-identical. Normalization is limited to workbook creation/
  modification timestamps and the temporary SQLite path in diagnostic strings.
- Complete dashboard manifests match, including chart traces/layouts/images,
  groupstats and full-data histogram statistics. Only `summary.generated_at` and
  the store-created diagnostic's temporary SQLite path are normalized.
- Dashboard HTML and offline runtime assets match. HTML normalization covers
  generated timestamps and the temporary SQLite path, not measurement values.
- Results are recorded in `after-proof-10000/comparison.json` and
  `after-proof-100000/comparison.json`. Proof captures are not timing samples;
  the base 100k proof was profiled and therefore has instrumentation overhead.

The new tests compare all KDE density coordinates/statistics against the original
Matplotlib calculation, compare rendered PNG bytes, compare pandas cells/types/
formats and XML, exercise full-data statistics with extreme observations, and
verify worker order, bounded cache reuse, failure cleanup and thread exhaustion.
Existing request-cache tests cover changed data/limits, signed zero, cancellation,
entry/byte bounds and unavailable optional statistical backends.

## Exact local validation

At implementation source `f45ccd196a40ef9fb1085355b416c6e1bfcd753a`, this
command returned **489 passed in 131.26 s**, exit 0 (13 related/required files, not the whole suite):

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_csv_summary_export_equivalence.py tests/test_hexafe_plotstats_adapter.py tests/test_csv_pipeline_performance.py tests/test_industrial_analytics_dashboard.py tests/test_industrial_analytics_workbook_charts.py tests/test_industrial_analytics_workflow.py tests/test_benchmark_paths.py tests/test_tabular_analytics_service.py tests/test_industrial_analytics_workbook_safety.py tests/test_csv_summary_utils.py tests/test_complexity_ratchet.py tests/test_bug_sweep_coverage.py tests/test_security_audit.py
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m ruff check .
git diff --check
```

Ruff and whitespace checks pass. No complexity budget or Bandit baseline changed.
SQL f-string text and line locations in `benchmark_paths.py` and
`tabular_analytics_service.py` were compared against the base and are unchanged;
new helpers remain below the complexity threshold. New files already match
`output-rendering-runtime` (#981), `industrial-and-tabular-workflows` (#982),
`test-and-audit-code` (#985), and documentation (#975) ownership rules.

Preserved adverse receipts: an initial helper invocation could not find
`/usr/bin/time` (exit 127; not counted as a sample); it was replaced by a scratch
`resource.getrusage` wrapper. The first integrated check had 157 passes and one
Diagnostics payload failure, fixed with a regression test before the green run.
A mistyped workbook test filename caused collection exit 4, with zero tests run;
the corrected command above uses `test_industrial_analytics_workbook_safety.py`.
A scratch comparison observer was interrupted because an overly broad path regex
scanned PNG base64; the bounded temporary-path regex then completed both
comparisons. These are harness/iteration receipts, not successful product trials.

## Review, limits and rollback

Internal scope/evidence audit: bounded source diff, full-data equivalence and
failure/cleanup tests pass. Actual coordinator model/reasoning remain **not
visible**. No subagents were used. After the user's updated instruction, relevant
`codex-corrections` lessons T02/T05/T13/T14 and W06/W07 were checked; no archived
permission or historical acceptance was imported into this task.

Independent exact-head review: pending external Claude Code. Hosted CI, Windows
source execution, frozen/packaged EXE behavior, clean-machine operation and visual
interaction in Excel/browser were **not verified**. No Windows or release claim
follows from Linux artifact equality. Mergeability and review threads were not
queried; no READY FOR MERGE verdict is issued.

Open risks: XlsxWriter retains workbook cells, so large-export RSS remains a
scaling concern. Shared-host load affects wall times; measurements below are
observations, not a controlled isolated-machine guarantee. Installed numerical
packages are reused across baseline/candidate; native acceleration and packaging
were not changed or separately certified. Rollback is a revert of `f45ccd19` followed by `042071ea`,
with no source-data migration or format change.


## MUST-to-evidence and review record

| Requirement | Evidence | Local status |
| --- | --- | --- |
| Workbook/dashboard content and full-data statistics | Base/candidate artifacts at both sizes; complete normalized XLSX/manifest/HTML comparisons; numerical and PNG equivalence tests | PASS at `f45ccd19` |
| Before/after 10k and 100k × 8, median of three with load/RSS | Accepted sample table below; raw benchmark JSON/CSV and resource receipts in scratch | See measurements below |
| Focused and required checks, no budget/baseline weakening | 489 passing tests, Ruff, whitespace checks; unchanged complexity/Bandit configuration and SQL expression locations | PASS |
| Bound processing and preserve cleanup/offline publication | Three threads and three pending jobs; joined success/failure paths, request cache bounds, serial fallback; existing workflow tests and offline assets | PASS |
| Local scope, commits and confidentiality | Current branch only; synthetic RNG fixture; no remote mutations or real data | PASS |

Internal findings: no unresolved P0/P1 identified. One P2 found before final
readiness, unbounded queued group jobs, was fixed in `f45ccd19` with a 100-group
regression test. Worker computation errors remain distinct from thread-start
failures. The initial 487-test/benchmark/artifact receipts remain in scratch;
source changes were followed by 489 tests and fresh artifact/performance evidence.
No independent reviewer verdict is implied.

Routing feedback: bounded integration remains the proposed class for comparable
behavior-preserving work, with explicit pending-job and cache limits included in
the execution packet. External orchestrator routing/review remains pending.

Remote-operation ledger: read-only Issue fetches for #1128 and #1124; local
commits only. No push, PR, review request, merge, branch retirement, deployment,
promotion, migration, release or publication was performed.

## Measurement method and environment

Python 3.11.16, pandas 3.0.6, NumPy 2.4.6, SciPy 1.17.1, Matplotlib 3.11.2,
XlsxWriter 3.2.9, hexafe-plotstats 0.1.0a1 and hexafe-groupstats 0.1.0rc3;
Linux x86_64. These are the observed shared-venv versions, not a new package
installation or Windows certification. `environment.json` records the resolved
interpreter and package versions. No repository-local `.so`, `.pyd`, `.dll` or
`.dylib` was found, including ignored files.

All timing samples use fresh Python processes, the same requested interpreter,
synthetic CSV fixture, and the benchmark's headless stubs. They are not labelled
cold-cache runs: the font/OS caches were not cleared. Test runs and artifact
comparison/profiling were completed before the accepted final timing batch.
Other agents still load this host. Peak RSS is Linux `RUSAGE_SELF.ru_maxrss`,
converted from KiB to MiB; the scratch wrapper records 1/5/15-minute load averages
before and after each process. Each reported timing/RSS is the median of three.
Stage medians are independent and do not necessarily sum to the total. In
particular, `dashboard_manifest` is included in `chart_generation`.

Exact timing command, with `N` = 10000/100000 and `R` = 1/2/3:

```bash
ulimit -c 0
unset QT_QPA_PLATFORMTHEME
export QT_QPA_PLATFORM=offscreen
export PYTHONPATH=src:.
TASK=/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1128
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python "$TASK/timewrap.py" "$TASK/after-$N-$R/resource.json" scripts/benchmark_paths.py --scenarios csv_summary_export_path --csv-rows "$N" --csv-columns 8 --output-dir "$TASK/after-$N-$R"
```

`run_baseline.sh` used the same CLI arguments with `base-N-R` outputs. For its
100k timing samples, `timewrap.py` selects the immutable `git archive` reference
from base `82f8f576`; the 10k samples ran before source edits. The accepted final
candidate samples use `f45ccd19`. Reference source files remain unedited; only synthetic outputs and temporary
application state are created.

Base/candidate artifact capture command, before and after implementation:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python "$TASK/capture.py" "$TASK/after-proof-$N" "$N"
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -u "$TASK/compare.py" "$TASK/base-proof-$N" "$TASK/after-proof-$N"
```

The final comparison commands returned exit 0 at both sizes. The immutable base
artifacts were captured first; no separate Git worktree was created. Initial
`042071ea` candidate measurements/proofs are retained in `initial-042071ea/` and
are superseded by the final `f45ccd19` evidence below. `summary.json` holds the
accepted samples' statistics, raw run totals, load readings and fixture hashes.


## Accepted measurements at `f45ccd19`

| Rows | Stage | Before median | After median |
| ---: | --- | ---: | ---: |
| 10,000 | total | 29.87 s | 21.78 s |
| 10,000 | chart_generation | 16.94 s | 14.13 s |
| 10,000 | dashboard_manifest | 16.09 s | 13.43 s |
| 10,000 | workbook_write | 10.19 s | 5.34 s |
| 10,000 | workbook_sheet_writes | 4.63 s | 1.11 s |
| 10,000 | Peak RSS | 312.2 MiB | 308.4 MiB |
| 100,000 | total | 134.38 s | 75.99 s |
| 100,000 | chart_generation | 52.00 s | 33.12 s |
| 100,000 | dashboard_manifest | 49.76 s | 31.06 s |
| 100,000 | workbook_write | 69.79 s | 36.19 s |
| 100,000 | workbook_sheet_writes | 37.78 s | 9.07 s |
| 100,000 | Peak RSS | 1007.6 MiB | 1015.0 MiB |

| Rows | Base median load (1/5/15 min) | Candidate median load (1/5/15 min) | Base 1-min range | Candidate 1-min range |
| ---: | --- | --- | --- | --- |
| 10,000 | 9.86 / 7.08 / 4.65 | 8.14 / 7.45 / 6.87 | 7.82–9.97 | 7.38–9.22 |
| 100,000 | 8.43 / 7.41 / 5.92 | 5.71 / 6.69 / 6.67 | 6.44–8.81 | 4.84–7.38 |

Observed total elapsed reductions are 27.1% (10k) and 43.5% (100k). Host load was
lower in the candidate phase, so these are shared-host observations, not an
isolated-machine attribution or guaranteed speedup. All three final 100k runs
were 75.31 / 76.85 / 75.99 seconds. Workbook sheet-write medians include the full
bulk writer; the baseline close field was unobserved (reported zero), while the
new close medians are 1.89 s / 18.70 s at 10k / 100k.

**Memory is not solved:** 100k RSS changed from 1007.6 to 1015.0 MiB. The retained
workbook cells still dominate; no streaming mode was enabled that could change
chart range/cached-value semantics. There is no claim of a 100k memory reduction.

Final local status: implementation, required focused checks, representative
measurements and equivalence evidence complete. Independent review and the
unverified platform/CI gates listed above remain external responsibilities.

## PR #1133 independent-review corrections

Authority: the external orchestrator's review-correction packet supplied in the
current session; starting HEAD `4c564a2e`. Whole-PR routing remains BOUNDED
INTEGRATION, coordinator only; runtime model/reasoning not visible. Current branch
and the PR comparison base `origin/integrate/2026.09-rc1-into-develop` are retained.
The earlier local-complete verdict above is historical and superseded for the
two reviewed defects. The correction packet, exact source identity, red/green
receipts and new measurements live under `scratchpad/codex/1133-review/` beside
the original `1128/` evidence directory.

MUST: reproduce each defect before its fix, preserve complete artifact semantics
and performance, rerun all original related/required checks, and commit each
finding separately. SHOULD: keep bulk writes and bounded per-column allocations.
DEFERRED: Windows/frozen-build/manual Excel and hosted CI evidence remains owned
by the external orchestrator; remote writes are forbidden.

### P1: oversized text stops bulk column writing

`p1-red.log`: four oversized ASCII/Unicode object/string cases fail because the
sentinels after the long cell disappear; both 32,767-character boundary cases
pass. Each test creates the pandas reference workbook before calling the bulk
writer. The reference truncates only the long cell and retains both sentinels.

`_column_values` now truncates string values to 32,767 characters before the bulk
write, matching XlsxWriter's per-cell behavior and retaining shared-string order.
Unexpected bulk-write return codes raise an error rather than publish a partial
success. Existing infinity conversion moved unchanged into the helper to keep
complexity bounded. No workbook options or literal formula/URL policy changed.

`p1-green.log`: **15 passed, 14 deselected**, including all prior bulk-writer
cases, all six text cases and both injected return-code failures. Cells, types,
formats, styles and every XLSX package member except core timestamps match pandas.
Focused Ruff and whitespace checks pass. Complete validation and fresh benchmark
results will be recorded after both finding commits.

### P2: object-dtype NumPy booleans become Excel numbers

`p2-red.log`: **3 failed, 1 passed**. NumPy booleans mixed with `None`, `pd.NA`
or `NaN` are written as numeric cells (`1`/`0`, type `n`) instead of pandas'
boolean cells (`TRUE`/`FALSE`, type `b`). The `pd.NaT` case already selects the
complex-type pandas fallback and passes. All reference workbooks were produced
before changing this boolean conversion.

Boolean columns now convert nonmissing values to Python `bool` and missing values
to empty strings before bulk writing. This covers object, NumPy and nullable
boolean columns without changing the frame. `p2-green.log`: **19 passed,
14 deselected**, with exact cells/types/styles and XLSX-part equality against
pandas for all four new cases and the previous bulk-writer fixtures. Focused Ruff
and whitespace checks pass. No baseline, budget, package, native or policy change.
