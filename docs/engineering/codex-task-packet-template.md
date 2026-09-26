# Codex task-packet template

Reviewed: 2026-09-23. Refs #1061. Use for new or explicitly reconciled tasks only.
Keep one bounded outcome and the three priority sections; link the
[playbook](codex-model-routing.md) rather than copying global instructions.
A prompt is requested configuration, not proof that the client applied it.

```text
Issue / observable user outcome / target release:
Repository / verified base+head / owned branch and PR target:
Current contract and source paths actually read:
Active-packet continuity: new task OR explicit reconciliation link;
  settings, authority and spent budgets that must remain unchanged:

Whole-change risk and reason:
Coordinator: client/version/sign-in class; exact model ID; reasoning;
  standard/Fast; single-agent/delegation; effective permissions:
Independent reviewer: review risk; model+effort; no-write enforcement:
Settled-critical exception: not used OR evidence for all four playbook conditions:
Preauthorized escalation ceiling, trigger and affected question (or none):
Requested / configured / observed settings; unknown = not visible:

MUST — blocking behavior/invariants and observable acceptance:
SHOULD — useful improvements that remain inside this scope:
DEFERRED — explicit later work and forbidden scope:

Preserved contracts: canonical package, local-first, confidentiality,
  SQLite/last-complete-output, offline, Python/native, Windows as applicable:
Owned files/symbols and allowed related changes:
Forbidden surfaces; data/remote/destructive approval boundaries:
Rollback or safe recovery; applicability of clean-machine/manual acceptance:

Delegation: zero/one/two implementation helpers, justified by actual independence;
  helper name | slice risk | model+effort | owned symbols | focused checks.
Concurrency including reviewer; effective sandbox/tools after inheritance:
One integration writer owns shared workflow/metadata conflict resolution.

Positive user journey / negative, cancellation and data-safety cases:
Focused checks and owners:
Aggregate/current-base CI and specialized gates, where they run:
Review baseline; one scope review + one delta verification;
  explicit trigger/question for further review:
Reusable evidence with source/dependency/configuration bindings:
Resource budget: model/API or subscription visibility, runner time/per-job cap,
  aggregate attempts if explicitly required; historical spent amounts:
Publication for CI may precede complete QA only under this packet's authority.

Autonomy: ordinary in-domain fixes, fixtures and review corrections continue.
Escalate: actual missing product/security/ownership decision, unsupported tool/model,
  crossed authority, exhausted budget or unresolved consequential defect.
Normal authorized base updates require reconciliation, not automatic abandonment.
Defects: deduplicate Issue, severity/confidence/impact, affected MUST/gate,
  owner, workaround and target stabilization pack; no silent failed-gate waiver.

Allowed branch/push/PR/review/CI actions:
Forbidden: author self-merge, release/tag/deploy, paid or destructive operations,
  production/private data operations unless separately explicitly approved.
Handoff: exact source/evidence, delivered behavior, findings/dispositions,
  remaining risk and one next action. No automatic restart.
```

Helpers return focused results, not another full QA campaign. The coordinator binds one integrated
result; [PR readiness](pr-routing-report-template.md) is distinct from a helper's completion.
The external orchestrator verifies the final head and merge predicate. Neither a stronger model nor
a new task name resets evidence, grants permissions or qualifies a Windows artifact.
