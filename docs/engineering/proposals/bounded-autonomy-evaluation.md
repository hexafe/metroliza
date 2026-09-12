# Bounded autonomy: proposal for Metroliza's independent assessment

Date: **2026-09-06**. Owner: Product Owner. Evaluation: **Issue #1030**.
Status: **PROPOSED, NOT ACTIVE POLICY**. No existing task, AGENTS rule, model selection, evidence ledger or permission is changed by this file.

Pozdrowienia od kuzyna z TupTupa. Sprawdź krytycznie — nie masz obowiązku zgadzać się z rodziną. :)

## Why this is here

The Product Owner asked whether a stronger delivery supervisor could finish a bounded task without repeatedly returning for permission to fix ordinary local failures. Similar practices are being written for TupTup. Metroliza must decide which principles fit its own repository rather than import another project's commands, risks or release authority.

Before recommending adoption, inspect current `AGENTS.md`, `docs/project/README.md`, `docs/project/architecture.md`, `docs/project/development_workflow.md`, the engineering routing/task-packet/report templates and applicable CI/release documents. Read relevant current Issues/PRs. Normal work targets **develop**, not the GitHub default master. This proposal starts from develop `77e398375e5277858110c746a428d13535db6a59`; reacquire live state for evaluation.

## Proposed principles to judge

### P1. Delegate an outcome

One delivery supervisor owns one bounded leaf Issue through inspection, implementation, validation, independent review and in-scope correction. The external orchestrator retains product direction, architectural/data-policy decisions, cross-PR integration and final merge/release decisions. Do not delegate an entire milestone as a monolithic coding task.

The packet must name the outcome, invariants, primary paths, approved companion tests/docs/snapshots, forbidden surfaces, exact source, workspace/resource ownership, existing commit identity, publication owner, handoff route and budgets. Inspect generated/source-hash dependencies before freezing file ownership. A security snapshot update needs an explicitly approved binding and producer-plus-pin review; never waive checks generically.

### P2. Repair ordinary development failures locally

Within the accepted scope, diagnose a compile/lint/unit failure, make a minimal supported correction, rerun affected checks and continue. Reuse verified source/dependencies, fix own temporary helpers, format owned files, choose an approved writable filesystem and clean only owned reproducible state after stopping its processes. Existing tool permissions still apply.

Candidate pilot budget: three substantive diagnosis/correction iterations. This is not three commands and not a ban on ordinary test-driven development. Record the hypothesis, new observation/change and outcome for each cycle. Do not repeat unchanged failures until green. Metroliza should select its own justified budget rather than copy this number automatically.

### P3. Failed evidence is not automatically a failed delivery task

Close and retain a failed frozen test/benchmark/certificate attempt. Never mutate its source in place, discard unfavorable measurements, transfer results to a changed head or resume a terminal ledger. Returning to development may be pre-authorized within scope.

Another formal attempt requires a fresh ID, source/environment binding, required review and an explicit count/prerequisite budget in the initial packet. Default: no new formal attempts unless named. Distinguish ordinary local debug cycles, hosted CI reruns, frozen benchmark campaigns and release evidence; their rules need not be identical. Preserve the project's actual measurement and CI policies.

### P4. Keep independent review inside the delivery loop

A packet may let the supervisor request a fresh read-only reviewer once a candidate exists, handle its findings, validate corrections and request follow-up review without a Product Owner roundtrip each time. Candidate pilot budget: initial review plus two correction/re-review cycles.

The reviewer did not author the change, sees the real contract/diff/evidence and pins exact final source. Self-review is not independent review. Keep adverse findings; no reviewer shopping. Later changes invalidate affected review. If genuine isolation is unavailable, mark external review pending. Coordinators/workers still cannot merge their own PRs.

### P5. Bound the team

Prefer one lead, optional disjoint read-only investigator, and a reviewer only when a candidate exists. Candidate pilot limit: two concurrent subagents, no recursive spawning. One writer per path; one owner per database, benchmark, GUI/browser and shared runtime resource. Delegate code only through ready, explicitly owned leaf Issues.

