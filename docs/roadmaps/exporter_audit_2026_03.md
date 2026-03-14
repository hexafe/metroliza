# Exporter Audit (2026-03)

## Goal
Assess whether export-path refactoring is still needed after the recent RC2 stabilization slices, and identify the next highest-value follow-up work.

## Constraints
- Preserve release confidence and behavior parity.
- Prefer small, reversible seams over broad architecture rewrites.
- Keep `modules/export_data_thread.py` as the compatibility entry point while extracting pure/helper logic.

## Key findings
1. **Refactoring is still needed in the exporter path.**
   - `modules/export_data_thread.py` remains very large (~3.5k LOC) and still concentrates orchestration, plotting, worksheet population, and result handling responsibilities.
2. **Recent seams reduced risk, but did not finish decomposition.**
   - Existing helper seams (`export_query_service`, `export_sheet_writer`, `export_chart_writer`, `export_google_result_utils`, `export_logging_service`) are useful and already in use.
3. **High-complexity method hotspots remain inside `ExportDataThread`.**
   - Largest methods still indicate “mixed concerns” hotspots (worksheet fill/write flow, group-analysis rendering/annotation, and top-level run path).
4. **Execution roadmap already reflects this status.**
   - Phase A completed small extractions (EX-001/EX-002/EX-003/EX-008), while deeper structural work (EX-004+) remains deferred to post-rc2.

## Current hotspot snapshot
Approximate size hotspots in `modules/export_data_thread.py`:
- `summary_sheet_fill` (~537 LOC)
- `annotate_violin_group_stats` (~228 LOC)
- `add_measurements_horizontal_sheet` (~197 LOC)
- `run` (~166 LOC)
- `_render_group_analysis_plot_asset` (~125 LOC)

These are the best next extraction targets because they combine control flow + formatting/layout details + state mutation.

## Recommended next refactor sequence
1. **Extract “summary sheet composition” service (highest priority).**
   - Move table-shaping and write-order decisions out of `summary_sheet_fill` into a stateless helper/service.
2. **Extract “group analysis rendering pipeline” coordinator.**
   - Separate annotation/style computation from writer side effects.
3. **Reduce `run()` to staged orchestration only.**
   - Keep state transitions and cancellation handling in thread class; delegate stage bodies.
4. **Add contract tests per seam before moving additional logic.**
   - Snapshot-like assertions for payload shapes and metadata contracts.

## What else should be prioritized (besides exporter)
- **Parity evidence capture:** keep executing and recording release-check parity evidence after each extraction slice.
- **Dialog/UI decomposition follow-up:** `modules/export_dialog.py` still has large widget/layout methods and can continue gradual service extraction (non-UI decisions first).
- **Deferred roadmap items remain correctly deferred:** plugin/LLM/warranty interfaces should wait until post-Phase-B boundaries stabilize.

## Risks and mitigations
- **Risk:** hidden behavior drift in workbook layout/plot details.
  - **Mitigation:** strict behavior-preserving seams + focused regression tests on writer outputs/metadata.
- **Risk:** overly broad refactor in one change set.
  - **Mitigation:** keep slices small with explicit rollback points.
- **Risk:** release confidence regression from untracked parity checks.
  - **Mitigation:** require parity evidence updates in release-check docs per slice.

## Suggested TODO backlog (near-term)
- [ ] Create `export_summary_composition_service.py` and extract non-I/O summary planning logic.
- [ ] Add dedicated tests for extracted summary composition contracts.
- [ ] Extract group analysis annotation payload builder from thread class.
- [ ] Add tests for annotation payload/data-shape parity.
- [ ] Run and record release-check parity evidence after each extraction merge.

