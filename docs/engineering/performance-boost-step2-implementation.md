# Performance Boost STEP2 — implementation plan

- **Status:** in progress. Tracker: Issue #1148. Audit report (Polish, PO): [`performance-boost-step2.md`](performance-boost-step2.md)
  (plan of PRs: §9). Audit branch and draft PR: `perf/step2-audit`, #1149.
- **Branch:** `perf/step2-boost`, created from `perf/step2-audit` at `013aafac` (audit base `78d5d775` + STEP2
  harnesses, opt-in instrumentation and PoC code). One commit series per packet; no merge, release or branch cleanup.
- **Coordinator:** Claude Opus 5.5 (Claude Code). Owns slicing, integration, verification, benchmarks, CI dispatch
  and reporting. Product decisions: PO.
- **Routing:** development-routing v1.1 (`SKILL.md` sha256 `fabf1230…`), model map v1.0 (`6dd04ecc…`).
  P01–P07: OpenAI capacity UNKNOWN (last observation 2026-10-19 17:52 UTC, 79% used), so the CLAUDE_ONLY route
  applied: one implementation packet at a time, `bounded_worker` (Claude Sonnet 5.5, high) for bounded slices,
  `claude_coordinator` (Claude Opus 5.5, high) for the launcher and the process-pool slices.
  From 2026-10-20 ≈18:45 CEST the user confirmed Codex capacity, so mode BOTH applies to P08–P13: `implementer`
  (Codex `gpt-6.1-sol`, high) in a detached worktree per packet, without commits (sandbox); the coordinator
  reviews, commits and cherry-picks. Usage is observed before and after every dispatch. Throughout: a fresh
  `independent_reviewer` (Claude Opus 5.5, high) per review batch plus at most one delta review, and at most
  two auxiliary contexts at once.

## 1. Scope

In scope: plan items A1–A3, B1–B5, C1–C4, D1–D2 from report §9.

Not changed without a PO decision (report §9, batch E): E1 automatic chart density, E2 supervisor second hash,
E3 background verification on the second launch, E4 smaller payload. Current behaviour is kept.

Deferred (proposed, needs PO confirmation):

| Item | Reason | Preserved seam |
|---|---|---|
| D3 persistent OCR worker in the EXE | no OCR workload or Windows OCR qualification available here; gain unmeasured | OCR worker entry and Job-object handling unchanged |
| D4 native code in the EXE | separate track #908 (packaging, parity evidence, native builds) | `auto` native selection unchanged |

## 2. Rules for every packet

**MUST**

1. Same results: identical data, rows, statistics, workbook and dashboard content, ordering and saved state as
   the base. Write the equivalence test against the current code first, then change the code.
2. No reduction of computation scope, chart quality, integrity checks or durability.
3. Qt widgets only on the GUI thread; work moves to `QThread` workers or process pools; no
   `processEvents()` from worker threads in new code.
4. SQLite: one writer per file; readers use their own connections; every `sqlite3.connect` is wrapped in
   `contextlib.closing` (repository guard).
5. Process pools use the spawn context from `metroliza.shared.compute_worker` and keep the packaged-Windows
   policy of #1134/#1138 (import prepare workers stay opt-in in the EXE).
6. Every new tracked file gets an owner in `docs/quality/bug_sweep/coverage.json`; no new third-party
   dependency.
7. Run focused tests plus the repository guards after `git add`: `ruff check .`,
   `tests/test_complexity_ratchet.py`, `tests/test_bug_sweep_coverage.py`, `tests/test_db_utils.py`,
   `tests/test_runtime_print_guard.py`, `tests/test_docs_markdown_links.py`, and every test file that greps
   for a changed symbol. Qt tests run with `env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen`.
8. Repository files never mention scratchpad paths, local tools or the local machine.

**Forbidden:** push, PR or Issue edits, merge, rebase, `git stash`, branch deletion, CI workflow changes outside
the packet, dependency installs, changes to the machine (power profile, services), running benchmarks
while another heavy job runs.

**Handback:** commits on `perf/step2-boost`, focused test commands and results, equivalence evidence, one
harness timing of the affected scenario, open risks, files changed.

## 3. Packets (in execution order)

Baseline numbers: report §4 (Linux, balanced profile, synthetic data). Targets are measured on the same
machine and profile as the baseline.

