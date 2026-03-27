# Parser Audit (2026-03)

## Goal
Assess parser-path performance and determine what is still required so new report parsers can be added quickly from example reports without turning the parser layer into another monolith.

## Scope
- CMM parser runtime hot path.
- Parser factory and plugin-resolution overhead.
- Current plugin authoring workflow for new report templates and formats.
- Native acceleration readiness and boundaries.

## What changed in this audit pass
1. Reduced steady-state parser-factory overhead in `modules/report_parser_factory.py`.
   - External entry-point discovery is now cached for the loaded runtime instead of rescanning package metadata on every resolve.
2. Reduced pure-Python CMM tokenization cost in `modules/cmm_parsing.py`.
   - Measurement extraction now tracks numeric-token counts incrementally.
   - The hot path no longer slices `raw_lines[index:]` and `split_lines[index:]` for every measurement row.
3. Added a regression test proving steady-state parser resolution does not rescan entry points after initial load.

## Measured findings

### 1. Parser-factory overhead was real and is now largely eliminated
Measured on 2026-03-27 against the repo `HEAD` as baseline and the current working tree as the audited result.

- `detect_format(...)` x1000:
  - baseline: `6.459651s`
  - current: `0.017788s`
  - delta: about `363x` faster
- `_iter_external_plugin_entry_points()` calls during those 1000 resolutions:
  - baseline: `1000`
  - current: `1`
- `get_parser(...)` x1000:
  - baseline: `6.960850s`
  - current: `0.240249s`
  - delta: about `29x` faster

### 2. Pure-Python CMM parsing was dominated by avoidable inner-loop work
Synthetic mixed workload: `120` reports x `120` measurements with single-line and multi-line tokens.

- `parse_raw_lines_to_blocks(...)`
  - baseline: `3.224058s`
  - current: `0.208094s`
  - delta: about `15.5x` faster

Current cProfile snapshot on the same workload:

- total profiled runtime: `0.613s` under profiler overhead
- dominant functions:
  - `parse_raw_lines_to_blocks`
  - `extract_measurement_tokens_and_raw_lines_consumed`
  - `process_line`
  - `append_tokens`
  - `is_number`

Interpretation:
- The previous `sum(...)` recount inside the token loop and repeated list slicing were major costs.
- After removing those, the remaining Python cost is mostly numeric-token classification and row-shape conversion.

### 3. Normalization is cheap; persistence is secondary
On the same parsed synthetic workload:

- normalized rows: `14400`
- `normalize_measurement_rows_python(...)`: `0.007624s`
- Python persistence to SQLite: `0.193630s`

Interpretation:
- Parser optimization should continue to focus on token extraction and line interpretation first.
- SQLite write cost matters, but it is not the primary parser bottleneck on the current path.

### 4. Native parser is architecturally ready but not active in this checkout
- `_metroliza_cmm_native` availability in this environment: `False`
- Runtime policy already supports:
  - `METROLIZA_CMM_PARSER_BACKEND=auto`
  - `METROLIZA_CMM_PARSER_BACKEND=python`
  - `METROLIZA_CMM_PARSER_BACKEND=native`
- Build/install path already exists via `maturin` in `modules/native/cmm_parser`

Interpretation:
- The repo is already prepared for native acceleration.
- The immediate blocker is not missing architecture; it is missing a built and installed extension in the working environment plus the benchmark/parity evidence to justify broader rollout.

## Remaining performance hotspots

### P1. `is_number(...)` is still hot
After this pass, numeric classification remains a large share of the pure-Python parse budget.

Practical next step:
- Replace repeated `float(...)` probes with a tokenization pass that stores parsed numeric state once per token.
- If that increases complexity too much in Python, keep the Python path readable and rely on the Rust backend for this kernel.

### P1. `process_line(...)` still performs a lot of shape branching
The current line-shape decoding is explicit and stable, but branch-heavy.

Practical next step:
- Consolidate repeated row-build patterns into table-driven converters for non-TP codes.
- Keep TP special handling separate because it has real semantic branching.

### P2. SQLite persistence remains noticeable at scale
Current persistence cost is acceptable relative to parsing, but it will become more visible once native parsing is enabled.

Practical next step:
- Re-measure after `_metroliza_cmm_native` is available.
- Only optimize persistence further if it becomes the dominant post-native cost.

### Out of scope for parser micro-optimization
- PDF text extraction itself was not benchmarked in this pass.
- If PyMuPDF page text extraction dominates real-world files, parser-loop optimization alone will not solve end-to-end latency.

## Architecture audit: current plugin model

## What is already good
1. There is a real plugin contract.
   - `BaseReportParserPlugin`, `PluginManifest`, `ProbeResult`, and `ParseResultV2` give a stable seam.
2. Runtime resolution is centralized.
   - `modules/report_parser_factory.py` handles registration, probe-based selection, and external plugin loading.
3. Backward compatibility is preserved.
   - Legacy parser construction still works through `get_parser(...)`.
4. A basic validation gate exists.
   - `modules/parser_plugin_validation.py`
   - `scripts/validate_parser_plugins.py`
