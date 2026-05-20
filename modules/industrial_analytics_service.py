"""Service layer for cached Oznak production analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
from typing import Any, Callable

import numpy as np
import pandas as pd

from modules.db import sqlite_connection_scope
from modules.hexafe_groupstats_adapter import analyze_group_metric
from modules.industrial_analytics_state import (
    FIXED_PRODUCTION_FIELDS,
    DynamicFieldFilter,
    ProductionAggregationState,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
    production_field_label,
    require_identifier,
)


PRODUCTION_RECORD_COLUMNS: tuple[str, ...] = (
    "id",
    "source_profile_id",
    "sync_run_id",
    "source_db_alias",
    "source_record_key",
    "process_timestamp",
    "reference",
    "part_number",
    "part_name",
    "revision",
    "serial",
    "batch_lot",
    "work_order",
    "station",
    "line",
    "operator_name",
    "process_status",
    "raw_record_json",
)
FIXED_METRIC_CANDIDATE_COLUMNS: tuple[str, ...] = ()
FIXED_METRIC_EXCLUDED_COLUMNS = frozenset(
    {
        *PRODUCTION_RECORD_COLUMNS,
        "created_at",
        "updated_at",
        "id",
        "raw_record_json",
    }
)
FIXED_METRIC_NUMERIC_TYPE_MARKERS = ("INT", "REAL", "NUM", "DEC", "DOUBLE", "FLOAT")
_SQLITE_BATCH_PARAMETER_TARGET = 900
_DYNAMIC_FIELD_BATCH_SIZE = 100


@dataclass(frozen=True)
class ProductionAnalyticsDiagnostic:
    """Structured diagnostic message for production analytics service calls."""

    severity: str
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


ProductionGroupstatsProgressCallback = Callable[[str], None]
ProductionGroupstatsCancelCheck = Callable[[], bool]


class ProductionGroupstatsCancelled(RuntimeError):
    """Raised when cooperative production groupstats cancellation is requested."""


@dataclass(frozen=True)
class ProductionMetricCandidate:
    """Numeric-looking fixed or dynamic production field available for analysis."""

    field_name: str
    display_label: str
    source_kind: str
    non_null_count: int
    numeric_count: int
    numeric_ratio: float
    sample_values: tuple[str, ...] = ()
    source_profile_ids: tuple[int, ...] = ()
    warning_flags: tuple[str, ...] = ()

    def to_selection(self) -> ProductionMetricSelection:
        return ProductionMetricSelection(
            field_name=self.field_name,
            display_label=self.display_label,
            source_kind=self.source_kind,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ProductionAnalyticsFrameResult:
    """Loaded production dataframe plus diagnostics."""

    dataframe: pd.DataFrame
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    row_count: int = 0
    bad_timestamp_count: int = 0
    missing_metrics: tuple[str, ...] = ()

    @property
    def has_rows(self) -> bool:
        return self.row_count > 0


@dataclass(frozen=True)
class ProductionFilterResult:
    """Filtered production dataframe plus row-count diagnostics."""

    dataframe: pd.DataFrame
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    input_row_count: int = 0
    output_row_count: int = 0


@dataclass(frozen=True)
class ProductionCohortResult:
    """Production dataframe annotated or filtered by a pasted reference cohort."""

    dataframe: pd.DataFrame
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    selected_count: int = 0
    missing_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductionAggregationResult:
    """Aggregated or row-level production analytics data."""

    dataframe: pd.DataFrame
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()
    source_row_count: int = 0
    output_row_count: int = 0
    is_aggregated: bool = False


@dataclass(frozen=True)
class ProductionGroupstatsInputResult:
    """Grouped numeric values prepared for one production metric."""

    metric: ProductionMetricSelection
    grouped_values: dict[str, np.ndarray]
    group_fields: tuple[str, ...] = ()
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()


@dataclass(frozen=True)
class _PreparedProductionGroupstatsGrouping:
    """Group labels and row positions shared by all selected production metrics."""

    dataframe: pd.DataFrame
    group_indices: dict[str, np.ndarray]
    group_fields: tuple[str, ...] = ()
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()


@dataclass(frozen=True)
class ProductionGroupstatsResult:
    """Groupstats output for selected production analytics metrics."""

    metrics: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[ProductionAnalyticsDiagnostic, ...] = ()

    @property
    def analyzed_metric_count(self) -> int:
        return sum(1 for metric in self.metrics if not metric.get("skipped"))


def discover_production_metric_candidates(
    db_file: str,
    *,
    filter_state: ProductionFilterState | None = None,
    numeric_threshold: float = 0.8,
    min_numeric_count: int = 2,
) -> tuple[ProductionMetricCandidate, ...]:
    """Discover numeric-looking fields in cached production data."""

    if not _industrial_tables_available(db_file):
        return ()

    dynamic_rows = _load_dynamic_metric_discovery_rows(db_file, filter_state=filter_state)
    candidates: list[ProductionMetricCandidate] = []
    for field_name in _fixed_metric_candidate_columns(db_file):
        fixed_rows = _load_fixed_metric_discovery_rows(
            db_file,
            field_name=field_name,
            filter_state=filter_state,
        )
        candidate = _build_metric_candidate(
            field_name=field_name,
            source_kind="fixed",
            values=fixed_rows["field_value"] if "field_value" in fixed_rows else pd.Series(dtype=object),
            source_profile_ids=(
                fixed_rows["source_profile_id"]
                if "source_profile_id" in fixed_rows
                else pd.Series(dtype=object)
            ),
            numeric_threshold=numeric_threshold,
            min_numeric_count=min_numeric_count,
        )
        if candidate is not None:
            candidates.append(candidate)

    if not dynamic_rows.empty:
        for field_name, group in dynamic_rows.groupby("field_name", dropna=False):
            field_text = str(field_name or "").strip()
            if not field_text:
                continue
            try:
                require_identifier("dynamic metric field", field_text)
            except ValueError:
                continue
            candidate = _build_metric_candidate(
                field_name=field_text,
                source_kind="dynamic",
                values=group["field_value"],
                source_profile_ids=group["source_profile_id"],
                numeric_threshold=numeric_threshold,
                min_numeric_count=min_numeric_count,
            )
            if candidate is not None:
                candidates.append(candidate)

    return tuple(sorted(candidates, key=lambda item: item.display_label.lower()))


def load_production_analytics_frame(
    db_file: str,
    *,
    filter_state: ProductionFilterState | None = None,
    metric_selection: tuple[ProductionMetricSelection, ...] = (),
) -> ProductionAnalyticsFrameResult:
    """Load cached production rows and selected dynamic metrics into one dataframe."""

    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    if not _industrial_tables_available(db_file):
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="error",
                code="industrial_cache_unavailable",
                message="Industrial cache tables are not initialized in this database.",
            )
        )
        return ProductionAnalyticsFrameResult(
            dataframe=pd.DataFrame(columns=_frame_base_columns()),
            diagnostics=tuple(diagnostics),
        )

    record_columns = _industrial_record_columns(db_file)
    fixed_metric_fields = tuple(
        metric.field_name
        for metric in metric_selection
        if metric.source_kind == "fixed"
        and metric.field_name in record_columns
        and metric.field_name not in PRODUCTION_RECORD_COLUMNS
    )
    dataframe = _load_fixed_production_frame(
        db_file,
        filter_state=filter_state,
        extra_columns=fixed_metric_fields,
    )
    if dataframe.empty:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="no_cached_production_rows",
                message="No cached production rows matched the selected filters.",
            )
        )
        return ProductionAnalyticsFrameResult(
            dataframe=dataframe,
            diagnostics=tuple(diagnostics),
            row_count=0,
        )

    dataframe = dataframe.rename(columns={"id": "industrial_record_id"})
    state = filter_state or ProductionFilterState()
    dynamic_fields = tuple(
        sorted(
            {
                metric.field_name
                for metric in metric_selection
                if metric.source_kind == "dynamic"
            }
            | {dynamic_filter.field_name for dynamic_filter in state.dynamic_filters}
        )
    )
    if dynamic_fields:
        dynamic_values = _load_dynamic_values_for_records(
            db_file,
            record_ids=tuple(int(value) for value in dataframe["industrial_record_id"].tolist()),
            field_names=dynamic_fields,
        )
        if not dynamic_values.empty:
            pivot = dynamic_values.pivot_table(
                index="record_id",
                columns="field_name",
                values="field_value",
                aggfunc="first",
            )
            pivot = pivot.reset_index().rename(columns={"record_id": "industrial_record_id"})
            dataframe = dataframe.merge(pivot, on="industrial_record_id", how="left")

    dataframe["process_datetime"] = pd.to_datetime(
        dataframe.get("process_timestamp"),
        errors="coerce",
        utc=True,
    )
    bad_timestamp_count = int(dataframe["process_datetime"].isna().sum())
    if bad_timestamp_count:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="bad_process_timestamps",
                message=f"{bad_timestamp_count} production row(s) have invalid process timestamps.",
                context={"bad_timestamp_count": bad_timestamp_count},
            )
        )

    if state.time_start or state.time_end:
        time_filter_result = _apply_time_filters(dataframe, state)
        dataframe = time_filter_result.dataframe
        diagnostics.extend(time_filter_result.diagnostics)
        if time_filter_result.input_row_count != time_filter_result.output_row_count:
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="info",
                    code="time_filters_applied",
                    message=(
                        "Production time filters reduced rows from "
                        f"{time_filter_result.input_row_count} to {time_filter_result.output_row_count}."
                    ),
                    context={
                        "input_row_count": time_filter_result.input_row_count,
                        "output_row_count": time_filter_result.output_row_count,
                    },
                )
            )

    missing_metrics: list[str] = []
    for metric in metric_selection:
        if metric.field_name not in dataframe.columns:
            missing_metrics.append(metric.field_name)
            continue
        dataframe[metric.field_name] = pd.to_numeric(dataframe[metric.field_name], errors="coerce")

    if missing_metrics:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="missing_selected_metrics",
                message=f"Missing selected metric(s): {', '.join(missing_metrics)}.",
                context={"missing_metrics": tuple(missing_metrics)},
            )
        )

    if state.dynamic_filters:
        filter_result = _apply_dynamic_filters(dataframe, state.dynamic_filters)
        dataframe = filter_result.dataframe
        diagnostics.extend(filter_result.diagnostics)

    return ProductionAnalyticsFrameResult(
        dataframe=dataframe,
        diagnostics=tuple(diagnostics),
        row_count=int(len(dataframe.index)),
        bad_timestamp_count=bad_timestamp_count,
        missing_metrics=tuple(missing_metrics),
    )


def apply_production_filters(
    dataframe: pd.DataFrame,
    filter_state: ProductionFilterState | None = None,
) -> ProductionFilterResult:
    """Apply production filters to an already loaded analytics dataframe."""

    state = filter_state or ProductionFilterState()
    filtered = dataframe.copy()
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    input_count = int(len(filtered.index))

    fixed_filters: tuple[tuple[str, tuple[Any, ...]], ...] = (
        ("source_profile_id", state.source_profile_ids),
        ("source_db_alias", state.source_db_aliases),
        ("reference", state.references),
        ("part_number", state.part_numbers),
        ("part_name", state.part_names),
        ("revision", state.revisions),
        ("serial", state.serials),
        ("batch_lot", state.batch_lots),
        ("work_order", state.work_orders),
        ("station", state.stations),
        ("line", state.lines),
        ("operator_name", state.operators),
        ("process_status", state.process_statuses),
    )
    for column, values in fixed_filters:
        if not values:
            continue
        if column not in filtered.columns:
            diagnostics.append(_missing_filter_field_diagnostic(column))
            continue
        filtered = filtered[filtered[column].isin(values)].copy()

    if state.time_start or state.time_end:
        time_filter_result = _apply_time_filters(filtered, state)
        filtered = time_filter_result.dataframe
        diagnostics.extend(time_filter_result.diagnostics)

    if state.dynamic_filters:
        dynamic_result = _apply_dynamic_filters(filtered, state.dynamic_filters)
        filtered = dynamic_result.dataframe
        diagnostics.extend(dynamic_result.diagnostics)

    output_count = int(len(filtered.index))
    if input_count != output_count:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="filters_applied",
                message=f"Production filters reduced rows from {input_count} to {output_count}.",
                context={"input_row_count": input_count, "output_row_count": output_count},
            )
        )
    return ProductionFilterResult(
        dataframe=filtered.reset_index(drop=True),
        diagnostics=tuple(diagnostics),
        input_row_count=input_count,
        output_row_count=output_count,
    )


def _apply_time_filters(
    dataframe: pd.DataFrame,
    state: ProductionFilterState,
) -> ProductionFilterResult:
    filtered = dataframe.copy()
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    input_count = int(len(filtered.index))
    if not state.time_start and not state.time_end:
        return ProductionFilterResult(
            dataframe=filtered.reset_index(drop=True),
            input_row_count=input_count,
            output_row_count=input_count,
        )
    if "process_datetime" not in filtered.columns:
        filtered["process_datetime"] = pd.to_datetime(
            filtered.get("process_timestamp"),
            errors="coerce",
            utc=True,
        )
    timestamps = pd.to_datetime(filtered["process_datetime"], errors="coerce", utc=True)
    mask = pd.Series(True, index=filtered.index)
    if state.time_start:
        start = pd.to_datetime(state.time_start, errors="coerce", utc=True)
        if pd.isna(start):
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="warning",
                    code="invalid_time_filter_start",
                    message=f"Invalid production time-start filter: {state.time_start}.",
                )
            )
        else:
            mask &= timestamps >= start
    if state.time_end:
        end = pd.to_datetime(state.time_end, errors="coerce", utc=True)
        if pd.isna(end):
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="warning",
                    code="invalid_time_filter_end",
                    message=f"Invalid production time-end filter: {state.time_end}.",
                )
            )
        else:
            mask &= timestamps < end
    filtered = filtered[mask].copy()
    return ProductionFilterResult(
        dataframe=filtered.reset_index(drop=True),
        diagnostics=tuple(diagnostics),
        input_row_count=input_count,
        output_row_count=int(len(filtered.index)),
    )


def apply_reference_cohorts(
    dataframe: pd.DataFrame,
    cohort_state: ReferenceCohortState | None = None,
) -> ProductionCohortResult:
    """Add reference-cohort columns and optionally filter to selected references."""

    cohort = cohort_state or ReferenceCohortState()
    output = dataframe.copy()
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    if "reference" not in output.columns:
        output["reference_marked"] = False
        output["reference_cohort"] = "All references"
        diagnostics.append(_missing_filter_field_diagnostic("reference"))
        return ProductionCohortResult(dataframe=output, diagnostics=tuple(diagnostics))

    selected = set(cohort.references)
    reference_text = output["reference"].fillna("").astype(str).str.strip()
    marked = reference_text.isin(selected) if selected else pd.Series(False, index=output.index)
    selected_count = int(marked.sum())
    present_references = set(reference_text[reference_text != ""].unique().tolist())
    missing_references = tuple(reference for reference in cohort.references if reference not in present_references)

    output["reference_marked"] = marked.astype(bool)
    if cohort.is_applied:
        output["reference_cohort"] = marked.map(
            {True: cohort.label, False: "Other references"}
        )
        output["reference_cohort_order"] = marked.map({True: 0, False: 1})
    else:
        output["reference_cohort"] = "All references"
        output["reference_cohort_order"] = 0

    if missing_references:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="reference_cohort_missing_items",
                message=(
                    f"{len(missing_references)} selected reference(s) were not found in "
                    "the current production data."
                ),
                context={"missing_references": missing_references},
            )
        )

    if cohort.mode == "filter_selected" and cohort.is_applied:
        before = int(len(output.index))
        output = output[output["reference_marked"]].copy()
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="reference_cohort_filter_applied",
                message=f"Reference cohort filter reduced rows from {before} to {len(output.index)}.",
                context={"input_row_count": before, "output_row_count": int(len(output.index))},
            )
        )

    return ProductionCohortResult(
        dataframe=output.reset_index(drop=True),
        diagnostics=tuple(diagnostics),
        selected_count=selected_count,
        missing_references=missing_references,
    )


def aggregate_production_frame(
    dataframe: pd.DataFrame,
    aggregation_state: ProductionAggregationState | None,
    metric_selection: tuple[ProductionMetricSelection, ...],
) -> ProductionAggregationResult:
    """Aggregate selected production metrics by time bucket and group fields."""

    state = aggregation_state or ProductionAggregationState()
    frame = dataframe.copy()
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    source_count = int(len(frame.index))
    metric_names = [metric.field_name for metric in metric_selection if metric.field_name in frame.columns]
    missing_metrics = [metric.field_name for metric in metric_selection if metric.field_name not in frame.columns]
    if missing_metrics:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="aggregation_missing_metrics",
                message=f"Missing metric(s) skipped during aggregation: {', '.join(missing_metrics)}.",
                context={"missing_metrics": tuple(missing_metrics)},
            )
        )
    if not metric_names:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="aggregation_no_metrics",
                message="No selected production metrics are available for aggregation.",
            )
        )
        return ProductionAggregationResult(
            dataframe=pd.DataFrame(),
            diagnostics=tuple(diagnostics),
            source_row_count=source_count,
            output_row_count=0,
            is_aggregated=state.is_aggregated,
        )

    for metric_name in metric_names:
        frame[metric_name] = pd.to_numeric(frame[metric_name], errors="coerce")

    if not state.is_aggregated:
        columns = [
            column
            for column in (
                "industrial_record_id",
                "process_datetime",
                "process_timestamp",
                "reference",
                "source_db_alias",
                "station",
                "line",
                "operator_name",
                "process_status",
                "reference_marked",
                "reference_cohort",
            )
            if column in frame.columns
        ] + metric_names
        output = frame.loc[:, list(dict.fromkeys(columns))].reset_index(drop=True)
        return ProductionAggregationResult(
            dataframe=output,
            diagnostics=tuple(diagnostics),
            source_row_count=source_count,
            output_row_count=int(len(output.index)),
            is_aggregated=False,
        )

    group_keys: list[str] = []
    if state.time_bucket != "none":
        bucket = _time_bucket_series(frame, state.time_bucket)
        frame["time_bucket_start"] = bucket
        bad_bucket_count = int(frame["time_bucket_start"].isna().sum())
        if bad_bucket_count:
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="warning",
                    code="aggregation_bad_timestamps",
                    message=f"{bad_bucket_count} row(s) were skipped because timestamps are invalid.",
                    context={"bad_timestamp_count": bad_bucket_count},
                )
            )
        frame = frame[frame["time_bucket_start"].notna()].copy()
        group_keys.append("time_bucket_start")

    for field_name in state.group_fields:
        if field_name not in frame.columns:
            diagnostics.append(_missing_filter_field_diagnostic(field_name, code="missing_group_field"))
            continue
        group_keys.append(field_name)

    if not group_keys:
        frame["_all_records_group"] = "All records"
        group_keys.append("_all_records_group")

    named_aggs: dict[str, pd.NamedAgg] = {}
    if state.include_raw_row_count:
        count_column = (
            "industrial_record_id"
            if "industrial_record_id" in frame.columns
            else "source_row_number"
            if "source_row_number" in frame.columns
            else metric_names[0]
        )
        named_aggs["raw_row_count"] = pd.NamedAgg(column=count_column, aggfunc="count")
    for metric_name in metric_names:
        for method in state.aggregation_methods:
            named_aggs[f"{metric_name}__{method}"] = pd.NamedAgg(
                column=metric_name,
                aggfunc=_aggregation_callable(method),
            )

    aggregated = (
        frame.groupby(group_keys, dropna=False)
        .agg(**named_aggs)
        .reset_index()
        .sort_values(group_keys)
        .reset_index(drop=True)
    )
    if "_all_records_group" in aggregated.columns:
        aggregated = aggregated.drop(columns=["_all_records_group"])
    return ProductionAggregationResult(
        dataframe=aggregated,
        diagnostics=tuple(diagnostics),
        source_row_count=source_count,
        output_row_count=int(len(aggregated.index)),
        is_aggregated=True,
    )


def build_production_groupstats_inputs(
    dataframe: pd.DataFrame,
    metric: ProductionMetricSelection,
    *,
    group_fields: tuple[str, ...] = (),
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
) -> ProductionGroupstatsInputResult:
    """Build grouped finite numeric values for one production metric."""

    prepared = _prepare_production_groupstats_grouping(
        dataframe,
        group_fields=group_fields,
        aggregation_state=aggregation_state,
        cohort_state=cohort_state,
    )
    return _build_groupstats_input_from_prepared(prepared, metric)


def _prepare_production_groupstats_grouping(
    dataframe: pd.DataFrame,
    *,
    group_fields: tuple[str, ...] = (),
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
) -> _PreparedProductionGroupstatsGrouping:
    """Prepare group labels and dataframe row positions once for groupstats metrics."""

    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    if not isinstance(dataframe, pd.DataFrame):
        return _PreparedProductionGroupstatsGrouping(
            dataframe=pd.DataFrame(),
            group_indices={},
        )

    aggregation = aggregation_state or ProductionAggregationState()
    requested_group_fields = tuple(group_fields or aggregation.group_fields)
    resolved_group_fields: list[str] = []
    active_positions = np.arange(len(dataframe.index), dtype=np.intp)
    key_columns: dict[str, Any] = {}

    if aggregation.time_bucket != "none":
        time_bucket_start = _time_bucket_series(dataframe, aggregation.time_bucket)
        valid_bucket_mask = time_bucket_start.notna().to_numpy(dtype=bool, na_value=False)
        bad_bucket_count = int((~valid_bucket_mask).sum())
        if bad_bucket_count:
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="warning",
                    code="groupstats_bad_timestamps",
                    message=(
                        f"{bad_bucket_count} row(s) were skipped from groupstats because "
                        "timestamps are invalid."
                    ),
                    context={"bad_timestamp_count": bad_bucket_count},
                )
            )
        active_positions = active_positions[valid_bucket_mask]
        key_columns["time_bucket_start"] = time_bucket_start.iloc[active_positions].to_numpy(
            copy=False
        )
        resolved_group_fields.append("time_bucket_start")

    cohort = cohort_state or ReferenceCohortState()
    if (
        cohort.is_applied
        and cohort.mode in {"compare_rest", "group_selected"}
        and "reference_cohort" in dataframe.columns
    ):
        key_columns["reference_cohort"] = dataframe["reference_cohort"].iloc[
            active_positions
        ].to_numpy(copy=False)
        resolved_group_fields.append("reference_cohort")

    for field_name in requested_group_fields:
        if field_name in resolved_group_fields:
            continue
        if field_name not in dataframe.columns:
            diagnostics.append(_missing_filter_field_diagnostic(field_name, code="missing_group_field"))
            continue
        key_columns[field_name] = dataframe[field_name].iloc[active_positions].to_numpy(copy=False)
        resolved_group_fields.append(field_name)

    if resolved_group_fields:
        key_frame = pd.DataFrame(
            {field_name: key_columns[field_name] for field_name in resolved_group_fields}
        )
        grouped_indices = {
            _groupstats_label(key, time_bucket=aggregation.time_bucket): active_positions[
                np.asarray(positions, dtype=np.intp)
            ]
            for key, positions in key_frame.groupby(
                list(resolved_group_fields),
                dropna=False,
                sort=True,
            ).indices.items()
        }
    else:
        grouped_indices = {"All production rows": active_positions}

    return _PreparedProductionGroupstatsGrouping(
        dataframe=dataframe,
        group_indices=grouped_indices,
        group_fields=tuple(resolved_group_fields),
        diagnostics=tuple(diagnostics),
    )


def _build_groupstats_input_from_prepared(
    prepared: _PreparedProductionGroupstatsGrouping,
    metric: ProductionMetricSelection,
) -> ProductionGroupstatsInputResult:
    """Build grouped finite metric arrays from a prepared grouping."""

    diagnostics: list[ProductionAnalyticsDiagnostic] = list(prepared.diagnostics)
    frame = prepared.dataframe
    if metric.field_name not in frame.columns:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="groupstats_missing_metric",
                message=f"Groupstats skipped missing metric: {metric.display_label}.",
                context={"metric": metric.field_name},
            )
        )
        return ProductionGroupstatsInputResult(
            metric=metric,
            grouped_values={},
            group_fields=prepared.group_fields,
            diagnostics=tuple(diagnostics),
        )

    grouped_values: dict[str, np.ndarray] = {}
    numeric_values = pd.to_numeric(frame[metric.field_name], errors="coerce").to_numpy(
        dtype=float,
        copy=False,
    )
    for label, positions in prepared.group_indices.items():
        values = numeric_values[positions]
        values = values[np.isfinite(values)]
        if values.size:
            grouped_values[label] = values

    if not grouped_values:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="groupstats_no_numeric_values",
                message=f"Groupstats skipped {metric.display_label}: no numeric values are available.",
                context={"metric": metric.field_name},
            )
        )
    elif len(grouped_values) < 2:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="groupstats_insufficient_groups",
                message=(
                    f"Groupstats skipped {metric.display_label}: at least two non-empty groups "
                    "are required."
                ),
                context={"metric": metric.field_name, "group_count": len(grouped_values)},
            )
        )

    low_sample_groups = {
        label: len(values)
        for label, values in grouped_values.items()
        if 0 < len(values) < 3
    }
    if low_sample_groups:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="groupstats_low_sample_groups",
                message=(
                    f"{metric.display_label} has group(s) with fewer than 3 numeric samples; "
                    "interpret comparisons cautiously."
                ),
                context={"metric": metric.field_name, "groups": low_sample_groups},
            )
        )

    return ProductionGroupstatsInputResult(
        metric=metric,
        grouped_values=grouped_values,
        group_fields=prepared.group_fields,
        diagnostics=tuple(diagnostics),
    )


def _emit_groupstats_progress(
    progress_callback: ProductionGroupstatsProgressCallback | None,
    message: str,
) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _raise_if_groupstats_cancelled(cancel_check: ProductionGroupstatsCancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ProductionGroupstatsCancelled("Production groupstats analysis was canceled.")


def analyze_production_groupstats(
    dataframe: pd.DataFrame,
    metric_selection: tuple[ProductionMetricSelection, ...],
    *,
    group_fields: tuple[str, ...] = (),
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
    alpha: float = 0.05,
    correction_method: str = "holm",
    posthoc_method: str = "auto",
    include_effect_size_ci: bool = False,
    ci_level: float = 0.95,
    ci_bootstrap_iterations: int = 1000,
    capability_benchmark: float = 1.33,
    simulation_validation_iterations: int = 0,
    simulation_random_seed: int = 42,
    backend: str = "auto",
    enable_rust_in_auto: bool = False,
    distribution_diagnostics: bool = True,
    progress_callback: ProductionGroupstatsProgressCallback | None = None,
    cancel_check: ProductionGroupstatsCancelCheck | None = None,
) -> ProductionGroupstatsResult:
    """Analyze selected production metrics with the hexafe-groupstats adapter."""

    metrics: list[dict[str, Any]] = []
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    _raise_if_groupstats_cancelled(cancel_check)
    prepared_grouping = _prepare_production_groupstats_grouping(
        dataframe,
        group_fields=group_fields,
        aggregation_state=aggregation_state,
        cohort_state=cohort_state,
    )
    total_metrics = len(metric_selection)
    for metric_index, metric in enumerate(metric_selection, start=1):
        _raise_if_groupstats_cancelled(cancel_check)
        _emit_groupstats_progress(
            progress_callback,
            f"Analyzing metric {metric_index}/{total_metrics}: {metric.display_label}",
        )
        input_result = _build_groupstats_input_from_prepared(prepared_grouping, metric)
        diagnostics.extend(input_result.diagnostics)
        if len(input_result.grouped_values) < 2:
            metrics.append(_skipped_groupstats_metric_payload(input_result, "insufficient_groups"))
            _emit_groupstats_progress(
                progress_callback,
                f"Skipped metric {metric_index}/{total_metrics}: {metric.display_label}",
            )
            continue
        _raise_if_groupstats_cancelled(cancel_check)
        try:
            raw_payload = analyze_group_metric(
                metric.display_label,
                input_result.grouped_values,
                spec_records=_metric_spec_records(metric),
                alpha=alpha,
                correction_method=correction_method,
                posthoc_method=posthoc_method,
                include_effect_size_ci=include_effect_size_ci,
                ci_level=ci_level,
                ci_bootstrap_iterations=ci_bootstrap_iterations,
                capability_benchmark=capability_benchmark,
                simulation_validation_iterations=simulation_validation_iterations,
                simulation_random_seed=simulation_random_seed,
                backend=backend,
                enable_rust_in_auto=enable_rust_in_auto,
                distribution_diagnostics=distribution_diagnostics,
            )
        except Exception as exc:  # pragma: no cover - defensive boundary around dependency
            diagnostics.append(
                ProductionAnalyticsDiagnostic(
                    severity="error",
                    code="groupstats_analysis_failed",
                    message=f"Groupstats failed for {metric.display_label}: {exc}",
                    context={"metric": metric.field_name},
                )
            )
            metrics.append(_skipped_groupstats_metric_payload(input_result, "analysis_failed"))
            _emit_groupstats_progress(
                progress_callback,
                f"Skipped metric {metric_index}/{total_metrics}: {metric.display_label}",
            )
            continue
        metrics.append(_groupstats_metric_payload(input_result, raw_payload))
        _emit_groupstats_progress(
            progress_callback,
            f"Completed metric {metric_index}/{total_metrics}: {metric.display_label}",
        )

    _raise_if_groupstats_cancelled(cancel_check)
    if not metric_selection:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="warning",
                code="groupstats_no_metrics",
                message="No production metrics were selected for groupstats.",
            )
        )

    return ProductionGroupstatsResult(metrics=tuple(metrics), diagnostics=tuple(diagnostics))


def _industrial_tables_available(db_file: str) -> bool:
    try:
        with sqlite_connection_scope(db_file) as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('industrial_records', 'industrial_record_values')
                """
            ).fetchall()
    except sqlite3.Error:
        return False
    return {row[0] for row in rows} == {"industrial_records", "industrial_record_values"}


