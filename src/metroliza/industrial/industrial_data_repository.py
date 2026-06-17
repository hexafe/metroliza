"""Repository helpers for Metroliza industrial cache storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Iterable, Mapping

from metroliza.reports.db import chunked_values, run_transaction_with_retry
from metroliza.industrial.industrial_data_schema import SYNC_RUN_STATUSES, ensure_industrial_data_schema
from metroliza.industrial.json_safety import to_json_storage_text, to_sqlite_storage_text


_FINISHED_SYNC_RUN_STATUSES = tuple(status for status in SYNC_RUN_STATUSES if status != "running")
_REDACT_URI_CREDENTIALS = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^:/\s]+:)([^@/\s]+)@")
_REDACT_KEY_VALUE = re.compile(
    r"(?i)\b(password|passwd|pwd|[a-z0-9_-]*token|[a-z0-9_-]*secret|credential|api[_-]?key|access[_-]?key)\s*([=:])\s*([^,\s;]+)"
)
_REDACT_QUOTED_KEY_VALUE = re.compile(
    r"(?i)(['\"]?(?:password|passwd|pwd|[a-z0-9_-]*token|[a-z0-9_-]*secret|credential|api[_-]?key|access[_-]?key)['\"]?\s*:\s*['\"])([^'\",;}]+)(['\"]?)"
)

SENSITIVE_KEY_NAMES = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_token",
        "api_key",
        "secret_key",
        "client_secret",
        "credential",
        "credentials",
    }
)
SENSITIVE_COMPACT_KEY_NAMES = frozenset(
    re.sub(r"[^a-z0-9]+", "", key) for key in SENSITIVE_KEY_NAMES
) | frozenset(
    {
        "apikey",
        "apitoken",
        "accesstoken",
        "refreshtoken",
        "accesskey",
        "secretkey",
        "clientsecret",
    }
)
SENSITIVE_COMPACT_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "apikey",
    "apitoken",
    "accesskey",
    "clientsecret",
)

KNOWN_RECORD_FIELDS = frozenset(
    {
        "source_record_key",
        "source_profile_id",
        "source_database_alias",
        "process_timestamp",
        "reference",
        "part_number",
        "part_name",
        "revision",
        "serial",
        "batch_lot",
        "work_order",
        "station",
        "line",
        "operator_name",
        "process_status",
        "raw_record",
    }
)

ROW_FIELD_ALIASES = {
    "record_key": "source_record_key",
    "source_primary_key": "source_record_key",
    "timestamp": "process_timestamp",
    "process_ts": "process_timestamp",
    "part": "part_name",
    "batch": "batch_lot",
    "lot": "batch_lot",
    "operator": "operator_name",
    "status": "process_status",
}


@dataclass(frozen=True)
class IndustrialSourceProfile:
    """Typed source profile metadata without credentials."""

    id: int
    profile_key: str
    profile_name: str
    source_db_alias: str
    database_type: str
    host: str | None
    port: int | None
    database_name: str | None
    source_object_name: str
    allowed_columns: tuple[str, ...]
    timestamp_column: str | None
    default_pagination_column: str | None
    is_enabled: bool
    created_at: str
    updated_at: str
    order_by_enabled: bool = True


@dataclass(frozen=True)
class IndustrialCacheCounts:
    """Summary counts for industrial cache tables."""

    source_profiles: int
    sync_runs: int
    records: int
    record_values: int
    join_rules: int
    link_candidates: int

    def as_dict(self) -> dict[str, int]:
        return {
            "source_profiles": self.source_profiles,
            "sync_runs": self.sync_runs,
            "records": self.records,
            "record_values": self.record_values,
            "join_rules": self.join_rules,
            "link_candidates": self.link_candidates,
        }


@dataclass(frozen=True)
class IndustrialSyncRunSummary:
    """Compact, redacted summary of one persisted industrial sync run."""

    id: int
    source_profile_id: int
    profile_key: str
    profile_name: str
    started_at: str
    finished_at: str | None
    status: str
    row_count: int
    error_summary: str | None
    diagnostics: Mapping[str, Any]


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp suitable for SQLite text columns."""

    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _to_json(value: Any) -> str | None:
    return to_json_storage_text(value)


