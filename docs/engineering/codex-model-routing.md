# Codex orchestration and model-routing playbook

Status: Active supporting engineering policy
Owner: Product/architecture maintainer
Last reviewed: 2026-08-31

This playbook expands the concise repository rules in [`../../AGENTS.md`](../../AGENTS.md). It
defines a reusable orchestration core, then binds that core to Metroliza's engineering and evidence
contracts. It does not replace the active Issue, product specification, architecture, development
workflow, branch/release policy, or a separately required approval.

## Universal orchestration core

### 1. Authority

The authority chain is:

1. **Product Owner** — owns product direction and approval for separately gated remote or
   destructive decisions.
2. **External project orchestrator** — owns the Issue/specification, task packet, whole-PR scope,
   routing selection, independent exact-head review, and merge decision.
3. **Codex coordinator** — owns bounded execution, useful decomposition, worker integration,
   validation, an internal exact-head readiness audit, and PR preparation.
4. **Workers** — own only the files, symbols, validation, and operations explicitly assigned in a
   bounded slice.

The external orchestrator's independent exact-head merge review is distinct from the coordinator's
internal diff/readiness audit. Neither role may treat the other role's unobserved work as evidence.
Workers cannot override the task packet or sources of truth.

The task packet is the active scope boundary. A coordinator or worker must not reopen product
strategy, broaden the roadmap, or invent missing architecture, security, privacy, data-ownership,
release, or remote-operation authority. A contradiction or missing authority is a stop condition.

### 2. Two independent, smallest-sufficient routing decisions

Every nontrivial PR has two independent classifications:

1. **Whole-task coordinator class**, selected from the bounded contract, unresolved decisions,
   consequence, and acceptance burden.
2. **Worker slice route**, selected separately for each explicitly owned slice when delegation is
   useful.

The highest-risk worker does not automatically set the coordinator route, and a coordinator does
not automatically pass its route to every worker. Apply an early-exit test before dispatch: if a
smaller route can satisfy the bounded contract and evidence burden, the larger route is not
admitted. File count and severity labels are review signals, not substitutes for this semantic
test.

An externally selected route cannot be silently downgraded, upgraded, inherited, retried through a
fallback, or substituted. If the requested route is unavailable or live evidence changes the
classification, stop and obtain an explicit external-orchestrator decision before dispatching a
different model or reasoning level.

### 3. Canonical normal coordinator routes

Capability-class wording remains useful when named models change. Until an explicit policy update,
this is the repository's one canonical normal-route table:

| Work class | Coordinator | Reasoning | Bounded-contract test |
| --- | --- | --- | --- |
| MECHANICAL / RECOVERY / INVENTORY | GPT-5.6 Luna | Medium | Extract, preserve, inventory, or make a predictable correction without opening a product or architecture decision |
| STANDARD / BOUNDED PATCH / TEST REPAIR / AUDIT FINALIZATION | GPT-5.6 Terra | High | Implement or finalize one accepted seam with bounded ownership and deterministic evidence |
| HIGH / CROSS-LAYER / P0-P1 WITH AN ACCEPTED CONTRACT | GPT-5.6 Sol | High | Integrate difficult or cross-layer behavior, including a high-severity fix whose product and architecture contract is already accepted |

Mechanical includes metadata checks, report extraction, recovery inventory, deterministic status
normalization, and narrow edits whose contract is fully known. Stop when discovery opens a new
boundary or decision.

Standard includes normal implementation, bounded patches, accepted adapters, focused test repair,
and finishing an audit from preserved evidence. It does not own unresolved product, architecture,
safety, migration, destructive, or remote-operation decisions.

High includes difficult integration, new cross-layer contracts, security/privacy or data-integrity
implementation, and P0/P1 fixes after the relevant contract is accepted. Strong validation and
independent review remain mandatory where consequence requires them; severity does not change the
reasoning route by itself.

### 4. Ultra admission contract

Ultra may be requested only when **all five** conditions are true:

1. A material product, architecture, safety, or milestone decision remains genuinely unresolved
   across multiple subsystems.
