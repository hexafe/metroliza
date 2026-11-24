"""Opt-in synthetic GUI journeys in the actual application, never normal startup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

GATE = "METROLIZA_RECIPE_QUALIFICATION_ROOT"
RECEIPT = "recipe-qualification.json"
CASES = ("main", "html", "larger")
TIMEOUT_SECONDS = 900
FAILURES = frozenset({"control_missing", "save_failed", "reopen_failed", "launch_failed",
    "form_mismatch", "start_failed", "screenshot_failed", "scenario_failed",
    "unexpected_decision", "timeout", "cleanup_timeout"})


def write_reports(source: Path) -> None:
    """Author ten in-range-date measurements plus two explicit date exclusions."""
    from metroliza.parsing.pdf_backend import require_pdf_backend
    backend = require_pdf_backend()
    source.mkdir()
    groups = {"A": (9.90, 9.92, 9.94, 9.96, 10.02, 9.92),
              "B": (10.02, 10.04, 10.06, 10.08, 10.10, 10.09)}
    for group_index, (revision, values) in enumerate(groups.items()):
        for index, measured in enumerate(values):
            with backend.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), "METROLIZA PDF PARSER SMOKE\nCMM REPORT\n"
                    "#SMOKE FEATURE\nDIM\n"
                    f"X 10 0.5 -0.5 {measured:.2f} {measured - 10:.2f} 0", fontsize=8)
                for text, x, y in (("PART NAME", 150, 16), ("Recipe Part", 208, 16),
                                  ("DRAWING No", 296, 46), ("ABCDE12345", 358, 46),
                                  ("DRAWING REV", 167, 46), (revision, 232, 46)):
                    page.insert_text((x, y), text, fontsize=6)
                sample = group_index * 6 + index
                page.insert_text((20, 62), f"SAMPLE NUMBER: {sample}", fontsize=6)
                report_date = "2024-01-02" if index == 5 else "2024-01-01"
                document.save(str(source / f"ABCDE12345_Recipe_Part_{report_date}_{sample}.pdf"))


def _button(widget, label):
    from PyQt6.QtWidgets import QPushButton
    found = [button for button in widget.findChildren(QPushButton) if button.text() == label]
    if len(found) != 1 or not found[0].isVisible():
        raise ValueError("control_missing")
    return found[0]


def _paint_ready(widget, window) -> bool:
    """Require a visible, enabled control wholly inside all enclosing viewports."""
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtWidgets import QAbstractScrollArea
    if not widget.isVisible() or not widget.isEnabled():
        return False
    if widget.rect().isEmpty() or widget.visibleRegion().isEmpty():
        return False
    bounds = QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())
    if not window.rect().contains(bounds):
        return False
    parent = widget.parentWidget()
    while parent is not None and parent is not window:
        if isinstance(parent, QAbstractScrollArea):
            viewport = parent.viewport()
            bounds = QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size())
            if not viewport.rect().contains(bounds):
                return False
        parent = parent.parentWidget()
    return True


class _Probe:
    def __init__(self, window, root: Path):
        from PyQt6.QtCore import QTimer
        from metroliza.app.build_provenance import load_build_provenance
        self.window, self.root = window, root
        self.workspace = window._ensure_recipe_workspace()
        self.controller, self.page = self.workspace.controller, self.workspace.run_page
        self.started = time.monotonic()
        self.index, self.waiting = 0, False
        self.phase, self._home_captured = "home_select", False
        self.reason, self.cancel_started = "none", None
        provenance = load_build_provenance()
        self.receipt = {"schema_version": 1, "status": "running", "reason": "none",
            "packaged": bool(getattr(sys, "frozen", False)), "native_windows": sys.platform == "win32",
            "source_sha": provenance.git_sha, "source_dirty": provenance.dirty,
            "qpa": "other", "scale": float(window.devicePixelRatioF()), "cases": [],
            "cleanup": "pending", "stage": "setup"}
        self.timer = QTimer(window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.controller.failed.connect(self.failed)

    def failed(self, _private_code):
        self.reason = "scenario_failed"

    def screenshot(self, name):
        if not self.window.grab().save(str(self.root / name), "PNG"):
            raise ValueError("screenshot_failed")

    def larger(self):
        from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
        from metroliza.recipes.storage import RecipeStore, StoredRecipe
        from metroliza.ui.recipe_editor import RecipeEditor
        store = RecipeStore(self.root / "private")
        editor = RecipeEditor(StoredRecipe(REPORTS_EXCEL_MAIN, builtin_binding(REPORTS_EXCEL_MAIN,
            str(self.root / "reports"), str(self.root / "larger.xlsx"))), store, self.window)
        editor.show()
        editor.name.setText("Synthetic larger flow")
        editor.dates.setChecked(True)
        editor.groups.setText("REVISION")
        editor.html.setChecked(True)
        saved = []
        editor.saved.connect(saved.append)
        _button(editor, "Zapisz recepturę").click()
        if len(saved) != 1:
            raise ValueError("save_failed")
        editor.close()
        reopened = RecipeStore(self.root / "private").load(saved[0].definition.recipe_id)
        if reopened != saved[0]:
            raise ValueError("reopen_failed")
        if not self.controller.launch(reopened.definition, reopened.binding):
            raise ValueError("launch_failed")

    def show_home(self):
        self.window._show_workspace_page("home")
        self.phase = "home_ready"

    def home_ready(self):
        from metroliza.recipes.builtin_recipes import BUILTIN_LABELS, QUICK_REPORT_RECIPES
        try:
            buttons = [_button(self.workspace.quick, BUILTIN_LABELS[recipe.recipe_id])
                       for recipe in QUICK_REPORT_RECIPES]
        except ValueError:
            return  # A normal Qt turn may still be making the Home controls visible.
        if not all(_paint_ready(button, self.window) for button in buttons):
            return
        if not self._home_captured:
            self.screenshot("home.png")
            self._home_captured = True
        self.phase = "select"

    def begin(self):
        from metroliza.recipes.builtin_recipes import BUILTIN_LABELS
        case = CASES[self.index]
        if case == "larger":
            self.larger()
        else:
            identity = "reports_excel_main" if case == "main" else "reports_dashboard_html"
            _button(self.workspace.quick, BUILTIN_LABELS[identity]).click()
        self.phase = "fill"  # Return to Qt after selection creates the form widgets.

    def _expected_fields(self):
        from metroliza.recipes.contracts import ParameterKey
        expected = {ParameterKey.INPUT_FOLDER, ParameterKey.OUTPUT_FILE}
        if CASES[self.index] == "larger":
            expected.update({ParameterKey.DATE_FROM, ParameterKey.DATE_TO})
        return expected

    def form_ready(self):
        controls = [editor for editor, _spec in self.page.fields.values()]
        return bool(controls) and all(_paint_ready(control, self.window)
                                     for control in (*controls, self.page.start_button))

    def fill(self):
        from metroliza.recipes.contracts import ParameterKey
        if set(self.page.fields) != self._expected_fields():
            raise ValueError("form_mismatch")
        if not self.form_ready():
            return
        case = CASES[self.index]
        suffix = ".html" if case == "html" else ".xlsx"
        values = {ParameterKey.INPUT_FOLDER: str(self.root / "reports"),
                  ParameterKey.OUTPUT_FILE: str(self.root / (case + suffix)),
                  ParameterKey.DATE_FROM: "2024-01-01", ParameterKey.DATE_TO: "2024-01-01"}
        for key, (editor, _spec) in self.page.fields.items():
            editor.setText(values[key])
        self.phase = "capture_start"  # Filling also changes/wraps the plan preview.

    def capture_start(self):
        if not self.form_ready():
            return
        case = CASES[self.index]
        self.screenshot(case + "-form.png")
        self.receipt["cases"].append({"case": case, "state": "running",
            "prompt_fields": len(self._expected_fields()), "start_clicks": 1})
        self.phase, self.waiting = "running", True
        self.page.start_button.click()
        if self.controller._task is None:
            raise ValueError("start_failed")

    def observe(self):
        from metroliza.recipes.run_state import RunState
        record = self.controller.last_record
        if self.controller.busy:
            if record and record.state is RunState.REQUIRES_DECISION:
                self.reason = "unexpected_decision"
            return
        if record is None or record.state not in {RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS}:
            raise ValueError("scenario_failed")
        self.receipt["cases"][-1]["state"] = record.state.value
        self.phase = "result_capture"

    def capture_result(self):
        if not self.form_ready():
            return
        self.screenshot(CASES[self.index] + "-result.png")
        self.index += 1
        self.waiting = False
        self.phase = "home_select"

    def finish_receipt(self, cleanup):
        from PyQt6.QtWidgets import QApplication
        self.timer.stop()
        app = QApplication.instance()
        self.receipt.update(status="failed" if self.reason != "none" else "passed",
            reason=self.reason, cleanup=cleanup,
            qpa=app.platformName() if app.platformName() in {"windows", "offscreen"} else "other",
            stage=CASES[min(self.index, 2)] if self.reason != "none" else "complete")
        with (self.root / RECEIPT).open("x", encoding="utf-8") as stream:
            json.dump(self.receipt, stream, allow_nan=False)
        # Normal bootstrap owns shutdown_qt; the driver owns the finite native Job.
        app.exit(0 if self.reason == "none" else 1)

    def closeout(self):
        if not self.controller.busy:
            self.finish_receipt("complete")
            return
        if self.cancel_started is None:
            self.cancel_started = time.monotonic()
            self.controller.cancel()
        elif time.monotonic() - self.cancel_started > 15:
            self.reason = "cleanup_timeout"
            self.finish_receipt("pending")

    def tick(self):
        try:
            if time.monotonic() - self.started > TIMEOUT_SECONDS:
                self.reason = "timeout"
            if self.reason != "none" or self.index == len(CASES):
                self.closeout()
            else:
                actions = {"home_select": self.show_home, "home_ready": self.home_ready,
                    "select": self.begin, "fill": self.fill, "capture_start": self.capture_start,
                    "running": self.observe, "result_capture": self.capture_result}
                actions[self.phase]()
        except Exception as error:
            reason = error.args[0] if error.args else None
            self.reason = reason if type(reason) is str and reason in FAILURES else "scenario_failed"
            self.closeout()


def install_recipe_qualification(main_window, root: Path) -> None:
    """Retain a nonblocking GUI probe; the normal bootstrap owns Qt teardown."""
    root = Path(root)
    if os.getenv(GATE) != str(root) or not root.is_absolute():
        raise ValueError("qualification_gate_required")
    if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
        raise ValueError("qualification_root_not_empty")
    write_reports(root / "reports")
    main_window._recipe_qualification = _Probe(main_window, root)
