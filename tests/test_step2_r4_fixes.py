"""Regression receipts for Performance Boost STEP2 review batch R4 (#1148)."""

from __future__ import annotations

import ast
import builtins
import gc
import importlib
from pathlib import Path
import sys
import threading
import time
import traceback
from types import ModuleType, SimpleNamespace

import pytest


def test_export_chart_collections_stay_on_gui_thread(qapplication_session, monkeypatch):
    from metroliza.app.gc_policy import install
    from metroliza.exporting import export_data_thread as module

    app = qapplication_session
    policy = install(app)
    gui = threading.get_ident()
    collections, worker_stacks, closed_in, results, errors = [], [], [], [], []
    close = module.plt.close

    def record_close(figure):
        closed_in.append(threading.get_ident())
        close(figure)

    monkeypatch.setattr(module.plt, "close", record_close)

    def record_collection(phase, _info):
        if phase == "start":
            collections.append(threading.get_ident())
            if threading.get_ident() != gui:
                worker_stacks.append("".join(traceback.format_stack()))

    def render():
        try:
            results.append(module.ExportDataThread._render_group_analysis_plot_asset(
                {"metric": "Synthetic diameter", "chart_payload": {
                    "groups": [{"group": "A", "values": [9.8, 10.0, 10.2, 10.1]}],
                    "spec_limits": {"nominal": 10.0, "lsl": 9.0, "usl": 11.0},
                }}, "histogram",
            ))
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=render)
    gc.callbacks.append(record_collection)
    try:
        worker.start()
        deadline = time.monotonic() + 30
        while worker.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            worker.join(0.005)
        assert not worker.is_alive(), "Export chart renderer did not finish"
        # Guarantee a positive collection receipt even for a sub-500 ms render.
        policy.collect_due(force_young=True)
    finally:
        worker.join(30)
        gc.callbacks.remove(record_collection)
    assert not errors, errors
    assert results[0]["image_data"].getvalue().startswith(b"\x89PNG\r\n\x1a\n")
    assert closed_in == [worker.ident]
    assert collections and all(ident == gui for ident in collections), worker_stacks


@pytest.mark.parametrize("leaked", [False, True])
def test_teardown_guard_restores_gc_and_names_leaking_test(monkeypatch, leaked):
    from tests import conftest

    sweeps = []
    policy = SimpleNamespace(collect_due=lambda **kwargs: sweeps.append(kwargs))
    app = SimpleNamespace(_metroliza_gc_policy=policy)
    monkeypatch.setattr(conftest, "retain_qapplication", lambda: None)
    monkeypatch.setattr(conftest, "_RETAINED_QT_APPLICATIONS", [app])
    hook = conftest.pytest_runtest_teardown(SimpleNamespace(nodeid="synthetic::gc_leak"))
    next(hook)
    enabled = gc.isenabled()
    try:
        gc.enable() if leaked else gc.disable()
        expected = pytest.fail.Exception if leaked else StopIteration
        with pytest.raises(expected, match="synthetic::gc_leak" if leaked else None):
            next(hook)
        assert not gc.isenabled()
        if not leaked:
            assert sweeps == [{"force_young": True}]
    finally:
        gc.enable() if enabled else gc.disable()


@pytest.mark.parametrize("late_action", ["cancel", "error"])
def test_export_cancel_and_error_after_terminal_dismissal(qapplication_session, monkeypatch, tmp_path, late_action):
    from PyQt6.QtWidgets import QDialog
    from tests.test_active_dialog_close_guards import (
        _ExportThread, _progress_dialog, _wait_until,
    )

    # Stub import tests can leave a stale attribute on the parent package.
    module = importlib.import_module("metroliza.ui.export_dialog")
    assert issubclass(module.ExportDialog, QDialog)
    cancel_calls, errors = [], []

    class CleaningExportThread(_ExportThread):
        def stop_exporting(self):
            cancel_calls.append("cancel")  # Cleanup still owns the running thread.

    request = SimpleNamespace(
        paths=SimpleNamespace(excel_file=str(tmp_path / "output.xlsx"), html_dashboard_file=None),
        options=SimpleNamespace(violin_plot_min_samplesize=6, summary_plot_scale=0),
    )
    monkeypatch.setattr(module, "build_validated_export_request", lambda **kwargs: request)
    monkeypatch.setattr(module, "create_export_data_thread", CleaningExportThread)
    monkeypatch.setattr(module, "create_worker_progress_dialog", _progress_dialog)
    monkeypatch.setattr(module.ExportDialog, "_load_dialog_config", lambda self: {"selected_preset": "fast_diagnostics"})
    monkeypatch.setattr(module, "load_dashboard_visual_settings", lambda: {})
    monkeypatch.setattr(module, "save_export_dialog_config", lambda *args: None)
    dialog = module.ExportDialog(db_file=str(tmp_path / "source.db"))
    dialog.config_path = tmp_path / "export-config.json"
    dialog.excel_file = tmp_path / "output.xlsx"
    dialog._set_path_field_value(dialog.excel_file_text_label, dialog.excel_file)
    monkeypatch.setattr(dialog, "_refresh_metadata_enrichment_notice", lambda: None)
    monkeypatch.setattr(dialog, "log_and_exit", errors.append)
    dialog._close_requested = True
    dialog.show_loading_screen()
    thread = dialog.export_thread
    try:
        assert _wait_until(qapplication_session, thread.isRunning)
        dialog.stop_exporting()
        thread.canceled.emit()
        assert dialog.loading_label is None
        assert thread.isRunning()
        if late_action == "cancel":
            dialog.stop_exporting()
            assert errors == []
            assert cancel_calls == ["cancel", "cancel"]
        else:
            dialog.on_export_error("late cleanup failure")
            assert dialog.export_error_message == "late cleanup failure"
    finally:
        thread.release()
        assert thread.wait(1000)
        qapplication_session.processEvents()
        dialog._changes_committed = True
        dialog.close()


