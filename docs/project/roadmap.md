# Metroliza Roadmap

Status: Active planning source of truth  
Owner: Product/architecture maintainer  
Last reviewed: 2026-08-23
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
| **1. Reproducible baseline and toolchain** | Clean setup, canonical end-to-end fixture, trustworthy CI/diagnostics/performance evidence | #901, #906, #912, #913, #914, #918, #922, #944, #952 |
| **2. Stable data and application core** | Versioned model, headless vertical slice, controlled import/OCR/database/filter/group/curation | #915, #916, #926, #927, #928, #929, #930, #931, #932, #945, #952, #954 |
| **3. Stable analysis and reporting** | One result model, supported statistics/capability, presets, Excel, dashboard, optional Google | #903, #904, #907, #917, #933, #934, #935, #936, #937, #938, #952 |
| **4. Tabular, industrial and realtime product lines** | Shared contracts for large flat files, cache-first production data and replayable monitoring | #919, #939, #940, #941, #952 |
| **5. Reproducibility, automation and sharing** | Workspaces, CLI, scheduled jobs, history, baselines, visual recipes and evidence bundles | #926, #942, #943, #945, #947, #948, #949, #952, #953 |
| **6. Controlled extensibility and optimization** | Canonical imports, reviewed security, extension contracts, LLM parser assistance, measured native promotion | #905, #906, #908, #928, #950, #951, #952 |
| **7. Stable release and lifecycle closeout** | Supported platform/build, manual evidence, accessibility/help, legacy/licensing decisions, 1.0 gate | #901, #920, #938, #946, #952, #955, #956, #957 |

