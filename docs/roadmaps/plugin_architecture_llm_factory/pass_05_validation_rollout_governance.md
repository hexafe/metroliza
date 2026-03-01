# Pass 5 — Validation, Rollout, and Governance

## Goal
Define operational controls for safe rollout of plugin architecture and LLM-generated plugins.

## Required outputs
1. End-to-end acceptance gates.
2. Rollout sequence by template/supplier.
3. Rollback and incident procedures.
4. Governance model for plugin quality.

## Validation strategy

### Test layers
- Unit tests: schema contracts, adapters, detector logic.
- Contract tests: every plugin must pass base parser contract suite.
- Fixture tests: supplier/template-specific expected outputs.
- Integration tests: parse thread + dedup + DB insertion flow.
- Regression tests: ensure legacy behavior compatibility during migration.

### Performance gates
Define measurable thresholds (to be finalized by baseline):
- Parse throughput delta vs baseline.
- Peak memory overhead.
- Failure rate under malformed input corpus.

### Native backend parity gate
For plugins using native acceleration:
- semantic parity with python path required,
- automatic fallback behavior validated,
- failure mode when native forced but unavailable validated.

## Rollout sequence
1. Dark launch: plugin architecture enabled, legacy path remains default.
2. Internal canary: selected templates/suppliers.
3. Regional canary: include diverse locale suppliers.
4. Broad rollout with monitoring.
5. Legacy deprecation decision checkpoint.

## Feature flags / controls
- `PARSER_PLUGIN_RUNTIME_ENABLED`
- `PARSER_V2_ENABLED`
- `PARSER_LEGACY_ADAPTER_REQUIRED`
- `PARSER_TEMPLATE_OVERRIDE=<plugin_id>`
- `PARSER_STRICT_MATCHING=true|false`

## Governance model
- Plugin ownership required (team + backup owner).
- Semantic versioning for plugin changes.
- Mandatory changelog entries for mapping/tolerance logic updates.
- Periodic conformance re-validation for active plugins.

## Rollback procedure
- Disable plugin runtime flag to return to legacy parser path.
- Freeze newly generated plugins.
- Revert to previous known-good plugin registry snapshot.
- Trigger incident review with captured diagnostics.

## Acceptance criteria
- Rollout/rollback runbook approved by operations.
- Alerts and dashboards defined for parse failures and fallback spikes.
- Governance checklist integrated into PR process.

## Risks
- Silent drift in plugin behavior over time.
- Operational complexity with many supplier-specific plugins.

## Fallback
- Periodic re-certification and stale-plugin retirement policy.
- Global emergency switch back to compatibility mode.

## Jira seed checklist
- [ ] Define plugin conformance CI gate.
- [ ] Define rollout stage checklist.
- [ ] Define monitoring dashboards and alerts.
- [ ] Define incident + rollback runbook.
- [ ] Define plugin ownership and review policy.
- [ ] Define legacy deprecation decision rubric.
