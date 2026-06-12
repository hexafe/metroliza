# Parser Plugin Specification

## Purpose

Use this specification when creating new Metroliza parser support for a
supplier-specific report template.

The default output is a **declarative YAML parser profile**: a reviewed
`profile.yaml` file that Metroliza loads with trusted runtime code. A generated
Python parser plugin is still supported, but only as an advanced operator-only
fallback when the YAML profile route cannot model the template.

## Route Summary

Use the YAML profile route first.

- Non-technical user flow: **Tools > Parser profiles...**
- Output: `profile.yaml`
- Runtime install location:
  `~/.metroliza/parser_plugins/profiles/approved/<profile-id>/profile.yaml`
- Good fit: stable template markers, report identity fields, line-based
  measurement rows, date/decimal normalization.
- Safety model: data-only YAML; no Python code, subprocesses, network calls,
  package installation, or profile-owned database writes.

Use the advanced Python plugin route only after operator review.

- Workspace command: `python scripts/create_parser_plugin_workspace.py ...`
- Output: `generated_plugin.py`
- Runtime install location: `~/.metroliza/parser_plugins/<plugin-id>.py`
- Good fit: custom document decoding, custom pre-processing, or parsing logic
  that cannot be represented as data-only extraction rules.
- Safety model: existing Metroliza parser APIs only; no network calls, package
  installation, shell commands, direct SQLite writes, or global runtime changes.

## Glossary

- **Parser profile**: a data-only YAML file for one supplier report layout.
- **Handoff folder**: the local workspace containing samples, expected results,
  prompts, contracts, profile drafts, responses, and artifacts.
- **Sample report**: a real report from the supplier/template family being
  approved.
- **Expected results**: manually checked rows in `expected_results.csv` that
  validation must match exactly.
- **Probe**: a cheap deterministic check that decides whether a parser matches a
  report.
- **Diagnose**: the action that explains profile selection and parse evidence
  for one sample report.
- **Repair prompt**: a focused prompt built from validation failures so a
  reviewer or LLM can return corrected file contents.
- **ParseResultV2**: the parser output contract that Metroliza persists through
  its normal report repository.
- **Advanced Python plugin**: a Python parser file for cases where YAML is not
  expressive enough.

## Default Route: Declarative YAML Profile

### In-App Handoff Workspace

The main window can create a local handoff folder:

```text
Tools > Parser profiles... > Create Handoff Folder
```

The handoff folder contains:

- `profile.yaml`
- `samples/`
- `expected_results.csv`
- `llm_handoff.md`
- `handoff_manifest.json`
- `NON_TECHNICAL_STEPS.md`
- `contracts/`
- `reference/contract_snippets.md`
- `prompts/`
- `responses/`
- `artifacts/`

The dialog does not call an LLM. It prepares local files that a user can give to
an approved external workflow or a human reviewer, and it provides open-folder,
copy-path, package-check, validate, diagnose, repair-prompt, and install actions
for the hidden profile-store location.

### Self-Contained LLM Handoff Package

Every generated LLM handoff package must contain enough information for a
disconnected LLM or human reviewer to build or repair the YAML profile without
browsing the repository.

Required package files:

- `handoff_manifest.json` with `schema_version`, `package_type`, `plugin_id`,
  `display_name`, `source_format`, `allowed_outputs`, validation commands,
  prompt order, and runtime persistence boundary.
- `contracts/00_read_this_first.md` with the package target and hard
  boundaries.
- `contracts/01_parser_api_contract.md` with the API snippets for
  `PluginManifest`, `ProbeResult`, `ParseResultV2`, `ReportInfoV2`,
  `MeasurementBlockV2`, and `MeasurementV2`.
- `contracts/02_runtime_selection_contract.md` with probe confidence rules and
  strict selection threshold.
- `contracts/03_sqlite_persistence_contract.md` stating that Metroliza owns
  SQLite writes and parsers must return `ParseResultV2`.
- `contracts/04_expected_results_contract.md` with the expected-results CSV
  columns and review rules.
- `contracts/05_security_and_safety_contract.md` forbidding network calls, shell
  commands, package installation, credential access, dynamic code execution, and
  plugin-owned database writes.
- `contracts/06_github_references.md` with source links as supplemental
  references only.
- `contracts/07_privacy_redaction_checklist.md` with the minimum
  sample-redaction review before external LLM sharing.
- `reference/contract_snippets.md` as the compact single-file version for
  cheap/local LLMs.
- `NON_TECHNICAL_STEPS.md` with step-by-step instructions for a non-technical
  user.

Prompt files must support two declarative-profile usage patterns:

- full prompts for stronger models or human reviewers,
- microtask prompts that split template markers, report fields, measurement row
  rules, normalization, complete YAML output, and repair into small tasks.

`handoff_manifest.json` must keep `full_prompt_order` and
`microtask_prompt_order` separate so a user does not mix the two routes
accidentally.

Repair prompts must also be self-contained. They must include failed validation
checks, compact API/persistence snippets, expected-results columns, allowed
outputs, and the instruction to return complete updated file contents only.

### Tiny Copyable Example

Sample report text:

```text
SYNTHETIC SUPPLIER ALPHA
Reference: REF123
Date: 2026-01-05
Sample: 0001
DIM X 10.0 0.1 -0.1 - 10.02 0.02 0
```

One `expected_results.csv` row:

```csv
sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance
sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0
```

Minimal `profile.yaml` fragment:

```yaml
schema_version: 1
plugin:
  plugin_id: supplier_alpha
  display_name: Supplier Alpha
  version: 0.1.0
  source_format: pdf
  supported_locales: ["*"]
  template_ids: ["synthetic_fixture"]
  priority: 900
probe:
  required_markers:
    - "SYNTHETIC SUPPLIER ALPHA"
  confidence: 92
extraction:
  report_fields:
    reference: 'Reference:\s*(?P<value>\S+)'
    report_date: 'Date:\s*(?P<value>\d{4}-\d{2}-\d{2})'
    sample_number: 'Sample:\s*(?P<value>\S+)'
  blocks:
    - header: "MAIN FEATURE"
      pattern: '^DIM\s+(?P<axis_code>\w+)\s+(?P<nominal>[-0-9.,]+)\s+(?P<tol_plus>[-0-9.,]+)\s+(?P<tol_minus>[-0-9.,]+)\s+(?P<bonus>[-0-9.,]+|-)\s+(?P<measured>[-0-9.,]+)\s+(?P<deviation>[-0-9.,]+)\s+(?P<out_of_tolerance>[-0-9.,]+)$'
normalization:
  decimal_separator: "."
  date_formats: ["%Y-%m-%d"]
  missing_value_tokens: ["", "-", "NA", "N/A"]
```

### Declarative Profile Contract

`profile.yaml` must be data-only YAML. It must not require Python code,
subprocesses, network access, package installation, shell commands, or direct
database writes.

Declarative profiles are intentionally constrained. Validation rejects profiles
that:

- install without at least one sample report and `expected_results.csv`,
- use an `expected_results.csv` file with no checked data rows,
- parse extra rows that are not represented in the checked expected-results
  rows,
- use path-like sample names outside the workspace `samples/` directory,
- use regex backreferences, nested repeating groups, unbounded dot wildcards, or
  row patterns that are not line-anchored,
- exceed runtime text and row-match limits intended to prevent a malformed
  profile from hanging parsing.

Required top-level sections:

- `schema_version`
- `plugin`
- `probe`
- `extraction`
- `normalization`

Required `plugin` fields:

- `plugin_id`
- `display_name`
- `version`
- `source_format`
- `template_ids`

Required `probe` fields:

- `required_markers`
- `confidence`

Required `extraction.report_fields` fields:

- `reference`
- `report_date`
- `sample_number`

Required measurement extraction:

- at least one `extraction.blocks` entry,
- each block must include a regex `pattern`,
- row captures should use the standard measurement names: `axis_code`,
  `nominal`, `tol_plus`, `tol_minus`, `bonus`, `measured`, `deviation`, and
  `out_of_tolerance`.

Runtime approval stores validated profiles under:

```text
~/.metroliza/parser_plugins/profiles/approved/<profile-id>/
```

Each approved profile must have:

- `profile.yaml`
- `approval.json`

The approval sidecar records the validation result and checksum. If the
checksum no longer matches, Metroliza does not load the profile.

### Declarative Validation And Installation

Use the in-app buttons for normal work:

```text
Tools > Parser profiles... > Check Package
Tools > Parser profiles... > Validate
Tools > Parser profiles... > Diagnose
Tools > Parser profiles... > Repair Prompt
Tools > Parser profiles... > Install
```

