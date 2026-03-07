# 2026.03-rc2 Stabilization Execution Plan

## 1. Purpose and scope
This document is the single operational source of truth for the 2026.03-rc2 export-path stabilization and safe refactor workstream. It defines what will be changed, what will be deferred, the order of execution, how progress is tracked, and how maintainers choose the next incremental step.

Scope for this execution cycle:
- Stabilize export behavior and reduce fragility in the current code path without changing end-user behavior.
- Extract low-risk seams that improve testability and readability in the existing architecture.
- Keep release confidence high by aligning changes with release checks and parity validation.

## 2. Non-goals / explicitly deferred work
The following are out of scope for `2026.03-rc2` and are intentionally deferred:
- Full plugin runtime implementation.
- Large-scale package/module renaming beyond surgical updates needed for RC-safe extractions.
- Redesign of export UI workflows or user-visible feature additions.
- New warranty/statistics product capabilities.
- LLM-assisted parser runtime integration beyond preparatory interfaces and documentation.

## 3. Current architecture findings
Primary architecture observations guiding this plan:
- `modules/ExportDataThread.py` has very high responsibility concentration (orchestration + rendering + writing + conversion handling), creating elevated change risk and difficult isolated testing.
- `modules/ExportDialog.py` interleaves UI and non-UI assembly/validation/completion concerns, increasing coupling between presentation and business flow logic.
- Existing helper seams already exist and should be preferred for RC-safe extraction/inversion work:
  - `modules/export_query_service.py`
  - `modules/export_sheet_writer.py`
  - `modules/export_summary_utils.py`
  - `modules/export_chart_writer.py`
  - `modules/export_grouping_utils.py`
- Release process references under `docs/release_checks/` should remain the operational gate for RC confidence.
- Roadmap and naming/policy references must be treated as design constraints and compatibility guides:
  - `docs/roadmaps/plugin_architecture_llm_factory/README.md`
  - `docs/module_naming_migration.md`
  - `docs/documentation_policy.md`

## 4. Refactor objectives
1. Reduce responsibility concentration in export execution paths with behavior-preserving extractions.
2. Increase seam-level unit coverage for extraction targets before larger structural changes.
3. Ensure each phase can be released independently with clear rollback points.
4. Maintain strict naming/documentation discipline to avoid churn before post-RC structural work.
5. Produce a clear handoff path into future plugin and parser-factory architecture work.

## 5. Workstreams / phases
### Phase A — RC-safe `2026.03-rc2` stabilization/refactor
- Behavior-preserving extractions from `ExportDataThread` and light dialog assembly cleanup.
- Add/extend targeted tests for extracted units and regression checks for export parity.
- Update release-check documentation touchpoints only where process changes are required.

### Phase B — Deferred `2026.04+` structural work
- Broader responsibility redistribution across export pipeline modules.
- Module boundary cleanup informed by `docs/module_naming_migration.md`.
- Additional architecture hardening that is too risky for rc2.

### Phase C — Future plugin runtime platform
- Align export pipeline boundaries with plugin runtime extension points.
- Formalize plugin lifecycle contracts and capability registration.

### Phase D — Future LLM-assisted parser factory
- Integrate parser-factory abstractions from roadmap into export/query assembly surfaces.
- Define safety and fallback behavior for LLM-assisted parsing flows.

### Phase E — Future warranty/statistics platform
- Isolate export telemetry/statistics surfaces needed for warranty/statistics integration.
- Add stable interfaces for downstream platform consumers.

## 6. Dependency order between phases
1. **Phase A** is mandatory before all subsequent phases.
2. **Phase B** depends on completed parity-safe extractions and confidence artifacts from Phase A.
3. **Phase C** depends on stable post-Phase-B module boundaries.
4. **Phase D** depends on plugin/runtime extension points from Phase C.
5. **Phase E** depends on stable runtime interfaces from Phases C/D and proven export observability.

## 7. Prioritized TODO list
| ID | title | status | linked phase | rationale | target files | required tests | required docs review | deferral note |
|---|---|---|---|---|---|---|---|---|
| EX-001 | Extract export context builder from thread path | todo | Phase A | Lowest-risk responsibility reduction with minimal behavior surface change | `modules/ExportDataThread.py`, `modules/export_query_service.py` | Focused unit tests for context assembly + existing export regression checks | `docs/release_checks/` entries touching export validation | — |
| EX-002 | Move conversion decision matrix into helper seam | todo | Phase A | Reduces branching complexity in thread execution loop | `modules/ExportDataThread.py`, `modules/export_summary_utils.py` | Unit tests for conversion routing and parity snapshots | `docs/release_checks/` | — |
| EX-003 | Isolate dialog non-UI completion validation helper | todo | Phase A | De-couple non-UI logic from `ExportDialog` UI flow without UX change | `modules/ExportDialog.py`, `modules/export_grouping_utils.py` | Dialog validation unit tests + smoke export flow | `docs/documentation_policy.md` conformance check | — |
| EX-004 | Introduce export orchestration façade for structural migration | deferred | Phase B | Needed for larger architecture cleanup but higher rc2 risk | `modules/ExportDataThread.py`, new façade module(s) | Integration tests across full export variants | `docs/module_naming_migration.md` alignment | Deferred to `2026.04+` for risk control |
| EX-005 | Define plugin runtime adapter contract draft | deferred | Phase C | Unblocks long-term plugin path after structural cleanup | `docs/roadmaps/plugin_architecture_llm_factory/README.md` and related modules | Contract tests (future) | Roadmap review with maintainers | Deferred until Phase C starts |
| EX-006 | Draft LLM parser factory bridge interface | deferred | Phase D | Sequenced after plugin contract stabilization | parser-factory interface files (future) | Safety/fallback tests (future) | Roadmap + policy review | Deferred pending Phase C outputs |
| EX-007 | Specify warranty/statistics export telemetry contract | deferred | Phase E | Depends on stable extension/runtime interfaces | telemetry interface files (future), export writer seams | Contract and data-shape tests (future) | release + documentation policy review | Deferred pending Phases C/D |

