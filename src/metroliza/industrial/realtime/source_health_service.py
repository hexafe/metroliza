"""Scheduled source-health evaluation independent of sample ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import StaleSourceDetector
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import from_json, to_json, utc_timestamp
from metroliza.industrial.realtime.stream_config import RealtimePollConfig
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition
from metroliza.industrial.realtime.timestamps import canonical_utc_timestamp, parse_utc_timestamp
from metroliza.reports.db import run_transaction_with_retry


@dataclass(frozen=True)
class SourceHealthSnapshot:
    """Current computed health for one configured realtime source stream."""

    source_profile_id: int
    stream_key: str
    evaluated_at: str
    status: str
    latest_event_time: str | None = None
    last_sample_id: int | None = None
    lag_seconds: float | None = None
    anomaly_event_id: int | None = None


class RealtimeSourceHealthService:
    """Recompute source freshness on a schedule, even when no new rows arrive."""

    def __init__(
        self,
        database: str,
        *,
        warning_seconds: float = 300.0,
        major_seconds: float = 900.0,
        connection=None,
    ) -> None:
        if warning_seconds <= 0:
            raise ValueError("warning_seconds must be positive")
        if major_seconds <= warning_seconds:
            raise ValueError("major_seconds must be greater than warning_seconds")
        self.database = database
        self.connection = connection
        self.warning_seconds = float(warning_seconds)
        self.major_seconds = float(major_seconds)
        self._event_repository = AnomalyEventRepository(database, connection=connection)

    def evaluate(
        self,
        config: RealtimePollConfig,
        *,
        now: str | None = None,
    ) -> SourceHealthSnapshot:
        """Evaluate and persist one source-health snapshot."""

        validated = config.validated()
        evaluated_at = canonical_utc_timestamp(now or utc_timestamp())
        latest = self._latest_sample(validated)
        anomaly_event_id = None
        if latest is None:
            snapshot = SourceHealthSnapshot(
                source_profile_id=validated.source_profile_id,
                stream_key=validated.stream_key,
                evaluated_at=evaluated_at,
                status="no_data",
            )
        else:
            sample, signal = latest
            lag_seconds = max(
                0.0,
                (
                    parse_utc_timestamp(evaluated_at)
                    - parse_utc_timestamp(sample.event_time)
                ).total_seconds(),
            )
            status = (
                "major"
                if lag_seconds >= self.major_seconds
                else "warning"
                if lag_seconds >= self.warning_seconds
                else "healthy"
            )
            if "stale_source" in validated.detectors:
                detector = StaleSourceDetector(
                    warning_seconds=self.warning_seconds,
                    major_seconds=self.major_seconds,
                )
                event = detector.score_one(
                    sample,
                    DetectorContext(signal=signal, now=evaluated_at),
                )
                if event is not None:
                    result = self._event_repository.insert_events((event,))
                    anomaly_event_id = result.event_ids[0] if result.event_ids else None
            snapshot = SourceHealthSnapshot(
                source_profile_id=validated.source_profile_id,
                stream_key=validated.stream_key,
                evaluated_at=evaluated_at,
                status=status,
                latest_event_time=sample.event_time,
                last_sample_id=sample.id,
                lag_seconds=lag_seconds,
                anomaly_event_id=anomaly_event_id,
            )
        self._persist(snapshot)
        return snapshot

    def evaluate_all(
        self,
        configs: Iterable[RealtimePollConfig],
        *,
        now: str | None = None,
    ) -> tuple[SourceHealthSnapshot, ...]:
        """Evaluate every enabled config with one consistent clock value."""

        evaluated_at = canonical_utc_timestamp(now or utc_timestamp())
        return tuple(
            self.evaluate(config, now=evaluated_at)
            for config in configs
            if config.enabled
        )

    def get_snapshot(
        self,
        *,
        source_profile_id: int,
        stream_key: str,
    ) -> SourceHealthSnapshot | None:
        """Return the last persisted health evaluation."""

        ensure_industrial_data_schema(self.database, connection=self.connection)

        def _get(cursor) -> SourceHealthSnapshot | None:
            cursor.execute(
                """
                SELECT source_profile_id, stream_key, evaluated_at, status, latest_event_time,
                       last_sample_id, lag_seconds, details_json
                FROM industrial_realtime_source_health
                WHERE source_profile_id = ? AND stream_key = ?
                """,
                (int(source_profile_id), str(stream_key)),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            details = from_json(row[7], {})
            return SourceHealthSnapshot(
                source_profile_id=int(row[0]),
                stream_key=str(row[1]),
                evaluated_at=str(row[2]),
                status=str(row[3]),
                latest_event_time=row[4],
                last_sample_id=int(row[5]) if row[5] is not None else None,
                lag_seconds=float(row[6]) if row[6] is not None else None,
                anomaly_event_id=(
                    int(details["anomaly_event_id"])
                    if isinstance(details, dict) and details.get("anomaly_event_id") is not None
                    else None
                ),
            )

        return run_transaction_with_retry(self.database, _get, connection=self.connection)

    def _latest_sample(
        self,
        config: RealtimePollConfig,
    ) -> tuple[IndustrialSample, SignalDefinition] | None:
        ensure_industrial_data_schema(self.database, connection=self.connection)
        placeholders = ", ".join("?" for _ in config.signal_keys)

        def _get(cursor):
            cursor.execute(
                f"""
                SELECT
                    samples.id, samples.source_profile_id, samples.signal_id,
                    samples.source_record_key, samples.event_time, samples.ingest_time,
                    samples.metric_name, samples.value, samples.reference, samples.part_number,
                    samples.revision, samples.station, samples.line, samples.work_order,
                    samples.batch_lot, samples.segment_key_json, samples.quality_flags_json,
                    samples.raw_record_json,
                    signals.signal_key, signals.unit, signals.nominal, signals.lsl, signals.usl,
                    signals.lower_warning, signals.upper_warning, signals.segment_fields_json,
                    signals.enabled, signals.created_at, signals.updated_at
                FROM industrial_samples AS samples
                JOIN industrial_signal_definitions AS signals ON signals.id = samples.signal_id
                WHERE samples.source_profile_id = ?
                  AND signals.signal_key IN ({placeholders})
                ORDER BY samples.event_time DESC, samples.id DESC
                LIMIT 1
                """,
                (config.source_profile_id, *config.signal_keys),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            sample = IndustrialSample(
                id=int(row[0]),
                source_profile_id=int(row[1]),
                signal_id=int(row[2]),
                source_record_key=str(row[3]),
                event_time=str(row[4]),
                ingest_time=str(row[5]),
                metric_name=str(row[6]),
                value=float(row[7]),
                reference=row[8],
                part_number=row[9],
                revision=row[10],
                station=row[11],
                line=row[12],
                work_order=row[13],
                batch_lot=row[14],
                segment_key=from_json(row[15], {}),
                quality_flags=tuple(from_json(row[16], [])),
                raw_record=from_json(row[17], {}) if row[17] else None,
            )
            signal = SignalDefinition(
                id=int(row[2]),
                source_profile_id=int(row[1]),
                signal_key=str(row[18]),
                metric_name=str(row[6]),
                unit=row[19],
                nominal=float(row[20]) if row[20] is not None else None,
                lsl=float(row[21]) if row[21] is not None else None,
                usl=float(row[22]) if row[22] is not None else None,
                lower_warning=float(row[23]) if row[23] is not None else None,
                upper_warning=float(row[24]) if row[24] is not None else None,
                segment_fields=tuple(from_json(row[25], [])),
                enabled=bool(row[26]),
                created_at=str(row[27]),
                updated_at=str(row[28]),
            )
            return sample, signal

        return run_transaction_with_retry(self.database, _get, connection=self.connection)

    def _persist(self, snapshot: SourceHealthSnapshot) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)
        details: dict[str, Any] = {
            "warning_seconds": self.warning_seconds,
            "major_seconds": self.major_seconds,
        }
        if snapshot.anomaly_event_id is not None:
            details["anomaly_event_id"] = snapshot.anomaly_event_id

        def _upsert(cursor) -> None:
            cursor.execute(
                """
                INSERT INTO industrial_realtime_source_health (
                    source_profile_id, stream_key, evaluated_at, latest_event_time,
                    last_sample_id, lag_seconds, status, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_profile_id, stream_key) DO UPDATE SET
                    evaluated_at = excluded.evaluated_at,
                    latest_event_time = excluded.latest_event_time,
                    last_sample_id = excluded.last_sample_id,
                    lag_seconds = excluded.lag_seconds,
                    status = excluded.status,
                    details_json = excluded.details_json
                WHERE excluded.evaluated_at >= industrial_realtime_source_health.evaluated_at
                """,
                (
                    snapshot.source_profile_id,
                    snapshot.stream_key,
                    snapshot.evaluated_at,
                    snapshot.latest_event_time,
                    snapshot.last_sample_id,
                    snapshot.lag_seconds,
                    snapshot.status,
                    to_json(details),
                ),
            )

        run_transaction_with_retry(self.database, _upsert, connection=self.connection)
