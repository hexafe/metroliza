"""CSV/Excel analytics source helpers for the shared production analytics workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import pandas as pd

from modules.csv_summary_utils import load_csv_with_fallbacks
from modules.excel_sheet_utils import unique_sheet_name
from modules.industrial_analytics_service import (
    ProductionAggregationResult,
    ProductionAnalyticsDiagnostic,
    ProductionMetricCandidate,
)


_SAFE_COLUMN_RE = re.compile(r"[^A-Za-z0-9_]+")
_TIMESTAMP_HINTS = ("timestamp", "time", "date", "datetime", "created", "process")
_REFERENCE_HINTS = ("reference", "ref", "part", "part_number", "id", "serial")


@dataclass(frozen=True)
class TabularAnalyticsLoadResult:
    """Loaded CSV/Excel table normalized for shared analytics."""

    dataframe: pd.DataFrame
    metric_candidates: tuple[ProductionMetricCandidate, ...]
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    column_mapping: dict[str, str] = field(default_factory=dict)
    source_file: str = ""
    sheet_name: str | None = None
    csv_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TabularAnalyticsWorkbookResult:
    """Workbook export result for tabular analytics."""

    output_file: str
    sheet_names: tuple[str, ...]
    parameter_sheet_count: int


def _excel_safe_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    safe_frame = dataframe.copy()
    for column in safe_frame.columns:
        dtype = safe_frame[column].dtype
        if isinstance(dtype, pd.DatetimeTZDtype):
            safe_frame[column] = safe_frame[column].dt.tz_convert(None)
    return safe_frame


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
    frame.insert(0, "source_row_number", range(1, len(frame.index) + 1))
    frame["source_file"] = path.name
    if resolved_sheet_name is not None:
        frame["source_sheet"] = str(resolved_sheet_name)

    timestamp_field = _resolve_requested_or_inferred_column(
        timestamp_column,
        mapping,
        frame.columns,
        hints=_TIMESTAMP_HINTS,
    )
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
        csv_config=csv_config,
    )


def discover_tabular_metric_candidates(
    dataframe: pd.DataFrame,
    *,
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
    if requested:
        requested_text = str(requested).strip()
        if requested_text in columns:
            return requested_text
        if requested_text in mapping:
            return mapping[requested_text]
        safe = _safe_column_name(requested_text, fallback="column")
        if safe in columns:
            return safe
    lowered = {str(column).casefold(): str(column) for column in columns}
    for hint in hints:
        for lowered_name, column in lowered.items():
            if hint in lowered_name:
                return column
    return None


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
    "TabularAnalyticsLoadResult",
    "TabularAnalyticsWorkbookResult",
    "discover_tabular_metric_candidates",
    "export_tabular_analytics_workbook",
    "load_tabular_analytics_file",
]
