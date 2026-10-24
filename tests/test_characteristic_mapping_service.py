from contextlib import closing
import sqlite3

import pytest

import random

from metroliza.reports import characteristic_mapping_service as service_module
from metroliza.reports.db import execute_with_retry
from modules.characteristic_mapping_service import (
    fetch_distinct_references,
    fetch_distinct_report_metric_names,
    fetch_mapping_impact_counts,
)


_NATIVE_SQLITE_VERSION = tuple(int(part) for part in sqlite3.sqlite_version.split('.'))


def _create_measurement_export_db(db_path):
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE vw_measurement_export (
                report_id INTEGER,
                measurement_id INTEGER,
                reference TEXT,
                header TEXT,
                ax TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO vw_measurement_export(report_id, measurement_id, reference, header, ax)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, 1, 'REF-1', ' DIA ', ' X '),
                (1, 2, 'REF-1', 'DIA', ''),
                (2, 3, 'REF-2', 'DIA', 'X'),
                (3, 4, 'REF-3', '   ', 'Y'),
                (4, 5, ' ', 'LENGTH', 'Y'),
                (5, 6, 'REF-2', 'LENGTH', 'Y'),
            ],
        )
        connection.commit()


def test_fetch_distinct_report_metric_names_matches_export_metric_identity(tmp_path):
    db_path = str(tmp_path / 'reports.db')
    _create_measurement_export_db(db_path)

    rows = fetch_distinct_report_metric_names(db_path)
    by_metric = {row['metric_name']: row for row in rows}

    assert list(by_metric) == ['DIA', 'DIA - X', 'LENGTH - Y']
    assert by_metric['DIA'] == {
        'metric_name': 'DIA',
        'measurement_count': 1,
        'report_count': 1,
        'reference_count': 1,
        'sample_references': ['REF-1'],
    }
    assert by_metric['DIA - X'] == {
        'metric_name': 'DIA - X',
        'measurement_count': 2,
        'report_count': 2,
        'reference_count': 2,
        'sample_references': ['REF-1', 'REF-2'],
    }
    assert by_metric['LENGTH - Y'] == {
        'metric_name': 'LENGTH - Y',
        'measurement_count': 2,
        'report_count': 2,
        'reference_count': 1,
        'sample_references': ['REF-2'],
    }


def test_fetch_distinct_report_metric_names_honors_sample_reference_limit(tmp_path):
    db_path = str(tmp_path / 'reports.db')
    _create_measurement_export_db(db_path)

    rows = fetch_distinct_report_metric_names(db_path, sample_reference_limit=1)
    by_metric = {row['metric_name']: row for row in rows}

    assert by_metric['DIA - X']['sample_references'] == ['REF-1']


def test_fetch_distinct_references_returns_non_empty_reference_counts(tmp_path):
    db_path = str(tmp_path / 'reports.db')
    _create_measurement_export_db(db_path)

    rows = fetch_distinct_references(db_path)

    assert rows == [
        {'reference': 'REF-1', 'measurement_count': 2, 'report_count': 1},
        {'reference': 'REF-2', 'measurement_count': 2, 'report_count': 2},
        {'reference': 'REF-3', 'measurement_count': 1, 'report_count': 1},
    ]


def test_fetch_mapping_impact_counts_applies_global_and_reference_scope(tmp_path):
    db_path = str(tmp_path / 'reports.db')
    _create_measurement_export_db(db_path)

    assert fetch_mapping_impact_counts(
        db_path,
        alias_name='DIA - X',
        scope_type='global',
        scope_value='ignored',
    ) == {'measurement_count': 2, 'report_count': 2, 'reference_count': 2}

    assert fetch_mapping_impact_counts(
        db_path,
        alias_name='LENGTH - Y',
        scope_type='reference',
        scope_value='REF-2',
    ) == {'measurement_count': 1, 'report_count': 1, 'reference_count': 1}

    assert fetch_mapping_impact_counts(
        db_path,
        alias_name='LENGTH - Y',
        scope_type='reference',
        scope_value='REF-MISSING',
    ) == {'measurement_count': 0, 'report_count': 0, 'reference_count': 0}


