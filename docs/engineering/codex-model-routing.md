# Codex orchestration and model-routing playbook

Status: policy update for new or explicitly reconciled tasks; repository adoption requires review.
Owner: external product/development orchestration. Reviewed: 2026-09-23. Refs #1061.

Root [AGENTS](../../AGENTS.md) is the concise router. The
[dated research](model-routing-research-2026-09-23.md) records vendor facts and limitations.
This document is a working policy, not an agent configuration, benchmark result or release approval.

## 1. Authority and continuity

PO owns product/release direction and separately approved remote/destructive operations. External
orchestration owns the leaf packet, risk/routing decision, independent merge assessment and merge.
The coordinator owns complete in-scope execution and integration; helpers own explicit slices only.
Ordinary related edits, fixtures, tests and review corrections need no repeated PO approval.
Actual scope, security, data ownership, cost or capability conflicts require adjudication.

**An active or paused packet is grandfathered.** This update must not switch WIN-DLV-1 or another
running executor, change its budget, reset failed attempts, rebase its source, restart it, or send it
new instructions. Apply revised routing at the next new task or an explicit reconciled handoff.
Old evidence keeps its actual model/source identity. Never relabel a 5.6 result as a GPT-6 result.
Updating a Project mirror does not edit ChatGPT settings.

Follow the [source hierarchy](../project/README.md). Read live relevant Issues/code/CI, not the full
old conversation each time. Recover lost sessions from published commits and accessible evidence;
mark unavailable local objects honestly and reconstruct only necessary missing work. Transfer
ownership before writes; a named archive path is not proof its bytes were transferred.

## 2. Delivery outcomes and severity triage

One leaf/PR delivers one coherent outcome or root-cause repair. A milestone coordinator joins leaves;
it does not turn the project into one giant PR. Roughly eight meaningful files or 600 net lines
prompt a slicing check, not an automatic stop or a cheaper risk classification.

Every distinct confirmed defect receives an existing/new deduplicated Issue with evidence,
impact/confidence, affected MUST, severity, owner, workaround and target release/pack. Unconfirmed
hypotheses stay labeled. A bot's P1/P2 badge alone neither sets severity nor authorizes deferral.

- **Critical/major or violated current MUST:** correct or safely contain now within the right leaf.
  Examples include confidential exposure, lost/corrupt data, materially wrong measurement/statistical
  results, blocked primary journeys and relevant serious crashes/hangs. Independent safe work may
  continue while a blocker is assigned; no competing fixes in unrelated PRs.
- **Minor with bounded impact:** record and target a coherent stabilization pack. Do not expand the
  current feature into unrelated refactors. The orchestrator explicitly adjudicates merge/release
  deferral; an unmet MUST cannot become minor just to save effort.
- **Cosmetic/speculative:** DEFERRED unless deliberately selected. Accessibility that prevents a main
  operation is not cosmetic. Missing root cause proves neither harmlessness nor product guilt.

Before each minor and major release, select related minor Issues by component/shared verification,
finish those packs, inspect the integrated release delta and run required regression and packaged
Windows journeys. Remaining minor items need explicit owner, rationale and next review target.
A patch release normally uses targeted verification plus every applicable security/data/package gate.
Do not postpone development testing until release or audit every unchanged file by ritual.

## 3. Routing dimensions and actual support

Classify whole-change risk separately from model, effort, delegation, speed and permissions.
Capability, tool access, client support, source evidence and release authority are not interchangeable.
A stronger model does not fix missing Windows/Docker access or retrieve an unavailable local file.

Verified current IDs: `gpt-6-luna`, `gpt-6-sol`, `gpt-6-astra`, and legacy `gpt-5.6-terra`.
No official GPT-6 Terra was confirmed in the inspected catalogue. Terra remains available only as
an explicit compatibility/availability or measured-workload choice; it is not a mandatory price tier.
Resolve ID and effort in the actual client at dispatch. Planned, configured and observed settings
are separate; absent telemetry is `not visible`, not a guess based on self-identification.

