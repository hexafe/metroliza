# CSV analytics/export performance — Issue #1028

Status: measured candidate in Draft PR #1029. Exact-final-head validation/review receipts are maintained on the PR. Parent #918 remains open.

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
six physical/twelve logical cores and 64 GiB RAM, Omarchy 4.0.2; the initial power-profile snapshot was balanced.
Continuous profile/frequency telemetry was not collected. One resolved environment and exact sibling SHAs are reused for A/B/C.
Agg, one BLAS/OpenMP/NumExpr thread, hash seed 0, and a shared dedicated font cache
within each block pair are fixed. No OS-cache dropping or machine setting changes.

Cases use seed 7 and all five chart flags (time series, histogram, violin, box,
groupstats), full dashboard detail, XLSX and separate parameter sheets:

| Case | Rows | Numeric columns | Selected metrics | Manual groups | Repetitions |
|---|---:|---:|---:|---:|---|
| Existing CI small | 300 | 4 | 4 | 3 | 7 per variant/block, 2 blocks |
| Medium-wide | 30,000 | 12 | 4 | 12 | 2 per variant, lower confidence |
| Bounded large | 150,001 | 4 | 4 | 12 | 2 per variant, lower confidence |
| Review boundary case | 600 | 4 | 4 | 24 | 2 per variant, lower confidence |

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

A user GameThread process was observed at approximately 630–674% CPU during the session.
Original local timings are treated as contended-host evidence. An optional repeat after
observed GameThread exit was stopped when external power-profile drift was found. The original confounder prevents
a quiet-machine claim. No local tests, builds or other worker benchmarks ran concurrently.

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

## Attribution A→B, separately from candidate improvement

The fixed A/B comparisons use identical fixtures, options and resolved dependencies.
The observed direction changes between the two small blocks. The medium and large
cases have only two samples per variant, and host load is uncontrolled.

| Case | A median seconds | B median seconds | Observed B minus A | Samples per variant |
|---|---:|---:|---:|---:|
| small contended | 14.783197 | 14.595880 | -1.27% | 14 |
| medium-wide | 112.143750 | 114.181714 | +1.82% | 2 |
| bounded large | 295.391484 | 309.440864 | +4.76% | 2 |

Attribution: **inconclusive at the few-percent scale; the primary workload does not
reproduce a material selected-import regression**. The historical workload/pin
mismatch is confirmed, but its contribution cannot be quantified without the old
environment. Do not label the larger observed A/B difference zero or dismiss it.
The separate small B profile contains no runtime calls in the five production
files changed by A→B; it excludes module-import initialization. Whole-process
measurements, including imports/setup, are retained separately in JSON.

## Candidate B→C measurements

The small B/C experiment is independent of the earlier A/B experiment; its B median
must not be substituted into A→B attribution. Parentheses below are MAD in seconds,
not confidence intervals. Raw samples, IQR, min/max, process durations, fixture hashes,
backend identity, peak RSS and output identities are retained in the compact JSON.

| Case | B median (MAD), seconds | C median (MAD), seconds | Time reduction | Peak RSS B→C, MiB | Samples per variant |
|---|---:|---:|---:|---:|---:|
| small contended | 15.718314 (0.668372) | 11.990279 (0.168196) | 23.72% | 209.77 → 209.91 | 14 |
| medium-wide | 114.181714 (1.469826) | 97.164397 (2.699797) | 14.90% | 454.61 → 455.91 | 2 |
| bounded large | 309.440864 (8.799697) | 251.104338 (1.224237) | 18.85% | 1195.38 → 1200.07 | 2 |
| 24-group review case | 75.405182 (1.392909) | 58.389874 (0.344148) | 22.57% | 219.32 → 221.90 | 2 |

Original contended small block medians independently favor C: 16.204504→12.154230 s and
14.438391→11.817838 s. The original contended small gain is 23.72%, below the 30% planning target.
All original observations remain available. A later optional extension was stopped
incomplete after discovering an externally changed low-power profile (AC online,
CPU0 about 1.1 GHz at 22:19:57 UTC). Its partial 25–26 s observations are retained
separately and excluded from comparison medians. No machine settings were changed. There is **no material memory improvement**: the large request retains
approximately 4.7 MiB more at peak, consistent with the bounded input snapshots.

