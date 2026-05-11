from __future__ import annotations

import pytest

from modules.industrial_analytics_state import (
    DynamicFieldFilter,
    ProductionAggregationState,
    ProductionAnalyticsRequest,
    ProductionChartSelection,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
    parse_reference_values,
    validate_production_analytics_request,
)


def test_reference_paste_parser_accepts_common_user_formats() -> None:
    assert parse_reference_values("REF1, REF2;REF3\nREF4 REF5\tREF6") == (
        "REF1",
        "REF2",
        "REF3",
        "REF4",
        "REF5",
        "REF6",
    )
    assert parse_reference_values("REF1 REF1,REF2") == ("REF1", "REF2")


def test_filter_state_normalizes_values_and_summarizes() -> None:
    state = ProductionFilterState(
        source_profile_ids=(2, 2, 1),
        references=(" REF-1 ", "REF-1", "REF-2"),
        stations=("S1", ""),
        dynamic_filters=(DynamicFieldFilter("cycle_time_s", "gt", 35),),
    )

    assert state.source_profile_ids == (2, 1)
    assert state.references == ("REF-1", "REF-2")
    assert state.stations == ("S1",)
    assert state.is_applied
    assert "Reference: 2" in state.summary()
    assert "Dynamic: 1" in state.summary()


def test_invalid_dynamic_field_identifier_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid dynamic field"):
        DynamicFieldFilter("bad-name", "eq", 1)


def test_dynamic_filter_requires_values_for_in_operator() -> None:
    with pytest.raises(ValueError, match="require at least one value"):
        DynamicFieldFilter("station_temp", "in", values=())

    state = DynamicFieldFilter("station_temp", "in", value=["22", "23"])
    assert state.values == ("22", "23")


def test_aggregation_state_validates_bucket_and_methods() -> None:
    state = ProductionAggregationState(
        time_bucket="week",
        aggregation_methods=("mean", "median", "mean"),
        group_fields=("station", "line"),
    )

    assert state.time_bucket == "week"
    assert state.aggregation_methods == ("mean", "median")
    assert state.group_fields == ("station", "line")

    with pytest.raises(ValueError, match="Unsupported production time bucket"):
        ProductionAggregationState(time_bucket="minute")
    with pytest.raises(ValueError, match="Unsupported aggregation method"):
        ProductionAggregationState(aggregation_methods=("mode",))


def test_reference_cohort_from_text_validates_mode_and_preserves_order() -> None:
    cohort = ReferenceCohortState.from_text("REF-2\nREF-1 REF-2", mode="compare_rest")

    assert cohort.references == ("REF-2", "REF-1")
    assert cohort.mode == "compare_rest"
    assert cohort.is_applied
    assert "2 selected" in cohort.summary()

    with pytest.raises(ValueError, match="Unsupported reference cohort mode"):
        ReferenceCohortState(references=("REF-1",), mode="bad")  # type: ignore[arg-type]


def test_empty_metric_selection_produces_readiness_warning_without_crash() -> None:
    request = ProductionAnalyticsRequest(
        db_file="metroliza.db",
        output_path="dashboard.html",
        metrics=(),
        charts=ProductionChartSelection(time_series=True),
    )

    readiness = validate_production_analytics_request(request)

    assert not readiness.ok
    assert readiness.messages == ("Select at least one production metric.",)
    assert readiness.summary == "Select at least one production metric."


def test_request_readiness_requires_database_chart_and_output() -> None:
    request = ProductionAnalyticsRequest(
        metrics=(ProductionMetricSelection("cycle_time_s"),),
        charts=ProductionChartSelection(
            time_series=False,
            histogram=False,
            violin=False,
            box=False,
            groupstats=False,
        ),
    )

    readiness = validate_production_analytics_request(request)

    assert not readiness.ok
    assert readiness.messages == (
        "Select a Metroliza report database with cached production data.",
        "Select at least one chart or analysis output.",
        "Select an output dashboard path.",
    )
