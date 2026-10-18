"""Full-data numerical and XLSX equivalence for the #1128 export fast paths."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
import zipfile

from matplotlib import cbook
import matplotlib.pyplot as plt
import numpy as np
import openpyxl
import pandas as pd
import pytest

from metroliza.charts.full_data_violin import full_data_violin
from metroliza.exporting.xlsx_writer_policy import pandas_xlsxwriter_engine_kwargs
from metroliza.tabular.tabular_xlsx_writer import write_tabular_dataframe


@pytest.mark.parametrize('values', [
    np.arange(3.0), np.arange(150.0),
    np.random.default_rng(1128).normal(size=10001),
    np.array([-1e6, *np.zeros(200), 1e6]), np.ones(12),
    np.array([4.0]), np.array([np.nan, 1.0, 2.0, np.inf, 4.0]),
])
def test_violin_retains_full_density_vertices_and_statistics(values):
    """Every coordinate and summary statistic matches Matplotlib's full data KDE."""
    from metroliza.charts.full_data_violin import _univariate_density

    def reference(data, coords):
        from matplotlib.mlab import GaussianKDE
        if np.all(data[0] == data):
            return (data[0] == coords).astype(float)
        return GaussianKDE(data).evaluate(coords)

    expected = cbook.violin_stats([values], reference)
    actual = cbook.violin_stats([values], _univariate_density)
    assert expected[0].keys() == actual[0].keys()
    for key in expected[0]:
        np.testing.assert_array_equal(actual[0][key], expected[0][key], err_msg=key)


def test_violin_png_is_identical_to_matplotlib_full_data_render():
    values = [np.random.default_rng(1128).normal(size=211), np.ones(40)]
    images = []
    for renderer in (lambda ax, data, **kw: ax.violinplot(data, **kw), full_data_violin):
        fig, ax = plt.subplots()
        try:
            renderer(ax, values, positions=[1, 2], showmedians=True, showextrema=False)
            image = BytesIO()
            fig.savefig(image, format='png')
            images.append(image.getvalue())
        finally:
            plt.close(fig)
    assert images[0] == images[1]


def _frame_cases():
    yield pd.DataFrame({
        '=header': ['=1+1', 'https://example.invalid', '@SUM(A1)', None, ''],
        'float': [np.nan, np.inf, -np.inf, -0.0, 1.23456789012345],
        'integer': pd.Series([1, None, -3, 2**55, 0], dtype='Int64'),
        'boolean': pd.Series([True, False, None, True, False], dtype='boolean'),
        'datetime': pd.to_datetime(['2026-01-01', None, '2026-01-02', None, '2026-01-03']),
    })
    yield pd.DataFrame({'mixed': [date(2026, 1, 1), datetime(2026, 1, 1), timedelta(days=1), {'a': 1}, ['b']]})
    yield pd.DataFrame({'category': pd.Categorical(['a', None, 'b']), 'text': pd.Series(['a', None, ''], dtype='string')})
    yield pd.DataFrame(columns=['a', 'b'])
    yield pd.DataFrame()
    yield pd.DataFrame([[1, 'a']], columns=pd.MultiIndex.from_tuples([('a', 'x'), ('b', 'y')]))


def _workbook(frame, path, writer_function):
    with pd.ExcelWriter(path, engine='xlsxwriter', engine_kwargs=pandas_xlsxwriter_engine_kwargs()) as writer:
        writer_function(frame, writer, 'Data')


def _read_cells(path):
    book = openpyxl.load_workbook(path)
    try:
        return [[(cell.value, cell.data_type, cell.number_format, cell.style_id)
                 for cell in row] for row in book['Data']]
    finally:
        book.close()


@pytest.mark.parametrize('frame', list(_frame_cases())[:-1])
def test_bulk_writer_matches_pandas_cells_types_formats_and_xml(frame, tmp_path):
    expected, actual = tmp_path / 'expected.xlsx', tmp_path / 'actual.xlsx'
    _workbook(frame, expected, lambda df, writer, sheet: df.to_excel(writer, sheet_name=sheet, index=False))
    _workbook(frame, actual, write_tabular_dataframe)
    assert _read_cells(expected) == _read_cells(actual)
    with zipfile.ZipFile(expected) as before, zipfile.ZipFile(actual) as after:
        assert before.namelist() == after.namelist()
        for name in before.namelist():
            if name != 'docProps/core.xml':
                assert before.read(name) == after.read(name), name


def test_bulk_writer_preserves_pandas_rejection_of_multiindex_columns(tmp_path):
    frame = list(_frame_cases())[-1]
    for writer_function in (write_tabular_dataframe, lambda df, writer, sheet: df.to_excel(writer, sheet_name=sheet, index=False)):
        with pytest.raises(NotImplementedError):
            _workbook(frame, tmp_path / 'multi.xlsx', writer_function)


def test_parallel_histogram_tables_match_serial_full_data_statistics():
    from metroliza.charts import hexafe_plotstats_adapter as adapter

    rng = np.random.default_rng(1128)
    groups = [(label, np.r_[rng.normal(center, 0.2, 2000), -100.0, 100.0])
              for label, center in [('B', 1.0), ('A', 2.0), ('C', 3.0)]]
    with adapter.histogram_stats_request():
        expected = [adapter.build_histogram_stats_table(values, title=label, lsl=0.5, usl=3.5)
                    for label, values in groups]
    with adapter.histogram_stats_request():
        actual = adapter.build_histogram_stats_tables(groups, lsl=0.5, usl=3.5)
        assert actual == expected
        assert [table.title for table in actual] == ['B', 'A', 'C']
        assert [dict(table.rows)['Samples'] for table in actual] == ['2002'] * 3
        # Workbook reuse after parallel dashboard computation must hit this cache.
        assert [adapter.build_histogram_stats_table(values, title=label, lsl=0.5, usl=3.5)
                for label, values in groups] == expected


