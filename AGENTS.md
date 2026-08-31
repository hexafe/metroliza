# Metroliza repository instructions

## Sources of truth

1. The active GitHub Issue and its accepted execution packet define the current task.
2. [`docs/project/README.md`](docs/project/README.md) defines the project source hierarchy.
3. [`docs/project/architecture.md`](docs/project/architecture.md) owns architecture, data, native,
   compatibility, and security boundaries.
4. [`docs/project/development_workflow.md`](docs/project/development_workflow.md) and
   [`docs/release_checks/branching_strategy.md`](docs/release_checks/branching_strategy.md) own
   delivery, branch, validation, and release rules.
5. [`docs/engineering/codex-model-routing.md`](docs/engineering/codex-model-routing.md) is the
   expanded AI-orchestration and model-routing playbook.

Do not silently skip, broaden, or reinterpret a requirement. Record an approved deferral with its
reason, owner, target Issue or phase, and preserved seam.

## Metroliza contracts

- Start normal Issue work from `develop` and target `develop`; never rely on GitHub's default base.
- Use `src/metroliza` and `metroliza.*` as canonical. Treat `modules.*` as compatibility-only.
- Preserve local-first operation, SQLite atomicity, bounded processing, offline dashboards,
  deterministic cleanup, and deterministic Python fallbacks.
- Native/Rust paths remain optional and require Python parity, representative benchmarks, locked
  builds, packaging proof, explicit fallback behavior, and rollback.
- Preserve packaged Windows compatibility and keep CI evidence distinct from clean-machine,
  packaged, live-service, legal, and release-owner evidence.
- Keep credentials, customer/supplier reports, proprietary measurement data, production extracts,
  secrets, and unredacted diagnostics out of repository, chat, and PR artifacts.
- Never claim a test, CI run, benchmark, review, merge, release, model, reasoning mode, token count,
  cost, or remote action without observed evidence. Report unavailable runtime identity as
  `not visible`.

## AI orchestration

The Product Owner owns product direction and separately gated remote or destructive decisions. The
external project orchestrator owns the Issue/specification, task packet, whole-PR routing,
independent exact-head review, and merge decision. The Codex coordinator owns bounded execution,
integration, validation, its internal exact-head readiness audit, and PR preparation. Workers own
only their explicitly assigned slices.

Use the smallest sufficient route for the bounded contract. The canonical route table and the five
mandatory Ultra-admission conditions are in
[`docs/engineering/codex-model-routing.md`](docs/engineering/codex-model-routing.md):

- mechanical, recovery, and inventory work uses GPT-5.6 Luna / Medium;
- standard work, bounded patches, test repair, and audit finalization use GPT-5.6 Terra / High;
- high or cross-layer work and P0/P1 implementation with an accepted contract use GPT-5.6 Sol /
  High.

Criticality, a milestone label, P0/P1 severity, or one maximum-risk worker slice never admits or
forces Ultra by itself. Ultra requires explicit external-orchestrator authorization, a written
rationale, and all five admission conditions. Apply the early-exit test before dispatch: when a
smaller route can satisfy the bounded contract, the larger route is not admitted.

Use one write coordinator by default. A second writer requires explicit external-orchestrator
authorization, completely path-disjoint ownership, and a durable content-addressed checkpoint
first. Minions are read-only by default, use the smallest sufficient route for their own bounded
slice, and never receive overlapping paths or symbols. Every agent reports its stable identity,
parent identity, requested model/reasoning, and observed runtime model/reasoning; use `not visible`
when the latter is unavailable. Never silently downgrade, fall back, or substitute a model or
reasoning level.

Before long full-suite, coverage, compatibility, fuzz/mutation, or multi-review work, push a
durable content-addressed preservation checkpoint. Never leave the sole valuable copy in `/tmp` or
another ephemeral workspace. Label preservation as not parked, not Ready, and not complete; split
long validation into restartable bounded slices with machine-readable receipts.

Freeze the exact head before independent review. Report automatic Actions, skipped jobs,
unavailable checks, and infrastructure-blocked checks truthfully; only observed applicable success
is green. After changing a PR from Draft to Ready, inspect every Ready-triggered review, every newer
comment, and every review thread before merge.

Every nontrivial packet uses explicit **MUST**, **SHOULD**, and **DEFERRED** sections and follows
[`docs/engineering/codex-task-packet-template.md`](docs/engineering/codex-task-packet-template.md).
Every nontrivial PR reports routing and evidence with
[`docs/engineering/pr-routing-report-template.md`](docs/engineering/pr-routing-report-template.md).

Codex coordinators and workers never merge their own PR. Standing merge authorization belongs only
to the external orchestrator and only after every gate in the expanded playbook is satisfied. It
never authorizes release promotion, real-data migration, deployment, destructive operations,
secrets, billing, external publication, or other remote product mutations.
