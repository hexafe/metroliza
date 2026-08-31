# PR routing-report template

Status: Active template
Owner: Product/architecture maintainer
Last reviewed: 2026-08-31

Copy this into a nontrivial PR description and replace every `<placeholder>`. Keep `none`, `not
applicable`, or `not visible` explicit. The report implements the evidence contract in
[`codex-model-routing.md`](./codex-model-routing.md) and receives execution details from
[`codex-task-packet-template.md`](./codex-task-packet-template.md).

```markdown
## Outcome

<Concise user/engineering outcome.>

<Choose exactly one linkage: `Closes #<issue>` when this PR completes the Issue, or `Refs #<issue>`
when it is only one tracked slice.>

## Scope and non-goals

Changed:

- <bounded outcome/path>

Not changed:

- <explicit adjacent behavior, configuration, release, migration, or follow-up>

Authorized final file/symbol set:

- `<path or symbol>`

Scope deviation: <none, or exact explanation and recorded approval>

## Routing report

- Coordinator AGENT_ID: <stable identity>
- Coordinator PARENT_AGENT_ID: <stable parent or NONE>
- Issue/lane/phase: <exact values>
- Authorized base commit/tree: `<commit>` / `<tree>`
- Whole-PR class: MECHANICAL / RECOVERY / INVENTORY | STANDARD / BOUNDED PATCH / TEST REPAIR / AUDIT FINALIZATION | HIGH / CROSS-LAYER / P0-P1 WITH AN ACCEPTED CONTRACT | ULTRA EXCEPTION
- Requested coordinator: <model/capability>
- Requested reasoning: <mode>
- Actual coordinator model: <observed value or not visible>
- Actual coordinator reasoning: <observed value or not visible>
- Routing rationale: <bounded contract, unresolved decisions, consequence, and evidence burden>
- Smaller sufficient route rejected because: <reason, or none>
- Per-agent selection visible: yes | no | partially
- Coordinator downgrade/fallback/substitution: <none or explicit evidence/approval>
- Ultra authorization and five-condition admission: <URL + rationale, or not admitted>
- Why delegation was used or skipped: <bounded ownership/context value or startup-cost reason>

| AGENT_ID / PARENT_AGENT_ID | Access | Planned model/reasoning | Actual model/reasoning | Exact non-overlapping ownership | Receipt/result |
| --- | --- | --- | --- | --- | --- |
| <child / parent> | READ-ONLY / authorized writer | <route and mode> | <observed values or not visible> | <sources/paths/symbols> | <durable receipt> |

One write coordinator by default: <confirmed or explicit second-writer authorization>

Read-only minions bounded and smallest-sufficient: <confirmed or blocker>

No overlapping write ownership: <confirmed or blocker>

## MUST-to-evidence matrix

| MUST requirement/invariant | Implementation evidence | Validation/review evidence | Status |
| --- | --- | --- | --- |
| <requirement> | `<path>` / <section/symbol> | `<command>` / <run URL or review> | PASS / FAIL / BLOCKED |

Known requirement gap hidden by aggregate green results: <none or exact risk>

Representative falsifier/broken-case evidence: <test/audit that would fail, or why not applicable>

## Preserved Metroliza contracts

- Branch/base: <`develop` or separately approved release path>
- Architecture/imports: <canonical package and compatibility effect>
- Data/SQLite: <atomicity, migration, cleanup, or not applicable>
- Native/performance: <Python parity, benchmark, packaging, rollback, or not applicable>
- Windows/release: <core/packaged/manual/release evidence or not applicable>
- Offline/network: <offline/local-first and integration effect>
- Confidentiality/security: <sanitized evidence and exposure review>
- Evidence honesty: <unobserved claims explicitly absent>

## Validation

Exact reviewed head: `<full SHA>`

Exact reviewed tree: `<full tree SHA>`

### Durable checkpoints and bounded receipts

| Purpose/status | Ref/commit/tree | Exact paths/content hashes | Completed gates | Remaining gates |
| --- | --- | --- | --- | --- |
| <preservation/final> | <durable evidence> | <scope/hash evidence> | <receipt IDs/results> | <exact list> |

