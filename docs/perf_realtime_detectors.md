# Realtime Detector Throughput Benchmark

`scripts/benchmark_realtime_detectors.py` measures deterministic anomaly detector throughput
without CSV parsing, SQLite persistence, UI work, or external benchmark dependencies. It prebuilds a
fixed synthetic sample set, then times detector `score_one` and `update_one` calls through the same
typed contracts used by realtime replay.

## Run

From the repository root:

```bash
PYTHONPATH=src:. python scripts/benchmark_realtime_detectors.py
```

Optional focused runs:

```bash
PYTHONPATH=src:. python scripts/benchmark_realtime_detectors.py --sizes 10000
PYTHONPATH=src:. python scripts/benchmark_realtime_detectors.py --detectors spec_limits,rolling_zscore
```

Use `--sizes 1000` or a smaller detector subset for quick sanity checks. The default command includes
the 100,000-sample pass and can take noticeably longer when stateful detectors dominate runtime.

The script uses only the Python standard library plus the in-repo Metroliza runtime modules.

## Sample Sizes

- `1,000` samples is a smoke-sized run. Use it to confirm imports, output shape, and detector
  counts quickly.
- `10,000` samples is a medium replay batch. It is useful for comparing day-to-day local changes
  while keeping runtime short.
- `100,000` samples is the default stress-sized run. Use it to spot sustained-throughput changes,
  especially in stateful detectors such as rolling z-score.

Synthetic samples are deterministic. Most values sit near a nominal process center, with periodic
warning and critical outliers so event counts remain non-zero and comparable between runs.

## Result Fields

- `total_seconds` is the sum of per-detector wall-clock time for that sample size.
- `samples/sec` is full-suite row throughput: sample count divided by `total_seconds`.
- `detector_calls/sec` is sample count multiplied by detector count, divided by `total_seconds`.
- `events/sec` is emitted detector events divided by `total_seconds`.
- `events` is the total number of emitted events across detectors.
- `event_counts` groups emitted events by `detector_key/severity`.
- `per_detector` shows each detector's own wall time, samples/sec, events, events/sec, and share of
  total benchmark time.

The default detector list is `spec_limits`, `iqr`, `mad_zscore`, `rolling_zscore`, and
`stale_source`. The stale-source path is timed with matching `now` and sample event timestamps, so it
exercises the detector's timestamp parsing and update path without intentionally creating stale
events.

## Interpretation

Use these numbers as a local regression signal, not an absolute production capacity claim. Hardware,
Python version, CPU governor, and concurrent load can change wall-clock throughput. Compare results
on the same machine and command when evaluating detector changes.

The benchmark intentionally excludes ingestion, database writes, event persistence, and GUI refresh.
Lower throughput here points at detector or contract overhead. Lower throughput in a full replay with
stable detector benchmark results usually points at I/O, persistence, or orchestration work instead.

For behavior validation scenarios, expected detector outputs, and current MVP detector gaps, see
`realtime_industrial_validation.md`.
