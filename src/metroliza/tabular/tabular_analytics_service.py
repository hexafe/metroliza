"""CSV/Excel analytics source helpers for the shared production analytics workflow."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Any

import pandas as pd

from metroliza.tabular.csv_summary_utils import (
    filter_csv_summary_by_group_keys,
    load_csv_with_fallbacks,
    detect_csv_read_configs,
)
from metroliza.reports.db import (
    quote_identifier as _quote_identifier,
    read_sql_dataframe,
    sqlite_connection_scope,
)
from metroliza.shared.excel_sheet_utils import unique_sheet_name
from metroliza.industrial.industrial_analytics_helpers import diagnostics_dataframe
from metroliza.industrial.industrial_analytics_service import (
    ProductionAggregationResult,
    ProductionAnalyticsDiagnostic,
    ProductionGroupstatsResult,
    ProductionMetricCandidate,
)
from metroliza.industrial.industrial_analytics_state import ProductionChartSelection
from metroliza.industrial.industrial_analytics_workbook import groupstats_result_dataframe
from metroliza.industrial.industrial_analytics_workbook_charts import add_analytics_workbook_charts

try:
    from metroliza.shared.grouping_filter_core import (
        parse_filter_expression as _parse_grouping_filter_expression,
    )
except ImportError:  # pragma: no cover - compatibility for older forks without the shared core.
    _parse_grouping_filter_expression = None


_SAFE_COLUMN_RE = re.compile(r"[^A-Za-z0-9_]+")
_TIMESTAMP_HINTS = (
    "timestamp",
    "time_stamp",
    "datetime",
    "date",
    "created",
    "created_at",
    "process_datetime",
    "process_timestamp",
    "event_at",
)
_REFERENCE_HINTS = ("reference", "ref", "part", "part_number", "id", "serial")
TABULAR_GROUP_COLUMN = "GROUP"
TABULAR_DEFAULT_GROUP = "POPULATION"
_INTERNAL_COLUMNS = frozenset(
    {
        "source_row_number",
        "source_file",
        "source_sheet",
        "process_datetime",
        "reference",
        TABULAR_GROUP_COLUMN,
    }
)
TABULAR_SQLITE_SIZE_THRESHOLD_BYTES = 150 * 1024 * 1024
TABULAR_SQLITE_ROW_THRESHOLD = 150_000
TABULAR_SQLITE_CHUNK_ROWS = 50_000
TABULAR_SQLITE_PREVIEW_ROWS = 5_000
_TABULAR_SQLITE_TABLE = "tabular_rows"
_TABULAR_NUMERIC_OPERATORS = frozenset({"=", "!=", ">", ">=", "<", "<="})
_TABULAR_DATE_OPERATORS = _TABULAR_NUMERIC_OPERATORS
_SQLITE_TEXT_FILTER_OPERATORS = frozenset(
    {
        "contains",
        "not_contains",
        "equals",
        "eq",
        "not_equals",
        "ne",
        "starts_with",
        "ends_with",
        "is_blank",
        "is_not_blank",
    }
)
_SQLITE_NUMBER_OPERATOR_SQL = {
    "equals": "=",
    "eq": "=",
    "not_equals": "!=",
    "ne": "!=",
    "greater_than": ">",
    "gt": ">",
    "greater_or_equal": ">=",
    "gte": ">=",
    "less_than": "<",
    "lt": "<",
    "less_or_equal": "<=",
    "lte": "<=",
}
_SQLITE_DATE_OPERATOR_SQL = {
    "on": "=",
    "equals": "=",
    "eq": "=",
    "not_on": "!=",
    "not_equals": "!=",
    "ne": "!=",
    "before": "<",
    "lt": "<",
    "on_or_before": "<=",
    "lte": "<=",
    "after": ">",
    "gt": ">",
    "on_or_after": ">=",
    "gte": ">=",
}
_COMPILED_SQLITE_FILTER_SQL_ATTRS = ("clause", "where_sql", "sqlite_where_sql", "sql")
_COMPILED_SQLITE_FILTER_COLUMN_ATTRS = ("columns", "referenced_columns", "source_columns")
TabularProgressCallback = Callable[[dict[str, Any]], None]
TabularCancelCheck = Callable[[], bool]


class TabularLoadCancelled(Exception):
    """Raised when a cancellable CSV/Excel analytics load is stopped by the caller."""


@dataclass(frozen=True)
class TabularSourceSnapshot:
    """Source-file fingerprint captured when a tabular analytics input is loaded."""

    path: str
    name: str
    size: int
    mtime_ns: int
    row_count: int
    csv_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TabularSqliteFilterExpression:
    """Safe SQLite predicate fragment for shared inline grouping filters.

    Expected integration points:
    - pass this object as ``grouping_filter`` after compiling shared filter specs;
    - pass a shared ``ParsedFilterExpression`` or spec iterable as ``grouping_filter``;
    - pass raw ``grouping_filter_expression`` plus aliases and let this module parse it.
    """

    clause: str = ""
    params: tuple[Any, ...] = ()
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class TabularSqliteStore:
    """File-backed row store for multi-file or large CSV Summary inputs."""

    path: str
    table_name: str
    columns: tuple[str, ...]
    source_columns: tuple[str, ...]
    row_count: int
    date_filter_columns: dict[str, str] = field(default_factory=dict)
    _grouping_index_columns: set[str] = field(default_factory=set, init=False, repr=False, compare=False)

    def cleanup(self) -> None:
        for candidate in (Path(self.path), Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass

    def read_dataframe(
        self,
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        columns: tuple[str, ...] | list[str] | None = None,
        limit: int | None = None,
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> pd.DataFrame:
        select_columns = _normalized_tabular_required_columns(self.columns, columns)
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        query = (
            f"SELECT {', '.join(_quote_identifier(column) for column in select_columns)} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql}"
        )
        if limit is not None and int(limit) >= 0:
            query = f"{query} LIMIT {int(limit)}"
        dataframe = read_sql_dataframe(self.path, query, params=params)
        return _restore_sqlite_dataframe(dataframe)

    def count_rows(
        self,
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> int:
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        query = f"SELECT COUNT(*) FROM {_quote_identifier(self.table_name)}{where_sql}"
        with sqlite_connection_scope(self.path) as connection:
            value = connection.execute(query, params).fetchone()[0]
        return int(value or 0)

    def has_rows(
        self,
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> bool:
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        query = f"SELECT 1 FROM {_quote_identifier(self.table_name)}{where_sql} LIMIT 1"
        with sqlite_connection_scope(self.path) as connection:
            return connection.execute(query, params).fetchone() is not None

    def row_ids(
        self,
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> list[int]:
        query, params = self.source_row_number_query(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
            order_by=True,
        )
        with sqlite_connection_scope(self.path) as connection:
            return [int(row[0]) for row in connection.execute(query, params).fetchall()]

    def source_row_number_query(
        self,
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
        order_by: bool = False,
    ) -> tuple[str, list[Any]]:
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        row_column = _quote_identifier("source_row_number")
        query = (
            f"SELECT {row_column} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql}"
        )
        if order_by:
            query = f"{query} ORDER BY {row_column}"
        return query, params

    def preview_value_rows(
        self,
        column: str,
        *,
        search_text: str = "",
        limit: int | None = None,
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        if column not in self.columns:
            return [], 0
        self._ensure_grouping_column_indexes((column,))
        value_expr = _sqlite_normalized_value_expr(column)
        where_parts: list[str] = []
        filter_where, params = self._where_clause(
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        filter_clause = filter_where.removeprefix(" WHERE ")
        if filter_clause:
            where_parts.append(filter_clause)
        search = str(search_text or "").strip().casefold()
        if search:
            where_parts.append(f"LOWER({value_expr}) LIKE ? ESCAPE '\\'")
            params.append(_sqlite_like_pattern(search))
        where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        grouped_query = (
            f"SELECT {value_expr} AS label, COUNT(*) AS row_count "
            f"FROM {_quote_identifier(self.table_name)}{where_sql} "
            "GROUP BY label"
        )
        query = (
            "SELECT label, row_count, COUNT(*) OVER () AS __total_rows "
            f"FROM ({grouped_query}) ORDER BY label COLLATE NOCASE"
        )
        if limit is not None and int(limit) >= 0:
            query = f"{query} LIMIT {int(limit)}"
        with sqlite_connection_scope(self.path) as connection:
            records = connection.execute(query, params).fetchall()
        total = int(records[0][2] or 0) if records else 0
        rows = [
            {
                "key": (str(label),),
                "label": str(label),
                "row_count": int(row_count or 0),
            }
            for label, row_count, _total_rows in records
        ]
        return rows, total

    def preview_group_keys(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> tuple[tuple[str, ...], ...]:
        normalized_columns = tuple(str(column) for column in columns if str(column) in self.columns)
        if not normalized_columns:
            return ()
        self._ensure_grouping_column_indexes(normalized_columns)
        expressions = [
            f"{_sqlite_normalized_value_expr(column)} AS {_quote_identifier(f'key_{index}')}"
            for index, column in enumerate(normalized_columns)
        ]
        where_sql, params = self._where_clause(
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        query = (
            f"SELECT DISTINCT {', '.join(expressions)} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql} "
            f"ORDER BY {', '.join(_quote_identifier(f'key_{index}') for index in range(len(expressions)))}"
        )
        with sqlite_connection_scope(self.path) as connection:
            records = connection.execute(query, params).fetchall()
        return tuple(tuple(str(part) for part in record) for record in records)

    def preview_group_rows(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        search_text: str = "",
        offset: int = 0,
        limit: int | None = None,
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_columns = tuple(str(column) for column in columns if str(column) in self.columns)
        if not normalized_columns:
            return [], 0
        self._ensure_grouping_column_indexes(normalized_columns)
        aliases = tuple(f"key_{index}" for index, _column in enumerate(normalized_columns))
        select_exprs = [
            f"{_sqlite_normalized_value_expr(column)} AS {_quote_identifier(alias)}"
            for alias, column in zip(aliases, normalized_columns, strict=False)
        ]
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        inner_query = (
            f"SELECT {', '.join(select_exprs)} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql}"
        )
        label_expr = " || ' | ' || ".join(_quote_identifier(alias) for alias in aliases)
        grouped_query = (
            f"SELECT {', '.join(_quote_identifier(alias) for alias in aliases)}, "
            f"COUNT(*) AS row_count, {label_expr} AS label "
            f"FROM ({inner_query}) "
            f"GROUP BY {', '.join(_quote_identifier(alias) for alias in aliases)}"
        )
        search = str(search_text or "").strip().casefold()
        outer_where = ""
        outer_params: list[Any] = []
        if search:
            outer_where = " WHERE LOWER(label) LIKE ? ESCAPE '\\'"
            outer_params.append(_sqlite_like_pattern(search))
        count_query = f"SELECT COUNT(*) FROM ({grouped_query}){outer_where}"
        query = (
            f"SELECT *, COUNT(*) OVER () AS __total_rows FROM ({grouped_query}){outer_where} "
            "ORDER BY label COLLATE NOCASE"
        )
        offset = max(0, int(offset or 0))
        if limit is not None and int(limit) >= 0:
            query = f"{query} LIMIT {int(limit)} OFFSET {offset}"
        elif offset:
            query = f"{query} LIMIT -1 OFFSET {offset}"
        with sqlite_connection_scope(self.path) as connection:
            records = connection.execute(query, [*params, *outer_params]).fetchall()
            total = (
                int(records[0][len(aliases) + 2] or 0)
                if records
                else int(connection.execute(count_query, [*params, *outer_params]).fetchone()[0] or 0)
            )
        rows: list[dict[str, Any]] = []
        for record in records:
            key = tuple(str(record[index]) for index in range(len(aliases)))
            rows.append(
                {
                    "key": key,
                    "label": str(record[len(aliases) + 1]),
                    "row_count": int(record[len(aliases)] or 0),
                }
            )
        return rows, total

    def count_rows_for_group_search(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        search_text: str = "",
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> int:
        grouped_query, params = self._grouped_search_query(
            columns,
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        search = str(search_text or "").strip().casefold()
        if not grouped_query or not search:
            return self.count_rows(
                filter_columns=filter_columns,
                selected_filter_keys=selected_filter_keys,
                base_column_filters=base_column_filters,
                column_filters=column_filters,
                column_filter_match_mode=column_filter_match_mode,
                grouping_filter=grouping_filter,
                grouping_filter_expression=grouping_filter_expression,
                grouping_filter_aliases=grouping_filter_aliases,
            )
        query = (
            f"SELECT COALESCE(SUM(row_count), 0) FROM ({grouped_query}) "
            "WHERE LOWER(label) LIKE ? ESCAPE '\\'"
        )
        with sqlite_connection_scope(self.path) as connection:
            return int(connection.execute(query, [*params, _sqlite_like_pattern(search)]).fetchone()[0] or 0)

    def has_rows_for_group_search(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        search_text: str = "",
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> bool:
        grouped_query, params = self._grouped_search_query(
            columns,
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        search = str(search_text or "").strip().casefold()
        if not grouped_query or not search:
            return self.has_rows(
                filter_columns=filter_columns,
                selected_filter_keys=selected_filter_keys,
                base_column_filters=base_column_filters,
                column_filters=column_filters,
                column_filter_match_mode=column_filter_match_mode,
                grouping_filter=grouping_filter,
                grouping_filter_expression=grouping_filter_expression,
                grouping_filter_aliases=grouping_filter_aliases,
            )
        query = f"SELECT 1 FROM ({grouped_query}) WHERE LOWER(label) LIKE ? ESCAPE '\\' LIMIT 1"
        with sqlite_connection_scope(self.path) as connection:
            return connection.execute(query, [*params, _sqlite_like_pattern(search)]).fetchone() is not None

    def row_ids_for_group_search(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        search_text: str = "",
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> list[int]:
        query, params = self.source_row_number_query_for_group_search(
            columns,
            search_text=search_text,
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
            order_by=True,
        )
        if not query:
            return []
        with sqlite_connection_scope(self.path) as connection:
            return [int(row[0]) for row in connection.execute(query, params).fetchall()]

    def source_row_number_query_for_group_search(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        search_text: str = "",
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
        order_by: bool = False,
    ) -> tuple[str, list[Any]]:
        normalized_columns = tuple(str(column) for column in columns if str(column) in self.columns)
        search = str(search_text or "").strip().casefold()
        if not normalized_columns:
            return "", []
        if not search:
            return self.source_row_number_query(
                filter_columns=filter_columns,
                selected_filter_keys=selected_filter_keys,
                base_column_filters=base_column_filters,
                column_filters=column_filters,
                column_filter_match_mode=column_filter_match_mode,
                grouping_filter=grouping_filter,
                grouping_filter_expression=grouping_filter_expression,
                grouping_filter_aliases=grouping_filter_aliases,
                order_by=order_by,
            )
        self._ensure_grouping_column_indexes(normalized_columns)
        aliases = tuple(f"key_{index}" for index, _column in enumerate(normalized_columns))
        select_exprs = [
            f"{_sqlite_normalized_value_expr(column)} AS {_quote_identifier(alias)}"
            for alias, column in zip(aliases, normalized_columns, strict=False)
        ]
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        row_column = _quote_identifier("source_row_number")
        base_query = (
            f"SELECT {row_column}, {', '.join(select_exprs)} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql}"
        )
        label_expr = " || ' | ' || ".join(_quote_identifier(alias) for alias in aliases)
        grouped_keys = ", ".join(_quote_identifier(alias) for alias in aliases)
        grouped_query = (
            f"SELECT {grouped_keys}, {label_expr} AS label "
            f"FROM base_rows GROUP BY {grouped_keys}"
        )
        join_clause = " AND ".join(
            f"base_rows.{_quote_identifier(alias)} = matching_groups.{_quote_identifier(alias)}"
            for alias in aliases
        )
        order_sql = f" ORDER BY base_rows.{row_column}" if order_by else ""
        query = (
            "WITH base_rows AS ("
            f"{base_query}"
            "), matching_groups AS ("
            f"SELECT {grouped_keys} FROM ({grouped_query}) "
            "WHERE LOWER(label) LIKE ? ESCAPE '\\'"
            ") "
            f"SELECT base_rows.{row_column} "
            "FROM base_rows JOIN matching_groups ON "
            f"{join_clause}{order_sql}"
        )
        return query, [*params, _sqlite_like_pattern(search)]

    def row_ids_for_group_keys(
        self,
        columns: tuple[str, ...] | list[str],
        selected_group_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | set[tuple[str, ...]],
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> list[int]:
        where_sql, params = self._where_clause_for_group_keys(
            columns,
            selected_group_keys,
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        if not where_sql:
            return []
        query = (
            f"SELECT {_quote_identifier('source_row_number')} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql} "
            f"ORDER BY {_quote_identifier('source_row_number')}"
        )
        with sqlite_connection_scope(self.path) as connection:
            return [int(row[0]) for row in connection.execute(query, params).fetchall()]

    def count_rows_for_group_keys(
        self,
        columns: tuple[str, ...] | list[str],
        selected_group_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | set[tuple[str, ...]],
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> int:
        where_sql, params = self._where_clause_for_group_keys(
            columns,
            selected_group_keys,
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        if not where_sql:
            return 0
        query = f"SELECT COUNT(*) FROM {_quote_identifier(self.table_name)}{where_sql}"
        with sqlite_connection_scope(self.path) as connection:
            return int(connection.execute(query, params).fetchone()[0] or 0)

    def count_source_row_numbers(
        self,
        row_ids: tuple[int, ...] | list[int] | set[int],
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> int:
        normalized_ids = tuple(
            dict.fromkeys(
                int(row_id)
                for row_id in row_ids
                if pd.notna(row_id)
            )
        )
        if not normalized_ids:
            return 0
        filter_where, filter_params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        filter_clause = filter_where.removeprefix(" WHERE ")
        row_column = _quote_identifier("source_row_number")
        total = 0
        with sqlite_connection_scope(self.path) as connection:
            for start in range(0, len(normalized_ids), 900):
                chunk = normalized_ids[start : start + 900]
                placeholders = ", ".join("?" for _row_id in chunk)
                row_clause = f"{row_column} IN ({placeholders})"
                where_parts = [part for part in (filter_clause, row_clause) if part]
                query = (
                    f"SELECT COUNT(*) FROM {_quote_identifier(self.table_name)} "
                    f"WHERE {' AND '.join(where_parts)}"
                )
                total += int(
                    connection.execute(query, [*filter_params, *chunk]).fetchone()[0] or 0
                )
        return total

    def _sqlite_column_filter_clause(
        self,
        column_filter: "TabularColumnFilter",
    ) -> tuple[str, list[Any]]:
        filter_clauses: list[str] = []
        params: list[Any] = []
        if column_filter.selected_values:
            placeholders = ", ".join("?" for _value in column_filter.selected_values)
            filter_clauses.append(
                f"{_sqlite_normalized_value_expr(column_filter.column)} IN ({placeholders})"
            )
            params.extend(column_filter.selected_values)
        if column_filter.has_date_filter:
            date_expr = self._sqlite_date_filter_expr(column_filter.column)
            date_operator = str(column_filter.date_operator or "").strip()
            date_value = _parse_tabular_filter_date(column_filter.date_value)
            if date_operator in _TABULAR_DATE_OPERATORS and date_value is not None:
                filter_clauses.append(f"{date_expr} {date_operator} date(?)")
                params.append(date_value.isoformat())
            else:
                lower = _parse_tabular_filter_date(column_filter.date_from)
                upper = _parse_tabular_filter_date(column_filter.date_to)
                if column_filter.date_mode in {"from", "between"} and lower is not None:
                    filter_clauses.append(f"{date_expr} >= date(?)")
                    params.append(lower.isoformat())
                if column_filter.date_mode in {"to", "between"} and upper is not None:
                    filter_clauses.append(f"{date_expr} <= date(?)")
                    params.append(upper.isoformat())
        if column_filter.has_numeric_filter:
            numeric_value = _parse_tabular_filter_number(column_filter.numeric_value)
            if numeric_value is not None and column_filter.numeric_operator in _TABULAR_NUMERIC_OPERATORS:
                text_expr, numeric_guard = _sqlite_numeric_text_and_guard(column_filter.column)
                filter_clauses.append(
                    f"(({numeric_guard}) AND CAST({text_expr} AS REAL) "
                    f"{column_filter.numeric_operator} ?)"
                )
                params.append(float(numeric_value))
        if not filter_clauses:
            return "", []
        return f"({' AND '.join(filter_clauses)})", params

    def is_date_filterable(self, column: str) -> bool:
        if column not in self.columns:
            return False
        if column in self.date_filter_columns:
            return True
        column_key = column.casefold()
        if not any(token in column_key for token in ("date", "time", "timestamp", "created", "updated")):
            return False
        query = (
            f"SELECT {_quote_identifier(column)} FROM {_quote_identifier(self.table_name)} "
            f"WHERE {_quote_identifier(column)} IS NOT NULL "
            f"AND TRIM(CAST({_quote_identifier(column)} AS TEXT)) != '' LIMIT 200"
        )
        with sqlite_connection_scope(self.path) as connection:
            values = [row[0] for row in connection.execute(query).fetchall()]
        if not values:
            return False
        parsed = pd.to_datetime(pd.Series(values), errors="coerce")
        return bool(parsed.notna().mean() >= 0.6)

    def date_bounds(self, column: str) -> tuple[date, date] | None:
        if column not in self.columns:
            return None
        date_expr = self._sqlite_date_filter_expr(column)
        query = (
            f"SELECT MIN({date_expr}), MAX({date_expr}) "
            f"FROM {_quote_identifier(self.table_name)} "
            f"WHERE {date_expr} IS NOT NULL"
        )
        with sqlite_connection_scope(self.path) as connection:
            lower, upper = connection.execute(query).fetchone()
        parsed_lower = pd.to_datetime(lower, errors="coerce")
        parsed_upper = pd.to_datetime(upper, errors="coerce")
        if pd.isna(parsed_lower) or pd.isna(parsed_upper):
            return None
        return parsed_lower.date(), parsed_upper.date()

    def _where_clause(
        self,
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        normalized_base_filters = _normalized_tabular_column_filters_for_columns(
            self.columns,
            base_column_filters,
        )
        if normalized_base_filters:
            self._ensure_grouping_column_indexes(
                tuple(column_filter.column for column_filter in normalized_base_filters)
            )
        for column_filter in normalized_base_filters:
            filter_clause, filter_params = self._sqlite_column_filter_clause(column_filter)
            if filter_clause:
                clauses.append(filter_clause)
                params.extend(filter_params)

        normalized_filters = _normalized_tabular_column_filters_for_columns(self.columns, column_filters)
        if normalized_filters:
            self._ensure_grouping_column_indexes(
                tuple(column_filter.column for column_filter in normalized_filters)
            )
            filter_mode = "or" if str(column_filter_match_mode or "").strip().casefold() == "or" else "and"
            grouped_clauses: list[str] = []
            grouped_params: list[Any] = []
            for column_filter in normalized_filters:
                filter_clause, filter_params = self._sqlite_column_filter_clause(column_filter)
                if filter_clause:
                    grouped_clauses.append(filter_clause)
                    grouped_params.extend(filter_params)
            if grouped_clauses:
                joiner = " OR " if filter_mode == "or" else " AND "
                clauses.append(f"({joiner.join(grouped_clauses)})")
                params.extend(grouped_params)

        compiled_grouping_filter = self._sqlite_grouping_filter(
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        if compiled_grouping_filter.clause:
            clauses.append(compiled_grouping_filter.clause)
            params.extend(compiled_grouping_filter.params)
            self._ensure_grouping_column_indexes(compiled_grouping_filter.columns)

        columns = tuple(str(column) for column in (filter_columns or ()) if str(column) in self.columns)
        selected_keys = tuple(
            tuple(str(part) for part in key)
            for key in (selected_filter_keys or ())
            if isinstance(key, (list, tuple)) and len(key) == len(columns)
        )
        if columns and selected_keys:
            self._ensure_grouping_column_indexes(columns)
            clauses.append(_sqlite_group_key_predicate(columns, selected_keys, params))
        return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params

    def _where_clause_for_group_keys(
        self,
        columns: tuple[str, ...] | list[str],
        selected_group_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | set[tuple[str, ...]],
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> tuple[str, list[Any]]:
        normalized_columns = tuple(str(column) for column in columns if str(column) in self.columns)
        selected_keys = tuple(
            tuple(str(part) for part in key)
            for key in (selected_group_keys or ())
            if isinstance(key, (list, tuple)) and len(key) == len(normalized_columns)
        )
        if not normalized_columns or not selected_keys:
            return "", []
        self._ensure_grouping_column_indexes(normalized_columns)
        filter_where, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        clauses: list[str] = []
        if filter_where:
            clauses.append(filter_where.removeprefix(" WHERE "))
        clauses.append(_sqlite_group_key_predicate(normalized_columns, selected_keys, params))
        return f" WHERE {' AND '.join(clauses)}", params

    def _sqlite_date_filter_expr(self, column: str) -> str:
        return f"date({_quote_identifier(self.date_filter_columns.get(column, column))})"

    def _grouped_search_query(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        base_column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        column_filter_match_mode: str = "and",
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> tuple[str, list[Any]]:
        normalized_columns = tuple(str(column) for column in columns if str(column) in self.columns)
        if not normalized_columns:
            return "", []
        self._ensure_grouping_column_indexes(normalized_columns)
        aliases = tuple(f"key_{index}" for index, _column in enumerate(normalized_columns))
        select_exprs = [
            f"{_sqlite_normalized_value_expr(column)} AS {_quote_identifier(alias)}"
            for alias, column in zip(aliases, normalized_columns, strict=False)
        ]
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            base_column_filters=base_column_filters,
            column_filters=column_filters,
            column_filter_match_mode=column_filter_match_mode,
            grouping_filter=grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
        )
        inner_query = (
            f"SELECT {', '.join(select_exprs)} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql}"
        )
        label_expr = " || ' | ' || ".join(_quote_identifier(alias) for alias in aliases)
        grouped_query = (
            f"SELECT {', '.join(_quote_identifier(alias) for alias in aliases)}, "
            f"COUNT(*) AS row_count, {label_expr} AS label "
            f"FROM ({inner_query}) "
            f"GROUP BY {', '.join(_quote_identifier(alias) for alias in aliases)}"
        )
        return grouped_query, params

    def _sqlite_grouping_filter(
        self,
        *,
        grouping_filter: Any = None,
        grouping_filter_expression: str | None = None,
        grouping_filter_aliases: Mapping[str, str] | None = None,
    ) -> TabularSqliteFilterExpression:
        return compile_tabular_sqlite_grouping_filter(
            self.columns,
            grouping_filter,
            grouping_filter_expression=grouping_filter_expression,
            grouping_filter_aliases=grouping_filter_aliases,
            date_filter_columns=self.date_filter_columns,
        )

    def _ensure_grouping_column_indexes(self, columns: tuple[str, ...] | list[str]) -> None:
        normalized_columns = tuple(
            dict.fromkeys(str(column) for column in columns if str(column) in self.columns)
        )
        pending = tuple(
            column for column in normalized_columns if column not in self._grouping_index_columns
        )
        if not pending:
            return
        with sqlite_connection_scope(self.path) as connection:
            _create_sqlite_grouping_indexes(connection, self.table_name, pending)
        self._grouping_index_columns.update(pending)


@dataclass(frozen=True)
class TabularAnalyticsLoadResult:
    """Loaded CSV/Excel table normalized for shared analytics."""

    dataframe: pd.DataFrame
    metric_candidates: tuple[ProductionMetricCandidate, ...]
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    column_mapping: dict[str, str] = field(default_factory=dict)
    source_file: str = ""
    sheet_name: str | None = None
    timestamp_column: str | None = None
    reference_column: str | None = None
    csv_config: dict[str, Any] = field(default_factory=dict)
    source_size: int | None = None
    source_mtime_ns: int | None = None
    source_files: tuple[str, ...] = ()
    source_snapshots: tuple[TabularSourceSnapshot, ...] = ()
    storage_mode: str = "dataframe"
    sqlite_store: TabularSqliteStore | None = None
    row_count: int | None = None
    load_timings_s: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TabularAnalyticsWorkbookResult:
    """Workbook export result for tabular analytics."""

    output_file: str
    sheet_names: tuple[str, ...]
    parameter_sheet_count: int


@dataclass(frozen=True)
class TabularGroupingResult:
    """CSV/Excel analytics frame after optional manual grouping assignments."""

    dataframe: pd.DataFrame
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    applied: bool = False
    group_count: int = 0
    custom_group_count: int = 0


@dataclass(frozen=True)
class TabularFilterResult:
    """CSV/Excel analytics frame after optional visual row filtering."""

    dataframe: pd.DataFrame
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    applied: bool = False
    input_row_count: int = 0
    output_row_count: int = 0


@dataclass(frozen=True)
class TabularColumnFilter:
    """One CSV/Excel row-filter rule scoped to one source column."""

    column: str
    selected_values: tuple[str, ...] = ()
    date_mode: str = "any"
    date_from: str | None = None
    date_to: str | None = None
    date_operator: str | None = None
    date_value: str | None = None
    numeric_operator: str | None = None
    numeric_value: float | int | str | None = None

    @property
    def has_value_filter(self) -> bool:
        return bool(self.selected_values)

    @property
    def has_date_filter(self) -> bool:
        has_range = self.date_mode in {"from", "to", "between"} and bool(self.date_from or self.date_to)
        has_operator = (
            str(self.date_operator or "").strip() in _TABULAR_DATE_OPERATORS
            and _parse_tabular_filter_date(self.date_value) is not None
        )
        return has_range or has_operator

    @property
    def has_numeric_filter(self) -> bool:
        return (
            str(self.numeric_operator or "").strip() in _TABULAR_NUMERIC_OPERATORS
            and _parse_tabular_filter_number(self.numeric_value) is not None
        )

    @property
    def is_active(self) -> bool:
        return bool(self.column and (self.has_value_filter or self.has_date_filter or self.has_numeric_filter))


def _excel_safe_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    safe_frame = dataframe.copy()
    for column in safe_frame.columns:
        dtype = safe_frame[column].dtype
        if isinstance(dtype, pd.DatetimeTZDtype):
            safe_frame[column] = safe_frame[column].dt.tz_convert(None)
    return safe_frame


def list_tabular_excel_sheets(input_file: str | Path) -> tuple[str, ...]:
    """Return workbook sheet names for a CSV/Excel analytics input file."""

    path = Path(input_file)
    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return ()
    with pd.ExcelFile(path) as workbook:
        return tuple(str(sheet) for sheet in workbook.sheet_names)


def selectable_tabular_source_columns(
    dataframe: pd.DataFrame,
    *,
    normalized_source_columns: set[str] | tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """Return user-facing CSV/Excel source columns, excluding analytics helper fields."""

    if not isinstance(dataframe, pd.DataFrame):
        return []
    known_sources = {str(column) for column in (normalized_source_columns or ())}
    excluded = set(_INTERNAL_COLUMNS)
    excluded.update({"GROUP_KEY", "GROUP_COLOR"})
    excluded_lookup = {column.casefold() for column in excluded}
    columns: list[str] = []
    for column in dataframe.columns:
        column_name = str(column)
        if known_sources:
            if column_name in known_sources and column_name.casefold() not in excluded_lookup:
                columns.append(column_name)
            continue
        if column_name.casefold() not in excluded_lookup and not column_name.startswith("__"):
            columns.append(column_name)
    return columns


def load_tabular_analytics_files(
    input_files: tuple[str | Path, ...] | list[str | Path],
    *,
    sheet_name: str | int | None = None,
    timestamp_column: str | None = None,
    reference_column: str | None = None,
    numeric_threshold: float = 0.8,
    min_numeric_count: int = 2,
    force_sqlite: bool | None = None,
    progress_callback: TabularProgressCallback | None = None,
    cancel_check: TabularCancelCheck | None = None,
) -> TabularAnalyticsLoadResult:
    """Load one or more tabular analytics files.

    Multiple inputs are intentionally CSV-only. Excel keeps the existing single-workbook
    sheet selection behavior.
    """

    paths = tuple(Path(path) for path in input_files or ())
    _raise_if_tabular_load_cancelled(cancel_check)
    if not paths:
        raise ValueError("Select at least one CSV or Excel file.")
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(str(path))

    if len(paths) == 1 and not _should_use_sqlite_for_paths(paths, force_sqlite=force_sqlite):
        return load_tabular_analytics_file(
            paths[0],
            sheet_name=sheet_name,
            timestamp_column=timestamp_column,
            reference_column=reference_column,
            numeric_threshold=numeric_threshold,
            min_numeric_count=min_numeric_count,
            force_sqlite=False,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    if any(path.suffix.lower() != ".csv" for path in paths):
        raise ValueError("Multiple-file and optimized large-file loading supports CSV files only.")

    return _load_csv_files_into_sqlite(
        paths,
        timestamp_column=timestamp_column,
        reference_column=reference_column,
        numeric_threshold=numeric_threshold,
        min_numeric_count=min_numeric_count,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def load_tabular_analytics_file(
    input_file: str | Path,
    *,
    sheet_name: str | int | None = None,
    timestamp_column: str | None = None,
    reference_column: str | None = None,
    numeric_threshold: float = 0.8,
    min_numeric_count: int = 2,
    force_sqlite: bool | None = None,
    progress_callback: TabularProgressCallback | None = None,
    cancel_check: TabularCancelCheck | None = None,
) -> TabularAnalyticsLoadResult:
    """Load CSV/Excel data and normalize it to the production analytics dataframe shape."""

    path = Path(input_file)
    _raise_if_tabular_load_cancelled(cancel_check)
    if not path.exists():
        raise FileNotFoundError(str(path))
    source_stat = path.stat()

    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    csv_config: dict[str, Any] = {}
    suffix = path.suffix.lower()
    if suffix == ".csv":
        if _should_use_sqlite_for_paths((path,), force_sqlite=force_sqlite):
            return _load_csv_files_into_sqlite(
                (path,),
                timestamp_column=timestamp_column,
                reference_column=reference_column,
                numeric_threshold=numeric_threshold,
                min_numeric_count=min_numeric_count,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
        raw_frame, csv_config = load_csv_with_fallbacks(path)
        resolved_sheet_name = None
    elif suffix in {".xlsx", ".xls"}:
        resolved_sheet_name = 0 if sheet_name is None else sheet_name
        raw_frame = pd.read_excel(path, sheet_name=resolved_sheet_name)
    else:
        raise ValueError("Unsupported analytics file type. Use CSV or Excel.")

    frame, mapping = _normalize_columns(raw_frame)
    frame, mapping = _reserve_internal_columns(frame, mapping)
    frame.insert(0, "source_row_number", range(1, len(frame.index) + 1))
    frame["source_file"] = path.name
    if resolved_sheet_name is not None:
        frame["source_sheet"] = str(resolved_sheet_name)

    timestamp_field = _resolve_requested_column(timestamp_column, mapping, frame.columns)
    if timestamp_field is None:
        timestamp_field = _infer_timestamp_column(frame, hints=_TIMESTAMP_HINTS)
    if timestamp_field is not None:
        frame["process_datetime"] = pd.to_datetime(frame[timestamp_field], errors="coerce", utc=True)
        bad_count = int(frame["process_datetime"].isna().sum())
        if bad_count:
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="warning",
                    code="tabular_bad_timestamps",
                    message=f"{bad_count} table row(s) have invalid timestamps.",
                    context={"timestamp_column": timestamp_field, "bad_timestamp_count": bad_count},
                )
            )
    else:
        frame["process_datetime"] = pd.NaT
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="tabular_timestamp_not_selected",
                message="No timestamp column was selected or inferred for this file.",
            )
        )

    reference_field = _resolve_requested_or_inferred_column(
        reference_column,
        mapping,
        frame.columns,
        hints=_REFERENCE_HINTS,
    )
    if reference_field is not None:
        frame["reference"] = frame[reference_field].fillna("").astype(str)
    else:
        frame["reference"] = ""
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="tabular_reference_not_selected",
                message="No reference/id column was selected or inferred for this file.",
            )
        )

    metric_candidates = discover_tabular_metric_candidates(
        frame,
        reserved_columns=tuple(
            column for column in (timestamp_field, reference_field) if column is not None
        ),
        numeric_threshold=numeric_threshold,
        min_numeric_count=min_numeric_count,
    )
    if not metric_candidates:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="tabular_no_numeric_metrics",
                message="No numeric columns were detected in the selected file.",
            )
        )

    return TabularAnalyticsLoadResult(
        dataframe=frame,
        metric_candidates=metric_candidates,
        diagnostics=tuple(diagnostics),
        column_mapping=mapping,
        source_file=str(path),
        sheet_name=None if resolved_sheet_name is None else str(resolved_sheet_name),
        timestamp_column=timestamp_field,
        reference_column=reference_field,
        csv_config=csv_config,
        source_size=int(source_stat.st_size),
        source_mtime_ns=int(source_stat.st_mtime_ns),
        source_files=(str(path),),
        source_snapshots=(
            TabularSourceSnapshot(
                path=str(path),
                name=path.name,
                size=int(source_stat.st_size),
                mtime_ns=int(source_stat.st_mtime_ns),
                row_count=int(len(frame.index)),
                csv_config=csv_config,
            ),
        ),
        storage_mode="dataframe",
        sqlite_store=None,
        row_count=int(len(frame.index)),
    )


def _should_use_sqlite_for_paths(
    paths: tuple[Path, ...],
    *,
    force_sqlite: bool | None,
) -> bool:
    if force_sqlite is True:
        return True
    if force_sqlite is False:
        return False
    if len(paths) > 1:
        return True
    path = paths[0]
    if path.suffix.lower() != ".csv":
        return False
    try:
        if path.stat().st_size >= TABULAR_SQLITE_SIZE_THRESHOLD_BYTES:
            return True
    except OSError:
        return False
    return _estimate_csv_data_rows(path) >= TABULAR_SQLITE_ROW_THRESHOLD


def _estimate_csv_data_rows(path: Path) -> int:
    try:
        newline_count = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                newline_count += chunk.count(b"\n")
        return max(0, newline_count - 1)
    except OSError:
        return 0


def _load_csv_files_into_sqlite(
    paths: tuple[Path, ...],
    *,
    timestamp_column: str | None,
    reference_column: str | None,
    numeric_threshold: float,
    min_numeric_count: int,
    progress_callback: TabularProgressCallback | None = None,
    cancel_check: TabularCancelCheck | None = None,
) -> TabularAnalyticsLoadResult:
    load_started_at = time.perf_counter()
    load_timings: dict[str, float] = {}

    def _record_load_timing(name: str, started_at: float) -> None:
        load_timings[name] = load_timings.get(name, 0.0) + (time.perf_counter() - started_at)

    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    sampled_specs: list[dict[str, Any]] = []
    file_specs: list[dict[str, Any]] = []
    global_original_columns: list[str] = []
    seen_original_columns: set[str] = set()
    source_columns: list[str] = []
    date_filter_source_columns: set[str] = set()
    timestamp_field: str | None = None
    reference_field: str | None = None

    for path in paths:
        sampling_started_at = time.perf_counter()
        _raise_if_tabular_load_cancelled(cancel_check)
        _emit_tabular_load_progress(
            progress_callback,
            stage="sampling",
            file=str(path),
            file_name=path.name,
            rows_loaded=0,
        )
        csv_config = _detect_csv_config(path)
        sample_frame = pd.read_csv(
            path,
            delimiter=csv_config["delimiter"],
            decimal=csv_config["decimal"],
            low_memory=False,
            nrows=200,
        )
        for column in sample_frame.columns:
            original = str(column)
            if original in seen_original_columns:
                continue
            seen_original_columns.add(original)
            global_original_columns.append(original)
        sampled_specs.append(
            {
                "path": path,
                "csv_config": csv_config,
                "sample_frame": sample_frame,
            }
        )
        _record_load_timing("sampling", sampling_started_at)

    global_sample = pd.DataFrame(columns=global_original_columns)
    normalized_global_sample, global_mapping = _normalize_columns(global_sample)
    _, global_mapping = _reserve_internal_columns(normalized_global_sample, global_mapping)
    source_columns = list(dict.fromkeys(global_mapping.values()))

    for sampled_spec in sampled_specs:
        path = sampled_spec["path"]
        sample_frame = sampled_spec["sample_frame"]
        csv_config = sampled_spec["csv_config"]
        mapping = {
            str(column): global_mapping[str(column)]
            for column in sample_frame.columns
            if str(column) in global_mapping
        }
        normalized_sample = sample_frame.rename(columns=mapping).copy()
        normalized_columns = tuple(str(column) for column in normalized_sample.columns)

        file_timestamp_field = _resolve_requested_column(timestamp_column, mapping, normalized_columns)
        if file_timestamp_field is None:
            file_timestamp_field = _infer_timestamp_column(normalized_sample, hints=_TIMESTAMP_HINTS)
        file_reference_field = _resolve_requested_or_inferred_column(
            reference_column,
            mapping,
            normalized_columns,
            hints=_REFERENCE_HINTS,
        )
        if timestamp_field is None and file_timestamp_field is not None:
            timestamp_field = file_timestamp_field
        if reference_field is None and file_reference_field is not None:
            reference_field = file_reference_field
        date_filter_source_columns.update(
            _sqlite_date_filter_source_columns(
                normalized_sample,
                normalized_columns,
                timestamp_field=file_timestamp_field,
            )
        )
        file_specs.append(
            {
                "path": path,
                "csv_config": csv_config,
                "mapping": mapping,
                "source_columns": normalized_columns,
                "timestamp_field": file_timestamp_field,
                "reference_field": file_reference_field,
            }
        )

    sqlite_setup_started_at = time.perf_counter()
    if timestamp_field is None:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="tabular_timestamp_not_selected",
                message="No timestamp column was selected or inferred for these CSV file(s).",
            )
        )
    if reference_field is None:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="tabular_reference_not_selected",
                message="No reference/id column was selected or inferred for these CSV file(s).",
            )
        )

    temp_file = tempfile.NamedTemporaryFile(
        prefix="metroliza_csv_summary_",
        suffix=".sqlite",
        delete=False,
    )
    db_path = Path(temp_file.name)
    temp_file.close()
    table_columns = ("source_row_number", "source_file", "process_datetime", "reference", *source_columns)
    date_filter_columns = _sqlite_date_filter_storage_columns(
        tuple(source_columns),
        date_filter_source_columns,
        table_columns,
    )
    storage_columns = (*table_columns, *date_filter_columns.values())
    row_number = 0
    bad_timestamp_count = 0
    metric_stats: dict[str, dict[str, Any]] = {}
    snapshots: list[TabularSourceSnapshot] = []

    try:
        with sqlite_connection_scope(str(db_path)) as connection:
            _create_sqlite_table(connection, _TABULAR_SQLITE_TABLE, storage_columns)
            _record_load_timing("sqlite_setup", sqlite_setup_started_at)
            for file_index, spec in enumerate(file_specs, start=1):
                _raise_if_tabular_load_cancelled(cancel_check)
                path = spec["path"]
                csv_config = spec["csv_config"]
                mapping = spec["mapping"]
                file_row_count = 0
                _emit_tabular_load_progress(
                    progress_callback,
                    stage="loading_file",
                    file=str(path),
                    file_name=path.name,
                    file_index=file_index,
                    file_count=len(file_specs),
                    rows_loaded=row_number,
                )
                chunk_read_started_at = time.perf_counter()
                chunk_iter = pd.read_csv(
                    path,
                    delimiter=csv_config["delimiter"],
                    decimal=csv_config["decimal"],
                    low_memory=False,
                    chunksize=TABULAR_SQLITE_CHUNK_ROWS,
                )
                for raw_chunk in chunk_iter:
                    _record_load_timing("chunk_read", chunk_read_started_at)
                    _raise_if_tabular_load_cancelled(cancel_check)
                    chunk_normalize_started_at = time.perf_counter()
                    normalized_chunk = raw_chunk.rename(columns=mapping)
                    _record_load_timing("chunk_normalize", chunk_normalize_started_at)
                    chunk_build_started_at = time.perf_counter()
                    output_chunk = pd.DataFrame(index=normalized_chunk.index)
                    chunk_row_count = int(len(normalized_chunk.index))
                    output_chunk["source_row_number"] = range(
                        row_number + 1,
                        row_number + chunk_row_count + 1,
                    )
                    output_chunk["source_file"] = path.name

                    chunk_timestamp_field = spec["timestamp_field"]
                    if chunk_timestamp_field is not None and chunk_timestamp_field in normalized_chunk.columns:
                        parsed_timestamps = pd.to_datetime(
                            normalized_chunk[chunk_timestamp_field],
                            errors="coerce",
                            utc=True,
                        )
                        bad_timestamp_count += int(parsed_timestamps.isna().sum())
                        output_chunk["process_datetime"] = _sqlite_datetime_text(parsed_timestamps)
                    else:
                        output_chunk["process_datetime"] = None

                    chunk_reference_field = spec["reference_field"]
                    if chunk_reference_field is not None and chunk_reference_field in normalized_chunk.columns:
                        output_chunk["reference"] = (
                            normalized_chunk[chunk_reference_field].fillna("").astype(str)
                        )
                    else:
                        output_chunk["reference"] = ""

                    for column in source_columns:
                        output_chunk[column] = normalized_chunk[column] if column in normalized_chunk else None
                    for column, storage_column in date_filter_columns.items():
                        if column in normalized_chunk:
                            parsed_dates = pd.to_datetime(
                                normalized_chunk[column],
                                errors="coerce",
                                utc=True,
                            )
                            output_chunk[storage_column] = _sqlite_datetime_text(parsed_dates)
                        else:
                            output_chunk[storage_column] = None
                    _record_load_timing("chunk_build_rows", chunk_build_started_at)
                    metric_stats_started_at = time.perf_counter()
                    _update_metric_stats(
                        metric_stats,
                        output_chunk,
                        source_columns=tuple(source_columns),
                        reserved_columns=tuple(
                            column
                            for column in (chunk_timestamp_field, chunk_reference_field)
                            if column is not None
                        ),
                    )
                    _record_load_timing("metric_stats", metric_stats_started_at)
                    sqlite_write_started_at = time.perf_counter()
                    output_chunk.loc[:, list(storage_columns)].to_sql(
                        _TABULAR_SQLITE_TABLE,
                        connection,
                        if_exists="append",
                        index=False,
                    )
                    _record_load_timing("sqlite_write", sqlite_write_started_at)
                    row_number += chunk_row_count
                    file_row_count += chunk_row_count
                    _emit_tabular_load_progress(
                        progress_callback,
                        stage="chunk_loaded",
                        file=str(path),
                        file_name=path.name,
                        file_index=file_index,
                        file_count=len(file_specs),
                        chunk_rows=chunk_row_count,
                        file_rows_loaded=file_row_count,
                        rows_loaded=row_number,
                    )
                    _raise_if_tabular_load_cancelled(cancel_check)
                    chunk_read_started_at = time.perf_counter()

                source_stat = path.stat()
                snapshots.append(
                    TabularSourceSnapshot(
                        path=str(path),
                        name=path.name,
                        size=int(source_stat.st_size),
                        mtime_ns=int(source_stat.st_mtime_ns),
                        row_count=file_row_count,
                        csv_config=csv_config,
                    )
                )
            _raise_if_tabular_load_cancelled(cancel_check)
            _emit_tabular_load_progress(
                progress_callback,
                stage="indexing",
                rows_loaded=row_number,
                file_count=len(file_specs),
            )
            indexing_started_at = time.perf_counter()
            _create_sqlite_indexes(
                connection,
                _TABULAR_SQLITE_TABLE,
                tuple(
                    dict.fromkeys(
                        column
                        for column in (
                            "source_row_number",
                            "source_file",
                            "process_datetime",
                            "reference",
                            *date_filter_columns.values(),
                            timestamp_field,
                            reference_field,
                        )
                        if column is not None
                    )
                ),
            )
            _record_load_timing("indexing", indexing_started_at)

        _raise_if_tabular_load_cancelled(cancel_check)
        if timestamp_field is not None and bad_timestamp_count:
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="warning",
                    code="tabular_bad_timestamps",
                    message=f"{bad_timestamp_count} table row(s) have invalid timestamps.",
                    context={
                        "timestamp_column": timestamp_field,
                        "bad_timestamp_count": bad_timestamp_count,
                    },
                )
            )
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="tabular_sqlite_store_created",
                message=(
                    f"CSV Summary loaded {row_number} row(s) from {len(paths)} CSV file(s) "
                    "through a temporary SQLite store."
                ),
                context={
                    "row_count": row_number,
                    "source_file_count": len(paths),
                    "sqlite_path": str(db_path),
                },
            )
        )
        metric_candidates_started_at = time.perf_counter()
        metric_candidates = _metric_candidates_from_stats(
            metric_stats,
            numeric_threshold=numeric_threshold,
            min_numeric_count=min_numeric_count,
        )
        _record_load_timing("metric_candidates", metric_candidates_started_at)
        if not metric_candidates:
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="warning",
                    code="tabular_no_numeric_metrics",
                    message="No numeric columns were detected in the selected CSV file(s).",
                )
            )
        store = TabularSqliteStore(
            path=str(db_path),
            table_name=_TABULAR_SQLITE_TABLE,
            columns=table_columns,
            source_columns=tuple(source_columns),
            row_count=row_number,
            date_filter_columns=dict(date_filter_columns),
        )
        _emit_tabular_load_progress(
            progress_callback,
            stage="preview",
            rows_loaded=row_number,
            file_count=len(file_specs),
        )
        _raise_if_tabular_load_cancelled(cancel_check)
        preview_started_at = time.perf_counter()
        preview = store.read_dataframe(limit=TABULAR_SQLITE_PREVIEW_ROWS)
        _record_load_timing("preview", preview_started_at)
        _emit_tabular_load_progress(
            progress_callback,
            stage="complete",
            rows_loaded=row_number,
            file_count=len(file_specs),
            sqlite_path=str(db_path),
        )
        first_snapshot = snapshots[0] if len(snapshots) == 1 else None
        csv_config: dict[str, Any]
        if len(snapshots) == 1:
            csv_config = dict(snapshots[0].csv_config)
        else:
            csv_config = {
                "files": {snapshot.path: dict(snapshot.csv_config) for snapshot in snapshots},
                "storage": "sqlite",
            }
        load_timings["total"] = time.perf_counter() - load_started_at
        return TabularAnalyticsLoadResult(
            dataframe=preview,
            metric_candidates=metric_candidates,
            diagnostics=tuple(diagnostics),
            column_mapping=global_mapping,
            source_file=str(paths[0]),
            sheet_name=None,
            timestamp_column=timestamp_field,
            reference_column=reference_field,
            csv_config=csv_config,
            source_size=first_snapshot.size if first_snapshot is not None else None,
            source_mtime_ns=first_snapshot.mtime_ns if first_snapshot is not None else None,
            source_files=tuple(str(path) for path in paths),
            source_snapshots=tuple(snapshots),
            storage_mode="sqlite",
            sqlite_store=store,
            row_count=row_number,
            load_timings_s=dict(load_timings),
        )
    except Exception:
        for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _detect_csv_config(path: Path) -> dict[str, Any]:
    best_config = detect_csv_read_configs(path)[0]
    return {"delimiter": best_config["delimiter"], "decimal": best_config["decimal"]}


def _raise_if_tabular_load_cancelled(cancel_check: TabularCancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise TabularLoadCancelled("CSV/Excel loading was canceled.")


def _emit_tabular_load_progress(
    progress_callback: TabularProgressCallback | None,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return
    progress_callback(dict(payload))


def _sqlite_date_filter_source_columns(
    dataframe: pd.DataFrame,
    columns: tuple[str, ...],
    *,
    timestamp_field: str | None,
) -> set[str]:
    candidates: set[str] = set()
    for column in columns:
        if column not in dataframe.columns:
            continue
        column_key = column.casefold()
        if column == timestamp_field:
            candidates.add(column)
            continue
        if not any(token in column_key for token in ("date", "time", "timestamp", "created", "updated")):
            continue
        if _looks_like_timestamp_column(dataframe[column]):
            candidates.add(column)
    return candidates


def _sqlite_date_filter_storage_columns(
    source_columns: tuple[str, ...],
    date_filter_source_columns: set[str],
    table_columns: tuple[str, ...],
) -> dict[str, str]:
    used = {column.casefold() for column in table_columns}
    storage_columns: dict[str, str] = {}
    for column in source_columns:
        if column not in date_filter_source_columns:
            continue
        base = f"__date_filter_{_safe_column_name(column, fallback='column')}"
        candidate = base
        suffix = 1
        while candidate.casefold() in used:
            suffix += 1
            candidate = f"{base}_{suffix}"
        used.add(candidate.casefold())
        storage_columns[column] = candidate
    return storage_columns


def _sqlite_datetime_text(series: pd.Series) -> pd.Series:
    text = series.dt.strftime("%Y-%m-%d %H:%M:%S")
    return text.where(series.notna(), None)


def _create_sqlite_table(
    connection: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    column_defs = []
    for column in columns:
        column_type = "INTEGER" if column == "source_row_number" else "TEXT"
        column_defs.append(f"{_quote_identifier(column)} {column_type}")
    connection.execute(
        f"CREATE TABLE {_quote_identifier(table_name)} ({', '.join(column_defs)})"
    )


def _create_sqlite_indexes(
    connection: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    seen: set[str] = set()
    created = False
    for column in columns:
        if column not in seen:
            seen.add(column)
        else:
            continue
        index_name = f"idx_{_safe_column_name(table_name, fallback='table')}_{_safe_column_name(column, fallback='column')}"
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {_quote_identifier(index_name)} "
            f"ON {_quote_identifier(table_name)} ({_quote_identifier(column)})"
        )
        created = True
    if created:
        connection.execute("PRAGMA optimize")


def _create_sqlite_grouping_indexes(
    connection: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    seen: set[str] = set()
    created = False
    for column in columns:
        if column in seen:
            continue
        seen.add(column)
        index_name = (
            f"idx_{_safe_column_name(table_name, fallback='table')}_"
            f"group_{_safe_column_name(column, fallback='column')}"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {_quote_identifier(index_name)} "
            f"ON {_quote_identifier(table_name)} ({_sqlite_normalized_value_expr(column)})"
        )
        created = True
    if created:
        connection.execute("PRAGMA optimize")


def _update_metric_stats(
    metric_stats: dict[str, dict[str, Any]],
    dataframe: pd.DataFrame,
    *,
    source_columns: tuple[str, ...],
    reserved_columns: tuple[str, ...],
) -> None:
    reserved = {
        "source_row_number",
        "source_file",
        "source_sheet",
        "process_datetime",
        "reference",
        *reserved_columns,
    }
    for column in source_columns:
        if column in reserved or column not in dataframe.columns:
            continue
        values = dataframe[column].dropna()
        if values.empty:
            continue
        stats = metric_stats.setdefault(
            column,
            {"non_null_count": 0, "numeric_count": 0, "sample_values": [], "sample_value_set": set()},
        )
        if pd.api.types.is_numeric_dtype(values):
            non_null_count = int(len(values.index))
            stats["non_null_count"] += non_null_count
            stats["numeric_count"] += non_null_count
            _append_metric_sample_values(stats, values)
            continue

        text_values = values.astype(str).str.strip()
        non_blank_mask = text_values != ""
        if not bool(non_blank_mask.any()):
            continue
        values = values[non_blank_mask]
        numeric_values = pd.to_numeric(values, errors="coerce")
        stats["non_null_count"] += int(len(values.index))
        stats["numeric_count"] += int(numeric_values.notna().sum())
        _append_metric_sample_values(stats, values)


def _append_metric_sample_values(stats: dict[str, Any], values: pd.Series) -> None:
    sample_values = stats["sample_values"]
    if len(sample_values) >= 5:
        return
    sample_value_set = stats.setdefault("sample_value_set", set(sample_values))
    for value in values:
        text = str(value)
        if text not in sample_value_set:
            sample_values.append(text)
            sample_value_set.add(text)
        if len(sample_values) >= 5:
            return


def _metric_candidates_from_stats(
    metric_stats: dict[str, dict[str, Any]],
    *,
    numeric_threshold: float,
    min_numeric_count: int,
) -> tuple[ProductionMetricCandidate, ...]:
    candidates: list[ProductionMetricCandidate] = []
    for column, stats in metric_stats.items():
        non_null_count = int(stats.get("non_null_count") or 0)
        numeric_count = int(stats.get("numeric_count") or 0)
        if non_null_count <= 0:
            continue
        numeric_ratio = numeric_count / non_null_count
        if numeric_count < int(min_numeric_count) or numeric_ratio < float(numeric_threshold):
            continue
        warning_flags = ("contains_non_numeric_values",) if numeric_count < non_null_count else ()
        candidates.append(
            ProductionMetricCandidate(
                field_name=column,
                display_label=_display_label_from_column(column),
                source_kind="fixed",
                non_null_count=non_null_count,
                numeric_count=numeric_count,
                numeric_ratio=round(numeric_ratio, 4),
                sample_values=tuple(stats.get("sample_values") or ()),
                warning_flags=warning_flags,
            )
        )
    return tuple(sorted(candidates, key=lambda item: item.display_label.lower()))


def build_tabular_grouping_dataframe(
    dataframe: pd.DataFrame,
    *,
    selector_columns: tuple[str, ...] | list[str] | None = None,
) -> pd.DataFrame:
    """Build DataGrouping-compatible rows from a normalized CSV/Excel analytics frame."""

    columns = ["REPORT_ID", "REFERENCE", "DATE", "SAMPLE_NUMBER", "PART_NAME", "FILENAME"]
    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
        return pd.DataFrame(columns=columns)

    frame = dataframe.copy().reset_index(drop=True)
    row_numbers = _source_row_numbers(frame)
    row_count = len(frame.index)
    references = _display_series(frame.get("reference"), fallback="", row_count=row_count)
    dates = _date_display_series(frame.get("process_datetime"), len(frame.index))
    filenames = _display_series(frame.get("source_file"), fallback="", row_count=row_count)
    sheet_names = _display_series(frame.get("source_sheet"), fallback="", row_count=row_count)
    source_labels = [
        " | ".join(part for part in (filename, f"Sheet: {sheet}" if sheet else "") if part)
        for filename, sheet in zip(filenames, sheet_names, strict=False)
    ]
    selectors = [
        column
        for column in (selector_columns or ())
        if column in frame.columns
    ]
    if selectors:
        selector_labels = _selector_display_labels(
            frame,
            selectors=tuple(selectors),
            row_numbers=row_numbers,
        )
    else:
        selector_labels = [
            reference if reference else f"Row {row_number}"
            for reference, row_number in zip(references, row_numbers, strict=False)
        ]
    return pd.DataFrame(
        {
            "REPORT_ID": row_numbers,
            "REFERENCE": selector_labels,
            "DATE": dates,
            "SAMPLE_NUMBER": [str(row_number) for row_number in row_numbers],
            "PART_NAME": selector_labels,
            "FILENAME": source_labels,
        },
        columns=columns,
    )


def tabular_file_group_labels(
    source_files: tuple[str | Path, ...] | list[str | Path],
    *,
    default_group: str = TABULAR_DEFAULT_GROUP,
) -> tuple[tuple[str, str], ...]:
    """Return deterministic display group labels for CSV Summary source files."""

    labels: list[tuple[str, str]] = []
    used: set[str] = set()
    for source_file in source_files or ():
        path = Path(source_file)
        source_name = path.name or str(source_file)
        base_label = path.stem.strip() or source_name.strip() or "File"
        if base_label.casefold() == default_group.casefold():
            base_label = f"{default_group} file"
        candidate = base_label
        suffix = 2
        while candidate.casefold() in used:
            candidate = f"{base_label} {suffix}"
            suffix += 1
        used.add(candidate.casefold())
        labels.append((source_name, candidate))
    return tuple(labels)


def build_tabular_file_grouping_dataframe(
    dataframe: pd.DataFrame | None = None,
    *,
    source_files: tuple[str | Path, ...] | list[str | Path] | None = None,
    source_snapshots: tuple[TabularSourceSnapshot, ...] | list[TabularSourceSnapshot] | None = None,
    default_group: str = TABULAR_DEFAULT_GROUP,
) -> pd.DataFrame:
    """Build manual grouping rows that assign each CSV Summary row to its source file."""

    columns = ["REPORT_ID", "GROUP"]
    snapshots = tuple(source_snapshots or ())
    if snapshots:
        labels = tabular_file_group_labels(
            tuple(snapshot.path or snapshot.name for snapshot in snapshots),
            default_group=default_group,
        )
        report_ids: list[int] = []
        groups: list[str] = []
        next_report_id = 1
        for snapshot, (_source_name, group_label) in zip(snapshots, labels, strict=False):
            row_count = max(0, int(snapshot.row_count or 0))
            if row_count:
                report_ids.extend(range(next_report_id, next_report_id + row_count))
                groups.extend([group_label] * row_count)
            next_report_id += row_count
        return pd.DataFrame({"REPORT_ID": report_ids, "GROUP": groups}, columns=columns)

    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty or "source_file" not in dataframe.columns:
        return pd.DataFrame(columns=columns)

    frame = dataframe.loc[:, ["source_file"]].copy().reset_index(drop=True)
    row_numbers = _source_row_numbers(dataframe.reset_index(drop=True))
    source_names = _display_series(frame.get("source_file"), fallback="File", row_count=len(frame.index))
    ordered_sources = tuple(dict.fromkeys(source_names))
    source_file_order = tuple(source_files or ordered_sources)
    labels_by_source = {
        source_name: group_label
        for source_name, group_label in tabular_file_group_labels(
            source_file_order,
            default_group=default_group,
        )
    }
    groups = [
        labels_by_source.get(source_name, labels_by_source.get(Path(source_name).name, "File"))
        for source_name in source_names
    ]
    return pd.DataFrame({"REPORT_ID": row_numbers, "GROUP": groups}, columns=columns)


def _selector_display_labels(
    frame: pd.DataFrame,
    *,
    selectors: tuple[str, ...],
    row_numbers: list[int],
) -> list[str]:
    if not selectors:
        return [f"Row {row_number}" for row_number in row_numbers]
    labels = pd.Series("", index=frame.index, dtype="string")
    for column in selectors:
        values = frame[column].where(~frame[column].isna(), "").astype(str).str.strip()
        values = values.mask(values == "", "")
        has_label = labels.str.len().fillna(0).gt(0)
        has_value = values.str.len().fillna(0).gt(0)
        labels = labels.mask(has_label & has_value, labels + " | " + values)
        labels = labels.mask(~has_label & has_value, values)
    fallback = pd.Series(
        [f"Row {row_number}" for row_number in row_numbers],
        index=frame.index,
        dtype="string",
    )
    selector_labels = labels.where(labels.str.len().fillna(0).gt(0), fallback).tolist()
    return [str(label) for label in selector_labels]


def apply_tabular_row_filter(
    dataframe: pd.DataFrame,
    *,
    filter_columns: tuple[str, ...] | list[str] | None = None,
    selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
    column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
    required_columns: tuple[str, ...] | list[str] | None = None,
) -> TabularFilterResult:
    """Filter normalized CSV/Excel analytics rows by selected column-value keys."""

    if not isinstance(dataframe, pd.DataFrame):
        return TabularFilterResult(dataframe=pd.DataFrame())

    input_count = int(len(dataframe.index))
    normalized_column_filters = _normalized_tabular_column_filters(dataframe, column_filters)
    if normalized_column_filters:
        mask = pd.Series(True, index=dataframe.index)
        for column_filter in normalized_column_filters:
            column_mask = pd.Series(True, index=dataframe.index)
            if column_filter.selected_values:
                selected_values = set(column_filter.selected_values)
                column_values = _normalized_tabular_filter_series(dataframe[column_filter.column])
                column_mask &= column_values.isin(selected_values)
            if column_filter.has_date_filter:
                column_mask &= _tabular_date_filter_mask(dataframe[column_filter.column], column_filter)
            if column_filter.has_numeric_filter:
                column_mask &= _tabular_numeric_filter_mask(dataframe[column_filter.column], column_filter)
            mask &= column_mask.fillna(False)
        filtered = dataframe.loc[mask].copy()
        output_count = int(len(filtered.index))
        diagnostic = ProductionAnalyticsDiagnostic(
            severity="info",
            code="tabular_filters_applied",
            message=f"CSV/Excel row filter reduced rows from {input_count} to {output_count}.",
            context={
                "column_filters": [
                    {
                        "column": item.column,
                        "selected_value_count": len(item.selected_values),
                        "date_mode": item.date_mode,
                        "date_from": item.date_from,
                        "date_to": item.date_to,
                        "date_operator": item.date_operator,
                        "date_value": item.date_value,
                        "numeric_operator": item.numeric_operator,
                        "numeric_value": _parse_tabular_filter_number(item.numeric_value),
                    }
                    for item in normalized_column_filters
                ],
                "input_row_count": input_count,
                "output_row_count": output_count,
            },
        )
        return TabularFilterResult(
            dataframe=_project_tabular_dataframe(filtered, required_columns).reset_index(drop=True),
            diagnostics=(diagnostic,),
            applied=True,
            input_row_count=input_count,
            output_row_count=output_count,
        )

    columns = tuple(column for column in (filter_columns or ()) if column in dataframe.columns)
    selected_keys = tuple(
        tuple(str(part) for part in key)
        for key in (selected_filter_keys or ())
        if isinstance(key, (list, tuple)) and len(key) == len(columns)
    )
    if not columns or not selected_keys:
        return TabularFilterResult(
            dataframe=_project_tabular_dataframe(dataframe, required_columns),
            applied=False,
            input_row_count=input_count,
            output_row_count=input_count,
        )

    filtered = filter_csv_summary_by_group_keys(dataframe, columns, selected_keys)
    output_count = int(len(filtered.index))
    diagnostic = ProductionAnalyticsDiagnostic(
        severity="info",
        code="tabular_filters_applied",
        message=f"CSV/Excel row filter reduced rows from {input_count} to {output_count}.",
        context={
            "filter_columns": list(columns),
            "selected_filter_count": len(selected_keys),
            "input_row_count": input_count,
            "output_row_count": output_count,
        },
    )
    return TabularFilterResult(
        dataframe=_project_tabular_dataframe(filtered, required_columns).reset_index(drop=True),
        diagnostics=(diagnostic,),
        applied=True,
        input_row_count=input_count,
        output_row_count=output_count,
    )


def materialize_tabular_dataframe(
    loaded: TabularAnalyticsLoadResult,
    *,
    filter_columns: tuple[str, ...] | list[str] | None = None,
    selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
    column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
    required_columns: tuple[str, ...] | list[str] | None = None,
) -> TabularFilterResult:
    """Return rows for analytics, using SQLite pushdown when the load result has a store."""

    if loaded.sqlite_store is None:
        return apply_tabular_row_filter(
            loaded.dataframe,
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            column_filters=column_filters,
            required_columns=required_columns,
        )

    normalized_filters = _normalized_tabular_column_filters_for_columns(
        loaded.sqlite_store.columns,
        column_filters,
    )
    legacy_columns = tuple(
        column for column in (filter_columns or ()) if column in loaded.sqlite_store.columns
    )
    legacy_keys = tuple(
        tuple(str(part) for part in key)
        for key in (selected_filter_keys or ())
        if isinstance(key, (list, tuple)) and len(key) == len(legacy_columns)
    )
    is_applied = bool(normalized_filters or (legacy_columns and legacy_keys))
    dataframe = loaded.sqlite_store.read_dataframe(
        filter_columns=legacy_columns,
        selected_filter_keys=legacy_keys,
        column_filters=normalized_filters,
        columns=required_columns,
    )
    input_count = int(loaded.sqlite_store.row_count)
    output_count = int(len(dataframe.index))
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    if is_applied:
        context: dict[str, Any] = {
            "input_row_count": input_count,
            "output_row_count": output_count,
        }
        if normalized_filters:
            context["column_filters"] = [
                {
                    "column": item.column,
                    "selected_value_count": len(item.selected_values),
                    "date_mode": item.date_mode,
                    "date_from": item.date_from,
                    "date_to": item.date_to,
                    "date_operator": item.date_operator,
                    "date_value": item.date_value,
                    "numeric_operator": item.numeric_operator,
                    "numeric_value": _parse_tabular_filter_number(item.numeric_value),
                }
                for item in normalized_filters
            ]
        else:
            context["filter_columns"] = list(legacy_columns)
            context["selected_filter_count"] = len(legacy_keys)
        diagnostics = (
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="tabular_filters_applied",
                message=f"CSV/Excel row filter reduced rows from {input_count} to {output_count}.",
                context=context,
            ),
        )
    return TabularFilterResult(
        dataframe=dataframe.reset_index(drop=True),
        diagnostics=diagnostics,
        applied=is_applied,
        input_row_count=input_count,
        output_row_count=output_count,
    )


def count_tabular_materialized_rows(
    loaded: TabularAnalyticsLoadResult,
    *,
    filter_columns: tuple[str, ...] | list[str] | None = None,
    selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
    column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
) -> int:
    """Count rows matching CSV Summary filters without loading every row when possible."""

    if loaded.sqlite_store is not None:
        return loaded.sqlite_store.count_rows(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            column_filters=column_filters,
        )
    return int(
        len(
            apply_tabular_row_filter(
                loaded.dataframe,
                filter_columns=filter_columns,
                selected_filter_keys=selected_filter_keys,
                column_filters=column_filters,
            ).dataframe.index
        )
    )


def cleanup_tabular_load_result(loaded: TabularAnalyticsLoadResult | None) -> None:
    """Remove temporary files owned by a tabular load result."""

    if loaded is not None and loaded.sqlite_store is not None:
        loaded.sqlite_store.cleanup()


def tabular_load_result_row_count(loaded: TabularAnalyticsLoadResult | None) -> int:
    if loaded is None:
        return 0
    if loaded.row_count is not None:
        return int(loaded.row_count)
    if loaded.sqlite_store is not None:
        return int(loaded.sqlite_store.row_count)
    return int(len(loaded.dataframe.index))


def _normalized_tabular_column_filters(
    dataframe: pd.DataFrame,
    column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None,
) -> tuple[TabularColumnFilter, ...]:
    return _normalized_tabular_column_filters_for_columns(dataframe.columns, column_filters)


def _normalized_tabular_column_filters_for_columns(
    columns,
    column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None,
) -> tuple[TabularColumnFilter, ...]:
    column_lookup = {str(column) for column in columns}
    normalized: list[TabularColumnFilter] = []
    seen: set[str] = set()
    for item in column_filters or ():
        if not isinstance(item, TabularColumnFilter):
            continue
        column = str(item.column or "").strip()
        if column not in column_lookup or column in seen:
            continue
        selected_values = tuple(
            dict.fromkeys(
                (str(value).strip() if value is not None else "") or "(blank)"
                for value in item.selected_values
            )
        )
        date_mode = item.date_mode if item.date_mode in {"from", "to", "between"} else "any"
        date_operator = str(item.date_operator or "").strip()
        if date_operator not in _TABULAR_DATE_OPERATORS:
            date_operator = None
        numeric_operator = str(item.numeric_operator or "").strip()
        if numeric_operator not in _TABULAR_NUMERIC_OPERATORS:
            numeric_operator = None
        numeric_value = _parse_tabular_filter_number(item.numeric_value)
        normalized_filter = TabularColumnFilter(
            column=column,
            selected_values=selected_values,
            date_mode=date_mode,
            date_from=str(item.date_from or "").strip() or None,
            date_to=str(item.date_to or "").strip() or None,
            date_operator=date_operator,
            date_value=str(item.date_value or "").strip() or None,
            numeric_operator=numeric_operator,
            numeric_value=numeric_value,
        )
        if normalized_filter.is_active:
            normalized.append(normalized_filter)
            seen.add(column)
    return tuple(normalized)


def _normalized_tabular_required_columns(
    available_columns,
    required_columns: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    available = tuple(str(column) for column in available_columns)
    if required_columns is None:
        return available
    available_lookup = set(available)
    selected = tuple(
        dict.fromkeys(str(column) for column in required_columns if str(column) in available_lookup)
    )
    return selected or available


def _project_tabular_dataframe(
    dataframe: pd.DataFrame,
    required_columns: tuple[str, ...] | list[str] | None,
) -> pd.DataFrame:
    if required_columns is None:
        return dataframe.copy()
    columns = _normalized_tabular_required_columns(dataframe.columns, required_columns)
    return dataframe.loc[:, list(columns)].copy()


def _restore_sqlite_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    if "process_datetime" in dataframe.columns:
        dataframe["process_datetime"] = pd.to_datetime(
            dataframe["process_datetime"],
            errors="coerce",
            utc=True,
        )
    if "source_row_number" in dataframe.columns:
        dataframe["source_row_number"] = pd.to_numeric(
            dataframe["source_row_number"],
            errors="coerce",
        ).astype("Int64")
    return dataframe


def _sqlite_like_pattern(
    value: str,
    *,
    match_mode: str = "contains",
    casefold: bool = True,
) -> str:
    text = str(value or "")
    if casefold:
        text = text.casefold()
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if match_mode == "starts_with":
        return f"{escaped}%"
    if match_mode == "ends_with":
        return f"%{escaped}"
    return f"%{escaped}%"


def _sqlite_group_key_predicate(
    columns: tuple[str, ...],
    selected_keys: tuple[tuple[str, ...], ...],
    params: list[Any],
) -> str:
    if len(columns) == 1:
        expression = _sqlite_normalized_value_expr(columns[0])
        values = [str(key[0]) for key in selected_keys]
        clauses: list[str] = []
        for start in range(0, len(values), 900):
            chunk = values[start : start + 900]
            placeholders = ", ".join("?" for _value in chunk)
            clauses.append(f"{expression} IN ({placeholders})")
            params.extend(chunk)
        return f"({' OR '.join(clauses)})"

    key_clauses: list[str] = []
    for key in selected_keys:
        parts = []
        for column, value in zip(columns, key, strict=False):
            parts.append(f"{_sqlite_normalized_value_expr(column)} = ?")
            params.append(str(value))
        key_clauses.append(f"({' AND '.join(parts)})")
    return f"({' OR '.join(key_clauses)})"


def _sqlite_normalized_value_expr(column: str) -> str:
    identifier = _quote_identifier(column)
    return f"COALESCE(NULLIF(TRIM(CAST({identifier} AS TEXT)), ''), '(blank)')"


def compile_tabular_sqlite_grouping_filter(
    available_columns: Iterable[str],
    grouping_filter: Any = None,
    *,
    grouping_filter_expression: str | None = None,
    grouping_filter_aliases: Mapping[str, str] | None = None,
    date_filter_columns: Mapping[str, str] | None = None,
) -> TabularSqliteFilterExpression:
    """Compile shared grouping filters into a SQLite predicate fragment.

    The returned object contains a WHERE-clause fragment without the ``WHERE`` keyword.
    Column names are resolved against ``available_columns`` or explicit aliases, and
    user values are always emitted as bound parameters.
    """

    columns = tuple(str(column) for column in available_columns)
    aliases = _normalize_sqlite_filter_aliases(columns, grouping_filter_aliases)
    compiled_filters: list[TabularSqliteFilterExpression] = []

    if grouping_filter is not None:
        compiled_filters.extend(
            _compile_sqlite_grouping_filter_input(
                grouping_filter,
                columns=columns,
                aliases=aliases,
                date_filter_columns=date_filter_columns,
            )
        )

    raw_expression = str(grouping_filter_expression or "").strip()
    if raw_expression:
        if _parse_grouping_filter_expression is None:
            raise RuntimeError(
                "Raw SQLite grouping filter expressions require "
                "metroliza.shared.grouping_filter_core.parse_filter_expression."
            )
        parse_columns = tuple(dict.fromkeys((*columns, *aliases.keys())))
        parsed_filter = _parse_grouping_filter_expression(
            raw_expression,
            parse_columns,
            aliases=aliases,
        )
        compiled_filters.extend(
            _compile_sqlite_grouping_filter_input(
                parsed_filter,
                columns=columns,
                aliases=aliases,
                date_filter_columns=date_filter_columns,
            )
        )

    return _combine_sqlite_filter_expressions(compiled_filters, joiner="AND")


def _compile_sqlite_grouping_filter_input(
    grouping_filter: Any,
    *,
    columns: tuple[str, ...],
    aliases: Mapping[str, str],
    date_filter_columns: Mapping[str, str] | None,
) -> tuple[TabularSqliteFilterExpression, ...]:
    if isinstance(grouping_filter, TabularSqliteFilterExpression):
        return (
            _validate_compiled_sqlite_filter(
                grouping_filter,
                columns=columns,
                aliases=aliases,
                date_filter_columns=date_filter_columns,
            ),
        )
    if isinstance(grouping_filter, str):
        return (
            compile_tabular_sqlite_grouping_filter(
                columns,
                grouping_filter_expression=grouping_filter,
                grouping_filter_aliases=aliases,
                date_filter_columns=date_filter_columns,
            ),
        )
    compiled_sql_filter = _compiled_sqlite_filter_from_object(
        grouping_filter,
        columns=columns,
        aliases=aliases,
        date_filter_columns=date_filter_columns,
    )
    if compiled_sql_filter is not None:
        return (compiled_sql_filter,)

    if hasattr(grouping_filter, "specs"):
        expression = getattr(grouping_filter, "expression", None)
        if expression is not None:
            return (
                _compile_sqlite_filter_spec(
                    expression,
                    columns=columns,
                    aliases=aliases,
                    date_filter_columns=date_filter_columns,
                ),
            )
        return (
            _compile_sqlite_filter_specs(
                getattr(grouping_filter, "specs"),
                match_mode=getattr(grouping_filter, "match_mode", "and"),
                columns=columns,
                aliases=aliases,
                date_filter_columns=date_filter_columns,
            ),
        )

    if _is_filter_spec_iterable(grouping_filter):
        return (
            _compile_sqlite_filter_specs(
                grouping_filter,
                match_mode=getattr(grouping_filter, "match_mode", "and"),
                columns=columns,
                aliases=aliases,
                date_filter_columns=date_filter_columns,
            ),
        )

    return (
        _compile_sqlite_filter_specs(
            (grouping_filter,),
            match_mode="and",
            columns=columns,
            aliases=aliases,
            date_filter_columns=date_filter_columns,
        ),
    )


def _compile_sqlite_filter_specs(
    specs: Iterable[Any],
    *,
    match_mode: str,
    columns: tuple[str, ...],
    aliases: Mapping[str, str],
    date_filter_columns: Mapping[str, str] | None,
) -> TabularSqliteFilterExpression:
    compiled_terms: list[TabularSqliteFilterExpression] = []
    for spec in specs or ():
        compiled_terms.append(
            _compile_sqlite_filter_spec(
                spec,
                columns=columns,
                aliases=aliases,
                date_filter_columns=date_filter_columns,
            )
        )
    mode = "OR" if str(match_mode or "").strip().casefold() == "or" else "AND"
    return _combine_sqlite_filter_expressions(compiled_terms, joiner=mode)


def _compile_sqlite_filter_spec(
    spec: Any,
    *,
    columns: tuple[str, ...],
    aliases: Mapping[str, str],
    date_filter_columns: Mapping[str, str] | None,
) -> TabularSqliteFilterExpression:
    children = getattr(spec, "children", None)
    operator = str(getattr(spec, "operator", "")).strip().casefold()
    if children is not None and operator in {"and", "or"}:
        compiled_children = [
            _compile_sqlite_filter_spec(
                child,
                columns=columns,
                aliases=aliases,
                date_filter_columns=date_filter_columns,
            )
            for child in children
        ]
        return _combine_sqlite_filter_expressions(
            compiled_children,
            joiner="OR" if operator == "or" else "AND",
        )
    column = _resolve_sqlite_filter_column(getattr(spec, "column", ""), columns, aliases)
    spec_type = _sqlite_filter_spec_type(spec, operator)
    if spec_type == "text":
        return _compile_sqlite_text_filter_spec(spec, column, operator)
    if spec_type == "membership":
        return _compile_sqlite_membership_filter_spec(spec, column, operator, date_filter_columns)
    if spec_type == "number":
        return _compile_sqlite_number_filter_spec(spec, column, operator)
    if spec_type == "date":
        return _compile_sqlite_date_filter_spec(spec, column, operator, date_filter_columns)
    raise TypeError(f"Unsupported SQLite grouping filter spec: {type(spec).__name__}")


def _compile_sqlite_text_filter_spec(
    spec: Any,
    column: str,
    operator: str,
) -> TabularSqliteFilterExpression:
    if operator not in _SQLITE_TEXT_FILTER_OPERATORS:
        raise ValueError(f"Unsupported text filter operator: {operator}")
    identifier = _quote_identifier(column)
    text_expr = f"CAST({identifier} AS TEXT)"
    case_sensitive = bool(getattr(spec, "case_sensitive", False))
    compare_expr = text_expr if case_sensitive else f"LOWER({text_expr})"
    value = "" if getattr(spec, "value", None) is None else str(getattr(spec, "value"))
    compare_value = value if case_sensitive else value.casefold()

    if operator == "contains":
        return TabularSqliteFilterExpression(
            clause=f"({identifier} IS NOT NULL AND {compare_expr} LIKE ? ESCAPE '\\')",
            params=(
                _sqlite_like_pattern(compare_value, match_mode="contains", casefold=False),
            ),
            columns=(column,),
        )
    if operator == "not_contains":
        return TabularSqliteFilterExpression(
            clause=f"({identifier} IS NULL OR {compare_expr} NOT LIKE ? ESCAPE '\\')",
            params=(
                _sqlite_like_pattern(compare_value, match_mode="contains", casefold=False),
            ),
            columns=(column,),
        )
    if operator in {"equals", "eq"}:
        if bool(getattr(spec, "wildcards", False)) and "*" in compare_value:
            return TabularSqliteFilterExpression(
                clause=f"({identifier} IS NOT NULL AND {compare_expr} LIKE ? ESCAPE '\\')",
                params=(_sqlite_wildcard_like_pattern(compare_value),),
                columns=(column,),
            )
        return TabularSqliteFilterExpression(
            clause=f"({identifier} IS NOT NULL AND {compare_expr} = ?)",
            params=(compare_value,),
            columns=(column,),
        )
    if operator in {"not_equals", "ne"}:
        if bool(getattr(spec, "wildcards", False)) and "*" in compare_value:
            return TabularSqliteFilterExpression(
                clause=f"({identifier} IS NULL OR {compare_expr} NOT LIKE ? ESCAPE '\\')",
                params=(_sqlite_wildcard_like_pattern(compare_value),),
                columns=(column,),
            )
        return TabularSqliteFilterExpression(
            clause=f"({identifier} IS NULL OR {compare_expr} != ?)",
            params=(compare_value,),
            columns=(column,),
        )
    if operator == "starts_with":
        return TabularSqliteFilterExpression(
            clause=f"({identifier} IS NOT NULL AND {compare_expr} LIKE ? ESCAPE '\\')",
            params=(
                _sqlite_like_pattern(compare_value, match_mode="starts_with", casefold=False),
            ),
            columns=(column,),
        )
    if operator == "ends_with":
        return TabularSqliteFilterExpression(
            clause=f"({identifier} IS NOT NULL AND {compare_expr} LIKE ? ESCAPE '\\')",
            params=(
                _sqlite_like_pattern(compare_value, match_mode="ends_with", casefold=False),
            ),
            columns=(column,),
        )
    if operator == "is_blank":
        return TabularSqliteFilterExpression(
            clause=f"({identifier} IS NULL OR TRIM({text_expr}) = '')",
            columns=(column,),
        )
    return TabularSqliteFilterExpression(
        clause=f"({identifier} IS NOT NULL AND TRIM({text_expr}) != '')",
        columns=(column,),
    )


def _compile_sqlite_membership_filter_spec(
    spec: Any,
    column: str,
    operator: str,
    date_filter_columns: Mapping[str, str] | None,
) -> TabularSqliteFilterExpression:
    values = _sqlite_membership_values(getattr(spec, "values", ()))
    if not values:
        raise ValueError("IN filters require at least one value")
    negate = bool(getattr(spec, "negate", False)) or operator == "not_in"
    value_kind = _sqlite_membership_value_kind(
        values,
        dayfirst=bool(getattr(spec, "dayfirst", False)),
    )
    if value_kind == "number":
        return _compile_sqlite_numeric_membership_filter_spec(spec, column, values, negate)
    if value_kind == "date":
        return _compile_sqlite_date_membership_filter_spec(
            spec,
            column,
            values,
            negate,
            date_filter_columns,
        )
    return _compile_sqlite_text_membership_filter_spec(spec, column, values, negate)


def _compile_sqlite_text_membership_filter_spec(
    spec: Any,
    column: str,
    values: tuple[Any, ...],
    negate: bool,
) -> TabularSqliteFilterExpression:
    identifier = _quote_identifier(column)
    text_expr = f"CAST({identifier} AS TEXT)"
    case_sensitive = bool(getattr(spec, "case_sensitive", False))
    compare_expr = text_expr if case_sensitive else f"LOWER({text_expr})"
    normalized_values = tuple(str(value) for value in values)
    if not case_sensitive:
        normalized_values = tuple(value.casefold() for value in normalized_values)
    use_wildcards = bool(getattr(spec, "wildcards", True))
    exact_values = tuple(
        value for value in normalized_values if not (use_wildcards and "*" in value)
    )
    wildcard_values = tuple(value for value in normalized_values if use_wildcards and "*" in value)

    params: list[Any] = []
    terms: list[str] = []
    if exact_values:
        in_clause, in_params = _sqlite_membership_in_predicate(
            compare_expr,
            exact_values,
            negate=negate,
        )
        terms.append(in_clause)
        params.extend(in_params)
    like_operator = "NOT LIKE" if negate else "LIKE"
    for value in wildcard_values:
        terms.append(f"{compare_expr} {like_operator} ? ESCAPE '\\'")
        params.append(_sqlite_wildcard_like_pattern(value))

    if not terms:
        clause = f"{identifier} IS NULL" if negate else "0"
    elif negate:
        clause = f"({identifier} IS NULL OR ({' AND '.join(terms)}))"
    else:
        clause = f"({identifier} IS NOT NULL AND ({' OR '.join(terms)}))"
    return TabularSqliteFilterExpression(clause=clause, params=tuple(params), columns=(column,))


def _compile_sqlite_numeric_membership_filter_spec(
    spec: Any,
    column: str,
    values: tuple[Any, ...],
    negate: bool,
) -> TabularSqliteFilterExpression:
    del spec
    text_expr, numeric_guard = _sqlite_numeric_text_and_guard(column)
    parsed_values = tuple(
        _sqlite_filter_number_value(value, field_name="IN value")
        for value in values
    )
    predicate, params = _sqlite_membership_in_predicate(
        f"CAST({text_expr} AS REAL)",
        parsed_values,
        negate=negate,
    )
    if negate:
        clause = f"((NOT ({numeric_guard})) OR {predicate})"
    else:
        clause = f"(({numeric_guard}) AND {predicate})"
    return TabularSqliteFilterExpression(clause=clause, params=tuple(params), columns=(column,))


def _compile_sqlite_date_membership_filter_spec(
    spec: Any,
    column: str,
    values: tuple[Any, ...],
    negate: bool,
    date_filter_columns: Mapping[str, str] | None,
) -> TabularSqliteFilterExpression:
    dayfirst = bool(getattr(spec, "dayfirst", False))
    parsed_values = tuple(
        _sqlite_filter_date_value(value, dayfirst=dayfirst, field_name="IN value").isoformat()
        for value in values
    )
    date_expr = _sqlite_date_filter_expr_for_column(column, date_filter_columns)
    predicate, params = _sqlite_membership_in_predicate(
        date_expr,
        parsed_values,
        negate=negate,
        placeholder_sql="date(?)",
    )
    if negate:
        clause = f"({date_expr} IS NULL OR {predicate})"
    else:
        clause = f"({predicate})"
    return TabularSqliteFilterExpression(clause=clause, params=tuple(params), columns=(column,))


def _compile_sqlite_number_filter_spec(
    spec: Any,
    column: str,
    operator: str,
) -> TabularSqliteFilterExpression:
    text_expr, numeric_guard = _sqlite_numeric_text_and_guard(column)
    if operator == "is_blank":
        return TabularSqliteFilterExpression(clause=f"(NOT ({numeric_guard}))", columns=(column,))
    if operator == "is_not_blank":
        return TabularSqliteFilterExpression(clause=f"({numeric_guard})", columns=(column,))

    if operator == "between":
        value = _sqlite_filter_number_value(getattr(spec, "value", None), field_name="value")
        second_value = _sqlite_filter_number_value(
            getattr(spec, "second_value", None),
            field_name="second_value",
        )
        lower, upper = sorted((value, second_value))
        return TabularSqliteFilterExpression(
            clause=f"(({numeric_guard}) AND CAST({text_expr} AS REAL) BETWEEN ? AND ?)",
            params=(lower, upper),
            columns=(column,),
        )

    sql_operator = _SQLITE_NUMBER_OPERATOR_SQL.get(operator)
    if sql_operator is None:
        raise ValueError(f"Unsupported number filter operator: {operator}")
    value = _sqlite_filter_number_value(getattr(spec, "value", None), field_name="value")
    if sql_operator == "!=":
        clause = f"((NOT ({numeric_guard})) OR CAST({text_expr} AS REAL) != ?)"
    else:
        clause = f"(({numeric_guard}) AND CAST({text_expr} AS REAL) {sql_operator} ?)"
    return TabularSqliteFilterExpression(clause=clause, params=(value,), columns=(column,))


def _compile_sqlite_date_filter_spec(
    spec: Any,
    column: str,
    operator: str,
    date_filter_columns: Mapping[str, str] | None,
) -> TabularSqliteFilterExpression:
    date_expr = _sqlite_date_filter_expr_for_column(column, date_filter_columns)
    if operator == "is_blank":
        return TabularSqliteFilterExpression(clause=f"({date_expr} IS NULL)", columns=(column,))
    if operator == "is_not_blank":
        return TabularSqliteFilterExpression(clause=f"({date_expr} IS NOT NULL)", columns=(column,))

    dayfirst = bool(getattr(spec, "dayfirst", False))
    if operator == "between":
        value = _sqlite_filter_date_value(
            getattr(spec, "value", None),
            dayfirst=dayfirst,
            field_name="value",
        )
        second_value = _sqlite_filter_date_value(
            getattr(spec, "second_value", None),
            dayfirst=dayfirst,
            field_name="second_value",
        )
        lower, upper = sorted((value, second_value))
        return TabularSqliteFilterExpression(
            clause=f"({date_expr} BETWEEN date(?) AND date(?))",
            params=(lower.isoformat(), upper.isoformat()),
            columns=(column,),
        )

    sql_operator = _SQLITE_DATE_OPERATOR_SQL.get(operator)
    if sql_operator is None:
        raise ValueError(f"Unsupported date filter operator: {operator}")
    value = _sqlite_filter_date_value(
        getattr(spec, "value", None),
        dayfirst=dayfirst,
        field_name="value",
    )
    if sql_operator == "!=":
        clause = f"({date_expr} IS NULL OR {date_expr} != date(?))"
    else:
        clause = f"({date_expr} {sql_operator} date(?))"
    return TabularSqliteFilterExpression(
        clause=clause,
        params=(value.isoformat(),),
        columns=(column,),
    )


def _combine_sqlite_filter_expressions(
    filters: Iterable[TabularSqliteFilterExpression],
    *,
    joiner: str,
) -> TabularSqliteFilterExpression:
    active = tuple(filter_expr for filter_expr in filters if filter_expr.clause)
    if not active:
        return TabularSqliteFilterExpression()
    params: list[Any] = []
    columns: list[str] = []
    clauses: list[str] = []
    for filter_expr in active:
        clauses.append(filter_expr.clause)
        params.extend(filter_expr.params)
        columns.extend(filter_expr.columns)
    if len(clauses) == 1:
        clause = clauses[0]
    else:
        joiner_text = f" {joiner} "
        clause = f"({joiner_text.join(clauses)})"
    return TabularSqliteFilterExpression(
        clause=clause,
        params=tuple(params),
        columns=tuple(dict.fromkeys(columns)),
    )


def _compiled_sqlite_filter_from_object(
    grouping_filter: Any,
    *,
    columns: tuple[str, ...],
    aliases: Mapping[str, str],
    date_filter_columns: Mapping[str, str] | None,
) -> TabularSqliteFilterExpression | None:
    clause = None
    for attr in _COMPILED_SQLITE_FILTER_SQL_ATTRS:
        value = getattr(grouping_filter, attr, None)
        if value is not None:
            clause = str(value)
            break
    if clause is None:
        return None

    params = getattr(grouping_filter, "params", getattr(grouping_filter, "parameters", ()))
    referenced_columns: tuple[str, ...] = ()
    for attr in _COMPILED_SQLITE_FILTER_COLUMN_ATTRS:
        value = getattr(grouping_filter, attr, None)
        if value:
            referenced_columns = tuple(str(column) for column in value)
            break
    if not referenced_columns:
        raise ValueError("Compiled SQLite grouping filters must declare referenced columns.")
    return _validate_compiled_sqlite_filter(
        TabularSqliteFilterExpression(
            clause=clause,
            params=tuple(params or ()),
            columns=referenced_columns,
        ),
        columns=columns,
        aliases=aliases,
        date_filter_columns=date_filter_columns,
    )


def _validate_compiled_sqlite_filter(
    compiled_filter: TabularSqliteFilterExpression,
    *,
    columns: tuple[str, ...],
    aliases: Mapping[str, str],
    date_filter_columns: Mapping[str, str] | None,
) -> TabularSqliteFilterExpression:
    clause = str(compiled_filter.clause or "").strip()
    if clause.upper().startswith("WHERE "):
        clause = clause[6:].strip()
    if not clause:
        return TabularSqliteFilterExpression()
    if any(token in clause for token in (";", "--", "/*", "*/")):
        raise ValueError("Compiled SQLite grouping filter contains unsafe SQL.")
    if clause.count("?") != len(compiled_filter.params):
        raise ValueError("Compiled SQLite grouping filter must use bound parameters.")

    resolved_columns = tuple(
        dict.fromkeys(
            _resolve_sqlite_filter_column(column, columns, aliases)
            for column in compiled_filter.columns
        )
    )
    quoted_identifiers = {
        identifier.replace('""', '"')
        for identifier in re.findall(r'"((?:[^"]|"")*)"', clause)
    }
    allowed_sql_identifiers = {*columns, *(date_filter_columns or {}).values()}
    unknown_identifiers = quoted_identifiers.difference(allowed_sql_identifiers)
    if unknown_identifiers:
        raise KeyError(f"SQLite grouping filter column not allowed: {sorted(unknown_identifiers)[0]}")
    return TabularSqliteFilterExpression(
        clause=f"({clause})",
        params=tuple(compiled_filter.params),
        columns=resolved_columns,
    )


def _sqlite_filter_spec_type(spec: Any, operator: str) -> str:
    spec_kind = str(
        getattr(spec, "kind", getattr(spec, "filter_type", getattr(spec, "value_type", "")))
    ).casefold()
    class_name = type(spec).__name__.casefold()
    if "membership" in spec_kind or "membership" in class_name or operator in {"in", "not_in"}:
        return "membership"
    if "text" in spec_kind or "text" in class_name or operator in {
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
    }:
        return "text"
    if "number" in spec_kind or "numeric" in spec_kind or "number" in class_name:
        return "number"
    if "date" in spec_kind or "date" in class_name:
        return "date"
    if operator in {"before", "after", "on", "not_on", "on_or_before", "on_or_after"}:
        return "date"
    if operator in {"greater_than", "gt", "greater_or_equal", "gte", "less_than", "lt"}:
        return "number"
    return ""


def _is_filter_spec_iterable(value: Any) -> bool:
    return not isinstance(value, (str, bytes, Mapping)) and isinstance(value, Iterable)


def _normalize_sqlite_filter_aliases(
    columns: tuple[str, ...],
    aliases: Mapping[str, str] | None,
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for alias, column in (aliases or {}).items():
        alias_text = str(alias or "").strip()
        if not alias_text:
            continue
        normalized[alias_text] = _resolve_sqlite_filter_column(str(column), columns, {})
    return normalized


def _resolve_sqlite_filter_column(
    column: str,
    columns: tuple[str, ...],
    aliases: Mapping[str, str],
) -> str:
    requested = str(column or "").strip()
    if requested in aliases:
        return aliases[requested]
    if requested in columns:
        return requested
    requested_key = requested.casefold()
    alias_lookup = {alias.casefold(): target for alias, target in aliases.items()}
    if requested_key in alias_lookup:
        return alias_lookup[requested_key]
    column_lookup = {candidate.casefold(): candidate for candidate in columns}
    if requested_key in column_lookup:
        return column_lookup[requested_key]
    safe = _safe_column_name(requested, fallback="column")
    if safe in column_lookup:
        return column_lookup[safe]
    raise KeyError(f"SQLite grouping filter column not allowed: {requested}")


def _sqlite_numeric_text_and_guard(column: str) -> tuple[str, str]:
    identifier = _quote_identifier(column)
    text_expr = f"TRIM(CAST({identifier} AS TEXT))"
    json_type_expr = f"CASE WHEN json_valid({text_expr}) THEN json_type({text_expr}) ELSE NULL END"
    numeric_guard = (
        f"{text_expr} != '' AND ("
        f"{json_type_expr} IN ('integer', 'real') "
        f"OR ({text_expr} NOT GLOB '*[^0-9]*') "
        f"OR (substr({text_expr}, 1, 1) IN ('+', '-') "
        f"AND substr({text_expr}, 2) != '' "
        f"AND substr({text_expr}, 2) NOT GLOB '*[^0-9]*')"
        ")"
    )
    return text_expr, numeric_guard


def _sqlite_date_filter_expr_for_column(
    column: str,
    date_filter_columns: Mapping[str, str] | None,
) -> str:
    storage_column = (date_filter_columns or {}).get(column, column)
    return f"date({_quote_identifier(storage_column)})"


def _sqlite_filter_number_value(value: Any, *, field_name: str) -> float:
    parsed = _parse_tabular_filter_number(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be numeric")
    return float(parsed)


def _sqlite_filter_date_value(value: Any, *, dayfirst: bool, field_name: str) -> date:
    parsed = pd.to_datetime(
        pd.Series([value]),
        errors="coerce",
        dayfirst=dayfirst,
        format="mixed",
    ).iloc[0]
    if pd.isna(parsed):
        raise ValueError(f"{field_name} must be date-like")
    return parsed.date()


def _sqlite_membership_values(values: Iterable[Any]) -> tuple[Any, ...]:
    normalized: list[Any] = []
    for value in values or ():
        text = str(value).strip()
        if text:
            normalized.append(value)
    return tuple(normalized)


def _sqlite_membership_value_kind(values: tuple[Any, ...], *, dayfirst: bool) -> str:
    if values and all(_sqlite_membership_value_looks_date_like(value) for value in values):
        parsed_dates = pd.to_datetime(
            pd.Series(list(values)),
            errors="coerce",
            dayfirst=dayfirst,
            format="mixed",
        )
        if parsed_dates.notna().all():
            return "date"
    parsed_numbers = pd.to_numeric(pd.Series(list(values)), errors="coerce")
    if values and parsed_numbers.notna().all():
        return "number"
    return "text"


def _sqlite_membership_value_looks_date_like(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.search(r"\d{4}", text) or any(marker in text for marker in ("/", ":")))


def _sqlite_membership_in_predicate(
    expression: str,
    values: tuple[Any, ...],
    *,
    negate: bool,
    placeholder_sql: str = "?",
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    operator = "NOT IN" if negate else "IN"
    for start in range(0, len(values), 900):
        chunk = values[start : start + 900]
        placeholders = ", ".join(placeholder_sql for _value in chunk)
        clauses.append(f"{expression} {operator} ({placeholders})")
        params.extend(chunk)
    joiner = " AND " if negate else " OR "
    if len(clauses) == 1:
        return clauses[0], params
    return f"({joiner.join(clauses)})", params


def _sqlite_wildcard_like_pattern(value: str) -> str:
    parts = str(value or "").split("*")
    escaped_parts = [
        part.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        for part in parts
    ]
    return "%".join(escaped_parts)


def _normalized_tabular_filter_series(series: pd.Series) -> pd.Series:
    normalized = series.where(~series.isna(), "(blank)")
    normalized = normalized.map(lambda value: str(value).strip() or "(blank)")
    return normalized.astype("string")


def _parse_tabular_filter_date(value: str | None):
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _parse_tabular_filter_number(value: float | int | str | None) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _tabular_date_filter_mask(series: pd.Series, column_filter: TabularColumnFilter) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    dates = parsed.dt.date
    valid_dates = dates.notna()
    mask = pd.Series(True, index=series.index)
    date_operator = str(column_filter.date_operator or "").strip()
    date_value = _parse_tabular_filter_date(column_filter.date_value)
    if date_operator in _TABULAR_DATE_OPERATORS and date_value is not None:
        if date_operator == "=":
            mask &= valid_dates & (dates == date_value)
        elif date_operator == "!=":
            mask &= valid_dates & (dates != date_value)
        elif date_operator == ">":
            mask &= valid_dates & (dates > date_value)
        elif date_operator == ">=":
            mask &= valid_dates & (dates >= date_value)
        elif date_operator == "<":
            mask &= valid_dates & (dates < date_value)
        else:
            mask &= valid_dates & (dates <= date_value)
        return mask.fillna(False)
    lower = _parse_tabular_filter_date(column_filter.date_from)
    upper = _parse_tabular_filter_date(column_filter.date_to)
    if column_filter.date_mode in {"from", "between"} and lower is not None:
        mask &= dates >= lower
    if column_filter.date_mode in {"to", "between"} and upper is not None:
        mask &= dates <= upper
    return mask.fillna(False)


def _tabular_numeric_filter_mask(series: pd.Series, column_filter: TabularColumnFilter) -> pd.Series:
    operator = str(column_filter.numeric_operator or "").strip()
    value = _parse_tabular_filter_number(column_filter.numeric_value)
    if operator not in _TABULAR_NUMERIC_OPERATORS or value is None:
        return pd.Series(True, index=series.index)
    numeric_series = pd.to_numeric(series, errors="coerce")
    valid_numeric = numeric_series.notna()
    if operator == "=":
        mask = valid_numeric & (numeric_series == value)
    elif operator == "!=":
        mask = valid_numeric & (numeric_series != value)
    elif operator == ">":
        mask = valid_numeric & (numeric_series > value)
    elif operator == ">=":
        mask = valid_numeric & (numeric_series >= value)
    elif operator == "<":
        mask = valid_numeric & (numeric_series < value)
    else:
        mask = valid_numeric & (numeric_series <= value)
    return mask.fillna(False)


def apply_tabular_grouping(
    dataframe: pd.DataFrame,
    grouping_df: pd.DataFrame | None,
    *,
    group_column: str = TABULAR_GROUP_COLUMN,
    default_group: str = TABULAR_DEFAULT_GROUP,
) -> TabularGroupingResult:
    """Apply manual DataGrouping assignments to a CSV/Excel analytics dataframe."""

    frame = dataframe.copy()
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    if not isinstance(grouping_df, pd.DataFrame) or grouping_df.empty or "GROUP" not in grouping_df.columns:
        return TabularGroupingResult(dataframe=frame)

    if "source_row_number" not in frame.columns:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="tabular_grouping_missing_row_number",
                message="Manual grouping was skipped because source row numbers are unavailable.",
            )
        )
        return TabularGroupingResult(dataframe=frame, diagnostics=tuple(diagnostics))

    grouping = grouping_df.copy()
    if "REPORT_ID" in grouping.columns:
        grouping_key = pd.to_numeric(grouping["REPORT_ID"], errors="coerce")
    elif "SAMPLE_NUMBER" in grouping.columns:
        grouping_key = pd.to_numeric(grouping["SAMPLE_NUMBER"], errors="coerce")
    else:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="tabular_grouping_missing_identity",
                message="Manual grouping was skipped because grouping rows have no source row identity.",
            )
        )
        return TabularGroupingResult(dataframe=frame, diagnostics=tuple(diagnostics))

    grouping = grouping.assign(__source_row_number=grouping_key)
    grouping = grouping[grouping["__source_row_number"].notna()].copy()
    if grouping.empty:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="tabular_grouping_empty_identity",
                message="Manual grouping was skipped because grouping row identities are empty.",
            )
        )
        return TabularGroupingResult(dataframe=frame, diagnostics=tuple(diagnostics))

    grouping[group_column] = _normalize_group_labels(grouping["GROUP"], default_group=default_group)
    assignment = (
        grouping.drop_duplicates(subset=["__source_row_number"], keep="last")
        .set_index("__source_row_number")[group_column]
        .to_dict()
    )
    row_numbers = pd.to_numeric(frame["source_row_number"], errors="coerce")
    frame[group_column] = row_numbers.map(assignment).fillna(default_group).astype(str)
    group_labels = sorted(label for label in frame[group_column].dropna().astype(str).unique() if label)
    custom_labels = [label for label in group_labels if label != default_group]
    has_default_group = default_group in group_labels
    if custom_labels and has_default_group:
        grouping_description = f"{len(custom_labels)} custom group(s) plus {default_group}."
    elif custom_labels:
        grouping_description = f"{len(custom_labels)} custom group(s)."
    else:
        grouping_description = f"{default_group} only."
    diagnostics.append(
        ProductionAnalyticsDiagnostic(
            severity="info",
            code="tabular_grouping_applied",
            message=f"Manual grouping applied: {grouping_description}",
            context={
                "group_count": len(group_labels),
                "custom_group_count": len(custom_labels),
                "default_group": default_group,
                "default_group_present": has_default_group,
            },
        )
    )
    return TabularGroupingResult(
        dataframe=frame,
        diagnostics=tuple(diagnostics),
        applied=True,
        group_count=len(group_labels),
        custom_group_count=len(custom_labels),
    )


def discover_tabular_metric_candidates(
    dataframe: pd.DataFrame,
    *,
    reserved_columns: tuple[str, ...] = (),
    numeric_threshold: float = 0.8,
    min_numeric_count: int = 2,
) -> tuple[ProductionMetricCandidate, ...]:
    """Discover numeric-looking table columns for CSV/Excel analytics."""

    reserved = {
        "source_row_number",
        "source_file",
        "source_sheet",
        "process_datetime",
        "reference",
    }
    reserved.update(str(column) for column in reserved_columns)
    candidates: list[ProductionMetricCandidate] = []
    for column in dataframe.columns:
        column_name = str(column)
        if column_name in reserved:
            continue
        values = dataframe[column].dropna()
        values = values[values.astype(str).str.strip() != ""]
        non_null_count = int(len(values.index))
        if non_null_count == 0:
            continue
        numeric_values = pd.to_numeric(values, errors="coerce")
        numeric_count = int(numeric_values.notna().sum())
        numeric_ratio = numeric_count / non_null_count if non_null_count else 0.0
        if numeric_count < int(min_numeric_count) or numeric_ratio < float(numeric_threshold):
            continue
        warning_flags = ()
        if numeric_count < non_null_count:
            warning_flags = ("contains_non_numeric_values",)
        candidates.append(
            ProductionMetricCandidate(
                field_name=column_name,
                display_label=_display_label_from_column(column_name),
                source_kind="fixed",
                non_null_count=non_null_count,
                numeric_count=numeric_count,
                numeric_ratio=round(numeric_ratio, 4),
                sample_values=tuple(dict.fromkeys(values.head(5).astype(str).tolist())),
                warning_flags=warning_flags,
            )
        )
    return tuple(sorted(candidates, key=lambda item: item.display_label.lower()))


def export_tabular_analytics_workbook(
    *,
    dataframe: pd.DataFrame,
    metric_candidates: tuple[ProductionMetricCandidate, ...],
    output_file: str | Path,
    aggregation_result: ProductionAggregationResult | None = None,
    groupstats_result: ProductionGroupstatsResult | None = None,
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = (),
    separate_parameter_sheets: bool = True,
    chart_selection: ProductionChartSelection | None = None,
    group_fields: tuple[str, ...] = (),
) -> TabularAnalyticsWorkbookResult:
    """Write workbook output for CSV/Excel analytics, optionally one sheet per metric."""

    output_path = Path(output_file)
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    sheet_names: list[str] = []
    safe_dataframe = _excel_safe_dataframe(dataframe)
    safe_aggregation_frame = (
        _excel_safe_dataframe(aggregation_result.dataframe)
        if aggregation_result is not None
        else None
    )
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        table_sheet = unique_sheet_name("Table Data", used_names)
        safe_dataframe.to_excel(writer, sheet_name=table_sheet, index=False)
        sheet_names.append(table_sheet)

        if safe_aggregation_frame is not None and not safe_aggregation_frame.empty:
            aggregate_sheet = unique_sheet_name("Aggregates", used_names)
            safe_aggregation_frame.to_excel(writer, sheet_name=aggregate_sheet, index=False)
            sheet_names.append(aggregate_sheet)

        summary_sheet = unique_sheet_name("Metrics", used_names)
        _metric_summary_dataframe(safe_dataframe, metric_candidates).to_excel(
            writer,
            sheet_name=summary_sheet,
            index=False,
        )
        sheet_names.append(summary_sheet)

        add_analytics_workbook_charts(
            writer=writer,
            dataframe=safe_dataframe,
            metric_selection=metric_candidates,
            chart_selection=chart_selection,
            data_sheet_name=table_sheet,
            used_names=used_names,
            sheet_names=sheet_names,
            group_fields=group_fields,
        )

        if groupstats_result is not None and groupstats_result.metrics:
            stats_sheet = unique_sheet_name("Groupstats", used_names)
            groupstats_result_dataframe(groupstats_result).to_excel(
                writer,
                sheet_name=stats_sheet,
                index=False,
            )
            sheet_names.append(stats_sheet)

        diagnostics_sheet = unique_sheet_name("Diagnostics", used_names)
        diagnostics_dataframe(diagnostics).to_excel(writer, sheet_name=diagnostics_sheet, index=False)
        sheet_names.append(diagnostics_sheet)

        parameter_sheet_count = 0
        if separate_parameter_sheets:
            for candidate in metric_candidates:
                if candidate.field_name not in safe_dataframe.columns:
                    continue
                parameter_sheet = unique_sheet_name(candidate.display_label, used_names)
                _parameter_dataframe(safe_dataframe, candidate.field_name).to_excel(
                    writer,
                    sheet_name=parameter_sheet,
                    index=False,
                )
                sheet_names.append(parameter_sheet)
                parameter_sheet_count += 1

    return TabularAnalyticsWorkbookResult(
        output_file=str(output_path),
        sheet_names=tuple(sheet_names),
        parameter_sheet_count=parameter_sheet_count,
    )


def _normalize_columns(dataframe: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    renamed: dict[Any, str] = {}
    for index, column in enumerate(dataframe.columns, start=1):
        original = str(column)
        candidate = _safe_column_name(original, fallback=f"column_{index}")
        base = candidate
        suffix = 1
        while candidate.casefold() in used:
            suffix += 1
            candidate = f"{base}_{suffix}"
        used.add(candidate.casefold())
        renamed[column] = candidate
        mapping[original] = candidate
    return dataframe.rename(columns=renamed).copy(), mapping


def _reserve_internal_columns(
    dataframe: pd.DataFrame,
    mapping: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Move source columns away from internal analytics column names."""

    renamed: dict[str, str] = {}
    used = {str(column).casefold() for column in dataframe.columns}
    internal_names = {name.casefold() for name in _INTERNAL_COLUMNS}
    for column in dataframe.columns:
        column_name = str(column)
        if column_name.casefold() not in internal_names:
            continue
        base = f"input_{column_name}"
        candidate = base
        suffix = 1
        while candidate.casefold() in used:
            suffix += 1
            candidate = f"{base}_{suffix}"
        used.add(candidate.casefold())
        renamed[column_name] = candidate

    if not renamed:
        return dataframe, mapping

    updated_mapping = {
        original: renamed.get(normalized, normalized)
        for original, normalized in mapping.items()
    }
    return dataframe.rename(columns=renamed).copy(), updated_mapping


