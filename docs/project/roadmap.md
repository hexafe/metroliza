# Metroliza Roadmap

Status: Active planning source of truth  
Owner: Product/architecture maintainer  
Last reviewed: 2026-08-22  
Planning unit: GitHub Issue

This roadmap orders work; it does not duplicate detailed acceptance criteria. The linked GitHub
Issue is authoritative for an executable work item. Release evidence belongs under
`docs/release_checks/`.

## 1. Planning principles

1. Trust the exact product head before adding broad scope.
2. Close release and data-integrity risks before architecture polish.
3. Split structural debt into behavior-preserving, reversible slices.
4. Keep local-first, SQLite, offline dashboard, Python fallback, and compatibility contracts
   intact unless a separately approved product change says otherwise.
5. Promote optional packages/native paths only after parity, performance, packaging, and rollback
   gates.
6. No implementation starts from an unchecked roadmap bullet alone; create or refine an Issue.
7. Completed plans become records or archive material, not parallel current roadmaps.

## 2. Current state

Branch decision date: 2026-08-22. Exact evidence is recorded in
[`rc2_branch_transition_decision_2026-08-22.md`](../release_checks/rc2_branch_transition_decision_2026-08-22.md).

- Canonical development base: `develop`.
- Frozen candidate/evidence line: `release/2026.06-rc2`.
- Retained transition/reference branch: `rc2`; no new routine development targets it.
- Default/historical production branch: `master` at
  `ab26258e72d285c3917a595515798da185800373`; promotion is not approved.
- Validated branch-point content: commit `a03bbdacbd6c308acf46ca31c16d0dd2caeab304`,
  tree `dc10e028332cb311cb0b2c110deecee2841b9799`.
- PR CI run `32585291955` passed static/security, full tests/coverage, native, Windows core, CMM
  performance, and benchmark trend gates for the same tree.
- Canonical release metadata: `2026.06 RC2 (build 260711)`.
- Immediate release constraint: #901 manual packaged/clean-machine Windows/Google/notices/legal
  evidence blocks `master` and stable-tag promotion.

## 3. Milestones

### Milestone 0 — Project governance reset — completed

Purpose: establish one control center and make GitHub Issues the work queue.

| Issue | Priority | Deliverable | Outcome |
|---|---|---|---|
| #899 | P0 | Product specification, architecture, roadmap, delivery workflow, ChatGPT workspace, Issue forms, PR/branch governance | Completed by PR #909; merged to the product line with green automatic CI |

### Milestone 1 — Trustworthy current product baseline

Purpose: prove what is releasable, remove branch ambiguity, and close promotion blockers.

| Issue | Priority | Deliverable | State/dependency |
|---|---|---|---|
| #900 | P0 | Exact-content automated validation and explicit branch/promotion decision | Decision implemented: `develop` + `release/2026.06-rc2`; closes after decision PR/ref sync |
| #901 | P1 | Packaged Windows, Google conversion, artifact/notices, and legal manual evidence | Active release blocker on the exact candidate |
| #906 | P1 | Review/eliminate/renew expiring Bandit findings before 2026-10-31 | Can proceed from `develop`; release-relevant fixes must be reconciled into the candidate |

Exit criteria:

- [x] exact tested/final tree identity and terminal automatic CI are recorded;
- [x] manual release blockers explicitly remain open rather than being waived;
- [x] `develop` is the canonical development base;
- [x] `release/2026.06-rc2` is the frozen candidate/evidence line;
- [x] `master` promotion is explicitly rejected pending manual evidence;
- [ ] #901 packaged, clean-machine Windows, Google, notices, and legal evidence is complete;
- [ ] no expired security exception remains;
- [ ] release owner records final Go/No-Go for promotion.

Do not mix broad refactoring into the release branch. Release-blocking fixes remain narrow and are
reconciled into `develop`.

### Milestone 2 — Planning and structural-risk reduction

Purpose: reduce the largest maintenance blast radii without changing product behavior.

Base branch: `develop`.

| Issue | Priority | Deliverable | Delivery style |
|---|---|---|---|
| #902 | P1 | One current roadmap, active-doc inventory, historical-plan archival | documentation-only slices |
| #903 | P1 | Smaller exporter seams and staged orchestration | one behavior-preserving seam per PR |
| #904 | P1 | Bounded dashboard controls/options/spec modules with stable browser contracts | one responsibility per PR |
| #905 | P1 | Canonical imports in behavior tests plus isolated compatibility tests | package-by-package ratchet |

