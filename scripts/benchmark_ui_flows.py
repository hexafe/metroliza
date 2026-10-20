"""Measure user-visible UI flows end to end on synthetic data (Performance Boost STEP2).

Each scenario drives the real windows and workers the way a user does (button handlers on the
GUI thread), in a fresh process, and reports from the user action:

* ``first_feedback_ms``: the first new visible window (dialog, loading indicator) after the action;
* ``result_ms``: the scenario's "useful result" condition (populated dialog, finished worker and
  updated UI, written file);
* GUI-thread stalls: a 5 ms QTimer cannot fire while the GUI thread is busy, so the longest gap
  between its ticks is the longest time the window could not repaint, animate or take input;
* the loading indicator ("duck", ``metroliza.ui.worker_progress_dialog``): creation cost, when
  ``show()`` was called, when it actually became visible, how many animation frames it painted
  while visible (expected one per 100 ms) and whether it was released afterwards;
* peak RSS of the whole process tree and CPU time (self and children).

Usage (offscreen Qt, private HOME; all data synthetic):

    python scripts/benchmark_ui_flows.py prepare --data-dir DIR
    python scripts/benchmark_ui_flows.py run --scenario NAME --data-dir DIR --out result.json
    python scripts/benchmark_ui_flows.py suite --data-dir DIR --runs 3 --out-dir OUT [--only a,b]

Scenarios run sequentially (never two at once). Numbers are source runs on the machine at hand;
they are not packaged-Windows numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_TIMEOUT_S = 900.0
_KEEP_ALIVE: list[Any] = []
STALL_TICK_MS = 5


# ---------------------------------------------------------------- probes (no Qt at import time)


class Clock:
    t0: float | None = None

    @classmethod
    def start(cls) -> None:
        cls.t0 = time.perf_counter()

    @classmethod
    def ms(cls, t: float | None = None) -> float | None:
        if cls.t0 is None:
            return None
        return round(((time.perf_counter() if t is None else t) - cls.t0) * 1000.0, 1)


def _proc_tree_rss_bytes() -> int:
    me = os.getpid()
    page = os.sysconf("SC_PAGE_SIZE")
    parents: dict[int, tuple[int, int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii", errors="replace") as handle:
                fields = handle.read().rsplit(")", 1)[1].split()
            parents[int(entry)] = (int(fields[1]), int(fields[21]) * page)
        except (OSError, IndexError, ValueError):
            continue
    keep = {me}
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _rss) in parents.items():
            if ppid in keep and pid not in keep:
                keep.add(pid)
                changed = True
    return sum(parents[pid][1] for pid in keep if pid in parents)


class ResourceSampler(threading.Thread):
    def __init__(self, interval_s: float = 0.05) -> None:
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.peak_rss = 0
        self.start_rss = 0
        self.max_children = 0
        self._halt = threading.Event()

    def run(self) -> None:
        self.start_rss = _proc_tree_rss_bytes()
        while not self._halt.is_set():
            self.peak_rss = max(self.peak_rss, _proc_tree_rss_bytes())
            self._halt.wait(self.interval_s)

    def stop(self) -> dict[str, float]:
        self._halt.set()
        self.join(timeout=2)
        self.peak_rss = max(self.peak_rss, _proc_tree_rss_bytes())
        return {
            "rss_start_mb": round(self.start_rss / 2**20, 1),
            "rss_peak_tree_mb": round(self.peak_rss / 2**20, 1),
        }


def cpu_seconds() -> dict[str, float]:
    me, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"self": me.ru_utime + me.ru_stime, "children": children.ru_utime + children.ru_stime}


class StallProbe:
    """Records every GUI event-loop gap longer than 30 ms after ``Clock.start``."""

    def __init__(self, app) -> None:
        from PyQt6.QtCore import QTimer

        self.gaps: list[tuple[float, float]] = []
        self._last = time.perf_counter()
        self._timer = QTimer(app)
        self._timer.setInterval(STALL_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def reset(self) -> None:
        self.gaps.clear()
        self._last = time.perf_counter()

    def _tick(self) -> None:
        now = time.perf_counter()
        gap = (now - self._last) * 1000.0
        self._last = now
        if gap > 30 and Clock.t0 is not None:
            self.gaps.append((Clock.ms(now - gap / 1000.0), round(gap, 1)))

    def summary(self, until_ms: float | None) -> dict[str, Any]:
        self._tick()
        gaps = [g for g in self.gaps if until_ms is None or g[0] <= until_ms]
        longest = max(gaps, key=lambda g: g[1], default=(None, 0.0))
        return {
            "longest_stall_ms": longest[1],
            "longest_stall_at_ms": longest[0],
            "stall_total_ms": round(sum(g[1] - STALL_TICK_MS for g in gaps), 1),
            "stalls_ge_100ms": sum(1 for g in gaps if g[1] >= 100),
            "stalls_ge_250ms": sum(1 for g in gaps if g[1] >= 250),
            "stalls_ge_1000ms": sum(1 for g in gaps if g[1] >= 1000),
            "top_stalls": sorted(gaps, key=lambda g: -g[1])[:5],
        }


def _visibility_filter_class():
    from PyQt6.QtCore import QEvent, QObject

    class _Visibility(QObject):
        def __init__(self, record):
            super().__init__()
            self.record = record

        def eventFilter(self, obj, event):  # noqa: N802 - Qt API
            if event.type() == QEvent.Type.Show and self.record["visible_ms"] is None:
                self.record["visible_ms"] = Clock.ms()
            elif event.type() == QEvent.Type.Hide and self.record["visible_ms"] is not None:
                self.record["hidden_ms"] = Clock.ms()
            return False

    return _Visibility


class DuckProbe:
    """Wraps the loading-indicator factories in every module that imported them."""

    FACTORIES = ("create_worker_progress_dialog", "create_delayed_worker_progress_dialog")

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._filters: list[Any] = []
        self.patched_modules: list[str] = []

    def install(self) -> None:
        import metroliza.ui.worker_progress_dialog as wpd

        originals = {name: getattr(wpd, name) for name in self.FACTORIES}
        visibility_class = _visibility_filter_class()
        wrapped = {name: self._wrap_factory(name, factory, visibility_class)
                   for name, factory in originals.items()}
        self._patch_importers(wpd, originals, wrapped)

    def _wrap_factory(self, name, factory, visibility_class):
        probe = self

        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            dialog, label, bar, movie = factory(*args, **kwargs)
            record = {
                "factory": name, "title": kwargs.get("window_title"),
                "created_ms": Clock.ms(started),
                "create_cost_ms": round((time.perf_counter() - started) * 1000, 1),
                "show_called_ms": None, "visible_ms": None, "hidden_ms": None, "frames": [],
                "alive_at_end": None,
            }
            original_show = dialog.show

            def show(*a, **k):
                if record["show_called_ms"] is None:
                    record["show_called_ms"] = Clock.ms()
                return original_show(*a, **k)

            dialog.show = show
            visibility = visibility_class(record)
            dialog.installEventFilter(visibility)
            probe._filters.append(visibility)
            movie.frameChanged.connect(lambda _i, r=record: r["frames"].append(Clock.ms()))
            record["_dialog"] = dialog
            probe.records.append(record)
            return dialog, label, bar, movie

        wrapped.__wrapped_original__ = factory
        return wrapped

    def _patch_importers(self, factory_module, originals, wrapped) -> None:
        """Replace the factory names every loaded metroliza module imported."""
        by_identity = {id(original): name for name, original in originals.items()}
        for module_name, module in list(sys.modules.items()):
            if not module_name.startswith("metroliza.") or module is factory_module:
                continue
            for attribute, value in list(vars(module).items()):
                name = by_identity.get(id(value))
                if name is not None and value is originals[name]:
                    setattr(module, attribute, wrapped[name])
                    self.patched_modules.append(f"{module_name}.{attribute}")

    def summary(self) -> list[dict[str, Any]]:
        out = []
        for record in self.records:
            visible, hidden = record["visible_ms"], record["hidden_ms"]
            frames_visible = [f for f in record["frames"] if visible is not None and f >= visible
                              and (hidden is None or f <= hidden)]
            shown_for = (hidden if hidden is not None else Clock.ms()) - visible if visible is not None else 0.0
            longest_frame_gap = 0.0
            previous = visible
            for frame in frames_visible:
                longest_frame_gap = max(longest_frame_gap, frame - previous)
                previous = frame
            if visible is not None:
                longest_frame_gap = max(longest_frame_gap, (hidden or Clock.ms()) - (previous or visible))
            dialog = record.get("_dialog")
            alive = None
            try:
                from PyQt6 import sip

                alive = dialog is not None and not sip.isdeleted(dialog)
            except Exception:  # noqa: BLE001
                alive = None
            out.append({
                "factory": record["factory"], "title": record["title"],
                "create_cost_ms": record["create_cost_ms"], "created_ms": record["created_ms"],
                "show_called_ms": record["show_called_ms"], "visible_ms": visible,
                "hidden_ms": hidden, "visible_for_ms": round(shown_for, 1),
                "frames_while_visible": len(frames_visible),
                "frames_expected": int(shown_for // 100) if visible is not None else 0,
                "longest_frame_gap_ms": round(longest_frame_gap, 1),
                "frames_while_hidden": len(record["frames"]) - len(frames_visible),
                "dialog_alive_at_end": alive,
            })
        return out


class WindowWatch:
    """First Show of any new top-level widget after the action (generic first feedback)."""

    def __init__(self, app) -> None:
        from PyQt6.QtCore import QEvent, QObject

        self.first_window_ms: float | None = None
        self.windows: list[tuple[float, str]] = []
        watch = self

        class _Filter(QObject):
            def eventFilter(self, obj, event):  # noqa: N802 - Qt API
                if (event.type() == QEvent.Type.Show and Clock.t0 is not None
                        and getattr(obj, "isWindow", lambda: False)()):
                    stamp = Clock.ms()
                    watch.windows.append((stamp, type(obj).__name__))
                    if watch.first_window_ms is None:
                        watch.first_window_ms = stamp
                return False

        self._filter = _Filter()
        app.installEventFilter(self._filter)


def auto_answer_message_boxes(log: list[str]) -> None:
    """Never block on QMessageBox: answer Yes/Ok and record what was asked."""
    from PyQt6.QtWidgets import QMessageBox

    def record(kind):
        def answer(*args, **kwargs):
            text = next((a for a in args if isinstance(a, str)), "")
            log.append(f"{kind}@{Clock.ms()}: {text[:80]}")
            return QMessageBox.StandardButton.Yes if kind == "question" else QMessageBox.StandardButton.Ok
        return answer

    for kind in ("question", "information", "warning", "critical"):
        setattr(QMessageBox, kind, staticmethod(record(kind)))

    def exec_(self, *args, **kwargs):
        log.append(f"exec@{Clock.ms()}: {self.text()[:80]}")
        return QMessageBox.StandardButton.Ok

    QMessageBox.exec = exec_


# ---------------------------------------------------------------- scenarios


class Context:
    def __init__(self, app, args) -> None:
        self.app = app
        self.args = args
        self.data = Path(args.data_dir)
        self.work = Path(tempfile.mkdtemp(prefix="ui-flow-"))
        self.marks: dict[str, float] = {}
        self.messages: list[str] = []
        self.extra: dict[str, Any] = {}

    def mark(self, name: str) -> None:
        self.marks.setdefault(name, Clock.ms())

    def copy_db(self, name: str) -> str:
        source = self.data / name
        target = self.work / name
        shutil.copy2(source, target)
        return str(target)

    def pump(self, condition: Callable[[], bool], timeout_s: float = SCENARIO_TIMEOUT_S) -> None:
        """Process events (setup only, not timed) until ``condition``."""
        deadline = time.monotonic() + timeout_s
        while not condition():
            self.app.processEvents()
            time.sleep(0.005)
            if time.monotonic() > deadline:
                raise TimeoutError("setup condition not reached")


def _main_window(ctx: Context):
    from metroliza.ui.main_window import MainWindow

    window = MainWindow("STEP2 benchmark", None)
    window.show()
    ctx.app.processEvents()
    if getattr(ctx.args, "wait_warmup", False):
        window.schedule_feature_import_warmup(delay_ms=0)
        ctx.pump(lambda: window._feature_import_warmup_completed)
        if window._feature_import_warmup_failures:
            raise RuntimeError("Feature warm-up failed")
        ctx.extra["wait_warmup"] = True
    return window


class Scenario:
    name = ""
    flows: tuple[str, ...] = ()

    def setup(self, ctx: Context) -> None: ...

    def action(self, ctx: Context) -> None: ...

    def done(self, ctx: Context) -> bool:
        return True

    def finish(self, ctx: Context) -> dict[str, Any]:
        return {}


def _reports_workspace(ctx: Context, *, db: str, source: str):
    window = _main_window(ctx)
    window.set_db_file(db)
    window.set_directory(source)
    workspace = window._ensure_reports_workspace()
    ctx.app.processEvents()
    return window, workspace


def _wrap_method(obj, name: str, ctx: Context, mark: str) -> None:
    original = getattr(obj, name)

    def wrapped(*args, **kwargs):
        ctx.mark(f"{mark}_start")
        try:
            return original(*args, **kwargs)
        finally:
            ctx.mark(f"{mark}_end")

    setattr(obj, name, wrapped)


class ReportsScan(Scenario):
    """IMP-SCAN + IMP-META: "Review reports" until the table and the fast metadata read are done."""

    name = "reports_scan"
    flows = ("IMP-SCAN", "IMP-META", "IMP-REVIEW")

    def setup(self, ctx):
        db = str(ctx.work / "scan.sqlite")
        source = str(ctx.data / ctx.args.pdf_set)
        self.window, self.ws = _reports_workspace(ctx, db=db, source=source)
        _wrap_method(self.ws, "on_preflight_completed", ctx, "preflight_completed")
        ctx.pump(lambda: self.ws.scan_button.isEnabled(), 30)

    def action(self, ctx):
        self.ws.scan_button.click()

    def done(self, ctx):
        finished = ("preflight_completed_end" in ctx.marks and self.ws.preflight_thread is None
                    and self.ws.metadata_thread is None)
        if finished:
            ctx.mark("metadata_read_done")
        return finished

    def finish(self, ctx):
        model = getattr(getattr(self.ws, "report_planner", None), "model", None)
        rows = model.rowCount() if model is not None and hasattr(model, "rowCount") else None
        return {"review_rows": rows}


class ReportsImport(Scenario):
    """IMP-RUN: import every reviewed report (after a completed scan, setup not timed)."""

    name = "reports_import"
    flows = ("IMP-RUN",)

    def setup(self, ctx):
        self.db = str(ctx.work / "import.sqlite")
        source = str(ctx.data / ctx.args.pdf_set)
        self.window, self.ws = _reports_workspace(ctx, db=self.db, source=source)
        ctx.pump(lambda: self.ws.scan_button.isEnabled(), 30)
        self.ws.scan_button.click()
        ctx.pump(lambda: self.ws._preflight_result is not None and self.ws.preflight_thread is None
                 and self.ws.metadata_thread is None)
        ctx.pump(lambda: self.ws.parse_button.isEnabled(), 60)
        _wrap_method(self.ws, "on_parse_finished", ctx, "parse_finished")

    def action(self, ctx):
        self.ws.parse_button.click()

    def done(self, ctx):
        return "parse_finished_end" in ctx.marks and self.ws.parse_thread is None

    def finish(self, ctx):
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(self.db)) as connection:
            reports = connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone()[0]
            rows = connection.execute("SELECT COUNT(*) FROM report_measurements").fetchone()[0]
        if ctx.args.keep_db:
            shutil.copy2(self.db, ctx.args.keep_db)
        return {"reports": reports, "measurement_rows": rows}


class ModifyDbOpen(Scenario):
    """DB-OPEN: Reports -> "Modify Database" until the window shows its data."""

    name = "modify_db_open"
    flows = ("DB-OPEN",)

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))
        ctx.app.processEvents()

    def action(self, ctx):
        self.window.launch_modifydb_dialog()
        ctx.mark("handler_returned")

    def done(self, ctx):
        dialog = getattr(self.window, "modifydb_dialog", None)
        return dialog is not None and dialog.isVisible() and "handler_returned" in ctx.marks


class ModifyDbApply(Scenario):
    """DB-APPLY: rename one reference in the normalise table and apply (confirmation auto-yes)."""

    name = "modify_db_apply"
    flows = ("DB-APPLY", "DB-EDIT")

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))
        self.window.launch_modifydb_dialog()
        self.dialog = self.window.modifydb_dialog
        ctx.pump(lambda: self.dialog.isVisible())
        table = self.dialog.reference_table if hasattr(self.dialog, "reference_table") else None
        if table is None:
            from PyQt6.QtWidgets import QTableWidget

            table = self.dialog.findChildren(QTableWidget)[0]
        item = table.item(0, 1) or table.item(0, 0)
        item.setText(item.text() + "_RENAMED")
        ctx.extra["renamed_from_table"] = table.objectName() or type(table).__name__

    def action(self, ctx):
        self.dialog.apply_changes()
        ctx.mark("apply_returned")

    def done(self, ctx):
        return "apply_returned" in ctx.marks


def _export_dialog(ctx: Context, db_name: str):
    window = _main_window(ctx)
    window.set_db_file(ctx.copy_db(db_name))
    window.launch_export_dialog()
    dialog = window.export_dialog
    ctx.pump(lambda: dialog.isVisible(), 30)
    return window, dialog


class ExportOpen(Scenario):
    name = "export_open"
    flows = ("EXP-OPEN",)

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))

    def action(self, ctx):
        self.window.launch_export_dialog()
        ctx.mark("handler_returned")

    def done(self, ctx):
        dialog = getattr(self.window, "export_dialog", None)
        return dialog is not None and dialog.isVisible()


class FilterOpen(Scenario):
    """FLT-OPEN: Export -> Filter "Edit..." until every value list is loaded."""

    name = "filter_open"
    flows = ("FLT-OPEN",)

    def setup(self, ctx):
        self.window, self.export = _export_dialog(ctx, ctx.args.db)

    def action(self, ctx):
        self.export.open_filter_window()
        ctx.mark("handler_returned")

    def done(self, ctx):
        dialog = getattr(self.export, "filter_window", None)
        if dialog is None or not dialog.isVisible():
            return False
        loading = getattr(dialog, "_value_loader", None) or getattr(dialog, "_values_loader", None)
        running = loading is not None and getattr(loading, "isRunning", lambda: False)()
        return not running and getattr(dialog, "_values_loaded", True) and dialog.reference_list.count() > 0


class GroupingOpen(Scenario):
    name = "grouping_open"
    flows = ("GRP-OPEN",)

    def setup(self, ctx):
        self.window, self.export = _export_dialog(ctx, ctx.args.db)

    def action(self, ctx):
        self.export.open_grouping_window()
        ctx.mark("handler_returned")

    def done(self, ctx):
        dialog = getattr(self.export, "grouping_window", None)
        if dialog is None or not dialog.isVisible() or "handler_returned" not in ctx.marks:
            return False
        # The data loads in a worker thread; wait for the populated dialog (older builds load synchronously).
        if getattr(dialog, "is_loading_grouping", lambda: False)():
            return False
        ctx.mark("dialog_populated")
        return True


class CharacteristicMappingOpen(Scenario):
    """GRP-MAP: "Match Characteristic Names" (modal exec) until it is shown populated."""

    name = "char_mapping_open"
    flows = ("GRP-MAP",)

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))

    def action(self, ctx):
        self.window.launch_characteristic_mapping_dialog()

    def done(self, ctx):
        from PyQt6.QtWidgets import QApplication

        modal = QApplication.activeModalWidget()
        if modal is not None and type(modal).__name__ == "CharacteristicMappingDialog":
            ctx.mark("dialog_visible")
            # The names load in a worker thread: finish when that load has completed, whether or not the
            # database holds any names. Older builds load synchronously and have no loading flag; there the
            # populated table is the completion signal.
            is_loading = getattr(modal, "is_loading_source_options", None)
            if is_loading is not None:
                if is_loading():
                    return False
            elif modal.metric_table.rowCount() == 0:
                return False
            ctx.mark("dialog_populated")
            modal.reject()
            return True
        return False


class ExportRun(Scenario):
    """EXP-RUN: Export with a preset until the completion message (first click in this process)."""

    name = "export_run"
    flows = ("EXP-RUN", "EXP-RESULT")

    def setup(self, ctx):
        self.window, self.export = _export_dialog(ctx, ctx.args.db)
        from metroliza.exporting.export_preset_utils import get_export_preset_label

        self.export.preset_combobox.setCurrentText(get_export_preset_label(ctx.args.preset))
        self.output = ctx.work / ("export.html" if ctx.args.preset == "html_dashboard_only" else "export.xlsx")
        self.export.excel_file = str(self.output)
        self.export._set_path_field_value(self.export.excel_file_text_label, str(self.output))
        ctx.app.processEvents()
        _wrap_method(self.export, "on_export_finished", ctx, "export_finished")
        ctx.extra["export_module_loaded_before_click"] = "metroliza.exporting.export_data_thread" in sys.modules

    def action(self, ctx):
        self.export.show_loading_screen()
        ctx.mark("handler_returned")

    def done(self, ctx):
        thread = getattr(self.export, "export_thread", None)
        running = thread is not None and thread.isRunning()
        return "export_finished_end" in ctx.marks and not running

    def finish(self, ctx):
        outputs = sorted(p.name for p in ctx.work.iterdir() if p.suffix in {".xlsx", ".html"})
        size = sum((ctx.work / name).stat().st_size for name in outputs)
        return {"outputs": outputs, "output_bytes": size, "preset": ctx.args.preset}


class ThemeSwitch(Scenario):
    """SHELL-THEME: switch to dark with the Reports review table populated."""

    name = "theme_switch"
    flows = ("SHELL-THEME",)

    def setup(self, ctx):
        source = str(ctx.data / ctx.args.pdf_set)
        self.window, self.ws = _reports_workspace(ctx, db=str(ctx.work / "t.sqlite"), source=source)
        ctx.pump(lambda: self.ws.scan_button.isEnabled(), 30)
        self.ws.scan_button.click()
        ctx.pump(lambda: self.ws._preflight_result is not None and self.ws.preflight_thread is None
                 and self.ws.metadata_thread is None)

    def action(self, ctx):
        self.window._set_theme_mode("dark")
        ctx.mark("handler_returned")

    def done(self, ctx):
        return "handler_returned" in ctx.marks


def _patch_file_dialog(paths: list[str]) -> None:
    from PyQt6.QtWidgets import QFileDialog

    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (list(paths), ""))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (paths[0], ""))


def _csv_dialog(ctx: Context):
    from metroliza.ui.industrial_analytics_dialog import SOURCE_TABULAR_FILE, IndustrialAnalyticsDialog

    window = _main_window(ctx)
    csv = ctx.work / ctx.args.csv
    shutil.copy2(ctx.data / ctx.args.csv, csv)
    _patch_file_dialog([str(csv)])
    dialog = IndustrialAnalyticsDialog(window, source_kind=SOURCE_TABULAR_FILE)
    dialog.show()
    ctx.app.processEvents()
    return window, dialog


def _csv_loaded(dialog) -> bool:
    return (dialog.tabular_load_result is not None and dialog.tabular_load_thread is None
            and dialog.metrics_list.count() > 0)


class CsvLoad(Scenario):
    """CSV-02 + CSV-03: pick a CSV in CSV Summary until its metrics are listed."""

    name = "csv_load"
    flows = ("CSV-02", "CSV-03")

    def setup(self, ctx):
        self.window, self.dialog = _csv_dialog(ctx)

    def action(self, ctx):
        self.dialog.select_input_file()
        ctx.mark("handler_returned")

    def done(self, ctx):
        return _csv_loaded(self.dialog)

    def finish(self, ctx):
        return {"metrics_listed": self.dialog.metrics_list.count(), "csv": ctx.args.csv}


class CsvAnalytics(Scenario):
    """CSV-09: "Create analytics" (dashboard, plus workbook when enabled) until it finishes."""

    name = "csv_analytics"
    flows = ("CSV-09", "CSV-05")

    def setup(self, ctx):
        self.window, self.dialog = _csv_dialog(ctx)
        self.dialog.select_input_file()
        ctx.pump(lambda: _csv_loaded(self.dialog))
        self.dialog.output_dashboard_file = str(ctx.work / "dashboard.html")
        self.dialog.output_workbook_file = str(ctx.work / "summary.xlsx")
        _wrap_method(self.dialog, "on_analytics_finished", ctx, "analytics_finished")

    def action(self, ctx):
        self.dialog.handle_start_button()
        ctx.mark("handler_returned")

    def done(self, ctx):
        return "analytics_finished_end" in ctx.marks and self.dialog.analytics_thread is None

    def finish(self, ctx):
        outputs = sorted(p.name for p in ctx.work.iterdir() if p.suffix in {".xlsx", ".html"})
        return {"outputs": outputs, "output_bytes": sum((ctx.work / n).stat().st_size for n in outputs)}


class IndustrialOpen(Scenario):
    """IND-01: open Industrial Data on a database holding a synthetic production cache."""

    name = "industrial_open"
    flows = ("IND-01",)

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))

    def action(self, ctx):
        self.window.launch_industrial_data_dialog()
        ctx.mark("handler_returned")

    def done(self, ctx):
        dialog = getattr(self.window, "industrial_data_dialog", None)
        return dialog is not None and dialog.isVisible() and "handler_returned" in ctx.marks

    def finish(self, ctx):
        # The Oznak status is computed in a background thread after the dialog is shown; let it finish
        # (not timed) so no worker is still running when the measurement ends. Older builds set it at once.
        dialog = getattr(self.window, "industrial_data_dialog", None)
        label = getattr(dialog, "oznak_label", None)
        deadline = time.monotonic() + 10
        while label is not None and "checking" in label.text().lower() and time.monotonic() < deadline:
            ctx.app.processEvents()
            time.sleep(0.005)
        return {"oznak_status": label.text() if label is not None else None}


class IndustrialBridge(Scenario):
    """IND-05: Industrial Data -> "CSV Summary..." until the analytics dialog is shown."""

    name = "industrial_bridge"
    flows = ("IND-05",)

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))
        self.window.launch_industrial_data_dialog()
        self.dialog = self.window.industrial_data_dialog
        ctx.pump(lambda: self.dialog.isVisible())

    def action(self, ctx):
        self.dialog.open_analytics_dialog()

    def done(self, ctx):
        from PyQt6.QtWidgets import QApplication

        modal = QApplication.activeModalWidget()
        if modal is not None and type(modal).__name__ == "IndustrialAnalyticsDialog":
            ctx.mark("analytics_dialog_visible")
            modal.reject()
            return True
        return False


class RealtimeOpen(Scenario):
    """RT-01: first open of the Realtime Monitor in this process."""

    name = "realtime_open"
    flows = ("RT-01",)

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))
        ctx.extra["realtime_module_loaded_before_click"] = (
            "metroliza.ui.realtime_industrial_monitoring_dialog" in sys.modules)

    def action(self, ctx):
        self.window.launch_realtime_industrial_monitoring_dialog()
        ctx.mark("handler_returned")

    def done(self, ctx):
        dialog = getattr(self.window, "realtime_monitoring_dialog", None) or getattr(
            self.window, "realtime_industrial_monitoring_dialog", None)
        if dialog is None:
            from PyQt6.QtWidgets import QApplication

            dialog = next((w for w in QApplication.topLevelWidgets()
                           if type(w).__name__ == "RealtimeIndustrialMonitoringDialog"), None)
        return dialog is not None and dialog.isVisible() and "handler_returned" in ctx.marks


class ModifyDbRecords(Scenario):
    """DB-RECORDS: Modify DB -> measurement rows tab, then one filter keystroke."""

    name = "modify_db_records"
    flows = ("DB-RECORDS",)

    def setup(self, ctx):
        self.window = _main_window(ctx)
        self.window.set_db_file(ctx.copy_db(ctx.args.db))
        self.window.launch_modifydb_dialog()
        self.dialog = self.window.modifydb_dialog
        ctx.pump(lambda: self.dialog.isVisible())
        self.tabs = self.dialog.tab_widget
        self.index = self.tabs.count() - 1  # the last tab: measurement rows
        self.filtered = False

    def action(self, ctx):
        self.tabs.setCurrentIndex(self.index)

    def done(self, ctx):
        from PyQt6.QtWidgets import QLineEdit, QTableView

        page = self.tabs.widget(self.index)
        views = page.findChildren(QTableView)
        rows = views[0].model().rowCount() if views and views[0].model() is not None else 0
        if not self.filtered:
            if rows > 0:
                ctx.mark("rows_loaded")
                ctx.extra["rows_loaded"] = rows
                edits = page.findChildren(QLineEdit)
                if edits:
                    self.filtered = True
                    ctx.mark("filter_typed")
                    edits[0].setText("X")
            return False
        if rows != ctx.extra["rows_loaded"]:
            ctx.mark("filter_applied")
            ctx.extra["rows_after_filter"] = rows
            return True
        return False


SCENARIOS: dict[str, type[Scenario]] = {
    cls.name: cls
    for cls in (ReportsScan, ReportsImport, ModifyDbOpen, ModifyDbApply, ModifyDbRecords, ExportOpen,
                FilterOpen, GroupingOpen, CharacteristicMappingOpen, ExportRun, ThemeSwitch, CsvLoad,
                CsvAnalytics, IndustrialOpen, IndustrialBridge, RealtimeOpen)
}


# ---------------------------------------------------------------- runner


def _profile_worker_class(spec: str, sink: list[str]) -> None:
    """Wrap ``module:QThreadClass.run`` in cProfile; each finished run appends its report."""
    import cProfile
    import importlib
    import io
    import pstats

    module_name, _, class_name = spec.partition(":")
    worker_class = getattr(importlib.import_module(module_name), class_name)
    original_run = worker_class.run

    def profiled_run(self, *a, **k):
        worker_profiler = cProfile.Profile()
        worker_profiler.enable()
        try:
            return original_run(self, *a, **k)
        finally:
            worker_profiler.disable()
            stream = io.StringIO()
            pstats.Stats(worker_profiler, stream=stream).sort_stats("cumulative").print_stats(60)
            sink.append(stream.getvalue())

    worker_class.run = profiled_run


def _profile_report(profiler, top: int) -> str:
    import io
    import pstats

    profiler.disable()
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(top)
    return stream.getvalue()


def _bootstrap_paths() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    for path in (str(ROOT), str(ROOT / "src")):
        if path not in sys.path:
            sys.path.insert(0, path)


class _Run:
    """One scenario run: probes, the poll loop and the result record."""

    def __init__(self, app, ctx, scenario, args) -> None:
        from PyQt6.QtCore import QTimer

        self.app, self.ctx, self.scenario, self.args = app, ctx, scenario, args
        self.duck = DuckProbe()
        self.duck.install()
        self.watch = WindowWatch(app)
        self.stall = StallProbe(app)
        self.sampler = ResourceSampler()
        self.result: dict[str, Any] = {"scenario": scenario.name, "flows": list(scenario.flows),
                                       "status": "ok"}
        self.cpu0: dict[str, float] | None = None
        self.deadline = 0.0
        self.thread_profiles: list[str] = []
        if getattr(args, "profile_thread", ""):
            _profile_worker_class(args.profile_thread, self.thread_profiles)
        self.profiler = None
        if getattr(args, "profile", 0):
            import cProfile

            self.profiler = cProfile.Profile()
        self.poll_timer = QTimer(app)
        self.poll_timer.setInterval(10)
        self.poll_timer.timeout.connect(self.poll)

    def fail(self, error: str) -> None:
        self.result.update(status="failed", error=error)

    def poll(self) -> None:
        from PyQt6.QtCore import QTimer

        try:
            finished = self.scenario.done(self.ctx)
        except Exception as error:  # noqa: BLE001
            self.fail(f"done(): {type(error).__name__}: {error}")
            finished = True
        if finished:
            self.ctx.mark("result")
            self.poll_timer.stop()
            QTimer.singleShot(50, self.app.quit)
        elif time.monotonic() > self.deadline:
            self.fail("timeout")
            self.poll_timer.stop()
            self.app.quit()

    def start(self) -> None:
        self.sampler.start()
        self.cpu0 = cpu_seconds()
        self.deadline = time.monotonic() + SCENARIO_TIMEOUT_S
        Clock.start()
        self.stall.reset()
        self.ctx.mark("action")
        self.poll_timer.start()
        if self.profiler is not None:
            self.profiler.enable()
        try:
            self.scenario.action(self.ctx)
        except Exception as error:  # noqa: BLE001
            self.fail(f"action(): {type(error).__name__}: {error}")
            self.app.quit()

    def finish(self) -> dict[str, Any]:
        result, ctx = self.result, self.ctx
        if self.profiler is not None:
            result["gui_thread_profile"] = _profile_report(self.profiler, int(self.args.profile))
        if self.thread_profiles:
            result["worker_thread_profiles"] = self.thread_profiles
        result_ms = ctx.marks.get("result")
        cpu1 = cpu_seconds()
        try:
            result.update(self.scenario.finish(ctx))
        except Exception as error:  # noqa: BLE001
            result.setdefault("warnings", []).append(f"finish(): {type(error).__name__}: {error}")
        cpu0 = self.cpu0 or cpu1
        result.update({
            "result_ms": result_ms,
            "first_feedback_ms": self.watch.first_window_ms,
            "windows_shown": self.watch.windows[:12],
            "marks_ms": ctx.marks,
            "cpu_self_s": round(cpu1["self"] - cpu0["self"], 2),
            "cpu_children_s": round(cpu1["children"] - cpu0["children"], 2),
            "message_boxes": ctx.messages,
            "duck": self.duck.summary(),
            "duck_patched": self.duck.patched_modules,
            **self.stall.summary(result_ms),
            **self.sampler.stop(),
            **ctx.extra,
        })
        return result


def run_scenario(args) -> dict[str, Any]:
    _bootstrap_paths()
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    ctx = Context(app, args)
    scenario = SCENARIOS[args.scenario]()
    auto_answer_message_boxes(ctx.messages)
    setup_started = time.perf_counter()
    scenario.setup(ctx)
    setup_ms = round((time.perf_counter() - setup_started) * 1000, 1)
    run = _Run(app, ctx, scenario, args)
    run.result["setup_ms"] = setup_ms
    QTimer.singleShot(300, run.start)
    app.exec()
    result = run.finish()
    shutil.rmtree(ctx.work, ignore_errors=True)
    # Keep every window, worker and probe alive until os._exit: destroying Qt objects from Python
    # in arbitrary order after the measurement crashed (SIGSEGV) in teardown, not in the scenario.
    _KEEP_ALIVE.extend((app, ctx, scenario, run))
    return result


def private_environment(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("METROLIZA_", "QT_QPA_PLATFORMTHEME"))}
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        env.pop(name, None)
    env.update(HOME=str(home), QT_QPA_PLATFORM="offscreen", MPLBACKEND="Agg",
               METROLIZA_LICENSE_VERIFICATION="0", PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    return env


def loadavg() -> list[float]:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return []


def suite(args) -> int:
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path(args.plan).read_text()) if args.plan else DEFAULT_PLAN
    only = set(filter(None, (args.only or "").split(",")))
    records = []
    for entry in plan:
        label = entry["label"]
        if only and label not in only:
            continue
        for run in range(1, args.runs + 1):
            home = Path(tempfile.mkdtemp(prefix="ui-flow-home-"))
            target = out / f"{label}-{run}.json"
            command = [sys.executable, str(Path(__file__).resolve()), "run", "--data-dir", args.data_dir,
                       "--out", str(target), *entry["args"]]
            before = loadavg()
            started = time.perf_counter()
            completed = subprocess.run(command, env=private_environment(home), cwd=str(home),
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       timeout=SCENARIO_TIMEOUT_S + 120)
            wall = round((time.perf_counter() - started) * 1000)
            shutil.rmtree(home, ignore_errors=True)
            record = json.loads(target.read_text()) if target.exists() else {"status": "failed"}
            record.update(label=label, run=run, process_wall_ms=wall, loadavg_before=before,
                          exit_code=completed.returncode)
            if completed.returncode != 0:
                record["log_tail"] = completed.stdout[-2000:]
            target.write_text(json.dumps(record, indent=1, default=str))
            records.append(record)
            print(f"{label} #{run}: {record.get('status')} result={record.get('result_ms')} ms "
                  f"stall={record.get('longest_stall_ms')} ms rss={record.get('rss_peak_tree_mb')} MB "
                  f"load={before}", flush=True)
    (out / "suite.json").write_text(json.dumps(records, indent=1, default=str))
    return 0


DEFAULT_PLAN = [
    {"label": "reports_scan_1500", "args": ["--scenario", "reports_scan", "--pdf-set", "pdf_1500"]},
    {"label": "reports_import_1500", "args": ["--scenario", "reports_import", "--pdf-set", "pdf_1500"]},
    {"label": "modify_db_open", "args": ["--scenario", "modify_db_open"]},
    {"label": "modify_db_apply", "args": ["--scenario", "modify_db_apply"]},
    {"label": "export_open", "args": ["--scenario", "export_open"]},
    {"label": "filter_open", "args": ["--scenario", "filter_open"]},
    {"label": "grouping_open", "args": ["--scenario", "grouping_open"]},
    {"label": "char_mapping_open", "args": ["--scenario", "char_mapping_open"]},
    {"label": "export_main_plots", "args": ["--scenario", "export_run", "--preset", "fast_diagnostics"]},
    {"label": "theme_switch_1500", "args": ["--scenario", "theme_switch", "--pdf-set", "pdf_1500"]},
]


def prepare(args) -> int:
    """Synthetic fixtures: a CSV Summary input and a production cache inside a report DB copy."""
    for path in (str(ROOT), str(ROOT / "src")):
        if path not in sys.path:
            sys.path.insert(0, path)
    import numpy as np

    data = Path(args.data_dir)
    rng = np.random.default_rng(7)
    rows = int(args.csv_rows)
    csv = data / f"csv_{rows // 1000}k.csv"
    days = np.datetime64("2025-01-01") + rng.integers(0, 365, rows).astype("timedelta64[D]")
    lines = np.array(["LINE_A", "LINE_B", "LINE_C"])[rng.integers(0, 3, rows)]
    with csv.open("w", encoding="utf-8", newline="") as handle:
        header = ["PART", "DATE", "LINE", *(f"DIM_{i:02d}" for i in range(1, 9))]
        handle.write(",".join(header) + "\n")
        dims = np.round(rng.normal(25.0, 0.2, (rows, 8)), 4)
        for index in range(rows):
            values = ",".join(f"{v:.4f}" for v in dims[index])
            handle.write(f"P-{index:06d},{days[index]},{lines[index]},{values}\n")
    print(f"wrote {csv} ({rows} rows)")

    source_db = data / args.industrial_db
    if source_db.exists():
        from scripts.benchmark_paths import _industrial_cache_rows
        from metroliza.industrial.industrial_data_repository import IndustrialDataRepository

        target = data / f"ind_{args.industrial_rows // 1000}k.sqlite"
        shutil.copy2(source_db, target)
        repository = IndustrialDataRepository(str(target))
        repository.ensure_schema()
        profile = repository.upsert_source_profile(
            profile_key="step2_source", profile_name="STEP2 synthetic source", source_db_alias="step2_db",
            database_type="sqlite", source_object_name="synthetic_records",
            allowed_columns=("source_record_key", "process_timestamp", "reference", "line", "station",
                             *(f"metric_{index:02d}" for index in range(1, 21))),
            timestamp_column="process_timestamp", default_pagination_column="source_record_key",
        )
        run_id = repository.create_sync_run(source_profile_id=profile.id, filters={"step2": True},
                                            diagnostics={})
        result = repository.upsert_industrial_records_from_rows(
            source_profile_id=profile.id, source_db_alias=profile.source_db_alias,
            rows=_industrial_cache_rows(start_index=1, row_count=int(args.industrial_rows), dynamic_fields=20),
            sync_run_id=run_id,
        )
        repository.finish_sync_run(sync_run_id=run_id, status="succeeded",
                                   row_count=int(result.get("processed", 0)), diagnostics={})
        print(f"wrote {target}: {result}")
    else:
        print(f"skipped the production cache: {source_db} is missing (run the 1500 import first)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--wait-warmup", action="store_true",
                     help="finish feature warm-up during setup, before timing the first action")
    run.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    run.add_argument("--data-dir", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--db", default="db_1500.sqlite", help="fixture DB name in --data-dir (copied)")
    run.add_argument("--pdf-set", default="pdf_small")
    run.add_argument("--preset", default="fast_diagnostics")
    run.add_argument("--keep-db", default="", help="reports_import: copy the resulting DB here")
    run.add_argument("--csv", default="csv_100k.csv", help="CSV fixture name in --data-dir")
    run.add_argument("--profile-thread", default="",
                     help="module:QThreadClass whose run() is profiled (worker threads)")
    run.add_argument("--profile", type=int, default=0,
                     help="cProfile the GUI thread from the action; keep N top cumulative rows")
    prep = sub.add_parser("prepare")
    prep.add_argument("--data-dir", required=True)
    prep.add_argument("--csv-rows", type=int, default=100_000)
    prep.add_argument("--industrial-rows", type=int, default=50_000)
    prep.add_argument("--industrial-db", default="db_1500.sqlite",
                      help="report DB that receives the synthetic production cache (copied)")
    many = sub.add_parser("suite")
    many.add_argument("--data-dir", required=True)
    many.add_argument("--out-dir", required=True)
    many.add_argument("--runs", type=int, default=3)
    many.add_argument("--only", default="")
    many.add_argument("--plan", default="")
    args = parser.parse_args(argv)
    if args.command == "suite":
        return suite(args)
    if args.command == "prepare":
        return prepare(args)
    result = run_scenario(args)
    Path(args.out).write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({k: result.get(k) for k in ("scenario", "status", "result_ms", "first_feedback_ms",
                                                  "longest_stall_ms", "rss_peak_tree_mb", "error")}))
    sys.stdout.flush()
    sys.stderr.flush()
    # Leave without interpreter/Qt teardown: the measurement is complete and written, and tearing
    # down live windows, threads and movies in arbitrary order can crash at exit.
    os._exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
