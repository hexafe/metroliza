"""Review dialog feedback for the pooled review (#1148 C2): throttled, batched, applied in order."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QThread, pyqtSignal

from metroliza.ui import parsing_dialog as parsing_dialog_module
from tests.metadata_review_fakes import review_result
from tests.test_metadata_review_ui import FULL, HOSTS, cell, settle, wait_until
from tests.test_metadata_review_ui import app as app, make_host as make_host, readers as readers


class _BurstPreflightThread(QThread):
    """Emits a review-pool-like burst of progress, then the result."""

    update_label = pyqtSignal(str)
    update_progress = pyqtSignal(int)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    result = None
    updates = 600

    def __init__(self, source_path, database_path, metadata_parsing_mode):
        super().__init__()

    def stop_scan(self):
        pass

    def run(self):
        for done in range(1, self.updates + 1):
            self.update_progress.emit(round(100 * done / self.updates))
            self.update_label.emit(f"Inspected {done}/{self.updates}")
        self.completed.emit(type(self).result)


class _Indicator:
    def __init__(self, events):
        self.events = events
        self.labels = []

    def show(self):
        self.events.append("indicator shown")

    def accept(self):
        self.events.append("indicator closed")

    reject = accept

    def setWindowModality(self, _modality):  # noqa: N802
        pass


@pytest.mark.parametrize("kind", HOSTS)
def test_scan_feedback_is_throttled_and_the_indicator_closes_after_the_review_is_applied(
    app, make_host, readers, monkeypatch, kind
):
    names = tuple(f"r{index:03d}.pdf" for index in range(40))
    readers.options = {"fast": {name: dict(FULL) for name in names}}
    host = make_host(kind)
    events, labels, values = [], [], []
    indicator = _Indicator(events)
    label = type("L", (), {"setText": lambda _s, text: labels.append(text)})()
    bar = type("B", (), {"setValue": lambda _s, value: values.append(value)})()
    monkeypatch.setattr(parsing_dialog_module, "create_worker_progress_dialog",
                        lambda *_a, **_k: (indicator, label, bar, None))
    monkeypatch.setattr(parsing_dialog_module, "ParsePreflightThread", _BurstPreflightThread)
    _BurstPreflightThread.result = review_result(names, source=host.directory, database=host.db_file)
    original_set_review = host.report_planner.set_review

    def recording_set_review(*args, **kwargs):
        events.append("review applied")
        return original_set_review(*args, **kwargs)

    monkeypatch.setattr(host.report_planner, "set_review", recording_set_review)
    shell_updates = []
    host.state_changed.connect(lambda: shell_updates.append(host._operation_progress))

    host.scan_reports()
    wait_until(app, lambda: host.preflight_thread is None)
    settle(app, host)

    assert events.index("review applied") < events.index("indicator closed")
    assert len(values) < 60 and len(labels) < 60  # 600 updates arrived in a burst
    assert len(shell_updates) < 80
    assert cell(host.report_planner, "r039.pdf", "reference").data() == "REF-A"


@pytest.mark.parametrize("kind", HOSTS)
def test_a_burst_of_readings_is_applied_in_batches_and_completely(app, make_host, readers, monkeypatch, kind):
    names = tuple(f"r{index:03d}.pdf" for index in range(300))
    readers.options = {"fast": {name: dict(FULL, reference=f"REF-{name}") for name in names}}
    host = make_host(kind)
    statuses = []
    original_status = host.report_planner.set_metadata_status

    def recording_status(text, variant="neutral"):
        statuses.append(text)
        return original_status(text, variant)

    monkeypatch.setattr(host.report_planner, "set_metadata_status", recording_status)
    host.on_preflight_completed(review_result(names, source=host.directory, database=host.db_file))
    settle(app, host)

    planner = host.report_planner
    assert planner.model.metadata_counts["pending"] == 0
    assert cell(planner, "r000.pdf", "reference").data() == "REF-r000.pdf"
    assert cell(planner, "r299.pdf", "reference").data() == "REF-r299.pdf"
    assert len(statuses) < 60  # not one restyle per report
    assert planner.metadata_status_text == ""  # the completed fast read clears the progress


@pytest.mark.parametrize("kind", HOSTS)
def test_queued_readings_of_a_retired_worker_never_reach_the_next_review(app, make_host, readers, kind):
    names = ("a.pdf", "b.pdf")
    readers.options = {"fast": {name: dict(FULL) for name in names}}
    host = make_host(kind)
    host.on_preflight_completed(review_result(names, source=host.directory, database=host.db_file))
    thread = host.metadata_thread
    reading = type("R", (), {"occurrence_id": "a.pdf", "mode": "light", "ocr_note": ""})()
    host._pending_readings.append((thread, reading))

    host._invalidate_preflight()

    assert host._pending_readings == [] and host._pending_metadata_progress is None
    settle(app, host)


def test_finished_preflight_is_released_on_gui_thread(app, make_host, readers, monkeypatch):
    import gc
    import threading
    import weakref
    from tests.test_detached_threads import _collect_in_another_thread

    finalized_in = []
    class TrackedPreflight(_BurstPreflightThread):
        def __del__(self):
            finalized_in.append(threading.current_thread())

    host = make_host('dialog')
    monkeypatch.setattr(parsing_dialog_module, 'ParsePreflightThread', TrackedPreflight)
    monkeypatch.setattr(host, 'on_preflight_completed', lambda result: None)
    TrackedPreflight.result = None
    gc.collect()
    gc.disable()
    try:
        host.scan_reports()
        thread = host.preflight_thread
        assert isinstance(thread, TrackedPreflight)
        reference = weakref.ref(thread)
        assert thread.wait(20000)
        wait_until(app, lambda: host.preflight_thread is None)
        del thread
        released_without_gc = reference() is None
        _collect_in_another_thread()
    finally:
        gc.enable()
    assert released_without_gc, 'preflight signals retain the finished thread in a cycle'
    assert finalized_in == [threading.current_thread()]
