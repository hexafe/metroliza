# OCR Benchmarking Master Handoff

Last updated: 2026-04-28 22:09 Europe/Warsaw

This is the canonical next-session entry point for Metroliza OCR benchmarking,
OCR acceleration, and parser metadata performance work.

## Mandatory Update Rule

After every OCR benchmark, implementation step, validation step, or hardware
experiment, update this file before ending the session.

Each update must include:

- current status,
- subagents/model split used for the step, or an explicit note that the step was
  small enough to keep local,
- exact non-confidential command shape,
- benchmark numbers,
- validation result,
- what changed in code/docs/package config,
- blockers or caveats,
- next recommended step.

Do not leave OCR benchmark status only in chat, ignored benchmark artifacts, or
temporary notes.

For broad OCR work, use subagents with task-appropriate models/effort to reduce
context loss and improve coverage. Split independent work into bounded tracks,
for example:

- confidentiality scan,
- parser/database persistence analysis,
- UI/progress integration analysis,
- benchmark validation,
- packaging/release validation.

Keep implementation ownership clear so concurrent agents do not edit the same
files. Record the split and outcome in this document after each step.

## Confidentiality Rule

The GitHub repository must not contain real report files or real report-derived
identifiers/data, even when the files are useful for benchmarking. Real-report
PDFs, report basenames, local corpus paths, raw OCR text, raw metadata values,
screenshots, crop images, and raw benchmark payloads must stay out of Git unless
they have been deliberately scrubbed into synthetic/non-identifying fixtures.

This tracked Git document must never contain:

- real report files,
- report filenames,
- report directory paths,
- customer/project-specific file paths,
- raw report metadata values,
- OCR text output,
- screenshots or crop contents,
- raw benchmark JSON payloads that include report paths or names.

Raw benchmark artifacts may contain local filenames/paths and must stay under
ignored local directories such as `benchmark_results/`. Do not force-add those
artifacts unless they have been scrubbed.

Before publishing, run a confidentiality scan over tracked and untracked
Git-bound files. At minimum, scan for:

- local corpus path fragments,
- report filename patterns,
- known external corpus basenames,
- accidental benchmark JSON or manifest files outside ignored paths.

Current 2026-04-29 audit result: Git-bound tracked and untracked non-ignored
files were scanned against saved-corpus report basenames/stems and local corpus
path markers. No exact real-report identifier hits were found. Git-bound binary
data files are limited to existing documentation/test fixtures, not raw OCR
benchmark reports; `benchmark_results/` remains ignored.

## Current Status

OpenVINO CPU is the best locally proven complete-metadata OCR backend.

It is validated through both:

- crop-level OCR over the saved 272-PDF benchmark corpus,
- full `CMMReportParser` complete-metadata parser path over the same saved
  272-PDF benchmark corpus.

The GUI import default remains light metadata for throughput. Complete metadata
is still useful when OCR-only header fields matter, but it is too slow to use as
the default blocking import path.

The preferred product direction is:

1. fast light import,
2. optional user-enabled background complete metadata enrichment,
3. visible non-blocking progress,
4. selective metadata merge that does not blindly overwrite reliable light
   metadata.

Quick analysis/import must stay light by default. Rich/background parsing must
only run when the user explicitly enables it in the UI for the current workflow
or a persisted preference designed for that purpose.

As of the latest local benchmark, the opt-in enrichment path exists inside the
parser worker, is synthetically validated, and has completed the saved-manifest
OpenVINO CPU benchmark. It preserves measurement rows and gives the user a fast
light-import phase before the slower OCR enrichment phase.

## Implementation Status

Implemented:

- `ParseRequest.metadata_parsing_mode`.
- `ParseRequest.run_background_metadata_enrichment`.
- Parser GUI metadata mode selector:
  - `Light metadata`,
  - `Complete metadata`.
- Parser GUI opt-in checkbox for post-import metadata enrichment.
- GUI default is light metadata.
- Programmatic `ParseRequest` default remains complete metadata.
- Light metadata skips header OCR fallback and records
  `header_ocr_skipped = "light_metadata_mode"`.
- Opt-in background complete-metadata enrichment after light import inside the
  parser worker.
- Enrichment progress stage split and cooperative cancellation through the
  existing parser progress dialog.
- Metadata-only enrichment persistence that updates metadata rows without
  replacing measurement rows.
- Conservative enrichment merge policy:
  - existing non-empty light metadata is preserved for stable filename-backed
    fields,
  - OCR-only fields can be filled or updated from complete metadata,
  - manual metadata overrides remain preserved.
- Saved-manifest opt-in enrichment benchmark with OpenVINO CPU.
- Standalone main-window metadata enrichment action for existing databases.
- Modeless main-window enrichment progress surface with cooperative cancel.
- Export current-state notice while metadata enrichment is active.
- Env-driven RapidOCR runtime selection:
  - `METROLIZA_HEADER_OCR_ENGINE=onnxruntime|openvino|tensorrt`,
  - `METROLIZA_HEADER_OCR_ACCELERATOR=cpu|cuda|dml|coreml`,
  - `METROLIZA_HEADER_OCR_DEVICE_ID`,
  - `METROLIZA_HEADER_OCR_CACHE_DIR`,
  - OpenVINO tuning env vars,
  - TensorRT cache/precision env vars.
- Parser diagnostics record:
  - `header_ocr_runtime_engine`,
  - `header_ocr_runtime_accelerator`.
- Benchmark helper supports saved manifests:
  - `scripts/benchmark_header_ocr_modes.py --manifest <LOCAL_CORPUS_MANIFEST_JSON>`.
- OpenVINO tuning matrix helper:
  - `scripts/benchmark_openvino_tuning_matrix.py`.
- OpenVINO is included in packaged OCR requirements and packaging config:
  - `requirements-ocr.txt`,
  - PyInstaller spec,
  - Nuitka helper,
  - packaged OCR validator,
  - third-party notices,
  - Windows OCR runtime diagnostics.

Not implemented yet:

- persisted enrichment preference,
- DirectML benchmark on Windows Intel/AMD hardware,
- CUDA/TensorRT benchmark on NVIDIA hardware,
- custom OpenVINO GPU/AUTO/NPU wrapper.

## 2026-04-25 Step Log

## 2026-04-26 Step Log

## 2026-04-28 Step Log

### Tests Cleanup Freeze And OCR Enrichment Stabilization

Status:

- implementation and validation step completed,
- test cleanup was re-verified as frozen with no broad deletion target,
- shared complete-metadata enrichment persistence helpers were added,
- standalone metadata enrichment discovery now parses metadata JSON and durable
  columns instead of relying on broad raw `metadata_json LIKE` markers,
