"""Ordered-choice equivalence and database cache regressions for #1127."""

from contextlib import closing
import sqlite3

import pytest

from metroliza.reports import filter_values
from metroliza.reports.filter_values import FILTER_VALUE_SPECS, load_filter_values
from metroliza.reports.report_query_service import (
    build_distinct_value_query, build_measurement_export_query, build_measurement_filter_query,
)
from metroliza.reports.report_schema import ensure_report_schema


@pytest.fixture
def choices_db(tmp_path):
    path = tmp_path / "choices.sqlite"
    ensure_report_schema(str(path))
    with closing(sqlite3.connect(path)) as connection, connection:
        # Foreign keys deliberately off: even old orphan records must stay excluded.
        connection.executescript("""
            INSERT INTO source_files(id,sha256,source_format,discovered_at,is_active)
            VALUES (1,'synthetic-1','pdf','2026',1),(2,'synthetic-2','pdf','2026',0);
            INSERT INTO parsed_reports(id,source_file_id,parser_id,template_family,template_variant,parse_status,created_at,updated_at)
            VALUES (1,1,'parser-z','family-z','v-z','parsed','2026','2026'),
                   (2,2,'parser-a','family-a','v-a','failed','2026','2026'),
                   (3,999,'excluded','excluded','excluded','parsed','2026','2026');
            INSERT INTO report_metadata(report_id,reference,part_name,revision,sample_number,operator_name,sample_number_kind,metadata_version)
            VALUES (1,'REF-Z',' Part ','Z','2','Z','unknown','v1'),
                   (2,'REF-A','Part','A','10','A','stats_count','v1');
            INSERT INTO report_measurements(report_id,row_order,header,ax,status_code)
            VALUES (1,1,'Z','X','ok'),(1,2,'A',' a ','nok'),(1,3,'A','X','unknown'),
                   (2,1,'A','y','ok'),(2,2,' ',NULL,'unknown'),(2,3,NULL,'','unknown'),
                   (3,1,'excluded-source','excluded-source','ok'),
                   (999,1,'excluded-report','excluded-report','ok');
        """)
    return str(path)


def _base_distinct_query(column, view, scope):
    """Frozen builder behavior from 82f8f576, before the #1127 optimization."""
    if scope:
        # Test inputs use either an explicit export query or this report-only scope.
        source_query = build_measurement_export_query(scope) if view == "vw_measurement_export" and " AS REPORT_ID" in scope else scope
        source = f"({source_query}) AS filtered_data"
    else:
        source = view
    return (f'SELECT DISTINCT "{column}" AS value FROM {source} '
            f'WHERE "{column}" IS NOT NULL AND TRIM(CAST("{column}" AS TEXT)) <> \'\' ORDER BY value')


@pytest.mark.parametrize("scope", [None, "default", "export", "report", "empty"])
@pytest.mark.parametrize("legacy", [False, True])
def test_all_fourteen_choices_match_base_in_order(choices_db, tmp_path, scope, legacy):
    database = choices_db
    if legacy:
        database = str(tmp_path / "legacy.sqlite")
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executescript("""
                CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT);
                CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY, REPORT_ID INTEGER, HEADER TEXT, AX TEXT);
                INSERT INTO REPORTS VALUES (1,'REF-Z'),(2,'REF-A');
                INSERT INTO MEASUREMENTS VALUES (1,1,'Z','X'),(2,1,'A',' a '),(3,2,'A','y'),(4,2,' ',NULL);
            """)
        ensure_report_schema(database)
    queries = {
        None: None,
        "default": build_measurement_export_query(),
        "export": build_measurement_filter_query(reference_values=["REF-Z"]),
        "report": "SELECT report_id AS REPORT_ID, reference AS REFERENCE FROM vw_report_overview WHERE report_id = 1",
        "empty": build_measurement_filter_query(reference_values=["absent"]),
    }
    query = queries[scope]
    with closing(sqlite3.connect(database)) as connection:
        expected = {
            attr: tuple(row[0] for row in connection.execute(_base_distinct_query(col, view, query)))
            for attr, col, view in FILTER_VALUE_SPECS
        }
        for _, column, view in FILTER_VALUE_SPECS:
            assert connection.execute(build_distinct_value_query(column, source_view=view, filter_query=query)).fetchall() == connection.execute(_base_distinct_query(column, view, query)).fetchall()
    assert load_filter_values(database, query) == expected


def test_unscoped_measurement_choices_use_existing_indexes(choices_db):
    with closing(sqlite3.connect(choices_db)) as connection:
        for column, index in [("AX", "ax"), ("HEADER", "header"), ("STATUS_CODE", "status")]:
            query = build_distinct_value_query(column)
            plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query))
            assert "idx_report_measurements_" + index in plan
            assert "selected_location" not in plan


@pytest.mark.parametrize("wal", [False, True])
def test_cache_invalidates_external_commit_and_keeps_scopes_separate(choices_db, monkeypatch, wal):
    with closing(sqlite3.connect(choices_db)) as writer:
        if wal:
            writer.execute("PRAGMA journal_mode=WAL")
        before = load_filter_values(choices_db)
        original = filter_values.ensure_report_schema
        monkeypatch.setattr(filter_values, "ensure_report_schema", lambda *_: pytest.fail("cache miss"))
        assert load_filter_values(choices_db) == before
        monkeypatch.setattr(filter_values, "ensure_report_schema", original)
        writer.execute("UPDATE report_measurements SET ax = 'CHANGED' WHERE report_id = 1")
        writer.commit()
        assert load_filter_values(choices_db)["ax_list"] == ("CHANGED", "y")
        scoped = load_filter_values(choices_db, build_measurement_filter_query(reference_values=["REF-A"]))
        assert scoped["ax_list"] == ("y",)
        assert load_filter_values(choices_db)["ax_list"] == ("CHANGED", "y")


def test_cache_invalidates_replacement_and_is_bounded(choices_db, tmp_path):
    before = load_filter_values(choices_db)
    replacement = tmp_path / "replacement.sqlite"
    with closing(sqlite3.connect(choices_db)) as src, closing(sqlite3.connect(replacement)) as dst:
        src.backup(dst)
        dst.execute("UPDATE report_measurements SET header = 'REPLACED'")
        dst.commit()
    replacement.replace(choices_db)
    assert load_filter_values(choices_db)["header_list"] != before["header_list"]
    for number in range(12):
        load_filter_values(choices_db, build_measurement_filter_query(reference_values=[f"missing-{number}"]))
    assert len(filter_values._CACHE) <= filter_values._CACHE_LIMIT


def test_cancel_and_writer_during_snapshot_do_not_cache(choices_db, monkeypatch):
    with pytest.raises(InterruptedError):
        load_filter_values(choices_db, cancelled=lambda: True)
    with filter_values._CACHE_LOCK:
        filter_values._CACHE.clear()
    # Simulate a changed DB/WAL signature between the snapshot and publication.
    original_signature = filter_values._database_signature
    calls = []

    def changing_signature(path):
        calls.append(path)
        return original_signature(path) + ((len(calls),),)

    monkeypatch.setattr(filter_values, "_database_signature", changing_signature)
    load_filter_values(choices_db)
    assert not filter_values._CACHE