5. There is already a native-acceleration escape hatch.
   - `modules/cmm_native_parser.py`
   - `modules/native/cmm_parser`

## What is not good enough yet
1. New parser creation from examples is still too manual.
   - `modules/llm_plugin_factory/scaffold.py` is only a string-template stub.
   - There is no generator that emits a plugin, sample fixtures, expected-output fixtures, and validation wiring as one package.
2. Validation is mostly structural, not semantic.
   - The default validation gate proves contract shape, not correctness against expected parsed values.
3. Template-level matching is underpowered.
   - The current CMM probe is effectively extension-based.
   - Future suppliers/templates need stronger report-template detection than file suffix alone.
4. There is no canonical sample-pack contract for onboarding a new parser.
   - That makes repeated “build a parser from these reports” tasks slower than necessary.
5. Benchmark coverage is still weak for onboarding and regressions.
   - There is no dedicated parser-onboarding benchmark that measures probe cost, parse cost, and semantic-validation cost for a sample pack.

## What “plugin-like parsers” should mean here
For future formats, adding a parser should look like adding a plugin package, not editing core parsing code until it happens to work.

Minimum target workflow:
1. Prepare a sample pack from example reports.
2. Generate a parser skeleton from that pack.
3. Generate fixture tests from expected values.
4. Run contract validation plus semantic validation.
5. Register the plugin externally or ship it with the app.

If a new parser still requires invasive edits across unrelated core modules, the plugin architecture is not finished.

## Recommended sample-pack contract
This is the missing operational contract that would make Codex-assisted parser generation fast and repeatable.

```text
sample_pack/
  reports/
    sample_01.pdf
    sample_02.pdf
    sample_03.pdf
  expected/
    report_metadata.csv
    measurements.csv
  probe_notes.md
  mapping_notes.md
  rollout_notes.md
```

Recommended contents:
- `reports/`
  - 3 to 8 representative reports from the same supplier/template
- `expected/report_metadata.csv`
  - `file_name,reference,report_date,sample_number,template_id`
- `expected/measurements.csv`
  - `file_name,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance`
- `probe_notes.md`
  - tell the generator what identifies this template
- `mapping_notes.md`
  - known quirks, locale issues, unit issues, OCR oddities
- `rollout_notes.md`
  - supplier name, country, version tags, risk notes

Why this matters:
- It gives Codex enough structure to produce both a parser and the tests that prove it.
- It avoids having “expected output” trapped in screenshots or ad hoc spreadsheets.

## Recommended roadmap for fast parser onboarding

### Priority 0: done in this audit pass
- Remove repeated factory entry-point scans from steady-state resolution.
- Remove avoidable Python tokenizer overhead in CMM parsing.

### Priority 1: highest-value next steps
1. Build and benchmark `_metroliza_cmm_native` locally.
   - The native path is already supported by policy and code.
   - Evidence is still missing in this checkout because the extension is unavailable.
2. Add a real sample-pack driven validation path.
   - A new CLI should validate a parser against `report_metadata.csv` and `measurements.csv`, not just the contract shape.
3. Expand the scaffold into a generator.
   - Output should include:
     - plugin file
     - sample fixture set
     - semantic validation test
     - probe test
     - repair-loop seed prompt

### Priority 2: architecture cleanup for future templates
1. Strengthen probe logic.
   - Split “format detection” from “template detection”.
2. Parse directly to `ParseResultV2` for new plugins.
   - Avoid forcing new plugins through legacy block adapters unless compatibility requires it.
3. Add a sample-pack benchmark harness.
   - Measure:
     - probe time
     - parse time
     - validation time
     - native vs Python delta when applicable

### Priority 3: only after evidence exists
1. Promote native parser to broader default usage only when:
   - parity passes on representative fixtures
   - speedup is reproduced on real supplier reports
2. Consider additional native kernels only if profiling shows clear payoff after native parse adoption.

## Rust/C recommendation

## Good native candidates
- CMM token extraction and multi-line measurement assembly
- Numeric-token classification
- Row normalization and SQLite marshaling

These are stable, loop-heavy kernels with measurable outputs.

## Bad native candidates
- Plugin registration and manifest handling
- Probe orchestration and fallback policy
- LLM scaffolding and repair-loop prompt generation
- Business-facing validation/reporting glue

These are not compute kernels. Native code would add complexity without solving the main bottleneck.

## Recommendation
- Keep the plugin/runtime authoring surface in Python.
- Keep native code limited to stable parse kernels and other proven hot loops.
- Do not widen native scope until the existing CMM native parser is built, benchmarked, and parity-validated in the working environment.

## Bottom line
1. Parser performance improved materially in this pass.
   - Factory resolution is no longer a steady-state bottleneck.
   - Pure-Python CMM parsing is much faster even without native code.
2. The next real performance lever is enabling and validating the existing Rust parser backend.
3. The next real product lever is not more micro-optimization.
   - It is a sample-pack driven parser-generation workflow with semantic validation, so adding a new report template feels like adding a plugin package rather than hand-editing core parser code.
