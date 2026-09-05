# CSV analytics/export performance — Issue #1028

Status: first-pass work in progress. Parent #918 remains open.

## Authority and fixed comparisons

- Coordinator: PERF-1028-COORDINATOR, parent ORCH-METROLIZA.
- Requested route: GPT-6 Astra / Ultra; actual runtime model and reasoning: not visible.
  No routing/client settings changed. One implementation writer.
- Read-only specialists: PERF-1028-RENDER-DIAG (render/export/history) and
  PERF-1028-MEMORY-DIAG (SQLite/conversions/native inventory); no worker execution of
  tests, builds or benchmarks, no recursive delegation.
- A: `9e01a2b7ceb796e06c845efad599af6f298a98af`.
- B and verified actual work base: `77e398375e5277858110c746a428d13535db6a59`,
  tree `c7679e12abfc863fee420a16da4a66ebc3e70e1e`.
- Branch: `perf/1028-csv-analytics-export`, PR base explicitly `develop`.
- A/B harness and dependency manifests are identical. A→B changes eight
  selected-import implementation/test paths; #1014/#1017 is not reopened.
- At initial preflight, open PRs #972/#973/#1025/#1026/#1027 did not own this pipeline.

## MUST

Measure A→B separately from B→C; retain raw interleaved samples and two independent
primary blocks. Preserve every output, numerical definition, selection/approval,
SQLite transaction, cancellation, security and offline contract. Profile separately.
Keep at most five measured hotspots and one coherent optimization. Validate final
bytes with applicable complete CI/Qt/coverage/static/security/release gates and
fresh independent review. Leave the PR Draft/open/unmerged.

## SHOULD

Remove proven unnecessary work first. Aim for roughly 30% end-to-end improvement
or material memory reduction; retain smaller changes only with repeatable evidence.

## DEFERRED

New dependencies, ABI/kernel, migration/index, cross-session cache, process pool,
source/import/enrichment/UI/planner changes, workflow or threshold changes, Ready,
merge and release are outside this shipping scope. Any native/library/index spike
requires the follow-up contract in #1028; none has been selected.

## Reproduction protocol (declared before candidate changes)

`scripts/benchmark_csv_pipeline.py` executes the real workflow with the existing
headless logger/PDF/Qt stubs from `benchmark_paths.py`. Its primary timing has no
writer wrappers, profiler or coverage. It measures the complete workflow call;
the separate process duration also includes imports, fixture preparation, result
serialization and artifact hashing. These boundaries differ from a full GUI run.

The fixed interpreter is CPython 3.11.16, Linux x86_64, on a Xeon W-10855M with
six physical/twelve logical cores and 64 GiB RAM, Omarchy 4.0.2, balanced power
profile. One resolved environment and exact sibling SHAs are reused for A/B/C.
Agg, one BLAS/OpenMP/NumExpr thread, hash seed 0, and a shared dedicated font cache
within each block pair are fixed. No OS-cache dropping or machine setting changes.

Cases use seed 7 and all five chart flags (time series, histogram, violin, box,
groupstats), full dashboard detail, XLSX and separate parameter sheets:

| Case | Rows | Numeric columns | Selected metrics | Manual groups | Repetitions |
|---|---:|---:|---:|---:|---|
| Existing CI small | 300 | 4 | 4 | 3 | 7 per variant/block, 2 blocks |
| Medium-wide | 30,000 | 12 | 4 | 12 | 2 per variant, lower confidence |
| Bounded large | 150,001 | 4 | 4 | 12 | 2 per variant, lower confidence |

Each independent block starts with a fresh-process warmup per variant, retained
but excluded from the measured median. Variant order alternates. Larger cases
contain missing/invalid numeric values, a 997-value categorical column and an
untrusted formula-like reference. The primary case remains exactly the CI fixture.
Each child has a 600-second timeout; the declared resource planning bound is 8 GiB
RSS. Oversized/unfinished cases must be reported rather than silently replaced.
Same-session repeated requests are separate observations, not fresh-process samples.

