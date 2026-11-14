from dataclasses import replace
import json
from threading import Event
import time
import types

from metroliza.shared import safe_bugreport
from scripts.reproduce_safe_bugreport import match_safe_bugreport

from metroliza.shared.safe_bugreport import (
    BUG_REPORT_UNAVAILABLE,
    BugReportAction,
    BugReportCategory,
    BugReportSnapshot,
    SafeBugReportEvent,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)


def test_report_contains_only_closed_codes_and_boolean_states():
    recorder = SafeBugReportRecorder()
    assert recorder.record(BugReportAction.CSV_OPENED)
    assert recorder.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    report = build_bug_report_markdown(
        BugReportCategory.WRONG_OUTPUT, recorder.snapshot(), release_version="0.8.0-dev.2"
    )

    assert "Category: `wrong_output`" in report
    assert "Application version: `0.8.0-dev.2`" in report
    assert "Reproduction status: `NOT_RUN`" in report
    assert "External input data: `not included`" in report
    assert "`csv_opened`" in report
    assert "`option_workbook` (enabled: `true`)" in report
    assert "Reproduction not performed. Input data was not captured." in report


def test_invalid_dynamic_values_are_rejected_and_never_serialized():
    recorder = SafeBugReportRecorder()
    secret = "Confidential customer name"
    assert not recorder.record(secret)  # type: ignore[arg-type]
    assert not recorder.record(BugReportAction.CSV_OPENED, enabled=secret)  # type: ignore[arg-type]
    report = build_bug_report_markdown(BugReportCategory.OTHER, recorder.snapshot())

    assert secret not in report
    assert "Recorded events lost: `true`" in report


def test_ring_is_bounded_and_reports_event_loss():
    recorder = SafeBugReportRecorder(max_events=2)
    for action in (BugReportAction.APP_OPENED, BugReportAction.CSV_OPENED,
                   BugReportAction.ANALYSIS_STARTED):
        assert recorder.record(action)

    snapshot = recorder.snapshot()
    assert len(snapshot.events) == 2
    assert snapshot.events_lost
    report = build_bug_report_markdown(BugReportCategory.OPERATION_FAILED, snapshot)
    assert "`app_opened`" not in report
    assert "Recorded events lost: `true`" in report


def test_serializer_fails_closed_for_tampered_snapshot():
    snapshot = BugReportSnapshot(
        events=(SafeBugReportEvent(BugReportAction.CSV_OPENED),),
        events_lost=False,
    )
    tampered = replace(snapshot, events=("sensitive value",))  # type: ignore[arg-type]

    report = build_bug_report_markdown(BugReportCategory.OTHER, tampered)
    assert "sensitive value" not in report
    assert report == BUG_REPORT_UNAVAILABLE


def test_category_and_boolean_types_are_exact():
    recorder = SafeBugReportRecorder()
    assert not recorder.record(BugReportAction.FILTER_APPLIED, enabled=1)  # type: ignore[arg-type]
    assert build_bug_report_markdown("wrong_output", recorder.snapshot()) == (
        BUG_REPORT_UNAVAILABLE
    )


def test_persistent_history_restores_only_closed_enum_and_boolean_values(tmp_path):
    first = SafeBugReportRecorder()
    assert first.record(BugReportAction.GROUPING_APPLIED)
    assert first.record(BugReportAction.OPTION_WORKBOOK, enabled=True)
    assert first.configure_history(tmp_path / "safe-bugreport-activity")
    assert first.flush(3)
    assert first.close_history(3)

    second = SafeBugReportRecorder()
    assert second.configure_history(tmp_path / "safe-bugreport-activity")
    assert second.flush(3)
    snapshot = second.snapshot()
    assert snapshot.previous_session_state == "available"
    assert [event.action for event in snapshot.events[-2:]] == [
        BugReportAction.GROUPING_APPLIED,
        BugReportAction.OPTION_WORKBOOK,
    ]
    assert snapshot.events[-1].enabled is True
    assert second.close_history(3)


