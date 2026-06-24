import sqlite3

import pandas as pd

from modules.data_grouping_service import (
    build_grouping_query,
    build_grouping_scope_query_from_filter_state,
    build_grouping_row_index,
    compute_group_key_for_df,
    load_grouping_dataframe,
    reassign_group_keys_to_default,
)
from modules.filter_state import FilterState


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


def test_build_grouping_scope_query_uses_report_scope_for_reference_and_part_filters():
    query = build_grouping_scope_query_from_filter_state(
        FilterState(
            ax_values=("AX1",),
            reference_values=("REF-1",),
            part_name_values=("Part A",),
            has_nok_only=True,
            date_from="2026-05-01",
        )
    )

    assert query is not None
    assert "FROM vw_measurement_export" in query
    assert "reference IN ('REF-1')" in query
    assert "ax IN ('AX1')" in query
    assert "part_name IN ('Part A')" in query
    assert "has_nok = 1" in query
    assert "report_date >= '2026-05-01'" in query


def test_build_grouping_scope_query_returns_none_without_reference_or_part_filters():
    assert build_grouping_scope_query_from_filter_state(FilterState()) is None


def test_build_grouping_scope_query_keeps_light_report_scope_for_reference_only():
    query = build_grouping_scope_query_from_filter_state(
        FilterState(reference_values=("REF-1",), part_name_values=("Part A",))
    )

    assert query is not None
    assert "FROM vw_grouping_reports" in query
    assert "reference IN ('REF-1')" in query
    assert "part_name IN ('Part A')" in query
    assert "vw_measurement_export" not in query


def test_build_grouping_scope_query_uses_measurement_scope_for_header_expression():
    query = build_grouping_scope_query_from_filter_state(
        FilterState(header_values=("VAL1",), expression_text="Reference=REF1")
    )

    assert query is not None
    assert "FROM (" in query
    assert "vw_measurement_export" in query
    assert "header IN ('VAL1')" in query
    assert 'LOWER(CAST("reference" AS TEXT)) = LOWER(' in query


def test_build_grouping_scope_query_does_not_ignore_revision_filters():
    query = build_grouping_scope_query_from_filter_state(FilterState(revision_values=("B",)))

    assert query is not None
    assert "vw_measurement_export" in query
    assert "revision IN ('B')" in query



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


def test_build_grouping_row_index_groups_duplicate_keys_with_counts():
    df = pd.DataFrame(
        [
            {
                "REPORT_ID": 1,
                "REFERENCE": "REF-1",
                "SAMPLE_NUMBER": "A",
                "GROUP_KEY": "k1",
                "GROUP": "POPULATION",
                "GROUP_COLOR": "#FFFFFF",
                "FILENAME": "a.csv",
            },
            {
                "REPORT_ID": 1,
                "REFERENCE": "REF-1",
                "SAMPLE_NUMBER": "A",
                "GROUP_KEY": "k1",
                "GROUP": "POPULATION",
                "GROUP_COLOR": "#FFFFFF",
                "FILENAME": "a.csv",
            },
            {
                "REPORT_ID": 2,
                "REFERENCE": "REF-2",
                "SAMPLE_NUMBER": "B",
                "GROUP_KEY": "k2",
                "GROUP": "CUSTOM",
                "GROUP_COLOR": "#ABCDEF",
                "FILENAME": "b.csv",
            },
        ]
    )

    indexed = build_grouping_row_index(df)

    assert indexed["GROUP_KEY"].tolist() == ["k1", "k2"]
    assert indexed["ROW_COUNT"].tolist() == [2, 1]
    assert indexed.loc[indexed["GROUP_KEY"] == "k1", "REFERENCE"].iloc[0] == "REF-1"
    assert len(df.index) == 3


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