Exit criteria:

- no active work exists only as a stale Markdown checklist;
- exporter and dashboard hotspots have smaller reviewable responsibilities;
- public artifact/DOM/storage/compatibility behavior remains proven by tests;
- architecture budgets decrease or remain stable;
- full CI remains green after each slice.

### Milestone 3 — Reusable analytical engines and measured acceleration

Purpose: clarify package ownership and reduce duplicated high-cost logic only where evidence
supports it.

Base branch: `develop`.

| Issue | Priority | Deliverable | Promotion gate |
|---|---|---|---|
| #907 | P2 | Reusable plot specifications in `hexafe-plotstats` for approved chart kinds | numerical/visual parity, rollback, packaging |
| #908 | P2 | Promote, retain as experimental, or retire each Rust/native candidate | representative performance, parity, maintenance cost |

Exit criteria:

- package boundaries and typed contracts are explicit;
- migrated behavior has deterministic fallback;
- no default changes solely from synthetic benchmarks;
- dependencies remain reproducible and security/packaging gates pass.

### Milestone 4 — First stable post-RC product line

Purpose: complete evidence, promote a reviewed candidate, and normalize the branch lifecycle.

Approved sequence:

1. close #901 against `release/2026.06-rc2`;
2. rerun required exact-head automatic/manual gates after any release fix;
3. record release-owner Go/No-Go;
4. merge only a Go candidate into `master` and create the approved stable tag;
5. synchronize the production result back into `develop`;
6. retire or archive the historical `rc2` branch through an explicit cleanup decision;
7. update user manuals and distribution/install guidance against the shipped binary.

Potential post-RC work becomes separate Issues before implementation:

- polished installer/update/distribution instructions;
- supported-workflow packaged smoke matrix for parsing, DB modification, export, CSV Summary,
  industrial cache, and realtime review;
- explicit deprecation plan for legacy Group Comparison/BOM entry points;
- stable compatibility matrix for Python source, PyInstaller, Nuitka, OCR, and optional native
  extensions.

## 4. Workstream map

### Release and quality

- #900 branch decision and exact automatic evidence — closing through the transition PR.
- #901 manual packaged/integration/legal evidence — next release priority.
- #906 time-bound security baseline review.

### Product and documentation

- #899 project control center and workflow — completed.
- #902 active-roadmap consolidation and archive hygiene.

### Architecture and maintainability

- #903 exporter orchestration decomposition.
- #904 dashboard controls/specification decomposition.
- #905 canonical-import test migration with compatibility preservation.

### Shared packages and performance

- #907 `hexafe-plotstats` boundary migration.
- #908 Rust/native promotion decisions.

## 5. Backlog intake rules

A new Issue enters the roadmap only after triage confirms:

- a clear user/problem or engineering-risk statement;
- one primary owner area;
- priority and validation tier;
- target base (`develop` or the explicitly approved release branch);
- acceptance criteria;
- dependencies and compatibility/data impact;
- rollback or deferral option for high-risk work.

Suggested priority meanings:

- **P0** — current product cannot be trusted, released, or safely developed without resolution.
- **P1** — important release, integrity, security, or high-blast-radius maintenance work.
- **P2** — valuable platform improvement with a safe workaround or no immediate release block.
- **P3** — polish/experiment; schedule only when higher priorities and evidence allow.

## 6. Deferred ideas policy

Ideas such as additional AI assistants, warranty/RCA tooling, generic plugin systems, cloud
collaboration, broad UI redesign, or new analytical families are not rejected, but they must not be
hidden inside architecture cleanup. Start each as a Feature or Research Issue with a user problem,
privacy/data boundary, expected decision, and measurable acceptance criteria.

## 7. Roadmap maintenance

At every monthly/release review:

1. compare this document with open/closed Issues;
2. verify default, development, release, and transition branch state;
3. verify the active candidate SHA/tree and release metadata;
4. remove closed work from active milestone tables or mark the outcome;
5. create Issues for newly approved work;
6. archive or reclassify superseded implementation plans;
7. update `Last reviewed` and link the review PR.

A roadmap item without an open Issue is a candidate idea, not scheduled development.
