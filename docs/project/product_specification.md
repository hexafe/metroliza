# Metroliza Product Specification

Status: Active  
Owner: Product/architecture maintainer  
Last reviewed: 2026-08-22  
Applies to: current `rc2` product line and post-RC2 development

## 1. Product definition

Metroliza is a local-first desktop application for industrial metrology and production-data
analysis. It imports heterogeneous measurement reports and tabular data, normalizes them into
SQLite-backed workflows, supports filtering and grouping, produces analysis-ready Excel output,
and generates offline interactive HTML dashboards. It also supports cache-first industrial data
workflows and explainable realtime monitoring.

Metroliza is not merely a report converter. Its product boundary includes:

- safe ingestion and normalization of measurement and production data;
- durable local data ownership in SQLite;
- repeatable analytical workflows with explicit grouping and filtering;
- statistical summaries, capability metrics, comparison analysis, and visual diagnostics;
- export and dashboard publication with deterministic fallback behavior;
- controlled extensibility through parser profiles/plugins and optional native backends;
- release-grade packaging, evidence, security, and compatibility contracts.

## 2. Product vision

Enable quality, metrology, and manufacturing engineers to move from supplier/CMM/production data
to trustworthy analysis without hand-editing spreadsheets, sending proprietary data to a remote
service, or learning a general-purpose programming stack.

The product should make the safe path the easy path:

- data stays local unless the user explicitly selects an integration such as Google conversion;
- source identity and provenance remain traceable;
- partial failures do not silently corrupt prior results;
- analysis limitations and detector explanations remain visible;
- optional acceleration never removes a deterministic Python fallback;
- packaged Windows users receive the same core behavior as source users.

## 3. Primary users

### 3.1 Metrology or quality engineer

Needs to import reports from CMMs and suppliers, correct metadata, filter characteristics, compare
samples/groups, review capability and variation, and produce a workbook or dashboard suitable for
engineering review.

### 3.2 Manufacturing or production-data engineer

Needs to fetch or import production records, retain source identity, work from a local cache,
filter/group large datasets, correlate production context with measurement results, and export
reviewable evidence without repeatedly querying production systems.

### 3.3 Operator or process owner

Needs bounded realtime monitoring, clear source-health status, explainable anomaly events,
replayable history, and a dashboard that distinguishes fresh, stale, warning, and failure states.

### 3.4 Maintainer or parser author

Needs stable contracts, deterministic tests, parser profile/plugin tooling, explicit package
boundaries, secure dependency handling, reproducible builds, and issue-driven change control.

## 4. Supported product workflows

### 4.1 Measurement-report import

1. The user selects PDF, CSV, Excel, ZIP, or another supported source.
2. Preflight identifies candidate files, validates safety/limits, and reports likely handling.
3. The parser resolver inspects bounded source content and selects a built-in parser, declarative
   profile, or approved external plugin using deterministic confidence and ambiguity rules.
4. OCR is used when required for report metadata, with packaged model/runtime diagnostics.
5. Parsed report metadata, measurements, warnings, provenance, and fingerprints are persisted
   atomically into SQLite.
6. Re-import refreshes or rejects data according to report identity and integrity contracts rather
   than silently duplicating inconsistent rows.

### 4.2 Report database review and modification

The user can inspect and edit supported report metadata such as reference, sample number, and
header values. One logical submission must be transactional and retry-safe. UI code delegates
query and write rules to report services rather than constructing ad-hoc SQL.

### 4.3 Filter, group, and export

1. The user selects a Metroliza database and output options.
2. Filters are translated into validated query scopes.
3. Optional grouping assignments identify comparison populations without polluting source data.
4. Export produces one or more of:
   - local Excel workbook;
   - offline HTML dashboard;
   - optional Google-converted workbook while preserving the local `.xlsx` fallback.
5. The result communicates success, warnings, cancellation, fallbacks, and artifact locations
   through structured outcomes.

