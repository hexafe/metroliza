# Group Analysis — Next-Step PR Plan (Post-Implementation Reality Check)

## Goal

Reflect shipped Group Analysis work accurately, then focus only on remaining spec-alignment gaps in small PRs.

## Shipped baseline (completed)

- ✅ Contracts and request plumbing for `group_analysis_level` / `group_analysis_scope`.
- ✅ Export dialog controls and level/scope UX wiring.
- ✅ Export integration baseline for Off/Light/Standard, including scope-mismatch skip messaging and diagnostics handoff.
- ✅ New service/writer modules are in active use (`group_analysis_service.py`, `group_analysis_writer.py`).
- ✅ Integration baseline exists for level behavior, scope behavior, and independence from `Extended plots`.

These are no longer active TODOs in this plan.

## Active gaps only (current TODO scope)

1. **Flag semantics parity with spec**
   - Align service-emitted user-facing flags with the spec contract:
     - per-group `LOW N` threshold semantics,
     - cross-group `IMBALANCED N` / `SEVERELY IMBALANCED N`,
     - interpretation `SPEC?` where required.
   - Ensure parity between service payload text and writer conditional-format triggers.

2. **Standard plot delivery beyond placeholders**
   - Replace current “reserved plot slot” placeholders with actual chart insertion where eligible.
   - Preserve conservative histogram gating and diagnostics skip rationale.

3. **Final spec/docs closeout audit**
   - Reconcile planning docs with what is truly shipped vs deferred.
   - Keep one explicit “next implementation step” for the subsequent cycle.

## Proposed PR sequence (remaining work only)

### PR 1 — Flag semantics alignment

**Files**

- `modules/group_analysis_service.py`
- `modules/group_analysis_writer.py`
- `tests/test_group_analysis_service.py`
- `tests/test_group_analysis_writer.py`

**Definition of done**

- Service emits spec-aligned flag vocabulary and thresholds.
- Writer formatting rules map cleanly to emitted flags.
- Tests lock expected flags in per-group, pairwise, and diagnostics surfaces.

---

### PR 2 — Standard plot implementation pass

**Files**

- `modules/group_analysis_writer.py`
- `modules/group_analysis_service.py` (only if payload metadata needs extension)
- integration/writer tests

**Definition of done**

- Standard mode inserts real eligible plots instead of placeholders.
- Histogram omission reasons remain deterministic and visible in diagnostics.
- Existing Light/Standard behavior and non-Group-Analysis exports remain backward compatible.

---

### PR 3 — Documentation closeout (final PR in cycle)

**Files**

- `docs/group_analysis/group_analysis_spec_and_implementation_plan.md`
- optional mirror: `docs/group_analysis/codex_group_analysis_instructions.md`
- any doc-check fixtures if wording-sensitive checks exist

**Definition of done**

- Status block clearly separates implemented vs deferred scope.
- One concrete next implementation step is recorded.
- Documentation wording matches tested/runtime behavior.

## TODO checklist

- [ ] PR 1: finalize flag semantics alignment.
- [ ] PR 2: finalize Standard plot implementation beyond placeholders.
- [ ] PR 3: finalize docs closeout/status audit (must be last PR).

## Sequencing rationale

Address payload semantics first (flags), then finish Standard visual output, then perform final docs closeout so documentation reflects the post-change reality.
