# Metroliza Product Specification

Status: Active product specification
Owner: Product/architecture maintainer  
Last reviewed: 2026-08-23
Applies to: product scope integrated through `develop`; release claims remain evidence-controlled
Product backlog epic: [#925](https://github.com/hexafe/metroliza/issues/925)
Feature catalog: [feature_catalog.md](./feature_catalog.md)

## 1. Purpose of this specification

This document defines what Metroliza is intended to do, who it serves, the product and data
boundaries it must preserve, and the acceptance contract for its major capabilities.

GitHub Issues carry implementation work. The linked feature Issue is authoritative for the detailed
scope and acceptance criteria of an in-flight capability. This specification remains the stable
product-level contract across individual implementation Issues and pull requests.

The accepted branch policy separates development from release evidence:

- `develop` is the canonical branch for normal Issue-driven development and integration;
- `release/2026.06-rc2` is the frozen release-candidate and evidence branch;
- `rc2` is a temporary historical transition/reference alias, not a routine development base;
- `master` remains the current production/history anchor and is unchanged pending the separate
  [#901 release-promotion decision](https://github.com/hexafe/metroliza/issues/901).

The authoritative branch rationale and release evidence remain in
[`docs/release_checks/`](../release_checks/), especially the
[branch transition decision](../release_checks/rc2_branch_transition_decision_2026-08-22.md) and
[release status](../release_checks/release_status.md). Product maturity statements here describe
scope and implementation maturity; they do not declare promotion or release.

## 2. Product definition

Metroliza is a local-first desktop engineering application for industrial metrology and
production-data analysis. It converts heterogeneous reports and tabular/industrial data into
traceable local datasets, supports repeatable filtering, grouping and statistical comparison, and
produces reviewable Excel, offline HTML and optional cloud-converted evidence.

The product is more than a report converter. Its supported boundary includes:

- safe import and parser resolution;
- OCR-assisted metadata extraction with human review;
- durable SQLite-backed local ownership;
- report/data curation with transactional corrections;
- typed filtering, grouping and characteristic mapping;
- descriptive, comparative, capability and distribution analysis;
- dashboard-first exploration and stable spreadsheet artifacts;
- cache-first production-data access;
- explainable replayable realtime monitoring;
- reproducible workspaces, presets, run manifests and evidence bundles;
- controlled parser/analysis/report extensibility;
- optional measured Python/Rust acceleration with deterministic fallback;
- supported packaging, diagnostics, security and release evidence.

## 3. Product vision

Enable quality, metrology, manufacturing and process engineers to move from supplier, CMM,
production and flat-file data to trustworthy engineering evidence without hand-rebuilding
spreadsheets, writing custom scripts for every workflow, or sending proprietary data to an
uncontrolled remote service.

The safe path must be the easy path:

- data remains local unless the user deliberately chooses an external integration;
- provenance survives import, correction, analysis and export;
- uncertain metadata remains reviewable rather than silently trusted;
- partial failures, cancellation and fallbacks remain visible;
- statistical assumptions and limitations remain attached to results;
- large workloads use bounded paths rather than unpredictable memory exhaustion;
- optional acceleration cannot remove a supported reference/fallback behavior;
- packaged users receive the same supported core contracts as source users;
- chat history and experimental branches never become the only record of a project decision.

## 4. Product principles

### 4.1 Local-first and explicit external boundaries

Core import, SQLite persistence, filtering, grouping, analysis, workbook generation, offline HTML,
replay and diagnostics work locally. Google conversion and any future external integrations are
opt-in and identify what leaves the machine.

### 4.2 Correctness before convenience or speed

Metroliza must not silently repair malformed input, select an ambiguous parser, hide invalid data,
or accept numerical drift because an implementation is faster. Performance work begins with
fixtures, profiling and parity.

### 4.3 Traceable evidence rather than opaque output

An output should identify its source state, parser/profile, configuration, methods, warnings,
application build and relevant extension/backend identity. A user must be able to distinguish
source data, accepted corrections, analysis decisions and local review annotations.

### 4.4 Atomic state and honest outcomes

Logical writes and artifact publication are atomic where practical. A failed operation must not
replace a previously complete state or report a complete-looking partial artifact as success.
Structured outcomes distinguish success, success with warnings, partial batch, cancellation,
fallback and failure.

### 4.5 One product contract across UI, CLI and automation

PyQt, CLI and scheduled jobs are adapters over shared application/domain services. Widgets,
workbook cells and generated HTML are not independent sources of statistical truth.

### 4.6 Controlled extensibility

Declarative parser profiles are preferred over executable code. Executable parser, analysis,
report and native extensions use narrow versioned contracts, explicit trust levels, deterministic
validation, dependency/security review and rollback.

## 5. Primary personas

### 5.1 Metrology or quality engineer

Imports CMM/supplier reports, reviews metadata, filters characteristics, groups samples, compares
populations, evaluates capability/variation, and produces evidence for engineering review.

### 5.2 Manufacturing or production-data engineer

Fetches or imports production records, retains source identity, works from a local cache, filters
and groups large datasets, correlates production context with measurements, and shares reviewable
results without repeatedly loading production systems.

### 5.3 Operator or process owner

Needs bounded monitoring, honest source freshness, explainable anomaly events, reliable restart,
replay, acknowledgement/review state and a dashboard that distinguishes warning, stale and failure.

### 5.4 Maintainer, analyst or parser author

Needs stable contracts, sanitized fixtures, reproducible builds, parser/profile tools, explicit
package/native boundaries, issue-driven scope and reliable test/release gates.

### 5.5 Reviewer or recipient

Needs to open an offline dashboard, workbook or evidence bundle on another supported machine,
verify provenance/integrity, understand warnings and distinguish current data from a historical
baseline without requiring repository access.

## 6. Product scope and maturity model

A feature can be:

- **release-candidate** — substantial behavior exists in the current candidate lineage, but the
  supported-release acceptance gate is not fully closed;
- **partial** — components exist, but no single coherent supported workflow exists;
- **experimental** — code/research exists behind opt-in, limited rollout or unresolved contracts;
- **planned** — the outcome is approved for the roadmap but not implemented as a supported flow;
- **decision required** — existing code/scope needs retain, extract, redesign or removal approval.

The complete maturity map and Issue links live in [feature_catalog.md](./feature_catalog.md).

## 7. Canonical end-to-end product flow

```text
Acquire or select source
    -> preflight and identify
        -> parse / OCR / normalize
            -> validate and review
                -> persist local canonical state
                    -> filter / group / map / configure
                        -> analyze and compare
                            -> visualize / export / share
                                -> record manifest / history / reproduce
```

Each stage returns typed data plus warnings/errors. Presentation layers may format those outcomes,
but cannot redefine their meaning.

## 8. Supported workflow specifications

The numbered workflow sections catalogue product capabilities; their numbering is not dependency
order. Authoritative strict prerequisites live in the feature Issues and
[feature catalog](./feature_catalog.md), while the [roadmap](./roadmap.md) orders foundational and
downstream delivery.

### 8.1 Workspace lifecycle — #926

A user can create, save, reopen, relink and validate a versioned analysis workspace containing
source references/fingerprints, stores, filter/group/mapping state, analysis configuration, visual
settings and output intent. Credentials and source measurements are not embedded by default.

Reopening determines whether the workspace is equivalent, stale, changed, partially unavailable or
newer than the application supports. Missing/moved inputs require explicit relinking; changed input
cannot be silently substituted.

The #926 schema/service foundation precedes and is consumed by #945 application-shell integration.

### 8.2 Unified import — #927

The user selects files, folders or supported archives. A non-destructive bounded preflight reports
candidate parser/profile, confidence, likely OCR path, duplicate/changed state, unsupported or
ambiguous inputs and safety violations. Import supports per-item status, aggregate progress,
cancellation, retry/resume and explicit duplicate policy.

A logical report is persisted atomically. Completion counts agree with actual database state and
separate imported, skipped, warned, failed and cancelled items.

#927 owns the orchestration and parser/OCR ports; #928 and #929 complete their downstream lifecycle
integrations over those accepted ports.

### 8.3 Parser profiles and plugins — #928

New supplier/machine templates use declarative profiles by default. Profiles have a versioned
schema, deterministic content-based probing, expected-results evidence, atomic install/update,
enable/disable/rollback and resolver diagnostics. Ambiguity is rejected visibly.

Advanced executable plugins have a stricter trust/security policy and do not enter the active
registry without validation and approval.

### 8.4 OCR metadata review — #929

Native text extraction is attempted where appropriate; OCR is a bounded adapter with model/runtime
integrity and diagnostics. Field candidates retain method/source/confidence/review state. An
uncertain candidate does not silently overwrite accepted metadata.

Users can accept, edit, reject or defer candidates. Optional background enrichment is cancellable,
idempotent and cannot duplicate measurements or corrupt an imported report.

### 8.5 Database and cache lifecycle — #930

Report databases and industrial caches have schema identity, compatibility checks, transactional
migrations, pre-migration backup, integrity checks, verified backup/restore and safe read-only
fallback where migration cannot complete.

Active databases cannot be overwritten by their own backup/archive action. Internally owned
temporary stores are cleaned deterministically; caller-owned stores are not deleted implicitly.

### 8.6 Report/data curation — #954

Users can search and inspect report provenance, warnings, parser/profile identity and measurement
summaries; correct supported typed metadata; resolve OCR candidates; perform bounded bulk edits;
manage aliases/exclusion through domain actions; and preview destructive scope.

One logical edit submission is transactional. Source-derived and user-corrected values remain
traceable, and affected workspaces/results become visibly stale.

### 8.7 Filtering — #931

One typed filter model supports report, tabular and industrial workflows, including equality,
inequality, ranges, contains, missing/blank, `IN`/`NOT IN`, grouped boolean conditions, preview and
versioned serialization.

In-memory and SQLite adapters share conformance fixtures. Values are bound; identifiers are
validated/quoted. Numeric/date/text coercion, invalid values, blanks, case and locale-independent
storage have explicit semantics.

#931 can close on the canonical contract, reference adapters/fixtures and foundational report
slice. The #939 tabular and #940 industrial adapters must pass those fixtures before their own
Issues close, but do not block #931.

### 8.8 Grouping and characteristic mapping — #932

Users can create manual and rule-based groups; preview counts, overlaps, unassigned/excluded rows;
name/order/style groups; and save reusable presets. Stable identities are separate from labels and
colors.

Characteristic aliases use documented reference-scoped and global precedence. Ambiguity or
collision is diagnosed instead of silently selected. Session-local assignments do not pollute
source data.

#932 owns the grouping/alias foundation consumed first by #933 descriptive/pairwise analysis and
then by #934 capability/distribution/risk analysis.

### 8.9 Presets/templates — #935

Named versioned presets describe compatible data selection, grouping, analysis, visualization and
output intent. Applying a preset previews changes, validates required fields and reports unsupported
or remapped options. Presets contain no credentials or source values and are distinct from complete
workspaces.

### 8.10 Group statistics and pairwise comparison — #933

For configured groups and characteristics, Metroliza validates sample availability and returns
descriptive statistics, pooled/overall context, pairwise comparisons, effect sizes, supported
confidence information, method/assumption metadata and low-sample/invalid-data warnings.

Statistical significance, effect magnitude and engineering relevance are not conflated. Results
are numerically identical across consumers of the same result model.

### 8.11 Capability, distribution and risk analysis — #934

Metroliza provides documented descriptive/robust statistics, two-sided `Cp`/`Cpk`, one-sided
`Cpu`/`Cpl`, explicit pooled/per-group scope, supported intervals or unavailable reasons,
distribution-shape evidence, candidate fits and goodness-of-fit/information metrics.

Poor fit preserves empirical evidence and warnings rather than fabricating confidence. Stochastic
methods record seed/configuration and pass reproducibility tolerances. Charts do not independently
refit data.

### 8.12 Cross-dataset baselines — #948

Users can create versioned draft/approved/superseded/retired baseline snapshots containing data or
references according to an explicit portability/confidentiality mode. Compatibility checks cover
schema, characteristic mapping, units, filters and methods.

Approved baselines are immutable. Current-versus-baseline results distinguish engineering
thresholds from statistical evidence and preserve both dataset identities and data-through ranges.

#948 consumes the #949 run-history/manifest foundation; later #953 packaging does not block the
baseline library.

### 8.13 Excel export — #936

The workbook exporter consumes canonical results and produces validated measurement sheets,
summaries, selected charts and provenance/warning metadata with deterministic ordering, sheet-name
collision handling, units and number formats.

Imported formula-like or URL-like text remains literal unless Metroliza deliberately owns the
formula/link. Publication is atomic; failure/cancellation does not leave a complete-looking corrupt
artifact. Size limits and graceful-degradation behavior are documented.

### 8.14 Offline HTML dashboard — #937

The dashboard opens offline on supported browsers and presents overview/provenance, warnings,
section navigation, group/pairwise/capability/distribution evidence, interactive Plotly charts,
static/dense-layer fallbacks, themes, visual preferences and local point marks.

DOM IDs, storage keys and manifest/payload schemas are versioned/tested. Plotly/browser failures
produce visible usable status/fallback, not blank panels. Publication is atomic and preserves the
last complete output.

#937 owns the core dashboard and baseline accessibility contract. #946 hardens accessibility
across the product, and #947 then adds reusable recipes/annotations over #937/#946.

### 8.15 Google conversion — #938

Google conversion is optional post-processing. A validated local `.xlsx` is preserved regardless
of cloud outcome. OAuth uses least supported privilege and private local token handling. Network
requests fail closed outside approved HTTPS hosts.

Uploads use bounded multipart/resumable transfer, safe retry, cancellation/timeout cleanup and
post-conversion tab/content validation. Results identify converted success, warnings, fallback,
cancellation or failure without leaking credentials.

### 8.16 CSV/Excel Summary — #939

Single or multiple CSV/Excel inputs preserve source-file and original-column identity, support
explicit type review/override, and use in-memory or SQLite-backed modes according to bounded
workload policy. Shared filters/groups/analysis contracts drive dashboard-first output and optional
workbooks.

Changed source snapshots invalidate or explicitly refresh reuse. Sampling/static visualization is
declared and does not silently change full-data calculation.

#939 is a downstream consumer of #931 and adds tabular adapters plus workflow-specific conformance
evidence without redefining canonical filter semantics.

### 8.17 Industrial/Oznak analytics — #940

Approved source profiles define table/view/column or reviewed read-only SQL boundaries. Credentials
are stored separately. Access check, preview, multi-source bounded fetch, row limits, explicit
fetch-all, timeout, cancellation and chunked atomic/explicit-partial cache persistence are supported.

Routine analysis is cache-first and does not require a CMM database. Dynamic fields remain
available through filters, dashboards and workbooks. Source health, lag and data-through time remain
visible.

#940 follows #939, consumes #931 and adds industrial adapters plus applicable shared-conformance
evidence without creating a prerequisite back to the filter foundation.

### 8.18 Realtime monitoring and replay — #941

Approved sources/signals use explicit event-time, arrival-time, timezone, ordering, late-data,
window, warm-up, reset and missing-data contracts from #919. Polling is bounded and offsets are
monotonic. Samples, detector events and consumer progress are persisted with restart recovery.

Supported transparent detectors include specification/warning limits, IQR, robust MAD z-score,
rolling z-score and stale-source checks. Alerts retain versioned configuration/window/evidence and
operator states. Replay uses the same detector interface. Advanced models remain optional and must
beat defined baselines for the operational cost.

### 8.19 Headless CLI — #942

A supported CLI exposes stable commands for relevant preflight, import, analysis, export, replay,
workspace validation and diagnostics. Versioned workspace/configuration files are preferred over
undocumented flag combinations.

Human and JSON outputs, stable exit codes, explicit overwrite/duplicate policy, interrupt cleanup
and display-independent execution are documented and tested against desktop/service parity.

### 8.20 Watched folders and scheduled jobs — #943

Local unattended jobs reference a workspace/preset, approved input source, target store and output
location. Watched files must satisfy a stability rule. Single-instance/locking, explicit duplicate
and overwrite policies, restart recovery, quarantine, retention, pause/cancel/retry and per-run
manifests are required.

Automation never guesses through parser ambiguity or metadata conflict.

#943 consumes the #949 run-history/manifest foundation for unattended jobs.

### 8.21 Diagnostic bundle — #944

Desktop/CLI can create a previewable sanitized bundle containing application/build/platform,
selected schema/configuration shape, backend/OCR/parser state, structured workflow events, error
codes and stage timings. Credentials, tokens, private keys, connection passwords, raw SQL and raw
measurements are excluded by default.

Redaction is deterministic/tested. Optional attachments remain the user’s explicit responsibility.

#944 closes with the shared diagnostic envelope, redaction/bundle contracts and reference adapters.
Workflow-specific parser, OCR, Google, industrial, realtime and automation payloads are downstream
integrations owned by those workflows.

### 8.22 Application shell and preferences — #945

The application identifies active workspace/database/cache/source, coordinates windows and tasks,
protects unsaved/active work on close, distinguishes user preferences from analysis configuration,
handles recent/missing paths and shows surviving output/fallback actions consistently.

Preferences are versioned, recoverable and non-sensitive.

### 8.23 Accessibility — #946

The canonical desktop flow and generated dashboard are keyboard-completable with logical focus,
visible focus, meaningful accessible names, non-color severity/group/selection cues, scalable text
and compact-display behavior. Dialog/lightbox focus is trapped/restored correctly and runtime
fallback status is accessible.

Formal certification is not claimed without an appropriate audit; supported baseline and known
limitations remain explicit.

#946 consumes the core #937 dashboard and #945 shell contracts before #947 visual recipes.

### 8.24 Visual recipes and annotations — #947

Presentation-only recipes control compatible palette, opacity, point size, overlays and layout
without altering analysis values. Built-ins are theme-aware and colorblind-safe. Local point marks
and annotations remain separate from source data and identify the result snapshot they reference.

Compatibility/fallback is explicit across HTML and static renderers.

#947 consumes #937/#946; it does not define the core dashboard or accessibility foundations.

### 8.25 Run history and reproducibility manifest — #949

Every supported run can record stable run ID, application/build, parser/profile/schema/method
versions, source/store identities or fingerprints, configuration, warnings/outcome/timings, artifact
paths/hashes and parent/derived relationships.

Rerun status distinguishes equivalent, changed input, changed configuration, changed method and
unavailable. Default manifests contain no credentials or raw measurements.

#949 owns the accepted interactive/CLI run identity, manifest and history foundation. #943
automation, #948 baselines and #953 bundles consume it later.

### 8.26 Evidence bundle — #953

Users can select validated outputs, run manifest, workspace/preset and optional explicitly
sanitized data to create an atomic portable package with relative links, hashes, schema/version and
human-readable README. “Outputs only” is the safe default. Archive format alone is not treated as
confidentiality protection.

### 8.27 Contextual help — #955

Primary workflows expose concise contextual help, explanations for high-risk decisions and
disabled states, links to current local/canonical manuals, troubleshooting/diagnostic actions and
safe GitHub feedback guidance. Help and release notes are tied to build/version where practical.

### 8.28 LLM-assisted parser creation — #950

Metroliza can prepare a minimal privacy-reviewed handoff package containing schema/contract,
sanitized sample, expected-results template, prompts and manifest; quarantine generated output;
run static/schema/security and deterministic expected-results validation; produce a bounded repair
report; and require explicit approval/install/rollback.

LLM output remains an untrusted proposal. No report is uploaded automatically.

#950 consumes the accepted #928 parser lifecycle and #951 extension interfaces; generated artifacts
cannot define those foundations.

### 8.29 Extension interfaces — #951

Parser, analysis and report/visual extensions use narrow versioned contracts with capability
discovery, compatibility checks, structured errors, lifecycle/rollback, trust levels, dependency
and license/security review, packaging behavior and run-manifest identity.

Analysis extensions cannot depend on PyQt widgets. Report extensions cannot silently recalculate
domain statistics.

#951 owns the stable extension-interface foundation and precedes the optional #950 AI workflow.

### 8.30 Predictable large-workload behavior — #952

Import, query, tabular, grouping, statistics, chart, Excel, dashboard and realtime workflows have
representative workload classes, end-to-end timing/memory evidence, bounded reads/writes, visible
memory-vs-SQLite and sampling/static policies, responsive background execution, cancellation and
cleanup.

Unsupported sizes fail early or visibly degrade rather than exhausting resources unpredictably.

#952 owns the shared workload, bounded-behavior, telemetry and cancellation envelope. #939, #940
and #941 add workflow-specific evidence before their own closure without blocking #952 on their
complete product workflows.

### 8.31 Legacy and licensing decisions — #956 and #957

Deprecated Group Comparison/BOM surfaces receive retain, replace, extract, migrate or remove
decisions with dependency/data inventory, supported replacement, compatibility window and release
notes. Existing code is not sufficient reason to keep permanent scope.

Licensing/activation receives a public/internal distribution decision, threat/privacy model,
supported startup/recovery contract and packaged evidence—or is extracted/removed cleanly. Signing
secrets are never embedded.

## 9. Functional requirement catalogue

### 9.1 Workspace and configuration

- **WSP-001** — Workspace files have a versioned schema and migration/unsupported-version policy.
- **WSP-002** — Workspace state separates portable configuration, machine paths, user preferences,
  credentials and source data.
- **WSP-003** — Missing, moved or changed referenced inputs are detected before reproduction.
- **WSP-004** — Workspace dirty state includes analysis-relevant configuration changes.
- **WSP-005** — Recovery/autosave does not overwrite a valid user workspace silently.
- **WSP-006** — Presets are versioned, previewable and compatible only with validated schemas.
- **WSP-007** — Visual recipes cannot alter statistical configuration.
- **WSP-008** — Workspace/preset identity is retained in run/report provenance.

### 9.2 Ingestion, parsing and OCR

- **ING-001** — Accept supported file/folder/archive sources through one preflighted import model.
- **ING-002** — Preflight is bounded and non-destructive.
- **ING-003** — Reject traversal, links, unsupported archive members and configured size/count
  violations before extraction publication.
- **ING-004** — Resolver uses immutable registry snapshots and deterministic confidence/priority/
  ambiguity rules.
- **ING-005** — Suffix alone cannot prove report-family identity.
- **ING-006** — Empty parse or failed persistence is failure, not successful import.
- **ING-007** — Valid final lines remain parseable without a trailing newline.
- **ING-008** — Retry/resume and duplicate policies are explicit and idempotent.
- **PAR-001** — Parser/profile identity, version/hash and source fingerprint survive provenance.
- **PAR-002** — Approved profiles carry expected-results evidence and atomic lifecycle.
- **PAR-003** — Disabled/removed profiles do not remain selected through stale registry/cache state.
- **PAR-004** — Executable plugins have stricter trust and security gates than declarative profiles.
- **OCR-001** — OCR candidates retain extraction method/source and review state.
- **OCR-002** — OCR uncertainty/conflict cannot silently overwrite accepted metadata.
- **OCR-003** — Background enrichment is cancellable, idempotent and measurement-preserving.
- **OCR-004** — Official packaged OCR operates offline with verified bundled assets/notices.

### 9.3 Persistence, curation and integrity

- **DAT-001** — SQLite is the canonical local persistence layer for supported stores.
- **DAT-002** — Logical multi-statement writes use centralized retryable transactions.
- **DAT-003** — Failed replacement/migration preserves the previous complete state.
- **DAT-004** — Schema version, migration, backup and integrity checks are explicit.
- **DAT-005** — Bound values and validated/quoted identifiers protect public query paths.
- **DAT-006** — Internally owned temporary stores are cleaned; caller-owned stores are not deleted.
- **DAT-007** — Source identity, timestamps, normalized columns and provenance remain stable.
- **CUR-001** — User corrections retain before/after and source-versus-user origin.
- **CUR-002** — Bulk/destructive edits preview scope and commit atomically.
- **CUR-003** — Relevant edits mark affected workspaces/results stale.
- **CUR-004** — Deletion/replace includes explicit impact and recovery/backup guidance.

### 9.4 Selection and preparation

- **FIL-001** — One typed filter contract compiles to supported in-memory and SQLite adapters.
- **FIL-002** — Invalid, missing, blank, numeric/date/text and case semantics are documented/tested.
- **FIL-003** — Preview and final execution use the same compiled filter.
- **FIL-004** — Saved filters detect incompatible, missing or renamed fields.
- **FIL-005** — Arbitrary SQL is not accepted by the general filter builder.
- **GRP-001** — Group identities are stable and separate from display labels/colors.
- **GRP-002** — Preview exposes overlaps, unassigned and excluded rows.
- **GRP-003** — Session-local grouping does not pollute source data.
- **GRP-004** — Alias precedence/collision behavior is deterministic and visible.
- **GRP-005** — GUI/dashboard/workbook consume identical group identity/order.

### 9.5 Analysis

- **ANA-001** — Methods define sample, missing/excluded, ordering, degrees-of-freedom and tolerance
  conventions.
- **ANA-002** — Group/pair output identifies groups, sample counts, method, effect and warning/
  interval status.
- **ANA-003** — Statistical significance, effect magnitude and engineering threshold are distinct.
- **ANA-004** — Pooled and per-group results are structurally/visually unambiguous.
- **ANA-005** — One-sided capability never displays undefined two-sided capability as valid.
- **ANA-006** — Poor/failed fit preserves empirical evidence and visible limitation.
- **ANA-007** — Stochastic methods record seed/configuration and reproducibility tolerance.
- **ANA-008** — Python/package/native implementations pass value, ordering and error parity where
  they claim the same contract.
- **ANA-009** — Renderers consume results and do not independently recompute/refit statistics.
- **ANA-010** — Baseline comparison validates schema, mapping, units and methods before execution.

### 9.6 Reporting and publication

- **REP-001** — One canonical result/report metadata schema drives GUI and outputs.
- **REP-002** — Outputs identify source/configuration/build/method/warnings and relevant extension.
- **REP-003** — Volatile metadata is isolated to keep regression tests meaningful.
- **XLS-001** — Excel structure, sheet naming, ordering, units and formats are deterministic/tested.
- **XLS-002** — Imported formula/URL-like text remains literal unless deliberately generated.
- **XLS-003** — Workbook publication/validation prevents complete-looking corrupt partial output.
- **DSH-001** — HTML dashboard is offline and has stable manifest/DOM/storage contracts.
- **DSH-002** — Browser/Plotly failure produces visible usable status/fallback.
- **DSH-003** — Sampling/static layers and freshness/data-through are declared honestly.
- **DSH-004** — Dashboard publication is atomic and preserves prior complete output.
- **GGL-001** — Google conversion is optional and cannot remove the local fallback.
- **GGL-002** — OAuth/token/network boundaries are least-privilege, private and host-restricted.
- **GGL-003** — Transfer retry/resume/cancellation/cleanup and converted-content validation are
  explicit.
- **SHR-001** — Evidence bundles preview included data/identifiers and default to outputs-only.
- **SHR-002** — Bundle hashes/schema and relative links support verification and portability.

### 9.7 Tabular, industrial and realtime

- **TAB-001** — Multi-file source and original-column identity survive normalization.
- **TAB-002** — Type inference is reviewable/overridable and invalid values remain diagnosable.
- **TAB-003** — In-memory and SQLite-backed modes pass equivalent conformance fixtures.
- **TAB-004** — Changed inputs invalidate/revalidate reusable snapshots.
- **IND-001** — Production access requires approved enabled source configuration.
- **IND-002** — Credentials are separated/redacted from config, logs and artifacts.
- **IND-003** — Fetch is bounded, cancellable and accurate about saved rows/partial outcomes.
- **IND-004** — Routine analysis is cache-first and dynamic fields survive through output.
- **IND-005** — Source health/lag/data-through remains visible.
- **RT-001** — Event/arrival time, ordering, late data, window, warm-up/reset and missing behavior
  are versioned contracts.
- **RT-002** — Samples/events/offsets commit and recover without duplicate/lost committed events.
- **RT-003** — Alerts include source/signal/detector/config/window/evidence identity.
- **RT-004** — Replay and live use the same detector interface.
- **RT-005** — Advanced models are optional and evaluated against transparent operational baselines.
- **RT-006** — Realtime never performs automatic process actuation.

### 9.8 Automation, traceability and diagnostics

- **AUT-001** — CLI and GUI share application/domain services.
- **AUT-002** — CLI commands have documented side effects, JSON schema and stable exit codes.
- **AUT-003** — Interrupt/cancel leaves stores/artifacts valid.
- **AUT-004** — Watched jobs wait for file stability and quarantine ambiguity/failure.
- **AUT-005** — Job restart/locking prevents duplicate commits and target-store corruption.
- **TRC-001** — Runs have stable identity and versioned reproducibility manifests.
- **TRC-002** — Manifest distinguishes source data-through, analysis and artifact generation times.
- **TRC-003** — Artifact hashes and changed-input/config/method status are available.
- **TRC-004** — Default history/manifest contains no credentials or raw measurements.
- **DIA-001** — Diagnostic bundle is previewable and sanitized by default.
- **DIA-002** — Redaction covers nested credentials, URIs, headers, environment, SQL and token-like
  values.
- **DIA-003** — Diagnostic generation is atomic and works in packaged builds.

### 9.9 UX, accessibility and help

- **UI-001** — Active workspace/database/cache/source is visible in every major workflow.
- **UI-002** — Background work has progress, cancellation, deterministic ownership and close guards.
- **UI-003** — Unsaved edits are not discarded without save/discard/cancel decision.
- **UI-004** — Completion actions target the actual surviving artifact after fallback/cancellation.
- **UI-005** — Preferences are versioned, recoverable, non-sensitive and distinct from analysis.
- **ACC-001** — Canonical workflow is keyboard-completable with logical/visible focus.
- **ACC-002** — Interactive controls have meaningful accessible names and status.
- **ACC-003** — Severity/group/selection does not rely on color alone.
- **ACC-004** — Text/display scaling preserves primary actions on supported displays.
- **HLP-001** — Primary workflows expose contextual current help and high-risk consequence text.
- **HLP-002** — Disabled/invalid controls expose an actionable reason.
- **HLP-003** — Support guidance warns against public confidential attachments.

### 9.10 Extensibility, AI, performance and lifecycle

- **EXT-001** — Canonical implementation/import path is `src/metroliza/` / `metroliza.*`.
- **EXT-002** — Root `modules/` remains compatibility-only until separately approved removal.
- **EXT-003** — Extension interfaces are versioned, capability-discoverable and fail before
  execution when incompatible.
- **EXT-004** — Analysis extensions cannot use widget state; report extensions cannot recalculate
  domain statistics silently.
- **EXT-005** — Extension identity/version/hash appears in provenance where applicable.
- **AI-001** — LLM handoff is minimal/privacy-reviewed/provider-neutral.
- **AI-002** — Generated output remains quarantined until deterministic validation and approval.
- **AI-003** — Repair evidence contains only approved minimal data.
- **PER-001** — Primary workflows have representative end-to-end timing/memory benchmarks.
- **PER-002** — Bounded resource, progress, cancellation and cleanup behavior is documented.
- **PER-003** — Sampling/static visualization never silently changes full-data calculation.
- **PER-004** — Native promotion requires parity, user-workflow gain, packaging and maintenance
  evidence.
- **LIF-001** — Deprecated features have replacement, compatibility window and migration/removal
  decision.
- **LIC-001** — Licensing is retained/extracted/redesigned/removed explicitly, not maintained by
  accident.
- **LIC-002** — Retained licensing has reviewed privacy/security/recovery and no embedded signing
  secret.

## 10. Canonical domain concepts

- **Source artifact** — selected file, archive member, tabular source, industrial source or replay
  source with identity/fingerprint and acquisition context.
- **Report** — one imported report identity with parser/profile, metadata, provenance, warnings and
  measurements.
- **Characteristic/measurement** — normalized identity, value, unit, nominal/specification,
  deviation, sample/report linkage and explicit missing/invalid/excluded state.
- **Metadata candidate** — extracted value with method/source/confidence/review state.
- **Validation issue** — stable category/code, severity, recoverability and source/domain context.
- **Filter expression** — versioned typed condition tree independent of storage adapter.
- **Group definition/assignment** — stable analysis-scoped group identity, rule/manual membership,
  display metadata and provenance.
- **Analysis configuration** — versioned method/options/tolerances/seed and selected data identity.
- **Analysis result** — presentation-independent numerical values, assumptions, warnings, ordering
  and provenance.
- **Report/dashboard model** — typed tables/charts/sections and canonical metadata consumed by
  renderers.
- **Workspace** — versioned user project connecting sources, stores, configuration and output
  intent without credentials/source embedding by default.
- **Preset** — reusable compatible configuration subset, distinct from complete workspace.
- **Run manifest** — stable run identity connecting inputs/configuration/outcome/artifacts.
- **Industrial cache** — local bounded persisted production rows and source context.
- **Realtime sample/event/offset** — ordered acquired value, detector evidence/operator state and
  monotonic progress.
- **Extension identity** — interface/type/id/version/hash/trust and capability metadata.
- **Evidence bundle** — selected portable artifacts plus manifest/hashes/readme.

## 11. Target architecture and dependency direction

```text
PyQt / CLI / automation adapters
        -> application use cases and jobs
            -> canonical domain models and contracts
                -> ports
                    <- parsers / OCR / SQLite / industrial / replay adapters
                    <- Python, package, or Rust analysis implementations
                    <- Excel, HTML, Google, manifest, bundle renderers
```

Rules:

1. UI widgets do not own statistical, parser or persistence behavior.
2. Application/domain tests run without a GUI process.
3. Raw extraction, parser-specific representation, normalization and validation are distinct.
4. Reports/renderers consume result models and do not read live widget state.
5. Rust/package implementations sit behind stable contracts with structured errors and parity.
6. Realtime adapters are isolated from file-analysis UI orchestration while sharing deliberate
   domain concepts.
7. `modules.*` remains compatibility-only; new implementation uses `metroliza.*`.
8. Directory movement is not architecture unless dependency direction/contracts improve.

Detailed current/target boundaries live in [architecture.md](./architecture.md) and #922.

## 12. Non-functional requirements

### 12.1 Correctness and reproducibility

- Curated sanitized fixtures define supported parser/analysis/report behavior.
- Numerical behavior changes are deliberate release changes, not incidental refactors.
- Ordering, tolerance, seed and unavailable/error behavior are documented.
- Outputs can be traced to source/configuration/build/method identity.

### 12.2 Reliability and recoverability

- Atomic transactions/publication protect prior complete state.
- Cancellation and shutdown have deterministic cleanup/order.
- Temporary state has explicit ownership.
- Retry distinguishes transient failure from permanent/poison input.
- Backup, replay and manifests support recovery/diagnosis.

### 12.3 Privacy and security

- Credentials, OAuth tokens, private keys, customer reports, proprietary drawings and unsanitized
  production extracts are never committed or included by default.
- External integration is opt-in and host/scope restricted.
- SQL values are bound and identifiers are fixed/validated/quoted.
- Secret/dependency/static security checks block newly introduced unreviewed serious findings.
- Exceptions have owner/rationale/evidence/finite expiry.
- Diagnostic/handoff/evidence packaging previews included content.

### 12.4 Performance and bounded resources

- Representative workload classes define supported expectations, not one universal time.
- Large paths stream/chunk/query-pushdown where safe.
- GUI remains responsive and jobs cancel safely.
- Sampling/static layers are visible and calculation scope remains explicit.
- Performance claims include correctness, environment, fixture, repeated results and complexity cost.

### 12.5 Portability and packaging

- CPython 3.11 is the current source/release baseline unless #920 changes it.
- Supported OS/architecture/browser/package matrix is explicit.
- Official Windows builds include required Qt/OCR/native-optional assets and third-party notices.
- Clean-machine smoke covers startup and representative workflows.
- Optional extensions cannot make standard startup unusable when absent.

### 12.6 Accessibility and usability

- Supported display/font scale and keyboard/focus baseline are explicit.
- Warnings/errors/fallbacks are visible and actionable.
- Primary actions do not disappear on supported laptop-class layouts.
- Accessibility limitations are documented honestly.

### 12.7 Maintainability and testability

- Narrow public contracts, package ownership and dependency budgets are enforced.
- Behavior-preserving extraction and behavior changes are separate.
- Unit, contract, fixture, integration, GUI smoke, report, native, packaging, performance and manual
  release gates are distinguishable.
- AI-generated code receives the same review/test/security standard as handwritten code.

## 13. Compatibility and versioning

Versioned artifacts/contracts include as applicable:

- workspace;
- presets, filters, groups and visual recipes;
- parser profiles/manifests and parser output;
- canonical data/analysis/result/report schemas;
- saved databases/caches and migrations;
- run manifests and evidence bundles;
- extension interfaces;
- detector/event configuration;
- CLI JSON output;
- dashboard manifest/DOM/storage contracts.

A schema change must have migration, explicit compatibility behavior or a documented breaking
release. Newer unsupported artifacts fail safely or open read-only where meaningful. Release tags
are immutable; permanent ad-hoc RC branches are not the long-term release archive.

## 14. Validation and release tiers

### Tier A — fast pull-request gate

- formatting/linting and selected type checks;
- unit and contract tests;
- architecture/repository hygiene;
- focused changed-feature tests;
- secret/security policy checks.

### Tier B — subsystem gate

- parser fixture/adapter tests;
- headless use-case integration;
- SQLite migration/integrity tests;
- report/dashboard structural/golden tests;
- Python/package/native parity;
- focused real-Qt/browser behavior where required.

### Tier C — full product CI

- exact supported full-suite recipe and coverage threshold;
- native locked builds/smoke/parity;
- canonical end-to-end workflow;
- performance guardrails that have stable baselines;
- artifact uploads and recorded exact SHA/run.

### Tier D — packaged/manual release gate

- clean Windows package build and launch/readiness;
- native-text and OCR parser smoke;
- SQLite, analysis, dashboard and workbook flow;
- optional Google exact-build sandbox smoke;
- notices/inventory/hashes/legal review;
- keyboard/accessibility and documented supported-platform smoke;
- rollback/migration/known-limitation evidence.

No feature is claimed in a supported release only because a branch or local test exists.

## 15. Stable post-RC / 1.0 acceptance

The first stable post-RC line requires:

1. The accepted #900 branch decision remains followed: normal work integrates through `develop`
   while release evidence stays authoritative on the frozen candidate line.
2. #901 either closes every manual promotion gate or explicitly blocks release.
3. #912 provides one reproducible end-to-end reference workflow.
4. #915/#916/#917 establish the canonical core contracts and at least one headless vertical slice.
5. Major release-candidate features claimed for the release meet their tracking-Issue acceptance
   criteria.
6. Supported workspace/configuration/report/database schemas and compatibility are documented.
7. Packaged Windows users can complete representative import, review, analysis, dashboard and
   workbook flows.
8. Security exceptions are current, finite and reviewed; no unreviewed serious finding remains.
9. Documentation/help reflects the shipped binary and known limitations.
10. Legacy/licensing scope decisions are explicit rather than accidental.
11. Every shipped capability maps to an Issue, tests and release evidence.

## 16. Feature-to-Issue traceability

| Area | Issues |
|---|---|
| Product epic | [#925](https://github.com/hexafe/metroliza/issues/925) |
| Workspace/import/parser/OCR/database/curation | #926, #927, #928, #929, #930, #954 |
| Filtering/grouping/presets | #931, #932, #935 |
| Analysis/baselines | #933, #934, #948 |
| Excel/dashboard/Google/visuals/sharing | #936, #937, #938, #947, #953 |
| Tabular/industrial/realtime | #939, #940, #941 |
| CLI/automation/diagnostics/history | #942, #943, #944, #949 |
| Application UX/accessibility/help | #945, #946, #955 |
| AI/extensions/performance | #950, #951, #952 |
| Legacy/licensing lifecycle decisions | #956, #957 |

Detailed maturity and dependencies are maintained in [feature_catalog.md](./feature_catalog.md).
Ordered delivery is maintained in [roadmap.md](./roadmap.md).

## 17. Explicit non-goals

Unless a separately approved Feature/Research Issue changes scope, Metroliza is not committed to:

- multi-tenant cloud/SaaS hosting;
- automatic upload of measurement/production data;
- a general-purpose BI platform or spreadsheet editor;
- arbitrary write access or unbounded polling against production databases;
- concurrent collaborative editing of one local SQLite file over network shares;
- automatic process/machine actuation;
- unreviewed AI-generated engineering decisions or parser installation;
- hidden anomaly remediation;
- unrestricted executable plugin access to network/shell/filesystem;
- native/Rust default promotion without workflow-level evidence;
- a public extension marketplace;
- pixel-identical output in every spreadsheet/browser environment;
- preserving every accidental legacy behavior forever;
- keeping licensing or legacy modules solely because code exists.

## 18. Open product decisions

- Exact-build package/Google/legal promotion evidence — #901.
- Active-roadmap archival and document authority — #902.
- Domain/application/report/realtime contracts — #915, #916, #917, #919.
- Supported platform/version/release policy — #920.
- Plotstats and native implementation ownership — #907, #908.
- Legacy Group Comparison/BOM lifecycle — #956.
- Licensing/activation lifecycle — #957.

A new capability begins as a Feature Issue containing user problem, maturity, target outcome,
acceptance criteria, dependencies, data/privacy impact, failure/rollback behavior, compatibility
impact and validation tier. Broad speculative work begins as a time-boxed Research Issue ending in
a go, defer or reject decision.
