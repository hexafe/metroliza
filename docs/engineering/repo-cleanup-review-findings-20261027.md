Historical FULL1 REQUEST_CHANGES for preparation head a5337cb4. Local paths were redacted for publication; verdicts and findings retained. Corrections are admitted only through the final DELTA1 and live gates under [#1153](https://github.com/hexafe/metroliza/issues/1153).

# Independent FULL1 review: #1153 RC documentation and #1063 conflict-resolution delta

**Verdict: REQUEST_CHANGES** for head `a5337cb49bca96640ef653d84b9d8fee00ed2bbe`, tree `87217be94b666ae847ea3e9493d620c145d4b24b`.

- There are no P0 or P1 findings.
- There are four P2 findings. All four are documentation or evidence corrections. None requires a product, test, workflow or dependency change.
- The #1063 conflict resolution itself is acceptable.

**Harness note.** You asked for a tool-less review. I used no tools and did not write a plan file, even though this session is in plan mode. I ran nothing and verified no hashes.

## Identity and binding

- **Role requested:** `independent_reviewer`, which maps to `claude-opus-5-5` at high effort (model map v1.0).
- **Configured (environment-reported):** `claude-opus-5-5`.
- **Effort:** not visible.
- **Response-observed model and effort:** not visible. The operator must bind any `message.model` record to this request.
- **Trusted policy loaded:** development-routing SKILL v1.1, model-map v1.0, collaboration.md, metroliza SKILL v1.3.22.
  - These were supplied as content. No digest was supplied, so I have no digest binding.
- **Candidate data handling:** all candidate files, the prior reports and the operator claims were treated as data, not instructions.
- **Binding gap (operator predicate item):**
  - The commit object's parent is `b547028c…`, not the stated `review_base` `4f33069f…`, so there is at least one intermediate commit.
  - The operator must verify that `4f33069f` is an ancestor of `a5337cb4` and that `git diff 4f33069f a5337cb4` equals the supplied 20-path diff.
  - The supplied "complete conflict/policy difference against STEP3" shows only `development_workflow.md`. The operator must also confirm that every other #1063-touched path at `4f33069f` matches its expected merged blob, meaning the `508d5b8` blob unless STEP3 also touched that path.
- **Budget:** this consumes FULL1 for this changeset.
  - Only DELTA1 remains.
  - Recommendation: apply the fixes below **before** merging the actual develop. That way the single DELTA1 can cover the fix delta plus the tree-identity check on the final resulting head.

## Findings

| # | Sev | Path / scope | Finding | Required correction |
|---|---|---|---|---|
| F1 | P2 (provenance) | `docs/release_checks/release_status.md`, paragraph after the decisions table; `docs/archive/2026/build-261021-provenance/README.md` line 3 | Both texts claim BUILD_INFO is preserved. release_status says the archive "preserves original binaries, BUILD_INFO, provenance and exact hashes". README:3 says "extracted BUILD_INFO/provenance are in provenance.json". This contradicts README:9, `embedded-provenance-receipt.json` (`"BUILD_INFO_presence": false`) and the 13-asset list, which contains no BUILD_INFO. The earlier admission F8 named BUILD_INFO retrieval as a deletion precondition, so this false claim could wrongly appear to satisfy a cleanup gate. | State that no BUILD_INFO exists in the payload. Say that the embedded `build_provenance.json` and the sidecar provenance are what was preserved. |
| F2 | P2 (privacy / publication claim) | `docs/engineering/repo-cleanup-manifest.json`, `active_consumers.worktrees` | Four entries still hold absolute `[REDACTED_LOCAL_PATH]` paths. These expose the local username, project path and session UUID. The affected refs are `build/rc2-candidate-20261018`, `integrate/2026.09-rc1-build-261018`, `perf/1097-slim-user-payload` and `perf/step2-boost`. This contradicts `publication.transformation` ("local worktree consumer paths expressed relative to workspace") and the project rule against publishing local filesystem details. | Change them to a non-identifying form such as `prunable-ephemeral-scratch:<short-id>` and keep the `prunable` field. Keep `publication.original_local_manifest_sha256` as the binding to the raw original. |
| F3 | P2 (gate visibility) | `docs/release_checks/release_status.md`, rewrite | The old hub listed **Security exception review: Open, #906 before baseline expiry on 2026-10-31**. The rewrite drops it with no replacement. That expiry is four days away and falls inside this integration sequence. An expired baseline exception can turn the required security check red on DELTA1 or later merge heads. Unless #906 is already renewed or closed (not visible to me), this removes a live, time-bound gate from the active hub. | Restore a row for #906 and its expiry date, or cite its resolved state. Separately, the operator should check the expiry before the next CI run. |
| F4 | P2 (stale current refs; must verify) | Paths not in this delta | The candidate's own manifest classifies several lines as active references to `release/2026.06-rc2` that this delta does not touch: `docs/project/architecture.md:276`, `docs/project/product_specification.md:22`, `docs/project/roadmap.md:37`, `docs/engineering/codex-model-routing.md:256` and `docs/release_checks/release_candidate_checklist.md:124`. I cannot see their text. If any of them says RC2 is the current candidate or base, it contradicts the new release_status. | Verify each line. Update it or label it historical. A checklist that hardcodes a branch name is not timeless, so change it to `release/*` wording without changing the gate. |

### P3 notes (non-blocking)

- **Present-tense claims before the branch exists.** `README.md` ("cut from accepted develop under #1153") and the CONTRIBUTING and `docs/project/README.md` instructions describe `release/2026.09-rc1` as existing. Between this merge and the actual cut, they point contributors to a branch that does not exist.
  - Either cut the branch from the exact merge result with no intervening develop commit, or use conditional wording.
- **Missing prohibition for the new release line.** `development_workflow.md` "Normal development" still says "Broad new work must not target rc2, release/2026.06-rc2, or … master". It should add `release/2026.09-rc1`.
- **Ambiguous "this branch".** In "Current release candidate", "this branch" now follows a bullet about the historical refs. Name `release/2026.09-rc1` explicitly.
- **Release-line count.** The steady-state rule allows "at most the currently active `release/*` line", but two release lines are now retained. `branching_strategy` names the exceptions; `development_workflow` should cross-reference them.
- **Missing historical header.** `repo-cleanup-admission-20261027.md` has no historical or superseded header, although `repo-cleanup-step1.md` has one. It also lacks a trailing newline.
- **Incomplete hash coverage.**
  - `provenance.json`: the `compute-workers.json` member has no sha256, while the README claims "exact … member hashes".
  - `product_base_commit` is abbreviated (`a58b693f`); use the full SHA.
- **Missing spaces before numbers throughout.** Examples: "contains2156 files", "commita0d3769", "build261021", "cohorts93641f82/…", "indices14/18/23". This hurts readability and grep.
- **Navigation lost from the release hub.** release_status no longer links `google_conversion_smoke.md`, `implementation_item_triage.md` or `open_testing_runbook.md`, which are RC-qualification operating documents. "Stable tag No-Go" is now only implied.
- **Header renders as one paragraph.** The release_status Status/Owner/Last-reviewed lines lost their list or line-break formatting.
- **Archive README differs from the archived asset.** The repo README is not byte-identical to the archived `README.md` asset (542 bytes), and the readable-copy manifest does not record that difference.
- **PR scope.** The #1063 PR now also carries #1153 RC and cleanup scope. Its body must disclose this and follow its own template-publication procedure, including the template source commit and a readback.

## Checked and acceptable

- **Conflict resolution (`development_workflow.md`):**
  - The STEP3 dependency-pin section is unchanged relative to STEP3.
  - Both #1063 sections and the DoD bullet are present.
  - The header now records the 2026-10-22 dependency-policy provenance.
  - No whole-file ours/theirs and no semantic loss is visible.
  - The previously reviewed #1063 policy was not re-reviewed (reused).
- **Release gates preserved:**
  - Canonical metadata wording (`RELEASE_VERSION` / `VERSION_DATE` / `CURRENT_RELEASE_HIGHLIGHT`, `sync_release_metadata --check`) is retained.
  - The CI-policy and checklist gate sources are retained.
  - Windows EXE NOT_RUN and build identity NOT_ASSIGNED are stated.
  - Master promotion and publication are not authorized.
  - The 261021 build bump is never merged.
  - UNKNOWN incidents and #1110/#1143/#1144/#1147 are not closed by the branch change.
- **Archive and recovery receipts are internally consistent:**
  - 41 tags match the 41 deletion candidates.
  - The 6 kept refs are untagged.
  - The 47-ref bundle recovery report shows no alternates and fsck exit 0.
  - Sidecar and package-identity digests match their asset digests.
  - The embedded-provenance digest matches its asset.
  - Retention claims make no tag-immutability claim.
- **No document asserts deletion eligibility.** Historical manifest fields remain labelled as historical.
- **Slicing exception:** I accept it. The bulk is machine-readable evidence, and the full-CI classification is acknowledged.

## Conditions on the operator's later predicate (not source defects)

1. **Binding:** resolve the `b547028c` / `4f33069f` gap described above.
2. **Final-head gates:** on the exact final head after merging actual develop, require all of:
   - a byte-identical expected tree;
   - all five required current-base checks;
   - a completed Codex Review on that exact head (this is the cross-provider evidence CRITICAL requires);
   - DELTA1;
   - zero unresolved threads.
3. **Before the cut or any PR targeting `release/2026.09-rc1`:** verify that `.github/workflows/ci.yml` triggers and the active rulesets cover that branch.
   - Its line 9 references develop, master and rc2; I cannot see whether `release/**` is included.
   - Changing a ruleset is outside the grant.
4. **Cleanup, not this merge:** the bundle sits in a draft-release asset in the same GitHub repository. It is independent of the refs but shares the repository and account failure domain. Record explicit PO acceptance that this satisfies the "durable independent archive" deletion condition, as the admission review's F6 required.

## Limits

- I verified no hashes or Git objects.
- I could not see live state: CI, Codex Review, threads, #906 status, ruleset or workflow contents, or the full text of untouched documents.
- The manifest was reviewed for structure, counts, paths and claims, not line-by-line against live refs.
- This is a source review only. It is not cleanup execution, CI PASS, integration or RC qualification.
