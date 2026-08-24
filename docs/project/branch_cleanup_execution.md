# Branch cleanup execution plan

- Status: Reconciled plan; no cleanup mutation is authorized
- Owner: Repository maintainer
- Last reviewed: 2026-08-24
- Evidence timestamp: `2026-08-24T06:46:02+02:00` (`Europe/Warsaw`)
- Repository: `hexafe/metroliza`
- Current integration baseline: `develop` at
  `1a060bfcc8c6e01901be7884d3a805f544eb918c`
- Live remote branch count: 9
- Execution issue: [#960](https://github.com/hexafe/metroliza/issues/960)
- Integrated source audit: closed [#911](https://github.com/hexafe/metroliza/issues/911), merged
  [PR #959](https://github.com/hexafe/metroliza/pull/959), and
  [`branch_audit.md`](branch_audit.md)

This document prepares later cleanup; it does not approve or perform it. A candidate disposition is
not permission to delete a ref. Every later mutation requires a fresh live-gate run, an exact-ref
decision recorded in #960, and external orchestrator approval under the project's destructive-
operation boundary. Approval covers one ref at one exact SHA. Any movement resets it.

No branch is deleted, no tag is created, moved, or deleted, no protected or release ref is updated,
and no history is rewritten by this plan or by PR #961.

## Integrated state and current gate

Completed:

- PR #910 integrated as `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`;
- the approved transition refs were reconciled without force;
- PR #958 integrated as `1b58303fee1483a88d2c987f7f06595dac8db7f3`;
- PR #959 integrated as current `develop`
  `1a060bfcc8c6e01901be7884d3a805f544eb918c`;
- #911 closed as completed.

The current gate is to reconcile, review, validate, and integrate PR #961. Its published remote head
at the evidence timestamp was `2a80a0dd3317fe17b5b4c3538e1adff1b284bd0b`. The normal merge of
current `develop` into the topic branch is `fcde300b13bca6b5cf6a49e7ee00ca410ddbca0a`.
The final content commit and exact-head CI belong in PR #961 metadata because a tracked document
cannot contain its own final commit SHA without changing that SHA.

The repository default remains `master`. `develop` is nevertheless the canonical base for normal
Issue-driven work. `release/2026.06-rc2` remains frozen release/evidence state, and `rc2` remains a
temporary transition/reference alias rather than a routine development base.

## Target branch model

```text
develop
├── feature/*
├── fix/*
├── refactor/*
├── docs/*
├── test/*
├── security/*
└── chore/*
```

- The canonical Issue namespaces above match [`branching_strategy.md`](../release_checks/branching_strategy.md)
  and [`development_workflow.md`](development_workflow.md). They are short-lived and merge through
  reviewed PRs into `develop`.
- Exploratory work still uses the documented namespace appropriate to its deliverable, a tracking
  Issue, bounded exit criteria, and a focused review; this plan adds no separate branch class.
- `master` stays outside the development tree as the default production/history anchor pending
  the separate #901 promotion decision.
- `release/2026.06-rc2` and `rc2` receive no routine development work.

The target model changes no GitHub default, protection, ruleset, release policy, tag, or ref by
itself.

## Current live-branch decision matrix

The nine rows below are the exact live remote inventory at the evidence timestamp. The active #961
row necessarily records its published pre-update head; its final reconciled head must be copied
from PR #961 into #960's recovery ledger before any later deletion evaluation.

| Branch and exact current SHA | Current role | Decision | Prerequisites | Risk | Rollback / recovery |
|---|---|---|---|---|---|
| `develop` — `1a060bfcc8c6e01901be7884d3a805f544eb918c` | Canonical Issue-driven integration branch and base of PR #961. | **KEEP**. | Preserve required checks and accepted branch policy; no #960 promotion operation. | GitHub still defaults to `master`, so contributors can select the wrong base. | Never delete or force-move it. Correct policy/settings through review and repair affected PR bases. |
| `master` — `ab26258e72d285c3917a595515798da185800373` | Repository default and production/history anchor. | **KEEP**; no promotion through #960. | Complete #901 and use a dedicated release decision/PR for any future promotion. | Treating ancestry as release evidence would bypass the product-wide delta and manual gates. | Use a reviewed revert or forward hotfix, then reconcile to `develop`; never rewrite production history. |
| `rc2` — `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac` | Temporary historical transition/reference alias; two commits behind `develop`. | **KEEP TEMPORARILY**. | #924 historical-ref decision, release reconciliation, full live deletion gate, and any required historical tag already present. | Early retirement can break unknown external references; continued use can attract wrong-base work. | Recreate only `refs/heads/rc2` from the exact full SHA in the approved ledger, then repair verified consumers. |
| `release/2026.06-rc2` — `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac` | Frozen candidate/evidence line while #901 remains open. | **KEEP**. | Complete #901 and a separate release-owner decision; reconcile accepted fixes into `develop`. | Feature drift or premature removal would invalidate release and rollback evidence. | Restore only from the approved exact ledger SHA or use a reviewed release-line revert; never move a published tag. |
| `docs/900-branch-transition` — `b978a759f341d2c0c44f61bc4d0416aec868fb0e` | Squash-integrated source of merged PR #910. | **DELETE candidate** after a fresh live gate. | Reconfirm its tree equals #910 squash `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`; verify every dependency class; record approval and ledger. | Graph-unique squash-source commits and an unknown external name consumer can be mistaken for unique product work or ignored. | Recreate the exact branch from recovery SHA `b978a759f341d2c0c44f61bc4d0416aec868fb0e`. |
| `docs/project-governance-reset` — `375cc433f0af4d2d0a49e5dacc33ec0b53733479` | Squash-integrated source of merged PR #909. | **DELETE candidate** after a fresh live gate. | Reconfirm its tree equals #909 squash `a03bbdacbd6c308acf46ca31c16d0dd2caeab304`; verify every dependency class; record approval and ledger. | The source commit leaves normal branch reachability, and an unknown external consumer may still use the name. | Recreate the exact branch from recovery SHA `375cc433f0af4d2d0a49e5dacc33ec0b53733479`. |
| `docs/project-specification-roadmap-2026-08` — `b8b698c020f616a3c53bcc5286291206ae1026f3` | Squash-integrated source of merged PR #958. | **DELETE candidate** after a fresh live gate. | Reconfirm its tree equals #958 squash `1b58303fee1483a88d2c987f7f06595dac8db7f3`; verify every dependency class; record approval and ledger. | Graph history differs despite zero source-to-squash tree delta; external name use remains unknown until the gate. | Recreate the exact branch from recovery SHA `b8b698c020f616a3c53bcc5286291206ae1026f3`. |
| `docs/911-branch-archaeology-audit` — `ee026f6a5af96792c7b3c2a76d5ced4cb57c6ff3` | Source of merged PR #959; its tree equals the #959 squash result. | **DELETE candidate**, but only after PR #961 is integrated and no longer depends on its history. | Reconfirm tree equivalence to `1a060bfcc8c6e01901be7884d3a805f544eb918c`; rerun every dependency check after #961 integration; record approval and ledger. | Removing it before the stacked-history handoff is complete can impair review or recovery. | Recreate the exact branch from recovery SHA `ee026f6a5af96792c7b3c2a76d5ced4cb57c6ff3`. |
| `docs/960-branch-cleanup-execution` — published snapshot `2a80a0dd3317fe17b5b4c3538e1adff1b284bd0b` | Active PR #961 head carrying this two-file plan. | **KEEP** while PR #961 is active; evaluate as a separate **DELETE candidate** only after merge. | Integrate #961 first; record its final reconciled full head from PR metadata as the recovery SHA; then rerun every live gate and obtain a separate approval. | A self-referential or stale SHA, active PR use, or premature deletion would break review and make recovery ambiguous. | Recreate only from the final PR-head SHA recorded in #960 immediately before any approved deletion; never substitute this pre-update snapshot or a similar commit. |

The first three DELETE candidates have no current open PR head/base use. Direct source-to-squash
tree comparison returned equality for all three. The audit source also equals its #959 squash tree.
Those facts establish integration evidence, not deletion permission. Repository documents that
name a branch for history or recovery do not by themselves require the live ref, but workflows,
rulesets, settings, releases, external handoffs, and rollback dependencies must still be checked
immediately before each proposed mutation.

## Historical dispositions

These records preserve useful evidence without resurrecting broad historical branches:

- **Recovered RC1 evidence:** no exact bare `rc1` tip is proven. Under #924, verify the intended
  state using concrete evidence such as `release/2026.03-rc1` at
  `260a70d00eec296e101b736776129778d86aa042` and the later fixes head
  `c593953f3f862289be84252d120a1c79c6f468ad`. Any tag decision is separate; this plan creates none.
- **Performance boost:** **SALVAGE** benchmark evidence, parity intent, and focused requirements
  through #918/#908 from recovered tip `75f79b5a1c9211019c8b5d75ea61a904aad5fc55`;
  do not recreate or wholesale-merge the historical branch.
- **Report metadata redesign:** **SALVAGE** unmet contract/schema intent through #917 from recovered
  tip `efe1c430c30ecb98ecb1246113e4869192f9c3bf`; do not wholesale-merge it.
- **Realtime/industrial/ML:** **SALVAGE** contracts, deterministic fixtures, source-safety and
  operator safeguards through #919/#941 from recovered tip
  `13c47617ef85dc1a92d2088a8e1bd873cee4fe76`; do not wholesale-merge it.

All recovered tips are already ancestors of `develop`; they are not missing code branches.

## Exact execution sequence

### Completed

1. Integrate #910 and the accepted branch policy.
2. Reconcile the approved transition refs without force.
3. Reconcile and integrate #958.
4. Reconcile and integrate #959.
5. Close #911 as completed.

### Current

6. Reconcile PR #961 with current `develop`, preserve the merged audit byte-for-byte, confirm the
   net diff is only this plan and its docs index entry, obtain exact-head review/CI, and integrate
   it through normal review. Integration of the plan authorizes no cleanup.

### After PR #961

7. Fetch and refresh the complete live inventory.
8. Evaluate each deletion candidate separately against the live gate.
9. Record one exact recovery-ledger entry per ref.
10. Obtain a separate external-orchestrator approval for each destructive operation.
11. Execute at most one approved mutation at a time, using an atomic expected-old-value guard tied
    to the exact approved SHA; abort without mutation if the ref moved.
12. Verify the resulting remote state immediately after that mutation and update #960.
13. Repeat only for another separately approved exact ref.
14. Run and attach a final live-branch inventory.

Recommended evaluation order, which is **not permission to delete anything**:

1. `docs/900-branch-transition`
2. `docs/project-governance-reset`
3. `docs/project-specification-roadmap-2026-08`
4. `docs/911-branch-archaeology-audit`, only after PR #961 integration
5. `docs/960-branch-cleanup-execution`, only after PR #961 integration

## Strict deletion gate

A branch remains **KEEP** unless every item is freshly proven for its exact current SHA:

- [ ] no open PR uses it as head or base, and no stacked review depends on its history;
- [ ] no workflow, ruleset, release, repository setting, document, scheduled job, deployment,
  submodule, script, known external integration, or handoff depends on the live branch name;
- [ ] graph plus direct tree/patch comparison proves no unreviewed unique work remains; a squash-
  integrated branch is never judged from graph uniqueness or ancestry alone;
- [ ] no release, support, or rollback evidence depends on the branch;
- [ ] any required historical tag already exists at the verified exact SHA;
- [ ] the exact commit object is durably recoverable without the branch being deleted: it is either
  reachable through a retained fetchable ref whose retention is verified, or stored in a verified
  Git bundle in maintainer-controlled durable storage with its checksum and restore test recorded;
- [ ] the full recovery SHA, evidence, approver, approval timestamp, and rollback owner are recorded
  in #960;
- [ ] the exact deletion command uses an expected-old-value lease for the approved full SHA and
  cannot delete a different tip if the branch moves between approval and execution;
- [ ] external orchestrator approval names this one ref and exact SHA.

Any ref movement invalidates every prior check and approval. A published tag is never moved. Tag
creation or correction requires its own reviewed decision and is outside this plan.

## Recovery ledger template

Record one entry in #960 before each later operation:

| Field | Required value |
|---|---|
| Exact ref | Full `refs/heads/...` or `refs/tags/...` name |
| Observed SHA | Full 40-character SHA immediately before approval |
| Intended mutation | One operation on this exact ref, including the expected-old-value guard |
| Integration evidence | Source/squash/tree/patch and PR links |
| Dependency evidence | PR, workflow, ruleset, setting, release, document and external checks |
| Release/tag evidence | Release/rollback dependency result and any required existing tag |
| Object-retention evidence | Retained fetchable ref, or durable Git-bundle location, checksum and clean restore-test result |
| Approval | Named approver, external-orchestrator decision link, and timestamp |
| Rollback owner | Named person responsible for recovery and verification |
| Expected result | Exact expected post-operation ref state |
| Verification | Commands/results and final remote inventory link |

### Conditional deletion command

After every gate and approval is complete, the separately authorized operator must bind deletion to
the approved old value atomically:

```bash
git push \
  --force-with-lease=refs/heads/<EXACT_BRANCH_NAME>:<APPROVED_FULL_SHA> \
  origin :refs/heads/<EXACT_BRANCH_NAME>
```

Here `--force-with-lease` is an expected-old-value guard for deletion, not permission to rewrite a
surviving branch. If the remote ref no longer equals `<APPROVED_FULL_SHA>`, the command must fail and
the gate must restart from the new tip. A name-only deletion command is not permitted.

## Rollback rules

### Branch deleted incorrectly

The SHA is an identifier, not an archive. Before deletion, prove that the exact commit can be
fetched from a retained durable ref or restored from the verified Git bundle recorded in the
ledger. A GitHub PR page or remembered SHA is not sufficient unless its backing ref is confirmed
fetchable and retained for the required recovery period.

After separate recovery approval, fetch or restore that preserved object into a clean clone and
verify that it resolves to the ledger's full SHA. A commit restored only from a bundle or another
off-repository location must first be uploaded without risking an existing ref or running historical
workflow code. Create a unique, one-use staging commit whose parent is `<RECORDED_FULL_SHA>`, then
push that commit to a newly generated non-branch ref under
`refs/notes/metroliza-recovery-staging/` with an expected-absent lease. The recovery approval and
ledger must cover the exact staging-ref name, staging SHA, owner and later removal:

```bash
git push --porcelain \
  --force-with-lease=refs/notes/metroliza-recovery-staging/<ONE_USE_ID>:0000000000000000000000000000000000000000 \
  origin <UNIQUE_STAGING_COMMIT>:refs/notes/metroliza-recovery-staging/<ONE_USE_ID>
```

The staging commit must be created locally after the one-use name is chosen, must have the recovered
commit as a parent, and must not be reused. Continue only when the porcelain result reports a newly
created reference; an up-to-date result, rejection or pre-existing staging ref is changed external
state and requires an abort. Before use, audit every push-triggered workflow and integration to prove
that the non-branch staging namespace cannot trigger it; do not fall back to a branch or tag without
a separately reviewed automation exclusion. Verify through GitHub's Git API that
`<RECORDED_FULL_SHA>` now exists in the target repository. If the recovery object was already
retained by a fetchable ref in the target repository, record and verify that ref instead of creating
a staging ref.

Confirm the deleted branch is still absent, then recreate it with GitHub's atomic create-ref
operation:

```bash
gh api --method POST repos/hexafe/metroliza/git/refs \
  -f ref='refs/heads/<EXACT_BRANCH_NAME>' \
  -f sha='<RECORDED_FULL_SHA>'
```

GitHub's create-ref endpoint rejects any existing branch, including a concurrent recreation
at the same SHA. Treat that rejection as changed external state and never overwrite the target ref.
Before aborting, remove any one-use staging ref with an expected-old-value lease bound to its
recorded staging SHA; if that cleanup fails, retain and record the staging ref for separate review
rather than forcing it. Then abort and rerun ownership and dependency checks. Apply the same
lease-guarded staging cleanup after the restored target branch is successfully verified. Only then
repair verified PR bases, workflows, settings, release references, or handoffs and rerun their
checks. Never assume an unreachable SHA can be restored, and never guess a recovery SHA from a
commit subject, prefix, nearby branch, or similar tree.

### Documentation or policy integration fails

Revert through a new reviewed PR, reopen the governing Issue if needed, and rerun exact-head docs
and CI checks. Never reset a protected branch.

### Release state fails

Use a reviewed revert or forward hotfix on the affected retained branch, then reconcile it into
`develop`. Freeze on any tag error: a published tag is never silently moved or recreated.

### Salvaged work fails

Close or revert only the focused salvage PR and apply its documented feature/schema/data rollback.
Historical branch names remain absent and are not used as rollback mechanisms.

## Acceptance gates

PR #961 is ready to integrate only when:

- its base is current `develop` and its net diff contains exactly
  `docs/project/branch_cleanup_execution.md` plus the matching `docs/README.md` entry;
- `branch_audit.md` is byte-for-byte the current `develop` version;
- all nine live branches appear exactly once with current SHAs and bounded dispositions;
- focused validation, the deterministic live audit, exact-head GitHub CI, and review are terminal;
- PR metadata records the final head and confirms that no cleanup mutation occurred.

Cleanup itself is complete only after the plan is integrated and every later mutation has passed a
fresh exact-ref gate, has a verified durable recovery object plus an individual recovery ledger and
approval, is verified immediately, and is included in the final inventory. This document never
supplies those approvals.
