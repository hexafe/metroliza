# Parser Plugin Docs

This directory is the active documentation set for creating, validating, installing, and operating Metroliza parser support for new supplier report templates.

Most supplier-template work should use **declarative parser profiles**. A profile is a reviewed YAML file that Metroliza reads with trusted in-app code. Generated Python parser plugins remain an advanced/operator-only path.

## Use these docs

- [`parser_plugin_specification.md`](./parser_plugin_specification.md) — the exact contract and output requirements for declarative profiles and advanced generated parser plugins.
- [`non_technical_workflow.md`](./non_technical_workflow.md) — step-by-step guide for a non-technical user from sample collection to installation.
- [`../release_checks/parser_plugin_rollout_runbook.md`](../release_checks/parser_plugin_rollout_runbook.md) — rollout, rollback, and review controls for production activation.

## In-app self-service

Open **Tools > Parser profiles...** from the main window.

The dialog shows the local profile store status and can create a handoff folder for a new supplier template. The folder includes:

- `profile.yaml` with the declarative parser profile template,
- `samples/` for representative supplier reports,
- `expected_results.csv` for manually checked values,
- `llm_handoff.md` for instructions to use with an external LLM or manual authoring workflow.

Metroliza does not call an LLM from this dialog. It only prepares local files for review and handoff, then offers **Open Folder** and **Copy Path** actions for the hidden profile workspace.

## Runtime loading

- Metroliza automatically discovers parser plugin files placed in `~/.metroliza/parser_plugins/`.
- Metroliza also discovers approved declarative profiles under `~/.metroliza/parser_plugins/profiles/approved/`.
- The parser factory infers the report source format from the file suffix, filters plugins whose manifests declare that format, asks each remaining plugin to `probe(...)`, and selects the best match by confidence, then manifest priority, then plugin id.
- Probe results are cached per plugin/path during the process lifetime so batch parsing does not repeat the same work.
- `PARSER_EXTERNAL_PLUGIN_PATHS` remains available for advanced overrides and developer testing.

## Manifest governance

- `plugin_id` must be stable and unique because it is the registry key.
- `display_name` is for human-facing UI and logs.
- `supported_formats` must list every format the parser is allowed to consider during selection.
- `supported_locales`, `template_ids`, and `capabilities` are metadata fields used for policy, diagnostics, and review, not for hidden registration logic.
- `priority` is a tie-breaker only. Higher values win when confidence is equal.

## Quick commands

Create a declarative profile handoff folder from the app:

```text
Tools > Parser profiles... > Create Handoff Folder
```

Validate and approve a declarative profile from a handoff folder:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder>
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose <handoff-folder>/profile.yaml <handoff-folder>/samples/sample_report_01.pdf
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install <handoff-folder>/profile.yaml --expected-results <handoff-folder>/expected_results.csv --workspace <handoff-folder> --approved-by operator
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py evidence supplier_alpha
```

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

## Historical design context

Archived parser-plugin design notes and superseded quickstart/status docs are under [`../archive/2026/feature-parser-plugin-factory/README.md`](../archive/2026/feature-parser-plugin-factory/README.md).