def _source_row_numbers(dataframe: pd.DataFrame) -> list[int]:
    if "source_row_number" not in dataframe.columns:
        return list(range(1, len(dataframe.index) + 1))
    values = pd.to_numeric(dataframe["source_row_number"], errors="coerce")
    fallback = pd.Series(range(1, len(dataframe.index) + 1), index=dataframe.index)
    return values.fillna(fallback).astype(int).tolist()


def _display_series(series: pd.Series | None, *, fallback: str, row_count: int) -> list[str]:
    if series is None:
        return [fallback] * row_count
    return [
        text if text else fallback
        for text in series.fillna("").astype(str).map(lambda value: value.strip()).tolist()
    ]


def _display_text(value, *, fallback: str) -> str:
    if pd.isna(value):
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _date_display_series(series: pd.Series | None, row_count: int) -> list[str]:
    if series is None:
        return [""] * row_count
    parsed = pd.to_datetime(series, errors="coerce")
    return [
        "" if pd.isna(value) else value.strftime("%Y-%m-%d %H:%M:%S")
        for value in parsed.tolist()
    ]


def _normalize_group_labels(series: pd.Series, *, default_group: str) -> pd.Series:
    labels = series.fillna(default_group).astype(str).str.strip()
    return labels.mask(labels == "", default_group)


