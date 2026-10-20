from concurrent.futures import Future, ProcessPoolExecutor
import multiprocessing
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from metroliza.exporting.contracts import ExportOptions
from metroliza.exporting import export_summary_render_pool as pool
from tests.test_export_plot_equivalence import assert_equivalent_pngs


@pytest.fixture(autouse=True)
def fixed_render_budget(monkeypatch):
    # Pool policy/ordering tests must exercise the requested counts on small CI hosts too.
    monkeypatch.setattr('metroliza.shared.compute_budget.logical_cpus', lambda: 16)
    monkeypatch.delenv('METROLIZA_COMPUTE_WORKERS', raising=False)


def _task():
    values = 10 + np.random.default_rng(1126).normal(0, 0.08, 18)
    frame = pd.DataFrame({
        'REFERENCE': ['SYNTHETIC'] * 18, 'HEADER': ['Diameter'] * 18,
        'AX': ['X'] * 18, 'NOM': [10.] * 18, '+TOL': [0.2] * 18,
        '-TOL': [-0.2] * 18, 'MEAS': values,
        'SAMPLE_NUMBER': [str(x) for x in range(18)],
        'DATE': ['2026-01-01'] * 18,
    })
    return dict(
        options=ExportOptions(generate_summary_sheet=True),
        grouping_df=None, sql_summary=None, header='Diameter - X', group=frame, col=5,
        toggles=dict(chart_density_mode='reduced', defer_non_essential_charts=True,
                     summary_sheet_minimum_charts={'distribution', 'iqr', 'histogram', 'trend'},
                     enable_chart_multiprocessing=False),
    )


def test_spawn_worker_matches_serial_pngs_and_worksheet_commands():
    task = _task()
    expected = pool.render_summary_group(task)
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'),
                             initializer=pool._initialize_render_worker) as executor:
        actual = executor.submit(pool.render_summary_group, task).result(timeout=90)
    assert not expected['failed'] and not actual['failed']
    assert len(actual['commands']) == len(expected['commands']) == 6
    for (op, left), (other_op, right) in zip(expected['commands'], actual['commands']):
        assert op == other_op
        if op == 'image':
            assert left[:3] == right[:3]
            assert_equivalent_pngs(left[3], right[3])
        else:
            assert left == right


@pytest.mark.parametrize('workers', [1, 2, 4, 8])
def test_every_worker_count_renders_the_serial_result_in_order(workers):
    from metroliza.shared.compute_worker import spawn_context

    tasks = [_task() for _ in range(4)]
    expected = [pool.render_summary_group(task) for task in tasks]
    with ProcessPoolExecutor(max_workers=workers, mp_context=spawn_context(),
                             initializer=pool._initialize_render_worker) as executor:
        actual = [future.result(timeout=120) for future in
                  [executor.submit(pool.render_summary_group, task) for task in tasks]]
    for left_result, right_result in zip(expected, actual):
        assert not left_result['failed'] and not right_result['failed']
        assert len(left_result['commands']) == len(right_result['commands']) == 6
        for (op, left), (other_op, right) in zip(left_result['commands'], right_result['commands']):
            assert op == other_op
            if op == 'image':
                assert left[:3] == right[:3]
                assert_equivalent_pngs(left[3], right[3])
            else:
                assert left == right


def _owner():
    return SimpleNamespace(
        generate_summary_sheet=True, generate_html_dashboard=False,
        chart_worker_count=2, chart_worker_queue_size=2, completion_metadata={},
        _optimization_toggles={'chart_density_mode': 'reduced'},
        _check_canceled=lambda: False,
    )


