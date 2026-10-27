"""Process-isolated GC policy checks: never alter the parent pytest GC policy."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_python(source):
    environment = {key: value for key, value in os.environ.items() if key != "QT_QPA_PLATFORMTHEME"}
    environment.update(QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-u", "-X", "faulthandler", "-c", textwrap.dedent(source)],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_cyclic_dialogs_are_destroyed_on_gui_thread_after_worker_allocations():
    output = run_python('''
        import gc
        import threading
        import weakref
        from PyQt6.QtCore import QCoreApplication, QEvent, Qt
        from PyQt6.QtWidgets import QApplication, QDialog, QPushButton
        from metroliza.app.gc_policy import install

        app = QApplication([])
        policy = install(app)
        gui = threading.get_ident()
        destroyed_in, refs = [], []
        def make_dialog():
            dialog = QDialog()
            refs.append(weakref.ref(dialog))
            dialog.button = QPushButton("x", dialog)
            dialog.button.clicked.connect(lambda: dialog.accept())
            dialog.destroyed.connect(lambda *_: destroyed_in.append(threading.get_ident()),
                                     Qt.ConnectionType.DirectConnection)
        for _ in range(20):
            make_dialog()
        def allocate():
            junk = [[i] for i in range(400_000)]
            del junk
        worker = threading.Thread(target=allocate)
        worker.start()
        worker.join()
        assert not gc.isenabled()
        # Drive the real timer rather than directly invoking the cleanup method.
        from PyQt6.QtCore import QTimer
        def check():
            if len(destroyed_in) == 20:
                app.quit()
        poll = QTimer(app)
        poll.timeout.connect(check)
        poll.start(10)
        QTimer.singleShot(5000, app.quit)
        app.exec()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert len(destroyed_in) == 20, destroyed_in
        assert all(thread == gui for thread in destroyed_in)
        assert all(ref() is None for ref in refs)
        assert policy.collections[0] >= 1
        print("destroyed=20 on_gui_thread=20 on_worker=0")
    ''')
    assert "destroyed=20 on_gui_thread=20 on_worker=0" in output


@pytest.mark.parametrize("enabled", [True, False])
def test_install_is_idempotent_and_uninstall_restores_state(enabled):
    run_python(f'''
        import gc
        from PyQt6.QtWidgets import QApplication
        from metroliza.app.gc_policy import install, INTERVAL_MS
        app = QApplication([])
        gc.set_threshold(711, 12, 13)
        gc.{'enable' if enabled else 'disable'}()
        policy = install(app)
        assert not gc.isenabled()
        assert install(app) is policy
        assert policy.timer.parent() is app
        assert policy.timer.interval() == INTERVAL_MS
        assert policy.timer.isActive()
        gc.set_threshold(900, 20, 30)
        policy.uninstall()
        policy.uninstall()
        assert gc.isenabled() is {enabled}
        assert gc.get_threshold() == (711, 12, 13)
        assert not policy.timer.isActive()
        replacement = install(app)
        assert replacement is not policy
        replacement.uninstall()
    ''')


def test_generation_order_thresholds_statistics_and_reentrancy():
    run_python('''
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        from metroliza.app import gc_policy
        app = QApplication([])
        policy = gc_policy.install(app)
        counts = [0, 0, 0]
        calls = []
        def collect(generation):
            calls.append(generation)
            policy.collect_due(force_young=True)  # finalizers can reenter Python
            counts[generation] = 0
            if generation < 2:
                counts[generation + 1] += 1
        with patch.object(gc_policy.gc, 'get_count', lambda: tuple(counts)), \
             patch.object(gc_policy.gc, 'get_threshold', lambda: (7, 2, 2)), \
             patch.object(gc_policy.gc, 'collect', collect):
            policy.collect_due()
            assert calls == []
            counts[:] = [7, 0, 0]
            policy.collect_due()
            assert calls == []  # strictly exceeds the threshold
            counts[:] = [8, 2, 2]
            policy.collect_due()
            assert calls == [0, 1, 2]
            assert policy.collections == [1, 1, 1]
            assert 0 <= policy.max_ms <= policy.total_ms
            policy.collect_due(force_young=True)
            assert calls == [0, 1, 2, 0]
        with patch.object(gc_policy.gc, 'get_threshold', lambda: (0, 0, 0)), \
             patch.object(gc_policy.gc, 'collect', collect):
            policy.collect_due()
            assert calls == [0, 1, 2, 0]
        policy.uninstall()
    ''')


def test_worker_cannot_install_collect_or_uninstall():
    run_python('''
        import gc
        import threading
        from PyQt6.QtWidgets import QApplication
        from metroliza.app.gc_policy import install
        app = QApplication([])
        errors = []
        def call_in_worker(callback):
            def run():
                try:
                    callback()
                except RuntimeError as error:
                    errors.append(str(error))
            thread = threading.Thread(target=run)
            thread.start()
            thread.join()
        enabled = gc.isenabled()
        call_in_worker(lambda: install(app))
        assert gc.isenabled() == enabled
        policy = install(app)
        call_in_worker(policy.collect_due)
        call_in_worker(policy.uninstall)
        assert len(errors) == 3
        assert all('GUI thread' in error for error in errors)
        assert policy.active and policy.collections == [0, 0, 0]
        policy.uninstall()
    ''')


def test_import_is_headless_and_non_gui_application_is_rejected():
    run_python('''
        import gc
        import sys
        enabled, thresholds = gc.isenabled(), gc.get_threshold()
        from metroliza.app.gc_policy import install
        assert 'PyQt6.QtWidgets' not in sys.modules
        assert gc.isenabled() == enabled and gc.get_threshold() == thresholds
        from PyQt6.QtCore import QCoreApplication
        app = QCoreApplication([])
        try:
            install(app)
        except TypeError:
            pass
        else:
            raise AssertionError('QCoreApplication accepted')
        assert gc.isenabled() == enabled and gc.get_threshold() == thresholds
    ''')


def test_bootstrap_installs_before_main_window_but_smoke_keeps_gc_state():
    run_python('''
        import gc
        import logging
        from types import SimpleNamespace
        from unittest.mock import patch
        from PyQt6.QtCore import QTimer
        from metroliza.app import bootstrap
        app = bootstrap.get_or_create_qapplication(gui_gc=False)
        enabled = gc.isenabled()
        with patch('metroliza.app.license_key_manager.LicenseKeyManager.generate_hardware_id'):
            bootstrap.run_startup_smoke_mode(logging.getLogger('test'))
        assert gc.isenabled() == enabled
        assert not hasattr(app, '_metroliza_gc_policy')
        class Window:
            def __init__(self, *args):
                assert not gc.isenabled()
                assert app._metroliza_gc_policy.timer.isActive()
            def show(self):
                QTimer.singleShot(0, app.quit)
        splash = SimpleNamespace(show_message=lambda *a, **k: None)
        config = bootstrap.StartupConfig(False, False, None, None, False)
        with patch.object(bootstrap, 'validate_license_bootstrap',
                          return_value=SimpleNamespace(is_valid=True, days_until_expiration=7)), \
             patch.object(bootstrap, 'create_startup_splash', return_value=splash), \
             patch.object(bootstrap, '_schedule_splash_finish_then_warmup'):
            assert bootstrap.launch_ui(config, main_window_factory=Window) == 0
        app._metroliza_gc_policy.uninstall()
    ''')


def test_shared_application_factory_installs_policy_for_gui_qualification_flows():
    # Qualification flows (fresh reopen, candidate UI checks, diagnostics) create their
    # application through get_or_create_qapplication() rather than launch_ui().
    run_python('''
        import gc
        from metroliza.app import bootstrap
        app = bootstrap.get_or_create_qapplication()
        policy = app._metroliza_gc_policy
        assert not gc.isenabled() and policy.timer.isActive()
        assert bootstrap.get_or_create_qapplication() is app
        assert app._metroliza_gc_policy is policy
        policy.uninstall()
    ''')
