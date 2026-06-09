"""Repository helpers for Metroliza industrial cache storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Iterable, Mapping

from metroliza.reports.db import run_transaction_with_retry
from metroliza.industrial.industrial_data_schema import SYNC_RUN_STATUSES, ensure_industrial_data_schema


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


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp suitable for SQLite text columns."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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

        def _upsert_rows(cursor) -> dict[str, int]:
            inserted = 0
            updated = 0
            value_rows = 0
            for row in rows:
                normalized = _normalize_row(row)
                record_key_raw = normalized.get("source_record_key")
                record_key = str(record_key_raw).strip() if record_key_raw is not None else ""
                if not record_key:
                    raise ValueError("each row must include source_record_key (or record_key alias)")

                cursor.execute(
                    """
                    SELECT id FROM industrial_records
                    WHERE source_profile_id = ? AND source_db_alias = ? AND source_record_key = ?
                    """,
                    (source_profile_id, source_db_alias, record_key),
                )
                existing = cursor.fetchone()
                is_insert = existing is None
                if is_insert:
                    inserted += 1
                else:
                    updated += 1

                raw_record = normalized.get("raw_record", dict(row))
                redacted_raw_record = _redact_sensitive_payload(raw_record)
                cursor.execute(
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
                    (
                        source_profile_id,
                        sync_run_id,
                        source_db_alias,
                        record_key,
                        normalized.get("process_timestamp"),
                        normalized.get("reference"),
                        normalized.get("part_number"),
                        normalized.get("part_name"),
                        normalized.get("revision"),
                        normalized.get("serial"),
                        normalized.get("batch_lot"),
                        normalized.get("work_order"),
                        normalized.get("station"),
                        normalized.get("line"),
                        normalized.get("operator_name"),
                        normalized.get("process_status"),
                        _to_json(redacted_raw_record) or "{}",
                        now,
                        now,
                    ),
                )
                cursor.execute(
                    """
                    SELECT id FROM industrial_records
                    WHERE source_profile_id = ? AND source_db_alias = ? AND source_record_key = ?
                    """,
                    (source_profile_id, source_db_alias, record_key),
                )
                record_row = cursor.fetchone()
                assert record_row is not None
                record_id = int(record_row[0])

                dynamic_items = [
                    (field_name, field_value)
                    for field_name, field_value in normalized.items()
                    if field_name not in KNOWN_RECORD_FIELDS and not _looks_sensitive_key(field_name)
                ]
                cursor.execute(
                    "DELETE FROM industrial_record_values WHERE record_id = ?",
                    (record_id,),
                )

                for field_name, field_value in dynamic_items:
                    if isinstance(field_value, (dict, list, tuple)):
                        value_text = None
                        value_json = _to_json(_redact_sensitive_payload(field_value))
                    elif field_value is None:
                        value_text = None
                        value_json = None
                    else:
                        value_text = str(field_value)
                        value_json = None
                    cursor.execute(
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
                        (record_id, field_name, value_text, value_json, now),
                    )
                    value_rows += 1

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
