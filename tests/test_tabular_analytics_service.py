from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd

from modules.industrial_analytics_dashboard import build_production_dashboard_manifest
from modules.industrial_analytics_service import (
    ProductionGroupstatsResult,
    aggregate_production_frame,
    analyze_production_groupstats,
)
from modules.industrial_analytics_state import (
    ProductionAggregationState,
    ProductionChartSelection,
    ProductionMetricSelection,
)
from modules.tabular_analytics_service import (
    TABULAR_GROUP_COLUMN,
    TabularColumnFilter,
    apply_tabular_row_filter,
    apply_tabular_grouping,
    build_tabular_grouping_dataframe,
    cleanup_tabular_load_result,
    count_tabular_materialized_rows,
    export_tabular_analytics_workbook,
    load_tabular_analytics_file,
    load_tabular_analytics_files,
    materialize_tabular_dataframe,
)


def _sample_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=6, freq="12h"),
            "Reference ID": ["R1", "R1", "R2", "R2", "R3", "R3"],
            "Line": ["L1", "L1", "L2", "L2", "L1", "L2"],
            "Length mm": [10.0, 10.1, 10.2, 10.4, 10.3, 10.5],
            "Width mm": [5.0, 5.1, 5.2, 5.4, 5.3, 5.5],
            "Comment": ["ok", "ok", "review", "ok", "ok", "review"],
        }
    )


def test_load_tabular_analytics_file_detects_csv_metrics_and_contract_columns(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file)
    by_name = {candidate.field_name: candidate for candidate in result.metric_candidates}

    assert {"length_mm", "width_mm"}.issubset(by_name)
    assert "comment" not in by_name
    assert "process_datetime" in result.dataframe.columns
    assert "reference" in result.dataframe.columns
    assert set(result.dataframe["reference"]) == {"R1", "R2", "R3"}
    assert result.csv_config["delimiter"] == ","


