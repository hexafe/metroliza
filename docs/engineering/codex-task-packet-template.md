# Codex task-packet template

Status: Active template
Owner: Product/architecture maintainer
Last reviewed: 2026-08-25

Use this template for every nontrivial Codex coordinator task and every delegated slice. Delete
instructional comments, replace every `<placeholder>`, and keep explicit `none` or `not applicable`
entries where silence would be ambiguous. The policy behind the template is
[`codex-model-routing.md`](./codex-model-routing.md).

## Pre-dispatch packet

```markdown
# <Issue/task number> — <short outcome>

## Durable authority

- Repository: <owner/repository>
- Issue/specification: <URL and number>
- Accepted execution packet/comment: <URL or none>
- Canonical base and verified SHA: <branch> @ <full SHA>
- Target branch: <exact PR base>
- Proposed work branch: <short-lived branch>
- Sources of truth read: <exact files/URLs/refs>

## Exact objective

<One observable outcome. State what becomes true, not a broad activity.>

## Whole-PR routing

- Class: MICRO | BOUNDED INTEGRATION | FEATURE / CROSS-LAYER | CRITICAL / MILESTONE
- Requested coordinator: <model or stable capability class>
- Requested reasoning: <mode or not specified>
- Classification rationale: <semantic consequence and acceptance burden>
- Silent downgrade allowed: no
- Evidence-based upward escalation: allowed; record before broadening

## Delegated slice routing

<!-- Repeat this table row for each slice. Use one coordinator-only row if not delegating. -->

| Slice | Risk | Planned route | Reasoning | Owned responsibility | Why delegate / why not |
| --- | --- | --- | --- | --- | --- |
| <name> | GREEN / YELLOW / RED / CRITICAL | <model/capability> | <mode or n/a> | <one bounded concern> | <context/ownership value or startup-cost reason> |

## Owned scope

- Files: <exact paths>
- Symbols/contracts: <exact names or none>
- Expected final file set: <deterministic list>
- Allowed remote operations: <exact operations or none>

## Forbidden surfaces and operations

- Files/symbols: <adjacent paths or contracts that must not change>
- Behavior/configuration: <out-of-scope product or policy behavior>
- Local operations: <destructive, privileged, broad cleanup, or none>
- Remote operations: <merge, long-lived refs, tags, deploy/release/migrate/publish, etc.>

## MUST — merge-blocking requirements and invariants

1. <Requirement with a testable result.>
2. <Preserved invariant.>

## SHOULD — expected, scope-bounded improvements

1. <Improvement that must not broaden owned scope.>

## DEFERRED — explicitly forbidden or later work

1. <Later Issue/outcome or explicit non-goal.>

## Preserved contracts

- <Source of truth + exact contract that must remain true.>
- <Architecture/data/security/compatibility/release contract.>
- <Confidentiality and evidence boundary.>

## Acceptance criteria

- [ ] <Observable outcome mapped to a MUST.>
- [ ] Final diff contains only the authorized scope.
- [ ] Actual model/reasoning is observed or reported as `not visible`.
- [ ] No unsupported test, CI, benchmark, review, merge, release, cost, or remote-action claim.

## Focused and integrated validation

| Gate | Exact command/check | Expected evidence | Owner | Applicability |
| --- | --- | --- | --- | --- |
| Focused | `<command>` | <observable output> | <worker/coordinator> | required |
| Integration | `<command>` | <observable output> | coordinator | required |
| Exact-head CI | <workflow/check names> | terminal result + run URL/ID + head SHA | coordinator/orchestrator | <required/n/a> |
| Windows packaged | <check/manual procedure> | <artifact/clean-machine evidence> | <owner> | <reason or n/a> |
| Native/Python parity | <check/benchmark> | <parity/fallback/rollback result> | <owner> | <reason or n/a> |
| Database/SQLite | <check/migration proof> | <atomicity/integrity/rollback result> | <owner> | <reason or n/a> |
| Security/privacy | <check/adversarial review> | <negative-path/sanitization result> | <owner> | <reason or n/a> |

## Stop and escalate

Stop before broadening or mutating when:

- <a source-of-truth contradiction or missing product/architecture decision appears>;
- <the base/head or accepted input moves unexpectedly>;
- <ownership must cross a forbidden surface>;
- <a destructive, privileged, force, release, migration, publication, or unapproved remote action
  becomes necessary>;
- <validation cannot prove a MUST without redesigning scope>.

Escalation record must contain: evidence, affected MUST, safe state, options, recommended next
decision, and operations not performed.

## Remote-operation policy

- Standing authorization in this packet: <exact normal push/PR/review/CI operations or none>
- Separately approved operations: <exact operation + approval evidence or none>
- Always excluded: <merge by coordinator/worker and packet-specific excluded mutations>
- Secrets/credentials required: <no, or approved secure mechanism without values>
```

## Post-execution handoff

Complete this after implementation and focused validation. Do not replace missing evidence with an
inference.

```markdown
## Post-execution handoff — <slice/coordinator name>

- Starting base/SHA: <branch> @ <full SHA>
- Ending head SHA: <full SHA or uncommitted>
- Actual runtime model: <observed model or not visible>
- Actual reasoning mode: <observed mode or not visible>
- Inherited coordinator model: yes | no | not visible | not applicable
- Route deviations: <none or evidence and approval>
- Changed ownership: <exact paths/symbols>
- Scope check: <clean or exact deviation>

### MUST evidence

| MUST | Evidence | Result |
| --- | --- | --- |
| <requirement> | <diff location, command, run, or review> | PASS / FAIL / BLOCKED |

### Validation executed

| Command/check | Exact outcome | Environment/fixture | Head SHA |
| --- | --- | --- | --- |
| `<command>` | <result/count/conclusion> | <relevant context> | <SHA> |

### Findings and corrections

- P0: <none or actionable finding>
- P1: <none or actionable finding>
- P2: <none or actionable finding>
- Correction cycles after readiness: <integer>
- Unresolved risk/blocker: <none or concise evidence>

### Routing feedback

- Coordinator class adequate: yes | no | not yet known
- Next materially similar task: <recommended class/model/reasoning and why>

### Remote-operation ledger

- Performed: <exact allowed operations or none>
- Not performed: <forbidden/destructive operations explicitly confirmed absent>
- Approval used: <source or none>
```

The coordinator integrates slice handoffs into the
[`pr-routing-report-template.md`](./pr-routing-report-template.md), reruns the final applicable
gates, and records the exact final head. A worker handoff is evidence input, not merge readiness.