def _industrial_record_columns(db_file: str) -> dict[str, str]:
    try:
        with sqlite_connection_scope(db_file) as conn:
            rows = conn.execute("PRAGMA table_info(industrial_records)").fetchall()
    except sqlite3.Error:
        return {}
    return {str(row[1]): str(row[2] or "") for row in rows}


def _fixed_metric_candidate_columns(db_file: str) -> tuple[str, ...]:
    record_columns = _industrial_record_columns(db_file)
    candidates: list[str] = []
    for field_name in FIXED_METRIC_CANDIDATE_COLUMNS:
        if field_name in record_columns:
            candidates.append(field_name)
    for field_name, declared_type in record_columns.items():
        if field_name in FIXED_METRIC_EXCLUDED_COLUMNS:
            continue
        if not _is_declared_numeric_type(declared_type):
            continue
        candidates.append(field_name)
    valid_candidates = []
    for field_name in dict.fromkeys(candidates):
        try:
            require_identifier("fixed metric field", field_name)
        except ValueError:
            continue
        valid_candidates.append(field_name)
    return tuple(valid_candidates)


def _is_declared_numeric_type(declared_type: str) -> bool:
    normalized = str(declared_type or "").upper()
    return any(marker in normalized for marker in FIXED_METRIC_NUMERIC_TYPE_MARKERS)