## 4. Whole-PR coordinator and reviewer

These defaults are provisional local engineering choices, not a Metroliza benchmark ranking.

| Class and actual scope | Coordinator | One independent scope reviewer |
| --- | --- | --- |
| MICRO, explicit code correction under a fixed contract | Luna 6 / high | Sol 6 / medium |
| BOUNDED INTEGRATION, accepted seam without new critical boundary | Sol 6 / medium | Sol 6 / high |
| FEATURE / CROSS-LAYER, ordinary multi-layer feature | Sol 6 / medium | Sol 6 / high |
| Complex feature state, failure paths or contracts | Sol 6 / high | Sol 6 / high |
| CRITICAL, proven settled bounded implementation exception below | Sol 6 / high | Astra 6 / high |
| Unresolved critical ownership/architecture, data-loss/concurrency reasoning | Astra 6 / high | Independent Astra 6 / high for the critical boundary |
| Formal milestone/release assessment | Astra 6 / high | Independent Astra 6 / high for unresolved critical acceptance |

A release assessor reuses already accepted independent reviews; it does not order another complete
review of every merged leaf. For a new unresolved critical change, an author cannot provide the
independent review of its own implementation. Required configured GitHub review remains; do not
request duplicate bot passes or add Sol review before the selected Astra review without a distinct risk.

### Settled-critical exception: all conditions are required

External orchestration may explicitly select Sol/high for a still-CRITICAL leaf only if the packet:

1. Names an accepted versioned contract and complete owned boundary, including failure/cancel paths.
2. States data/authorization/concurrency invariants, testable negative cases and rollback or safe
   recovery/idempotence where relevant; no unresolved ownership or irreversible side effect remains.
3. Does not ask the implementer to invent a new trust/transaction/native-lifetime architecture or
   decide release risk. Small file count and the word "migration" do not establish settlement.
4. Assigns one independent Astra/high review of that whole affected critical boundary and retains
   all specialized tests and separate operational approvals.

If any condition is unproved, use Astra/high for the unresolved work. An expensive reviewer after
implementation is not a substitute for resolving a missing design beforehand. Conversely, a
mechanical fixture next to SQLite is not automatically critical. Formal release ownership remains
with the designated release owner, not the model.

### Reasoning and escalation

For coding, begin at Luna/high or Sol/medium; use Sol/high for complex states/invariants.
Astra/high is our deliberate critical-risk choice, not OpenAI's universal default. For a bounded
noncritical question requiring Astra, low/medium may suffice. Trivial non-code can use Luna low/medium.

Do not translate old Ultra into `xhigh`, `max` or an API value automatically. Client Ultra combines
reasoning/delegation; API model cards expose a different effort enum. Luna has no Ultra mode in the
current client guide. Higher effort and Fast need a specific expected benefit and a finite budget.
Keep standard speed by default. A prompt requesting a setting does not configure it.

A packet may preauthorize one escalation ceiling and question (for example Sol medium to high).
First distinguish insufficient evidence, environment denial, ambiguity and oversized scope from
reasoning difficulty. No automatic Luna -> Sol -> Astra ladder or new team after every P2.
Switch only with one writer and a recorded handoff; do not silently weaken a selected critical route.
Unavailable required models get one concrete alternative for orchestration, not fabricated access.

## 5. Adaptive workers and effective permissions

GREEN code/fixtures: Luna/high (trivial non-code low/medium). YELLOW accepted integration: Sol/medium.
RED complex reasoning: Sol/high. CRITICAL: Astra/high unless the same explicit settled exception is
satisfied. Worker risk does not downgrade the whole-PR coordinator or reviewer.

