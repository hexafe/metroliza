from __future__ import annotations

import json
import uuid

import pytest

from metroliza.shared import diagnostic_events
from metroliza.shared.diagnostic_events import (
    BuildPackager,
    DiagnosticOperation,
    ExceptionDiagnosticEvent,
    ExceptionKind,
    RuntimeMode,
    RuntimeProvenanceEvent,
    StartupCallsite,
    StartupDiagnosticEvent,
    StartupMode,
    StartupOutcome,
    ValidationStatus,
    WorkflowDiagnosticEvent,
    WorkflowError,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
    serialize_diagnostic_event,
)
from metroliza.shared.diagnostic_wire import (
    MAX_EVENT_BYTES,
    WireValidationError,
    decode_event,
    encode_event,
)


INVOCATION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
STARTUP_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OPERATION_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _workflow() -> WorkflowDiagnosticEvent:
    return WorkflowDiagnosticEvent(
        invocation_id=INVOCATION_ID,
        operation_id=OPERATION_ID,
        sequence=1,
        operation=WorkflowOperation.LOCAL_EXPORT,
        stage=WorkflowStage.STARTED,
        outcome=WorkflowOutcome.STARTED,
    )


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
        "ascii"
    )


@pytest.mark.parametrize(
    "event",
    [
        _workflow(),
        RuntimeProvenanceEvent(
            invocation_id=INVOCATION_ID,
            startup_id=STARTUP_ID,
            sequence=1,
            runtime=RuntimeMode.SOURCE,
            packager=BuildPackager.SOURCE,
            release_year=2026,
            release_month=9,
            release_candidate=None,
        ),
        StartupDiagnosticEvent(
            invocation_id=INVOCATION_ID,
            startup_id=STARTUP_ID,
            sequence=2,
            mode=StartupMode.UNKNOWN,
            callsite=StartupCallsite.BOOTSTRAP,
            outcome=StartupOutcome.STARTUP_FAILED,
            exception=ExceptionDiagnosticEvent(
                operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
                exception_kind=ExceptionKind.RUNTIME_ERROR,
                has_traceback=False,
                traceback_frames=0,
                cause_count=0,
                context_count=0,
                group_count=0,
                group_member_count=0,
                structure_truncated=False,
            ),
        ),
    ],
)
def test_wire_round_trip_preserves_canonical_safe_payload(event: object) -> None:
    encoded = encode_event(event)

    decoded = decode_event(encoded)

    assert serialize_diagnostic_event(decoded) == encoded.decode("ascii")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"[]",
        b"{}",
        b"\xff",
        b'{"event_code":"legacy_log_suppressed","event_code":"legacy_log_suppressed","source_class":"external"}',
        b'{"event_code":"legacy_log_suppressed","source_class":"external","path":"C:/private/report.xlsx"}',
        b'{"event_code":"legacy_log_suppressed","source_class":NaN}',
        b' {"event_code":"legacy_log_suppressed","source_class":"external"}',
        b'{"event_code":"legacy_log_suppressed","source_class":"external"}\n',
        ("[" * 1100 + "0" + "]" * 1100).encode("ascii"),
        b"x" * (MAX_EVENT_BYTES + 1),
    ],
)
def test_wire_rejects_noncanonical_malformed_and_schema_escape_bytes(payload: bytes) -> None:
    with pytest.raises(WireValidationError, match="^invalid diagnostic wire event$"):
        decode_event(payload)


def test_wire_rejects_bool_as_bounded_counter() -> None:
    payload = json.loads(encode_event(_workflow()))
    payload["selected_report_count"] = True

    with pytest.raises(WireValidationError, match="^invalid diagnostic wire event$"):
        decode_event(_canonical(payload))


def test_wire_rejects_invalid_cross_field_terminal_claim() -> None:
    payload = json.loads(encode_event(_workflow()))
    payload.update(stage="finished", outcome="completed", error="output_failed")

    with pytest.raises(WireValidationError, match="^invalid diagnostic wire event$"):
        decode_event(_canonical(payload))


def test_wire_rejects_counter_outside_its_named_workflow() -> None:
    payload = json.loads(encode_event(_workflow()))
    payload["selected_report_count"] = 1

    with pytest.raises(WireValidationError, match="^invalid diagnostic wire event$"):
        decode_event(_canonical(payload))


def test_workflow_completed_can_truthfully_leave_validation_not_performed() -> None:
    event = WorkflowDiagnosticEvent(
        invocation_id=INVOCATION_ID,
        operation_id=OPERATION_ID,
        sequence=8,
        operation=WorkflowOperation.LOCAL_EXPORT,
        stage=WorkflowStage.FINISHED,
        outcome=WorkflowOutcome.COMPLETED,
        error=WorkflowError.NONE,
        validation_status=ValidationStatus.NOT_PERFORMED,
        published_artifact_count=1,
        duration_ms=500,
    )

    payload = json.loads(encode_event(event))

    assert payload["validation_status"] == "not_performed"
    assert set(payload) == {
        "event_code",
        "invocation_id",
        "operation_id",
        "sequence",
        "operation",
        "stage",
        "outcome",
        "error",
        "validation_status",
        "selected_report_count",
        "imported_report_count",
        "published_artifact_count",
        "duration_ms",
    }


def test_export_omissions_are_distinct_from_fallback() -> None:
    event = WorkflowDiagnosticEvent(
        invocation_id=INVOCATION_ID,
        operation_id=OPERATION_ID,
        sequence=4,
        operation=WorkflowOperation.LOCAL_EXPORT,
        stage=WorkflowStage.FINISHED,
        outcome=WorkflowOutcome.COMPLETED_WITH_OMISSIONS,
    )

    assert json.loads(encode_event(event))["outcome"] == "completed_with_omissions"


def test_import_warnings_keep_closed_error_and_authoritative_counts() -> None:
    event = WorkflowDiagnosticEvent(
        invocation_id=INVOCATION_ID,
        operation_id=OPERATION_ID,
        sequence=4,
        operation=WorkflowOperation.SELECTED_IMPORT,
        stage=WorkflowStage.FINISHED,
        outcome=WorkflowOutcome.COMPLETED_WITH_WARNINGS,
        error=WorkflowError.PROCESSING_FAILED,
        selected_report_count=5,
        imported_report_count=3,
    )

    payload = json.loads(encode_event(event))
    assert payload["outcome"] == "completed_with_warnings"
    assert payload["imported_report_count"] == 3

    with pytest.raises(diagnostic_events.DiagnosticEventValidationError):
        WorkflowDiagnosticEvent(
            invocation_id=INVOCATION_ID,
            operation_id=OPERATION_ID,
            sequence=5,
            operation=WorkflowOperation.SELECTED_IMPORT,
            stage=WorkflowStage.FINISHED,
            outcome=WorkflowOutcome.COMPLETED_WITH_WARNINGS,
            error=WorkflowError.INPUT_REJECTED,
            selected_report_count=2,
            imported_report_count=3,
        )
