from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
import types
import uuid
import zipfile

from metroliza.shared import diagnostic_store
from metroliza.shared.diagnostic_events import (
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
    encode_incident,
)
from metroliza.shared.diagnostic_ring import LOSS_ACCOUNTING_BYTES, RingLoss, RingSnapshot
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
from metroliza.shared.diagnostic_wire import encode_event

SESSION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
REPORT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OPERATION_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _incident(
    *,
    report_id: uuid.UUID = REPORT_ID,
    session_id: uuid.UUID = SESSION_ID,
    created_at_ms: int | None = None,
):
    event = encode_event(
        WorkflowDiagnosticEvent(
            invocation_id=session_id,
            operation_id=OPERATION_ID,
            sequence=1,
            operation=WorkflowOperation.LOCAL_EXPORT,
            stage=WorkflowStage.STARTED,
            outcome=WorkflowOutcome.STARTED,
        )
    )
    history = RingSnapshot((event,), RingLoss(), len(event) + LOSS_ACCOUNTING_BYTES)
    observation = IncidentObservation(
        launch=LaunchState.STARTED,
        handshake=HandshakeState.ACCEPTED,
        channel=ChannelState.COMPLETE,
        exit_code=7,
        termination=TerminationState.OBSERVED_EXIT,
        clean_terminal_received=True,
        source_dropped=0,
        source_loss_known=True,
        elapsed_ms=20,
    )
    return build_incident(
        report_id=report_id,
        session_id=session_id,
        created_at_ms=time.time_ns() // 1_000_000 if created_at_ms is None else created_at_ms,
        build_git_sha="a" * 40,
        observation=observation,
        history=history,
    )


def test_interrupted_link_publication_recovers_exact_pair_without_losing_prior_incidents(tmp_path):
    store = IncidentStore(tmp_path / "state")
    prior = _incident()
    assert store.publish(prior).status is StoreStatus.SAVED
    later = _incident(report_id=uuid.uuid4())
    stage = diagnostic_store._write_stage(store.root, encode_incident(later))
    final = store.root / f"incident-{later.report_id.hex}.json"
    os.link(stage, final)
    assert final.stat().st_nlink == 2
    reopened = IncidentStore(store.root)
    listing = reopened.list_reports()
    assert listing.status is StoreStatus.AVAILABLE
    assert {row.report_id for row in listing.reports} == {prior.report_id, later.report_id}
    assert not stage.exists()
    assert final.stat().st_nlink == 1
    assert reopened.load(prior.report_id).incident == prior
    assert reopened.load(later.report_id).incident == later


def test_recovery_rejects_internal_pair_with_an_external_alias(tmp_path):
    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    incident = _incident()
    stage = diagnostic_store._write_stage(store.root, encode_incident(incident))
    final = store.root / f"incident-{incident.report_id.hex}.json"
    alias = tmp_path / "external-alias.json"
    os.link(stage, final)
    os.link(stage, alias)

    assert store.list_reports().status is StoreStatus.ROOT_UNAVAILABLE
    assert stage.exists()
    assert final.exists()
    assert alias.exists()


def test_recovery_rejects_unmatched_internal_hardlink_pair(tmp_path):
    store = IncidentStore(tmp_path / "state")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    first = diagnostic_store._write_stage(store.root, b"bounded")
    second = store.root / f".stage-{uuid.uuid4().hex}.tmp"
    os.link(first, second)

    assert store.list_reports().status is StoreStatus.ROOT_UNAVAILABLE
    assert first.exists()
    assert second.exists()


def test_publish_list_and_load_revalidate_private_complete_incident(tmp_path) -> None:
    root = tmp_path / "state" / "diagnostics"
    store = IncidentStore(root)
    incident = _incident()

    result = store.publish(incident)
    listing = store.list_reports()
    loaded = store.load(REPORT_ID)

    assert result.status is StoreStatus.SAVED
    assert listing.status is StoreStatus.AVAILABLE
    assert [record.report_id for record in listing.reports] == [REPORT_ID]
    assert loaded.status is StoreStatus.AVAILABLE
    assert loaded.incident == incident
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    report_path = root / f"incident-{REPORT_ID.hex}.json"
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert report_path.stat().st_nlink == 1