2. The wrong decision creates high-consequence or long-lived lock-in.
3. The task primarily requires synthesis, adversarial reasoning, or decision design beyond a
   bounded GPT-5.6 Sol / High implementation.
4. The result still has one primary Issue and one coherent artifact, proposal, or PR.
5. A written stop, durable-checkpoint, minion-ownership, and handoff plan exists before work starts.

If any condition is false, use GPT-5.6 Sol / High or a smaller normal route. `CRITICAL`,
`MILESTONE`, P0, P1, release, migration, remote, destructive, security, or maximum worker risk
never admits Ultra alone. Ultra also requires explicit external-orchestrator authorization and a
written rationale naming the unresolved decision and the five satisfied conditions.

Ultra is for exceptional synthesis or adversarial decision work, not a substitute for smaller
scope, accepted contracts, durable checkpoints, or independent review. A bounded implementation
inside a critical program stays on its smallest sufficient normal route.

### 5. Coordinator and minion governance

Use one write coordinator by default. A second writer is permitted only when the external
orchestrator explicitly authorizes it, owned paths and symbols are completely disjoint, and the
first writer's valuable state already has a durable content-addressed checkpoint. No agent may
hold overlapping write ownership, even sequentially, without a recorded handoff and refreshed
scope.

Minions are read-only by default. A task packet sets a finite maximum, stable child identities,
exact sources or paths, one bounded responsibility per minion, and a no-mutation rule. If a minion
must write, it becomes an explicitly authorized additional writer under the stricter rule above.
Each minion uses the smallest sufficient route for its own slice: GPT-5.6 Luna / Medium for
mechanical evidence, GPT-5.6 Terra / High for bounded specialist analysis, and GPT-5.6 Sol / High
for difficult cross-layer or adversarial analysis. Minions never inherit Ultra merely from the
coordinator or from one maximum-risk slice.

Delegation is an ownership and independent-context tool, not a ritual. Skip it when startup and
context-loading cost exceeds the bounded benefit. One coordinator integrates all receipts and owns
the final scope, classification, exact-head evidence, and handoff.

### 6. Actual-runtime honesty and route deviations

Pre-dispatch records the requested model and reasoning. Post-execution records only observed
runtime evidence:

- requested and actual coordinator model/reasoning;
- requested and actual worker model/reasoning;
- every route deviation, its approval, and its evidence.

When model or reasoning identity is unavailable, report `not visible`. Never fabricate or infer a
model, reasoning mode, token/credit usage, latency, cost, or savings. Do not blame a named model
when runtime identity was hidden; distinguish Product Owner feedback from repository-observable
delivery outcomes.

No silent downgrade, fallback, retry, inheritance, or substitution is allowed. Runtime inability
to honor a requested route is a stop/escalation condition, not permission to choose a nearby route.
The optimization goal is the lowest reasonable total effort to a correct durable handoff, including
context loading, failed attempts, correction cycles, CI reruns, review, and rework.

### 7. Task packets, identity, and bounded ownership

Every nontrivial task packet uses the
[`codex-task-packet-template.md`](./codex-task-packet-template.md) and distinguishes:

- **MUST** — merge-blocking requirements and invariants;
- **SHOULD** — expected improvements that must remain inside approved scope;
- **DEFERRED** — explicitly forbidden or later work.

Every coordinator and minion records `AGENT_ID`, `PARENT_AGENT_ID`, Issue, lane, phase, authorized
base commit and tree, branch or `READ-ONLY`, requested route, and actual runtime visibility. The
packet also states the exact objective, routing rationale and early-exit result, owned files and
symbols, read/write authority, forbidden surfaces and operations, preserved contracts, acceptance,
validation slices, stop conditions, checkpoint plan, receipt plan, and remote-operation policy.

Orchestration never creates an autonomous unbounded loop. Every participant stays inside a finite
packet and exact ownership. Workers and coordinators do not silently promote SHOULD or DEFERRED
items. Prefer one durable/public contract, one primary runtime concern, and one coherent outcome per
PR; portfolio coordination may sequence multiple Issues but does not merge their write ownership.

