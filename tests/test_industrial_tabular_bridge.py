from __future__ import annotations

import pandas as pd

import metroliza.industrial.industrial_tabular_bridge as industrial_tabular_bridge
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_tabular_bridge import load_industrial_cache_tabular_result
from metroliza.reports.db import sqlite_connection_scope


def test_industrial_cache_bridge_exposes_source_and_dynamic_columns(tmp_path) -> None:
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "length_mm", "fixture"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {
                "source_record_key": "row-1",
                "process_timestamp": "2026-06-01T10:00:00Z",
                "reference": "REF-1",
                "length_mm": "12.5",
                "fixture": "F1",
            },
            {
                "source_record_key": "row-2",
                "process_timestamp": "2026-06-01T10:01:00Z",
                "reference": "REF-2",
                "length_mm": "12.7",
                "fixture": "F2",
            },
        ),
    )

    loaded = load_industrial_cache_tabular_result(db_file)
    try:
        assert loaded.storage_mode == "sqlite"
        assert loaded.row_count == 2
        assert loaded.csv_config["cache_summary"]["source_profiles"] == 1
        assert loaded.csv_config["cache_summary"]["records"] == 2
        assert "source" in loaded.dataframe.columns
        assert "length_mm" in loaded.dataframe.columns
        assert loaded.dataframe.loc[0, "source"] == "Line A"
        assert loaded.dataframe.loc[0, "fixture"] == "F1"
        assert any(candidate.field_name == "length_mm" for candidate in loaded.metric_candidates)
        sqlite_frame = loaded.sqlite_store.read_dataframe(columns=("source", "length_mm", "fixture"))
        assert sqlite_frame.to_dict("records")[0] == {
            "source": "Line A",
            "length_mm": "12.5",
            "fixture": "F1",
        }
    finally:
        loaded.sqlite_store.cleanup()


def test_industrial_cache_bridge_uses_existing_sqlite_view_without_dataframe_wide_merge(
    tmp_path,
    monkeypatch,
) -> None:
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "length_mm", "fixture"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=tuple(
            {
                "source_record_key": f"row-{index}",
                "process_timestamp": "2026-06-01T10:00:00Z",
                "reference": f"REF-{index}",
                "length_mm": str(12.0 + index / 10),
                "fixture": f"F{index % 2}",
            }
            for index in range(1, 8)
        ),
    )

    def fail_dataframe_merge(*_args, **_kwargs):
        raise AssertionError("industrial CSV Summary bridge should not merge a full pandas frame")

    monkeypatch.setattr(pd.DataFrame, "merge", fail_dataframe_merge)

    loaded = load_industrial_cache_tabular_result(db_file)
    try:
        assert loaded.storage_mode == "sqlite"
        assert loaded.row_count == 7
        assert len(loaded.dataframe.index) == 7
        assert loaded.sqlite_store.path == str(db_file)
        assert loaded.sqlite_store.owns_file is False
        assert loaded.sqlite_store.indexable is False
        assert loaded.sqlite_store.row_count == 7
        with sqlite_connection_scope(str(db_file)) as conn:
            view_row = conn.execute(
                "SELECT type FROM sqlite_master WHERE name = ?",
                (loaded.sqlite_store.table_name,),
            ).fetchone()
        assert view_row is not None
        assert view_row[0] == "view"
        sqlite_frame = loaded.sqlite_store.read_dataframe(columns=("reference", "length_mm", "fixture"))
        assert sqlite_frame.loc[0, "reference"] == "REF-1"
        assert sqlite_frame.loc[6, "fixture"] == "F1"
    finally:
        view_name = loaded.sqlite_store.table_name
        loaded.sqlite_store.cleanup()
    with sqlite_connection_scope(str(db_file)) as conn:
        assert (
            conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (view_name,)).fetchone()
            is None
        )


def test_industrial_cache_bridge_reuses_cached_dynamic_metadata(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "length_mm"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {"source_record_key": "row-1", "reference": "REF-1", "length_mm": "12.5"},
            {"source_record_key": "row-2", "reference": "REF-2", "length_mm": "12.6"},
        ),
    )

    loaded = load_industrial_cache_tabular_result(db_file)
    loaded.sqlite_store.cleanup()

    def fail_dynamic_metadata(*_args, **_kwargs):
        raise AssertionError("dynamic metadata should come from the cache on repeated opens")

    monkeypatch.setattr(industrial_tabular_bridge, "_dynamic_field_metadata", fail_dynamic_metadata)

    loaded = load_industrial_cache_tabular_result(db_file)
    try:
        assert loaded.row_count == 2
        assert "length_mm" in loaded.sqlite_store.columns
    finally:
        loaded.sqlite_store.cleanup()


