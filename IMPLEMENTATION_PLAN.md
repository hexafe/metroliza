# Metroliza Unified Implementation Plan

This is the single, execution-ready plan that combines all previously discussed work into one prioritized roadmap.

## Current implementation status (repo audit)

Audit result based on the current repository state:
- **Phase 0:** ✅ Implemented.
- **Phase 1:** 🟡 Partially implemented.
- **Phase 2:** 🟡 Partially implemented (limited correctness work landed, structural refactor pending).
- **Phase 3:** 🔴 Not implemented.
- **Phase 4:** 🟡 Partially implemented (Phase 0 regression tests exist; broader baseline missing).

Use this section as the source of truth for what is done vs still outstanding.

## Goals
- Fix correctness issues first (grouping/plot mismatches, crashes, dedupe bugs).
- Standardize module communication through dataclass contracts.
- Improve cancellation/reliability for long-running parse/export tasks.
- Reduce maintenance cost via refactor, tests, and CI.

## Delivery principles
- **Safety first:** crash prevention and data correctness before refactor.
- **Backward compatibility:** use fallbacks during key/schema transitions.
- **Small mergeable slices:** each phase can ship independently.
- **Definition of done per phase:** test coverage + observable acceptance criteria.

---

## Phase 0 — Safety hotfixes (Priority P0, 1–2 days)

### Status: ✅ Completed

### Implementation checklist
1. **Shared safe Excel sheet-name utility** — ✅ done.
2. **Harden stats math (Cp/Cpk edge cases)** — ✅ done.
3. **Fix parse dedupe fingerprint** — ✅ done.
4. **Harden license parsing/validation** — ✅ done.

### Scope
1. Add a shared **safe Excel sheet-name utility** used by all sheet creation paths.
   - Sanitize invalid characters (`[]:*?/\\`).
   - Truncate to 31 chars.
   - Ensure uniqueness with deterministic suffixing.
2. Harden stats math (Cp/Cpk and related computations).
   - Guard for empty arrays, NaN, and `sigma == 0`.
   - Emit `N/A` rather than raising.
3. Fix parse dedupe fingerprint.
   - Use DB identity where available, otherwise composite key:
     `(REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER)`.
4. Harden license parsing/validation.
   - Local parse wrappers with targeted `try/except`.
   - Invalid payloads return an invalid-license state (no crash).

### Acceptance criteria
- Known failing exports no longer crash on invalid sheet names or zero-variance data.
- Duplicate detection distinguishes same filename across different directories.
- Malformed license strings are handled gracefully.

---

## Phase 1 — Reliability and cancellation (Priority P1, 2–3 days)

### Status: ✅ Completed

### Implementation checklist
1. **Cooperative cancellation in parse/export workers** — ✅ mostly done.
   - Cancellation flags and checkpoints are present in parse/export threads.
   - Forced thread termination in normal flow appears removed.
2. **Eliminate UI-thread blocking waits** — ✅ done.
   - Cancel handlers request cancellation and return immediately.
   - Guardrail tests now enforce no `.wait()` usage in parse/export dialog cancel flows.
3. **Adjust `CustomLogger` behavior in user flows** — ✅ done.
   - User-facing error paths consistently use `CustomLogger(..., reraise=False)`.
   - Guardrail tests prevent regressions in logger call-site behavior.

### Scope
1. Convert parse/export workers to **cooperative cancellation**.
   - Add cancellation flag checked at granular checkpoints (I/O, row loops, chart creation).
   - Remove forced `terminate()` usage in normal flow.
2. Eliminate UI-thread blocking waits.
   - Use non-blocking status updates and bounded wait/timeout patterns.
3. Adjust `CustomLogger` behavior in user flows.
   - Avoid unconditional re-raise for recoverable user-facing errors.
   - Preserve full diagnostics in logs.

### Acceptance criteria
- User cancellation exits workers cleanly.
- UI remains responsive during long-running operations.
- Recoverable errors show actionable message + preserved logs.

---

## Phase 2 — Correctness + structure + performance (Priority P1/P2, 3–5 days)

### Status: 🟡 Partially implemented

### Implementation checklist
1. **Fix grouping/plot mismatch root causes** — ✅ completed.
   - Deterministic sort by selected mode exists in export flow.
   - Stable merge key strategy (`GROUP_KEY`/`REPORT_ID`/composite fallback) and duplicate-key warning path are implemented.
   - Violin label/value payload now filters NaN-only buckets and preserves aligned labels/values from a single grouped source before plotting.
2. **Introduce dataclass contracts in `modules/contracts.py`** — ✅ completed for parse/export entrypoints.
   - `ParseRequest`, `AppPaths`, `ExportOptions`, `GroupingAssignment`, and `ExportRequest` exist.
   - Validation helpers now cover parse, paths, options, grouping, and end-to-end export request validation.
   - Parse and export thread entrypoints now require validated request dataclasses from UI call sites.
3. **Decompose heavy workers into testable units** — 🔴 not started.
4. **Create shared DB utilities module (`db.py`)** — 🔴 not started.
5. **Performance cleanup** — 🔴 not started.

### Scope
1. Fix grouping/plot mismatch root causes.
   - Merge grouping via stable unique key (prefer `REPORT_ID`; fallback composite fingerprint).
   - Add duplicate-key detection/warnings.
   - Enforce deterministic sort in summary path based on selected mode (`date`/`sample`).
   - Build violin values and labels from the same grouped object.
