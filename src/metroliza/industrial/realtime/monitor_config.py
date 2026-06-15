"""Persistence for realtime industrial monitor configurations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from metroliza.industrial.industrial_analytics_state import (
    SUPPORTED_AGGREGATION_METHODS,
    SUPPORTED_TIME_BUCKETS,
    require_identifier,
)
from metroliza.industrial.industrial_data_schema import ensure_industrial_data_schema
from metroliza.industrial.realtime.sample_repository import from_json, to_json, utc_timestamp
from metroliza.industrial.realtime.stream_config import (
    DEFAULT_CONTEXT_FIELDS,
    DEFAULT_SEGMENT_FIELDS,
    RealtimePollConfig,
    RealtimeStreamConfigError,
    reject_sensitive_config_payload,
)
from metroliza.reports.db import run_transaction_with_retry


DISPLAY_MODES = frozenset({"raw", "aggregated"})
DEFAULT_AGGREGATION_METHODS = ("mean",)


@dataclass(frozen=True)
class RealtimeMonitorConfig:
    """Saved operator configuration for one realtime stream."""

    source_profile_id: int
    stream_key: str
    cursor_column: str
    event_time_column: str
    record_key_column: str
    signal_keys: tuple[str, ...]
    signal_columns: Mapping[str, str]
    id: int | None = None
    enabled: bool = True
    polling_interval_seconds: float = 60.0
    timeout_seconds: float = 30.0
    chunk_size: int = 500
    max_catchup_rows_per_cycle: int = 5_000
    allowed_lateness_seconds: float = 0.0
    segment_fields: tuple[str, ...] = DEFAULT_SEGMENT_FIELDS
    context_fields: tuple[str, ...] = DEFAULT_CONTEXT_FIELDS
    detectors: tuple[str, ...] = ("spec_limits",)
    display_mode: str = "raw"
    aggregation_time_bucket: str = "none"
    aggregation_methods: tuple[str, ...] = DEFAULT_AGGREGATION_METHODS
    aggregation_group_fields: tuple[str, ...] = ()
    dashboard_output_path: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_poll_config(self) -> RealtimePollConfig:
        """Return the bounded polling config used by the runtime."""

        return RealtimePollConfig(
            source_profile_id=self.source_profile_id,
            stream_key=self.stream_key,
            cursor_column=self.cursor_column,
            event_time_column=self.event_time_column,
            record_key_column=self.record_key_column,
            signal_keys=self.signal_keys,
            signal_columns=self.signal_columns,
            enabled=self.enabled,
            polling_interval_seconds=self.polling_interval_seconds,
            chunk_size=self.chunk_size,
            max_catchup_rows_per_cycle=self.max_catchup_rows_per_cycle,
            allowed_lateness_seconds=self.allowed_lateness_seconds,
            timeout_seconds=self.timeout_seconds,
            segment_fields=self.segment_fields,
            context_fields=self.context_fields,
            detectors=self.detectors,
        )

    def validated(self) -> "RealtimeMonitorConfig":
        """Return a normalized monitor config or raise a safety error."""

        reject_sensitive_config_payload(
            {
                "signal_columns": dict(self.signal_columns),
                "dashboard_output_path": self.dashboard_output_path,
            }
        )
        poll_config = self.to_poll_config().validated()
        display_mode = str(self.display_mode or "raw").strip().lower()
        if display_mode not in DISPLAY_MODES:
            raise RealtimeStreamConfigError(f"Unsupported realtime display mode: {self.display_mode}")

        aggregation_time_bucket = str(self.aggregation_time_bucket or "none").strip().lower()
        if aggregation_time_bucket not in SUPPORTED_TIME_BUCKETS:
            raise RealtimeStreamConfigError(
                f"Unsupported realtime aggregation time bucket: {self.aggregation_time_bucket}"
            )
        aggregation_methods = tuple(
            dict.fromkeys(str(method or "").strip().lower() for method in self.aggregation_methods)
        )
        if not aggregation_methods:
            raise RealtimeStreamConfigError("Select at least one realtime aggregation method.")
        invalid_methods = [
            method for method in aggregation_methods if method not in SUPPORTED_AGGREGATION_METHODS
        ]
        if invalid_methods:
            raise RealtimeStreamConfigError(
                f"Unsupported realtime aggregation method(s): {', '.join(invalid_methods)}"
            )
        aggregation_group_fields = tuple(
            dict.fromkeys(str(field or "").strip() for field in self.aggregation_group_fields)
        )
        for field_name in aggregation_group_fields:
            try:
                require_identifier("aggregation group field", field_name)
            except ValueError as exc:
                raise RealtimeStreamConfigError(str(exc)) from exc

        dashboard_output_path = str(self.dashboard_output_path or "").strip() or None
        return replace(
            self,
            source_profile_id=poll_config.source_profile_id,
            stream_key=poll_config.stream_key,
            cursor_column=poll_config.cursor_column,
            event_time_column=poll_config.event_time_column,
            record_key_column=poll_config.record_key_column,
            signal_keys=poll_config.signal_keys,
            signal_columns=poll_config.signal_columns,
            enabled=poll_config.enabled,
            polling_interval_seconds=poll_config.polling_interval_seconds,
            timeout_seconds=poll_config.timeout_seconds,
            chunk_size=poll_config.chunk_size,
            max_catchup_rows_per_cycle=poll_config.max_catchup_rows_per_cycle,
            allowed_lateness_seconds=poll_config.allowed_lateness_seconds,
            segment_fields=poll_config.segment_fields,
            context_fields=poll_config.context_fields,
            detectors=poll_config.detectors,
            display_mode=display_mode,
            aggregation_time_bucket=aggregation_time_bucket,
            aggregation_methods=aggregation_methods,
            aggregation_group_fields=aggregation_group_fields,
            dashboard_output_path=dashboard_output_path,
        )


class RealtimeMonitorConfigRepository:
    """Store and retrieve realtime monitor configs from the local Metroliza DB."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def upsert_config(self, config: RealtimeMonitorConfig) -> RealtimeMonitorConfig:
        self.ensure_schema()
        validated = config.validated()
        now = utc_timestamp()

        def _upsert(cursor) -> RealtimeMonitorConfig:
            cursor.execute(
                """
                INSERT INTO industrial_realtime_monitor_configs (
                    source_profile_id,
                    stream_key,
                    enabled,
                    cursor_column,
                    event_time_column,
                    record_key_column,
                    signal_keys_json,
                    signal_columns_json,
                    polling_interval_seconds,
                    timeout_seconds,
                    chunk_size,
                    max_catchup_rows_per_cycle,
                    allowed_lateness_seconds,
                    segment_fields_json,
                    context_fields_json,
                    detectors_json,
                    display_mode,
                    aggregation_time_bucket,
                    aggregation_methods_json,
                    aggregation_group_fields_json,
                    dashboard_output_path,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_profile_id, stream_key) DO UPDATE SET
                    enabled = excluded.enabled,
                    cursor_column = excluded.cursor_column,
                    event_time_column = excluded.event_time_column,
                    record_key_column = excluded.record_key_column,
                    signal_keys_json = excluded.signal_keys_json,
                    signal_columns_json = excluded.signal_columns_json,
                    polling_interval_seconds = excluded.polling_interval_seconds,
                    timeout_seconds = excluded.timeout_seconds,
                    chunk_size = excluded.chunk_size,
                    max_catchup_rows_per_cycle = excluded.max_catchup_rows_per_cycle,
                    allowed_lateness_seconds = excluded.allowed_lateness_seconds,
                    segment_fields_json = excluded.segment_fields_json,
                    context_fields_json = excluded.context_fields_json,
                    detectors_json = excluded.detectors_json,
                    display_mode = excluded.display_mode,
                    aggregation_time_bucket = excluded.aggregation_time_bucket,
                    aggregation_methods_json = excluded.aggregation_methods_json,
                    aggregation_group_fields_json = excluded.aggregation_group_fields_json,
                    dashboard_output_path = excluded.dashboard_output_path,
                    updated_at = excluded.updated_at
                """,
                _config_row_values(validated, created_at=now, updated_at=now),
            )
            cursor.execute(
                """
                SELECT
                    id,
                    source_profile_id,
                    stream_key,
                    enabled,
                    cursor_column,
                    event_time_column,
                    record_key_column,
                    signal_keys_json,
                    signal_columns_json,
                    polling_interval_seconds,
                    timeout_seconds,
                    chunk_size,
                    max_catchup_rows_per_cycle,
                    allowed_lateness_seconds,
                    segment_fields_json,
                    context_fields_json,
                    detectors_json,
                    display_mode,
                    aggregation_time_bucket,
                    aggregation_methods_json,
                    aggregation_group_fields_json,
                    dashboard_output_path,
                    created_at,
                    updated_at
                FROM industrial_realtime_monitor_configs
                WHERE source_profile_id = ? AND stream_key = ?
                """,
                (validated.source_profile_id, validated.stream_key),
            )
            row = cursor.fetchone()
            assert row is not None
            return _row_to_config(row)

        return run_transaction_with_retry(self.database, _upsert, connection=self.connection)

    def list_configs(
        self,
        *,
        enabled_only: bool = False,
        source_profile_id: int | None = None,
    ) -> list[RealtimeMonitorConfig]:
        self.ensure_schema()

        def _list(cursor) -> list[RealtimeMonitorConfig]:
            where: list[str] = []
            params: list[Any] = []
            if enabled_only:
                where.append("enabled = 1")
            if source_profile_id is not None:
                where.append("source_profile_id = ?")
                params.append(int(source_profile_id))
            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            cursor.execute(
                f"""
                SELECT
                    id,
                    source_profile_id,
                    stream_key,
                    enabled,
                    cursor_column,
                    event_time_column,
                    record_key_column,
                    signal_keys_json,
                    signal_columns_json,
                    polling_interval_seconds,
                    timeout_seconds,
                    chunk_size,
                    max_catchup_rows_per_cycle,
                    allowed_lateness_seconds,
                    segment_fields_json,
                    context_fields_json,
                    detectors_json,
                    display_mode,
                    aggregation_time_bucket,
                    aggregation_methods_json,
                    aggregation_group_fields_json,
                    dashboard_output_path,
                    created_at,
                    updated_at
                FROM industrial_realtime_monitor_configs
                {where_clause}
                ORDER BY source_profile_id ASC, stream_key ASC
                """,
                tuple(params),
            )
            return [_row_to_config(row) for row in cursor.fetchall()]

        return run_transaction_with_retry(self.database, _list, connection=self.connection)

    def delete_config(self, *, source_profile_id: int, stream_key: str) -> None:
        self.ensure_schema()

        def _delete(cursor) -> None:
            cursor.execute(
                """
                DELETE FROM industrial_realtime_monitor_configs
                WHERE source_profile_id = ? AND stream_key = ?
                """,
                (int(source_profile_id), str(stream_key or "").strip()),
            )

        run_transaction_with_retry(self.database, _delete, connection=self.connection)


