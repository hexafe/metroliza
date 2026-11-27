"""Bind canonical typed filters to one loaded CSV or Excel source snapshot."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from metroliza.reports.db import (
    QueryScope, quote_identifier, read_query_scope_result, sqlite_readonly_connection_scope,
)
from metroliza.shared.grouping_filter_core import DataFrameFilterSpec, FilterExpressionGroup
from metroliza.shared.typed_filter import (
    FilterField, FilterPreview, compile_typed_filter_sqlite, install_typed_filter_sqlite, parse_typed_filter,
)
from metroliza.tabular.tabular_analytics_service import (
    TabularAnalyticsLoadResult, _require_tabular_source_revision, _sqlite_numeric_filter_source,
    _tabular_source_revision,
)

_ROW_ID = '"source_row_number"'
_PREVIEW_LIMIT = 20
STALE_TYPED_FILTER = "The typed filter needs a new preview for these rows. Open Filters or clear the filter."
TYPED_FILTER_COMBINATION = "Clear the existing row filters and groups before using a typed expression."


def supports_tabular_typed_filter(loaded: TabularAnalyticsLoadResult | None) -> bool:
    return bool(isinstance(loaded, TabularAnalyticsLoadResult) and loaded.source_snapshots and loaded.source_column_identities
                and loaded.sqlite_store is not None and loaded.sqlite_store.owns_file
                and all(snapshot.file_identity is not None for snapshot in loaded.source_snapshots))


def _field_bindings(loaded):
    if not supports_tabular_typed_filter(loaded):
        raise ValueError("Load a CSV or Excel file before using a typed expression.")
    store = loaded.sqlite_store
    labels = Counter(raw.strip().casefold() for raw, _ in loaded.source_column_identities)
    for (raw, occurrence), column in loaded.source_column_identities.items():
        kind = loaded.column_types.get((raw, occurrence))
        if kind is None:
            if column in store.metric_columns:
                kind = "number"
            elif column in store.date_filter_columns:
                kind = "date"
            else:
                kind = "text"
        label = raw.strip() or "Unnamed column"
        if labels[raw.strip().casefold()] > 1 or not raw.strip():
            label = f"{label} (occurrence {occurrence})"
        digest = sha256(raw.encode("utf-8")).hexdigest()[:20]
        yield FilterField(f"csv_{digest}_{occurrence}", kind, label, "csv_summary"), column


def tabular_typed_filter_fields(loaded: TabularAnalyticsLoadResult) -> tuple[FilterField, ...]:
    return tuple(item for item, _ in _field_bindings(loaded))


def _referenced_fields(expression):
    if isinstance(expression, FilterExpressionGroup):
        for child in expression.children:
            yield from _referenced_fields(child)
    else:
        yield expression.column


@dataclass(frozen=True, eq=False)
class TabularTypedFilterScope:
    """Internal compiled rule and its owner. A reload requires explicit re-preview."""

    text: str = field(repr=False)
    expression: DataFrameFilterSpec = field(repr=False)
    _loaded: TabularAnalyticsLoadResult = field(repr=False)
    _store_revision: tuple[int, int, int, int, int] = field(repr=False)
    _from_sql: str = field(repr=False)
    _parameters: tuple[str, ...] = field(repr=False)

    def matches_loaded(self, loaded: TabularAnalyticsLoadResult | None) -> bool:
        return loaded is self._loaded

    def require_loaded(self, loaded: TabularAnalyticsLoadResult | None) -> None:
        if not self.matches_loaded(loaded):
            raise ValueError(STALE_TYPED_FILTER)

    def _require_source_revision(self):
        for snapshot in self._loaded.source_snapshots:
            _require_tabular_source_revision(
                Path(snapshot.path), (*snapshot.file_identity, snapshot.size, snapshot.mtime_ns)
            )
        _require_tabular_source_revision(Path(self._loaded.sqlite_store.path), self._store_revision)

    @contextmanager
    def read_connection(self, loaded, *, cancel_check=None):
        self.require_loaded(loaded)
        self._require_source_revision()
        with sqlite_readonly_connection_scope(loaded.sqlite_store.path) as connection:
            if cancel_check is not None:
                connection.set_progress_handler(lambda: int(cancel_check()), 1000)
            connection.execute("BEGIN")
            install_typed_filter_sqlite(connection)
            yield connection
        self._require_source_revision()

    def query(self, projection: str) -> QueryScope:
        return QueryScope(f"SELECT {projection} {self._from_sql} ORDER BY {_ROW_ID}", self._parameters)

    def preview(self, *, cancel_check=None) -> FilterPreview:
        loaded = self._loaded
        path = loaded.sqlite_store.path
        with self.read_connection(loaded, cancel_check=cancel_check) as connection:
            count = read_query_scope_result(
                path, QueryScope(f"SELECT COUNT(*) {self._from_sql}", self._parameters), connection=connection,
            ).rows[0][0]
            query = self.query(_ROW_ID)
            bounded = QueryScope(f"{query.sql} LIMIT ?", (*query.params, _PREVIEW_LIMIT))
            sample = read_query_scope_result(path, bounded, connection=connection).rows if count else ()
        return FilterPreview(count, tuple(row[0] for row in sample))


def prepare_tabular_typed_filter(loaded: TabularAnalyticsLoadResult, text: str) -> TabularTypedFilterScope:
    bindings = {item.field_id: (item, column) for item, column in _field_bindings(loaded)}
    expression = parse_typed_filter(text, (item for item, _ in bindings.values()))
    if expression is None:
        raise ValueError("Enter a typed filter expression.")
    return _compile_tabular_typed_filter(loaded, bindings, expression, text=text.strip())


def _compile_tabular_typed_filter(loaded, bindings, expression, *, text) -> TabularTypedFilterScope:
    store = loaded.sqlite_store
    columns = {}
    projection = []
    for index, field_id in enumerate(dict.fromkeys(_referenced_fields(expression))):
        item, column = bindings[field_id]
        alias = f"value_{index}"
        columns[field_id] = alias
        if item.kind == "number":
            value = _sqlite_numeric_filter_source(column, store.numeric_filter_columns)
        else:
            physical = store.date_filter_columns[column] if item.kind == "date" else column
            value = quote_identifier(physical)
        projection.append(f"{value} AS {quote_identifier(alias)}")
    compiled = compile_typed_filter_sqlite(expression, columns, table_alias="typed_values")
    # The correlated projection gives the compiler existing canonical input values
    # while the outer query still returns the normal analytics/export columns.
    source = (
        f"FROM {quote_identifier(store.table_name)} "
        f"WHERE EXISTS (SELECT 1 FROM (SELECT {', '.join(projection)}) AS typed_values WHERE {compiled.sql})"
    )
    revision = _tabular_source_revision(Path(store.path))
    return TabularTypedFilterScope(text, expression, loaded, revision, source, compiled.parameters)