@pytest.mark.parametrize('workers,html_only', [(2, False), (4, False), (8, False), (2, True)])
def test_multireference_workbook_and_dashboard_match_serial(monkeypatch, tmp_path, workers, html_only):
    from dataclasses import replace
    from metroliza.exporting.contracts import AppPaths, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread
    from tests.test_export_workbook_equivalence import build_equivalence_db, read_package_parts

    db = tmp_path / 'synthetic.sqlite'
    build_equivalence_db(db, tmp_path, references=('REF-A', 'REF-B'), reports_per_reference=3)
    # Freeze only volatile dashboard metadata; compare every HTML/asset byte.
    import metroliza.charts.export_html_dashboard as dashboard
    from datetime import datetime
    class FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 1, 1)
    monkeypatch.setattr(dashboard, 'datetime', FixedDatetime)
    monkeypatch.setattr(dashboard, 'uuid4', lambda: SimpleNamespace(hex='fixed'))
    monkeypatch.setattr(pool, 'MAX_RENDER_WORKERS', 8)
    outputs = []
    for count in (1, workers):
        directory = tmp_path / str(count)
        directory.mkdir()
        output = directory / 'report.xlsx'
        options = replace(ExportOptions(), preset='full_report', generate_summary_sheet=True,
                          generate_html_dashboard=True, chart_worker_count=count,
                          chart_worker_queue_size=16)
        if html_only:
            options = replace(options, preset='html_dashboard_only', export_target='html_dashboard',
                              backend_target='html', generate_summary_sheet=False)
        paths = AppPaths(str(db), None if html_only else str(output),
                         str(directory / 'report_dashboard.html'))
        thread = ExportDataThread(ExportRequest(paths, options))
        thread.run()
        assert thread.completion_metadata['local_export_outcome'] == 'completed'
        if count > 1:
            assert thread.completion_metadata['summary_render_pool']['mode'] == 'spawn'
            assert thread.completion_metadata['summary_render_pool']['completed'] > 0
        outputs.append(({} if html_only else read_package_parts(output), {
            str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob('*') if path.is_file() and path != output
        }))
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize('column,value', [('REFERENCE', None), ('REFERENCE', ' '),
                                         ('HEADER', None), ('AX', None)])
def test_missing_group_identity_retains_python_statistics(column, value):
    task = _task()
    task['group'][column] = value
    owner = _owner()
    owner._ensure_sample_number_column = lambda group: group
    owner._lookup_sql_measurement_summary = lambda **kw: pytest.fail('Unexpected SQL aggregate')
    owner._summary_render_options = task['options']
    owner.prepared_grouping_df = None
    result = pool._render_task(owner, (task['header'], task['group'], {'measurement_plan': {'summary_column': 1}}))
    assert result['sql_summary'] is None
    assert result['col'] == task['col']


