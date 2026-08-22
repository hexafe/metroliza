# RC2 Branch Transition and Automated Validation Decision — 2026-08-22

Status: Active release/branch decision  
Owner: Release and architecture maintainer  
Decision Issue: #900  
Manual promotion evidence: #901  
Release identity: `2026.06 RC2 (build 260711)`

## Decision summary

**GO** for establishing a trustworthy development/release branch topology from the validated RC2
content.  
**NO-GO** for promotion to `master`, a stable tag, or a production-release claim.

The approved topology is:

- `develop` — canonical base for all new Issue-driven development;
- `release/2026.06-rc2` — frozen release-candidate and promotion-evidence line;
- `rc2` — retained transition/reference branch; no new feature or refactor work targets it after
  this decision is merged;
- `master` — unchanged historical/default branch until the release owner accepts all automatic and
  manual promotion gates.

This decision creates and fast-forwards branches only. It does not rewrite history, delete a
branch, move a tag, change release metadata, or declare the RC released.

## Repository state before the decision

- `master`: `ab26258e72d285c3917a595515798da185800373`, dated 2026-03-30.
- Product implementation head before governance: `rc2` at
  `202690eb21087314a3c8000aa3ebdb58a1a09c1b`, dated 2026-07-17.
- At the 2026-08-22 audit snapshot, the implementation head was 278 commits ahead of `master` and
  zero commits behind it.
- PR #895 documented green CI for the earlier head
  `ce7556098626f93d3ade95abd49ede00be341611` but intentionally closed without promotion.
- Commit `202690eb21087314a3c8000aa3ebdb58a1a09c1b` was one product-wide commit after that prior
  validated head and therefore required fresh evidence.

## Validated branch point

Project-governance PR #909 was built from the current product head and merged to `rc2` as:

- final commit: `a03bbdacbd6c308acf46ca31c16d0dd2caeab304`;
- final tree: `dc10e028332cb311cb0b2c110deecee2841b9799`;
- parent product commit: `202690eb21087314a3c8000aa3ebdb58a1a09c1b`.

Pull-request CI run `32585291955` tested GitHub's synthetic merge commit:

- tested merge commit: `0a3f2b982f827466f214cede76995a5bf3effa14`;
- tested tree: `dc10e028332cb311cb0b2c110deecee2841b9799`.

The tested synthetic merge and the final squash merge have the same tree SHA. The automated evidence
therefore applies to the exact repository content selected as the branch point, even though the
commit object and parent structure differ.

## Automated evidence

CI run `32585291955` completed with these terminal results:

| Gate | Result |
|---|---|
| Compile check | Passed |
| Parser-profile self-service smoke | Passed |
| Ruff full repository | Passed |
| Selected strict mypy boundaries | Passed |
| Release metadata consistency | Passed |
| Secret scan | Passed |
| Release hygiene | Passed |
| Dependency/security audit, including pinned sibling packages | Passed |
| Main test suite | `3030 passed, 21 skipped, 8 warnings, 98 subtests passed` |
| Additional real-Qt append shards | Passed |
| Aggregate line coverage | `83.80%` |
| Canonical `src/metroliza` line coverage | `85.72%` |
| Blocking coverage threshold | `80%` — passed |
| Native wheel builds and imports | Passed |
| Native chart/parser/export parity smoke | Passed |
| Windows core path/SQLite/metadata smoke | Passed |
| CMM parser performance guardrail | Passed |
| Performance trend check | Passed |

The following manual/opt-in lanes were intentionally skipped by normal PR CI:

- packaged Windows startup benchmark;
- packaging smoke;
- live Google conversion smoke.

Their skipped state is not a failure of the automatic gate, but it is also not release-promotion
evidence.

## Branches created

The following refs were created from commit
`a03bbdacbd6c308acf46ca31c16d0dd2caeab304` before this decision-document PR:

- `develop`;
- `release/2026.06-rc2`;
- `docs/900-branch-transition` for this documentation change.

After this decision PR is reviewed and merged, `develop` and `release/2026.06-rc2` are to be
fast-forwarded to the final decision commit so all active lines share the same policy/evidence
baseline. `rc2` receives the decision through the PR merge. No force update is permitted.

## Active branch policy

### `develop`

Use for:

- new features;
- behavior-preserving refactors;
- tests and quality work;
- documentation not specific to the current frozen release;
- dependency and shared-package work approved by an Issue.

Issue branches start from `develop` and normally target `develop`.

### `release/2026.06-rc2`

Use only for:

- release-blocking defect fixes;
- packaging and clean-machine fixes;
- release evidence and checklists;
- release metadata/notes required for the candidate;
- narrowly approved security or legal-notice changes.

Every change must link a release Issue and be backported or reconciled into `develop` so the lines do
not diverge silently.

### `rc2`

Retain as a historical transition/reference branch while the release is unresolved. Do not start
new work from it and do not target routine pull requests at it after this decision. It may be
retired only in a separate explicit cleanup after the release branch and `develop` are established
and any useful external references are preserved.

### `master`

Do not merge or force-update it during this transition. Promotion requires:

1. exact automatic CI for the final release-candidate content;
2. all applicable #901 packaged/manual/Google/legal evidence;
3. release-owner go decision;
4. reviewed merge plan and stable tag.

`master` remaining the GitHub default branch does not make it the development base. Pull-request
base must be selected explicitly as `develop` or `release/2026.06-rc2` according to scope.

## Remaining promotion blockers

Issue #901 owns the release-blocking evidence that automatic CI cannot honestly replace:

- approved PyInstaller and Nuitka artifact builds;
- third-party notice and inventory staging/hash verification;
- representative parser, SQLite, dashboard, realtime, workbook, and export smoke on packaged
  artifacts;
- clean-machine Windows executable launch/readiness evidence;
- secure live Google conversion smoke with cleanup and preserved local `.xlsx` fallback;
- release-owner/legal review of PyQt/Qt, PyMuPDF, Rust crates, and generated notices.

Until #901 is complete, the candidate remains **NO-GO for `master` promotion**.

## Release-fix flow

1. Create or refine a release-blocking Issue.
2. Branch from `release/2026.06-rc2` using `fix/<issue>-...`, `security/<issue>-...`, or
   `docs/<issue>-...`.
3. Target the pull request at `release/2026.06-rc2`.
4. Run the required automatic and manual validation tier against the exact candidate head.
5. Reconcile the accepted commit into `develop` through a reviewed PR/cherry-pick strategy; do not
   let the fix live only on the release line.
6. If a change expands product scope or destabilizes the candidate, defer it to `develop` or cut a
   later candidate rather than silently mutating RC2 scope.

## Rollback and failure handling

- Branch creation is non-destructive and can be abandoned without rewriting existing history.
- A failed candidate is fixed through normal commits or superseded by a new release branch/tag; a
  published tag is never moved.
- If branch policy proves unsuitable, change it through a new Issue and documentation PR.
- `master` and prior release evidence remain untouched until promotion.
- No application behavior changed as part of the branch decision itself.

## Completion criteria for #900

- [x] Current selected content has terminal automatic CI evidence.
- [x] Exact commit/tree identity and test outcomes are recorded.
- [x] Manual promotion blockers are explicitly linked to #901 and not waived.
- [x] `develop` is named and created as the canonical development base.
- [x] `release/2026.06-rc2` is named and created as the candidate/evidence line.
- [x] `master` promotion is explicitly rejected pending manual evidence.
- [x] No force-push, history rewrite, or destructive branch operation is used.
- [ ] This decision PR is merged and active branch refs are fast-forwarded to its final commit.
