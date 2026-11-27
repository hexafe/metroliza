import logging
import sqlite3
import stat
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from os import fstat
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, TypeVar
from urllib.parse import quote

from metroliza.reports.import_persist_profile import (
    close_persist_connection,
    measure_persist_stage,
    observe_persist_connection,
    observe_persist_checkpoint,
    persist_sqlite_options,
)
from metroliza.shared.sqlite_paths import sqlite_sidecar_path_problem


TRANSIENT_SQLITE_ERRORS = (
    'database is locked',
    'database schema is locked',
    'unable to open database file',
)

T = TypeVar('T')
logger = logging.getLogger(__name__)


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


class _SQLiteJournalNameError(sqlite3.OperationalError):
    """SQLite could not open a database and the journal path exceeds a filesystem limit."""


def _is_transient_sqlite_error(exc: sqlite3.OperationalError) -> bool:
    """Return True when the sqlite OperationalError message indicates a retryable lock/open issue."""
    return not isinstance(exc, _SQLiteJournalNameError) and any(
        token in str(exc).lower() for token in TRANSIENT_SQLITE_ERRORS
    )


def _normalize_sql_params(params: tuple[Any, ...] | list[Any] | None) -> tuple[Any, ...]:
    if params is None:
        return ()
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    raise ValueError('params must be a tuple or list when provided')


def _apply_sqlite_pragmas(
    conn: sqlite3.Connection, pragma_config: SQLitePragmaConfig, *, initialize_wal: bool = True,
    database_path: Path | None = None,
) -> None:
    """Apply deterministic PRAGMAs for predictable runtime behavior across all call sites."""
    with closing(conn.cursor()) as cursor:
        if initialize_wal:
            with _explain_sqlite_write_open_error(database_path):
                cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute(f'PRAGMA synchronous={pragma_config.synchronous}')
        cursor.execute('PRAGMA temp_store=MEMORY')
        cursor.execute('PRAGMA foreign_keys=ON')
        if pragma_config.cache_size is not None:
            cursor.execute(f'PRAGMA cache_size={int(pragma_config.cache_size)}')
        if pragma_config.mmap_size is not None:
            cursor.execute(f'PRAGMA mmap_size={int(pragma_config.mmap_size)}')


class _ManagedSQLiteConnection(sqlite3.Connection):
    """A connection that can retain the file identity observed at open time."""


def _managed_connect_options():
    options = persist_sqlite_options()
    options.setdefault("factory", _ManagedSQLiteConnection)
    return options


def _validate_new_database_name(path: Path) -> None:
    if problem := sqlite_sidecar_path_problem(path):
        raise sqlite3.OperationalError(problem)


@contextmanager
def _explain_sqlite_write_open_error(path: Path | None):
    try:
        yield
    except sqlite3.OperationalError as exc:
        error_code = getattr(exc, "sqlite_errorcode", 0)
        if path is not None and error_code & 0xff in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_IOERR):
            if problem := sqlite_sidecar_path_problem(path):
                raise _SQLiteJournalNameError(f"{exc}. Path check: {problem}") from exc
        raise


def connect_sqlite(
    db_path: str,
    timeout_s: float = 5.0,
    *,
    pragma_config: SQLitePragmaConfig = DEFAULT_PRAGMA_CONFIG,
    initialize_wal: bool = True,
    existing_identity: tuple[int, int] | None = None,
) -> sqlite3.Connection:
    """Create a SQLite connection and apply deterministic PRAGMAs on open."""
    path = None if str(db_path) == ":memory:" else Path(db_path).resolve()
    with measure_persist_stage("connection_open"):
        before = sqlite_file_identity(path) if path is not None else None
        if existing_identity is not None:
            _require_database_identity(path, existing_identity, include_empty=True)
        if existing_identity is None:
            if path is not None and before is None and not path.exists():
                _validate_new_database_name(path)
            connection = sqlite3.connect(db_path, timeout=timeout_s, **_managed_connect_options())
        else:
            uri = f"file:{quote(str(Path(db_path).absolute()))}?mode=rw"
            connection = sqlite3.connect(uri, uri=True, timeout=timeout_s, **_managed_connect_options())
        try:
            if existing_identity is not None:
                _require_database_identity(path, existing_identity, include_empty=True)
            _apply_sqlite_pragmas(connection, pragma_config, initialize_wal=initialize_wal, database_path=path)
            # WAL setup initializes the header when this handle creates the file.
            opened = sqlite_file_identity(path) if path is not None else None
            if (
                path is not None
                and opened is not None
                and (before is None or before == opened)
                and Path(db_path).resolve() == path
            ):
                connection._metroliza_opened_database = path, opened
        except BaseException:
            connection.close()
            raise
    observe_persist_connection(connection)
    return connection


