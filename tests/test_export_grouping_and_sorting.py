import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import numpy as np
import pytest

from metroliza.analytics.row_table import RowTable
from metroliza.exporting import export_data_thread as export_module

from modules.export_data_thread import ExportDataThread  # noqa: E402
from modules.contracts import AppPaths, ExportOptions, ExportRequest  # noqa: E402
from modules.export_grouping_utils import (  # noqa: E402
    apply_group_assignments,
    prepare_grouping_dataframe,
    set_default_group_label,
)
from modules.chart_render_service import build_violin_payload_vectorized  # noqa: E402


def _sort_table(table, mode):
    owner = SimpleNamespace(
        selected_sorting_parameter=mode,
        _is_sample_sort_mode=ExportDataThread._is_sample_sort_mode,
    )
    return ExportDataThread._sort_header_group(owner, table)


@pytest.mark.parametrize('mode', ['sample', 'sample #', 'sample number', 'part #', 'part number', ' PART NUMBER '])
def test_header_sort_literal_sample_order_and_shallow_copy(mode):
    samples = ['10', '2', '1', '01', 'bad', '', None, float('nan'), '-0', '0', ' 2 ', '٢', '+inf', '-inf', '0.30000000000000004']
    cells = [[] for _ in samples]
    rows = tuple((index, value, 'invalid', cells[index]) for index, value in enumerate(samples))
    table = RowTable(rows, ('ID', 'SAMPLE_NUMBER', 'DATE', 'CELL'), 'Population')
    result = _sort_table(table, mode)
    expected = [8, 13, 9, 14, 3, 2, 0, 10, 1, 11, 12, 5, 4, 6, 7]
    assert result['ID'].tolist() == expected
    assert result.columns == ('ID', 'SAMPLE_NUMBER', 'DATE', 'CELL')
    assert result.default_group_label is None
    assert result is not table
    assert table.rows is rows
    assert table.default_group_label == 'Population'
    for row, index in zip(result.rows, expected):
        assert all(actual is original for actual, original in zip(row, rows[index]))
    result['ID'] = range(len(result))
    assert table.rows is rows


@pytest.mark.parametrize('mode', ['date', 'unknown', ''])
def test_header_sort_literal_date_order(mode):
    values = ['2024-01-02', '2024-01-01', 'bad', None, date(2024, 1, 2), datetime(2024, 1, 2), '', float('nan'), np.datetime64('2024-01-01')]
    samples = ['2', '10', 'z', '4', '1', '1', '6', '7', '2']
    rows = tuple((index, sample, value) for index, (sample, value) in enumerate(zip(samples, values)))
    table = RowTable(rows, ('ID', 'SAMPLE_NUMBER', 'DATE'), 'Population')
    result = _sort_table(table, mode)
    assert result['ID'].tolist() == [1, 8, 4, 5, 0, 3, 6, 7, 2]
    assert result.default_group_label is None
    assert table.rows is rows
    for row in result.rows:
        assert all(value is original for value, original in zip(row, rows[row[0]]))


@pytest.mark.parametrize('mode,rows,expected', [
    ('sample', (), []),
    ('date', (), []),
    ('sample', ((0, '1', 'bad'),), [0]),
    ('date', ((0, '1', '2024-01-01'),), [0]),
    ('sample', ((0, 'β', 'x'), (1, '', 'x'), (2, 'x', 'x'), (3, None, 'x'), (4, float('nan'), 'x')), [1, 2, 0, 3, 4]),
    ('date', ((0, '2', 'β'), (1, '1', ''), (2, '1', None), (3, '1', float('nan')), (4, '2', '')), [1, 4, 0, 2, 3]),
    ('sample', ((0, -0.0, 'x'), (1, 0.0, 'x'), (2, '0', 'x'), (3, '-0', 'x')), [3, 0, 2, 1]),
])
def test_header_sort_literal_edges(mode, rows, expected):
    table = RowTable(rows, ('ID', 'SAMPLE_NUMBER', 'DATE'), 'Population')
    result = _sort_table(table, mode)
    assert result['ID'].tolist() == expected
    assert result.columns == table.columns
    assert result.default_group_label is None
    assert table.rows is rows


