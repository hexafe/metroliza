# Codex orchestration and model-routing playbook

Status: Active supporting engineering policy
Owner: Product/architecture maintainer
Last reviewed: 2026-08-25

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

### 2. Two separate routing decisions

Every nontrivial PR has two independent classifications:

1. **Whole-PR coordinator class**, selected from the complete change, consequence, and acceptance
   burden.
2. **Worker slice risk**, selected separately for each bounded slice when delegation is useful.

A GREEN or YELLOW slice never downgrades a FEATURE / CROSS-LAYER or CRITICAL / MILESTONE
coordinator. The external orchestrator's requested coordinator cannot be silently downgraded.
Upward escalation is permitted when live evidence reveals greater risk or complexity. If a named
model is unavailable, use an equivalent or stronger capability only when the runtime allows it;
escalate before substituting a weaker coordinator.

### 3. Whole-PR coordinator classes

Capability-class wording is durable even when named models change. The named routes below are the
currently accepted mapping.

| Class | Default coordinator | Reasoning | Whole-change test |
| --- | --- | --- | --- |
| MICRO | GPT-5.6 Luna | Medium | One explicit correction, accepted contract, focused proof, no new boundary or milestone |
| BOUNDED INTEGRATION | GPT-5.6 Terra | High | One accepted seam across limited layers/files, without new architecture, security boundary, or phase closure |
| FEATURE / CROSS-LAYER | GPT-5.6 Sol | High | Normal feature, new durable contract, several layers, production/privacy boundary, or broad evidence |
| CRITICAL / MILESTONE | GPT-5.6 Sol | Ultra | Security/data-loss/destructive/remote boundary, migration, release/phase completion, or major durable decision |

#### MICRO

Use only when all relevant facts are already accepted: typically one to three files, one explicit
correction, no new public/runtime boundary, no security or privacy boundary, no milestone closure,
and focused validation can prove the outcome.

#### BOUNDED INTEGRATION

Use for one accepted seam, typically across two to six meaningful files or a small number of
symbols. It does not own new domain/security architecture, migrations, destructive/remote behavior,
formal phase closure, or broad requirement-to-evidence reconciliation.

#### FEATURE / CROSS-LAYER

Use for a normal product feature or new durable contract, runtime plus UI plus tests, several
application layers, a provider/privacy/build boundary, significant negative-path design, broad
integration evidence, or a defect likely to cause meaningful rework. Routine leaf slices may still
go to Luna or Terra while Sol retains whole-PR integration and evidence ownership.

#### CRITICAL / MILESTONE

Use for security, confidential-data exposure or data-loss risk, database schema/data migration,
concurrency or atomicity, secrets, release promotion/closure, packaged production decisions,
remote/destructive work, or a policy/architecture decision whose error would cause broad drift.
Ultra is high-compute coordination and review, not permission for a monolithic PR or for a remote
operation.

File count is a reviewability signal, not a substitute for semantics. Roughly eight meaningful
files, 600 net new lines, multiple independent outcomes, or overlapping central-file ownership
requires re-slicing or concise justification. Staying below a threshold never lowers a semantically
cross-layer or critical change.

### 4. Worker slice routing

| Slice risk | Default worker | Typical bounded ownership |
| --- | --- | --- |
| GREEN | GPT-5.6 Luna | Leaf UI/docs/copy, fixtures, mappings, predictable tests, mechanical refactors |
| YELLOW | GPT-5.6 Terra | Bounded integration, routing/state, accepted adapters, E2E/accessibility workflows |
| RED | GPT-5.6 Sol | Architecture, durable/public contracts, privacy/exposure boundaries, difficult integration or review |
| CRITICAL | GPT-5.6 Sol | Security, migrations, data integrity, concurrency, secrets, remote/database or destructive boundaries |

GREEN work stops on ambiguity and does not alter architecture or public/private boundaries. YELLOW
work integrates accepted contracts but escalates new ownership, security, privacy, or architecture
decisions. RED and CRITICAL work own difficult boundaries but still remain bounded by the packet.

Delegation is an ownership and context tool, not a ritual. Skip it when worker startup or
context-loading cost exceeds the work. Keep write ownership disjoint; never assign concurrent
workers to overlapping paths or symbols. If per-worker model selection is unavailable, prefer
sequential bounded work under the selected coordinator. Do not claim economy-model savings by
spawning inherited expensive agents.

### 5. Actual-runtime honesty

Pre-dispatch records the requested route. Post-execution records only observed runtime evidence:

- requested and actual coordinator model/reasoning;
- requested and actual worker model/reasoning, and inheritance when visible;
- routing deviations and their reason.

