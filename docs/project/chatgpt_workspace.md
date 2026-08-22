# Metroliza ChatGPT Workspace

Status: Active workspace convention  
Owner: Maintainer  
Last reviewed: 2026-08-22

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

## 2. Project container

Recommended project name:

```text
Metroliza Development
```

Recommended project-level instruction:

```text
Treat GitHub repository hexafe/metroliza as the source of truth. Start development work from a
GitHub Issue, inspect the current target branch and relevant files before proposing changes, and
keep one primary Issue per implementation chat. Use src/metroliza as the canonical package and
modules only as a compatibility layer. Preserve local-first behavior, SQLite atomicity, offline
dashboards, deterministic Python fallbacks, packaging compatibility, and sensitive-data hygiene.
Never claim tests or CI passed without an actual result. Record durable decisions and follow-up
work back in GitHub Issues, pull requests, or docs/project.
```

Keep project-level instructions short and stable. Put feature-specific detail in the linked Issue,
not in a permanently growing instruction block.

## 3. Canonical project sources

Use the following small source set as the persistent context layer:

### Always-current control sources

1. `docs/project/README.md`
2. `docs/project/product_specification.md`
3. `docs/project/architecture.md`
4. `docs/project/roadmap.md`
5. `docs/project/development_workflow.md`
6. `docs/project/chatgpt_workspace.md`

### Repository and contributor sources

7. `README.md`
8. `CONTRIBUTING.md`
9. `pyproject.toml`
10. `.github/pull_request_template.md`
11. `.github/workflows/ci.yml`

### Release sources

12. `src/metroliza/app/version.py`
13. `docs/release_checks/release_status.md`
14. `docs/release_checks/release_candidate_checklist.md`
15. `docs/release_checks/branching_strategy.md`
16. the latest exact release-audit/evidence document

### Architecture guard sources

17. `tests/test_directory_reorganization_architecture.py`
18. packaging/hidden-import guard tests
19. current package-owned contract files relevant to the active Issue

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
4. any local test/artifact constraint not already in the Issue.

The first action should be to read the Issue and current branch state through GitHub, not to rely on
memory from another chat.

## 6. Standard chat-to-GitHub workflow

1. **Open Issue** — problem, scope, acceptance criteria, validation tier.
2. **Create Issue chat** — read Issue, relevant code/docs/tests, and branch state.
3. **Plan bounded slice** — state affected files/contracts, risks, rollback, and tests.
4. **Create branch** — use Issue-number naming.
5. **Implement** — keep scope narrow; surface discoveries early.
6. **Validate** — run actual focused/full/manual gates as required.
7. **Open PR** — link Issue, evidence, risk/rollback, docs/release impact.
8. **Review/repair** — resolve review threads and CI for the exact head.
9. **Merge/close** — update Issue and durable docs.
10. **Archive chat** — retain only as history after the GitHub record is complete.

## 7. Context handoff template

When moving work between chats, post a concise handoff to the Issue or PR:

```text
Current branch/SHA:
Issue and acceptance criteria status:
Implemented:
Validation executed and exact results:
Open blocker/risk:
Next bounded action:
Files/contracts that must not change:
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
- [ ] Add the stable project-level instruction from section 2.
- [ ] Add the canonical sources from section 3.
- [ ] Create the nine control chats from section 4 only as they become useful.
- [ ] Use `00 — Control Tower / Roadmap` to select the next open Issue.
- [ ] Use one new implementation chat for each Issue slice.
- [ ] Write every durable decision/follow-up back to GitHub.
- [ ] Review and prune sources/chats monthly or each release cycle.