Grouped analysis is dashboard-first for routine review. Workbook output remains available when an
editable or formal spreadsheet artifact is required.

### 4.4 CSV/Excel Summary

The user imports one or more CSV/Excel files into an internal local row store, filters and groups
rows, computes statistical summaries, and generates an offline dashboard with optional workbook
output. Large inputs must use bounded/streaming paths, stable normalized-column identity, and
controlled static-layer rendering rather than requiring full duplicate in-memory frames.

### 4.5 Industrial Data

The user configures approved production sources, runs guided filters or reviewed SQL recipes,
streams bounded results into a local cache, and analyzes cached rows through shared tabular
analytics. Production access is cache-first: routine analysis should not require repeated live
queries or a selected CMM report database.

Source credentials and diagnostics must be protected. Operator-facing logs must redact nested
credentials, URI passwords, token-like fields, and raw sensitive SQL text.

### 4.6 Realtime industrial monitoring

The user selects enabled sources and polling/replay controls. Samples, stream events, detector
results, source health, and consumer offsets are stored with transactional and monotonicity
contracts. Deterministic detectors cover specification/warning limits, robust fences/z-scores,
rolling behavior, and stale-source checks. Events include operator-readable explanations and can
be replayed without loading an unsafe serialized model.

### 4.7 Parser profiles and plugins

New supplier templates should be onboarded through declarative profiles or external parser plugins
by default. Handoff workspaces may include sanitized samples, expected-results CSV files, a
self-contained contract, validation evidence, diagnose output, repair prompts, privacy guidance,
and an approval manifest. Built-in parser changes are reserved for shared interfaces, resolver
behavior, or formats intentionally accepted as core product parsers.

### 4.8 Dashboard review

HTML dashboards operate offline and support theme selection, navigation, Plotly interactions,
static dense layers, visual recipes, chart enlargement, point search/marking, freshness/status
communication, and atomic publication. A failed generation must not overwrite the last complete
artifact or report success for an empty/missing dashboard.

## 5. Functional requirements

### 5.1 Ingestion and parsing

- **ING-001** — Accept supported report, archive, CSV, and Excel inputs through one preflighted
  import workflow.
- **ING-002** — Reject unsafe archive traversal, symlinks, unsupported members, excessive members,
  and bounded-size violations before publication into the destination.
- **ING-003** — Resolve parsers from immutable registry snapshots with deterministic confidence,
  priority, and ambiguity rules.
- **ING-004** — Share one bounded source inspection between resolver, parser, metadata, and
  provenance paths where possible.
- **ING-005** — Treat an empty parse or failed persistence as failure, not successful import.
- **ING-006** — Preserve valid final lines even when a source file has no trailing newline.
- **ING-007** — Provide OCR diagnostics that distinguish OCR extraction from filename-derived
  fallback metadata.
- **ING-008** — Publish parser-profile generations atomically and invalidate changed/removed
  registrations and caches coherently.

### 5.2 Persistence and data integrity

- **DAT-001** — SQLite is the canonical local persistence layer for report, cache, and realtime
  workflows.
- **DAT-002** — Each logical multi-statement write runs in one centralized retryable transaction.
- **DAT-003** — Failed replacement/import operations preserve the previous complete state.
- **DAT-004** — Identifier quoting, fixed query maps, typed query scopes, and bound values protect
  public data-access paths.
- **DAT-005** — Internally owned temporary stores are cleaned on success/failure; caller-owned
  stores are not deleted implicitly.
- **DAT-006** — Source identifiers, normalized columns, timestamps, and provenance remain stable
  across multi-file, cache, and replay workflows.
- **DAT-007** — User-visible grouping assignments remain session/local-analysis state unless the
  user explicitly persists them.

### 5.3 Analysis

- **ANA-001** — Provide descriptive statistics and capability metrics appropriate to two-sided and
  one-sided specifications.
- **ANA-002** — Grouped analysis supports overall and pairwise comparisons with diagnostics and
  limitations visible to the reviewer.
