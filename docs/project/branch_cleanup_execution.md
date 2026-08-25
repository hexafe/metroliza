# Branch cleanup closeout and final-state contract

- Status: Gates 1–4 completed and verified; documentation closeout before Gate 5
- Owner: Repository maintainer
- Last reviewed: 2026-08-25
- Repository: `hexafe/metroliza`
- Observed-state timestamp: `2026-08-25T06:53:22+02:00` (`Europe/Warsaw`)
- Current integration baseline: `develop` at
  `112151f6983c7131c6d2861cb5437a706a3356c4`
- Observed ordinary branch count: 5
- Authoritative exact-ref execution ledger: [#960](https://github.com/hexafe/metroliza/issues/960)
- Historical source audit: closed [#911](https://github.com/hexafe/metroliza/issues/911), merged
  [PR #959](https://github.com/hexafe/metroliza/pull/959), and
  [`branch_audit.md`](branch_audit.md)
- Integrated cleanup plan: merged [PR #961](https://github.com/hexafe/metroliza/pull/961)

This is the durable closeout record for the branch cleanup plan. PR #961 is merged, and Gates 1–4
are complete. The sole remaining cleanup candidate is the source branch carrying this closeout.

This document does not approve or perform Gate 5. A candidate disposition is never permission to
delete a ref. Every destructive operation requires a fresh live gate, one exact ref and SHA, a
verified durable recovery ref, explicit Product Owner authorization, an expected-old-SHA guard,
one-time execution, and immediate verification recorded in #960.

## Completed integrations and cleanup gates

The integrated control plane is:

- PR #910 — branch/release policy, squash
  `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac`;
- PR #958 — product specification, feature catalog, roadmap, and dependency model, squash
  `1b58303fee1483a88d2c987f7f06595dac8db7f3`;
- PR #959 — branch archaeology audit, squash
  `1a060bfcc8c6e01901be7884d3a805f544eb918c`;
- PR #961 — branch cleanup execution plan, squash/current `develop`
  `112151f6983c7131c6d2861cb5437a706a3356c4`;
- #911 — closed completed.

Each completed gate was separately evidenced, independently checked, approved for one exact ref,
executed with an expected-old-SHA lease, and verified against the complete remote state.

| Gate | Deleted exact ref | Authorized old SHA | Integrated through | Retained recovery ref | Result ledger |
|---:|---|---|---|---|---|
| 1 | `refs/heads/docs/900-branch-transition` | `b978a759f341d2c0c44f61bc4d0416aec868fb0e` | PR #910 / `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac` | `refs/pull/910/head` at the source SHA | #960 comment `5397731377`; `DELETED AND VERIFIED` |
| 2 | `refs/heads/docs/project-governance-reset` | `375cc433f0af4d2d0a49e5dacc33ec0b53733479` | PR #909 / `a03bbdacbd6c308acf46ca31c16d0dd2caeab304` | `refs/pull/909/head` at the source SHA | #960 comment `5399428127`; `DELETED AND VERIFIED` |
| 3 | `refs/heads/docs/project-specification-roadmap-2026-08` | `b8b698c020f616a3c53bcc5286291206ae1026f3` | PR #958 / `1b58303fee1483a88d2c987f7f06595dac8db7f3` | `refs/pull/958/head` at the source SHA | #960 comment `5401133929`; `DELETED AND VERIFIED` |
| 4 | `refs/heads/docs/911-branch-archaeology-audit` | `ee026f6a5af96792c7b3c2a76d5ced4cb57c6ff3` | PR #959 / `1a060bfcc8c6e01901be7884d3a805f544eb918c` | `refs/pull/959/head` at the source SHA | #960 comment `5405315752`; `DELETED AND VERIFIED` |

The four ordinary source refs are absent. The four recovery refs above remained fetchable at their
recorded SHAs when this closeout state was observed. Historical document references to a deleted
branch are audit/recovery evidence, not a requirement to recreate or retain the ordinary ref.

## Observed five-branch pre-Gate-5 state

The complete authenticated remote advertisement exposed exactly these five ordinary branches:

| Observed branch | Exact observed SHA | Decision and role |
|---|---|---|
| `develop` | `112151f6983c7131c6d2861cb5437a706a3356c4` | **KEEP** — canonical Issue-driven integration branch. |
| `docs/960-branch-cleanup-execution` | `6bd6e543288156ae676fc5205a15f18ec2dce593` | Sole remaining short-lived cleanup candidate. This source head is pre-closeout evidence only. |
| `master` | `ab26258e72d285c3917a595515798da185800373` | **KEEP** — repository default and production/history anchor; no promotion through #960. |
| `rc2` | `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac` | **KEEP TEMPORARILY** — transition/reference alias; retirement remains governed by #924 and release reconciliation. |
| `release/2026.06-rc2` | `1eeeab27352ed2c6bcbdca2af81f3fdd7c1f8cac` | **KEEP** — frozen candidate/evidence line while #901 remains open. |

`6bd6e543288156ae676fc5205a15f18ec2dce593` was the branch head before this documentation
closeout. It must not be reused as Gate 5 evidence after the branch moves. The final post-closeout
head must receive a completely fresh Gate 5.

## Final intended four-branch model

After the closeout PR merges and the source branch later passes its separate Gate 5, the intended
ordinary branch inventory is exactly:

| Final branch | Durable role |
|---|---|
| `develop` | Canonical Issue-driven integration branch and target for normal reviewed work. |
| `master` | Repository default and production/history anchor. #960 performs no promotion. |
| `release/2026.06-rc2` | Frozen candidate/evidence line while #901 remains open. |
| `rc2` | Temporary transition/reference alias; retirement remains separately governed by #924 and release reconciliation. |

Normal short-lived Issue branches continue to use the canonical `feature/*`, `fix/*`,
`refactor/*`, `docs/*`, `test/*`, `security/*`, and `chore/*` namespaces from
[`branching_strategy.md`](../release_checks/branching_strategy.md) and
[`development_workflow.md`](development_workflow.md). This closeout changes no GitHub default,
protection, ruleset, release policy, tag, or long-lived ref.

The four-branch target is intentionally recorded before Gate 5. Once Gate 5 is completed, no new
repository edit is required merely to state that the source branch was deleted. #960 remains the
source of the actual final execution timestamp, exact deleted SHA, recovery-ref verification,
command result, and complete final inventory.

## Closeout PR and Gate 5 sequencing

The required sequence is:

1. Reuse `docs/960-branch-cleanup-execution`; do not create a competing branch.
2. Merge current `develop` into it normally, preserving published history; do not rebase or force.
3. Update exactly `docs/README.md`, `docs/project/branch_audit.md`, and
   `docs/project/branch_cleanup_execution.md`; validate the exact three-file net diff, and open one
   focused PR to `develop` with `Refs #960` rather than closing the Issue.
4. Run focused validation, exact-head GitHub CI, and review before merging that closeout PR.
5. Only after the closeout PR merges may Gate 5 begin against the branch's new exact final head.
6. Verify the new PR's `refs/pull/<number>/head` at that exact final head and use it as the required
   recovery ref. The older PR #961 ref and pre-closeout SHA are historical evidence, not substitutes.
7. Recheck every dependency and recovery condition, then obtain new exact-ref Product Owner
   authorization. Any branch movement invalidates all earlier Gate 5 evidence and authorization.
8. Execute at most one expected-old-SHA-guarded deletion, verify the complete remote state, and
   record the final result in #960.

This closeout PR starts no Gate 5 evidence collection, requests no destructive authorization, and
authorizes no deletion, tag operation, release operation, deployment, recovery, or other ref
mutation.

## Historical archaeology dispositions preserved

Cleanup does not erase or reinterpret the evidence recovered by #911:

- **RC1 recovery evidence:** no exact bare `rc1` tip is proven. Under #924, any historical-state or
  tag decision must use concrete evidence such as `release/2026.03-rc1` at
  `260a70d00eec296e101b736776129778d86aa042` and the later fixes head
  `c593953f3f862289be84252d120a1c79c6f468ad`; this closeout creates or moves no tag.
- **Performance boost:** salvage benchmark evidence, parity intent, fixtures, and focused
  requirements through #918/#908 from recovered tip
  `75f79b5a1c9211019c8b5d75ea61a904aad5fc55`; do not recreate or wholesale-merge the branch.
- **Report metadata redesign:** salvage contract, identity, schema, and migration intent through
  #917 from recovered tip `efe1c430c30ecb98ecb1246113e4869192f9c3bf`; do not wholesale-merge it.
- **Realtime/industrial/ML:** salvage stream/replay contracts, deterministic fixtures, read-only
  source safety, detector transparency, and operator safeguards through #919/#941 from recovered
  tip `13c47617ef85dc1a92d2088a8e1bd873cee4fe76`; do not wholesale-merge it.

All recovered tips are ancestors of `develop`; they are evidence, not missing live branches.

## Product, architecture, release, and data boundaries

The cleanup changes branch reachability only. It does not change application behavior, product
scope, roadmap dependencies, or these accepted contracts:

- `develop` remains canonical for Issue-driven integration;
- `src/metroliza` remains the canonical implementation package;
- `modules` remains compatibility-only and is not a second implementation architecture;
- local-first behavior and confidential measurement-data handling remain mandatory;
- SQLite writes and publication remain atomic;
- deterministic Python fallbacks remain available when optional/native acceleration is absent;
- dashboards retain offline behavior;
- packaged Windows compatibility remains required and is not proven by documentation-only tests;
- #901 remains the release-promotion evidence gate, published tags are immutable, and accepted
  release fixes must reconcile into `develop`;
- `rc2` retirement and any RC-history tag decision remain outside #960 under #924/release
  reconciliation.

## Fresh exact-ref deletion gate

A branch remains **KEEP** unless every item is freshly proven for its exact current SHA:

- [ ] no open PR uses it as head or base, and no stacked review depends on its history;
- [ ] no workflow, ruleset, release, setting, document, scheduled job, deployment, submodule,
  script, package job, support process, known integration, or handoff requires the live name;
- [ ] graph plus direct tree/patch comparison proves no unreviewed unique work remains;
- [ ] no release, support, rollback, or product-control evidence requires the branch;
- [ ] the exact commit is durably fetchable from the verified retained PR ref or another separately
  approved and restore-tested recovery object;
- [ ] #960 records the exact ref, SHA, evidence, approver, approval timestamp, rollback owner,
  expected result, and guarded command;
- [ ] the deletion uses
  `--force-with-lease=refs/heads/<branch>:<approved-full-sha>` and no name-only fallback;
- [ ] the Product Owner authorization names that one exact ref and SHA.

Any candidate or recovery-ref movement invalidates the gate. A tag is never created, moved, or
deleted as an implicit part of branch cleanup.

## Recovery and rollback boundaries

The SHA is an identifier, not an archive. Before any deletion, a clean-clone test must prove that
the exact commit and tree can be fetched through the recorded retained ref. A GitHub page or
remembered SHA is insufficient without a fetchable backing ref.

Recovery is a separate incident operation requiring its own authorization. It must:

1. recheck ownership and every dependency surface;
2. fetch the retained recovery ref and require the recorded exact commit/tree;
3. require the target ordinary branch to remain absent;
4. recreate it with GitHub's atomic create-ref API, which rejects any existing target, including a
   concurrent same-SHA recreation;
5. abort on any mismatch or rejection rather than overwrite, fast-forward, force, or guess;
6. immediately verify the recovered branch and complete remote inventory.

If recovery ever relies on a bundle or off-repository object, the separately approved procedure
must first transfer it through a unique expected-absent non-branch ref under
`refs/notes/metroliza-recovery-staging/`, audit workflow/integration behavior, and remove that
staging ref with a lease bound to its recorded SHA. There is no branch/tag fallback. A cleanup
failure retains and records the staging ref for separate review rather than forcing it.

Documentation/policy integration failures use a new reviewed revert PR, never a reset of a
protected branch. Release-state failures use a reviewed revert or forward hotfix on the affected
retained branch and reconcile the result into `develop`. Published tags are never silently moved
or recreated. Focused salvage failures revert only the focused salvage PR; historical branch names
are not rollback mechanisms.

## Closeout acceptance

This documentation closeout is ready only when:

- the existing source branch was normally merged with exact
  `develop@112151f6983c7131c6d2861cb5437a706a3356c4` without rebase or force;
- the net PR diff contains exactly `docs/README.md`, `docs/project/branch_audit.md`, and
  `docs/project/branch_cleanup_execution.md`;
- the observed five-branch state, four completed gates, four recovery refs, and final four-branch
  target are validated against the live remote;
- focused documentation/policy/catalog tests, release hygiene, and `git diff --check` pass;
- GitHub CI and Codex Review are terminal for the exact final PR head;
- the PR metadata states that Gate 5 was not begun and no destructive ref mutation occurred.

Gate 5 is complete only after the closeout PR merges and a new exact-head gate, new PR recovery-ref
verification, separate authorization, one guarded deletion, and complete post-delete verification
are recorded in #960. This document intentionally already describes that final target and never
supplies destructive authorization.
