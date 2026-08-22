# Metroliza Development Workflow

Status: Active  
Owner: Maintainer  
Last reviewed: 2026-08-22

## 1. Core rule: Issue first

Every implementation change starts from a GitHub Issue. The Issue explains why the work exists and
what completion means; the branch and pull request implement it.

Exceptions are limited to trivial typo/link fixes that cannot affect behavior, packaging, release
evidence, or a public contract. Even then, the pull request must explain the scope.

One pull request should have one primary Issue. If an Issue needs several independently reviewable
slices, use several pull requests and keep the Issue open until all acceptance criteria are met.

## 2. Transitional branch policy

The documented long-term policy says `master` is production-ready, but the repository currently has
a different physical state:

- `master`: `ab26258e72d285c3917a595515798da185800373`;
- `rc2`: `202690eb21087314a3c8000aa3ebdb58a1a09c1b`;
- `rc2` is 278 commits ahead and zero behind at the 2026-08-22 audit snapshot.

Until #900 closes:

- base current documentation, validation fixes, and narrowly approved work on `rc2`;
- target pull requests at `rc2`;
- do not merge feature/docs/refactor work directly into stale `master`;
- do not cut a new release from stale `master`;
- do not force-push, rebase-rewrite, or create a synthetic history reconciliation that changes the
  validated product tree;
- treat promotion to `master` as a release-owner decision requiring #900 and #901 evidence.

After #900, update this document and `docs/release_checks/branching_strategy.md` in the decision PR.

## 3. Issue lifecycle

### 3.1 Create

Use one of the structured forms:

- Bug report — observed incorrect behavior or regression.
- Feature request — a user-facing capability or behavior change.
- Technical task — architecture, refactor, tests, performance, docs, security, or release work.

The title uses the temporary explicit prefix format until repository labels/milestones are fully
configured:

```text
[P0][Release] Validate current rc2 HEAD
[P1][Architecture] Decompose exporter stage coordination
[P2][Feature] Add an approved analytical view
```

### 3.2 Triage

Confirm:

- type and priority;
- owning area;
- user/engineering problem;
- acceptance criteria;
- dependencies/blockers;
- data, security, compatibility, packaging, and documentation impact;
- validation tier;
- whether the work must be split.

Close duplicate, superseded, or rejected Issues with a reason. Do not leave an Issue open merely as
a vague idea bucket.

### 3.3 Definition of Ready

An Issue is ready when:

- [ ] the current behavior/problem is stated;
- [ ] intended outcome and non-goals are stated;
- [ ] acceptance criteria are testable;
- [ ] affected package/workflow is identified;
- [ ] compatibility/data migration risk is identified;
- [ ] validation tier and likely focused tests are named;
- [ ] dependencies are resolved or linked;
- [ ] the work is small enough for one reviewable PR or has an explicit slice plan.

### 3.4 Implement

Create a branch from the current approved base.

Recommended names:

```text
fix/<issue>-short-description
feature/<issue>-short-description
refactor/<issue>-short-description
docs/<issue>-short-description
test/<issue>-short-description
chore/<issue>-short-description
release/YYYY.MM-rcN
hotfix/<version>-short-description
```

Examples:

```text
docs/899-project-governance-reset
refactor/903-export-run-stages
fix/900-parser-preflight-regression
```

Implementation rules:

- Keep scope aligned with the Issue.
- Add or change tests with behavior changes.
- Separate refactor from feature behavior.
- Use canonical `metroliza.*` imports for new/touched implementation.
- Keep `modules.*` changes limited to explicit compatibility maintenance.
- Reuse package-owned contracts and services instead of reaching into private attributes.
- Preserve atomic transactions/publication and deterministic cleanup.
- Do not commit generated local artifacts unless the repository explicitly tracks that artifact
  and its regeneration contract.

### 3.5 Pull request

A pull request must:

- link the primary Issue (`Closes #...` when the PR completes it, otherwise `Refs #...`);
- state user/engineering impact and non-goals;
- describe risk and rollback;
- identify validation tier and exact commands/results;
- call out schema, public contract, packaging, security, native, Google, dashboard, or compatibility
  impact;
- remain small enough to review or explain why a larger integration PR is unavoidable.

Do not use “tests pass” as evidence without the command, result, or CI run. Do not mark a manual gate
complete from a mocked/unit test.

### 3.6 Review and merge

Review checks:

- acceptance criteria are covered;
- behavior and failure paths are understood;
- ownership boundaries improve or remain stable;
- tests prove the changed contract rather than only implementation details;
- sensitive data is absent;
- documentation/release evidence is synchronized;
- rollback is possible.

Preferred merge style for normal work is squash when repository policy/settings allow it, so one
Issue slice becomes one understandable commit. Release reconciliation may use a different method
only when history/evidence requires it.

### 3.7 Definition of Done

- [ ] Issue acceptance criteria are satisfied.
- [ ] Required focused/full/manual validation is recorded.
- [ ] CI is terminal for the exact merged head.
- [ ] Documentation and changelog/release evidence are updated when applicable.
- [ ] Compatibility/data migration and rollback are complete.
- [ ] Temporary files/flags/dead plans are removed or explicitly tracked.
- [ ] Follow-up work has separate Issues rather than hidden TODOs.
- [ ] The primary Issue is closed by the merge or closed with a final evidence comment.