def _config_row_values(
    config: RealtimeMonitorConfig,
    *,
    created_at: str,
    updated_at: str,
) -> tuple[Any, ...]:
    return (
        config.source_profile_id,
        config.stream_key,
        int(bool(config.enabled)),
        config.cursor_column,
        config.event_time_column,
        config.record_key_column,
        to_json(list(config.signal_keys)),
        to_json(dict(config.signal_columns)),
        config.polling_interval_seconds,
        config.timeout_seconds,
        config.chunk_size,
        config.max_catchup_rows_per_cycle,
        config.allowed_lateness_seconds,
        to_json(list(config.segment_fields)),
        to_json(list(config.context_fields)),
        to_json(list(config.detectors)),
        config.display_mode,
        config.aggregation_time_bucket,
        to_json(list(config.aggregation_methods)),
        to_json(list(config.aggregation_group_fields)),
        config.dashboard_output_path,
        created_at,
        updated_at,
    )


def _row_to_config(row) -> RealtimeMonitorConfig:
    signal_keys = tuple(str(value) for value in from_json(row[7], []))
    segment_fields = tuple(str(value) for value in from_json(row[14], [])) or DEFAULT_SEGMENT_FIELDS
    context_fields = tuple(str(value) for value in from_json(row[15], [])) or DEFAULT_CONTEXT_FIELDS
    detectors = tuple(str(value) for value in from_json(row[16], [])) or ("spec_limits",)
    aggregation_methods = (
        tuple(str(value) for value in from_json(row[19], [])) or DEFAULT_AGGREGATION_METHODS
    )
    return RealtimeMonitorConfig(
        id=int(row[0]),
        source_profile_id=int(row[1]),
        stream_key=str(row[2]),
        enabled=bool(row[3]),
        cursor_column=str(row[4]),
        event_time_column=str(row[5]),
        record_key_column=str(row[6]),
        signal_keys=signal_keys,
        signal_columns={str(key): str(value) for key, value in dict(from_json(row[8], {})).items()},
        polling_interval_seconds=float(row[9]),
        timeout_seconds=float(row[10]),
        chunk_size=int(row[11]),
        max_catchup_rows_per_cycle=int(row[12]),
        allowed_lateness_seconds=float(row[13]),
        segment_fields=segment_fields,
        context_fields=context_fields,
        detectors=detectors,
        display_mode=str(row[17]),
        aggregation_time_bucket=str(row[18]),
        aggregation_methods=aggregation_methods,
        aggregation_group_fields=tuple(str(value) for value in from_json(row[20], [])),
        dashboard_output_path=row[21],
        created_at=str(row[22]),
        updated_at=str(row[23]),
    ).validated()