Fresh-process samples run after font/library-cache warmups. They are process-cold,
not OS-cache-cold. Whole-process medians include imports, fixture setup and receipt
hashing; the primary workflow timer includes CSV/SQLite load through complete
HTML/XLSX publication. No cache-dropping or machine-wide changes occurred.

Separate same-process request times (request 0, 1, 2) are:
- B: 8.834171 s, 7.932339 s, 8.386767 s.
- C: 6.945657 s, 6.402642 s, 6.509871 s.

These supplemental requests occurred near the external host-state transition;
they demonstrate repeated-request behavior and are not an isolated cache speedup.
Their RSS values are cumulative process high-water marks, not live retained-memory
measurements. All three requests were compared semantically; caches clear between
requests. A real test also changes input data, limits and chart selection at the
same source path across successive requests.

## Ranked small-workload diagnosis and scope

Separate cProfile on B took 23.87 s; inclusive spans overlap and must not be summed
or used as speedup evidence. The first Issue checkpoint preceded production edits.

| Rank | Measured hotspot | Mechanism, risk and decision |
|---|---|---|
| 1 | 48 histogram payloads, 10.22 s; fitting nested 10.02 s | Unsupported grouped PNG fits every group then returns no image; tables repeat across outputs. Bypass that dead end and reuse immutable table rows within a bounded request. |
| 2 | 12 dashboard distribution renders, 6.02 s | Keep every image. Naive PNG sharing would change sizes/styles/extrema/sampling seeds, so it was rejected without shipping an experiment. |
| 3 | Four groupstats calculations, 2.35 s | Analysis and prepared metrics already reuse their results. No change. |
| 4 | Eight pandas writes, 0.52 s; workbook close 0.27 s | Small-case cost does not justify changing writer contracts. Larger full materialization remains a memory investigation, not a proved allocation diagnosis. |
| 5 | SQLite load 0.086 s; workbook grouping 0.072 s; finite coercion 0.031 s | No small-case evidence for an index or conversion rewrite. Additional actual 12/997-group probes are recorded below. |

Three production paths change: `hexafe_plotstats_adapter.py`,
`industrial_analytics_workflow.py`, and `industrial_analytics_workbook_charts.py`.
The grouped workbook histogram still emits the same editable chart and tables;
only an unavailable artifact attempt disappears. The cache stores at most 64
entries / 8 MiB of retained input-and-row payload. One bounded lookup snapshot may
exist transiently; Python object overhead is additionally bounded by entry count.
Full finite float64 bytes preserve order; hexadecimal limits preserve signed zero.
The table helper has fixed full-fit/default distribution settings and no selectable
compute backend. Titles/render settings are applied outside cached rows. Failures
and unavailable results are not cached. Each nested workflow owns an isolated
context, reset and cleared on every exit. Source verification remains live.

A cache-off ablation, with grouped-PNG bypass retained, had median 13.879835 s
versus 11.792553 s for C (three samples each); all three pairs favored caching.
The cache-disabled experimental constant is not in the shipping branch. Small C
profiling reduced payload builds 48→24 and standalone table calculations 24→12.
The 24-group supplemental case was declared during independent review before
execution; it does not replace the original primary workload. Its separate counter
run reached exactly 64 admitted entries and cleared both contexts to zero entries
and zero payload bytes. The driver extension changes only the case catalog;
original case settings and worker/controller code remain unchanged.

## Full output and adjacent-path proof

The semantic matrix compares all worksheet cells/types/formulas/order, every XLSX
part/chart reference/style/relationship, exact HTML, PNGs and offline assets for
small, medium, large and 24-group B/C; A/B is also checked for the three original
cases. Only XLSX timestamps and the store-created Diagnostics context's temporary
SQLite path are normalized. Literal matching fragments in user cells remain
significant, with a targeted negative test. The earlier broad normalization was
hardened in independent review correction pass 1.

All main cases preserve ten sheets, twelve dashboard plots, eight editable XLSX
charts and eight XLSX images. Complete Table Data rows/columns and literal formula-like
strings are read back; generated hyperlinks remain absent. Representative histogram
and violin PNGs were visually inspected. No visual/numerical tolerance was relaxed.

