# Release Playbook (Beginner)

This playbook explains the **full beginner-friendly release-candidate flow** from feature freeze to final release merge.

Authoritative source for branch naming rules: `docs/release_checks/branching_strategy.md`.

Use this together with:

- [`release_candidate_checklist.md`](./release_candidate_checklist.md)
- [`release_branching_playbook.md`](./release_branching_playbook.md)
- [`branching_strategy.md`](./branching_strategy.md)

---

## 1) End-to-end example: feature freeze → final merge

Example target release: `v1.8.0`.

1. **Feature freeze declared**
   - Product/Release Manager announces freeze date/time.
   - Engineering stops merging new features into `main` for this release scope.
   - Engineering Lead confirms the release scope (what is in, what is out).

2. **Cut RC branch from `main`**
   - Branch name: `release/1.8.0-rc1`.
   - This branch now holds only stabilization work (bug fixes, release blockers, docs/tests updates tied to release readiness).

3. **Stabilize and test RC1**
   - QA executes release checklist, regression, and smoke testing.
   - Bugs found during RC testing are fixed **on the RC branch** first.
   - Product/Release Manager tracks blocker status and go/no-go criteria.

4. **If issues are found, continue on RC1 or cut RC2**
   - Minor/isolated fixes: keep patching `release/1.8.0-rc1`.
   - Significant churn or reset of test confidence: cut `release/1.8.0-rc2` from the current stabilized RC tip and retest.

5. **Go decision**
   - QA signs off that required tests/checklists passed.
   - Engineering confirms no open release blockers.
   - Product/Release Manager gives final release approval.

6. **Tag the approved RC commit as final version**
   - Create annotated tag `v1.8.0` at the exact approved commit.

7. **Merge release branch back to `main`**
   - Merge the final RC branch to keep `main` aligned with release-hotfix commits.
   - Verify release notes/changelog updates are present.

8. **Post-release communication**
   - Product/Release Manager announces release completion.
   - Engineering monitors hotfix channels.

---

## 2) Exact Git command snippets

> Replace `1.8.0` and branch/tag names with your target version.

### A. Create RC branch

```bash
git checkout main
git pull --ff-only origin main
git checkout -b release/1.8.0-rc1
git push -u origin release/1.8.0-rc1
```

### B. Fix RC issues on RC branch

```bash
git checkout release/1.8.0-rc1
git pull --ff-only origin release/1.8.0-rc1
# ... edit files ...
git add -A
git commit -m "fix(rc): resolve blocker in export flow"
git push origin release/1.8.0-rc1
```

### C. Cut `rc2` (when needed)

```bash
git checkout release/1.8.0-rc1
git pull --ff-only origin release/1.8.0-rc1
git checkout -b release/1.8.0-rc2
git push -u origin release/1.8.0-rc2
```

### D. Tag final release commit

```bash
git checkout release/1.8.0-rc2
git pull --ff-only origin release/1.8.0-rc2
git tag -a v1.8.0 -m "Release v1.8.0"
git push origin v1.8.0
```

### E. Merge release branch back to `main` (back-merge)

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff release/1.8.0-rc2 -m "merge: finalize v1.8.0 from rc2"
git push origin main
```

---

## 3) Keep this doc tutorial-only

For policy and gate details, use:

- Branch roles/naming/merge/tag policy: [`branching_strategy.md`](./branching_strategy.md)
- RC gates, required checks, and sign-off criteria: [`release_candidate_checklist.md`](./release_candidate_checklist.md)

This beginner playbook intentionally focuses on sequence and command flow.