- parser-dialog rich metadata enrichment is disabled and cleared when Complete
  metadata mode is selected,
- export dialog refreshes the active-enrichment notice before export worker
  startup,
- continuation handoff written to
  `docs/roadmaps/OCR_TEST_CLEANUP_NEXT_SESSION_README.md`.

Subagents/model split:

- Jason explorer, GPT-5.4 Mini, medium effort: read-only test cleanup
  verification,
- Arendt explorer, GPT-5.4, medium effort: read-only enrichment duplication and
  discovery analysis,
- Hegel explorer, GPT-5.4 Mini, medium effort: read-only parser/export UI
  analysis,
- local implementation: shared enrichment helpers, parsed-JSON discovery,
  parser/export UI updates, regression tests, and handoff docs.

Non-confidential command shapes:

```bash
python -m pytest --collect-only -q tests
python -m pytest <focused_ocr_enrichment_tests> -q
QT_QPA_PLATFORM=offscreen python -m pytest <focused_parser_export_ui_tests> -q
python -m ruff check <touched_python_files_and_tests>
python -m py_compile <touched_python_files>
```

Benchmark numbers:

- no OCR corpus benchmark in this step.

Validation result:

- focused enrichment regression slice: `4 passed`,
- focused parser/export UI slice: `9 passed`,
- focused OCR/persistence/package/UI slice: `65 passed`,
- ruff over touched Python files/tests: passed,
- py_compile over touched Python files: passed,
- full test collection: `1259 tests collected`.

Files changed in this step:

- `modules/parse_reports_thread.py`,
- `modules/metadata_enrichment_thread.py`,
- `modules/parsing_dialog.py`,
- `modules/export_dialog.py`,
- `tests/test_metadata_enrichment_thread.py`,
- `tests/test_parsing_dialog_selection_flow.py`,
- `tests/test_export_presets.py`,
- `docs/roadmaps/OCR_TEST_CLEANUP_NEXT_SESSION_README.md`,
- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- the initial focused implementation validation did not include the real PDF
  GUI smoke or saved 272-PDF OCR benchmark; both gates were completed in the
  follow-up runtime gate below,
- the worktree already contained many OCR/report-metadata/test edits before this
  pass, so future commits should stage intentionally.

Next recommended step:

- run a small real-DB GUI smoke covering light import with enrichment enabled,
  standalone enrichment, and export while enrichment is active, then run
  `python scripts/validate_packaged_pdf_parser.py --require-header-ocr`.

### Runtime Gate Completion After Tests/OCR Stabilization

Status:

- runtime gate completed,
- real-DB light import plus opt-in complete metadata enrichment passed on one
  local report from the ignored/example corpus,
- standalone enrichment mutation preserved existing measurement rows,
- export dialog showed the active-enrichment current-state notice before export
  worker startup,
- packaged OCR validator passed,
- saved 272-PDF OpenVINO CPU complete-metadata acceptance benchmark passed.

Subagents/model split:

- Hume worker, GPT-5.4, medium effort: GUI/runtime smoke using temporary files
  only,
- Turing worker, GPT-5.4 Mini, medium effort: packaged OCR dependency
  validation,
- Dewey explorer, GPT-5.4, medium effort: saved-manifest benchmark readiness
  and one-report OpenVINO smoke,
- Pascal explorer, GPT-5.4 Mini, medium effort: release hygiene, test
  collection, and confidentiality checks,
- local execution: full saved 272-PDF OpenVINO CPU acceptance benchmark and
  roadmap updates.

Non-confidential command shapes:

```bash
QT_QPA_PLATFORM=offscreen python <TEMP_REAL_DB_GUI_SMOKE_SCRIPT>
python scripts/validate_packaged_pdf_parser.py --require-header-ocr
python -m pytest --collect-only -q tests
METROLIZA_HEADER_OCR_ENGINE=openvino python scripts/benchmark_header_ocr_modes.py \
  --manifest <LOCAL_CORPUS_MANIFEST_JSON> \
  --mode complete \
  --limit 0 \
  --progress-every 25 \
  --compact \
  --output <TEMP_OUTPUT_JSON>
```

Benchmark numbers:

- saved manifest PDFs found/selected: `272 / 272`,
- completed mode/PDF runs: `272 / 272`,
- OK/error count: `272 / 0`,
- stopped due to budget: `false`,
- total wall time: `332.2351s`,
- complete-mode summed parser wall: `331.5432s`,
- average parser wall per report: `1.2189s`,
- summed OCR runtime: `290.95s`,
- average OCR runtime per report: `1.0697s`,
- header extraction mode: `ocr = 272`,
- OCR runtime engine: `openvino = 272`,
- runtime accelerator: `cpu`.

Validation result:

- real-DB smoke persisted one parsed report with `223` measurement rows,
- metadata-only enrichment preserved the exact measurement row count,
- standalone enrichment discovery returned no work after the report was already
  enriched,
- export dialog notice while enrichment was active:
  `Metadata enrichment is running. Export will use the current database state.`,
- packaged OCR validator result: passed, validating header OCR dependencies and
  3 vendored model files,
- full test collection: `1259 tests collected`,
- tracked-files confidentiality scan found no corpus/report-path leaks in
  committed files; ignored benchmark artifacts remain ignored.

Files changed:

- `docs/roadmaps/OCR_TEST_CLEANUP_NEXT_SESSION_README.md`,
- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- the benchmark output JSON was written under `/tmp` and contains local report
  paths; do not copy it into tracked files,
- DirectML, CUDA, TensorRT, and OpenVINO GPU/AUTO/NPU still require target
  hardware validation,
- the worktree remains dirty with many pre-existing OCR/report-metadata/test
  changes, so future commits should stage intentionally.

Next recommended step:

- keep test cleanup frozen and rerun the saved OCR acceptance benchmark only if
  OCR/parser behavior changes again; before publishing, run the publication
  checklist and stage only intended files.

### Standalone Modeless Enrichment Resume

Status:

- implementation step started,
- confirmed this document is the current tracked OCR handoff,
- confirmed the latest completed benchmark already covers the saved 272-PDF
  light-import plus opt-in OpenVINO CPU enrichment path,
- proceeding with the next recorded plan item: standalone modeless
  main-window metadata enrichment for existing databases.

Subagents/model split:

- Pauli explorer, GPT-5.4 Mini, low effort: main-window/export integration
  points,
- Ptolemy explorer, GPT-5.4 Mini, low effort: existing DB worklist,
  repository, and worker boundaries,
- local implementation: standalone worker, main-window action/progress surface,
  focused tests, validation, and this handoff update.

Non-confidential command shapes:

