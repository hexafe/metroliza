from __future__ import annotations

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
    ValidationStatus,
    WorkflowDiagnosticEvent,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_incident import (
    ChannelState,
    HandshakeState,
    IncidentObservation,
    LaunchState,
    TerminationState,
    build_incident,
)
from metroliza.shared.diagnostic_ring import LOSS_ACCOUNTING_BYTES, RingLoss, RingSnapshot
from metroliza.shared.diagnostic_store import IncidentStore, StoreResult, StoreStatus
from metroliza.shared.diagnostic_wire import encode_event
from metroliza.ui.incident_dialog import IncidentDialog, open_incident_viewer


SESSION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
REPORT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OPERATION_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _incident(*, loss: bool = False):
    event = encode_event(
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
    )
    ring_loss = RingLoss(invalid_events=1, invalid_bytes=9) if loss else RingLoss()
    history = RingSnapshot((event,), ring_loss, len(event) + LOSS_ACCOUNTING_BYTES)
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
        report_id=REPORT_ID,
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