def test_fetch_mapping_impact_counts_validates_inputs(tmp_path):
    db_path = str(tmp_path / 'reports.db')
    _create_measurement_export_db(db_path)

    with pytest.raises(ValueError, match='alias_name is required'):
        fetch_mapping_impact_counts(db_path, alias_name=' ', scope_type='global')

    with pytest.raises(ValueError, match='scope_value is required for reference scope'):
        fetch_mapping_impact_counts(db_path, alias_name='DIA - X', scope_type='reference')


def test_discovery_helpers_fail_soft_for_alias_only_database(tmp_path):
    db_path = str(tmp_path / 'aliases_only.db')
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE CHARACTERISTIC_ALIASES (
                id INTEGER PRIMARY KEY,
                alias_name TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_value TEXT NULL
            )
            """
        )
        connection.commit()

    assert fetch_distinct_report_metric_names(db_path) == []
    assert fetch_distinct_references(db_path) == []
    assert fetch_mapping_impact_counts(
        db_path,
        alias_name='DIA - X',
        scope_type='global',
    ) == {'measurement_count': 0, 'report_count': 0, 'reference_count': 0}


def test_discovery_helpers_fail_soft_when_measurement_view_columns_are_missing(tmp_path):
    db_path = str(tmp_path / 'malformed_measurements.db')
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute('CREATE TABLE vw_measurement_export (reference TEXT)')
        connection.execute("INSERT INTO vw_measurement_export(reference) VALUES ('REF-1')")
        connection.commit()

    assert fetch_distinct_report_metric_names(db_path) == []
    assert fetch_distinct_references(db_path) == []
    assert fetch_mapping_impact_counts(
        db_path,
        alias_name='DIA - X',
        scope_type='global',
    ) == {'measurement_count': 0, 'report_count': 0, 'reference_count': 0}


def test_service_falls_back_to_legacy_reports_measurements_schema(tmp_path):
    db_path = str(tmp_path / 'legacy.db')
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute('CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)')
        connection.execute(
            """
            CREATE TABLE MEASUREMENTS (
                ID INTEGER PRIMARY KEY,
                REPORT_ID INTEGER,
                HEADER TEXT,
                AX TEXT
            )
            """
        )
        connection.executemany(
            'INSERT INTO REPORTS(ID, REFERENCE) VALUES (?, ?)',
            [(10, 'R-B'), (11, 'R-A')],
        )
        connection.executemany(
            'INSERT INTO MEASUREMENTS(ID, REPORT_ID, HEADER, AX) VALUES (?, ?, ?, ?)',
            [
                (1, 10, 'WIDTH', 'Y'),
                (2, 11, 'WIDTH', ''),
                (3, 11, 'WIDTH', 'Y'),
            ],
        )
        connection.commit()

    rows = fetch_distinct_report_metric_names(db_path)
    by_metric = {row['metric_name']: row for row in rows}

    assert by_metric['WIDTH'] == {
        'metric_name': 'WIDTH',
        'measurement_count': 1,
        'report_count': 1,
        'reference_count': 1,
        'sample_references': ['R-A'],
    }
    assert by_metric['WIDTH - Y'] == {
        'metric_name': 'WIDTH - Y',
        'measurement_count': 2,
        'report_count': 2,
        'reference_count': 2,
        'sample_references': ['R-A', 'R-B'],
    }


# ---------------------------------------------------------------------------
# Equivalence of fetch_distinct_report_metric_names with the per-metric
# reference implementation it replaced (1 aggregate query + 1 query per metric).
# ---------------------------------------------------------------------------


_METRIC_IDENTITY_SQL = """
    CASE
        WHEN TRIM(COALESCE(CAST(header AS TEXT), '')) <> ''
          AND TRIM(COALESCE(CAST(ax AS TEXT), '')) <> ''
        THEN TRIM(CAST(header AS TEXT)) || ' - ' || TRIM(CAST(ax AS TEXT))
        WHEN TRIM(COALESCE(CAST(header AS TEXT), '')) <> ''
        THEN TRIM(CAST(header AS TEXT))
        ELSE ''
    END