def _safe_column_name(value: str, *, fallback: str) -> str:
    name = _SAFE_COLUMN_RE.sub("_", str(value or "").strip()).strip("_").lower()
    if not name:
        name = fallback
    if name[0].isdigit():
        name = f"col_{name}"
    return name


def _resolve_requested_or_inferred_column(
    requested: str | None,
    mapping: dict[str, str],
    columns,
    *,
    hints: tuple[str, ...],
) -> str | None:
    requested_column = _resolve_requested_column(requested, mapping, columns)
    if requested_column is not None:
        return requested_column
    lowered = {str(column).casefold(): str(column) for column in columns}
    for hint in hints:
        for lowered_name, column in lowered.items():
            if _column_name_matches_hint(lowered_name, hint):
                return column
    return None


def _column_name_matches_hint(lowered_name: str, hint: str) -> bool:
    if hint in {"id", "ref"}:
        tokens = [token for token in re.split(r"[^a-z0-9]+", lowered_name) if token]
        return hint in tokens
    return hint in lowered_name


def _resolve_requested_column(
    requested: str | None,
    mapping: dict[str, str],
    columns,
) -> str | None:
    if requested:
        requested_text = str(requested).strip()
        if requested_text in columns:
            return requested_text
        if requested_text in mapping:
            return mapping[requested_text]
        safe = _safe_column_name(requested_text, fallback="column")
        if safe in columns:
            return safe
    return None


