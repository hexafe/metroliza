# Metroliza ChatGPT Workspace

Status: Active workspace convention  
Owner: Maintainer  
Last reviewed: 2026-08-31

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
Treat the active Issue/specification and repository instructions as task authority; inspect the
current branch and exact head as execution state. Keep Product Owner, external orchestrator, Codex
coordinator, and bounded-worker roles distinct. Classify the whole PR separately from worker
slices and use the smallest route that can satisfy each bounded contract. Critical, milestone,
P0/P1, or maximum-worker-risk labels never admit Ultra alone; require explicit authority and every
canonical Ultra condition. Use one write coordinator by default and read-only, non-overlapping
minions on their own smallest-sufficient routes. Never silently downgrade, fall back, inherit, or
substitute a route; report unavailable runtime identity as `not visible`. Use explicit MUST,
SHOULD, and DEFERRED scope, durable content-addressed checkpoints before long gates, no sole
valuable copy in `/tmp`, restartable validation slices, and machine-readable receipts. Freeze the
exact head for review; report skipped, unavailable, and infrastructure-blocked CI honestly; after
Draft becomes Ready inspect every triggered review, newer comment, and thread. Codex coordinators
and workers do not merge their own PRs. Require separate approval for release, deployment,
migration, destructive, secret, billing, publication, and other remote product mutations.
```

Use this second block as the Metroliza project instruction:

```text
Treat GitHub repository hexafe/metroliza and its active Issue as durable truth. Read root AGENTS.md,
docs/project/README.md, docs/project/architecture.md, docs/project/development_workflow.md, and
docs/release_checks/branching_strategy.md before changing a bounded branch. Start normal work from
and target develop; never rely on the default branch. Use src/metroliza as canonical and modules
only for compatibility. Preserve local-first behavior, SQLite atomicity, bounded processing,
offline dashboards, deterministic Python fallbacks, Python/Rust parity and representative
benchmark gates, packaged Windows compatibility, and confidential measurement-data hygiene. Apply
the canonical coordinator/worker routes, five-condition Ultra admission, checkpoint/receipt
contract, and exact-head readiness policy in
docs/engineering/codex-model-routing.md. Never claim tests, CI,
benchmarks, packaged/manual gates, model/reasoning, merge, release, or remote actions without an
observed result. Record durable decisions and follow-up work in Issues, PRs, or active repository
docs.
```

Keep both instruction blocks short and stable. Put feature-specific detail and the exact selected
route in the linked Issue/task packet, not in a permanently growing instruction block. Named-model
mappings remain authoritative in the repository playbook and should be refreshed there rather than
copied into global instructions.

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
8. `docs/engineering/codex-model-routing.md`

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
3. `AGENT_ID`, `PARENT_AGENT_ID`, lane, phase, authorized commit/tree, and branch or `READ-ONLY`;
4. explicit requested outcome (audit, implementation, review, or evidence);
5. whole-PR coordinator class/model/reasoning, routing rationale, and smaller-route early-exit;
6. bounded worker identities, read/write authority, non-overlapping ownership, and planned routes;
7. durable checkpoint, restartable validation-slice, and machine-readable receipt plan;
8. the accepted execution packet or a completed
   [`Codex task packet`](../engineering/codex-task-packet-template.md);
9. any local test/artifact constraint not already in the Issue.

The first action should be to read the Issue and current branch state through GitHub, not to rely on
memory from another chat. Read the repository sources of truth before editing and report a moved
base, contradiction, or missing authority instead of silently adapting the packet.

## 6. Standard chat-to-GitHub workflow

1. **Open Issue** — problem, scope, acceptance criteria, validation tier.
2. **Create Issue chat** — read Issue, relevant code/docs/tests, and branch state.
3. **Classify and packet** — apply the smallest-sufficient normal route separately to the
   coordinator and each worker; admit Ultra only with explicit authority and all five conditions.
   Record identity, rationale, early exit, MUST/SHOULD/DEFERRED, ownership, forbidden work, stops,
   checkpoints, receipts, validation, and remote policy.
4. **Plan bounded ownership** — default to one writer and read-only minions; state exact disjoint
   files/symbols, risks, rollback, and tests.
5. **Create branch** — use Issue-number naming.
6. **Implement** — keep scope narrow, surface discoveries early, and preserve valuable bytes before
   they exist only in an ephemeral workspace.
7. **Checkpoint** — before long full-suite, coverage, compatibility, fuzz/mutation, or review work,
   push a content-addressed preservation checkpoint labelled not parked, not Ready, and not
   complete.
8. **Validate in bounded slices** — run actual focused/full/manual gates as required and retain
   restartable machine-readable receipts tied to the exact commit/tree.
9. **Open draft PR** — link Issue and use the
   [`PR routing report`](../engineering/pr-routing-report-template.md) for evidence, risk, rollback,
   and routing details.
10. **Freeze and review** — coordinator audits the exact diff/readiness; external orchestrator uses
    a sufficiently independent smallest-sufficient route for exact-head review. Resolve findings,
    threads, and CI only for the unchanged head.
11. **Inspect the Ready boundary** — if Draft becomes Ready, wait for and inspect every triggered
    review, all newer comments, and every thread before any merge decision.
12. **Merge/close** — only the authorized external orchestrator merges after all standing gates;
    update Issue and durable docs. Codex coordinators/workers do not merge.
13. **Archive chat** — retain only as history after the GitHub record is complete.

## 7. Context handoff template

When moving work between chats, post a concise handoff to the Issue or PR:

```text
AGENT_ID / PARENT_AGENT_ID / Issue / lane / phase:
Current branch/SHA:
Authorized base/tree and final tree:
Issue and acceptance criteria status:
Whole-PR class and requested coordinator/reasoning:
Routing rationale and smaller-route early-exit result:
Actual runtime model/reasoning or not visible:
Worker identities, read/write authority, routes, and non-overlapping ownership:
Implemented:
Durable checkpoint ref/SHA/tree, status, paths, and content hashes:
Validation executed and exact results:
Restartable machine-readable receipt locations/hashes:
Review findings (P0/P1/P2) and correction cycles:
Exact-head CI/review/thread status:
Draft-to-Ready time and all post-Ready reviews/comments/threads inspection cutoff:
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
- Refresh `AGENTS.md`, the routing playbook, and both templates together when the accepted
  capability mapping or orchestration contract changes; do not patch an uploaded copy alone.

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
