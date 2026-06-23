from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import warnings
import zipfile

import pandas as pd
import pytest

from modules.grouping_filter_core import (
    NumberFilterSpec,
    TextFilterSpec,
    apply_filter_specs,
    parse_filter_expression,
)
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
    TABULAR_DEFAULT_GROUP,
    TABULAR_GROUP_COLUMN,
    TabularColumnFilter,
    TabularLoadCancelled,
    TabularSourceSnapshot,
    TabularSqliteFilterExpression,
    apply_tabular_row_filter,
    apply_tabular_grouping,
    build_tabular_file_grouping_dataframe,
    build_tabular_grouping_dataframe,
    cleanup_tabular_load_result,
    compile_tabular_sqlite_grouping_filter,
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


def _sqlite_index_names(store) -> set[str]:
    with sqlite3.connect(store.path) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?",
                (store.table_name,),
            ).fetchall()
        }


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


def test_build_tabular_file_grouping_dataframe_assigns_custom_file_groups_only() -> None:
    frame = pd.DataFrame(
        {
            "source_row_number": [1, 2, 3, 4],
            "source_file": ["dataset1.csv", "dataset1.csv", "supplier1.csv", "test123.csv"],
            "length_mm": [10.0, 10.2, 10.4, 10.6],
        }
    )

    grouping = build_tabular_file_grouping_dataframe(frame)
    grouped = apply_tabular_grouping(frame, grouping)

    assert grouping.to_dict("list") == {
        "REPORT_ID": [1, 2, 3, 4],
        "GROUP": ["dataset1", "dataset1", "supplier1", "test123"],
    }
    assert grouped.applied is True
    assert grouped.custom_group_count == 3
    assert TABULAR_DEFAULT_GROUP not in set(grouped.dataframe[TABULAR_GROUP_COLUMN])


def test_build_tabular_file_grouping_dataframe_disambiguates_duplicate_and_reserved_stems() -> None:
    snapshots = (
        TabularSourceSnapshot(
            path="/tmp/first/dataset.csv",
            name="dataset.csv",
            size=10,
            mtime_ns=1,
            row_count=2,
        ),
        TabularSourceSnapshot(
            path="/tmp/second/dataset.csv",
            name="dataset.csv",
            size=10,
            mtime_ns=2,
            row_count=1,
        ),
        TabularSourceSnapshot(
            path="/tmp/third/POPULATION.csv",
            name="POPULATION.csv",
            size=10,
            mtime_ns=3,
            row_count=1,
        ),
    )

    grouping = build_tabular_file_grouping_dataframe(source_snapshots=snapshots)

    assert grouping.to_dict("list") == {
        "REPORT_ID": [1, 2, 3, 4],
        "GROUP": ["dataset", "dataset", "dataset 2", "POPULATION file"],
    }


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


def test_multi_csv_sqlite_uses_global_header_mapping_for_sanitized_collisions(tmp_path) -> None:
    first_file = tmp_path / "line_a.csv"
    second_file = tmp_path / "line_b.csv"
    pd.DataFrame({"A": ["first-a"], "A!": ["first-bang"]}).to_csv(first_file, index=False)
    pd.DataFrame({"A!": ["second-bang"]}).to_csv(second_file, index=False)

    result = load_tabular_analytics_files((first_file, second_file))
    try:
        materialized = materialize_tabular_dataframe(
            result,
            required_columns=("source_file", "a", "a_2"),
        ).dataframe

        assert result.storage_mode == "sqlite"
        assert result.column_mapping["A"] == "a"
        assert result.column_mapping["A!"] == "a_2"
        assert materialized["a"].iloc[0] == "first-a"
        assert pd.isna(materialized["a"].iloc[1])
        assert materialized["a_2"].tolist() == ["first-bang", "second-bang"]
    finally:
        cleanup_tabular_load_result(result)


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


