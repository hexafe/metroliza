# PR routing-report template

Status: Active template
Owner: Product/architecture maintainer
Last reviewed: 2026-09-05

Use the sections relevant to the change, replace placeholders and retain explicit unavailable or
inapplicable evidence. Keep the report proportionate: MICRO work does not need a milestone essay.
The [playbook](./codex-model-routing.md) owns routing; the
[task packet](./codex-task-packet-template.md) owns execution scope.

```markdown
## Outcome

<One user/engineering result and its value.>
Closes #<primary Issue> <!-- Use Refs instead if this PR is only a slice. -->

## Identity, scope and rollback

- Base / head / tree: <exact refs>
- Changed files/contracts: <bounded list>
- Explicit non-goals: <adjacent work not performed>
- Scope change authority: <none or decision URL>
- Main risk and rollback: <preserved data-safe route>

## Routing

- Agent / parent / role: <IDs; coordinator or read-only reviewer>
- Whole-PR class: MICRO | BOUNDED INTEGRATION | FEATURE / CROSS-LAYER | CRITICAL / MILESTONE
- Consequence and reasoning difficulty: <separate rationale>
- Execution surface / sign-in: <client or direct API; relevant access>
- Requested model / product control: <actual label; product control N/A for direct API>
- Request-level API effort / applied effort updates: <separate values when used; otherwise N/A>
- Actual model / effective effort / topology: <observed values or not visible>
- Fallback/deviation: <none or exact requested/observed change and authority>
- Why this route: <expected value; no unmeasured superiority/cost claim>
- Delegation: <none or bounded ownership reason>
- Checkpoint / effort budget outcome: <deliverable, spent budget if observed>

<!-- Optional: omit when these capabilities were not used or required. -->
- Capability use and availability: <context management, async, steering, effort updates, UI>
- Approved changes during execution: <packet/decision revision; effect on scope and effort>
- Pending-operation disposition: <completed / cancelled / preserved; stale results reconciled>
- Safety stop: <none or sanitized error/state and operator disposition; never auto-retried>

A selected Ultra label does not prove a helper count or API effort. After an effort update, the
response's request-level effort field does not establish the updated effective effort.

<!-- Only include worker rows for actual workers. -->
| Agent / parent | Role and ownership | Requested route | Observed route / inheritance | Evidence |
| --- | --- | --- | --- | --- |
| <IDs> | <disjoint slice / read-only review> | <model / effort> | <observed or not visible> | <result> |

## MUST-to-evidence matrix

| Requirement | Implementation evidence | Validation/falsifier | Result |
| --- | --- | --- | --- |
| <MUST> | <symbol/diff> | <command or exact-head check> | PASS / FAIL / BLOCKED |

Known gap hidden by aggregate results: <none or exact risk>.

## Validation

| Command/check | Result | Exact head / environment | Required/applicable reason |
| --- | --- | --- | --- |
| <focused/local/static> | <actual result> | <SHA and relevant environment> | <reason> |
| <CI workflow> | <run URL, terminal conclusion> | <head/current base> | <reason> |
| <conditional manual/package gate> | <actual artifact/procedure or not run> | <candidate> | <reason> |

- Integration-result/base currentness: <verified state>
- Local baseline failures: <none or exact failures, A/B evidence and separate disposition>
- Unrun gates: <not run; not green>
- Preserved contracts: <applicable canonical package, local-first/offline, SQLite atomicity,
  confidentiality, Python/native parity, Windows packaging, release and rollback evidence>

A local result is not hosted CI, and hosted CI is not packaged/manual evidence.

## Independent review and correction history

- Requested independent reviewer route: <model / effort>
- Actual independent reviewer model / effort: <observed or not visible>
- Review evidence: <URL, reviewed SHA, scope, result>
- Coordinator self-audit: <separate result; not the independent review>
- P0/P1/P2 findings: <none or each finding + evidence + disposition>
- Local test-driven iterations: <concise account; not review-round count>
- Independent-review correction rounds: <count and authority>
- Repeated same-boundary findings / contract audit: <none or decision>
- Later blocker: <none or exact evidence>

A requested route or GitHub review trigger does not identify the hosted runtime. A clear
reviewer outcome is still required even when the runtime identity is not visible.

## Readiness and remote operations

- GitHub Codex Review: <exact-head result or pending>
- External independent exact-head review: <result or pending>
- Required CI/manual gates: <terminal-green / blocked / pending>
- Unresolved review threads: <observed integer or not yet checked>
- Head unchanged since review: <yes/no>
- Current-base evidence and mergeability: <verified / pending>
- External orchestrator decision: READY FOR MERGE | NOT READY | pending
- Remote writes performed: <exact scoped operations>
- Excluded operations not performed: <force, unrelated refs, tags, release/deploy,
  real-data migration, destructive actions, billing/publication, etc.>

Codex coordinators and workers have not merged this PR. Only the authorized external
orchestrator may squash-merge after the playbook's full predicate is satisfied. No model
route or READY label authorizes release, destructive or other separately gated operations.

## Routing lesson

<Retain/change model or effort based on the actual failure class, acceptance quality and
rework. Token/credit/cost figures only if observed. State one lesson, not a new policy system.>
```

Do not mark READY while any applicable exact-head review, CI/manual result, thread count or
integration/mergeability gate is unknown. Changed head or invalidated base evidence revokes the
previous readiness conclusion. Keep remaining gaps visible; a checkpoint is not completion.