## 8. Per-phase definition of done
### Phase A done
- At least one responsibility extraction from `ExportDataThread` merged with no intentional behavior change.
- Required tests pass and release-check parity evidence is recorded.
- Progress tracker updated with completed IDs and next actionable item.

### Phase B done
- Structural boundary changes merged with naming migration alignment notes.
- Integration test suite covers key export variants.
- Rollback notes updated for changed boundaries.

### Phase C done
- Plugin runtime contract documented and prototyped behind stable interfaces.
- Core export flows run unchanged when plugin extensions are disabled.

### Phase D done
- LLM parser-factory bridge interface integrated with explicit fallback behavior.
- Safety test coverage for invalid/ambiguous parser output exists.

### Phase E done
- Warranty/statistics contract finalized and verified against export telemetry outputs.
- Backward-compatible runtime behavior confirmed.

## 9. Test strategy
- Prefer incremental, extraction-scoped unit tests before integration changes.
- Maintain export parity checks as a hard gate for Phase A.
- For each TODO item, define required tests before coding and record pass/fail in tracker notes.
- Use regression snapshots or deterministic fixtures where conversion/render output is sensitive.
- Keep test additions behavior-focused (no broad refactors hidden in test-only changes).

## 10. Documentation update rules
- This file is the operational execution source; update it first when plan state changes.
- Keep TODO statuses synchronized with actual merged code state (`todo`/`in_progress`/`done`/`deferred`).
- Any release procedure impact requires same-change review of relevant files in `docs/release_checks/`.
- Naming or module boundary changes must be checked against `docs/module_naming_migration.md`.
- Any roadmap-affecting decision must cross-reference `docs/roadmaps/plugin_architecture_llm_factory/README.md`.
- All documentation edits must respect `docs/documentation_policy.md`.

## 11. Risk register
| Risk ID | Risk | Likelihood | Impact | Mitigation | Trigger |
|---|---|---|---|---|---|
| R-01 | Behavior regression while extracting from `ExportDataThread` | Medium | High | Small PRs, parity tests, explicit rollback points | Export output mismatch in release checks |
| R-02 | Hidden UI coupling in `ExportDialog` during non-UI extraction | Medium | Medium | Limit scope to helper extraction, run smoke UI flow | Validation/completion flow drift |
| R-03 | Deferred structural debt slows later phases | High | Medium | Keep strict tracker hygiene and phase prerequisites | Phase B kickoff blocked by unclear A outputs |
| R-04 | Roadmap drift between execution and future platform plans | Medium | Medium | Require docs cross-check in each phase | New work conflicts with roadmap docs |

## 12. Rollback / parity strategy
- Every Phase A change must preserve previous behavior by default.
- Keep extraction PRs narrow so each can be reverted independently.
- Use release-check parity comparisons as acceptance and rollback triggers.
- If parity fails, revert the smallest recent extraction and re-run checks before proceeding.
- Do not stack multiple high-risk refactors in a single change set.

## 13. Progress tracker
| Item ID | current status | owner | last update | notes | next candidate step |
|---|---|---|---|---|---|
| EX-001 | todo | maintainer | 2026-03-01 | Planned as first low-risk extraction in export flow | Start EX-001 |
| EX-002 | todo | maintainer | 2026-03-01 | Blocked on EX-001 seam confirmation | After EX-001 done, start EX-002 |
| EX-003 | todo | maintainer | 2026-03-01 | Can run parallel after EX-001 if capacity allows | Start when EX-001 reaches done |
| EX-004 | deferred | maintainer | 2026-03-01 | Explicitly deferred beyond rc2 | Revisit in 2026.04 planning |
| EX-005 | deferred | maintainer | 2026-03-01 | Future plugin runtime phase | Revisit after Phase B completion |
| EX-006 | deferred | maintainer | 2026-03-01 | Depends on plugin runtime contract | Revisit after EX-005 outcomes |
| EX-007 | deferred | maintainer | 2026-03-01 | Depends on platform interfaces from C/D | Revisit after EX-006 outcomes |

## 14. “Next recommended step”
Execute **EX-001** only: extract a pure helper that builds export context data from `ExportDataThread` into `modules/export_query_service.py`, with no behavior changes and with focused unit test coverage.
