"""SQLite schema helpers for characteristic alias lookups."""

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
    'CREATE INDEX IF NOT EXISTS idx_characteristic_alias_scope_lookup ON CHARACTERISTIC_ALIASES(alias_name, scope_type, scope_value)',
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

