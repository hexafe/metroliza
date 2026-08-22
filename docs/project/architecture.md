# Metroliza Architecture

Status: Active  
Owner: Architecture maintainer  
Last reviewed: 2026-08-22

## 1. Architectural intent

Metroliza is a local-first modular desktop application with PyQt orchestration, SQLite-backed data
ownership, offline analysis/reporting, optional external integrations, and optional Rust/native
acceleration. The architecture must prioritize data integrity and controlled failure over maximal
abstraction or premature distribution.

The canonical application package is `src/metroliza/`. The root `modules/` tree is an intentional
compatibility layer and is not a second implementation area.

## 2. System context

```text
Measurement reports / ZIP / CSV / Excel
                  |
                  v
       Preflight + parser resolver
                  |
      built-in / profile / plugin parser
                  |
                  v
       normalized report contracts
                  |
                  v
        SQLite report repository
                  |
       +----------+-----------+
       |                      |
       v                      v
 Filter/group/query      Metadata editing
       |
       v
 Analytics + chart specifications
       |
       +----------+----------------+
       |                           |
       v                           v
 Excel/workbook export       Offline HTML dashboard
       |
       v
 Optional Google conversion with local fallback

Approved production sources / CSV / Excel
                  |
                  v
       bounded fetch or local row store
                  |
                  v
        industrial/tabular cache
                  |
       +----------+-----------+
       |                      |
       v                      v
 shared analytics       realtime event stream
                               |
                               v
                    deterministic detectors
                               |
                               v
                    operator dashboard/replay
```

## 3. Package map and ownership

| Package | Primary ownership | Must not become |
|---|---|---|
| `metroliza.app` | startup, version metadata, application lifecycle, feature warmup | a feature/business-logic dumping ground |
| `metroliza.ui` | PyQt widgets, presentation, user interaction, window/task coordination | owner of SQL, persistence rules, or statistical algorithms |
| `metroliza.parsing` | preflight, parser contracts, resolver/registry, parser profiles/plugins, parse orchestration | owner of UI state or export formatting |
| `metroliza.cmm` | CMM-specific parsing and domain helpers where separated from generic parsing | a generic persistence or UI package |
| `metroliza.reports` | report schema, repositories, transactions, query scopes, report services | direct dependency on PyQt widgets |
| `metroliza.storage` | reusable local storage/lifecycle primitives | a duplicate report/industrial domain layer |
| `metroliza.tabular` | normalized CSV/Excel row store, filtering, grouping, tabular analysis services | a UI-specific workflow implementation |
| `metroliza.industrial` | source configuration, cache, production analytics, realtime stream, anomaly domain | a direct report-UI dependency or unbounded live-query client |
| `metroliza.analytics` | statistical adapters and reusable analytical contracts | exporter/UI orchestration |
| `metroliza.charts` | chart specs, rendering adapters, dashboard shell/controls, visual options | workbook lifecycle, report persistence, or source credentials |
| `metroliza.exporting` | export request/outcome contracts, staged execution, workbook/Google orchestration | parser registry or UI widget ownership |
| `metroliza.integrations` | external-integration hygiene and narrow adapters | a place for core local behavior |
| `metroliza.native` | versioned Rust crates and build metadata | the only available implementation of a required workflow |
| `metroliza.native_bridges` | Python/native selection, parity, fallback, and diagnostics | unguarded imports that break source/frozen startup |
| `metroliza.shared` | genuinely cross-cutting small contracts/utilities | a catch-all package that recreates cycles |
| `metroliza.resources` | packaged data/assets/model-resource location | runtime business logic |
| `metroliza.workers` | narrow background-worker infrastructure | domain logic hidden inside generic threads |
| `modules` | compatibility aliases and legacy public import paths | new implementation code |

Package-owned request contracts live with their workflows: parsing, exporting, industrial, and
tabular. Shared compatibility facades may re-export contracts but must not become the canonical
owner.

## 4. Core runtime flows

### 4.1 Startup and window lifecycle

1. `metroliza.py`/application startup establishes the source path, runtime configuration, license
   mode, optional splash, and main application lifecycle.
2. `metroliza.app` owns version/startup policy and feature warmup.
3. `metroliza.ui` creates the main window and delegates long-running work to bounded tasks/workers.
4. Window/task coordinators prevent duplicate workflows, unsafe closes, or cleanup before workers
   stop.
5. Startup smoke modes must remain non-interactive and packaging-safe.