@pytest.mark.parametrize('mode,helper,values,expected', [
    ('sample', '_sample_numeric', ['2', '1'], ('SAMPLE_NUMBER', 'DATE')),
    ('sample', '_sample_numeric', ['bad', ''], ('SAMPLE_NUMBER', 'DATE', '_sample_numeric')),
    ('date', '_date_sort', ['2024-01-02', '2024-01-01'], ('SAMPLE_NUMBER', 'DATE')),
    ('date', '_date_sort', ['bad', ''], ('SAMPLE_NUMBER', 'DATE', '_date_sort')),
])
def test_header_sort_preexisting_helper_column_contract(mode, helper, values, expected):
    rows = tuple((value if mode == 'sample' else str(index), value if mode == 'date' else 'x', index) for index, value in enumerate(values))
    table = RowTable(rows, ('SAMPLE_NUMBER', 'DATE', helper), 'Population')
    result = _sort_table(table, mode)
    assert result.columns == expected
    assert result.default_group_label is None
    assert table.rows is rows
    assert table.columns == ('SAMPLE_NUMBER', 'DATE', helper)


@pytest.mark.parametrize('mode,rows,columns,error,message', [
    ('sample', (), ('DATE',), ValueError, 'tuple.index(x): x not in tuple'),
    ('date', (), ('SAMPLE_NUMBER',), ValueError, 'tuple.index(x): x not in tuple'),
    ('date', (('2024-01-01',),), ('DATE',), ValueError, 'tuple.index(x): x not in tuple'),
    ('sample', ((),), ('SAMPLE_NUMBER',), IndexError, 'tuple index out of range'),
])
def test_header_sort_errors(mode, rows, columns, error, message):
    table = RowTable(rows, columns)
    with pytest.raises(error) as caught:
        _sort_table(table, mode)
    assert str(caught.value) == message
    assert table.rows is rows


def test_header_sort_unsupported_date_objects_do_not_hash_or_compare():
    class UnhashableString(str):
        __hash__ = None

        def __eq__(self, other):
            raise AssertionError('date equality callback')

    class DateObject:
        __hash__ = None

        def __ne__(self, other):
            return False

        def __str__(self):
            return '2024-01-01'

        def __eq__(self, other):
            raise AssertionError('date equality callback')

    values = [UnhashableString('2024-01-02'), DateObject(), ['invalid']]
    table = RowTable(tuple((str(index), value) for index, value in enumerate(values)), ('SAMPLE_NUMBER', 'DATE'))
    result = _sort_table(table, 'date')
    assert result['SAMPLE_NUMBER'].tolist() == ['1', '0', '2']
    assert result.rows[0][1] is values[1]


def test_header_sort_work_count_avoids_full_width_helper_rows():
    table = RowTable((('2', '2024-01-02'), ('1', '2024-01-01')), ('SAMPLE_NUMBER', 'DATE'))
    with patch.object(RowTable, 'copy', side_effect=AssertionError('full-width copy')), patch.object(RowTable, 'assign', side_effect=AssertionError('helper assign')), patch.object(RowTable, 'drop', side_effect=AssertionError('helper drop')):
        assert _sort_table(table, 'sample')['SAMPLE_NUMBER'].tolist() == ['1', '2']
        assert _sort_table(table, 'date')['SAMPLE_NUMBER'].tolist() == ['1', '2']


def test_header_sort_work_count_caches_exact_date_strings_per_call():
    table = RowTable((('2', '2024-01-02'), ('1', '2024-01-01'), ('0', '2024-01-02'), ('3', 'invalid'), ('4', 'invalid')), ('SAMPLE_NUMBER', 'DATE'))
    with patch.object(export_module, '_coerce_datetime_or_none', wraps=export_module._coerce_datetime_or_none) as parse:
        _sort_table(table, 'date')
        assert parse.call_count == 3
        table['DATE'] = ['2025-01-01'] * 5
        _sort_table(table, 'date')
        assert parse.call_count == 4


def test_row_table_take_rows_preserves_selection_and_shallow_cells():
    cells = [[], {}]
    table = RowTable((('a', cells[0]), ('b', cells[1])), ('LABEL', 'CELL'), 'Population')
    result = table.take_rows(iter([1, 0, 1, -1]))
    assert result.columns == ('LABEL', 'CELL')
    assert result['LABEL'].tolist() == ['b', 'a', 'b', 'b']
    assert result.default_group_label is None
    assert result.rows[0][1] is cells[1]
    assert result.rows[1][1] is cells[0]
    result['LABEL'] = ['x'] * 4
    assert table['LABEL'].tolist() == ['a', 'b']
    result.rows[1][1].append('shared')
    assert cells[0] == ['shared']
    assert table.take_rows([]).rows == ()
    with pytest.raises(IndexError, match='tuple index out of range'):
        table.take_rows([2])