def _from_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def redact_sensitive_text(value: Any, *, max_len: int | None = 320) -> str:
    """Redact credential-like fragments from free-form diagnostics text."""

    text = str(value or "").strip()
    text = _REDACT_URI_CREDENTIALS.sub(r"\1<redacted>@", text)
    text = _REDACT_KEY_VALUE.sub(r"\1\2<redacted>", text)
    text = _REDACT_QUOTED_KEY_VALUE.sub(r"\1<redacted>\3", text)
    if max_len is not None and len(text) > max_len:
        return f"{text[: max_len - 3]}..."
    return text


def looks_sensitive_key(key: str) -> bool:
    """Return whether a payload key should be treated as credential-like."""

    token = str(key or "").strip().lower()
    compact_token = re.sub(r"[^a-z0-9]+", "", token)
    return (
        token in SENSITIVE_KEY_NAMES
        or compact_token in SENSITIVE_COMPACT_KEY_NAMES
        or any(part in compact_token for part in SENSITIVE_COMPACT_SUBSTRINGS)
    )


def _looks_sensitive_key(key: str) -> bool:
    return looks_sensitive_key(key)


def _redact_sensitive_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            normalized_key = str(key)
            if _looks_sensitive_key(normalized_key):
                redacted[normalized_key] = "<redacted>"
                continue
            redacted[normalized_key] = _redact_sensitive_payload(nested)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_payload(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value, max_len=None)
    return value


def _normalize_allowed_columns(allowed_columns: Iterable[str] | None) -> tuple[str, ...]:
    if not allowed_columns:
        return ()
    seen: set[str] = set()
    normalized: list[str] = []
    for column in allowed_columns:
        name = str(column).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return tuple(normalized)


def _normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        key_name = str(key).strip()
        if not key_name:
            continue
        key_name = ROW_FIELD_ALIASES.get(key_name, key_name)
        normalized[key_name] = value
    return normalized


@dataclass(frozen=True)
class _PreparedIndustrialRecordRow:
    record_key: str
    record_params: tuple[Any, ...]
    dynamic_values: tuple[tuple[str, str | None, str | None], ...]


def _dynamic_value_storage(field_value: Any) -> tuple[str | None, str | None]:
    if isinstance(field_value, (dict, list, tuple)):
        return None, _to_json(_redact_sensitive_payload(field_value))
    if field_value is None:
        return None, None
    return to_sqlite_storage_text(field_value), None


