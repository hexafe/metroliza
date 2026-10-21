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