def test_row_table_sort_indices_uses_existing_comparator_and_stability():
    table = RowTable(((0, 'β'), (1, ''), (2, None), (3, float('nan')), (4, 'β')), ('ID', 'VALUE'), 'Population')
    expected = [1, 0, 4, 2, 3]
    assert table._sort_indices((table['VALUE'],)) == expected
    assert table.sort_values('VALUE')['ID'].tolist() == expected
    assert table.sort_values('VALUE', key=lambda values: ['same'] * len(values))['ID'].tolist() == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError, match='sort key must preserve row count'):
        table.sort_values('VALUE', key=lambda values: [])
    # The independent iloc contract remains unchanged, including coercion of
    # iterable indices and its preexisting metadata behavior.
    assert table.iloc[['1', -1]]['ID'].tolist() == [1, 4]
    assert table.iloc[:1].default_group_label is None


@pytest.mark.parametrize('method_names', [('take_rows',), ('_sort_indices',), ('take_rows', '_sort_indices')])
def test_row_table_sort_values_ignores_preexisting_subclass_helper_names(method_names):
    callbacks = []

    def existing_method(self, *args, **kwargs):
        callbacks.append('unexpected helper dispatch')
        raise RuntimeError('preexisting subclass helper invoked')

    derived = type('ExistingDerivedTable', (RowTable,), dict.fromkeys(method_names, existing_method))
    cells = [[] for _ in range(5)]
    rows = ((2, 'b', cells[0]), (1, 'a', cells[1]), (0, None, cells[2]), (10, 'b', cells[3]), (3, 'b', cells[4]))
    table = derived(rows, ('ID', 'VALUE', 'CELL'), 'Population')
    key_calls = []

    def key(values):
        key_calls.append(tuple(values))
        return values

    result = table.sort_values(['VALUE', 'ID'], key=key)
    assert callbacks == []
    assert key_calls == [('b', 'a', None, 'b', 'b'), (2, 1, 0, 10, 3)]
    assert type(result) is RowTable
    assert result['ID'].tolist() == [1, 10, 2, 3, 0]
    assert result.columns == ('ID', 'VALUE', 'CELL')
    assert result.default_group_label is None
    assert table.rows is rows
    assert table.default_group_label == 'Population'
    for result_row, index in zip(result.rows, [1, 3, 0, 4, 2]):
        assert all(value is original for value, original in zip(result_row, rows[index]))
    result['ID'] = range(5)
    assert table.rows is rows


@pytest.mark.parametrize('failure', ['missing column', 'short key', 'raising key'])
def test_row_table_sort_values_keeps_key_callback_and_error_order(failure):
    calls = []
    table = RowTable(((2, 'b'), (1, 'a')), ('ID', 'VALUE'), 'Population')

    def key(values):
        calls.append(tuple(values))
        if failure == 'raising key':
            raise RuntimeError('key failure')
        return []

    error = RuntimeError if failure == 'raising key' else ValueError
    with pytest.raises(error) as caught:
        table.sort_values(['VALUE', 'MISSING'] if failure == 'missing column' else ['VALUE', 'ID'], key=key)
    assert str(caught.value) == {
        'missing column': 'tuple.index(x): x not in tuple',
        'short key': 'sort key must preserve row count',
        'raising key': 'key failure',
    }[failure]
    assert calls == ([] if failure == 'missing column' else [('b', 'a')])
    assert table.rows == ((2, 'b'), (1, 'a'))
    assert table.default_group_label == 'Population'