def _build_metric_candidate(
    *,
    field_name: str,
    source_kind: str,
    values: pd.Series,
    source_profile_ids: pd.Series,
    numeric_threshold: float,
    min_numeric_count: int,
) -> ProductionMetricCandidate | None:
    text_values = values.dropna().astype(str)
    text_values = text_values[text_values.str.strip() != ""]
    non_null_count = int(len(text_values.index))
    if non_null_count == 0:
        return None
    numeric_values = pd.to_numeric(text_values, errors="coerce")
    numeric_count = int(numeric_values.notna().sum())
    numeric_ratio = numeric_count / non_null_count if non_null_count else 0.0
    if numeric_count < int(min_numeric_count) or numeric_ratio < float(numeric_threshold):
        return None
    warning_flags = ()
    if numeric_count < non_null_count:
        warning_flags = ("contains_non_numeric_values",)
    return ProductionMetricCandidate(
        field_name=field_name,
        display_label=production_field_label(field_name),
        source_kind=source_kind,
        non_null_count=non_null_count,
        numeric_count=numeric_count,
        numeric_ratio=round(numeric_ratio, 4),
        sample_values=tuple(dict.fromkeys(text_values.head(5).astype(str).tolist())),
        source_profile_ids=tuple(
            sorted(
                int(value)
                for value in source_profile_ids.dropna().unique().tolist()
            )
        ),
        warning_flags=warning_flags,
    )


