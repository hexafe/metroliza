from __future__ import annotations

import dataclasses
import json
import time
import uuid
import zipfile

import pytest

try:
    from PyQt6.QtWidgets import QApplication, QFileDialog
except (AttributeError, ImportError):  # pragma: no cover - optional local dependency
    pytest.skip("PyQt6 is unavailable", allow_module_level=True)

from metroliza.shared import diagnostic_store
from metroliza.shared.diagnostic_events import (
    BuildPackager,
    RecipeFlowState,
    RuntimeMode,
    RuntimeProvenanceEvent,
    StartupCallsite,
    StartupDiagnosticEvent,
    StartupMode,
    StartupOutcome,
    ValidationStatus,
    WorkflowDiagnosticEvent,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_incident import (
    MAX_COUNTER,
    MAX_ELAPSED_MS,
    ChannelState,
    HandshakeState,
    IncidentObservation,
    LaunchState,
    TerminationState,
    build_incident,
)
from metroliza.shared.diagnostic_ring import LOSS_ACCOUNTING_BYTES, RingLoss, RingSnapshot
from metroliza.shared.diagnostic_store import IncidentStore, StoreResult, StoreStatus
from metroliza.shared.diagnostic_transport import ChildRecorder
from metroliza.shared.diagnostic_wire import decode_event, encode_event
from metroliza.shared.safe_bugreport import BugReportAction, SafeBugReportRecorder
from metroliza.ui import safe_bugreport_dialog
from metroliza.ui.incident_dialog import IncidentDialog, open_incident_viewer


SESSION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
REPORT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OPERATION_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _incident(*, loss: bool = False, report_id: uuid.UUID = REPORT_ID, events: tuple[bytes, ...] | None = None):
    if events is None:
        events = (
            encode_event(
                WorkflowDiagnosticEvent(
                    invocation_id=SESSION_ID,
                    operation_id=OPERATION_ID,
                    sequence=1,
                    operation=WorkflowOperation.LOCAL_EXPORT,
                    stage=WorkflowStage.FINISHED,
                    outcome=WorkflowOutcome.COMPLETED,
                    validation_status=ValidationStatus.NOT_PERFORMED,
                    published_artifact_count=1,
                    duration_ms=25,
                )
            ),
        )
    ring_loss = RingLoss(invalid_events=1, invalid_bytes=9) if loss else RingLoss()
    history = RingSnapshot(events, ring_loss, sum(map(len, events)) + LOSS_ACCOUNTING_BYTES)
    observation = IncidentObservation(
        launch=LaunchState.STARTED,
        handshake=HandshakeState.ACCEPTED,
        channel=ChannelState.LOSS_OBSERVED if loss else ChannelState.COMPLETE,
        exit_code=0,
        termination=TerminationState.OBSERVED_EXIT,
        clean_terminal_received=True,
        source_dropped=0,
        source_loss_known=True,
        elapsed_ms=30,
    )
    return build_incident(
        report_id=report_id,
        session_id=SESSION_ID,
        created_at_ms=time.time_ns() // 1_000_000,
        build_git_sha="a" * 40,
        observation=observation,
        history=history,
    )


def test_viewer_lists_and_renders_only_closed_safe_summary(tmp_path) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident(loss=True)).status is StoreStatus.SAVED

    dialog = IncidentDialog(store=store)
    preview = dialog.preview.toPlainText()

    assert dialog.reports_table.rowCount() == 1
    assert REPORT_ID.hex in preview
    assert "Diagnostic channel: Complete terminal record with recording loss" in preview
    assert "Recording history: Incomplete" in preview
    assert "Recorder rejected or dropped: 1" in preview
    assert "Workflow issue: None recorded" in preview
    assert "Domain validation: Not performed" in preview
    assert "Published artifacts: 1" in preview
    assert "Workflow duration: 25 ms" in preview
    assert "Native stack: Unavailable" in preview
    assert "published_artifact_count" not in preview
    assert "validation_status" not in preview
    assert "local_export" not in preview
    assert str(store.root) not in preview
    assert "{" not in preview
    dialog.close()


