# Metroliza repository instructions

## Sources and continuity

Read the active Issue/packet and relevant live code/CI. Use [project hierarchy](docs/project/README.md),
[architecture](docs/project/architecture.md), [development workflow](docs/project/development_workflow.md)
and [release rules](docs/release_checks/branching_strategy.md) for their boundaries.
The [playbook](docs/engineering/codex-model-routing.md) owns model allocation and delivery;
its research is optional reference, not compulsory context for every task.

**Revision 2026-09-23 applies to new or explicitly reconciled tasks only.** Do not switch,
interrupt, restart or re-budget running/paused executors. Existing WIN-DLV-1 retains its packet.
New models do not invalidate correct old evidence. No client configuration is installed here.

## Non-negotiable contracts

- Normal branches start from and target `develop`; never assume GitHub's default base.
- Remote branches are disposable execution refs, not evidence archives. Steady state is `master` + `develop` + an active `release/*` when needed + current PR heads.
- Do not create a remote branch per agent, reviewer, test attempt or checkpoint. Reuse the Issue branch for in-scope corrections.
- After merge, retire the source branch in the same closeout unless a named live PR/release/integration dependency still requires that exact ref; record its retirement trigger.
- Canonical package: `src/metroliza` / `metroliza.*`; `modules.*` is compatibility-only.
- Preserve local-first, SQLite atomicity, bounded processing, offline dashboards, deterministic
  cleanup, last-complete-output safety and deterministic Python fallbacks.
- Optional Rust/native work needs locked builds, Python parity including failure/cancel/fallback,
  representative performance, packaging proof and rollback.
- Source CI is not packaged Windows, clean-machine, live-service, legal or release-owner evidence.
- No credentials, customer/supplier measurements/reports, production extracts or raw diagnostics
  in chat/repository/artifacts. Never invent tests, CI, review, merge, runtime or usage evidence.

## Delivery and review

One coherent outcome per Issue/PR, with **MUST**, **SHOULD**, **DEFERRED**. Critical/major or violated
MUST: correct or safely contain now within authority. Every distinct defect gets a deduplicated
Issue. Lesser defects get evidence, impact, owner, workaround and target stabilization pack rather
than hijacking the feature. Bot priority, severity and merge/release disposition are separate.

Test affected behavior continuously. One complete affected-scope/direct-consumer review, grouped
blocking fixes, then delta verification. Extra rounds need a named material blocker or invalidated
assumption. No whole-repository audit per correction or full QA per helper. Reuse valid unchanged
evidence, but rebind the exact-head verdict. Keep required CI, GitHub Codex Review, independent
review and adjudicated/resolved threads. Self-check is not independent review.

Before each minor/major release, complete selected stabilization packs, inspect integrated changes
and execute applicable full regression and real Windows-package journeys. Remaining minor Issues
need explicit disposition. Never relabel FAIL, skipped or unknown as PASS.

## Routing and helpers

Separate risk, model, reasoning, delegation, speed and effective permissions. New-task defaults:

| Whole change | Coordinator | Independent scope reviewer |
| --- | --- | --- |
| MICRO code | GPT-6 Luna / high | GPT-6 Sol / medium |
| BOUNDED INTEGRATION | GPT-6 Sol / medium | GPT-6 Sol / high |
| FEATURE / CROSS-LAYER | GPT-6 Sol / medium; high for complex state/contracts | GPT-6 Sol / high |
| Settled bounded CRITICAL, only with all playbook exception conditions | GPT-6 Sol / high | GPT-6 Astra / high |
| Unresolved critical data/ownership/architecture or formal milestone | GPT-6 Astra / high | Independent Astra / high for critical acceptance |

Trivial non-code may use Luna low/medium. Verify `gpt-6-luna`, `gpt-6-sol`, `gpt-6-astra` availability;
`gpt-5.6-terra` is an explicit compatibility option, not GPT-6 Terra. No silent downgrade or default
Max/Ultra/Fast. Ultra is client-specific, not a universal API reasoning value.

Begin without implementation helpers; add one or two only for useful disjoint slices. Default
maximum is two additional contexts concurrently, including reviewer, not a staffing target.
GREEN code Luna/high; YELLOW Sol/medium; RED Sol/high; unresolved CRITICAL Astra/high.
Set model AND effort, ownership and focused checks. No recursive swarm, overlapping writers or
invented savings from expensive inheritance. Verify effective read-only permissions for reviewers;
a prompt is not enforcement. Observed identity/effort/usage is evidence or `not visible`.

## Authority and handoff

PO owns direction and separately gated operations. External orchestration owns packets, routing,
risk decisions and merge; coordinator owns tactical execution/integration and routine in-scope
corrections without per-file/per-commit PO approvals. Use the [packet](docs/engineering/codex-task-packet-template.md)
and [PR report](docs/engineering/pr-routing-report-template.md). GitHub is durable;
a remote archive pathname is not recovered code.

Only external orchestration squash-merges under the playbook's exact-head/current-base predicate:
all applicable gates, adjudicated/resolved threads, no later blocker and mergeability. Publication
for CI, merge and release are distinct. No author self-merge, force rewrite, release/tag/deploy,
live-data migration, secrets, billing or destructive authority follows from a model choice.