def _missing_filter_field_diagnostic(
    field_name: str,
    *,
    code: str = "missing_filter_field",
) -> ProductionAnalyticsDiagnostic:
    return ProductionAnalyticsDiagnostic(
        severity="warning",
        code=code,
        message=f"Production field '{field_name}' is not available in the loaded data.",
        context={"field_name": field_name},
    )


def _apply_dynamic_filters(
    dataframe: pd.DataFrame,
    dynamic_filters: tuple[DynamicFieldFilter, ...],
) -> ProductionFilterResult:
    filtered = dataframe.copy()
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    input_count = int(len(filtered.index))
    for dynamic_filter in dynamic_filters:
        field_name = dynamic_filter.field_name
        if field_name not in filtered.columns:
            diagnostics.append(_missing_filter_field_diagnostic(field_name))
            continue
        mask = _dynamic_filter_mask(filtered[field_name], dynamic_filter)
        filtered = filtered[mask].copy()
    output_count = int(len(filtered.index))
    if input_count != output_count:
        diagnostics.append(
            ProductionAnalyticsDiagnostic(
                severity="info",
                code="dynamic_filters_applied",
                message=f"Dynamic production filters reduced rows from {input_count} to {output_count}.",
                context={"input_row_count": input_count, "output_row_count": output_count},
            )
        )
    return ProductionFilterResult(
        dataframe=filtered.reset_index(drop=True),
        diagnostics=tuple(diagnostics),
        input_row_count=input_count,
        output_row_count=output_count,
    )