```bash
git status --short --branch
sed -n "<handoff-ranges>" docs/roadmaps/OCR_BENCHMARKING_MASTER.md
rg -n "<metadata-enrichment-symbols>" modules tests docs/roadmaps/OCR_BENCHMARKING_MASTER.md
```

Benchmark numbers:

- no OCR corpus benchmark in this resume/status step.

Validation result:

- pending implementation and focused validation.

Files changed:

- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- the current working tree already contains many OCR/report-metadata edits, so
  implementation will keep the change scoped and avoid reverting unrelated
  work.

Next recommended step:

- implement the standalone modeless enrichment action and verify export remains
  launchable while enrichment is active.

### Standalone Modeless Enrichment Implementation

Status:

- implementation step completed,
- added a DB-first standalone metadata enrichment worker for existing databases,
- added a main-window `Enrich Metadata` action/button with modeless progress and
  cooperative cancel,
- export remains launchable while enrichment is active and now shows an inline
  current-state notice instead of blocking the export flow.

Subagents/model split:

- Pauli explorer, GPT-5.4 Mini, low effort: confirmed `MainWindow` owns the
  correct modeless state and export should get a non-blocking notice,
- Ptolemy explorer, GPT-5.4 Mini, low effort: confirmed the standalone worker
  needs a DB-first worklist and should reuse metadata-only persistence,
- local implementation: worker module, main-window integration, export notice,
  and focused worker tests.

Non-confidential command shapes:

```bash
rg -n "<main-window-and-enrichment-symbols>" modules tests docs/roadmaps/OCR_BENCHMARKING_MASTER.md
sed -n "<relevant-ranges>" modules/main_window.py modules/metadata_enrichment_thread.py modules/export_dialog.py
```

Benchmark numbers:

- no OCR corpus benchmark in this implementation step.

Validation result:

- focused enrichment/schema persistence tests: `4 passed`,
- focused enrichment/parser-dialog/persistence slice with Qt offscreen:
  `10 passed`,
- ruff over touched Python files: passed,
- py_compile over touched Python files/tests: passed,
- confidentiality scan over this step's touched files had no local corpus path
  hits; matches were limited to synthetic `.pdf` fixture names in tests and
  pre-existing non-confidential historical benchmark wording in this handoff.

Files changed:

- `modules/metadata_enrichment_thread.py`,
- `modules/main_window.py`,
- `modules/export_dialog.py`,
- `tests/test_metadata_enrichment_thread.py`,
- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- the standalone worklist uses persisted source file paths; moved or missing
  source PDFs are skipped for now and should get a clearer user-facing warning
  in a follow-up if needed,
- no saved-corpus benchmark was rerun because this step changes UI/worklist
  orchestration, not the OCR backend itself.

Next recommended step:

- run a small real-DB GUI smoke on a local database to confirm the modeless
  progress surface stays usable during export, then decide whether to add a
  richer missing-source warning/resume details view.

### Confidentiality Cleanup And Enrichment Constraint

Status:

- completed tracked confidentiality cleanup for known report/corpus identifiers,
- recorded the product constraint that rich/background parsing is user-enabled
  only and quick analysis stays light by default,
- mapped the metadata-only persistence approach for the future enrichment worker.

Subagents/model split:

- Boole explorer, inherited GPT-5 model: Git-bound confidentiality scan,
- Arendt explorer, inherited GPT-5 model: persistence/thread/UI hook analysis,
- local implementation: sanitized tracked docs/scripts/modules/tests and updated
  this master handoff.

Non-confidential command shapes:

```bash
rg -n "<known-confidential-patterns>" docs scripts modules tests
jq -r "<manifest-basename-expression>" <IGNORED_LOCAL_CORPUS_MANIFEST_JSON> | rg -F -f <TEMP_PATTERN_FILE> <GIT_BOUND_FILES>
python -m pytest <metadata_and_ocr_fixture_tests> -q
```

Validation result:

- broad scrub scan over Git-bound docs/scripts/modules/tests: no hits for the
  checked confidential corpus/report patterns,
- exact basename scan from the ignored saved benchmark manifest over tracked and
  untracked non-ignored files: no hits,
- synthetic metadata/OCR fixture tests: `29 passed`.

Files changed:

- sanitized the OCR status report and public script usage examples,
- replaced report-derived OCR/operator/part-name fixtures with synthetic values,
- removed report-derived operator/profile aliases from tracked code,
- kept ignored benchmark artifacts untouched.

Caveats:

- ignored `benchmark_results/` still contains local raw benchmark artifacts and
  must remain ignored,
- output from benchmark helper scripts may contain local paths/report names and
  should not be staged without scrubbing.

Next recommended step:

- implement opt-in background rich metadata enrichment behind an explicit UI
  control, using metadata-only persistence so existing measurement rows are not
  deleted.

### Background Enrichment Persistence Implementation

Status:

- implementation step completed,
- fixed the background enrichment persistence path to call the metadata-only
  repository API instead of a non-existent full-payload helper,
- added a conservative selective merge before persistence:
  - existing non-empty light metadata is preserved for stable filename-backed
    fields,
  - OCR-only fields can be filled or updated from complete metadata,
  - manual overrides recorded in metadata JSON remain preserved,
  - measurement rows are not touched.

Subagents/model split:

- Hilbert explorer, GPT-5.4 Mini: metadata-only persistence and merge boundary
  analysis,
- Laplace explorer, GPT-5.4 Mini: UI/progress/cancel integration analysis,
- local implementation: parser-thread merge and persistence call update.

Non-confidential command shapes:

```bash
rg -n "<metadata-enrichment-symbols>" modules tests docs/roadmaps/OCR_BENCHMARKING_MASTER.md
sed -n "<relevant-ranges>" modules/parse_reports_thread.py modules/report_repository.py
```

Benchmark numbers:

- no OCR corpus benchmark in this implementation step.

Validation result:

- pending focused regression tests and lint/compile checks.

Files changed:

- `modules/parse_reports_thread.py`,
- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- the complete-pass candidate table still stores complete extraction candidates;
  final selected metadata may preserve existing light values when the merge
  policy keeps stable fields unchanged.

Next recommended step:

- add focused worker-flow tests for complete-mode forcing, metadata-only
  persistence, measurement-row preservation, raw-report JSON marker preservation,
  and selective merge behavior.

### Background Enrichment Regression Tests Added

Status:

- implementation step completed,
- added synthetic regression coverage for the enrichment batch helper,
  conservative merge policy, complete-mode forcing, metadata-only persistence,
  measurement-row preservation, and raw-report JSON marker preservation.

Subagents/model split:

- no additional subagent; this was a focused local test implementation after the
  persistence/UI explorers returned.

Non-confidential command shapes:

```bash
sed -n "<test-helper-ranges>" tests/test_thread_flow_helpers.py
```

Benchmark numbers:

- no OCR corpus benchmark in this test implementation step.

Validation result:

- pending test execution.

Files changed:

- `tests/test_thread_flow_helpers.py`,
- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- test fixtures use synthetic values only; they do not validate real OCR quality
  or the saved corpus runtime path.

Next recommended step:

- run focused tests, ruff, py_compile, and a confidentiality scan over Git-bound
  files changed by this step.

### Background Enrichment Validation

Status:

- validation step completed.

Subagents/model split:

- no additional subagent; validation was local command execution.

Non-confidential command shapes:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest <focused_parse_metadata_ocr_tests> -q
python -m ruff check <touched_python_files_and_related_tests>
python -m py_compile <touched_python_files>
rg -n "<local-path-confidentiality-patterns>" <touched_git_bound_files>
```

Benchmark numbers:

- no OCR corpus benchmark in this validation step.

Validation result:

- focused parse/metadata/OCR regression slice: `181 passed, 2 subtests passed`,
- ruff: passed,
- py_compile: passed,
- local-path confidentiality scan over touched Git-bound files: no hits,
- broader scan hits were limited to this handoff's own confidentiality-rule text
  and ignored-artifact placeholders.

Files changed:

- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- this validates the synthetic worker/repository behavior, not the saved
  272-PDF enrichment benchmark path.

Next recommended step:

- run the saved 272-PDF manifest through the enrichment path with OpenVINO CPU
  on a local machine that has the ignored manifest available, then compare
  runtime, metadata merge decisions, measurement row preservation, and database
  write behavior.

### Handoff Status Alignment

Status:

- documentation update completed,
- top-level implementation status now reflects that opt-in enrichment,
  metadata-only persistence, progress/cancel integration, and conservative merge
  behavior are implemented and synthetically validated,
- current recommended next steps now start with the saved-corpus enrichment
  benchmark instead of reimplementing the worker.

Subagents/model split:

- no additional subagent; this was a focused local handoff update.

Non-confidential command shapes:

```bash
sed -n "<summary-ranges>" docs/roadmaps/OCR_BENCHMARKING_MASTER.md
```

Benchmark numbers:

- no OCR corpus benchmark in this documentation step.

Validation result:

- documentation-only alignment; previous validation remains the latest code
  validation result.

Files changed:

- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- this alignment section was written before the full saved-manifest enrichment
  benchmark below; use the later benchmark section for current performance
  numbers.

Next recommended step:

- see the latest current recommended next steps near the end of this handoff.

### One-Report Enrichment Path Smoke

Status:

- benchmark smoke completed on the saved manifest path, limited to one report,
- exercised the real light-import then opt-in complete-enrichment worker path
  with OpenVINO CPU and four OCR threads,
- confirmed complete enrichment wrote OCR metadata while preserving measurement
  rows in the temporary database.

Subagents/model split:

- no additional subagent; this was local runtime verification.

Non-confidential command shape:

```bash
METROLIZA_HEADER_OCR_ENGINE=openvino METROLIZA_HEADER_OCR_THREADS=4 python -c "<light-import-then-enrichment-smoke>"
```

Benchmark numbers:

- reports: `1`,
- light import wall time: `0.2154s`,
- enrichment wall time: `5.0572s`,
- parse result: `1 / 1`,
- enrichment result: `1 / 1`,
- measurement rows preserved: `233 / 233`,
- header extraction mode after enrichment: `ocr`,
- enrichment marker in raw report JSON: present,
- merge summary: `6` preserved fields, `3` updated fields.

Validation result:

- passed.

Files changed:

- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- OpenVINO emitted a telemetry write warning in the sandboxed environment; OCR
  execution and persistence still completed,
- this is a cold one-report smoke and should not be used as the full saved-corpus
  performance number.

Next recommended step:

- run the full saved 272-PDF enrichment benchmark with the same OpenVINO CPU
  settings and compare aggregate runtime, merge decisions, measurement row
  preservation, and database write behavior.

### Full Saved-Manifest Enrichment Benchmark

Status:

- benchmark completed,
- ran light import first, then opt-in complete metadata enrichment through the
  parser worker on the saved manifest,
- used OpenVINO CPU with four OCR threads,
- preserved measurement rows and measurement counts.

Subagents/model split:

- no additional subagent; this was a local long-running benchmark.

Non-confidential command shape:

```bash
METROLIZA_HEADER_OCR_ENGINE=openvino METROLIZA_HEADER_OCR_THREADS=4 python <TEMP_ENRICHMENT_BENCHMARK_SCRIPT>
```

Benchmark numbers:

- manifest entries: `272`,
- unique persisted reports: `271`,
- duplicate-by-SHA explanation: 1 duplicate manifest entry,
- light import: `272 / 272`, `41.3569s`, `0.1520s/manifest-entry`,
- enrichment: `272 / 272`, `336.2871s`, `1.2363s/manifest-entry`,
- combined wall time: `377.6440s`, `1.3884s/manifest-entry`,
- measurement rows before enrichment: `23,569`,
- measurement rows after enrichment: `23,569`,
- enrichment markers: `271 / 271` persisted reports,
- post-enrichment header extraction mode: `ocr = 271`,
- post-enrichment parse status: `parsed_with_warnings = 271`.

Validation result:

- passed,
- measurement rows preserved,
- measurement count preserved,
- local duplicate check confirmed `272` manifest files and `271` unique
  SHA-256 hashes.

Files changed:

- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- benchmark used a temporary local script and temporary SQLite database,
- raw output artifacts were not written to tracked files,
- OpenVINO emitted the same telemetry write warning seen in the one-report
  smoke; OCR execution and persistence completed.

Next recommended step:

- decide whether the current parser-dialog enrichment UX is enough or whether a
  standalone main-window enrichment action or persisted preference is needed.

### Modeless Background Enrichment UX Decision

Status:

- implementation planning step completed,
- product direction selected for the next implementation pass:
  - add a standalone metadata enrichment action for existing databases,
  - run enrichment in a worker thread,
  - show modeless progress so the rest of the app remains usable,
  - allow export while enrichment is running, with clear current-state semantics.

Subagents/model split:

- no additional subagent; this was a focused local planning update.

Non-confidential command shape:

```bash
sed -n "<status-and-next-step-ranges>" docs/roadmaps/OCR_BENCHMARKING_MASTER.md
```

Benchmark numbers:

- no OCR benchmark in this planning step.

Validation result:

- documentation-only update.

Implementation notes:

- The existing parser-dialog enrichment progress UI is still application-modal
  and should not be used as the final UX for a standalone enrichment action.
- The next implementation should add a modeless progress surface, such as a
  status-bar panel, dock-like panel, or small non-modal progress dialog.
- Enrichment should keep using a background worker thread and cooperative
  cancellation.
- Enrichment should keep using the metadata-only persistence path so
  measurements are not rewritten.
- The user should be able to continue using the app, including export, while
  enrichment runs.
- Export concurrency policy:
  - export may run while enrichment is active,
  - export reads the metadata state available when its queries execute,
  - if enrichment is still active, show a concise warning that export may contain
    partially enriched metadata,
  - do not silently block export unless SQLite lock contention or a concrete
    data-integrity issue is detected.
- SQLite notes:
  - existing app connections use WAL mode,
  - per-report enrichment transactions should keep read contention low,
  - OCR and export can still compete for CPU, so both may slow down.

Acceptance criteria:

- Starting standalone enrichment does not make the main window application-modal.
- Export dialog can be opened while enrichment is running.
- Export can start while enrichment is running and either completes from the
  current DB state or shows a clear lock/error message.
- Enrichment progress shows processed/total counts, ETA when available, and
  cancellation.
- Cancellation stops after the current report and keeps already written metadata
  valid.
- Measurement row counts are unchanged before and after enrichment.
- If export starts during active enrichment, the user sees a non-blocking notice
  explaining that metadata may be partially enriched.

Files changed:

- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`.

