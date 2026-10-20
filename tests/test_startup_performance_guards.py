import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _drop_leaked_qt_stubs() -> None:
    for module_name in ("PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets"):
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, "__file__", None) is None:
            sys.modules.pop(module_name, None)


def test_main_window_does_not_top_level_import_heavy_feature_stacks():
    module_ast = ast.parse(Path("src/metroliza/ui/main_window.py").read_text(encoding="utf-8"))
    blocked = {
        "metroliza.ui.export_dialog",
        "metroliza.ui.parsing_dialog",
        "metroliza.parsing.metadata_enrichment_thread",
        "metroliza.ui.modify_db",
        "metroliza.ui.about_window",
        "metroliza.ui.release_notes_dialog",
        "metroliza.ui.characteristic_mapping_dialog",
        "metroliza.ui.industrial_data_dialog",
        "metroliza.ui.industrial_analytics_dialog",
    }

    imported_modules = set()
    for node in module_ast.body:
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert imported_modules.isdisjoint(blocked)


def test_main_window_feature_warmup_uses_canonical_import_paths():
    _drop_leaked_qt_stubs()
    from metroliza.ui.main_window import FEATURE_IMPORT_WARMUP_MODULES

    warmed_modules = [module_name for _label, module_name in FEATURE_IMPORT_WARMUP_MODULES]

    assert warmed_modules
    assert all(module_name.startswith("metroliza.") for module_name in warmed_modules)
    assert all(not module_name.startswith("modules.") for module_name in warmed_modules)


def test_parse_contract_import_does_not_load_heavy_analytics_stacks():
    script = """
import json
import sys
from metroliza.shared.parse_contracts import ParseRequest, validate_parse_request

validate_parse_request(ParseRequest(source_directory="reports", db_file="metroliza.db"))
print(json.dumps({name: name in sys.modules for name in ("pandas", "matplotlib", "scipy")}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        env={**os.environ, "PYTHONPATH": "src:."},
        text=True,
        capture_output=True,
    )

    loaded_modules = json.loads(result.stdout)
    assert loaded_modules == {"pandas": False, "matplotlib": False, "scipy": False}


def test_startup_profile_writes_jsonl_events(tmp_path):
    profile_path = tmp_path / "startup-profile.jsonl"
    script = """