def test_feature_warmup_reports_setup_failure(qapplication_session, monkeypatch):
    from metroliza.charts import matplotlib_runtime
    from tests.test_main_window_metadata_ui import _wait_for_filter_shutdown

    module = importlib.import_module("metroliza.ui.main_window")
    def fail_setup():
        raise RuntimeError("synthetic backend setup failure")

    monkeypatch.delenv(module.WARMUP_IN_THREAD_ENV, raising=False)
    monkeypatch.setattr(matplotlib_runtime, "configure_headless_matplotlib", fail_setup)
    monkeypatch.setattr(module, "FEATURE_IMPORT_WARMUP_MODULES", (("fake", "synthetic.fake"),))
    logged, finished = [], []
    monkeypatch.setattr(module, "CustomLogger", lambda error, **kwargs: logged.append(str(error)))
    window = module.MainWindow("test", None)
    window.schedule_feature_import_warmup(delay_ms=0, on_finished=lambda: finished.append(True))
    try:
        _wait_for_filter_shutdown(lambda: window._feature_import_warmup_completed)
        assert window._feature_import_warmup_failures == [{
            "module": "<warmup>", "error_type": "RuntimeError", "message": "synthetic backend setup failure",
        }]
        assert logged and "<warmup>" in logged[0]
        assert finished == [True]
        assert window.statusBar().currentMessage() == "Some tools will finish loading when opened."
    finally:
        window.close()


def test_modify_db_releases_record_indicator_when_install_raises(monkeypatch):
    module = importlib.import_module("metroliza.ui.modify_db")

    released, errors = [], []
    slot = SimpleNamespace(thread=object(), pending_specs=[], progress_dialog=object(),
                           state="loading", banner=SimpleNamespace(setVisible=lambda _visible: None))

    def fail_install(*args):
        raise ValueError("synthetic record install failure")

    def release(current):
        released.append(current.progress_dialog)
        current.progress_dialog = None

    host = SimpleNamespace(
        _current_record_slot=lambda *args: slot, _install_record_rows=fail_install,
        _release_record_progress=release, log_and_exit=errors.append,
    )
    module.ModifyDB._on_record_rows_loaded(host, "measurements", 1, [])
    assert slot.thread is None and slot.progress_dialog is None
    assert len(released) == 1 and isinstance(errors[0], ValueError)


@pytest.mark.parametrize("available", [True, False])
def test_benchmark_records_gc_policy_before_scenario_setup(qapplication_session, monkeypatch, tmp_path, available):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from metroliza.app import gc_policy
    from scripts import benchmark_ui_flows as harness

    events, result = [], {}
    app = SimpleNamespace(exec=lambda: None)
    ctx = SimpleNamespace(work=tmp_path / "scenario")
    scenario = SimpleNamespace(setup=lambda context: events.append("setup"))
    run = SimpleNamespace(start=lambda: None, result=result, finish=lambda: result)
    monkeypatch.setattr(harness, "_bootstrap_paths", lambda: None)
    monkeypatch.setattr(QApplication, "instance", lambda: app)
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
    monkeypatch.setattr(harness, "Context", lambda *args: ctx)
    monkeypatch.setattr(harness, "SCENARIOS", {"synthetic": lambda: scenario})
    monkeypatch.setattr(harness, "auto_answer_message_boxes", lambda *args: None)
    ctx.messages = []
    monkeypatch.setattr(harness, "_Run", lambda *args: run)
    monkeypatch.setattr(gc_policy, "install", lambda application: events.append("install"))
    monkeypatch.setattr(harness, "_KEEP_ALIVE", [])
    original_import = builtins.__import__

    def import_without_policy(name, *args, **kwargs):
        if name == "metroliza.app.gc_policy":
            raise ImportError("Older tree has no GC policy")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as import_patch:
        if not available:
            import_patch.setattr(builtins, "__import__", import_without_policy)
        output = harness.run_scenario(SimpleNamespace(scenario="synthetic"))
    assert output["gc_policy"] == ("installed" if available else "absent")
    assert events == (["install", "setup"] if available else ["setup"])


@pytest.mark.parametrize("module_name", ["export_dialog", "industrial_analytics_dialog", "parsing_dialog"])
def test_lightweight_progress_fallback_ignores_delayed_keywords(monkeypatch, module_name):
    # Execute the real fallback import block against the lightweight module it supports.
    path = Path(__file__).resolve().parents[1] / "src/metroliza/ui" / f"{module_name}.py"
    tree = ast.parse(path.read_text())
    block = next(node for node in tree.body if isinstance(node, ast.Try) and any(
        isinstance(child, ast.ImportFrom) and child.module == "metroliza.ui.worker_progress_dialog"
        for child in node.body
    ))
    calls = []
    stub = ModuleType("metroliza.ui.worker_progress_dialog")

    def create(parent, *, window_title, initial_status_text, on_cancel):
        calls.append((parent, window_title, initial_status_text, on_cancel))
        return "dialog", "label", "bar", None

    stub.create_worker_progress_dialog = create
    monkeypatch.setitem(sys.modules, stub.__name__, stub)
    namespace = {}
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(path), "exec"), namespace)
    for name in ("create_worker_progress_dialog", "create_delayed_worker_progress_dialog"):
        if name in namespace:
            assert namespace[name](
                "parent", window_title="test", initial_status_text="working", on_cancel=None,
                action_started_at=1.0, cancellable=False,
            ) == ("dialog", "label", "bar", None)
    assert calls and all(call == ("parent", "test", "working", None) for call in calls)
