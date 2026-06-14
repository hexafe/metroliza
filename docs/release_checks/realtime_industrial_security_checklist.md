# Realtime Industrial Security Checklist

This checkpoint covers the non-GUI security boundary for realtime industrial
polling configuration. It intentionally does not enable live polling from the UI
and does not add detector or dashboard behavior.

## Hardened Areas

- Realtime stream YAML is non-secret and rejects credential-like keys at any
  nesting depth.
- Stream, signal, metric, cursor, timestamp, segment, context, and detector
  identifiers are validated before a poller can use them.
- Stream source columns are checked against the selected source profile
  allowlist when one is configured.
- Polling policy defaults are bounded: positive batch limit, positive timeout,
  non-negative lag threshold, and non-negative detector history window.
- SQL diagnostics store a hash and redacted summary only. Raw SQL text is not
  kept in realtime diagnostics.

## Production Rules

- Use a read-only production database account with access limited to a safe
  view or allowlisted table.
- Keep credentials in the local user credential store or environment variables,
  never in YAML or SQLite.
- Configure cursor, event time, and record-key columns for every realtime
  stream.
- Keep batch limits and query timeouts small until synthetic replay and a
  monitored dry run prove the source is stable.
- Review detector thresholds with the process owner before enabling operator
  alerts.

## Validation

Run before merging this checkpoint:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest \
  tests/test_realtime_stream_config.py \
  tests/test_realtime_source_security.py -q
PYTHONPATH=src:. python -m ruff check \
  src/metroliza/industrial/realtime/stream_config.py \
  tests/test_realtime_stream_config.py \
  tests/test_realtime_source_security.py
```

## Remaining Risks

- The polling service must enforce this config boundary before source reads.
- Live source access still needs fake-adapter offset tests before any GUI entry
  can start continuous monitoring.
