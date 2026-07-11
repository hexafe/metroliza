"""Immutable industrial analytics request contracts and validators."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metroliza.charts.dashboard_visual_options import normalize_dashboard_visual_settings
from metroliza.industrial.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
    require_identifier as require_analytics_identifier,
)
from metroliza.shared.dashboard_interactivity import (
    DashboardInteractivityOptions,
    normalize_dashboard_interactivity_options,
)
from metroliza.tabular.contracts import GroupingAssignments, validate_grouping_df
from metroliza.tabular.tabular_analytics_service import (
    TabularAnalyticsLoadResult,
    TabularColumnFilter,
)


@dataclass(frozen=True)
class IndustrialAnalyticsRequest:
    """Top-level immutable request contract for industrial analytics workflows."""

    source_kind: str
    output_dashboard_file: str
    dashboard_detail_mode: str = "full"
    db_file: str = ""
    input_file: str = ""
    output_workbook_file: str = ""
    metric_selection: tuple[ProductionMetricSelection, ...] = ()
    filter_state: ProductionFilterState | None = None
    aggregation_state: ProductionAggregationState | None = None
    cohort_state: ReferenceCohortState | None = None
    chart_selection: ProductionChartSelection | None = None
    separate_parameter_sheets: bool = True
    sheet_name: str | int | None = None
    timestamp_column: str | None = None
    reference_column: str | None = None
    tabular_load_result: TabularAnalyticsLoadResult | None = None
    tabular_filter_columns: tuple[str, ...] = ()
    tabular_filter_keys: tuple[tuple[str, ...], ...] = ()
    tabular_column_filters: tuple[TabularColumnFilter, ...] = ()
    tabular_filter_expression: str = ""
    grouping_df: GroupingAssignments | None = None
    dashboard_visual_settings: dict[str, Any] | None = None
    dashboard_interactivity_options: DashboardInteractivityOptions | dict[str, Any] | None = None


_ANALYTICS_SOURCE_KINDS = {"production_cache", "tabular_file"}
_DASHBOARD_DETAIL_MODES = {"fast", "full"}


def validate_industrial_analytics_request(
    request: IndustrialAnalyticsRequest,
    *,
    require_runnable: bool = False,
) -> IndustrialAnalyticsRequest:
    """Validate and normalize an industrial analytics request."""

    if not isinstance(request, IndustrialAnalyticsRequest):
        raise ValueError(
            "Analytics request must be provided as an IndustrialAnalyticsRequest instance."
        )

    source_kind = _normalize_analytics_source_kind(request.source_kind)
    output_dashboard_file = _normalize_optional_output_path(
        request.output_dashboard_file,
        suffix=".html",
        field_name="dashboard output path",
        required=require_runnable,
    )
    output_workbook_file = _normalize_optional_output_path(
        request.output_workbook_file,
        suffix=".xlsx",
        field_name="workbook output path",
        required=False,
    )
    db_file = _normalize_optional_text(request.db_file, field_name="database path")
    input_file = _normalize_optional_text(
        request.input_file,
        field_name="CSV/Excel input path",
    )

    if require_runnable and source_kind == "production_cache" and not db_file:
        raise ValueError("Select a Metroliza report database before creating analytics.")
    if require_runnable and source_kind == "tabular_file" and not input_file:
        raise ValueError("Select a CSV or Excel file before creating analytics.")

    return IndustrialAnalyticsRequest(
        source_kind=source_kind,
        output_dashboard_file=output_dashboard_file,
        dashboard_detail_mode=_normalize_dashboard_detail_mode(
            request.dashboard_detail_mode
        ),
        db_file=db_file,
        input_file=input_file,
        output_workbook_file=output_workbook_file,
        metric_selection=_normalize_metric_selection(request.metric_selection),
        filter_state=_normalize_filter_state(request.filter_state),
        aggregation_state=_normalize_aggregation_state(request.aggregation_state),
        cohort_state=_normalize_cohort_state(request.cohort_state),
        chart_selection=_normalize_chart_selection(request.chart_selection),
        separate_parameter_sheets=bool(request.separate_parameter_sheets),
        sheet_name=_normalize_sheet_name(request.sheet_name),
        timestamp_column=_normalize_optional_identifier(
            request.timestamp_column,
            "time column",
        ),
        reference_column=_normalize_optional_identifier(
            request.reference_column,
            "part/id column",
        ),
        tabular_load_result=_normalize_tabular_load_result(request.tabular_load_result),
        tabular_filter_columns=_normalize_filter_columns(
            request.tabular_filter_columns
        ),
        tabular_filter_keys=_normalize_filter_keys(request.tabular_filter_keys),
        tabular_column_filters=_normalize_column_filters(
            request.tabular_column_filters
        ),
        tabular_filter_expression=_normalize_optional_text(
            request.tabular_filter_expression,
            field_name="tabular filter expression",
        ),
        grouping_df=validate_grouping_df(request.grouping_df),
        dashboard_visual_settings=normalize_dashboard_visual_settings(
            request.dashboard_visual_settings
        ),
        dashboard_interactivity_options=_normalize_dashboard_interactivity_options(
            request.dashboard_interactivity_options
        ),
    )


def _normalize_analytics_source_kind(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Analytics source kind must be provided as a string.")
    source_kind = value.strip().lower()
    if source_kind not in _ANALYTICS_SOURCE_KINDS:
        raise ValueError(f"Unsupported analytics source kind: {value}")
    return source_kind


def _normalize_dashboard_detail_mode(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Dashboard rendering mode must be provided as a string.")
    detail_mode = value.strip().lower()
    if detail_mode not in _DASHBOARD_DETAIL_MODES:
        raise ValueError(f"Unsupported dashboard rendering mode: {value}")
    return detail_mode


def _normalize_dashboard_interactivity_options(
    value: object,
) -> DashboardInteractivityOptions:
    if value is not None and not isinstance(
        value,
        (DashboardInteractivityOptions, dict),
    ):
        raise ValueError(
            "Dashboard interactivity options must be provided as a "
            "DashboardInteractivityOptions instance or mapping."
        )
    return normalize_dashboard_interactivity_options(value, strict=True)


def _normalize_optional_output_path(
    value: object,
    *,
    suffix: str,
    field_name: str,
    required: bool,
) -> str:
    text = _normalize_optional_text(value, field_name=field_name)
    if not text:
        if required:
            raise ValueError(f"A {field_name} is required.")
        return ""
    path = Path(text)
    if not path.suffix:
        path = path.with_suffix(suffix)
    elif path.suffix.lower() != suffix:
        raise ValueError(f"{field_name.capitalize()} must use the {suffix} extension.")
    return str(path)


def _normalize_optional_text(value: object, *, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(
            f"{field_name.capitalize()} must be provided as a string when set."
        )
    return value.strip()


def _normalize_metric_selection(
    value: tuple[ProductionMetricSelection, ...]
    | list[ProductionMetricSelection]
    | None,
) -> tuple[ProductionMetricSelection, ...]:
    if not value:
        return ()
    metrics = tuple(value)
    if any(not isinstance(metric, ProductionMetricSelection) for metric in metrics):
        raise ValueError(
            "Analytics metric selection must contain ProductionMetricSelection entries."
        )
    return metrics


def _normalize_filter_state(
    value: ProductionFilterState | None,
) -> ProductionFilterState:
    if value is None:
        return ProductionFilterState()
    if not isinstance(value, ProductionFilterState):
        raise ValueError("Analytics filter state must be a ProductionFilterState instance.")
    return value


def _normalize_aggregation_state(
    value: ProductionAggregationState | None,
) -> ProductionAggregationState:
    if value is None:
        return ProductionAggregationState()
    if not isinstance(value, ProductionAggregationState):
        raise ValueError(
            "Analytics aggregation state must be a ProductionAggregationState instance."
        )
    return value


def _normalize_cohort_state(
    value: ReferenceCohortState | None,
) -> ReferenceCohortState:
    if value is None:
        return ReferenceCohortState()
    if not isinstance(value, ReferenceCohortState):
        raise ValueError("Analytics cohort state must be a ReferenceCohortState instance.")
    return value


def _normalize_chart_selection(
    value: ProductionChartSelection | None,
) -> ProductionChartSelection:
    if value is None:
        return ProductionChartSelection()
    if not isinstance(value, ProductionChartSelection):
        raise ValueError(
            "Analytics chart selection must be a ProductionChartSelection instance."
        )
    return value


def _normalize_sheet_name(value: object) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text or None
    raise ValueError("Excel sheet selection must be a string, integer, or None.")


def _normalize_optional_identifier(value: object, field_name: str) -> str | None:
    text = _normalize_optional_text(value, field_name=field_name)
    if not text:
        return None
    require_analytics_identifier(field_name, text)
    return text


def _normalize_tabular_load_result(
    value: TabularAnalyticsLoadResult | None,
) -> TabularAnalyticsLoadResult | None:
    if value is None:
        return None
    if not isinstance(value, TabularAnalyticsLoadResult):
        raise ValueError(
            "Loaded CSV/Excel data must be a TabularAnalyticsLoadResult instance."
        )
    return value


def _normalize_filter_columns(
    value: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    if not value:
        return ()
    columns: list[str] = []
    for column in value:
        normalized = _normalize_optional_identifier(column, "tabular filter column")
        if normalized:
            columns.append(normalized)
    return tuple(columns)


def _normalize_filter_keys(
    value: tuple[tuple[str, ...], ...] | list[tuple[str, ...]] | None,
) -> tuple[tuple[str, ...], ...]:
    if not value:
        return ()
    normalized_keys: list[tuple[str, ...]] = []
    for key in value:
        if not isinstance(key, tuple | list):
            raise ValueError("Tabular filter keys must be sequences of strings.")
        normalized_parts = tuple(
            str(part).strip() for part in key if str(part).strip()
        )
        if normalized_parts:
            normalized_keys.append(normalized_parts)
    return tuple(normalized_keys)


def _normalize_column_filters(
    value: tuple[TabularColumnFilter, ...] | list[TabularColumnFilter] | None,
) -> tuple[TabularColumnFilter, ...]:
    if not value:
        return ()
    filters = tuple(value)
    if any(not isinstance(item, TabularColumnFilter) for item in filters):
        raise ValueError(
            "Tabular column filters must contain TabularColumnFilter entries."
        )
    return filters


__all__ = [
    "IndustrialAnalyticsRequest",
    "validate_industrial_analytics_request",
]
