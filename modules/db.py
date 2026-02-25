import sqlite3
import time
from contextlib import closing
from typing import Any, Callable, TypeVar

import pandas as pd


TRANSIENT_SQLITE_ERRORS = (
    'database is locked',
    'database schema is locked',
    'unable to open database file',
)

T = TypeVar('T')


def connect_sqlite(db_path: str, timeout_s: float = 5.0) -> sqlite3.Connection:
    """Create a SQLite connection with common defaults for the app."""
    return sqlite3.connect(db_path, timeout=timeout_s)


def execute_with_retry(
    db_path: str,
    query: str,
    params: tuple[Any, ...] | None = None,
    *,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> list[tuple[Any, ...]]:
    """Execute a query and return rows with a small retry policy for transient SQLite errors."""
    params = params or ()
    attempts = retries + 1

    for attempt in range(attempts):
        try:
            with closing(connect_sqlite(db_path)) as conn:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                conn.commit()
                return rows
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            is_transient = any(token in message for token in TRANSIENT_SQLITE_ERRORS)
            if not is_transient or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)

    return []


def execute_select_with_columns(
    db_path: str,
    query: str,
    params: tuple[Any, ...] | None = None,
    *,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> tuple[list[tuple[Any, ...]], list[str]]:
    """Execute a SELECT query and return rows with column names."""
    params = params or ()
    attempts = retries + 1

    for attempt in range(attempts):
        try:
            with closing(connect_sqlite(db_path)) as conn:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    column_names = [description[0] for description in (cursor.description or [])]
                return rows, column_names
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            is_transient = any(token in message for token in TRANSIENT_SQLITE_ERRORS)
            if not is_transient or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)

    return [], []



def execute_many_with_retry(
    db_path: str,
    statements: list[tuple[str, tuple[Any, ...]]],
    *,
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
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


def run_transaction_with_retry(
    db_path: str,
    operation: Callable[[sqlite3.Cursor], T],
    *,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> T:
    """Run a cursor operation in a transaction with retry on transient SQLite errors."""
    attempts = retries + 1

    for attempt in range(attempts):
        conn: sqlite3.Connection | None = None
        cursor: sqlite3.Cursor | None = None
        try:
            conn = connect_sqlite(db_path)
            cursor = conn.cursor()
            result = operation(cursor)
            conn.commit()
            return result
        except sqlite3.OperationalError as exc:
            if conn is not None:
                conn.rollback()

            message = str(exc).lower()
            is_transient = any(token in message for token in TRANSIENT_SQLITE_ERRORS)
            if not is_transient or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)
        except Exception:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    raise sqlite3.OperationalError('Failed to complete SQLite transaction after retries')


def read_sql_dataframe(db_path: str, query: str) -> pd.DataFrame:
    """Read a SQL query into a DataFrame using a managed SQLite connection."""
    with closing(connect_sqlite(db_path)) as conn:
        return pd.read_sql_query(query, conn)
