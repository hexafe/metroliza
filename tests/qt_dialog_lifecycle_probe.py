"""Phase5614139597: explicitly admitted hosted real-Qt reduction, never a pytest test.

Importing this module imports only the standard library. No Qt execution is
permitted until the private, exact-probe admission has been checked.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess


PHASE = "5614139597"
SOURCE_SHA = "216877364752c20bcdc65752382da470c4f363d5"
SOURCE_TREE = "719b80423271ff59c6fe08ace819fee2ae151fa0"
VARIANTS = ("industrial_ui", "plain_ui", "minimal_filter", "uninstalled_filter")
_APP = None


def _admitted() -> None:
    if (platform.system() != "Linux" or platform.machine() != "x86_64"
            or os.getuid() == 0
            or platform.freedesktop_os_release().get("ID") != "ubuntu"
            or platform.freedesktop_os_release().get("VERSION_ID") != "24.04"
            or os.environ.get("QT_QPA_PLATFORM") != "offscreen"):
        raise ValueError("admitted_standard_guest_required")
    root = Path(os.environ["TMPDIR"]).parent
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("private_admission_required")
    admission = json.loads((root / "admission.json").read_text())
    if (admission.get("phase") != PHASE or admission.get("run_attempt") != 1
            or root.name != "qt998-" + str(admission.get("run_id"))
            or admission.get("workload_sha") != SOURCE_SHA
            or admission.get("workload_tree") != SOURCE_TREE
            or admission.get("probe_sha256") != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
        raise ValueError("probe_admission_mismatch")
    identity = subprocess.check_output(
        ["git", "--no-optional-locks", "rev-parse", "HEAD", "HEAD^{tree}"], timeout=10,
        stderr=subprocess.DEVNULL, text=True,
    ).splitlines()
    if identity != [SOURCE_SHA, SOURCE_TREE]:
        raise ValueError("immutable_source_required")


def _mark(variant: str, cycle: int, phase: str) -> None:
    # Fixed primitive values only; no QObject, repr, argument or path payload.
    print(f"QT998_PROBE {variant} {cycle} {phase}", flush=True)


def _check_dialog(dialog, app) -> None:
    from PyQt6.QtCore import QThread

    assert QThread.currentThread() == app.thread(), "gui_thread"
    assert dialog.thread() == app.thread(), "dialog_affinity"
    assert dialog._metroliza_window_event_filter.parent() is dialog, "filter_parent"
    assert dialog._metroliza_window_event_filter.thread() == dialog.thread(), "filter_affinity"


def _industrial_cycle(app, variant, cycle) -> None:
    from metroliza.ui import industrial_analytics_dialog as industrial

    dialog = industrial.IndustrialAnalyticsDialog(source_kind=industrial.SOURCE_TABULAR_FILE)
    _mark(variant, cycle, "parent_constructed")  # Includes its real configure/theme calls.
    dialog.show()
    _mark(variant, cycle, "parent_show")
    dialog.loading_dialog, dialog.loading_label, dialog.loading_bar, dialog.loading_gif = (
        industrial.create_worker_progress_dialog(
            dialog, window_title="Loading CSV / Excel data...",
            initial_status_text=industrial.build_three_line_status(
                "Loading CSV/Excel data...", "Reading rows and detecting metric columns", "ETA --"),
            on_cancel=dialog.cancel_tabular_load,
        )
    )
    _mark(variant, cycle, "progress_constructed")  # Includes theme, children, sizing, movie start.
    dialog.loading_bar.setRange(0, 0)
    dialog.loading_dialog.show()  # Preserve the real1000ms delayed-show contract.
    _mark(variant, cycle, "progress_show")  # Request boundary, not proof of visibility.
    _check_dialog(dialog, app)
    _check_dialog(dialog.loading_dialog, app)
    assert dialog.loading_dialog.parent() is dialog, "progress_parent"
    assert dialog.loading_gif.parent() is dialog.loading_dialog, "movie_parent"
    assert dialog.loading_gif.thread() == app.thread(), "movie_affinity"
    assert dialog.loading_dialog._loading_gif_buffer.parent() is dialog.loading_dialog, "buffer_parent"
    assert dialog.loading_dialog._delayed_show_timer.parent() is dialog.loading_dialog, "timer_parent"
    assert dialog.tabular_load_thread is None and dialog.analytics_thread is None, "ui_only"
    _mark(variant, cycle, "ownership_checked")
    app.processEvents()
    _mark(variant, cycle, "events")
    dialog.loading_dialog.close()  # Terminal UI portion only; no load-result processing.
    _mark(variant, cycle, "progress_close")
    dialog.close()
    _mark(variant, cycle, "parent_close")
    # Scope exit releases only the caller's reference. Preserve genuine cycles,
    # progress attributes, movie behavior and any still-pending source callbacks.


def _minimal_filter(self, watched, event):
    return False


def _plain_cycle(app, variant, cycle) -> None:
    from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

    from metroliza.ui import ui_foundation as foundation

    dialog = QDialog()
    _mark(variant, cycle, "constructed")
    foundation.configure_window_size(dialog, minimum=(720, 560), initial=(880, 680))
    if variant == "uninstalled_filter":
        dialog.removeEventFilter(dialog._metroliza_window_event_filter)
    _mark(variant, cycle, "configured")
    QVBoxLayout(dialog).addWidget(QLabel("Dialog lifecycle reduction", dialog))
    _mark(variant, cycle, "layout")
    foundation.apply_metroliza_theme(dialog)
    _mark(variant, cycle, "themed")
    _check_dialog(dialog, app)
    _mark(variant, cycle, "ownership_checked")
    dialog.show()
    _mark(variant, cycle, "show")
    app.processEvents()
    _mark(variant, cycle, "events")
    dialog.close()
    _mark(variant, cycle, "close")


def _run(variant: str, cycles: int) -> None:
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    from metroliza.ui import ui_foundation as foundation

    global _APP
    _APP = QApplication([])  # Retain through all cycles; interpreter teardown is a separate boundary.
    assert QThread.currentThread() == _APP.thread(), "gui_thread"
    if variant == "minimal_filter":
        # A predeclared replacement control, not an observer or product change.
        foundation._AdaptiveWindowEventFilter.eventFilter = _minimal_filter
    _mark(variant, 0, "application")
    cycle_function = _industrial_cycle if variant == "industrial_ui" else _plain_cycle
    for cycle in range(1, cycles + 1):
        _mark(variant, cycle, "cycle_start")
        cycle_function(_APP, variant, cycle)
        _mark(variant, cycle, "release")
        _mark(variant, cycle, "complete")
    # No stronger teardown, post-release event drain or collection is added.
    _mark(variant, cycles, "process_exit")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--cycles", type=int, choices=range(1, 201), required=True)
    args = parser.parse_args(argv)
    try:
        _admitted()
        _mark(args.variant, 0, "startup")
        _run(args.variant, args.cycles)
        return 0
    except Exception as error:
        print("QT998_PROBE_ERROR " + type(error).__name__, flush=True)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