### 8. Durable checkpoints, restartable validation, and receipts

Before a long full-suite, coverage, compatibility, fuzz/mutation, or multi-review stage, preserve
the current valuable bytes in a remote, content-addressed checkpoint. Record the branch/ref, commit
and tree SHAs, changed paths, content hashes where useful, completed gates, remaining gates, and
authorized next operation. A local commit that is not durably available to the next coordinator is
not sufficient.

No sole valuable copy may remain in `/tmp`, an ephemeral worker workspace, an untracked file, or a
chat transcript through multiple stages. Temporary artifacts may support a gate only when their
durable receipt records how to reproduce them and no unique implementation or decision exists only
there.

A preservation checkpoint must say that it is preservation only and is **not parked, not Ready,
and not complete**. It does not satisfy final validation, review, CI, parking, or merge gates.

Partition long validation into deterministic, restartable, bounded slices. Each slice emits a
machine-readable receipt containing at least agent identity, exact commit/tree, command or check,
environment/fixture, start/end or duration evidence when observed, result/exit status, output or
artifact hash/location, and remaining work. One coordinator audits and integrates the receipts.
The PR report records elapsed time when observed, correction cycles, and durable outputs without
inventing token or monetary cost.

### 9. Validation, exact-head review, and CI truthfulness

Minions run only assigned read-only inspection or focused validation and return sanitized receipts.
The coordinator runs the integrated local gate, checks the exact diff and scope, and freezes the
final head before independent review. The external orchestrator independently verifies that exact
head and the current merge state.

Evidence records the exact command or GitHub check, observed outcome, relevant environment or
fixture, and commit SHA. Never turn unit or mocked evidence into a manual, packaged, live-service,
or production claim. Report unrelated failures without silently repairing another Issue's scope.

Automatic Actions, manually dispatched Actions, skipped jobs, cancelled jobs, unavailable CI, and
infrastructure-blocked CI are distinct states. Only an observed applicable success is green; a
skipped, unavailable, infrastructure-blocked, pending, cancelled, or unrun check is never silently
counted as success. Passing aggregate automation never substitutes for an applicable manual gate.

Before external review, high/cross-layer and high-consequence PRs provide a MUST-to-evidence
matrix, exact-head scope review, adversarial gap hunt, representative falsifier where applicable,
P0/P1/P2 findings, correction-cycle count, routing adequacy, durable checkpoint and receipt
evidence, and actual runtime identity or `not visible`.

Use a sufficiently independent, smallest-sufficient review route. An Ultra-authored policy or
decision PR normally receives GPT-5.6 Sol / High review; a ceremonial second Ultra review adds no
evidence. Any changed head invalidates earlier exact-head review and starts a new review cycle.

Changing a PR from Draft to Ready creates a separate inspection boundary. Before merge, wait for
and inspect every Ready-triggered review, all comments newer than the transition, and every review
thread. Record the transition time, inspection cutoff, result, and unresolved-thread count. Never
replace an absent Ready-triggered review with an unapproved duplicate manual trigger.

### 10. Routing feedback and standing merge authorization

For each nontrivial PR, record actionable P0/P1/P2 findings, correction cycles after readiness was
first claimed, durable outputs, elapsed time when observed, whether the route proved adequate, and
the recommended route for the next materially similar task. A post-readiness P1 requires explicit
routing review, but no finding or repeated cycle automatically upgrades the next task: reapply the
normal-route tests and, for Ultra, all five admission conditions.

Prefer one strong independent reviewer over repetitive same-context reviews. Add reviewers for
disjoint boundaries, not prestige. A focused follow-up may review a changed commit only after
confirming the current head, scope, and integration state.

Codex coordinators and workers never merge their own PR. The external project orchestrator has
standing Product Owner authorization to squash-merge an ordinary green PR only when all are
observed:

- its own independent exact-head review concludes `READY FOR MERGE`;
- the reviewed head is unchanged;
- required CI and every applicable project-specific/manual/integration-result gate is
  terminal-green for that head and current base;
