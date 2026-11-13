"""Frozen executable selection and Qt-free worker contracts (#1134)."""

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from metroliza.shared import compute_worker
from metroliza.shared import diagnostic_runtime_audit as audit


def test_source_spawn_does_not_change_executable(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(compute_worker, 'worker_executable', lambda: pytest.fail('source identity check'))
    assert compute_worker.spawn_context().get_start_method() == 'spawn'


def test_frozen_spawn_selects_only_verified_compute_sibling(monkeypatch, tmp_path):
    from metroliza.shared import diagnostic_package

    application = tmp_path / 'metroliza_application.exe'
    monkeypatch.setattr(sys, 'executable', str(application))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(diagnostic_package, 'inspect_package', lambda root: SimpleNamespace(valid=True))
    selected = []
    monkeypatch.setattr(compute_worker.multiprocessing, 'get_context',
                        lambda method: SimpleNamespace(set_executable=selected.append))
    compute_worker.spawn_context()
    assert selected == [str(tmp_path / 'metroliza_compute_worker.exe')]
    monkeypatch.setattr(diagnostic_package, 'inspect_package',
                        lambda root: diagnostic_package.PackageIdentity(False, 'component_missing',
                            component='metroliza_compute_worker.exe'))
    with pytest.raises(RuntimeError, match='component_missing:metroliza_compute_worker.exe'):
        compute_worker.spawn_context()
    assert len(selected) == 1
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'other.exe'))
    with pytest.raises(RuntimeError, match='compute_package_identity_failed'):
        compute_worker.spawn_context()


def test_compute_entry_dispatches_before_any_product_import():
    root = Path(__file__).resolve().parents[1]
    code = """
import multiprocessing, runpy, sys
seen = []
def dispatch():
    assert not any(n.startswith(('metroliza', 'PyQt6')) for n in sys.modules)
    seen.append(True)
multiprocessing.freeze_support = dispatch
try:
    runpy.run_path(sys.argv[1], run_name='__main__')
except SystemExit as result:
    assert result.code == 2
assert seen == [True]
"""
    subprocess.run([sys.executable, '-c', code, str(root / 'packaging/metroliza_compute_worker_entry.py')],
                   check=True, capture_output=True)


@pytest.mark.parametrize('canceled', [False, True])
def test_real_summary_renderer_and_import_parser_load_without_qt(canceled):
    code = """
import importlib.abc, sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('PyQt6'):
            raise AssertionError('Qt import: ' + fullname)
sys.meta_path.insert(0, NoQt())
from tests.test_export_summary_render_pool import _task
sys.frozen = True
sys.executable = 'metroliza_compute_worker.exe'
from metroliza.shared import compute_worker
compute_worker.initialize_compute_runtime = lambda: None
from metroliza.exporting.export_summary_render_pool import render_summary_group, _initialize_render_worker
import threading
event = threading.Event()
if sys.argv[1] == 'True':
    event.set()
_initialize_render_worker(event)
result = render_summary_group(_task())
assert not result['failed']
if event.is_set():
    assert result['commands'] == []
else:
    assert any(op == 'image' for op, args in result['commands'])
from metroliza.parsing.import_prepare_pool import _worker_parser_class
_worker_parser_class()
assert not any(n.startswith('PyQt6') for n in sys.modules)
"""
    subprocess.run([sys.executable, '-c', code, str(canceled)], check=True, capture_output=True,
                   env=dict(os.environ, PYTHONPATH='src:.'), timeout=90)


def _frame(module, name):
    return SimpleNamespace(f_globals={'__name__': module}, f_code=SimpleNamespace(co_name=name), f_back=None)