Representative large outputs: HTML 7,977,393 bytes, offline Plotly asset 3,598,158
bytes, XLSX about 36,521,020 bytes (a few metadata/compression bytes vary). Every
record reports actual SQLite creation and successful cleanup; the large load
crosses four ingestion batches. There is no reduction of requested output work.

Adjacent measurements use the existing report/export and industrial harnesses,
including their writer wrappers, so they are diagnostic comparisons rather than
the primary uninstrumented speedup evidence. Three samples plus a warmup per variant;
query probes hold 30,000 rows fixed and vary actual group cardinality with empty search.

| Adjacent case | B median seconds | C median seconds | C minus B | Review threshold crossed |
|---|---:|---:|---:|---|
| report | 0.199503 | 0.202665 | +0.003162 s (+1.59%) | False |
| industrial | 13.081902 | 13.685658 | +0.603756 s (+4.62%) | False |
| groups-12 | 0.978305 | 0.989909 | +0.011604 s (+1.19%) | False |
| groups-997 | 0.944943 | 0.959656 | +0.014714 s (+1.56%) | False |

The industrial sequence straddled GameThread exit and had strongly falling raw
times; its +4.62% / +0.604 s aggregate median is inconclusive. The unchanged
dashboard stage varied more than the workbook stage. A planned post-game repeat
was not reached before external power-profile drift stopped the optional extension.
The review criterion is a repeatable regression over both 5% and 0.1 s; these
criteria do not modify CI thresholds. This remaining uncertainty is explicit. Adjacent XLSX/dashboard artifacts are compared
semantically. The standalone report probe initially failed before measurement due
to the harness stub's parent-package import order; the preserved retry loads that
namespace before installing the same headless stub for both variants. No production
fix or measured sample was discarded for that setup failure.

## Native inventory, validation and next opportunity

Optional existing bridges cover CMM parsing, group-stat coercion, comparison
bootstrap, distribution Anderson-Darling work and chart rendering. None loaded in
these CSV measurements: observed groupstats backend is Python and PNG rendering is
Agg. SQLite execution and XlsxWriter remain on existing paths. No new native/library,
index, process-pool or cross-session-cache spike was justified or shipped.

Next highest-value opportunity: avoid the remaining grouped-artifact statistics
that are computed while only its Plotly figure is consumed. First evaluate reuse
of already returned immutable rows under a complete computation contract; if the
pinned API cannot express that, propose a narrow upstream artifact-selection API.
Any dependency/native/index follow-up must quantify end-to-end benefit including
conversion/startup, exact semantics/fallback/invalidation/cancellation, Windows
packaging, maintenance/license/security cost and rollback. Writer allocation and
row-oriented streaming deserve a separate large-case profile; global constant-memory
mode is unsafe without proving pandas write order, tables/merges and chart references.

Focused cache/workbook/workflow/export/security tests, real successive-request
checks and artifact mutation tests are included. Current full CI runs include
unit tests, nine isolated appended Qt shards, combined/canonical coverage ≥80%,
Ruff/compile/type/architecture/C901, release metadata/hygiene, secret scanning and
pinned-sibling security audit. Exact-final-head local/remote results and fresh
independent review are recorded on PR #1029 rather than self-referencing this file's
commit. Required checks come from effective branch rules, not a green workflow
summary. The same prior candidate head had advisory CSV push PASS 4.477469 s and
PR FAIL 6.594658 s against the unchanged historical baseline; final raw outcomes
must be reported separately. CMM native execution is verified from its usage log,
not from a successful fallback/skip. Manual packaged/startup lanes remain opt-in;
no packaged executable or release acceptance is claimed.

Evidence is bound to production commit `187ebd694f1e66516fb4a8ccfe272011d68e6216`
and the three unchanged production blob IDs in the compact JSON. Ordinary later
commits hold tooling/tests/evidence. Raw samples/profiles/generated outputs remain
in the durable coordinator checkout under `artifacts/perf-1028`, with hashes in
[`perf_csv_pipeline_1028.json`](perf_csv_pipeline_1028.json). The serial benchmark driver and strict comparator are preserved in git; the
supplemental existing-harness driver remains in durable artifacts with its hash.
Run the primary driver with --case medium, --case large or --case many-groups
and --samples 2 --blocks 1 for the lower-confidence supplemental comparisons. Revert this
PR to restore the original computation; no migration or persistent-cache cleanup
is needed. This is a bounded pipeline audit, not a whole-repository performance audit.