Start with zero implementation helpers. Add one for one genuinely independent slice and two only
when there are two useful disjoint slices. Default maximum: two additional contexts concurrently,
including the independent reviewer. Thus two workers plus a reviewer need staging, not four live
contexts by default. A distinct exceptional specialist needs explicit scope and total budget.
No recursive swarm, overlapping writers or helper invented merely to stay busy.

Choose both model and effort for each helper; verify actual inheritance before claiming economy.
Give it only the needed contract, paths, positive/negative acceptance and evidence pointers.
Helpers return a compact result and focused tests; the coordinator owns aggregate validation.
If safe isolation or the requested model selection cannot be enforced, serialize the work.

**Read-only is both a role and an effective-permission question.** Check the child's actual sandbox,
approval mode, connector tools and write authority after inheritance/overrides. An instruction or
custom-agent default alone does not prove enforcement. If effective read-only cannot be assured,
review a controlled snapshot or use a separate no-write context. Do not change the active parent's
permissions as a side effect of adopting this policy. Independent reviewers inspect requirements and
source/tests rather than merely endorsing the author's conclusion; reuse their context for deltas.

## 6. Bounded review, tests and budgets

Default cycle: implement with focused tests -> one complete affected-scope review -> consolidate
blocking families -> regression checks -> delta review of fixes/direct consumers -> exact-head merge
disposition. Extra review needs a named substantive blocker/invalidated assumption and a limited
question. Critical discoveries are raised promptly; other safe review work may finish together.
This is a review-effort default, never permission to accept a serious remaining defect.

Use representative fail-before/negative controls for consequential new invariants, not test-count
claims or an enormous redundant Cartesian matrix. Distinguish a test-oracle defect, product defect,
environment issue and unknown. Preserve all original failures and retries. A later PASS is not a
retroactive fix of an unexplained older failure. No retry-until-green, skip/xfail, sleeps, forced
clicks, silent threshold changes or fabricated source edits to obtain another run.

Plan aggregate checks on stabilized source once where they add evidence; existing required CI is
canonical integration evidence when it actually covers the contract. Do not duplicate its entire
suite locally per comment/worker. An explicitly required local/manual/specialized gate remains until
its owner changes it with evidence. Changes to CI or protected gates require a separate approved
infrastructure/policy change. Relevant tests and security/data checks continue during development.

A task defines finite reasoning/agent/experiment and resource boundaries. Prefer meaningful effort
or runner-time budgets over approvals per routine commit. Record API charges, subscription allowance,
CI runner time and wall time separately; no invented conversion or savings. An approved model change
does not reset a shared subscription quota. Existing task limits remain intact until reconciled.
At exhaustion, preserve work and escalate one concrete decision; no automatic restart or hidden new
budget. Further diagnostic runs need a correction or a named evidence question, not random sampling.

## 7. Context and optional new capabilities

Keep AGENTS a router; load specialized guidance only for its affected boundary. Keep a compact task
state/ownership/decision table on GitHub, not repeated historical logs in every prompt. After
compaction or a lost session, recheck current refs, ownership and accessible evidence before writing.
Do not throw away accepted unchanged evidence solely because a model or head changed.

Optional client/API capabilities are described, not enabled, by the research. `configuration_update`
can change GPT-6 effort between API responses under documented constraints; it is not a model switch
or guaranteed Codex/Herdr feature. Track effective settings explicitly and respect its compaction
restrictions. Astra's experimental context notes/search, when available, concern the same task and do
not recover lost local files or replace GitHub authority. Enable only in a separately chosen new task.
Async tool calls and steering do not grant parallel write permission or approval to interrupt an
active operation. No application SDK/framework or `.codex` configuration is introduced here.

## 8. Three distinct acceptance gates

**Publication for CI/review:** verify scope, branch authority, secrets and side effects. An authorized
Draft can honestly carry incomplete/red local results. A bounded synthetic engineering experiment
can obtain missing evidence under its explicit authority without declaring unrelated failed gates
green. A Draft badge is not a security sandbox or release permission.