Phases overlap where work is safely parallel, but their exit gates define dependency order. For
example, parser-profile documentation can progress while exact-head CI runs, but a new workspace
schema should not become stable before the canonical model and compatibility policy are accepted.

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
| [#944](https://github.com/hexafe/metroliza/issues/944) | Sanitized diagnostic bundle and shared redaction rules |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Workload classes, bounded behavior and performance envelopes |
| [#906](https://github.com/hexafe/metroliza/issues/906) | Eliminate or explicitly renew expiring reviewed security findings |
| [#901](https://github.com/hexafe/metroliza/issues/901) | Exact-build Windows/Google/notices/legal manual evidence |

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
- performance baselines identify fixture/environment/build and are not unsupported seed numbers;
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
| [#927](https://github.com/hexafe/metroliza/issues/927) | Unified preflight/import queue/cancel/retry/partial-batch contract |
| [#928](https://github.com/hexafe/metroliza/issues/928) | Parser-profile/plugin lifecycle and resolver evidence |
| [#929](https://github.com/hexafe/metroliza/issues/929) | Reviewable OCR candidates and safe enrichment |
| [#930](https://github.com/hexafe/metroliza/issues/930) | Database/cache schema migration, backup, integrity and repair |
| [#954](https://github.com/hexafe/metroliza/issues/954) | Report browser, curation and transactional corrections |
| [#931](https://github.com/hexafe/metroliza/issues/931) | Shared typed filter contract and backend conformance |
| [#932](https://github.com/hexafe/metroliza/issues/932) | Reusable grouping and characteristic mapping |
| [#945](https://github.com/hexafe/metroliza/issues/945) | Consistent workspace context, task ownership and preferences |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Bounded core import, query and analysis behavior |
| [#926](https://github.com/hexafe/metroliza/issues/926) | Workspace schema foundation, initially for the canonical slice |

### Delivery sequence

1. Characterize current vertical flow and side effects with #912/#922.
2. Accept canonical domain/request/result/error contracts in #915.
3. Wrap existing behavior behind one headless use case; do not rewrite algorithms yet.
4. Route one existing PyQt action through that service.
5. Stabilize parser/OCR/database/filter/group contracts around the same vertical slice.
6. Introduce workspace persistence only for accepted stable contracts.
7. Remove duplicated orchestration after parity, not before.

### Exit criteria

- selected import/analysis workflow runs without starting PyQt;
- domain/application code does not import widgets;
- invalid/missing/excluded/provenance/unit behavior is explicit and tested;
- parser/OCR/data edits are traceable and transactional;
- filter/group semantics are consistent across supported adapters;
- one versioned workspace can save/reopen the canonical configuration safely;
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

1. Define result/report metadata and method/version/warning contracts.
2. Freeze supported statistical definitions with fixtures and parity.
3. Make GUI/dashboard/workbook consume the same result structures.
4. Split exporter/dashboard concentration one behavior-preserving seam at a time.
5. Stabilize preset schema and report regressions.
6. Close Excel and dashboard 1.0 structural, failure and accessibility contracts.
7. Treat Google as optional post-processing after local workbook validation.
8. Move reusable plots to external package only chart-by-chart behind parity/rollback.

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
| [#939](https://github.com/hexafe/metroliza/issues/939) | CSV/Excel Summary v1.0 |
| [#940](https://github.com/hexafe/metroliza/issues/940) | Cache-first Oznak/production analytics v1.0 |
| [#919](https://github.com/hexafe/metroliza/issues/919) | Event/time/window/detector/replay architecture contracts |
| [#941](https://github.com/hexafe/metroliza/issues/941) | Operator-ready realtime monitoring/replay v1.0 |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Bounded large-data behavior and workflow-level performance evidence |

### Delivery sequence

1. Run filter/group/analysis conformance fixtures across report, tabular and industrial adapters.
2. Stabilize multi-file source/column/type and SQLite snapshot identity.
3. Complete cache lifecycle, dynamic fields, source freshness and credential separation.
4. Accept realtime event/time/window/offset/detector contracts.
5. Validate deterministic replay and transparent detectors before live rollout.
6. Add operator review states, restart recovery and honest dashboard freshness.
7. Produce representative load/lag/false-positive/rollback evidence before production use.

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
| [#942](https://github.com/hexafe/metroliza/issues/942) | Supported headless CLI |
| [#943](https://github.com/hexafe/metroliza/issues/943) | Watched folders and scheduled local jobs |
| [#949](https://github.com/hexafe/metroliza/issues/949) | Run history and reproducibility manifests |
| [#948](https://github.com/hexafe/metroliza/issues/948) | Approved cross-dataset baselines |
| [#947](https://github.com/hexafe/metroliza/issues/947) | Versioned visual recipes and local annotations |
| [#953](https://github.com/hexafe/metroliza/issues/953) | Portable verifiable evidence bundle |
| [#944](https://github.com/hexafe/metroliza/issues/944) | Shared diagnostic/redaction/bundle support |
| [#945](https://github.com/hexafe/metroliza/issues/945) | Workspace context and task ownership across interactive and automated flows |
| [#952](https://github.com/hexafe/metroliza/issues/952) | Bounded automation, sharing and cleanup behavior |

### Delivery sequence

1. Complete workspace schema on accepted stable contracts.
2. Expose the same services via CLI with stable JSON/exit codes.
3. Add run identity/manifests and artifact hashes.
4. Add safe watched/scheduled jobs using CLI/application contracts.
5. Add immutable approved baseline snapshots and comparison history.
6. Separate visual recipes/annotations from statistical configuration/source data.
7. Produce portable evidence bundles with outputs-only default and explicit data preview.

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
| [#950](https://github.com/hexafe/metroliza/issues/950) | Privacy-reviewed LLM parser-profile generation/repair |
| [#951](https://github.com/hexafe/metroliza/issues/951) | Versioned parser/analysis/report extension interfaces |
| [#952](https://github.com/hexafe/metroliza/issues/952) | End-to-end performance and resource envelopes |

### Delivery sequence

1. Isolate legacy compatibility tests and enforce decreasing import budgets.
2. Renew/eliminate security findings before expiry.
3. Stabilize parser interface and trust levels first.
4. Quarantine/validate/approve generated parser artifacts.
5. Define analysis/report extension contracts only after canonical core/result schemas are stable.
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
| **Reproducible baseline** | Phase 1: #912, #913, #914, #918, #922, #944, initial #952 |
| **Stable core and reporting** | Phases 2–3: #915–#917, #926–#937, #903, #904, #907, #954 |
| **Tabular and industrial analytics** | Phase 4 tabular/industrial: #939, #940, relevant #931/#932/#952 |
| **Realtime analytics MVP** | #919, #941, realtime parts of #937/#944/#952 |
| **Automation and reproducibility** | Phase 5: #942, #943, #947–#949, #953, complete #926 |
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