def test_inventory_uses_full_path_metadata_when_direntry_identity_is_zero(
    tmp_path, monkeypatch
) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    incident = _incident()
    assert store.publish(incident).status is StoreStatus.SAVED
    real_scandir = os.scandir
    with real_scandir(store.root) as entries:
        scanned = tuple((entry.name, entry.path) for entry in entries)
    weak_stat_calls: list[str] = []

    class WeakWindowsEntry:
        def __init__(self, name, path):
            self.name, self.path = name, path

        def stat(self, *, follow_symlinks=True):
            weak_stat_calls.append(self.name)
            metadata = os.stat(self.path, follow_symlinks=follow_symlinks)
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

    monkeypatch.setattr(diagnostic_store.os, "scandir", lambda _root: WeakWindowsScan())

    inventory = store._inventory()

    assert inventory is not None
    assert inventory.reports == (
        store.root / f"incident-{incident.report_id.hex}.json",
    )
    assert inventory.total_bytes == len(encode_incident(incident))
    assert weak_stat_calls == []


def test_quota_failure_preserves_previous_complete_report(tmp_path, monkeypatch) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    first = _incident()
    second_id = uuid.UUID("44444444-4444-4444-8444-444444444444")
    second = _incident(report_id=second_id)
    assert store.publish(first).status is StoreStatus.SAVED
    original = encode_incident(first)
    monkeypatch.setattr(diagnostic_store, "MAX_REPORTS", 1)

    result = store.publish(second)

    assert result.status is StoreStatus.QUOTA_EXCEEDED
    assert store.load(REPORT_ID).incident == first
    assert (store.root / f"incident-{REPORT_ID.hex}.json").read_bytes() == original
    assert not (store.root / f"incident-{second_id.hex}.json").exists()


