"""SQLite schema helpers for characteristic alias lookups."""

from __future__ import annotations

import csv
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


def fetch_all_characteristic_aliases(
    db_path: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, str | None]]:
    """Fetch all alias mappings ordered for deterministic UI rendering."""
    query = '''
        SELECT alias_name, canonical_name, scope_type, scope_value
        FROM CHARACTERISTIC_ALIASES
        ORDER BY alias_name COLLATE NOCASE ASC,
                 scope_type ASC,
                 scope_value COLLATE NOCASE ASC,
                 id ASC
    '''
    rows = execute_with_retry(
        db_path,
        query,
        params=(),
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

    try:
        aliases = fetch_characteristic_aliases(
            db_path,
            normalized_metric_name,
            reference=reference,
            connection=connection,
        )
    except sqlite3.OperationalError as exc:
        if 'no such table: CHARACTERISTIC_ALIASES' in str(exc):
            return normalized_metric_name
        raise

    if aliases:
        return str(aliases[0].get('canonical_name') or normalized_metric_name)
    return normalized_metric_name


def _normalize_alias_mapping_payload(payload: dict[str, str | None], *, row_number: int | None = None) -> dict[str, str | None]:
    """Validate and normalize one mapping payload for batch workflows."""
    alias_name = str(payload.get('alias_name') or '').strip()
    canonical_name = str(payload.get('canonical_name') or '').strip()
    scope_type = str(payload.get('scope_type') or '').strip().lower()
    scope_value = str(payload.get('scope_value') or '').strip() or None

    if not alias_name:
        suffix = f' at row {row_number}' if row_number is not None else ''
        raise ValueError(f'alias_name is required{suffix}')

    if not canonical_name:
        suffix = f' at row {row_number}' if row_number is not None else ''
        raise ValueError(f'canonical_name is required{suffix}')

    try:
        normalized_scope_type, normalized_scope_value = normalize_alias_scope(scope_type, scope_value)
    except ValueError as exc:
        suffix = f' at row {row_number}' if row_number is not None else ''
        raise ValueError(f'{exc}{suffix}') from exc

    return {
        'alias_name': alias_name,
        'canonical_name': canonical_name,
        'scope_type': normalized_scope_type,
        'scope_value': normalized_scope_value,
    }


def upsert_characteristic_aliases_bulk(
    db_path: str,
    mappings: list[dict[str, str | None]],
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> int:
    """Validate and upsert many alias mappings in one transaction."""
    normalized_rows = [
        _normalize_alias_mapping_payload(mapping, row_number=index + 1)
        for index, mapping in enumerate(mappings)
    ]
    if not normalized_rows:
        return 0

    def operation(cursor) -> int:
        ensure_characteristic_alias_table(cursor)
        for row in normalized_rows:
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
                    row['alias_name'],
                    row['scope_type'],
                    row['scope_value'],
                    row['scope_value'],
                ),
            )
            existing_row = cursor.fetchone()
            if existing_row is None:
                cursor.execute(
                    '''
                    INSERT INTO CHARACTERISTIC_ALIASES(alias_name, canonical_name, scope_type, scope_value)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (
                        row['alias_name'],
                        row['canonical_name'],
                        row['scope_type'],
                        row['scope_value'],
                    ),
                )
            else:
                cursor.execute(
                    '''
                    UPDATE CHARACTERISTIC_ALIASES
                    SET canonical_name = ?, scope_type = ?, scope_value = ?
                    WHERE id = ?
                    ''',
                    (
                        row['canonical_name'],
                        row['scope_type'],
                        row['scope_value'],
                        existing_row[0],
                    ),
                )
        return len(normalized_rows)

    return run_transaction_with_retry(
        db_path,
        operation,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


def export_characteristic_aliases_csv(
    db_path: str,
    destination_path: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> int:
    """Export all alias mappings to a CSV file."""
    rows = fetch_all_characteristic_aliases(db_path, connection=connection)
    with open(destination_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=['alias_name', 'canonical_name', 'scope_type', 'scope_value'],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    'alias_name': row.get('alias_name') or '',
                    'canonical_name': row.get('canonical_name') or '',
                    'scope_type': row.get('scope_type') or '',
                    'scope_value': row.get('scope_value') or '',
                }
            )
    return len(rows)


def import_characteristic_aliases_csv(
    db_path: str,
    source_path: str,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> int:
    """Import alias mappings from CSV and upsert them as a batch."""
    with open(source_path, newline='', encoding='utf-8') as csv_file:
        reader = csv.DictReader(csv_file)
        required_headers = {'alias_name', 'canonical_name', 'scope_type', 'scope_value'}
        headers = set(reader.fieldnames or [])
        if not required_headers.issubset(headers):
            missing = ', '.join(sorted(required_headers - headers))
            raise ValueError(f'CSV is missing required columns: {missing}')

        rows = [
            {
                'alias_name': row.get('alias_name'),
                'canonical_name': row.get('canonical_name'),
                'scope_type': row.get('scope_type'),
                'scope_value': row.get('scope_value'),
            }
            for row in reader
        ]

    return upsert_characteristic_aliases_bulk(
        db_path,
        rows,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


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
