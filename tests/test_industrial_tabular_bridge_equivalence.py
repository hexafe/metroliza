"""Equivalence of the Industrial cache bridge metadata and facet computation.

The oracle below is the earlier implementation (one statement per dynamic field for the value
facets, a per-value Python callback for the numeric statistics). The bridge must produce the same
metadata, facets, counts and previews as the oracle for representative scopes and filters.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from typing import Any

import pytest

import metroliza.industrial.industrial_tabular_bridge as bridge
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.reports.db import sqlite_connection_scope
from metroliza.tabular.tabular_analytics_service import TabularColumnFilter


# --- oracle: earlier implementation, kept verbatim -------------------------------------------------


def _oracle_dynamic_field_metadata(connection, *, where_sql, params):
    connection.create_function("metroliza_is_numeric_text", 1, bridge._is_numeric_text)
    value_expr = "TRIM(COALESCE(NULLIF(values_row.field_value_text, ''), values_row.field_value_json, ''))"
    rows = connection.execute(
        f"""
        WITH field_values AS (
            SELECT
                values_row.field_name AS field_name,
                {value_expr} AS field_value
            FROM industrial_record_values values_row
            JOIN industrial_records records
                ON records.id = values_row.record_id
            {where_sql}
        )
        SELECT
            field_name,
            COUNT(NULLIF(field_value, '')) AS non_null_count,
            COALESCE(SUM(
                CASE
                    WHEN field_value <> '' AND metroliza_is_numeric_text(field_value)
                    THEN 1
                    ELSE 0
                END
            ), 0) AS numeric_count,
            MIN(NULLIF(field_value, '')) AS sample_value
        FROM field_values
        GROUP BY field_name
        ORDER BY field_name COLLATE NOCASE
        """,
        params,
    ).fetchall()
    dynamic_fields: list[str] = []
    dynamic_stats: dict[str, dict[str, Any]] = {}
    for field_name_raw, non_null_count, numeric_count, sample_value in rows:
        field_name = str(field_name_raw or "").strip()
        if not field_name:
            continue
        dynamic_fields.append(field_name)
        sample_values = [str(sample_value)] if sample_value not in (None, "") else []
        dynamic_stats[field_name] = {
            "non_null_count": int(non_null_count or 0),
            "numeric_count": int(numeric_count or 0),
            "sample_values": sample_values,
        }
    return tuple(dynamic_fields), dynamic_stats


def _oracle_insert_dynamic_value_facets(connection, *, scope_key, field_name, output_column):
    value_expr = "COALESCE(NULLIF(values_row.field_value_text, ''), values_row.field_value_json)"
    normalized_expr = bridge._normalized_value_sql(value_expr)
    connection.execute(
        f"""
        INSERT OR REPLACE INTO {bridge._quote_identifier(bridge._INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)} (
            scope_key,
            column_name,
            normalized_value,
            display_value,
            row_count,
            updated_at
        )
        SELECT
            ?,
            ?,
            {normalized_expr} AS normalized_value,
            {normalized_expr} AS display_value,
            COUNT(*) AS row_count,
            CURRENT_TIMESTAMP
        FROM temp_industrial_tabular_scope_records scope_records
        LEFT JOIN industrial_record_values values_row
            ON values_row.record_id = scope_records.record_id
            AND values_row.field_name = ?
        GROUP BY normalized_value, display_value
        """,
        (scope_key, output_column, field_name),
    )


def _oracle_refresh_value_facets(connection, *, scope_key, row_count, where_sql, params, dynamic_fields):
    connection.execute(
        f"DELETE FROM {bridge._quote_identifier(bridge._INDUSTRIAL_TABULAR_VALUE_FACETS_TABLE)} WHERE scope_key = ?",
        (scope_key,),
    )
    if row_count <= 0:
        return
    connection.execute("DROP TABLE IF EXISTS temp_industrial_tabular_scope_records")
    connection.execute("CREATE TEMP TABLE temp_industrial_tabular_scope_records (record_id INTEGER PRIMARY KEY)")
    connection.execute(
        f"""
        INSERT INTO temp_industrial_tabular_scope_records (record_id)
        SELECT records.id
        FROM industrial_records records
        {where_sql}
        """,
        params,
    )
    columns, dynamic_columns = bridge._industrial_tabular_columns(dynamic_fields)
    bridge._insert_base_value_facets(connection, scope_key=scope_key, columns=columns)
    for field_name, output_column in zip(dynamic_fields, dynamic_columns, strict=False):
        _oracle_insert_dynamic_value_facets(
            connection, scope_key=scope_key, field_name=field_name, output_column=output_column,
        )
    connection.execute("DROP TABLE IF EXISTS temp_industrial_tabular_scope_records")
    connection.execute("PRAGMA optimize")


def _use_oracle(monkeypatch) -> None:
    monkeypatch.setattr(bridge, "_dynamic_field_metadata", _oracle_dynamic_field_metadata)
    monkeypatch.setattr(bridge, "_refresh_value_facets", _oracle_refresh_value_facets)


# --- synthetic cache -------------------------------------------------------------------------------

_LENGTH_VALUES = (
    "12.5", "-3", "7", "12.50", " 5 ", "1e3", "٣", "1_000", "nan", "inf", "-inf", "Inf", "-Infinity",
    "1.2.3", ".5", "5.", "--5", "+5", "9" * 400, "0x10", "12abc", "", "-0.0", "1.0e+20", "9e999",
    "1,5", "\t8\n",
)


def _build_cache(path) -> dict[str, int]:
    repository = IndustrialDataRepository(str(path))
    profile_ids: dict[str, int] = {}
    for key, name in (("line_a", "Line A"), ("line_b", "Line B"), ("line_c", "")):
        profile = repository.upsert_source_profile(
            profile_key=key, profile_name=name or key, source_db_alias=f"alias_{key}",
            database_type="mssql", source_object_name="measurements",
        )
        profile_ids[key] = profile.id
        repository.upsert_industrial_records_from_rows(
            source_profile_id=profile.id,
            source_db_alias=profile.source_db_alias,
            rows=(
                {
                    "source_record_key": f"{key}-{index}",
                    "process_timestamp": f"2026-06-0{1 + index % 3}T10:0{index % 6}:00Z",
                    "reference": ("REF-1", "ref-1", " REF-2 ", "", None)[index % 5],
                    "part_number": f"PN-{index % 2}",
                    "station": ("S1", "S2")[index % 2] if index % 4 else None,
                    "operator_name": " ",
                }
                for index in range(9)
            ),
        )
    with sqlite_connection_scope(str(path)) as connection:
        record_ids = [row[0] for row in connection.execute("SELECT id FROM industrial_records ORDER BY id")]
        values: list[tuple[int, str, Any, Any]] = []
        for position, record_id in enumerate(record_ids):
            values.append((record_id, "length_mm", _LENGTH_VALUES[position % len(_LENGTH_VALUES)], None))
            values.append((record_id, "Fixture", ("F1", "f1", " F1 ", "F2", "", None)[position % 6], None))
            values.append((record_id, "fixture", ("A", "a", "B")[position % 3], None))
            if position % 3 == 0:
                values.append((record_id, "sparse", "1.25", None))
            if position % 4 == 1:
                values.append((record_id, "payload", None, json.dumps({"k": position % 2})))
            if position % 5 == 2:
                values.append((record_id, "json_number", "", "12"))
            if position % 7 == 0:
                values.append((record_id, " padded ", "3.5", None))
            if position == 3:
                values.append((record_id, "   ", "ignored", None))
            values.append((record_id, "Length mm", f"{position}.{position}25", None))
        connection.executemany(
            "INSERT INTO industrial_record_values (record_id, field_name, field_value_text, field_value_json, created_at)"
            " VALUES (?, ?, ?, ?, '2026-06-01T00:00:00Z')",
            values,
        )
        connection.commit()
    return profile_ids


def _snapshot(db_file, **load_kwargs) -> dict[str, Any]:
    loaded = bridge.load_industrial_cache_tabular_result(db_file, **load_kwargs)
    store = loaded.sqlite_store
    try:
        snapshot: dict[str, Any] = {
            "row_count": loaded.row_count,
            "columns": tuple(store.columns),
            "candidates": [asdict(candidate) for candidate in loaded.metric_candidates],
            "preview": loaded.dataframe.fillna("<NA>").to_dict("records"),
            "scope_key": store.value_facet_scope_key,
        }
        with sqlite_connection_scope(str(db_file)) as connection:
            # JSON retains SQLite scalar types as well as literal values and row order.
            quoted = ", ".join(bridge._quote_identifier(column) for column in store.columns)
            snapshot["ordered_rows"] = connection.execute(
                f"SELECT json_array({quoted}) FROM {bridge._quote_identifier(store.table_name)}"
                " ORDER BY source_row_number"
            ).fetchall()
            snapshot["catalog"] = connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master"
                " WHERE name NOT LIKE 'industrial_tabular_rows_%' ORDER BY type, name"
            ).fetchall()
            snapshot["view_sql"] = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (store.table_name,),
            ).fetchone()[0].replace(store.table_name, "industrial_tabular_rows_VIEW")
            snapshot["metadata_rows"] = connection.execute(
                "SELECT scope_key, row_count, max_record_id, max_updated_at, value_count, max_value_id,"
                " dynamic_fields_json, dynamic_stats_json FROM industrial_tabular_metadata_cache"
                " ORDER BY scope_key"
            ).fetchall()
            snapshot["facet_scopes"] = connection.execute(
                "SELECT DISTINCT scope_key FROM industrial_tabular_value_facets ORDER BY scope_key"
            ).fetchall()
            snapshot["facets"] = sorted(
                connection.execute(
                    "SELECT scope_key, column_name, normalized_value, display_value, row_count"
                    " FROM industrial_tabular_value_facets"
                ).fetchall()
            )
        snapshot["previews"] = {
            column: store.preview_value_rows(column, limit=500) for column in store.columns[1:]
        }
        snapshot["counts"] = {
            "all": store.count_rows(),
            "length_mm": store.count_rows(
                column_filters=(TabularColumnFilter(column="length_mm", numeric_operator=">", numeric_value=5),)
            ),
            "fixture_keys": store.count_rows(
                filter_columns=("fixture",), selected_filter_keys=(("F1",), ("A",)),
            ),
            "station_keys": store.count_rows(
                filter_columns=("station",), selected_filter_keys=(("S1",), ("(blank)",)),
            ),
        }
        snapshot["projected"] = store.read_dataframe(
            columns=("source_row_number", "source", "reference", store.columns[-1]),
        ).to_json(orient="split", double_precision=15)
        return snapshot
    finally:
        store.cleanup()


def _scopes(profile_ids: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {},
        {"source_profile_ids": (profile_ids["line_a"],)},
        {"source_profile_ids": (profile_ids["line_b"], profile_ids["line_c"])},
        {"source_db_aliases": ("alias_line_b",)},
        {"source_profile_ids": (profile_ids["line_a"],), "source_db_aliases": ("alias_line_a",)},
        {"source_db_aliases": ("alias_missing",)},
    ]


@pytest.fixture()
def synthetic_cache(tmp_path):
    path = tmp_path / "template.sqlite"
    profile_ids = _build_cache(path)
    return path, profile_ids


def _copy(template, tmp_path, name):
    target = tmp_path / name
    shutil.copy2(template, target)
    return target


def test_bridge_matches_earlier_implementation_for_every_scope(synthetic_cache, tmp_path, monkeypatch):
    template, profile_ids = synthetic_cache
    oracle_db = _copy(template, tmp_path, "oracle.sqlite")
    actual_db = _copy(template, tmp_path, "actual.sqlite")
    scopes = _scopes(profile_ids)

    with monkeypatch.context() as patch:
        _use_oracle(patch)
        expected = [_snapshot(oracle_db, **scope) for scope in scopes]
    actual = [_snapshot(actual_db, **scope) for scope in scopes]

    for scope, want, got in zip(scopes, expected, actual, strict=True):
        assert got == want, scope
    # A scope without rows still yields the fixed empty column set and no facets.
    assert actual[-1]["row_count"] == 0


def test_bridge_second_load_from_cached_metadata_matches_earlier_implementation(
    synthetic_cache, tmp_path, monkeypatch,
):
    template, profile_ids = synthetic_cache
    oracle_db = _copy(template, tmp_path, "oracle.sqlite")
    actual_db = _copy(template, tmp_path, "actual.sqlite")
    with monkeypatch.context() as patch:
        _use_oracle(patch)
        _snapshot(oracle_db)
        expected = _snapshot(oracle_db)
    _snapshot(actual_db)
    assert _snapshot(actual_db) == expected

    # Deleting only the facets (cached metadata stays valid) rebuilds the same facets.
    with sqlite_connection_scope(str(actual_db)) as connection:
        connection.execute("DELETE FROM industrial_tabular_value_facets")
        connection.commit()
    assert _snapshot(actual_db) == expected


def test_bridge_keeps_facets_of_the_current_scope_only(synthetic_cache, tmp_path):
    template, profile_ids = synthetic_cache
    db_file = _copy(template, tmp_path, "scopes.sqlite")
    first = _snapshot(db_file)
    second = _snapshot(db_file, source_profile_ids=(profile_ids["line_a"],))
    assert len(first["facet_scopes"]) == 1
    assert second["facet_scopes"] == [(second["scope_key"],)]
    assert first["scope_key"] != second["scope_key"]
    assert [row[0] for row in second["metadata_rows"]] == [second["scope_key"]]
    assert {row[0] for row in second["facets"]} == {second["scope_key"]}


def test_numeric_statistics_match_python_float_semantics(synthetic_cache, tmp_path):
    template, _profile_ids = synthetic_cache
    db_file = _copy(template, tmp_path, "numeric.sqlite")
    with sqlite_connection_scope(str(db_file)) as connection:
        stored = connection.execute(
            "SELECT field_value_text, field_value_json FROM industrial_record_values WHERE field_name = 'length_mm'"
        ).fetchall()
        expected_non_null = 0
        expected_numeric = 0
        for text, json_value in stored:
            value = (text if text not in (None, "") else json_value) or ""
            value = str(value).strip()
            if value:
                expected_non_null += 1
                expected_numeric += bridge._is_numeric_text(value)
        fields, stats = bridge._dynamic_field_metadata(connection, where_sql="", params=())
    assert "length_mm" in fields
    assert stats["length_mm"]["non_null_count"] == expected_non_null
    assert stats["length_mm"]["numeric_count"] == expected_numeric
    assert 0 < expected_numeric < expected_non_null


def test_sparse_dense_blank_json_collision_and_orphan_rows_match_oracle(
    synthetic_cache, tmp_path, monkeypatch,
):
    template, profile_ids = synthetic_cache
    edge = _copy(template, tmp_path, "edge.sqlite")
    with sqlite_connection_scope(str(edge)) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        ids = [row[0] for row in connection.execute("SELECT id FROM industrial_records ORDER BY id")]
        values = (None, "", " ", "\t\n", "(blank)", "01", "+1.2", "1.2x", "NaN", "1e999")
        connection.executemany(
            "INSERT INTO industrial_record_values"
            " (record_id, field_name, field_value_text, field_value_json, created_at)"
            " VALUES (?, ?, ?, ?, '2026-06-01')",
            [
                (record_id, field, values[index % len(values)], '{"z": 2, "a": 1}')
                for index, record_id in enumerate(ids)
                for field in ("source", "A B", "A-B", "only_blank")
            ] + [(999999, "orphan_only", "9", None), (ids[0], "absent_elsewhere", "7", None)],
        )
        connection.execute("UPDATE industrial_record_values SET field_value_text = NULL,"
                           " field_value_json = NULL WHERE field_name = 'only_blank'")
        connection.execute("UPDATE industrial_records SET source_profile_id = 999999 WHERE id = ?", (ids[-1],))
        connection.commit()
    oracle_db = _copy(edge, tmp_path, "oracle-edge.sqlite")
    actual_db = _copy(edge, tmp_path, "actual-edge.sqlite")
    for scope in ({}, {"source_profile_ids": (profile_ids["line_a"],)},
                  {"source_profile_ids": (999999,)}, {"source_profile_ids": (-1,)}):
        with monkeypatch.context() as patch:
            _use_oracle(patch)
            expected = _snapshot(oracle_db, **scope)
        assert _snapshot(actual_db, **scope) == expected


def test_duplicate_values_retain_schema_rejection(synthetic_cache):
    import sqlite3

    template, _profiles = synthetic_cache
    with sqlite_connection_scope(str(template)) as connection:
        row = connection.execute(
            "SELECT record_id, field_name FROM industrial_record_values LIMIT 1"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO industrial_record_values (record_id, field_name, created_at) VALUES (?, ?, 'now')",
                row,
            )


@pytest.mark.parametrize("new_name", ["Renamed | [profile]", "", " ", "Line B", "N\0tail"])
def test_profile_name_invalidation_matches_cold_reference(
    synthetic_cache, tmp_path, new_name,
):
    template, profiles = synthetic_cache
    warm_db = _copy(template, tmp_path, "warm.sqlite")
    _snapshot(warm_db)
    with sqlite_connection_scope(str(warm_db)) as connection:
        # Deliberately leave record/profile timestamps and all old aggregate maxima unchanged.
        connection.execute("UPDATE industrial_source_profiles SET profile_name = ? WHERE id = ?",
                           (new_name, profiles["line_a"]))
        connection.commit()
    cold_db = _copy(warm_db, tmp_path, "cold.sqlite")
    with sqlite_connection_scope(str(cold_db)) as connection:
        connection.execute("DELETE FROM industrial_tabular_metadata_cache")
        connection.execute("DELETE FROM industrial_tabular_value_facets")
        connection.commit()
    expected = _snapshot(cold_db)
    assert _snapshot(warm_db) == expected
    assert _snapshot(warm_db) == expected


def test_out_of_scope_profile_name_keeps_warm_metadata(synthetic_cache, tmp_path, monkeypatch):
    template, profiles = synthetic_cache
    db_file = _copy(template, tmp_path, "scoped-warm.sqlite")
    scope = {"source_profile_ids": (profiles["line_a"],)}
    expected = _snapshot(db_file, **scope)
    with sqlite_connection_scope(str(db_file)) as connection:
        connection.execute("UPDATE industrial_source_profiles SET profile_name = 'Outside scope' WHERE id = ?",
                           (profiles["line_b"],))
        connection.commit()

    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("an unrelated profile must not invalidate this scope")

    monkeypatch.setattr(bridge, "_dynamic_field_metadata", fail_refresh)
    monkeypatch.setattr(bridge, "_refresh_value_facets", fail_refresh)
    assert _snapshot(db_file, **scope) == expected


def test_general_sqlite_fallback_keeps_literal_snapshot(synthetic_cache, tmp_path, monkeypatch):
    template, _profiles = synthetic_cache
    actual = _copy(template, tmp_path, "native.sqlite")
    fallback = _copy(template, tmp_path, "fallback.sqlite")
    with monkeypatch.context() as patch:
        _use_oracle(patch)
        expected = _snapshot(actual)
    monkeypatch.setattr(bridge.sqlite3, "sqlite_version_info", (3, 34, 0))
    assert _snapshot(fallback) == expected


@pytest.fixture()
def materialized_sqlite_engine():
    # Read the actual parser, independently of the advertised dispatch-version seam.
    with sqlite_connection_scope(":memory:") as connection:
        version = connection.execute("SELECT sqlite_version()").fetchone()[0]
    if tuple(int(part) for part in version.split(".")) < (3, 35, 0):
        pytest.skip("native MATERIALIZED execution requires SQLite 3.35+")


def test_distinct_numeric_classification_activates_once_per_value(
    synthetic_cache, monkeypatch, materialized_sqlite_engine,
):
    template, _profiles = synthetic_cache
    with sqlite_connection_scope(str(template)) as connection:
        connection.execute(
            "INSERT INTO industrial_record_values"
            " (record_id, field_name, field_value_text, created_at)"
            " SELECT id, 'repeat', '1_000', '2026-06-01' FROM industrial_records"
        )
        connection.commit()
        expected = _oracle_dynamic_field_metadata(connection, where_sql="", params=())
        numeric = bridge._is_numeric_text
        calls = []

        def counted(value):
            calls.append(value)
            return numeric(value)

        monkeypatch.setattr(bridge, "_is_numeric_text", counted)
        assert bridge._dynamic_field_metadata(connection, where_sql="", params=()) == expected
        assert calls.count("1_000") == 1
        assert len(calls) == len(set(calls))


def test_present_facet_query_activates_with_literal_ordered_results(
    synthetic_cache, materialized_sqlite_engine,
):
    template, _profiles = synthetic_cache
    with sqlite_connection_scope(str(template)) as connection:
        queries = []
        connection.set_trace_callback(queries.append)
        metadata = bridge._load_or_refresh_tabular_metadata(connection, where_sql="", params=())
        actual = connection.execute(
            "SELECT column_name, normalized_value, display_value, row_count"
            " FROM industrial_tabular_value_facets ORDER BY column_name, normalized_value, display_value"
        ).fetchall()
        assert any("WITH present AS MATERIALIZED" in query for query in queries)
        _oracle_refresh_value_facets(
            connection, scope_key=metadata.scope_key, row_count=metadata.row_count,
            where_sql="", params=(), dynamic_fields=metadata.dynamic_fields,
        )
        assert connection.execute(
            "SELECT column_name, normalized_value, display_value, row_count"
            " FROM industrial_tabular_value_facets ORDER BY column_name, normalized_value, display_value"
        ).fetchall() == actual


def test_fingerprint_keeps_literal_timestamp_for_all_profile_inputs(tmp_path):
    with sqlite_connection_scope(str(tmp_path / "fingerprint.sqlite")) as connection:
        connection.execute("CREATE TABLE industrial_records (id INTEGER, source_profile_id INTEGER, updated_at TEXT)")
        connection.execute("CREATE TABLE industrial_record_values (id INTEGER, record_id INTEGER)")
        connection.execute("CREATE TABLE industrial_source_profiles (id INTEGER, profile_name)")
        connection.execute("INSERT INTO industrial_records VALUES (1, 1, 'fixed')")
        for name in (None, "", "N\0a", "N\0b", b"N\x00b", 123, "123"):
            connection.execute("DELETE FROM industrial_source_profiles")
            connection.execute("INSERT INTO industrial_source_profiles VALUES (1, ?)", (name,))
            fingerprint = bridge._metadata_scope_fingerprint(connection, where_sql="", params=())
            assert fingerprint[:2] == (1, 1)
            assert fingerprint[3:] == (0, 0)
            assert fingerprint[2] == "fixed"
        connection.execute("DELETE FROM industrial_source_profiles")
        assert bridge._metadata_scope_fingerprint(connection, where_sql="", params=())[2] == "fixed"


def test_metadata_cache_persists_literal_record_timestamp(synthetic_cache):
    warm, _profiles = synthetic_cache
    _snapshot(warm)
    with sqlite_connection_scope(str(warm)) as connection:
        assert connection.execute("SELECT max_updated_at FROM industrial_tabular_metadata_cache").fetchone()[0] == (
            connection.execute("SELECT MAX(updated_at) FROM industrial_records").fetchone()[0]
        )


def test_metadata_query_error_rolls_back_without_published_view(synthetic_cache, monkeypatch):
    import sqlite3

    template, _profiles = synthetic_cache

    def fail_query(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected metadata error")

    monkeypatch.setattr(bridge, "_distinct_dynamic_metadata_rows", fail_query)
    monkeypatch.setattr(bridge, "_general_dynamic_metadata_rows", fail_query)
    with pytest.raises(sqlite3.OperationalError, match="injected metadata error"):
        bridge.load_industrial_cache_tabular_result(template)
    with sqlite_connection_scope(str(template)) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE 'industrial_tabular_rows_%'"
        ).fetchall() == []
        assert connection.execute("SELECT * FROM industrial_tabular_metadata_cache").fetchall() == []
        assert connection.execute("SELECT * FROM industrial_tabular_value_facets").fetchall() == []


def _raw_orphan_snapshot(db_file):
    loaded = bridge.load_industrial_cache_tabular_result(db_file)
    store = loaded.sqlite_store
    try:
        with sqlite_connection_scope(str(db_file)) as connection:
            rows = connection.execute(
                f"SELECT * FROM {bridge._quote_identifier(store.table_name)} ORDER BY source_row_number"
            ).fetchall()
            facets = connection.execute(
                "SELECT column_name, normalized_value, display_value, row_count"
                " FROM industrial_tabular_value_facets ORDER BY column_name, normalized_value, display_value"
            ).fetchall()
            token = connection.execute("SELECT max_updated_at FROM industrial_tabular_metadata_cache").fetchone()[0]
        return {
            "rows": [tuple((type(value).__name__, value) for value in row) for row in rows],
            "facets": facets, "token": token, "row_count": loaded.row_count,
            "preview": loaded.dataframe.to_dict("records"),
            "counts": store.count_rows(),
            "value_previews": {
                column: store.preview_value_rows(column, limit=500)
                for column in ("source", "source_profile_id")
            },
        }
    finally:
        store.cleanup()


def test_blob_orphan_profile_id_public_read_and_warm_invalidation(synthetic_cache, tmp_path):
    template, _profiles = synthetic_cache
    warm = _copy(template, tmp_path, "blob-warm.sqlite")
    _raw_orphan_snapshot(warm)
    for index, value in enumerate((
        b"orphan", "orphan", '["sqlite_blob","6f727068616e"]', b"different", b"", 999, "999text",
    )):
        with sqlite_connection_scope(str(warm)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("UPDATE industrial_records SET source_profile_id = ? WHERE id = 1", (value,))
            connection.commit()
        cold = _copy(warm, tmp_path, f"blob-cold-{index}.sqlite")
        with sqlite_connection_scope(str(cold)) as connection:
            connection.execute("DELETE FROM industrial_tabular_metadata_cache")
            connection.execute("DELETE FROM industrial_tabular_value_facets")
            connection.commit()
        expected = _raw_orphan_snapshot(cold)
        actual = _raw_orphan_snapshot(warm)
        assert actual == expected
        with sqlite_connection_scope(str(warm)) as connection:
            assert actual["token"] == connection.execute("SELECT MAX(updated_at) FROM industrial_records").fetchone()[0]
        assert actual["row_count"] == 27
        # The source ID keeps its storage type; source labels still use the alias fallback.
        assert actual["rows"][0][1:4] == (
            ("str", "alias_line_a"), ("str", "alias_line_a"), (type(value).__name__, value),
        )


def test_profile_types_null_missing_and_nul_match_reopened_cold_cache(synthetic_cache, tmp_path):
    warm, profiles = synthetic_cache
    with sqlite_connection_scope(str(warm)) as connection:
        # Preserve the complete profile schema, but permit the original fingerprint's
        # NULL/numeric/TEXT/BLOB vectors without SQLite TEXT affinity coercing them.
        connection.execute("PRAGMA foreign_keys = OFF")
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'industrial_source_profiles'"
        ).fetchone()[0]
        connection.execute(schema.replace("industrial_source_profiles", "replacement_profiles", 1)
                           .replace("profile_name TEXT NOT NULL", "profile_name"))
        connection.execute("INSERT INTO replacement_profiles SELECT * FROM industrial_source_profiles")
        connection.execute("DROP TABLE industrial_source_profiles")
        connection.execute("ALTER TABLE replacement_profiles RENAME TO industrial_source_profiles")
        connection.commit()
    _raw_orphan_snapshot(warm)
    for index, value in enumerate((None, "", "N\0a", "N\0b", b"N\x00b", 123, "123")):
        with sqlite_connection_scope(str(warm)) as connection:
            connection.execute("UPDATE industrial_source_profiles SET profile_name = ? WHERE id = ?",
                               (value, profiles["line_a"]))
            assert connection.execute("SELECT typeof(profile_name) FROM industrial_source_profiles WHERE id = ?",
                                      (profiles["line_a"],)).fetchone()[0] == (
                "null" if value is None else "blob" if type(value) is bytes else "integer" if type(value) is int else "text"
            )
            connection.commit()
        _assert_warm_matches_cold(warm, tmp_path, f"profile-cold-{index}.sqlite")
    with sqlite_connection_scope(str(warm)) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DELETE FROM industrial_source_profiles WHERE id = ?", (profiles["line_a"],))
        connection.commit()
    _assert_warm_matches_cold(warm, tmp_path, "profile-missing.sqlite")


def _assert_warm_matches_cold(warm, tmp_path, name):
    cold = _copy(warm, tmp_path, name)
    with sqlite_connection_scope(str(cold)) as connection:
        connection.execute("DELETE FROM industrial_tabular_metadata_cache")
        connection.execute("DELETE FROM industrial_tabular_value_facets")
        connection.commit()
    expected = _raw_orphan_snapshot(cold)
    assert _raw_orphan_snapshot(warm) == expected
    assert _raw_orphan_snapshot(warm) == expected


@pytest.mark.parametrize("column", ["source", "source_profile_id"])
@pytest.mark.parametrize("corruption", ["missing", "extra", "count", "blob", "nul"])
def test_profile_facet_relation_rejects_missing_extra_counts_and_exact_bytes(
    synthetic_cache, tmp_path, column, corruption,
):
    warm, _profiles = synthetic_cache
    _raw_orphan_snapshot(warm)
    with sqlite_connection_scope(str(warm)) as connection:
        row_id = connection.execute(
            "SELECT rowid FROM industrial_tabular_value_facets WHERE column_name = ? LIMIT 1", (column,),
        ).fetchone()[0]
        if corruption == "missing":
            connection.execute("DELETE FROM industrial_tabular_value_facets WHERE rowid = ?", (row_id,))
        elif corruption == "extra":
            connection.execute(
                "INSERT INTO industrial_tabular_value_facets"
                " SELECT scope_key, column_name, 'extra', 'extra', 1, updated_at"
                " FROM industrial_tabular_value_facets WHERE rowid = ?", (row_id,),
            )
        elif corruption == "count":
            connection.execute("UPDATE industrial_tabular_value_facets SET row_count = row_count + 1 WHERE rowid = ?",
                               (row_id,))
        elif corruption == "blob":
            connection.execute("UPDATE industrial_tabular_value_facets SET display_value = CAST(display_value AS BLOB)"
                               " WHERE rowid = ?", (row_id,))
        else:
            connection.execute("UPDATE industrial_tabular_value_facets SET display_value = display_value || ?"
                               " WHERE rowid = ?", ("\0different", row_id))
        connection.commit()
    _assert_warm_matches_cold(warm, tmp_path, "relation-cold.sqlite")


def test_unchanged_profile_facets_do_not_rewrite_persisted_cache(synthetic_cache, monkeypatch):
    warm, _profiles = synthetic_cache
    expected = _snapshot(warm)
    with sqlite_connection_scope(str(warm)) as connection:
        for table in ("industrial_tabular_metadata_cache", "industrial_tabular_value_facets"):
            connection.execute(f"UPDATE {table} SET updated_at = 'unchanged-sentinel'")
        connection.commit()

    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("matching relations must reuse the cache")

    monkeypatch.setattr(bridge, "_refresh_value_facets", fail_refresh)
    monkeypatch.setattr(bridge, "_dynamic_field_metadata", fail_refresh)
    assert _snapshot(warm) == expected
    with sqlite_connection_scope(str(warm)) as connection:
        for table in ("industrial_tabular_metadata_cache", "industrial_tabular_value_facets"):
            assert connection.execute(f"SELECT DISTINCT updated_at FROM {table}").fetchall() == [("unchanged-sentinel",)]


def test_reopened_v2_metadata_row_migrates_to_literal_timestamp(synthetic_cache, tmp_path):
    warm, profiles = synthetic_cache
    _snapshot(warm)
    with sqlite_connection_scope(str(warm)) as connection:
        connection.execute("UPDATE industrial_tabular_metadata_cache SET max_updated_at = ?", ("v2:" + "a" * 64,))
        connection.execute("UPDATE industrial_source_profiles SET profile_name = 'migration' WHERE id = ?",
                           (profiles["line_a"],))
        connection.commit()
    _assert_warm_matches_cold(warm, tmp_path, "migration-cold.sqlite")
    with sqlite_connection_scope(str(warm)) as connection:
        assert connection.execute("SELECT max_updated_at FROM industrial_tabular_metadata_cache").fetchone()[0] == (
            connection.execute("SELECT MAX(updated_at) FROM industrial_records").fetchone()[0]
        )


def test_warm_facet_validation_query_error_propagates_without_cache_writes(synthetic_cache, monkeypatch):
    import sqlite3

    warm, _profiles = synthetic_cache
    expected = _snapshot(warm)
    validate = bridge._profile_value_facets_match

    def deny_hex(operation, _first, second, _database, _trigger):
        return sqlite3.SQLITE_DENY if operation == sqlite3.SQLITE_FUNCTION and second == "hex" else sqlite3.SQLITE_OK

    def fail_query(connection, **kwargs):
        connection.set_authorizer(deny_hex)
        try:
            return validate(connection, **kwargs)
        finally:
            connection.set_authorizer(None)

    with monkeypatch.context() as patch:
        patch.setattr(bridge, "_profile_value_facets_match", fail_query)
        with pytest.raises(sqlite3.OperationalError, match="not authorized"):
            bridge.load_industrial_cache_tabular_result(warm)
    assert _snapshot(warm) == expected