def test_header_sort_subclasses_and_noncanonical_layouts_use_fallback():
    class CustomTable(RowTable):
        pass

    tables = [
        CustomTable((('2', '2024-01-02'), ('1', '2024-01-01')), ('SAMPLE_NUMBER', 'DATE')),
        RowTable((('2', '2024-01-02', 'extra'), ('1', '2024-01-01', 'extra')), ('SAMPLE_NUMBER', 'DATE')),
        RowTable((('2', '2024-01-02'), ('1', '2024-01-01')), ['SAMPLE_NUMBER', 'DATE']),
        RowTable((('2', '2024-01-02', 'old'), ('1', '2024-01-01', 'old')), ('SAMPLE_NUMBER', 'DATE', '_sample_numeric')),
        RowTable((('2', '2024-01-02', 'old'), ('1', '2024-01-01', 'old')), ('SAMPLE_NUMBER', 'DATE', '_date_sort')),
        RowTable((('2', '2024-01-02', 'unused'), ('1', '2024-01-01', 'unused')), ('SAMPLE_NUMBER', 'DATE', 'DATE')),
    ]
    with patch.object(export_module, '_sort_header_row_table', side_effect=AssertionError('fast path')):
        for table in tables:
            for mode in ['sample', 'date']:
                assert _sort_table(table, mode)['SAMPLE_NUMBER'].tolist() == ['1', '2']


def test_header_sort_pandas_uses_unchanged_fallback():
    table = pd.DataFrame({'SAMPLE_NUMBER': ['10', '2', '1'], 'DATE': ['2024-01-02', '2024-01-01', '2024-01-02']}, index=[4, 2, 8])
    before = table.copy(deep=True)
    with patch.object(export_module, '_sort_header_row_table', side_effect=AssertionError('fast path')):
        sample_result = _sort_table(table, 'sample')
        date_result = _sort_table(table, 'date')
    pd.testing.assert_frame_equal(sample_result, before.loc[[8, 2, 4]])
    pd.testing.assert_frame_equal(date_result, before.loc[[2, 8, 4]])
    pd.testing.assert_frame_equal(table, before)


def test_header_date_cache_keeps_subclass_and_object_callback_counts():
    class DateString(str):
        __hash__ = None

        def __eq__(self, other):
            raise AssertionError('new equality callback')

    value = DateString('2024-01-01')
    table = RowTable((('1', value), ('2', value)), ('SAMPLE_NUMBER', 'DATE'))
    with patch.object(export_module, '_coerce_datetime_or_none', wraps=export_module._coerce_datetime_or_none) as parse:
        result = _sort_table(table, 'date')
    assert parse.call_count == 2
    assert result.rows[0][1] is value
    assert result.rows[1][1] is value


