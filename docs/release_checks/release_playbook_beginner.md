# Release Playbook (Beginner)

This playbook explains the **full beginner-friendly release-candidate flow** from feature freeze to final release merge.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

Use this together with:

- [`release_candidate_checklist.md`](./release_candidate_checklist.md)
- [`release_branching_playbook.md`](./release_branching_playbook.md)
- [`open_testing_runbook.md`](./open_testing_runbook.md)
- [`branching_strategy.md`](./branching_strategy.md)

---

## 1) End-to-end example: feature freeze → final merge

Example target release: `v2026.05`.

1. **Feature freeze declared**
   - Product/Release Manager announces freeze date/time.
   - Engineering freezes the approved release scope on `develop`; later routine development stays
     out of the release branch.
   - Engineering Lead confirms the release scope (what is in, what is out).

2. **Cut RC branch from `develop`**
   - Branch name: `release/2026.05-rc1`.
   - This branch now holds only stabilization work (bug fixes, release blockers, docs/tests updates tied to release readiness).

3. **Open testing readiness (before broad RC testing)**
   - Complete the checklist's
     [scope, ownership, and freeze](./release_candidate_checklist.md#1-scope-ownership-and-freeze)
     gate: name owners, freeze scope, classify every open defect, and record the branch, exact
     commit, build identity, and artifact IDs in a dated evidence file.
   - Run the exact-build
     [clean Python 3.11 local gate](./release_candidate_checklist.md#2-clean-python-311-local-gate)
     and
     [automatic GitHub CI gate](./release_candidate_checklist.md#3-automatic-github-ci-gate)
     before distributing the candidate broadly.

4. **Stabilize and test RC1**
   - QA executes open testing and the checklist's
     [packaging](./release_candidate_checklist.md#4-packaging-and-clean-machine-gate),
     [Google conversion](./release_candidate_checklist.md#5-google-conversion-gate),
     [product/data-integrity](./release_candidate_checklist.md#6-product-and-data-integrity-smoke),
     and [security](./release_candidate_checklist.md#7-security-and-privacy-gate) gates.
   - Bugs found during RC testing are fixed on short-lived branches that target the RC branch.
   - Every accepted RC fix is reconciled into `develop` through review.
   - Product/Release Manager tracks blocker status and go/no-go criteria.

5. **If issues are found, continue on RC1 or cut RC2**
   - Minor/isolated fixes: keep patching `release/2026.05-rc1`.
   - Significant churn or reset of test confidence: cut `release/2026.05-rc2` from the current stabilized RC tip and retest.

6. **Promotion decision and rollback readiness**
   - Complete the checklist's
     [promotion decision and rollback](./release_candidate_checklist.md#8-promotion-decision-and-rollback)
     gate: resolve all release blockers, record required sign-offs, verify the previous stable
     artifact, and name the rollback owner and procedure.

   - QA signs off that required tests/checklists passed.
   - Engineering confirms no open release blockers.
   - Product/Release Manager gives final release approval.

7. **Merge the approved release branch into `master`**
   - Merge the final RC branch only after the promotion decision and evidence review.
   - Verify release notes/changelog updates are present.

8. **Tag the reviewed production commit and reconcile it**
   - Create annotated tag `v2026.05` at the exact reviewed `master` merge commit.
   - Reconcile the production result into `develop` through a reviewed PR.

9. **Post-release communication**
   - Product/Release Manager announces release completion.
   - Engineering monitors hotfix channels.

---

## 2) Exact Git command snippets

> Replace `2026.05` and branch/tag names with your target release month.

### A. Create RC branch

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b release/2026.05-rc1
git push -u origin release/2026.05-rc1
```

### B. Fix RC issues on RC branch

```bash
git checkout release/2026.05-rc1
git pull --ff-only origin release/2026.05-rc1
git checkout -b fix/<issue>-release-blocker
# ... edit files ...
git add -A
git commit -m "fix(rc): resolve blocker in export flow"
git push -u origin fix/<issue>-release-blocker
```

Open a reviewed PR from the fix branch to `release/2026.05-rc1`. After acceptance, reconcile the
fix into `develop` through a separate reviewed PR.

### C. Cut `rc2` (when needed)

```bash
git checkout release/2026.05-rc1
git pull --ff-only origin release/2026.05-rc1
git checkout -b release/2026.05-rc2
git push -u origin release/2026.05-rc2
```

### D. Merge the approved release branch into `master`

```bash
git checkout master
git pull --ff-only origin master
git merge --no-ff release/2026.05-rc2 -m "merge: finalize v2026.05 from rc2"
git push origin master
```

### E. Tag the reviewed production commit

```bash
git checkout master
git tag -a v2026.05 -m "Release v2026.05"
git push origin v2026.05
```

Then reconcile the tagged production result into `develop` through a reviewed PR.

---

## 3) Keep this doc tutorial-only

For policy and gate details, use:

- Branch roles/naming/merge/tag policy: [`branching_strategy.md`](./branching_strategy.md)
- RC gates, required checks, and sign-off criteria: [`release_candidate_checklist.md`](./release_candidate_checklist.md)

This beginner playbook intentionally focuses on sequence and command flow.
