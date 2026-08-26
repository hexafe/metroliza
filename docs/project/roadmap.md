# Metroliza Roadmap

Status: Active planning source of truth  
Owner: Product/architecture maintainer  
Last reviewed: 2026-08-26
Planning unit: GitHub Issue
Product backlog epic: [#925](https://github.com/hexafe/metroliza/issues/925)
Feature catalog: [feature_catalog.md](./feature_catalog.md)

This roadmap orders outcomes and defines gates. It does not duplicate every Issue acceptance
criterion. The linked GitHub Issue is authoritative for executable scope. Release evidence remains
under `docs/release_checks/`.

## 1. Planning principles

1. Establish the trustworthy product head before promoting or layering broad new scope.
2. Capture current behavior with sanitized fixtures before changing architecture.
3. Protect data integrity, reproducibility, diagnostics and rollback before visual polish.
4. Deliver one coherent vertical slice at a time; do not create new multi-month feature branches.
5. Keep behavior changes separate from structural extraction.
6. Share domain/application contracts across PyQt, CLI and automation.
7. Preserve local-first operation, SQLite ownership, offline dashboards, explicit fallbacks and
   compatibility until an approved product decision changes them.
8. Promote package/native paths only after numerical, end-to-end performance, packaging and
   maintenance evidence.
9. A roadmap bullet without an open Issue is an idea, not scheduled work.
10. Completed plans become release evidence, reference records or archive material rather than
    parallel active roadmaps.

## 2. Current repository and product state

Branch decision date: 2026-08-22. Authoritative branch rationale and release evidence remain in
[`rc2_branch_transition_decision_2026-08-22.md`](../release_checks/rc2_branch_transition_decision_2026-08-22.md)
and [`release_status.md`](../release_checks/release_status.md).

- `develop` is the canonical branch for normal Issue-driven development and integration.
- `release/2026.06-rc2` is the frozen release-candidate and evidence branch.
- `rc2` is a temporary historical transition/reference alias, not a routine development base.
- `master` remains the current production/history anchor and is unchanged pending the separate
  [#901 release-promotion decision](https://github.com/hexafe/metroliza/issues/901).
- Canonical release metadata remains `2026.06 RC2 (build 260711)`; this roadmap does not duplicate
  or supersede the release evidence required for promotion.

## 3. Roadmap overview

| Phase | Outcome | Principal Issues |
|---|---|---|
| **0. Project control and branch truth** | One source of truth, full Issue backlog, explicit branch/release decision | #899, #900, #902, #911, #921, #923, #924, #925 |
| **1. Reproducible baseline and toolchain** | Clean setup, canonical end-to-end fixture, complete bug-sweep ownership, trustworthy CI/diagnostics/performance evidence | #974, #975–#985, #901, #906, #912, #913, #914, #918, #922, initial #917/#920, #944, initial #952 |
| **2. Stable data and application core** | Versioned model, headless vertical slice, controlled import/OCR/database/filter/group/curation | #915, #916, #926, #927, #928, #929, #930, #931, #932, #945, #952, #954 |
| **3. Stable analysis and reporting** | One result model, supported statistics/capability, presets, Excel, dashboard, optional Google | #903, #904, #907, #917, #933, #934, #935, #936, #937, #938, #952 |
| **4. Tabular, industrial and realtime product lines** | Shared contracts for large flat files, cache-first production data and replayable monitoring | #952, #939, #940, #919, #941 |
| **5. Reproducibility, automation and sharing** | Workspaces, CLI, scheduled jobs, history, accessibility hardening, baselines, visual recipes and evidence bundles | #926, #945, #942, #944, #952, #949, #943, #948, #946, #947, #953 |
| **6. Controlled extensibility and optimization** | Canonical imports, reviewed security, extension contracts, LLM parser assistance, measured native promotion | #905, #906, #908, #928, #951, #950, #952 |
| **7. Stable release and lifecycle closeout** | Supported platform/build, manual evidence, accessibility/help, legacy/licensing decisions, 1.0 gate | #901, #920, #938, #946, #952, #955, #956, #957 |

Phases overlap where work is safely parallel, but their exit gates define dependency order. For
example, parser-profile documentation can progress while exact-head CI runs, but a new workspace
schema should not become stable before the canonical model and compatibility policy are accepted.

### Dependency and phase semantics

Under [#967](https://github.com/hexafe/metroliza/issues/967), an Issue's `## Dependencies` section
contains strict prerequisites only. `## Downstream consumers`, `## Cross-phase integration` and
conformance obligations keep important later relationships visible without reversing the strict
edge. A foundation may close with stable contracts, reference implementations/fixtures and one
accepted vertical slice; later adapters must pass those fixtures before their own Issues close.

Multi-phase Issues distinguish an early contract slice from later product integration or release
evidence. These slices keep the strict graph schedulable without pretending that the full feature
is complete early:

| Foundation | Earlier accepted slice | Later completion or integration |
|---|---|---|
| #917 result/provenance/error schema | baseline contracts begin in Phase 1 and support Phase 2 services | complete cross-renderer/report integration in Phase 3 |
| #920 compatibility/version/platform policy | version and compatibility rules begin in Phase 1 | packaged-platform and release-process closeout in Phase 7 |
| #944 diagnostics/redaction | shared envelope, redaction, bundle writer and reference adapters in Phase 1 | workflow-specific payload integrations continue in Phases 2–7 |
| #952 performance envelopes | workload/telemetry/bounded-behavior foundation begins in Phase 1 and closes after its #903/#904 prerequisites in Phase 3 | workflow-specific evidence continues in Phases 4–7 |
| #946 accessibility | cross-product hardening required by #947 occurs in Phase 5 | complete manual release evidence in Phase 7 |

## 4. Phase 0 — Project control and branch truth

### Goal

Make GitHub the durable control plane and remove ambiguity about project state, branches and active
planning sources.

### Issues

| Issue | Outcome |
|---:|---|
| [#899](https://github.com/hexafe/metroliza/issues/899) | Project specification, architecture, roadmap and issue-first workflow |
| [#925](https://github.com/hexafe/metroliza/issues/925) | Complete product feature epic and Issue-linked backlog |
| [#902](https://github.com/hexafe/metroliza/issues/902) | One current roadmap; completed/superseded planning moved to reference/archive |
| [#911](https://github.com/hexafe/metroliza/issues/911) | Evidence-based inventory/disposition of every remote branch |
| [#924](https://github.com/hexafe/metroliza/issues/924) | Review/preserve/retire release branches without history loss |
| [#921](https://github.com/hexafe/metroliza/issues/921) | Labels, milestones, repository defaults and branch protection |
| [#923](https://github.com/hexafe/metroliza/issues/923) | ChatGPT project sources/chats aligned to GitHub Issues and docs |
| [#900](https://github.com/hexafe/metroliza/issues/900) | Completed canonical branch/release decision and non-destructive transition |

### Exit criteria

- full product and engineering backlog exists as Issues;
- every remote branch has a documented role/disposition;
- no active work depends only on a chat or stale roadmap checklist;
- the accepted candidate content and branch decision are recorded without force-push/history rewrite;
- `develop` is named as the canonical development base;
- repository settings support issue/PR-driven work;
- `docs/project/` is the planning entry point and `docs/release_checks/` remains release evidence.

### Prohibited shortcuts

- merging historical branches wholesale;
- deleting branches before reviewing unique commits;
- renaming/promoting the default branch without terminal evidence;
- opening broad implementation PRs directly from an undocumented branch.

## 5. Phase 1 — Reproducible baseline and toolchain

### Goal

Create a clean, repeatable foundation that can prove whether future changes preserve product
behavior.

### Issues

| Issue | Outcome |
|---:|---|
| [#912](https://github.com/hexafe/metroliza/issues/912) | One sanitized end-to-end reference workflow from import to report |
| [#913](https://github.com/hexafe/metroliza/issues/913) | Canonical Python/Rust development and packaging environment |
| [#914](https://github.com/hexafe/metroliza/issues/914) | Pull-request quality gates and release smoke lanes |
| [#918](https://github.com/hexafe/metroliza/issues/918) | Representative benchmarks and Python/Rust parity foundation |
| [#922](https://github.com/hexafe/metroliza/issues/922) | Honest current-state code/data-flow and supported-workflow map |
| [#917](https://github.com/hexafe/metroliza/issues/917) | Initial result/provenance/error contracts needed by cross-cutting foundations |
| [#920](https://github.com/hexafe/metroliza/issues/920) | Initial compatibility, version identity and supported-platform policy |
| [#944](https://github.com/hexafe/metroliza/issues/944) | Shared diagnostic envelope, bundle and redaction foundation with reference adapters |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Initial workload classes, bounded-behavior and performance-envelope contracts |
| [#906](https://github.com/hexafe/metroliza/issues/906) | Eliminate or explicitly renew expiring reviewed security findings |
| [#901](https://github.com/hexafe/metroliza/issues/901) | Exact-build Windows/Google/notices/legal manual evidence |

### Repository-wide bug sweep

| Issue | Ordered quality outcome |
|---:|---|
| [#974](https://github.com/hexafe/metroliza/issues/974) | Complete-surface bug-sweep program and final acceptance |
| [#975](https://github.com/hexafe/metroliza/issues/975) | Exact baseline, one-primary-owner coverage ledger, finding protocol, and validator |
| [#976](https://github.com/hexafe/metroliza/issues/976) | Build, CI, dependencies, packaging, and Windows audit |
| [#983](https://github.com/hexafe/metroliza/issues/983) | Security, confidentiality, configuration, diagnostics, and licensing audit |
| [#979](https://github.com/hexafe/metroliza/issues/979) | SQLite, cache, migration, persistence, and atomicity audit |
| [#980](https://github.com/hexafe/metroliza/issues/980) | Filtering, grouping, analytics, statistics, and Python/native parity audit |
| [#978](https://github.com/hexafe/metroliza/issues/978) | Import, parsing, OCR, archive, and validation audit |
| [#981](https://github.com/hexafe/metroliza/issues/981) | Reports, Excel, Google, dashboards, and atomic publication audit |
| [#977](https://github.com/hexafe/metroliza/issues/977) | Startup, PyQt lifecycle, threading, cancellation, and state audit |
| [#982](https://github.com/hexafe/metroliza/issues/982) | Tabular, industrial, realtime, and long-running workflow audit |
| [#984](https://github.com/hexafe/metroliza/issues/984) | Compatibility, import, dead-path, and packaged-discovery audit |
| [#985](https://github.com/hexafe/metroliza/issues/985) | Test-gap challenge and final residual-risk closeout |

#975 runs first. The initial Product Owner decision then requires one audit PR at a time in the
table order; later parallelization requires an explicit decision and proof that shared artifacts,
test environments, and exact-baseline assumptions do not overlap. #985 runs after every wave has a
merged exact-SHA report or an explicit blocker. The canonical control plane is
[docs/quality/bug_sweep/README.md](../quality/bug_sweep/README.md).

### Canonical baseline must exercise

1. source preflight and parser resolution;
2. native-text and/or OCR metadata path;
3. atomic SQLite persistence and duplicate behavior;
4. validation, missing/invalid/excluded values;
5. filtering and grouping;
6. descriptive, pairwise and capability analysis;
7. HTML dashboard and spreadsheet structure;
8. provenance, warnings and run identity;
9. actual timing/memory/backend environment.

### Exit criteria

- a fresh checkout follows one documented setup path;
- the canonical fixture contains no confidential data;
- expected parsed records, warnings, numerical results and report structures are versioned;
- local and CI commands are the same or explicitly shared;
- native extensions can be built/tested or fail with explicit supported fallback;
- diagnostics distinguish environment, parser, persistence, analysis and rendering failure;
- the shared #944 diagnostic/redaction contract is proven without requiring every downstream
  workflow payload;
- performance baselines identify fixture/environment/build and are not unsupported seed numbers;
- #917/#920 foundation slices and the initial #952 envelope are accepted for later consumers;
- every tracked path has exactly one primary #975–#985 audit owner, every confirmed finding has one
  authoritative Issue, and remaining uncertainty is categorized explicitly;
- exact packaged/manual release blockers are visible and owned.

## 6. Phase 2 — Stable data and application core

### Goal

Make the central import-to-analysis workflow versioned, headless and independent of widget state.

### Core architecture Issues

| Issue | Outcome |
|---:|---|
| [#915](https://github.com/hexafe/metroliza/issues/915) | Canonical source/report/measurement/validation/configuration/result model |
| [#916](https://github.com/hexafe/metroliza/issues/916) | First headless application-service vertical slice used by existing PyQt flow |

### Product Issues

| Issue | Outcome |
|---:|---|
| [#926](https://github.com/hexafe/metroliza/issues/926) | Workspace schema foundation, initially for the canonical slice |
| [#927](https://github.com/hexafe/metroliza/issues/927) | Import orchestration, preflight, queue and parser/OCR ports |
| [#928](https://github.com/hexafe/metroliza/issues/928) | Parser-profile/plugin lifecycle consuming the #927 resolver port |
| [#929](https://github.com/hexafe/metroliza/issues/929) | Reviewable OCR extraction consuming #927/#928 contracts |
| [#930](https://github.com/hexafe/metroliza/issues/930) | Database/cache schema migration, backup, integrity and repair |
| [#931](https://github.com/hexafe/metroliza/issues/931) | Canonical typed filter contract and reference in-memory/SQLite conformance |
| [#932](https://github.com/hexafe/metroliza/issues/932) | Canonical grouping, aliases, preview, presets and serialization foundation |
| [#945](https://github.com/hexafe/metroliza/issues/945) | Shell/context integration consuming #926 and #944 |
| [#954](https://github.com/hexafe/metroliza/issues/954) | Report browser and transactional curation after OCR/database/group foundations |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Bounded core import, query and analysis behavior |

### Delivery sequence

1. Characterize the current vertical flow and side effects with #912/#922.
2. Accept #915 domain contracts, the required #917/#920 foundation slices and the #916 headless
   application-service boundary.
3. Establish #927 import orchestration and its parser-resolution/metadata-extraction ports using
   deterministic current/reference adapters for the foundational slice.
4. Complete #928 parser lifecycle over the #927 resolver port, then #929 OCR review/enrichment over
   the accepted import/parser contracts.
5. Establish #926 workspace schema/services before #945 integrates them into the application shell.
6. Establish #931 expression/parser/validation/serialization/compiler contracts and prove
   reference in-memory/SQLite conformance on the foundational/report slice.
7. Establish #932 grouping/alias identities, preview and serialization before Phase 3 analysis.
8. Complete #930 lifecycle safety, then #954 curation over accepted OCR/database/group contracts.
9. Route the accepted vertical slice through #945 shell/task/context integration.
10. Remove duplicated orchestration after parity, not before.

### Exit criteria

- selected import/analysis workflow runs without starting PyQt;
- domain/application code does not import widgets;
- invalid/missing/excluded/provenance/unit behavior is explicit and tested;
- #927 ports are stable before the #928/#929 lifecycle integrations close;
- parser/OCR/data edits are traceable and transactional;
- #931 reference in-memory/SQLite adapters and the foundational/report slice pass shared filter
  conformance; unfinished Phase 4 adapters do not block #931 closure;
- #932 grouping/alias semantics are stable before #933 descriptive/pairwise analysis begins;
- one versioned workspace can save/reopen the canonical configuration safely;
- #945 consumes #926/#944 rather than redefining workspace or diagnostic contracts;
- progress, cancellation and errors use structured application outcomes;
- existing GUI remains functional through the extracted service.

## 7. Phase 3 — Stable analysis and reporting

### Goal

Deliver supported statistical interpretation and deterministic outputs from one canonical result
model.

### Issues

| Issue | Outcome |
|---:|---|
| [#917](https://github.com/hexafe/metroliza/issues/917) | One report/result/provenance schema for GUI, HTML and Excel |
| [#933](https://github.com/hexafe/metroliza/issues/933) | Group statistics and pairwise comparison v1.0 |
| [#934](https://github.com/hexafe/metroliza/issues/934) | Capability, distribution and risk analysis v1.0 |
| [#935](https://github.com/hexafe/metroliza/issues/935) | Versioned analysis/output presets/templates |
| [#936](https://github.com/hexafe/metroliza/issues/936) | Excel export v1.0 |
| [#937](https://github.com/hexafe/metroliza/issues/937) | Offline HTML dashboard v1.0 |
| [#938](https://github.com/hexafe/metroliza/issues/938) | Optional Google conversion with guaranteed local fallback |
| [#903](https://github.com/hexafe/metroliza/issues/903) | Behavior-preserving exporter decomposition |
| [#904](https://github.com/hexafe/metroliza/issues/904) | Bounded dashboard modules and stable browser contracts |
| [#907](https://github.com/hexafe/metroliza/issues/907) | Measured plotstats package boundary |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Bounded analysis, rendering and publication behavior |

### Delivery sequence

1. Complete the #917 result/report metadata and method/version/warning contract begun earlier.
2. Complete #933 descriptive/pairwise analysis over #932 group identities, then extend those scopes
   with #934 capability/distribution/risk analysis.
3. Stabilize #935 presets only after the accepted filter/group/analysis contracts.
4. Split exporter/dashboard concentration through #903/#904 behavior-preserving seams and close the
   shared #952 envelope before Phase 4 workflow-specific evidence.
5. Close #936 Excel and the core #937 offline dashboard over the same result structures; #937 owns
   baseline accessibility, while #946 hardening and #947 recipes remain downstream.
6. Treat #938 Google conversion as optional post-processing after local workbook validation.
7. Move reusable plots to an external package only chart-by-chart behind parity/rollback.

### Exit criteria

- every displayed metric has documented scope/method/unavailable behavior;
- pooled and per-group values cannot be confused;
- GUI/HTML/Excel values and warnings agree;
- renderers do not recompute domain statistics;
- workbook/dashboard publication is atomic and structurally validated;
- formula/URL-like source text remains safe literal content;
- dashboard opens offline with visible browser/Plotly fallback;
- presets reproduce canonical output settings and detect incompatibility;
- Google failure always identifies a valid local fallback where one was produced;
- structural decompositions reduce blast radius without output drift.

## 8. Phase 4 — Tabular, industrial and realtime product lines

### Goal

Use the stable core contracts to make flat-file, production-cache and realtime workflows first-class
rather than parallel applications.

### Issues

| Issue | Outcome |
|---:|---|
| [#952](https://github.com/hexafe/metroliza/issues/952) | Shared performance envelope required before workflow-specific evidence |
| [#939](https://github.com/hexafe/metroliza/issues/939) | CSV/Excel Summary v1.0 |
| [#940](https://github.com/hexafe/metroliza/issues/940) | Cache-first Oznak/production analytics v1.0 |
| [#919](https://github.com/hexafe/metroliza/issues/919) | Event/time/window/detector/replay architecture contracts |
| [#941](https://github.com/hexafe/metroliza/issues/941) | Operator-ready realtime monitoring/replay v1.0 |

### Delivery sequence

1. Start from the closed #931/#932/#933/#934/#936/#937 contracts and shared #952 performance
   envelope; do not redefine canonical semantics inside a workflow adapter.
2. Complete #939 tabular field/execution adapters and run the shared filter/group/analysis and
   workload fixtures against in-memory and SQLite-backed modes.
3. Complete #940 industrial adapters after #939, including cache lifecycle, dynamic fields, source
   freshness, credential separation and the same applicable #931 conformance fixtures.
4. Complete #941 after #940 and #919, then validate deterministic replay, transparent detectors,
   operator review states, restart recovery and honest dashboard freshness.
5. Produce representative load/lag/false-positive/rollback evidence before production use.

### Exit criteria

- in-memory and SQLite-backed tabular modes produce equivalent supported results;
- changed source files/snapshots cannot be mistaken for old data;
- production access is bounded, approved, credential-safe and cache-first;
- dynamic fields survive through local analysis/output;
- replay is deterministic and live/replay share detector interfaces;
- restart preserves monotonic progress without duplicate/lost committed events;
- alerts are explainable and support operator review state;
- dashboard generation time and data-through/freshness are distinct;
- advanced ML remains optional and is evaluated against transparent baselines.

## 9. Phase 5 — Reproducibility, automation and sharing

### Goal

Turn repeatable interactive work into durable, scriptable, reviewable engineering workflows.

### Issues

| Issue | Outcome |
|---:|---|
| [#926](https://github.com/hexafe/metroliza/issues/926) | Complete portable/relinkable workspace lifecycle |
| [#945](https://github.com/hexafe/metroliza/issues/945) | Workspace context and task ownership across interactive and automated flows |
| [#942](https://github.com/hexafe/metroliza/issues/942) | Supported headless CLI |
| [#944](https://github.com/hexafe/metroliza/issues/944) | Downstream workflow payload integration over the shared diagnostic foundation |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Workflow-specific bounded automation, sharing and cleanup evidence |
| [#949](https://github.com/hexafe/metroliza/issues/949) | Run history and reproducibility manifests |
| [#943](https://github.com/hexafe/metroliza/issues/943) | Watched folders and scheduled local jobs |
| [#948](https://github.com/hexafe/metroliza/issues/948) | Approved cross-dataset baselines |
| [#946](https://github.com/hexafe/metroliza/issues/946) | Cross-product accessibility hardening required by reusable visual recipes |
| [#947](https://github.com/hexafe/metroliza/issues/947) | Versioned visual recipes and local annotations |
| [#953](https://github.com/hexafe/metroliza/issues/953) | Portable verifiable evidence bundle |

### Delivery sequence

1. Complete the portable #926 workspace lifecycle and #945 shell/context integration on the
   accepted Phase 2 foundations.
2. Expose the same services through #942 CLI with stable JSON/exit codes.
3. Establish #949 run identity/manifests and artifact hashes before its downstream consumers.
4. Add #943 watched/scheduled jobs and #948 immutable baselines over the #949 history contract.
5. Complete the Phase 5 #946 accessibility-hardening slice over #937/#945 before #947 reusable
   visual recipes and annotations.
6. Produce #953 portable evidence bundles over #949 manifests with outputs-only default and
   explicit data preview.
7. Apply the already accepted #944/#952 contracts to workflow-specific payloads and evidence.

### Exit criteria

- a canonical workspace reopens/relinks and reproduces supported results;
- CLI and GUI return equivalent domain results;
- automated jobs do not process unstable files or guess through ambiguity;
- restart/locking/quarantine and run manifests prevent hidden partial state;
- history distinguishes changed input/config/method/artifact;
- approved baselines are immutable/versioned and compatible before use;
- evidence bundles verify hashes, work with relative links and exclude credentials/source data by
  default;
- local annotations remain separate from source data.

## 10. Phase 6 — Controlled extensibility and optimization

### Goal

Allow safe extension and measured optimization without recreating uncontrolled module/plugin sprawl.

### Issues

| Issue | Outcome |
|---:|---|
| [#905](https://github.com/hexafe/metroliza/issues/905) | Canonical imports in behavior tests; compatibility tests isolated |
| [#906](https://github.com/hexafe/metroliza/issues/906) | Current finite reviewed security exceptions |
| [#908](https://github.com/hexafe/metroliza/issues/908) | Promote, keep experimental or retire each native candidate |
| [#928](https://github.com/hexafe/metroliza/issues/928) | Declarative parser lifecycle as the controlled extension foundation |
| [#951](https://github.com/hexafe/metroliza/issues/951) | Versioned parser/analysis/report extension interfaces |
| [#950](https://github.com/hexafe/metroliza/issues/950) | Privacy-reviewed LLM parser-profile generation/repair |
| [#952](https://github.com/hexafe/metroliza/issues/952) | End-to-end performance and resource envelopes |

### Delivery sequence

1. Isolate legacy compatibility tests and enforce decreasing import budgets.
2. Renew/eliminate security findings before expiry.
3. Complete the #928 parser lifecycle and trust levels first.
4. Establish #951 parser/analysis/report extension interfaces over #928 and canonical schemas.
5. Add #950 LLM-assisted generation/repair as an optional consumer of #928/#951, with quarantine,
   deterministic validation and explicit approval.
6. Re-evaluate native candidates against current representative workloads.
7. Retain only extensions/accelerators with ownership, contracts, parity, packaging and maintenance
   rationale.

### Exit criteria

- new implementation uses canonical package paths;
- `modules.*` remains only measured compatibility surface;
- no security exception expires silently;
- declarative and executable extensions have distinct trust policies;
- incompatible extensions fail before execution;
- analysis/report extensions cannot bypass canonical result/statistical contracts;
- LLM output cannot install without deterministic evidence and approval;
- every retained native path has parity, benchmark, fallback and package evidence;
- no default changes solely because a microbenchmark is faster.

## 11. Phase 7 — Stable release and lifecycle closeout

### Goal

Ship a stable, supported product identity and close scope that otherwise remains accidental.

### Issues

| Issue | Outcome |
|---:|---|
| [#920](https://github.com/hexafe/metroliza/issues/920) | Supported OS/architecture/browser, versioning, packaging and release process |
| [#901](https://github.com/hexafe/metroliza/issues/901) | Exact-build Windows, Google, notices/hashes and legal evidence |
| [#938](https://github.com/hexafe/metroliza/issues/938) | Exact-build optional Google conversion evidence with local fallback |
| [#946](https://github.com/hexafe/metroliza/issues/946) | Keyboard/accessibility baseline and manual smoke |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Supported workload and packaged resource-behavior evidence |
| [#955](https://github.com/hexafe/metroliza/issues/955) | Contextual help, current manuals and troubleshooting |
| [#956](https://github.com/hexafe/metroliza/issues/956) | Legacy Group Comparison/BOM retain/migrate/remove decisions |
| [#957](https://github.com/hexafe/metroliza/issues/957) | Licensing/activation retain/extract/redesign/remove decision |

### Exit criteria

- stable version/tag/branch strategy replaces ad-hoc RC state;
- supported and unsupported platform/build/browser combinations are explicit;
- one version identity reaches app, packages, native modules, logs, reports and manifests;
- clean build and clean-machine startup/core-flow evidence exists;
- notices/inventory/hashes and legal/release-owner sign-off are recorded;
- canonical desktop flow and dashboard meet the documented keyboard/accessibility baseline;
- manuals/help match the shipped build and known limitations;
- deprecated entry points have migration/removal or explicit retained scope;
- licensing is an intentional supported distribution decision or removed/extracted;
- no P0/release-blocking Issue remains unresolved;
- every shipped feature claimed for the release has closed acceptance evidence.

## 12. Suggested milestone mapping

GitHub milestone creation/configuration is tracked by #921. Recommended milestones:

| Milestone | Included phases/issues |
|---|---|
| **Foundation and branch recovery** | Phase 0: #899, #900, #902, #911, #921, #923, #924, #925 |
| **Reproducible baseline** | Phase 1: #974, #975–#985, #912, #913, #914, #918, #922, initial #917/#920, #944, initial #952 |
| **Stable core and reporting** | Phases 2–3: #915–#917, #926–#937, #903, #904, #907, #954 |
| **Tabular and industrial analytics** | Phase 4 tabular/industrial: #939, #940, relevant #931/#932/#952 |
| **Realtime analytics MVP** | #919, #941, realtime parts of #937/#944/#952 |
| **Automation and reproducibility** | Phase 5: #942, #943, #946–#949, #953, complete #926 |
| **Extensibility and performance** | Phase 6: #905, #906, #908, #950–#952 |
| **1.0 release hardening** | Phase 7: #901, #920, #946, #955–#957 and all selected feature gates |

## 13. Prioritization policy

When priorities conflict, use this order:

1. Incorrect result, data loss/corruption, secret exposure or unsafe production access.
2. Untrusted release/branch/build state and missing reproducibility evidence.
3. Migration, diagnostic, cancellation and rollback gaps.
4. Architecture blockers affecting multiple committed outcomes.
5. Primary user workflow friction and accessibility blockers.
6. Measured end-to-end performance bottlenecks.
7. New analytical/output/automation capability.
8. Optional integration, extensibility, experimental ML and polish.

Priority labels:

- **P0** — product/release/development state cannot be trusted safely without resolution;
- **P1** — important integrity, security, release or primary-workflow outcome;
- **P2** — valuable capability with a safe workaround or no immediate release block;
- **P3** — experiment/polish; schedule only after higher gates and evidence permit.

## 14. Backlog intake and decomposition

A Feature Issue must include:

- current maturity and evidence;
- user problem/persona;
- concrete target outcome;
- scope and non-goals;
- testable acceptance criteria;
- dependencies and compatibility/migration impact;
- data/privacy/security boundary;
- failure, cancellation, partial-success and rollback/fallback behavior;
- required validation tier.

A tracking Issue is decomposed into reviewable implementation Issues/PRs. One implementation PR
has one primary outcome. Research work is time-boxed and ends in go, defer or reject evidence.

## 15. Explicitly deferred or rejected-by-default scope

The following do not enter implementation without separate approved Issues and product/data
boundaries:

- cloud/SaaS multi-tenancy;
- collaborative network editing;
- automatic external upload or telemetry;
- arbitrary production DB writes;
- automatic machine/process actuation;
- unrestricted plugin marketplace;
- AI-generated engineering decisions without deterministic evidence/human approval;
- broad UI toolkit rewrite;
- native rewrite by adjacency rather than profiling;
- encryption claims based only on packaging into a ZIP;
- permanent support for every accidental legacy behavior.

## 16. Roadmap maintenance

At least monthly and every release cycle:

1. compare this roadmap with open/closed Issues and #925;
2. verify repository/branch/release snapshot values;
3. move completed outcomes to release evidence or archive/reference status;
4. create/decompose newly approved Issues;
5. check that every active capability maps to the feature catalog;
6. review blocked/dependency chains and limit parallel work;
7. verify security exception dates and manual release gates;
8. update `Last reviewed` in the same PR.

The roadmap is not a second task tracker. GitHub Issues hold work; this document explains sequence,
product gates and dependencies.
