# Codex orchestration and model-routing playbook

Status: Active supporting engineering policy
Owner: Product/architecture maintainer
Last reviewed: 2026-09-04
Decision: [#1024](https://github.com/hexafe/metroliza/issues/1024)

This playbook expands [`../../AGENTS.md`](../../AGENTS.md). It does not replace the active Issue,
architecture, development workflow, branch/release policy, or a separately required approval.
The defaults below apply to new packets. Existing named routes, scope freezes, correction limits
and approval gates remain binding until an explicit replacement packet is issued.

## Verified model reference

Official sources were checked on 2026-09-04; the routing recommendations are project decisions,
not measured claims of model superiority on Metroliza.

- **GPT-6 Astra**: API ID `gpt-6-astra`; documented efforts are `low`, `medium`, `high`, `xhigh`,
  and `max`. There is no documented Astra `none` or `ultra` effort in this reference. [1]
- **GPT-6 Pro** is the ChatGPT product option for Astra. It is not a Codex model ID or an effort
  value; Chat controls must not be translated into API parameters by name alone. [2]
- **GPT-5.6 Luna, Terra and Sol** remain separate options. Their documented API efforts include
  `none`, `low`, `medium`, `high`, `xhigh`, and `max`; this policy normally uses medium/high. [3–5]
- Astra access is rolling out. Availability in Chat, Work, Codex and API may differ. Work/Codex
  allowances are separate from Chat, and Astra usage can consume allowance faster than Sol. [2,6]

Use only controls actually supported by the execution surface. Historical `Ultra`, an effort
value, a Pro option and multi-agent execution are not interchangeable. An old Ultra packet needs
an explicit route refresh, not a blind replacement with `max`. A model name in a prompt requests a
route; it does not prove which model executed it.

## Universal orchestration core

### 1. Authority

The authority chain is Product Owner → external project orchestrator → Codex coordinator → bounded
workers. The Product Owner owns direction and separately gated decisions. The external orchestrator
owns specifications, routing, independent exact-head merge review and the merge decision. The
coordinator owns execution, integration, validation and PR preparation; workers own only assigned
slices. Internal readiness review is not the external independent merge review.

No role may invent missing product, security, data-ownership, release or remote-operation authority.
The active packet is the scope boundary. Routing changes do not authorize an operation or waive a
gate. A high-capability model is not evidence of correctness.

### 2. Two separate routing decisions

Classify the whole PR separately from each delegated slice. Also distinguish:

- **Consequence**: severity, data/security exposure, release and rollback obligations.
- **Reasoning difficulty**: unresolved contracts, coupling, uncertainty and quality of evidence.
- **Phase**: diagnosis/design, implementation, independent review or mechanical execution.
- **Route**: model and supported reasoning effort, chosen separately from worker count.

A small accepted correction can be implemented by Terra while a critical whole-PR coordinator and
review retain Astra ownership. Conversely, a short change that invents a security contract is not
MICRO. A P0 label, a merge operation, elapsed time or a large allowance does not itself select
`xhigh`/`max`. File count is a reviewability signal, never a substitute for semantic scope.

### 3. Whole-PR coordinator classes

| Class | Default coordinator | Reasoning | Whole-change test |
| --- | --- | --- | --- |
| MICRO | GPT-5.6 Luna | medium | Accepted mechanical change, inventory, or evidence collection; no unresolved contract |
| BOUNDED INTEGRATION | GPT-5.6 Terra | high | Implementation of one accepted seam with bounded integration evidence |
| FEATURE / CROSS-LAYER | GPT-6 Astra | high | New feature, UI workflow, durable contract, or several coupled layers |
| CRITICAL / MILESTONE | GPT-6 Astra | high | Integrity, concurrency, security, migration, packaging or major architectural responsibility |

Astra `high` is the default for substantial UI/backend work, not a mandate for every task. A
mechanical closeout of an already accepted decision can use Luna/medium; the external merge owner
and all safety/evidence gates remain unchanged. A release or migration decision is not mechanical.
GPT-5.6 Sol/high remains an explicit complex-work or reviewer alternative when justified by prior
successful evidence, availability or value; it is not a silent fallback from a named Astra task.

#### Reasoning selection

| Effort | Use | Escalation boundary |
| --- | --- | --- |
| low | Deterministic extraction, short triage or lookup with explicit expected output | Not the default for cross-layer implementation or safety review |
| medium | Mechanical work, known transformations, bounded evidence checking | Escalate when the contract is unresolved rather than guessing |
| high | Normal engineering implementation and independent code review | Default for Astra features and critical engineering |
| xhigh | Hard root-cause analysis, competing architecture choices, cross-contract adversarial audit | Define the question, evidence matrix, checkpoint and exit first |
| max | Exceptional quality-first investigation where added exploration has a plausible material benefit | Requires explicit orchestrator approval and a finite experiment budget |

For a hard investigation, separate Astra/xhigh diagnosis from high-effort implementation once the
contract is settled. Do not run `max` for routine fixes, CI polling, receipts or repeated reviews.
No policy requires maximum effort solely because work is P0/P1, security-related or a milestone.

### 4. Worker slice routing

| Slice | Default route | Ownership |
| --- | --- | --- |
| GREEN | GPT-5.6 Luna / medium | Mechanical inventory, docs/copy, fixtures, predictable leaf changes |
| YELLOW | GPT-5.6 Terra / high | Accepted adapters, bounded UI/state implementation and regression tests |
| RED | GPT-6 Astra / high | Difficult integration, architecture, public contracts or independent review |
| CRITICAL | GPT-6 Astra / high | Data/security/concurrency boundaries with stronger evidence obligations |

The orchestrator may explicitly select Sol/high as an alternative. `xhigh` is assigned to a
particular unresolved slice, not inherited from its parent's severity. Default to one writer and
at most two read-only specialists per Issue. More writers require disjoint ownership and explicit
integration order; more helpers require a stated reason and budget. No recursive delegation.

Do not spawn several expensive reviewers to repeat the same audit. One read-only reviewer can use
an independent context with the same model; independence does not require a different model family.
If child model selection is not available or visible, do not claim economy savings. Prefer bounded
sequential work to unmeasured fan-out. At most one xhigh/max investigation is active by default;
parallel high-effort work on independent Issues needs disjoint worktrees and explicit coordination.

### 5. Actual-runtime honesty

Record agent ID, parent ID, role, requested model/effort, observed model/effort, inheritance and
route deviations. Use `not visible` when runtime identity is unavailable; that fact alone is not a
project blocker. Never infer execution identity from a requested route, a review command or a
subscription label. A GitHub review request does not prove the hosted review model or effort.

Check availability through the normal execution surface. If the selected route is unavailable,
use only an explicitly preapproved named alternative, record the reason, and retain the same
acceptance/review obligations; otherwise ask the external orchestrator to re-route. Do not retry an
unavailable route indefinitely, silently downgrade it, or equate two models by their names.
Observed deviation from an explicitly required route needs disposition before further mutation.

Optimize validated product value per total effort: context loading, implementation, validation,
review, failed attempts and rework all count. A larger allowance is capacity, not a spending target.
Record costs/tokens/credits only when observed; API prices do not measure subscription consumption.
After comparable completed tasks, use acceptance quality, rework and observed usage to adjust the
route. No benchmark framework or policy-prose parser is required to make that decision.

### 6. Task packets and bounded ownership

Use [`codex-task-packet-template.md`](./codex-task-packet-template.md). State the outcome once, link
the authoritative context, and separate **MUST**, **SHOULD**, and **DEFERRED**. Include owned and
forbidden scope, observable acceptance, relevant validation, remote authority and named fallback.
Do not copy an entire project history into every worker prompt.

Every nontrivial packet defines a first useful checkpoint, an effort/time budget appropriate to
its scope, a preservation/handoff location and a finite independent-review correction budget.
Unless a packet says otherwise, permit routine local test-driven iterations and one bounded
independent-review correction round inside the same contract. A second such round needs an
orchestrator decision. A local lint/test correction is not automatically a review-correction round.
No edit-count limit should force abandonment of an in-scope fix; no budget authorizes scope creep.

At a checkpoint, preserve a reviewable patch, runnable prototype, failing reproducer or concrete
finding. If progress stalls, preserve the state and report the missing decision instead of spending
the remaining budget on more prose. Audit tasks need evidence; prototype tasks need runnable work.
Changing files invalidates affected validation; run the full applicable gate on the final candidate,
not after every intermediate edit. Never carry old exact-head evidence onto changed bytes.

### 7. Validation ownership and evidence

Workers run focused validation for their assigned slice. The coordinator runs the integrated gate
and verifies the final diff. The external orchestrator checks exact head, current integration base
and merge readiness independently. Record command/check, observed result, relevant environment and
SHA; never promote a mock/unit result into packaged, live-service or production evidence.

Risk increases evidence rigor, not compulsory compute. For UI changes, test the real action-to-
worker contract and inspect actual rendered layouts. For SQLite, test real transactions, competing
connections, rollback and old supported databases. For source binding, test changes between review,
parse and persistence. Green unit counts alone do not prove those boundaries.

The workflow and packet select applicable CI/manual/security/performance/release gates. Report
unrun or inapplicable gates explicitly. An unrelated baseline failure needs separate evidence and
disposition; it is not silently repaired, waived or relabelled green in another Issue's PR.

### 8. Strong-model readiness gate

FEATURE / CROSS-LAYER and CRITICAL / MILESTONE PRs require a concise MUST-to-evidence matrix,
exact-head diff/scope inspection, an adversarial negative-path and cross-contract check, and a
representative falsifier that would fail for the broken behavior (or a precise non-applicability
reason). Record actionable findings and residual risks, not just aggregate test totals.

Astra/high is the default independent review route for these changes; bounded accepted changes may
use Sol/high. Use xhigh only for an unresolved difficult boundary. A milestone does not require
maximum compute. MICRO work does not inherit the full milestone evidence report.

### 9. Review and empirical routing feedback

All PRs retain focused validation, required GitHub Actions, GitHub Codex Review, independent
exact-head review and zero unresolved review threads. A changed head invalidates prior readiness;
a later blocking finding reopens it. Requested reviewer route and hosted runtime evidence remain
separate. Do not claim an exact reviewer model from `@codex review` alone.

Classify a new finding by consequence and reproduce it. A P1 requires explicit routing review,
not an automatic move to maximum effort. First decide whether the failure came from implementation,
a missing contract, an untested integration or the environment. Two repeated findings on the same
boundary trigger one bounded contract audit before another patch loop. The outcome may be a new
contract, smaller scope or a better test, not necessarily a stronger model.

Prefer one independent review on the final head over repeated same-context reviews. Corrections
need replacement exact-head evidence; a focused follow-up may reuse unaffected tests only where
the packet allows and the integration state is verified. A repeated post-Ready review request is
not a model-routing strategy. Existing Ready-boundary and later-blocker rules remain applicable.

### 10. Standing merge authorization

Codex coordinators and workers never merge their own PR.

The external project orchestrator has standing Product Owner authorization to squash-merge an
ordinary green PR only when all are observed:

- its own independent exact-head review concludes `READY FOR MERGE`;
- the reviewed head is unchanged;
- required CI and every applicable project-specific/manual/integration-result gate is
  terminal-green for that head/current base;
- zero review threads remain unresolved;
- no later blocker exists;
- GitHub reports the PR mergeable.

Update the branch when integration-result checks would otherwise be stale. Any changed head, base
movement that invalidates evidence, or later blocker revokes the earlier readiness conclusion.

Standing merge authorization does **not** include release promotion, migrations against real data,
deployment, destructive operations, secrets, billing, external publication, or other remote
product mutations. It does not authorize force-pushes, long-lived-ref changes, tag operations, or
closing an Issue before merge evidence. Each such action retains its separate explicit approval.

## Metroliza-specific binding

The rules below bind the reusable core to this repository. They must not be generalized into a
one-size-fits-all policy for other projects.

### 11. Sources, engineering, and branch contracts

When sources disagree, apply the hierarchy in
[`../project/README.md`](../project/README.md#source-of-truth-hierarchy). An accepted current
GitHub Issue/PR defines in-flight work; `docs/project/` owns current product, architecture, roadmap,
and delivery policy; `docs/release_checks/` owns release evidence and promotion decisions; and the
code, tests, configuration, `README.md`, and `CONTRIBUTING.md` remain binding executable/build
contracts. Chat, memory, unmerged branches, and historical documents are not durable authority.

Metroliza-specific contracts are:

- `develop` is the canonical integration base and target for normal Issue work. `master` is the
  production/history anchor; `release/2026.06-rc2` is frozen and `rc2` is transition/reference only.
- GitHub Issues and repository documents are durable truth; chat and memory are working context.
- `src/metroliza`/`metroliza.*` is canonical and `modules.*` is compatibility-only.
- Preserve local-first behavior, SQLite atomic transactions/publication and deterministic cleanup,
  bounded/cache-first processing, offline dashboards, and last-complete-output safety.
- Native acceleration remains optional. Python is the behavioral reference; parity includes normal,
  warning, failure, cancellation, fallback, packaging, and representative performance behavior.
- Preserve supported packaged Windows behavior and distinguish automated Windows core checks from
  real packaged/clean-machine evidence.
- Treat customer/supplier reports, measurement geometry/traceability, production databases and
  extracts, credentials, keys, and unredacted diagnostics as confidential.
- Do not claim test, CI, benchmark, packaging, merge, release, or remote-operation success without
  direct observation.
- Dependabot default-branch activation remains separately owned by
  [#966](https://github.com/hexafe/metroliza/issues/966); this orchestration policy neither
  implements nor authorizes it.

Follow the detailed architecture, compatibility, data-integrity, security, and release contracts in
[`../project/architecture.md`](../project/architecture.md),
[`../project/development_workflow.md`](../project/development_workflow.md), and
[`../release_checks/branching_strategy.md`](../release_checks/branching_strategy.md) instead of
duplicating them here.

#### Metroliza evidence binding

Use the validation tiers in
[`../project/development_workflow.md`](../project/development_workflow.md#6-validation-tiers). The
following gates are conditional on the changed contract rather than boilerplate claims:

| Impact | Required Metroliza evidence when applicable |
| --- | --- |
| Documentation/policy | Markdown links and indexes, policy consistency, release hygiene, `git diff --check`, focused policy tests |
| Normal CI | Required GitHub Actions terminal-green for the exact head/current integration result |
| Packaged Windows | Windows core/packaging checks plus real packaged or clean-machine evidence when the acceptance criterion requires it |
| Native/Rust | Locked build/tests, Python reference parity including failure/cancel/fallback behavior, packaging proof, representative benchmark, rollback |
| Performance | Representative benchmark command, baseline and environment; never extrapolate from a microbenchmark |
| Database/SQLite | Transaction/atomicity, rollback, migration/idempotence, concurrency, cleanup, and data-integrity proof appropriate to the change |
| Security/privacy | Secret and dependency checks plus negative-path/exposure review; sanitized evidence only |
| Release | Exact candidate automation plus all required manual Windows, Google, notices/legal, rollback, and release-owner evidence |

Passing ordinary CI does not satisfy an applicable Tier 4 packaged/manual/release gate. A
documentation-only PR reports product gates as not applicable instead of pretending to rerun them.
For Metroliza, the universal standing merge predicate therefore means required exact-head CI plus
every applicable Windows, native/Python parity, benchmark, SQLite/database, security,
documentation, manual, release, and current-`develop` integration gate.

### 12. TupTup-to-Metroliza adaptation record

The original adoption in #965 reviewed these exact TupTup blobs; this is historical provenance,
not the current named-model mapping:

- `hexafe/TupTup/AGENTS.md` — `2e2e5013decdf025e8e5d55ef354ddc2b2af9c5b`;
- `hexafe/TupTup/docs/engineering/codex-model-routing.md` —
  `2e49a655b0f8098abf498c7f2e5b795c0cf2f8a0`.

TupTup PR #31 and commit `18751a76d46f83597f6abf49fad509060abb1677` are supporting
provenance. The current Metroliza mapping is defined in sections 3–4 above.
This adoption does not bootstrap `hexafe/ai-dev-platform` or authorize a cross-repository mutation.

| Universal core retained | TupTup-specific rule excluded | Metroliza-specific rule added |
| --- | --- | --- |
| Product Owner → external orchestrator → coordinator → bounded worker authority chain | Next.js generated agent rules, TypeScript/App Router, and `pnpm` commands | Python/PyQt repository and canonical `src/metroliza` package contracts |
| Separate whole-PR coordinator and worker-slice routing | Supabase, RLS, private Storage, signed-URL, Auth, and `space` ownership rules | SQLite atomicity, idempotence, cleanup, migration, and last-complete-publication safety |
| Explicit model mapping and no silent coordinator downgrade | OpenAI/Mapy provider constraints and real-key-free TupTup build rules | Deterministic Python fallback and Python/Rust parity, locked native builds, benchmark and rollback gates |
| Explicit MUST/SHOULD/DEFERRED packets, bounded ownership, and stop conditions | GPX/source-bank/ZIP/import identity, importer dry-run, and two-run database invariants | Bounded/cache-first measurement processing and confidential supplier/customer data handling |
| Actual-runtime honesty and no unsupported token/cost/savings claims | Private-space/couple-focused catalogue, public-registration, SaaS, entitlements, and billing roadmap rules | Offline dashboards and packaged Windows/core-versus-clean-machine evidence distinction |
| Strong-model exact-head evidence, independent review, GitHub Codex Review, and zero threads | PWA/Play Store and Vercel staging/production policy | `develop` integration, frozen RC branch, `master` production anchor, #901 release evidence, and release reconciliation |
| Empirical P0/P1/P2 and correction-cycle feedback loop | Literal `CI`, `Database`, and `Security` checks against TupTup `main` as a universal gate | Applicable exact-head CI plus Windows/native/benchmark/SQLite/security/docs/release gates against Metroliza's current base |
| Narrow standing squash-merge authorization plus explicit remote/destructive exclusions | Supabase/import-specific remote exclusions as if shared by every repository | Real-data migration, release promotion, deployment/publication, long-lived refs, and tag changes remain separately gated |

No TupTup product rule may leak into Metroliza, and no Metroliza data, Windows, native, branch or
release rule may be generalized as a universal requirement for other repositories.

### 13. Completion standard

Use [`pr-routing-report-template.md`](./pr-routing-report-template.md) for the durable PR record.
Completion means the approved outcome is proven at the exact head: authorized scope, acceptance,
applicable validation, current integration evidence, review/thread state, runtime honesty,
deferrals and remote-operation status are recorded. A checkpoint or Draft PR is not merge readiness.

## Official sources

1. [GPT-6 Astra model and supported efforts](https://developers.openai.com/api/docs/models/gpt-6-astra)
2. [GPT-5.6 and GPT-6 Pro in ChatGPT](https://help.openai.com/en/articles/20001354-gpt-56-and-gpt-6-pro-in-chatgpt)
3. [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
4. [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
5. [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
6. [ChatGPT Work and Codex: availability and usage](https://help.openai.com/en/articles/20001275)
