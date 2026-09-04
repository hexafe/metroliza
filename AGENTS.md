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

Use these project defaults for new packets; the playbook owns availability and escalation details:

| Whole-PR class | Default coordinator |
| --- | --- |
| MICRO | GPT-5.6 Luna / medium |
| BOUNDED INTEGRATION | GPT-5.6 Terra / high |
| FEATURE / CROSS-LAYER | GPT-6 Astra / high |
| CRITICAL / MILESTONE | GPT-6 Astra / high |

Risk determines evidence and approval rigor, not automatic maximum reasoning. Use Astra `xhigh`
for a bounded unresolved architecture/root-cause audit; `max` needs an explicit benefit, budget,
checkpoint and exit condition. Historical `Ultra` is not an Astra effort value. GPT-6 Pro is the
ChatGPT product option, not a Codex model ID. GPT-5.6 Sol / high remains an explicitly selectable
complex-work/review alternative; no model or effort substitution may be silent.

Default to one writer per Issue and at most two bounded read-only helpers. Route leaf work to
Luna, accepted integrations to Terra, and difficult contracts to Astra; select reasoning for each
slice separately. No recursive delegation, overlapping writes, or automatic expensive-agent fan-out.
Skip delegation when its context/integration cost exceeds its value.

Every nontrivial packet uses explicit **MUST**, **SHOULD**, and **DEFERRED** sections and follows
[`docs/engineering/codex-task-packet-template.md`](docs/engineering/codex-task-packet-template.md).
Name each agent and its parent, outcome, route, ownership, checkpoint, finite review-correction
budget and allowed remote operations. Routine local test-driven iterations within that scope are
not new review-correction rounds. Stop for changed contracts/authority, not an arbitrary edit count.
Two repeated findings on the same boundary require a contract review, not an automatic compute
increase. Existing explicit packet limits and frozen PRs remain binding until separately refreshed.

Every nontrivial PR reports routing and evidence with
[`docs/engineering/pr-routing-report-template.md`](docs/engineering/pr-routing-report-template.md).
Requested and observed runtime identity are separate; `not visible` alone is not a blocker. Optimize
validated product value and total effort including rework, not consumption of an available allowance.

Codex coordinators and workers never merge their own PR. Standing merge authorization belongs only
to the external orchestrator and only after every gate in the expanded playbook is satisfied. It
never authorizes release promotion, real-data migration, deployment, destructive operations,
secrets, billing, external publication, or other remote product mutations.