def test_viewer_lists_stored_timeline_in_order_across_operations_and_selection(tmp_path) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    startup_id = uuid.UUID("44444444-4444-4444-8444-444444444444")
    recipe_id = uuid.UUID("55555555-5555-4555-8555-555555555555")
    export = WorkflowDiagnosticEvent(
        SESSION_ID, OPERATION_ID, 1, WorkflowOperation.LOCAL_EXPORT, WorkflowStage.STARTED, WorkflowOutcome.STARTED,
    )
    events = tuple(map(encode_event, (
        StartupDiagnosticEvent(SESSION_ID, startup_id, 1, StartupMode.UNKNOWN,
                               StartupCallsite.BOOTSTRAP, StartupOutcome.INVOCATION_STARTED),
        RuntimeProvenanceEvent(SESSION_ID, startup_id, 2, RuntimeMode.SOURCE, BuildPackager.SOURCE,
                               release_version="0.8.0-dev.5"),
        export,
        WorkflowDiagnosticEvent(SESSION_ID, recipe_id, 1, WorkflowOperation.RECIPE_FLOW,
                                WorkflowStage.STARTED, WorkflowOutcome.STARTED,
                                flow_id=uuid.uuid4(), run_id=uuid.uuid4(), step_id=uuid.uuid4(),
                                flow_state=RecipeFlowState.RUNNING),
        dataclasses.replace(export, sequence=2, stage=WorkflowStage.FINISHED, outcome=WorkflowOutcome.COMPLETED,
                            published_artifact_count=1),
    )))
    assert store.publish(_incident(events=events)).status is StoreStatus.SAVED
    other_id = uuid.UUID("66666666-6666-4666-8666-666666666666")
    assert store.publish(_incident(report_id=other_id)).status is StoreStatus.SAVED
    dialog = IncidentDialog(store=store)
    try:
        assert dialog.reports_table.rowCount() == 2

        def select(report_id):
            dialog.reports_table.selectRow(next(
                row for row in range(dialog.reports_table.rowCount())
                if dialog.reports_table.item(row, 0).text() == report_id.hex
            ))
            return dialog.preview.toPlainText()

        preview = select(REPORT_ID)
        assert "Latest workflow: Local export" in preview
        timeline = preview.split("Recent event timeline\n")[1]
        assert timeline.splitlines() == [
            "1. Startup · Bootstrap · Invocation started",
            "2. Build provenance recorded",
            "3. Local export · Started",
            "4. Recipe flow · Started",
            "5. Local export · Finished · Completed",
        ]
        assert recipe_id.hex not in timeline and "recipe_flow" not in timeline
        assert dialog.export_button.isEnabled()

        preview = select(other_id)
        assert preview.split("Recent event timeline\n")[1] == "1. Local export · Finished · Completed"
        assert REPORT_ID.hex not in preview
    finally:
        dialog.close()


def test_viewer_bounds_timeline_and_shows_omitted_retained_events(tmp_path) -> None:
    _app()
    event = WorkflowDiagnosticEvent(
        SESSION_ID, OPERATION_ID, 1, WorkflowOperation.LOCAL_EXPORT,
        WorkflowStage.PROCESSING, WorkflowOutcome.MILESTONE,
    )
    events = tuple(encode_event(dataclasses.replace(event, sequence=step)) for step in range(1, 43))
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident(events=events)).status is StoreStatus.SAVED
    dialog = IncidentDialog(store=store)
    try:
        timeline = dialog.preview.toPlainText().split("Recent event timeline\n")[1].splitlines()
        assert timeline[0] == "Earlier recorded events omitted: 2"
        assert timeline[1:] == [f"{step}. Local export · Processing · Milestone observed" for step in range(3, 43)]
    finally:
        dialog.close()


