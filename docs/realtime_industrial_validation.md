# Realtime Industrial Validation Fixtures

This validation layer uses deterministic CSV fixtures to prove detector behavior before any live
database polling or GUI work is added. Fixtures are generated with:

```bash
PYTHONPATH=src:. python scripts/generate_realtime_industrial_fixtures.py --output tests/fixtures/industrial_realtime --force
```

Running the command twice should produce byte-identical files. Each validation fixture includes:
`record_id`, `process_timestamp`, `part_number`, `revision`, `station`, `line`, `metric_value`,
`metric_name`, and `expected_label`. Compatibility alias columns are also present for older replay
tests.

## Scenario Matrix

The default validation constants are nominal `100`, warning limits `95` and `105`, and spec limits
`90` and `110`. Statistical fixtures use a baseline of `n=40`, `q1=99`, `q3=101`, `iqr=2`,
`median=100`, and `mad=1` unless a test supplies a segment-specific baseline.

| Fixture | What It Proves | Expected Result |
|---|---|---|
| `stable_normal_process.csv` | Normal process noise should not create operator alerts. | No spec or rolling z-score events. |
| `single_high_outlier.csv` | One high excursion is explainable across spec, IQR, MAD, and rolling z-score detectors. | One critical spec event and one major event from each statistical detector. |
| `single_low_outlier.csv` | One low excursion is explainable across the same detectors. | One critical spec event and one major event from each statistical detector. |
| `usl_lsl_breach.csv` | Both sides of the spec window are detected and explained. | Two critical spec events, one above USL and one below LSL. |
| `warning_limit_breach.csv` | A warning-limit event does not get promoted to a spec breach. | One warning spec-limit event. |
| `gradual_drift_upward.csv` | MVP drift visibility currently comes from configured warning/spec thresholds. | One or more warning events once values cross the upper warning limit. |
| `sudden_step_change.csv` | Rolling z-score can catch the first shifted points when pre-step history has variance. | At least one major rolling z-score event. |
| `stuck_sensor.csv` | Repeated identical values should not create a false statistical alert with current detectors. | No rolling z-score event because zero variance is skipped. |
| `missing_stale_data.csv` | Stale-source events attach to the last persisted sample because events require a sample id. | One source-level stale event when scored with a later `now`. |
| `station_segment_baselines.csv` | Station-specific baselines avoid cross-station false positives. | Only the injected high value for station S2 is flagged with the S2 baseline. |
| `low_sample_count.csv` | Statistical detectors respect minimum history requirements. | No IQR, MAD, or rolling z-score events. |

## Known MVP Gaps

- There is no dedicated gradual-drift detector yet. Drift is visible only through warning/spec
  limits or a static statistical baseline.
- There is no dedicated step-change detector. Rolling z-score catches the initial jump, then adapts.
- There is no stuck-sensor detector. Repeated identical values create zero variance and are skipped.
- Replay does not load persisted baselines yet, so IQR and MAD validation supplies baselines directly
  in tests.
- Segment-specific baselines are test-driven but not automatically selected by replay orchestration.