def sqlite_file_identity(db_path: str | Path, *, include_empty=False) -> tuple[int, int] | None:
    """Identity of an existing regular database entry, without following a new alias."""
    try:
        info = Path(db_path).lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or (info.st_size == 0 and not include_empty):
        return None
    return info.st_dev, info.st_ino


class DatabaseSourceChanged(sqlite3.OperationalError):
    """The selected filename no longer identifies the file originally accepted."""


@dataclass(frozen=True)
class SQLiteFileBinding:
    """Bind a file chooser result to its resolved path and filesystem identity."""

    path: Path
    identity: tuple[int, int] | None

    @classmethod
    def capture(cls, db_path: str | Path):
        path = Path(db_path).expanduser().resolve()
        identity = sqlite_file_identity(path, include_empty=True)
        if identity is None and path.exists():
            raise ValueError("Choose a regular SQLite database file.")
        return cls(path, identity)

    def require(self, db_path: str | Path) -> None:
        """Fail before acting on a different or newly created filesystem entry."""
        if Path(db_path).expanduser().resolve() != self.path:
            raise DatabaseSourceChanged("The selected database was replaced or removed.")
        _require_database_identity(self.path, self.identity, include_empty=True)


@dataclass(frozen=True)
class _CreatedReportDatabase:
    """Keep the exclusive creation inode alive until its owner accepts the file."""

    binding: SQLiteFileBinding
    _stream: BinaryIO

    def require(self, db_path):
        if self._stream.closed:
            raise DatabaseSourceChanged("The database creation proof is no longer available.")
        self.binding.require(db_path)

    def close(self):
        self._stream.close()


def _reserve_selected_report_database(db_path, binding):
    binding.require(db_path)
    _validate_new_database_name(binding.path)
    try:
        stream = binding.path.open("xb")
    except FileExistsError as exc:
        raise DatabaseSourceChanged("The selected database path is no longer empty.") from exc
    try:
        info = fstat(stream.fileno())
        return _CreatedReportDatabase(SQLiteFileBinding(binding.path, (info.st_dev, info.st_ino)), stream)
    except BaseException:
        stream.close()
        raise


def _connect_selected_import_database(db_path, binding, *, initialize_wal):
    from metroliza.reports.report_schema import check_report_schema_version

    connection = connect_sqlite(db_path, initialize_wal=initialize_wal, existing_identity=binding.identity)
    try:
        binding.require(db_path)
        check_report_schema_version(connection, opening=True)
        connection._metroliza_opened_database = binding.path, binding.identity
    except BaseException:
        connection.close()
        raise
    return connection


def _require_database_identity(db_path, identity, *, include_empty=False) -> None:
    if sqlite_file_identity(db_path, include_empty=include_empty) != identity:
        raise DatabaseSourceChanged("The selected database was replaced or removed.")


def report_recovery_source(connection, db_path: str) -> Path:
    """Find the sibling directory for a historical connection with a known file identity."""
    opened = getattr(connection, "_metroliza_opened_database", None)
    if opened is None:
        raise ValueError("Reopen the Reports database in Metroliza before upgrading its schema.")
    path, identity = opened
    if Path(db_path).resolve() != path:
        raise sqlite3.OperationalError("The selected database was replaced or removed.")
    _require_database_identity(path, identity)
    return path


def _require_existing_report_schema(connection) -> None:
    from metroliza.reports.report_schema import is_report_schema_ready_cached

    if not is_report_schema_ready_cached(connection):
        raise sqlite3.OperationalError("The selected database does not have the current Reports schema.")


def _connect_existing_report_database(db_path, identity):
    _require_database_identity(db_path, identity)
    database_uri = f"file:{quote(str(Path(db_path).absolute()))}?mode=rw"
    with measure_persist_stage("connection_open"), _explain_sqlite_write_open_error(Path(db_path)):
        connection = sqlite3.connect(database_uri, uri=True, timeout=5.0, **_managed_connect_options())
        try:
            _require_database_identity(db_path, identity)
            _require_existing_report_schema(connection)
            _apply_sqlite_pragmas(connection, DEFAULT_PRAGMA_CONFIG)
            connection._metroliza_opened_database = Path(db_path).resolve(), identity
        except BaseException:
            connection.close()
            raise
    observe_persist_connection(connection)
    return connection


