"""Industrial-owned facade for the dependency-neutral SQLite schema implementation."""

from __future__ import annotations

from metroliza.industrial.realtime.timestamps import canonical_utc_timestamp
from metroliza.reports.db import run_transaction_with_retry, sqlite_connection_scope
from metroliza.storage.industrial_schema import (
    JOIN_MATCH_MODES,
    LINK_CANDIDATE_STATUSES,
    SCHEMA_INDEX_STATEMENTS,
    SCHEMA_TABLE_STATEMENTS,
    SCHEMA_VERSION,
    SYNC_RUN_STATUSES,
    TIMESTAMP_STORAGE_FORMAT,
    ensure_industrial_data_schema as _ensure_industrial_data_schema,
)


def ensure_industrial_data_schema(
    database: str,
    *,
    connection=None,
    retries: int = 4,
    retry_delay_s: float = 1,
) -> None:
    """Ensure industrial cache tables, indexes, and schema metadata exist."""

    _ensure_industrial_data_schema(
        database,
        transaction_runner=run_transaction_with_retry,
        connection_scope=sqlite_connection_scope,
        canonical_timestamp=canonical_utc_timestamp,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


__all__ = [
    "JOIN_MATCH_MODES",
    "LINK_CANDIDATE_STATUSES",
    "SCHEMA_INDEX_STATEMENTS",
    "SCHEMA_TABLE_STATEMENTS",
    "SCHEMA_VERSION",
    "SYNC_RUN_STATUSES",
    "TIMESTAMP_STORAGE_FORMAT",
    "ensure_industrial_data_schema",
]