def test_expired_reports_are_not_loaded_and_are_cleaned_before_publish(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    old_ms = time.time_ns() // 1_000_000 - diagnostic_store.MAX_AGE_MS - 1
    old_ids: list[uuid.UUID] = []
    for index in range(diagnostic_store.MAX_REPORTS):
        report_id = uuid.UUID(f"{index + 100:08x}-0000-4000-8000-000000000000")
        session_id = uuid.UUID(f"{index + 200:08x}-0000-4000-8000-000000000000")
        old_ids.append(report_id)
        payload = encode_incident(
            _incident(report_id=report_id, session_id=session_id, created_at_ms=old_ms)
        )
        path = store.root / f"incident-{report_id.hex}.json"
        path.write_bytes(payload)
        path.chmod(0o600)

    assert store.load(old_ids[0]).status is StoreStatus.INVALID
    current = _incident()
    result = store.publish(current)

    assert result.status is StoreStatus.SAVED
    assert all(
        not (store.root / f"incident-{report_id.hex}.json").exists() for report_id in old_ids
    )
    assert store.load(REPORT_ID).incident == current


def test_publish_failure_does_not_replace_existing_report(tmp_path, monkeypatch) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    first = _incident()
    assert store.publish(first).status is StoreStatus.SAVED
    second_id = uuid.UUID("44444444-4444-4444-8444-444444444444")
    original = encode_incident(first)

    def fail_publish(_stage, _final):
        raise OSError("synthetic")

    monkeypatch.setattr(diagnostic_store, "_publish_stage", fail_publish)
    result = store.publish(_incident(report_id=second_id))

    assert result.status is StoreStatus.IO_FAILED
    assert (store.root / f"incident-{REPORT_ID.hex}.json").read_bytes() == original
    assert not (store.root / f"incident-{second_id.hex}.json").exists()


def test_failed_post_publish_readback_rolls_back_only_new_inode(tmp_path, monkeypatch) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    original_reader = diagnostic_store._safe_file_bytes
    final = store.root / f"incident-{REPORT_ID.hex}.json"

    def fail_final(path, maximum):
        if path == final:
            raise OSError("synthetic_readback_failure")
        return original_reader(path, maximum)

    monkeypatch.setattr(diagnostic_store, "_safe_file_bytes", fail_final)
    result = store.publish(_incident())

    assert result.status is StoreStatus.IO_FAILED
    assert not final.exists()


def test_two_concurrent_publications_are_serialized(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    identifiers = (
        REPORT_ID,
        uuid.UUID("44444444-4444-4444-8444-444444444444"),
    )
    barrier = threading.Barrier(2)
    statuses: list[StoreStatus] = []

    def publish(identifier: uuid.UUID) -> None:
        barrier.wait()
        statuses.append(store.publish(_incident(report_id=identifier)).status)

    threads = [threading.Thread(target=publish, args=(identifier,)) for identifier in identifiers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses == [StoreStatus.SAVED, StoreStatus.SAVED]
    assert {record.report_id for record in store.list_reports().reports} == set(identifiers)


def test_two_cross_process_publications_keep_distinct_session_history(tmp_path) -> None:
    root = tmp_path / "diagnostics"
    first_report = REPORT_ID
    second_report = uuid.UUID("44444444-4444-4444-8444-444444444444")
    first_session = SESSION_ID
    second_session = uuid.UUID("55555555-5555-4555-8555-555555555555")
    payloads = (
        (tmp_path / "first.incident", _incident(report_id=first_report, session_id=first_session)),
        (
            tmp_path / "second.incident",
            _incident(report_id=second_report, session_id=second_session),
        ),
    )
    script = (
        "from pathlib import Path; import sys; "
        "from metroliza.shared.diagnostic_store import IncidentStore; "
        "print(IncidentStore(Path(sys.argv[1])).publish(Path(sys.argv[2]).read_bytes()).status.value)"
    )
    children = []
    for path, incident in payloads:
        path.write_bytes(encode_incident(incident))
        children.append(
            subprocess.Popen(
                [sys.executable, "-c", script, str(root), str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    statuses = []
    for child in children:
        stdout, _stderr = child.communicate(timeout=5)
        assert child.returncode == 0
        statuses.append(stdout.strip())
    assert set(statuses) <= {StoreStatus.SAVED.value, StoreStatus.LOCK_UNAVAILABLE.value}
    assert StoreStatus.SAVED.value in statuses

    store = IncidentStore(root)
    listing = store.list_reports()
    assert listing.status is StoreStatus.AVAILABLE
    expected_sessions = {first_report: first_session, second_report: second_session}
    reports_by_status = zip((first_report, second_report), statuses)
    assert {record.report_id for record in listing.reports} == {
        report for report, status in reports_by_status if status == StoreStatus.SAVED.value
    }
    for record in listing.reports:
        incident = store.load(record.report_id).incident
        assert incident is not None
        expected = expected_sessions[record.report_id]
        assert incident.session_id == expected
        assert {json.loads(event)["invocation_id"] for event in incident.events} == {
            expected.hex
        }


def test_list_distinguishes_unavailable_store_from_empty_store(tmp_path, monkeypatch) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.list_reports().status is StoreStatus.AVAILABLE

    monkeypatch.setattr(diagnostic_store._StoreLock, "acquire", lambda _self: False)
    unavailable = store.list_reports()

    assert unavailable.status is StoreStatus.LOCK_UNAVAILABLE
    assert unavailable.reports == ()


def test_default_root_failure_is_lazy_and_all_store_operations_fail_closed(
    tmp_path, monkeypatch
) -> None:
    def unavailable_root():
        raise OSError("synthetic_default_root_failure")

    monkeypatch.setattr(diagnostic_store, "_default_root", unavailable_root)
    store = IncidentStore()
    destination = tmp_path / "selected.zip"

    assert store.root is None
    assert store.publish(_incident()).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.list_reports().status is StoreStatus.ROOT_UNAVAILABLE
    assert store.load(REPORT_ID).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.export(REPORT_ID, destination).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.begin_session(SESSION_ID).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.authenticate_session(SESSION_ID).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.end_session(SESSION_ID, clean=False).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.resolve_session(SESSION_ID, REPORT_ID).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.list_unclean_sessions().status is StoreStatus.ROOT_UNAVAILABLE
    assert not destination.exists()


def test_symlink_root_and_hardlinked_report_fail_closed(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    assert IncidentStore(link).list_reports().status is StoreStatus.ROOT_UNAVAILABLE

    store = IncidentStore(tmp_path / "safe")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    report = store.root / f"incident-{REPORT_ID.hex}.json"
    os.link(report, tmp_path / "alias.json")

    assert store.load(REPORT_ID).status is StoreStatus.ROOT_UNAVAILABLE
    assert store.list_reports().status is StoreStatus.ROOT_UNAVAILABLE


def test_corrupt_stored_incident_is_not_listed_or_loaded_as_empty(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.publish(_incident()).status is StoreStatus.SAVED
    report = store.root / f"incident-{REPORT_ID.hex}.json"
    report.write_bytes(b'{"path":"C:/private/report.xlsx"}')

    assert store.load(REPORT_ID).status is StoreStatus.INVALID
    assert store.list_reports().status is StoreStatus.INVALID


def test_export_cancel_existing_destination_and_exact_safe_members(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    incident = _incident()
    assert store.publish(incident).status is StoreStatus.SAVED

    assert store.export(REPORT_ID, None).status is StoreStatus.CANCELLED
    existing = tmp_path / "existing.zip"
    existing.write_bytes(b"preserve")
    assert store.export(REPORT_ID, existing).status is StoreStatus.DESTINATION_EXISTS
    assert existing.read_bytes() == b"preserve"

    destination = tmp_path / "incident.zip"
    assert store.export(REPORT_ID, destination).status is StoreStatus.EXPORTED
    with zipfile.ZipFile(destination) as bundle:
        assert set(bundle.namelist()) == {"incident.json", "manifest.json", "summary.json"}
        incident_bytes = bundle.read("incident.json")
        manifest = json.loads(bundle.read("manifest.json"))
        summary = json.loads(bundle.read("summary.json"))
    assert incident_bytes == encode_incident(incident)
    manifest_entry = next(item for item in manifest["files"] if item["name"] == "incident.json")
    assert manifest_entry["sha256"] == hashlib.sha256(incident_bytes).hexdigest()
    assert summary["native_stack"] == "unavailable"
    assert "supervisor_pid" not in destination.read_bytes().decode("latin1")


def test_marker_tracks_started_authenticated_clean_and_does_not_export(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.begin_session(SESSION_ID).status is StoreStatus.MARKER_STARTED
    assert store.list_unclean_sessions().sessions == ()
    assert store.end_session(SESSION_ID, clean=True).status is StoreStatus.INVALID
    assert store.authenticate_session(SESSION_ID).status is StoreStatus.MARKER_AUTHENTICATED
    assert store.end_session(SESSION_ID, clean=True).status is StoreStatus.MARKER_CLEAN_ENDED
    assert store.list_unclean_sessions().sessions == ()

    assert store.publish(_incident()).status is StoreStatus.SAVED
    destination = tmp_path / "incident.zip"
    assert store.export(REPORT_ID, destination).status is StoreStatus.EXPORTED
    with zipfile.ZipFile(destination) as bundle:
        assert not any(name.startswith("marker") for name in bundle.namelist())


def test_unclean_marker_is_conservative_and_false_retention_is_rejected(
    tmp_path, monkeypatch
) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    missing = uuid.UUID("44444444-4444-4444-8444-444444444444")
    assert store.end_session(missing, clean=False).status is StoreStatus.NOT_FOUND
    assert store.begin_session(SESSION_ID).status is StoreStatus.MARKER_STARTED

    monkeypatch.setattr(diagnostic_store, "_process_start_identity", lambda _pid: None)
    result = store.list_unclean_sessions()

    assert result.status is StoreStatus.AVAILABLE
    assert len(result.sessions) == 1
    assert result.sessions[0].session_id == SESSION_ID
    assert result.sessions[0].state == "unclean_unknown"


def test_matching_published_incident_resolves_only_its_exact_unclean_marker(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.begin_session(SESSION_ID).status is StoreStatus.MARKER_STARTED
    assert store.publish(_incident()).status is StoreStatus.SAVED

    result = store.resolve_session(SESSION_ID, REPORT_ID)

    assert result.status is StoreStatus.MARKER_RESOLVED
    assert result.report_id == REPORT_ID
    assert not (store.root / f"marker-{SESSION_ID.hex}.json").exists()
    assert store.load(REPORT_ID).status is StoreStatus.AVAILABLE


def test_abandoned_stage_and_excess_clean_markers_are_boundedly_cleaned(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    assert store.list_reports().status is StoreStatus.AVAILABLE
    abandoned = store.root / f".stage-{uuid.uuid4().hex}.tmp"
    abandoned.write_bytes(b"safe-stage")
    for index in range(21):
        identifier = uuid.UUID(f"{index + 10:08x}-0000-4000-8000-000000000000")
        assert store.begin_session(identifier).status is StoreStatus.MARKER_STARTED
        assert store.authenticate_session(identifier).status is StoreStatus.MARKER_AUTHENTICATED
        assert store.end_session(identifier, clean=True).status is StoreStatus.MARKER_CLEAN_ENDED

    next_id = uuid.UUID("55555555-5555-4555-8555-555555555555")
    assert store.begin_session(next_id).status is StoreStatus.MARKER_STARTED

    assert not abandoned.exists()
    marker_count = len(list(store.root.glob("marker-*.json")))
    assert marker_count <= 21


def test_cleanup_expires_only_old_clean_markers(tmp_path) -> None:
    store = IncidentStore(tmp_path / "diagnostics")
    clean_id = uuid.UUID("66666666-6666-4666-8666-666666666666")
    unknown_id = uuid.UUID("77777777-7777-4777-8777-777777777777")
    next_id = uuid.UUID("88888888-8888-4888-8888-888888888888")
    assert store.begin_session(clean_id).status is StoreStatus.MARKER_STARTED
    assert store.authenticate_session(clean_id).status is StoreStatus.MARKER_AUTHENTICATED
    assert store.end_session(clean_id, clean=True).status is StoreStatus.MARKER_CLEAN_ENDED
    assert store.begin_session(unknown_id).status is StoreStatus.MARKER_STARTED

    old_ms = time.time_ns() // 1_000_000 - diagnostic_store.MAX_AGE_MS - 1
    process_identity = diagnostic_store._process_start_identity(os.getpid())
    assert process_identity is not None
    for identifier, phase in ((clean_id, "clean_ended"), (unknown_id, "started")):
        path = store.root / f"marker-{identifier.hex}.json"
        path.write_bytes(
            diagnostic_store._marker_bytes(
                identifier,
                "unknown",
                os.getpid(),
                process_identity,
                phase,
                old_ms,
            )
        )
        path.chmod(0o600)

    assert store.begin_session(next_id).status is StoreStatus.MARKER_STARTED
    assert not (store.root / f"marker-{clean_id.hex}.json").exists()
    assert (store.root / f"marker-{unknown_id.hex}.json").exists()


def test_windows_process_identity_uses_pointer_width_handle_and_filetime(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class FakeFunction:
        def __init__(self, implementation):
            self.implementation = implementation
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.implementation(*args)

    handle = 0x1234_5678_8765_4321

    def get_times(received, creation, _exit, _kernel, _user):
        observed["get_handle"] = received
        creation._obj.dwHighDateTime = 0x01234567
        creation._obj.dwLowDateTime = 0x89ABCDEF
        return 1

    def close(received):
        observed["close_handle"] = received
        return 1

    kernel = types.SimpleNamespace(
        OpenProcess=FakeFunction(lambda _access, _inherit, _pid: handle),
        GetProcessTimes=FakeFunction(get_times),
        CloseHandle=FakeFunction(close),
    )
    monkeypatch.setattr(
        diagnostic_store.ctypes,
        "windll",
        types.SimpleNamespace(kernel32=kernel),
        raising=False,
    )

    identity = diagnostic_store._windows_process_start_identity(99)

    assert identity == 0x0123456789ABCDEF
    assert observed == {"get_handle": handle, "close_handle": handle}
    assert kernel.OpenProcess.restype is not None
    assert kernel.GetProcessTimes.argtypes is not None
