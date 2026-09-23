# PR routing-report template

Reviewed: 2026-09-23. Refs #1061. Use with the [playbook](codex-model-routing.md).
Keep a compact current record and links; do not paste full historical logs. This report does not
request fresh product-wide audits. Every unknown remains explicit.

```markdown
## Outcome and scope

Refs/Closes #<primary Issue>; one delivered behavior:
Changed paths/symbols; non-goals; deviations and authority:
Exact head/tree; current base; tested integration result:
State: Draft / awaiting review / Ready for external decision / merged.

## Routing and authority

Whole-PR risk / semantic reason:
Requested coordinator client+model+effort / speed / delegation:
Configured and observed runtime (or `not visible`):
Critical exception evidence and independent review risk (or not used):
Current task/operation authority; no silent active-task migration:

| Role/slice | Risk | Requested model/effort | Observed/inherited | Owned scope | Effective permissions | Focused evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Coordinator/helper/reviewer | ... | ... | ... | ... | ... | ... |

Why this number of helpers; review context reused:
Allowed escalation actually used and reason:

## MUST evidence and preserved contracts

| MUST / primary or negative behavior | Source evidence | Test/review result and exact binding | Status |
| --- | --- | --- | --- |
| ... | ... | ... | PASS / FAIL / BLOCKED / NOT_RUN / justified N/A |

Canonical package/compatibility, SQLite/atomicity, confidential data,
offline behavior, Python/native parity and Windows applicability:
Representative failing-before/negative control, or actual reason not applicable:
Reused unchanged evidence and why dependencies/configuration still match:

## Validation and findings

| Command/check | Source/environment | First-pass/retried/failed/not-run | Evidence link |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

All prior adverse runs stay linked; skipped is not PASS.
A source/native result does not establish packaged/clean-machine/manual acceptance.

| Issue/finding | Evidence and impact | Severity/confidence | Blocking gate/MUST | Fix or accepted deferral | Owner/pack |
| --- | --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... | ... |

Nonblocking deferral is open work, not repaired work. Bot priority alone is not severity.
Primary residual risk and rollback:

## Review and readiness

One scoped review: scope, source and outcome:
Delta verification: fixed families, affected consumers, source and outcome:
Extra round, if any: named blocker/invalidated assumption and limited question:
Configured GitHub Codex Review, actual final state:
Independent exact-head review, nonauthor identity/role, actual final state:
Threads: adjudicated/resolved count OR unknown; later blockers:
Required CI + applicable local/manual gates for current head/base:
Head unchanged; mergeable; external verdict READY FOR MERGE / NOT READY / pending:

## Resources and remote actions

Observed usage and original remaining budget; unknown telemetry not estimated:
Actual agent starts/review rounds/aggregate runs; no invented cost saving:
Published/merged/released/artifact-qualified: separate actual states:
Operations performed and approval links; excluded operations not performed:
Next concrete action; residual Issues with target review/release:
```

Only external orchestration may merge under the unchanged standing predicate. A new head requires
an updated readiness decision, not automatic erasure of valid unchanged evidence or a new full audit.
Missing required checks or unresolved substantive findings prohibit Ready. A model policy, source
merge or successful build never authorizes release promotion, deployment or real-data migration.