"""

_REFERENCE_SQL = "NULLIF(TRIM(COALESCE(CAST(reference AS TEXT), '')), '')"


def _original_metric_source_cte(source_sql: str) -> str:
    return f"""
        WITH measurement_source AS (
            {source_sql}
        ),
        metric_source AS (
            SELECT
                {_METRIC_IDENTITY_SQL} AS metric_name,
                {_REFERENCE_SQL} AS reference,
                report_id,
                measurement_id
            FROM measurement_source
        )
    """


def _oracle_fetch_sample_references(db_path, source_sql, metric_name, *, sample_reference_limit, connection=None):
    limit = max(0, int(sample_reference_limit or 0))
    if limit == 0:
        return []

    try:
        rows = execute_with_retry(
            db_path,
            f"""
            {_original_metric_source_cte(source_sql)}
            SELECT reference
            FROM metric_source
            WHERE metric_name = ?
              AND reference IS NOT NULL
            GROUP BY reference
            ORDER BY LOWER(reference), reference
            LIMIT ?
            """,
            params=(metric_name, limit),
            connection=connection,
        )
    except sqlite3.OperationalError as exc:
        if service_module._is_missing_measurement_source_error(exc):
            return []
        raise
    return [str(row[0]) for row in rows]


def _oracle_fetch_distinct_report_metric_names(db_path, *, sample_reference_limit=3, connection=None):
    source_sql = service_module._measurement_source_sql(db_path, connection=connection)
    if source_sql is None:
        return []

    try:
        rows = execute_with_retry(
            db_path,
            f"""
            {_original_metric_source_cte(source_sql)}
            SELECT
                metric_name,
                COUNT(*) AS measurement_count,
                COUNT(DISTINCT report_id) AS report_count,
                COUNT(DISTINCT reference) AS reference_count
            FROM metric_source
            WHERE metric_name <> ''
            GROUP BY metric_name
            ORDER BY LOWER(metric_name), metric_name
            """,
            connection=connection,
        )
    except sqlite3.OperationalError as exc:
        if service_module._is_missing_measurement_source_error(exc):
            return []
        raise

    return [
        {
            'metric_name': str(metric_name),
            'measurement_count': int(measurement_count or 0),
            'report_count': int(report_count or 0),
            'reference_count': int(reference_count or 0),
            'sample_references': _oracle_fetch_sample_references(
                db_path,
                source_sql,
                str(metric_name),
                sample_reference_limit=sample_reference_limit,
                connection=connection,
            ),
        }
        for metric_name, measurement_count, report_count, reference_count in rows
    ]


_EQUIVALENCE_LIMITS = [0, 1, 2, 3, 4, 100, -2, None, '2']

# (reference, header, ax) variants covering NULL/blank/whitespace/mixed-case/numeric/duplicate values.
_TRICKY_ROWS = [
    ('REF-b', 'DIA', 'X'),
    ('ref-B', 'DIA', 'X'),
    ('Ref-a', 'DIA', 'X'),
    ('REF-A', 'DIA', 'X'),
    ('REF-A', 'DIA', 'X'),
    ('  REF-A  ', 'DIA', 'X'),
    (None, 'DIA', 'X'),
    ('', 'DIA', 'X'),
    ('   ', 'DIA', 'X'),
    (None, 'ONLY-NULL', ''),
    ('', 'ONLY-NULL', None),
    (12, 'NUM', 'Z'),
    (7, 'NUM', 'Z'),
    ('7', 'NUM', 'Z'),
    ('\u00c4REF', 'UNI', ''),
    ('\u00e4ref', 'UNI', ''),
    ('zref', 'UNI', ''),
    ('ZREF', 'UNI', ''),
    ('REF-1', '   ', 'IGNORED'),
    ('REF-1', None, 'IGNORED'),
    ('REF-1', ' mixed ', ' Case '),
    ('REF-2', 'Mixed', 'case'),
    ('REF-3', 'MIXED', 'CASE'),
]


def _build_view_db(db_path, rows):
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute(
            'CREATE TABLE vw_measurement_export '
            '(report_id INTEGER, measurement_id INTEGER, reference, header, ax)'
        )
        connection.executemany(
            'INSERT INTO vw_measurement_export(report_id, measurement_id, reference, header, ax) '
            'VALUES (?, ?, ?, ?, ?)',
            [(index // 3 + 1, index + 1, ref, header, ax) for index, (ref, header, ax) in enumerate(rows)],
        )


def _random_rows(seed, count=600):
    rng = random.Random(seed)
    headers = [f'H{i:02d}' for i in range(40)] + ['h00', ' H01 ', '', None]
    axes = ['X', 'Y', '', None, ' Z ', 'x']
    references = (
        [f'REF-{i:02d}' for i in range(15)]
        + [f'ref-{i:02d}' for i in range(5)]
        + [None, '', '  ', 3, '\u00c4B', '\u00e4b']
    )
    return [(rng.choice(references), rng.choice(headers), rng.choice(axes)) for _ in range(count)]


def _assert_equivalent(db_path, **kwargs):
    for limit in _EQUIVALENCE_LIMITS:
        expected = _oracle_fetch_distinct_report_metric_names(db_path, sample_reference_limit=limit, **kwargs)
        actual = fetch_distinct_report_metric_names(db_path, sample_reference_limit=limit, **kwargs)
        assert actual == expected, f'limit={limit!r}'
        for row in actual:
            assert type(row['metric_name']) is str
            assert all(type(row[key]) is int for key in ('measurement_count', 'report_count', 'reference_count'))
            assert type(row['sample_references']) is list
            assert all(type(reference) is str for reference in row['sample_references'])
        assert [list(row) for row in actual] == [list(row) for row in expected]
    default = _oracle_fetch_distinct_report_metric_names(db_path, **kwargs)
    assert fetch_distinct_report_metric_names(db_path, **kwargs) == default
    return default


def test_metric_names_equivalent_to_per_metric_reference_on_tricky_values(tmp_path):
    db_path = str(tmp_path / 'tricky.db')
    _build_view_db(db_path, _TRICKY_ROWS)

    expected = _assert_equivalent(db_path)

    assert [tuple(row.values()) for row in expected] == [
        ('DIA - X', 9, 3, 4, ['REF-A', 'Ref-a', 'REF-b']),
        ('MIXED - CASE', 1, 1, 1, ['REF-3']),
        ('Mixed - case', 1, 1, 1, ['REF-2']),
        ('mixed - Case', 1, 1, 1, ['REF-1']),
        ('NUM - Z', 3, 2, 2, ['12', '7']),
        ('ONLY-NULL', 2, 1, 0, []),
        ('UNI', 4, 2, 4, ['ZREF', 'zref', '\u00c4REF']),
    ]

    by_metric = {row['metric_name']: row for row in expected}
    assert 'ONLY-NULL' in by_metric and by_metric['ONLY-NULL']['sample_references'] == []
    assert by_metric['DIA - X']['sample_references'] == ['REF-A', 'Ref-a', 'REF-b']
    assert all(row['metric_name'] for row in expected)


def test_metric_names_equivalent_on_randomised_database(tmp_path):
    for seed in (1, 2, 3):
        db_path = str(tmp_path / f'random_{seed}.db')
        _build_view_db(db_path, _random_rows(seed))
        expected = _assert_equivalent(db_path)
        assert len(expected) > 20


def test_metric_names_equivalent_with_explicit_connection(tmp_path):
    db_path = str(tmp_path / 'with_connection.db')
    _build_view_db(db_path, _TRICKY_ROWS + _random_rows(9, 200))

    with closing(sqlite3.connect(db_path)) as connection:
        _assert_equivalent(db_path, connection=connection)
        assert fetch_distinct_report_metric_names(db_path, connection=connection) == (
            fetch_distinct_report_metric_names(db_path)
        )


def test_metric_names_equivalent_on_current_report_tables(tmp_path):
    db_path = str(tmp_path / 'current_tables.db')
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute('CREATE TABLE parsed_reports (id INTEGER PRIMARY KEY)')
        connection.execute('CREATE TABLE report_metadata (report_id INTEGER, reference TEXT)')
        connection.execute(
            'CREATE TABLE report_measurements (id INTEGER PRIMARY KEY, report_id INTEGER, header TEXT, ax TEXT)'
        )
        references = ['b-ref', 'B-ref', 'A-ref', None, '', 'a-REF']
        for report_id, reference in enumerate(references, start=1):
            connection.execute('INSERT INTO parsed_reports(id) VALUES (?)', (report_id,))
            if report_id != 4:  # report 4 has no metadata row: LEFT JOIN yields NULL reference
                connection.execute(
                    'INSERT INTO report_metadata(report_id, reference) VALUES (?, ?)', (report_id, reference)
                )
        # report 7 has measurements but no parsed_reports row: dropped by the JOIN
        for index in range(60):
            connection.execute(
                'INSERT INTO report_measurements(report_id, header, ax) VALUES (?, ?, ?)',
                (index % 7 + 1, f'M{index % 5}', 'X' if index % 2 else ''),
            )

    expected = _assert_equivalent(db_path)
    assert {row['metric_name'] for row in expected} >= {'M0', 'M0 - X', 'M1', 'M1 - X'}


def test_metric_names_equivalent_on_legacy_schema(tmp_path):
    db_path = str(tmp_path / 'legacy_equivalence.db')
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute('CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)')
        connection.execute('CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY, REPORT_ID INTEGER, HEADER TEXT, AX TEXT)')
        references = ['R-b', 'r-B', 'R-A', None, '', ' R-A ', 'r-a']
        connection.executemany(
            'INSERT INTO REPORTS(ID, REFERENCE) VALUES (?, ?)',
            list(enumerate(references, start=1)),
        )
        connection.executemany(
            'INSERT INTO MEASUREMENTS(ID, REPORT_ID, HEADER, AX) VALUES (?, ?, ?, ?)',
            [(i, i % 7 + 1, f'W{i % 4}', ('Y', '', None)[i % 3]) for i in range(1, 50)],
        )

    expected = _assert_equivalent(db_path)
    assert expected


def test_metric_names_equivalent_when_source_is_missing_or_malformed(tmp_path):
    empty_db = str(tmp_path / 'empty.db')
    with closing(sqlite3.connect(empty_db)):
        pass
    assert fetch_distinct_report_metric_names(empty_db) == _oracle_fetch_distinct_report_metric_names(empty_db) == []

    only_reports = str(tmp_path / 'only_reports.db')
    with closing(sqlite3.connect(only_reports)) as connection, connection:
        connection.execute('CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)')
    assert (
        fetch_distinct_report_metric_names(only_reports)
        == _oracle_fetch_distinct_report_metric_names(only_reports)
        == []
    )

    malformed = str(tmp_path / 'malformed.db')
    with closing(sqlite3.connect(malformed)) as connection, connection:
        connection.execute('CREATE TABLE vw_measurement_export (reference TEXT)')
        connection.execute("INSERT INTO vw_measurement_export(reference) VALUES ('REF-1')")
    assert (
        fetch_distinct_report_metric_names(malformed)
        == _oracle_fetch_distinct_report_metric_names(malformed)
        == []
    )

    blank_only = str(tmp_path / 'blank_only.db')
    _build_view_db(blank_only, [('REF-1', '  ', 'X'), ('REF-2', None, 'Y')])
    assert fetch_distinct_report_metric_names(blank_only) == _oracle_fetch_distinct_report_metric_names(blank_only) == []


def test_metric_names_sample_limit_semantics(tmp_path):
    db_path = str(tmp_path / 'limits.db')
    _create_measurement_export_db(db_path)

    def samples(limit):
        return {
            row['metric_name']: row['sample_references']
            for row in fetch_distinct_report_metric_names(db_path, sample_reference_limit=limit)
        }

    assert samples(0) == {'DIA': [], 'DIA - X': [], 'LENGTH - Y': []}
    assert samples(-1) == samples(None) == samples(0)
    assert samples(1)['DIA - X'] == ['REF-1']
    assert samples(2)['DIA - X'] == ['REF-1', 'REF-2']
    assert samples(1000)['DIA - X'] == ['REF-1', 'REF-2']
    # reference_count is independent of the sample limit
    assert {r['reference_count'] for r in fetch_distinct_report_metric_names(db_path, sample_reference_limit=0)} == {1, 2}


def test_metric_names_use_a_single_data_query_regardless_of_metric_count(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'single_query.db')
    _build_view_db(db_path, _random_rows(5))
    metric_queries = []
    real_execute = service_module.execute_with_retry

    def counting_execute(db, query, *args, **kwargs):
        if 'metric_source' in query:
            metric_queries.append(query)
        return real_execute(db, query, *args, **kwargs)

    monkeypatch.setattr(service_module, 'execute_with_retry', counting_execute)

    rows = fetch_distinct_report_metric_names(db_path)

    assert len(rows) > 20
    assert len(metric_queries) == 1


@pytest.mark.parametrize('version', [(3, 34, 9), (3, 35, 0), sqlite3.sqlite_version_info])
def test_metric_source_materialization_version_guard_preserves_ordered_results(tmp_path, monkeypatch, version):
    db_path = str(tmp_path / 'version_guard.db')
    _build_view_db(db_path, _TRICKY_ROWS)
    monkeypatch.setattr(service_module.sqlite3, 'sqlite_version_info', version)
    source_sql = service_module._measurement_source_sql(db_path)
    cte = service_module._metric_source_cte(source_sql)
    original = _original_metric_source_cte(source_sql)
    if version < (3, 35, 0):
        assert cte == original
    else:
        assert cte == original.replace('metric_source AS (', 'metric_source AS MATERIALIZED (')
        if _NATIVE_SQLITE_VERSION < (3, 35, 0):
            pytest.skip('Generated SQL checked; native SQLite cannot execute materialization hints before 3.35')
    _assert_equivalent(db_path)


def test_metric_names_materialized_plan_scans_measurement_source_once(tmp_path, monkeypatch):
    if _NATIVE_SQLITE_VERSION < (3, 35, 0):
        pytest.skip('SQLite materialization hints require 3.35+')
    db_path = str(tmp_path / 'materialized_plan.db')
    _build_view_db(db_path, _TRICKY_ROWS + _random_rows(13))
    metric_queries = []
    real_execute = service_module.execute_with_retry

    def capture_execute(db, query, *args, **kwargs):
        if 'ranked_references AS' in query:
            metric_queries.append(query)
        return real_execute(db, query, *args, **kwargs)

    monkeypatch.setattr(service_module, 'execute_with_retry', capture_execute)
    actual = fetch_distinct_report_metric_names(db_path)
    assert actual == _oracle_fetch_distinct_report_metric_names(db_path)
    assert len(metric_queries) == 1
    with closing(sqlite3.connect(db_path)) as connection:
        plan = connection.execute('EXPLAIN QUERY PLAN ' + metric_queries[0], (3,)).fetchall()
    details = [row[3].split() for row in plan]
    assert ['MATERIALIZE', 'metric_source'] in details, plan
    assert sum(tokens[:2] == ['SCAN', 'vw_measurement_export'] for tokens in details) == 1, plan
    assert sum(tokens[:2] == ['SCAN', 'metric_source'] for tokens in details) == 2, plan


@pytest.mark.parametrize('version', [(3, 34, 9), sqlite3.sqlite_version_info])
def test_metric_names_equivalent_on_unmigrated_legacy_fallback(tmp_path, monkeypatch, version):
    from metroliza.reports import report_schema

    db_path = str(tmp_path / 'legacy_fallback.db')
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute('CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE)')
        connection.execute('CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY, REPORT_ID INTEGER, HEADER, AX)')
        connection.executemany(
            'INSERT INTO REPORTS(ID, REFERENCE) VALUES (?, ?)',
            [(index + 1, row[0]) for index, row in enumerate(_TRICKY_ROWS)],
        )
        connection.executemany(
            'INSERT INTO MEASUREMENTS(ID, REPORT_ID, HEADER, AX) VALUES (?, ?, ?, ?)',
            [(index + 1, index + 1, row[1], row[2]) for index, row in enumerate(_TRICKY_ROWS)],
        )
    monkeypatch.setattr(report_schema, 'ensure_report_schema', lambda *args, **kwargs: None)
    monkeypatch.setattr(service_module.sqlite3, 'sqlite_version_info', version)
    assert 'FROM MEASUREMENTS' in service_module._measurement_source_sql(db_path)
    expected = _assert_equivalent(db_path)
    assert [row['metric_name'] for row in expected] == [
        'DIA - X', 'MIXED - CASE', 'Mixed - case', 'mixed - Case', 'NUM - Z', 'ONLY-NULL', 'UNI',
    ]
