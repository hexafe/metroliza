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

Classify the whole PR separately from any delegated slice:

| Whole-PR class | Default coordinator |
| --- | --- |
| MICRO | GPT-5.6 Luna / Medium |
| BOUNDED INTEGRATION | GPT-5.6 Terra / High |
| FEATURE / CROSS-LAYER | GPT-5.6 Sol / High |
| CRITICAL / MILESTONE | GPT-5.6 Sol / Ultra |

| Slice risk | Default worker |
| --- | --- |
| GREEN | GPT-5.6 Luna |
| YELLOW | GPT-5.6 Terra |
| RED | GPT-5.6 Sol |
| CRITICAL | GPT-5.6 Sol |

An externally selected coordinator cannot be silently downgraded. Escalate upward when evidence
requires it. Delegate only when bounded ownership or independent context improves the work; skip a
worker when startup and context-loading cost exceed the slice.

Every nontrivial packet uses explicit **MUST**, **SHOULD**, and **DEFERRED** sections and follows
[`docs/engineering/codex-task-packet-template.md`](docs/engineering/codex-task-packet-template.md).
Every nontrivial PR reports routing and evidence with
[`docs/engineering/pr-routing-report-template.md`](docs/engineering/pr-routing-report-template.md).

Codex coordinators and workers never merge their own PR. Standing merge authorization belongs only
to the external orchestrator and only after every gate in the expanded playbook is satisfied. It
never authorizes release promotion, real-data migration, deployment, destructive operations,
secrets, billing, external publication, or other remote product mutations.
