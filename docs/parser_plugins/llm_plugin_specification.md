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

## Required behavior

### `manifest`

The manifest must preserve the requested:

- `plugin_id`
- `display_name`
- `supported_formats`

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
- assert the result is `ParseResultV2` when parsing is implemented
- assert the `plugin_id` matches the requested value

## Installation target

After validation passes, the generated plugin file is installed by copying it to:

`~/.metroliza/parser_plugins/<plugin-id>.py`

Metroliza will auto-discover that file and include it in parser factory resolution on the next app start or process start.

## Definition of done

A generated parser plugin is ready only when all are true:

- validation passes via `scripts/validate_parser_plugins.py`
- manually checked expected values match the parsed result
- the plugin file is installed in `~/.metroliza/parser_plugins/`
- Metroliza selects the plugin for the intended supplier report format
- rollout approval follows the parser plugin runbook
