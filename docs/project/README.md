# Metroliza Project Control Center

Status: Active  
Owner: Product/architecture maintainer  
Last reviewed: 2026-08-23
Review cadence: every release cycle or monthly, whichever is sooner

This directory is the canonical entry point for planning and developing Metroliza. GitHub Issues
track executable work. These documents explain the product, feature catalog, architecture, delivery
rules and ordered roadmap. Release evidence remains under `docs/release_checks/`.

## Start here

1. [Product specification](./product_specification.md) — product definition, personas, workflows,
   full requirements, domain concepts, quality attributes, compatibility and release acceptance.
2. [Feature catalog](./feature_catalog.md) — every major product capability, current maturity,
   roadmap phase, strict prerequisites and tracking Issue.
3. [Roadmap](./roadmap.md) — eight ordered delivery phases, exit gates, milestone mapping and Issue
   prerequisite/integration sequencing.
4. [Architecture](./architecture.md) — canonical packages, dependency direction, data flows,
   compatibility layers, native backends and concentration risks.
5. [Development workflow](./development_workflow.md) — issue-first delivery, branch/PR rules,
   validation tiers, Definition of Ready and Definition of Done.
6. [ChatGPT workspace](./chatgpt_workspace.md) — project sources/chats aligned to GitHub so chat
   history never becomes the only record of a decision.
7. [RC2 branch transition decision](../release_checks/rc2_branch_transition_decision_2026-08-22.md)
   — authoritative branch roles, exact automatic evidence and the pending release blockers.

## GitHub control plane

### Product backlog