- Preservation checkpoint truthfully labelled not parked / not Ready / not complete: yes | no | n/a
- Sole valuable copy in `/tmp` or ephemeral storage: no | <blocker and recovery location>
- Restartable validation-slice receipt audit: <machine-readable locations/hashes/result>
- Observed elapsed time: <value or not visible>
- Durable outputs: <commits/comments/artifacts/receipts>
- Correction cycles: <integer>

### Local/focused

| Command/check | Exact result | Head/tree |
| --- | --- | --- |
| `<command>` | <exit/result/count> | `<SHA>` |

### GitHub exact-head evidence

| Workflow/check | Trigger | Run ID or URL | Head SHA | Observed state/conclusion | Required/applicable reason |
| --- | --- | --- | --- | --- | --- |
| <name> | automatic / manual / none | <ID/URL or unavailable> | `<SHA>` | success / failure / cancelled / skipped / unavailable / infrastructure-blocked / pending | <reason> |

Integration-result/base currentness: <observed status and base SHA>

Manual/conditional gates not run: <gate + why not applicable, or blocker>

Only observed applicable success is green. Skipped, unavailable, infrastructure-blocked,
cancelled, pending, and unrun states remain distinct and are never silently treated as success.

## Exact-head and adversarial review

- Final diff reviewed against authorized scope: yes | no
- Final head frozen before independent review: yes | no
- Independent review route and sufficiency: <requested/actual model and rationale>
- Requirement/document consistency: <result>
- Negative/failure paths: <result or not applicable>
- Confidentiality/security boundaries: <result>
- Production/disabled behavior: <result or not applicable>
- Windows/native/benchmark/SQLite/release applicability: <result>
- TupTup-specific leakage check: <result or not applicable>
- Project-specific rule incorrectly generalized: <result>
- Later blocker after review: <none or exact blocker>

### Actionable findings

- P0: <none or finding + disposition>
- P1: <none or finding + disposition>
- P2: <none or finding + disposition>
- Informational observations: <none or concise note>
- Correction cycles after readiness: <integer>

### Routing feedback

- Coordinator class adequate: yes | no | pending
- Routing review required: <yes/no and trigger>
- Next materially similar task recommendation: <class/model/reasoning and rationale>

## Review and readiness ledger

- GitHub Codex Review: <requested at SHA / result / pending>
- Independent exact-head review: <reviewer/result/SHA or pending>
- Draft-to-Ready transition: <timestamp or not performed>
- Ready-triggered review: <observed event/result or none observed after bounded wait>
- All comments newer than Ready inspected through: <timestamp/result>
- Every review thread inspected after Ready: yes | no | not applicable
- Unresolved review-thread count: <integer or not yet observed>
- Required CI terminal-green: yes | no | pending
- Head unchanged since readiness review: yes | no | pending
- GitHub mergeable: yes | no | unknown
- External orchestrator conclusion: READY FOR MERGE | NOT READY | pending

The Codex coordinator/workers have not merged this PR. A READY result authorizes only the external
orchestrator's ordinary squash merge under the repository playbook; it does not authorize release
promotion, real-data migration, deployment, destructive operations, secrets, billing, external
publication, or other remote product mutations.

## Risk and rollback

- Primary risk: <risk>
- Mitigation: <evidence/control>
- Rollback: <reviewed revert/disable/data-safe route>

## Remote-operation ledger

- Allowed operations performed: <branch push, PR, CI, review request, or none>
- Destructive/privileged operations performed: none | <exact separately approved action>
- Unrelated refs/tags/branches changed: no | <exact approved exception>
- Release/deploy/migrate/publish/merge performed: no | <exact separately approved action>
- Approval evidence: <task packet/comment or none>
```

Do not mark the report READY while an exact-head check, review, thread count, mergeability result,
applicable conditional gate, or post-Ready review inspection is unknown. A changed head invalidates
earlier exact-head evidence and starts a new readiness review cycle.