def test_tabular_sqlite_store_streams_batches_and_aggregates_without_materialization(tmp_path) -> None:
    input_file = tmp_path / "aggregate.csv"
    pd.DataFrame(
        {
            "Line": ["A", "A", "B", "B"],
            "Length mm": [10.0, 12.0, 20.0, 24.0],
            "Width mm": [1.0, 3.0, 5.0, "bad"],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, reference_column="Line", force_sqlite=True)
    try:
        assert result.sqlite_store is not None
        store = result.sqlite_store

        query_result = store.read_query_result(columns=("source_row_number", "line"))
        batches = list(store.iter_row_batches(columns=("source_row_number", "line"), batch_size=2))
        aggregates = store.aggregate_numeric_columns(("length_mm", "width_mm"), group_columns=("line",))

        assert query_result.columns == ("source_row_number", "line")
        assert query_result.rows == ((1, "A"), (2, "A"), (3, "B"), (4, "B"))
        assert [batch.row_count for batch in batches] == [2, 2]
        assert batches[0].as_dicts() == [
            {"source_row_number": 1, "line": "A"},
            {"source_row_number": 2, "line": "A"},
        ]

        by_key = {(row["line"], row["metric"]): row for row in aggregates}
        assert by_key[("A", "length_mm")]["n"] == 2
        assert by_key[("A", "length_mm")]["mean"] == 11.0
        assert by_key[("B", "length_mm")]["max"] == 24.0
        assert by_key[("A", "width_mm")]["stddev"] == pytest.approx(2**0.5)
        assert by_key[("B", "width_mm")]["n"] == 1
        assert by_key[("B", "width_mm")]["stddev"] is None
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_csv_loading_reports_progress(tmp_path) -> None:
    input_file = tmp_path / "progress.csv"
    pd.DataFrame(
        {
            "Station": ["A", "B", "A"],
            "Length mm": [10.0, 10.1, 10.2],
        }
    ).to_csv(input_file, index=False)
    progress_events: list[dict[str, object]] = []

    result = load_tabular_analytics_file(
        input_file,
        force_sqlite=True,
        progress_callback=progress_events.append,
    )
    try:
        stages = [event["stage"] for event in progress_events]

        assert "sampling" in stages
        assert "chunk_loaded" in stages
        assert "indexing" in stages
        assert progress_events[-1]["stage"] == "complete"
        assert progress_events[-1]["rows_loaded"] == 3
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_csv_loading_can_cancel_between_chunks(tmp_path, monkeypatch) -> None:
    input_file = tmp_path / "cancel.csv"
    pd.DataFrame(
        {
            "Station": ["A", "B", "C", "D", "E"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)
    progress_events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "modules.tabular_analytics_service.TABULAR_SQLITE_CHUNK_ROWS",
        2,
    )

    def cancel_after_first_chunk() -> bool:
        return any(event.get("stage") == "chunk_loaded" for event in progress_events)

    with pytest.raises(TabularLoadCancelled):
        load_tabular_analytics_file(
            input_file,
            force_sqlite=True,
            progress_callback=progress_events.append,
            cancel_check=cancel_after_first_chunk,
        )

    assert [event["stage"] for event in progress_events].count("chunk_loaded") == 1


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


def test_sqlite_load_defers_source_column_indexes_until_preview_filter(tmp_path) -> None:
    input_file = tmp_path / "lazy_indexes.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=5, freq="D"),
            "Reference ID": ["R1", "R1", "R2", "R2", "R3"],
            "Line": ["L1", "L1", "L2", "L1", "L2"],
            "Station": ["A", "B", "A", "A", "B"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    assert result.sqlite_store is not None
    store = result.sqlite_store

    try:
        initial_indexes = _sqlite_index_names(store)
        load_timings = result.load_timings_s

        assert load_timings["total"] > 0.0
        assert load_timings["sampling"] >= 0.0
        assert load_timings["chunk_read"] >= 0.0
        assert load_timings["chunk_normalize"] >= 0.0
        assert load_timings["chunk_build_rows"] >= 0.0
        assert load_timings["metric_stats"] >= 0.0
        assert load_timings["sqlite_write"] >= 0.0
        assert load_timings["indexing"] >= 0.0
        assert load_timings["metric_candidates"] >= 0.0
        assert load_timings["preview"] >= 0.0
        assert {
            "idx_tabular_rows_source_row_number",
            "idx_tabular_rows_source_file",
            "idx_tabular_rows_process_datetime",
            "idx_tabular_rows_reference",
            "idx_tabular_rows_date_filter_time_stamp",
            "idx_tabular_rows_time_stamp",
            "idx_tabular_rows_reference_id",
        }.issubset(initial_indexes)
        assert "idx_tabular_rows_line" not in initial_indexes
        assert "idx_tabular_rows_station" not in initial_indexes
        assert "idx_tabular_rows_length_mm" not in initial_indexes
        assert "idx_tabular_rows_group_line" not in initial_indexes
        assert "idx_tabular_rows_group_station" not in initial_indexes

        rows, total = store.preview_group_rows(
            ("station",),
            column_filters=(TabularColumnFilter("line", selected_values=("L1",)),),
            limit=20,
        )
        lazy_indexes = _sqlite_index_names(store)

        assert total == 2
        assert rows == [
            {"key": ("A",), "label": "A", "row_count": 2},
            {"key": ("B",), "label": "B", "row_count": 1},
        ]
        assert "idx_tabular_rows_group_line" in lazy_indexes
        assert "idx_tabular_rows_group_station" in lazy_indexes
        assert "idx_tabular_rows_line" not in lazy_indexes
        assert "idx_tabular_rows_station" not in lazy_indexes
        assert "idx_tabular_rows_length_mm" not in lazy_indexes
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


def test_sqlite_value_preview_uses_window_total_without_extra_group_count(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "value_preview_total.csv"
    pd.DataFrame(
        {
            "Station": ["A", "A", "B", "C"],
            "Length mm": [10.0, 10.1, 10.2, 10.3],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    assert result.sqlite_store is not None
    store = result.sqlite_store
    store._ensure_grouping_column_indexes(("station",))
    executed_sql: list[str] = []

    class CountingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=()):
            executed_sql.append(str(sql))
            return self.connection.execute(sql, params)

    @contextmanager
    def counting_scope(path):
        connection = sqlite3.connect(path)
        try:
            yield CountingConnection(connection)
        finally:
            connection.close()

    monkeypatch.setattr(
        "modules.tabular_analytics_service.sqlite_connection_scope",
        counting_scope,
    )
    try:
        rows, total = store.preview_value_rows("station", limit=1)

        assert total == 3
        assert rows == [{"key": ("A",), "label": "A", "row_count": 2}]
        assert len(executed_sql) == 1
        assert "COUNT(*) OVER ()" in executed_sql[0]
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_grouping_filter_expression_applies_to_preview_count_and_row_ids(
    tmp_path,
) -> None:
    input_file = tmp_path / "sqlite_expression_filters.csv"
    pd.DataFrame(
        {
            "Line": ["L1", "L1", "L2", "L1", "L2", "L1"],
            "Station": ["A", "B", "A", "A", "B", "B"],
            "Part": ["body-pre", "cap", "body-side", "body-front", "cap", "body-back"],
            "TimeStamp": [
                "2026-04-30",
                "2026-05-02",
                "2026-05-03",
                "2026-05-04",
                "2026-05-05",
                "2026-05-06",
            ],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4, 10.5],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        aliases = {"Part": "part", "TimeStamp": "timestamp", "Length": "length_mm"}
        expression = "(Part=body* AND TimeStamp>=2026-05-01) OR (Part=cap AND Length<10.2)"

        rows, total = result.sqlite_store.preview_group_rows(
            ("station",),
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
            limit=20,
        )

        assert total == 2
        assert rows == [
            {"key": ("A",), "label": "A", "row_count": 2},
            {"key": ("B",), "label": "B", "row_count": 2},
        ]
        assert result.sqlite_store.count_rows(
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
        ) == 4
        assert result.sqlite_store.row_ids(
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
        ) == [2, 3, 4, 6]
        value_rows, value_total = result.sqlite_store.preview_value_rows(
            "station",
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
            limit=20,
        )
        assert value_total == 2
        assert value_rows == [
            {"key": ("A",), "label": "A", "row_count": 2},
            {"key": ("B",), "label": "B", "row_count": 2},
        ]
        parsed = parse_filter_expression(
            "(part=body* AND timestamp>=2026-05-01) OR (part=cap AND length_mm<10.2)",
            result.sqlite_store.columns,
        )
        assert result.sqlite_store.row_ids(grouping_filter=parsed) == [2, 3, 4, 6]
        assert result.sqlite_store.row_ids_for_group_keys(
            ("station",),
            {("A",)},
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
        ) == [3, 4]
        assert result.sqlite_store.count_rows_for_group_keys(
            ("station",),
            {("A",)},
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
        ) == 2
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_grouping_filter_expression_supports_membership_lists(tmp_path) -> None:
    input_file = tmp_path / "sqlite_membership_filters.csv"
    pd.DataFrame(
        {
            "Station": ["A", "B", "A", "B", "A", "B"],
            "Part": ["body-pre", "cap", "nut", "body-side", "gear shaft", None],
            "TimeStamp": [
                "2026-05-01",
                "2026-05-02",
                "2026-05-03",
                "2026-05-04",
                "2026-05-05",
                "",
            ],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4, 10.5],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        aliases = {"Part": "part", "Length": "length_mm", "Time": "timestamp"}
        expression = 'Part IN (body*, "gear shaft") AND Length IN (10, 10.3, 10.4)'
        parsed = parse_filter_expression(
            'part IN (body*, "gear shaft") AND length_mm IN (10, 10.3, 10.4)',
            result.sqlite_store.columns,
        )
        expected_ids = result.dataframe.loc[parsed.mask(result.dataframe), "source_row_number"].tolist()

        assert expected_ids == [1, 4, 5]
        assert result.sqlite_store.row_ids(
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
        ) == expected_ids
        assert result.sqlite_store.count_rows(
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
        ) == 3
        rows, total = result.sqlite_store.preview_group_rows(
            ("station",),
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
            limit=20,
        )
        assert total == 2
        assert rows == [
            {"key": ("A",), "label": "A", "row_count": 2},
            {"key": ("B",), "label": "B", "row_count": 1},
        ]
        assert result.sqlite_store.row_ids_for_group_keys(
            ("station",),
            {("A",)},
            grouping_filter_expression=expression,
            grouping_filter_aliases=aliases,
        ) == [1, 5]

        assert result.sqlite_store.row_ids(
            grouping_filter_expression="Part NOT IN (body*, cap)",
            grouping_filter_aliases=aliases,
        ) == [3, 5, 6]
        assert result.sqlite_store.row_ids(
            grouping_filter_expression="Time IN (2026-05-02, 2026-05-05)",
            grouping_filter_aliases=aliases,
        ) == [2, 5]
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_grouping_filter_expression_does_not_warn_for_mixed_date_values() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scalar_filter = compile_tabular_sqlite_grouping_filter(
            ("timestamp",),
            grouping_filter_expression="timestamp >= 13.05.2026",
        )
        membership_filter = compile_tabular_sqlite_grouping_filter(
            ("timestamp",),
            grouping_filter_expression="timestamp IN (13.05.2026, 15.05.2026)",
        )

    assert not any("Could not infer format" in str(warning.message) for warning in caught)
    assert scalar_filter.params == ("2026-05-13",)
    assert membership_filter.params == ("2026-05-13", "2026-05-15")


def test_sqlite_membership_filter_escapes_wildcard_like_metacharacters(tmp_path) -> None:
    input_file = tmp_path / "sqlite_membership_escape.csv"
    pd.DataFrame(
        {
            "Station": ["A_%", "Axx_%", "Axx12", "A%2", "Alpha"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        parsed = parse_filter_expression("station IN (A*_%, A%2)", result.sqlite_store.columns)
        expected_ids = result.dataframe.loc[parsed.mask(result.dataframe), "source_row_number"].tolist()

        assert expected_ids == [1, 2, 4]
        assert result.sqlite_store.row_ids(grouping_filter=parsed) == expected_ids
        rows, total = result.sqlite_store.preview_group_rows(
            ("station",),
            grouping_filter_expression="station IN (A*_%, A%2)",
            limit=20,
        )
        assert total == 3
        assert rows == [
            {"key": ("A%2",), "label": "A%2", "row_count": 1},
            {"key": ("A_%",), "label": "A_%", "row_count": 1},
            {"key": ("Axx_%",), "label": "Axx_%", "row_count": 1},
        ]
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_membership_filter_chunks_large_value_lists(tmp_path) -> None:
    input_file = tmp_path / "sqlite_membership_large_list.csv"
    pd.DataFrame(
        {
            "Code": ["P-000", "P-904", "P-999"],
            "Length mm": [10.0, 10.1, 10.2],
        }
    ).to_csv(input_file, index=False)
    expression = "Code IN (" + ", ".join(f"P-{index:03d}" for index in range(905)) + ")"

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        assert result.sqlite_store.row_ids(grouping_filter_expression=expression) == [1, 2]
        assert result.sqlite_store.count_rows(grouping_filter_expression=expression) == 2
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_shared_filter_specs_match_pandas_and_escape_like_wildcards(tmp_path) -> None:
    input_file = tmp_path / "sqlite_shared_specs.csv"
    pd.DataFrame(
        {
            "Station": ["A_%", "A_1", "A%2", "Alpha", "Beta"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        specs = (
            TextFilterSpec("station", "contains", "A_%"),
            NumberFilterSpec("length_mm", "gte", 10),
        )
        expected_ids = apply_filter_specs(
            result.dataframe,
            specs,
            match_mode="and",
        )["source_row_number"].astype(int).tolist()
        compiled = compile_tabular_sqlite_grouping_filter(result.sqlite_store.columns, specs)

        rows, total = result.sqlite_store.preview_group_rows(
            ("station",),
            grouping_filter=compiled,
            limit=20,
        )

        assert expected_ids == [1]
        assert result.sqlite_store.row_ids(grouping_filter=specs) == expected_ids
        assert result.sqlite_store.count_rows(grouping_filter=compiled) == len(expected_ids)
        assert total == 1
        assert rows == [{"key": ("A_%",), "label": "A_%", "row_count": 1}]
    finally:
        cleanup_tabular_load_result(result)


def test_sqlite_grouping_filter_rejects_unknown_columns_before_execution(tmp_path) -> None:
    input_file = tmp_path / "sqlite_unknown_filter_column.csv"
    pd.DataFrame({"Station": ["A", "B"], "Length mm": [10.0, 10.1]}).to_csv(
        input_file,
        index=False,
    )

    result = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        with pytest.raises(KeyError, match="not allowed"):
            result.sqlite_store.count_rows(
                grouping_filter=(TextFilterSpec("missing_column", "contains", "A"),),
            )
        with pytest.raises(KeyError, match="not allowed"):
            result.sqlite_store.row_ids(
                grouping_filter_expression="Bad Alias = A",
                grouping_filter_aliases={"Bad Alias": "missing_column"},
            )
        with pytest.raises(ValueError, match="bound parameters"):
            result.sqlite_store.count_rows(
                grouping_filter=TabularSqliteFilterExpression(
                    clause='"station" = ?',
                    columns=("station",),
                ),
            )
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


def test_tabular_not_equal_filters_exclude_invalid_values_in_pandas_and_sqlite(tmp_path) -> None:
    input_file = tmp_path / "not_equal_filter_parity.csv"
    pd.DataFrame(
        {
            "Event Date": ["2026-01-01", "bad-date", "", "2026-01-02"],
            "Value": ["1", "x", "", "2"],
            "TraceCode": ["TC-001", "TC-002", "TC-003", "TC-004"],
        }
    ).to_csv(input_file, index=False)
    pandas_loaded = load_tabular_analytics_file(input_file)
    sqlite_loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        for loaded in (pandas_loaded, sqlite_loaded):
            numeric_result = materialize_tabular_dataframe(
                loaded,
                column_filters=(TabularColumnFilter("value", numeric_operator="!=", numeric_value="1"),),
                required_columns=("source_row_number",),
            )
            date_result = materialize_tabular_dataframe(
                loaded,
                column_filters=(
                    TabularColumnFilter(
                        "event_date",
                        date_operator="!=",
                        date_value="2026-01-01",
                    ),
                ),
                required_columns=("source_row_number",),
            )

            assert numeric_result.dataframe["source_row_number"].tolist() == [4]
            assert date_result.dataframe["source_row_number"].tolist() == [4]
    finally:
        cleanup_tabular_load_result(pandas_loaded)
        cleanup_tabular_load_result(sqlite_loaded)


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


def test_sqlite_metric_detection_preserves_chunked_numeric_candidates(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "chunked_metrics.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=5, freq="h"),
            "Reference ID": ["R1", "R1", "R2", "R2", "R3"],
            "Line": ["L1", "L1", "L2", "L2", "L3"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
            "Width mm": ["5.0", "5.1", "5.2", "bad", "5.4"],
            "Comment": ["ok", "ok", "review", "ok", "hold"],
        }
    ).to_csv(input_file, index=False)
    monkeypatch.setattr("modules.tabular_analytics_service.TABULAR_SQLITE_CHUNK_ROWS", 2)

    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        by_name = {candidate.field_name: candidate for candidate in loaded.metric_candidates}

        assert {"length_mm", "width_mm"}.issubset(by_name)
        assert "line" not in by_name
        assert "time_stamp" not in by_name
        assert "reference_id" not in by_name
        assert by_name["width_mm"].numeric_count == 4
        assert by_name["width_mm"].warning_flags == ("contains_non_numeric_values",)
    finally:
        cleanup_tabular_load_result(loaded)


def test_sqlite_metric_detection_preserves_counts_warnings_and_samples(
    tmp_path,
    monkeypatch,
) -> None:
    input_file = tmp_path / "metric_contracts.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=8, freq="h"),
            "Reference ID": [f"R{index}" for index in range(8)],
            "Pure mm": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7],
            "Mixed mm": ["1", "2", "bad", "3", "4", "", None, " "],
            "Blank mm": ["1", " ", "", "2", None, "   ", "3", "4"],
            "Sample mm": [10, 11, 12, 13, 14, 15, 16, 17],
        }
    ).to_csv(input_file, index=False)
    monkeypatch.setattr("modules.tabular_analytics_service.TABULAR_SQLITE_CHUNK_ROWS", 3)

    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    try:
        by_name = {candidate.field_name: candidate for candidate in loaded.metric_candidates}

        assert {"pure_mm", "mixed_mm", "blank_mm", "sample_mm"}.issubset(by_name)
        assert by_name["pure_mm"].non_null_count == 8
        assert by_name["pure_mm"].numeric_count == 8
        assert by_name["mixed_mm"].non_null_count == 5
        assert by_name["mixed_mm"].numeric_count == 4
        assert by_name["mixed_mm"].numeric_ratio == 0.8
        assert by_name["mixed_mm"].warning_flags == ("contains_non_numeric_values",)
        assert by_name["blank_mm"].non_null_count == 4
        assert by_name["blank_mm"].numeric_count == 4
        assert by_name["blank_mm"].warning_flags == ()
        assert len(by_name["sample_mm"].sample_values) == 5
    finally:
        cleanup_tabular_load_result(loaded)


def test_sqlite_group_search_counts_and_row_ids_stay_in_sql(tmp_path) -> None:
    input_file = tmp_path / "group_search_sqlite.csv"
    pd.DataFrame(
        {
            "Line": ["L1", "L1", "L2", "L2", "L1"],
            "Station": ["A", "B", "A", "A", "A"],
            "Length mm": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    assert loaded.sqlite_store is not None
    store = loaded.sqlite_store

    try:
        assert store.count_rows_for_group_search(("line",), search_text="L1") == 3
        assert store.has_rows_for_group_search(("line",), search_text="L1")
        assert store.row_ids_for_group_search(("line",), search_text="L1") == [1, 2, 5]

        filtered_count = store.count_rows_for_group_search(
            ("line",),
            search_text="L1",
            column_filters=(TabularColumnFilter("station", selected_values=("A",)),),
        )
        filtered_row_ids = store.row_ids_for_group_search(
            ("line",),
            search_text="L1",
            column_filters=(TabularColumnFilter("station", selected_values=("A",)),),
        )

        assert filtered_count == 2
        assert filtered_row_ids == [1, 5]
        assert not store.has_rows_for_group_search(("line",), search_text="missing")
        assert store.count_rows_for_group_search(("line",), search_text="missing") == 0
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
