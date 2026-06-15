# Realtime Industrial Monitoring

## When To Use This Guide

Use realtime industrial monitoring when a production source should be checked
regularly for unusual process values, late data, or values outside approved
limits.

This guide is for operators, process owners, and support staff. It explains the
words used in the monitor, how to prepare a safe setup, and how to respond to
events. It does not replace the normal [Industrial Data](industrial_data.md)
workflow for manual fetches and CSV Summary analysis.

## Important Words

| Word | Plain meaning |
|---|---|
| Signal | One value that the line records and Metroliza should watch. Examples are cycle time, torque, pressure, temperature, or a measured dimension. |
| Sample | One recorded value for one signal at one point in time. |
| Event time | The time when the value happened on the production line. Use this time when checking the part, station, shift, or work order. |
| Ingest time | The time when Metroliza copied or saw the value. If ingest time is much later than event time, the source may be delayed. |
| Baseline | The approved picture of normal behavior for a signal. A baseline can be built from replayed historical data or another reviewed period. |
| Detector | A rule that checks samples. One detector may check limits; another may check whether the value looks unusual compared with the baseline. |
| Anomaly event | A record created when a detector finds something that needs review. An event should explain what was observed and why it was flagged. |
| Severity | The event urgency: critical, major, warning, or info. Severity tells you how quickly to respond; it is not a final quality decision by itself. |

## Setup Before Live Monitoring

Set up monitoring in this order. Do not start live polling until replay has been
reviewed.

1. Create or choose a read-only database profile.

   The production database account must be read-only. It should be limited to
   the approved table or view and only the approved columns. Do not use an
   admin account, a write-capable account, or a shared password copied into a
   document. Enter credentials only through the app or the approved local
   credential prompt.

2. Define the signals.

   For each signal, record the metric name, unit, station or line grouping if
   needed, warning limits, specification limits, and whether the signal is
   enabled. Use names that operators recognize. Ask the process owner before
   adding extra columns or watching a value whose meaning is unclear.

3. Choose a safe polling interval.

   Start with a slow interval agreed with IT or MES support. The interval should
   be longer than the source update cycle and should leave enough time for the
   source database to answer without queueing work. If source lag grows, row
   counts jump unexpectedly, or operators see stale-source events, stop live
   polling and review the interval before restarting.

4. Replay before live use.

   Run synthetic replay first, then replay recent historical production data.
   Review the events with the process owner. Confirm that expected problems are
   caught, normal variation stays quiet, false positives are understood, and
   thresholds match current process rules.

5. Confirm the rollback path.

   Before the first live run, confirm who can disable the realtime profile, who
   can stop scheduled polling, and how operators will return to manual
   Industrial Data and CSV Summary work if monitoring is paused.

## Using The Monitor Dialog

Open the monitor from **Tools > Real-time Industrial Monitoring...**. If no
Metroliza database is selected, the app creates a temporary local SQLite store
for the session; for normal monitoring, select a persistent database first.

The dialog has three operator areas:

- **Sources** lists the configured industrial database profiles. Check one or
  more enabled sources to monitor them in parallel. Disabled sources are shown
  for context but cannot be checked or polled.
- **Configuration** stores the stream key, cursor column, event-time column,
  record key column, signal columns, polling interval, timeout, row limits,
  display mode, aggregation settings, context fields, segment fields, detector
  list, and dashboard file location.
- **Status** and **Diagnostics** show the result of each poll cycle, including
  fetched rows, inserted samples, detector events, source lag, and safe
  diagnostics.

Keep the query timeout less than or equal to the polling interval. Keep row
limits bounded. Signal columns use `signal_name=source_column` entries, one per
line or separated by commas. Use **raw** dashboard mode to review recent samples
directly, or **aggregated** mode when operators need CSV Summary-style sample
aggregates between refreshes.

Use **Save Current Source** when the visible form should be saved only for the
selected source. Use **Apply Current to Checked** only when the same settings
should intentionally be copied to every checked source. **Start Checked** and
**Poll Once** use the currently checked enabled sources; they do not poll
unchecked or disabled sources.

Credentials are not stored in the monitor config. The monitor uses the same
local credential store as the Industrial Data workflow. Do not paste passwords,
tokens, or connection strings into signal, context, segment, dashboard, or
diagnostic fields.

## Severity Meaning

| Severity | Operator meaning | Typical action |
|---|---|---|
| Critical | A value crossed a formal specification limit or another rule marked as critical. | Follow the plant response plan. Check the part, station, time, and recent events immediately. Escalate to the process owner or quality owner. |
| Major | A value is strongly unusual compared with the approved baseline, or the data source is badly delayed. | Review soon. Check whether a setup, tool, material, station, or source problem explains the change. Escalate if the same signal repeats. |
| Warning | A value is near a limit, drifting, or delayed enough to watch. | Monitor the trend, compare with recent runs, and decide whether adjustment or closer review is needed. |
| Info | Context that may help explain the source or detector behavior. | Read it when reviewing the source. It usually does not require immediate action. |

Severity is a review priority. It is not an automatic scrap decision and it is
not a replacement for the local quality procedure.

## Reading An Event

When an event appears, check these fields first:

- signal name and unit,
- station, line, part number, revision, batch, or work order if shown,
- event time,
- ingest time,
- detector name,
- observed value,
- expected value or limit if shown,
- explanation, and
- current status.

Use event time to find the real production context. Use ingest time to judge
whether Metroliza saw the value promptly. If ingest time is late, review source
lag before making a process conclusion.

## Spec-Limit Events And Process-Drift Events

Spec-limit events are about agreed limits. If the value crosses an upper or
lower specification limit, treat it as a direct quality or process review item.
If it crosses only a warning limit, it means the value is close enough to a
limit that operators should watch it.

Process-drift events are about change from normal behavior. A value can be
inside the formal specification and still be unusual compared with the
baseline. This can happen after tool wear, material changes, setup changes,
station changes, sensor changes, or gradual process movement.

Use this rule of thumb:

- A spec-limit event asks, "Did this value cross an approved limit?"
- A process-drift event asks, "Is this value unusual for this signal now?"

Both deserve review, but they answer different questions. Do not treat a drift
event as a failed part without checking the local process rule.

## Handling False Positives

A false positive is an event that was technically flagged but is not useful for
operators.

When this happens:

1. Mark or record the event as a false positive.
2. Add a short comment with the reason, such as planned setup change, approved
   trial batch, sensor maintenance, known source delay, or baseline no longer
   current.
3. Keep the event history. Do not delete it just to make the list clean.
4. Tell the process owner if the same false positive repeats.
5. Review the signal definition, warning limits, specification limits,
   baseline, segment fields, or polling interval before changing detector
   settings.

Do not lower limits or disable a detector only to silence noise. Threshold
changes should be reviewed by the process owner and recorded in the rollout
notes.

## Before Enabling A Source

Use this short check before a source is allowed to run live:

- The database profile is read-only.
- The source uses an approved table, view, or reviewed read-only query.
- The signal list is approved by the process owner.
- Warning and specification limits are reviewed.
- Baselines are built from an approved period or replay set.
- Synthetic replay passed.
- Historical replay was reviewed.
- Polling interval is approved as safe for the source.
- Source lag is visible and checked.
- Operators know what critical, major, warning, and info mean.
- False-positive handling is agreed.
- Rollback steps are known.

For release sign-off, use the
[Realtime Industrial Monitoring Rollout Checklist](../release_checks/realtime_industrial_rollout_checklist.md).