## Review correction 2: measurement provenance guard

GitHub review identified that the original driver labeled working-tree execution
with HEAD/tree without rejecting local edits. The driver now rejects tracked,
staged and untracked changes before imports, checks output placement before any
fixture write, and verifies the same clean HEAD/tree again before publishing a
receipt. The shared driver has its own SHA256, checked again after execution.
Use clean comparison checkouts and external or git-ignored output directories;
the coordinator checkout's untracked artifact directory is not exempted.

Earlier raw measurements are preserved as **unguarded historical receipts**;
the new guard is not retroactive proof. The A/B checkouts and the separately
committed cache-off ablation (`288ec7f7f8547775001b5f4bf47f0bd53c3fc46e`) remain
available. The three measured production blobs were independently reverified as
unchanged, and all saved raw/parity hashes were checked. No measured sample is
relabeled as having run this newer guarded driver. A future guarded repeat on a
stable host is the remaining confirmation task; the first-pass budget does not
permit repeating the entire matrix after this tooling-only correction.

## Native provenance correction under authority #5558038371

The historical results above and their original JSON arrays remain unchanged.
The Ready-time P1 (`discussion_r3943387619`) showed that clean Git status does
not identify ignored importable native binaries. The permanent fail-first test
creates an inert ignored file, proves clean Git status and actual
`PathFinder`/`ExtensionFileLoader` resolution, and requires rejection without
executing or deleting it. All eight root/src and suffix cases failed on the
starting driver at `522f8b36ee570e3ee34593dd062e27f59d63d6c5`.

The supported trust model is a trusted CPython interpreter, standard-library
bootstrap and installed environment, with controlled synthetic benchmark
processes. The guard detects accidental/stale inputs and changes visible at
checkpoints. It is not an OS sandbox, supply-chain/build attestation, malicious
loader defense, transitive shared-library inventory, or atomic protection against
someone changing and restoring files between checks.

The driver rejects checkout-local extension candidates, including ignored files,
root/src packages, namespace directories and symlink aliases. It never removes
build artifacts. A clean separate comparison checkout is the supported route for
local builds. Every existing effective `sys.path` directory is inventoried through
identifier-named package/namespace directories; normal `.so`/`.pyd` and ABI variants
are recognized conservatively. Installed extension records contain a logical
search-root/relative origin, local absolute spelling/resolved target, SHA-256 and
size. Standard native bridge wrapper packages also receive source hashes. The
interpreter has its own content/platform/version/suffix identity; binary source or
build provenance is explicitly not inferred from a filename or the checkout SHA.

The five Metroliza bridges and installed `_hexafe_groupstats_native` are resolved
without importing candidate binaries. An import audit hook rejects an extension
whose resolved origin was not in the initial inventory before native execution,
including explicit `ExtensionFileLoader` calls and nonstandard filename suffixes.
An unidentified explicit `hexafe-groupstats` `rust/target` fallback outside the
inventoried search roots is unsupported and terminates the worker; optional
backend exception handling cannot turn it into a successful fallback receipt.
Non-directory import roots, cyclic directory links and unsupported native loader
or loaded-origin cases also fail closed. The policy does not alter backend
settings. Requested backend environment, availability, imported bridges/extensions
and computational use are separate fields; import is never labelled proof of
application computation.

Before and after each measured request, and before `result.json`, the worker
rechecks source/driver/helper identity, native inventory/content, bridge resolution
and loaded-origin agreement. The selected checkout and shared tooling checkout
both have independently recorded and checked clean Git HEAD/tree identities and
native-build rejection. This includes the actual shared `scripts.benchmark_paths`
source, whose logical root/path/hash is recorded; checking only B and the two C
driver files would omit that executed harness. The legacy five-entry
`native_modules` import summary remains alongside the richer native manifest. A comparison also binds every sample to fixed source,
driver/helper and per-variant native identities. Existing output directories are
refused so a failed run cannot overwrite an earlier valid receipt. A failed sample
never produces a successful aggregate summary. Harmless ignored logs, output and
bytecode caches remain permitted.

