from __future__ import annotations

from contextlib import closing
import sqlite3

import numpy as np
import pandas as pd

import modules.industrial_analytics_service as industrial_analytics_service
from modules.industrial_analytics_service import (
    aggregate_production_frame,
    analyze_production_groupstats,
    apply_production_filters,
    apply_reference_cohorts,
    build_production_groupstats_inputs,
    discover_production_metric_candidates,
    load_production_analytics_frame,
)
from modules.industrial_analytics_state import (
    DynamicFieldFilter,
    ProductionAggregationState,
    ProductionFilterState,
    ProductionMetricSelection,
    ReferenceCohortState,
)
from modules.industrial_data_repository import IndustrialDataRepository
from tests.industrial_analytics_fixtures import seed_production_analytics_cache


def _table_exists(db_path: str, table_name: str) -> bool:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def test_metric_discovery_uses_dynamic_numeric_fields_without_report_metadata(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    candidates = discover_production_metric_candidates(db_path)
    by_name = {candidate.field_name: candidate for candidate in candidates}

    assert not _table_exists(db_path, "report_metadata")
    assert {"cycle_time_s", "temperature_c", "force_n", "pressure_bar", "defect_count"}.issubset(
        by_name
    )
    assert "mostly_numeric_value" in by_name
    assert by_name["mostly_numeric_value"].warning_flags == ("contains_non_numeric_values",)
    assert "fixture_text_code" not in by_name


def test_metric_discovery_includes_fixed_numeric_record_columns(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("ALTER TABLE industrial_records ADD COLUMN machine_speed_rpm REAL")
        conn.execute(
            """
            UPDATE industrial_records
            SET machine_speed_rpm = 1200.0 + id
            """
        )
        conn.commit()

    candidates = discover_production_metric_candidates(db_path)
    by_name = {candidate.field_name: candidate for candidate in candidates}

    assert by_name["machine_speed_rpm"].source_kind == "fixed"
    result = load_production_analytics_frame(
        db_path,
        metric_selection=(
            ProductionMetricSelection(
                "machine_speed_rpm",
                display_label="Machine speed",
                source_kind="fixed",
            ),
        ),
    )
    assert result.has_rows
    assert "machine_speed_rpm" in result.dataframe.columns
    assert pd.api.types.is_numeric_dtype(result.dataframe["machine_speed_rpm"])


def test_load_frame_pivots_dynamic_metrics_and_parses_time_without_report_metadata(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    fixture = seed_production_analytics_cache(db_path)

    result = load_production_analytics_frame(
        db_path,
        metric_selection=(
            ProductionMetricSelection("cycle_time_s"),
            ProductionMetricSelection("temperature_c"),
            ProductionMetricSelection("mostly_numeric_value"),
        ),
    )

    frame = result.dataframe
    assert result.row_count == fixture["row_count"]
    assert result.bad_timestamp_count == 0
    assert not result.missing_metrics
    assert not _table_exists(db_path, "report_metadata")
    assert {"industrial_record_id", "cycle_time_s", "temperature_c", "process_datetime"}.issubset(
        frame.columns
    )
    assert pd.api.types.is_numeric_dtype(frame["cycle_time_s"])
    assert pd.api.types.is_datetime64_any_dtype(frame["process_datetime"])
    assert int(frame["mostly_numeric_value"].isna().sum()) == 1


def test_load_frame_chunks_large_dynamic_metric_reads(tmp_path) -> None:
    db_path = str(tmp_path / "large_dynamic.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    rows = [
        {
            "source_primary_key": f"ROW-{index}",
            "process_timestamp": "2026-05-11T00:00:00Z",
            "reference": f"REF-{index}",
            "cycle_time_s": float(index),
            "raw_record": {"event_id": f"ROW-{index}", "cycle_time_s": float(index)},
        }
        for index in range(1100)
    ]
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=rows,
        sync_run_id=sync_run_id,
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=len(rows))

    result = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    assert result.row_count == 1100
    assert "cycle_time_s" in result.dataframe.columns
    assert int(result.dataframe["cycle_time_s"].notna().sum()) == 1100


def test_load_frame_chunks_large_fixed_reference_filters(tmp_path) -> None:
    db_path = str(tmp_path / "large_fixed_filters.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    rows = [
        {
            "source_primary_key": f"ROW-{index}",
            "process_timestamp": "2026-05-11T00:00:00Z",
            "reference": f"REF-{index}",
            "cycle_time_s": float(index),
            "raw_record": {"event_id": f"ROW-{index}", "cycle_time_s": float(index)},
        }
        for index in range(1100)
    ]
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=rows,
        sync_run_id=sync_run_id,
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=len(rows))

    result = load_production_analytics_frame(
        db_path,
        filter_state=ProductionFilterState(references=tuple(f"REF-{index}" for index in range(1100))),
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    assert result.row_count == 1100
    assert int(result.dataframe["cycle_time_s"].notna().sum()) == 1100


def test_load_frame_applies_time_filters_after_parsing_mixed_timestamps(tmp_path) -> None:
    db_path = str(tmp_path / "mixed_timestamps.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=[
            {
                "source_primary_key": "ROW-OLD",
                "process_timestamp": "2026-05-10T00:00:00Z",
                "reference": "REF-OLD",
                "cycle_time_s": 10.0,
                "raw_record": {"event_id": "ROW-OLD", "cycle_time_s": 10.0},
            },
            {
                "source_primary_key": "ROW-MIXED",
                "process_timestamp": "05/12/2026 01:00:00",
                "reference": "REF-MIXED",
                "cycle_time_s": 12.0,
                "raw_record": {"event_id": "ROW-MIXED", "cycle_time_s": 12.0},
            },
        ],
        sync_run_id=sync_run_id,
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=2)

    result = load_production_analytics_frame(
        db_path,
        filter_state=ProductionFilterState(time_start="2026-05-11T00:00:00Z"),
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    assert result.row_count == 1
    assert result.dataframe["reference"].tolist() == ["REF-MIXED"]
    assert "time_filters_applied" in {diagnostic.code for diagnostic in result.diagnostics}


def test_load_frame_respects_fixed_reference_and_source_filters(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    fixture = seed_production_analytics_cache(db_path)
    profile = fixture["profile"]

    result = load_production_analytics_frame(
        db_path,
        filter_state=ProductionFilterState(
            source_profile_ids=(profile.id,),
            references=("REF-100",),
            stations=("S1",),
        ),
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    assert result.has_rows
    assert set(result.dataframe["reference"]) == {"REF-100"}
    assert set(result.dataframe["station"]) == {"S1"}
    assert set(result.dataframe["source_profile_id"]) == {profile.id}


def test_missing_selected_metric_returns_warning_not_crash(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    result = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("unknown_metric"),),
    )

    assert result.has_rows
    assert result.missing_metrics == ("unknown_metric",)
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["missing_selected_metrics"]


def test_missing_industrial_cache_tables_return_unavailable_diagnostic(tmp_path) -> None:
    db_path = str(tmp_path / "empty.db")
    sqlite3.connect(db_path).close()

    result = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    assert not result.has_rows
    assert result.diagnostics[0].code == "industrial_cache_unavailable"
    assert discover_production_metric_candidates(db_path) == ()


def test_load_frame_applies_dynamic_numeric_filters(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    result = load_production_analytics_frame(
        db_path,
        filter_state=ProductionFilterState(
            dynamic_filters=(
                DynamicFieldFilter("cycle_time_s", "gt", 40, value_kind="numeric"),
            )
        ),
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    assert result.has_rows
    assert result.dataframe["cycle_time_s"].min() > 40
    assert "dynamic_filters_applied" in {diagnostic.code for diagnostic in result.diagnostics}


def test_load_frame_applies_dynamic_text_filters(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)

    result = load_production_analytics_frame(
        db_path,
        filter_state=ProductionFilterState(
            dynamic_filters=(DynamicFieldFilter("fixture_text_code", "contains", "ALP"),)
        ),
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    assert result.has_rows
    assert set(result.dataframe["fixture_text_code"]) == {"alpha"}


def test_apply_production_filters_handles_time_range_on_loaded_frame(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    loaded = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    filtered = apply_production_filters(
        loaded.dataframe,
        ProductionFilterState(
            time_start="2026-05-11T00:00:00Z",
            time_end="2026-05-12T00:00:00Z",
        ),
    )

    assert filtered.output_row_count < filtered.input_row_count
    assert filtered.dataframe["process_datetime"].min() >= pd.Timestamp(
        "2026-05-11T00:00:00Z"
    )
    assert filtered.dataframe["process_datetime"].max() < pd.Timestamp(
        "2026-05-12T00:00:00Z"
    )


def test_reference_cohort_marks_missing_and_filters_selected_references(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    loaded = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    highlighted = apply_reference_cohorts(
        loaded.dataframe,
        ReferenceCohortState.from_text("REF-100\nREF-NOT-FOUND", mode="compare_rest"),
    )

    assert highlighted.selected_count > 0
    assert highlighted.missing_references == ("REF-NOT-FOUND",)
    assert set(highlighted.dataframe["reference_cohort"]) == {
        "Selected references",
        "Other references",
    }

    filtered = apply_reference_cohorts(
        loaded.dataframe,
        ReferenceCohortState.from_text("REF-100", mode="filter_selected"),
    )
    assert set(filtered.dataframe["reference"]) == {"REF-100"}


def test_aggregate_production_frame_by_day_and_station(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    loaded = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    aggregated = aggregate_production_frame(
        loaded.dataframe,
        ProductionAggregationState(
            time_bucket="day",
            aggregation_methods=("mean", "median", "count"),
            group_fields=("station",),
        ),
        (ProductionMetricSelection("cycle_time_s"),),
    )

    assert aggregated.is_aggregated
    assert aggregated.output_row_count > 0
    assert {
        "time_bucket_start",
        "station",
        "raw_row_count",
        "cycle_time_s__mean",
        "cycle_time_s__median",
        "cycle_time_s__count",
    }.issubset(aggregated.dataframe.columns)
    assert int(aggregated.dataframe["raw_row_count"].sum()) == loaded.row_count


def test_aggregate_production_frame_week_bucket_starts_on_monday(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    loaded = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    aggregated = aggregate_production_frame(
        loaded.dataframe,
        ProductionAggregationState(time_bucket="week", aggregation_methods=("mean",)),
        (ProductionMetricSelection("cycle_time_s"),),
    )

    assert aggregated.is_aggregated
    assert set(aggregated.dataframe["time_bucket_start"].dt.weekday) == {0}


def test_aggregate_production_frame_none_preserves_row_level_values(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    loaded = load_production_analytics_frame(
        db_path,
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
    )

    row_level = aggregate_production_frame(
        loaded.dataframe,
        ProductionAggregationState(time_bucket="none", aggregation_methods=("mean",)),
        (ProductionMetricSelection("cycle_time_s"),),
    )

    assert not row_level.is_aggregated
    assert row_level.output_row_count == loaded.row_count
    assert "cycle_time_s" in row_level.dataframe.columns


def test_groupstats_inputs_support_line_grouping(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    metric = ProductionMetricSelection("cycle_time_s")
    loaded = load_production_analytics_frame(db_path, metric_selection=(metric,))

    inputs = build_production_groupstats_inputs(
        loaded.dataframe,
        metric,
        group_fields=("line",),
    )

    assert inputs.group_fields == ("line",)
    assert set(inputs.grouped_values) == {"L1", "L2"}
    assert all(len(values) > 0 for values in inputs.grouped_values.values())
    assert all(isinstance(values, np.ndarray) for values in inputs.grouped_values.values())


def test_groupstats_inputs_convert_metric_once_per_metric(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "GROUP": ["A", "A", "B", "B", "C", "C"],
            "length_mm": ["1.0", "bad", "2.0", "3.0", None, "4.0"],
        }
    )
    metric = ProductionMetricSelection("length_mm", "Length")
    original_to_numeric = industrial_analytics_service.pd.to_numeric
    calls = 0

    def count_to_numeric(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_to_numeric(*args, **kwargs)

    monkeypatch.setattr(industrial_analytics_service.pd, "to_numeric", count_to_numeric)

    inputs = build_production_groupstats_inputs(frame, metric, group_fields=("GROUP",))

    assert calls == 1
    assert inputs.grouped_values["A"].tolist() == [1.0]
    assert inputs.grouped_values["B"].tolist() == [2.0, 3.0]
    assert inputs.grouped_values["C"].tolist() == [4.0]


def test_groupstats_analysis_reuses_prepared_numpy_groups(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "GROUP": ["A", "A", "A", "B", "B", "B"],
            "length_mm": [1.0, "2.0", "bad", 4.0, 5.0, 6.0],
            "width_mm": [10.0, 11.0, 12.0, 20.0, None, 22.0],
        }
    )
    calls: list[tuple[str, dict[str, np.ndarray]]] = []

    def fake_analyze_group_metric(metric_identity, grouped_values, **_kwargs):
        calls.append((metric_identity, grouped_values))
        return {
            "spec_status": "no_spec",
            "descriptive_stats": [
                {"group": label, "n": len(values)}
                for label, values in grouped_values.items()
            ],
            "pairwise_rows": [],
            "posthoc_rows": [],
            "capability_rows": [],
            "metric_summary": {"metric": metric_identity},
            "capability": {},
        }

    monkeypatch.setattr(
        "modules.industrial_analytics_service.analyze_group_metric",
        fake_analyze_group_metric,
    )

    result = analyze_production_groupstats(
        frame,
        (
            ProductionMetricSelection("length_mm", "Length"),
            ProductionMetricSelection("width_mm", "Width"),
        ),
        group_fields=("GROUP",),
    )

    assert result.analyzed_metric_count == 2
    assert [metric["metric"] for metric in result.metrics] == ["Length", "Width"]
    assert [identity for identity, _grouped_values in calls] == ["Length", "Width"]
    for _identity, grouped_values in calls:
        assert set(grouped_values) == {"A", "B"}
        assert all(isinstance(values, np.ndarray) for values in grouped_values.values())
        assert all(values.dtype.kind == "f" for values in grouped_values.values())
    assert calls[0][1]["A"].tolist() == [1.0, 2.0]
    assert calls[1][1]["B"].tolist() == [20.0, 22.0]


def test_groupstats_reference_cohort_compares_selected_against_rest(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    metric = ProductionMetricSelection("cycle_time_s")
    loaded = load_production_analytics_frame(db_path, metric_selection=(metric,))
    cohort_state = ReferenceCohortState.from_text("REF-100\nREF-101", mode="compare_rest")
    cohort = apply_reference_cohorts(loaded.dataframe, cohort_state)

    result = analyze_production_groupstats(
        cohort.dataframe,
        (metric,),
        cohort_state=cohort_state,
    )

    assert result.analyzed_metric_count == 1
    metric_result = result.metrics[0]
    assert not metric_result["skipped"]
    assert metric_result["group_fields"] == ["reference_cohort"]
    assert set(metric_result["group_sample_counts"]) == {"Selected references", "Other references"}
    assert metric_result["descriptive_stats"]
    assert "result" not in metric_result


def test_groupstats_insufficient_groups_returns_diagnostic_not_crash(tmp_path) -> None:
    db_path = str(tmp_path / "production_only.db")
    seed_production_analytics_cache(db_path)
    metric = ProductionMetricSelection("cycle_time_s")
    loaded = load_production_analytics_frame(
        db_path,
        filter_state=ProductionFilterState(lines=("L1",)),
        metric_selection=(metric,),
    )

    result = analyze_production_groupstats(
        loaded.dataframe,
        (metric,),
        group_fields=("line",),
    )

    assert result.metrics[0]["skipped"]
    assert "groupstats_insufficient_groups" in {diagnostic.code for diagnostic in result.diagnostics}