class IndustrialDataRepository:
    """Persistence facade for additive industrial cache tables."""

    def __init__(self, database: str, *, connection=None):
        self.database = database
        self.connection = connection

    def ensure_schema(self) -> None:
        ensure_industrial_data_schema(self.database, connection=self.connection)

    def upsert_source_profile(
        self,
        *,
        profile_key: str,
        profile_name: str,
        source_db_alias: str,
        database_type: str,
        source_object_name: str,
        host: str | None = None,
        port: int | None = None,
        database_name: str | None = None,
        allowed_columns: Iterable[str] | None = None,
        timestamp_column: str | None = None,
        default_pagination_column: str | None = None,
        is_enabled: bool = True,
        order_by_enabled: bool = True,
    ) -> IndustrialSourceProfile:
        self.ensure_schema()
        now = utc_timestamp()
        normalized_columns = _normalize_allowed_columns(allowed_columns)

        def _upsert(cursor) -> IndustrialSourceProfile:
            cursor.execute(
                """
                INSERT INTO industrial_source_profiles (
                    profile_key,
                    profile_name,
                    source_db_alias,
                    database_type,
                    host,
                    port,
                    database_name,
                    source_object_name,
                    allowed_columns_json,
                    timestamp_column,
                    default_pagination_column,
                    is_enabled,
                    order_by_enabled,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_key) DO UPDATE SET
                    profile_name = excluded.profile_name,
                    source_db_alias = excluded.source_db_alias,
                    database_type = excluded.database_type,
                    host = excluded.host,
                    port = excluded.port,
                    database_name = excluded.database_name,
                    source_object_name = excluded.source_object_name,
                    allowed_columns_json = excluded.allowed_columns_json,
                    timestamp_column = excluded.timestamp_column,
                    default_pagination_column = excluded.default_pagination_column,
                    is_enabled = excluded.is_enabled,
                    order_by_enabled = excluded.order_by_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_key,
                    profile_name,
                    source_db_alias,
                    database_type,
                    (host or "").strip() or None,
                    int(port) if port is not None else None,
                    (database_name or "").strip() or None,
                    source_object_name,
                    _to_json(list(normalized_columns)),
                    timestamp_column,
                    default_pagination_column,
                    int(bool(is_enabled)),
                    int(bool(order_by_enabled)),
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                SELECT
                    id,
                    profile_key,
                    profile_name,
                    source_db_alias,
                    database_type,
                    host,
                    port,
                    database_name,
                    source_object_name,
                    allowed_columns_json,
                    timestamp_column,
                    default_pagination_column,
                    is_enabled,
                    created_at,
                    updated_at,
                    order_by_enabled
                FROM industrial_source_profiles
                WHERE profile_key = ?
                """,
                (profile_key,),
            )
            row = cursor.fetchone()
            assert row is not None
            return IndustrialSourceProfile(
                id=int(row[0]),
                profile_key=str(row[1]),
                profile_name=str(row[2]),
                source_db_alias=str(row[3]),
                database_type=str(row[4]),
                host=row[5],
                port=int(row[6]) if row[6] is not None else None,
                database_name=row[7],
                source_object_name=str(row[8]),
                allowed_columns=tuple(_from_json(row[9], [])),
                timestamp_column=row[10],
                default_pagination_column=row[11],
                is_enabled=bool(row[12]),
                created_at=str(row[13]),
                updated_at=str(row[14]),
                order_by_enabled=bool(row[15]),
            )

        return run_transaction_with_retry(self.database, _upsert, connection=self.connection)

    def list_source_profiles(self, *, include_disabled: bool = False) -> list[IndustrialSourceProfile]:
        self.ensure_schema()

        def _list_profiles(cursor) -> list[IndustrialSourceProfile]:
            where_clause = "" if include_disabled else "WHERE is_enabled = 1"
            cursor.execute(
                f"""
                SELECT
                    id,
                    profile_key,
                    profile_name,
                    source_db_alias,
                    database_type,
                    host,
                    port,
                    database_name,
                    source_object_name,
                    allowed_columns_json,
                    timestamp_column,
                    default_pagination_column,
                    is_enabled,
                    created_at,
                    updated_at,
                    order_by_enabled
                FROM industrial_source_profiles
                {where_clause}
                ORDER BY profile_name COLLATE NOCASE ASC, id ASC
                """
            )
            profiles: list[IndustrialSourceProfile] = []
            for row in cursor.fetchall():
                profiles.append(
                    IndustrialSourceProfile(
                        id=int(row[0]),
                        profile_key=str(row[1]),
                        profile_name=str(row[2]),
                        source_db_alias=str(row[3]),
                        database_type=str(row[4]),
                        host=row[5],
                        port=int(row[6]) if row[6] is not None else None,
                        database_name=row[7],
                        source_object_name=str(row[8]),
                        allowed_columns=tuple(_from_json(row[9], [])),
                        timestamp_column=row[10],
                        default_pagination_column=row[11],
                        is_enabled=bool(row[12]),
                        created_at=str(row[13]),
                        updated_at=str(row[14]),
                        order_by_enabled=bool(row[15]),
                    )
                )
            return profiles

        return run_transaction_with_retry(self.database, _list_profiles, connection=self.connection)

    def create_sync_run(
        self,
        *,
        source_profile_id: int,
        filters: Mapping[str, Any] | None = None,
        oznak_version: str | None = None,
        oznak_commit: str | None = None,
        diagnostics: Mapping[str, Any] | None = None,
        started_at: str | None = None,
    ) -> int:
        self.ensure_schema()
        started = started_at or utc_timestamp()
        filters_payload = _redact_sensitive_payload(dict(filters or {}))
        diagnostics_payload = _redact_sensitive_payload(dict(diagnostics or {}))

        def _create(cursor) -> int:
            cursor.execute(
                """
                INSERT INTO industrial_sync_runs (
                    source_profile_id,
                    started_at,
                    status,
                    row_count,
                    error_summary,
                    filters_json,
                    oznak_version,
                    oznak_commit,
                    diagnostics_json
                )
                VALUES (?, ?, 'running', 0, NULL, ?, ?, ?, ?)
                """,
                (
                    source_profile_id,
                    started,
                    _to_json(filters_payload),
                    oznak_version,
                    oznak_commit,
                    _to_json(diagnostics_payload),
                ),
            )
            return int(cursor.lastrowid)

        return run_transaction_with_retry(self.database, _create, connection=self.connection)

    def finish_sync_run(
        self,
        *,
        sync_run_id: int,
        status: str,
        row_count: int,
        error_summary: str | None = None,
        diagnostics: Mapping[str, Any] | None = None,
        finished_at: str | None = None,
    ) -> None:
        self.ensure_schema()
        if status not in _FINISHED_SYNC_RUN_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(_FINISHED_SYNC_RUN_STATUSES)}")
        finished = finished_at or utc_timestamp()
        diagnostics_payload = _redact_sensitive_payload(dict(diagnostics or {}))
        redacted_error_summary = (
            redact_sensitive_text(error_summary, max_len=500) if error_summary else None
        )

        def _finish(cursor) -> None:
            cursor.execute(
                """
                UPDATE industrial_sync_runs
                SET
                    finished_at = ?,
                    status = ?,
                    row_count = ?,
                    error_summary = ?,
                    diagnostics_json = ?
                WHERE id = ?
                """,
                (
                    finished,
                    status,
                    int(row_count),
                    redacted_error_summary,
                    _to_json(diagnostics_payload),
                    sync_run_id,
                ),
            )
            if cursor.rowcount < 1:
                raise ValueError(f"sync_run_id not found: {sync_run_id}")

        run_transaction_with_retry(self.database, _finish, connection=self.connection)

    def latest_sync_run(
        self,
        *,
        source_profile_id: int | None = None,
    ) -> IndustrialSyncRunSummary | None:
        """Return the most recent persisted sync run, if one exists."""

        self.ensure_schema()

        def _latest(cursor) -> IndustrialSyncRunSummary | None:
            params: tuple[Any, ...]
            profile_filter = ""
            if source_profile_id is None:
                params = ()
            else:
                profile_filter = "WHERE runs.source_profile_id = ?"
                params = (source_profile_id,)
            cursor.execute(
                f"""
                SELECT
                    runs.id,
                    runs.source_profile_id,
                    profiles.profile_key,
                    profiles.profile_name,
                    runs.started_at,
                    runs.finished_at,
                    runs.status,
                    runs.row_count,
                    runs.error_summary,
                    runs.diagnostics_json
                FROM industrial_sync_runs AS runs
                JOIN industrial_source_profiles AS profiles
                    ON profiles.id = runs.source_profile_id
                {profile_filter}
                ORDER BY COALESCE(runs.finished_at, runs.started_at) DESC, runs.id DESC
                LIMIT 1
                """,
                params,
            )
            row = cursor.fetchone()
            if row is None:
                return None
            diagnostics = _from_json(row[9], {})
            if not isinstance(diagnostics, dict):
                diagnostics = {}
            return IndustrialSyncRunSummary(
                id=int(row[0]),
                source_profile_id=int(row[1]),
                profile_key=str(row[2]),
                profile_name=str(row[3]),
                started_at=str(row[4]),
                finished_at=str(row[5]) if row[5] else None,
                status=str(row[6]),
                row_count=int(row[7]),
                error_summary=row[8],
                diagnostics=diagnostics,
            )

        return run_transaction_with_retry(self.database, _latest, connection=self.connection)

    def upsert_industrial_records_from_rows(
        self,
        *,
        source_profile_id: int,
        source_db_alias: str,
        rows: Iterable[Mapping[str, Any]],
        sync_run_id: int | None = None,
    ) -> dict[str, int]:
        self.ensure_schema()
        now = utc_timestamp()
        prepared_rows: list[_PreparedIndustrialRecordRow] = []
        value_rows = 0

        for row in rows:
            normalized = _normalize_row(row)
            record_key_raw = normalized.get("source_record_key")
            record_key = str(record_key_raw).strip() if record_key_raw is not None else ""
            if not record_key:
                raise ValueError("each row must include source_record_key (or record_key alias)")

            raw_record = normalized.get("raw_record", dict(row))
            redacted_raw_record = _redact_sensitive_payload(raw_record)
            dynamic_values = tuple(
                (field_name, *_dynamic_value_storage(field_value))
                for field_name, field_value in normalized.items()
                if field_name not in KNOWN_RECORD_FIELDS and not _looks_sensitive_key(field_name)
            )
            value_rows += len(dynamic_values)
            prepared_rows.append(
                _PreparedIndustrialRecordRow(
                    record_key=record_key,
                    record_params=(
                        source_profile_id,
                        sync_run_id,
                        source_db_alias,
                        record_key,
                        to_sqlite_storage_text(normalized.get("process_timestamp")),
                        to_sqlite_storage_text(normalized.get("reference")),
                        to_sqlite_storage_text(normalized.get("part_number")),
                        to_sqlite_storage_text(normalized.get("part_name")),
                        to_sqlite_storage_text(normalized.get("revision")),
                        to_sqlite_storage_text(normalized.get("serial")),
                        to_sqlite_storage_text(normalized.get("batch_lot")),
                        to_sqlite_storage_text(normalized.get("work_order")),
                        to_sqlite_storage_text(normalized.get("station")),
                        to_sqlite_storage_text(normalized.get("line")),
                        to_sqlite_storage_text(normalized.get("operator_name")),
                        to_sqlite_storage_text(normalized.get("process_status")),
                        _to_json(redacted_raw_record) or "{}",
                        now,
                        now,
                    ),
                    dynamic_values=dynamic_values,
                )
            )

        if not prepared_rows:
            return {
                "processed": 0,
                "inserted": 0,
                "updated": 0,
                "value_rows": 0,
            }

        def _upsert_rows(cursor) -> dict[str, int]:
            inserted = 0
            updated = 0
            existing_record_keys: set[str] = set()
            unique_record_keys = tuple(dict.fromkeys(row.record_key for row in prepared_rows))
            for key_chunk in chunked_values(unique_record_keys, chunk_size=800):
                placeholders = ", ".join("?" for _ in key_chunk)
                cursor.execute(
                    f"""
                    SELECT source_record_key
                    FROM industrial_records
                    WHERE source_profile_id = ?
                      AND source_db_alias = ?
                      AND source_record_key IN ({placeholders})
                    """,
                    (source_profile_id, source_db_alias, *key_chunk),
                )
                existing_record_keys.update(str(row[0]) for row in cursor.fetchall())

            inserted_record_keys: set[str] = set()
            for prepared_row in prepared_rows:
                if (
                    prepared_row.record_key in existing_record_keys
                    or prepared_row.record_key in inserted_record_keys
                ):
                    updated += 1
                    continue
                inserted += 1
                inserted_record_keys.add(prepared_row.record_key)

            cursor.executemany(
                """
                INSERT INTO industrial_records (
                    source_profile_id,
                    sync_run_id,
                    source_db_alias,
                    source_record_key,
                    process_timestamp,
                    reference,
                    part_number,
                    part_name,
                    revision,
                    serial,
                    batch_lot,
                    work_order,
                    station,
                    line,
                    operator_name,
                    process_status,
                    raw_record_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_profile_id, source_db_alias, source_record_key) DO UPDATE SET
                    sync_run_id = excluded.sync_run_id,
                    process_timestamp = excluded.process_timestamp,
                    reference = excluded.reference,
                    part_number = excluded.part_number,
                    part_name = excluded.part_name,
                    revision = excluded.revision,
                    serial = excluded.serial,
                    batch_lot = excluded.batch_lot,
                    work_order = excluded.work_order,
                    station = excluded.station,
                    line = excluded.line,
                    operator_name = excluded.operator_name,
                    process_status = excluded.process_status,
                    raw_record_json = excluded.raw_record_json,
                    updated_at = excluded.updated_at
                """,
                [row.record_params for row in prepared_rows],
            )

            record_ids_by_key: dict[str, int] = {}
            for key_chunk in chunked_values(unique_record_keys, chunk_size=800):
                placeholders = ", ".join("?" for _ in key_chunk)
                cursor.execute(
                    f"""
                    SELECT source_record_key, id
                    FROM industrial_records
                    WHERE source_profile_id = ?
                      AND source_db_alias = ?
                      AND source_record_key IN ({placeholders})
                    """,
                    (source_profile_id, source_db_alias, *key_chunk),
                )
                record_ids_by_key.update((str(row[0]), int(row[1])) for row in cursor.fetchall())

            missing_keys = [key for key in unique_record_keys if key not in record_ids_by_key]
            if missing_keys:
                raise RuntimeError("industrial record upsert did not return all affected record ids")

            record_ids = tuple(record_ids_by_key[key] for key in unique_record_keys)
            for record_id_chunk in chunked_values(record_ids, chunk_size=900):
                placeholders = ", ".join("?" for _ in record_id_chunk)
                cursor.execute(
                    f"DELETE FROM industrial_record_values WHERE record_id IN ({placeholders})",
                    tuple(record_id_chunk),
                )

            final_dynamic_values_by_key: dict[
                str, tuple[tuple[str, str | None, str | None], ...]
            ] = {}
            for prepared_row in prepared_rows:
                final_dynamic_values_by_key[prepared_row.record_key] = prepared_row.dynamic_values

            dynamic_params = [
                (record_ids_by_key[record_key], field_name, value_text, value_json, now)
                for record_key, dynamic_values in final_dynamic_values_by_key.items()
                for field_name, value_text, value_json in dynamic_values
            ]
            if dynamic_params:
                cursor.executemany(
                    """
                    INSERT INTO industrial_record_values (
                        record_id,
                        field_name,
                        field_value_text,
                        field_value_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(record_id, field_name) DO UPDATE SET
                        field_value_text = excluded.field_value_text,
                        field_value_json = excluded.field_value_json
                    """,
                    dynamic_params,
                )

            return {
                "processed": inserted + updated,
                "inserted": inserted,
                "updated": updated,
                "value_rows": value_rows,
            }

        return run_transaction_with_retry(self.database, _upsert_rows, connection=self.connection)

    def summarize_counts(self, *, source_profile_id: int | None = None) -> IndustrialCacheCounts:
        self.ensure_schema()

        def _counts(cursor) -> IndustrialCacheCounts:
            profile_filter = ""
            params: tuple[Any, ...]
            if source_profile_id is None:
                params = ()
            else:
                profile_filter = " WHERE source_profile_id = ?"
                params = (source_profile_id,)

            cursor.execute("SELECT COUNT(*) FROM industrial_source_profiles")
            source_profiles = int(cursor.fetchone()[0])

            cursor.execute(f"SELECT COUNT(*) FROM industrial_sync_runs{profile_filter}", params)
            sync_runs = int(cursor.fetchone()[0])

            cursor.execute(f"SELECT COUNT(*) FROM industrial_records{profile_filter}", params)
            records = int(cursor.fetchone()[0])

            if source_profile_id is None:
                cursor.execute("SELECT COUNT(*) FROM industrial_record_values")
            else:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM industrial_record_values values_row
                    JOIN industrial_records records_row ON records_row.id = values_row.record_id
                    WHERE records_row.source_profile_id = ?
                    """,
                    (source_profile_id,),
                )
            record_values = int(cursor.fetchone()[0])

            cursor.execute("SELECT COUNT(*) FROM industrial_join_rules")
            join_rules = int(cursor.fetchone()[0])

            if source_profile_id is None:
                cursor.execute("SELECT COUNT(*) FROM industrial_link_candidates")
            else:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM industrial_link_candidates candidates
                    JOIN industrial_records records_row ON records_row.id = candidates.industrial_record_id
                    WHERE records_row.source_profile_id = ?
                    """,
                    (source_profile_id,),
                )
            link_candidates = int(cursor.fetchone()[0])

            return IndustrialCacheCounts(
                source_profiles=source_profiles,
                sync_runs=sync_runs,
                records=records,
                record_values=record_values,
                join_rules=join_rules,
                link_candidates=link_candidates,
            )

        return run_transaction_with_retry(self.database, _counts, connection=self.connection)