When model or reasoning identity is unavailable, report `not visible`. Never fabricate or infer a
model, reasoning mode, token/credit usage, latency, cost, or savings. Do not blame a named model
when runtime identity was hidden; distinguish model limits from oversized scope, ambiguous packets,
weak acceptance evidence, and integration failures.

The optimization goal is the lowest reasonable total effort to a correct merge. It includes
context loading, failed attempts, QA/CI reruns, review corrections, follow-up commits, and
architectural rework—not only the first execution.

### 6. Task packets and bounded ownership

Every nontrivial task packet uses the
[`codex-task-packet-template.md`](./codex-task-packet-template.md) and distinguishes:

- **MUST** — merge-blocking requirements and invariants;
- **SHOULD** — expected improvements that must remain inside approved scope;
- **DEFERRED** — explicitly forbidden or later work.

A packet also states the exact objective, whole-PR class/model/reasoning, delegated slice risk and
route, owned files/symbols, forbidden surfaces and operations, preserved contracts, observable
acceptance criteria, focused validation, stop/escalation conditions, and remote-operation policy.
Workers and coordinators do not silently promote SHOULD or DEFERRED items.

Orchestration never creates an autonomous unbounded agent loop. Every coordinator and worker stays
inside a finite packet, bounded ownership, explicit stop conditions, and the recorded authority for
local and remote operations.

Prefer one durable/public contract, one security boundary, one primary runtime concern, and one
product outcome per PR. Keep behavior changes separate from structural refactors and keep formal
release/phase closure separate from ordinary implementation when practical.

### 7. Validation ownership and evidence

Workers run only the focused validation assigned to their slice and return sanitized evidence. The
coordinator runs the integrated local gate, checks the final diff and scope, and prepares exact-head
evidence. The external orchestrator independently verifies the exact PR head and merge state.

Evidence records the exact command or GitHub check, the observed outcome, relevant environment or
fixture, and the commit SHA. Never turn a mocked/unit result into a manual, packaged, live-service,
or production claim. An unrelated failing gate is reported and triaged, not silently repaired in
another Issue's PR.

Each repository's active workflow and task packet select the applicable focused, CI, integration,
manual, data, security, performance, packaging, and release gates. Passing an aggregate automated
suite never substitutes for an applicable manual or production claim. A gate that cannot apply is
reported as not applicable with a reason rather than presented as unrun success.

### 8. Strong-model readiness gate

Before external review, every FEATURE / CROSS-LAYER and CRITICAL / MILESTONE PR must provide:

1. a concise MUST-to-evidence matrix;
2. an exact-head diff and authorized-scope review;
3. an adversarial gap hunt covering negative paths, confidentiality/security, production or
   disabled behavior where applicable, source-of-truth consistency, and tests that could pass
   without proving the claimed invariant;
4. evidence that a representative broken behavior would fail acceptance validation, or a precise
   explanation of why that falsification is not applicable to a documentation-only contract;
5. actionable findings by severity and confirmation that no known risk is hidden by green
   aggregate results;
6. correction-cycle count, routing adequacy, and a recommendation for the next materially similar
   task;
7. actual model/reasoning evidence or `not visible`.

A formal milestone uses Ultra coordination or a separately justified Ultra exact-head review.
MICRO work does not inherit this full gate; BOUNDED INTEGRATION uses evidence appropriate to its
accepted seam.

### 9. Review and empirical routing feedback

All PRs retain focused validation, required GitHub Actions, GitHub Codex Review, an independent
exact-head review, and zero unresolved review threads. A changed head invalidates prior exact-head
readiness. A later blocking comment or newly discovered contradiction reopens readiness even if CI
is still green.

For each nontrivial PR, record:

- actionable P0/P1/P2 findings;
- correction cycles after readiness was first claimed;
- whether the coordinator class proved adequate;
- the recommended class for the next materially similar task.

Apply the feedback as follows:

- any P1 after readiness requires explicit routing review;
- a P2 or repeated correction cycle normally escalates the next similar task by one class when the
  higher class's semantic criteria apply;
- otherwise retain the class and strengthen model/reasoning or independent review; CRITICAL /
  MILESTONE is the ceiling;
- three materially similar clean PRs may justify considering one lower class;
- CRITICAL / MILESTONE is never automatically downgraded.

Prefer one strong independent reviewer over several repetitive same-context reviews. Add reviewers
for disjoint critical boundaries, not prestige. A focused follow-up may review the new commit and
previously accepted boundary after first confirming the current head and integration state.

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
