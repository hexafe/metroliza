# Metroliza ChatGPT Workspace

Status: Active workspace convention  
Owner: Maintainer  
Last reviewed: 2026-10-18 (routing/adoption update)

## 1. Purpose

ChatGPT is a working interface for research, repository inspection, planning, implementation,
review, and documentation. It is not the durable project database.

GitHub remains the source of truth:

- Issues define work and acceptance criteria;
- branches/commits contain implementation;
- pull requests contain review and validation evidence;
- `docs/project/` contains current product/architecture/roadmap/workflow decisions;
- `docs/release_checks/` contains release evidence.

Any important decision reached in chat must be written back to an Issue, pull request, or active
repository document before the chat is considered complete.

## 2. Project container and copyable instructions

Recommended project name:

```text
Metroliza Development
```

Use the first block as a concise reusable global custom instruction across projects. It contains
only universal orchestration rules; repository-specific rules belong in each project's block and
sources of truth.

```text
Treat the accepted active Issue/packet and repository instructions as task authority; inspect
owned worktree/base/head/tree. Apply shared development-routing policy v1.1 and model map v1.0.
Resolve semantic roles to exact IDs/effort from the authoritative map; do not copy fixed model
tables. If local skills are absent, obtain the authoritative versioned contents/snapshot and
accepted packet from the coordinator, recording origin/hash rather than requiring host paths or
inferring defaults. Either Codex or Claude can coordinate. Separate PO direction, external
independent merge decision, coordinator execution and bounded worker ownership. The author never
self-merges. Use MUST/SHOULD/DEFERRED, owned/forbidden scope and finite spent/remaining budgets.
Observe BOTH/OPENAI_ONLY/CLAUDE_ONLY/NEITHER/UNKNOWN from applicable timestamped capacity evidence;
missing/invalid/>60min data is UNKNOWN, no paid probes or reserve inferred from tokens/API cost.
A fallback cannot waive named gates. Use useful disjoint delegation, normally at most two auxiliary
contexts including reviewers, no recursive swarm; one writer per file, one coordinator, one
Docker/CI owner, one heavy validation run and at most one active Claude invocation. Takeover needs
idle old writers/processes and verified source/resource ownership. One independent scope review
and at most one changed-head delta use fresh non-fork contexts; provide prior findings to delta.
Extra rounds need a named blocker and explicit finite extension within user caps. Preserve adverse
receipts and valid unchanged evidence. Report requested, configured/reported and response-observed
model/effort separately; unsupported identity is not visible. Source review, CI, integration and
user acceptance are separate. Retain all project/named gates and existing permissions; a model or
provider choice grants no remote/destructive/release/data/secret/billing action authority.
```

Use this second block as the Metroliza project instruction:

```text
Treat GitHub repository hexafe/metroliza and its accepted active Issue/packet as durable truth.
Read root AGENTS.md and relevant project, architecture, development workflow and release contracts.
Normal work starts from and targets develop; never rely on the default branch. Canonical code is
src/metroliza; modules is compatibility-only. Preserve local-first, SQLite atomicity, bounded
processing, offline dashboards, deterministic Python fallback, Python/native parity and packaging,
representative benchmarks, Windows journeys and confidential measurement-data hygiene. Apply
shared semantic roles/modes via docs/engineering/codex-model-routing.md; no fixed model table here.
The accepted Oct18 direction (#1061 comment 6251973769) covers current and future work: new tasks
immediately; running/paused packets at the next safe boundary with source/owner/gate/budget
continuity. Do not interrupt/reset/spend/reassign merely for policy change. Before #1063 merge,
accepted Issue/packet direction governs; after merge the repository playbook is active. Named
review/acceptance gates remain until explicitly reconciled. Keep GitHub Codex Review, independent
exact-head review, resolved threads and all applicable actual CI/SQLite/native/Windows/release
gates. CRITICAL/milestone integration needs applicable cross-provider evidence or a candidate user
exception. Only authorized external orchestration merges, never the author. Release, tag/deploy,
real data and destructive operations retain separate authority. Remote branches are WIP, not
archives: mark merged sources DELETE_CANDIDATE; before any deletion prove the complete live-consumer
list and clean-repository fetch of exact commit/tree from retained recovery ref, then use a PO
approved finite exact-ref/full-SHA manifest with expected-old-value guards. Never fabricate tests,
manual evidence, model identity, usage, merge or actions. Write durable decisions/follow-ups to
Issues, PRs or active docs.
```

