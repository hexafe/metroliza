# Parser Plugin Docs

This directory is the active documentation set for adding Metroliza support for
new supplier report templates.

## Default Route: Declarative YAML Profile

Most work should use a **declarative parser profile**. This is a reviewed
`profile.yaml` file that trusted Metroliza code reads at runtime. It is the
normal route for non-technical users and for LLM-assisted handoff.

Use this route when the supplier report can be described with:

- stable text markers that identify the template,
- regex patterns for report reference, report date, and sample number,
- line-based measurement row patterns,
- date and decimal normalization rules.

Open the in-app workflow from:

```text
Tools > Parser profiles...
```

The dialog can create a handoff folder, open it, copy its path, check the
package, validate the profile, diagnose parser selection, create a repair
prompt, and install an approved profile. After installation, restart Metroliza
and parse reports through the normal report import flow.

## Advanced Route: Python Plugin

Use an advanced generated Python plugin only when the YAML profile route cannot
model the supplier template. Examples include reports that need custom
pre-processing, multi-stage parsing, unusual document decoding, or logic that
cannot be expressed as data-only extraction rules.

This route is operator-only. Python plugin output must stay inside the existing
Metroliza parser architecture and must not add network calls, package
installation, shell commands, direct database writes, or unrelated runtime
changes.

## Use These Docs

- [`../user_manual/parser_profiles.md`](../user_manual/parser_profiles.md):
  plain-English in-app manual for **Tools > Parser profiles...**.
- [`non_technical_workflow.md`](./non_technical_workflow.md): step-by-step
  YAML profile workflow from sample collection to installation.
- [`parser_plugin_specification.md`](./parser_plugin_specification.md): exact
  contract for declarative profiles and the advanced Python fallback.
- [`../release_checks/parser_plugin_rollout_runbook.md`](../release_checks/parser_plugin_rollout_runbook.md):
  rollout, rollback, and review controls for production activation.

## Glossary

- **Parser profile**: a data-only YAML file that tells Metroliza how to parse
  one report template.
- **Handoff folder**: the local workspace created by the app for samples,
  expected results, prompts, contracts, and profile drafts.
- **Sample report**: a real report from the supplier/template you want to parse.
- **Expected results**: the manually checked rows in `expected_results.csv` that
  validation must match exactly.
- **Probe**: the quick check that decides whether a parser probably matches a
  report.
- **Diagnose**: the action that explains profile selection and parse evidence
  for one sample report.
- **Repair prompt**: a focused prompt built from a validation failure so a
  reviewer or LLM can return a corrected `profile.yaml`.
- **Advanced Python plugin**: a Python parser file for operator-only cases where
  YAML is not expressive enough.

## In-App Self-Service

The handoff folder created by **Tools > Parser profiles... > Create Handoff
Folder** includes:

- `profile.yaml` with the declarative parser profile template,
- `samples/` for representative supplier reports,
- `expected_results.csv` for every parsed row in each approval sample,
- `llm_handoff.md` for instructions to use with an approved LLM or reviewer,
- `handoff_manifest.json` for package identity, allowed outputs, and validation
  commands,
- `contracts/` and `reference/contract_snippets.md` with the parser API,
  runtime selection, SQLite persistence boundary, expected-results contract,
  safety rules, and privacy-redaction checklist,
- `prompts/` with small sequential tasks for local, cheap, or disconnected LLMs,
- `NON_TECHNICAL_STEPS.md` with the same workflow written as a checklist.

Metroliza does not call an LLM from this dialog. It prepares local files for
review and handoff, then provides folder actions plus package check, validation,
diagnose, repair-prompt, and install actions for the hidden profile workspace.

## Tiny Copyable Example

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

## When To Ask For Help

Stop and ask an operator, release owner, or data owner when:

- privacy is uncertain or you are unsure whether samples may be shared,
- you do not have representative samples,
- validation fails repeatedly after repair,
- Diagnose shows that the wrong parser is selected,
- parsed values pass technically but do not match the report's business meaning,
- the sample set includes multiple visible layouts,
- any LLM output adds Python, network access, package installation, shell
  commands, database-write behavior, or installer changes.

## YAML Profile Commands

Create a declarative profile handoff folder from the app:

```text
Tools > Parser profiles... > Create Handoff Folder
```

The matching CLI commands are available for operators and automation:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py handoff --plugin-id supplier_alpha --source-format pdf --output-dir <handoff-folder>
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py integrity <handoff-folder>
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder>
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose <handoff-folder>/profile.yaml <handoff-folder>/samples/sample_report_01.pdf
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py repair <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --output <handoff-folder>/artifacts/profile_repair_prompt.md
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --approved-by operator
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py evidence supplier_alpha
```

## Runtime Loading

- Metroliza automatically discovers approved declarative profiles under
  `~/.metroliza/parser_plugins/profiles/approved/`.
- Metroliza automatically discovers advanced parser plugin files placed in
  `~/.metroliza/parser_plugins/`.
- Normal report import discovers `.pdf`, `.csv`, `.xlsx`, and `.xls` files when
  an installed parser manifest supports the corresponding source format.
- The file suffix is only a transport/discovery gate. The parser factory asks
  compatible plugins to recognize the report family from decoded contents and
  requires semantic measurement-row evidence from current plugins.
- Semantic matches rank ahead of legacy lexical matches, followed by confidence
  and manifest priority. A remaining tie is reported as ambiguous instead of
  selecting a parser by name.
- Match and no-match probe results are cached by source content and registry
  generation. Inspection failures are retried instead of becoming sticky.
- Registry refresh is validated, single-flight, and atomic. Removed or disabled
  plugins disappear from the next generation, and external plugins cannot
  replace reserved built-in ids such as `cmm`.
- `PARSER_EXTERNAL_PLUGIN_PATHS` remains available for advanced overrides and
  developer testing.

## Manifest Governance

- `plugin_id` must be stable and unique because it is the registry key. Duplicate
  ids are rejected; explicit replacement is limited to non-built-in manual
  registrations.
- Parser classes must be constructible with `file_path`, `database`, and the
  optional `connection` keyword, and their probe must accept `(input_ref,
  context)`. Invalid signatures are rejected before a registry generation is
  published.
- `display_name` is for human-facing UI and logs.
- `supported_formats` must list every format the parser is allowed to consider
  during selection.
- `supported_locales`, `template_ids`, and `capabilities` are metadata fields
  used for policy, diagnostics, and review, not for hidden registration logic.
- `priority` is a tie-breaker only after semantic evidence and confidence.

## Advanced Python Commands

Create an advanced generated-plugin workspace:

```bash
python scripts/create_parser_plugin_workspace.py --plugin-id supplier_alpha --source-format pdf
```

Validate an advanced generated Python plugin:

```bash
python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf --expected-results expected_results_template.csv
```

Generate a repair prompt after failed advanced-plugin validation:

```bash
python scripts/build_parser_plugin_repair_prompt.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf --expected-results expected_results_template.csv --output artifacts/repair_prompt.md
```

Explain why a specific report selects one plugin over another:

```bash
python scripts/explain_parser_resolution.py samples/sample_report_01.pdf --paths generated_plugin.py
```

## Historical Design Context

Archived parser-plugin design notes and superseded quickstart/status docs are
under [`../archive/2026/feature-parser-plugin-factory/README.md`](../archive/2026/feature-parser-plugin-factory/README.md).