def test_persistent_history_restores_when_direntry_metadata_is_incomplete(
    tmp_path, monkeypatch
):
    root = tmp_path / "safe-bugreport-activity"
    first = SafeBugReportRecorder()
    assert first.configure_history(root)
    assert first.record(BugReportAction.GROUPING_APPLIED)
    assert first.flush(3)
    assert first.close_history(3)

    real_scandir = safe_bugreport.os.scandir
    with real_scandir(root) as entries:
        scanned = tuple((entry.name, entry.path) for entry in entries)
    weak_stat_calls: list[str] = []

    class WeakWindowsEntry:
        def __init__(self, name, path):
            self.name, self.path = name, path

        def stat(self, *, follow_symlinks=True):
            weak_stat_calls.append(self.name)
            metadata = safe_bugreport.os.stat(
                self.path, follow_symlinks=follow_symlinks
            )
            return types.SimpleNamespace(
                st_mode=metadata.st_mode,
                st_ino=0,
                st_dev=0,
                st_nlink=0,
                st_uid=metadata.st_uid,
                st_size=metadata.st_size,
                st_file_attributes=getattr(metadata, "st_file_attributes", 0),
            )

    class WeakWindowsScan:
        def __enter__(self):
            return iter(WeakWindowsEntry(*entry) for entry in scanned)

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(safe_bugreport.os, "scandir", lambda _root: WeakWindowsScan())

    second = SafeBugReportRecorder()
    assert second.configure_history(root)
    assert second.flush(3)
    assert second.snapshot().previous_session_state == "available"
    assert [event.action for event in second.snapshot().events[-1:]] == [
        BugReportAction.GROUPING_APPLIED,
    ]
    assert weak_stat_calls == []
    assert second.close_history(3)


def test_restore_overflow_marks_the_live_snapshot_incomplete(tmp_path):
    root = tmp_path / "history"
    first = SafeBugReportRecorder(max_events=2)
    assert first.configure_history(root)
    assert first.record(BugReportAction.CSV_OPENED)
    assert first.record(BugReportAction.FILTER_APPLIED)
    assert first.flush(3)
    assert first.close_history(3)
    second = SafeBugReportRecorder(max_events=2)
    assert second.record(BugReportAction.ANALYSIS_STARTED)
    assert second.configure_history(root)
    assert second.flush(3)
    assert second.snapshot().events_lost
    assert second.close_history(3)


def test_unconfigured_history_reports_not_available():
    snapshot = SafeBugReportRecorder().snapshot()
    assert snapshot.previous_session_state == "not_available"


def test_persistent_history_rejects_unknown_schema_and_surfaces_data_loss(tmp_path):
    root = tmp_path / "safe-bugreport-activity"
    root.mkdir(mode=0o700)
    (root / "activity.json").write_text(
        json.dumps({"schema": 99, "events": [], "events_lost": False}), encoding="ascii"
    )
    recorder = SafeBugReportRecorder()
    assert recorder.configure_history(root)
    assert recorder.flush(3)
    snapshot = recorder.snapshot()
    assert snapshot.events_lost
    assert snapshot.previous_session_state == "unknown"
    assert recorder.close_history(3)


def test_disk_write_failure_is_best_effort_and_sets_lost_flag(tmp_path, monkeypatch):
    recorder = SafeBugReportRecorder()
    assert recorder.configure_history(tmp_path / "safe-bugreport-activity")
    monkeypatch.setattr(
        safe_bugreport._diagnostic_store,
        "_write_stage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk fault")),
    )
    assert recorder.record(BugReportAction.CSV_OPENED)
    assert recorder.flush(3)
    assert recorder.snapshot().events_lost
    assert recorder.close_history(3)


def test_non_private_root_fails_closed(tmp_path, monkeypatch):
    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(
        safe_bugreport._diagnostic_store, "_ensure_private_root", lambda _root: False
    )
    assert recorder.configure_history(tmp_path / "blocked")
    assert recorder.record(BugReportAction.APP_OPENED)
    assert recorder.flush(3)
    snapshot = recorder.snapshot()
    assert snapshot.events_lost
    assert snapshot.events[-1].action is BugReportAction.APP_OPENED
    assert recorder.close_history(3)


def test_two_live_recorders_do_not_merge_sessions(tmp_path):
    root = tmp_path / "safe-bugreport-activity"
    first = SafeBugReportRecorder()
    assert first.configure_history(root)
    assert first.record(BugReportAction.APP_OPENED)
    time.sleep(0.05)

    second = SafeBugReportRecorder()
    assert second.configure_history(root)
    assert second.record(BugReportAction.CSV_OPENED)
    assert second.flush(3)
    assert second.snapshot().events_lost
    assert second.close_history(3)
    assert first.close_history(3)