Keep both instruction blocks short and stable. Put feature-specific detail and the exact selected
route in the linked Issue/task packet, not in a permanently growing instruction block. Named-model
mappings remain authoritative in the versioned shared map; the repository playbook binds its
roles and gates. Obtain the matching shared snapshot and packet rather than copying model tables.

## 3. Canonical project sources

Use the following small source set as the persistent context layer:

### Always-current control sources

1. `AGENTS.md`
2. `docs/project/README.md`
3. `docs/project/product_specification.md`
4. `docs/project/architecture.md`
5. `docs/project/roadmap.md`
6. `docs/project/development_workflow.md`
7. `docs/project/chatgpt_workspace.md`
8. `docs/engineering/codex-model-routing.md` plus its accepted packet and authoritative shared
   policy v1.1 / map v1.0 snapshot (origin/hash recorded; obtain if not locally available)

### Repository and contributor sources

9. `README.md`
10. `CONTRIBUTING.md`
11. `pyproject.toml`
12. `.github/pull_request_template.md`
13. `.github/workflows/ci.yml`
14. `docs/engineering/codex-task-packet-template.md`
15. `docs/engineering/pr-routing-report-template.md`

### Release sources

16. `src/metroliza/app/version.py`
17. `docs/release_checks/release_status.md`
18. `docs/release_checks/release_candidate_checklist.md`
19. `docs/release_checks/branching_strategy.md`
20. the latest exact release-audit/evidence document

### Architecture guard sources

21. `tests/test_directory_reorganization_architecture.py`
22. packaging/hidden-import guard tests
23. current package-owned contract files relevant to the active Issue

Do not make every historical roadmap a permanent project source. Retrieve archived/reference files
only when the Issue needs their history. A smaller canonical source set reduces contradictions and
stale context.

When GitHub integration is available, read the current branch files directly rather than relying on
an old uploaded copy. Refresh any uploaded project source after the corresponding repository file
changes.

## 4. Chat structure

Use stable “control” chats for ongoing coordination and one disposable implementation chat per
Issue.

### 4.1 `00 — Control Tower / Roadmap`

Purpose:

- project status and priority review;
- branch/release state;
- triage of new ideas into Issues;
- roadmap and milestone maintenance;
- deciding which Issue is next.

Inputs:

- `docs/project/README.md`;
- `docs/project/roadmap.md`;
- open Issues;
- latest release status.

Outputs:

- new/refined Issues;
- priority/dependency changes;
- updates to `docs/project/roadmap.md`.

Do not implement feature code in this chat.

### 4.2 `01 — Release / CI / Packaging`

Purpose:

- #900 exact-head validation;
- #901 packaged Windows/Google/legal evidence;
- CI failures, artifacts, coverage, security, and release decisions.

Inputs:

- exact commit SHA;
- workflow runs/jobs/logs;
- release checklist/status/audit docs;
- packaging scripts and manifests.

Outputs:

- evidence comments/PRs;
- blocker Issues;
- explicit go/no-go recommendation.

Never infer manual packaged evidence from unit tests.

### 4.3 `02 — Architecture / Refactoring`

Purpose:

- package boundaries;
- #903 exporter decomposition;
- #904 dashboard decomposition;
- #905 compatibility-test migration;
- architecture audits and decision records.

Inputs:

- architecture document;
- exact Issue;
- current code and focused tests;
- complexity/cycle/legacy budgets.

Outputs:

- a bounded slice plan;
- one reviewable implementation branch/PR;
- updated tests and architecture documentation.

No broad “clean the entire repo” change sets.

### 4.4 `03 — Parsing / OCR / Parser Plugins`

Purpose:

- report preflight/resolver/parser behavior;
- OCR metadata and packaged runtime;
- parser profile/plugin contracts, fixtures, validation, and rollout.

