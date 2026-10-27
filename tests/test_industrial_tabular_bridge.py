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


def test_industrial_view_literals_do_not_reinterpret_question_marks(tmp_path):
    database = str(tmp_path / "literal-scope.sqlite")
    repository = IndustrialDataRepository(database)
    alias = "source?' OR 1=1 --"
    profile = repository.upsert_source_profile(
        profile_key="literal_scope",
        profile_name="Synthetic source",
        source_db_alias=alias,
        database_type="sqlite",
        source_object_name="measurements",
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=alias,
        rows=({"source_record_key": "selected", "reference": "REF-1"},),
    )
    loaded = load_industrial_cache_tabular_result(
        database, source_db_aliases=(alias, "other?source"),
    )
    try:
        assert loaded.row_count == 1
        assert loaded.sqlite_store.read_dataframe()["source_record_key"].tolist() == ["selected"]
    finally:
        loaded.sqlite_store.cleanup()


def test_scope_replacement_prunes_facets_and_rebuilds_saved_previews(tmp_path):
    from metroliza.industrial.industrial_cache_target import (
        IndustrialCacheTarget, disposable_cache_counts, persist_temporary_industrial_cache,
    )

    database = tmp_path / "scopes.sqlite"
    repository = IndustrialDataRepository(str(database))
    profiles = [repository.upsert_source_profile(
        profile_key=f"line_{i}", profile_name=f"Line {i}", source_db_alias=f"line_{i}",
        database_type="sqlite", source_object_name="events",
    ) for i in range(2)]
    for i, profile in enumerate(profiles):
        repository.upsert_industrial_records_from_rows(
            source_profile_id=profile.id, source_db_alias=profile.source_db_alias,
            rows=({"source_record_key": f"row-{j}", "length_mm": str(i * 10 + j)} for j in range(3)),
        )
    all_sources = load_industrial_cache_tabular_result(database)
    single = load_industrial_cache_tabular_result(database, source_profile_ids=(profiles[0].id,))
    try:
        with sqlite_connection_scope(str(database)) as connection:
            for table in ("industrial_tabular_value_facets", "industrial_tabular_metadata_cache"):
                assert connection.execute(f"SELECT DISTINCT scope_key FROM {table}").fetchall() == [
                    (single.sqlite_store.value_facet_scope_key,),
                ]
        counts = disposable_cache_counts(database)
        # Derived Summary tables are rebuilt from operator data, never counted as it.
        assert counts["industrial_records"] == 6
        assert "industrial_tabular_value_facets" not in counts
        assert single.sqlite_store.preview_value_rows("length_mm", search_text="missing")[1] == 0
        assert single.sqlite_store.preview_group_rows(("length_mm",), offset=99)[1] == 3
        # Missing derived facets must use the current view, not report no values.
        with sqlite_connection_scope(str(database)) as connection:
            connection.execute("DELETE FROM industrial_tabular_value_facets")
            connection.commit()
        assert single.sqlite_store.preview_value_rows("length_mm")[1] == 3
        assert single.sqlite_store.preview_group_rows(("length_mm",))[1] == 3
        assert single.sqlite_store.preview_value_rows("length_mm", search_text="missing")[1] == 0
        saved = persist_temporary_industrial_cache(
            IndustrialCacheTarget("temporary", str(database), is_temporary=True), tmp_path / "saved.sqlite",
        )
        reopened = load_industrial_cache_tabular_result(saved.cache_db_file)
        try:
            assert reopened.sqlite_store.preview_value_rows("length_mm")[1] == 6
            with sqlite_connection_scope(saved.cache_db_file) as connection:
                assert connection.execute(
                    "SELECT DISTINCT scope_key FROM industrial_tabular_value_facets"
                ).fetchall() == [(reopened.sqlite_store.value_facet_scope_key,)]
        finally:
            reopened.sqlite_store.cleanup()
    finally:
        single.sqlite_store.cleanup()
        all_sources.sqlite_store.cleanup()


def _small_cache(tmp_path):
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {"source_record_key": f"row-{index}", "reference": f"REF-{index % 2}", "length_mm": str(10 + index)}
            for index in range(6)
        ),
    )
    return db_file


def _derived_state(db_file):
    with sqlite_connection_scope(str(db_file)) as connection:
        views = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE 'industrial_tabular_rows_%'"
        ).fetchall()
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        derived = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("industrial_tabular_metadata_cache", "industrial_tabular_value_facets")
            if table in tables
        }
    return views, derived


def test_cancelled_load_leaves_no_view_or_derived_rows(tmp_path, monkeypatch) -> None:
    db_file = _small_cache(tmp_path)

    # Canceled before any work.
    try:
        load_industrial_cache_tabular_result(db_file, cancel_check=lambda: True)
    except industrial_tabular_bridge.IndustrialCacheLoadCanceled:
        pass
    else:
        raise AssertionError("the load should have been canceled")
    assert _derived_state(db_file)[0] == []

    # Canceled while SQLite runs the metadata statements: the open transaction is rolled back.
    state = {"cancel": False}
    original = industrial_tabular_bridge._dynamic_field_metadata

    def flag_then_run(*args, **kwargs):
        state["cancel"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(industrial_tabular_bridge, "_dynamic_field_metadata", flag_then_run)
    monkeypatch.setattr(industrial_tabular_bridge, "_CANCEL_CHECK_INTERVAL_STEPS", 1)
    try:
        load_industrial_cache_tabular_result(db_file, cancel_check=lambda: state["cancel"])
    except industrial_tabular_bridge.IndustrialCacheLoadCanceled:
        pass
    else:
        raise AssertionError("the load should have been canceled")
    views, derived = _derived_state(db_file)
    assert views == []
    assert all(count == 0 for count in derived.values())

    # Canceled after the view was built: the view is dropped again.
    monkeypatch.undo()
    state["cancel"] = False
    store_type = industrial_tabular_bridge.TabularSqliteStore
    read_dataframe = store_type.read_dataframe

    def flag_after_read(self, *args, **kwargs):
        frame = read_dataframe(self, *args, **kwargs)
        state["cancel"] = True
        return frame

    monkeypatch.setattr(store_type, "read_dataframe", flag_after_read)
    try:
        load_industrial_cache_tabular_result(db_file, cancel_check=lambda: state["cancel"])
    except industrial_tabular_bridge.IndustrialCacheLoadCanceled:
        pass
    else:
        raise AssertionError("the load should have been canceled")
    assert _derived_state(db_file)[0] == []

    # The same cache loads normally afterwards.
    monkeypatch.undo()
    loaded = load_industrial_cache_tabular_result(db_file, cancel_check=lambda: False)
    try:
        assert loaded.row_count == 6
    finally:
        loaded.sqlite_store.cleanup()
