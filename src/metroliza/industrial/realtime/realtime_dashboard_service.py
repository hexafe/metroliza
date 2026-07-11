"""Read models for persisted realtime industrial dashboard data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from metroliza.industrial.anomaly.contracts import ANOMALY_SEVERITIES
from metroliza.industrial.anomaly.event_repository import (
    ANOMALY_EVENT_STATUSES,
    AnomalyEventRepository,
)
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import from_json, utc_timestamp
from metroliza.industrial.realtime.timestamps import canonical_utc_timestamp
from metroliza.reports.db import run_transaction_with_retry

_SEVERITY_RANKS = {"info": 1, "warning": 2, "major": 3, "critical": 4}
_SEVERITY_BY_RANK = {rank: severity for severity, rank in _SEVERITY_RANKS.items()}


@dataclass(frozen=True)
class DashboardAnomalyEvent:
    """Operator-facing anomaly event summary without source connection details."""

    id: int
    sample_id: int
    signal_id: int
    source_profile_id: int
    profile_key: str
    profile_name: str
    signal_key: str
    metric_name: str
    unit: str | None
    event_time: str
    detector_key: str
    severity: str
    score: float
    observed_value: float
    expected_value: float | None
    threshold: dict[str, Any]
    explanation: str
    status: str
    created_at: str
    station: str | None = None
    line: str | None = None
    reference: str | None = None
    part_number: str | None = None
    revision: str | None = None
    work_order: str | None = None
    batch_lot: str | None = None


@dataclass(frozen=True)
class SignalTimelinePoint:
    """One persisted sample point plus persisted anomaly overlays for a dashboard chart."""

    sample_id: int
    signal_id: int
    source_profile_id: int
    signal_key: str
    metric_name: str
    unit: str | None
    event_time: str
    ingest_time: str
    value: float
    anomaly_count: int
    open_anomaly_count: int
    highest_severity: str | None
    reference: str | None = None
    part_number: str | None = None
    revision: str | None = None
    station: str | None = None
    line: str | None = None
    work_order: str | None = None
    batch_lot: str | None = None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceLagHealth:
    """Operator-safe source health summary derived from stream offsets."""

    source_profile_id: int
    profile_key: str
    profile_name: str
    stream_key: str
    event_time_watermark: str | None
    last_success_at: str | None
    lag_seconds: float | None
    status: str
    health: str
    is_enabled: bool


@dataclass(frozen=True)
class SignalAggregateRow:
    """CSV Summary-style persisted sample aggregate for one watched signal."""

    source_profile_id: int
    profile_key: str
    profile_name: str
    signal_id: int
    signal_key: str
    metric_name: str
    unit: str | None
    sample_count: int
    first_event_time: str
    last_event_time: str
    minimum: float
    maximum: float
    average: float
    latest_value: float
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    below_lsl_count: int = 0
    above_usl_count: int = 0
    nok_count: int = 0
    nok_pct: float = 0.0


class RealtimeDashboardService:
    """Query persisted realtime samples, anomaly events, and offsets for dashboards."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection
        self._event_repository = AnomalyEventRepository(database, connection=connection)

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def list_open_anomaly_events(
        self,
        *,
        signal_id: int | None = None,
        detector_key: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[DashboardAnomalyEvent]:
        self.ensure_schema()

        def _list(cursor) -> list[DashboardAnomalyEvent]:
            where = ["events.status = 'open'"]
            params: list[Any] = []
            _append_event_filters(
                where,
                params,
                signal_id=signal_id,
                detector_key=detector_key,
                severity=severity,
            )
            params.append(_positive_limit(limit))
            cursor.execute(
                f"""
                {_DASHBOARD_EVENT_SELECT}
                WHERE {' AND '.join(where)}
                ORDER BY events.event_time DESC, events.id DESC
                LIMIT ?
                """,
                tuple(params),
            )
            return [_dashboard_event_from_row(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def anomaly_counts_by_severity(
        self,
        *,
        status: str | None = None,
        signal_id: int | None = None,
        detector_key: str | None = None,
    ) -> dict[str, int]:
        self.ensure_schema()

        def _count(cursor) -> dict[str, int]:
            where: list[str] = []
            params: list[Any] = []
            _append_event_filters(
                where,
                params,
                status=status,
                signal_id=signal_id,
                detector_key=detector_key,
            )
            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            cursor.execute(
                f"""
                SELECT events.severity, COUNT(*)
                FROM industrial_anomaly_events AS events
                {where_clause}
                GROUP BY events.severity
                """,
                tuple(params),
            )
            counts = {severity: 0 for severity in ANOMALY_SEVERITIES}
            counts.update({str(row[0]): int(row[1]) for row in cursor.fetchall()})
            return counts

        return run_transaction_with_retry(self.database, _count, connection=self.connection)

    def anomaly_counts_by_detector(
        self,
        *,
        status: str | None = None,
        signal_id: int | None = None,
        severity: str | None = None,
    ) -> dict[str, int]:
        self.ensure_schema()

        def _count(cursor) -> dict[str, int]:
            where: list[str] = []
            params: list[Any] = []
            _append_event_filters(
                where,
                params,
                status=status,
                signal_id=signal_id,
                severity=severity,
            )
            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            cursor.execute(
                f"""
                SELECT events.detector_key, COUNT(*)
                FROM industrial_anomaly_events AS events
                {where_clause}
                GROUP BY events.detector_key
                ORDER BY events.detector_key ASC
                """,
                tuple(params),
            )
            return {str(row[0]): int(row[1]) for row in cursor.fetchall()}

        return run_transaction_with_retry(self.database, _count, connection=self.connection)

    def recent_events_by_signal(
        self,
        *,
        signal_id: int,
        limit: int = 50,
        status: str | None = None,
    ) -> list[DashboardAnomalyEvent]:
        self.ensure_schema()

        def _list(cursor) -> list[DashboardAnomalyEvent]:
            where = ["events.signal_id = ?"]
            params: list[Any] = [int(signal_id)]
            _append_event_filters(where, params, status=status)
            params.append(_positive_limit(limit))
            cursor.execute(
                f"""
                {_DASHBOARD_EVENT_SELECT}
                WHERE {' AND '.join(where)}
                ORDER BY events.event_time DESC, events.id DESC
                LIMIT ?
                """,
                tuple(params),
            )
            return [_dashboard_event_from_row(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def signal_timeline_window(
        self,
        *,
        signal_id: int,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 500,
    ) -> list[SignalTimelinePoint]:
        self.ensure_schema()

        def _list(cursor) -> list[SignalTimelinePoint]:
            where = ["samples.signal_id = ?"]
            params: list[Any] = [int(signal_id)]
            if start_time is not None:
                where.append("samples.event_time >= ?")
                params.append(canonical_utc_timestamp(start_time))
            if end_time is not None:
                where.append("samples.event_time <= ?")
                params.append(canonical_utc_timestamp(end_time))
            params.append(_positive_limit(limit))
            cursor.execute(
                f"""
                SELECT
                    samples.id,
                    samples.signal_id,
                    samples.source_profile_id,
                    signals.signal_key,
                    samples.metric_name,
                    signals.unit,
                    samples.event_time,
                    samples.ingest_time,
                    samples.value,
                    samples.reference,
                    samples.part_number,
                    samples.revision,
                    samples.station,
                    samples.line,
                    samples.work_order,
                    samples.batch_lot,
                    samples.quality_flags_json,
                    COUNT(events.id),
                    COALESCE(SUM(CASE WHEN events.status = 'open' THEN 1 ELSE 0 END), 0),
                    MAX(
                        CASE events.severity
                            WHEN 'info' THEN 1
                            WHEN 'warning' THEN 2
                            WHEN 'major' THEN 3
                            WHEN 'critical' THEN 4
                            ELSE NULL
                        END
                    )
                FROM industrial_samples AS samples
                JOIN industrial_signal_definitions AS signals ON signals.id = samples.signal_id
                LEFT JOIN industrial_anomaly_events AS events ON events.sample_id = samples.id
                WHERE {' AND '.join(where)}
                GROUP BY
                    samples.id,
                    samples.signal_id,
                    samples.source_profile_id,
                    signals.signal_key,
                    samples.metric_name,
                    signals.unit,
                    samples.event_time,
                    samples.ingest_time,
                    samples.value,
                    samples.reference,
                    samples.part_number,
                    samples.revision,
                    samples.station,
                    samples.line,
                    samples.work_order,
                    samples.batch_lot,
                    samples.quality_flags_json
                ORDER BY samples.event_time ASC, samples.id ASC
                LIMIT ?
                """,
                tuple(params),
            )
            return [_timeline_point_from_row(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def recent_signal_timeline_window(
        self,
        *,
        signal_id: int,
        limit: int = 500,
    ) -> list[SignalTimelinePoint]:
        """Return the most recent persisted samples for a signal in chart order."""

        self.ensure_schema()

        def _list(cursor) -> list[SignalTimelinePoint]:
            cursor.execute(
                """
                SELECT *
                FROM (
                    SELECT
                        samples.id,
                        samples.signal_id,
                        samples.source_profile_id,
                        signals.signal_key,
                        samples.metric_name,
                        signals.unit,
                        samples.event_time,
                        samples.ingest_time,
                        samples.value,
                        samples.reference,
                        samples.part_number,
                        samples.revision,
                        samples.station,
                        samples.line,
                        samples.work_order,
                        samples.batch_lot,
                        samples.quality_flags_json,
                        COUNT(events.id),
                        COALESCE(SUM(CASE WHEN events.status = 'open' THEN 1 ELSE 0 END), 0),
                        MAX(
                            CASE events.severity
                                WHEN 'info' THEN 1
                                WHEN 'warning' THEN 2
                                WHEN 'major' THEN 3
                                WHEN 'critical' THEN 4
                                ELSE NULL
                            END
                        )
                    FROM industrial_samples AS samples
                    JOIN industrial_signal_definitions AS signals ON signals.id = samples.signal_id
                    LEFT JOIN industrial_anomaly_events AS events ON events.sample_id = samples.id
                    WHERE samples.signal_id = ?
                    GROUP BY
                        samples.id,
                        samples.signal_id,
                        samples.source_profile_id,
                        signals.signal_key,
                        samples.metric_name,
                        signals.unit,
                        samples.event_time,
                        samples.ingest_time,
                        samples.value,
                        samples.reference,
                        samples.part_number,
                        samples.revision,
                        samples.station,
                        samples.line,
                        samples.work_order,
                        samples.batch_lot,
                        samples.quality_flags_json
                    ORDER BY samples.event_time DESC, samples.id DESC
                    LIMIT ?
                ) AS recent_samples
                ORDER BY recent_samples.event_time ASC, recent_samples.id ASC
                """,
                (int(signal_id), _positive_limit(limit)),
            )
            return [_timeline_point_from_row(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def recent_sample_signal_ids(self, *, limit: int = 25) -> tuple[int, ...]:
        """Return signal ids with recent persisted samples, newest signal first."""

        self.ensure_schema()

        def _list(cursor) -> tuple[int, ...]:
            cursor.execute(
                """
                SELECT signal_id
                FROM (
                    SELECT
                        samples.signal_id AS signal_id,
                        MAX(samples.event_time) AS latest_event_time,
                        MAX(samples.id) AS latest_sample_id
                    FROM industrial_samples AS samples
                    JOIN industrial_signal_definitions AS signals ON signals.id = samples.signal_id
                    WHERE signals.enabled = 1
                    GROUP BY samples.signal_id
                    ORDER BY latest_event_time DESC, latest_sample_id DESC
                    LIMIT ?
                ) AS recent_signals
                """,
                (_positive_limit(limit),),
            )
            return tuple(int(row[0]) for row in cursor.fetchall())

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def sample_aggregate_rows(
        self,
        *,
        signal_ids: Iterable[int] | None = None,
        limit: int | None = 100,
    ) -> list[SignalAggregateRow]:
        """Build CSV Summary-style aggregates from persisted realtime samples."""

        self.ensure_schema()
        requested_signal_ids = None if signal_ids is None else tuple(dict.fromkeys(int(v) for v in signal_ids))
        if requested_signal_ids == ():
            return []

        def _list(cursor) -> list[SignalAggregateRow]:
            where: list[str] = []
            params: list[Any] = []
            if requested_signal_ids is not None:
                placeholders = ", ".join("?" for _ in requested_signal_ids)
                where.append(f"samples.signal_id IN ({placeholders})")
                params.extend(requested_signal_ids)
            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            limit_clause = ""
            if limit is not None:
                limit_clause = "LIMIT ?"
                params.append(_positive_limit(limit))
            cursor.execute(
                f"""
                SELECT
                    samples.source_profile_id,
                    profiles.profile_key,
                    profiles.profile_name,
                    samples.signal_id,
                    signals.signal_key,
                    signals.metric_name,
                    signals.unit,
                    COUNT(samples.id) AS sample_count,
                    MIN(samples.event_time) AS first_event_time,
                    MAX(samples.event_time) AS last_event_time,
                    MIN(samples.value) AS minimum,
                    MAX(samples.value) AS maximum,
                    AVG(samples.value) AS average,
                    (
                        SELECT latest.value
                        FROM industrial_samples AS latest
                        WHERE latest.signal_id = samples.signal_id
                        ORDER BY latest.event_time DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_value,
                    signals.nominal,
                    signals.lsl,
                    signals.usl,
                    COALESCE(
                        SUM(
                            CASE
                                WHEN signals.lsl IS NOT NULL
                                    AND NOT (
                                        signals.nominal IS NOT NULL
                                        AND ABS(signals.nominal) <= 0.000000000001
                                        AND ABS(signals.lsl) <= 0.000000000001
                                    )
                                    AND samples.value < signals.lsl
                                THEN 1
                                ELSE 0
                            END
                        ),
                        0
                    ) AS below_lsl_count,
                    COALESCE(
                        SUM(
                            CASE
                                WHEN signals.usl IS NOT NULL AND samples.value > signals.usl
                                THEN 1
                                ELSE 0
                            END
                        ),
                        0
                    ) AS above_usl_count
                FROM industrial_samples AS samples
                JOIN industrial_signal_definitions AS signals ON signals.id = samples.signal_id
                JOIN industrial_source_profiles AS profiles ON profiles.id = samples.source_profile_id
                {where_clause}
                GROUP BY
                    samples.source_profile_id,
                    profiles.profile_key,
                    profiles.profile_name,
                    samples.signal_id,
                    signals.signal_key,
                    signals.metric_name,
                    signals.unit,
                    signals.nominal,
                    signals.lsl,
                    signals.usl
                ORDER BY last_event_time DESC, samples.signal_id ASC
                {limit_clause}
                """,
                tuple(params),
            )
            return [_aggregate_row_from_row(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def source_lag_health(
        self,
        *,
        max_lag_seconds: float = 300.0,
    ) -> list[SourceLagHealth]:
        self.ensure_schema()
        max_lag = _positive_lag_limit(max_lag_seconds)

        def _list(cursor) -> list[SourceLagHealth]:
            cursor.execute(
                """
                WITH source_streams AS (
                    SELECT source_profile_id, stream_key
                    FROM industrial_realtime_source_health
                    UNION
                    SELECT source_profile_id, stream_key
                    FROM industrial_stream_offsets
                )
                SELECT
                    source_streams.source_profile_id,
                    profiles.profile_key,
                    profiles.profile_name,
                    source_streams.stream_key,
                    COALESCE(health.latest_event_time, offsets.event_time_watermark),
                    offsets.last_success_at,
                    COALESCE(health.lag_seconds, offsets.lag_seconds),
                    COALESCE(offsets.status, health.status, 'idle'),
                    profiles.is_enabled,
                    health.status
                FROM source_streams
                JOIN industrial_source_profiles AS profiles
                  ON profiles.id = source_streams.source_profile_id
                LEFT JOIN industrial_stream_offsets AS offsets
                  ON offsets.source_profile_id = source_streams.source_profile_id
                 AND offsets.stream_key = source_streams.stream_key
                LEFT JOIN industrial_realtime_source_health AS health
                  ON health.source_profile_id = source_streams.source_profile_id
                 AND health.stream_key = source_streams.stream_key
                ORDER BY source_streams.source_profile_id ASC, source_streams.stream_key ASC
                """
            )
            return [_source_health_from_row(row, max_lag) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def acknowledge_event(
        self,
        *,
        event_id: int,
        ack_by: str,
        comment: str | None = None,
        ack_at: str | None = None,
    ) -> None:
        self._event_repository.acknowledge_event(
            event_id=event_id,
            ack_by=ack_by,
            comment=comment,
            ack_at=ack_at,
        )

    def resolve_event(
        self,
        *,
        event_id: int,
        resolved_by: str,
        comment: str | None = None,
        resolved_at: str | None = None,
    ) -> None:
        self._event_repository.resolve_event(
            event_id=event_id,
            resolved_by=resolved_by,
            comment=comment,
            resolved_at=resolved_at,
        )

    def mark_event_false_positive(
        self,
        *,
        event_id: int,
        marked_by: str,
        comment: str | None = None,
        marked_at: str | None = None,
    ) -> None:
        self._event_repository.mark_event_false_positive(
            event_id=event_id,
            marked_by=marked_by,
            comment=comment,
            marked_at=marked_at,
        )

    def dashboard_snapshot(
        self,
        *,
        open_event_limit: int = 100,
        timeline_limit: int = 300,
        signal_limit: int = 25,
        max_lag_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """Build a static-renderer snapshot from persisted rows only."""

        open_events = self.list_open_anomaly_events(limit=open_event_limit)
        source_health = self.source_lag_health(max_lag_seconds=max_lag_seconds)
        signal_ids = tuple(
            dict.fromkeys(
                (
                    *(event.signal_id for event in open_events),
                    *self.recent_sample_signal_ids(limit=signal_limit),
                )
            )
        )
        aggregate_rows = self.sample_aggregate_rows(signal_ids=signal_ids, limit=None)
        aggregate_by_signal_id = {row.signal_id: row for row in aggregate_rows}
        signals: list[dict[str, Any]] = []
        for signal_id in signal_ids:
            timeline = self.recent_signal_timeline_window(signal_id=signal_id, limit=timeline_limit)
            recent_events = self.recent_events_by_signal(signal_id=signal_id, limit=open_event_limit)
            event = next((item for item in open_events if item.signal_id == signal_id), None)
            aggregate = aggregate_by_signal_id.get(signal_id)
            first_point = timeline[0] if timeline else None
            signal_key = (
                first_point.signal_key
                if first_point
                else (aggregate.signal_key if aggregate else (event.signal_key if event else str(signal_id)))
            )
            metric_name = (
                first_point.metric_name
                if first_point
                else (aggregate.metric_name if aggregate else (event.metric_name if event else str(signal_id)))
            )
            unit = first_point.unit if first_point else (aggregate.unit if aggregate else (event.unit if event else None))
            source_name = _profile_label(event) or _aggregate_profile_label(aggregate)
            signals.append(
                {
                    "signal_id": signal_id,
                    "signal_key": signal_key,
                    "metric_name": metric_name,
                    "unit": unit,
                    "source_name": source_name,
                    "samples": [asdict(point) for point in timeline],
                    "events": [asdict(item) for item in recent_events],
                }
            )
        return {
            "generated_at": utc_timestamp(),
            "title": "Real-time Industrial Monitoring",
            "source_health": [asdict(row) for row in source_health],
            "events": [asdict(event) for event in open_events],
            "aggregate_rows": [asdict(row) for row in aggregate_rows],
            "signals": signals,
        }


_DASHBOARD_EVENT_SELECT = """
    SELECT
        events.id,
        events.sample_id,
        events.signal_id,
        samples.source_profile_id,
        profiles.profile_key,
        profiles.profile_name,
        signals.signal_key,
        samples.metric_name,
        signals.unit,
        events.event_time,
        events.detector_key,
        events.severity,
        events.score,
        events.observed_value,
        events.expected_value,
        events.threshold_json,
        events.explanation,
        events.status,
        events.created_at,
        samples.station,
        samples.line,
        samples.reference,
        samples.part_number,
        samples.revision,
        samples.work_order,
        samples.batch_lot
    FROM industrial_anomaly_events AS events
    JOIN industrial_samples AS samples ON samples.id = events.sample_id
    JOIN industrial_signal_definitions AS signals ON signals.id = events.signal_id
    JOIN industrial_source_profiles AS profiles ON profiles.id = samples.source_profile_id
"""


def _append_event_filters(
    where: list[str],
    params: list[Any],
    *,
    status: str | None = None,
    signal_id: int | None = None,
    detector_key: str | None = None,
    severity: str | None = None,
) -> None:
    if status is not None:
        _validate_status(status)
        where.append("events.status = ?")
        params.append(status)
    if signal_id is not None:
        where.append("events.signal_id = ?")
        params.append(int(signal_id))
    if detector_key is not None:
        where.append("events.detector_key = ?")
        params.append(detector_key)
    if severity is not None:
        _validate_severity(severity)
        where.append("events.severity = ?")
        params.append(severity)


def _validate_status(status: str) -> None:
    if status not in ANOMALY_EVENT_STATUSES:
        raise ValueError(f"unsupported anomaly event status: {status}")


def _validate_severity(severity: str) -> None:
    if severity not in ANOMALY_SEVERITIES:
        raise ValueError(f"unsupported anomaly severity: {severity}")


def _positive_limit(limit: int) -> int:
    value = int(limit)
    if value < 1:
        raise ValueError("limit must be positive")
    return value


def _positive_lag_limit(value: float) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("max_lag_seconds must be positive")
    return parsed


def _dashboard_event_from_row(row) -> DashboardAnomalyEvent:
    return DashboardAnomalyEvent(
        id=int(row[0]),
        sample_id=int(row[1]),
        signal_id=int(row[2]),
        source_profile_id=int(row[3]),
        profile_key=str(row[4]),
        profile_name=str(row[5]),
        signal_key=str(row[6]),
        metric_name=str(row[7]),
        unit=row[8],
        event_time=str(row[9]),
        detector_key=str(row[10]),
        severity=str(row[11]),
        score=float(row[12]),
        observed_value=float(row[13]),
        expected_value=float(row[14]) if row[14] is not None else None,
        threshold=dict(from_json(row[15], {})),
        explanation=str(row[16]),
        status=str(row[17]),
        created_at=str(row[18]),
        station=row[19],
        line=row[20],
        reference=row[21],
        part_number=row[22],
        revision=row[23],
        work_order=row[24],
        batch_lot=row[25],
    )


def _timeline_point_from_row(row) -> SignalTimelinePoint:
    return SignalTimelinePoint(
        sample_id=int(row[0]),
        signal_id=int(row[1]),
        source_profile_id=int(row[2]),
        signal_key=str(row[3]),
        metric_name=str(row[4]),
        unit=row[5],
        event_time=str(row[6]),
        ingest_time=str(row[7]),
        value=float(row[8]),
        reference=row[9],
        part_number=row[10],
        revision=row[11],
        station=row[12],
        line=row[13],
        work_order=row[14],
        batch_lot=row[15],
        quality_flags=tuple(from_json(row[16], [])),
        anomaly_count=int(row[17]),
        open_anomaly_count=int(row[18]),
        highest_severity=_SEVERITY_BY_RANK.get(int(row[19])) if row[19] is not None else None,
    )


def _source_health_from_row(row, max_lag_seconds: float) -> SourceLagHealth:
    lag_seconds = float(row[6]) if row[6] is not None else None
    status = str(row[7])
    computed_status = str(row[9]) if len(row) > 9 and row[9] is not None else None
    if computed_status == "healthy":
        health = "healthy"
    elif computed_status in {"warning", "major"}:
        health = "lagging"
    elif computed_status == "no_data":
        health = "unknown"
    else:
        health = _offset_health(
            status=status,
            lag_seconds=lag_seconds,
            max_lag_seconds=max_lag_seconds,
        )
    return SourceLagHealth(
        source_profile_id=int(row[0]),
        profile_key=str(row[1]),
        profile_name=str(row[2]),
        stream_key=str(row[3]),
        event_time_watermark=row[4],
        last_success_at=row[5],
        lag_seconds=lag_seconds,
        status=status,
        health=health,
        is_enabled=bool(row[8]),
    )


def _aggregate_row_from_row(row) -> SignalAggregateRow:
    sample_count = int(row[7])
    below_lsl_count = int(row[17] or 0)
    above_usl_count = int(row[18] or 0)
    nok_count = below_lsl_count + above_usl_count
    return SignalAggregateRow(
        source_profile_id=int(row[0]),
        profile_key=str(row[1]),
        profile_name=str(row[2]),
        signal_id=int(row[3]),
        signal_key=str(row[4]),
        metric_name=str(row[5]),
        unit=row[6],
        sample_count=sample_count,
        first_event_time=str(row[8]),
        last_event_time=str(row[9]),
        minimum=float(row[10]),
        maximum=float(row[11]),
        average=float(row[12]),
        latest_value=float(row[13]),
        nominal=float(row[14]) if row[14] is not None else None,
        lsl=float(row[15]) if row[15] is not None else None,
        usl=float(row[16]) if row[16] is not None else None,
        below_lsl_count=below_lsl_count,
        above_usl_count=above_usl_count,
        nok_count=nok_count,
        nok_pct=(nok_count / sample_count) if sample_count else 0.0,
    )


def _offset_health(*, status: str, lag_seconds: float | None, max_lag_seconds: float) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"error", "failed"}:
        return "error"
    if lag_seconds is None:
        return "unknown"
    if lag_seconds > max_lag_seconds or normalized in {"stale", "lagging"}:
        return "lagging"
    if normalized in {"idle", "running", "succeeded", "healthy"}:
        return "healthy"
    return "unknown"


def _profile_label(event: DashboardAnomalyEvent | None) -> str:
    if event is None:
        return ""
    return event.profile_name or event.profile_key


def _aggregate_profile_label(row: SignalAggregateRow | None) -> str:
    if row is None:
        return ""
    return row.profile_name or row.profile_key
