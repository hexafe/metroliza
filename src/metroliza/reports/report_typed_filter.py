"""Bind a report draft once for typed preview and workbook snapshot selection."""

from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from metroliza.reports.db import (
    QueryScope,
    count_query_scope_rows,
    quote_identifier,
    read_query_scope_result,
    sqlite_readonly_connection_scope,
)
from metroliza.reports.report_query_service import _MEASUREMENT_EXPORT_SELECT_FROM_VIEW
from metroliza.reports.report_schema import SCHEMA_VIEW_STATEMENTS, _normalized_schema_sql
from metroliza.shared.filter_state import FilterState, REPORT_FILTER_FIELDS, decode_filter_state, summarize_filter_state
from metroliza.shared.typed_filter import (
    FilterField,
    compile_typed_filter_sqlite,
    install_typed_filter_sqlite,
    parse_typed_filter,
)


REPORT_TYPED_FILTER_FIELDS = (
    FilterField("reference", "text", "Ref", "Reports"),
    FilterField("header", "text", "Dimension", "Reports"),
    FilterField("ax", "text", "Axis", "Reports"),
    FilterField("status_code", "text", "Status", "Reports"),
    FilterField("meas", "number", "Measurement", "Reports"),
    FilterField("report_date", "date", "Date", "Reports"),
)
REPORT_TYPED_FILTER_MODE_HINT = (
    "Typed filters require Whole database, Main plots and local XLSX without grouping, "
    "HTML, Google Sheets or industrial context."
)
_PREVIEW_LIMIT = 20
_PREVIEW_COLUMNS = ("MEASUREMENT_ID", "REFERENCE", "HEADER", "MEAS", "DATE")
_LIST_FIELDS = tuple(sorted(name for name in REPORT_FILTER_FIELDS if name.endswith("_values")))
_EXPRESSION_COLUMNS = {item.field_id: item.field_id for item in REPORT_TYPED_FILTER_FIELDS}
_EXPRESSION_COLUMNS["report_date"] = "DATE"
_MEASUREMENT_VIEW = "vw_measurement_export"
_SUPPORTED_MEASUREMENT_VIEW_SQL = frozenset(
    statement for statement in map(_normalized_schema_sql, SCHEMA_VIEW_STATEMENTS)
    if statement.startswith(f"create view {_MEASUREMENT_VIEW} ")
)


class ReportTypedViewError(ValueError):
    """The database does not expose the canonical typed Reports projection."""


def require_report_typed_view(connection) -> None:
    """Validate the main database projection in the same read as typed selection."""
    with closing(connection.execute(
        "SELECT sql FROM main.sqlite_schema WHERE type = 'view' AND name = ?", (_MEASUREMENT_VIEW,),
    )) as cursor:
        definition = cursor.fetchone()
    if not definition or not definition[0] or _normalized_schema_sql(definition[0]) not in _SUPPORTED_MEASUREMENT_VIEW_SQL:
        raise ReportTypedViewError(
            "Typed filters require the standard Reports measurement view. "
            "Restore an intact Reports database or import the source reports into a new database."
        )


@dataclass(frozen=True)
class ReportTypedFilterScope:
    database: Path
    stamp: tuple
    state: FilterState = field(repr=False)
    query: QueryScope = field(init=False, repr=False)

    def __post_init__(self) -> None:
        state = decode_filter_state(asdict(self.state))
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "query", _compile_report_typed_filter(state))

    def require_current_database(self, database) -> None:
        if Path(database).resolve() != self.database or _database_stamp(self.database) != self.stamp:
            raise ValueError("The report database changed. Preview the typed draft again.")

    def describe(self) -> str:
        _, details = summarize_filter_state(self.state)
        return f"Typed filter\n{details}"


@dataclass(frozen=True)
class ReportTypedFilterPreview:
    matching_count: int
    rows: tuple[tuple, ...]


def _file_stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _database_stamp(database):
    try:
        main = _file_stamp(database)
    except OSError as exc:
        raise ValueError("The report database is unavailable. Choose a database and preview again.") from exc
    try:
        wal = _file_stamp(database.with_name(database.name + "-wal"))
    except FileNotFoundError:
        wal = None
    except OSError as exc:
        raise ValueError("The report database changed or is unavailable. Preview the typed draft again.") from exc
    return main, wal if wal and wal[2] else None


def _list_predicates(state):
    clauses = []
    parameters = []
    for name in _LIST_FIELDS:
        values = tuple(value.strip() for value in getattr(state, name) if value.strip())
        if values:
            column = quote_identifier(name.removesuffix("_values"))
            markers = ", ".join("?" for _ in values)
            clauses.append(f"source.{column} IN ({markers})")
            parameters.extend(values)
    return clauses, parameters


def _append_date_predicates(state, clauses, parameters):
    first = date.fromisoformat(state.date_from[:10]) if state.date_from else None
    last = date.fromisoformat(state.date_to[:10]) if state.date_to else None
    if first and last and first > last:
        raise ValueError("From must be on or before To.")
    for operator, day in ((">=", first), ("<=", last)):
        if day is not None:
            clauses.append(f'source."DATE" {operator} ?')
            parameters.append(day.isoformat())


def _compile_report_typed_filter(state: FilterState) -> QueryScope:
    expression = parse_typed_filter(state.expression_text, REPORT_TYPED_FILTER_FIELDS)
    if expression is None:
        raise ValueError("Enter a typed report filter expression.")
    compiled = compile_typed_filter_sqlite(expression, _EXPRESSION_COLUMNS, table_alias="source")
    clauses, parameters = _list_predicates(state)
    _append_date_predicates(state, clauses, parameters)
    if state.has_nok_only:
        clauses.append('source."HAS_NOK" = 1')
    clauses.append(compiled.sql)
    parameters.extend(compiled.parameters)
    base = " ".join(("SELECT", _MEASUREMENT_EXPORT_SELECT_FROM_VIEW, f"FROM main.{_MEASUREMENT_VIEW}"))
    return QueryScope(
        " ".join(("SELECT source.*", f"FROM ({base}) AS source", "WHERE", " AND ".join(clauses))),
        tuple(parameters),
    )


def prepare_report_typed_filter(database, state: FilterState) -> ReportTypedFilterScope:
    path = Path(database).resolve()
    return ReportTypedFilterScope(path, _database_stamp(path), state)


def preview_report_typed_filter(scope, *, cancelled=lambda: False) -> ReportTypedFilterPreview:
    database = str(scope.database)
    scope.require_current_database(database)
    with sqlite_readonly_connection_scope(database, timeout_s=1.0) as connection:
        connection.set_progress_handler(lambda: int(cancelled()), 1000)
        connection.execute("BEGIN")
        require_report_typed_view(connection)
        install_typed_filter_sqlite(connection)
        count = count_query_scope_rows(database, scope.query, connection=connection, retries=0)
        projection = ", ".join(quote_identifier(column) for column in _PREVIEW_COLUMNS)
        preview_sql = " ".join((
            "SELECT", projection, f"FROM ({scope.query.sql}) AS scoped",
            'ORDER BY scoped."MEASUREMENT_ID" LIMIT ?',
        ))
        sample = read_query_scope_result(
            database, QueryScope(preview_sql, (*scope.query.params, _PREVIEW_LIMIT)),
            connection=connection, retries=0,
        )
    scope.require_current_database(database)
    return ReportTypedFilterPreview(count, sample.rows)