Caveats:

- this is an implementation plan, not a code change,
- actual export/enrichment concurrency should be validated with a synthetic DB
  test and, ideally, one real local smoke using ignored benchmark inputs.

Next recommended step:

- implement the standalone modeless enrichment action and its export-concurrency
  notice.

## Benchmark Corpus Notes

There are two local corpus sizes mentioned in historical notes:

- a saved 272-PDF benchmark corpus manifest,
- an older larger local tree with 4,333 PDF files.

For apples-to-apples OCR acceleration comparisons, use the saved 272-PDF
manifest. Do not write the manifest contents, report names, or report paths into
tracked docs.

Use command shape:

```bash
METROLIZA_HEADER_OCR_ENGINE=openvino python scripts/benchmark_header_ocr_modes.py \
  --manifest <LOCAL_CORPUS_MANIFEST_JSON> \
  --mode complete \
  --limit 0 \
  --progress-every 10 \
  --output <IGNORED_LOCAL_OUTPUT_JSON>
```

The local manifest and output JSON are intentionally ignored artifacts because
they contain report paths/names.

## Full-Corpus Benchmarks

### 272-PDF Saved Benchmark Corpus

Light metadata:

- result: `272 / 272` OK,
- total wall time: `23.0449s`,
- average wall time: `0.0847s/report`,
- OCR: skipped,
- header extraction mode: `none = 272`,
- OCR-only nulls:
  - `report_time = 272`,
  - `revision = 272`,
  - `operator_name = 272`,
  - `comment = 272`.

Complete metadata, ONNX Runtime CPU:

- result: `272 / 272` OK,
- total wall time: `793.1743s`,
- average wall time: `2.9161s/report`,
- summed header OCR runtime: `753.7865s`,
- average header OCR runtime: `2.7713s/report`,
- header extraction mode: `ocr = 272`,
- header OCR errors: `0`,
- OCR-only coverage:
  - `report_time`: filled for all 272,
  - `revision`: filled for 235,
  - `operator_name`: filled for 239,
  - `comment`: filled for 121.

Complete metadata, OpenVINO CPU:

- result: `272 / 272` OK,
- total wall time: `367.5089s`,
- average wall time: `1.3511s/report`,
- summed header OCR runtime: `294.6840s`,
- average header OCR runtime: `1.0834s/report`,
- header extraction mode: `ocr = 272`,
- header OCR errors: `0`.

OpenVINO CPU selected configuration:

- `METROLIZA_HEADER_OCR_ENGINE=openvino`,
- `METROLIZA_HEADER_OCR_THREADS=4`,
- no OpenVINO performance hint,
- no OpenVINO stream override.

OpenVINO CPU vs ONNX Runtime CPU, full parser:

- wall-time speedup: `2.1582x`,
- summed OCR runtime speedup: `2.5579x`,
- matched PDF paths: `272 / 272`,
- compared metadata field differences: `0`,
- compared metadata source differences: `0`.

Light import plus opt-in OpenVINO CPU enrichment:

- manifest entries: `272`,
- unique persisted reports: `271`,
- duplicate-by-SHA explanation: 1 duplicate manifest entry collapsed to the
  existing parsed report row,
- light import result: `272 / 272` processed,
- light import wall time: `41.3569s`,
- light import average wall time: `0.1520s/manifest-entry`,
- enrichment result: `272 / 272` processed,
- enrichment wall time: `336.2871s`,
- enrichment average wall time: `1.2363s/manifest-entry`,
- combined wall time: `377.6440s`,
- combined average wall time: `1.3884s/manifest-entry`,
- persisted measurement rows before enrichment: `23,569`,
- persisted measurement rows after enrichment: `23,569`,
- measurement row preservation: passed,
- measurement count preservation: passed,
- post-enrichment header extraction mode:
  - `ocr = 271`,
- post-enrichment raw-report enrichment marker:
  - present for `271 / 271` persisted reports,
- post-enrichment parse status:
  - `parsed_with_warnings = 271`,
- aggregate preserved-field counts:
  - `part_name = 208`,
  - `reference = 104`,
  - `reference_raw = 104`,
  - `report_date = 28`,
  - `sample_number = 189`,
  - `sample_number_kind = 268`,
  - `stats_count_int = 72`,
  - `stats_count_raw = 197`,
- aggregate updated-field counts:
  - `comment = 119`,
  - `operator_name = 237`,
  - `reference = 8`,
  - `reference_raw = 8`,
  - `report_time = 270`,
  - `revision = 233`,
  - `sample_number = 1`,
  - `stats_count_int = 26`,
  - `stats_count_raw = 1`.

Interpretation:

- user-visible light import completes much earlier than complete OCR parsing,
- total light-plus-enrichment wall time is close to the full complete OpenVINO
  parser path, but with better first-result latency,
- conservative merge preserved stable light metadata frequently while still
  filling OCR-only fields.

Light vs complete ONNX Runtime CPU:

- complete ONNX CPU is about `34.4x` slower than light metadata,
- complete materially fills OCR-only fields,
- complete is not automatically better for filename/body-backed fields,
- future enrichment must merge selectively.

### 4,333-PDF Older Local Tree

Light metadata full ingestion:

- discovered PDFs: `4,333`,
- persisted unique reports: `4,328`,
- duplicate-by-SHA explanation: 5 duplicates,
- measurement rows: `352,642`,
- elapsed: `672.88s`,
- throughput: `6.4321 reports/s`,
- parse status: `parsed_with_warnings = 4,328`,
- header extraction mode: `none = 4,328`,
- OCR skipped: `light_metadata_mode = 4,328`.

Metadata quality quick counts from that light-mode database:

- `source_files = 4,328`,
- `source_file_locations = 4,328`,
- `parsed_reports = 4,328`,
- `report_metadata = 4,328`,
- `report_measurements = 352,642`,
- `report_metadata_candidates = 20,763`,
- `report_metadata_warnings = 9,084`,
- warning counts:
  - `insufficient_header_text = 4,328`,
  - `template_variant_unresolved = 4,328`,
  - `semantic_duplicate_identity_hash_detected = 428`,
- selected candidate source counts:
  - `part_name: filename_candidate = 4,328`,
  - `reference: filename_candidate = 3,479`,
  - `report_date: filename_candidate = 4,310`,
  - `sample_number: filename_candidate = 4,323`,
  - `stats_count_raw: filename_candidate = 4,323`,
- null counts:
  - `reference = 849`,
  - `report_date = 18`,
  - `sample_number = 5`,
  - `part_name = 0`,
  - `stats_count_raw = 5`.

Do not use the 4,333-PDF numbers for OpenVINO/ONNX complete-mode speedup unless
both backends are rerun on that exact same corpus.

## Small-Sample Parser Benchmarks

5-report extracted set:

- complete sequential: `17.0569s`,
- light sequential: `0.6543s`,
- complete two-stage workers 4: `16.8575s`,
- light two-stage workers 4: `1.0211s`,
- finding: light is about `26x` faster; two-stage did not materially improve
  complete mode on this tiny set.

20-report stratified sample:

- complete sequential: `61.7470s`,
- complete two-stage workers 2: `59.0412s`,
- complete two-stage workers 4: `45.6996s`,
- light sequential: `1.9446s`,
- light two-stage workers 4: `3.3755s`,
- measurement rows matched across modes: `1,558`,
- finding: light sequential is about `31.8x` faster than complete sequential.

20-report same-path metadata quality comparison:

- complete elapsed: `61.1431s`,
- light elapsed: `2.2576s`,
- reports parsed: `20 / 20` in both modes,
- measurement rows: `1,558` in both modes,
- light speedup: about `27.1x`,
- metadata field differences out of 20:
  - `reference = 10`,
  - `report_date = 3`,
  - `sample_number = 16`,
  - `part_name = 12`,
  - `revision = 16`,
  - `stats_count_raw = 19`,
  - `operator_name = 17`,
  - `comment = 14`,
- light null where complete had value:
  - `reference = 2`,
  - `revision = 16`,
  - `operator_name = 17`,
  - `comment = 14`,
- complete null where light had value:
  - `report_date = 2`,
  - `stats_count_raw = 1`.

20-report OpenVINO parser-path smoke:

- ONNX CPU wall time: `60.8865s`,
- ONNX CPU summed OCR runtime: `55.7621s`,
- OpenVINO CPU wall time: `26.8019s`,
- OpenVINO CPU summed OCR runtime: `23.2762s`,
- wall-time speedup: `2.2717x`,
- OCR runtime speedup: `2.3957x`,
- matched paths: `20`,
- compared metadata field differences: `0`.

## OCR Backend Benchmarks

### Crop-Level 272 Header Crops

ONNX Runtime CPU:

- summed OCR runtime: `694.2830s`,
- average OCR runtime: `2.5525s/crop`.

OpenVINO CPU:

- summed OCR runtime: `218.4110s`,
- average OCR runtime: `0.8030s/crop`,
- speedup: `3.1788x`,
- record-count diff files: `0`,
- raw OCR text diff files: `0`.

Interpretation:

- crop-only speedup is larger than full-parser speedup because parser overhead
  remains outside OCR,
- full parser validation is the acceptance benchmark for app behavior.

### T480 OpenVINO Test

Local low-end Intel baseline:

- OpenVINO available devices: `CPU` only,
- ONNX Runtime CPU average OCR: `2.7708s/report`,
- OpenVINO CPU average OCR: `1.3089s/report`,
- speedup: about `2.12x`,
- metadata parity: exact match on all compared fields for `5 / 5` files.

### OpenVINO CPU Tuning Screen

Sanity pass:

- corpus size: 1 report from the saved manifest,
- variants tested: 7,
- successful variants: `7 / 7`,
- fastest wall/OCR variant in this one-report sanity pass:
  - `openvino_t6_default`,
- interpretation:
  - one-report cold runs are noisy and are only useful for rejecting unsupported
    options.

20-report tuning screen:

| Variant | Wall time | OCR runtime | Avg wall/report | Avg OCR/report | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `openvino_t4_default` | `26.6023s` | `23.1569s` | `1.3301s` | `1.1578s` | fastest |
| `openvino_t2_default` | `35.9454s` | `32.6173s` | `1.7973s` | `1.6309s` | slower |
| `openvino_t6_default` | `26.7760s` | `23.2956s` | `1.3388s` | `1.1648s` | near tie, slightly slower |
| `openvino_t4_latency` | `26.7971s` | `23.2983s` | `1.3399s` | `1.1649s` | near tie, slightly slower |
| `openvino_t4_throughput` | `36.5673s` | `33.1451s` | `1.8284s` | `1.6573s` | slower |
| `openvino_t4_latency_streams1` | `26.7321s` | `23.2449s` | `1.3366s` | `1.1622s` | near tie, slightly slower |
| `openvino_t4_throughput_streams2` | `36.3965s` | `32.9990s` | `1.8198s` | `1.6500s` | slower |

Metadata parity for the 20-report tuning screen:

- baseline: `openvino_t4_default`,
- compared variants: 6,
- common paths per comparison: `20`,
- compared metadata field differences: `0` for every variant,
- compared metadata source differences: `0` for every variant.

Conclusion:

- keep `openvino_t4_default`,
- do not add a default OpenVINO performance hint,
- do not set a default OpenVINO stream override,
- do not full-confirm any alternate tuning variant because none beat the
  already full-confirmed four-thread default on the 20-report screen.

## RapidOCR Tuning Benchmarks

5-report RapidOCR variant matrix:

- baseline PNG zoom 4:
  - elapsed `14.4231s`,
  - average OCR `2.7825s/report`,
  - field match rate `1.0000`,
- direct numpy zoom 4:
  - elapsed `14.4346s`,
  - average OCR `2.8113s/report`,
  - field match rate `0.9000`,
