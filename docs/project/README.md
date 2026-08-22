# Metroliza Project Control Center

Status: Active  
Owner: Product/architecture maintainer  
Last reviewed: 2026-08-22  
Review cadence: every release cycle or monthly, whichever is sooner

This directory is the canonical entry point for planning and developing Metroliza.
GitHub Issues track executable work. These documents explain the product, its architecture,
the delivery rules, and the current roadmap. Release evidence remains under
`docs/release_checks/`.

## Start here

- [Product specification](./product_specification.md) — what Metroliza is, who it serves,
  supported workflows, requirements, and product boundaries.
- [Architecture](./architecture.md) — canonical packages, data flows, compatibility layers,
  native backends, and current concentration risks.
- [Roadmap](./roadmap.md) — ordered milestones and the Issues that carry each work item.
- [Development workflow](./development_workflow.md) — issue-first delivery, branch rules,
  validation tiers, Definition of Ready, and Definition of Done.
- [ChatGPT workspace](./chatgpt_workspace.md) — how project chats and source files should be
  organized without allowing chat history to replace GitHub as the source of truth.

## Source-of-truth hierarchy

When two documents disagree, use this order:

1. The exact open GitHub Issue and its accepted follow-up comments define an in-flight work
   item.
2. `docs/project/` defines current product scope, architecture intent, roadmap, and delivery
   policy.
3. `docs/release_checks/` defines release status, evidence, blockers, and promotion decisions.
4. `docs/user_manual/` defines current end-user behavior.
5. `README.md`, `CONTRIBUTING.md`, configuration, tests, and code define installation and
   executable contracts.
6. `docs/archive/` and documents explicitly marked historical/reference-only preserve context
   but do not assign new work.

A decision made only in a chat, local note, or unmerged branch is not a project decision. Record
it in an Issue, pull request, or active document before relying on it.

## Repository snapshot

Audit date: 2026-08-22.

- `master` is the default branch and currently points to
  `ab26258e72d285c3917a595515798da185800373` from 2026-03-30.
- `rc2` contains the current product line and points to
  `202690eb21087314a3c8000aa3ebdb58a1a09c1b` from 2026-07-17.
- At the audit snapshot, `rc2` is 278 commits ahead of `master` and zero commits behind it.
- PR #895 records green exact-head CI for the earlier RC2 head
  `ce7556098626f93d3ade95abd49ede00be341611` and was intentionally closed without promotion.
- The current `rc2` head is one large product-wide commit after that validated head and must be
  revalidated before any promotion decision.
- Canonical release metadata still identifies `2026.06 RC2 (build 260711)`.

Until #900 is resolved, `rc2` is the working base for current product documentation and fixes,
while `master` must remain untouched. This is a temporary repository-state rule, not a claim
that the release has been promoted.

## Initial issue-driven backlog

| Issue | Priority | Purpose |
|---|---|---|
| #899 | P0 | Establish this project control center and issue-driven workflow. |
| #900 | P0 | Validate the exact current `rc2` head and decide the promotion/development branch path. |
| #901 | P1 | Close packaged Windows, Google conversion, and legal release evidence. |
| #902 | P1 | Consolidate active roadmaps and archive superseded planning documents. |
| #903 | P1 | Continue behavior-preserving decomposition of `ExportDataThread`. |
| #904 | P1 | Split dashboard controls and visual configuration into bounded modules. |
| #905 | P1 | Burn down legacy `modules.*` imports in behavior tests while retaining shims. |
| #906 | P1 | Renew or eliminate reviewed Bandit findings before their expiry. |
| #907 | P2 | Centralize reusable plot specifications in `hexafe-plotstats` behind parity gates. |
| #908 | P2 | Re-evaluate Rust/native acceleration candidates using measured promotion gates. |

## Working rules

- Start implementation from an Issue with acceptance criteria.
- Use one primary Issue per pull request; split broad work before coding.
- Keep behavior changes separate from structural refactors.
- New implementation imports use `metroliza.*`; `modules.*` remains compatibility-only.
- Preserve local-first operation, deterministic fallbacks, SQLite atomicity, bounded data
  processing, and offline dashboard output.
- Record exact commands and outcomes for validation. Do not write “tests passed” without naming
  the tests or CI run.
- Never commit credentials, OAuth tokens, customer reports, production extracts, or proprietary
  fixtures.
- Close an Issue only when its acceptance criteria and documentation impact are complete.

## Maintaining this control center

The maintainer reviews this directory at least monthly and during every release cycle. Update the
review date when the content is checked against the current default/product branches, open Issues,
release metadata, and active release evidence. Superseded implementation plans should be archived
rather than allowed to compete with the current roadmap.