Content fingerprinting and checkpoint validation occur outside workflow timing.
`workflow_s` retains raw elapsed wall-clock semantics. The necessary import-time
allowlist check is timed separately in `native_import_guard_s`;
`workflow_excluding_import_guard_s` is only an adjusted diagnostic. Performance
confirmation uses the raw measurement. Process time, setup and peak RSS remain
raw and include guard effects; checkpoint allocations/page-cache effects cannot
be removed by subtracting durations. `provenance_s`, setup and the native receipt's
verification/import counters overlap and must not be added as disjoint costs.
Residual audit dispatch/timer overhead is not claimed to be zero. Profiles remain
diagnostic only.

| Boundary / finding | Permanent regression or evidence |
|---|---|
| Ready P1: ignored executable input despite clean Git | `test_ignored_importable_native_is_rejected_before_execution`, actual Git + resolution, root/src and all current suffixes plus `.so`/`.pyd` |
| Windows suffix case, including `.PYD` and uppercase ABI suffixes | Same root/src rejection matrix plus `test_external_native_suffix_inventory_without_execution`; real Windows resolution without loading inert files, external origin/hash inclusion |
| Installed inventory, same basename, different content | `test_external_native_inventory_detects_drift`, `test_same_named_artifacts_have_distinct_content_identity` |
| Same size/mtime, addition/removal/replacement | `test_external_native_inventory_detects_drift` five mutation modes |
| File/directory links and checkout aliases | `test_native_symlink_identity_and_retargeting`, `test_checkout_symlink_to_external_native_is_rejected`; real host support required |
| Unknown ordinary/explicit native loader input | `test_new_native_input_is_blocked_before_binary_execution`; inert files, isolated processes |
| Loaded origin/spec/search/removal mismatch, aliases and extension exports | `test_loaded_native_origin_must_agree`, `test_native_alias_uses_verified_canonical_import_resolution`, `test_native_exported_modules_are_bound_to_verified_provider` (actual SciPy/Cython/pybind objects and negative provider relationships) |
| Installed wrapper identity without execution | `test_installed_bridge_package_is_identified_without_execution` |
| Actual trusted native computation | `test_trusted_native_execution_is_recorded_without_claiming_application_use` executes NumPy addition; `test_installed_metroliza_native_execution` executes the existing installed wheel's coercion kernel when available |
| Clean fallback and harmless ignored outputs/cache | `test_clean_fallback_and_harmless_ignored_outputs` |
| In-request native/source/helper/driver/shared-harness drift and initial dirty/shared-native inputs | `test_worker_drift_never_publishes_a_success_receipt`; two real synthetic Git checkouts, unchanged-root positive control, Linux RSS worker |
| Previous receipt and cross-sample identity | `test_compare_preserves_previous_receipt_directory`, `test_compare_rejects_different_implementations_between_samples` |
| Earlier P1: dirty/staged/untracked source and driver drift | Existing `test_benchmark_rejects_dirty_checkout_before_recording_identity` and `test_benchmark_rejects_commit_or_driver_drift` retained |
| Earlier independent P2: unavailable resource / portable help | Existing three absent-resource isolated-process regressions retained; portable matrix selected in native Windows core smoke |
| Earlier cache-boundary P2 and comparator P3 | Existing real 24-group/64-entry evidence and literal Diagnostics-fragment regression retained |

Scope increases from twelve to fourteen paths: one directly necessary provenance
helper and one isolated regression file. The helper is registered in the pending
analytics audit ledger; the test remains covered by the existing pending test
rule. Existing Windows/native jobs only extend relevant test selection. The three
production modules and original output/numerical contracts remain unchanged.
Fresh comparison and exact-head validation receipts are recorded below/on PR
#1029; #918, historical attribution uncertainty, absent demonstrated memory
improvement and the unmatched historical CI baseline remain open limitations.