def test_saturated_history_clear_then_new_scenario_is_fifo_and_complete(tmp_path, monkeypatch):
    root = tmp_path / "safe-bugreport-activity"
    recorder = SafeBugReportRecorder()
    for _ in range(safe_bugreport.MAX_EVENTS + 1):
        assert recorder.record(BugReportAction.ANALYSIS_FAILED)
    assert recorder.snapshot().events_lost
    negative = build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, recorder.snapshot())
    assert match_safe_bugreport(negative).status == "NO_SCENARIO_MATCH"
    assert recorder.configure_history(root)
    assert recorder.flush(3)
    assert recorder.snapshot().events_lost

    new_actions = (
        BugReportAction.GROUPING_APPLIED,
        BugReportAction.OPTION_WORKBOOK,
        BugReportAction.OPTION_GROUPING,
        BugReportAction.ANALYSIS_STARTED,
    )
    entered, release = Event(), Event()
    original_clear = safe_bugreport.LocalBugReportHistoryStore.clear_locked

    def blocked_clear(store):
        entered.set()
        return release.wait(5) and original_clear(store)

    monkeypatch.setattr(safe_bugreport.LocalBugReportHistoryStore, "clear_locked", blocked_clear)
    try:
        assert recorder.clear_history()
        assert entered.wait(3)
        pending = recorder.snapshot()
        assert pending.clear_state == "pending"
        assert pending.events_lost
        assert pending.events == ()
        for action in new_actions:
            assert recorder.record(
                action, enabled=True if action in {
                    BugReportAction.OPTION_WORKBOOK, BugReportAction.OPTION_GROUPING
                } else None
            )
    finally:
        release.set()
    assert recorder.flush(3)
    snapshot = recorder.snapshot()
    assert snapshot.clear_state == "complete"
    assert not snapshot.events_lost
    assert snapshot.previous_session_state == "not_available"
    assert [event.action for event in snapshot.events] == list(new_actions)
    report = build_bug_report_markdown(BugReportCategory.WRONG_OUTPUT, snapshot)
    assert match_safe_bugreport(report).status == "SCENARIO_MATCHED"
    assert match_safe_bugreport(report).scenario == "csv_grouping_xlsx_v1"
    assert recorder.close_history(3)

    payload = json.loads((root / "activity.json").read_text(encoding="ascii"))
    assert payload["events"] == [
        {
            "action": action.value,
            "enabled": True if action in {
                BugReportAction.OPTION_WORKBOOK, BugReportAction.OPTION_GROUPING
            } else None,
        }
        for action in new_actions
    ]
    assert payload["events_lost"] is False


def test_clear_queue_full_fails_without_claiming_completion(tmp_path):
    root = tmp_path / "history"
    assert safe_bugreport._diagnostic_store._ensure_private_root(root)
    held_lock = safe_bugreport._diagnostic_store._StoreLock(root)
    assert held_lock.acquire()
    recorder = SafeBugReportRecorder(write_queue_size=1)
    assert recorder.configure_history(root)
    try:
        assert recorder.clear_history()
        assert not recorder.clear_history()
        snapshot = recorder.snapshot()
        assert snapshot.clear_state == "error"
        assert snapshot.events_lost
    finally:
        held_lock.release()
    assert recorder.flush(3)
    assert recorder.snapshot().clear_state == "complete"
    assert recorder.close_history(3)


def test_clear_disk_failure_is_visible_and_does_not_reset_loss(tmp_path, monkeypatch):
    root = tmp_path / "history"
    recorder = SafeBugReportRecorder()
    assert recorder.configure_history(root)
    assert recorder.record(BugReportAction.CSV_OPENED)
    assert recorder.flush(3)
    monkeypatch.setattr(
        safe_bugreport.LocalBugReportHistoryStore,
        "clear_locked",
        lambda _store: False,
    )
    assert recorder.clear_history()
    assert recorder.flush(3)
    snapshot = recorder.snapshot()
    assert snapshot.clear_state == "error"
    assert snapshot.events_lost
    assert recorder.close_history(3)
    payload = json.loads((root / "activity.json").read_text(encoding="ascii"))
    assert payload["events"] == [{"action": "csv_opened", "enabled": None}]


def test_clear_without_held_lock_fails_closed_and_keeps_file(tmp_path):
    root = tmp_path / "history"
    first = SafeBugReportRecorder()
    assert first.configure_history(root)
    assert first.record(BugReportAction.APP_OPENED)
    assert first.flush(3)

    second = SafeBugReportRecorder()
    assert second.configure_history(root)
    assert second.flush(3)
    assert second.clear_history()
    assert second.flush(3)
    assert second.snapshot().clear_state == "error"
    assert second.snapshot().events_lost
    assert second.close_history(3)
    assert first.close_history(3)
    payload = json.loads((root / "activity.json").read_text(encoding="ascii"))
    assert payload["events"] == [{"action": "app_opened", "enabled": None}]
