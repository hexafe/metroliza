"""Phase5618809967: explicitly admitted hosted real-Qt reduction, never a pytest test.

Importing this module imports only the standard library. No Qt execution is
permitted until the private, exact-probe admission has been checked.
"""

import argparse
import csv
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import threading
import time
import weakref


PHASE = "5618809967"
SOURCE_SHA = "216877364752c20bcdc65752382da470c4f363d5"
SOURCE_TREE = "719b80423271ff59c6fe08ace819fee2ae151fa0"
VARIANTS = ("async_reference", "async_owned_teardown")
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


def _python_observers():
    # Callbacks retain only primitive counters/IDs. No Qt or referent inspection.
    gui_ident = threading.get_ident()
    counts = {"gc": [0] * 4, "wrappers": [0] * 6}
    refs = []

    def collection(phase, info):
        offset = 0 if phase == "start" else 2
        counts["gc"][offset + int(threading.get_ident() != gui_ident)] += 1

    def watch(obj, kind):
        def released(reference):
            counts["wrappers"][kind * 2 + int(threading.get_ident() != gui_ident)] += 1
        refs.append(weakref.ref(obj, released))
        assert len(refs) <= 600, "bounded_weakrefs"

    return counts, refs, collection, watch


def _write_fixture(root):
    path = root / "table.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("Time Stamp", "Reference ID", "Line", "Length mm", "Width mm"))
        writer.writerows((
            ("2026-05-10 08:00:00", "R1", "L1", 10.0, 5.0),
            ("2026-05-10 09:00:00", "R1", "L2", 10.2, 5.2),
            ("2026-05-10 10:00:00", "R2", "L1", 10.1, 5.1),
            ("2026-05-10 11:00:00", "R2", "L2", 10.4, 5.4),
        ))
    return path


def _wait_for_load(dialog, app):
    # Preserve tests/test_industrial_analytics_dialog.py's real polling timing.
    deadline = time.monotonic() + 5.0
    shown = False
    while dialog.tabular_load_thread is not None and time.monotonic() < deadline:
        shown = dialog.loading_dialog.isVisible() or shown
        app.processEvents()
        time.sleep(0.01)
    assert dialog.tabular_load_thread is None, "loader_deadline"
    return dialog.loading_dialog.isVisible() or shown


def _check_loaded(dialog, root):
    from metroliza.tabular.tabular_analytics_service import tabular_load_result_row_count

    assert tabular_load_result_row_count(dialog.tabular_load_result) == 4, "loaded_rows"
    labels = {dialog.metrics_list.item(index).text() for index in range(dialog.metrics_list.count())}
    assert {"Length Mm", "Width Mm"}.issubset(labels), "loaded_metrics"
    assert "line" in {dialog.group_field_combo.itemData(index)
                      for index in range(dialog.group_field_combo.count())}, "group_column"
    assert dialog.timestamp_column_combo.currentData() == "time_stamp", "time_column"
    assert dialog.reference_column_combo.currentData() == "reference_id", "reference_column"
    assert dialog.start_button.isEnabled(), "loaded_ready"
    store = dialog.tabular_load_result.sqlite_store
    assert store is not None and store.owns_file, "real_owned_store"
    path = Path(store.path).resolve()
    assert path.is_relative_to(root.resolve()) and path.is_file(), "private_loaded_store"
    return path  # Primitive path only; do not retain the result across close.


def _check_ownership(dialog, thread, app):
    _check_dialog(dialog, app)
    _check_dialog(dialog.loading_dialog, app)
    assert dialog.parent() is None, "test_owned_parent"
    assert dialog.loading_dialog.parent() is dialog, "progress_parent"
    assert dialog.loading_gif.parent() is dialog.loading_dialog, "movie_parent"
    assert dialog.loading_gif.thread() == app.thread(), "movie_affinity"
    assert dialog.loading_dialog._loading_gif_buffer.parent() is dialog.loading_dialog, "buffer_parent"
    assert dialog.loading_dialog._delayed_show_timer.parent() is dialog.loading_dialog, "timer_parent"
    assert dialog.loading_dialog._delayed_show_timer.interval() == 1000, "real_show_delay"
    assert thread.parent() is None and thread.thread() == app.thread(), "loader_object_affinity"
    assert dialog.analytics_thread is None, "load_only"