from modules.startup_profile import record_event
record_event("test_event", detail="ok")
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        env={
            **os.environ,
            "METROLIZA_STARTUP_PROFILE": "1",
            "METROLIZA_STARTUP_PROFILE_PATH": str(profile_path),
        },
    )

    events = [
        json.loads(line)
        for line in Path(profile_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events
    assert events[-1]["name"] == "test_event"
    assert events[-1]["detail"] == "ok"
    assert events[-1]["elapsed_ms"] >= 0
    # Wall-clock stamp used by the Windows startup route benchmark.
    assert abs(events[-1]["epoch_ms"] - time.time() * 1000) < 120_000


def test_windows_startup_benchmark_fails_on_crash_or_missing_profile_evidence():
    script = Path("scripts/measure_windows_startup.ps1").read_text(encoding="utf-8")

    assert "$RequiredStartupEvents = @(" in script
    assert "'first_event_loop_tick'" in script
    assert "function Assert-StartupRunSucceeded" in script
    assert "Startup run failed with exit code" in script
    assert "Startup profile JSONL was not created" in script
    assert "Startup profile JSONL is empty" in script
    assert "missing required event" in script
    assert "Assert-StartupRunSucceeded -Run $run -ProfilePath $profilePath -Events $events" in script


def _run_import_probe(script):
    return subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        env={
            **{key: value for key, value in os.environ.items() if key != "QT_QPA_PLATFORMTHEME"},
            "PYTHONPATH": "src:.",
            "QT_QPA_PLATFORM": "offscreen",
        },
        text=True,
        capture_output=True,
    )


def test_industrial_analytics_dialog_import_does_not_load_scipy_stats():
    script = """
import json
import sys
import metroliza.ui.industrial_analytics_dialog  # noqa: F401

print(json.dumps({
    "scipy.stats": "scipy.stats" in sys.modules,
    "hexafe_groupstats": "hexafe_groupstats" in sys.modules,
}))
"""
    loaded_modules = json.loads(_run_import_probe(script).stdout)

    assert loaded_modules == {"scipy.stats": False, "hexafe_groupstats": False}


def test_groupstats_adapter_loads_engine_on_first_analysis():
    script = """
import json
import sys
from metroliza.analytics.hexafe_groupstats_adapter import analyze_group_metric

before = "scipy.stats" in sys.modules
payload = analyze_group_metric(
    "Length",
    {"A": [1.0, 1.1, 1.2, 1.3, 1.4], "B": [2.0, 2.1, 2.2, 2.3, 2.4]},
    spec_records=[{"lsl": 0.5, "nominal": 1.5, "usl": 2.5}],
    backend="python",
)
print(json.dumps({
    "before": before,
    "after": "scipy.stats" in sys.modules,
    "has_rows": bool(payload["descriptive_stats"]),
}))
"""
    result = json.loads(_run_import_probe(script).stdout)

    assert result == {"before": False, "after": True, "has_rows": True}


def test_every_feature_warmup_import_is_safe_in_worker_thread(tmp_path):
    script = r'''
import importlib
import threading
from PyQt6 import QtCore, QtGui, QtWidgets
from metroliza.ui.main_window import FEATURE_IMPORT_WARMUP_MODULES
from metroliza.charts.matplotlib_runtime import configure_headless_matplotlib

# Retain exactly one QApplication in this fresh process, on the main thread.
app = QtWidgets.QApplication([])
main_ident = threading.get_ident()
errors = []

def guarded(original):
    def call(*args, **kwargs):
        if threading.get_ident() != main_ident:
            raise AssertionError("Qt access during worker import: " + str(original))
        return original(*args, **kwargs)
    return call

seen = set()
for module in (QtCore, QtGui, QtWidgets):
    for cls in vars(module).values():
        if not isinstance(cls, type) or cls in seen:
            continue
        if issubclass(cls, QtCore.QObject) or cls is QtGui.QPixmap:
            seen.add(cls)
            cls.__init__ = guarded(cls.__init__)
for cls in (QtCore.QCoreApplication, QtGui.QGuiApplication, QtWidgets.QApplication):
    cls.instance = staticmethod(guarded(cls.instance))
QtCore.QTimer.singleShot = staticmethod(guarded(QtCore.QTimer.singleShot))

def work():
    try:
        # Negative controls prove the guard reaches C++ constructors and app access.
        for create in (QtCore.QObject, QtWidgets.QWidget, QtCore.QTimer,
                       QtWidgets.QApplication.instance, QtGui.QPixmap):
            try:
                create()
            except AssertionError:
                pass
            else:
                raise AssertionError("Qt guard did not fire")
        configure_headless_matplotlib()
        for _, name in FEATURE_IMPORT_WARMUP_MODULES:
            importlib.import_module(name)
        import matplotlib
        assert matplotlib.get_backend().lower() == "agg"
    except BaseException as error:
        errors.append(error)

worker = threading.Thread(target=work)
worker.start()
worker.join(45)
assert not worker.is_alive(), "worker import hung"
assert not errors, repr(errors)
'''
    subprocess.run(
        [sys.executable, "-c", script], check=True, timeout=60,
        env={**os.environ, "HOME": str(tmp_path), "MPLBACKEND": "QtAgg"},
        capture_output=True, text=True,
    )


def test_concurrent_gui_and_warmup_imports_wait_for_complete_modules(tmp_path):
    # Fresh processes keep each import genuinely cold without deleting live Qt modules.
    script = r'''
import importlib
import importlib.abc
import importlib.machinery
import sys
import threading
from PyQt6.QtWidgets import QApplication
from metroliza.ui.main_window import warm_feature_imports
from metroliza.charts.matplotlib_runtime import configure_headless_matplotlib

app = QApplication([])
target, symbol, dependent = sys.argv[1:]
entered, release = threading.Event(), threading.Event()
errors, results = [], []

class Loader:
    def __init__(self, wrapped):
        self.wrapped = wrapped
    def create_module(self, spec):
        return self.wrapped.create_module(spec)
    def exec_module(self, module):
        entered.set()
        assert release.wait(10)
        self.wrapped.exec_module(module)

class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target_module=None):
        if fullname == target:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            spec.loader = Loader(spec.loader)
            return spec

sys.meta_path.insert(0, Finder())

def work():
    try:
        configure_headless_matplotlib()
        results.append(warm_feature_imports())
    except BaseException as error:
        errors.append(error)

worker = threading.Thread(target=work)
worker.start()
assert entered.wait(30), "target was never warmed"
assert symbol not in vars(sys.modules[target]), "fixture did not pause partial import"
# Release independently of the GUI event loop, which is about to wait in import.
timer = threading.Timer(0.025, release.set)
timer.start()
if dependent == "1":
    # The GUI imports a module that itself imports the in-flight feature module.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "synthetic_feature_open.py").write_text(
            "from " + target + " import " + symbol + "\n")
        sys.path.insert(0, directory)
        opened = importlib.import_module("synthetic_feature_open")
else:
    opened = importlib.import_module(target)
assert getattr(opened, symbol) is getattr(sys.modules[target], symbol)
worker.join(45)
timer.join(5)
assert not worker.is_alive(), "concurrent imports deadlocked"
assert not errors, repr(errors)
assert len(results) == 1 and not results[0][1], repr(results)
'''
    targets = (
        ("metroliza.ui.parsing_dialog", "ParsingDialog"),
        ("metroliza.ui.export_dialog", "ExportDialog"),
        ("metroliza.exporting.export_data_thread", "ExportDataThread"),
        ("metroliza.ui.realtime_industrial_monitoring_dialog", "RealtimeIndustrialMonitoringDialog"),
    )
    for repeat in range(3):
        for target, symbol in targets:
            subprocess.run(
                [sys.executable, "-c", script, target, symbol, str(repeat % 2)],
                check=True, timeout=90, capture_output=True, text=True,
                env={**os.environ, "HOME": str(tmp_path), "MPLBACKEND": "Agg"},
            )


def test_benchmark_warmup_is_opt_in(monkeypatch):
    from types import SimpleNamespace
    from scripts import benchmark_ui_flows as harness
    from metroliza.ui import main_window

    calls = []

    class Window:
        _feature_import_warmup_completed = True
        _feature_import_warmup_failures = []

        def __init__(self, *args):
            pass

        def show(self):
            calls.append("show")

        def schedule_feature_import_warmup(self, **kwargs):
            calls.append("warmup")

    monkeypatch.setattr(main_window, "MainWindow", Window)
    ctx = SimpleNamespace(args=SimpleNamespace(wait_warmup=False),
                          app=SimpleNamespace(processEvents=lambda: None), extra={},
                          pump=lambda ready: calls.append(ready()))
    harness._main_window(ctx)
    assert calls == ["show"]
    calls.clear()
    ctx.args.wait_warmup = True
    harness._main_window(ctx)
    assert calls == ["show", "warmup", True]
    assert ctx.extra == {"wait_warmup": True}


def test_startup_stall_probe_separates_post_paint_without_hiding_total(qapplication_session, monkeypatch):
    from metroliza.app import startup_stall_probe as probe

    clock = [0.0]
    events = []
    monkeypatch.setattr(probe.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(probe, "record_event", lambda name, **kw: events.append((name, kw)))
    total = probe.StallProbe(qapplication_session)
    monkeypatch.setattr(probe, "_PROBE", total)
    monkeypatch.setattr(probe, "_POST_PAINT_PROBE", None)
    clock[0] = 0.2
    total._tick()
    probe.begin_post_paint_probe()
    post_paint = probe._POST_PAINT_PROBE
    probe.begin_post_paint_probe()
    assert probe._POST_PAINT_PROBE is post_paint
    clock[0] = 0.23
    try:
        probe.record_summary("warmup_finished")
        name, fields = events[-1]
        assert name == "gui_stall_summary"
        assert fields["max_gap_ms"] == 200.0
        assert fields["blocked_ms"] == 220.0
        assert fields["post_paint"]["max_gap_ms"] == 30.0
        assert fields["post_paint"]["blocked_ms"] == 25.0
    finally:
        total._timer.stop()
        post_paint._timer.stop()