def test_compute_audit_accepts_only_cpython_spawn_signature(monkeypatch):
    worker = r'C:\Program Files\Metroliza\metroliza_compute_worker.exe'
    from tests.test_windows_runtime_audit import _windows_spawn_module

    module = _windows_spawn_module(monkeypatch)
    frame = SimpleNamespace(f_code=module.Popen.__init__.__code__,
                            f_globals=module.__dict__, f_back=None)
    import multiprocessing.spawn
    from unittest.mock import patch

    application = r'C:\Program Files\Metroliza\metroliza_application.exe'
    with patch.object(sys, 'executable', application), patch.object(sys, 'frozen', True, create=True):
        # Use CPython's real frozen command builder, not an invented argv shape.
        command = ' '.join('"%s"' % value for value in multiprocessing.spawn.get_command_line(parent_pid=123, pipe_handle=456))
    args = (worker, command, None)
    assert audit.classify_compute_call(args, frame, worker) == ('compute_worker_launch', 'metroliza')
    for bad in ((worker, command + ' extra', None), ('other.exe', command, None),
                (worker, command, 'other'), (worker, command.replace('123', '-1'), None)):
        assert audit.classify_compute_call(bad, frame, worker)[0] != 'compute_worker_launch'
    assert audit.classify_compute_call(args, _frame('unrelated', '__init__'), worker)[0] == 'other_frames'


@pytest.mark.parametrize('platform', ['win32', 'linux'])
@pytest.mark.parametrize('reason', ['verified', 'component_missing', 'component_modified', 'unavailable'])
@pytest.mark.parametrize('configured', ['auto', '3', '16'])
def test_both_pool_policies_require_supported_validated_frozen_compute(
    monkeypatch, tmp_path, platform, reason, configured,
):
    from metroliza.shared import diagnostic_package
    from metroliza.exporting import export_summary_render_pool as render
    from metroliza.parsing import import_prepare_pool as prepare
    from tests.test_export_summary_render_pool import _owner

    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'metroliza_application.exe'))
    identity = diagnostic_package.PackageIdentity(reason == 'verified', reason,
                                                  component='metroliza_compute_worker.exe')
    monkeypatch.setattr(diagnostic_package, 'inspect_package', lambda root: identity)
    monkeypatch.setattr(os, 'cpu_count', lambda: 12)
    monkeypatch.setenv(prepare.WORKERS_ENV, configured)
    monkeypatch.delenv(prepare.MIN_REPORTS_ENV, raising=False)
    monkeypatch.delenv('METROLIZA_EXPORT_GROUP_MIN_GROUPS', raising=False)
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '1')
    supported = platform == 'win32' and reason == 'verified'
    assert compute_worker.compute_workers_available() is supported
    # Packaged Windows import workers are opt-in (#1136 evidence): 'auto' resolves to 0.
    expected = (0 if configured == 'auto' else int(configured)) if supported else 0
    assert prepare.resolve_prepare_worker_count(5000) == expected
    assert render._pool_policy(_owner(), 40) == (
        'spawn' if supported else 'serial_frozen_multiprocessing_unavailable'
    )


def test_pool_launch_revalidates_compute_identity_after_policy_check(monkeypatch, tmp_path):
    from metroliza.shared import diagnostic_package
    from metroliza.exporting import export_summary_render_pool as render
    from metroliza.parsing import import_prepare_pool as prepare
    from tests.test_export_summary_render_pool import _owner

    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'metroliza_application.exe'))
    identity = diagnostic_package.PackageIdentity(True, 'verified')
    monkeypatch.setattr(diagnostic_package, 'inspect_package', lambda root: identity)
    monkeypatch.setattr(os, 'cpu_count', lambda: 12)
    monkeypatch.setenv(prepare.WORKERS_ENV, '3')
    monkeypatch.delenv(prepare.MIN_REPORTS_ENV, raising=False)
    monkeypatch.delenv('METROLIZA_EXPORT_GROUP_MIN_GROUPS', raising=False)
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '1')
    monkeypatch.setattr(render, 'ProcessPoolExecutor', lambda **kw: pytest.fail('unvalidated render'))
    monkeypatch.setattr(prepare, 'ProcessPoolExecutor', lambda **kw: pytest.fail('unvalidated import'))
    owner = _owner()
    entries = list(range(40))
    results = render.iter_summary_render_results(owner, entries)
    assert next(results) == (0, None)
    assert prepare.resolve_prepare_worker_count(5000) == 3
    identity = diagnostic_package.PackageIdentity(False, 'component_modified',
                                                  component='metroliza_compute_worker.exe')
    assert list(results) == [(entry, None) for entry in entries[1:]]
    assert owner.completion_metadata['summary_render_pool']['mode'] == 'serial_pool_failure'
    with pytest.raises(RuntimeError, match='component_modified:metroliza_compute_worker.exe'):
        prepare.ImportPreparePool([], database_path='unused', metadata_parsing_mode='light',
                                  workers=3, parser_plugin_id='builtin')


