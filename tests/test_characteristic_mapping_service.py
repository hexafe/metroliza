import sqlite3

import pytest

from modules.characteristic_mapping_service import (
    fetch_distinct_references,
    fetch_distinct_report_metric_names,
    fetch_mapping_impact_counts,
)


def _create_measurement_export_db(db_path):
    with sqlite3.connect(db_path) as connection:
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
    with sqlite3.connect(db_path) as connection:
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
    with sqlite3.connect(db_path) as connection:
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
    with sqlite3.connect(db_path) as connection:
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
