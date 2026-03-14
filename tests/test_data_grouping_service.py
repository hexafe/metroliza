import pandas as pd

from modules.data_grouping_service import (
    build_grouping_query,
    compute_group_key_for_df,
    load_grouping_dataframe,
    reassign_group_keys_to_default,
)


def test_build_grouping_query_defaults_without_filter():
    query = build_grouping_query(None)

    assert 'FROM REPORTS' in query


def test_load_grouping_dataframe_delegates_to_reader():
    calls = {}

    def _reader(db_file, query):
        calls['db_file'] = db_file
        calls['query'] = query
        return pd.DataFrame({'REFERENCE': []})

    frame = load_grouping_dataframe(_reader, 'db.sqlite', 'SELECT * FROM REPORTS WHERE 1=1')

    assert isinstance(frame, pd.DataFrame)
    assert calls['db_file'] == 'db.sqlite'
    assert 'FILTERED_DATA' in calls['query']


def test_compute_group_key_for_df_is_stable():
    df = pd.DataFrame([
        {'REFERENCE': 'R1', 'FILELOC': 'a', 'FILENAME': 'f1', 'DATE': '2024-01-01', 'SAMPLE_NUMBER': '1'},
        {'REFERENCE': 'R1', 'FILELOC': 'a', 'FILENAME': 'f1', 'DATE': '2024-01-01', 'SAMPLE_NUMBER': '1'},
    ])

    keys = compute_group_key_for_df(df)

    assert keys.iloc[0] == keys.iloc[1]


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
