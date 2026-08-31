# Codex task-packet template

Status: Active template
Owner: Product/architecture maintainer
Last reviewed: 2026-08-31

Use this template for every nontrivial Codex coordinator task and every delegated slice. Delete
instructional comments, replace every `<placeholder>`, and keep explicit `none` or `not applicable`
entries where silence would be ambiguous. The policy behind the template is
[`codex-model-routing.md`](./codex-model-routing.md).

## Pre-dispatch packet

```markdown
# <Issue/task number> — <short outcome>

## Agent identity

AGENT_ID: <stable coordinator or worker ID>
PARENT_AGENT_ID: <stable parent ID or NONE>
ISSUE: #<number>
LANE: <one bounded lane>
PHASE: <planning / implementation / validation / review / recovery>
AUTHORIZED_BASE: <branch>@<40-character commit SHA>
AUTHORIZED_TREE: <40-character tree SHA>
BRANCH: <exact branch or READ-ONLY>
REQUESTED_MODEL: <model or stable capability class>
REQUESTED_REASONING: <mode>

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

- Class: MECHANICAL / RECOVERY / INVENTORY | STANDARD / BOUNDED PATCH / TEST REPAIR / AUDIT FINALIZATION | HIGH / CROSS-LAYER / P0-P1 WITH AN ACCEPTED CONTRACT | ULTRA EXCEPTION
- Requested coordinator: <model or stable capability class>
- Requested reasoning: <mode or not specified>
- Routing rationale: <bounded contract, unresolved decisions, consequence, and evidence burden>
- Smaller sufficient route rejected because: <reason, or none — use the smaller route>
- Silent downgrade, fallback, inheritance, retry, or substitution allowed: no
- Route deviation authority: <external-orchestrator approval or none>

### Ultra admission — complete only for an Ultra exception

- Explicit external-orchestrator authorization: <URL/comment or not admitted>
- [ ] A material product, architecture, safety, or milestone decision remains genuinely unresolved
      across multiple subsystems.
- [ ] A wrong decision creates high-consequence or long-lived lock-in.
- [ ] The task primarily requires synthesis, adversarial reasoning, or decision design beyond a
      bounded GPT-5.6 Sol / High implementation.
- [ ] The result has one primary Issue and one coherent artifact, proposal, or PR.
- [ ] A written stop, durable-checkpoint, minion-ownership, and handoff plan exists before work.
- Admission rationale: <how all five are satisfied, or `not admitted`>

If any box is unchecked, use GPT-5.6 Sol / High or a smaller normal route. `CRITICAL`, `MILESTONE`,
P0, P1, release, migration, remote/destructive work, or maximum worker risk never admits Ultra
alone.

## Delegated slice routing

Read-only minions are the default. State a finite maximum and repeat one row per slice. Any writer
after the coordinator requires explicit authorization, completely disjoint paths/symbols, and a
durable checkpoint first.

- Maximum minions: <integer>
- Write coordinators: <one by default; authorized exception and evidence if more>

| AGENT_ID | PARENT_AGENT_ID | Slice | Access | Planned route | Exact owned sources/paths/symbols | Why delegate / why not |
| --- | --- | --- | --- | --- | --- | --- |
| <child ID> | <parent ID> | <one bounded concern> | READ-ONLY / authorized writer | <model + reasoning> | <non-overlapping ownership> | <independent context/value or startup-cost reason> |

No worker inherits the coordinator route or maximum slice risk automatically. Each uses the
smallest sufficient route for its own bounded contract.

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
- [ ] Worker ownership is bounded, read-only by default, and non-overlapping.
- [ ] Required durable checkpoint and restartable validation receipts exist.
- [ ] No unsupported test, CI, benchmark, review, merge, release, cost, or remote-action claim.

## Focused and integrated validation

Split long work into deterministic, restartable slices. Each completed slice produces a
machine-readable receipt tied to the exact commit/tree.

| Slice/gate | Exact command/check | Expected evidence | Owner | Receipt destination | Applicability |
| --- | --- | --- | --- | --- | --- |
| Focused | `<command>` | <observable output> | <worker/coordinator> | <durable receipt/comment/artifact> | required |
| Integration | `<command>` | <observable output> | coordinator | <durable receipt> | required |
| Exact-head CI | <workflow/check names> | observed status + run URL/ID + head SHA | coordinator/orchestrator | <PR report> | <required/n/a> |
| Windows packaged | <check/manual procedure> | <artifact/clean-machine evidence> | <owner> | <receipt> | <reason or n/a> |
| Native/Python parity | <check/benchmark> | <parity/fallback/rollback result> | <owner> | <receipt> | <reason or n/a> |
| Database/SQLite | <check/migration proof> | <atomicity/integrity/rollback result> | <owner> | <receipt> | <reason or n/a> |
| Security/privacy | <check/adversarial review> | <negative-path/sanitization result> | <owner> | <receipt> | <reason or n/a> |

Receipt schema: `agent_id`, `parent_agent_id`, `head_sha`, `tree_sha`, `command_or_check`,
`environment_or_fixture`, observed timing when available, `result`, `exit_status`,
`artifact_or_output_hash`, and `remaining_work`.

## Durable checkpoint and handoff plan

- Trigger before long full-suite/coverage/compatibility/fuzz/mutation/multi-review work: <stage>
- Durable ref, commit, and tree: <planned remote checkpoint>
- Changed-path/content-hash evidence: <plan>
- Preservation label: `PRESERVATION ONLY — NOT PARKED / NOT READY / NOT COMPLETE`
- Sole valuable copy in `/tmp` or another ephemeral workspace: forbidden
- Completed/remaining-gate receipt location: <durable location>
- Next authorized operation and handoff owner: <operation / AGENT_ID>

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

- AGENT_ID: <stable identity>
- PARENT_AGENT_ID: <stable parent or NONE>
- Issue/lane/phase: <exact values>
- Starting base/SHA: <branch> @ <full SHA>
- Authorized tree: <full tree SHA>
- Ending head SHA: <full SHA or uncommitted>
- Ending tree SHA: <full tree SHA or uncommitted>
- Requested model/reasoning: <requested route>
- Actual runtime model: <observed model or not visible>
- Actual reasoning mode: <observed mode or not visible>
- Route deviations/fallback/substitution: <none or explicit approval and evidence>
- Routing rationale and smaller-route early-exit result: <evidence>
- Changed ownership: <exact paths/symbols>
- Scope check: <clean or exact deviation>

### Worker ownership and receipts

| AGENT_ID | Access | Exact ownership | Requested route | Actual route | Receipt/result |
| --- | --- | --- | --- | --- | --- |
| <ID> | READ-ONLY / authorized writer | <sources/paths/symbols> | <model/reasoning> | <observed or not visible> | <durable evidence> |

No overlapping write ownership: <confirmed or blocker>

### Durable checkpoints

| Purpose/status | Ref/commit/tree | Paths/content hashes | Completed gates | Remaining gates |
| --- | --- | --- | --- | --- |
| <preservation/final> | <durable evidence> | <evidence> | <bounded receipts> | <exact list> |

Sole valuable copy in `/tmp` or ephemeral storage: no | <blocker and recovery location>

### MUST evidence

| MUST | Evidence | Result |
| --- | --- | --- |
| <requirement> | <diff location, command, run, or review> | PASS / FAIL / BLOCKED |

### Validation executed

| Command/check | Exact outcome | Environment/fixture | Head SHA |
| --- | --- | --- | --- |
| `<command>` | <result/count/conclusion> | <relevant context> | <SHA> |

Machine-readable receipt evidence: <durable locations/hashes and audit result>

### Findings and corrections

- P0: <none or actionable finding>
- P1: <none or actionable finding>
- P2: <none or actionable finding>
- Correction cycles after readiness: <integer>
- Unresolved risk/blocker: <none or concise evidence>

### Routing feedback

- Coordinator class adequate: yes | no | not yet known
- Next materially similar task: <recommended class/model/reasoning and why>

### Draft-to-Ready review inspection

- Draft-to-Ready transition: <timestamp or not performed>
- Ready-triggered review observed/result: <exact event or none observed after bounded wait>
- All newer comments inspected through: <timestamp>
- Every review thread inspected / unresolved count: <result / integer>

### Remote-operation ledger

- Performed: <exact allowed operations or none>
- Not performed: <forbidden/destructive operations explicitly confirmed absent>
- Approval used: <source or none>
```

The coordinator integrates slice handoffs into the
[`pr-routing-report-template.md`](./pr-routing-report-template.md), reruns the final applicable
gates, and records the exact final head. A worker handoff is evidence input, not merge readiness.
