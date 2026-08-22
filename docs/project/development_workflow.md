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

## 2. Active branch policy

The branch decision and exact validation evidence are recorded in
[`rc2_branch_transition_decision_2026-08-22.md`](../release_checks/rc2_branch_transition_decision_2026-08-22.md).

### Normal development

- `develop` is the canonical development base.
- Create feature, fix, refactor, test, security, documentation, and chore branches from `develop`
  unless the Issue is explicitly release-specific.
- Normal pull requests target `develop`.
- Broad new work must not target `rc2`, `release/2026.06-rc2`, or stale `master`.

### Current release candidate

- `release/2026.06-rc2` is the frozen candidate/evidence branch for
  `2026.06 RC2 (build 260711)`.
- Only release-blocking fixes, packaging/evidence work, release metadata/notes, and narrowly
  approved security/legal changes target this branch.
- Every accepted release-line change is reconciled into `develop` through a reviewed PR or an
  explicitly recorded equivalent; do not allow a release-only fix to disappear from future work.

### Transitional and production branches

- `rc2` is retained as a historical transition/reference branch. Do not start new routine work from
  it or target new routine pull requests at it after #900.
- `master` remains unchanged until exact candidate automation plus all applicable #901 packaged,
  clean-machine Windows, Google, notices, and legal evidence receives a release-owner Go decision.
- No force-push, history rewrite, or synthetic branch reconciliation is permitted.
- GitHub still presents `master` as the default branch, so select the PR base explicitly:
  `develop` for normal work or `release/2026.06-rc2` for approved release work.

## 3. Issue lifecycle

### 3.1 Create

Use one of the structured forms:

- Bug report — observed incorrect behavior or regression.
- Feature request — a user-facing capability or behavior change.
- Technical task — architecture, refactor, tests, performance, docs, security, or release work.

Use explicit priority/type prefixes until repository labels are expanded:

```text
[P0][Release] Close packaged promotion evidence
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
- target base branch;
- whether the work must be split.

Close duplicate, superseded, or rejected Issues with a reason. Do not leave an Issue open merely as
a vague idea bucket.

### 3.3 Definition of Ready

An Issue is ready when:

- [ ] the current behavior/problem is stated;
- [ ] intended outcome and non-goals are stated;
- [ ] acceptance criteria are testable;
- [ ] affected package/workflow is identified;
- [ ] target branch (`develop` or approved release branch) is identified;
- [ ] compatibility/data migration risk is identified;
- [ ] validation tier and likely focused tests are named;
- [ ] dependencies are resolved or linked;
- [ ] the work is small enough for one reviewable PR or has an explicit slice plan.

### 3.4 Implement

Create a branch from the approved base.

Recommended names:

```text
fix/<issue>-short-description
feature/<issue>-short-description
refactor/<issue>-short-description
docs/<issue>-short-description
test/<issue>-short-description
security/<issue>-short-description
chore/<issue>-short-description
release/YYYY.MM-rcN
hotfix/<version>-short-description
```

Examples:

```text
docs/902-roadmap-consolidation
refactor/903-export-run-stages
security/906-bandit-renewal
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
- Release-line work must remain within the frozen candidate scope and name its reconciliation path
  to `develop`.

### 3.5 Pull request

A pull request must:

- target the correct base branch explicitly;
- link the primary Issue (`Closes #...` when the PR completes it, otherwise `Refs #...`);
- state user/engineering impact and non-goals;
- describe risk and rollback;
- identify validation tier and exact commands/results;
- call out schema, public contract, packaging, security, native, Google, dashboard, or compatibility
  impact;
- explain release-to-`develop` reconciliation when it targets a release branch;
- remain small enough to review or explain why a larger integration PR is unavoidable.

Do not use “tests pass” as evidence without the command, result, or CI run. Do not mark a manual gate
complete from a mocked/unit test.

### 3.6 Review and merge

Review checks:

- acceptance criteria are covered;
- the base branch is correct;
- behavior and failure paths are understood;
- ownership boundaries improve or remain stable;
- tests prove the changed contract rather than only implementation details;
- sensitive data is absent;
- documentation/release evidence is synchronized;
- rollback is possible;
- release fixes have a documented reconciliation path into `develop`.

Preferred merge style for normal work is squash when repository policy/settings allow it, so one
Issue slice becomes one understandable commit. Release reconciliation may use a different method
only when history/evidence requires it.

### 3.7 Definition of Done

- [ ] Issue acceptance criteria are satisfied.
- [ ] Required focused/full/manual validation is recorded.
- [ ] CI is terminal for the exact merged content/tree.
- [ ] Documentation and changelog/release evidence are updated when applicable.
- [ ] Compatibility/data migration and rollback are complete.
- [ ] Release-line work is reconciled into `develop` or has an explicit tracked blocker.
- [ ] Temporary files/flags/dead plans are removed or explicitly tracked.
- [ ] Follow-up work has separate Issues rather than hidden TODOs.
- [ ] The primary Issue is closed by the merge or closed with a final evidence comment.

## 4. Priority model

| Priority | Meaning | Typical examples |
|---|---|---|
| P0 | Product head, data, release, or development base cannot be trusted safely | unvalidated candidate, destructive corruption risk, active secret exposure |
| P1 | Important release/integrity/security risk or major maintenance blast radius | packaging blocker, expiring security waiver, giant critical orchestrator |
| P2 | Valuable platform/product improvement with a workable current path | package centralization, measured optional acceleration |
| P3 | Polish, experiment, or low-impact convenience | minor visual refinements, exploratory spike |

Priority is about impact and urgency, not implementation size.

## 5. Type and area taxonomy

Recommended labels when repository label configuration is expanded:

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
- terminal GitHub Actions run for the exact head/content tree.

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
docs(project): consolidate active roadmaps
fix(parsing): reject mutated source before persistence
refactor(export): extract cancellation-safe stage coordinator
test(compat): move report behavior tests to canonical imports
```

A commit should be understandable without reading the entire diff. Avoid messages such as
“updates”, “fix stuff”, or model/session descriptions.

## 8. Release workflow

Current RC2 flow:

1. normal development proceeds on Issue branches from `develop`;
2. `release/2026.06-rc2` is frozen for release fixes/evidence only;
3. each release fix is validated on the exact candidate head and reconciled into `develop`;
4. #901 closes packaged Windows, Google, notice, and legal evidence;
5. the release owner records Go/No-Go;
6. only a Go candidate merges to `master` and receives a stable tag;
7. the production result is synchronized back to `develop`;
8. `rc2` can then be retired through an explicit cleanup decision.

Future normal flow:

1. develop features/refactors on Issue branches from `develop`;
2. cut `release/YYYY.MM-rcN` when scope freezes;
3. allow only fixes, evidence, version metadata, and release documentation on the release branch;
4. validate exact head automatically and manually;
5. merge approved release into `master` and tag `vYYYY.MM`;
6. sync the production result back to `develop`;
7. archive completed release plans/evidence appropriately.

## 9. AI-assisted development rules

AI tools may inspect GitHub, propose plans, edit bounded branches, create Issues/PRs, and analyze
results. They do not replace review/evidence.

- Begin from the Issue and read current branch/code/docs before proposing a change.
- Verify the target branch explicitly; do not rely on GitHub's default `master` selection.
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