Operator CLI equivalents:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py handoff --plugin-id <profile-id> --source-format pdf --output-dir <handoff-folder>
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py integrity <handoff-folder>
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder>
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose <handoff-folder>/profile.yaml <handoff-folder>/samples/sample_report_01.pdf
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py repair <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --output <handoff-folder>/artifacts/profile_repair_prompt.md
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --approved-by operator
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py evidence <profile-id>
```

After installation, restart Metroliza and parse reports through the normal
report import/parse workflow.

### Declarative Definition Of Done

- Declarative profile validation passes via
  `scripts/parser_plugin_self_service.py validate`.
- The handoff package passes `scripts/parser_plugin_self_service.py integrity`.
- Declarative profile approval uses `scripts/parser_plugin_self_service.py
  install` with at least one sample and `expected_results.csv`.
- The parsed result matches every manually verified value in
  `expected_results.csv`.
- No extra parsed measurement rows are left unchecked by `expected_results.csv`.
- The profile is installed in its approved runtime location with a matching
  `approval.json` checksum.
- Metroliza discovers the profile's report file type during normal import and
  selects the profile for the intended supplier report format.
- Rollout approval follows the parser plugin runbook.

## When To Ask For Help

Stop and ask an operator, release owner, or data owner when:

- privacy is uncertain or you are unsure whether samples may be shared,
- representative samples are missing,
- validation fails repeatedly after repair,
- Diagnose shows that the wrong parser is selected,
- parsed values pass technically but do not match the report's business meaning,
- the sample set contains multiple visible layouts,
- any LLM output adds Python, network access, package installation, shell
  commands, database-write behavior, or installer changes.

These rules apply to both YAML profiles and advanced Python plugins. Any LLM
output that expands runtime behavior must be rejected or escalated before it is
used.

## Advanced Route: Python Plugin

Use this section only when a declarative profile cannot represent the supplier
template.

The output must be a Python plugin file that Metroliza can load through the
parser factory without manual architecture changes.

### Required Workspace Inputs

- `supplier_intake.md`
- 3 to 5 real sample reports from one supplier and one template family
- `expected_results_template.csv` with manually verified expected values
- `prompts/01_analysis_prompt.md`
- `prompts/02_implementation_prompt.md`
- `prompts/microtasks/` when using a small/local LLM
- `contracts/` or `reference/contract_snippets.md`
- the scaffold files generated in the workspace

### Required Plugin Files

- `generated_plugin.py`
- `tests/test_generated_plugin.py`

No extra files are required unless the prompt explicitly asks for an additional
explanation artifact.

### Required Implementation Contract

The generated plugin must:

- inherit both `BaseReportParser` and `BaseReportParserPlugin`,
- define a class-level `manifest: PluginManifest`,
- implement `probe(input_ref, context) -> ProbeResult`,
- implement `open_report(self)`,
- implement `split_text_to_blocks(self)`,
- implement `parse_to_v2(self) -> ParseResultV2`,
- implement `to_legacy_blocks(parse_result_v2)`.

### Runtime Selection Model

The parser factory evaluates a report in this order:

1. Infer the source format from the file suffix.
2. Load built-in and external parser plugins.
3. Keep only plugins whose manifest `supported_formats` includes that format.
4. Ask each remaining plugin to `probe(...)` with a `ProbeContext`.
5. Accept only plugins whose probe says `can_parse=True` and whose confidence is
   high enough for the active selection mode.
6. Choose the winner by confidence, then manifest `priority`, then `plugin_id`.

This means `probe(...)` must be cheap, deterministic, and specific enough to
distinguish the intended template family from generic format-level parsers.

### Required Behavior

#### `manifest`

The manifest must preserve the requested:

- `plugin_id`
- `display_name`
- `supported_formats`

It should also set the supporting fields deliberately:

- `supported_locales` for locale coverage and review.
- `template_ids` for template-family identifiers.
- `priority` as a tie-breaker when confidence is equal.
- `capabilities` for structured metadata such as OCR requirements.

It must not invent new registry mechanisms or change how Metroliza discovers
plugins.

#### `probe(...)`

The probe must be deterministic and cheap.

It should rely on:

- file extension / source format,
- stable template markers,
- predictable header strings,
- version strings or supplier-specific labels when available.

It must return a valid `ProbeResult` with:

- the same `plugin_id` as the manifest,
- confidence in the `0..100` range,
- useful `reasons`.

#### `open_report(...)`

This method must extract reproducible raw text or raw sheet content from the
source file and populate `self.raw_text`.

#### `split_text_to_blocks(...)`

This method must populate `self.blocks_text` using the legacy measurement row
order:

```text
[AX, NOM, +TOL, -TOL, BONUS, MEAS, DEV, OUTTOL]
```

#### `parse_to_v2(...)`

This method must:

- call `open_report()` if `self.raw_text` is empty,
- call `split_text_to_blocks()` if `self.blocks_text` is empty,
- convert the parsed content into `ParseResultV2`,
- fill `ParseMetaV2`, `ReportInfoV2`, `MeasurementBlockV2`, and
  `MeasurementV2`,
- preserve supplier/reference/date/sample identity correctly.

#### `to_legacy_blocks(...)`

This adapter must convert a `ParseResultV2` back into the legacy `blocks_text`
shape used by compatibility paths.

### Persistence

Generated plugins should not implement database writes. The generic base parser
bridge persists `ParseResultV2` through
`ReportRepository.persist_parsed_report(...)`.

The bridge maps:

- `ParseResultV2.report/meta` to canonical report metadata,
- each `MeasurementV2` to one `report_measurements` row,
- parser warnings to metadata warnings,
- positive `out_of_tolerance` values to NOK status,
- raw tokens, line references, extensions, and block index to
  `raw_measurement_json`.

If `ParseResultV2.errors` is not empty, the bridge raises an error and does not
create a successful parsed-report row. Built-in parsers can still override the
persistence path when they need richer metadata extraction.

### Output Quality Rules

The generated plugin must:

- stay within the existing Metroliza parser architecture,
- use only stdlib plus imports already allowed by the scaffold,
- avoid network access, subprocess calls, or unrelated filesystem scanning,
- avoid new package dependencies,
- avoid non-deterministic behavior,
- avoid changing global runtime flags or factory logic,
- avoid direct SQLite connections, table creation, or database writes.

### Test Requirements

`tests/test_generated_plugin.py` must:

- import the generated parser class,
- instantiate it against a sample file,
- exercise `probe(...)` for the same sample,
- assert the result is `ParseResultV2` when parsing is implemented,
- assert the `plugin_id` matches the requested value,
- use the workspace `expected_results_template.csv` as the correctness
  reference for manual review or semantic validation.

### Advanced Python Commands

Create an advanced generated-plugin workspace:

```bash
python scripts/create_parser_plugin_workspace.py --plugin-id supplier_alpha --source-format pdf
```

Validate an advanced generated Python plugin:

```bash
python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf --expected-results expected_results_template.csv
```

Generate a repair prompt after failed validation:

```bash
python scripts/build_parser_plugin_repair_prompt.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf --expected-results expected_results_template.csv --output artifacts/repair_prompt.md
```

Explain why a specific report selects one plugin over another:

```bash
python scripts/explain_parser_resolution.py samples/sample_report_01.pdf --paths generated_plugin.py
```

After advanced generated-plugin validation passes, the generated plugin file is
installed by copying it to:

```text
~/.metroliza/parser_plugins/<plugin-id>.py
```

Metroliza will auto-discover that file and include it in parser factory
resolution on the next app start or process start.

### Advanced Python Definition Of Done

- Advanced Python plugin validation passes via
  `scripts/validate_parser_plugins.py`.
- The parsed result matches the manually verified values in
  `expected_results_template.csv`.
- The plugin file is installed in its approved runtime location.
- Metroliza selects the plugin for the intended supplier report format.
- Rollout approval follows the parser plugin runbook.

## Implementation Pointers For Future Codex Sessions

Future sessions that refine the parser profile or LLM handoff builder should
start here, then check:

1. `src/metroliza/parsing/parser_profile_handoff.py` for declarative handoff
   package creation, integrity checks, validation artifacts, repair prompts, and
   install helpers.
2. `src/metroliza/ui/parser_plugin_wizard.py` for the in-app
   handoff/validation actions.
3. `scripts/parser_plugin_self_service.py` for the non-technical/operator CLI.
4. `src/metroliza/parsing/declarative_parser_profiles.py` for YAML profile
   validation, approval, loading, and runtime constraints.
5. `src/metroliza/parsing/llm_plugin_factory/scaffold.py` for advanced Python
   plugin package files.
6. `src/metroliza/parsing/parser_plugin_repair_loop.py` for advanced generated
   plugin repair prompts.
7. `src/metroliza/parsing/parse_result_v2_persistence.py` and
   `src/metroliza/parsing/base_report_parser.py` for the generic V2-to-SQLite
   bridge.
8. `src/metroliza/parsing/parse_reports_thread.py` and
   `src/metroliza/reports/report_parser_factory.py` for runtime discovery,
   source-format filtering, and batch failure isolation.
9. `tests/test_parser_plugin_contracts.py`, `tests/test_parser_plugin_wizard.py`,
   `tests/test_parser_plugin_repair_loop.py`, `tests/test_parser_plugin_scripts.py`,
   `tests/test_parser_plugin_self_service_cli.py`, `tests/test_thread_flow_helpers.py`,
   `tests/test_declarative_parser_profiles.py`, and `tests/test_report_parser_factory.py`
   for acceptance coverage.
