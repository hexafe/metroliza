# PR routing-report template

Status: Active template
Owner: Product/architecture maintainer
Last reviewed: 2026-08-25

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

- Whole-PR class: MICRO | BOUNDED INTEGRATION | FEATURE / CROSS-LAYER | CRITICAL / MILESTONE
- Requested coordinator: <model/capability>
- Requested reasoning: <mode>
- Actual coordinator model: <observed value or not visible>
- Actual coordinator reasoning: <observed value or not visible>
- Classification rationale: <semantic risk and acceptance burden>
- Per-agent selection visible: yes | no | partially
- Coordinator route deviation: <none or evidence/approval>
- Why delegation was used or skipped: <bounded ownership/context value or startup-cost reason>

| Slice | Risk | Planned model/reasoning | Actual model/reasoning | Inheritance/deviation | Responsibility | Focused validation |
| --- | --- | --- | --- | --- | --- | --- |
| <name> | GREEN / YELLOW / RED / CRITICAL | <route and mode> | <observed values or not visible> | <inheritance and route deviation> | <bounded ownership> | `<command>` → <result> |

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

### Local/focused

| Command/check | Exact result | Head/tree |
| --- | --- | --- |
| `<command>` | <exit/result/count> | `<SHA>` |

### GitHub exact-head evidence

| Workflow/check | Run ID or URL | Head SHA | Conclusion | Required/applicable reason |
| --- | --- | --- | --- | --- |
| <name> | <ID/URL> | `<SHA>` | success / failure / pending | <reason> |

Integration-result/base currentness: <observed status and base SHA>

Manual/conditional gates not run: <gate + why not applicable, or blocker>

## Exact-head and adversarial review

- Final diff reviewed against authorized scope: yes | no
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
or applicable conditional gate is unknown. A changed head invalidates earlier exact-head evidence
and starts a new readiness review cycle.
