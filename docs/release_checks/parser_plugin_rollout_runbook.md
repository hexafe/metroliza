# Parser Plugin Rollout / Rollback Runbook

## Purpose
Operational checklist for enabling parser-plugin updates (including LLM-assisted candidates) with clear ownership and rollback controls.

Active operator docs:

- [`../parser_plugins/README.md`](../parser_plugins/README.md)
- [`../parser_plugins/non_technical_workflow.md`](../parser_plugins/non_technical_workflow.md)
- [`../parser_plugins/llm_plugin_specification.md`](../parser_plugins/llm_plugin_specification.md)

## PR governance checklist
Use this checklist on parser plugin PRs before merge:

- [ ] Plugin owner and backup owner are listed in the PR description.
- [ ] Workspace and sample pack were prepared with `python scripts/create_parser_plugin_workspace.py ...` or an equivalent documented packet.
- [ ] Plugin manifest versioning decision is documented (`patch`/`minor`/`major`).
- [ ] `python scripts/validate_parser_plugins.py` output is attached.
- [ ] `expected_results_template.csv` or an equivalent fixture comparison summary is attached.
- [ ] If validation failed during development, repair-loop artifact (`scripts/build_parser_plugin_repair_prompt.py`) is attached or linked.
- [ ] Fixture deltas are reviewed by a human approver.
- [ ] Resolver diagnostics for the representative sample show the intended plugin winning for the intended report.
- [ ] Rollback strategy is noted (disable via feature flag and/or revert registry change).

## Staged rollout checklist

1. **Dark launch**
   - Keep legacy path available.
   - Enable plugin in non-production/preview environment.
2. **Internal canary**
   - Run representative supplier fixtures.
   - Watch parse failure and fallback metrics.
3. **Regional canary**
   - Include locale-diverse suppliers.
   - Compare unresolved field counts to baseline.
4. **Broad rollout**
   - Record final sign-off and promotion timestamp.

## Installation note

Validated end-user parser plugins are installed by copying the final plugin file into:

`~/.metroliza/parser_plugins/`

Metroliza auto-discovers plugins from that folder on the next process start.

## Rollback steps

1. Disable plugin runtime flag or template override.
2. Revert plugin registration/package to last known-good version.
3. Re-run validation gate on restored snapshot and confirm resolver diagnostics still select the expected parser.
4. Publish incident note with impact, mitigation, and follow-up owner.

## Legacy deprecation rubric
Only remove legacy parser path when all are true:

- At least 14 days of stable CI + canary signal.
- No unresolved must-fix defects for migrated templates.
- Explicit owner sign-off for rollback confidence.