def test_load_tabular_analytics_file_uses_explicit_time_and_reference_columns(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    pd.DataFrame(
        {
            "Created At": pd.date_range("2026-05-10 08:00", periods=4, freq="h"),
            "Batch Number": [1001, 1001, 1002, 1002],
            "Numeric ID": [1, 2, 3, 4],
            "Length mm": [10.0, 10.2, 10.1, 10.4],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(
        input_file,
        timestamp_column="Created At",
        reference_column="Batch Number",
    )

    assert result.timestamp_column == "created_at"
    assert result.reference_column == "batch_number"
    assert set(result.dataframe["reference"]) == {"1001", "1002"}
    assert result.dataframe["process_datetime"].notna().all()
    assert "batch_number" not in {candidate.field_name for candidate in result.metric_candidates}


def test_load_tabular_analytics_file_does_not_steal_cycle_time_as_timestamp(tmp_path) -> None:
    input_file = tmp_path / "cycle_times.csv"
    pd.DataFrame(
        {
            "Reference ID": ["R1", "R2", "R3"],
            "Update Count": [1, 2, 3],
            "Cycle Time S": [38.1, 39.4, 37.9],
            "Result": ["ok", "ok", "review"],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file)

    assert result.timestamp_column is None
    assert result.dataframe["process_datetime"].isna().all()
    metric_names = {candidate.field_name for candidate in result.metric_candidates}
    assert "update_count" in metric_names
    assert "cycle_time_s" in metric_names
    assert "tabular_timestamp_not_selected" in {
        diagnostic.code for diagnostic in result.diagnostics
    }


def test_load_tabular_analytics_file_preserves_source_columns_that_match_internal_names(
    tmp_path,
) -> None:
    input_file = tmp_path / "internal_names.csv"
    pd.DataFrame(
        {
            "source_row_number": [9001, 9002],
            "source_file": ["operator-a.csv", "operator-b.csv"],
            "reference": ["R1", "R2"],
            "GROUP": ["Shift A", "Shift B"],
            "Length mm": [10.0, 10.2],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file)

    assert result.dataframe["source_row_number"].tolist() == [1, 2]
    assert result.dataframe["source_file"].tolist() == ["internal_names.csv", "internal_names.csv"]
    assert result.dataframe["reference"].tolist() == ["R1", "R2"]
    assert result.dataframe["input_source_row_number"].tolist() == [9001, 9002]
    assert result.dataframe["input_source_file"].tolist() == ["operator-a.csv", "operator-b.csv"]
    assert result.dataframe["input_group"].tolist() == ["Shift A", "Shift B"]
    assert result.column_mapping["source_row_number"] == "input_source_row_number"
    assert result.column_mapping["GROUP"] == "input_group"


def test_load_tabular_analytics_files_combines_multiple_csvs_in_sqlite(tmp_path) -> None:
    first_file = tmp_path / "line_a.csv"
    second_file = tmp_path / "line_b.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=3, freq="h"),
            "Line": ["A", "A", "B"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(first_file, index=False)
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-11 08:00", periods=2, freq="h"),
            "Line": ["B", "A"],
            "Length mm": [10.6, 10.8],
        }
    ).to_csv(second_file, index=False)

    result = load_tabular_analytics_files((first_file, second_file))
    sqlite_path = Path(result.sqlite_store.path)
    try:
        assert result.storage_mode == "sqlite"
        assert sqlite_path.exists()
        assert result.row_count == 5
        assert result.source_files == (str(first_file), str(second_file))
        assert [snapshot.row_count for snapshot in result.source_snapshots] == [3, 2]
        assert result.dataframe["source_row_number"].tolist() == [1, 2, 3, 4, 5]
        assert result.dataframe["source_file"].tolist() == [
            "line_a.csv",
            "line_a.csv",
            "line_a.csv",
            "line_b.csv",
            "line_b.csv",
        ]
        assert {candidate.field_name for candidate in result.metric_candidates} == {"length_mm"}

        filtered = materialize_tabular_dataframe(
            result,
            column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
            required_columns=("source_row_number", "length_mm"),
        )

        assert filtered.applied is True
        assert filtered.input_row_count == 5
        assert filtered.output_row_count == 3
        assert count_tabular_materialized_rows(
            result,
            column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
        ) == 3
        assert filtered.dataframe.columns.tolist() == ["source_row_number", "length_mm"]
        assert filtered.dataframe["source_row_number"].tolist() == [1, 2, 5]
    finally:
        cleanup_tabular_load_result(result)
    assert not sqlite_path.exists()


def test_load_tabular_analytics_file_can_use_sqlite_for_single_csv_filters(tmp_path) -> None:
    input_file = tmp_path / "single_large_path.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=5, freq="D"),
            "Station": ["A", "B", "A", "A", "B"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        assert result.storage_mode == "sqlite"
        assert result.row_count == 5
        assert result.source_snapshots[0].row_count == 5

        filtered = materialize_tabular_dataframe(
            result,
            column_filters=(
                TabularColumnFilter("station", selected_values=("A",)),
                TabularColumnFilter(
                    "time_stamp",
                    date_mode="between",
                    date_from="2026-05-11",
                    date_to="2026-05-13",
                ),
            ),
        )

        assert filtered.output_row_count == 2
        assert filtered.dataframe["station"].tolist() == ["A", "A"]
        assert pd.to_datetime(filtered.dataframe["time_stamp"]).dt.strftime("%Y-%m-%d").tolist() == [
            "2026-05-12",
            "2026-05-13",
        ]
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_group_preview_and_selection_respect_column_filters(tmp_path) -> None:
    input_file = tmp_path / "group_preview.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=5, freq="D"),
            "Line": ["L1", "L1", "L2", "L1", "L2"],
            "Station": ["A", "B", "A", "A", "B"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        filters = (
            TabularColumnFilter("line", selected_values=("L1",)),
            TabularColumnFilter("time_stamp", date_mode="from", date_from="2026-05-13"),
        )

        rows, total = result.sqlite_store.preview_group_rows(
            ("station",),
            column_filters=filters,
            limit=20,
        )
        searched_rows, searched_total = result.sqlite_store.preview_group_rows(
            ("station",),
            column_filters=(TabularColumnFilter("line", selected_values=("L1",)),),
            search_text="b",
            limit=20,
        )

        assert total == 1
        assert rows == [{"key": ("A",), "label": "A", "row_count": 1}]
        assert searched_total == 1
        assert searched_rows == [{"key": ("B",), "label": "B", "row_count": 1}]
        assert result.sqlite_store.row_ids_for_group_keys(
            ("station",),
            {("A",)},
            column_filters=filters,
        ) == [4]
        assert result.sqlite_store.count_rows_for_group_keys(
            ("station",),
            {("A",)},
            column_filters=filters,
        ) == 1
        assert result.sqlite_store.count_source_row_numbers(
            [1, 4],
            column_filters=filters,
        ) == 1
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_group_preview_search_treats_wildcards_literally(tmp_path) -> None:
    input_file = tmp_path / "wildcards.csv"
    pd.DataFrame(
        {
            "Station": ["100%", "1000", "A_1", "AB1"],
            "Length mm": [10.0, 10.1, 10.2, 10.3],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        percent_rows, percent_total = result.sqlite_store.preview_group_rows(
            ("station",),
            search_text="100%",
            limit=20,
        )
        underscore_rows, underscore_total = result.sqlite_store.preview_group_rows(
            ("station",),
            search_text="A_",
            limit=20,
        )

        assert percent_total == 1
        assert percent_rows == [{"key": ("100%",), "label": "100%", "row_count": 1}]
        assert underscore_total == 1
        assert underscore_rows == [{"key": ("A_1",), "label": "A_1", "row_count": 1}]
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_tabular_date_filter_matches_pandas_for_non_iso_dates(tmp_path) -> None:
    input_file = tmp_path / "non_iso_dates.csv"
    pd.DataFrame(
        {
            "Time Stamp": ["05/10/2026", "05/11/2026", "05/12/2026"],
            "Station": ["A", "B", "A"],
            "Length mm": [10.0, 10.1, 10.2],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        filtered = materialize_tabular_dataframe(
            result,
            column_filters=(
                TabularColumnFilter(
                    "time_stamp",
                    date_mode="between",
                    date_from="2026-05-11",
                    date_to="2026-05-12",
                ),
            ),
        )

        assert filtered.output_row_count == 2
        assert filtered.dataframe["time_stamp"].tolist() == ["05/11/2026", "05/12/2026"]
        assert not any(str(column).startswith("__date_filter_") for column in filtered.dataframe.columns)
        assert result.sqlite_store.date_bounds("time_stamp") == (
            pd.Timestamp("2026-05-10").date(),
            pd.Timestamp("2026-05-12").date(),
        )
    finally:
        cleanup_tabular_load_result(result)


def test_load_tabular_analytics_file_detects_excel_metrics(tmp_path) -> None:
    input_file = tmp_path / "table.xlsx"
    _sample_table().to_excel(input_file, index=False, sheet_name="Measurements")

    result = load_tabular_analytics_file(input_file, sheet_name="Measurements")
    metric_names = {candidate.field_name for candidate in result.metric_candidates}

    assert {"length_mm", "width_mm"}.issubset(metric_names)
    assert result.sheet_name == "Measurements"
    assert result.dataframe["process_datetime"].notna().all()


def test_tabular_reference_inference_does_not_treat_width_as_id(tmp_path) -> None:
    input_file = tmp_path / "width_only.xlsx"
    pd.DataFrame({"Width mm": [5.0, 5.2]}).to_excel(
        input_file,
        index=False,
        sheet_name="Measurements",
    )

    result = load_tabular_analytics_file(input_file, sheet_name="Measurements")

    assert result.reference_column is None
    assert {candidate.field_name for candidate in result.metric_candidates} == {"width_mm"}


def test_tabular_grouping_dataframe_builds_source_row_identity_rows(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    grouping_frame = build_tabular_grouping_dataframe(loaded.dataframe)

    assert grouping_frame["REPORT_ID"].tolist() == [1, 2, 3, 4, 5, 6]
    assert set(grouping_frame["REFERENCE"]) == {"R1", "R2", "R3"}
    assert grouping_frame["SAMPLE_NUMBER"].tolist() == ["1", "2", "3", "4", "5", "6"]
    assert grouping_frame["FILENAME"].str.contains("table.csv").all()


def test_tabular_grouping_dataframe_uses_user_selector_columns_independent_of_reference(
    tmp_path,
) -> None:
    input_file = tmp_path / "tracecodes.csv"
    pd.DataFrame(
        {
            "Batch": ["B1", "B1", "B2"],
            "TraceCode": ["TC-001", "TC-002", "TC-003"],
            "Cavity": ["C1", "C2", "C1"],
            "Length mm": [10.0, 10.1, 10.2],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, reference_column="Batch")

    grouping_frame = build_tabular_grouping_dataframe(
        loaded.dataframe,
        selector_columns=("tracecode", "cavity"),
    )

    assert loaded.reference_column == "batch"
    assert grouping_frame["REFERENCE"].tolist() == [
        "TC-001 | C1",
        "TC-002 | C2",
        "TC-003 | C1",
    ]
    assert grouping_frame["PART_NAME"].tolist() == grouping_frame["REFERENCE"].tolist()


def test_apply_tabular_row_filter_uses_selected_column_keys(tmp_path) -> None:
    input_file = tmp_path / "tracecodes.csv"
    pd.DataFrame(
        {
            "Reference": ["R1", "R2", "R3"],
            "TraceCode": ["TC-001", "TC-002", "TC-003"],
            "Length mm": [10.0, 10.2, 10.4],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    filtered = apply_tabular_row_filter(
        loaded.dataframe,
        filter_columns=("tracecode",),
        selected_filter_keys=(("TC-001",), ("TC-003",)),
    )

    assert filtered.applied is True
    assert filtered.input_row_count == 3
    assert filtered.output_row_count == 2
    assert filtered.dataframe["tracecode"].tolist() == ["TC-001", "TC-003"]
    assert [diagnostic.code for diagnostic in filtered.diagnostics] == ["tabular_filters_applied"]


def test_apply_tabular_row_filter_combines_column_scoped_filters_and_date_bounds(tmp_path) -> None:
    input_file = tmp_path / "column_filters.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=5, freq="D"),
            "Line": ["L1", "L1", "L2", "L1", "L2"],
            "Station": ["A", "B", "A", "A", "B"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    filtered = apply_tabular_row_filter(
        loaded.dataframe,
        column_filters=(
            TabularColumnFilter("line", selected_values=("L1",)),
            TabularColumnFilter("station", selected_values=("A",)),
            TabularColumnFilter(
                "time_stamp",
                date_mode="between",
                date_from="2026-05-11",
                date_to="2026-05-13",
            ),
        ),
    )

    assert filtered.applied is True
    assert filtered.output_row_count == 1
    assert filtered.dataframe["line"].tolist() == ["L1"]
    assert filtered.dataframe["station"].tolist() == ["A"]
    assert pd.to_datetime(filtered.dataframe["time_stamp"]).dt.strftime("%Y-%m-%d").tolist() == [
        "2026-05-13"
    ]
    assert filtered.diagnostics[0].context["column_filters"][2]["date_mode"] == "between"


def test_apply_tabular_row_filter_supports_numeric_comparisons_and_ignores_non_numeric_values(
    tmp_path,
) -> None:
    input_file = tmp_path / "numeric_filters.csv"
    pd.DataFrame(
        {
            "Value": [1, "1", "2", "x", None],
            "Value2": [0, 2, 2, "x", 2],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    filtered = apply_tabular_row_filter(
        loaded.dataframe,
        column_filters=(
            TabularColumnFilter("value", numeric_operator="=", numeric_value="1"),
            TabularColumnFilter("value2", numeric_operator=">", numeric_value="1"),
        ),
    )

    assert filtered.applied is True
    assert filtered.output_row_count == 1
    assert filtered.dataframe["source_row_number"].tolist() == [2]
    assert filtered.diagnostics[0].context["column_filters"][0]["numeric_operator"] == "="
    assert filtered.diagnostics[0].context["column_filters"][1]["numeric_operator"] == ">"


def test_sqlite_tabular_numeric_filters_match_expected_rows(tmp_path) -> None:
    input_file = tmp_path / "numeric_filters_sqlite.csv"
    pd.DataFrame(
        {
            "Value": [1, "1", "2", "x", None],
            "Value2": [0, 2, 2, "x", 2],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        equals_and_gt = materialize_tabular_dataframe(
            loaded,
            column_filters=(
                TabularColumnFilter("value", numeric_operator="=", numeric_value="1"),
                TabularColumnFilter("value2", numeric_operator=">", numeric_value="1"),
            ),
        )
        gt_only = materialize_tabular_dataframe(
            loaded,
            column_filters=(TabularColumnFilter("value2", numeric_operator=">", numeric_value="1"),),
        )

        assert equals_and_gt.output_row_count == 1
        assert equals_and_gt.dataframe["source_row_number"].tolist() == [2]
        assert gt_only.output_row_count == 3
        assert gt_only.dataframe["source_row_number"].tolist() == [2, 3, 5]
        assert count_tabular_materialized_rows(
            loaded,
            column_filters=(TabularColumnFilter("value2", numeric_operator=">", numeric_value="1"),),
        ) == 3
    finally:
        cleanup_tabular_load_result(loaded)


def test_sqlite_materialization_projects_columns_and_count_uses_pushdown(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "wide_sqlite_projection.csv"
    row_count = 20000
    dataframe = pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=row_count, freq="min"),
            "Line": [f"L{index % 6}" for index in range(row_count)],
            "Station": [f"S{index % 4}" for index in range(row_count)],
            "Length mm": [10.0 + (index % 10) * 0.01 for index in range(row_count)],
            "Width mm": [5.0 + (index % 8) * 0.01 for index in range(row_count)],
            "Meta A": [f"A{index % 100}" for index in range(row_count)],
            "Meta B": [f"B{index % 80}" for index in range(row_count)],
            "Meta C": [f"C{index % 60}" for index in range(row_count)],
            "Meta D": [f"D{index % 40}" for index in range(row_count)],
        }
    )
    dataframe.to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    assert loaded.sqlite_store is not None

    requested_columns: list[tuple[str, ...] | None] = []
    store_type = type(loaded.sqlite_store)
    original_read_dataframe = store_type.read_dataframe

    def capture_read_dataframe(self, *args, **kwargs):
        columns = kwargs.get("columns")
        requested_columns.append(tuple(columns) if columns is not None else None)
        return original_read_dataframe(self, *args, **kwargs)

    monkeypatch.setattr(store_type, "read_dataframe", capture_read_dataframe)
    try:
        filtered = materialize_tabular_dataframe(
            loaded,
            column_filters=(TabularColumnFilter("line", selected_values=("L1", "L2")),),
            required_columns=("source_row_number", "line", "length_mm"),
        )

        assert filtered.applied is True
        assert filtered.input_row_count == row_count
        assert filtered.output_row_count > 0
        assert filtered.dataframe.columns.tolist() == ["source_row_number", "line", "length_mm"]
        assert requested_columns == [("source_row_number", "line", "length_mm")]

        monkeypatch.setattr(
            store_type,
            "read_dataframe",
            lambda self, *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("count should use sqlite count pushdown, not read_dataframe")
            ),
        )
        assert count_tabular_materialized_rows(
            loaded,
            column_filters=(TabularColumnFilter("line", selected_values=("L1", "L2")),),
        ) == filtered.output_row_count
    finally:
        cleanup_tabular_load_result(loaded)


def test_apply_tabular_grouping_keeps_unassigned_rows_in_population(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    grouping_frame = build_tabular_grouping_dataframe(loaded.dataframe)
    grouping_frame["GROUP"] = "POPULATION"
    grouping_frame.loc[grouping_frame["REPORT_ID"].isin([1, 2]), "GROUP"] = "Selected"

    grouped = apply_tabular_grouping(loaded.dataframe, grouping_frame)

    assert grouped.applied
    assert grouped.group_count == 2
    assert grouped.custom_group_count == 1
    assert grouped.dataframe[TABULAR_GROUP_COLUMN].tolist() == [
        "Selected",
        "Selected",
        "POPULATION",
        "POPULATION",
        "POPULATION",
        "POPULATION",
    ]
    assert [diagnostic.code for diagnostic in grouped.diagnostics] == ["tabular_grouping_applied"]


def test_apply_tabular_grouping_omits_population_when_all_rows_are_assigned(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    grouping_frame = build_tabular_grouping_dataframe(loaded.dataframe)
    grouping_frame["GROUP"] = ["A", "A", "B", "B", "C", "C"]

    grouped = apply_tabular_grouping(loaded.dataframe, grouping_frame)

    assert set(grouped.dataframe[TABULAR_GROUP_COLUMN]) == {"A", "B", "C"}
    assert grouped.diagnostics[0].context["default_group_present"] is False
    assert grouped.diagnostics[0].message == "Manual grouping applied: 3 custom group(s)."


def test_tabular_data_reuses_dashboard_and_aggregation_path(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    metrics = tuple(candidate.to_selection() for candidate in loaded.metric_candidates[:1])
    aggregation = ProductionAggregationState(
        time_bucket="day",
        aggregation_methods=("mean",),
        group_fields=("line",),
    )

    aggregated = aggregate_production_frame(loaded.dataframe, aggregation, metrics)
    manifest = build_production_dashboard_manifest(
        frame=loaded.dataframe,
        metric_selection=metrics,
        aggregation_state=aggregation,
        aggregation_result=aggregated,
        chart_selection=ProductionChartSelection(time_series=True, histogram=True, violin=True, box=True),
        diagnostics=loaded.diagnostics + aggregated.diagnostics,
    )

    assert aggregated.is_aggregated
    assert "line" in aggregated.dataframe.columns
    assert manifest["summary"]["chart_count"] == 5
    assert {chart["chart_type"] for chart in manifest["charts"]} == {
        "time_series",
        "time_series_raw_aggregate",
        "histogram",
        "violin",
        "box",
    }
    histogram = next(chart for chart in manifest["charts"] if chart["chart_type"] == "histogram")
    assert histogram["plotly_spec"]["config"].get("staticPlot") is not True
    assert histogram["plotly_spec"]["layout"]["yaxis"]["title"]["text"] == "Frequency (%)"
    assert histogram["group_labels"] == ["L1", "L2"]
    assert histogram["stats_tables"]


def test_tabular_groupstats_without_specs_runs_overall_and_unique_pairwise_tests() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=24, freq="h"),
            "GROUP": ["POPULATION"] * 8 + ["A"] * 8 + ["B"] * 8,
            "length_mm": [
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                8.0,
                10.0,
                11.0,
                12.0,
                13.0,
                14.0,
                15.0,
                16.0,
                17.0,
                1.1,
                2.1,
                3.1,
                4.1,
                5.1,
                6.1,
                7.1,
                8.1,
            ],
        }
    )

    result = analyze_production_groupstats(
        frame,
        (ProductionMetricSelection("length_mm", "Length Mm"),),
        group_fields=("GROUP",),
    )

    metric = result.metrics[0]
    assert metric["omnibus"]["test_name"]
    assert metric["omnibus"]["p_value"] is not None
    assert [(row["group_a"], row["group_b"]) for row in metric["pairwise_rows"]] == [
        ("POPULATION", "A"),
        ("POPULATION", "B"),
        ("A", "B"),
    ]
    assert all(
        (row["group_b"], row["group_a"]) not in {
            (other["group_a"], other["group_b"])
            for other in metric["pairwise_rows"]
        }
        for row in metric["pairwise_rows"]
    )
    assert {row["significant"] for row in metric["pairwise_rows"]} == {False, True}


def test_tabular_groupstats_without_population_compares_each_custom_pair() -> None:
    frame = pd.DataFrame(
        {
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=24, freq="h"),
            "GROUP": ["A"] * 8 + ["B"] * 8 + ["C"] * 8,
            "length_mm": [
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                8.0,
                10.0,
                11.0,
                12.0,
                13.0,
                14.0,
                15.0,
                16.0,
                17.0,
                20.0,
                21.0,
                22.0,
                23.0,
                24.0,
                25.0,
                26.0,
                27.0,
            ],
        }
    )

    result = analyze_production_groupstats(
        frame,
        (ProductionMetricSelection("length_mm", "Length Mm"),),
        group_fields=("GROUP",),
    )

    metric = result.metrics[0]
    assert metric["group_sample_counts"] == {"A": 8, "B": 8, "C": 8}
    assert [(row["group_a"], row["group_b"]) for row in metric["pairwise_rows"]] == [
        ("A", "B"),
        ("A", "C"),
        ("B", "C"),
    ]
    assert all("POPULATION" not in (row["group_a"], row["group_b"]) for row in metric["pairwise_rows"])


def test_tabular_aggregation_counts_source_rows_when_metric_values_are_missing() -> None:
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3],
            "process_datetime": pd.date_range("2026-05-10 08:00", periods=3, freq="h"),
            "machine": ["M1", "M1", "M2"],
            "length_mm": [10.0, None, 10.5],
        }
    )

    aggregated = aggregate_production_frame(
        frame,
        ProductionAggregationState(
            time_bucket="none",
            aggregation_methods=("mean",),
            group_fields=("machine",),
        ),
        (ProductionMetricSelection("length_mm", "Length Mm"),),
    )

    by_machine = dict(zip(aggregated.dataframe["machine"], aggregated.dataframe["raw_row_count"], strict=False))
    assert by_machine == {"M1": 2, "M2": 1}
    assert int(aggregated.dataframe["raw_row_count"].sum()) == len(frame.index)


def test_tabular_workbook_export_writes_separate_parameter_sheets(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    output_file = tmp_path / "analytics.xlsx"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    metrics = tuple(candidate.to_selection() for candidate in loaded.metric_candidates)
    aggregated = aggregate_production_frame(
        loaded.dataframe,
        ProductionAggregationState(time_bucket="day", aggregation_methods=("mean",)),
        metrics,
    )

    result = export_tabular_analytics_workbook(
        dataframe=loaded.dataframe,
        metric_candidates=loaded.metric_candidates,
        output_file=output_file,
        aggregation_result=aggregated,
        diagnostics=loaded.diagnostics + aggregated.diagnostics,
        separate_parameter_sheets=True,
    )

    assert Path(result.output_file).exists()
    assert result.parameter_sheet_count == len(loaded.metric_candidates)
    workbook = pd.ExcelFile(output_file)
    assert {"Table Data", "Aggregates", "Metrics", "Diagnostics"}.issubset(workbook.sheet_names)
    assert {"Length Mm", "Width Mm"}.issubset(workbook.sheet_names)


def test_tabular_workbook_export_includes_selected_chart_outputs(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    output_file = tmp_path / "analytics_with_charts.xlsx"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)

    result = export_tabular_analytics_workbook(
        dataframe=loaded.dataframe,
        metric_candidates=loaded.metric_candidates[:1],
        output_file=output_file,
        chart_selection=ProductionChartSelection(
            time_series=True,
            histogram=True,
            violin=True,
            box=True,
        ),
        separate_parameter_sheets=False,
    )

    assert "Charts" in result.sheet_names
    with zipfile.ZipFile(output_file) as workbook_zip:
        names = set(workbook_zip.namelist())
    assert any(name.startswith("xl/charts/chart") for name in names)
    assert any(name.startswith("xl/media/image") for name in names)


def test_tabular_workbook_export_includes_groupstats_distribution_rows(tmp_path) -> None:
    input_file = tmp_path / "table.csv"
    output_file = tmp_path / "analytics_groupstats.xlsx"
    _sample_table().to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file)
    groupstats = ProductionGroupstatsResult(
        metrics=(
            {
                "metric": "Length Mm",
                "primary_insight": {"headline": "Selected group has higher mean."},
                "metric_summary": {"simulation_validation": {"iterations": 3}},
                "descriptive_stats": (
                    {
                        "group": "A",
                        "n": 3,
                        "mean": 10.2,
                        "std": 0.1,
                        "median": 10.2,
                        "iqr": 0.1,
                        "min": 10.0,
                        "max": 10.4,
                        "cp": 1.1,
                        "cpk": 1.0,
                        "capability": "ok",
                        "nok_count": 0,
                        "nok_percent": 0.0,
                    },
                ),
                "distribution_rows": (
                    {
                        "group": "A",
                        "n": 3,
                        "skewness": 0.2,
                        "excess_kurtosis": -1.0,
                        "normality_test": "Shapiro-Wilk",
                        "normality_p_value": 0.82,
                        "normality_status": "consistent",
                    },
                ),
                "capability_rows": (
                    {
                        "group": "A",
                        "n": 3,
                        "mean": 10.2,
                        "sigma": 0.1,
                        "cp": 1.1,
                        "cpk": 1.0,
                    },
                ),
                "pairwise_rows": (),
                "posthoc_rows": (
                    {
                        "group_a": "A",
                        "group_b": "B",
                        "family": "parametric",
                        "method_name": "Games-Howell",
                        "adjusted_p_value": 0.03,
                        "effect_size": 0.7,
                        "effect_type": "hedges_g",
                    },
                ),
            },
        ),
    )

    result = export_tabular_analytics_workbook(
        dataframe=loaded.dataframe,
        metric_candidates=loaded.metric_candidates[:1],
        output_file=output_file,
        groupstats_result=groupstats,
        separate_parameter_sheets=False,
    )

    assert "Groupstats" in result.sheet_names
    groupstats_sheet = pd.read_excel(output_file, sheet_name="Groupstats")
    assert {"insight", "descriptive", "distribution", "capability", "posthoc"}.issubset(
        set(groupstats_sheet["row_type"])
    )
    distribution = groupstats_sheet[groupstats_sheet["row_type"] == "distribution"].iloc[0]
    assert distribution["normality_test"] == "Shapiro-Wilk"
    assert distribution["skewness"] == 0.2
    posthoc = groupstats_sheet[groupstats_sheet["row_type"] == "posthoc"].iloc[0]
    assert posthoc["test_used"] == "Games-Howell"
    assert posthoc["effect_type"] == "hedges_g"
