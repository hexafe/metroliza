from __future__ import annotations

import json
import uuid

import pytest

from metroliza.shared.diagnostic_events import (
    WorkflowDiagnosticEvent,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_incident import (
    MAX_INCIDENT_BYTES,
    ChannelState,
    HandshakeState,
    IncidentObservation,
    IncidentValidationError,
    LaunchState,
    TerminationState,
    build_incident,
    decode_incident,
    encode_incident,
)
from metroliza.shared.diagnostic_ring import LOSS_ACCOUNTING_BYTES, RingLoss, RingSnapshot
from metroliza.shared.diagnostic_wire import encode_event


SESSION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
REPORT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OPERATION_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _observation(
    *,
    channel: ChannelState = ChannelState.COMPLETE,
    source_dropped: int = 0,
) -> IncidentObservation:
    return IncidentObservation(
        launch=LaunchState.STARTED,
        handshake=HandshakeState.ACCEPTED,
        channel=channel,
        exit_code=1,
        termination=TerminationState.OBSERVED_EXIT,
        clean_terminal_received=True,
        source_dropped=source_dropped,
        source_loss_known=True,
        elapsed_ms=25,
    )


def _event(sequence: int = 1) -> bytes:
    return encode_event(
        WorkflowDiagnosticEvent(
            invocation_id=SESSION_ID,
            operation_id=OPERATION_ID,
            sequence=sequence,
            operation=WorkflowOperation.LOCAL_EXPORT,
            stage=WorkflowStage.STARTED,
            outcome=WorkflowOutcome.STARTED,
        )
    )


def _incident(
    *, history: RingSnapshot | None = None, observation: IncidentObservation | None = None
):
    selected = history or RingSnapshot(
        (_event(),), RingLoss(), len(_event()) + LOSS_ACCOUNTING_BYTES
    )
    return build_incident(
        session_id=SESSION_ID,
        report_id=REPORT_ID,
        created_at_ms=1_800_000_000_000,
        build_git_sha="a" * 64,
        observation=observation or _observation(),
        history=selected,
    )


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
        "ascii"
    )


def test_incident_round_trip_keeps_only_closed_safe_fields() -> None:
    encoded = encode_incident(_incident())

    decoded = decode_incident(encoded)

    assert encode_incident(decoded) == encoded
    assert set(json.loads(encoded)) == {
        "schema_version",
        "report_id",
        "session_id",
        "created_at_ms",
        "build_git_sha",
        "observation",
        "events",
        "ring_loss",
        "native_stack",
    }
    assert decoded.native_stack == "unavailable"
    assert decoded.build_git_sha == "a" * 64


def test_incident_accepts_clean_terminal_with_explicit_source_loss() -> None:
    incident = _incident(
        observation=_observation(channel=ChannelState.LOSS_OBSERVED, source_dropped=3)
    )

    decoded = decode_incident(encode_incident(incident))

    assert decoded.observation.clean_terminal_received is True
    assert decoded.observation.channel is ChannelState.LOSS_OBSERVED
    assert decoded.observation.source_dropped == 3


def test_incident_requires_loss_observed_for_ring_rejection() -> None:
    loss = RingLoss(invalid_events=1, invalid_bytes=12)
    history = RingSnapshot((_event(),), loss, len(_event()) + LOSS_ACCOUNTING_BYTES)

    with pytest.raises(IncidentValidationError, match="^invalid diagnostic incident$"):
        _incident(history=history)

    accepted = _incident(
        history=history, observation=_observation(channel=ChannelState.LOSS_OBSERVED)
    )
    assert decode_incident(encode_incident(accepted)).ring_loss.invalid_events == 1


def test_incident_rejects_event_from_another_session() -> None:
    other = uuid.UUID("44444444-4444-4444-8444-444444444444")
    event = encode_event(
        WorkflowDiagnosticEvent(
            invocation_id=other,
            operation_id=OPERATION_ID,
            sequence=1,
            operation=WorkflowOperation.LOCAL_EXPORT,
            stage=WorkflowStage.STARTED,
            outcome=WorkflowOutcome.STARTED,
        )
    )
    history = RingSnapshot((event,), RingLoss(), len(event) + LOSS_ACCOUNTING_BYTES)

    with pytest.raises(IncidentValidationError, match="^invalid diagnostic incident$"):
        _incident(history=history)


def test_incident_rejects_duplicate_or_regressing_sequences() -> None:
    first = _event(2)
    duplicate = _event(2)
    history = RingSnapshot(
        (first, duplicate),
        RingLoss(),
        len(first) + len(duplicate) + LOSS_ACCOUNTING_BYTES,
    )

    with pytest.raises(IncidentValidationError, match="^invalid diagnostic incident$"):
        _incident(history=history)


def test_incident_rejects_false_saturation_claim() -> None:
    loss = RingLoss(counters_saturated=True)
    history = RingSnapshot((_event(),), loss, len(_event()) + LOSS_ACCOUNTING_BYTES)

    with pytest.raises(IncidentValidationError, match="^invalid diagnostic incident$"):
        _incident(
            history=history,
            observation=_observation(channel=ChannelState.LOSS_OBSERVED),
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(path="C:/private/report.xlsx"),
        lambda payload: payload["observation"].update(source_loss_known=False),
        lambda payload: payload.update(native_stack="raw_dump_attached"),
        lambda payload: payload["events"].append(payload["events"][0]),
    ],
)
def test_incident_decoder_rejects_schema_escape_and_inconsistent_claims(mutator) -> None:
    payload = json.loads(encode_incident(_incident()))
    mutator(payload)

    with pytest.raises(IncidentValidationError, match="^invalid diagnostic incident$"):
        decode_incident(_canonical(payload))


def test_incident_decoder_rejects_duplicate_keys_and_oversize_before_schema_use() -> None:
    with pytest.raises(IncidentValidationError, match="^invalid diagnostic incident$"):
        decode_incident(b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(IncidentValidationError, match="^invalid diagnostic incident$"):
        decode_incident(b"x" * (MAX_INCIDENT_BYTES + 1))