@pytest.mark.parametrize('count,workers,frozen,mode', [
    (4, 2, False, 'serial_small_export'), (40, 1, False, 'serial_small_export'),
    (40, 2, True, 'serial_frozen_multiprocessing_unavailable'),
])
def test_serial_policy_never_starts_pool(monkeypatch, count, workers, frozen, mode):
    owner = _owner()
    owner.chart_worker_count = workers
    monkeypatch.setattr(pool.sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(pool, 'ProcessPoolExecutor', lambda **kw: pytest.fail('Unexpected pool'))
    entries = list(range(count))
    assert list(pool.iter_summary_render_results(owner, entries)) == [(x, None) for x in entries]
    assert owner.completion_metadata['summary_render_pool']['mode'] == mode


class _Executor:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.submitted = []
        self.closed = False

    def submit(self, _func, task):
        future = Future()
        future.set_result(task['value'])
        self.submitted.append(future)
        return future

    def shutdown(self, **kwargs):
        self.closed = kwargs == dict(wait=False, cancel_futures=True)


def _fake_tasks(monkeypatch, owner, executor):
    def create(**kwargs):
        executor.kwargs = kwargs
        return executor
    monkeypatch.setattr(pool, 'ProcessPoolExecutor', create)
    monkeypatch.setattr(pool, '_render_task', lambda o, e: dict(value=e, toggles=dict(o._optimization_toggles)))
    return pool.iter_summary_render_results(owner, list(range(8)))


def test_queue_is_bounded_ordered_and_shutdown_on_early_close(monkeypatch):
    owner, executor = _owner(), _Executor()
    results = _fake_tasks(monkeypatch, owner, executor)
    assert next(results) == (0, None)
    assert next(results) == (1, 1)
    assert len(executor.submitted) == 2
    results.close()
    assert executor.closed
    assert owner.completion_metadata['summary_render_pool']['max_pending'] == 2


def test_complete_pool_collection_preserves_order(monkeypatch):
    owner, executor = _owner(), _Executor()
    assert list(_fake_tasks(monkeypatch, owner, executor)) == [(0, None)] + [(x, x) for x in range(1, 8)]
    assert executor.closed
    assert owner.completion_metadata['summary_render_pool']['completed'] == 7


def test_export_pool_reuses_workers_across_small_references(monkeypatch):
    owner, executor = _owner(), _Executor()
    _fake_tasks(monkeypatch, owner, executor)
    session = pool.SummaryRenderPool(owner, 12)
    assert session.executor is None
    for entries in (list(range(6)), list(range(6, 12))):
        actual = list(pool.iter_summary_render_results(owner, entries, render_pool=session))
        assert actual == [(entries[0], None)] + [(x, x) for x in entries[1:]]
        assert session.executor is executor
        assert not executor.closed
    assert len(executor.submitted) == 10
    assert session.telemetry['completed'] == 10
    session.close()
    session.close()
    assert executor.closed


def test_failed_export_pool_stays_serial_for_later_references(monkeypatch):
    owner, executor = _owner(), _Executor()
    _fake_tasks(monkeypatch, owner, executor)
    calls = []
    def fail(*args):
        calls.append(1)
        raise RuntimeError('failed submission')
    executor.submit = fail
    session = pool.SummaryRenderPool(owner, 12)
    for entries in (list(range(6)), list(range(6, 12))):
        assert list(session.iter_results(entries)) == [(x, None) for x in entries]
    assert calls == [1]
    assert executor.closed
    session.close()


def test_worker_count_is_capped_and_spawn_is_explicit(monkeypatch):
    owner, executor = _owner(), _Executor()
    owner.chart_worker_count = 99
    owner.chart_worker_queue_size = 99
    assert len(list(_fake_tasks(monkeypatch, owner, executor))) == 8
    assert executor.kwargs['max_workers'] == pool.MAX_RENDER_WORKERS
    assert executor.kwargs['mp_context'].get_start_method() == 'spawn'
    assert executor.kwargs['initializer'] is pool._initialize_render_worker
    assert owner.completion_metadata['summary_render_pool']['max_pending'] <= 8


def test_partial_pool_failure_does_not_duplicate_already_collected_group(monkeypatch):
    owner, executor = _owner(), _Executor()
    results = _fake_tasks(monkeypatch, owner, executor)
    assert next(results) == (0, None)
    assert next(results) == (1, 1)
    def fail(*args):
        raise RuntimeError('late submission failure')
    executor.submit = fail
    assert list(results) == [(x, None) for x in range(2, 8)]
    assert executor.closed


@pytest.mark.parametrize('failure', ['startup', 'event', 'task', 'submit', 'result', 'timeout'])
def test_pool_failure_replays_every_remaining_group_serially(monkeypatch, failure):
    owner, executor = _owner(), _Executor()
    results = _fake_tasks(monkeypatch, owner, executor)
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic pool failure')
    if failure == 'startup':
        monkeypatch.setattr(pool, 'ProcessPoolExecutor', fail)
    elif failure == 'event':
        monkeypatch.setattr(pool, 'spawn_context', lambda: SimpleNamespace(Event=fail))
    elif failure == 'task':
        monkeypatch.setattr(pool, '_render_task', fail)
    elif failure == 'submit':
        executor.submit = fail
    else:
        def failed_future(*args):
            future = Future()
            error = TimeoutError if failure == 'timeout' else RuntimeError
            future.set_exception(error('synthetic worker failure'))
            return future
        executor.submit = failed_future
    assert list(results) == [(x, None) for x in range(8)]
    assert owner.completion_metadata['summary_render_pool']['mode'] == 'serial_pool_failure'


def test_policy_change_discards_queued_render_and_cancellation_cleans_up(monkeypatch):
    owner, executor = _owner(), _Executor()
    results = _fake_tasks(monkeypatch, owner, executor)
    assert next(results) == (0, None)
    assert next(results) == (1, 1)
    owner._optimization_toggles['chart_density_mode'] = 'full'
    assert next(results) == (2, None)
    owner._check_canceled = lambda: True
    assert list(results) == []
    assert executor.closed


def _pause_chart_worker(initializer, initargs, started, release_path, trace_dir):
    """Pause a real chart in a spawn child, without creating a QApplication."""
    initializer(*initargs)
    from metroliza.exporting.export_data_thread import ExportDataThread

    save = ExportDataThread._save_summary_chart

    def save_chart(self, *args, **kwargs):
        result = save(self, *args, **kwargs)
        import os

        with (Path(trace_dir) / f'{os.getpid()}.charts').open('a') as trace:
            trace.write(kwargs['chart_type'] + '\n')
        started.set()
        deadline = time.monotonic() + 30
        while not Path(release_path).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert Path(release_path).exists(), 'Test did not release the active chart'
        return result

    ExportDataThread._save_summary_chart = save_chart


@pytest.mark.parametrize('release_chart', [True, False], ids=['chart-boundary', 'stuck-chart'])
def test_cancel_active_spawn_render_stops_charts_and_reaps_workers(monkeypatch, tmp_path, release_chart):
    context = multiprocessing.get_context('spawn')
    started = context.Event()
    release = tmp_path / 'release'
    canceled = threading.Event()
    owner = _owner()
    owner._check_canceled = canceled.is_set
    executors = []
    processes = []
    managers = []

    def create(**kwargs):
        initializer = kwargs.pop('initializer')
        initargs = kwargs.pop('initargs', ())
        executor = ProcessPoolExecutor(
            **kwargs, initializer=_pause_chart_worker,
            initargs=(initializer, initargs, started, str(release), str(tmp_path)),
        )
        executors.append(executor)
        return executor

    monkeypatch.setattr(pool, 'ProcessPoolExecutor', create)
    monkeypatch.setattr(pool, '_render_task', lambda o, e: _task())
    results = pool.iter_summary_render_results(owner, list(range(8)))
    assert next(results) == (0, None)
    collected, errors = [], []

    def collect():
        try:
            collected.extend(results)
        except BaseException as exc:
            errors.append(exc)

    collector = threading.Thread(target=collect)
    collector.start()
    try:
        assert started.wait(30), 'Worker never reached active chart rendering'
        processes.extend(executors[0]._processes.values())
        managers.append(executors[0]._executor_manager_thread)
        assert any(p.is_alive() for p in processes)
        cancel_start = time.monotonic()
        canceled.set()
        # Let the parent poll before allowing the current chart to finish.
        if release_chart:
            time.sleep(0.3)
            release.touch()
        collector.join(timeout=5)
        assert not collector.is_alive(), 'Cancellation blocked on an in-flight render'
        assert time.monotonic() - cancel_start < 5
        assert not errors
        assert all(not p.is_alive() and p.exitcode is not None for p in processes)
        assert all(not manager.is_alive() for manager in managers)
        charts = [chart for trace in tmp_path.glob('*.charts') for chart in trace.read_text().splitlines()]
        assert charts and set(charts) == {'distribution'}, 'Subsequent charts rendered after cancellation'
        assert collected == [], 'Canceled render results escaped to workbook replay'
        if release_chart:
            assert all(p.exitcode == 0 for p in processes), 'Cooperative workers were forcibly stopped'
    finally:
        # The old implementation must also leave this deliberately failing test cleanly.
        canceled.set()
        release.touch()
        collector.join(timeout=30)
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)


