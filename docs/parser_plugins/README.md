# Parser Plugin Docs

This directory is the active documentation set for creating, validating, installing, and operating Metroliza parser plugins for new supplier report templates.

## Use these docs

- [`llm_plugin_specification.md`](./llm_plugin_specification.md) — the exact contract and output requirements for an LLM-generated parser plugin.
- [`non_technical_workflow.md`](./non_technical_workflow.md) — step-by-step guide for a non-technical user from sample collection to installation.
- [`../release_checks/parser_plugin_rollout_runbook.md`](../release_checks/parser_plugin_rollout_runbook.md) — rollout, rollback, and review controls for production activation.

## Runtime loading

- Metroliza automatically discovers parser plugin files placed in `~/.metroliza/parser_plugins/`.
- The parser factory inspects the loaded report format, asks compatible plugins to `probe(...)`, and selects the best match by confidence, then priority, then plugin id.
- `PARSER_EXTERNAL_PLUGIN_PATHS` remains available for advanced overrides and developer testing.

## Quick commands

Create a workspace:

```bash
python scripts/create_parser_plugin_workspace.py --plugin-id supplier_alpha --source-format pdf
```

Validate a generated plugin:

```bash
python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf
```

Generate a repair prompt after failed validation:

```bash
python scripts/build_parser_plugin_repair_prompt.py --paths generated_plugin.py --plugin-id supplier_alpha --sample-input samples/sample_report_01.pdf --output artifacts/repair_prompt.md
```

## Historical design context

The planning/design package that led to this workflow remains under [`../roadmaps/plugin_architecture_llm_factory/README.md`](../roadmaps/plugin_architecture_llm_factory/README.md). Superseded intermediate quickstart/status docs are archived under [`../archive/2026/feature-parser-plugin-factory/README.md`](../archive/2026/feature-parser-plugin-factory/README.md).
