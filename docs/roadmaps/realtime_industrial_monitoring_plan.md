# Realtime Industrial Monitoring Plan

## Status

Active plan for introducing realtime industrial monitoring as a separate layer
from manual Industrial Data fetches, CSV Summary, and report parsing.

The operator-facing guide is
[Realtime Industrial Monitoring](../user_manual/realtime_industrial_monitoring.md).
The release gate is
[Realtime Industrial Monitoring Rollout Checklist](../release_checks/realtime_industrial_rollout_checklist.md).

## Goal

Give operators a safe way to see unusual production values, source delays, and
limit crossings close to when they happen. The monitor must read production
data, store local samples and events, explain why an event was raised, and allow
rollback without affecting the production database.

## Non-Goals

- Do not write to the production database.
- Do not replace local quality procedures.
- Do not make automatic scrap, hold, or release decisions.
- Do not start with GUI-only behavior before replay, storage, detector, and
  rollback checks are ready.
- Do not add heavy machine-learning dependencies for the first rollout unless
  the release owner explicitly asks for them.
- Do not store passwords, tokens, or full connection strings in docs, test
  fixtures, screenshots, or logs.

## Concepts Used By The Plan

- A signal is one watched value from the production source.
- A sample is one value for one signal at one event time.
- Event time is when the value happened on the line.
- Ingest time is when Metroliza saw or copied the value.
- A baseline is the approved normal behavior for a signal.
- A detector is a rule that checks samples.
- An anomaly event is the record created when a detector flags a sample.
- Severity is the review priority: critical, major, warning, or info.

## Workstreams

| Workstream | Owner focus | Done when |
|---|---|---|
| Source safety | Read-only access, approved columns, bounded polling, source lag visibility. | A pilot source can be polled without writes, unbounded fetches, or hidden lag. |
| Signal setup | Signal names, units, limits, segment fields, and enabled state. | Operators and the process owner agree that watched signals mean the right thing. |
| Replay and baselines | Synthetic replay, historical replay, baseline review, false-positive review. | Replay catches known problems and normal historical data is not noisy. |
| Detector behavior | Spec-limit, drift/statistical, and stale-source events with explanations. | Each event says what happened, why it was flagged, and how urgent it is. |
| Operator workflow | Severity meanings, event review, false-positive handling, escalation owners. | Operators know how to respond without treating severity as an automatic quality decision. |
| Release and rollback | Rollout checklist, evidence, disable path, return to manual workflow. | The source can be paused and the team can return to manual Industrial Data and CSV Summary. |

## Phase 1: Foundation

- Keep realtime monitoring separate from the manual Industrial Data and CSV
  Summary workflow.
- Store source offsets, signals, samples, baselines, detector settings, and
  anomaly events in local Metroliza storage.
- Keep production database access read-only.
- Require bounded reads for live polling.
- Store event time and ingest time for every sample.
- Keep source lag visible.

## Phase 2: Replay Before Live

- Run the synthetic fixture matrix described in
  [Realtime Industrial Validation Fixtures](../realtime_industrial_validation.md).
- Replay recent historical data from the intended source before polling live.
- Review false positives with the process owner.
- Adjust warning limits, specification limits, segment fields, or baselines only
  after review.
- Keep replay output as release evidence.

## Phase 3: Live Pilot

- Start with one source and a small set of approved signals.
- Use a conservative polling interval approved by the source owner.
- Confirm that each live read is bounded by a cursor, time window, row limit, or
  equivalent guard.
- Watch source lag, row counts, duplicate events, and operator feedback.
- Pause polling if source lag grows or event volume becomes noisy.

## Phase 4: Operator Rollout

- Give operators the
  [Realtime Industrial Monitoring](../user_manual/realtime_industrial_monitoring.md)
  guide before the pilot.
- Review critical, major, warning, and info meanings.
- Explain the difference between spec-limit events and process-drift events.
- Agree how false positives are marked and reviewed.
- Name escalation owners for process issues and source access issues.

## Phase 5: Release Gate

Use the
[Realtime Industrial Monitoring Rollout Checklist](../release_checks/realtime_industrial_rollout_checklist.md)
before the feature is considered release-ready.

The release evidence must show:

- synthetic replay passed,
- historical replay was reviewed,
- no unbounded fetch path remains,
- source lag was verified,
- thresholds were reviewed by the process owner, and
- rollback steps were tested or explicitly accepted by the release owner.

For detector throughput checks, use
[Realtime Detector Throughput Benchmark](../perf_realtime_detectors.md) as a
local regression signal.

## Rollback Plan

Rollback must be possible without changing the production database.

1. Disable scheduled polling or the realtime source profile.
2. Keep local samples and events for review.
3. Return operators to manual Industrial Data fetches and CSV Summary.
4. Review source lag, thresholds, false positives, and polling interval.
5. Re-enable only after the process owner and release owner accept the change.

## Open Follow-Ups

- Decide how operator acknowledgements and false-positive comments appear in the
  first UI.
- Decide how much source-lag history operators need on screen.
- Decide whether baselines are refreshed manually only or through a reviewed
  scheduled job.
- Decide which events should be included in release evidence for the first pilot.
