"""SQLite schema helpers for characteristic alias lookups."""

from __future__ import annotations

import sqlite3

from modules.db import execute_with_retry
from modules.db import run_transaction_with_retry


CHARACTERISTIC_ALIAS_SCHEMA_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS CHARACTERISTIC_ALIASES (
            id INTEGER PRIMARY KEY,
            alias_name TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_value TEXT NULL,
            created_at TEXT NULL,
            updated_at TEXT NULL
        )''',
    'CREATE INDEX IF NOT EXISTS characteristic_alias_scope_lookup ON CHARACTERISTIC_ALIASES(alias_name, scope_type, scope_value)',
)


def ensure_characteristic_alias_table(cursor) -> None:
    """Create characteristic alias table/indexes in a migration-safe way."""
    for statement in CHARACTERISTIC_ALIAS_SCHEMA_STATEMENTS:
        cursor.execute(statement)


def ensure_characteristic_alias_schema(
    db_path: str,
    *,
    connection=None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> None:
    """Ensure characteristic alias schema exists for an existing or new database."""

    def operation(cursor) -> None:
        ensure_characteristic_alias_table(cursor)

    run_transaction_with_retry(
        db_path,
        operation,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


def normalize_alias_scope(scope_type: str, scope_value: str | None) -> tuple[str, str | None]:
    """Validate and normalize alias scope fields.

    Returns:
        ``(scope_type, scope_value)`` with canonical lowercase scope type.
        For ``global`` scope, ``scope_value`` is always ``None``.
    """
    normalized_scope_type = str(scope_type or '').strip().lower()
    if normalized_scope_type not in {'global', 'reference'}:
        raise ValueError('scope_type must be one of: global, reference')

    normalized_scope_value = str(scope_value or '').strip() or None
    if normalized_scope_type == 'reference' and not normalized_scope_value:
        raise ValueError('scope_value is required for reference scope')

    if normalized_scope_type == 'global':
        return normalized_scope_type, None

    return normalized_scope_type, normalized_scope_value


def fetch_characteristic_aliases(
    db_path: str,
    alias_name: str,
    *,
    reference: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, str | None]]:
    """Fetch aliases for one alias key with reference-first ordering."""
    normalized_alias_name = str(alias_name or '').strip()
    if not normalized_alias_name:
        raise ValueError('alias_name is required')

    query = '''
        SELECT alias_name, canonical_name, scope_type, scope_value
        FROM CHARACTERISTIC_ALIASES
        WHERE alias_name = ?
          AND (
            (scope_type = 'reference' AND scope_value = ?)
            OR scope_type = 'global'
          )
        ORDER BY
            CASE
                WHEN scope_type = 'reference' AND scope_value = ? THEN 0
                WHEN scope_type = 'global' THEN 1
                ELSE 2
            END,
            id ASC
    '''
    rows = execute_with_retry(
        db_path,
        query,
        params=(normalized_alias_name, reference, reference),
        connection=connection,
    )
    return [
        {
            'alias_name': row[0],
            'canonical_name': row[1],
            'scope_type': row[2],
            'scope_value': row[3],
        }
        for row in rows
    ]


def resolve_characteristic_alias(
    metric_name: str,
    reference: str | None,
    db_path: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> str:
    """Resolve metric name using reference->global alias priority.

    Priority:
      1) exact reference-scoped alias for current reference
      2) global alias
      3) original ``metric_name`` (fallback)
    """
    normalized_metric_name = str(metric_name or '').strip()
    if not normalized_metric_name:
        return str(metric_name or '')

    aliases = fetch_characteristic_aliases(
        db_path,
        normalized_metric_name,
        reference=reference,
        connection=connection,
    )
    if aliases:
        return str(aliases[0].get('canonical_name') or normalized_metric_name)
    return normalized_metric_name


def upsert_characteristic_alias(
    db_path: str,
    alias_name: str,
    canonical_name: str,
    scope_type: str,
    scope_value: str | None = None,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> None:
    """Create or update one alias row keyed by alias + normalized scope."""
    normalized_alias_name = str(alias_name or '').strip()
    if not normalized_alias_name:
        raise ValueError('alias_name is required')

    normalized_canonical_name = str(canonical_name or '').strip()
    if not normalized_canonical_name:
        raise ValueError('canonical_name is required')

    normalized_scope_type, normalized_scope_value = normalize_alias_scope(scope_type, scope_value)

    def operation(cursor) -> None:
        cursor.execute(
            '''
            SELECT id
            FROM CHARACTERISTIC_ALIASES
            WHERE alias_name = ? AND scope_type = ?
              AND (
                (scope_value IS NULL AND ? IS NULL)
                OR scope_value = ?
              )
            ORDER BY id ASC
            LIMIT 1
            ''',
            (
                normalized_alias_name,
                normalized_scope_type,
                normalized_scope_value,
                normalized_scope_value,
            ),
        )
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                '''
                INSERT INTO CHARACTERISTIC_ALIASES(alias_name, canonical_name, scope_type, scope_value)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    normalized_alias_name,
                    normalized_canonical_name,
                    normalized_scope_type,
                    normalized_scope_value,
                ),
            )
            return

        cursor.execute(
            '''
            UPDATE CHARACTERISTIC_ALIASES
            SET canonical_name = ?,
                scope_type = ?,
                scope_value = ?
            WHERE id = ?
            ''',
            (
                normalized_canonical_name,
                normalized_scope_type,
                normalized_scope_value,
                row[0],
            ),
        )

    run_transaction_with_retry(
        db_path,
        operation,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


def delete_characteristic_alias(
    db_path: str,
    alias_name: str,
    scope_type: str,
    scope_value: str | None = None,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> int:
    """Delete one alias row (or rows) by alias + normalized scope."""
    normalized_alias_name = str(alias_name or '').strip()
    if not normalized_alias_name:
        raise ValueError('alias_name is required')

    normalized_scope_type, normalized_scope_value = normalize_alias_scope(scope_type, scope_value)

    def operation(cursor) -> int:
        cursor.execute(
            '''
            DELETE FROM CHARACTERISTIC_ALIASES
            WHERE alias_name = ? AND scope_type = ?
              AND (
                (scope_value IS NULL AND ? IS NULL)
                OR scope_value = ?
              )
            ''',
            (
                normalized_alias_name,
                normalized_scope_type,
                normalized_scope_value,
                normalized_scope_value,
            ),
        )
        return int(cursor.rowcount or 0)

    return run_transaction_with_retry(
        db_path,
        operation,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