- numpy zoom 4, classifier off:
  - elapsed `14.2603s`,
  - average OCR `2.7682s/report`,
  - field match rate `0.9000`,
- numpy zoom 3:
  - elapsed `12.5192s`,
  - average OCR `2.4320s/report`,
  - field match rate `0.8000`,
- numpy zoom 3, classifier off:
  - elapsed `12.4071s`,
  - average OCR `2.4083s/report`,
  - field match rate `0.8000`,
- zoom 2 and 1.5 variants:
  - slower than zoom 3,
  - field match about `0.6500`.

Conclusion:

- numpy input did not help,
- classifier-off did not help enough,
- lower zoom reduced quality too much.

Recognition-only fixed cells:

- per-cell runtime: about `0.04-0.05s`,
- quality failed on real bordered/blank cells,
- not viable without a separate localization/preprocessing stage.

## Crop Geometry Experiments

One-file narrower header-table crop smoke:

- current crop zoom 4: `3.4476s`, required fields `6`,
- current crop zoom 3: `2.5634s`, required fields `6`,
- current crop zoom 2: `2.3579s`, required fields `6`,
- table crop zoom 4: `2.3885s`, required fields `6`,
- table crop zoom 3: `2.2360s`, required fields `6`,
- table crop zoom 2: `2.1518s`, required fields `6`.

5-report crop-variant benchmark:

- current crop zoom 4 baseline:
  - elapsed `16.2026s`,
  - average OCR `3.0557s/report`,
  - field match `1.0000`,
- current crop zoom 3:
  - elapsed `13.3546s`,
  - average OCR `2.5027s/report`,
  - field match `0.8000`,
- aggressive table crop zoom 4:
  - elapsed `13.8829s`,
  - average OCR `2.5964s/report`,
  - field match `0.8750`,
- aggressive table crop zoom 3:
  - elapsed `11.7028s`,
  - average OCR `2.1806s/report`,
  - field match `0.7750`,
- aggressive table crop zoom 2:
  - elapsed `12.4914s`,
  - average OCR `2.3494s/report`,
  - field match `0.6000`.

5-report less-aggressive left-crop sweep:

- left crop variant 10 percent, zoom 4:
  - elapsed `15.4418s`,
  - average OCR `2.9100s/report`,
  - field match `0.8500`,
  - all-fields match `2 / 5`,
- left crop variant 12 percent, zoom 4:
  - elapsed `13.7448s`,
  - average OCR `2.5724s/report`,
  - field match `0.8750`,
  - all-fields match `2 / 5`,
- left crop variant 16 percent, zoom 4:
  - elapsed `14.1429s`,
  - average OCR `2.6575s/report`,
  - field match `0.8750`,
  - all-fields match `0 / 5`,
- left crop variant 18 percent, zoom 4:
  - elapsed `13.2772s`,
  - average OCR `2.4805s/report`,
  - field match `0.8750`,
  - all-fields match `0 / 5`.

Conclusion:

- cropping can reduce runtime,
- but it changes OCR segmentation and metadata output too often,
- do not adopt crop shrinking as a direct complete-metadata optimization.

## Threading Experiments

5-report OCR thread-count benchmark:

- current crop zoom 4, threads 1:
  - elapsed `26.2910s`,
  - average OCR `5.0812s/report`,
  - field match `1.0000`,
- current crop zoom 4, threads 2:
  - elapsed `17.9303s`,
  - average OCR `3.4116s/report`,
  - field match `1.0000`,
- current crop zoom 4, threads 4:
  - elapsed `15.0492s`,
  - average OCR `2.8337s/report`,
  - field match `1.0000`,
- current crop zoom 4, threads 6:
  - elapsed `16.0262s`,
  - average OCR `3.0094s/report`,
  - field match `1.0000`,
- current crop zoom 4, threads 8:
  - elapsed `15.9640s`,
  - average OCR `2.9958s/report`,
  - field match `1.0000`.

Conclusion:

- 4 ONNX intra-op threads is the best tested default on this machine,
- higher thread counts were slower,
- two-stage worker parallelism can reduce wall time in some samples but inflates
  total CPU OCR time because engines are per thread.

## Embedded Image-Block Experiments

Direct embedded image-block OCR:

- rendered crop control:
  - elapsed `15.8698s`,
  - average OCR `2.9897s/report`,
  - field match `1.0000`,
- direct image block:
  - elapsed `13.2918s`,
  - average OCR `2.4939s/report`,
  - field match `0.4250`.

Padded embedded image-block OCR:

- padded direct image block:
  - elapsed `15.6631s`,
  - average OCR `2.9109s/report`,
  - field match `0.5250`.

Conclusion:

- direct image-block input is not metadata-safe,
- padding did not recover quality,
- keep rendered crop OCR.

## Unavailable Or Deferred Backend Probes

Current Linux environment:

- ONNX Runtime providers:
  - `AzureExecutionProvider`,
  - `CPUExecutionProvider`,
- no NVIDIA GPU provider,
- no valid Linux DirectML benchmark,
- no TensorRT runtime,
- OpenVINO reports CPU only when no GPU device is visible.

DirectML probe:

- not a valid Linux benchmark,
- RapidOCR logged Windows-only fallback behavior,
- must be benchmarked on Windows with DirectML provider available.

CUDA probe:

- not a valid benchmark on current hardware,
- CUDA provider unavailable,
- must be benchmarked on NVIDIA hardware with compatible `onnxruntime-gpu`.

TensorRT probe:

- failed as expected when TensorRT runtime was missing,
- must be benchmarked on NVIDIA hardware with TensorRT installed,
- record first-run engine build/cache behavior separately.

## Backend Decision Matrix

Adopted or locally validated:

- ONNX Runtime CPU:
  - default fallback,
  - slow but reliable,
- OpenVINO CPU:
  - preferred locally validated complete-OCR CPU backend,
  - packaged selectable backend.

Next real-hardware experiments:

- Windows DirectML:
  - highest-priority GPU/APU test for Windows Intel and AMD machines,
  - likely reachable through RapidOCR ONNX Runtime provider config,
- NVIDIA CUDA:
  - lower priority unless NVIDIA deployment hardware exists,
  - likely simpler than TensorRT,
- NVIDIA TensorRT:
  - potentially faster,
  - higher packaging/cache complexity,
- OpenVINO GPU/AUTO/NPU:
  - promising for Intel hardware,
  - current RapidOCR OpenVINO wrapper is CPU-only in practice,
  - needs custom wrapper or ONNX Runtime OpenVINO EP path,