def test_frozen_windows_policy_uses_windows_threshold_and_environment(monkeypatch):
    monkeypatch.setattr(pool.sys, 'platform', 'win32')
    monkeypatch.setattr(pool, 'compute_workers_available', lambda: True)
    monkeypatch.setattr(pool.sys, 'frozen', True, raising=False)
    monkeypatch.delenv('METROLIZA_EXPORT_GROUP_MIN_GROUPS', raising=False)
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '1')
    owner = _owner()
    assert pool._pool_policy(owner, 39) == 'serial_small_export'
    assert pool._pool_policy(owner, 40) == 'spawn'
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '0')
    assert pool._pool_policy(owner, 40) == 'serial_disabled'
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MIN_GROUPS', '50')
    assert pool._pool_policy(owner, 40) == 'serial_small_export'


def test_frozen_executor_uses_shared_compute_context_and_worker_cap(monkeypatch):
    monkeypatch.setattr(pool.sys, 'platform', 'win32')
    monkeypatch.setattr(pool, 'compute_workers_available', lambda: True)
    monkeypatch.setattr(pool.sys, 'frozen', True, raising=False)
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MIN_GROUPS', '2')
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_WORKERS', '2')
    context = SimpleNamespace(Event=multiprocessing.get_context("spawn").Event)
    monkeypatch.setattr(pool, 'spawn_context', lambda: context)
    owner, executor = _owner(), _Executor()
    owner.chart_worker_count = 4
    assert len(list(_fake_tasks(monkeypatch, owner, executor))) == 8
    assert executor.kwargs['mp_context'] is context
    assert executor.kwargs['max_workers'] == 2


