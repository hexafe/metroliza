import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, TypeVar


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


@dataclass(frozen=True)
class QueryResult:
    """Pandas-free result contract for SQLite SELECT queries."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    @property
    def empty(self) -> bool:
        return not self.rows

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def column(self, name: str) -> tuple[Any, ...]:
        try:
            index = self.columns.index(name)
        except ValueError as exc:
            raise KeyError(name) from exc
        return tuple(row[index] for row in self.rows)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=False)) for row in self.rows]


@dataclass(frozen=True)
class QueryScope:
    """Reusable SQL scope that can be counted, materialized, or streamed."""

    sql: str
    params: tuple[Any, ...] | list[Any] | None = ()
    columns: tuple[str, ...] = ()
    row_count_sql: str | None = None
    row_count_params: tuple[Any, ...] | list[Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", _normalize_sql_params(self.params))
        if self.row_count_params is None:
            object.__setattr__(self, "row_count_params", self.params)
        else:
            object.__setattr__(self, "row_count_params", _normalize_sql_params(self.row_count_params))
        object.__setattr__(self, "columns", tuple(str(column) for column in self.columns))


@dataclass(frozen=True)
class RowBatch:
    """One streamed SQL result batch with stable columns and source offset."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    batch_index: int
    offset: int

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=False)) for row in self.rows]


def _is_transient_sqlite_error(exc: sqlite3.OperationalError) -> bool:
    """Return True when the sqlite OperationalError message indicates a retryable lock/open issue."""
    message = str(exc).lower()
    return any(token in message for token in TRANSIENT_SQLITE_ERRORS)


def _normalize_sql_params(params: tuple[Any, ...] | list[Any] | None) -> tuple[Any, ...]:
    if params is None:
        return ()
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    raise ValueError('params must be a tuple or list when provided')


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
    attempts = retries + 1

    for attempt in range(attempts):
        owns_connection = connection is None
        try:
            normalized_params: tuple[Any, ...]
            if params is None:
                normalized_params = ()
            elif isinstance(params, tuple):
                normalized_params = params
            else:
                raise ValueError('params must be a tuple when provided')

            if owns_connection:
                with sqlite_connection_scope(db_path) as conn:
                    with closing(conn.cursor()) as cursor:
                        cursor.execute(query, normalized_params)
                        rows = cursor.fetchall()
                    conn.commit()
                    return rows

            with closing(connection.cursor()) as cursor:
                cursor.execute(query, normalized_params)
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


def quote_identifier(value: str) -> str:
    """Return a safely quoted SQLite identifier."""
    return '"' + str(value).replace('"', '""') + '"'


def chunked_values(values, chunk_size: int = 900):
    """Yield tuple chunks sized for SQLite parameter limits."""
    size = max(1, int(chunk_size))
    chunk: list[Any] = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            yield tuple(chunk)
            chunk.clear()
    if chunk:
        yield tuple(chunk)


def read_sql_dataframe(
    db_path: str,
    query: str,
    params: tuple[Any, ...] | list[Any] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> Any:
    """Read a SQL query into a legacy DataFrame while callers migrate to rows."""
    try:
        import importlib

        pd = importlib.import_module("pandas")
    except ImportError as exc:  # pragma: no cover - clean runtime should use read_sql_query_result.
        raise RuntimeError(
            "read_sql_dataframe is a legacy migration shim and requires pandas; "
            "runtime code should use read_sql_query_result instead."
        ) from exc

    result = read_sql_query_result(
        db_path,
        query,
        params=params,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
    return pd.DataFrame(result.rows, columns=result.columns)


def read_sql_query_result(
    db_path: str,
    query: str,
    params: tuple[Any, ...] | list[Any] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> QueryResult:
    """Read a SQL query into a row/column result with transient retry handling."""
    attempts = retries + 1
    normalized_params = _normalize_sql_params(params)

    for attempt in range(attempts):
        try:
            if connection is None:
                with sqlite_connection_scope(db_path) as conn:
                    return _fetch_query_result(conn, query, normalized_params)
            return _fetch_query_result(connection, query, normalized_params)
        except sqlite3.OperationalError as exc:
            if not _is_transient_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)

    return QueryResult(columns=(), rows=())


def _fetch_query_result(
    connection: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...],
) -> QueryResult:
    with closing(connection.cursor()) as cursor:
        cursor.execute(query, params)
        rows = tuple(cursor.fetchall())
        columns = tuple(description[0] for description in (cursor.description or ()))
    return QueryResult(columns=columns, rows=rows)


def read_query_scope_result(
    db_path: str,
    scope: QueryScope,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> QueryResult:
    """Read a reusable ``QueryScope`` into a row/column result."""

    return read_sql_query_result(
        db_path,
        scope.sql,
        params=scope.params,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )


def count_query_scope_rows(
    db_path: str,
    scope: QueryScope,
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> int:
    """Return the row count for a scope without materializing scope rows."""

    count_sql = scope.row_count_sql or f"SELECT COUNT(*) FROM ({scope.sql}) AS scoped_rows"
    count_params = scope.row_count_params if scope.row_count_sql else scope.params
    rows = execute_with_retry(
        db_path,
        count_sql,
        params=count_params,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
    return int(rows[0][0] or 0) if rows else 0


def iter_sql_query_batches(
    db_path: str,
    query: str,
    params: tuple[Any, ...] | list[Any] | None = None,
    *,
    batch_size: int = 1000,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> Iterator[RowBatch]:
    """Stream SELECT rows in bounded batches without building a full result list."""

    normalized_params = _normalize_sql_params(params)
    safe_batch_size = max(1, int(batch_size))
    attempts = retries + 1
    yielded = False

    def _batches(conn: sqlite3.Connection) -> Iterator[RowBatch]:
        nonlocal yielded
        with closing(conn.cursor()) as cursor:
            cursor.execute(query, normalized_params)
            columns = tuple(description[0] for description in (cursor.description or ()))
            offset = 0
            batch_index = 0
            while True:
                rows = tuple(cursor.fetchmany(safe_batch_size))
                if not rows:
                    return
                yielded = True
                yield RowBatch(
                    columns=columns,
                    rows=rows,
                    batch_index=batch_index,
                    offset=offset,
                )
                offset += len(rows)
                batch_index += 1

    for attempt in range(attempts):
        try:
            if connection is None:
                with sqlite_connection_scope(db_path) as conn:
                    yield from _batches(conn)
            else:
                yield from _batches(connection)
            return
        except sqlite3.OperationalError as exc:
            if yielded or not _is_transient_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)


def iter_query_scope_batches(
    db_path: str,
    scope: QueryScope,
    *,
    batch_size: int = 1000,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
) -> Iterator[RowBatch]:
    """Stream a ``QueryScope`` in bounded row batches."""

    yield from iter_sql_query_batches(
        db_path,
        scope.sql,
        params=scope.params,
        batch_size=batch_size,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