### 4.2 Report ingestion

1. UI builds a validated parse request.
2. Preflight enumerates files, applies archive/path/size safety limits, and produces user-visible
   readiness or rejection information.
3. The parser resolver takes an immutable registry snapshot, performs bounded/shared inspection,
   and returns one exact parser decision or a clear no-match/ambiguous result.
4. The selected parser produces a versioned normalized result.
5. A report repository persists report identity, metadata, candidates, warnings, measurements, and
   duplicate/provenance data in one logical transaction.
6. UI consumes a structured outcome; it does not infer success from partial counters or log text.

### 4.3 Report query, filtering, and grouping

1. UI collects user choices and constructs typed filter/group contracts.
2. Report/tabular services validate field names, values, ranges, and membership semantics.
3. SQLite query scopes use fixed shapes, quoted identifiers, and bound values.
4. Group assignments remain isolated analysis state unless explicitly saved by a product feature.
5. Large selections are counted/streamed before broad materialization when possible.

### 4.4 Export

1. UI builds `ExportRequest` and nested package-owned contracts.
2. `ExportDataThread` remains the Qt orchestration entry point.
3. Query, aggregation, summary composition, chart payload, workbook writing, dashboard generation,
   Google conversion, logging, and outcome shaping are delegated through explicit seams.
4. Artifacts are written to staging/private locations, validated, and atomically published where
   supported.
5. Cancellation and cleanup are stage-aware.
6. The final `ExportOutcome` reports usable artifacts, warnings, fallback state, cancellation, or
   failure.

The exporter is a current concentration risk. #903 decomposes it in behavior-preserving slices;
this architecture does not authorize a rewrite.

### 4.5 Dashboard generation

1. Product workflows produce typed/copy-safe chart and dashboard payloads.
2. Shared chart/dashboard modules build the shell, controls, visual configuration, Plotly specs,
   static layers, and metadata.
3. A manifest is validated before publication.
4. HTML remains offline/self-contained and preserves local browser preferences/marks.
5. Publication is atomic; failure preserves the last complete generation.

Large embedded HTML/CSS/JavaScript modules are a current concentration risk. #904 introduces
bounded internal modules without changing DOM/storage contracts or requiring a frontend toolchain.

### 4.6 Tabular and industrial analytics

1. CSV/Excel or production rows enter a normalized local row store/cache.
2. Source identity and original-to-normalized column mapping are preserved.
3. Filtering, grouping, aggregation, dashboard, and optional workbook paths reuse tabular/industrial
   contracts rather than duplicate UI logic.
4. Production fetching is bounded and cache-first. Live source failures do not invalidate already
   saved rows without an explicit all-or-nothing contract.
5. Dynamic fields remain available through filtering, grouping, dashboard, and export contracts.

### 4.7 Realtime monitoring

1. Source pollers/replay readers produce validated samples in bounded batches.
2. Samples, stream events, and monotonic offsets commit together where required.
3. Detector consumers process persisted events, quarantine permanent poison events, and advance
   offsets only after successful handling.
4. Detector outputs are explainable events stored without unsafe model deserialization.
5. Dashboard refresh reads a consistent SQLite snapshot and refuses stale health/status overwrite.
6. Shutdown waits for database workers and dependent consumers before session cleanup.

## 5. Dependency direction

Preferred direction:

```text
app/ui -> workflow contracts/services -> repositories/storage -> SQLite/files
      \-> exporting/charts/analytics through explicit package-owned contracts
      \-> industrial/tabular through their service contracts

parsing -> reports contracts/repository
industrial -> storage/shared; optional report linking through explicit boundary
exporting -> reports/tabular query contracts, analytics/charts, integration adapters
charts -> analytics payloads and rendering only
native_bridges -> native extensions plus Python reference implementations
```

Rules:

- UI may call services but must not own persistence/query semantics.
- Repositories must not import PyQt UI.
- Shared packages must not import feature packages merely to avoid a local helper.
- Feature packages expose narrow contracts instead of reaching into another package's private
  attributes.
- Compatibility facades may re-export but may not introduce a second state owner.
- Architecture tests enforce package cycles, legacy-reference budgets, naming, and selected strict
  type boundaries.

## 6. SQLite and data-ownership rules

- One logical write unit uses one centralized retryable transaction.
- Context managers/explicit ownership close connections deterministically.
- A function that creates a temporary database/store owns its cleanup; a caller-provided path is
  not removed implicitly.