Both small and large currently use SQLite: the loaders unconditionally call
`_load_tabular_files_into_sqlite`. The old 150 MiB/150,000-row predicate is unused.
The large case crosses four 50,000-row ingestion batches; the preview is bounded
at 5,000 rows. Actual storage diagnostics and cleanup must be recorded.

An initial A/B block ran while a user game used approximately 630–670% CPU.
Those samples are preserved as contended exploratory evidence. This load is a
confounder and does not establish a quiet-machine performance result. No tests,
builds or other worker benchmarks ran concurrently.

Example (run serially with the same interpreter):

```bash
python scripts/benchmark_csv_pipeline.py --compare A=/path/to/A B=/path/to/B \
  --case small --output benchmark_results/1028/ab-small
python scripts/benchmark_csv_pipeline.py --compare B=/path/to/B C=/path/to/C \
  --case small --output benchmark_results/1028/bc-small
python scripts/benchmark_csv_pipeline.py --worker --repo /path/to/B --case small \
  --profile --output benchmark_results/1028/profile-B
```

## Historical signal and attribution limits

Direct raw job-log reads confirmed the four previously reported failing advisory
CSV comparisons: 5.305036, 7.101278, 8.694528 and 7.135517 seconds. Successful job
conclusions do not make those comparisons pass. The stages are inclusive/progress
intervals, not a CPU profile; notably the writer wrapper reported zero close time.

The stored 4.298208-second baseline originated in
`810ce7992e003a29ace7d9443c0c488e6dcc70f6`. That harness had no manual grouping
and `groupstats=False`, with different plotstats/groupstats sibling SHAs. It is an
unequal-workload historical baseline, so its ratios cannot establish a #1017
regression. Controlled fixed A→B is still required. Historical complete dependency
resolution and hardware are unavailable; no reconstruction is claimed.

## Artifact parity contract

`scripts/compare_csv_pipeline_artifacts.py` reads every XLSX ZIP part and all
worksheet cells/types/formulas, checks offline asset references, and compares HTML
and assets exactly. Only XLSX creation/modification timestamps and the temporary
SQLite diagnostic path are normalized. This normalization was established on A/B
before candidate changes: the primary A/B HTML and all other XLSX parts matched
byte-for-byte. No visual or numerical tolerance is relaxed; PNG bytes must match.

## Results and measured scope

