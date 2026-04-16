import sqlite3

import pandas as pd

from modules.data_grouping_service import (
    build_grouping_query,
    compute_group_key_for_df,
    load_grouping_dataframe,
    reassign_group_keys_to_default,
)


def test_build_grouping_query_defaults_without_filter():
    query = build_grouping_query(None)

    assert 'FROM vw_grouping_reports' in query
    assert 'report_id AS REPORT_ID' in query


def test_load_grouping_dataframe_delegates_to_reader():
    calls = {}

    def _reader(db_file, query):
        calls['db_file'] = db_file
        calls['query'] = query
        return pd.DataFrame({'REPORT_ID': []})

    frame = load_grouping_dataframe(_reader, 'db.sqlite', 'SELECT * FROM REPORTS WHERE 1=1')

    assert isinstance(frame, pd.DataFrame)
    assert calls['db_file'] == 'db.sqlite'
    assert 'filtered_data' in calls['query']


def test_build_grouping_query_strips_trailing_semicolons_from_filter_query():
    connection = sqlite3.connect(':memory:')
    connection.execute(
        'CREATE TABLE vw_grouping_reports (report_id integer, reference text, report_date text, sample_number text, part_name text, revision text, template_variant text, has_nok integer, nok_count integer, file_name text)'
    )

    query = build_grouping_query(
        'SELECT report_id, reference, report_date, sample_number, part_name, revision, template_variant, has_nok, nok_count, file_name '
        'FROM vw_grouping_reports;  '
    )
    rows = connection.execute(query).fetchall()

    assert rows == []
    assert 'FROM vw_grouping_reports;' not in query



def test_compute_group_key_for_df_is_stable():
    df = pd.DataFrame([
        {'REPORT_ID': 1, 'REFERENCE': 'R1', 'DATE': '2024-01-01', 'SAMPLE_NUMBER': '1'},
        {'REPORT_ID': 1, 'REFERENCE': 'R2', 'DATE': '2024-01-02', 'SAMPLE_NUMBER': '99'},
    ])

    keys = compute_group_key_for_df(df)

    assert keys.iloc[0] == keys.iloc[1]


def test_compute_group_key_for_df_avoids_delimiter_collisions():
    df = pd.DataFrame([
        {'REPORT_ID': 1, 'REFERENCE': 'A|B', 'DATE': '2024-01-01', 'SAMPLE_NUMBER': '1'},
        {'REPORT_ID': 2, 'REFERENCE': 'A', 'DATE': '2024-01-01', 'SAMPLE_NUMBER': '1'},
    ])

    keys = compute_group_key_for_df(df)

    assert keys.iloc[0] != keys.iloc[1]


def test_reassign_group_keys_to_default_updates_only_selected_custom_rows():
    df = pd.DataFrame(
        [
            {'GROUP': 'CUSTOM', 'GROUP_KEY': 'a', 'GROUP_COLOR': '#ABCDEF'},
            {'GROUP': 'CUSTOM', 'GROUP_KEY': 'b', 'GROUP_COLOR': '#ABCDEF'},
            {'GROUP': 'POPULATION', 'GROUP_KEY': 'c', 'GROUP_COLOR': '#FFFFFF'},
        ]
    )

    changed = reassign_group_keys_to_default(
        df,
        selected_part_keys=['b', 'c'],
        default_group='POPULATION',
        group_color_column='GROUP_COLOR',
        default_group_color='#FFFFFF',
    )

    assert changed
    assert df.loc[df['GROUP_KEY'] == 'b', 'GROUP'].iloc[0] == 'POPULATION'
    assert df.loc[df['GROUP_KEY'] == 'a', 'GROUP'].iloc[0] == 'CUSTOM'
