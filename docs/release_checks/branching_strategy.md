# Branching strategy

This document defines the lightweight branching model used for Metroliza development and release
work. Current RC roles and qualification are recorded in [release status](release_status.md).
The historical branch transition and automatic evidence are recorded in
[`rc2_branch_transition_decision_2026-08-22.md`](./rc2_branch_transition_decision_2026-08-22.md).

## 0) Active repository state — naming decision 2026-11-13

The Product Owner selected `main`, `dev`, `rc`, plus genuinely active unmerged PR heads under
[#960](https://github.com/hexafe/metroliza/issues/960). This supersedes earlier current-role names,
while preserving history, exact-ref recovery, review gates and release acceptance:

| Ref | Obligation | Owner | Lifecycle |
|---|---|---|---|
| `main` | GitHub default, production/history anchor (renamed from `master`) | repository owner | long-lived; no product promotion from renaming |
| `dev` | daily Issue-driven integration and normal PR target (formerly `develop`) | repository owner | long-lived |
| `rc` | active frozen candidate source/evidence line | release owner | long-lived name; each candidate requires its own exact evidence and release decision |

The migration renames historical `rc2` to `rc`, preserving hosted `blob/rc2/...` redirects for
frozen parser-plugin scaffolds (#1187), then advances `rc` through a history-preserving reviewed PR
from `release/2026.09-rc1` with only admitted migration corrections. Verify redirects and content
both before and after that advance. Do not recreate the retired names; doing so can replace the
redirect. Renaming does not qualify the frozen build or promote development product code.

CI retains legacy literal/pattern push coverage for safe transition. That compatibility does not
authorize old branches, and removing those literals is not a required later config-only cleanup.
Remote retirement still uses the exact-ref cleanup gate; active PR heads retire with their PRs.

The 2026.06 RC2 cycle closed without a release (#901). `release/2026.06-rc2` was retired;
its head `1eeeab27` remains at `archive/2026.06-rc2/final`, a recovery point rather than an
accepted release. `release/1158-build-261029` was also retired (recovery: `refs/pull/1169/head`).
Earlier inventories and release decisions below remain historical evidence.

## 0.1) Historical repository state — decision 2026-10-27 (superseded)

Under [#1153](https://github.com/hexafe/metroliza/issues/1153), integrate #1109, #1142, the accepted
STEP2+STEP3 aggregate and refreshed #1063 into develop using merge commits, then cut
`release/2026.09-rc1` from the accepted final develop. Exact commits, trees and gates are in that
execution ledger. Current candidate source is distinct from final packaged qualification.

(Superseded: the current retained refs are listed in section 0.) Keep seven refs after the finite cleanup: master, develop, release/2026.09-rc1, historical rc2,
historical release/2026.06-rc2, and the dependency branches for #972/#973. The two historical refs
and two dependency branches are named exceptions to the ordinary small branch set. They remain
until their own lifecycle/update criteria are met. No master promotion or published release.

Final build identity and Windows packaged EXE acceptance are pending. Before RC distribution,
qualify the exact final artifact per release_status and the RC checklist; do not reuse historical
build261021 metadata. Archive source/provenance separately. Preserve history, retained recovery
refs, original adverse receipts and expected-old-SHA deletion guards.

Newly admitted release work selects `dev` normally, or `rc` for approved frozen-candidate work.
The historical June and October selections below do not assign current work.

## 0.2) Historical repository state — decision 2026-08-22

- `develop` is the canonical branch for new Issue-driven development.
- `release/2026.06-rc2` is the frozen release-candidate/evidence branch for
  `2026.06 RC2 (build 260711)`.
- `rc2` is retained as a historical transition/reference branch and is no longer a target for new
  routine work.
- `master` remains the unchanged default/historical production branch until the current candidate
  receives complete automatic and manual promotion evidence plus a release-owner Go decision.

Validated branch-point content before this decision PR:

- commit: `a03bbdacbd6c308acf46ca31c16d0dd2caeab304`;
- tree: `dc10e028332cb311cb0b2c110deecee2841b9799`;
- CI run: `32585291955`;
- CI-tested synthetic merge: `0a3f2b982f827466f214cede76995a5bf3effa14`;
- tested and final tree SHA are identical.

The automatic gates passed, but packaged/clean-machine Windows, live Google conversion,
third-party notice/artifact, and legal/release-owner evidence remains open in #901. Therefore:

- branch reorganization: **Go**;
- `master` promotion/stable tag: **No-Go pending #901**.

Because GitHub still presents `master` as the default branch, every new pull request must select
its base explicitly: normally `develop`, or `release/2026.06-rc2` for approved release work (historical; that branch was retired on 2026-11-04).

## 0.3) Current Dependabot policy

The checked-in `.github/dependabot.yml` targets normal version-update PRs at `dev`.
GitHub reads this configuration from the actual default branch, `main`, so synchronization there
is required before activation. Security-update PRs still target that default separately;
`target-branch` does not redirect them. This does not authorize routine work on `main`.
Reconcile accepted security fixes into `dev` and `rc` where applicable.

## 1) Branch purposes

### `main`

`main`: current production-ready branch and historical/default production anchor. It represents
the last accepted production state; the historical `2026.06 RC2` cycle was closed without a release
(#901, 2026-11-04) and is not a promotion candidate. Only reviewed, release-owner-approved candidate merges and
minimal production hotfixes belong here.

`main` is not a development base. Its default-branch status does not authorize feature/refactor
work or promotion from an unvalidated branch.

### `dev`

Integration branch for active Issue-driven development:

- features;
- bug fixes not specific to the frozen candidate;
- behavior-preserving refactors;
- tests, documentation, security, dependencies, and shared-package work;
- future release preparation before feature freeze.

Normal Issue branches start from and target `dev`.

### `rc`

Current candidate source/evidence line, originally cut from accepted development under #1153 as `release/2026.09-rc1`. Only approved
release fixes, qualification evidence and reviewed candidate metadata belong here after freeze.
Reconcile accepted fixes into `dev`. Final build/EXE qualification and release-owner Go remain
separate from the source cut and repository cleanup.

### `release/2026.06-rc2` (retired 2026-11-04)

Retired: the 2026.06 RC2 cycle closed without a release (#901). Recovery point:
`archive/2026.06-rc2/final` → `1eeeab27`. The restrictions below are kept as the historical record of
that line. Allowed changes were limited to:

- release-blocking defects;
- packaging/clean-machine fixes;
- release checks, evidence, notes, and metadata;
- narrowly approved security/legal-notice changes.

Every accepted release-line fix must be reconciled into `develop`. No feature expansion, broad
refactor, convenience dependency upgrade, or visual redesign enters this branch without the formal
late-scope exception process.

### `rc2` (historical name)

Historical transition/reference branch (same commit as `archive/2026.06-rc2/final`). Do not branch new
work from it or target pull requests at it. The migration redirects the old hosted
`blob/rc2/...` links to `rc`; preserve verification of the frozen consumer (#1187).

### `hotfix/*`

Urgent production-fix branches cut from `main` after a stable release. They merge into `main`
and are then reconciled into `dev` and any active release line as applicable.

### Issue branches

Short-lived branches for one Issue or one reviewable slice of an Issue.

## 2) Issue branch naming

Use the primary Issue number and a short lowercase description:

- Bug fix: `fix/<issue>-<description>`
- Feature: `feature/<issue>-<description>`
- Refactor: `refactor/<issue>-<description>`
- Documentation: `docs/<issue>-<description>`
- Tests: `test/<issue>-<description>`
- Security: `security/<issue>-<description>`
- Chore/CI/dependency: `chore/<issue>-<description>`

Examples:

```text
docs/902-roadmap-consolidation
refactor/903-export-run-stages
security/906-bandit-renewal
fix/901-packaged-startup-blocker
```

Keep one primary Issue per branch/PR. Split broad Issues into several independently reviewable
branches instead of one product-wide change set.

## 3) Release and hotfix naming

- Release candidate branch: `rc`; candidate numbers belong to release metadata/tags, not new branches
  - Historical example (retired 2026-11-04, tag `archive/2026.06-rc2/final`): `release/2026.06-rc2`
- Hotfix branches: `hotfix/<version>-<description>`
  - Example: `hotfix/2026.09.1-startup-fix`

Future candidate preparation on the existing line:

```bash
# Prepare the approved dev scope on rc through a reviewed release PR.
git checkout rc
git pull --ff-only origin rc
```

Do not reuse the historical bare `rc2` naming pattern for future cycles.

## 4) Merge directions

### Normal development

```text
Issue branch -> dev
```

### Current/future release stabilization

```text
dev -> rc                         (reviewed approved scope at feature freeze)
release-fix branch -> rc
accepted release fix -> dev        (reviewed reconciliation)
approved rc -> main                (release-owner Go and all promotion gates)
main -> dev                        (post-release synchronization)
```

### Production hotfix

```text
main -> hotfix/<version>-...
hotfix -> main
hotfix result -> dev and rc where applicable
```

No direct feature/refactor merge into `main` or frozen `rc`.

## 5) Allowed change types per branch

### `main`

Allowed:

- approved release merges;
- approved minimal hotfixes;
- documentation tied directly to production behavior when reviewed through the same process.

Not allowed:

- incomplete features;
- experiments;
- broad refactors;
- work based on stale branch assumptions.

### `dev`

Allowed:

- Issue-driven features and bug fixes;
- behavior-preserving refactors;
- tests, documentation, dependency maintenance, and research decisions;
- integration work that remains releasable through normal review.

Not allowed:

- untracked work without an Issue;
- unrelated scope bundled into one branch;
- secret/proprietary fixtures.

### `rc`

Allowed:

- bug/regression fixes required for release;
- release notes/version metadata;
- packaging, smoke, security, and evidence work;
- documentation required for release readiness.

Not allowed:

- new feature scope;
- broad architecture refactors;
- convenience dependency upgrades;
- visual redesign.

Late-scope exception: after feature freeze, a scope-expanding change enters the RC line only when
`implementation_item_triage.md` records the rationale, owner, target RC, test evidence,
rollback/deferral option, and explicit release-owner approval. Manual release evidence still
applies.

### `hotfix/*`

Allowed:

- minimal production fix;
- required regression test;
- required release/version/documentation evidence.

Not allowed:

- unrelated cleanup;
- features;
- broad dependency changes or refactors.

## 6) Pull requests and merge safety

- Every PR links one primary Issue.
- Every PR explicitly selects the correct base branch; never rely on the GitHub default.
- CI evidence must be terminal for the exact PR head/content tree.
- Behavior changes and structural refactors should be separate PRs.
- A large integration PR must explain why it could not be safely split.
- Release-line PRs must document reconciliation into `dev`.
- Avoid force-push after release evidence/review starts; if unavoidable, invalidate and rerun exact
  head evidence.
- Prefer squash merge for normal Issue slices when repository settings permit it.
- Release/history reconciliation uses the merge method that preserves required evidence and is
  explicitly stated in the release decision.

## 7) Tagging rules

- Tag each approved release candidate on `rc` using an annotated tag:
  `vYYYY.MM-rcN`.
- After production promotion, tag the approved merge commit on `main` as `vYYYY.MM`.
- Do not move or recreate a published tag. Create a new `-rcN` or patch version.
- Hotfix versions must progress monotonically according to the selected release scheme.
- The 2026.06 RC2 line is never tagged as stable: its cycle closed without a release (#901); its
  head is preserved only as the recovery tag `archive/2026.06-rc2/final`.

## 8) Branch lifecycle and housekeeping

The intended steady state is deliberately small:

```text
main                   # production/history default
dev                    # daily integration and normal PR target
rc                     # active candidate; immutable tags identify each release iteration
<active PR heads>      # feature/fix/docs/test/chore/etc. currently being reviewed or integrated
```

A remote branch is a **temporary execution ref, not an archive or evidence store**. Durable evidence
lives in the linked Issue/PR, commit/tree SHA, CI run, retained artifact, and release tag when
applicable.

### Create fewer branches

- Create one branch for one primary Issue/PR when implementation actually starts.
- Do not create remote branches for backlog ideas, read-only reviewers, agents, test attempts,
  review rounds, checkpoints, or "maybe useful later" snapshots.
- Keep in-scope corrections on the existing branch/PR.
- Research/design work uses an Issue/comment or a documentation PR. It gets a dedicated remote
  branch only when it contains a concrete mergeable deliverable.
- A replacement `-v2` branch is exceptional: record why the first branch cannot continue and close
  or retire the predecessor rather than keeping competing versions indefinitely.

### Delete as part of merge closeout

The merging orchestrator owns the **retirement decision** in the same closeout as the merge.
Merge authority does not itself authorize destructive ref deletion.

Default lifecycle:

> **Merged PR -> mark its source branch DELETE_CANDIDATE immediately -> delete it in the next approved exact-ref cleanup batch.**

A cleanup batch may contain many branches, so this safety gate must not turn ordinary housekeeping
into one approval per branch. Before mutation, however, the Product Owner approval must name the
finite manifest containing each exact branch and expected full SHA.

Keep the branch only when a **named live dependency** still requires that ref name, such as an open
PR based on it, an active release/integration stack, or a currently running executor/workflow that
cannot yet move. The keep decision must name the consumer and the exact retirement trigger.

A historical link, old CI run, benchmark, audit, review, or useful commit is **not** a reason to keep
the branch. Preserve that evidence through verified retained PR refs/artifacts; every deletion still requires
the clean-repository recovery-fetch proof below, including merged and squash-merged work.

Closed or superseded unmerged PRs also retire once unique useful work is either integrated elsewhere
or deliberately preserved in a durable PR/commit/document. Do not merge stale code merely to make
the branch list shorter.

### Temporary integration stacks are exceptions

Normal work starts from and targets `dev`. A delivery may temporarily use an integration branch
and, when genuinely required, one acceptance/package branch. Such a stack must have:

- one delivery owner;
- an explicit dependency map;
- a named final destination;
- a retirement trigger.

Do not grow a tree of per-worker/per-test integration branches. When leaf work is integrated into the
retained integration branch, retire the leaf branch. When the delivery is reconciled into its final
branch, retire the integration/acceptance refs.

### Cleanup gate

Before deleting a branch:

1. re-read its exact current ref/full SHA, PR state and complete remote inventory;
2. inspect the full live-consumer list from the
   [exact-ref deletion gate](../project/branch_cleanup_execution.md#fresh-exact-ref-deletion-gate):
   open PR head/base and stacked review history; workflows, rulesets, releases, settings, documents,
   scheduled jobs, deployments, submodules, scripts, package jobs, support processes, known
   integrations and handoffs; also active executors, release/integration stacks, rollback and
   product-control evidence. Record any named consumer and retirement trigger. Historical mentions
   alone are not live consumers. Private GitHub App settings and unknown off-GitHub consumers need
   explicit owner/PO attestation; absence from repository search is not proof of no consumers;
3. prove accepted work is present in the retained destination and no unreviewed unique work remains,
   using graph plus direct tree/patch comparisons as applicable. For **every deletion**, including
   merged, squash-merged, closed and superseded PR branches, prove in a clean disposable repository
   that the exact source commit and tree can be fetched from the recorded durable retained recovery
   ref (for example `refs/pull/<number>/head`) or separately approved restore-tested recovery object.
   Record fetched commit/tree and successful fetch result. A SHA, web page, merged badge or squash
   destination alone is not recovery proof; keep separately preserved unique work for unmerged PRs;
4. obtain Product Owner approval for the finite manifest of exact refs/full expected SHAs with
   recovery ref/commit/tree, consumer evidence/attestations, rollback owner and guarded command;
   record that manifest, approver, approval timestamp and expected result in the authoritative
   exact-ref execution ledger #960 before execution;
   candidate or recovery movement invalidates the affected gate and authorization;
5. delete each approved exact ref/SHA at most once with an expected-old-value lease; never use a
   wildcard, blind force, name-only fallback or automatic retry/alternate mutation after failure;
6. immediately verify absence, unchanged recovery ref/commit/tree and complete remote inventory,
   including retained heads unchanged; record actual per-row result, immediate verification and
   adverse receipts in #960. Batch summaries in #921 or another assigned ledger link to those
   canonical per-ref records and never replace them.

A branch with no open PR and no explicit release/integration role is a cleanup candidate immediately.
Housekeeping should happen continuously after merges, not as a rare repository-wide archaeology
project. There is no cosmetic numeric branch cap, but the normal count should be approximately the
long-lived refs plus genuinely active PR heads.

### Long-lived and historical release refs

Keep `main`, `dev` and `rc` in their current roles. Preserve historical release points as verified
immutable recovery refs (annotated `archive/...` tags or retained PR refs). Retire superseded topic
and release refs through the exact-ref gate. The naming migration does not authorize production
promotion or recreate retired branch names; each candidate still needs its own qualification.