The [first public checkpoint](https://github.com/hexafe/metroliza/issues/1028#issuecomment-5554520956)
preceded production edits. Compact raw timings and environment identity are in
[`perf_csv_pipeline_1028.json`](perf_csv_pipeline_1028.json).

Initial contended A/B medians: A 14.783197 s, B 14.595880 s; median RSS 214,832 and
214,834 KiB. This does not show a large feature regression, but host contention
limits attribution. Single exploratory B probes: medium 113.341565 s / 465,484 KiB;
large 291.107645 s / 1,224,484 KiB. Both retained all rows, ten sheets, twelve
dashboard charts and successfully cleaned the actual temporary SQLite store.

Separate cProfile on small B (23.87 s instrumented; overlapping inclusive spans):

| Rank | Cost | Observation / decision |
|---|---|---|
| 1 | Histogram preparation: 48 calls, 10.22 s; fitting nested 10.02 s | Remove unsupported grouped-PNG work and reuse identical immutable table rows |
| 2 | Dashboard distribution rendering: 12 calls, 6.02 s | Keep distinct image settings and all images; reject naive image sharing |
| 3 | Groupstats: four calls, 2.35 s | Already reuses analysis and prepared metric data |
| 4 | pandas writes 0.52 s; workbook close 0.27 s | Retain all sheets/cells; larger writer work remains a follow-up |
| 5 | SQLite ingestion 0.086 s; workbook grouping 0.072 s; finite coercion 0.031 s | Small-case costs do not justify an index or conversion rewrite |

The candidate changes three production files: the workbook chart helper bypasses
an unavailable grouped PNG operation; the plotstats adapter stores at most 64
immutable table entries / 8 MiB of retained input-and-row payload; the workflow
owns a separate context per request. A lookup may transiently create one bounded
input snapshot. Complete float64 input bytes preserve order and signed zero;
hexadecimal limits distinguish positive/negative zero. The fixed table computation
uses full fitting and default distribution settings; render settings and titles
are applied outside the reused result. Failed/unavailable results are not cached.
Context reset and buffer clearing run on every exit, including nested requests.
Source verification and publication/cancellation checks remain on the original path.

Focused evidence so far: 55 adapter/workbook/cache/comparator tests, 122 adjacent
tabular/industrial/workflow/security tests, then 17 cache/comparator/C901 tests after
the signed-zero key refinement; full Ruff passed. Exact candidate performance,
full final-byte CI-equivalent validation, independent review and remote CI are pending.

## Candidate observations (provisional until the full matrix completes)

Small B→C, two blocks of seven fresh-process observations each: B median
15.718314 s (MAD 0.668372, IQR 1.687535), C 11.990279 s (MAD 0.168196,
IQR 0.308707), a 3.728035 s / 23.72% reduction. Median peak RSS is effectively
unchanged: 214,802 → 214,946 KiB. Median whole-process duration is
18.015192 → 14.287146 s. This is below the 30% planning target and remains
contended-host evidence, not quiet-machine proof.

A separate three-sample cache ablation retained the grouped-PNG bypass but disabled
cache admission in an isolated, unshipped worktree. Its median was 13.879835 s
versus 11.792553 s with the cache; all three paired observations favored reuse.
This supports retaining both related changes. The ablation patch is preserved;
its cache-disabled constant is not in the shipping branch.

The separate candidate profile reduced histogram payload builds from 48 to 24
and standalone table computations from 24 to 12. Candidate instrumented inclusive
spans were 4.30 s for payload builds and 2.35 s for standalone table calculations;
these are diagnostic counters/timings, not the claimed speedup.

The next rendering opportunity is in the pinned plotstats grouped artifact API:
it still calculates tables while constructing dashboard plots even when the
caller only uses the figure. A future library change could expose explicit
artifact requirements or reusable immutable results. That needs a scoped
follow-up contract and a measured full-call comparison, including conversions,
fallback, cancellation and Windows packaging; no dependency change ships here.

## Native and storage inventory

The existing optional bridges cover CMM parsing, group-stat numeric coercion,
comparison bootstrap, distribution Anderson-Darling work and chart rendering.
The CSV pipeline measurements loaded none of these extension modules. The pinned
groupstats workbook result reported the Python backend; rendered PNGs used Agg.
CMM parsing is outside CSV chart preparation. SQLite query execution remains in
the existing sqlite3/store path, and XLSX writing uses the existing XlsxWriter
integration. No profile evidence justified a new kernel, writer library, process
pool or scratch index spike. No index is proposed without EXPLAIN evidence.

The larger pipeline still materializes full data for its complete Table Data and
parameter-sheet contract. Replacing that with global XlsxWriter constant-memory
mode would risk pandas column-oriented writes, tables, merges and chart ranges;
it was not attempted. Peak memory must be evaluated independently from the small
CPU improvement. These observations do not constitute a repository-wide audit.

## Independent review correction, pass 1

The independent reviewer identified a missing actual high-cardinality/cache-boundary
case and an overly broad diagnostic-path normalization in the comparison tool.
The latter now recognizes only the store-created Diagnostics context field;
a literal matching fragment in ordinary user cells remains significant, with
an adversarial test that changes only the relevant literal content.

Before running the additional case, declare 600 rows / four numeric metrics /
24 actual manual groups, two fresh-process samples plus one warmup per B/C variant,
the same full output/chart flags, a 600-second child timeout and the existing
8 GiB planning bound. This is lower-confidence supplemental correctness evidence,
chosen to exceed the 64-entry cache boundary, not a replacement primary workload.
A separate instrumented run records actual cache admissions and cleanup.
The benchmark driver adds only this case-catalog entry; original case settings and
worker/controller functions are unchanged. Original and extended driver hashes
are retained in the compact receipt. Production bytes remain frozen.