def test_parallel_histogram_tables_share_bounded_cache_and_join_workers(monkeypatch):
    from threading import Barrier, enumerate as threads
    from metroliza.charts import hexafe_plotstats_adapter as adapter

    barrier = Barrier(3, timeout=10)
    calls = []

    def compute(values, **kwargs):
        calls.append(values[0])
        barrier.wait()
        return (('Samples', str(len(values))), ('Mean', str(float(np.mean(values)))))

    monkeypatch.setattr(adapter, '_histogram_table_rows_from_plotstats', compute)
    monkeypatch.setattr(adapter, '_HISTOGRAM_TABLE_CACHE_MAX_ENTRIES', 2)
    groups = [(str(index), np.arange(2000.0) + index) for index in range(3)]
    with adapter.histogram_stats_request():
        tables = adapter.build_histogram_stats_tables(groups)
        cache = adapter._histogram_table_cache.get()
        assert [table.title for table in tables] == ['0', '1', '2']
        assert len(cache.rows) == 2
        assert cache.payload_bytes <= adapter._HISTOGRAM_TABLE_CACHE_MAX_BYTES
        assert len(calls) == 3
    assert not cache.rows and cache.payload_bytes == 0
    assert not any(thread.name.startswith('histogram-stats') for thread in threads())


def test_parallel_histogram_failure_joins_workers_and_releases_request(monkeypatch):
    from threading import enumerate as threads
    from metroliza.charts import hexafe_plotstats_adapter as adapter

    def fail(*args, **kwargs):
        raise ValueError('synthetic fit failure')

    monkeypatch.setattr(adapter, '_histogram_table_rows_from_plotstats', fail)
    with pytest.raises(ValueError, match='synthetic fit failure'):
        with adapter.histogram_stats_request():
            cache = adapter._histogram_table_cache.get()
            adapter.build_histogram_stats_tables([('a', np.arange(3000.0)), ('b', np.arange(3000.0))])
    assert not cache.rows and cache.payload_bytes == 0
    assert adapter._histogram_table_cache.get() is None
    assert not any(thread.name.startswith('histogram-stats') for thread in threads())


def test_histogram_tables_fall_back_to_serial_if_threads_cannot_start(monkeypatch):
    from metroliza.charts import hexafe_plotstats_adapter as adapter

    class UnavailablePool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, *args):
            raise RuntimeError('synthetic thread exhaustion')

    monkeypatch.setattr(adapter, 'ThreadPoolExecutor', UnavailablePool)
    monkeypatch.setattr(adapter, '_histogram_table_rows_from_plotstats',
                        lambda values, **kw: (('Samples', str(len(values))),))
    tables = adapter.build_histogram_stats_tables([('b', np.arange(3000.0)), ('a', np.arange(3000.0))])
    assert [table.title for table in tables] == ['b', 'a']
    assert [dict(table.rows)['Samples'] for table in tables] == ['3000', '3000']


def test_bulk_writer_retains_non_dataframe_diagnostics_payload(tmp_path):
    from metroliza.industrial.industrial_analytics_helpers import DiagnosticsSheetPayload

    payload = DiagnosticsSheetPayload(({'code': 'synthetic', 'message': '=literal', 'context': {'a': 1}},))
    expected, actual = tmp_path / 'expected.xlsx', tmp_path / 'actual.xlsx'
    _workbook(payload, expected, lambda data, writer, sheet: data.to_excel(writer, sheet_name=sheet, index=False))
    _workbook(payload, actual, write_tabular_dataframe)
    assert _read_cells(expected) == _read_cells(actual)


def test_histogram_pool_keeps_at_most_three_jobs_pending():
    from metroliza.charts.hexafe_plotstats_adapter import _bounded_histogram_tables

    class Future:
        def __init__(self, pool, job):
            self.pool, self.job = pool, job

        def result(self):
            self.pool.pending -= 1
            fn, *args = self.job
            return fn(*args)

    class Pool:
        pending = 0
        maximum = 0

        def submit(self, *job):
            self.pending += 1
            self.maximum = max(self.pending, self.maximum)
            assert self.pending <= 3
            return Future(self, job)

    pool = Pool()
    groups = list(range(100))
    assert _bounded_histogram_tables(pool, lambda group: group, groups) == groups
    assert pool.maximum == 3
    assert pool.pending == 0


def test_histogram_worker_runtime_error_is_not_mistaken_for_thread_exhaustion(monkeypatch):
    from metroliza.charts import hexafe_plotstats_adapter as adapter

    calls = []

    def fail(values, **kwargs):
        calls.append(1)
        raise RuntimeError('synthetic computation failure')

    monkeypatch.setattr(adapter, '_histogram_table_rows_from_plotstats', fail)
    with pytest.raises(RuntimeError, match='synthetic computation failure'):
        adapter.build_histogram_stats_tables([('a', np.arange(3000.0)), ('b', np.arange(3000.0))])
    assert len(calls) == 2
