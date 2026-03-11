# UI Revamp Phase Tracker (Final)

Status legend: `Not started` | `In progress` | `Blocked` | `Complete`

## Mandatory Implementation Order

| Phase | Name | Status | Depends on |
|---|---|---|---|
| 1 | Foundation + shared shell | Complete | — |
| 2 | Characteristic matching | Complete | Phase 1 |
| 3 | Export | Complete | Phase 2 |
| 4 | Grouping | Complete | Phase 1 |
| 5 | Filter | Complete | Phase 1, Phase 4 |
| 6 | Modify DB | Complete | Phase 1 |
| 7 | Global consistency pass | Complete | Phases 1–6 |
| 8 | Docs alignment + QA evidence | Complete | Phase 7 (can prep in parallel) |
| 9 | Archive move (closure only) | Complete | Phase 8 |

## Phase Details and Exit Criteria

## Phase 1 — Foundation + shared shell

- Scope: app shell layout, global status region, shared action placement, base spacing/typography compliance.
- Exit criteria:
  - Shared header/status/action regions are standardized.
  - Baseline controls align with `design-system.md` tokens and interaction states.
  - No blocker-level regressions in keyboard flow.

## Phase 2 — Characteristic matching

- Scope: mapping layout, coverage indicators, row-level validation guidance.
- Exit criteria:
  - Source/target mapping flow is scannable and unambiguous.
  - Validation appears both inline and in summary where needed.

## Phase 3 — Export

- Scope: preflight readiness, output options grouping, post-run summary.
- Exit criteria:
  - Export readiness is explicit before execution.
  - Result summary includes output destination and warnings.

## Phase 4 — Grouping

- Scope: operation discoverability, preview before apply, destructive safety copy.
- Exit criteria:
  - Group operation intent and effects are predictable before confirmation.
  - High-impact actions include explicit safety messaging.

## Phase 5 — Filter

- Scope: persistent active filters, criteria composition clarity, reset behavior.
- Exit criteria:
  - Active filters remain visible.
  - AND/OR logic is explicit in UI copy and layout.
  - No-result state offers recovery action.

## Phase 6 — Modify DB

- Scope: risk-tiered actions, impact preview, deliberate destructive confirmation.
- Exit criteria:
  - Risk is visible before execution.
  - Destructive operations require explicit acknowledgment.
  - Completion state includes operational next steps.

## Phase 7 — Global consistency pass

- Scope: cross-screen token compliance, hierarchy normalization, interaction consistency.
- Exit criteria:
  - Shared component behavior is consistent across screens.
  - Language tone and helper/validation patterns are standardized.

## Phase 8 — Docs alignment + QA evidence

- Scope: docs updates, screenshots/evidence, release-note mapping for UI wording changes.
- Exit criteria:
  - User/internal docs match implemented UI behavior.
  - QA evidence links are captured for each phase outcome.

## Phase 9 — Archive move (closure only)

- Scope: move superseded drafts and finalize archival index after sign-off.
- Exit criteria:
  - Active docs reference final state.
  - Archive index updated with closure date and rationale.

## Open Risks / Notes

- No open blockers after implementation and consistency sweep.
- Follow-up: collect additional operator feedback during next release cycle.
