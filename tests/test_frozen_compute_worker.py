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


def test_real_summary_renderer_and_import_parser_load_without_qt():
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
from metroliza.exporting.export_summary_render_pool import render_summary_group
result = render_summary_group(_task())
assert not result['failed']
assert any(op == 'image' for op, args in result['commands'])
from metroliza.parsing.import_prepare_pool import _worker_parser_class
_worker_parser_class()
assert not any(n.startswith('PyQt6') for n in sys.modules)
"""
    subprocess.run([sys.executable, '-c', code], check=True, capture_output=True,
                   env=dict(os.environ, PYTHONPATH='src:.'), timeout=90)


def _frame(module, name):
    return SimpleNamespace(f_globals={'__name__': module}, f_code=SimpleNamespace(co_name=name), f_back=None)


def test_compute_audit_accepts_only_cpython_spawn_signature():
    worker = r'C:\Program Files\Metroliza\metroliza_compute_worker.exe'
    frame = _frame('multiprocessing.popen_spawn_win32', '__init__')
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