class TestExportSortingAndGrouping(unittest.TestCase):

    def test_prepare_grouping_dataframe_returns_none_for_missing_group_column(self):
        grouping_df = pd.DataFrame({'REFERENCE': ['R1']})

        prepared = prepare_grouping_dataframe(grouping_df)

        self.assertIsNone(prepared)


    def test_prepare_grouping_dataframe_keeps_group_color_column(self):
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'GROUP': ['G1'],
                'GROUP_COLOR': ['#FDE2E4'],
            }
        )

        prepared = prepare_grouping_dataframe(grouping_df)

        self.assertIn('GROUP_COLOR', prepared.columns)
        self.assertEqual(prepared['GROUP_COLOR'].iloc[0], '#FDE2E4')


    def test_apply_group_assignments_uses_ungrouped_fallback_by_default(self):
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'GROUP': [None],
            }
        )
        grouping_df = prepare_grouping_dataframe(grouping_df)

        merged, applied, _, _ = apply_group_assignments(header_group, grouping_df)

        self.assertTrue(applied)
        self.assertEqual(merged['GROUP'].tolist(), ['UNGROUPED'])


    def test_apply_group_assignments_group_analysis_path_uses_population_fallback(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'GROUP': ['   '],
            }
        )
        grouping_df = prepare_grouping_dataframe(grouping_df)

        merged, applied = thread._apply_group_assignments(
            header_group,
            grouping_df,
            group_analysis_mode=True,
            fallback_group_label='POPULATION',
        )

        self.assertTrue(applied)
        self.assertEqual(merged['GROUP'].tolist(), ['POPULATION'])

    def test_apply_group_assignments_can_use_population_fallback_for_summary_charts(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1, 2],
                'REFERENCE': ['R1', 'R1'],
                'DATE': ['2024-01-01', '2024-01-01'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [1.0, 1.2],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'GROUP': ['A'],
            }
        )
        grouping_df = prepare_grouping_dataframe(grouping_df)

        merged, applied = thread._apply_group_assignments(
            header_group,
            grouping_df,
            fallback_group_label='POPULATION',
        )

        self.assertTrue(applied)
        self.assertEqual(merged['GROUP'].tolist(), ['A', 'POPULATION'])

    def test_apply_group_assignments_group_analysis_uses_grouping_default_label_attr(self):
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'GROUP': ['   '],
            }
        )
        set_default_group_label(grouping_df, 'All Samples')
        grouping_df = prepare_grouping_dataframe(grouping_df)

        merged, applied, _, _ = apply_group_assignments(
            header_group,
            grouping_df,
            group_analysis_mode=True,
        )

        self.assertTrue(applied)
        self.assertEqual(merged['GROUP'].tolist(), ['All Samples'])

    def test_apply_group_assignments_returns_contract_metadata(self):
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'GROUP': ['G1'],
                'GROUP_COLOR': ['#FDE2E4'],
            }
        )
        grouping_df = prepare_grouping_dataframe(grouping_df)

        merged, applied, merge_keys, duplicate_count = apply_group_assignments(header_group, grouping_df)

        self.assertTrue(applied)
        self.assertEqual(merge_keys, ['GROUP_KEY'])
        self.assertEqual(duplicate_count, 0)
        self.assertEqual(merged['GROUP'].tolist(), ['G1'])
        self.assertEqual(merged['GROUP_COLOR'].tolist(), ['#FDE2E4'])

    def test_apply_group_assignments_matches_integer_like_report_id_variants(self):
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1, 2],
                'REFERENCE': ['R1', 'R1'],
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['1', '2'],
                'MEAS': [1.0, 2.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1.0, '2.0'],
                'GROUP': ['A', 'B'],
            }
        )
        grouping_df = prepare_grouping_dataframe(grouping_df)

        merged, applied, merge_keys, duplicate_count = apply_group_assignments(header_group, grouping_df)

        self.assertTrue(applied)
        self.assertEqual(merge_keys, ['GROUP_KEY'])
        self.assertEqual(duplicate_count, 0)
        self.assertEqual(merged['GROUP'].tolist(), ['A', 'B'])

    def test_apply_group_assignments_returns_false_when_grouping_is_missing(self):
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )

        merged, applied, merge_keys, duplicate_count = apply_group_assignments(header_group, None)

        self.assertFalse(applied)
        self.assertIsNone(merge_keys)
        self.assertEqual(duplicate_count, 0)
        self.assertEqual(merged['REPORT_ID'].tolist(), [1])
        self.assertNotIn('GROUP_KEY', merged.columns)
        self.assertNotIn('GROUP', merged.columns)

    def test_apply_group_assignments_returns_false_when_no_merge_key_is_usable(self):
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = prepare_grouping_dataframe(
            pd.DataFrame(
                {
                    'GROUP': ['G1'],
                }
            )
        )

        merged, applied, merge_keys, duplicate_count = apply_group_assignments(header_group, grouping_df)

        self.assertFalse(applied)
        self.assertIsNone(merge_keys)
        self.assertEqual(duplicate_count, 0)
        self.assertEqual(merged['REPORT_ID'].tolist(), [1])
        self.assertIn('GROUP_KEY', merged.columns)
        self.assertNotIn('GROUP', merged.columns)

    def test_apply_group_assignments_returns_false_when_no_rows_match_grouping(self):
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = prepare_grouping_dataframe(
            pd.DataFrame(
                {
                    'REPORT_ID': [999],
                    'GROUP': ['G1'],
                }
            )
        )

        merged, applied, merge_keys, duplicate_count = apply_group_assignments(header_group, grouping_df)

        self.assertFalse(applied)
        self.assertEqual(merge_keys, ['GROUP_KEY'])
        self.assertEqual(duplicate_count, 0)
        self.assertEqual(merged['GROUP'].tolist(), ['UNGROUPED'])

    def test_constructor_accepts_export_request_contract(self):
        request = ExportRequest(
            paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'),
            options=ExportOptions(export_type='LINE', sorting_parameter='Sample #', violin_plot_min_samplesize=1),
        )

        thread = ExportDataThread(export_request=request)

        self.assertEqual(thread.db_file, ':memory:')
        self.assertEqual(thread.selected_export_type, 'line')
        self.assertEqual(thread.selected_sorting_parameter, 'sample #')
        self.assertEqual(thread.violin_plot_min_samplesize, 2)
    def test_sort_by_sample_number_uses_numeric_order(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions(sorting_parameter='Part number')))
        header_group = pd.DataFrame(
            {
                'SAMPLE_NUMBER': ['10', '2', '1'],
                'DATE': ['2024-01-03', '2024-01-02', '2024-01-01'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        sorted_group = thread._sort_header_group(header_group)

        self.assertEqual(sorted_group['SAMPLE_NUMBER'].tolist(), ['1', '2', '10'])

    def test_sort_by_date_falls_back_to_sample_for_ties(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions(sorting_parameter='Date')))
        header_group = pd.DataFrame(
            {
                'SAMPLE_NUMBER': ['2', '1', '3'],
                'DATE': ['2024-01-02', '2024-01-02', '2024-01-01'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        sorted_group = thread._sort_header_group(header_group)

        self.assertEqual(sorted_group['SAMPLE_NUMBER'].tolist(), ['3', '1', '2'])

    def test_prepare_grouping_df_adds_group_key_for_report_id_identity(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        thread.df_for_grouping = pd.DataFrame(
            {
                'REPORT_ID': [10, 10],
                'REFERENCE': ['R1', 'R2'],
                'DATE': ['2024-01-01', '2024-01-02'],
                'SAMPLE_NUMBER': ['001', '999'],
                'GROUP': ['A', 'B'],
            }
        )

        grouping_df = thread._prepare_grouping_df()

        self.assertIn('GROUP_KEY', grouping_df.columns)
        self.assertEqual(len(grouping_df), 2)
        self.assertEqual(grouping_df['GROUP_KEY'].iloc[0], grouping_df['GROUP_KEY'].iloc[1])

    def test_resolve_group_merge_keys_prefers_group_key_then_report_id(self):
        header_with_group_key = pd.DataFrame({'GROUP_KEY': ['abc'], 'REFERENCE': ['R1']})
        grouping_with_group_key = pd.DataFrame({'GROUP_KEY': ['abc'], 'GROUP': ['G1']})
        self.assertEqual(ExportDataThread._resolve_group_merge_keys(header_with_group_key, grouping_with_group_key), ['GROUP_KEY'])

        header_with_id = pd.DataFrame({'REPORT_ID': [1], 'REFERENCE': ['R1'], 'SAMPLE_NUMBER': ['1']})
        grouping_with_id = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['G1']})
        self.assertEqual(ExportDataThread._resolve_group_merge_keys(header_with_id, grouping_with_id), ['REPORT_ID'])


    def test_resolve_group_merge_keys_skips_blank_group_key_and_uses_report_id(self):
        header_group = pd.DataFrame({'GROUP_KEY': [''], 'REPORT_ID': [10], 'REFERENCE': ['R1'], 'SAMPLE_NUMBER': ['1']})
        grouping_df = pd.DataFrame({'GROUP_KEY': [''], 'REPORT_ID': [10], 'GROUP': ['A']})

        keys = ExportDataThread._resolve_group_merge_keys(header_group, grouping_df)

        self.assertEqual(keys, ['REPORT_ID'])

    def test_resolve_group_merge_keys_skips_blank_report_id_and_returns_none(self):
        header_group = pd.DataFrame({
            'REPORT_ID': [np.nan],
            'REFERENCE': ['R1'],
            'DATE': ['2024-01-01'],
            'SAMPLE_NUMBER': ['1'],
        })
        grouping_df = pd.DataFrame({
            'REPORT_ID': [None],
            'GROUP': ['A'],
        })

        keys = ExportDataThread._resolve_group_merge_keys(header_group, grouping_df)

        self.assertIsNone(keys)

    def test_build_violin_payload_drops_nan_and_empty_groups(self):
        header_group = pd.DataFrame(
            {
                'GROUP': ['A', 'A', 'B', 'C'],
                'MEAS': [1.0, float('nan'), float('nan'), 2.0],
            }
        )

        labels, values, can_render = build_violin_payload_vectorized(
            header_group,
            'GROUP',
            min_samplesize=1,
        )

        self.assertEqual(labels, ['A', 'C'])
        self.assertEqual(values, [[1.0], [2.0]])
        self.assertTrue(can_render)


    def test_build_violin_payload_preserves_input_group_order(self):
        header_group = pd.DataFrame(
            {
                'GROUP': ['B', 'A', 'B', 'A'],
                'MEAS': [1.0, 2.0, 1.1, 2.1],
            }
        )

        labels, values, can_render = build_violin_payload_vectorized(
            header_group,
            'GROUP',
            min_samplesize=1,
        )

        self.assertEqual(labels, ['B', 'A'])
        self.assertEqual(values, [[1.0, 1.1], [2.0, 2.1]])
        self.assertTrue(can_render)

    def test_build_violin_payload_honors_minimum_sample_size(self):
        header_group = pd.DataFrame(
            {
                'SAMPLE_NUMBER': ['1', '1', '2'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        labels, values, can_render = build_violin_payload_vectorized(
            header_group,
            'SAMPLE_NUMBER',
            min_samplesize=2,
        )

        self.assertEqual(labels, ['1', '2'])
        self.assertEqual(values, [[1.0, 1.1], [0.9]])
        self.assertFalse(can_render)

    def test_build_summary_scatter_payload_uses_positional_x_for_string_groups(self):
        header_group = pd.DataFrame(
            {
                'GROUP': ['A', 'A', 'B'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        x_values, y_values, labels = ExportDataThread._build_summary_scatter_payload(header_group, 'GROUP')

        self.assertTrue(np.issubdtype(x_values.dtype, np.number))
        self.assertEqual(x_values.tolist(), [0.0, 1.0, 2.0])
        self.assertEqual(y_values.tolist(), [1.0, 1.1, 0.9])
        self.assertEqual(labels, ['A', '', 'B'])

    def test_build_summary_scatter_payload_preserves_numeric_sample_positions(self):
        header_group = pd.DataFrame(
            {
                'SAMPLE_NUMBER': ['10', '11', '12'],
                'MEAS': [1.0, 1.1, 0.9],
            }
        )

        x_values, y_values, labels = ExportDataThread._build_summary_scatter_payload(header_group, 'SAMPLE_NUMBER')

        self.assertTrue(np.issubdtype(x_values.dtype, np.number))
        self.assertEqual(x_values.tolist(), [10.0, 11.0, 12.0])
        self.assertEqual(y_values.tolist(), [1.0, 1.1, 0.9])
        self.assertEqual(labels, ['10', '11', '12'])

    def test_prepared_grouping_df_is_cached_per_export_thread_instance(self):
        thread = ExportDataThread(
            export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions())
        )
        thread.df_for_grouping = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'GROUP': ['A'],
            }
        )

        with patch.object(thread, '_prepare_grouping_df', wraps=thread._prepare_grouping_df) as prepare_mock:
            first = thread.prepared_grouping_df
            second = thread.prepared_grouping_df

        self.assertIs(first, second)
        self.assertEqual(prepare_mock.call_count, 1)

    def test_apply_group_assignments_keeps_latest_duplicate_assignment(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'DATE': ['2024-01-01'],
                'SAMPLE_NUMBER': ['1'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1, 1],
                'GROUP': ['OLD_GROUP', 'NEW_GROUP'],
            }
        )
        grouping_df = thread._add_group_key(grouping_df)

        with patch('modules.export_data_thread.logger.warning') as warning_mock:
            merged, applied = thread._apply_group_assignments(header_group, grouping_df)

        self.assertTrue(applied)
        self.assertEqual(merged['GROUP'].tolist(), ['NEW_GROUP'])
        warning_mock.assert_called_once()

    def test_apply_group_assignments_with_report_id_preserves_sample_number_column(self):
        thread = ExportDataThread(export_request=ExportRequest(paths=AppPaths(db_file=':memory:', excel_file='dummy.xlsx'), options=ExportOptions()))
        header_group = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'REFERENCE': ['R1'],
                'SAMPLE_NUMBER': ['7'],
                'MEAS': [1.0],
            }
        )
        grouping_df = pd.DataFrame(
            {
                'REPORT_ID': [1],
                'SAMPLE_NUMBER': ['999'],
                'GROUP': ['A'],
            }
        )

        merged, applied = thread._apply_group_assignments(header_group, grouping_df)

        self.assertTrue(applied)
        self.assertIn('SAMPLE_NUMBER', merged.columns)
        self.assertNotIn('SAMPLE_NUMBER_x', merged.columns)
        self.assertNotIn('SAMPLE_NUMBER_y', merged.columns)
        self.assertEqual(merged['SAMPLE_NUMBER'].tolist(), ['7'])


if __name__ == '__main__':
    unittest.main()