- AMD Ryzen AI / Vitis AI:
  - specialized,
  - defer until target NPU hardware exists,
- AMD Linux ROCm/MIGraphX:
  - support matrix risk,
  - defer unless Linux AMD deployment is confirmed,
- PaddleOCR/PaddleOCR HPI:
  - technically interesting,
  - heavier stack and packaging shift,
  - do not pursue before DirectML/OpenVINO/CUDA/TensorRT routes.

## 2026-04-29 Step Log

### GitHub Confidentiality Audit And Closeout Validation

Status:

- publish-hygiene/confidentiality validation completed,
- strengthened the GitHub confidentiality rule to explicitly prohibit real
  report files and real report-derived identifiers/data, even for benchmarking,
- audited Git-bound tracked and untracked non-ignored files for saved-corpus
  report basename/stem matches and local benchmark/corpus artifacts,
- confirmed ignored benchmark artifacts remain outside the Git-bound tree,
- ran focused OCR/package/UI validation after the documentation update.

Subagents/model split:

- Raman explorer, GPT-5.4 Mini, medium effort: read-only Git-bound
  confidentiality audit,
- Poincare explorer, GPT-5.4 Mini, low effort: read-only closeout validation
  checklist,
- local execution: redacted exact report-identifier scan, package validator,
  focused tests, ruff, py_compile, and roadmap updates.

Non-confidential command shapes:

```bash
git status --short --branch
git ls-files
git ls-files --others --exclude-standard
git status --ignored -s benchmark_results/ocr_parse_performance
python <REDACTED_REPORT_IDENTIFIER_SCAN>
python scripts/validate_packaged_pdf_parser.py --require-header-ocr
python -m ruff check <touched_ocr_files_tests_and_roadmaps>
python -m py_compile <touched_ocr_python_files>
QT_QPA_PLATFORM=offscreen python -m pytest <focused_ocr_package_ui_tests> -q
```

Benchmark numbers:

- no OCR corpus benchmark in this step,
- saved 272-PDF acceptance benchmark was not rerun because OCR/parser behavior
  did not change.

Validation result:

- Git-bound files scanned: `407`,
- saved-corpus report basename/stem patterns scanned: `542`,
- exact real-report identifier hits in Git-bound files: `0`,
- Git-bound local benchmark/report artifact path scan: no files under
  `benchmark_results/` or the local report corpus,
- `benchmark_results/` remains ignored,
- packaged OCR validator: passed, validating header OCR dependencies and 3
  vendored model files,
- ruff over touched OCR files/tests/roadmaps: passed,
- py_compile over touched OCR Python files: passed,
- focused enrichment/schema/parser/export slice: `24 passed`,
- broader OCR/package/UI slice: `65 passed`.

Files changed:

- `docs/roadmaps/OCR_BENCHMARKING_MASTER.md`,
- `docs/roadmaps/OCR_TEST_CLEANUP_NEXT_SESSION_README.md`.

Caveats:

- existing tracked documentation/test fixture PDFs remain in the Git-bound tree;
  the audit found no saved-corpus report basename/stem matches against them,
- ignored benchmark outputs may contain local report paths/names and must stay
  ignored unless explicitly scrubbed,
- `gh` is installed but not authenticated; use SSH for push if publishing from
  this environment.

Next recommended step:

- stage intentionally from the dirty worktree, push through SSH if publishing,
  and use connector/API checks for GitHub status because `gh` is not logged in.

## Current Recommended Next Steps

1. Keep the test cleanup frozen unless a fresh audit identifies a specific
   stale or duplicate test with a named replacement.
2. Rerun the saved 272-PDF OCR acceptance benchmark only after OCR/parser
   behavior changes again.
3. Before publishing, run the publication checklist, keep ignored benchmark
   artifacts out of Git, and stage only intentional files from the dirty
   worktree.
4. Test DirectML on Windows Intel/AMD target hardware.
5. Test CUDA/TensorRT only on NVIDIA target hardware.
6. Keep this document updated after each step.

## Validation Commands

Focused validation used after the OpenVINO full-parser update:

```bash
python -m ruff check \
  modules/header_ocr_backend.py \
  modules/cmm_report_parser.py \
  modules/contracts.py \
  modules/parse_reports_thread.py \
  modules/parsing_dialog.py \
  scripts/benchmark_header_ocr_modes.py \
  scripts/inspect_ocr_benchmark_results.py \
  scripts/compare_ocr_metadata_benchmarks.py \
  scripts/validate_packaged_pdf_parser.py \
  scripts/windows_ocr_runtime_diagnostics.py \
  tests/test_header_ocr_backend.py \
  tests/test_packaged_pdf_parser_validation.py \
  tests/test_packaging_spec_hiddenimports.py \
  tests/test_requirements_hygiene.py
```

```bash
python -m py_compile \
  modules/header_ocr_backend.py \
  modules/cmm_report_parser.py \
  modules/contracts.py \
  modules/parse_reports_thread.py \
  modules/parsing_dialog.py \
  scripts/benchmark_header_ocr_modes.py \
  scripts/inspect_ocr_benchmark_results.py \
  scripts/compare_ocr_metadata_benchmarks.py \
  scripts/validate_packaged_pdf_parser.py \
  scripts/windows_ocr_runtime_diagnostics.py
```

```bash
QT_QPA_PLATFORM=offscreen python -m pytest \
  tests/test_contracts.py \
  tests/test_parsing_dialog_selection_flow.py \
  tests/test_thread_flow_helpers.py \
  tests/test_report_schema_repository.py \
  tests/test_report_metadata_persistence.py \
  tests/test_report_metadata_extractor.py \
  tests/test_header_ocr_backend.py \
  tests/test_header_ocr_diagnostics_script.py \
  tests/test_packaged_pdf_parser_validation.py \
  tests/test_packaging_spec_hiddenimports.py \
  tests/test_requirements_hygiene.py \
  -q
```

Latest result:

- `181 passed, 2 subtests passed`.

Packaged OCR validation:

```bash
python scripts/validate_packaged_pdf_parser.py --require-header-ocr
```

Latest result:

- passed,
- validated packaged header OCR dependencies and 3 vendored model files.

## Publication Checklist

Before pushing or opening a PR:

- confirm the GitHub-bound tree contains no real reports, real report names,
  report paths, raw OCR text, raw metadata values, screenshots, or crop images,
- ensure benchmark result JSON/manifest/crops remain ignored,
- do not force-add `benchmark_results/` unless scrubbed,
- scan tracked docs/tests/scripts for report filenames and report paths,
- remove any raw OCR values that came from real reports,
- keep this file as the only durable tracked OCR benchmark handoff,
- update `docs/README.md` if this file moves.