## 4. Priority model

| Priority | Meaning | Typical examples |
|---|---|---|
| P0 | Product head, data, release, or development base cannot be trusted safely | unvalidated release head, destructive corruption risk, active secret exposure |
| P1 | Important release/integrity/security risk or major maintenance blast radius | packaging blocker, expiring security waiver, giant critical orchestrator |
| P2 | Valuable platform/product improvement with a workable current path | package centralization, measured optional acceleration |
| P3 | Polish, experiment, or low-impact convenience | minor visual refinements, exploratory spike |

Priority is about impact and urgency, not implementation size.

## 5. Type and area taxonomy

Recommended labels when repository label configuration is added:

### Type

- `type:bug`
- `type:feature`
- `type:refactor`
- `type:docs`
- `type:test`
- `type:performance`
- `type:security`
- `type:release`
- `type:research`

### Area

- `area:app`
- `area:ui`
- `area:parsing`
- `area:ocr`
- `area:reports`
- `area:storage`
- `area:export`
- `area:charts-dashboard`
- `area:tabular`
- `area:industrial`
- `area:realtime`
- `area:analytics`
- `area:native`
- `area:packaging-ci`
- `area:docs`

### Priority/status

- `priority:P0` through `priority:P3`
- `status:needs-triage`
- `status:ready`
- `status:blocked`
- `status:in-progress`
- `status:needs-evidence`

Until labels exist, retain the priority/type prefix in the Issue title and use checklists/comments
for status.

## 6. Validation tiers

### Tier 0 — Documentation/process only

Use when no code, runtime configuration, packaging, or generated artifact changes.

Expected evidence:

```bash
PYTHONPATH=src:. python -m pytest tests/test_docs_markdown_links.py -q
python scripts/check_release_hygiene.py
git diff --check
```

Add any repository policy/index tests affected by the change.

### Tier 1 — Focused behavior

Use for a small, isolated implementation change.

Expected evidence:

- focused unit/contract tests for the changed behavior;
- Ruff on changed paths;
- compileall or appropriate language build check;
- `git diff --check`.

### Tier 2 — Subsystem integration

Use for parser, report repository, export, dashboard, tabular, industrial, realtime, UI task, or
native adapter changes.

Expected evidence:

- focused tests plus the subsystem regression set;
- architecture/compatibility tests when boundaries change;
- relevant performance/parity tests;
- full Ruff and compileall;
- release metadata/docs checks when applicable.

### Tier 3 — Full repository CI

Required for broad/cross-cutting changes, dependency changes, shared contracts, schema changes,
release candidates, and any change with large blast radius.

Expected evidence:

- exact CI test/coverage recipe;
- all real-Qt append shards;
- blocking coverage threshold;
- strict selected mypy boundaries;
- security and dependency audit;
- native locked builds/tests;
- release hygiene/docs/metadata checks;
- terminal GitHub Actions run for the exact head.

### Tier 4 — Release/manual evidence

Required when claiming a packaged/release/integration behavior:

- PyInstaller/Nuitka artifact build and hashes;
- clean-machine Windows launch/readiness;
- packaged parser/OCR/SQLite/dashboard/workbook smoke;
- secure Google conversion smoke when applicable;
- notices/inventory/legal review;
- rollback/fallback observation.

Automated tests cannot substitute for Tier 4 when the acceptance criterion concerns a real
packaged executable, OAuth service, clean machine, or legal sign-off.

## 7. Commit guidance

Use concise imperative messages with a useful scope:

```text
docs(project): add canonical roadmap and workflow
fix(parsing): reject mutated source before persistence
refactor(export): extract cancellation-safe stage coordinator
test(compat): move report behavior tests to canonical imports
```

A commit should be understandable without reading the entire diff. Avoid messages such as
“updates”, “fix stuff”, or model/session descriptions.

## 8. Release workflow

Long-term intended flow:

1. develop features/refactors on Issue branches from the approved development base;
2. cut `release/YYYY.MM-rcN` when scope freezes;
3. allow only fixes, evidence, version metadata, and release documentation on the release branch;
4. validate exact head automatically and manually;
5. merge approved release into `master` and tag `vYYYY.MM`;
6. sync the production result back to the development base;
7. archive completed release plans/evidence appropriately.

The current ad-hoc `rc2` state is governed by #900 and #901 before this normal flow resumes.

## 9. AI-assisted development rules

AI tools may inspect GitHub, propose plans, edit bounded branches, create Issues/PRs, and analyze
results. They do not replace review/evidence.

- Begin from the Issue and read current branch/code/docs before proposing a change.
- Do not invent repository state or claim tests were run without an actual result.
- Do not make one product-wide commit when the work can be reviewed in slices.
- Keep private reasoning out of commits/Issues; record the decision, evidence, and trade-off.
- Do not expose secrets, customer data, proprietary reports, or local filesystem details.
- Verify generated changes against tests and public contracts.
- Write durable decisions back to GitHub; chat history is not the project database.

## 10. Handling discoveries during implementation

When unrelated work is found:

1. stop expanding the current PR;
2. record a new Issue with evidence and priority;
3. link it from the current Issue/PR;
4. continue only the approved scope unless the discovery is a release/data/security blocker;
5. for blockers, explain the scope change and split/re-triage when practical.

This prevents audits and refactors from turning into unreviewable “fix everything” branches.