class _StuckComputeProcess:
    def __init__(self):
        self.alive = True
        self.terminated = False
        self.killed = False
        self.joins = []

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.alive = False

    def join(self, timeout):
        self.joins.append(timeout)


@pytest.mark.parametrize('kind', ['render', 'prepare'])
def test_selected_compute_pools_poll_cancellation_and_reap_owned_processes(monkeypatch, tmp_path, kind):
    from concurrent.futures import Future, TimeoutError
    import threading
    from metroliza.shared import diagnostic_package
    from metroliza.exporting import export_summary_render_pool as render
    from metroliza.parsing import import_prepare_pool as prepare
    from tests.test_export_summary_render_pool import _owner

    selected, shutdown, polls, manager_joins, feeder = [], [], [], [], []
    canceled = threading.Event()
    context = SimpleNamespace(set_executable=selected.append, Event=threading.Event)
    monkeypatch.setattr(compute_worker.multiprocessing, 'get_context', lambda method: context)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'metroliza_application.exe'))
    monkeypatch.setattr(diagnostic_package, 'inspect_package',
                        lambda root: diagnostic_package.PackageIdentity(True, 'verified'))
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MIN_GROUPS', '2')
    monkeypatch.setenv('METROLIZA_EXPORT_GROUP_MP', '1')
    child = _StuckComputeProcess()
    manager = SimpleNamespace(join=lambda timeout: manager_joins.append(timeout), is_alive=lambda: False)

    class CancelingFuture(Future):
        def result(self, timeout=None):
            polls.append(timeout)
            canceled.set()
            raise TimeoutError()

    class Executor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._processes = {1: child}
            self._executor_manager_thread = manager
            self._call_queue = SimpleNamespace(cancel_join_thread=lambda: feeder.append(True))

        def submit(self, *args):
            return CancelingFuture()

        def shutdown(self, **kwargs):
            shutdown.append(kwargs)

    if kind == 'render':
        owner = _owner()
        owner._check_canceled = canceled.is_set
        executor = Executor()
        monkeypatch.setattr(render, 'ProcessPoolExecutor', lambda **kw: Executor.__init__(executor, **kw) or executor)
        monkeypatch.setattr(render, '_render_task', lambda o, e: {'toggles': {}})
        results = render.iter_summary_render_results(owner, list(range(8)))
        assert list(results) == [(0, None)]
        assert executor.kwargs['initargs'][0].is_set()
        assert polls == [render.RESULT_POLL_SECONDS]
    else:
        monkeypatch.setattr(prepare, 'ProcessPoolExecutor', Executor)
        pool = prepare.ImportPreparePool(['synthetic'], database_path='unused', metadata_parsing_mode='light',
                                         workers=2, parser_plugin_id='builtin', should_cancel=canceled.is_set)
        with pytest.raises(prepare.ImportPreparationCancelled):
            pool._result(pool._futures[0])
        pool.close(cancel=True)
        assert pool._futures == {}
        assert feeder == [True]
        assert polls == [prepare._RESULT_POLL_SECONDS]
    assert selected == [str(tmp_path / 'metroliza_compute_worker.exe')]
    assert child.terminated and child.killed and not child.is_alive()
    assert child.joins and all(timeout >= 0 for timeout in child.joins)
    assert manager_joins and shutdown[0]['cancel_futures']
