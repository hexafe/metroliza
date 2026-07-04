# SQLite Realtime Event Stream

## Status

Implemented as a local orchestration layer for realtime industrial monitoring.

## Purpose

Metroliza still polls production sources through bounded, read-only queries and
still keeps dashboard state in persisted SQLite read models. The local event
stream adds an append-only event log between sample persistence and downstream
consumers so detector execution, replay, and diagnostics can be retried without
writing to the production database.

This is a SQLite-backed local event stream, not Kafka-style infrastructure. Do
not add Kafka, RabbitMQ, MQTT, Redis, Celery, or an external broker for this
layer.

## Design

- `industrial_realtime_stream_events` stores append-only local stream events.
- `industrial_realtime_consumer_offsets` stores per-consumer checkpoints.
- Polling writes `sample_batch_committed` after local sample persistence.
- The source offset advances only after sample persistence and stream append
  succeed.
- `RealtimeDetectorConsumer` reads sample-batch events by event id, loads the
  referenced persisted samples, runs deterministic detectors, persists anomaly
  events idempotently, and then advances its consumer offset.
- Dashboard services continue to query `industrial_samples`,
  `industrial_anomaly_events`, and `industrial_stream_offsets` directly.

## Guarantees

- Delivery is at least once.
- Sample writes remain idempotent through the existing
  `(source_profile_id, signal_id, source_record_key)` uniqueness rule.
- Anomaly writes remain idempotent through the existing `(sample_id,
  detector_key)` uniqueness rule.
- Stream writes are idempotent by deterministic `idempotency_key`.
- Consumer offsets advance only after processing succeeds.
- Diagnostics and payloads must not retain raw SQL, passwords, tokens, or
  connection strings.

## Limits

There is no automatic retention in the first implementation. Keep stream rows
for replay/debug until release owners decide on a retention policy such as
manual cleanup, last-N-days cleanup, or cleanup after all active consumers have
passed an event id.
