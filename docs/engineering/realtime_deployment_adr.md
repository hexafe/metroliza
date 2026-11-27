# Realtime monitoring MVP deployment decision

[Issue #919](https://github.com/hexafe/metroliza/issues/919) defines replay and detector
contracts for the operator workflow in [#941](https://github.com/hexafe/metroliza/issues/941).

## Decision

Use the existing desktop process for the MVP, with bounded polling and detector work off
the GUI thread. Keep samples, checkpoints and alert history in the local SQLite store.
Use the same detector contract for historical CSV replay and the worker that consumes
committed samples. A desktop session owns its worker and waits for it to stop before
releasing the database.

Proceed with synthetic replay and explicit operator sessions. Defer live rollout and
unattended execution to #941 and the [rollout checklist](../release_checks/realtime_industrial_rollout_checklist.md).
Before a live pilot, obtain approval for the read-only source, refresh interval and process
response, then measure restart recovery, source load and alert burden on representative replay.
Reconsider a separate worker process or service when a supported unattended use case needs
independent uptime or measurements show the desktop cannot meet its responsiveness or
resource budget. Keep the existing local event log and consumer checkpoint boundary.

| Deployment | Benefit and cost for the MVP |
| --- | --- |
| Desktop process with a background worker | Reuses the operator session, source approvals and local SQLite ownership. Monitoring stops with the desktop. |
| Local worker process | Isolates worker failures from the GUI. Requires supervision, an IPC protocol and explicit ownership of worker and database shutdown. |
| Independently managed service | Enables unattended acquisition and independent restart. Requires a service identity, deployment and monitoring, durable handoff and a reviewed authentication boundary. |

Defer Isolation Forest deployment. The optional experiment below trains and scores in
memory. The production detector registry remains limited to supported deterministic detectors,
and loading legacy pickle-backed model artifacts stays disabled. Reconsider ML after a
cost improvement on held-out target-line replay and approval of a safe model artifact format.

## Operational target and alert cost

Flag specification breaches and process shifts for operator review. Source lateness is a
separate health alert. The plant response plan governs process decisions. A missed specification
breach risks delayed containment. A missed process drift or step delays the investigation.
False alerts consume operator review time and repeated alerts can obscure the next useful event.

The synthetic comparison counts a contiguous run of equal non-normal labels as one episode.
An alert during the episode counts once for detection. Each alert on a normal row costs one
point, missing a labelled specification episode costs 100, missing a labelled process episode
costs 10, and each sample of delay to the first alert costs one. These dimensionless weights
express priorities for the synthetic comparison. Obtain process-owner weights and escalation
targets before using costs to approve a live rollout. Every labelled specification episode
must have an alert from the configured specification rule.

## Time, replay and alert evidence

| Surface | Contract and current limit |
| --- | --- |
| Sample identity and time | Source profile, signal and source record key identify a sample. Event time is the process timestamp normalized to UTC. Ingest time records observation by Metroliza. A source timestamp without an offset uses the source's configured timezone. |
| Live ordering and late data | Poll with the saved source cursor and its record-key tie-breaker when configured. Accept a timestamp on the saved watermark-minus-lateness boundary. Count and skip older values while advancing past consumed source rows. Score each admitted batch by event time and stored sample ID. Previously stored alerts stay immutable when a late row arrives. |
| Ordered replay | Reject decreasing event times before writing. Within a batch, dry run breaks ties by source record key and persisted replay breaks ties by stored sample ID. Stateful results at tied times can differ with mode or batch size. Keep a fixed batch size and use distinct UTC timestamps when comparing the reference modes. Repeating against the same destination deduplicates samples and detector events. Use a fresh destination when evaluating a different configuration. |
| State and warm-up | Score a point before updating detector state. Rolling z-score needs 30 valid earlier values, retains up to 500 and skips scoring with zero variance. Live consumption keeps histories by signal and segment. Ordered CSV replay currently keeps one rolling history per detector for the replayed signal. Compare rolling output on single-segment fixtures until replay isolates segment histories. IQR and MAD use stored statistics for the exact signal and segment from the baselines available at replay start. |
| Missing values and reset | Skip missing values according to the input contract and keep counters or warnings for skipped live rows. A fresh replay starts with empty rolling history. Live restart resumes the durable source and consumer checkpoints, and rolling detection reconstructs its history from persisted samples. The stream validity and offset rules apply during a deliberate reset or reseed. |
| Alert evidence | Retain sample and signal identity, detector identity, observed value, threshold, severity and explanation. Stored IQR and MAD replay adds baseline identity, version and available bounds. A reproducible live alert also needs the exact effective configuration revision and applicable rolling-window or baseline identity. Current consumer retries can read newer signal settings or baselines. Pin that evidence before treating replay as a reconstruction of historical live alerts. |

| Input mode | Ordering, recovery and tradeoff |
| --- | --- |
| Ordered CSV replay | A repeatable local fixture and a bounded batch size support detector comparisons. The file is already ordered and acquisition lateness is outside this path. |
| Cyclic read-only polling | Reuses source queries and a durable cursor. Freshness is limited by the poll interval. Late arrivals need a saved watermark and explicit admission policy. |
| Push or streaming updates | Could improve freshness. The producer and consumer would need stable event IDs, durable offsets and a convention for duplicate and reordered delivery. Defer this input mode until a source requires it and replay can verify its restart behavior. |

The [SQLite event-stream design](../roadmaps/sqlite_realtime_event_stream.md) describes
at-least-once handling and idempotence. Pin the effective configuration and baseline,
define a tie-break shared by stored and dry-run replay, and bound isolated segment histories
before using replay to reproduce historical live alerts. The [branch audit](../project/branch_audit.md#featurerealtime-industrial-ml-anomaly-historical)
records the integrated historical source and preserves operator monitoring under #941.

## Synthetic comparison

The fixture suite covers 255 scored rows across eight scenarios, including a step at
103.5 below the warning limit of 105. An independent nominal reference supplies 256
evenly spaced normal quantiles with mean 100 and standard deviation 1. IQR uses the
reference quartiles. Rolling z-score starts fresh per scenario. Isolation Forest uses
the same training values with 100 trees, contamination 0.01, seed 919 and one worker.
The comparison counts the union of alerting rows when combining a detector with limits.

| Detectors | Alerting rows | Alerts on normal rows | Missed specification episodes | Missed process episodes | Cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Specification and warning limits | 30 | 2 | 0 | 1 | 12 |
| IQR alone | 48 | 12 | 0 | 0 | 12 |
| Rolling z-score alone | 10 | 0 | 2 | 2 | 220 |
| Isolation Forest alone | 49 | 13 | 0 | 0 | 13 |
| Limits and IQR | 48 | 12 | 0 | 0 | 12 |
| Limits and rolling z-score | 34 | 2 | 0 | 0 | 2 |
| Limits and Isolation Forest | 49 | 13 | 0 | 0 | 13 |

Each detected episode alerted on its first labelled sample in this fixture. Rolling
z-score caught the below-warning step after warm-up. The combined limits and rolling
z-score rule had the lowest cost here. The synthetic labels are sharp and the dataset
is small. Validate alert burden, detection delay and limits on representative target-line
replay before changing a deployed rule.

Run from the repository root to reproduce the fixture hashes, per-scenario counts and
totals. The recorded run used Python 3.11.16 and scikit-learn 1.9.1. Without the optional
dependency the same script reports deterministic baselines and marks scikit-learn
unavailable. [Evaluation script](../../scripts/evaluate_realtime_reference.py) ·
[Synthetic fixtures](../realtime_industrial_validation.md)

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src:. python scripts/evaluate_realtime_reference.py
```
