# Branch cleanup execution plan

- Status: Proposed; execution is not authorized by this document
- Owner: Repository maintainer
- Last reviewed: 2026-08-22
- Repository: `hexafe/metroliza`
- Execution issue: [#960](https://github.com/hexafe/metroliza/issues/960)
- Source audit: [#911](https://github.com/hexafe/metroliza/issues/911),
  [PR #959](https://github.com/hexafe/metroliza/pull/959), and
  [`branch_audit.md`](branch_audit.md)

This is the approval artifact for later branch cleanup. It converts the evidence in the branch
audit into an ordered decision matrix, deletion gate, and rollback procedure. It does not perform
or authorize a branch deletion, tag creation, merge, force-update, or history rewrite. Each future
mutation requires a separate human approval recorded in #960 after the prerequisites below have
been reverified against live refs.

## Target branch model

The target day-to-day development model is:

```text
develop
├── feature/*
├── fix/*
├── refactor/*
└── research/*
```

- `develop` is the protected canonical integration base and the target for normal pull requests.
- `feature/*`, `fix/*`, and `refactor/*` are short-lived Issue branches. They merge through reviewed
  pull requests and become deletion candidates only after integration.
- `research/*` contains bounded experiments with explicit exit criteria. Production behavior is
  recovered through a new `feature/*`, `fix/*`, or `refactor/*` branch rather than by merging a
  research branch wholesale.
- `master` remains outside the development tree as the protected historical/production anchor
  until the release strategy is approved.
- `release/2026.06-rc2` and `rc2` are temporary transition exceptions. They receive no routine
  development work and do not become permanent parents in the target model.

The target model does not itself change GitHub's default branch, protection rules, release policy,
or any ref. Those are separately reviewed repository operations.

## Branch decision matrix

Counts and SHAs below come from the 2026-08-22 audit snapshot. Before executing any row, refresh
the live head, ancestry, unique-commit count, open pull requests, workflow references, and release
dependencies. A decision describes the intended outcome; it is not approval to perform it.

| Branch | Current role | Decision | Prerequisites | Risk | Rollback |
| --- | --- | --- | --- | --- | --- |
| `develop` | Canonical development baseline at audited tip `a03bbdacbd6c`; 0 unique commits relative to itself. | **KEEP** as the protected root of the target model. | Accept the branch-role policy in #900/PR #910; verify required checks and protections; separately review any default-branch setting change. | GitHub still presents stale `master` as default, so new work can start from the wrong base. An unreviewed release-only update could also diverge the release line. | The branch itself is not removed. If repository settings change incorrectly, restore the recorded prior default/protection settings and repair affected PR bases; never reset or force-push `develop`. |
| `master` | GitHub default and historical/production anchor at `ab26258e72d2`; 279 behind / 0 ahead of `develop`, 0 unique commits, but 904 files of tip-tree drift. | **KEEP** until a separate release strategy and promotion decision. | Complete #901 release evidence and #920 release-policy work before any promotion; require a dedicated reviewed release PR. | Treating “0 unique commits” as permission to replace `master` would bypass a product-wide diff and unresolved manual release gates. | No cleanup mutation is planned. If a later promotion is faulty, use a reviewed revert or forward hotfix and reconcile it to `develop`; do not rewrite production history. |
| `rc2` | Temporary transition/reference alias at `a03bbdacbd6c`, exactly equal to audited `develop` and `release/2026.06-rc2`; 0 unique commits. Open PRs #910 and #958 currently target it. | **KEEP TEMPORARILY**; reconsider retirement only after the transition is complete. | Resolve #910 and #958; freeze routine work; reconcile release state; pass the deletion gate; under #924 verify whether a historical tag is required. | Early deletion breaks active PR bases and historical references. Continued use creates competing integration branches. | If a later approved deletion is wrong, recreate only `refs/heads/rc2` from the full SHA recorded immediately before deletion, then repair affected PR bases. |
| `release/2026.06-rc2` | Frozen release-candidate/evidence line at audited tip `a03bbdacbd6c`; 0 unique commits at the snapshot. | **KEEP** through release closeout. | Restrict changes to release blockers/evidence; complete #901; reconcile every accepted release-only commit back to `develop`; verify exact-head CI. | Feature drift invalidates release evidence; failure to reconcile a release fix can lose it from future development. | Revert a faulty release change through review or recreate the branch from its recorded SHA if it is accidentally removed. Never force-move the branch or a published tag. |
| `docs/900-branch-transition` | Active documentation/governance branch for #900 and open PR #910; audited 0 behind / 1 ahead with 1 unique commit. | **MERGE** through PR #910, then evaluate the source branch for deletion separately. | Diagnose the observed unit-test failure; obtain green exact-head CI; review overlap with #958; record source and merge SHAs; obtain maintainer approval. | Merging red CI contradicts the policy being introduced. Wrong ordering can block the planned fast-forward of `develop` and restore stale roadmap language. | Revert a faulty documentation merge through a new PR. If the source branch is later deleted incorrectly, recreate it from the recorded full source SHA. |
| `docs/project-governance-reset` | Obsolete source branch for squash-merged PR #909. It has 1 graph-unique source commit at `375cc433f0af`, but its tip tree is identical to `develop`, so no unique content remains. | **DELETE** only after the deletion gate passes. | Reconfirm zero tip-tree drift; verify no open PR, workflow, protection rule, release process, or documentation depends on the name; record full recovery SHA; obtain explicit deletion approval. | Its source commit will cease to be reachable from a normal branch head, and an unsearched external dependency may still name it. | Recreate exactly `refs/heads/docs/project-governance-reset` from recorded SHA `375cc433f0af4d2d0a49e5dacc33ec0b53733479`, after approval. |
| `docs/project-specification-roadmap-2026-08` | Active product-planning branch in open PR #958; audited 0 behind / 4 ahead with 4 unique documentation commits. | **MERGE** after branch-policy reconciliation, then evaluate the source branch for deletion separately. | Integrate #910 first; reconcile overlapping `docs/project/README.md` and `roadmap.md`; retarget to `develop` when permitted; fix the observed unit-test failure; obtain review and green exact-head CI. | Merging out of order can reintroduce `rc2` as the normal product line or overwrite accepted branch policy. | Revert a faulty documentation merge through a new PR. Recreate the source branch from its recorded full SHA if an approved post-merge deletion proves premature. |
| `performance-boost` | Historical broad performance/native line at recovered tip `75f79b5a1c92`; no live remote head and 0 unique commits relative to `develop`. It was merged and reverted on `master` and later integrated into the development line. | **SALVAGE** evidence and requirements only; keep the old branch absent. | Route still-valid work through #918/#908; establish a current benchmark; define parity, test, and rollback gates; create a focused branch from `develop`. | Replaying the old 107-file delta can duplicate integrated changes and revive regressions that motivated the production revert. | Close or revert the focused salvage PR. The historical branch remains absent and no historical ref needs restoration. |
| `report-metadata-redesign` | Historical metadata/provenance work recovered from closed draft PR #892 at `efe1c430c30e`; no live exact-name head and 0 unique commits relative to `develop`. | **SALVAGE** unmet schema intent only; keep historical names absent. | Map requirements to current code and #917, with #915/#929/#930 for adjacent model, OCR, and database work; prove compatibility and migration rollback in a focused branch from `develop`. | The historical 241-file delta mixes schema, OCR, persistence, UI, and tests and can duplicate landed behavior or regress the canonical result model. | Revert or close the focused salvage PR and restore data only through its reviewed migration rollback. No historical branch restoration is required. |
| `feature/realtime-industrial-ml-anomaly` | Historical realtime/ML line recovered from closed PR #898 at `13c47617ef85`; no live remote head and 0 unique commits relative to `develop`. | **SALVAGE** validated contracts, fixtures, and operator safeguards only; keep the old branch absent. | Route gaps through #919/#941; define replay, bounded-read, detector, performance, UI, and rollback acceptance criteria; use a focused branch from `develop`. | The historical 776-file delta contains line integration and unrelated changes; wholesale revival obscures provenance and invalidates current evidence. | Close or revert the focused salvage PR and disable the new behavior through its reviewed rollback path. The historical branch remains unchanged and absent. |

## Exact execution order

Do not skip or parallelize steps that have an explicit dependency. Stop when a prerequisite fails
or the live ref differs from its recorded audit state.

1. **Approve the evidence base.** Review #911, PR #959, and `branch_audit.md`; record the accepted
   inventory SHAs in #960. Keep PR #959 audit-only.
2. **Accept the branch-role policy first.** Repair PR #910's test failure, obtain green exact-head
   checks, review its overlap with #958, and merge #910 only after approval.
3. **Reconcile the transition refs.** Confirm the accepted #910 result is a fast-forward for both
   `develop` and `release/2026.06-rc2`. Update either ref only with separate human approval, then
   verify the `develop`, `rc2`, and release-candidate trees expected by #900.
4. **Integrate the audit.** Update `docs/911-branch-archaeology-audit` from the accepted `develop`
   state without rewriting history, refresh stale measurements, obtain green checks, and merge
   PR #959 only after review.
5. **Integrate this plan.** Retarget the #960 plan PR from the audit branch to `develop` after #959
   lands, verify that its diff contains only this artifact and its index entry, obtain approval,
   and merge it. This step authorizes no cleanup by itself.
6. **Freeze branch roles.** Protect `develop`; keep `master`, `rc2`, and
   `release/2026.06-rc2` in the roles stated in the matrix; stop routine work from targeting
   `master` or `rc2`.
7. **Integrate product-planning documentation.** Reconcile
   `docs/project-specification-roadmap-2026-08` with accepted #910 language, fix its CI, retarget it
   to `develop`, and merge through #958 only after approval.
8. **Evaluate the already-integrated source branch.** Run the deletion gate for
   `docs/project-governance-reset`. If every item passes and deletion is explicitly approved, it is
   eligible for a later one-branch deletion operation.
9. **Evaluate merged source branches individually.** After their PRs land, run the same deletion
   gate separately for `docs/900-branch-transition`, `docs/911-branch-archaeology-audit`, the #960
   plan branch, and `docs/project-specification-roadmap-2026-08`. Never batch the approval.
10. **Salvage historical themes.** Use new focused branches from `develop` for approved work from
    performance (#918/#908), report metadata (#917), and realtime industrial (#919/#941). Do not
    recreate or wholesale-merge the historical branch names.
11. **Close the release transition separately.** Complete #901, reconcile every release fix, and
    make any production promotion through a dedicated reviewed PR. Under #924, verify the final RC
    tag requirement and all dependencies before even proposing retirement of `rc2`.
12. **Run a final audit.** Confirm that remaining long-lived refs have one documented role and all
    other heads are active, short-lived branches rooted in the target model. Attach the final
    inventory and every approval/recovery SHA to #960.

## Deletion gate

A branch may be proposed for deletion only when **all** boxes are checked against current remote
state. A failed or unknown item means **KEEP** until the uncertainty is resolved.

- [ ] **No open PR:** no open pull request uses the branch as either head or base, and no stacked PR
  still needs its commits.
- [ ] **No workflow dependency:** no workflow, ruleset, deployment, submodule, script, status check,
  scheduled job, external integration, or repository setting names the branch.
- [ ] **No unique commits:** graph and tree checks prove that every valuable commit/content change
  is reachable from an intentional retained ref. Squash merges require tree/patch verification;
  ancestry alone is insufficient.
- [ ] **No release dependency:** no active release, packaging job, evidence record, changelog,
  download, support procedure, or rollback runbook depends on the branch name or tip.
- [ ] **Historical tag exists if required:** for a meaningful release boundary, an approved
  immutable annotated tag already resolves to the verified historical SHA before branch deletion.
  Tag creation is a separate human-approved action and is not performed by this plan.

The execution record must also contain the branch's full pre-deletion SHA, evidence links for all
five checks, approver, timestamp, and rollback owner. Approval applies to one exact branch at one
exact SHA. If the ref moves after review, the gate resets.

## Rollback strategy

### Recovery ledger

Before any future mutation, record in #960:

- exact branch name and full source/target SHAs;
- decision-matrix row and deletion-gate evidence;
- approving maintainer and rollback owner;
- expected result and verification commands;
- timestamp and links to the governing PR, Issue, CI run, and release evidence.

### Branch deleted incorrectly

After separate approval, recreate only the exact deleted ref from the ledger's full SHA:

```bash
git push origin <RECORDED_FULL_SHA>:refs/heads/<EXACT_BRANCH_NAME>
```

Then restore affected PR bases, workflows, or release references and rerun their checks. Never infer
the recovery SHA from a similar message and never use force-push.

### Documentation or policy merge fails

Revert the accepted merge or squash commit through a new reviewed PR. Reopen the governing Issue,
restore the previously recorded policy text if needed, and rerun the exact-head documentation and
CI checks. Do not reset a protected branch.

### Release change fails

Use a reviewed revert or forward hotfix on `master` or the active release branch, then reconcile the
correction into `develop`. A published tag is never silently moved. A wrong tag requires release
freeze, an incident record, and a separately approved correction strategy.

### Salvaged work fails

Close or revert the focused salvage PR and apply its documented feature, schema, or data rollback.
Because salvage starts from `develop` and does not resurrect historical refs, the archived branch
state remains untouched.

## Completion criteria

Branch cleanup is complete only when:

- the target development model is documented and reflected in open PR bases;
- every remaining long-lived branch has one intentional, protected role;
- every removed branch passed the gate and has a recovery ledger entry;
- no valuable commit or release boundary is reachable only from a deleted branch;
- historical themes survive through current Issues and focused work rather than revived branches;
- the final inventory and all human approvals are attached to #960.