For a difficult end-to-end leaf, Astra/Ultra may be selected only when supported by the actual client/model; an expressly approved Astra/XHigh fallback is possible. High remains appropriate for a well-defined implementation/review. Lighter supported workers may do mechanical or read-heavy tasks. Model, reasoning, agent count, autonomy and permissions are separate. Record actual identity or `not visible`; do not invent cost savings or unsupported configuration tokens.

### P6. Stop for a decision or safety boundary

Escalate missing product/data/privacy/architecture decisions, unapproved security changes, potential real-data destruction/exposure, unresolvable ownership/source drift, missing required evidence or exhausted progress budgets. State the precise decision needed, not only BLOCKED.

A tool denial stops the denied operation. Do not rotate/probe credentials, change identity/transport or disable protection to bypass it. Continue only unrelated work already authorized. A local dependency is not automatically in scope. A known, pre-approved invocation-only commit identity may resolve missing metadata; it is not GitHub authentication.

### P7. Remote rights remain explicit

An initial packet may authorize named branch-scoped commits/pushes/PR/comments through working approved tools. External-only publication means zero worker writes and one accessible handoff. No force push, self-merge, real database migration, Google service action, release/tag/promotion, deployment, secrets or billing rights arise from this proposal. Keep Metroliza's standing merge and release rules; never borrow another project's authority.

### P8. Short reporting, retained proof

Chat: normally 8–12 lines, around 150–200 words or less, with status, exact source, real results, first blocker, publication state and next decision. One canonical technical checkpoint on the owning issue/PR; mirrors are links plus a short status. Preserve full receipts, hashes, measurements and source/patches in appropriate files. N/A and NOT RUN are not PASS.

If publication is unavailable, deliver one safe handoff and necessary patch through a genuinely available file channel. A host-local path is not access for another session. Without attachments, include necessary safe payload once, not duplicate reports. Never publish customer data, proprietary measurements, credentials or raw private logs. Read historical evidence only for a concrete unresolved question.

## MUST: Metroliza-specific evaluation

For each P1–P8 return **ADOPT / ADAPT / REJECT**, exact repository evidence, proposed wording and any unresolved decision. A supported rejection is useful, not failure.

Explicitly preserve and evaluate implications for:

- Canonical `src/metroliza` and `metroliza.*`; compatibility-only legacy modules.
- Local-first operation, SQLite transactions, cancellation and deterministic cleanup.
- Correct measurement/statistical semantics, complete exports/offline dashboards and sensitive customer/supplier data.
- Optional native/Rust paths, deterministic Python fallbacks, parity, representative benchmarks, locked builds, packaging and rollback.
- Windows support: hosted CI is not clean-machine or packaged-application proof.
- Frozen performance baselines, CI thresholds, import/provenance/approval guards and separate release-owner/live-service evidence.

Do not copy TupTup's Next/Supabase commands or its six-row runtime protocol. Read the actual Metroliza workflow and choose checks based on the changed boundary. Do not retrofit this policy into active #1028/#1029 or a frozen campaign.

## SHOULD: output and pilot

Use the existing Codex session at a safe task boundary; no immediate competing worker is requested. Astra/High is a reasonable requested evaluator route if available and approved locally; use more reasoning only for a genuine unresolved question.

Produce one assessment, a minimal proposed documentation diff, and one suitable low-blast-radius pilot with exact files, resource ownership, repair/review budgets, formal-attempt count, publication rights and escalation criteria. Success metrics: unnecessary human roundtrips avoided, correct acceptance, substantive findings and preserved evidence—not agent count or fabricated token savings.

## DEFERRED

Activation/merge of new rules, changes to active packets, production code, CI thresholds, frozen benchmarks, dependencies, native/packaging contracts, customer datasets, credentials, remote services and releases. Assessment first; a separately reviewed adoption decision follows. This draft does not authorize the evaluator to overwrite existing instructions.

## Terminology sources

[Codex subagents](https://developers.openai.com/codex/subagents) and [agent approvals/security](https://developers.openai.com/codex/agent-approvals-security), checked 2026-09-06. Client support must be verified at dispatch. The budgets and proposed workflow above are engineering policy choices, not claims that OpenAI certifies their suitability for Metroliza.