def test_capture_current_state_opens_the_authoritative_frozen_preview(tmp_path, monkeypatch) -> None:
    _app()
    recorder = SafeBugReportRecorder()
    recorder.record(BugReportAction.CSV_OPENED)
    monkeypatch.setattr(safe_bugreport_dialog, "recorder", recorder)
    dialog = open_incident_viewer(store=IncidentStore(tmp_path / "diagnostics"))
    safe_preview = None
    try:
        assert not dialog.export_button.isEnabled()
        dialog.capture_button.click()
        safe_preview = dialog.findChild(safe_bugreport_dialog.SafeBugReportDialog)
        assert safe_preview is not None and safe_preview.isVisible()
        assert safe_preview.parent() is dialog
        assert "csv_opened" in safe_preview.preview.toPlainText()
        recorder.record(BugReportAction.FILTER_APPLIED)
        assert "filter_applied" not in safe_preview.preview.toPlainText()
        safe_preview.refresh_button.click()
        assert "filter_applied" in safe_preview.preview.toPlainText()
        assert dialog.reports_table.rowCount() == 0
    finally:
        if safe_preview is not None:
            safe_preview.close()
        dialog.close()


@pytest.mark.parametrize("invalid_fields", [{"event_code": "sentinel_unknown"}, {"raw_input": "sentinel_private"}])
def test_invalid_retained_timeline_payload_clears_previous_preview_and_export(tmp_path, invalid_fields) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    dialog = IncidentDialog(store=store)
    try:
        assert dialog.export_button.isEnabled()
        report = store.root / f"incident-{REPORT_ID.hex}.json"
        payload = json.loads(report.read_bytes())
        payload["events"][0].update(invalid_fields)
        report.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="ascii")
        dialog._load_selected()
        assert dialog.preview.toPlainText() == "The selected incident could not be validated."
        assert not dialog.export_button.isEnabled()
    finally:
        dialog.close()


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_saturated_values_are_lower_bounds_in_preview_and_selected_export(tmp_path, offset):
    _app()
    original = _incident()
    elapsed = min(MAX_ELAPSED_MS, MAX_ELAPSED_MS + offset)
    event = encode_event(dataclasses.replace(decode_event(original.events[0]), duration_ms=elapsed))
    recorder = ChildRecorder(-1, -1)
    recorder.dropped = min(MAX_COUNTER, MAX_COUNTER + offset - 1)
    assert not recorder.enqueue_bytes(event)
    assert recorder.dropped == min(MAX_COUNTER, MAX_COUNTER + offset)
    incident = build_incident(
        report_id=REPORT_ID,
        session_id=SESSION_ID,
        created_at_ms=original.created_at_ms,
        build_git_sha=original.build_git_sha,
        observation=dataclasses.replace(
            original.observation,
            channel=ChannelState.LOSS_OBSERVED,
            source_dropped=recorder.dropped,
            elapsed_ms=elapsed,
        ),
        history=RingSnapshot((event,), RingLoss(), len(event) + LOSS_ACCOUNTING_BYTES),
    )
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(incident).status is StoreStatus.SAVED
    dialog = IncidentDialog(store=store)
    preview = dialog.preview.toPlainText()
    qualifier = "At least " if offset >= 0 else ""
    assert f"Elapsed: {qualifier}{elapsed} ms" in preview
    assert f"Workflow duration: {qualifier}{elapsed} ms" in preview
    assert f"Source queue drops: {qualifier}{recorder.dropped}" in preview
    destination = tmp_path / "selected.zip"
    assert store.export(REPORT_ID, destination).status is StoreStatus.EXPORTED
    with zipfile.ZipFile(destination) as archive:
        payload = json.loads(archive.read("incident.json"))
    assert payload["observation"]["source_dropped"] == recorder.dropped
    assert payload["observation"]["elapsed_ms"] == elapsed
    assert payload["events"][0]["duration_ms"] == elapsed
    dialog.close()


