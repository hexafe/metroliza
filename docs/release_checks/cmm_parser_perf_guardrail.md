# CMM Parser Perf Guardrail Runbook

This runbook defines the CI quality gate for the CMM parser backend benchmark scenario (`cmm_parser_backend_compare`) and how to triage failures.

## CI gate definition

Workflow job: `cmm-parser-perf-gate` in `.github/workflows/ci.yml`.

The gate uses a fixed synthetic workload and must run with:

- `scripts/benchmark_paths.py --scenarios cmm_parser_backend_compare`
- `--cmm-bench-report-count 120`
- `--cmm-bench-measurements-per-report 120`
- `--enforce-cmm-parser-guardrail`
- `--cmm-native-min-speedup-ratio 0.90`
- `--cmm-native-min-usage-rate 0.95`

## Trend evidence and artifacts

The job performs:

1. **Warmup run** (discarded from trend signal).
2. **3 measured runs** persisted as JSON artifacts.
3. Trend comparison with `scripts/benchmark_trend_compare.py` against `docs/perf_baseline_snapshot.json`, scoped to `cmm_parser_backend_compare`.

Uploaded artifact bundle: `cmm-parser-perf-artifacts`.

Expected artifact contents:

- `benchmark_results/cmm_perf_gate/runs/run-*/benchmark-paths.json`
- `benchmark_results/cmm_perf_gate/trend-report.json`

## Expected variance guidance

Because this benchmark is runtime-sensitive and runs on shared hosted runners, minor run-to-run jitter is expected. The trend gate uses a 12% median-regression threshold for this reason.

- Treat small single-run oscillations as noise.
- Use the **median across 3 measured runs** as the decision signal.
- The guardrail hard-fails only when:
  - native speedup ratio falls below `0.90`, or
  - native parser usage rate falls below `0.95`, or
  - trend comparison reports median regression greater than the CMM gate threshold (`12%`).

## Failure triage checklist

When `cmm-parser-perf-gate` fails:

1. **Classify failure type**
   - Guardrail threshold failure (`speedup`/`usage rate`).
   - Trend regression failure (`trend-report.json`).
   - Infrastructure/setup failure (wheel build/install, missing artifact, etc.).
2. **Inspect per-run JSONs**
   - Compare `stage_timings_s.native_speedup_ratio` across all three runs.
   - Check `input_metrics.native_parse_backend_rate` for native usage drift.
3. **Verify native availability path**
   - Confirm CMM native wheel build/install succeeded in the same job.
   - Confirm no fallback-only execution path was unintentionally forced.
4. **Correlate with recent parser/backend changes**
   - Look for edits in CMM parser backend, parsing hot paths, telemetry wiring, or environment variable defaults.
5. **Decide action**
   - If regression is real: fix/optimize before merge.
   - If baseline is stale but behavior is acceptable: refresh `docs/perf_baseline_snapshot.json` in a dedicated baseline-update PR with rationale.
   - If runner noise is suspected: re-run once, then require a documented rationale before changing thresholds.

## Baseline/threshold governance

- Keep `0.90` speedup and `0.95` native usage as pinned CI baselines unless a deliberate governance decision updates them.
- Any threshold or baseline snapshot change must include:
  - explicit rationale,
  - before/after median evidence,
  - link to the CI artifacts that motivated the change.