def _dynamic_filter_mask(series: pd.Series, dynamic_filter: DynamicFieldFilter) -> pd.Series:
    operator = dynamic_filter.operator
    if operator == "is_null":
        return series.isna() | (series.astype(str).str.strip() == "")
    if operator == "is_not_null":
        return series.notna() & (series.astype(str).str.strip() != "")

    use_numeric = dynamic_filter.value_kind == "numeric" or operator in {"lt", "lte", "gt", "gte"}
    if use_numeric:
        numeric_series = pd.to_numeric(series, errors="coerce")
        if operator in {"in", "not_in"}:
            values = pd.to_numeric(pd.Series(list(dynamic_filter.values)), errors="coerce").dropna()
            if operator == "in":
                return numeric_series.isin(values.tolist())
            return ~numeric_series.isin(values.tolist())
        value = pd.to_numeric(pd.Series([dynamic_filter.value]), errors="coerce").iloc[0]
        if pd.isna(value):
            return pd.Series(False, index=series.index)
        if operator == "eq":
            return numeric_series == value
        if operator == "ne":
            return numeric_series != value
        if operator == "lt":
            return numeric_series < value
        if operator == "lte":
            return numeric_series <= value
        if operator == "gt":
            return numeric_series > value
        if operator == "gte":
            return numeric_series >= value
        return pd.Series(False, index=series.index)

    text_series = series.fillna("").astype(str).str.casefold()
    value = str(dynamic_filter.value or "").strip().casefold()
    if operator == "eq":
        return text_series == value
    if operator == "ne":
        return text_series != value
    if operator == "contains":
        return text_series.str.contains(value, regex=False, na=False)
    if operator == "starts_with":
        return text_series.str.startswith(value, na=False)
    if operator == "ends_with":
        return text_series.str.endswith(value, na=False)
    values = {str(item).strip().casefold() for item in dynamic_filter.values}
    if operator == "in":
        return text_series.isin(values)
    if operator == "not_in":
        return ~text_series.isin(values)
    return pd.Series(False, index=series.index)