Inputs:

- sanitized fixtures only;
- parser plugin specification;
- expected-results CSV;
- focused parser/OCR tests and diagnostics.

Outputs:

- parser Issue/PR/evidence;
- sanitized plugin handoff packages;
- updated user/maintainer docs.

Never upload proprietary supplier reports or credentials to a chat without an approved sanitized
workflow.

### 4.5 `04 — Export / Excel / Dashboards`

Purpose:

- workbook and dashboard behavior;
- group analysis;
- Google conversion/fallback;
- chart specifications and visual parity;
- #903, #904, and #907 implementation slices.

Inputs:

- export contracts/outcomes;
- chart/dashboard modules;
- representative sanitized fixtures;
- focused workbook/dashboard tests.

Outputs:

- narrow Issue/PR;
- parity evidence;
- user manual/update when behavior changes.

Keep visual redesign separate from behavior-preserving decomposition.

### 4.6 `05 — Industrial / Tabular / Realtime`

Purpose:

- CSV/Excel Summary;
- production source/cache workflows;
- industrial filtering/grouping/export;
- realtime samples/events/detectors/replay/dashboard.

Inputs:

- contracts, schemas, repositories, services;
- synthetic/replay fixtures;
- source-safety and rollout docs;
- focused performance/consistency tests.

Outputs:

- bounded Issue/PR;
- data migration/rollback notes;
- operator/user documentation and validation evidence.

Do not use real production credentials or extracts in chat.

### 4.7 `06 — Native / Performance`

Purpose:

- Rust crates, bridges, parity, benchmarks, and packaging;
- #908 promotion decisions;
- dependency boundary/performance research.

Inputs:

- representative benchmarks;
- Python reference behavior;
- native bridge policy;
- locked Rust manifests and packaging checks.

Outputs:

- promote/experimental/retire decision;
- parity/performance tests;
- deterministic rollback documentation.

No native-default decision from a microbenchmark alone.

### 4.8 `07 — Bug Triage`

Purpose:

- reproduce and classify defects;
- gather logs/screenshots/steps;
- identify area, priority, regression range, and safe workaround;
- create/refine a Bug Issue.

Outputs:

- one structured Issue;
- reproduction fixture/test plan;
- routing to an Issue-specific implementation chat.

Do not let this become a permanent implementation chat for unrelated bugs.

### 4.9 `08 — Documentation / User Manuals`

Purpose:

- product/control documentation;
- user manuals;
- release notes and archive hygiene;
- #902.

Inputs:

- current shipped behavior and UI;
- project docs policy/index;
- linked Issue/PR.

Outputs:

- documentation-only PRs where practical;
- archive/reclassification decisions;
- link/index validation.

## 5. Issue-specific implementation chats

Create a new chat for each implementation slice using this naming convention:

```text
#<issue> — <short title> — <branch>
```

Examples:

```text
#900 — Validate current rc2 HEAD — validation/900-rc2-head
#903 — Extract export run stages — refactor/903-export-run-stages
#906 — Review Bandit baseline — security/906-bandit-renewal
```

Start the chat with:

1. the Issue link/number;
2. target/base branch;
3. explicit requested outcome (audit, implementation, review, or evidence);
4. whole-change risk, provider mode/evidence, coordinator and semantic slice/review roles,
   resolved map version/ID/effort and requested/configured/response-observed evidence;
5. the accepted execution packet or a completed
   [`development task packet`](../engineering/codex-task-packet-template.md);
6. any local test/artifact constraint not already in the Issue.

The first action should be to read the Issue and current branch state through GitHub, not to rely on
memory from another chat. Read the repository sources of truth before editing and report a moved
base, contradiction, or missing authority instead of silently adapting the packet.

## 6. Standard chat-to-GitHub workflow

1. **Open Issue** — problem, scope, acceptance criteria, validation tier.
2. **Create Issue chat** — read Issue, relevant code/docs/tests, and branch state.
3. **Classify and packet** — select the whole-PR coordinator separately from worker slices; record
   MUST, SHOULD, DEFERRED, ownership, forbidden work, validation, stops, and remote policy.
