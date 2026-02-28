# Release Playbook (Beginner)

This playbook explains the **full beginner-friendly release-candidate flow** from feature freeze to final release merge.

Use this together with:

- [`release_candidate_checklist.md`](./release_candidate_checklist.md)
- [`release_branching_playbook.md`](./release_branching_playbook.md)

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
git pull origin main
git checkout -b release/1.8.0-rc1
git push -u origin release/1.8.0-rc1
```

### B. Fix RC issues on RC branch

```bash
git checkout release/1.8.0-rc1
git pull origin release/1.8.0-rc1
# ... edit files ...
git add -A
git commit -m "fix(rc): resolve blocker in export flow"
git push origin release/1.8.0-rc1
```

### C. Cut `rc2` (when needed)

```bash
git checkout release/1.8.0-rc1
git pull origin release/1.8.0-rc1
git checkout -b release/1.8.0-rc2
git push -u origin release/1.8.0-rc2
```

### D. Tag final release commit

```bash
git checkout release/1.8.0-rc2
git pull origin release/1.8.0-rc2
git tag -a v1.8.0 -m "Release v1.8.0"
git push origin v1.8.0
```

### E. Merge release branch back to `main` (back-merge)

```bash
git checkout main
git pull origin main
git merge --no-ff release/1.8.0-rc2 -m "merge: finalize v1.8.0 from rc2"
git push origin main
```

---

## 3) Common mistakes to avoid

1. **Merging new features into RC branch**
   - RC branches are for stabilization only.
   - New features increase risk and can invalidate QA sign-off.

2. **Forgetting the back-merge to `main`**
   - If RC-only fixes are not merged back, `main` can miss production fixes.
   - This creates divergence and surprises in the next release cycle.

3. **Tagging the wrong commit**
   - Tag only the commit that QA + Engineering + Product approved.
   - Avoid tagging a local unpushed or unreviewed commit.

4. **Re-testing gaps after late fixes**
   - Even small RC fixes need targeted retest.
   - Risk-based regression scope should be explicitly recorded.

---

## 4) Decision tree: cut `rc2` vs postpone release

Use this quick decision flow when RC testing finds issues:

1. **Is there any release-blocker bug open?**
   - **No** → continue final checks and prepare release.
   - **Yes** → go to step 2.

2. **Can all blockers be fixed, reviewed, and re-tested within the release window without elevated risk?**
   - **Yes** → apply fixes on current RC; go to step 3.
   - **No** → go to step 4.

3. **Did fixes significantly change core paths or require broad regression reset?**
   - **Yes** → cut `rc2`, run full/expanded regression, then reassess.
   - **No** → keep current RC branch, run targeted + required regression, then reassess.

4. **If timeline/risk remains unacceptable after estimation**
   - Postpone release.
   - Re-baseline scope/date with Product/Release Manager.
   - Communicate revised plan and expected next RC cut.

Rule of thumb:

- **Cut `rc2`** when confidence needs a clean new candidate due to meaningful late changes.
- **Postpone release** when confidence cannot be restored inside the planned window.

---

## 5) Approval ownership by step

| Step | Engineering | QA | Product / Release Manager |
|---|---|---|---|
| Feature freeze scope confirmation | **Approve** (Eng Lead) | Consult | **Approve** |
| RC branch cut (`release/<version>-rc1`) | **Approve/Execute** | Inform | **Approve** |
| RC bug-fix merges | **Approve/Execute** | Consult | Inform |
| RC test pass and sign-off | Consult | **Approve** | Inform |
| Go / No-Go meeting | **Approve readiness** | **Approve test status** | **Final decision / Approve** |
| Final tag creation (`vX.Y.Z`) | **Approve/Execute** | Confirm tested commit | **Approve** |
| Back-merge RC to `main` | **Approve/Execute** | Inform | Confirm release complete |

Suggested minimum gate before tagging:

- Engineering: no unresolved release blockers.
- QA: required checklist/regression complete and signed off.
- Product/Release Manager: release objectives met and communication ready.