2. Introduce dataclass contracts in `modules/contracts.py`.
   - `ParseRequest`, `AppPaths`, `ExportOptions`, `GroupingAssignment`, `ExportRequest`.
   - Add validators (`validate_export_options`, `validate_paths`, `validate_grouping_df`).
3. Decompose heavy workers into testable units.
   - Split `ExportDataThread` into acquisition, workbook writing, stats/chart generation.
   - Add pure functions for formulas/statistics.
4. Create shared DB utilities module (`db.py`).
   - Connection handling, retry policy, query helpers.
5. Performance cleanup.
   - Cache workbook formats.
   - Remove redundant matplotlib figure creation.
   - Precompute expensive loop constants.

### Acceptance criteria
- Grouped plots are deterministic and label/data aligned on regression datasets.
- Parse/export entrypoints accept request dataclasses rather than long primitive arg lists.
- No measurable regressions in existing export outputs.

---

## Phase 3 — Documentation + developer quality baseline (Priority P2, 1–2 days)

### Status: 🔴 Not implemented

### Implementation checklist
1. **Rewrite `README.md` (quickstart/setup/run/package/troubleshooting)** — 🟡 partial (overview exists, but no full quickstart/troubleshooting baseline).
2. **Dependency hygiene (UTF-8 + split runtime/dev/build)** — 🔴 not started.
3. **Baseline CI (`compileall`, lint, smoke tests)** — 🔴 not started.
4. **Add `CONTRIBUTING.md` + architecture notes** — 🔴 not started.

### Scope
1. Rewrite `README.md`.
   - Quickstart.
   - Environment setup.
   - Run/package commands.
   - Troubleshooting.
2. Dependency hygiene.
   - Normalize `requirements.txt` to UTF-8.
   - Split runtime vs dev/build dependencies where practical.
3. Add baseline CI.
   - `compileall`.
   - Lint step.
   - Minimal smoke tests.
4. Add `CONTRIBUTING.md` and architecture notes.
   - Module interaction overview.
   - Dataclass contract usage.
   - Parse → DB → group/filter → export flow.

### Acceptance criteria
- New contributor can install, run, and package from docs alone.
- CI runs on each PR with basic quality gates.

---

## Phase 4 — Test coverage baseline (Priority P1/P2, 2–4 days)

### Status: 🟡 Partially implemented

### Implementation checklist
- **Unit tests for Phase 0 regressions** — ✅ done.
- **Additional unit tests (grouping merge key correctness + deterministic label/value order)** — 🔴 not started.
- **Integration test (parse → DB → export happy path)** — 🔴 not started.

### Unit tests
- License parsing and validation edge cases.
- Sheet naming sanitizer/uniqueness behavior.
- Cp/Cpk behavior for sigma=0, NaN, empty samples.
- Dedupe behavior for same filename across distinct directories.
- Grouping merge key correctness and deterministic label/value order.

### Integration test
- Lightweight parse → DB → export happy path using sample fixtures.

### Acceptance criteria
- Core regression suite protects known failure modes.
- Happy-path integration verifies end-to-end viability.

---


## Branching and merge strategy
- Primary implementation branch: `roadmap/phase-implementation`.
- Use short-lived child branches per phase (for example, `roadmap/phase-0-safety-hotfixes`, `roadmap/phase-1-reliability`).
- Each phase lands only after:
  1. implementation is complete for that phase scope,
  2. phase tests/checks pass,
  3. PR review is approved.
- Merge sequence to `main` is strictly phase-ordered (Phase 0 -> 1 -> 2 -> 3 -> 4).
- If a later phase depends on earlier unfinished work, keep it behind feature flags or defer until prior phase is merged.

---

## Milestone sequence
1. **Week 1:** Phase 0 + grouping correctness tests from Phase 2.
2. **Week 2:** Phase 1 (cooperative cancellation + logger behavior).
3. **Week 3:** Remaining Phase 2 structure/performance work + grouping alignment hardening.
4. **Week 4:** Phase 3 docs/CI + Phase 4 coverage baseline.

---

## Risk management
- **Key migration risk:** add fallback mapping and migration guardrails.
- **Output drift risk during refactor:** snapshot/golden checks for representative exports.
- **Cancellation race/deadlock risk:** bounded waits + explicit state transitions + logging.
- **Abstraction overhead risk:** incremental rollouts and strict interface boundaries.

---

## Definition of Done (global)
- [x] Grouping mismatch bug fixed and covered by tests.
- [x] Export/parse entrypoints use dataclass contracts (grouping internals still being hardened).
- [x] Normal operation avoids forced thread termination.
- [x] Reliability fixes merged for dedupe, sheet naming, stats edge cases, and license parsing.
- [ ] Docs updated with architecture and operating instructions.
- [ ] CI executes compile + tests + lint successfully.

## Remaining execution order (updated)
1. Execute remaining **Phase 2** structural items in small mergeable PRs:
   - worker decomposition,
   - DB utilities.
2. Execute **Phase 3** developer baseline (README quickstart, dependency cleanup, CI, contributing docs).
3. Execute **Phase 4** coverage expansion (grouping regressions + integration happy path).
