# Performance Boost STEP3 — implementation plan

- **Status:** implementation in progress since 2026-10-22; packet acceptance and evidence are tracked in Issue #1151. Audit (Polish, PO):
  [`performance-boost-step3-audit.md`](performance-boost-step3-audit.md); all 126 findings with packet and
  verdict: [`performance-boost-step3-findings.md`](performance-boost-step3-findings.md)
  ([JSON](performance-boost-step3-findings.json)); per-flow estimate:
  [`performance-boost-step3-estimate.json`](performance-boost-step3-estimate.json); measurement PoC diffs (not for
  merging): [`performance-boost-step3-poc/`](performance-boost-step3-poc/).
- **Base:** `perf/step3-audit` = `perf/step2-boost` at `101e5a44` (STEP2 package, draft PR #1150, not merged) plus the
  STEP3 audit documents. STEP3 stacks on STEP2.
- **Branch:** `perf/step3-boost`, created from the head of `perf/step3-audit`; one commit series per packet. One
  draft PR `perf/step3-boost` → `perf/step2-boost`. No merge, rebase of pushed history, release or branch cleanup.
- **Coordinator:** Codex (assigned by the user on 2026-10-21). Owns slicing, worker dispatch, review, integration,
  benchmarks, CI and reporting. Product decisions: PO.
- **Routing:** development-routing v1.1 (`SKILL.md` sha256 `fbd50c68…`), model map v1.0 (`6dd04ecc…`).
  `implementer` = `gpt-6.1-sol` high for packets. Review follows the routing classes; when only OpenAI is used,
  the same-provider `reviewer` (`gpt-6.1-sol` xhigh, fresh read-only context) stands in for the Claude reviewer
  roles, and every FEATURE/CRITICAL packet gets one. `escalation_reviewer` (`gpt-6-astra`) only on a named
  trigger; Claude review only if the user confirms Claude capacity. At most two auxiliary contexts at once; one
  writer per file.

## 1. Outcome and scope

**Outcome:** the STEP3 packets below, each with identical outputs, measured against `101e5a44` on the same machine.
Expected result from the audit (§4 there, quiet post-STEP2 medians, Linux, `balanced`): 18 flows
231.6 s → about 162 s (−30%), range 144–184 s.

| Flow | After STEP2 | Expected after STEP3 | Main packets |
| --- | ---: | ---: | --- |
| Extended 216 groups | 68.8 s | ~42.5 s | T01, T02, T03, T06 |
| CSV analytics 100k | 35.4 s | ~29.5 s (~26.5 s with E6) | T07, T08, T09, (T12) |
| `benchmark_paths` CSV Summary | 64.9 s | ~48 s (~45 s with E6) | T10, T11, T08, T09, (T12) |
| Main plots 1500 | 27.7 s | ~20.8 s | T04, T05, T06 |
| Industrial → CSV Summary | 5.7 s | ~3.8 s | T16 |
| CSV load 100k | 4.7 s | ~3.7 s | T13 |
| Filter open | 1.29 s | ~0.55 s | T14 |
| Review / import 1500 | 8.4 / 9.6 s | ~7.2 / ~8.4 s | T20, T21 / T18, T19 |

Not in the sums: GUI freezes at large grouping (3.9–7.2 s per dialog open at 100k assignments, GPT micro-benchmarks)
and cancel latency (estimated up to ~15 s export, ~30 s CSV analytics); T00 adds scenarios to measure them.

**PO decisions (do not implement without an explicit decision recorded on the tracker):**
- **E5:** XLSX deflate level 6 → 1 (Main −3.7 s, file +34%). T06 keeps level 6.
- **E6:** a compute pool for CSV analytics (PoC: −17% wall, +750 MB RSS, +73% total CPU). T12a only measures.
- **E7:** deferring Industrial base facets (A10-F03), which moves cost to the first filter open.

**Never in STEP3:** less computation (e.g. fits on a sample), lower chart density/quality, weaker integrity or
durability checks, changes to the GUI-thread GC policy (A16-F01), launcher changes (A19-*), new third-party
dependencies.

## 2. Rules for every packet

**MUST**

1. Same results as `101e5a44`: identical data, rows and their order, statistics, workbook members, dashboard
   content and saved state. Write the equivalence test against the current code first, see it pass on the base,
   then change the code. If a packet cannot keep identity, stop and report; do not weaken a comparison.
2. Keep the general/fallback path for every fast path, with a test that exercises it.
3. Qt widgets only on the GUI thread. Workers are `QThread`s or the shared spawn context from
   `metroliza.shared.compute_worker`. No `gc.collect()` outside the GUI thread; no `processEvents()` from worker
   threads. Keep a `QThread` referenced until `finished`, then `deleteLater`.
4. SQLite: one writer per file; readers own their connections; every `sqlite3.connect` sits in
   `contextlib.closing` (repository guard). Keep transaction and checkpoint order (#1132, #1137).
5. Lazy imports: modules imported at start-up stay pandas/SciPy-free (`tests/test_pandas_free_runtime_helpers.py`,
   `tests/test_bootstrap_startup.py`, `tests/test_analytics_exporting_boundary.py`).
6. Every new tracked file gets an owner in `docs/quality/bug_sweep/coverage.json`. Python edits that move lines
   above Bandit-baselined findings need the baseline rebound (its fingerprints include line numbers), then the
   repository's full security gate.
7. Before every commit: focused tests, every test file that greps for a changed symbol or for the changed call
   site's callers, and the repository guards after `git add`: `ruff check .`, `tests/test_complexity_ratchet.py`,
   `tests/test_bug_sweep_coverage.py`, `tests/test_db_utils.py`, `tests/test_runtime_print_guard.py`,
   `tests/test_docs_markdown_links.py`, and `git diff --check`. Qt tests run with
   `env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen`, `ulimit -c 0`, no pytest `-n`.
8. Repository files never mention local paths, local tools or the local machine.

**Forbidden:** merge, rebase or force-push of pushed branches, `git stash`, branch deletion, CI workflow changes
outside a packet, dependency installs, machine changes (power profile, services), a benchmark while another heavy
job runs, and Windows candidate acceptance runs without the user's consent.

**Handback per packet:** commits, test commands with exit status, equivalence evidence (which outputs, which
fixtures, result), stage-focused A/B evidence or explicit performance PENDING under the delivery amendment below,
machine state, open risks, files changed, the configured model/effort of every worker and reviewer.

## 3. Equivalence and measurement protocol

- **Fixtures:** the harness's synthetic data (`benchmark_ui_flows.py prepare`): `db_1500`, `db_small`, `csv_100k`,
  `ind_50k`, `pdf_1500`, plus edge-case fixtures written by each packet's tests.
- **Workbooks:** compare XLSX packages member by member: same member names and order, CRC32 and bytes. The only
  allowed difference is the creation/modification timestamp in `docProps/core.xml`; two runs of the same code also
  differ there, and `output_bytes` can differ by one byte for that reason.
- **HTML dashboards:** compare after masking ISO timestamps (`generated_at` and similar), subject to the named,
  narrowly scoped generation-directory exception below. All asset contents remain byte-identical.
- **Databases:** compare `sqlite_master` definitions (tables, indexes, views and triggers), then dump and compare
  tables row by row in primary-key order (import, CSV load).
- **SQL rewrites:** identical result sets in identical order on the harness DB and on edge fixtures (NULL, blank,
  whitespace, numeric-looking text, orphans, duplicates).
- **Images:** PNG bytes identical. A pixel change drops that sub-item (report it); it is not reviewed away.
- **Timing:** clean detached worktree of `101e5a44` and the candidate, both with compiled bytecode and the same
  harness file copied in; `balanced` profile recorded with the power probe; sequential A/B in ABBA order (≥2 per
  side for flows over 20 s, ≥3 otherwise), one heavy job at a time on the machine.
  Report ratios from one session; profiling runs are diagnostics, not results.
- **Platform:** Windows is not measured locally. Record which claims only Windows CI or the packaged EXE can
  prove; packaged Windows keeps 2 render workers and opt-in import-prepare/review pools.

### PO amendment — product delivery and staged performance evidence (2026-10-24)

Authority: [current PO delivery steering](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6381122991).
This amendment supersedes the requirement to complete a full end-to-end timing series before
every packet handback or subsequent product wave. It preserves all output, fallback, computation,
chart-quality, integrity, durability, test, review and CI requirements.

- Freeze the existing measurement orchestration, resource supervision, admission gates, probes and
  comparator, retaining their source bindings and all adverse receipts. Further infrastructure fixes
  are allowed only when necessary to restore the computer's settings safely. Do not expand the
  tooling or repeat long series in response to the same unstable measurement conditions.
- Measure each packet's changed stage on its complete representative input. For T11 this means
  validation of all 100k assignments and GUI blocking. Stage boundaries, useful results, sample
  counts and machine state remain explicit; a stage measurement never claims full-flow performance.
  No work performed by the product may be removed or shortened. Use the existing infrastructure
  for packet-specific test and benchmark cases, without a new resource-control framework.
- Record code/output/review/test/CI verification separately from stage and end-to-end performance.
  An unmeasured or unsuitable timing is **PENDING**, never zero, PASS or an inferred gain. Product
  integration and subsequent optimizations may proceed with performance PENDING once their actual
  correctness, review, tests and required wave CI pass. Review budgets and the wave integration
  order remain unchanged. Push the authorized branch after local validation to obtain actual CI.
- Reserve the complete rotated end-to-end campaign for T28 on a suitable, stable measurement
  station. Keep its 18 audit flows plus T00, identical harness and output comparisons, balanced
  profile and n=3 (n=2 for flows over 60 s). If suitable conditions are unavailable, record
  **measurement pending** and retain the missing evidence explicitly; this does not block other
  product packets or authorize repeated multi-hour attempts in the unchanged conditions.
- Codex remains the coordinator. Opus has a bounded planning/advisory role when needed; do not
  transfer the entire coordination context. The PO's continuing browser use and TupTup hold remain
  in force; do not repeat browser-closing or quiet-window questions.

Excluded or intentionally stopped series remain excluded. Available strict functional output
comparisons remain useful correctness evidence, without turning their timings into accepted data.
The final four-stage Polish report must distinguish measured seconds and reductions from PENDING
or incomparable cells and preserve the stated common-flow set and aggregate weights.

### PO amendment — C01 import runtime timestamps (2026-10-25)

Authority: [explicit narrow C01 approval](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6399420191).
This is the sole additional exception to the comparator freeze above. Independently generated
`101e5a44` full imports differ in deliberately generated persistence timestamps. The unchanged
comparator's failed A/A result and the excluded f02 timing series remain retained.

Allow a named, explicitly enabled import-only comparison exception at exactly these locations:
`parsed_reports.created_at`, `parsed_reports.updated_at`,
`report_metadata_candidates.created_at`, `report_metadata_warnings.created_at`,
`report_parse_state.updated_at`, `source_file_locations.discovered_at` and
`source_files.discovered_at`. Validate the timestamp type and exact UTC format and the declared
import database/schema scope. Require the explicit `--import-runtime-timestamps` option together
with `--sqlite`, literal paired `import.sqlite` filenames and the canonical eight-core-table import
schema binding. Keep the default comparison strict. All other columns, row counts,
types, ordering, schema objects and output files remain literal. Do not change product persistence.
Require calendar-valid `YYYY-MM-DD HH:MM:SS` UTC only for `report_parse_state.updated_at`,
which baseline SQLite writes with `CURRENT_TIMESTAMP`; require `YYYY-MM-DDTHH:MM:SSZ` only
for the other six locations written by baseline `utc_timestamp()`. Reject cross-location formats.

Prove each allowed location and negative cases for the same timestamp pattern elsewhere,
malformed/null values, changed measurements/metadata/JSON and changed schema. Permit only the
necessary comparator, existing tests, T28 caller/binding and this plan update. Resource controllers,
supervision, admission gates, probes, numerical settings and all other frozen tools stay unchanged.
C01 has a separately approved maximum of one FULL1 and one DELTA1 review; preserve all earlier
packet/resource review receipts and exhausted budgets without resetting them. Focused tests,
MUST-7, full-output A/A and A/B checks and required integration/CI remain mandatory. Excluded
timings never become accepted because output comparison later succeeds.

### Coordinator correction — C02 persistence cache withdrawal (2026-10-25)

Authority: the PO's [continuing necessary-fix authorization](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6346416141),
applied in the [bounded C02 admission](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6400732869).
Full-input T28 profiling identified recursive validation of T19 A09a-F01 persistence-row caches as
extra owner-thread work. Profiling is diagnostic, not accepted end-to-end performance evidence.
Withdraw only production, transfer and consumption of that cache; use the existing general row
writer with outer membership frozen and nested source values live. Retain legacy prepared-state
compatibility without trusting cached tuples. Preserve T19 A07-F03 enrichment indexing, replacement
invalidation, live approval/fallback, T21 metadata work, STEP2's per-report fail-closed registry
refresh, full computation, transaction/checkpoint order, integrity and durability.

This correction adds no comparator, resource controller, admission, probe, numerical or dependency
exception and no new cache/revision framework. Require baseline behavioral tests, final-source
focused/caller tests, staged MUST-7/full security, complete import-output identity, one independent
FULL1 and at most one DELTA1, an integrated full suite and required CI. C02 is a distinct corrective
patch with that bounded review budget; retain every earlier review/adverse receipt and exhausted
budget. Mark timing PENDING until an unchanged unprofiled final campaign qualifies it.

### Coordinator correction — C03 native lookup test oracle (2026-10-25)

Authority: the continuing necessary-fix authorization above, applied in the
[bounded C03 admission](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6401236089).
The integrated C02 suite returned 1 with two native OCR test failures; retain that adverse result.
A source-bound seed58 control reproduces both failures on original `101e5a44` and C02: one
attribute expression can invoke raw-key equality more than once. The failed suite's original seed
was not captured; the control does not prove its precise historical trigger or a product regression.

Correct only the existing native lookup test's invalid fixed-callback premise. Observe the exact
original dictionary lookup, require its complete ordered callback sequence and literal geometry,
then require the candidate to match. Preserve stateful sensitivity and demonstrate rejection of
the extra-membership/extra-lookup mutant across fixed and random seeds. Keep product geometry,
all output comparisons and measurement infrastructure unchanged; no permissive callback ranges,
assertion skips, selected favorable seed or interpreter-setting workaround.

C03 has at most one independent FULL1 and one DELTA1 for this distinct test-oracle correction.
Preserve C02's source-only review, failed integrated suite and all older budgets/receipts. Require
focused/caller tests, staged MUST-7/full security, a corrected integrated full suite and actual
required CI before qualification. This is not a performance change or accepted timing evidence.

### PO amendment — technical-report publication (2026-10-23)

Authority: [explicit PO consent](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6359252320).
Publish the approved T08 review and analogous STEP3 technical reports on #1151/PR1152,
including findings, tests, source hashes and model routing for unpublished candidates.
Omit local filesystem paths, user/customer data and secrets. This standing consent
preserves all source/review/test/CI gates; earlier automatic publication rejections
remain recorded and do not authorize an alternate-tool bypass before consent.

### PO amendment — temporary measurement widget exception (2026-10-23)

Authority: [explicit PO consent](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6358316138).
The machine-change ban has one narrow exception: temporarily disable only `omarchy.agents`
during reserved STEP3 measurement sessions and restore its exact prior entry, settings and
position after each session, including failure or interruption. If initially disabled, leave
it disabled. Preserve parallel user edits; private configuration backups must not be published.
Before admission, confirm the disabled state and termination of existing collectors, then all
unchanged balanced/AC, CPU, quota, TupTup and shared-lock guards. This grants no power-profile,
service or other machine changes, and does not establish quietness or waive output checks.

### PO amendment — matched CPU partition during browser use (2026-10-23)

Authority: [PO resource steering and scoped verification](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6369451625).
The PO holds TupTup until Metroliza finishes, permits continued Firefox use and requests
the remaining CPU capacity for measurements. Do not repeat reservation questions under
that continuing instruction. Temporarily assign disjoint sets of complete physical cores
and their SMT siblings to the browser and benchmark; both A and B use the same fixed mask.
This adds only scoped process/thread affinity to the machine-change exception. Preserve
prior policies and parallel user changes, and restore after success, failure or interruption.
Other heavy jobs remain held; power, services, cgroups and global scheduling stay unchanged.

Record actual topology, masks, native math-thread policy, balanced/AC, load, temperature
and applicable storage headroom. Affinity can change native numerical defaults: generate
fresh baseline/A-A controls in the same condition, retain earlier-condition evidence separately
and keep every number and output literal. No numerical mask is admitted. Capture each
algorithm's complete original-consumed population, including any deliberate existing
selection, without introducing new sampling or changing aggregate/workbook scope.

Settle before a recorded measurement epoch; preserve all setup and cleanup observations.
New unrestricted browser tasks, escaped benchmark threads or monitor failures after the
epoch exclude the complete series. Keep the shared lock across all gaps and the separately
authorized widget lifecycle. Affinity is not global exclusivity: RAM, caches, I/O and
thermal/power limits remain shared. Report polling/identity/lifecycle limits and actual
restoration; do not claim atomic or continuously isolated process trees. This changes the
measurement condition, not computation, output-comparison rules or E5/E6/E7 authority.

Implementation evidence: [scoped desktop reservation and restoration controls](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6376031359).
The coordinator applies the existing CPU-reservation instruction to an exactly bound interactive
desktop process and its descendants as well as the browser; this is not separately named PO consent
for a desktop executable. Exclude the owned benchmark subtree, validate UID, process/thread start
identities and the literal executable link/device/inode, and keep unrelated work subject to the
unchanged load guard. Do not introduce process-name exemptions.

Capture and journal all initial policies before the first affinity write. A newly observed,
unrecorded task outside its assigned mask may be reconciled only during preparation, before the
measurement epoch: at most three complete rescans under the same finite deadline. Known or reused
identity slots, parallel edits, root/UID/executable, permission, asynchronous-monitor and deadline
failures remain fatal. After the epoch, newly observed unrestricted work excludes the whole series.
Cleanup must retain the primary error and terminate/reap owned work even when status reporting is
broken. Independent restoration audits include live tasks absent from the journal; fallback recovery
cannot turn failed supervisor cleanup into successful qualification. Keep failed qualification and
restoration verdicts separate. These controls remain sampled, with observation/syscall races.

Retain exact original process policies by PID, start time and UID after the last live thread record
retires. Journal before mutation or retirement, deduplicate only exact masks, and fail closed on
ambiguous, incomplete or capped history without eviction. Only an unknown process may inherit a
unique policy from its verified current parent; never guess an orphan's target. Preserve diagnostics
that distinguish absent from multiple candidates. Source and limits:
[retained-history correction and requalification](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6377917914).

Use finite direct-parent supervision for a long measurement session: launcher success means only
STARTED. Retain the same OFD lock through bounded termination, reaping, exact journal recovery and
independent audit; require the actual child outcome and coherent completion before accepting times.
Missing terminals remain missing, and any recovery excludes the measurement. Individual-owner-loss
controls do not establish automatic recovery after simultaneous loss of both owners or the cause of
an earlier unexplained exit. Keep cleanup independent of reporting and lease health.

A workload-ready marker may precede its next owned-token snapshot; wait for exact membership under
the original deadline before a controlled signal. Only an identity-proved departed requester may be
retired without assigning a policy or writing to a replacement. A still-live requester with an
unverified parent, UID/permission/history error or parallel edit remains fatal. Rebind helper source
pins and exercise the actual guarded constructor before host admission. Source and limits:
[five controls and independent closure audit](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6379837103).
Resource full1/delta1 remain exhausted REQUEST_CHANGES; subsequent corrections have execution proof,
not a third formal review. Simultaneous-owner-loss/interrupted-recovery native controls remain NOT_RUN.

An additional interactive browser outside the admitted trees remains competing load and excludes
the complete series; completed output parity does not accept interrupted timing samples. Bind only
the necessary additional exact tree under the existing CPU-reservation authority, with a finite
task-specific cap of two explicit interactive roots and an exact ordered authority hash. Reject
duplicates and identity/executable/UID drift; preserve independent restoration for both trees and
partial admission. Do not widen to a whole desktop/session ancestor or use a process-name exemption.
Unrelated heavy work retains the same guard. Source, authority interpretation and limitations:
[two-root controls and independent audit](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6380891101).

A private harness home also needs private Matplotlib and XDG home/search directories on both sides;
inherited configuration paths can escape a home override. Record the selected environment and
preserve the matched native-math policy. Do not change numerical thread settings to repair timing
or output differences.

### PO amendment — intentional nondeterminism (2026-10-22)

Authority: [PO decision on #1151](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6340146427).
The previous T00 stop followed the original contract. Dashboard publication deliberately names its asset
generation directory with `uuid.uuid4()` for atomic publication; independently generated baseline outputs
therefore have different generation names. Do not change the product's publication code.

- **Named exception — dashboard asset generation:** pair exactly one generation directory on each side
  (`export_dashboard_assets.generation-<32 lowercase hex>`). Compare every relative asset name and every byte.
  In HTML, mask only the exact `generation-[0-9a-f]{32}` token naming that paired directory in its asset
  references. The same pattern elsewhere must still cause FAIL. Missing, extra or ambiguous generations,
  changed relative names or changed asset bytes remain failures. All other output differences stay literal.
- **Further intentional nondeterminism:** an exception may be admitted without waiting for the PO only when
  all three conditions hold: (a) it reproduces in `101e5a44` versus `101e5a44`; (b) it comes from a deliberate
  mechanism in baseline code; and (c) it has a narrow, named pattern with a negative test proving that the
  same pattern elsewhere still causes FAIL. Record each exception and its evidence in the packet handback.
  Every other difference, especially one absent from baseline-versus-baseline, still means STOP.
  **Named T02 application:** the HTML-only harness destination `export.html` deliberately produces
  `export_assets.generation-<32 lowercase hex>` through the same baseline publication mechanism.
  Independent `101e5a44` HTML-only outputs reproduce the original comparator's filename failure.
  Admit this second named asset base under the three conditions above, with the same literal asset,
  reference-location and negative controls as `export_dashboard_assets`. Pair exactly one generation
  overall on each side, and keep the asset base name itself literal: mixed bases still fail.
**Named T08 application — CSV Summary temporary SQLite diagnostic:** independently
generated `101e5a44` `benchmark_paths` CSV Summary workbooks differ in the deliberately
random basename created by `NamedTemporaryFile(prefix="metroliza_csv_summary_",
suffix=".sqlite")`. The basename is stored in the `sqlite_path` field of the
`tabular_sqlite_store_created` diagnostic's context on the `Diagnostics` sheet.
Admit this exception only with the comparator's explicit `--csv-summary-temp-root`
argument, bound to the same recorded actual temporary directory for both exports.
The default comparison remains strict.

Locate the unique diagnostic row and its plain shared-string context through the
workbook relationships and exact headers. The context has exactly the original
`row_count`, `source_file_count` and `sqlite_path` fields with unchanged types and
values outside the basename. Both literal parent paths must equal the recorded
root. Permit only the eight-character `[a-z0-9_]` nonce in
`metroliza_csv_summary_<nonce>.sqlite`. Prove that this shared-string entry is
referenced only by that context cell across all worksheets. Substitute only the
paired basename's raw ASCII bytes, without XML reserialization; the resulting
whole member must match bytes, length and CRC. All other package members, names,
order, worksheet bytes, strings, diagnostics, charts, images and asset bytes remain
literal under the existing core-timestamp rule.

Wrong roots, malformed/ambiguous scope, changed sibling context fields, extra
uses of the shared-string entry, the same differing token elsewhere, changed
serialization or invalid CRC must fail. Retain the original strict baseline
failure and the negative controls in the T08 handback. Lexical POSIX/Windows-root
test coverage does not establish native Windows runtime or packaged acceptance.
Do not change the product's temporary-file allocation, publication or randomness.

- **T00 baseline-versus-baseline control:** independently generate XLSX, HTML with its assets, and SQLite
  outputs on `101e5a44`; the comparator must return 0 for each type. Preserve the earlier failed receipt.
- **T00 review corrections:** reject an empty Group Analysis result (require more than zero metrics); compare
  indexes, views and triggers as well as table definitions and rows; request cancellation only after an
  observed marker of actual processing, rather than the first progress label.
- **Resume order:** tests with captured exit codes, the one remaining delta review, MUST-7, T00 commit,
  push `perf/step3-boost`, one draft PR to `perf/step2-boost` marked do not merge, then packet handback.
  Proceed to T01 under the existing wave and file-ownership rules after refreshing quota, power profile,
  the shared heavy-job lock and TupTup load. The amendment does not reset the review budget or waive any
  other validation, resource, publication or Windows-acceptance gate.
- **T00 attempt-budget exception:** after the two failed resume attempts, the PO explicitly authorized
  [one additional T00 attempt](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6341046406)
  on 2026-10-22 to correct observation of Group Analysis metrics before payload cleanup. The requirement
  for nonempty metrics, every other gate and the one remaining delta review stay unchanged. This does
  not extend the attempt budget of another packet.

### PO amendment — dependency versions and T00 CI correction (2026-10-22)

Authority: [PO decision on #1151](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6345338339).
CI installs the requirement files; their open ranges selected XlsxWriter 3.3.0 while local T00
validation and measurements used 3.2.9. The original product source and XLSX tests are unchanged
from `101e5a44`. Preserve the failed CI receipts and fix dependency selection without changing the
exporter's version guard, workbook output or test tolerances.

- Freeze existing direct dependencies in all seven `requirements*.txt` to exact versions, retaining
  immutable Git commit pins. Runtime/development pins use the environment validated for STEP3;
  build/optional pins record separate provenance and unverified execution where applicable.
  No new dependencies, local installs or workflow changes are authorized by this amendment.
- This explicitly admits the T00 dependency correction after the prior attempts, with a limit of
  two unsuccessful correction attempts. It does not reset full1/delta1 review consumption, another
  packet's budget, or any output, full-suite, CI, resource and Windows-acceptance gate.
- After the stale Pillow requirement assertion and the security-audit failure consumed those attempts,
  the PO [authorized one further correction attempt](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6345655315)
  to select setuptools 84.2.1 and finish the unchanged gates. The PO also requested Opus 5.5 high
  diagnostic consultation for uncertainty or problems absent in STEP2. This advisory is distinct from
  formal review; existing review consumption and other restrictions remain unchanged.
- Adopt the [dependency update policy](../project/development_workflow.md#dependency-versions-and-updates):
  periodically review release notes, security, useful features and compatibility before a separate
  update PR, validation and package rebuild/qualification. Direct pins do not lock all transitive
  dependencies or the complete toolchain. T01 remains gated on T00/wave-0 completion.

Pin provenance for this correction: runtime/dev versions match the installed environment used for
the existing successful output comparisons and measurements, including XlsxWriter 3.2.9 and pandas
3.0.6. Build versions come from the successful native-wheel job in
[run 39805759494](https://github.com/hexafe/metroliza/actions/runs/39805759494/job/119918504136),
with duplicate development/build entries aligned to that validated environment, except setuptools.
The job's already-satisfied setuptools 79.0.1 fails the current advisory audit; select published
84.2.1 for its security fixes, then require the same security/build gates. Existing exact
pins and Git SHAs remain unchanged. Four optional packages lacked execution evidence: scikit-learn
1.9.1, river 0.26.1, opencv-python 4.14.0.94 and openvino 2026.4.1 were selected from non-yanked stable
PyPI releases within their previous ranges. Their published metadata was checked for Python 3.11
and direct-dependency constraints; installation, full resolution, optional execution and Windows
package qualification remain unverified. These metadata checks do not establish runtime compatibility.
The correction spans ten files because the six requirement files, two existing requirement/security
policy tests and two authority/policy documents form one consistent dependency-selection change;
no new package is added. The security test retains an exact assertion for the selected Pillow pin.

### PO amendment — necessary correctness fixes and continuing authority (2026-10-22)

Authority: [PO instruction on #1151](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6346416141).
The PO authorizes the prepared workbook-format cache correction and further technical fixes necessary
to deliver STEP3 with measured performance improvement and unchanged correct output. Routine corrective
scope and justified follow-up attempts do not require repeated PO approval. After unsuccessful attempts,
preserve the evidence, stop the unchanged approach, obtain a new discriminator and consult Opus 5.5 high
for uncertainty or problems absent in STEP2. This supersedes the earlier requirement to wait for another
attempt/scope grant; it does not authorize retrying unchanged failures until green.

T00 may correct `exporting/export_sheet_writer.py` with regressions in its existing test file before
T01. This advances only T27 item A03-F06 as a prerequisite of wave 0; record it once in the handbacks
and do not repeat the implementation or mark the rest of T27 complete. The global cache keyed only
by an ephemeral adapter's numeric ID can return formats belonging to
a previous workbook. A controlled experiment on unmodified `101e5a44` with XlsxWriter 3.2.9 reproduced
foreign-format ownership, an invalid style reference and an openpyxl error; the isolated-cache control
and identity comparison between correct outputs passed. Preserve the malformed baseline evidence.
Correcting this defect need not reproduce a malformed workbook. Valid exports must retain literal
member/order/CRC/byte identity under the existing narrow timestamp/generation exceptions, with all data,
styles, layout and charts preserved. Do not mask invalid styles or weaken the comparator.

Each further correction must name its concrete defect, regression test and output evidence. Full-suite,
CI, resource coordination and existing formal review budgets remain required. The PO's broader fix
authority does not authorize reducing computation/quality/integrity/durability, GC/launcher changes,
new dependencies or installs, machine changes, other pushes, merge/rebase/force-push, or Windows
candidate acceptance. E5/E6/E7 remain PO decisions under the original plan. A correction is not a new
output exception unless it addresses a demonstrated invalid baseline result while preserving valid ones.

## 4. Packets

| ID | Wave | Packet | Files (main) | Class / role | Expected gain | After |
| --- | --- | --- | --- | --- | --- | --- |
| T00 | 0 | Harness scenarios, output comparison tool | `scripts/benchmark_ui_flows.py`, new `scripts/compare_export_outputs.py` | BOUNDED / implementer | enables T22–T26 measurement | — |
| T01 | 1 | Panel table without discarded measurements (A01-F01) | `exporting/export_data_thread.py` | BOUNDED / implementer | Extended −13% (PoC) | T00 |
| T02 | 1 | Plotstats-first summary charts (A02-F01, A04-F01) | `exporting/export_data_thread.py`, `charts/chart_renderer.py` | FEATURE / implementer + reviewer | Extended −24% after T01 (PoC) | T01 |
| T03 | 1 | Remaining Extended chart costs (A01-F03, A01-F02, A01-F04, A03-F04, B01-F01) | `exporting/export_data_thread.py`, `exporting/export_summary_utils.py`, `charts/chart_render_spec.py` | BOUNDED | −2…−5 s | T02 |
| T04 | 1 | Main partitions on indexed columns (A02-F02, B04-F01) | `exporting/export_query_service.py`, `exporting/export_data_thread.py` | BOUNDED | −2.3…−2.5 s (measured SQL) | T03 |
| T05 | 1 | Header-group sort without helper columns (A02-F03, A18-F02) | `exporting/export_data_thread.py`, `analytics/row_table.py` | BOUNDED | −0.6…−1.5 s | T04 |
| T06 | 1 | XLSX packaging: parallel deflate, no packaging on cancel (C-04, A03-F01 a, A03-F03) | `exporting/export_backends.py`, new `exporting/xlsx_parallel_package.py` | FEATURE / + reviewer | Main −3…−4 s, Extended −1 s | T00 |
| T07 | 2 | Caching lazy pandas proxies (C-02) | 12 modules with `_LazyPandas`, new `shared/lazy_modules.py` | BOUNDED (mechanical, >8 files: reasoned exception) | −0.5…−1.5 s CSV | — |
| T08 | 2 | Plotstats adapter numeric fast paths (A04-F03, A04-F04, A04-F05, A04-F02) | `charts/chart_numeric_helpers.py`, `charts/hexafe_plotstats_adapter.py`, explicit preview caller in `charts/dashboard_visual_options.py` | BOUNDED | −2…−5 s CPU CSV | — |
| T09 | 2 | Dashboard writer and time-series traces (A11-F02, A11-F01, A11-F07, A11-F04, `_json_values`) | `industrial/industrial_analytics_dashboard.py` | BOUNDED | −2…−4 s CSV | T07 |
| T10 | 2 | CSV Summary workbook on the bulk sheet writer (C-03) | `tabular/tabular_xlsx_writer.py`, `tabular/tabular_analytics_service.py` | FEATURE / + reviewer | −8…−12 s `benchmark_paths` | T13 |
| T11 | 2 | One validated grouping snapshot (A06-F01, A10-F01) | `tabular/contracts.py`, `industrial/contracts.py`, `industrial/industrial_workers.py`, `ui/industrial_analytics_dialog.py`, workflow | FEATURE / + reviewer | −1…−3 s; GUI −2…−5 s at 100k | T00 |
| T12a | 2 | E6 input: fits-only compute pool measurement | PoC only (no merge-ready code) | BOUNDED | decision input | T08, T09 |
| T13 | 2 | CSV load row loop (A05-F01, A05-F03, A05-F04) | `tabular/tabular_analytics_service.py` | BOUNDED | 4.7 → ~3.7 s | — |
| T14 | 3 | Filter values from a report-level relation (A09a-F02) | `reports/report_query_service.py`, `reports/filter_values.py` | BOUNDED | 1.29 → ~0.55 s (measured SQL) | — |
| T15 | 3 | Characteristic Mapping CTE materialised (A09a-F03) | `reports/characteristic_mapping_service.py` | MICRO / economy_worker | −0.2…−0.35 s | — |
| T16 | 3 | Industrial bridge facets (A10-F02, A10-F04, A10-F05, A10-F09) | `industrial/industrial_tabular_bridge.py` | BOUNDED | 5.7 → ~3.8–4.5 s | — |
| T17 | 3 | Grouping open and Modify DB records (A14-F05, A14-F04, B07-F01, A06-F05, A06-F04, A14-F06, C-01) | `ui/data_grouping.py`, `shared/grouping_filter_core.py`, `tabular/data_grouping_service.py`, `tabular/grouping_assignment_store.py`, `ui/modify_db.py`, `ui/modify_db_records.py` | BOUNDED | Grouping −0.15 s; records −0.4 s | — |
| T18 | 4 | Registry refresh cost — conditional (A07-F02, A08b-F02, A07-F04) | `parsing/report_parser_factory.py`, `parsing/declarative_parser_profiles.py` | CRITICAL-adjacent / + reviewer | −0.4…−0.8 s or NOT_APPLICABLE | — |
| T19 | 4 | Persistence-ready rows, enrichment index (A09a-F01, A07-F03) | `reports/report_repository.py`, `parsing/cmm_report_parser.py`, `parsing/parse_reports_thread.py` | CRITICAL (persistence) / + reviewer | −0.5…−1.5 s import | — |
| T20 | 4 | Review token normalisation (A08a-F03, A09b-F01) | `cmm/block_parser.py`, `reports/header_ocr_corrections.py` | BOUNDED | −0.5…−1.4 s Review | — |
| T21 | 4 | Quick metadata path (A08a-F01, A08a-F02, A08b-F01, A08a-F04) | `parsing/review_pool.py`, `parsing/cmm_report_parser.py`, `parsing/header_ocr_geometry.py`, `parsing/metadata_review.py` | FEATURE / + reviewer | −0.5…−1.2 s Review | T19 |
| T22 | 5 | Tabular grouping and filter dialogs (A15b-F01…F07) | `ui/tabular_analytics_grouping_dialog.py`, `ui/tabular_analytics_filter_dialog.py` | BOUNDED | freezes 3.9–7.2 s → <0.5 s | T00 |
| T23 | 5 | Industrial analytics dialog, part selection, mapping editor (A15a-F01, A15a-F03, A05-F02, A05-F06, A05-F07, A06-F02, A14-F01, A14-F02, A09a-F04) | see §5 | BOUNDED (split if >600 lines) | GUI −0.4…−2 s per action | T00, T13, T17 |
| T24 | 5 | Admin/edit work off the GUI thread (A09b-F02, A09a-F05, A09b-F03, A08b-F03, B05-F01, B08-F01, A09a-F07, A09b-F04) | see §5 | BOUNDED | GUI −0.1…−5 s per action | T00 |
| T25 | 6 | Cancellation latency (A10-F08, A11-F06, A14-F08, A15a-F02, A14-F07) | `industrial/industrial_analytics_workflow.py`, `industrial/industrial_analytics_dashboard.py`, `ui/modify_db_records.py`, `ui/industrial_data_dialog.py` | FEATURE (Qt lifetime) / + reviewer | cancel → idle < 1 s | T00, T09 |
| T26 | 7 | Group Analysis export (A18-F01, A18-F03, A18-F04, A18-F05) | `analytics/group_analysis_service.py`, `analytics/distribution_shape_analysis.py`, `analytics/hexafe_groupstats_adapter.py` | BOUNDED | −1…−3 s at 100k rows | T00 |
| T27 | 7 | Hygiene (A13-F02, A10-F06, A16-F03, A03-F06, A15a-F07, A15a-F05) | see §5 | MICRO/BOUNDED | small | — |
| T28 | — | Integration benchmark, report, CI | docs, Issue | coordinator | final numbers | all admitted packets |

Paths are relative to `src/metroliza/` unless they start with `scripts/` or `docs/`. Line numbers below are at
`101e5a44` and only help to find the code; bind to the symbol.

## 5. Packet details

### T00 — Harness scenarios and output comparison (C-06)
- **What:** measurement support for the packets whose effect today's harness cannot show; no product change.
- **Where:** `scripts/benchmark_ui_flows.py` (Scenario classes from line 403; `run` arguments near 1181; cleanup
  of the work directory near 1044), new `scripts/compare_export_outputs.py`, new tests (the UI harness has none
  yet; `tests/test_benchmark_paths.py` is the pattern for script tests), `docs/quality/bug_sweep/coverage.json`.
- **How:**
  1. `run --keep-output DIR`: copy the scenario's outputs before the work directory is removed.
  2. `scripts/compare_export_outputs.py A B`: XLSX member comparison (names, order, CRC32, bytes;
     `docProps/core.xml` timestamps ignored), HTML comparison with masked ISO timestamps, optional SQLite table
     dump comparison; exit 0 only when equal, print the first difference otherwise.
  3. New scenarios with deterministic synthetic fixtures from `prepare`:
     - `csv_grouping_open`: CSV Summary 100k with a saved 216-group / 100k-row assignment; open the grouping dialog
       until it is populated; report the longest GUI stall;
     - `csv_grouped_analytics`: the same grouping through "Create analytics". Its observation deadline is
       3600 s (suite supervisor: 3720 s); the full 100k-row/216-group reference requires longer than the
       ordinary 900 s. Every other scenario keeps its 900 s deadline (suite: 1020 s);
     - `export_cancel` and `csv_analytics_cancel`: request cancel at a fixed mark after work starts; result =
       time from the request to an idle GUI with the thread finished and no output left behind;
     - `group_analysis_export`: an export with Group Analysis enabled (use the dialog option the product exposes).
- **Tests:** unit tests for the comparison tool (equal, member differs, member missing, timestamp-only difference)
  and a smoke test that each new scenario builds its fixture.
- **Done when:** the new scenarios run on `101e5a44` and record their baseline in the handback.

### T01 — Panel table without discarded measurements (A01-F01, verified)
- **What:** `render_panel_table` measures every label/value in up to 10 font-shrink passes (56k extent probes for
  216 groups) although explicit column fractions and shared row metrics make the measurements unused.
- **Where:** `exporting/export_data_thread.py`: `render_panel_table` (3191), inner `_measure_layout`,
  `_measure_text_extent` (3155), caller `render_panel_table_in_panel_axes` (3360) used by the Extended histogram
  table (~6955).
- **How:** decide once per call whether the layout needs text metrics (`explicit_label_fraction` and
  `explicit_value_fraction` set **and** `shared_row_metrics` present); if not, skip all `_measure` calls and keep
  every other step unchanged: compaction, the font-shrink loop and its final font size, overflow flag, fallbacks
  and explicit row heights. Reference: `performance-boost-step3-poc/poc1_table_layout.patch`.
- **Tests:** a spy on `_measure_text_extent` proves zero calls on the explicit path; the returned metadata and the
  table's column widths/font sizes equal the measuring path on ≥20 synthetic tables (overflow, compact labels,
  wrapped values, symbol-font text); the general path still measures.
- **Done when:** Extended `full_report` workbook identical to the base; A/B Extended shows the gain.

### T02 — Plotstats-first summary charts (A02-F01, A04-F01, verified)
- **What:** with the default `matplotlib` backend, `summary_sheet_fill` builds and styles a full legacy figure
  for the distribution, IQR and trend charts, extracts geometry with a full `canvas.draw()`, and then
  `PlotstatsChartRenderer` renders its own PNG from the payload; the legacy figure is discarded. Building it only
  on fallback gave −24% on Extended with identical output.
- **Where:** `exporting/export_data_thread.py`: `summary_sheet_fill` (6162), non-native branches of the distribution
  chart (~6486–6550), IQR (~6639–6690) and trend (~7194–7230); `_save_summary_chart` (4291);
  `_reserve_summary_image_slot` (6343); `_summary_image_slot_with_scale` (4395);
  `_resolve_summary_image_display_scale` (4367). `charts/chart_renderer.py`: `PlotstatsChartRenderer` (333),
  `_render_plotstats_payload` (367).
- **How:**
  1. Add a public `PlotstatsChartRenderer` method that returns the Plotstats result or `None` (wrapping the private
     one).
  2. Preserve each baseline branch's theme timing and rcParams side effects: distribution and trend call
     `apply_summary_plot_theme()` first; IQR inherits ambient rcParams. Try the payload render;
     on success use its PNG and backend, and reserve the slot from the declared figure size without creating
     axes. Prove equality of the slot from a figure and from the size in a unit test.
  3. On `None` or an exception, run the existing legacy path unchanged (figure, geometry,
     `_save_summary_chart(fig, …)`). Restore only a failed speculative attempt's input rcParams before
     this unchanged legacy retry; preserve successful-render and legacy-retry side effects.
  4. `resolved_render_spec` is read only by `charts/native_chart_compositor.py`; check that the HTML dashboard
     output stays identical and set it from the payload-only builders if any consumer needs it.

  Reference: `performance-boost-step3-poc/poc2_plotstats_first_with_poc1.patch`.
- **Tests:** spy shows no `plt.subplots` for successful Plotstats charts; forced Plotstats failure gives the same
  PNG as the base fallback; identity of `full_report` and `html_dashboard_only` outputs; existing chart parity and
  renderer tests.
- **Done when:** both presets identical to the base and A/B shows the gain; reviewer pass.

### T03 — Remaining Extended chart costs
- **What / where / how:**
  - A01-F03: precomputed model curve drawn with `sns.lineplot`. In `render_density_line` (2926), use `ax.plot`
    with the same style when x is sorted and unique; keep seaborn otherwise.
  - A01-F02: `render_histogram_annotations` (961) runs `figure.draw_without_rendering()` for the whole figure,
    table included, before placing labels. Prepare only what the collision checks use. **Only if PNG bytes stay
    identical.**
  - A01-F04 / A03-F04: `_numeric_array` (461) and `exporting/export_summary_utils.py::_to_numeric_array` (30)
    walk float arrays through Python. Use a finite mask for real float dtypes and keep the scalar path for
    object/mixed input.
  - B01-F01: `charts/chart_render_spec.py` imports `scipy.stats.gaussian_kde` at module level (line 39). Import it
    on first use in `_resolve_violin_density_shape` (1299).
- **Tests:** PNG identity for every chart kind; numeric helpers exactly equal (NaN, ±inf, None, Decimal, strings).
- **Done when:** Extended identical; drop any sub-item that changes pixels and report it.
- **T03 implementation disposition (2026-10-22):** A01-F02 is dropped: preparing only the annotation axes
  changed the literal PNG for a `layout='tight'` scene containing a table when compared with the frozen
  original function. The existing whole-figure preparation and its regression assertions remain unchanged;
  the failed prototype and independent captures are retained in the packet evidence. Other T03 sub-items
  still require their own equivalence and complete Extended validation before packet completion.

### T04 — Main partitions on indexed columns (A02-F02, B04-F01, verified)
- **What:** each of the 37 partitions filters the snapshot on the computed `EXPORT_PARTITION_KEY`, so the
  snapshot's `REFERENCE` index is unused and every load scans 216k rows. An equivalent predicate on indexed
  source columns measured 3.6 → 1.27 s with identical rows and order.
- **Where:** `exporting/export_query_service.py`: `build_analytical_partition_query` (109),
  `fetch_partition_header_counts` (175), `load_export_partition_dataframe` (218),
  `load_measurement_export_partition_dataframe` (253). `exporting/export_data_thread.py`:
  `_iter_reference_partitions` (4080), `_index_export_snapshot` (4018), `_prepare_export_snapshot` (3983).
- **How:**
  - Map the typed key to a predicate:
    - `reference:<v>` → `REFERENCE = ? AND NULLIF(TRIM(REFERENCE), '') IS NOT NULL`;
    - `report:<id>` → `REPORT_ID = ? AND NULLIF(TRIM(REFERENCE), '') IS NULL`.
  - Apply it to the snapshot; add a `REPORT_ID` index to the snapshot if the plan needs one.
  - Make the row order explicit and equal to today's (snapshot insertion order).
  - Keep the current path for the live-query fallback (no snapshot).
- **Tests:** identical rows and order for references that are numeric-looking, blank, NULL, padded, Unicode and
  shared across reports; the fallback path; `EXPLAIN QUERY PLAN` uses the index.
- **Done when:** Main `fast_diagnostics` workbook identical; A/B shows the gain.

### T05 — Header-group sort without helper columns (A02-F03, A18-F02)
- **What:** `_sort_header_group` copies the RowTable, appends a temporary key column, sorts, then drops it, which
  rebuilds every full-width row.
- **Where:** `exporting/export_data_thread.py::_sort_header_group` (4655); `analytics/row_table.py`
  (`__getitem__` 283, `drop` 337).
- **How:** compute the sort keys once (dates parsed once per distinct string), stable-sort row indices with the same
  comparator and tie order, and build the result from the original rows. Add a small `RowTable` helper (take by
  indices) instead of `assign`/`drop`.
- **Tests:** identical order against the old function on mixed dates, numbers, blanks and ties; Main identical.

### T06 — XLSX packaging: parallel deflate, no packaging on cancel (C-04, A03-F01 option a, A03-F03)
- **What:** XlsxWriter 3.2.9 `Workbook._store_workbook` writes every member serially with zlib level 6 at the end
  of the export. Main spends 4.96 s CPU on deflate, 4.4 s of it on 289 MB of sheet XML; Extended 1.38 s, PNGs
  included. A
  cancelled export still serialises and compresses the whole workbook before the file is removed.
- **Where:** `exporting/export_backends.py`: `ExcelExportBackend` (599), `create_writer` (604), `close_writer`
  (610), `run` (~717); new `exporting/xlsx_parallel_package.py`.
- **How:**
  - Keep the level (`Z_DEFAULT_COMPRESSION`), member order, timestamps and ZIP64 behaviour.
  - Deflate large members concurrently in a bounded thread pool (zlib releases the GIL) and write the members in
    the original order.
  - Do not replace `zipfile` process-wide. Bind the hook to the installed XlsxWriter version, with an automatic
    fallback to stock `close()` on version mismatch or any error before the output is written.
  - Keep the temporary-file publication atomic.
  - On cancel or failure: release XlsxWriter's temporary files, write no package and leave no output.
  - E5 (level 1) is a PO decision and is not part of T06.
- **Tests:**
  - extracted members byte-identical to stock `close()` for Main, Extended and the CSV Summary workbook;
  - `zipfile.testzip()` and an openpyxl load pass;
  - fallback path covered;
  - cancel test: no file left, time bounded.
- **Done when:** reviewer pass; A/B Main and Extended.

### T07 — Caching lazy pandas proxies (C-02)
- **What:** 12 modules define `_LazyPandas`, whose `__getattr__` calls `importlib.import_module("pandas")` on every
  attribute access; `industrial/industrial_analytics_dashboard.py::_json_values` (3577) calls `pd.isna` per value
  (400k calls in one CSV analytics run). `ui/data_grouping.py` already caches the attribute (STEP2).
- **Where:**
  - modules with `_LazyPandas`:
    - `ui/tabular_analytics_grouping_dialog.py`;
    - `ui/tabular_analytics_filter_dialog.py`;
    - `tabular/tabular_analytics_service.py`;
    - `tabular/data_grouping_service.py` (also `_LazyNumpy`);
    - `tabular/csv_summary_utils.py`;
    - `shared/grouping_filter_core.py`;
    - `industrial/industrial_tabular_bridge.py`;
    - `industrial/industrial_export_service.py`;
    - `industrial/industrial_analytics_workbook_charts.py`;
    - `industrial/industrial_analytics_workbook.py`;
    - `industrial/industrial_analytics_service.py`;
    - `industrial/industrial_analytics_dashboard.py`;
  - new `shared/lazy_modules.py`.
- **How:** one shared proxy that imports on first attribute access and caches the attribute (or the module); no
  import at module load. `_json_values` is changed in T09.
- **Tests:** the pandas-free import tests (§2 MUST 5); a unit test that the proxy imports once and returns the same
  objects.

### T08 — Plotstats adapter numeric fast paths (A04-F03, A04-F04, A04-F05, A04-F02)
- **Where:** `charts/chart_numeric_helpers.py`: `as_finite_float` (14), `_raw_numeric_items` (34),
  `finite_float_list` (53), `finite_array` (62). `charts/hexafe_plotstats_adapter.py`: `_finite_values` (1080),
  `_canonical_legend_key` (2532), `_constant_line_axis_and_value` (2815),
  `_payload_with_resolved_histogram_bin_count` (1530), `build_plotstats_dashboard_spec` (562).
  The narrow caller amendment adds an explicit `preview_only=True` only in
  `charts/dashboard_visual_options.py::build_dashboard_visual_preview_spec`; ordinary adapter callers
  retain the default full-artifact computation. The shared wrapper also serves full industrial analytics,
  so a wrapper-wide or title-inferred preview optimization is excluded.
- **How:**
  - finite masks for real float ndarray/Series, returning arrays to array consumers and lists only at JSON
    boundaries;
  - A04-F02: the chart-preview path requests five distribution fits it does not show, twice per refresh;
    request only what the preview consumes;
  - in the legend key, check the semantic label before computing line geometry;
  - resolve histogram bins once per payload and carry them.
- **Tests:** exact equality of values and order (−0.0, NaN, ±inf, None, Decimal, numeric strings, mixed objects);
  identical bins; dashboard HTML identical for `csv_analytics` and the `benchmark_paths` CSV Summary path.

### T09 — Dashboard writer and time-series traces (A11-F02, A11-F01, A11-F07, A11-F04)
- **Where:** `industrial/industrial_analytics_dashboard.py`: `write_production_dashboard` (291),
  `_copy_manifest_with_plotly_budget` (1417), `_build_time_series_charts` (1598), `_chart_payload` (2892),
  `_sample_allocations` (3215), `_json_values` (3577).
- **How:**
  - clone the specs once and keep per-spec compact JSON sizes for the budget decisions (two clones and four
    measurements today);
  - decide the hybrid/static layer before raw traces are materialised, honouring `include_plotly_specs` and the
    writer thresholds;
  - correct the allocation without rescanning all groups per point;
  - `_json_values`: compute the NA mask once.
- **Tests:** dashboard HTML identical (masked timestamps); unit tests that budget/omission decisions are unchanged
  across sizes around each threshold.

### T10 — CSV Summary workbook on the bulk sheet writer (C-03)
- **What:** `tabular/tabular_xlsx_writer.py::write_tabular_dataframe` (36) writes data through XlsxWriter's per-cell
  `write_column` (4.6M `_write` calls in the `benchmark_paths` CSV Summary path; workbook export 31 of 65 s). The
  reports export already writes through `exporting/xlsx_bulk_sheet.py`.
- **Where:** `tabular/tabular_xlsx_writer.py`; `tabular/tabular_analytics_service.py::export_tabular_analytics_workbook`
  (4520); reuse `exporting/xlsx_bulk_sheet.py`: `bulk_write_enabled` (59), `plan_bulk_rows` (216),
  `BulkRowsWorksheet` (266), `write_bulk_block` (275). Compare the use in
  `exporting/export_backends.py::_extract_table_columns_and_rows` (560).
- **How:**
  1. Create the data sheets as `BulkRowsWorksheet` before pandas writes the header. pandas reuses an existing sheet
     of that name.
  2. Feed the column arrays and keep `_column_values` semantics: strings truncated to 32767, ±inf as text,
     booleans as Python bool, datetime format, blanks.
  3. Fall back to the current code for unsupported kinds.
- **Tests:**
  - Workbook members identical, including `sharedStrings.xml` order. The current writer is column-major, like
    pandas.
  - If the shared-string order cannot be kept, stop and report with a cell-by-cell equality proof; do not weaken
    the comparison.
- **Done when:** reviewer pass; `benchmark_paths --scenarios csv_summary_export_path` A/B.

### T11 — One validated grouping snapshot (A06-F01, A10-F01)
- **What:** the same 100k assignments are validated 3–4 times, partly on the GUI thread
  (`validate_industrial_analytics_request` 6.9 s in the profile, two calls); `_record_value` builds a lower-case
  dict per lookup.
- **Where:**
  - `tabular/contracts.py`: `validate_grouping_df` (30), `validate_grouping_assignments` (36), `_record_value`
    (119);
  - `industrial/contracts.py::validate_industrial_analytics_request` (65);
  - `industrial/industrial_workers.py::IndustrialAnalyticsThread` (316);
  - `ui/industrial_analytics_dialog.py`: `show_loading_screen`, `create_analytics_thread`;
  - `industrial/industrial_analytics_workflow.py::run_tabular_file_analytics` (278).
- **How:** exact key first, then one case-folded mapping per record with the same alias/None/collision precedence.
  An immutable validated snapshot bound to the grouping revision travels from the dialog to the thread to the
  workflow; public entry points still validate untrusted input.
- **Tests:** identical validation results and errors on the existing contract tests plus collision/alias cases;
  GUI stall in `csv_grouped_analytics`. Under the delivery amendment, packet timing focuses on the full-input
  validation and GUI-blocking stages; full-flow timing is separate T28 evidence and may remain PENDING.

### T12a — E6 decision input: fits-only compute pool
- **What:** the per-metric pool PoC (`performance-boost-step3-poc/poc3_metric_pool.patch`) gave −17% wall at
  +750 MB RSS and +73% total CPU. Measure the narrower design: only the distribution fits, which take about 35% of
  the flow (24 Nelder-Mead fits on 100k values), run in the shared compute pool, with warm workers and identical
  results.
- **Output:** wall, RSS and total CPU for `csv_analytics` and `benchmark_paths` with 4 workers and with 2 workers
  (`METROLIZA_COMPUTE_WORKERS=2`, the packaged Windows cap), posted on the tracker; no merge-ready code until the PO
  decides.

**Measured decision input (2026-10-23):** the fits-only pool did not improve either scenario in the
matched resource/native-math condition defined in §3. E6 remains undecided; no pool code is adopted.
Each row is an independent serial/pool ABBA block, two observations per arm. Scenario time starts
after parent imports and pool readiness; cold-command time also includes process/import/startup and
shutdown costs. Positive time reduction means faster; the negative values below mean slower.

| Flow | Workers | Scenario serial / pool (s) | Time reduction | Cold command serial / pool (s) |
| --- | ---: | ---: | ---: | ---: |
| CSV analytics | 2 | 35.003 / 40.810 | −16.59% | 40.993 / 47.932 |
| CSV analytics | 4 | 35.000 / 39.078 | −11.65% | 40.864 / 46.236 |
| Paths CSV Summary | 2 | 64.509 / 68.864 | −6.75% | 66.717 / 72.411 |
| Paths CSV Summary | 4 | 62.129 / 62.448 | −0.51% | 64.470 / 65.880 |

| Flow | Workers | Whole-command total CPU serial / pool (s) | Peak RSS serial / pool (MiB) | Peak PSS serial / pool (MiB) |
| --- | ---: | ---: | ---: | ---: |
| CSV analytics | 2 | 57.468 / 66.725 | 654.953 / 896.223 | 616.216 / 760.895 |
| CSV analytics | 4 | 57.148 / 66.587 | 647.338 / 1129.533 | 608.412 / 904.265 |
| Paths CSV Summary | 2 | 114.002 / 116.194 | 1013.686 / 1262.600 | 1002.572 / 1155.032 |
| Paths CSV Summary | 4 | 111.367 / 115.727 | 1018.840 / 1503.920 | 1007.844 / 1305.749 |

All 16 measured commands and 16 strict output comparisons exited 0. Independent original
`101e5a44` A/A and accepted-stock controls passed first, followed by all six serial/2/4-worker
functional flows and six full-output comparisons. No numerical comparison exception was added.
Full workflow input remains 100k rows; fits retain the exact original-consumed 30 Paths populations
and eight GUI populations of 50k values, including limits/configuration. Concurrent internal fit-entry
arrival differs even in original Paths A/A; its trace is diagnostic, while population multiplicity,
complete fit results, published row/order and output bytes remain gates.

The first pool variant failed complete-fit identity on KDE bits and is excluded. The second keeps
canonical KDE in the parent and delegates only non-KDE fits; six complete-result qualifications
passed in each separately recorded native-math condition. Earlier-condition results are not pooled.
The recorded [diagnostic and disposition](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6369314193)
remain evidence rather than a review or adoption decision.

Total CPU counts the owned process tree once; import, task, KDE and harness counters are descriptive
components and are not added again. RSS/PSS are sampled process-tree peaks (shared pages count in
each RSS; PSS apportions them); finite sampling may miss transients. These medians are limited
observations, not a statistical or platform-wide claim. Source/output rechecks, process termination,
resource guards and exact CPU/widget restoration passed. Shared memory/cache/thermal effects remain;
Windows and packaged-candidate behavior were not measured.

### T13 — CSV load row loop (A05-F01, A05-F03, A05-F04)
- **Where:** `tabular/tabular_analytics_service.py`: `_load_tabular_files_into_sqlite` (1709),
  `_parse_tabular_numbers` (2468), `_iter_normalized_numeric_rows` (2496), `_looks_like_identifier_number` (2527),
  `_update_metric_stats_from_row` (2535).
- **How:**
  - normalise each cell once and pass the text on;
  - build the reserved set once per file;
  - precompiled pattern with a cheap pre-check;
  - per-chunk metric statistics;
  - reuse the parsed timestamp when the date filter column is the timestamp field;
  - avoid the whole-column reparse when one cell fails.
- **Tests:** SQLite dump and metric candidates identical on `csv_100k` and edge fixtures (blank, text tokens,
  decimal comma, leading zeros, >15 digits, timestamps).

### T14 — Filter values from a report-level relation (A09a-F02, verified)
- **What:** report-level filter fields are read from the full measurement export (about 144 rows per report before
  `DISTINCT`). A report-level relation with `EXISTS(report_measurements)` measured 1.05 → 0.28 s with identical
  results on the harness DB.
- **Where:** `reports/filter_values.py`: `_query_values` (95), `load_filter_values` (108), `FILTER_VALUE_SPECS`;
  `reports/report_query_service.py`: `build_distinct_value_query` (646), `_distinct_filter_scope` (665).
- **How:**
  - unfiltered canonical scope: query report-level storage with the `EXISTS` guard;
  - filtered scope: derive the distinct report ids once in the same snapshot;
  - keep measurement-level fields on the row filter;
  - preserve the `FILENAME` alias, blank/NULL exclusion and order.
- **Tests:** equal results with orphan reports (no measurements), filename aliases, filtered scopes, blanks.

### T15 — Characteristic Mapping CTE materialised (A09a-F03)
- **Where:** `reports/characteristic_mapping_service.py::_metric_source_cte` (115).
- **How:** `AS MATERIALIZED`, guarded by the runtime SQLite version (3.35+); unchanged SQL otherwise.
- **Tests:** ordered rows equal; plan shows one measurement scan.

### T16 — Industrial bridge facets (A10-F02, A10-F04, A10-F05, A10-F09)
- **Where:** `industrial/industrial_tabular_bridge.py`: `_metadata_scope_fingerprint` (520),
  `_refresh_value_facets` (633), `_insert_base_value_facets` (671), `_insert_dynamic_value_facets` (705),
  `_dynamic_field_metadata` (758), `_create_industrial_tabular_view` (878).
- **How:**
  - group only the present values per field and add each field's blank count as scope rows minus present rows
    (today: a records × fields cross join);
  - classify numeric text once per distinct value;
  - restructure the windowed view so correlated subqueries do not run per projected row;
  - first make the scope fingerprint include the profile-name inputs of the cached labels (correctness
    prerequisite).
  - A10-F03 (defer base facets) only with E7.
- **Tests:** facet rows identical; bridge preview, counts and projected reads identical on `ind_50k` and sparse/dense
  fixtures.

### T17 — Grouping open and Modify DB records
- **Where and how:**
  - `ui/data_grouping.py`: in `populate_list_widgets` (1583), block selection signals during population and run
    one selection callback; vectorise `_ensure_group_color_integrity` (1069).
  - `shared/grouping_filter_core.py::_preview_frame` (262): build labels only for the visible page.
  - `tabular/data_grouping_service.py::build_grouping_row_index` (242): reuse the index when the filtered and full
    inputs are identical.
  - `tabular/grouping_assignment_store.py`: add an index on `group_name`.
  - `ui/modify_db.py::populate_tables` (494): fill hidden tabs on first view.
  - `ui/modify_db_records.py::add_batch` (66): build the search haystack on the first search, or in a background
    step after the first display (C-01).
  - Keep the reopen path of Grouping synchronous: draft protection depends on it (STEP2 P04).
- **Tests:** identical list content, order, colours and selection; identical search results; harness stalls.

### T18 — Registry refresh cost (A07-F02, A08b-F02, A07-F04) — conditional
- **Constraint:** the per-report `get_registry_snapshot()` refresh is deliberate. STEP2 P05 (`585a33d0`) kept it:
  there was "no cheap exact change signal that keeps the mid-import generation check fail-closed".
- **Where:** `parsing/report_parser_factory.py`: `get_registry_snapshot` (441), `_callable_accepts_keyword` (626),
  `_ensure_external_plugins_loaded_once` (1314), `invoke_parser_factory` (1639).
  `parsing/declarative_parser_profiles.py::profile_store_signature`.
- **How:**
  - Implement only an **exact** cheap signal. Example: stat tuples (`st_mtime_ns`, `st_size`, `st_ino`) of every
    configuration source, plus the disabled-ids setting. The full refresh still runs whenever the signal changes.
  - Prove fail-closed behaviour: a profile, plugin path or disabled id changed in the middle of an import must
    abort or reject exactly as today.
  - If no exact signal exists, record NOT_APPLICABLE.
  - A07-F04 (cache the keyword inspection per factory) is independent and can land alone.

### T19 — Persistence-ready rows and enrichment index (A09a-F01, A07-F03)
- **Where:** `reports/report_repository.py`: `_mapping_measurement_row` (364), `_measurement_rows` (1059),
  `_replace_full_report_payload` (1521); `parsing/cmm_report_parser.py::export_prepared_state` (1383);
  `parsing/parse_reports_thread.py`: `_selected_enrichment_identity` (1752), `_enrichment_transaction_approval`
  (1873).
- **How:**
  - original A09a-F01 carried versioned persistence-ready row tuples and exact JSON text from preparation;
    **withdrawn by C02** after full-input profiling identified costly recursive source-key validation. Use the
    existing general row writer; retain outer membership freezing, live nested values and legacy-state compatibility;
  - build an occurrence-id → identity index and an identity set once per immutable import plan, rebuilt when the
    plan is replaced.
- **Tests:** full DB dump identical (pattern of `tests/test_report_measurement_rows_equivalence.py`); enrichment
  approvals identical including duplicates; transaction/checkpoint order unchanged.

### T20 — Review token normalisation (A08a-F03, A09b-F01)
- **Where:** `cmm/block_parser.py`: `_normalize_status_token` (36), `split_status_token` (95);
  `reports/header_ocr_corrections.py`: `compact_token` (132), `canonicalize_label` (148),
  `postprocess_header_ocr_item` (360).
- **How:** return early for float tokens before string normalisation; ASCII fast path before NFKD; bounded caches
  for pure string functions.
- **Tests:** parsed blocks, headers and metadata identical over `pdf_1500` and the parser fixtures.

### T21 — Quick metadata path (A08a-F01, A08a-F02, A08b-F01, A08a-F04)
- **Where:** `parsing/review_pool.py`: `read_metadata_chunk_in_worker` (116), `read_metadata_in_order` (349);
  `parsing/metadata_review.py::read_metadata_one`; `parsing/cmm_report_parser.py`: `_extract_first_page_header_items`
  (682), `open_report` (762); `parsing/header_ocr_geometry.py::_block_candidates` (85).
- **How:**
  - seed the metadata workers with the parent's probe entries under the P07b checks (generation, fingerprint,
    source identity);
  - add a metadata-only open that extracts the same first-page header items, page count and geometry without full
    text;
  - ask PyMuPDF for text geometry without image bytes where only text is used.
- **Tests:** metadata readings identical on `pdf_1500`; P07b probe-cache tests; OCR path unchanged.

### T22 — Tabular grouping and filter dialogs (A15b-F01…F07)
- **Where:** `ui/tabular_analytics_grouping_dialog.py`: `_selector_color_map` (817), `_group_assignments` (1244),
  `_apply_group_assignments` (1360), `_sqlite_selector_preview_should_run_async` (1472),
  `_render_selector_preview` (2184); `ui/tabular_analytics_filter_dialog.py`: `_column_date_bounds` (917),
  `_accept_filter` (1013).
- **How:**
  - fill the buckets in one pass over entries sorted once;
  - memoise colour normalisation;
  - build the assignment dict from vectorised arrays;
  - keep signals blocked during async restore;
  - align the async threshold with the SQLite storage threshold;
  - cache date bounds per column and scope;
  - count once on accept.
- **Tests:** identical dialog state (assignments, colours, selections, commands); stalls in `csv_grouping_open`.

### T23 — Industrial analytics dialog, part selection, mapping editor
- **Where and how:**
  - `ui/industrial_analytics_dialog.py`: `_tabular_filtered_row_count` (1553), `_sync_grouping_summary` (2042),
    `_tabular_grouping_has_population` (2068). Cache per grouping revision and filter.
  - `tabular/tabular_analytics_service.py`: `count_source_row_numbers` (1029), `date_bounds` (1145),
    `has_rows_for_group_search` (812). Use indexable predicates and early limits.
  - `tabular/grouping_assignment_store.py::_selected_key_predicate` (~543): key lookup through a temporary keyed
    table.
  - `ui/data_grouping.py::_select_visible_parts_for_grouping` (2060): block signals, one final callback.
  - `ui/characteristic_mapping_dialog.py::_refresh_impact_preview` (~398) and
    `reports/characteristic_mapping_service.py::fetch_mapping_impact_counts` (270): debounce and load in the
    background.
- **Split:** T23a dialog/service counts, T23b part selection and mapping editor, if over about 600 lines.

### T24 — Admin and edit work off the GUI thread
- **Scope:** A09b-F02 / A09a-F05 (Modify DB apply: one connection, batched), A09b-F03 (alias CSV import/export),
  A08b-F03 (parser profile validation), B05-F01 (industrial links refresh), B08-F01 (industrial filter
  references), A09a-F07 / A09b-F04 (schema ensure on upgraded/explicit connections).
- **How:** run each through the existing background-task pattern with click-anchored indicators. Keep atomicity and
  per-record commit semantics where they are contracts.

### T25 — Cancellation latency (A10-F08, A11-F06, A14-F08, A15a-F02, A14-F07)
- **Where:** `industrial/industrial_analytics_workflow.py::_write_dashboard` (971);
  `industrial/industrial_analytics_dashboard.py`: `build_production_dashboard_manifest` (145),
  `write_production_dashboard` (291); `ui/modify_db_records.py::cancel_load_thread` (368);
  `ui/industrial_data_dialog.py` (`_stop_oznak_status_check`, `_stop_analytics_load`, ~862).
- **How:**
  - forward `cancel_check` to the manifest and writer loops (per metric, chart and serialisation step);
  - replace GUI-thread `wait()` calls with finished-signal ownership: keep the thread referenced until `finished`,
    then `deleteLater`;
  - the export cancel without packaging is in T06.
- **Tests:** cancel scenarios reach idle under 1 s after the request; no leaked threads; the Qt lifetime tests and
  the GC-policy tests stay green; repeated open/cancel/close loops without crashes.

### T26 — Group Analysis export (A18-F01, A18-F03, A18-F04, A18-F05)
- **Where:** `analytics/group_analysis_service.py`: `_group_table` (151), the readiness normalisation (~1596),
  `build_group_analysis_payload` (1872); `analytics/distribution_shape_analysis.py`
  (`_fit_profile_distributions_by_group`, ~174); `analytics/hexafe_groupstats_adapter.py` (~691).
- **How:**
  - carry the normalised table from readiness into the builder;
  - read key columns by index instead of a dict per row;
  - request the KDE reference only where it is consumed;
  - compute one-sided capability once per group.
- **Tests:** Group Analysis payload and workbook identical; `group_analysis_export` A/B.

### T27 — Hygiene
- A13-F02: application theme applied twice per open window on a theme switch.
- A10-F06: Realtime monitor imports the analytics workflow eagerly through `industrial/industrial_workers.py`.
- A16-F03: the splash `QMovie` is not stopped or deleted.
- A03-F06: workbook format cache keyed by `id(workbook)` without eviction. Advanced to the T00
  correctness prerequisite by the PO continuing-authority amendment; acceptance remains evidence-gated.
- A15a-F07: analytics dialogs retained as children on every reopen.
- A15a-F05: status refresh re-imports profiles on every refresh.

Each item lands only with its focused test and no output change.

## 6. Order, ownership and parallelism

- Waves run in order; inside a wave, packets with disjoint files may run two at a time.
- Shared files force a sequence:
  - `exporting/export_data_thread.py`: T01 → T02 → T03 → T04 → T05;
  - `industrial/industrial_analytics_dashboard.py`: T07 → T09 → T25;
  - `tabular/tabular_analytics_service.py`: T13 → T10 → T23;
  - `ui/data_grouping.py`: T17 → T23;
  - `exporting/export_backends.py`: T06 only.
- Integrate every packet on `perf/step3-boost` before the next packet that shares a file starts from it.
- After each wave: full test suite once on the integrated head, push, and CI (Linux and Windows core smoke,
  packaging smoke) before the next wave.

## 7. T28 — Final integration benchmark and report

- **Benchmark:** 18 flows of the audit plus the T00 scenarios. `101e5a44` against the final head; quiet machine,
  `balanced`, same harness file, versions rotated, n=3 (n=2 for flows over 60 s). Run the identity checks for every
  output.
- **Report:** results section (Polish, PO) in `docs/engineering/performance-boost-step3.md`, linked from the audit,
  and one results comment on the tracker. List each packet with its measured gain, identity evidence and anything
  NOT_APPLICABLE or dropped.
- **PO reporting addition (2026-10-22):** compare before STEP1, after STEP1, after STEP2 and after STEP3,
  broken down by modules/user flows and in aggregate. Show elapsed seconds and percentage time reduction
  against both the preceding stage and the before-STEP1 baseline. Bind historical measurements to their
  revisions, harness, fixture and conditions; obtain matching measurements where needed for a valid comparison,
  and explicitly mark unavailable or incomparable cells. State the common flow set and weights behind each
  sum; new scenarios stay separate from a sum that lacks earlier counterparts. This adds reporting without
  waiving the required final `101e5a44` versus STEP3 benchmark or any output/resource gate.
  Recorded with the [T02 handback](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6351520064).
- **Windows:** CI only. A packaged test EXE or Windows candidate acceptance only on the user's request.

## 8. Budget and stop rules

- Observe the Codex usage window before admitting each packet and after it. Admit the next packet only when its
  estimate fits; otherwise stop at a clean boundary (committed, pushed, tracker updated) and report.
- One full review plus at most one delta review per packet or batch. Stop after two unsuccessful attempts at a
  packet and report the blocker; do not loop.
- Value order if the window is short: T00 → T01 → T02 → T04 → T14 → T06 → T07–T09 → T10 → T13 → T16 → the rest.

## 9. Out of scope or not applicable

| Item | Reason |
| --- | --- |
| A16-F01 GC full-sweep frequency | crash-mitigation policy; needs its own stability evidence on Windows |
| A19-F01…F03 launcher | speculative; Rust launcher qualification is separate |
| A04-F06, A11-F03 PNG/zlib levels in images | changes image bytes |
| A06-F03, A14-F03 synchronous Grouping reopen | draft-protection semantics (STEP2 P04) |
| A13-F03, A13-F04, A13-F05, A15a-F06 | speculative or OS-dependent; revisit with a measured case |
| A05-F05, A15a-F04 Excel sheet listing | unmeasured; CSV is the measured path |
| A07-F01 probe cache limit (2048) | handled with #1143 (same threshold) |
| A07-F05, A10-F07, A12-F01…F03, A13-F01, A08b-F04, A02-F04…F06, A03-F02, A03-F05, B02-F01, B02-F02, B03-F01, B03-F02 | low value; take only alongside a packet touching the same code, with identity proof |
| A09a-F06, A11-F05, A16-F02, A18-F06, B06-F01 | speculative or negligible in the measured flows |
