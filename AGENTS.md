# Metroliza repository instructions

## Sources and continuity

Read the active Issue/packet and relevant live code/CI. Use [project hierarchy](docs/project/README.md),
[architecture](docs/project/architecture.md), [development workflow](docs/project/development_workflow.md)
and [release rules](docs/release_checks/branching_strategy.md) for their boundaries.
The [playbook](docs/engineering/codex-model-routing.md) binds shared `development-routing` policy
v1.1 and model map v1.0 to Metroliza delivery. Resolve semantic roles from that versioned shared
map; dated research is historical reference, not the current model default. Clients without local
skills must obtain the authoritative policy/map snapshot and accepted packet through the
coordinator before dispatch; no particular host path or inferred model default is required.

**[User adoption: 2026-10-18](https://github.com/hexafe/metroliza/issues/1061#issuecomment-6251973769).**
Current and future work follows accepted #1061 direction. New tasks adopt immediately. Running/paused work, including WIN-DLV-1, adopts at its next safe packet boundary
with recorded source, owner and spent/remaining budget continuity; do not interrupt, reset, spend
or reassign merely because policy changed. Named review/acceptance gates remain until explicitly
reconciled. Before #1063 merges, accepted Issue/packet direction governs execution and these branch
files are a review candidate; after merge they are the active repository source. Old evidence
keeps its actual identity. No client configuration is installed here.

## Non-negotiable contracts

- Normal branches start from and target `develop`; never assume GitHub's default base.
- Remote branches are disposable execution refs, not evidence archives. Steady state is `master` + `develop` + an active `release/*` when needed + current PR heads.
- Do not create a remote branch per agent, reviewer, test attempt or checkpoint. Reuse the Issue branch for in-scope corrections.
- After merge, mark the source branch for retirement in the same closeout unless a named live PR/release/integration dependency still requires that exact ref. Actual deletion is a separate destructive step using a Product-Owner-approved finite manifest of exact refs/full SHAs and expected-old-value guards.
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
blocking fixes, then at most one changed-head delta in a fresh non-fork context supplied with prior
findings and affected dependencies. Extra rounds need a named blocker and an explicit finite budget
extension within the user cap. No whole-repository audit per correction or full QA per helper.
Reuse valid unchanged evidence, but rebind the exact-head verdict. Keep required CI, GitHub Codex Review, independent
review and adjudicated/resolved threads. Self-check is not independent review.

Before each minor/major release, complete selected stabilization packs, inspect integrated changes
and execute applicable full regression and real Windows-package journeys. Remaining minor Issues
need explicit disposition. Never relabel FAIL, skipped or unknown as PASS.

## Routing and helpers

Separate risk, model, reasoning, delegation, speed and effective permissions. Use the highest of
packet risk, path floor and semantic risk. MICRO uses `economy_worker`; BOUNDED/FEATURE/CRITICAL use
`implementer`. Select independent review by class and observed provider mode in the playbook;
CRITICAL alone does not automatically add `escalation_reviewer`. Resolve exact IDs/effort at dispatch
from shared map v1.0 and record overrides. Standard speed; no silent downgrade or default Ultra.

Either Codex or Claude may coordinate. Record BOTH / OPENAI_ONLY / CLAUDE_ONLY / NEITHER / UNKNOWN
from applicable timestamped capacity evidence; missing, invalid or older-than-60-minute data is
UNKNOWN. Never make paid quota probes or infer reserve from token/cost estimates. A generic approved
fallback cannot waive a specifically assigned reviewer or Metroliza's actual gates.

Delegate only useful disjoint slices, normally at most two auxiliary contexts concurrently,
including reviewers. No recursive swarm or overlapping writers. One coordinator, one writer per
file, one Docker/CI owner and one heavy validation run; at most one active Claude invocation per
task. Verify former writers/processes idle and transfer resource ownership before takeover.
Independent review uses fresh non-fork context, trusted instructions and exact immutable sources;
verify effective no-write permissions or use a controlled snapshot and disclose limitations.
Record requested, configured/reported and response-observed identity/effort separately; unsupported
telemetry is `not visible`. Keep finite shared budgets and consumed/remaining review rounds.

## Authority and handoff

PO owns direction and separately gated operations. External orchestration owns packets, routing,
risk decisions and merge; the Codex or Claude coordinator owns tactical execution/integration and
routine in-scope corrections without per-file/per-commit PO approvals. Use the [packet](docs/engineering/codex-task-packet-template.md)
and [PR report](docs/engineering/pr-routing-report-template.md). GitHub is durable;
a remote archive pathname is not recovered code.

Only external orchestration merges under the playbook's exact-head/current-base predicate:
all applicable gates, adjudicated/resolved threads, no later blocker and mergeability. Prefer squash
merge for normal Issue slices; release/history reconciliation uses the evidence-preserving method
explicitly stated in the release decision, as required by the [branching strategy](docs/release_checks/branching_strategy.md).
Publication for CI, merge and release are distinct. No author self-merge, force rewrite, release/tag/deploy,
live-data migration, secrets, billing or destructive authority follows from a model choice.
