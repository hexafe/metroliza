## Linked Issue

- Primary Issue: Closes #
- Related Issues/PRs:

A normal PR should have one primary Issue. Use `Refs #...` instead of `Closes #...` when this is only one slice of a larger Issue.

## Change type

- [ ] Bug fix
- [ ] Feature
- [ ] Behavior-preserving refactor
- [ ] Tests / quality
- [ ] Performance
- [ ] Security
- [ ] Documentation / governance
- [ ] CI / packaging / release evidence
- [ ] Research / decision record

## Summary

What changed, why it is needed, and who/which workflow benefits?

## Scope and non-goals

### In scope

-

### Explicitly not in scope

-

## Contracts and risk

Check every affected surface and describe it below.

- [ ] SQLite/schema/data ownership or migration
- [ ] Parser/profile/plugin contract
- [ ] Public import or `modules.*` compatibility
- [ ] Workbook sheet/table/formula behavior
- [ ] Dashboard DOM, local-storage, manifest, or publication behavior
- [ ] Environment variable/configuration
- [ ] Native/Rust backend or Python fallback
- [ ] Packaging/frozen executable/resources
- [ ] Credentials, security boundary, dependency, or sensitive diagnostics
- [ ] Release metadata/evidence
- [ ] None of the above

Risk/compatibility notes:

## Failure, cancellation, and rollback

- Failure behavior:
- Cancellation/shutdown behavior:
- Rollback/feature-disable path:
- Prior data/artifact safety:

## Validation tier

- [ ] Tier 0 — documentation/process only
- [ ] Tier 1 — focused behavior
- [ ] Tier 2 — subsystem integration
- [ ] Tier 3 — full repository CI
- [ ] Tier 4 — packaged/manual release evidence

## Validation evidence

List exact commands and outcomes. Do not write only “tests passed”.

```text
command:
result:
```

For CI/release work include the exact commit SHA, workflow run ID, terminal job status, skipped lanes, coverage, and artifacts.

## UI / artifact evidence (when applicable)

- [ ] Screenshots/captures use sanitized data.
- [ ] Workbook/dashboard/packaged artifacts were inspected, not only unit-tested.
- [ ] Accessibility/keyboard and compact-window behavior were considered for shared UI changes.

Evidence/location:

## Google conversion smoke-check evidence (required when applicable)

This section is required when the PR touches `src/metroliza/exporting/google_drive_export.py`,
`src/metroliza/exporting/export_backends.py`, `src/metroliza/exporting/export_data_thread.py`, Google
export UI/contracts, or the Google transport/credential boundary.

- [ ] Live smoke evidence is included, or omission is explicitly justified because this PR is not claiming a releasable Google behavior.
- Command:
- Date/time:
- Exact SHA/build:
- Environment/sandbox account description (no credentials):
- Pass/fail:
- File ID/HTTPS URL and required-tab validation:
- Cancellation/cleanup result:
- Local `.xlsx` fallback observed:
- Sanitized log/evidence location:

## Documentation and release impact

- [ ] User manual updated or no user-visible behavior changed.
- [ ] `docs/project/` updated when product/architecture/roadmap/workflow changed.
- [ ] `docs/release_checks/` updated only when actual release evidence changed.
- [ ] `CHANGELOG.md`/version metadata updated or not required.
- [ ] New active docs are indexed in `docs/README.md`.
- [ ] Superseded temporary docs were archived/reclassified.

## Final checklist

- [ ] The PR matches the linked Issue acceptance criteria.
- [ ] The change is small/reviewable, or the reason for an integration-sized PR is documented.
- [ ] Behavior changes are separated from structural refactors unless explicitly approved.
- [ ] New/touched implementation uses canonical `metroliza.*` imports; `modules.*` remains compatibility-only.
- [ ] Tests cover the changed contract and relevant failure path.
- [ ] No credentials, OAuth tokens, proprietary reports, production extracts, private keys, or unredacted sensitive diagnostics are included.
- [ ] Follow-up work has separate Issues rather than hidden TODOs.
- [ ] CI/manual evidence refers to the exact PR head.
