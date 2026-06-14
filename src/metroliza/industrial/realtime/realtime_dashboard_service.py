"""Read models for persisted realtime industrial dashboard data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from metroliza.industrial.anomaly.contracts import ANOMALY_SEVERITIES
from metroliza.industrial.anomaly.event_repository import (
    ANOMALY_EVENT_STATUSES,
    AnomalyEventRepository,
)
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import from_json, utc_timestamp
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
                params.append(start_time)
            if end_time is not None:
                where.append("samples.event_time <= ?")
                params.append(end_time)
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
                SELECT
                    offsets.source_profile_id,
                    profiles.profile_key,
                    profiles.profile_name,
                    offsets.stream_key,
                    offsets.event_time_watermark,
                    offsets.last_success_at,
                    offsets.lag_seconds,
                    offsets.status,
                    profiles.is_enabled
                FROM industrial_stream_offsets AS offsets
                JOIN industrial_source_profiles AS profiles ON profiles.id = offsets.source_profile_id
                ORDER BY offsets.source_profile_id ASC, offsets.stream_key ASC
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
        max_lag_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """Build a static-renderer snapshot from persisted rows only."""

        open_events = self.list_open_anomaly_events(limit=open_event_limit)
        source_health = self.source_lag_health(max_lag_seconds=max_lag_seconds)
        signal_ids = tuple(dict.fromkeys(event.signal_id for event in open_events))
        signals: list[dict[str, Any]] = []
        for signal_id in signal_ids:
            timeline = self.signal_timeline_window(signal_id=signal_id, limit=timeline_limit)
            recent_events = self.recent_events_by_signal(signal_id=signal_id, limit=open_event_limit)
            event = next((item for item in open_events if item.signal_id == signal_id), None)
            first_point = timeline[0] if timeline else None
            signal_key = first_point.signal_key if first_point else (event.signal_key if event else str(signal_id))
            metric_name = first_point.metric_name if first_point else (event.metric_name if event else str(signal_id))
            unit = first_point.unit if first_point else (event.unit if event else None)
            source_name = _profile_label(event)
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
    return SourceLagHealth(
        source_profile_id=int(row[0]),
        profile_key=str(row[1]),
        profile_name=str(row[2]),
        stream_key=str(row[3]),
        event_time_watermark=row[4],
        last_success_at=row[5],
        lag_seconds=lag_seconds,
        status=status,
        health=_offset_health(status=status, lag_seconds=lag_seconds, max_lag_seconds=max_lag_seconds),
        is_enabled=bool(row[8]),
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