**Merge:** only external orchestration squash-merges under standing PO authorization after its own
independent exact-head verdict READY FOR MERGE, unchanged reviewed head, terminal-success required
checks for the current integration result/base, every applicable project-specific gate, adjudicated
and resolved review threads, no later blocker and actual mergeability. Refresh integration evidence
when base movement invalidates it. The review can reuse bound unchanged evidence and inspect the
new delta; it is not an automatic third full audit. No author self-merge or force/direct-base shortcut.

**Release/package:** merge alone does not qualify an EXE, clean machine, live-service operation,
legal approval or real-data workflow. Bind the complete candidate, artifact identity and actual
journeys; apply [development tiers](../project/development_workflow.md#6-validation-tiers) and
[branch/release rules](../release_checks/branching_strategy.md). After minor/major stabilization,
record remaining issue dispositions and the release owner's Go/No-Go. Source publication, release,
tag/deploy, migration, credentials, billing and destructive operations retain separate authority.

## 9. Metroliza-specific evidence binding

Normal base/target: `develop`; `master` is production/history, with the frozen release references
controlled by the branch decision, not changed by model policy. Canonical `src/metroliza`,
compatibility-only `modules`, local-first/confidential data, SQLite transactions/publication,
bounded processing, deterministic cleanup/fallback and offline dashboards remain mandatory.

| Impact | Required evidence when applicable |
| --- | --- |
| Documentation/process | Tier 0 structure/links, policy consistency, hygiene, diff and affected policy tests; not invented product QA |
| Normal integration | Exact-head/current-base required GitHub checks and focused behavior, real Qt append/coverage where required |
| SQLite/data | Atomicity, rollback/idempotence, concurrency, connection/worker ownership and correct row/result identity |
| Native/Rust | Locked build, Python parity including warning/failure/cancel/fallback, representative performance, packaging, rollback |
| Privacy/security | Appropriate negative-path/exposure and dependency/secret checks; no raw measurement/credential evidence |
| Windows packaging | Real packaged path, ordinary-user/no-developer-Python, relevant cancel/reopen, OCR/SQLite/workbook/dashboard/fallback behavior |
| Performance | Representative command/baseline/environment; advisory failure stays recorded, not extrapolated from a microbenchmark |
| Release | Exact full candidate plus applicable clean-machine Windows, Google, notices/legal, rollback and release-owner evidence |

No benchmark/model name certifies scientific correctness or data safety. A documentation-only
change cannot mark runtime evidence PASS; a native source test cannot certify a packaged EXE.
Separate product decisions still govern real-data usage and local representative-data acceptance.
Dependabot activation and other separately owned infrastructure remain outside this policy.

## 10. Adoption record and reporting

This replaces the reusable routing/process guidance adopted in #965 while preserving its Metroliza
bindings. Historical reference blobs remain recorded: TupTup AGENTS `2e2e5013decdf025e8e5d55ef354ddc2b2af9c5b`
and old playbook `2e49a655b0f8098abf498c7f2e5b795c0cf2f8a0`. Current comparison is TupTup PR175
at `d0db1cc476942cb77e26adb8e759c4edbb8e5e67`, still an unmerged proposal at inspection.
We adopt independently verified model facts and the approved delivery-first direction, not TupTup's
Next.js/Supabase/RLS/space/GPX/Mapy/Vercel rules or its CI check names. Metroliza's Windows/native/data
rules are equally not universal requirements for other repositories.

Use the [task packet](codex-task-packet-template.md) and [PR report](pr-routing-report-template.md).
Report delivered behavior, precise blockers, fixed/deferred Issues, actual source/artifact evidence,
review rounds and observed usage. Learn from the next real bounded tasks without running a new
four-model benchmark campaign. Repeated misses trigger examination of scope/tests/instructions and
then justified routing adjustment, not automatic model escalation or automatic critical downgrade.