4. **Plan bounded slice** — state affected files/contracts, risks, rollback, and tests.
5. **Create branch** — use Issue-number naming.
6. **Implement** — keep scope narrow; surface discoveries early.
7. **Validate** — run actual focused/full/manual gates as required.
8. **Open PR** — link Issue and use the
   [`PR routing report`](../engineering/pr-routing-report-template.md) for evidence, risk, rollback,
   and routing details.
9. **Review/repair** — one independent affected-scope review, consolidate blockers, then at most
   one changed-head delta in a fresh non-fork context supplied with prior findings. The external
   orchestrator verifies the independent exact-head merge decision, threads and actual required CI.
   Further review needs a named blocker and explicit finite budget extension within user caps.
10. **Merge/close** — only the authorized external orchestrator merges after all standing gates;
    update Issue and durable docs. Neither Codex nor Claude authors self-merge.
11. **Archive chat** — retain only as history after the GitHub record is complete.

## 7. Context handoff template

When moving work between chats, post a concise handoff to the Issue or PR:

```text
Owned worktree/branch/base/head/tree and dirty-patch owner:
Issue/adoption authority, acceptance criteria and pre-merge/merged-source activation:
Shared policy/map version, origin/hash and packet binding:
Mode; applicable quota source/time/window/reset or UNKNOWN:
Current coordinator/writer/resource owners; old processes idle before takeover:
Requested/configured-reported/response-observed IDs/effort (not visible if absent):
Named project/model/cross-provider/acceptance gates retained or explicit amendment:
Budget spent/remaining, consumed/remaining review rounds and user caps:
Fresh non-fork scope/delta review evidence; prior findings supplied to delta:
Issue and acceptance criteria status:
Whole-PR class and requested coordinator/reasoning:
Actual runtime model/reasoning or not visible:
Implemented:
Validation executed and exact results:
Review findings (P0/P1/P2) and correction cycles:
Exact-head CI/review/thread status:
Open blocker/risk:
Next bounded action:
Files/contracts that must not change:
Remote operations performed/not performed:
```

Do not copy a long chat transcript. Preserve the facts and decisions needed to continue.

## 8. Source refresh and hygiene

- Review project sources monthly and every release cycle.
- Replace uploaded copies after merged documentation changes.
- Remove superseded roadmap/handoff files from the persistent source set.
- Use GitHub retrieval for live Issues, branches, commits, PRs, and code.
- Keep one control chat per domain; close/archive obsolete implementation chats.
- Do not paste the same broad context into every chat. Link the Issue and canonical docs instead.
- Do not use chat memory as evidence that a test, purchase, release, or manual smoke happened.
- Refresh `AGENTS.md`, the routing playbook, and both templates together when the accepted shared
  policy/map binding changes; preserve the authoritative map as the single ID source. Refresh
  uploaded copies only after integration; they do not activate repository policy or change
  ChatGPT settings. Keep accepted in-flight Issue/packet authority explicit before merge.

## 9. Privacy and security

Never add the following to project sources or chats unless an explicitly approved sanitized process
exists:

- Google `credentials.json`, `token.json`, access/refresh tokens, client secrets;
- production database credentials or connection strings;
- customer/supplier reports containing proprietary identifiers or geometry;
- production extracts with sensitive traceability data;
- private signing keys, license secrets, or unredacted diagnostics;
- local paths/usernames when not required for a reproducible report.

Use synthetic fixtures, redacted logs, expected-results contracts, and local-only secure smoke
runbooks.

## 10. Initial workspace setup checklist

- [ ] Create/use the `Metroliza Development` project container.
- [ ] Add the reusable global and Metroliza project instruction blocks from section 2 to their
      respective settings.
- [ ] Add the canonical sources from section 3.
- [ ] Create the nine control chats from section 4 only as they become useful.
- [ ] Use `00 — Control Tower / Roadmap` to select the next open Issue.
- [ ] Use one new implementation chat for each Issue slice.
- [ ] Use the routing playbook and task-packet template for nontrivial work.
- [ ] Write every durable decision/follow-up back to GitHub.
- [ ] Review and prune sources/chats monthly or each release cycle.
