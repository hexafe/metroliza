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

CSV_ALIAS_HEADERS = ('alias_name', 'canonical_name', 'scope_type', 'scope_value')


class CharacteristicAliasImportValidationError(ValueError):
    """Raised when CSV import validation fails for one or more rows."""

    def __init__(
        self,
        row_errors: list[str],
        *,
        summary: str | None = None,
        row_error_details: list[dict[str, str | int | None]] | None = None,
        total_rows_processed: int = 0,
    ):
        self.row_errors = [str(error or '').strip() for error in (row_errors or []) if str(error or '').strip()]
        self.row_error_details = list(row_error_details or [])
        self.total_rows_processed = int(total_rows_processed or 0)
        self.invalid_rows = len(self.row_error_details) or len(self.row_errors)
        self.valid_rows = max(0, self.total_rows_processed - self.invalid_rows)
        if summary is None:
            summary = 'CSV import contains invalid mapping rows.'
        self.summary = str(summary)
        message_lines = [str(summary)]
        if self.row_errors:
            message_lines.extend(self.row_errors)
        super().__init__('\n'.join(message_lines))


def _build_validation_issue(
    *,
    row_number: int,
    field: str,
    code: str,
    category: str,
    remediation_hint: str,
    message: str,
) -> dict[str, str | int]:
    return {
        'row_number': row_number,
        'field': field,
        'code': code,
        'category': category,
        'remediation_hint': remediation_hint,
        'message': message,
    }


def _validate_alias_mapping_payload(
    payload: dict[str, str | None],
    *,
    row_number: int,
) -> tuple[dict[str, str | None] | None, list[dict[str, str | int]]]:
    """Validate/normalize one payload and return structured issues."""
    alias_name = str(payload.get('alias_name') or '').strip()
    canonical_name = str(payload.get('canonical_name') or '').strip()
    scope_type = str(payload.get('scope_type') or '').strip().lower()
    scope_value = str(payload.get('scope_value') or '').strip() or None

    issues: list[dict[str, str | int]] = []
    if not alias_name:
        issues.append(
            _build_validation_issue(
                row_number=row_number,
                field='alias_name',
                code='missing_alias_name',
                category='missing_required_field',
                remediation_hint='Provide a non-empty alias_name value.',
                message=f'alias_name is required at row {row_number}',
            )
        )

    if not canonical_name:
        issues.append(
            _build_validation_issue(
                row_number=row_number,
                field='canonical_name',
                code='missing_canonical_name',
                category='missing_required_field',
                remediation_hint='Provide the canonical_name to map this alias to.',
                message=f'canonical_name is required at row {row_number}',
            )
        )

    if scope_type not in {'global', 'reference'}:
        issues.append(
            _build_validation_issue(
                row_number=row_number,
                field='scope_type',
                code='invalid_scope_type',
                category='invalid_value',
                remediation_hint="Use scope_type 'global' or 'reference'.",
                message=f'scope_type must be one of: global, reference at row {row_number}',
            )
        )
    elif scope_type == 'reference' and not scope_value:
        issues.append(
            _build_validation_issue(
                row_number=row_number,
                field='scope_value',
                code='reference_scope_requires_scope_value',
                category='scope_requirements',
                remediation_hint='Set scope_value for reference-scoped aliases.',
                message=f'scope_value is required for reference scope at row {row_number}',
            )
        )

    if issues:
        return None, issues

    normalized_scope_type, normalized_scope_value = normalize_alias_scope(scope_type, scope_value)
    return (
        {
            'alias_name': alias_name,
            'canonical_name': canonical_name,
            'scope_type': normalized_scope_type,
            'scope_value': normalized_scope_value,
        },
        [],
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
        writer = csv.DictWriter(csv_file, fieldnames=list(CSV_ALIAS_HEADERS))
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


def _normalized_csv_headers(fieldnames: list[str] | None) -> list[str]:
    """Return normalized CSV headers suitable for dictionary lookups."""
    return [str(name or '').strip() for name in (fieldnames or [])]


def import_characteristic_aliases_csv(
    db_path: str,
    source_path: str,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> int:
    """Import alias mappings from CSV and upsert them as a batch."""
    with open(source_path, newline='', encoding='utf-8-sig') as csv_file:
        reader = csv.DictReader(csv_file)
        reader.fieldnames = _normalized_csv_headers(reader.fieldnames)

        required_headers = set(CSV_ALIAS_HEADERS)
        headers = set(reader.fieldnames or [])
        if not required_headers.issubset(headers):
            missing = ', '.join(sorted(required_headers - headers))
            raise ValueError(f'CSV is missing required columns: {missing}')

        rows = []
        row_error_details: list[dict[str, str | int | None]] = []
        seen_keys: dict[tuple[str, str, str | None], int] = {}
        for index, row in enumerate(reader, start=2):
            normalized_row = {str(key or '').strip(): value for key, value in row.items()}
            payload = {
                'alias_name': normalized_row.get('alias_name'),
                'canonical_name': normalized_row.get('canonical_name'),
                'scope_type': normalized_row.get('scope_type'),
                'scope_value': normalized_row.get('scope_value'),
            }
            normalized_payload, issues = _validate_alias_mapping_payload(payload, row_number=index)
            if issues:
                row_error_details.extend(issues)
                continue

            key = (
                str(normalized_payload.get('alias_name') or ''),
                str(normalized_payload.get('scope_type') or ''),
                normalized_payload.get('scope_value'),
            )
            existing_row_number = seen_keys.get(key)
            if existing_row_number is not None:
                alias_name, scope_type, scope_value = key
                scope_suffix = f'/{scope_value}' if scope_value else ''
                row_error_details.append(
                    _build_validation_issue(
                        row_number=index,
                        field='alias_name',
                        code='duplicate_key_collision',
                        category='duplicate_collision',
                        remediation_hint='Remove or merge duplicate alias rows with the same alias_name + scope.',
                        message=(
                            f'duplicate alias/scope key for "{alias_name}" ({scope_type}{scope_suffix}) '
                            f'at row {index}; first seen at row {existing_row_number}'
                        ),
                    )
                )
                continue

            seen_keys[key] = index
            rows.append(normalized_payload)

    if row_error_details:
        row_errors = [str(detail.get('message') or '').strip() for detail in row_error_details if detail.get('message')]
        raise CharacteristicAliasImportValidationError(
            row_errors,
            summary='CSV import failed validation. Fix the row issues below and retry.',
            row_error_details=row_error_details,
            total_rows_processed=(len(rows) + len({int(detail['row_number']) for detail in row_error_details})),
        )

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
