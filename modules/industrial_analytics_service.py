"""Service layer for cached Oznak production analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
from typing import Any

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


@dataclass(frozen=True)
class ProductionAnalyticsDiagnostic:
    """Structured diagnostic message for production analytics service calls."""

    severity: str
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


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
    grouped_values: dict[str, tuple[float, ...]]
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
        count_column = "industrial_record_id" if "industrial_record_id" in frame.columns else metric_names[0]
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

    frame = dataframe.copy()
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
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
            diagnostics=tuple(diagnostics),
        )

    aggregation = aggregation_state or ProductionAggregationState()
    requested_group_fields = tuple(group_fields or aggregation.group_fields)
    resolved_group_fields: list[str] = []

    if aggregation.time_bucket != "none":
        frame["time_bucket_start"] = _time_bucket_series(frame, aggregation.time_bucket)
        bad_bucket_count = int(frame["time_bucket_start"].isna().sum())
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
        frame = frame[frame["time_bucket_start"].notna()].copy()
        resolved_group_fields.append("time_bucket_start")

    cohort = cohort_state or ReferenceCohortState()
    if (
        cohort.is_applied
        and cohort.mode in {"compare_rest", "group_selected"}
        and "reference_cohort" in frame.columns
    ):
        resolved_group_fields.append("reference_cohort")

    for field_name in requested_group_fields:
        if field_name in resolved_group_fields:
            continue
        if field_name not in frame.columns:
            diagnostics.append(_missing_filter_field_diagnostic(field_name, code="missing_group_field"))
            continue
        resolved_group_fields.append(field_name)

    grouped_values: dict[str, tuple[float, ...]] = {}
    if resolved_group_fields:
        grouped_frames = frame.groupby(resolved_group_fields, dropna=False, sort=True)
        iterator = ((_groupstats_label(key), group) for key, group in grouped_frames)
    else:
        iterator = (("All production rows", frame),)

    for label, group in iterator:
        values = _finite_numeric_values(group[metric.field_name])
        if values:
            grouped_values[label] = tuple(values)

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
        group_fields=tuple(resolved_group_fields),
        diagnostics=tuple(diagnostics),
    )


def analyze_production_groupstats(
    dataframe: pd.DataFrame,
    metric_selection: tuple[ProductionMetricSelection, ...],
    *,
    group_fields: tuple[str, ...] = (),
    aggregation_state: ProductionAggregationState | None = None,
    cohort_state: ReferenceCohortState | None = None,
    alpha: float = 0.05,
    correction_method: str = "holm",
) -> ProductionGroupstatsResult:
    """Analyze selected production metrics with the hexafe-groupstats adapter."""

    metrics: list[dict[str, Any]] = []
    diagnostics: list[ProductionAnalyticsDiagnostic] = []
    for metric in metric_selection:
        input_result = build_production_groupstats_inputs(
            dataframe,
            metric,
            group_fields=group_fields,
            aggregation_state=aggregation_state,
            cohort_state=cohort_state,
        )
        diagnostics.extend(input_result.diagnostics)
        if len(input_result.grouped_values) < 2:
            metrics.append(_skipped_groupstats_metric_payload(input_result, "insufficient_groups"))
            continue
        try:
            raw_payload = analyze_group_metric(
                metric.display_label,
                input_result.grouped_values,
                spec_records=[{}],
                alpha=alpha,
                correction_method=correction_method,
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
            continue
        metrics.append(_groupstats_metric_payload(input_result, raw_payload))

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


def _groupstats_label(key: Any) -> str:
    if not isinstance(key, tuple):
        key = (key,)
    parts = []
    for value in key:
        if pd.isna(value):
            parts.append("(blank)")
        elif hasattr(value, "isoformat"):
            parts.append(value.isoformat())
        else:
            parts.append(str(value))
    return " | ".join(part.strip() or "(blank)" for part in parts)


def _finite_numeric_values(series: pd.Series) -> list[float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[np.isfinite(values)]
    return [float(value) for value in values.tolist()]


def _groupstats_metric_payload(
    input_result: ProductionGroupstatsInputResult,
    raw_payload: dict[str, Any],
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
        "skipped": False,
        "spec_status": raw_payload.get("spec_status"),
        "spec_payload": raw_payload.get("spec_payload"),
        "analysis_policy": raw_payload.get("analysis_policy"),
        "descriptive_stats": list(raw_payload.get("descriptive_stats") or []),
        "pairwise_rows": list(raw_payload.get("pairwise_rows") or []),
        "capability": raw_payload.get("capability") or {},
        "backend_used": raw_payload.get("backend_used"),
        "selection_detail": raw_payload.get("selection_detail"),
        "posthoc_family": raw_payload.get("posthoc_family"),
        "posthoc_method_name": raw_payload.get("posthoc_method_name"),
        "pairwise_strategy": raw_payload.get("pairwise_strategy"),
        "posthoc_strategy": raw_payload.get("posthoc_strategy"),
        "capability_strategy": raw_payload.get("capability_strategy"),
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
        "pairwise_rows": [],
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
    record_placeholders = ", ".join("?" for _ in record_ids)
    field_placeholders = ", ".join("?" for _ in field_names)
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
    params = tuple(record_ids) + tuple(field_names)
    with sqlite_connection_scope(db_file) as conn:
        return pd.read_sql_query(query, conn, params=params)


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
    if state.time_start:
        clauses.append("records.process_timestamp >= ?")
        params.append(state.time_start)
    if state.time_end:
        clauses.append("records.process_timestamp < ?")
        params.append(state.time_end)
    return clauses, params


def _append_in_filter(
    clauses: list[str],
    params: list[Any],
    column_sql: str,
    values: tuple[Any, ...],
) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    clauses.append(f"{column_sql} IN ({placeholders})")
    params.extend(values)


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
