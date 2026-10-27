"""Ordered-choice equivalence and database cache regressions for #1127."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

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


@pytest.fixture
def report_choice_edges(choices_db):
    with closing(sqlite3.connect(choices_db)) as connection, connection:
        connection.executescript("""
            INSERT INTO source_files(id,sha256,source_format,discovered_at,is_active)
            VALUES (4,'synthetic-4','pdf','2026',1),(5,'synthetic-5','pdf','2026',1);
            INSERT INTO parsed_reports(id,source_file_id,parser_id,template_family,template_variant,parse_status,created_at,updated_at)
            VALUES (4,4,'empty-parser','empty-family','empty-variant','parsed','2026','2026'),
                   (5,5,'01','  ','','parsed','2026','2026');
            INSERT INTO report_metadata(report_id,reference,part_name,revision,sample_number,operator_name,sample_number_kind,metadata_version)
            VALUES (4,'EMPTY','empty-part','empty-rev','empty-sample','empty-operator','unknown','v1'),
                   (5,'01','  ','',NULL,' 01 ','unknown','v1');
            INSERT INTO report_measurements(report_id,row_order,header,ax,status_code)
            VALUES (5,1,'01','1','ok'),(5,2,'01','1','ok');
            INSERT INTO source_file_locations(id,source_file_id,absolute_path,directory_path,file_name,file_extension,discovered_at,is_active)
            VALUES (1,1,'/synthetic/old','/synthetic','old.pdf','.pdf','2024',1),
                   (2,1,'/synthetic/tie','/synthetic','tie.pdf','.pdf','2025',1),
                   (3,1,'/synthetic/chosen','/synthetic','01.pdf','.pdf','2025',1),
                   (4,1,'/synthetic/inactive','/synthetic','inactive.pdf','.pdf','2026',0),
                   (5,2,'/synthetic/blank','/synthetic','  ','.pdf','2026',1),
                   (6,5,'/synthetic/numeric','/synthetic','01.pdf','.pdf','2026',1);
        """)
    return choices_db


def _typed_choices(values):
    return {key: tuple((type(value), value) for value in choices) for key, choices in values.items()}


@pytest.mark.parametrize("scope", [None, "blank", "default", "padded", "filtered", "row", "empty", "custom"])
def test_t14_ordered_typed_choices_preserve_original_scope(report_choice_edges, scope):
    canonical = build_measurement_export_query()
    custom = """SELECT 1 AS REPORT_ID, 1 AS MEASUREMENT_ID, 7 AS REFERENCE,
        X'3031' AS PART_NAME, 2.5 AS REVISION, ' 01 ' AS TEMPLATE_VARIANT,
        '02' AS SAMPLE_NUMBER, 'custom' AS OPERATOR_NAME, NULL AS SAMPLE_NUMBER_KIND,
        3 AS AX, 'custom-header' AS HEADER, 'nok' AS STATUS_CODE,
        'custom.pdf' AS FILENAME, 'custom-parser' AS PARSER_ID, '' AS TEMPLATE_FAMILY"""
    query = {
        None: None, "blank": "  ", "default": canonical, "padded": "  " + canonical + ";  ",
        "filtered": build_measurement_filter_query(reference_values=["REF-Z", "01"]),
        "row": build_measurement_filter_query(ax_values=["X"]),
        "empty": build_measurement_filter_query(reference_values=["absent"]), "custom": custom,
    }[scope]
    # Freeze the old DISTINCT-over-scope operation independently of the builder.
    normalized = query.strip().rstrip(";").rstrip() if query else ""
    with closing(sqlite3.connect(report_choice_edges)) as connection:
        expected = {}
        for attribute, column, view in FILTER_VALUE_SPECS:
            source = f"({normalized}) AS filtered_data" if normalized else view
            old_query = (f'SELECT DISTINCT "{column}" AS value FROM {source} '
                         f'WHERE "{column}" IS NOT NULL AND TRIM(CAST("{column}" AS TEXT)) <> \'\' '
                         'ORDER BY value')
            expected[attribute] = tuple(row[0] for row in connection.execute(old_query))
            actual = connection.execute(build_distinct_value_query(column, source_view=view, filter_query=query))
            assert _typed_choices({attribute: tuple(row[0] for row in actual)}) == _typed_choices({attribute: expected[attribute]})
    assert _typed_choices(load_filter_values(report_choice_edges, query)) == _typed_choices(expected)
    assert len(expected) == 14
    if scope in (None, "blank"):
        assert expected["reference_list"] == ("01", "EMPTY", "REF-A", "REF-Z")
        assert expected["filename_list"] == ("FILENAME",)
    elif scope in ("default", "padded"):
        assert expected == {
            "ax_list": (" a ", "1", "X", "y"), "header_list": ("01", "A", "Z"),
            "all_headers_list": ("01", "A", "Z"), "reference_list": ("01", "REF-A", "REF-Z"),
            "part_name_list": (" Part ", "Part"), "revision_list": ("A", "Z"),
            "template_variant_list": ("v-a", "v-z"), "sample_number_list": ("10", "2"),
            "operator_name_list": (" 01 ", "A", "Z"), "sample_number_kind_list": ("stats_count", "unknown"),
            "status_code_list": ("nok", "ok", "unknown"), "filename_list": ("01.pdf",),
            "parser_id_list": ("01", "parser-a", "parser-z"), "template_family_list": ("family-a", "family-z"),
        }
    elif scope == "custom":
        assert _typed_choices(expected)["reference_list"] == ((int, 7),)
        assert _typed_choices(expected)["part_name_list"] == ((bytes, b"01"),)
        assert _typed_choices(expected)["revision_list"] == ((float, 2.5),)


def _t14_indexed_report_lookup(step):
    return step in {
        "SEARCH meas USING COVERING INDEX idx_report_measurements_report (report_id=?)",
        "SEARCH meas EXISTS USING COVERING INDEX idx_report_measurements_report (report_id=?)",
    }


@pytest.mark.parametrize("step", [
    "SCAN meas USING COVERING INDEX idx_report_measurements_report (report_id=?)",
    "SEARCH meas EXISTS USING COVERING INDEX idx_report_measurements_report_header_ax (report_id=?)",
    "SEARCH other EXISTS USING COVERING INDEX idx_report_measurements_report (report_id=?)",
    "SEARCH meas EXISTS USING COVERING INDEX idx_report_measurements_report",
    "SEARCH meas EXISTS USING COVERING INDEX idx_report_measurements_report (header=?)",
])
def test_t14_indexed_report_lookup_rejects_wrong_activation(step):
    assert not _t14_indexed_report_lookup(step)


def test_t14_canonical_report_choices_use_indexed_exists(report_choice_edges):
    canonical = build_measurement_export_query()
    with closing(sqlite3.connect(report_choice_edges)) as connection:
        traced = []
        connection.set_trace_callback(traced.append)
        values = filter_values._query_values(connection, canonical, FILTER_VALUE_SPECS, lambda: False)
        report_queries = [query for query in traced if "AS report_choices" in query]
        assert len(report_queries) == 10
        assert len(traced) == 13  # The two header lists share their query.
        for query in report_queries:
            assert "vw_measurement_export" not in query
            plan = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query)]
            assert any(_t14_indexed_report_lookup(step) for step in plan)
            assert not any("SCAN meas" in step for step in plan)
        assert values["filename_list"] == ("01.pdf",)
        assert "EMPTY" not in values["reference_list"]


@pytest.mark.parametrize("scope", [None, "blank", "padded", "filtered", "custom", "subclass"])
def test_t14_uncertain_scope_retains_original_report_query(scope):
    calls = []

    class CustomScope(str):
        def strip(self, *args):
            calls.append("strip")
            return super().strip(*args)

        def __eq__(self, other):
            pytest.fail("eligibility must not compare custom strings")

    canonical = build_measurement_export_query()
    query = {
        None: None, "blank": "  ", "padded": canonical + ";",
        "filtered": build_measurement_filter_query(reference_values=["REF-Z"]),
        "custom": canonical.replace("reference AS REFERENCE", "7 AS REFERENCE"),
        "subclass": CustomScope(canonical),
    }[scope]
    result = build_distinct_value_query("REFERENCE", source_view="vw_report_overview", filter_query=query)
    assert "report_choices" not in result
    if scope == "subclass":
        assert calls == ["strip"]


def test_t14_custom_columns_and_views_do_not_gain_eligibility_callbacks():
    class CustomColumn(str):
        def upper(self):
            pytest.fail("report eligibility must not dispatch custom column methods")

    query = build_distinct_value_query(
        CustomColumn("REFERENCE"), source_view="vw_report_overview", filter_query=build_measurement_export_query(),
    )
    assert "report_choices" not in query
    other_view = build_distinct_value_query(
        "REFERENCE", source_view="custom_view", filter_query=build_measurement_export_query(),
    )
    assert "report_choices" not in other_view


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


@pytest.mark.skipif(os.name != "posix", reason="chmod changes inode ctime only on POSIX")
@pytest.mark.parametrize("wal", [False, True])
def test_cache_ignores_reader_metadata_changes(choices_db, monkeypatch, wal):
    with closing(sqlite3.connect(choices_db)) as keeper:
        keeper.execute("PRAGMA journal_mode=" + ("WAL" if wal else "DELETE"))
        target = Path(choices_db + "-wal" if wal else choices_db)
        original = filter_values._query_values

        def query_with_metadata_change(*args):
            values = original(*args)
            before = target.stat()
            os.chmod(target, before.st_mode)
            after = target.stat()
            assert after.st_ctime_ns != before.st_ctime_ns
            assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
                before.st_ino, before.st_size, before.st_mtime_ns,
            )
            return values

        monkeypatch.setattr(filter_values, "_query_values", query_with_metadata_change)
        before = load_filter_values(choices_db)
        # Neither the next lookup nor snapshot publication should depend on ctime.
        os.chmod(target, target.stat().st_mode)
        monkeypatch.setattr(filter_values, "ensure_report_schema", lambda *_: pytest.fail("cache miss"))
        assert load_filter_values(choices_db) == before


@pytest.mark.parametrize("mode", ["DELETE", "TRUNCATE", "RESTART"])
def test_cache_invalidates_same_size_commit_with_unchanged_timestamps(choices_db, monkeypatch, mode):
    # The database header is read on Windows only; exercise that policy everywhere.
    monkeypatch.setattr(filter_values, "_DATABASE_HEADER_BYTES", 100)
    database = Path(choices_db)
    wal = Path(choices_db + "-wal")
    # The fixture schema is ready. Its schema writer would switch DELETE to WAL
    # and add unrelated WAL frames, obscuring the controlled same-size commits.
    monkeypatch.setattr(filter_values, "ensure_report_schema", lambda *_: None)
    # Model creation-time ctime (CPython 3.11 on Windows), even on Unix.
    original_stat = Path.stat

    def creation_time_fields(stat):
        fields = {name: getattr(stat, name) for name in dir(stat) if name.startswith("st_")}
        fields.update(st_ctime=0, st_ctime_ns=0)
        return SimpleNamespace(**fields)

    def creation_time_stat(path, *args, **kwargs):
        stat = original_stat(path, *args, **kwargs)
        if path not in (database, wal):
            return stat
        return creation_time_fields(stat)

    monkeypatch.setattr(Path, "stat", creation_time_stat)
    with closing(sqlite3.connect(choices_db)) as writer:
        writer.execute("PRAGMA journal_mode=" + ("DELETE" if mode == "DELETE" else "WAL"))
        writer.execute("UPDATE report_measurements SET ax = 'FIRST' WHERE report_id = 1")
        writer.commit()
        if mode != "DELETE":
            # Copy the initial commit into the DB before caching, keeping the WAL.
            assert writer.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()[0] == 0
        before = load_filter_values(choices_db)
        paths = (database,) if mode == "DELETE" else (database, wal)
        stats = {path: path.stat() for path in paths}
        database_header = database.read_bytes()[:100]
        wal_header = wal.read_bytes()[:32] if mode != "DELETE" else None
        if mode != "DELETE":
            assert writer.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()[0] == 0
        writer.execute("UPDATE report_measurements SET ax = 'LATER' WHERE report_id = 1")
        writer.commit()
        for path, stat in stats.items():
            assert path.stat().st_ino == stat.st_ino
            assert path.stat().st_size == stat.st_size
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            assert path.stat().st_mtime_ns == stat.st_mtime_ns
        if mode != "DELETE":
            assert database.read_bytes()[:100] == database_header
            assert wal.read_bytes()[:32] != wal_header
        else:
            assert database.read_bytes()[:100] != database_header
        assert before["ax_list"] == ("FIRST", "y")
        assert load_filter_values(choices_db)["ax_list"] == ("LATER", "y")


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


def test_unreadable_header_loads_values_without_caching(choices_db, monkeypatch):
    monkeypatch.setattr(filter_values, "_DATABASE_HEADER_BYTES", 100)
    database = Path(choices_db)
    original_open = Path.open

    def locked_open(path, *args, **kwargs):
        if path == database:
            raise PermissionError("sharing violation")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked_open)
    first = load_filter_values(choices_db)
    calls = []
    original_schema = filter_values.ensure_report_schema
    monkeypatch.setattr(
        filter_values, "ensure_report_schema", lambda *args: calls.append(args) or original_schema(*args)
    )
    assert load_filter_values(choices_db) == first
    assert calls, "an unreadable header must not produce a cache hit"


@pytest.mark.skipif(os.name == "nt", reason="the POSIX fcntl lock rule")
def test_posix_signature_never_opens_the_live_database_file(choices_db, monkeypatch):
    # Closing any descriptor of a SQLite database drops this process's fcntl locks.
    database = Path(choices_db)
    opened = []
    original_open = Path.open

    def recording_open(path, *args, **kwargs):
        opened.append(Path(path))
        return original_open(path, *args, **kwargs)

    with closing(sqlite3.connect(choices_db)) as keeper:
        keeper.execute("PRAGMA journal_mode=WAL")
        keeper.execute("UPDATE report_measurements SET ax = ax")
        keeper.commit()
        monkeypatch.setattr(Path, "open", recording_open)
        filter_values._database_signature(database)
    assert database not in opened
    assert Path(choices_db + "-wal") in opened
