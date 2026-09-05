# Codex task-packet template

Status: Active template
Owner: Product/architecture maintainer
Last reviewed: 2026-09-05

Use this for nontrivial work. Replace placeholders, remove inapplicable detail and link the
[playbook](./codex-model-routing.md) instead of repeating it. Keep **MUST**, **SHOULD**, **DEFERRED**,
owned scope, evidence and authority explicit. A small task needs a small packet.

## Pre-dispatch packet

```markdown
# <Issue> — <one observable outcome>

AGENT_ID: <unique role/Issue identifier>
PARENT_AGENT_ID: <identifier or NONE>
ROLE: <coordinator / read-only reviewer / bounded worker>
PHASE: <diagnose / prototype / implement / review / mechanical closeout>

## Durable authority

- Repository and Issue: <owner/repository, Issue URL>
- Accepted packet/decision: <URL or this packet>
- Verified base/SHA/tree: <develop @ full SHA / tree>
- Work branch / PR base: <short-lived branch> / <develop>
- Relevant sources: <exact files/refs; no whole-chat dump>

## Routing and value

- Whole-PR class: MICRO | BOUNDED INTEGRATION | FEATURE / CROSS-LAYER | CRITICAL / MILESTONE
- Consequence: <severity and data/security/release implications>
- Unresolved reasoning problem: <question, or none: contract already accepted>
- Requested model: <GPT-6 Astra / GPT-5.6 Luna / Terra / Sol / explicit alternative>
- Execution surface / sign-in: <Codex client, ChatGPT Work, Chat or direct API; relevant access>
- Requested product control: <actual displayed label, e.g. High / Ultra; N/A for direct API>
- API effort, when applicable: <Astra: low / medium / high / xhigh / max; otherwise not visible>
- Approved phase/effort transitions: <conditions and ceiling, or none>
- Why this route: <benefit relative to total effort, not the severity label alone>
- Approved availability fallback: <exact model/effort + conditions, or none>
- Independent review route: <requested model/effort; hosted actual may be not visible>

Do not silently substitute model or effort. Codex Ultra is valid when exposed, but is not an
Astra API effort; GPT-6 Pro is not a Codex model ID. Hidden runtime identity alone is not a blocker.

<!-- Optional: include only capabilities actually used or needed by acceptance. -->
- Runtime capabilities: <context management / async tools / steering / effort updates / UI tools>
- Availability and approval: <verified client/request support, opt-in authority; or unavailable>
- Pending-work owner and finish condition: <bounded jobs, stale-result handling, reconciliation>
- Capability fallback: <approved ordinary execution path; or blocker if acceptance requires it>

Follow the playbook's compatibility limits; this packet does not enable unsupported combinations.
Complete already-authorized work to the intended deliverable, asking only for a material missing
decision. Name an applicable instruction/skill that blocks work rather than inventing a new gate.

## Ownership and effort budget

- Allowed files/symbols: <bounded list>
- Forbidden surfaces: <specific contracts/files>
- Writers: <default 1>
- Read-only helpers: <default 0, maximum 2 unless explicitly approved>
- Delegation: <why it helps, or none>; recursive delegation: prohibited
- First useful checkpoint: <runnable slice / failing reproducer / decision matrix>
- Budget and exit: <finite time/effort budget and required partial handoff>
- Preservation: <Issue/PR/branch artifact; no confidential data>
- Local iterations: ordinary in-scope test-driven changes allowed
- Independent-review corrections: <default 1 bounded round, or explicit alternative>

<!-- Include only when delegating; no placeholder worker table is required otherwise. -->
| Agent | Parent | Risk | Requested route | Read/write ownership | Deliverable / focused check |
| --- | --- | --- | --- | --- | --- |
| <ID> | <ID> | GREEN / YELLOW / RED / CRITICAL | <model / effort> | <disjoint scope> | <proof> |

## MUST — acceptance and preserved invariants

1. <User/engineering outcome and observable success criterion.>
2. <Regression/falsifier that detects the original broken behavior.>
3. <Applicable local-first, SQLite, confidentiality, Windows/native or other contract.>
4. <Only authorized files and remote operations; no unsupported evidence claims.>

## SHOULD — useful improvements inside scope

- <Improvement or none.>

## DEFERRED — forbidden or separately owned work

- <Outcome, owner/Issue and preserved seam; or explicit non-goal.>

## Validation

| Gate | Exact command/check | Required evidence and owner | Applicability |
| --- | --- | --- | --- |
| Focused | <command> | <regression/result, worker or coordinator> | required |
| Integration | <command> | <cross-contract/real workflow result, coordinator> | <required or reason> |
| Final local/static | <commands> | <results bound to final bytes> | <required or reason> |
| Exact-head CI | <workflow/checks> | <run, SHA/current base, terminal conclusion> | <required or reason> |
| Conditional | <Windows/native/SQLite/security/performance/manual gate> | <actual proof + owner> | <each applicable gate> |

Run focused checks during local iteration; run full applicable validation on the final
candidate, not after every edit. Changed bytes invalidate affected evidence. No blanket
baseline-failure waiver, threshold reduction or green claim for an unrun gate.

## Stop, preserve and escalate

Stop for changed product/security/architecture authority, forbidden scope, an exhausted
budget, unavailable route without an approved alternative, or inability to prove a MUST.
A routine local test/lint correction is not a new independent-review round.
Two repeated same-boundary findings require a bounded contract audit before another patch.

State whether base movement is acceptable for this task: <pinned read-only audit may continue;
implementation must inspect overlap and refresh integration evidence; no silent head rewrite>.
Preserve work and report the exact missing decision, safe state and actions not performed.

## Remote-operation policy

- Authorized normal writes: <branch/commit/push/PR/review/CI operations or none>
- Separately approved operations: <exact operation + approval, or none>
- Excluded: <merge by coordinator/worker, force-push, release/deploy, real-data migration,
  destructive actions, secrets, billing/publication and packet-specific exclusions>
- Terminal handoff: <Draft PR / audit report / prototype; never imply merge readiness from WIP>
```

## Post-execution handoff

```markdown
## Handoff — <agent ID>

- Agent / parent / role: <IDs and role>
- Starting base / final head / tree: <exact refs or uncommitted>
- Execution surface / requested model / product control: <surface and selected route>
- Request-level API effort / applied effort updates: <separate values when used; otherwise N/A>
- Actual model / effective effort / topology: <observed values or not visible>
- Capability use / steering / pending actions: <only when used; revised packet and reconciled state>
- Worker inheritance / fallback / deviation: <observed or not visible; approval if changed>
- Outcome and preserved artifact: <what now works; Issue/PR/commit>
- Scope: <exact paths; deviation and authority if any>
- Validation: <commands, exact results and SHAs; unrun gates separately>
- Findings: <P0/P1/P2, evidence and disposition; unresolved risk>
- Local iteration / independent-review rounds: <report separately>
- Budget outcome: <checkpoint reached / exhausted; usage only when observed>
- Routing lesson: <retain/change route and evidence; do not blame hidden runtime identity>
- Remote operations: <performed / not performed>
- Next action and frozen contracts: <one bounded continuation>
```

Integrate the handoff into the [PR report](./pr-routing-report-template.md). Do not paste repeated
transcripts or rerun a worker's full suite merely to reproduce its receipt. The coordinator still
owns the final integrated gate; a worker handoff is evidence input, not merge readiness.
