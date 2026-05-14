"""CSV/Excel analytics source helpers for the shared production analytics workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

import pandas as pd

from modules.csv_summary_utils import (
    filter_csv_summary_by_group_keys,
    load_csv_with_fallbacks,
    detect_csv_read_configs,
)
from modules.db import sqlite_connection_scope
from modules.excel_sheet_utils import unique_sheet_name
from modules.industrial_analytics_service import (
    ProductionAggregationResult,
    ProductionAnalyticsDiagnostic,
    ProductionGroupstatsResult,
    ProductionMetricCandidate,
)
from modules.industrial_analytics_state import ProductionChartSelection
from modules.industrial_analytics_workbook import groupstats_result_dataframe
from modules.industrial_analytics_workbook_charts import add_analytics_workbook_charts


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
TABULAR_SQLITE_ROW_THRESHOLD = 300_000
TABULAR_SQLITE_CHUNK_ROWS = 50_000
TABULAR_SQLITE_PREVIEW_ROWS = 5_000
_TABULAR_SQLITE_TABLE = "tabular_rows"


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
class TabularSqliteStore:
    """File-backed row store for multi-file or large CSV Summary inputs."""

    path: str
    table_name: str
    columns: tuple[str, ...]
    source_columns: tuple[str, ...]
    row_count: int
    date_filter_columns: dict[str, str] = field(default_factory=dict)

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
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            column_filters=column_filters,
        )
        query = (
            f"SELECT {', '.join(_quote_identifier(column) for column in self.columns)} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql}"
        )
        if limit is not None and int(limit) >= 0:
            query = f"{query} LIMIT {int(limit)}"
        with sqlite_connection_scope(self.path) as connection:
            dataframe = pd.read_sql_query(query, connection, params=params)
        return _restore_sqlite_dataframe(dataframe)

    def count_rows(
        self,
        *,
        filter_columns: tuple[str, ...] | list[str] | None = None,
        selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
    ) -> int:
        where_sql, params = self._where_clause(
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            column_filters=column_filters,
        )
        query = f"SELECT COUNT(*) FROM {_quote_identifier(self.table_name)}{where_sql}"
        with sqlite_connection_scope(self.path) as connection:
            value = connection.execute(query, params).fetchone()[0]
        return int(value or 0)

    def preview_value_rows(
        self,
        column: str,
        *,
        search_text: str = "",
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        if column not in self.columns:
            return [], 0
        value_expr = _sqlite_normalized_value_expr(column)
        where_parts: list[str] = []
        params: list[Any] = []
        search = str(search_text or "").strip().casefold()
        if search:
            where_parts.append(f"LOWER({value_expr}) LIKE ?")
            params.append(f"%{search}%")
        where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        count_query = (
            f"SELECT COUNT(*) FROM ("
            f"SELECT {value_expr} AS label FROM {_quote_identifier(self.table_name)}"
            f"{where_sql} GROUP BY label)"
        )
        query = (
            f"SELECT {value_expr} AS label, COUNT(*) AS row_count "
            f"FROM {_quote_identifier(self.table_name)}{where_sql} "
            f"GROUP BY label ORDER BY label COLLATE NOCASE"
        )
        if limit is not None and int(limit) >= 0:
            query = f"{query} LIMIT {int(limit)}"
        with sqlite_connection_scope(self.path) as connection:
            total = int(connection.execute(count_query, params).fetchone()[0] or 0)
            records = connection.execute(query, params).fetchall()
        rows = [
            {
                "key": (str(label),),
                "label": str(label),
                "row_count": int(row_count or 0),
            }
            for label, row_count in records
        ]
        return rows, total

    def preview_group_keys(
        self,
        columns: tuple[str, ...] | list[str],
        *,
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
    ) -> tuple[tuple[str, ...], ...]:
        normalized_columns = tuple(str(column) for column in columns if str(column) in self.columns)
        if not normalized_columns:
            return ()
        expressions = [
            f"{_sqlite_normalized_value_expr(column)} AS {_quote_identifier(f'key_{index}')}"
            for index, column in enumerate(normalized_columns)
        ]
        where_sql, params = self._where_clause(column_filters=column_filters)
        query = (
            f"SELECT DISTINCT {', '.join(expressions)} "
            f"FROM {_quote_identifier(self.table_name)}{where_sql} "
            f"ORDER BY {', '.join(_quote_identifier(f'key_{index}') for index in range(len(expressions)))}"
        )
        with sqlite_connection_scope(self.path) as connection:
            records = connection.execute(query, params).fetchall()
        return tuple(tuple(str(part) for part in record) for record in records)

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
        column_filters: tuple["TabularColumnFilter", ...] | list["TabularColumnFilter"] | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        normalized_filters = _normalized_tabular_column_filters_for_columns(
            self.columns,
            column_filters,
        )
        if normalized_filters:
            for column_filter in normalized_filters:
                filter_clauses: list[str] = []
                if column_filter.selected_values:
                    placeholders = ", ".join("?" for _value in column_filter.selected_values)
                    filter_clauses.append(
                        f"{_sqlite_normalized_value_expr(column_filter.column)} IN ({placeholders})"
                    )
                    params.extend(column_filter.selected_values)
                if column_filter.has_date_filter:
                    date_expr = self._sqlite_date_filter_expr(column_filter.column)
                    lower = _parse_tabular_filter_date(column_filter.date_from)
                    upper = _parse_tabular_filter_date(column_filter.date_to)
                    if column_filter.date_mode in {"from", "between"} and lower is not None:
                        filter_clauses.append(f"{date_expr} >= date(?)")
                        params.append(lower.isoformat())
                    if column_filter.date_mode in {"to", "between"} and upper is not None:
                        filter_clauses.append(f"{date_expr} <= date(?)")
                        params.append(upper.isoformat())
                if filter_clauses:
                    clauses.append(f"({' AND '.join(filter_clauses)})")
        else:
            columns = tuple(str(column) for column in (filter_columns or ()) if str(column) in self.columns)
            selected_keys = tuple(
                tuple(str(part) for part in key)
                for key in (selected_filter_keys or ())
                if isinstance(key, (list, tuple)) and len(key) == len(columns)
            )
            if columns and selected_keys:
                key_clauses: list[str] = []
                for key in selected_keys:
                    parts = []
                    for column, value in zip(columns, key, strict=False):
                        parts.append(f"{_sqlite_normalized_value_expr(column)} = ?")
                        params.append(str(value))
                    key_clauses.append(f"({' AND '.join(parts)})")
                clauses.append(f"({' OR '.join(key_clauses)})")
        return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params

    def _sqlite_date_filter_expr(self, column: str) -> str:
        return f"date({_quote_identifier(self.date_filter_columns.get(column, column))})"


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

    @property
    def has_value_filter(self) -> bool:
        return bool(self.selected_values)

    @property
    def has_date_filter(self) -> bool:
        return self.date_mode in {"from", "to", "between"} and bool(self.date_from or self.date_to)

    @property
    def is_active(self) -> bool:
        return bool(self.column and (self.has_value_filter or self.has_date_filter))


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
) -> TabularAnalyticsLoadResult:
    """Load one or more tabular analytics files.

    Multiple inputs are intentionally CSV-only. Excel keeps the existing single-workbook
    sheet selection behavior.
    """

    paths = tuple(Path(path) for path in input_files or ())
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
        )

    if any(path.suffix.lower() != ".csv" for path in paths):
        raise ValueError("Multiple-file and optimized large-file loading supports CSV files only.")

    return _load_csv_files_into_sqlite(
        paths,
        timestamp_column=timestamp_column,
        reference_column=reference_column,
        numeric_threshold=numeric_threshold,
        min_numeric_count=min_numeric_count,
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
) -> TabularAnalyticsLoadResult:
    """Load CSV/Excel data and normalize it to the production analytics dataframe shape."""

    path = Path(input_file)
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
) -> TabularAnalyticsLoadResult:
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    file_specs: list[dict[str, Any]] = []
    global_mapping: dict[str, str] = {}
    source_columns: list[str] = []
    date_filter_source_columns: set[str] = set()
    timestamp_field: str | None = None
    reference_field: str | None = None

    for path in paths:
        csv_config = _detect_csv_config(path)
        sample_frame = pd.read_csv(
            path,
            delimiter=csv_config["delimiter"],
            decimal=csv_config["decimal"],
            low_memory=False,
            nrows=200,
        )
        normalized_sample, mapping = _normalize_columns(sample_frame)
        normalized_sample, mapping = _reserve_internal_columns(normalized_sample, mapping)
        normalized_columns = tuple(str(column) for column in normalized_sample.columns)
        for original, normalized in mapping.items():
            global_mapping.setdefault(original, normalized)
        for column in normalized_columns:
            if column not in source_columns:
                source_columns.append(column)

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
            for spec in file_specs:
                path = spec["path"]
                csv_config = spec["csv_config"]
                mapping = spec["mapping"]
                file_row_count = 0
                chunk_iter = pd.read_csv(
                    path,
                    delimiter=csv_config["delimiter"],
                    decimal=csv_config["decimal"],
                    low_memory=False,
                    chunksize=TABULAR_SQLITE_CHUNK_ROWS,
                )
                for raw_chunk in chunk_iter:
                    normalized_chunk = raw_chunk.rename(columns=mapping)
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
                    output_chunk.loc[:, list(storage_columns)].to_sql(
                        _TABULAR_SQLITE_TABLE,
                        connection,
                        if_exists="append",
                        index=False,
                    )
                    row_number += chunk_row_count
                    file_row_count += chunk_row_count

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
            _create_sqlite_indexes(
                connection,
                _TABULAR_SQLITE_TABLE,
                (
                    "source_row_number",
                    "source_file",
                    "process_datetime",
                    "reference",
                    *source_columns[:32],
                    *date_filter_columns.values(),
                ),
            )

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
        metric_candidates = _metric_candidates_from_stats(
            metric_stats,
            numeric_threshold=numeric_threshold,
            min_numeric_count=min_numeric_count,
        )
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
        preview = store.read_dataframe(limit=TABULAR_SQLITE_PREVIEW_ROWS)
        first_snapshot = snapshots[0] if len(snapshots) == 1 else None
        csv_config: dict[str, Any]
        if len(snapshots) == 1:
            csv_config = dict(snapshots[0].csv_config)
        else:
            csv_config = {
                "files": {snapshot.path: dict(snapshot.csv_config) for snapshot in snapshots},
                "storage": "sqlite",
            }
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
        text_values = values.astype(str).str.strip()
        values = values[text_values != ""]
        if values.empty:
            continue
        numeric_values = pd.to_numeric(values, errors="coerce")
        stats = metric_stats.setdefault(
            column,
            {"non_null_count": 0, "numeric_count": 0, "sample_values": []},
        )
        stats["non_null_count"] += int(len(values.index))
        stats["numeric_count"] += int(numeric_values.notna().sum())
        sample_values = stats["sample_values"]
        for value in values.astype(str).tolist():
            if value not in sample_values:
                sample_values.append(value)
            if len(sample_values) >= 5:
                break


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
        selector_labels = [
            " | ".join(
                _display_text(row.get(column), fallback="")
                for column in selectors
            ).strip()
            for _index, row in frame[selectors].iterrows()
        ]
        selector_labels = [
            label if label else f"Row {row_number}"
            for label, row_number in zip(selector_labels, row_numbers, strict=False)
        ]
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


def apply_tabular_row_filter(
    dataframe: pd.DataFrame,
    *,
    filter_columns: tuple[str, ...] | list[str] | None = None,
    selected_filter_keys: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None = None,
    column_filters: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None = None,
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
                    }
                    for item in normalized_column_filters
                ],
                "input_row_count": input_count,
                "output_row_count": output_count,
            },
        )
        return TabularFilterResult(
            dataframe=filtered.reset_index(drop=True),
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
            dataframe=dataframe.copy(),
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
        dataframe=filtered.reset_index(drop=True),
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
) -> TabularFilterResult:
    """Return rows for analytics, using SQLite pushdown when the load result has a store."""

    if loaded.sqlite_store is None:
        return apply_tabular_row_filter(
            loaded.dataframe,
            filter_columns=filter_columns,
            selected_filter_keys=selected_filter_keys,
            column_filters=column_filters,
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
        normalized_filter = TabularColumnFilter(
            column=column,
            selected_values=selected_values,
            date_mode=date_mode,
            date_from=str(item.date_from or "").strip() or None,
            date_to=str(item.date_to or "").strip() or None,
        )
        if normalized_filter.is_active:
            normalized.append(normalized_filter)
            seen.add(column)
    return tuple(normalized)


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


def _quote_identifier(value: str) -> str:
    return f'"{str(value).replace(chr(34), chr(34) * 2)}"'


def _sqlite_normalized_value_expr(column: str) -> str:
    identifier = _quote_identifier(column)
    return f"COALESCE(NULLIF(TRIM(CAST({identifier} AS TEXT)), ''), '(blank)')"


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


def _tabular_date_filter_mask(series: pd.Series, column_filter: TabularColumnFilter) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    dates = parsed.dt.date
    mask = pd.Series(True, index=series.index)
    lower = _parse_tabular_filter_date(column_filter.date_from)
    upper = _parse_tabular_filter_date(column_filter.date_to)
    if column_filter.date_mode in {"from", "between"} and lower is not None:
        mask &= dates >= lower
    if column_filter.date_mode in {"to", "between"} and upper is not None:
        mask &= dates <= upper
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
    diagnostics.append(
        ProductionAnalyticsDiagnostic(
            severity="info",
            code="tabular_grouping_applied",
            message=(
                f"Manual grouping applied: {len(custom_labels)} custom group(s) plus "
                f"{default_group}."
            ),
            context={
                "group_count": len(group_labels),
                "custom_group_count": len(custom_labels),
                "default_group": default_group,
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
        _diagnostics_dataframe(diagnostics).to_excel(writer, sheet_name=diagnostics_sheet, index=False)
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


def _diagnostics_dataframe(diagnostics: tuple[ProductionAnalyticsDiagnostic, ...]) -> pd.DataFrame:
    if not diagnostics:
        return pd.DataFrame([{"severity": "info", "code": "ok", "message": "No diagnostics."}])
    return pd.DataFrame(
        [
            {
                "severity": diagnostic.severity,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "context": diagnostic.context,
            }
            for diagnostic in diagnostics
        ]
    )


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
    "TabularSqliteStore",
    "TabularAnalyticsWorkbookResult",
    "TabularColumnFilter",
    "TabularFilterResult",
    "TabularGroupingResult",
    "apply_tabular_row_filter",
    "apply_tabular_grouping",
    "build_tabular_grouping_dataframe",
    "cleanup_tabular_load_result",
    "count_tabular_materialized_rows",
    "discover_tabular_metric_candidates",
    "export_tabular_analytics_workbook",
    "list_tabular_excel_sheets",
    "load_tabular_analytics_file",
    "load_tabular_analytics_files",
    "materialize_tabular_dataframe",
    "selectable_tabular_source_columns",
    "tabular_load_result_row_count",
]
