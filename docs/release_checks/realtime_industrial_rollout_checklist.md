# Realtime Industrial Monitoring Rollout Checklist

Use this checklist before realtime industrial monitoring is enabled for a
release candidate, pilot line, or production source.

This checklist is about safe rollout. It does not allow writing to the
production database, bypassing local quality rules, or storing raw secrets in
docs, tickets, screenshots, or logs.

## Required References

- Operator guide:
  [Realtime Industrial Monitoring](../user_manual/realtime_industrial_monitoring.md)
- Rollout plan:
  [Realtime Industrial Monitoring Plan](../roadmaps/realtime_industrial_monitoring_plan.md)
- Detector fixture matrix:
  [Realtime Industrial Validation Fixtures](../realtime_industrial_validation.md)
- Local detector benchmark:
  [Realtime Detector Throughput Benchmark](../perf_realtime_detectors.md)

## Safety And Source Setup

- [ ] The source profile uses read-only database access.
- [ ] The profile points to an approved table, view, or reviewed read-only query.
- [ ] The approved column list is documented without passwords, tokens, or full
      connection strings.
- [ ] Credentials are entered only through the app or approved local credential
      prompt.
- [ ] The first live source has a named process owner and support owner.
- [ ] The polling interval is approved by IT, MES support, or the source owner.
- [ ] The polling interval is longer than the source update cycle.
- [ ] The live read is bounded by a cursor, event-time window, row limit, or
      equivalent guard.
- [ ] There is no unbounded fetch path in the live polling loop.

## Signal And Threshold Review

- [ ] Every enabled signal has a clear operator-facing name.
- [ ] Every enabled signal has the correct unit or an explicit "unit not used"
      decision.
- [ ] Station, line, part, revision, or other segment fields are reviewed.
- [ ] Warning limits are reviewed by the process owner.
- [ ] Specification limits are reviewed by the process owner.
- [ ] Baseline source data is approved for the current process state.
- [ ] Detector severity mapping is reviewed and understood.
- [ ] Threshold changes are recorded in release notes or rollout evidence.

## Replay Gate

- [ ] Synthetic replay pass completed.
- [ ] Expected synthetic spec-limit events were produced.
- [ ] Expected synthetic process-drift or statistical events were produced.
- [ ] Synthetic normal-process data stayed quiet.
- [ ] Historical replay completed before live polling.
- [ ] Historical replay used recent data from the target line or a representative
      source.
- [ ] False positives from replay were reviewed.
- [ ] Thresholds were adjusted only with process-owner approval.
- [ ] Replay output was kept as release evidence.

## Live Source Lag And Load

- [ ] Source lag was checked during the pilot run.
- [ ] Event time and ingest time were compared.
- [ ] Stale-source events were reviewed before process conclusions were made.
- [ ] Repeated polling did not duplicate samples or events.
- [ ] Row counts stayed within the approved range.
- [ ] Database owners saw no unacceptable load from polling.
- [ ] Operators know whom to contact when source lag grows.

## Operator Readiness

- [ ] Operators have the realtime monitoring guide.
- [ ] Critical, major, warning, and info meanings are reviewed with operators.
- [ ] Operators know the difference between spec-limit events and process-drift
      events.
- [ ] Operators know how to record or mark false positives.
- [ ] Operators know that severity is a review priority, not an automatic scrap
      decision.
- [ ] Escalation owners are named for process issues and source access issues.

## Implementation Checkpoints

- [x] 2026-06-14: Added direct CMM parser probe regressions so generic PDFs do
      not score as perfect CMM matches.
- [x] 2026-06-14: Added realtime stream config validation, sample mapping,
      bounded poll query, one-cycle service, source runtime, and offset-safety
      tests.
- [x] 2026-06-14: Added diagnostics/security regressions for nested secret
      redaction, URI credential redaction, and safe SQL metadata.
- [x] 2026-06-14: Added parser plugin handoff package completeness tests for
      LLM-ready local contract content and small ordered implementation steps.
- [x] 2026-06-14: Added no-selected-database realtime dashboard launch coverage
      using a temporary session SQLite store.
- [x] 2026-06-14: Focused validation passed:
      `111 passed` across CMM probe, parser plugin contracts, realtime
      dashboard launch, industrial source/security, Oznak adapter, and realtime
      poller/config/service tests.
- [x] 2026-06-14: Broader #1/#2 suite passed:
      `416 passed, 2 skipped` across realtime, anomaly, industrial, Oznak,
      CMM probe, and parser plugin contract tests.
- [x] 2026-06-14: Full local pytest passed:
      `2065 passed, 289 skipped, 83 subtests passed`.
- [x] 2026-06-14: Realtime/anomaly source slice coverage measured at `89%`.
- [x] 2026-06-14: Final CI-shaped combined coverage rerun passed at `82%`,
      above the `80%` release gate. The earlier one-shot whole-scope coverage
      probe was not the release gate because it omitted the UI/dialog coverage
      shards used by CI.
- [x] 2026-06-14: Local realtime detector benchmark completed through `100,000`
      synthetic samples. Observed throughput was about `2,101 samples/sec` for
      all deterministic detectors together; rolling z-score dominated runtime
      and should stay visible in future optimization reviews.
- [x] 2026-06-14: Final staged release hygiene passed after adding a narrow
      allowlist for the named synthetic realtime CSV fixtures.
- [x] 2026-06-14: Pushed GitHub CI passed for commit
      `307acd16031c5622093ba52a9a64d2b2146d7f02` in run
      [`27506446912`](https://github.com/hexafe/metroliza/actions/runs/27506446912).
- [x] 2026-06-15: Replaced the static monitor launch with a modeless
      realtime monitoring dialog that supports multi-source checkboxes,
      persisted polling configuration, status, diagnostics, raw/aggregated
      dashboard output, and live bounded polling through the existing Oznak
      credential store.
- [x] 2026-06-15: Focused realtime/UI validation passed:
      `96 passed` across realtime config, poller, schema, Oznak realtime
      adapter, monitor dialog, dashboard service/HTML, and main-window tests.
- [x] 2026-06-15: Local release gates passed:
      `ruff check .`, `compileall`, release metadata sync, release hygiene,
      and full offscreen pytest (`2078 passed, 293 skipped, 6 warnings,
      83 subtests passed`).
- [x] 2026-06-15: Security audit passed after allowing the temporary
      `pip-audit` environment to upgrade. `pip-audit` reported no known
      vulnerabilities; existing Bandit findings remain report-only baseline
      warnings.

## Rollback Steps

Before rollout, confirm each step can be done by the named owner.

1. Disable the realtime source profile or scheduled polling.
2. Disable the affected detector or signal only if the process owner approves.
3. Keep the local event and sample history for review.
4. Return operators to manual Industrial Data fetches and CSV Summary if
   monitoring is paused.
5. Record the rollback reason, time, owner, and affected source.
6. Review thresholds, polling interval, source lag, and false positives before
   re-enabling live monitoring.
7. If the release itself must be rolled back, revert the release branch or
   deployment package using the normal release playbook.

## Final Sign-Off

- [ ] Documentation updated and indexed.
- [ ] Synthetic replay pass recorded.
- [ ] Historical replay pass recorded.
- [ ] Source lag verified.
- [ ] No unbounded fetch path remains.
- [ ] Thresholds reviewed by the process owner.
- [ ] Rollback steps reviewed.
- [ ] Release owner accepts remaining risks.