- [#925 — complete product feature roadmap](https://github.com/hexafe/metroliza/issues/925) is the
  canonical checklist for all user-facing capabilities.
- Feature Issues [#926–#957](https://github.com/hexafe/metroliza/issues?q=is%3Aissue+repo%3Ahexafe%2Fmetroliza+number%3A926..957)
  cover workspace, import, parsers, OCR, database/curation, filters/groups, statistics, reports,
  tabular/industrial/realtime, automation, traceability, accessibility, extensibility, performance,
  legacy and licensing decisions.
- The full mapping and maturity status live in [feature_catalog.md](./feature_catalog.md).

### Dependency policy

[Issue #967](https://github.com/hexafe/metroliza/issues/967) defines `Dependencies` as strict
prerequisites only. The resulting #926–#957 graph must remain acyclic. Downstream consumers,
cross-phase integrations and shared-fixture obligations remain visible in their Issues and the
roadmap, but they do not create reverse prerequisites for their foundations.

### Project and engineering backlog

| Issue | Purpose |
|---:|---|
| [#899](https://github.com/hexafe/metroliza/issues/899) | Establish the project source of truth and issue-driven workflow. |
| [#900](https://github.com/hexafe/metroliza/issues/900) | Accepted the canonical development, frozen candidate, transition and production branch roles. |
| [#901](https://github.com/hexafe/metroliza/issues/901) | Close exact-build Windows, Google, notices/hashes and legal evidence. |
| [#902](https://github.com/hexafe/metroliza/issues/902) | Consolidate active roadmaps and archive superseded planning documents. |
| [#903](https://github.com/hexafe/metroliza/issues/903) | Decompose `ExportDataThread` one behavior-preserving seam at a time. |
| [#904](https://github.com/hexafe/metroliza/issues/904) | Split dashboard controls/options/specification into bounded modules. |
| [#905](https://github.com/hexafe/metroliza/issues/905) | Move behavior tests to canonical imports while retaining explicit shims. |
| [#906](https://github.com/hexafe/metroliza/issues/906) | Eliminate or renew reviewed security findings before expiry. |
| [#907](https://github.com/hexafe/metroliza/issues/907) | Move reusable plots to `hexafe-plotstats` only behind parity/rollback. |
| [#908](https://github.com/hexafe/metroliza/issues/908) | Promote, keep experimental or retire each Rust/native candidate. |
| [#911](https://github.com/hexafe/metroliza/issues/911) | Complete branch archaeology and evidence-based disposition. |
| [#912](https://github.com/hexafe/metroliza/issues/912) | Define one canonical end-to-end reference workflow. |
| [#913](https://github.com/hexafe/metroliza/issues/913) | Consolidate a reproducible Python/Rust environment. |
| [#914](https://github.com/hexafe/metroliza/issues/914) | Add reliable PR and release quality gates. |
| [#915](https://github.com/hexafe/metroliza/issues/915) | Define canonical measurement, analysis and result models. |
| [#916](https://github.com/hexafe/metroliza/issues/916) | Extract the first headless application-service vertical slice. |
| [#917](https://github.com/hexafe/metroliza/issues/917) | Consolidate result/report metadata and provenance. |
| [#918](https://github.com/hexafe/metroliza/issues/918) | Establish representative benchmarks and Python/Rust parity. |
| [#919](https://github.com/hexafe/metroliza/issues/919) | Define realtime replay, stream/window and detector contracts. |
| [#920](https://github.com/hexafe/metroliza/issues/920) | Define supported platforms, versioning and release process. |
| [#921](https://github.com/hexafe/metroliza/issues/921) | Configure labels, milestones, branch protection and repository defaults. |
| [#922](https://github.com/hexafe/metroliza/issues/922) | Map current codebase, data flow and supported workflows. |
| [#923](https://github.com/hexafe/metroliza/issues/923) | Apply the ChatGPT project source/chat policy. |
| [#924](https://github.com/hexafe/metroliza/issues/924) | Review, preserve and retire historical release branches safely. |

## Source-of-truth hierarchy

When sources disagree, use this order:

1. The accepted current GitHub Issue/PR defines an in-flight work item and reviewed change.
2. `docs/project/` defines current product scope, feature catalog, architecture intent, roadmap and
   delivery policy.
3. `docs/release_checks/` defines release status, evidence, blockers and promotion decisions.
4. `docs/user_manual/` defines current end-user behavior.
5. Code, tests, configuration, `README.md` and `CONTRIBUTING.md` define executable/build contracts.
6. `docs/archive/` and files marked historical/reference-only preserve context but do not assign
   new work.

A decision made only in chat, local notes, an unmerged branch or an unchecked roadmap bullet is not
a durable project decision. Record it in an Issue, pull request, ADR or active document.

## Repository and branch state

Decision date: 2026-08-22. The authoritative rationale and release evidence are in the
[RC2 branch transition decision](../release_checks/rc2_branch_transition_decision_2026-08-22.md)
and the active [release status](../release_checks/release_status.md).

- `develop` is the canonical branch for normal Issue-driven development and integration.
- `release/2026.06-rc2` is the frozen release-candidate and evidence branch.
- `rc2` is a temporary historical transition/reference alias, not a routine development base.
- `master` remains the current production/history anchor and is unchanged pending the separate
  [#901 release-promotion decision](https://github.com/hexafe/metroliza/issues/901).
- Normal work branches from and targets `develop`; approved release fixes target the frozen line
  and must be reconciled into `develop`.

## Delivery model

```text
product requirement / evidence
    -> tracking or implementation Issue
        -> short-lived branch from the documented current base
            -> focused pull request
                -> actual validation evidence
                    -> merge
                        -> issue close / roadmap and release update
```

### Working rules

- Start meaningful implementation from an Issue with testable acceptance criteria.
- Branch normal work from and target `develop`; use `release/2026.06-rc2` only for approved
  release fixes and evidence.
- Use one primary Issue/outcome per pull request; split broad work before coding.
- Keep behavior changes separate from structural refactors.
- New implementation imports use `metroliza.*`; `modules.*` remains compatibility-only.
- Preserve local-first operation, SQLite atomicity, bounded processing, offline dashboards and
  deterministic fallbacks unless a separately approved product change says otherwise.
- Report exact commands, fixtures, environments, results and CI run/SHA. Never claim an unrun test.
- Never commit credentials, tokens, customer reports, production extracts, proprietary drawings or
  unsanitized fixtures.
- Close a feature only when code, acceptance criteria, docs, diagnostics, compatibility and release
  evidence are complete—not merely because code exists on a branch.

## Maintaining this control center

At least monthly and every release cycle:

1. compare #925, the feature catalog and roadmap with open/closed Issues;
2. verify branch/release snapshot values;
3. update maturity only from code/tests/release evidence;
4. archive completed/superseded planning records;
5. review blocked dependencies and limit parallel work;
6. verify expiring security exceptions and manual release blockers;
7. update `Last reviewed` in the review PR.