- the Draft-to-Ready inspection boundary, when used, is complete;
- zero review threads remain unresolved;
- no later blocker exists;
- GitHub reports the PR mergeable.

Update the branch when integration-result checks would otherwise be stale. Any changed head, base
movement that invalidates evidence, later blocker, or newer uninspected review activity revokes the
earlier readiness conclusion.

Standing merge authorization does **not** include release promotion, migrations against real data,
deployment, destructive operations, secrets, billing, external publication, or other remote
product mutations. It does not authorize force-pushes, long-lived-ref changes, tag operations, or
closing an Issue before merge evidence. Each such action retains separate explicit approval.

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

Current accepted TupTup policy was reviewed at the two exact blobs recorded by #965:

- `hexafe/TupTup/AGENTS.md` — `2e2e5013decdf025e8e5d55ef354ddc2b2af9c5b`;
- `hexafe/TupTup/docs/engineering/codex-model-routing.md` —
  `2e49a655b0f8098abf498c7f2e5b795c0cf2f8a0`.

TupTup PR #31 and commit `18751a76d46f83597f6abf49fad509060abb1677` are supporting
provenance; the accepted current files are authoritative.
This adoption documents the reusable core; it does not bootstrap `hexafe/ai-dev-platform`, add
runtime/schema tooling, or authorize a cross-repository mutation.

| Universal core retained | TupTup-specific rule excluded | Metroliza-specific rule added |
| --- | --- | --- |
| Product Owner → external orchestrator → coordinator → bounded worker authority chain | Next.js generated agent rules, TypeScript/App Router, and `pnpm` commands | Python/PyQt repository and canonical `src/metroliza` package contracts |
| Separate whole-PR coordinator and worker-slice routing | Supabase, RLS, private Storage, signed-URL, Auth, and `space` ownership rules | SQLite atomicity, idempotence, cleanup, migration, and last-complete-publication safety |
| Accepted Luna/Terra/Sol mapping and no silent coordinator downgrade | OpenAI/Mapy provider constraints and real-key-free TupTup build rules | Deterministic Python fallback and Python/Rust parity, locked native builds, benchmark and rollback gates |
| Explicit MUST/SHOULD/DEFERRED packets, bounded ownership, and stop conditions | GPX/source-bank/ZIP/import identity, importer dry-run, and two-run database invariants | Bounded/cache-first measurement processing and confidential supplier/customer data handling |
| Actual-runtime honesty and no unsupported token/cost/savings claims | Private-space/couple-focused catalogue, public-registration, SaaS, entitlements, and billing roadmap rules | Offline dashboards and packaged Windows/core-versus-clean-machine evidence distinction |
| Strong-model exact-head evidence, independent review, GitHub Codex Review, and zero threads | PWA/Play Store and Vercel staging/production policy | `develop` integration, frozen RC branch, `master` production anchor, #901 release evidence, and release reconciliation |
| Empirical P0/P1/P2 and correction-cycle feedback loop | Literal `CI`, `Database`, and `Security` checks against TupTup `main` as a universal gate | Applicable exact-head CI plus Windows/native/benchmark/SQLite/security/docs/release gates against Metroliza's current base |
| Narrow standing squash-merge authorization plus explicit remote/destructive exclusions | Supabase/import-specific remote exclusions as if shared by every repository | Real-data migration, release promotion, deployment/publication, long-lived refs, and tag changes remain separately gated |

The adversarial adaptation rule is bidirectional: no TupTup product rule may leak into Metroliza,
and no Metroliza architecture, data, Windows, native, branch, or release rule may be generalized as
a universal requirement for other repositories.

### 13. Completion standard

Use [`pr-routing-report-template.md`](./pr-routing-report-template.md) for the durable PR record.
Completion means the approved current outcome is proven at the exact head: authorized scope,
acceptance, local validation, applicable CI/manual gates, document consistency, review findings,
threads, runtime honesty, deferrals, and remote-operation status are all recorded. The coordinator
stops rather than inventing missing authority or evidence.
