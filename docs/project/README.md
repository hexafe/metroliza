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
- [RC2 branch transition decision](../release_checks/rc2_branch_transition_decision_2026-08-22.md)
  — exact automated evidence, active branch topology, and the explicit no-go for `master` pending
  manual release evidence.

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

## Repository and branch state

Decision date: 2026-08-22. The authoritative evidence and rationale are in
[`rc2_branch_transition_decision_2026-08-22.md`](../release_checks/rc2_branch_transition_decision_2026-08-22.md).

- `master` remains the GitHub default/historical production branch at
  `ab26258e72d285c3917a595515798da185800373`. It is not the development base and is not approved
  for promotion yet.
- `develop` is the canonical base for new Issue-driven development.
- `release/2026.06-rc2` is the frozen release-candidate/evidence branch for release identity
  `2026.06 RC2 (build 260711)`.
- `rc2` is retained as a transition/reference branch. Routine feature, refactor, and documentation
  work must no longer target it after the #900 decision.
- New release fixes target `release/2026.06-rc2` and must be reconciled into `develop`.
- Because GitHub still presents `master` as the default branch, contributors must select the pull
  request base explicitly: normally `develop`, or `release/2026.06-rc2` for approved release work.

The validated branch point after governance PR #909 is commit
`a03bbdacbd6c308acf46ca31c16d0dd2caeab304`, tree
`dc10e028332cb311cb0b2c110deecee2841b9799`. Pull-request CI run `32585291955`
tested the same tree and passed static/security checks, the full test/coverage suite, native wheel
and parity smoke, Windows core smoke, the CMM parser performance guardrail, and benchmark trend
checks. Manual packaging, clean-machine Windows, Google, and legal evidence remains open in #901;
therefore the candidate is not approved for `master` or a stable tag.

## Issue-driven backlog

| Issue | Priority | State/purpose |
|---|---|---|
| #899 | P0 | Completed — project control center and issue-driven workflow. |
| #900 | P0 | Branch transition and automatic validation decision; completes with the decision PR/ref sync. |
| #901 | P1 | Open — packaged Windows, Google conversion, notices, and legal promotion evidence. |
| #902 | P1 | Open — consolidate active roadmaps and archive superseded planning documents. |
| #903 | P1 | Open — continue behavior-preserving decomposition of `ExportDataThread`. |
| #904 | P1 | Open — split dashboard controls and visual configuration into bounded modules. |
| #905 | P1 | Open — burn down legacy `modules.*` imports in behavior tests while retaining shims. |
| #906 | P1 | Open — renew or eliminate reviewed Bandit findings before their expiry. |
| #907 | P2 | Open — centralize reusable plot specifications in `hexafe-plotstats` behind parity gates. |
| #908 | P2 | Open — re-evaluate Rust/native acceleration candidates using measured promotion gates. |

## Working rules

- Start implementation from an Issue with acceptance criteria.
- Branch normal work from `develop`; branch approved release fixes from
  `release/2026.06-rc2`.
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
review date when the content is checked against the current default/development/release branches,
open Issues, release metadata, and active release evidence. Superseded implementation plans should
be archived rather than allowed to compete with the current roadmap.