Two setup attempts were rejected before workflow execution: standard SciPy
aliases and native-exported pybind submodules exposed an incomplete loaded-module
model. Patching paused for independent contract reconciliation. Ordinary aliases
now require canonical `ModuleSpec`/module-object/origin agreement. Exported
submodules have an explicit `native_export` kind bound to an already verified
extension provider: canonical registration, provider dictionary attribute chain,
identical object and matching origin are checked at every checkpoint. They do not
pretend to be independent binary imports and do not expand the pre-load allowlist.
Both failed launches and permanent fail-first regressions are preserved separately;
neither launch contributes a measurement sample.

### Fresh guarded small-workload confirmation

This series measured `b631e0dbeee75f10dc9da18ddc09f1c11752a56a`, tree
`866eacc8ad28251e69ec318a49165ca7141104d6`, against fixed B
`77e398375e5277858110c746a428d13535db6a59`. Both used that same C driver and
shared tooling. Driver SHA-256 was
`61ea5b5adf41d49943ed04b32b242863642f63039c565386054bb93fda92c62e`;
measured helper SHA-256 was
`a4bf5097b4c5e04785be248e5ee2b8cff622bc41d5bd8f4c81a6ab52179e6eb9`.
The additive `native_guarded_confirmation` JSON field retains all twelve raw
observations in execution order. All older JSON fields/data remain unchanged and
historical, including their former Draft status description.

One declared fresh-process warmup per variant preceded five interleaved pairs,
one request per process, serially apart from tests/builds. The seed-7 fixture had
300 rows, four numeric columns/metrics and three groups. All twelve complete
HTML/assets/XLSX artifacts, including warmups, passed the preserved comparator
against the first B output. All fixture hashes and package versions agreed.
CPython 3.11.16/Agg and the same installed environment were used for both variants.

| Raw measurement | B median | Measured current median | Dispersion B / current |
|---|---:|---:|---|
| Workflow seconds | 36.461032 | 28.461491 | MAD 0.415916 / 0.276011; IQR 3.130917 / 0.384797 |
| Process seconds | 58.790219 | 51.821177 | MAD 1.656813 / 0.051012 |
| Peak RSS KiB | 240400 | 240044 | MAD 224 / 304 |
| Setup seconds | 8.506258 | 8.387334 | Includes initialization/guard effects |
| Provenance checkpoint seconds | 17.464198 | 18.275262 | Overlaps native verification/setup counters |
| Import guard seconds inside workflow | 0.001279 | 0.001386 | Reported separately; raw workflow remains primary |

Workflow medians differ by -21.94% on this series; each interleaved pair favored
the measured candidate. This is a limited confirmation, not general performance
acceptance. The 356 KiB median RSS difference does not establish memory improvement.
The host remained on AC with **power-saver**, unchanged by the agent, throughout
44 observations from 09:48:00 to 09:59:08 UTC on 2026-09-06; one-minute load ranged
2.87–4.94. Historical measurements used balanced, so the series cannot be pooled
or its absolute timing attributed solely to production code. No profiled or
coverage timing is used here; #918 and advisory CSV FAIL remain unchanged.

All receipts identify the same 616 native artifact records, 155 loaded records
and 149 observed native imports. The six optional bridge resolutions were absent
and the bridges unloaded; requested backend overrides were empty. Scientific
extensions were identified by origin/content, while import itself was explicitly
not claimed to prove their computational use by this workflow. Actual trusted
NumPy/SciPy and installed Metroliza-wheel regression execution are separate
integration evidence. Local raw receipts retain resolved absolute paths; public
evidence uses logical roots and hashes.

Independent contract reconciliation subsequently confirmed that Windows normal
resolution accepts uppercase suffixes. Twelve added conservative suffix cases
failed first; the classifier now normalizes suffix case while preserving the
module basename and recorded path spelling. This is an inventory/default-rejection
correction; the existing pre-load audit hook already rejected unidentified origins.
The final helper SHA-256 is
`d02b2e1dab22b59b13f8c0d468b7287667e6262e6415409c79ddaefae219b0eb`.
Complete inventories and content identities from both classifiers were compared
against the actual measured receipts over all seven effective roots for B and C:
all 616 records matched exactly. Driver, shared harness and all three production
modules remain byte-identical to b631. With independent agreement, this preserves
the unaffected Linux comparison as **measured at b631**, with final suffix behavior
validated separately by current tests and native Windows CI. It does not claim
that the changed helper executed this series or certify its final overhead.