- Schema and migration helpers are idempotent and tested against representative old databases.
- Query construction separates trusted internal fragments from bound external values.
- Timestamps use explicit timezone/canonical storage contracts.
- Realtime offsets are monotonic and tied to persisted work.
- Backup/restore/extraction uses sibling staging plus validation before replacement.

## 7. Parser extension architecture

The default extension path is declarative profile or external plugin.

Required concepts:

- `BaseReportParser` / versioned parse result contract;
- plugin manifest and stable plugin ID;
- bounded `probe(...)` with confidence and semantic evidence;
- `parse_to_v2(...)` plus explicit legacy adaptation where required;
- approved local installation/rollback and generation-aware resolver invalidation;
- sanitized fixtures and expected-results validation;
- no implicit network access or subprocess execution.

Built-in parsers are appropriate only when the format is a maintained core format or when a shared
resolver/parser interface must change.

## 8. Native architecture

Native acceleration is optional and policy-controlled.

- Rust crates use committed `Cargo.lock` files and `--locked` builds.
- Python remains the behavioral reference unless a separately documented decision changes that.
- Backends expose `python`, `auto`, and/or `native` semantics appropriate to the subsystem.
- `auto` may select native only when the extension and required symbols are available and the path
  is allowlisted/promoted.
- Forced native mode must fail or warn/fallback according to the documented contract; it must not
  silently produce a different result.
- Parity covers numerical outputs, metadata, warnings, failure/cancellation behavior, and packaged
  availability.
- Promotion requires representative benchmarks and packaging cost review (#908).

## 9. Compatibility policy

- `src/metroliza/` is canonical.
- New files use snake_case and new imports use `metroliza.*`.
- `modules.*`, root wrappers such as `VersionDate.py`, dynamic import strings, and packaging hidden
  imports remain only where an explicit compatibility contract requires them.
- Behavior tests should migrate toward canonical imports; explicit compatibility tests preserve the
  old public paths (#905).
- Shim removal is a compatibility-breaking project, not routine cleanup.
- Public environment variables, artifact names, workbook sheet names, parser IDs, dashboard DOM
  IDs/storage keys, and SQLite schema fields are compatibility surfaces and require migration plans
  when changed.

## 10. Security boundaries

- Credentials/tokens remain local, private, atomic, and excluded from Git.
- Google transport is HTTPS-only and restricted to approved hosts; response-provided locations are
  revalidated.
- Diagnostics redact secrets and sensitive query/source content.
- Imported spreadsheet text is neutralized against formula/link activation where product-generated
  formulas are not intended.
- Archive extraction rejects traversal, links, special files, collisions, and resource abuse.
- Dynamic SQL exceptions are reviewed, finite, and tracked by #906.
- CI actions and dependency refs are immutable according to release policy.

## 11. Current architectural risks

| Risk | Evidence | Treatment |
|---|---|---|
| Branch/source-of-truth divergence | `rc2` is 278 commits ahead of stale default `master` | #900 before promotion or broad feature work |
| Unvalidated product-wide head | current `rc2` is one large commit after the last documented green exact head | #900 exact-head CI and review |
| Exporter concentration | `export_data_thread.py` is about 306 KB and owns mixed concerns | #903 incremental seams |
| Dashboard concentration | controls/options/spec modules embed large shared behavior surfaces | #904 contract-preserving split |
| Compatibility ambiguity in tests | behavior tests still use many `modules.*` imports | #905 measured burn-down, shims retained |
| Planning duplication | multiple active/historical roadmaps compete for attention | #902 consolidate/archive |
| Expiring security exceptions | reviewed Bandit baseline entries expire 2026-10-31 | #906 review/eliminate/renew narrowly |
| Optional package boundary drift | plotting/native capabilities exist in multiple locations | #907 and #908 with parity/performance gates |

## 12. Architecture change process

A change requires an Architecture or Technical Task Issue when it changes package ownership,
persistence/schema, public contracts, plugin APIs, dashboard DOM/storage contracts, native defaults,
or compatibility behavior.

The Issue must state:

- current and proposed boundary;
- user/product reason;
- affected data and compatibility surfaces;
- migration and rollback;
- tests/evidence;
- whether an ADR-like permanent decision record is required.

Large changes are divided into behavior-preserving seams. Architecture is improved by reducing
ownership ambiguity and blast radius, not by moving files without a measurable contract benefit.