def _owned_teardown(dialog, thread, app):
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent, QThread

    assert QThread.currentThread() == app.thread(), "gui_teardown"
    if not sip.isdeleted(thread):
        assert thread.isFinished() and not thread.isRunning(), "terminal_before_deletion"
        QCoreApplication.sendPostedEvents(thread, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(thread), "loader_cpp_deleted"
    verified = False
    if not sip.isdeleted(dialog):
        # Transient control-only wrappers verify these six subtree representatives.
        # Nothing from this tuple escapes teardown or becomes a lifetime registry.
        children = (dialog._metroliza_window_event_filter, dialog.loading_dialog,
                    dialog.loading_dialog._metroliza_window_event_filter, dialog.loading_gif,
                    dialog.loading_dialog._loading_gif_buffer, dialog.loading_dialog._delayed_show_timer)
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        assert all(sip.isdeleted(child) for child in children), "subtree_cpp_deleted"
        verified = True
    assert sip.isdeleted(dialog), "parent_cpp_deleted"
    return verified


def _async_cycle(app, variant, cycle, fixture, watch):
    from PyQt6 import sip

    from metroliza.ui import industrial_analytics_dialog as industrial

    dialog = industrial.IndustrialAnalyticsDialog(source_kind=industrial.SOURCE_TABULAR_FILE)
    watch(dialog, 0)
    _mark(variant, cycle, "parent_constructed")
    dialog.input_file = str(fixture)
    dialog.load_metrics()
    thread = dialog.tabular_load_thread  # Source test221 retains this local until its test returns.
    assert thread is not None, "real_loader_created"
    watch(dialog.loading_dialog, 1)
    watch(thread, 2)
    _mark(variant, cycle, "load_started")
    _check_ownership(dialog, thread, app)
    _mark(variant, cycle, "ownership_checked")
    shown = _wait_for_load(dialog, app)
    if not sip.isdeleted(thread):
        assert thread.isFinished() and not thread.isRunning(), "loader_terminal"
    _mark(variant, cycle, "worker_terminal")  # Source finished slot has joined/scheduled deletion.
    store_path = _check_loaded(dialog, fixture.parent)
    _mark(variant, cycle, "load_checked")
    assert dialog.close(), "parent_close_accepted"
    assert dialog.tabular_load_result is None, "result_released"
    assert not any(Path(str(store_path) + suffix).exists() for suffix in ("", "-wal", "-shm")), "store_removed"
    _mark(variant, cycle, "parent_close")
    owned = variant == "async_owned_teardown"
    verified = _owned_teardown(dialog, thread, app) if owned else False
    result = {"variant": variant, "cycle": cycle, "shown": shown,
              "parent_deleted": sip.isdeleted(dialog), "thread_deleted": sip.isdeleted(thread),
              "subtree_verified": verified, "load_rows": 4, "store_removed": True}
    _mark(variant, cycle, "boundary")
    return result  # Only primitives escape; no cleanup stronger than the declared control.


def _run(variant: str, cycles: int) -> None:
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    global _APP
    _APP = QApplication([])  # Keep source-test QApplication retention, including interpreter exit.
    assert QThread.currentThread() == _APP.thread(), "gui_thread"
    fixture = _write_fixture(Path(os.environ["TMPDIR"]))
    counts, refs, collection, watch = _python_observers()
    gc.callbacks.append(collection)
    _mark(variant, 0, "application")
    try:
        for cycle in range(1, cycles + 1):
            _mark(variant, cycle, "cycle_start")
            result = _async_cycle(_APP, variant, cycle, fixture, watch)
            _mark(variant, cycle, "release")
            result.update(gc=list(counts["gc"]), wrappers=list(counts["wrappers"]))
            print("QT998_LIFETIME " + json.dumps(result, separators=(",", ":")), flush=True)
            _mark(variant, cycle, "complete")
        _mark(variant, cycles, "process_exit")
    finally:
        gc.callbacks.remove(collection)
        # No forced GC, parent registry, global event drain, or destruction observer.
        # refs retain Python weakrefs only through the measured sequence.
        assert len(refs) <= 600, "bounded_weakrefs"


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
