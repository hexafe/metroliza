import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, TypeVar

import pandas as pd


TRANSIENT_SQLITE_ERRORS = (
    'database is locked',
    'database schema is locked',
    'unable to open database file',
)

T = TypeVar('T')


@dataclass(frozen=True)
class SQLitePragmaConfig:
    """SQLite PRAGMA defaults applied deterministically for each new app connection."""

    synchronous: str = 'NORMAL'
    cache_size: int | None = None
    mmap_size: int | None = None


DEFAULT_PRAGMA_CONFIG = SQLitePragmaConfig(synchronous='NORMAL')


def _is_transient_sqlite_error(exc: sqlite3.OperationalError) -> bool:
    """Return True when the sqlite OperationalError message indicates a retryable lock/open issue."""
    message = str(exc).lower()
    return any(token in message for token in TRANSIENT_SQLITE_ERRORS)


def _apply_sqlite_pragmas(conn: sqlite3.Connection, pragma_config: SQLitePragmaConfig) -> None:
    """Apply deterministic PRAGMAs for predictable runtime behavior across all call sites."""
    with closing(conn.cursor()) as cursor:
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute(f'PRAGMA synchronous={pragma_config.synchronous}')
        cursor.execute('PRAGMA temp_store=MEMORY')
        cursor.execute('PRAGMA foreign_keys=ON')
        if pragma_config.cache_size is not None:
            cursor.execute(f'PRAGMA cache_size={int(pragma_config.cache_size)}')
        if pragma_config.mmap_size is not None:
            cursor.execute(f'PRAGMA mmap_size={int(pragma_config.mmap_size)}')


def connect_sqlite(
    db_path: str,
    timeout_s: float = 5.0,
    *,
    pragma_config: SQLitePragmaConfig = DEFAULT_PRAGMA_CONFIG,
) -> sqlite3.Connection:
    """Create a SQLite connection and apply deterministic PRAGMAs on open."""
    connection = sqlite3.connect(db_path, timeout=timeout_s)
    _apply_sqlite_pragmas(connection, pragma_config)
    return connection


@contextmanager
def sqlite_connection_scope(
    db_path: str,
    *,
    timeout_s: float = 5.0,
    pragma_config: SQLitePragmaConfig = DEFAULT_PRAGMA_CONFIG,
) -> Iterator[sqlite3.Connection]:
    """Yield a managed SQLite connection suitable for multi-query workflows."""
    if pragma_config == DEFAULT_PRAGMA_CONFIG:
        with closing(connect_sqlite(db_path, timeout_s=timeout_s)) as conn:
            yield conn
        return

    with closing(connect_sqlite(db_path, timeout_s=timeout_s, pragma_config=pragma_config)) as conn:
        yield conn


def execute_with_retry(
    db_path: str,
    query: str,
    params: tuple[Any, ...] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> list[tuple[Any, ...]]:
    """Execute a query and return rows with a small retry policy for transient SQLite errors."""
    params = params or ()
    attempts = retries + 1

    for attempt in range(attempts):
        owns_connection = connection is None
        try:
            if owns_connection:
                with sqlite_connection_scope(db_path) as conn:
                    with closing(conn.cursor()) as cursor:
                        cursor.execute(query, params)
                        rows = cursor.fetchall()
                    conn.commit()
                    return rows

            with closing(connection.cursor()) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
            connection.commit()
            return rows
        except sqlite3.OperationalError as exc:
            if connection is not None:
                connection.rollback()
            if not _is_transient_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)
        except Exception:
            if connection is not None:
                connection.rollback()
            raise

    return []


def execute_select_with_columns(
    db_path: str,
    query: str,
    params: tuple[Any, ...] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> tuple[list[tuple[Any, ...]], list[str]]:
    """Execute a SELECT query and return rows with column names."""
    params = params or ()
    attempts = retries + 1

    for attempt in range(attempts):
        try:
            if connection is None:
                with sqlite_connection_scope(db_path) as conn:
                    with closing(conn.cursor()) as cursor:
                        cursor.execute(query, params)
                        rows = cursor.fetchall()
                        column_names = [description[0] for description in (cursor.description or [])]
                    return rows, column_names

            with closing(connection.cursor()) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                column_names = [description[0] for description in (cursor.description or [])]
            return rows, column_names
        except sqlite3.OperationalError as exc:
            if not _is_transient_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)

    return [], []



def execute_many_with_retry(
    db_path: str,
    statements: list[tuple[str, tuple[Any, ...]]],
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> None:
    """Execute many write statements in a single transaction with retry on transient SQLite errors."""

    def operation(cursor: sqlite3.Cursor) -> None:
        for query, params in statements:
            cursor.execute(query, params)

    run_transaction_with_retry(
        db_path,
        operation,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


def run_transaction_with_retry(
    db_path: str,
    operation: Callable[[sqlite3.Cursor], T],
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> T:
    """Run a cursor operation in a transaction with retry on transient SQLite errors."""
    attempts = retries + 1

    for attempt in range(attempts):
        conn: sqlite3.Connection | None = connection
        cursor: sqlite3.Cursor | None = None
        owns_connection = connection is None
        try:
            if conn is None:
                conn = connect_sqlite(db_path)
            cursor = conn.cursor()
            result = operation(cursor)
            conn.commit()
            return result
        except sqlite3.OperationalError as exc:
            if conn is not None:
                conn.rollback()
            if not _is_transient_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)
        except Exception:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if owns_connection and conn is not None:
                conn.close()

    raise sqlite3.OperationalError('Failed to complete SQLite transaction after retries')


def read_sql_dataframe(
    db_path: str,
    query: str,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> pd.DataFrame:
    """Read a SQL query into a DataFrame using managed SQLite connection(s) with transient retry handling."""
    attempts = retries + 1

    for attempt in range(attempts):
        try:
            if connection is None:
                with sqlite_connection_scope(db_path) as conn:
                    return pd.read_sql_query(query, conn)
            return pd.read_sql_query(query, connection)
        except sqlite3.OperationalError as exc:
            if not _is_transient_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)

    return pd.DataFrame()