@contextmanager
def sqlite_connection_scope(
    db_path: str,
    *,
    timeout_s: float = 5.0,
    pragma_config: SQLitePragmaConfig = DEFAULT_PRAGMA_CONFIG,
    initialize_wal: bool = True,
    existing_identity: tuple[int, int] | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a managed SQLite connection suitable for multi-query workflows."""
    conn = (
        connect_sqlite(db_path, timeout_s=timeout_s)
        if pragma_config == DEFAULT_PRAGMA_CONFIG and initialize_wal and existing_identity is None
        else connect_sqlite(
            db_path, timeout_s=timeout_s, pragma_config=pragma_config,
            initialize_wal=initialize_wal, existing_identity=existing_identity,
        )
    )
    try:
        yield conn
    finally:
        close_persist_connection(conn)


def _preflight_report_schema_write(db_path: str) -> tuple[tuple[int, int] | None, bool]:
    from metroliza.reports.report_schema import check_report_schema_version

    if str(db_path) == ":memory:":
        return None, False
    path = Path(db_path).resolve()
    if not path.is_file():
        return None, False
    identity = sqlite_file_identity(path)
    with sqlite_readonly_connection_scope(db_path, resolve_path=False) as connection:
        historical = check_report_schema_version(connection, before_in_place_upgrade=True)
    if identity is not None:
        _require_database_identity(path, identity)
    return identity, historical


@contextmanager
def sqlite_report_schema_connection_scope(db_path: str):
    """Preserve the journal mode of an older Reports file during admission."""
    identity, historical = _preflight_report_schema_write(db_path)
    with sqlite_connection_scope(
        db_path, initialize_wal=not historical, existing_identity=identity,
    ) as connection:
        yield connection


@contextmanager
def sqlite_selected_reports_connection_scope(db_path: str, binding: SQLiteFileBinding | None):
    """Open a selected Reports file, or defer connection ownership for a standalone consumer."""
    if binding is None:
        yield None
        return

    if binding.identity is None:
        raise DatabaseSourceChanged("The selected Reports database has not been created yet.")

    from metroliza.reports.report_schema import check_report_schema_version

    binding.require(db_path)
    with sqlite_readonly_connection_scope(db_path, resolve_path=False) as reader:
        check_report_schema_version(reader, opening=True)
    binding.require(db_path)
    with sqlite_connection_scope(
        db_path, initialize_wal=False, existing_identity=binding.identity,
    ) as connection:
        binding.require(db_path)
        check_report_schema_version(connection, opening=True)
        yield connection


# Import checkpoint cadence (PO decision 2026-10-18, #1136). A WAL checkpoint syncs the
# database file; doing it after every report cost ~125 ms per report on Windows (about
# 90 % of import persist time). A passive checkpoint runs after a commit once
# IMPORT_CHECKPOINT_COMMITS commits or IMPORT_CHECKPOINT_SECONDS have passed since the last
# one, when import persistence completes, and when the import connection closes (also on
# cancellation). The cadence is commit-triggered: on a sudden power loss only the reports
# committed since the last checkpoint can be lost, the database stays consistent, and
# re-running the import adds them because present reports are skipped. An application
# crash loses nothing that was committed.
IMPORT_CHECKPOINT_SECONDS = 2.0
IMPORT_CHECKPOINT_COMMITS = 25


class _LazySQLiteConnection:
    """Owner-thread connection handle that creates no DB before first SQL use."""

    def __init__(self, db_path, *, clock=time.monotonic, existing_identity=None, selected_database=None):
        self._db_path = db_path
        self._existing_identity = existing_identity
        self._selected_database = selected_database
        self.created_database: _CreatedReportDatabase | None = None
        self._connection = None
        self.opened_database: tuple[Path, tuple[int, int]] | None = None
        self._clock = clock
        self._last_checkpoint = clock()
        self._commits_since_checkpoint = 0
        self._uncheckpointed = False

    def __getattr__(self, name):
        if name == "cursor":
            self._require_current_database()
        if self._connection is None:
            self._open()
        return getattr(self._connection, name)

    def _require_current_database(self):
        if self._selected_database is not None:
            self._selected_database.require(self._db_path)
        elif self._existing_identity is not None:
            _require_database_identity(self._db_path, self._existing_identity)

    def _open(self):
        if self._selected_database is not None:
            self._open_selected_database()
            return
        if self._existing_identity is not None:
            self._connection = _connect_existing_report_database(self._db_path, self._existing_identity)
            self.opened_database = Path(self._db_path).resolve(), self._existing_identity
            return
        path = Path(self._db_path).resolve()
        before = sqlite_file_identity(path)
        # An existing Reports file may require migration. Preserve its journal
        # mode so schema admission can choose a safe upgrade path.
        identity, historical = _preflight_report_schema_write(self._db_path)
        self._connection = connect_sqlite(
            self._db_path, initialize_wal=not historical, existing_identity=identity,
        )
        after = sqlite_file_identity(path)
        if after is not None and (before is None or before == after) and Path(self._db_path).resolve() == path:
            self.opened_database = path, after

    def _open_selected_database(self):
        binding = self._selected_database
        initialize_wal = binding.identity is None
        if initialize_wal:
            self.created_database = _reserve_selected_report_database(self._db_path, binding)
            binding = self._selected_database = self.created_database.binding
        binding.require(self._db_path)
        if self._existing_identity is not None:
            self._connection = _connect_existing_report_database(self._db_path, self._existing_identity)
        else:
            self._connection = _connect_selected_import_database(
                self._db_path, binding, initialize_wal=initialize_wal,
            )
        self.opened_database = binding.path, binding.identity

    def close(self):
        if self._connection is not None:
            # SQLite checkpoints on close only for the last connection to the database, so
            # sync the tail explicitly while a reader or another instance keeps it open.
            try:
                self.checkpoint_pending()
            finally:
                close_persist_connection(self._connection)

    def checkpoint_after_commit(self):
        # NORMAL commits do not sync the WAL; a checkpoint does. Bounded cadence, see
        # IMPORT_CHECKPOINT_SECONDS / IMPORT_CHECKPOINT_COMMITS above.
        self._uncheckpointed = True
        self._commits_since_checkpoint += 1
        if (self._commits_since_checkpoint < IMPORT_CHECKPOINT_COMMITS
                and self._clock() - self._last_checkpoint < IMPORT_CHECKPOINT_SECONDS):
            return
        self._checkpoint()

    def checkpoint_pending(self):
        """Checkpoint now when commits are not fully checkpointed (or the last attempt failed)."""
        if self._connection is not None and self._uncheckpointed:
            self._checkpoint()

    def _checkpoint(self):
        # PASSIVE respects readers/writers and never retries or opens a transaction. The
        # commit before it already succeeded, so a checkpoint error (for example a full disk
        # while the database file grows) is logged and never turns that report into a failure.
        # The cadence restarts either way; an attempt that raised, or that returned busy or
        # left WAL frames unsynced (a reader pinned them), stays pending, so the persistence
        # boundary and close retry it.
        self._commits_since_checkpoint = 0
        self._last_checkpoint = self._clock()
        try:
            with measure_persist_stage("checkpoint"):
                result = self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        except sqlite3.Error as exc:
            logger.warning("Import WAL checkpoint failed; committed reports are kept: %s", exc)
            return
        incomplete = bool(result) and bool(result[0] or result[2] < result[1])
        self._uncheckpointed = incomplete
        if incomplete:
            logger.debug("Import WAL checkpoint incomplete: busy=%s frames=%s checkpointed=%s",
                         *result)
        observe_persist_checkpoint(result)


@contextmanager
def lazy_sqlite_connection_scope(
    db_path: str, *, existing_identity: tuple[int, int] | None = None,
    selected_database: SQLiteFileBinding | None = None,
    on_created_database: Callable[[_CreatedReportDatabase], bool] | None = None,
):
    """Reuse the import connection and hand off any creation proof after SQLite closes."""
    if (selected_database is not None and existing_identity is not None
            and selected_database.identity != existing_identity):
        raise DatabaseSourceChanged("The import plan does not match the selected Reports database.")
    connection = _LazySQLiteConnection(
        db_path, existing_identity=existing_identity, selected_database=selected_database,
    )
    try:
        yield connection
    finally:
        try:
            connection.close()
        finally:
            created = connection.created_database
            connection.created_database = None
            if created is not None:
                retained = False
                try:
                    retained = on_created_database is not None and on_created_database(created)
                finally:
                    if not retained:
                        created.close()


def _checkpoint_import_connection(connection):
    if isinstance(connection, _LazySQLiteConnection):
        connection.checkpoint_after_commit()


def checkpoint_pending_import_commits(connection):
    """Sync committed import reports before a long phase that may not commit (enrichment)."""
    if isinstance(connection, _LazySQLiteConnection):
        connection.checkpoint_pending()


@contextmanager
def sqlite_readonly_connection_scope(
    db_path: str, *, immutable: bool = False, timeout_s: float = 5.0,
    existing_identity: tuple[int, int] | None = None,
    resolve_path: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Yield a managed read-only connection with a timeout and unchanged PRAGMAs.

    Use ``immutable`` only for a closed snapshot whose bytes cannot be modified
    by another connection for the entire scope. It disables SQLite locking and
    sidecar access; live databases must retain the default.
    """

    if existing_identity is not None:
        _require_database_identity(db_path, existing_identity)
    resolved_path = Path(db_path).resolve(strict=False) if resolve_path else Path(db_path).absolute()
    database_uri = f"file:{quote(str(resolved_path))}?mode=ro"
    if immutable:
        database_uri += "&immutable=1"
    with closing(sqlite3.connect(database_uri, uri=True, timeout=timeout_s, **persist_sqlite_options())) as connection:
        if existing_identity is not None:
            _require_database_identity(db_path, existing_identity)
            _require_existing_report_schema(connection)
        yield connection


def backup_sqlite_database(
    source_path: str, destination_path: str, *, source_binding: SQLiteFileBinding | None = None,
    progress=None,
) -> None:
    """Write and integrity-check a consistent SQLite backup at ``destination_path``."""

    if source_binding is not None:
        source_binding.require(source_path)
    with sqlite_readonly_connection_scope(source_path) as source_connection:
        if source_binding is not None:
            source_connection.execute("BEGIN DEFERRED")
            source_connection.execute("SELECT 1 FROM main.sqlite_schema LIMIT 1").fetchone()
            source_binding.require(source_path)
        backup_sqlite_connection(source_connection, destination_path, progress=progress)
    if source_binding is not None:
        source_binding.require(source_path)


def backup_sqlite_connection(source_connection, destination_path: str, *, progress=None) -> None:
    """Copy a connection's readable snapshot and verify SQLite integrity."""
    with closing(sqlite3.connect(destination_path)) as destination_connection:
        source_connection.backup(destination_connection, progress=progress)
        check_sqlite_integrity(destination_connection)


def check_sqlite_integrity(connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or str(integrity[0]).lower() != "ok":
        raise RuntimeError("SQLite backup failed integrity validation")


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


def _run_in_borrowed_transaction(connection, operation):
    if connection is None or not connection.in_transaction:
        raise ValueError("Joining a transaction requires an active borrowed connection")
    cursor = connection.cursor(**persist_sqlite_options(cursor=True))
    try:
        return operation(cursor)
    finally:
        cursor.close()


def run_transaction_with_retry(
    db_path: str,
    operation: Callable[[sqlite3.Cursor], T],
    *,
    connection: sqlite3.Connection | None = None,
    retries: int = 2,
    retry_delay_s: float = 0.05,
    join_transaction: bool = False,
) -> T:
    """Run a cursor operation in a transaction with transient-error retry.

    The default retains commit/rollback ownership even for a borrowed connection.
    ``join_transaction=True`` requires an active borrowed transaction and leaves
    commit, rollback and retry of the complete unit to its outer owner.
    """
    if join_transaction:
        # The outer owner retries the entire unit, and owns rollback/commit as well.
        return _run_in_borrowed_transaction(connection, operation)
    return _retry_transaction(db_path, operation, connection, retries, retry_delay_s)


def _retry_transaction(db_path, operation, connection, retries, retry_delay_s):
    attempts = retries + 1

    for attempt in range(attempts):
        conn: sqlite3.Connection | None = connection
        cursor: sqlite3.Cursor | None = None
        owns_connection = connection is None
        try:
            if conn is None:
                conn = connect_sqlite(db_path)
            cursor = conn.cursor(**persist_sqlite_options(cursor=True))
            result = operation(cursor)
            with measure_persist_stage("commit"):
                conn.commit()
        except sqlite3.OperationalError as exc:
            if conn is not None:
                conn.rollback()
            if not _is_transient_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(retry_delay_s)
            continue
        except Exception:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if owns_connection and conn is not None:
                close_persist_connection(conn)

        # Maintenance runs with the statement finalized and outside the retry
        # boundary: a checkpoint failure must never replay a committed write.
        _checkpoint_import_connection(conn)
        return result

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
    rows = read_sql_query_result(
        db_path,
        count_sql,
        params=count_params,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    ).rows
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
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[RowBatch]:
    """Stream SELECT rows in bounded batches, optionally cancelling owned SQL execution.

    Cancellation checks SQLite VM progress and lock waits, including connection PRAGMAs.
    Caller-owned connections retain their handlers and cannot opt into cancellation here.
    """

    if connection is not None and should_cancel is not None:
        raise ValueError("Cancellation requires an owned SQLite connection")
    normalized_params = _normalize_sql_params(params)
    safe_batch_size = max(1, int(batch_size))
    attempts = retries + 1
    yielded = False

    for attempt in range(attempts):
        try:
            with (
                _batch_connection_scope(db_path, should_cancel, connection) as conn,
                closing(_iter_cursor_batches(conn, query, normalized_params, safe_batch_size, should_cancel)) as batches,
            ):
                for batch in batches:
                    yielded = True
                    yield batch
            return
        except sqlite3.OperationalError as exc:
            if should_cancel is not None and should_cancel():
                return
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


@contextmanager
def sqlite_query_only_connection_scope(
    db_path: str, *, plain_path: bool = False, timeout_s: float = 5.0
) -> Iterator[sqlite3.Connection]:
    """Block SQL writes while allowing SQLite's normal WAL housekeeping on close.

    Open only an existing database, without initializing its journal mode.
    SQLite recovery/checkpoint and sidecar cleanup may still change files.
    ``plain_path`` supports UNC shares that SQLite URI authorities reject. In
    that mode check existence before opening, as a plain SQLite path can create
    a file. The default URI mode additionally enforces existence at open time.
    """

    if plain_path:
        if not Path(db_path).is_file():
            raise sqlite3.OperationalError("database does not exist")
        target = str(db_path)
    else:
        resolved_path = Path(db_path).resolve(strict=False)
        target = f"file:{quote(str(resolved_path))}?mode=rw"
    with closing(sqlite3.connect(
        target, uri=not plain_path, timeout=timeout_s, **persist_sqlite_options()
    )) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute("PRAGMA query_only=ON")
        yield connection


@contextmanager
def _batch_connection_scope(
    db_path: str,
    should_cancel: Callable[[], bool] | None,
    connection: sqlite3.Connection | None,
) -> Iterator[sqlite3.Connection]:
    """Keep normal connection defaults, with short busy waits for cancellable readers."""

    if connection is not None:
        yield connection
        return
    if should_cancel is None:
        with sqlite_connection_scope(db_path) as connection:
            yield connection
        return
    with closing(sqlite3.connect(db_path, timeout=0.05)) as connection:
        connection.set_progress_handler(should_cancel, 1000)
        _run_cancellable_sqlite(lambda: _apply_sqlite_pragmas(connection, DEFAULT_PRAGMA_CONFIG), should_cancel)
        yield connection


def _run_cancellable_sqlite(operation: Callable[[], T], should_cancel: Callable[[], bool] | None) -> T:
    """Retain a five-second lock allowance, polling cancellation between short busy waits."""

    if should_cancel is None:
        return operation()
    deadline = time.monotonic() + 5.0
    while True:
        if should_cancel():
            raise sqlite3.OperationalError("interrupted")
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if not _is_transient_sqlite_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _iter_cursor_batches(
    connection: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...],
    batch_size: int,
    should_cancel: Callable[[], bool] | None,
) -> Iterator[RowBatch]:
    """Own one cursor and keep row offsets stable across each bounded fetch."""

    with closing(connection.cursor()) as cursor:
        _run_cancellable_sqlite(lambda: cursor.execute(query, params), should_cancel)
        columns = tuple(description[0] for description in (cursor.description or ()))
        offset = 0
        batch_index = 0
        while True:
            if should_cancel is not None and should_cancel():
                return
            rows = tuple(cursor.fetchmany(batch_size))
            if not rows:
                return
            yield RowBatch(columns=columns, rows=rows, batch_index=batch_index, offset=offset)
            offset += len(rows)
            batch_index += 1



def selected_reports_worker_options(db_path, binding: SQLiteFileBinding | None) -> dict:
    """Pass connection ownership to the worker thread without carrying a live handle."""
    if binding is None:
        return {}
    return {"connection_scope": lambda: sqlite_selected_reports_connection_scope(db_path, binding)}
