# LLM Parser Plugin Specification

## Purpose

Use this specification when asking an LLM to generate a new Metroliza parser plugin for a supplier-specific report template.

The output must be a Python plugin file that Metroliza can load through the parser factory without manual architecture changes.

## Inputs the LLM must receive

- `supplier_intake.md`
- 3-5 real sample reports from one supplier and one template family
- `expected_results_template.csv` with manually verified expected values
- `prompts/01_analysis_prompt.md`
- `prompts/02_implementation_prompt.md`
- the scaffold files generated in the workspace

## Files the LLM must return

- `generated_plugin.py`
- `tests/test_generated_plugin.py`

No extra files are required unless the prompt explicitly asks for an additional explanation artifact.

## Required implementation contract

The generated plugin must:

- inherit both `BaseReportParser` and `BaseReportParserPlugin`
- define a class-level `manifest: PluginManifest`
- implement `probe(input_ref, context) -> ProbeResult`
- implement `open_report(self)`
- implement `split_text_to_blocks(self)`
- implement `parse_to_v2(self) -> ParseResultV2`
- implement `to_legacy_blocks(parse_result_v2)`

## Runtime selection model

The parser factory evaluates a report in this order:

1. Infer the source format from the file suffix.
2. Load built-in and external parser plugins.
3. Keep only plugins whose manifest `supported_formats` includes that format.
4. Ask each remaining plugin to `probe(...)` with a `ProbeContext`.
5. Accept only plugins whose probe says `can_parse=True` and whose confidence is high enough for the active selection mode.
6. Choose the winner by confidence, then manifest `priority`, then `plugin_id`.

This means `probe(...)` must be cheap, deterministic, and specific enough to distinguish the intended template family from generic format-level parsers.

## Required behavior

### `manifest`

The manifest must preserve the requested:

- `plugin_id`
- `display_name`
- `supported_formats`

It should also set the supporting fields deliberately:

- `supported_locales` for locale coverage and review.
- `template_ids` for template-family identifiers.
- `priority` as a tie-breaker when confidence is equal.
- `capabilities` for structured metadata such as OCR requirements.

It must not invent new registry mechanisms or change how Metroliza discovers plugins.

### `probe(...)`

The probe must be deterministic and cheap.

It should rely on:

- file extension / source format
- stable template markers
- predictable header strings
- version strings or supplier-specific labels when available

It must return a valid `ProbeResult` with:

- the same `plugin_id` as the manifest
- confidence in the `0..100` range
- useful `reasons`

### `open_report(...)`

This method must extract reproducible raw text or raw sheet content from the source file and populate `self.raw_text`.

### `split_text_to_blocks(...)`

This method must populate `self.blocks_text` using the legacy measurement row order:

`[AX, NOM, +TOL, -TOL, BONUS, MEAS, DEV, OUTTOL]`

### `parse_to_v2(...)`

This method must:

- call `open_report()` if `self.raw_text` is empty
- call `split_text_to_blocks()` if `self.blocks_text` is empty
- convert the parsed content into `ParseResultV2`
- fill `ParseMetaV2`, `ReportInfoV2`, `MeasurementBlockV2`, and `MeasurementV2`
- preserve supplier/reference/date/sample identity correctly

### `to_legacy_blocks(...)`

This adapter must convert a `ParseResultV2` back into the legacy `blocks_text` shape used by compatibility paths.

## Output quality rules

The generated plugin must:

- stay within the existing Metroliza parser architecture
- use only stdlib plus imports already allowed by the scaffold
- avoid network access, subprocess calls, or unrelated filesystem scanning
- avoid new package dependencies
- avoid non-deterministic behavior
- avoid changing global runtime flags or factory logic

## Test requirements

`tests/test_generated_plugin.py` must:

- import the generated parser class
- instantiate it against a sample file
- exercise `probe(...)` for the same sample
- assert the result is `ParseResultV2` when parsing is implemented
- assert the `plugin_id` matches the requested value
- use the workspace `expected_results_template.csv` as the correctness reference for manual review or semantic validation

## Installation target

After validation passes, the generated plugin file is installed by copying it to:

`~/.metroliza/parser_plugins/<plugin-id>.py`

Metroliza will auto-discover that file and include it in parser factory resolution on the next app start or process start.

## Definition of done

A generated parser plugin is ready only when all are true:

- validation passes via `scripts/validate_parser_plugins.py`
- the parsed result matches the manually verified values in `expected_results_template.csv`
- the plugin file is installed in `~/.metroliza/parser_plugins/`
- Metroliza selects the plugin for the intended supplier report format
- rollout approval follows the parser plugin runbook
