Historical initial admission report, before ordered integration. Current execution and later changed-head gates are recorded in [#1153](https://github.com/hexafe/metroliza/issues/1153). Original report SHA256: `e5fed7a08337db5543407cc479088a27e56e1f8f5ec7085040675e3de40ebe1a`. Source findings and limitations below are retained.

# Independent review: EXECUTE-REPO-CLEANUP-20261027, FULL1 admission

**Verdict for the cleanup package: ACCEPT with findings.** I found no P0 or P1 issues.

**Verdict for #1109: READY_FOR_MERGE**, provided the pre-merge readback below passes. This covers the integration result only. It reuses the existing leaf reviews and is not a new product audit. If any readback item fails or can't be read, the verdict becomes INCOMPLETE.

## Model evidence and limitations

- **Requested:** the `independent_reviewer` role, which resolves to `claude-opus-5-5` at high effort (model map version 1.0).
- **Configured, as visible to me:** model ID `claude-opus-5-5`. Effort is `not visible`.
- **Observed in the response:** `not visible`.
- **Only the Read tool was available.** I could not compute SHA256s or run git. The hashes `a4526f5b…f6` (step1.md, 28783 bytes) and `7989a14f…09` (manifest, 319339 bytes) are taken as given. `package-seal.json` binds the same values, but to paths under `repo-cleanup-step1/docs/engineering/`. That the `candidate/` copies are byte-identical to those is your claim, not something I checked.
- **Not read in full:** the manifest (I read about 1,800 of its lines: the counts, all readiness entries, the #1149 dispositions, 3 of the 47 branch entries), `resolved1063-index.diff` (lines 1–810 of 2000; I did not see the `development_workflow.md` hunk), and the head of the startup log. I found no ruleset readback file; the ruleset claims come from the package.
- **Files read:**
  - `trusted/`: all 7 files.
  - `candidate/`: `repo-cleanup-step1.md`, `package-seal.json`, `pr1109-fresh.json`, `run1109-pr.json`, `simulation.json`, `1109-startup.log` (tail), `1109-packaging.log` (tail), `pr1109-body.md`, `pr1150-body.md`, `comment-6276489652.md`, the manifest (partial), the #1063 diff (partial).
  - Source snapshots: `source-1109`, `source-1142` and `source-STEP3`: `packaging/pyinstaller_common.py` and `metroliza_onefile.spec`; `source-1109`: `docs/release_checks/branching_strategy.md`, `docs/ci-policy.md`; `source-1142`: `docs/ci-policy.md`.

## The failed manual run 39064576622 (it stays FAIL)

**Both jobs checked out 82f8 directly.** That is head 82f8, not the synthetic merge 520fd207.

**Startup job 117493403937 (Windows).**
- It ran `build_windows_exe.ps1 -Mode both`, which is the legacy `metroliza_onefile.spec`.
- PyInstaller died in an isolated subprocess importing `onnxruntime.quantization`, exit code 3221225477.
- In the #1142 sources, `ci-policy.md` reroutes the startup benchmark to the supervised onedir, the portable envelope and the launcher. It states the legacy onefile spec is no longer built there.
- The ONNX workaround in later `pyinstaller_common.py` only covers onedir builds (`ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES`, `filter_onedir_hiddenimports`).
- **So the legacy Windows onefile route is still untested, not fixed.**

**Packaging job 117493403972 (Linux).**
- `pyinstaller packaging/metroliza_onefile.spec` hit `ModuleNotFoundError: scripts`. At 82f8, neither the spec nor `pyinstaller_common` puts the repo root on `sys.path`.
- The #1142 and STEP3 sources fix this in code (`_REPO_ROOT` appended at `pyinstaller_common.py:15-18`).
- Later PASS evidence is cited but I did not inspect it: run 39532176909 at a176139d (from the #1150 body) and run 40351594372 at 18d67f (from the package).

**Neither job is a merge gate for #1109.**
- `ci-policy.md` marks both as non-blocking and release-only.
- The package says the rulesets require exactly the five checks, and those passed.
- #1109's own MUST list (in the PR body) uses the shipped supervised portable route as its gate. That job, 117489412394, passed.
- The PR body itself discloses both failures.

**No repair or rerun is needed before #1109.**
- Between the #1109 and #1142 merges, `develop` will carry the 82f8 packaging defect. That only affects the release-only smoke job.
- The supervised and launcher routes later passed in dispatch 39298529257 at 78d5 (comment 6276489652). That is evidence for the actual routes, not for the legacy path.
- Windows EXE final RC acceptance stays NOT_RUN and is not a merge gate.

## Pre-merge readback for #1109

All seven must hold, read immediately before the merge:

1. `develop` is still `784e44b2…`, the PR head is still `82f8f576…`, the base is `develop`, and the PR is not a draft.
2. GitHub reports MERGEABLE and CLEAN, not BEHIND or BLOCKED.
3. No newer run has a failing result on any of the 5 required check names. The latest passing PR run is 39064650589.
4. The Codex marker still shows `completed`, `has_unresolved_findings:false` for 82f8, and there are no newer comments with findings.
5. **The review-thread check is not covered by the evidence I was given.**
   - `pr1109-fresh.json` has no `reviewThreads` field.
   - Its `reviews:[]` doesn't fit the PR body's "38 previously unresolved threads resolved".
   - The CLEAN state only indirectly suggests zero unresolved threads, and only because the package says the ruleset requires conversation resolution.
   - Read back `reviewThreads.isResolved` via GraphQL with full pagination.
6. The ruleset allows merge commits and does not require linear history. If it doesn't, stop; changing that setting is not covered by the grant.
7. Merge with `--merge --match-head-commit 82f8f576…` and **without** `--delete-branch`. Afterwards, read back:
   - `develop` points to a new merge commit with parents [784, 82f8] and tree `a590d34d…`;
   - the PR shows MERGED;
   - the push CI run on `develop` was observed.

## Findings

| # | Severity | Applies to | Finding |
|---|---|---|---|
| F1 | P2 | #1142 and later | With "branches must be up to date" required and a merge commit landing, #1142, the STEP2+STEP3 PR and #1063 will each show BEHIND. Updating them changes the head, which invalidates the head-bound Codex review, CI and review verdict. Plan an update commit with the expected tree (71d2, then 6287, then a46b) per step. Then rerun Codex and CI and do a short delta review based on tree identity. The package's "rebind checks" step doesn't account for this. |
| F2 | P2 | #1142 | The #1109 body still names the #1142 reference as `15ddbeb7` with tree `bd812a3d`. The current values are `78d5d775` with tree `71d2ce0a`. Don't use the stale tree as a predicate; correct or override it when #1142 is admitted. |
| F3 | P3 | #1109 | The thread-evidence gap described in readback item 5. |
| F4 | P3 | #1109 | Head 82f8 also has a historical required-check **FAILURE**: Windows core smoke in push run 36321711197 (Windows timing, tracked in #1110). Later SUCCESS runs on the same SHA supersede it for merging. The package's #1109 failure section leaves this out; the PR body discloses it. Don't relabel it. |
| F5 | P2 | Release, not #1109 | The legacy Windows onefile route (`build_windows_exe.ps1 -Mode both` / onefile spec on Windows) is unqualified. The release owner must either retire it or qualify it before the final RC, if it is distributed. |
| F6 | P2 | Cleanup | GitHub tags are only "immutable" if a tag ruleset protects them; check for one. Creating that ruleset is a repository setting outside the grant, so otherwise call them retained recovery tags. The manifest's own deletion conditions also require a durable independent archive with SHA256 and a recorded owner. That is still NOT_RUN. Either copy the bundle off the workspace, or have the user explicitly accept the GitHub tags plus a clean-clone fetch of commit **and** tree as sufficient. |
| F7 | P2 | Cleanup order | Deleting a head ref closes its PR. Deleting a base ref closes PRs that target it: the stacked #1149 → #1150 → #1152 chain, with #1149's base being `integrate/2026.09-rc1-build-261018`. Close or retarget explicitly first, with an integration link and readback. |
| F8 | P3 | Cleanup | The `build/step2-rc1-261021` exception: downloading the artifacts and BUILD_INFO is NOT_RUN. Artifacts expire by retention time, not by branch. Finish this or get an explicit waiver before deleting that ref. |
| F9 | P3 | #1109 closeout | "Closes #1108" won't auto-close the issue, because `develop` isn't the default branch. It needs a manual disposition. After the merge, GitHub may automatically mark contained source PRs as merged; keep that state. |

## Package checks

**Manifest counts are consistent:**
- 38 delete-after-integration + 3 archive-then-delete = 41 deletion candidates;
- 6 kept branches + the future release branch = 7 retained;
- 47 remote heads; all 7 pins match.

**Safety guards are correct:**
- Each prepared delete uses `--force-with-lease=refs/heads/X:<full-sha>` with the right semantics.
- Every entry has `deletion_eligible_now=false`.

**The three exceptions are recorded correctly:**
- the 261021 build provenance;
- 7/7 patch-equivalent commits for `win-dlv-1/engineering`, with all 9 SHAs and the 2 merge commits listed, and not mislabelled as ancestry;
- the rejected ONNX branch, archived and not to be merged.

**Historical fields are superseded:** `execution_authority.*=false`, `NOT_RUN_FORBIDDEN_THIS_STEP` and the seal's "stop for orchestrator" instruction are superseded by the grant. Rebuild the delete commands from validated fields. Don't execute the stored text as-is.

**#1149:** 5 accepted + 12 replaced + 11 audit-only = 28 files, which is complete. The withdrawn PoC defects are listed separately. The R4Δ fixes (P3 only) were not re-reviewed, which is disclosed. The final bindings for C13, C14 and C15 are present, and their FULL1+DELTA1 budgets are spent as recorded. The package is complete here.

**#1063:**
- What I read is docs and policy only.
- Under its own definition (changes to gate and review-integrity governance), it is CRITICAL. That means an independent review of the conflict resolution, plus cross-provider evidence or an explicit user exception before integration.
- A Codex Review of the refreshed head can supply the OpenAI side.
- The final head will be reviewed separately.

## Remote branch retirement and local worktrees

**Keeping the registered local worktrees and their local branches does allow remote branch deletion, as far as content is concerned.**
- Deleting a remote branch doesn't touch local refs, worktrees or uncommitted work.
- Local branches will show upstream `[gone]`.

**Dependencies still to clear before each deletion:**
1. Open head and base PRs (F7).
2. Queued or running CI on that branch, re-checked at deletion time.
3. Live links in open issue and PR bodies. For example, #1110, #1108, #1106, #1096 and #1095 reference `build/onefile-20260927`; repoint them to the tag or SHA, or record that the owner accepts the broken link.
4. The 261021 artifact archive (F8).
5. Active writers in those worktrees. A later `git push` from one would recreate the remote branch, so check and notify the owners, and read back the remote after deleting.
6. A fresh, finite manifest frozen after integration: the current one was taken on the pre-merge base.

Each later step needs its own fresh base/head/check/thread/Codex readback and a review of whatever changed. No master promotion, release, tag outside `archive/`, or settings change is covered by the grant.
