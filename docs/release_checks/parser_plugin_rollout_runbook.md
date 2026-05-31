# Parser Plugin Rollout / Rollback Runbook

## Purpose
Operational checklist for enabling parser-plugin updates with clear ownership and rollback controls.

Active operator docs:

- [`../parser_plugins/README.md`](../parser_plugins/README.md)
- [`../parser_plugins/non_technical_workflow.md`](../parser_plugins/non_technical_workflow.md)
- [`../parser_plugins/parser_plugin_specification.md`](../parser_plugins/parser_plugin_specification.md)

## PR governance checklist
Use this checklist on parser plugin PRs before merge:

- [ ] Plugin owner and backup owner are listed in the PR description.
- [ ] Workspace and sample pack were prepared with **Tools > Parser profiles...** for declarative profiles, `python scripts/create_parser_plugin_workspace.py ...` for advanced Python plugins, or an equivalent documented packet.
- [ ] Profile/plugin versioning decision is documented (`patch`/`minor`/`major`).
- [ ] For declarative profiles, `python scripts/parser_plugin_self_service.py validate ...` output is attached.
- [ ] For declarative profiles, `python scripts/parser_plugin_self_service.py evidence <profile-id>` output is attached after approval.
- [ ] For advanced Python plugins, `python scripts/validate_parser_plugins.py ...` output is attached.
- [ ] `expected_results.csv`, `expected_results_template.csv`, or an equivalent fixture comparison summary is attached.
- [ ] For declarative profiles, `profile.yaml` is data-only and has no generated Python, subprocess, network, or dependency changes.
- [ ] For declarative profiles, approval metadata/checksum is recorded before production activation.
- [ ] If validation failed during development, repair-loop notes or artifact are attached or linked.
- [ ] Fixture deltas are reviewed by a human approver.
- [ ] Resolver diagnostics for the representative sample show the intended plugin winning for the intended report.
- [ ] Rollback strategy is noted (disable profile/plugin, restore backup, and/or revert registry change).

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

Validated declarative parser profiles are installed under:

`~/.metroliza/parser_plugins/profiles/approved/<profile-id>/`

Each approved profile directory contains `profile.yaml` and `approval.json`. Metroliza ignores a profile when the approval checksum does not match the profile file.

Declarative profiles must be installed through:

```bash
PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install profile.yaml --expected-results expected_results.csv --workspace . --approved-by <approver>
```

Install refuses profiles without at least one sample report and `expected_results.csv` validation evidence.

Advanced validated end-user parser plugins are installed by copying the final plugin file into:

`~/.metroliza/parser_plugins/`

Metroliza auto-discovers approved profiles and advanced plugins on the next process start.

## Rollback steps

1. Disable the affected parser profile or plugin.
2. For declarative profiles, move the current approved profile aside and restore the latest known-good backup.
3. For advanced plugins, revert the plugin file/package to the last known-good version.
4. Re-run validation gate on restored snapshot and confirm resolver diagnostics still select the expected parser.
5. Restart Metroliza or the parsing process so discovery reloads the restored state.
6. Publish incident note with impact, mitigation, and follow-up owner.

## Legacy deprecation rubric
Only remove legacy parser path when all are true:

- At least 14 days of stable CI + canary signal.
- No unresolved must-fix defects for migrated templates.
- Explicit owner sign-off for rollback confidence.
