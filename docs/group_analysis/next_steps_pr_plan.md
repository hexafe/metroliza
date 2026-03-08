# Group Analysis — Audit and PR Plan (Current Repo vs Spec)

## Goal

Audit the repo against the implementation plan, then define the next PR sequence with a **docs/todo closeout as the last PR**.

## Current-state audit (spec vs repo)

| Area | Plan expectation | Current repo state | Status |
|---|---|---|---|
| Contracts + request plumbing | `group_analysis_level` / `group_analysis_scope` validated and propagated | Implemented in contracts + export dialog service + tests | ✅ Done |
| Export dialog UX | Separate Group Analysis section, level/scope controls, scope disabled when Off | Implemented in `ExportDialog` + tests | ✅ Done |
| Export integration | Off/Light/Standard flow, scope mismatch messaging, diagnostics always written | Implemented in `ExportDataThread` + integration coverage | ✅ Done |
| Service/writer architecture | New service + writer path active, legacy writer not extended | Implemented (`group_analysis_service.py`, `group_analysis_writer.py`) | ✅ Done |
| Flag semantics parity | `LOW N`, `IMBALANCED N`, `SEVERELY IMBALANCED N`, `SPEC?` end-to-end | Implemented in service + writer conditional formatting + tests | ✅ Done |
| Standard plots | Standard should insert real eligible plots (not placeholders) | **Not complete**: still writes reserved plot-slot text/placeholders | ❌ Open |
| Final docs closeout | Status + next-step wording reflects shipped behavior | Needs refresh now that flags are complete | ⚠️ Needs update |

## Remaining scope (active TODO only)

1. **Standard plot delivery beyond placeholders**
   - Replace reserved plot-slot text with real chart insertion for eligible Standard metrics.
   - Keep deterministic eligibility and diagnostics skip reasons.

2. **Final documentation and TODO closeout (last PR)**
   - Update implementation status sections to reflect true shipped state.
   - Record one concrete next step after Standard plots land.

## Proposed PR sequence

### PR 1 — Standard plot insertion (code)

**Target files**
- `modules/group_analysis_writer.py`
- `modules/ExportDataThread.py` (if plot assets/plumbing need extension)
- `modules/group_analysis_service.py` (only if payload metadata needs extension)
- tests in:
  - `tests/test_group_analysis_writer.py`
  - `tests/test_group_analysis_service.py`
  - `tests/test_export_data_thread_group_analysis.py`

**Definition of done**
- Standard mode inserts real charts for eligible metrics.
- Histogram/violin skips remain deterministic and visible in diagnostics.
- Light mode and non-Group-Analysis export behavior remain unchanged.

---

### PR 2 — Docs/todo closeout (must be last PR)

**Target files**
- `docs/group_analysis/group_analysis_spec_and_implementation_plan.md`
- `docs/group_analysis/codex_group_analysis_instructions.md`
- `docs/group_analysis/next_steps_pr_plan.md`

**Definition of done**
- Docs clearly separate implemented vs deferred work.
- TODO checklist reflects only post-plot remaining work.
- One concrete next implementation step is recorded.

## TODO checklist

- [ ] PR 1: deliver Standard plot insertion beyond placeholders.
- [ ] PR 2 (last PR): update plan/status/todo docs to match shipped behavior.

## Sequencing rationale

The largest functional gap is Standard chart insertion. Close that first in code, then run a final documentation/todo PR so the roadmap reflects the true end-of-cycle state.
