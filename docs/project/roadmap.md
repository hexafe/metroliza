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

- Current product line: `rc2` at `202690eb21087314a3c8000aa3ebdb58a1a09c1b`.
- Default branch: stale `master` at `ab26258e72d285c3917a595515798da185800373`.
- Canonical release metadata: `2026.06 RC2 (build 260711)`.
- Last documented exact-head green CI: earlier RC2 commit
  `ce7556098626f93d3ade95abd49ede00be341611`, recorded by PR #895.
- Immediate constraint: current head must be validated and the canonical development/promotion
  branch must be decided before broad feature work.

## 3. Milestones

### Milestone 0 — Project governance reset

Purpose: establish one control center and make GitHub Issues the work queue.

| Issue | Priority | Deliverable | Exit signal |
|---|---|---|---|
| #899 | P0 | Project specification, architecture, roadmap, delivery workflow, ChatGPT workspace, Issue forms, PR/branch governance | Governance PR merged into the current product line |

This milestone changes documentation and development process only. It does not promote `rc2`, alter
release metadata, or refactor application behavior.

### Milestone 1 — Trustworthy current product baseline

Purpose: prove what is releasable and remove branch ambiguity.

| Issue | Priority | Deliverable | Depends on |
|---|---|---|---|
| #900 | P0 | Exact-head automated validation and explicit `rc2`/`master`/release-branch decision | #899 process baseline |
| #901 | P1 | Packaged Windows, Google conversion, artifact/notices, and legal manual evidence | candidate SHA selected by #900 |
| #906 | P1 | Review/eliminate/renew expiring Bandit findings before 2026-10-31 | current validated code and dependency pins |

Exit criteria:

- exact SHA and terminal CI run recorded;
- no current-head validation gap;
- manual release blockers satisfied or explicitly block promotion;
- canonical development base named;
- branch strategy updated to match the decision;
- no expired security exception;
- release owner records go/no-go.

Do not mix broad refactoring into this milestone unless it fixes a release-blocking defect found by
validation.

### Milestone 2 — Planning and structural-risk reduction

Purpose: reduce the largest maintenance blast radii without changing product behavior.

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

Purpose: ship a stable product identity after the branch/release decision and structural risk
baseline.

Candidate outcomes, to be converted into separate Feature/Release Issues after #900:

- final stable version/branch/tag naming and migration from the ad-hoc `rc2` line;
- polished installer/update/distribution instructions;
- supported-workflow smoke matrix for report parsing, DB modification, export, CSV Summary,
  industrial cache, and realtime review;
- explicit deprecation plan for legacy Group Comparison/BOM entry points;
- user-manual refresh against the shipped binary;
- stable compatibility matrix for Python source, PyInstaller, Nuitka, OCR, and optional native
  extensions.

These candidates are not approved implementation work until Issues define their scope and
acceptance criteria.

## 4. Workstream map

### Release and quality

- #900 exact-head validation and branch decision.
- #901 manual packaged/integration/legal evidence.
- #906 time-bound security baseline review.

### Product and documentation

- #899 project control center and workflow.
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
2. verify branch and release snapshot values;
3. remove closed work from active milestone tables or mark the outcome;
4. create Issues for newly approved work;
5. archive or reclassify superseded implementation plans;
6. update `Last reviewed` and link the review PR.

A roadmap item without an open Issue is a candidate idea, not scheduled development.