def _infer_timestamp_column(dataframe: pd.DataFrame, *, hints: tuple[str, ...]) -> str | None:
    lowered = {str(column).casefold(): str(column) for column in dataframe.columns}
    for hint in hints:
        for lowered_name, column in lowered.items():
            if hint in lowered_name and _looks_like_timestamp_column(dataframe[column]):
                return column
    return None


def _looks_like_timestamp_column(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    values = series.dropna()
    if values.empty or pd.api.types.is_numeric_dtype(values):
        return False
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    valid_count = int(parsed.notna().sum())
    required_count = min(2, len(values.index))
    return valid_count >= required_count and (valid_count / len(values.index)) >= 0.8


def _display_label_from_column(column_name: str) -> str:
    return str(column_name or "").replace("_", " ").strip().title()


def _metric_summary_dataframe(
    dataframe: pd.DataFrame,
    metric_candidates: tuple[ProductionMetricCandidate, ...],
) -> pd.DataFrame:
    rows = []
    for candidate in metric_candidates:
        if candidate.field_name not in dataframe.columns:
            continue
        values = pd.to_numeric(dataframe[candidate.field_name], errors="coerce").dropna()
        rows.append(
            {
                "metric": candidate.display_label,
                "field_name": candidate.field_name,
                "n": int(values.count()),
                "mean": float(values.mean()) if not values.empty else None,
                "median": float(values.median()) if not values.empty else None,
                "std": float(values.std(ddof=1)) if len(values.index) > 1 else None,
                "min": float(values.min()) if not values.empty else None,
                "max": float(values.max()) if not values.empty else None,
            }
        )
    return pd.DataFrame(rows)


def _parameter_dataframe(dataframe: pd.DataFrame, metric_field: str) -> pd.DataFrame:
    context_columns = [
        column
        for column in (
            "source_row_number",
            "process_datetime",
            "reference",
            TABULAR_GROUP_COLUMN,
            "source_file",
            "source_sheet",
        )
        if column in dataframe.columns
    ]
    columns = list(dict.fromkeys(context_columns + [metric_field]))
    parameter_frame = dataframe.loc[:, columns].copy()
    parameter_frame[metric_field] = pd.to_numeric(parameter_frame[metric_field], errors="coerce")
    return parameter_frame


__all__ = [
    "TABULAR_DEFAULT_GROUP",
    "TABULAR_GROUP_COLUMN",
    "TabularAnalyticsLoadResult",
    "TabularSourceSnapshot",
    "TabularLoadCancelled",
    "TabularSqliteFilterExpression",
    "TabularSqliteStore",
    "TabularAnalyticsWorkbookResult",
    "TabularColumnFilter",
    "TabularFilterResult",
    "TabularGroupingResult",
    "apply_tabular_row_filter",
    "apply_tabular_grouping",
    "build_tabular_file_grouping_dataframe",
    "build_tabular_grouping_dataframe",
    "cleanup_tabular_load_result",
    "compile_tabular_sqlite_grouping_filter",
    "count_tabular_materialized_rows",
    "discover_tabular_metric_candidates",
    "export_tabular_analytics_workbook",
    "list_tabular_excel_sheets",
    "load_tabular_analytics_file",
    "load_tabular_analytics_files",
    "materialize_tabular_dataframe",
    "selectable_tabular_source_columns",
    "tabular_file_group_labels",
    "tabular_load_result_row_count",
]