- **ANA-003** — Large tabular workflows can stream/filter/group without requiring duplicate full
  dataset materialization.
- **ANA-004** — Statistical/native adapters expose stable typed contracts and parity tests.
- **ANA-005** — Realtime detectors are deterministic, explainable, replayable, and validated against
  fixed fixtures.
- **ANA-006** — Invalid/blank numeric and date values have consistent semantics across pandas-like
  and SQLite-backed execution paths.

### 5.4 Export and publication

- **EXP-001** — Local Excel export remains a guaranteed artifact when selected and when optional
  Google conversion degrades.
- **EXP-002** — Dashboard-only export treats missing, empty, or failed dashboard output as failure.
- **EXP-003** — Workbook sidecar dashboard failures are warnings when the requested workbook is
  otherwise usable.
- **EXP-004** — Dashboard and other published artifacts use staging/validation and atomic promotion.
- **EXP-005** — Imported formula-like and URL-like source text remains literal in generated
  workbooks unless the product intentionally generates a formula/link.
- **EXP-006** — Google upload uses approved HTTPS hosts, bounded retry, resumable transfer for large
  files, validation, cancellation cleanup, and converted-file cleanup on fatal failure.
- **EXP-007** — Cancellation and shutdown leave no falsely completed operation or half-published
  result.
- **EXP-008** — Output results expose artifact paths, warnings, fallback state, and cancellation via
  structured outcomes rather than UI string parsing.

### 5.5 User interface

- **UI-001** — Routine workflows fit laptop-class displays without hidden primary actions or
  unbounded modal overflow.
- **UI-002** — Long-running work uses background tasks with progress, cancellation, deterministic
  ownership, and safe close guards.
- **UI-003** — Unsaved edits or active operations are not discarded by an unguarded window close.
- **UI-004** — Controls communicate validation corrections, disabled-state reasons, source health,
  freshness, warnings, and failure recovery.
- **UI-005** — Keyboard navigation and accessible names/states are part of acceptance for shared
  controls and generated dashboards.
- **UI-006** — Temporary session workspaces and files are removed only after dependent workers stop.

### 5.6 Extensibility and compatibility

- **EXT-001** — New implementation modules and imports use `src/metroliza/` and `metroliza.*`.
- **EXT-002** — Root `modules/` is compatibility-shim space only; no new implementation belongs
  there.
- **EXT-003** — Legacy shims remain until a separately approved compatibility-breaking plan proves
  import, packaging, dynamic-loading, and user migration safety.
- **EXT-004** — External parser plugins receive only documented contracts and approved local
  resources; no implicit network/subprocess capability is introduced.
- **EXT-005** — Optional native backends provide deterministic Python fallback and explicit backend
  selection/rollback controls.
- **EXT-006** — Shared packages such as `hexafe-groupstats`, `hexafe-plotstats`, and `oznak` remain
  pinned reproducibly according to release policy.

## 6. Non-functional requirements

### 6.1 Local-first and privacy

- Core parsing, SQLite, analysis, workbook generation, and HTML dashboards work without a cloud
  service.
- External integration is opt-in and clearly communicates what is uploaded.
- Logs, diagnostics, fixtures, parser handoffs, and Issues must not contain credentials, tokens,
  customer reports, proprietary drawings, or unsanitized production extracts.

### 6.2 Reliability and recoverability

- Atomic writes/publication protect prior complete data and artifacts.
- Cancellation and shutdown are deterministic.
- Bounded retries distinguish transient failures from permanent poison events.
- Replay and reproducible fixtures exist for critical parsers, realtime events, and analytical
  contracts.

### 6.3 Performance and bounded resources

- Large input paths stream or chunk work where practical.
- Query filters are pushed down before broad loads when safe and measurable.
- Dashboard density controls protect browser responsiveness.
- Performance changes require before/after benchmarks on representative workloads, not only
  microbenchmarks.

### 6.4 Security