def _time_bucket_series(frame: pd.DataFrame, time_bucket: str) -> pd.Series:
    timestamps = pd.to_datetime(
        frame["process_datetime"] if "process_datetime" in frame.columns else frame.get("process_timestamp"),
        errors="coerce",
        utc=True,
    )
    if time_bucket == "hour":
        return timestamps.dt.floor("h")
    if time_bucket == "day":
        return timestamps.dt.floor("D")
    if time_bucket == "week":
        return timestamps.dt.normalize() - pd.to_timedelta(timestamps.dt.weekday, unit="D")
    if time_bucket == "month":
        return timestamps.dt.to_period("M").dt.start_time.dt.tz_localize("UTC")
    if time_bucket == "year":
        return timestamps.dt.to_period("Y").dt.start_time.dt.tz_localize("UTC")
    return timestamps


def _aggregation_callable(method: str):
    if method == "p05":
        return lambda series: series.quantile(0.05)
    if method == "p95":
        return lambda series: series.quantile(0.95)
    return method


def _groupstats_label(key: Any, *, time_bucket: str | None = None) -> str:
    if not isinstance(key, tuple):
        key = (key,)
    parts = []
    for value in key:
        if pd.isna(value):
            parts.append("(blank)")
        elif time_bucket and time_bucket != "none" and hasattr(value, "isoformat"):
            parts.append(_format_time_bucket_label(value, time_bucket))
        elif hasattr(value, "isoformat"):
            parts.append(value.isoformat())
        else:
            parts.append(str(value))
    return " | ".join(part.strip() or "(blank)" for part in parts)


def _format_time_bucket_label(value: Any, time_bucket: str) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    if time_bucket == "year":
        return timestamp.strftime("%Y")
    if time_bucket == "month":
        return timestamp.strftime("%Y-%m")
    if time_bucket == "day":
        return timestamp.strftime("%Y-%m-%d")
    if time_bucket == "week":
        return f"Week of {timestamp.strftime('%Y-%m-%d')}"
    if time_bucket == "hour":
        return timestamp.strftime("%Y-%m-%d %H:00")
    return timestamp.isoformat()