| # | Item | Class / route | Main files | Baseline → target | Equivalence and tests |
|---:|---|---|---|---|---|
| P01 | A1 launcher splash, production | CRITICAL-adjacent / claude_coordinator | `packaging/launcher/src/**`, `src/metroliza/app/launcher_splash.py`, `startup_splash.py`, supervisor, `THIRD_PARTY_NOTICES` | warm start 1068 ms without a window → ≤150 ms; cold: 1.95 s blank → 0; focus 6/14 → all | progress-window fallback when the splash is disabled or fails; splash during the exit-75 repair; no splash for a second instance; close path when the window thread starts late; status text encoded with `errors="replace"`; `cargo test`; Windows CI timeline and launcher qualification |
| P02 | B1 Characteristic Mapping | BOUNDED / bounded_worker | `reports/characteristic_mapping_service.py`, `ui/characteristic_mapping_dialog.py` | 163 s GUI freeze → <2 s, no freeze | single query (window function) returning the same metrics, counts and sample references in the same order (`LOWER(reference), reference`); current and legacy schema; full comparison on the small DB, 30-metric sample on the 1500-report DB |
| P03 | B2 + B4 Industrial Data | FEATURE / bounded_worker | `industrial/industrial_tabular_bridge.py`, `ui/industrial_data_dialog.py`, `ui/industrial_analytics_dialog.py`, `industrial/oznak_adapter.py` | bridge 10.0 s freeze → open <1 s, work in a worker; Industrial Data open 0.78 s → ≤0.4 s | COUNT once per filter change, facets in SQL; identical metadata, facets and counts (#1145 scope rules); `oznak` status text identical without importing the package on the GUI thread |
| P04 | B3 Grouping | BOUNDED / bounded_worker | `tabular/data_grouping_service.py`, `ui/data_grouping.py` | 1.23 s freeze → <0.3 s | vectorised aggregation; identical groups, keys, order and saved state |
| P05 | C4 import | CRITICAL (persistence) / bounded_worker | `reports/report_repository.py`, `reports/report_schema.py`, `parsing/report_parser_factory.py`, `parsing/parse_reports_thread.py` | 12.9 s; schema readiness 13%, registry 8% of the profile → −≈20% | schema readiness re-checked when `PRAGMA schema_version` changes; registry snapshot once per import with a generation check that fails closed; identical rows (full DB comparison); #1132 re-verification and #1137 commit/checkpoint order unchanged |
| P06 | C1 compute budget | FEATURE / bounded_worker | new `shared/compute_budget.py`; import prepare, render and review pools | — | one worker budget (logical CPUs − 1, env override); BLAS/OMP/MKL = 1 thread in pool workers (measured −12% wall, −47% CPU in Extended); identical results at 1/2/4/8 workers |
| P07 | C2 Review reports in a pool | FEATURE / claude_coordinator | `parsing/preflight.py`, `parsing/metadata_review.py`, `ui/parsing_dialog.py` | 25.6 s → ≤9 s; code 19.2 → 6.6 s at 4 workers | identical entries (deduplication in order), readings and overrides; file-change detection; registry generation consistent in workers; streamed rows, throttled signals; serial fallback; EXE policy of #1134 |
| P08 | C3 Extended plots | FEATURE / bounded_worker | `exporting/export_summary_render_pool.py`, `exporting/export_data_thread.py` | 48 groups 35.3 s → ≤26 s at 4 workers; dashboard 50.7 s serial → parallel | one pool per export, workers from the budget; density switch still discards pending results (E1 untouched); identical XLSX/HTML content at 1/2/4/8 workers |
| P09 | D2 CSV analytics | FEATURE / bounded_worker | `industrial/industrial_analytics_workflow.py`, `tabular/tabular_analytics_service.py` | 50.3 s → <20 s; CSV load 4.93 s → lower | one distribution fit per series shared by histogram, table and PNG; vectorised conversions; identical statistics (#1133) and dashboard values; no sampling |
| P10 | D1 chart render | FEATURE / bounded_worker | chart rendering in `exporting/export_data_thread.py`, `charts/**` | ≈1.0 s per group in one process → −30% | font lookup cache, fewer text layout passes, faster lossless PNG; pixel parity with #1126 |
| P11 | A2 warm-up off the GUI thread | FEATURE / bounded_worker | `ui/main_window.py` | GUI stall after first paint 180 ms → <50 ms; first Export click 1.72 s freeze → ≤0.2 s | export and realtime modules in the warm-up; opening a tool during warm-up waits for that module; non-daemon thread joined on close; Agg before `pyplot`; no Qt objects created at import (test) |
| P12 | A3 loading indicator | FEATURE / bounded_worker | `ui/worker_progress_dialog.py` + dialogs from report §7 | indicator 0.98–2.7 s after the click → ≤1.1 s; frames 53–100% → ≥90% | threshold from the click; `QMovie` only while visible; dialog released; close after the result is applied; throttled progress; wire the 7 operations without an indicator and the 3 short freezes; cancel/error/close paths unchanged |
| P13 | B5 Modify DB | FEATURE / bounded_worker | `ui/modify_db.py`, `ui/modify_db_records.py` | open 0.18 s, records 2.67 s → no GUI freeze, records faster | model/view for the open table; faster record loader; golden tests of #1121, edits and undo |

Review batches (fresh `independent_reviewer`, one full review plus at most one delta each): R1 = P01;
R2 = P02–P05; R3 = P06–P09 with the R2 fixes and the detached-thread/QApplication fixes; R4 = P10–P13
(P10 moved from R3 to R4 so that R3 can start while P10 and P11 run in parallel).

## 4. Before/after protocol

- Same machine, power profile `balanced` (recorded before and after with the power probe), synthetic data.
- Clean detached worktrees of the base (`78d5d775`) and of the package head, the same copy of
  `scripts/benchmark_ui_flows.py`; versions alternated per scenario, order flipped per run, 3 runs per UI
  scenario, never two benchmarks at once.
- Output equivalence: workbook content hash without `docProps`, dashboard content without timestamps, DB
  dumps after import, Characteristic Mapping and Review results compared item by item.
- Windows: `windows-first-run-timeline` (opt-in CI job) for P01 with the base and the package launcher on the
  same onedir, plus `Native launcher qualification`.
- Results: report §4.2 (new), measurements JSON, Issue #1148.