def test_serial_policies_never_validate_the_package_identity(monkeypatch):
    # compute_workers_available() hashes the packaged executables on frozen Windows.
    calls = []
    monkeypatch.setattr(pool, 'compute_workers_available', lambda: calls.append(1) or False)
    monkeypatch.setattr(pool.sys, 'platform', 'win32')
    monkeypatch.setattr(pool.sys, 'frozen', True, raising=False)
    monkeypatch.delenv('METROLIZA_EXPORT_GROUP_MIN_GROUPS', raising=False)
    owner = _owner()
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '0')
    assert pool._pool_policy(owner, 40) == 'serial_disabled'
    assert pool._pool_policy(owner, 39) == 'serial_small_export'
    assert calls == []
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '1')
    assert pool._pool_policy(owner, 40) == 'serial_frozen_multiprocessing_unavailable'
    assert calls == [1]


@pytest.mark.parametrize('summary_sheet', [True, False])
def test_each_pooled_chart_image_is_registered_once(summary_sheet, monkeypatch):
    from dataclasses import replace
    from metroliza.exporting.contracts import AppPaths, ExportRequest
    from metroliza.exporting.export_data_thread import ExportDataThread

    task = _task()
    task['options'] = replace(task['options'], generate_summary_sheet=summary_sheet,
                              generate_html_dashboard=True)
    result = pool.render_summary_group(task)
    assert not result['failed']
    charts = [chart for section in result['dashboard_sections'] for chart in section['charts']]
    assert charts
    if summary_sheet:
        assert all(isinstance(chart['image_buffer'], tuple) for chart in charts)
    else:
        assert all(isinstance(chart['image_buffer'], bytes) for chart in charts)
    owner = ExportDataThread(ExportRequest(AppPaths('unused.sqlite', 'unused.xlsx'), task['options']))
    registered = []
    register = owner._register_chart_image
    def record(payload):
        buffer = register(payload)
        registered.append(buffer)
        return buffer
    monkeypatch.setattr(owner, '_register_chart_image', record)
    sheet_images = []
    sheet = SimpleNamespace(write=lambda *args: None,
                            insert_image=lambda *args: sheet_images.append(args[-1]['image_data']))
    pool.apply_summary_render_result(owner, sheet, result)
    assert len(registered) == len(charts)
    if summary_sheet:
        assert len(sheet_images) == len(charts)
        assert all(chart['image_buffer'] is buffer for chart, buffer in zip(charts, sheet_images))
    else:
        assert not sheet_images