def test_industrial_cache_bridge_serves_value_and_single_group_previews_from_facets(
    tmp_path,
    monkeypatch,
) -> None:
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "fixture", "length_mm"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {
                "source_record_key": "row-1",
                "reference": "REF-1",
                "fixture": "F1",
                "length_mm": "12.5",
            },
            {
                "source_record_key": "row-2",
                "reference": "REF-2",
                "fixture": "F1",
                "length_mm": "12.6",
            },
            {
                "source_record_key": "row-3",
                "reference": "REF-3",
                "fixture": "F2",
                "length_mm": "12.7",
            },
        ),
    )

    loaded = load_industrial_cache_tabular_result(db_file)

    def fail_live_grouping_indexes(*_args, **_kwargs):
        raise AssertionError("industrial previews should use cached value facets")

    monkeypatch.setattr(
        type(loaded.sqlite_store),
        "_ensure_grouping_column_indexes",
        fail_live_grouping_indexes,
    )

    try:
        rows, total = loaded.sqlite_store.preview_value_rows("fixture", limit=10)
        assert total == 2
        assert rows == [
            {"key": ("F1",), "label": "F1", "row_count": 2},
            {"key": ("F2",), "label": "F2", "row_count": 1},
        ]

        searched_rows, searched_total = loaded.sqlite_store.preview_value_rows(
            "fixture",
            search_text="F2",
            limit=10,
        )
        assert searched_total == 1
        assert searched_rows == [{"key": ("F2",), "label": "F2", "row_count": 1}]

        group_rows, group_total = loaded.sqlite_store.preview_group_rows(("fixture",), limit=10)
        assert group_total == 2
        assert group_rows == rows
    finally:
        loaded.sqlite_store.cleanup()


def test_industrial_cache_bridge_refreshes_facets_after_immediate_dynamic_update(tmp_path) -> None:
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "fixture"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {
                "source_record_key": "row-1",
                "reference": "REF-1",
                "fixture": "F1",
            },
        ),
    )
    loaded = load_industrial_cache_tabular_result(db_file)
    try:
        rows, _total = loaded.sqlite_store.preview_value_rows("fixture", limit=10)
        assert rows == [{"key": ("F1",), "label": "F1", "row_count": 1}]
    finally:
        loaded.sqlite_store.cleanup()

    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {
                "source_record_key": "row-1",
                "reference": "REF-1",
                "fixture": "F9",
            },
        ),
    )

    loaded = load_industrial_cache_tabular_result(db_file)
    try:
        rows, total = loaded.sqlite_store.preview_value_rows("fixture", limit=10)
        assert total == 1
        assert rows == [{"key": ("F9",), "label": "F9", "row_count": 1}]
    finally:
        loaded.sqlite_store.cleanup()


def test_industrial_cache_bridge_prunes_abandoned_tabular_views(tmp_path) -> None:
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "fixture"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=({"source_record_key": "row-1", "reference": "REF-1", "fixture": "F1"},),
    )
    with sqlite_connection_scope(str(db_file)) as conn:
        conn.execute(
            "CREATE VIEW industrial_tabular_rows_abandoned AS "
            "SELECT 1 AS source_row_number"
        )

    loaded = load_industrial_cache_tabular_result(db_file)
    try:
        with sqlite_connection_scope(str(db_file)) as conn:
            old_view = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = ?",
                ("industrial_tabular_rows_abandoned",),
            ).fetchone()
            current_view = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = ?",
                (loaded.sqlite_store.table_name,),
            ).fetchone()
        assert old_view is None
        assert current_view is not None
    finally:
        loaded.sqlite_store.cleanup()


def test_industrial_cache_bridge_discovers_metric_after_preview_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(industrial_tabular_bridge, "TABULAR_SQLITE_PREVIEW_ROWS", 2)
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "late_metric"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {"source_record_key": "row-1", "reference": "REF-1"},
            {"source_record_key": "row-2", "reference": "REF-2"},
            {"source_record_key": "row-3", "reference": "REF-3", "late_metric": "10.5"},
            {"source_record_key": "row-4", "reference": "REF-4", "late_metric": "11.5"},
        ),
    )

    loaded = load_industrial_cache_tabular_result(db_file)
    try:
        assert len(loaded.dataframe.index) == 2
        assert "late_metric" in loaded.dataframe.columns
        assert loaded.dataframe["late_metric"].isna().all()
        candidate_names = {candidate.field_name for candidate in loaded.metric_candidates}
        assert "late_metric" in candidate_names
    finally:
        loaded.sqlite_store.cleanup()