- CI blocks secrets and newly introduced unreviewed medium/high security findings.
- Dynamic SQL boundaries are typed, quoted, allowlisted, and parameterized.
- OAuth and local credentials use private atomic files, reject unsafe targets, and never enter the
  repository.
- Dependencies, actions, Rust crates, and release artifacts are pinned/inventoried reproducibly.
- Security exceptions have owners, rationale, evidence, and finite expiry.

### 6.5 Portability and packaging

- Supported source development baseline is CPython 3.11.
- Windows packaged builds include required Qt/OCR/runtime assets and third-party notices.
- Packaged-executable smoke evidence covers startup readiness and representative core workflows.
- Optional native modules cannot make the default packaged application unusable when absent.

### 6.6 Testability and observability

- Business rules live behind services/contracts rather than only in Qt widgets.
- Critical data flows expose structured diagnostics without leaking sensitive data.
- Unit, subsystem, full-CI, native, packaging, and manual release gates are distinguishable.
- Architectural budgets prevent silent growth in cycles, complexity, and compatibility imports.

## 7. Canonical domain concepts

- **Report** — one imported measurement-report identity with metadata, provenance, warnings, and
  measurements.
- **Measurement/characteristic** — one normalized measured value with nominal/specification,
  deviation, axis/header, and report linkage.
- **Grouping assignment** — analysis-scoped mapping from selected rows/reports to named comparison
  groups.
- **Tabular row store** — local normalized representation of CSV/Excel or cached industrial rows.
- **Industrial source** — approved production source configuration with bounded query/fetch rules.
- **Industrial cache** — local source-owned/cross-source dataset used for analysis without repeated
  live access.
- **Realtime sample/event/offset** — append-only source data, detector outcome, and monotonic
  consumer progress.
- **Parser profile/plugin** — approved external description or implementation that converts a
  recognized supplier format into Metroliza's versioned parser result contract.
- **Export outcome** — structured success/warning/cancel/failure result and produced artifacts.
- **Dashboard manifest** — validated typed payload describing generated dashboard content before
  atomic publication.

## 8. Product boundaries and non-goals

The following are not current product commitments unless a new approved Issue changes scope:

- multi-tenant cloud/SaaS hosting;
- automatic upload of measurement or production data;
- general-purpose BI/data-warehouse replacement;
- collaborative concurrent editing of one local SQLite file over a network share;
- unreviewed AI-generated engineering decisions or hidden anomaly remediation;
- support for arbitrary user SQL without approved read-only boundaries;
- removal of legacy import shims during normal refactoring;
- native/Rust promotion without measured parity and packaging evidence;
- plugin execution with implicit network, shell, or unrestricted filesystem access;
- visual redesign bundled into architecture-only extractions.

## 9. Release-quality target for the first stable post-RC line

A stable post-RC release is acceptable when:

- #900 establishes green exact-head automated evidence and a canonical branch decision;
- #901 closes or explicitly blocks every manual artifact/promotion gate;
- the selected release commit has reproducible version metadata, dependency inventory, notices,
  and hashes;
- packaged Windows users can launch and complete representative parsing, SQLite, dashboard, and
  workbook workflows;
- no known unreviewed medium/high security finding or expired baseline remains;
- current user workflows and limitations are documented;
- open development work is tracked in Issues rather than embedded only in stale roadmaps;
- rollback/fallback behavior is verified for Google, native backends, dashboard publication, and
  parser persistence.

## 10. Open product decisions

- **Branch and release identity:** #900.
- **Manual artifact promotion evidence:** #901.
- **Planning-source consolidation:** #902.
- **Exporter and dashboard structural boundaries:** #903 and #904.
- **Compatibility-test migration:** #905.
- **Security exception renewal:** #906.
- **Reusable plotting package boundary:** #907.
- **Native acceleration promotion:** #908.

New product capabilities must begin as a Feature Issue that states the user problem, affected
persona/workflow, acceptance criteria, data/privacy impact, failure/rollback behavior, and required
validation tier.