def test_viewer_revalidates_selected_incident_before_preview(tmp_path) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    dialog = IncidentDialog(store=store)
    report = store.root / f"incident-{REPORT_ID.hex}.json"
    report.write_bytes(b'{"unsafe":"sentinel"}')
    report.chmod(0o600)

    dialog._load_selected()

    assert dialog.preview.toPlainText() == "The selected incident could not be validated."
    assert "sentinel" not in dialog.preview.toPlainText()
    assert not dialog.export_button.isEnabled()
    dialog.close()


def test_export_cancel_calls_store_without_creating_output(tmp_path, monkeypatch) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    dialog = IncidentDialog(store=store)
    calls: list[tuple[uuid.UUID, object]] = []
    original_export = store.export

    def record_export(report_id, destination):
        calls.append((report_id, destination))
        return original_export(report_id, destination)

    monkeypatch.setattr(store, "export", record_export)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))

    dialog._export_selected()

    assert calls == [(REPORT_ID, None)]
    assert dialog.status_label.text() == "Export cancelled."
    assert list(tmp_path.rglob("*.zip")) == []
    dialog.close()


def test_export_preserves_existing_destination_and_reports_fixed_status(
    tmp_path, monkeypatch
) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"existing")
    dialog = IncidentDialog(store=store)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args: (str(destination), "ZIP archive (*.zip)"),
    )

    dialog._export_selected()

    assert destination.read_bytes() == b"existing"
    assert dialog.status_label.text() == (
        "The destination already exists; no file was replaced."
    )
    dialog.close()


def test_export_writes_only_selected_safe_bundle(tmp_path, monkeypatch) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    destination = tmp_path / "selected.zip"
    dialog = IncidentDialog(store=store)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args: (str(destination), "ZIP archive (*.zip)"),
    )

    dialog._export_selected()

    assert dialog.status_label.text() == "The selected incident was exported locally."
    with zipfile.ZipFile(destination) as bundle:
        assert set(bundle.namelist()) == {"incident.json", "manifest.json", "summary.json"}
    dialog.close()


def test_export_storage_failure_uses_fixed_message(tmp_path, monkeypatch) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    destination = tmp_path / "output.zip"
    dialog = IncidentDialog(store=store)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args: (str(destination), "ZIP archive (*.zip)"),
    )
    monkeypatch.setattr(
        store,
        "export",
        lambda *_args: StoreResult(StoreStatus.IO_FAILED, REPORT_ID),
    )

    dialog._export_selected()

    assert dialog.status_label.text() == "The incident could not be exported."
    assert str(destination) not in dialog.status_label.text()
    assert not destination.exists()
    dialog.close()


def test_unresolved_marker_is_described_without_crash_inference(tmp_path, monkeypatch) -> None:
    _app()
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.begin_session(SESSION_ID).status is StoreStatus.MARKER_STARTED
    monkeypatch.setattr(diagnostic_store, "_process_start_identity", lambda _pid: None)

    dialog = IncidentDialog(store=store)

    text = dialog.unclean_status_label.text().lower()
    assert dialog.unclean_list.count() == 1
    assert "cause is unknown" in text
    assert "not proof" in text
    assert "crashed" in text
    assert "did crash" not in text
    dialog.close()


def test_unavailable_default_store_does_not_prevent_viewer_opening(monkeypatch) -> None:
    _app()

    def unavailable_root():
        raise OSError("private root unavailable")

    monkeypatch.setattr(diagnostic_store, "_default_root", unavailable_root)
    dialog = open_incident_viewer()

    assert dialog.isVisible()
    assert dialog.reports_table.rowCount() == 0
    assert dialog.status_label.text() == "Incident storage is unavailable."
    assert "private root unavailable" not in dialog.status_label.text()
    dialog.close()