def _finite_numeric_array(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, copy=False)
    return values[np.isfinite(values)]


def _coerce_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _metric_spec_records(metric: ProductionMetricSelection) -> list[dict[str, float | None]]:
    if metric.lsl is None and metric.usl is None:
        return []
    return [_metric_spec_record(metric)]


def _metric_spec_record(metric: ProductionMetricSelection) -> dict[str, float | None]:
    lsl = metric.lsl
    usl = metric.usl
    nominal = None
    if lsl is not None and usl is not None and lsl < usl:
        nominal = (lsl + usl) / 2.0
    return {
        "lsl": lsl,
        "nominal": nominal,
        "usl": usl,
    }


def _ordered_groupstats_labels(labels: Any) -> list[str]:
    unique_labels: list[str] = []
    seen: set[str] = set()
    for label in labels or []:
        normalized = str(label)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_labels.append(normalized)
    population = [label for label in unique_labels if label == "POPULATION"]
    others = [label for label in unique_labels if label != "POPULATION"]
    return population + others


def _order_groupstats_pairwise_rows(
    rows: Any,
    *,
    group_order: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []

    order_index = {label: index for index, label in enumerate(group_order)}
    ordered_rows: list[dict[str, Any]] = []
    seen_pairs: set[frozenset[str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        group_a = str(row.get("group_a") or "")
        group_b = str(row.get("group_b") or "")
        if not group_a or not group_b or group_a == group_b:
            continue
        pair_key = frozenset((group_a, group_b))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        normalized = dict(row)
        if group_a != "POPULATION" and group_b == "POPULATION":
            normalized["group_a"] = "POPULATION"
            normalized["group_b"] = group_a
            delta_mean = _coerce_float(normalized.get("delta_mean"))
            if delta_mean is not None:
                normalized["delta_mean"] = -delta_mean
            group_a, group_b = "POPULATION", group_a
        elif group_a != "POPULATION" and group_b != "POPULATION":
            if order_index.get(group_b, 10_000) < order_index.get(group_a, 10_000):
                normalized["group_a"] = group_b
                normalized["group_b"] = group_a
                delta_mean = _coerce_float(normalized.get("delta_mean"))
                if delta_mean is not None:
                    normalized["delta_mean"] = -delta_mean
                group_a, group_b = group_b, group_a
        ordered_rows.append(normalized)

    def _sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        group_a = str(row.get("group_a") or "")
        group_b = str(row.get("group_b") or "")
        index_a = order_index.get(group_a, 10_000)
        index_b = order_index.get(group_b, 10_000)
        if group_a == "POPULATION" or group_b == "POPULATION":
            return (0, max(index_a, index_b), min(index_a, index_b))
        return (1, min(index_a, index_b), max(index_a, index_b))

    return sorted(ordered_rows, key=_sort_key)


def _groupstats_metric_payload(
    input_result: ProductionGroupstatsInputResult,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    group_order = _ordered_groupstats_labels(input_result.grouped_values.keys())
    return {
        "metric": input_result.metric.display_label,
        "field_name": input_result.metric.field_name,
        "group_fields": list(input_result.group_fields),
        "group_count": len(input_result.grouped_values),
        "group_sample_counts": {
            label: len(values)
            for label, values in input_result.grouped_values.items()
        },
        "skipped": False,
        "spec_status": raw_payload.get("spec_status"),
        "spec_payload": raw_payload.get("spec_payload"),
        "analysis_policy": raw_payload.get("analysis_policy"),
        "descriptive_stats": list(raw_payload.get("descriptive_stats") or []),
        "distribution_rows": list(raw_payload.get("distribution_rows") or []),
        "omnibus": raw_payload.get("omnibus") or {},
        "pairwise_rows": _order_groupstats_pairwise_rows(
            list(raw_payload.get("pairwise_rows") or []),
            group_order=group_order,
        ),
        "posthoc_rows": _order_groupstats_pairwise_rows(
            list(raw_payload.get("posthoc_rows") or []),
            group_order=group_order,
        ),
        "capability_rows": list(raw_payload.get("capability_rows") or []),
        "metric_summary": raw_payload.get("metric_summary") or {},
        "capability": raw_payload.get("capability") or {},
        "backend_used": raw_payload.get("backend_used"),
        "selection_detail": raw_payload.get("selection_detail"),
        "posthoc_family": raw_payload.get("posthoc_family"),
        "posthoc_method_name": raw_payload.get("posthoc_method_name"),
        "pairwise_strategy": raw_payload.get("pairwise_strategy"),
        "posthoc_strategy": raw_payload.get("posthoc_strategy"),
        "capability_strategy": raw_payload.get("capability_strategy"),
        "correction_method": raw_payload.get("correction_method"),
        "correction_policy": raw_payload.get("correction_policy"),
        "analysis_restriction_label": raw_payload.get("analysis_restriction_label"),
        "distribution_flags": list(raw_payload.get("distribution_flags") or []),
        "simulation_validation": raw_payload.get("simulation_validation"),
        "capability_benchmark": raw_payload.get("capability_benchmark"),
        "posthoc_method": raw_payload.get("posthoc_method"),
        "backend_requested": raw_payload.get("backend_requested"),
        "enable_rust_in_auto": raw_payload.get("enable_rust_in_auto"),
        "structured_insights": list(raw_payload.get("structured_insights") or []),
        "primary_insight": raw_payload.get("primary_insight") or {},
        "insights": list(raw_payload.get("insights") or []),
        "warnings": list(raw_payload.get("warnings") or []),
    }


def _skipped_groupstats_metric_payload(
    input_result: ProductionGroupstatsInputResult,
    skip_reason: str,
) -> dict[str, Any]:
    return {
        "metric": input_result.metric.display_label,
        "field_name": input_result.metric.field_name,
        "group_fields": list(input_result.group_fields),
        "group_count": len(input_result.grouped_values),
        "group_sample_counts": {
            label: len(values)
            for label, values in input_result.grouped_values.items()
        },
        "skipped": True,
        "skip_reason": skip_reason,
        "descriptive_stats": [],
        "distribution_rows": [],
        "pairwise_rows": [],
        "posthoc_rows": [],
        "capability_rows": [],
        "metric_summary": {},
        "capability": {},
        "structured_insights": [],
        "primary_insight": {},
        "insights": [],
        "warnings": [],
    }


def _load_dynamic_metric_discovery_rows(
    db_file: str,
    *,
    filter_state: ProductionFilterState | None,
) -> pd.DataFrame:
    where_clauses, params = _fixed_filter_sql(filter_state)
    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    query = f"""
        SELECT
            values_row.field_name,
            COALESCE(values_row.field_value_text, values_row.field_value_json) AS field_value,
            records.source_profile_id
        FROM industrial_record_values values_row
        JOIN industrial_records records ON records.id = values_row.record_id
        {where_sql}
        ORDER BY values_row.field_name COLLATE NOCASE, records.id
    """
    with sqlite_connection_scope(db_file) as conn:
        return pd.read_sql_query(query, conn, params=params)


def _load_fixed_metric_discovery_rows(
    db_file: str,
    *,
    field_name: str,
    filter_state: ProductionFilterState | None,
) -> pd.DataFrame:
    require_identifier("fixed metric field", field_name)
    where_clauses, params = _fixed_filter_sql(filter_state)
    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    query = f"""
        SELECT
            records.{_quote_identifier(field_name)} AS field_value,
            records.source_profile_id
        FROM industrial_records records
        {where_sql}
        ORDER BY records.id
    """
    with sqlite_connection_scope(db_file) as conn:
        return pd.read_sql_query(query, conn, params=params)


def _load_fixed_production_frame(
    db_file: str,
    *,
    filter_state: ProductionFilterState | None,
    extra_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    record_columns = _industrial_record_columns(db_file)
    selected_columns = list(PRODUCTION_RECORD_COLUMNS)
    for column in extra_columns:
        require_identifier("fixed metric field", column)
        if column in record_columns and column not in selected_columns:
            selected_columns.append(column)
    select_columns = ", ".join(
        f"records.{_quote_identifier(column)} AS {_quote_identifier(column)}"
        for column in selected_columns
    )
    where_clauses, params = _fixed_filter_sql(filter_state)
    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    query = f"""
        SELECT {select_columns}
        FROM industrial_records records
        {where_sql}
        ORDER BY records.reference COLLATE NOCASE, records.process_timestamp, records.id
    """
    with sqlite_connection_scope(db_file) as conn:
        return pd.read_sql_query(query, conn, params=params)


def _load_dynamic_values_for_records(
    db_file: str,
    *,
    record_ids: tuple[int, ...],
    field_names: tuple[str, ...],
) -> pd.DataFrame:
    if not record_ids or not field_names:
        return pd.DataFrame(columns=["record_id", "field_name", "field_value"])
    for field_name in field_names:
        require_identifier("dynamic field", field_name)
    frames: list[pd.DataFrame] = []
    with sqlite_connection_scope(db_file) as conn:
        for field_chunk in _chunk_tuple(field_names, _DYNAMIC_FIELD_BATCH_SIZE):
            record_batch_size = max(1, _SQLITE_BATCH_PARAMETER_TARGET - len(field_chunk))
            for record_chunk in _chunk_tuple(record_ids, record_batch_size):
                record_placeholders = ", ".join("?" for _ in record_chunk)
                field_placeholders = ", ".join("?" for _ in field_chunk)
                query = f"""
                    SELECT
                        record_id,
                        field_name,
                        COALESCE(field_value_text, field_value_json) AS field_value
                    FROM industrial_record_values
                    WHERE record_id IN ({record_placeholders})
                      AND field_name IN ({field_placeholders})
                    ORDER BY record_id, field_name COLLATE NOCASE
                """
                params = tuple(record_chunk) + tuple(field_chunk)
                frames.append(pd.read_sql_query(query, conn, params=params))
    if not frames:
        return pd.DataFrame(columns=["record_id", "field_name", "field_value"])
    return pd.concat(frames, ignore_index=True)


def _chunk_tuple(values: tuple[Any, ...], size: int) -> tuple[tuple[Any, ...], ...]:
    safe_size = max(1, int(size))
    return tuple(values[index : index + safe_size] for index in range(0, len(values), safe_size))


def _fixed_filter_sql(filter_state: ProductionFilterState | None) -> tuple[list[str], list[Any]]:
    state = filter_state or ProductionFilterState()
    clauses: list[str] = []
    params: list[Any] = []
    _append_in_filter(clauses, params, "records.source_profile_id", state.source_profile_ids)
    _append_in_filter(clauses, params, "records.source_db_alias", state.source_db_aliases)
    for column, values in (
        ("reference", state.references),
        ("part_number", state.part_numbers),
        ("part_name", state.part_names),
        ("revision", state.revisions),
        ("serial", state.serials),
        ("batch_lot", state.batch_lots),
        ("work_order", state.work_orders),
        ("station", state.stations),
        ("line", state.lines),
        ("operator_name", state.operators),
        ("process_status", state.process_statuses),
    ):
        _append_in_filter(clauses, params, f"records.{column}", values)
    return clauses, params


def _append_in_filter(
    clauses: list[str],
    params: list[Any],
    column_sql: str,
    values: tuple[Any, ...],
) -> None:
    if not values:
        return
    chunks = _chunk_tuple(tuple(values), _SQLITE_BATCH_PARAMETER_TARGET)
    chunk_clauses: list[str] = []
    for chunk in chunks:
        placeholders = ", ".join("?" for _ in chunk)
        chunk_clauses.append(f"{column_sql} IN ({placeholders})")
        params.extend(chunk)
    if len(chunk_clauses) == 1:
        clauses.append(chunk_clauses[0])
    else:
        clauses.append("(" + " OR ".join(chunk_clauses) + ")")


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _frame_base_columns() -> tuple[str, ...]:
    return tuple(column for column, _label in FIXED_PRODUCTION_FIELDS) + (
        "industrial_record_id",
        "source_profile_id",
        "sync_run_id",
        "raw_record_json",
        "process_datetime",
    )


__all__ = [
    "ProductionAnalyticsDiagnostic",
    "ProductionAnalyticsFrameResult",
    "ProductionAggregationResult",
    "ProductionCohortResult",
    "ProductionFilterResult",
    "ProductionGroupstatsInputResult",
    "ProductionGroupstatsCancelled",
    "ProductionGroupstatsResult",
    "ProductionMetricCandidate",
    "aggregate_production_frame",
    "analyze_production_groupstats",
    "apply_production_filters",
    "apply_reference_cohorts",
    "build_production_groupstats_inputs",
    "discover_production_metric_candidates",
    "load_production_analytics_frame",
]
