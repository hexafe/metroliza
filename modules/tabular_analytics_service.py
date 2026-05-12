"""CSV/Excel analytics source helpers for the shared production analytics workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import pandas as pd

from modules.csv_summary_utils import filter_csv_summary_by_group_keys, load_csv_with_fallbacks
from modules.excel_sheet_utils import unique_sheet_name
from modules.industrial_analytics_service import (
    ProductionAggregationResult,
    ProductionAnalyticsDiagnostic,
    ProductionMetricCandidate,
)
from modules.industrial_analytics_state import ProductionChartSelection
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


def load_tabular_analytics_file(
    input_file: str | Path,
    *,
    sheet_name: str | int | None = None,
    timestamp_column: str | None = None,
    reference_column: str | None = None,
    numeric_threshold: float = 0.8,
    min_numeric_count: int = 2,
) -> TabularAnalyticsLoadResult:
    """Load CSV/Excel data and normalize it to the production analytics dataframe shape."""

    path = Path(input_file)
    if not path.exists():
        raise FileNotFoundError(str(path))

    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    csv_config: dict[str, Any] = {}
    suffix = path.suffix.lower()
    if suffix == ".csv":
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
    )


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
) -> TabularFilterResult:
    """Filter normalized CSV/Excel analytics rows by selected column-value keys."""

    if not isinstance(dataframe, pd.DataFrame):
        return TabularFilterResult(dataframe=pd.DataFrame())

    input_count = int(len(dataframe.index))
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
    "TabularAnalyticsWorkbookResult",
    "TabularFilterResult",
    "TabularGroupingResult",
    "apply_tabular_row_filter",
    "apply_tabular_grouping",
    "build_tabular_grouping_dataframe",
    "discover_tabular_metric_candidates",
    "export_tabular_analytics_workbook",
    "list_tabular_excel_sheets",
    "load_tabular_analytics_file",
    "selectable_tabular_source_columns",
]
