"""Closed, share-safe incident envelope for supervised diagnostics."""

from __future__ import annotations

import dataclasses
import json
import re
import uuid
from dataclasses import dataclass
from enum import Enum

from metroliza.shared.diagnostic_events import (
    RuntimeProvenanceEvent,
    StartupDiagnosticEvent,
    WorkflowDiagnosticEvent,
)
from metroliza.shared.diagnostic_ring import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_EVENTS,
    LOSS_ACCOUNTING_BYTES,
    RingLoss,
    RingSnapshot,
)
from metroliza.shared.diagnostic_wire import WireValidationError, decode_event, encode_event


INCIDENT_SCHEMA_VERSION = 1
MAX_INCIDENT_BYTES = 3 * 1024 * 1024
MAX_COUNTER = 2**32 - 1
MAX_ELAPSED_MS = 86_400_000
MAX_UNIX_MS = 2**63 - 1
_INCIDENT_ERROR = "invalid diagnostic incident"
_UUID_HEX = re.compile(r"[0-9a-f]{32}\Z")
_BUILD_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class IncidentValidationError(ValueError):
    """Raised without reflecting incident-controlled content."""


class LaunchState(str, Enum):
    STARTED = "started"
    FAILED = "failed"


class HandshakeState(str, Enum):
    MISSING = "missing"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


class ChannelState(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    FLOODED = "flooded"
    LOSS_OBSERVED = "loss_observed"


class TerminationState(str, Enum):
    NOT_STARTED = "not_started"
    OBSERVED_EXIT = "observed_exit"
    POSIX_SIGNAL = "posix_signal"
    STILL_RUNNING = "still_running"


@dataclass(frozen=True, slots=True)
class IncidentObservation:
    launch: LaunchState
    handshake: HandshakeState
    channel: ChannelState
    exit_code: int | None
    termination: TerminationState
    clean_terminal_received: bool
    source_dropped: int
    source_loss_known: bool
    elapsed_ms: int

    def __post_init__(self) -> None:
        _observation_payload(self)


@dataclass(frozen=True, slots=True)
class DiagnosticIncident:
    schema_version: int
    report_id: uuid.UUID
    session_id: uuid.UUID
    created_at_ms: int
    build_git_sha: str
    observation: IncidentObservation
    events: tuple[bytes, ...]
    ring_loss: RingLoss
    native_stack: str = "unavailable"

    def __post_init__(self) -> None:
        _incident_payload(self)


def _literal(value: object, enum_type: type[Enum]) -> str:
    if type(value) is not enum_type:
        raise IncidentValidationError(_INCIDENT_ERROR)
    literal = value.value
    if type(literal) is not str:
        raise IncidentValidationError(_INCIDENT_ERROR)
    return literal


def _bounded_integer(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _uuid_hex(value: object) -> str:
    if type(value) is not uuid.UUID:
        raise IncidentValidationError(_INCIDENT_ERROR)
    text = value.hex
    if _UUID_HEX.fullmatch(text) is None or text[12] != "4" or text[16] not in "89ab":
        raise IncidentValidationError(_INCIDENT_ERROR)
    return text


def _build_sha(value: object) -> str:
    if type(value) is not str or (value != "unknown" and _BUILD_SHA.fullmatch(value) is None):
        raise IncidentValidationError(_INCIDENT_ERROR)
    return value


def _observation_payload(observation: IncidentObservation) -> dict[str, object]:
    launch = _literal(observation.launch, LaunchState)
    handshake = _literal(observation.handshake, HandshakeState)
    channel = _literal(observation.channel, ChannelState)
    termination = _literal(observation.termination, TerminationState)
    _validate_observation_scalars(observation)
    _validate_observation_termination(observation)
    _validate_observation_channel(observation)
    return {
        "launch": launch,
        "handshake": handshake,
        "channel": channel,
        "exit_code": observation.exit_code,
        "termination": termination,
        "clean_terminal_received": observation.clean_terminal_received,
        "source_dropped": observation.source_dropped,
        "source_loss_known": observation.source_loss_known,
        "elapsed_ms": observation.elapsed_ms,
    }


def _validate_observation_scalars(observation: IncidentObservation) -> None:
    if observation.exit_code is not None and (
        type(observation.exit_code) is not int or not -(2**31) <= observation.exit_code <= 2**32 - 1
    ):
        raise IncidentValidationError(_INCIDENT_ERROR)
    if type(observation.clean_terminal_received) is not bool:
        raise IncidentValidationError(_INCIDENT_ERROR)
    if not _bounded_integer(observation.source_dropped, MAX_COUNTER):
        raise IncidentValidationError(_INCIDENT_ERROR)
    if type(observation.source_loss_known) is not bool:
        raise IncidentValidationError(_INCIDENT_ERROR)
    if not _bounded_integer(observation.elapsed_ms, MAX_ELAPSED_MS):
        raise IncidentValidationError(_INCIDENT_ERROR)
    if not observation.source_loss_known and observation.source_dropped != 0:
        raise IncidentValidationError(_INCIDENT_ERROR)
    if observation.source_loss_known:
        if (
            observation.handshake is not HandshakeState.ACCEPTED
            or not observation.clean_terminal_received
        ):
            raise IncidentValidationError(_INCIDENT_ERROR)


def _validate_observation_termination(observation: IncidentObservation) -> None:
    if observation.launch is LaunchState.FAILED:
        valid = (
            observation.termination is TerminationState.NOT_STARTED
            and observation.exit_code is None
            and observation.handshake is not HandshakeState.ACCEPTED
            and not observation.clean_terminal_received
        )
        if not valid:
            raise IncidentValidationError(_INCIDENT_ERROR)
    elif observation.termination is TerminationState.NOT_STARTED:
        raise IncidentValidationError(_INCIDENT_ERROR)
    if observation.termination in (TerminationState.OBSERVED_EXIT, TerminationState.POSIX_SIGNAL):
        if observation.exit_code is None:
            raise IncidentValidationError(_INCIDENT_ERROR)
    elif observation.exit_code is not None:
        raise IncidentValidationError(_INCIDENT_ERROR)
    if observation.termination is TerminationState.POSIX_SIGNAL and observation.exit_code >= 0:
        raise IncidentValidationError(_INCIDENT_ERROR)


def _validate_observation_channel(observation: IncidentObservation) -> None:
    if observation.clean_terminal_received:
        valid = (
            observation.handshake is HandshakeState.ACCEPTED
            and observation.channel in (ChannelState.COMPLETE, ChannelState.LOSS_OBSERVED)
            and observation.source_loss_known
        )
        if not valid:
            raise IncidentValidationError(_INCIDENT_ERROR)
    if observation.channel is ChannelState.COMPLETE and not observation.clean_terminal_received:
        raise IncidentValidationError(_INCIDENT_ERROR)



def _loss_payload(loss: RingLoss) -> dict[str, object]:
    if type(loss) is not RingLoss:
        raise IncidentValidationError(_INCIDENT_ERROR)
    payload = dataclasses.asdict(loss)
    for key, value in payload.items():
        if key == "counters_saturated":
            if type(value) is not bool:
                raise IncidentValidationError(_INCIDENT_ERROR)
        elif not _bounded_integer(value, MAX_COUNTER):
            raise IncidentValidationError(_INCIDENT_ERROR)
    if payload["counters_saturated"] and not any(
        value == MAX_COUNTER for key, value in payload.items() if key != "counters_saturated"
    ):
        raise IncidentValidationError(_INCIDENT_ERROR)
    return payload


def _event_payloads(events: object, session_id: str) -> tuple[list[dict[str, object]], int]:
    if type(events) is not tuple or len(events) > DEFAULT_MAX_EVENTS:
        raise IncidentValidationError(_INCIDENT_ERROR)
    payloads: list[dict[str, object]] = []
    encoded_bytes = LOSS_ACCOUNTING_BYTES
    sequences: dict[tuple[str, str], int] = {}
    for encoded in events:
        try:
            event = decode_event(encoded)
            canonical = encode_event(event)
        except WireValidationError:
            raise IncidentValidationError(_INCIDENT_ERROR) from None
        if type(event) not in (
            RuntimeProvenanceEvent,
            StartupDiagnosticEvent,
            WorkflowDiagnosticEvent,
        ):
            raise IncidentValidationError(_INCIDENT_ERROR)
        if event.invocation_id.hex != session_id:
            raise IncidentValidationError(_INCIDENT_ERROR)
        if type(event) is WorkflowDiagnosticEvent:
            sequence_key = ("workflow", event.operation_id.hex)
        else:
            sequence_key = ("startup", event.startup_id.hex)
        previous = sequences.get(sequence_key)
        if previous is not None and event.sequence <= previous:
            raise IncidentValidationError(_INCIDENT_ERROR)
        sequences[sequence_key] = event.sequence
        value = json.loads(canonical)
        if type(value) is not dict:
            raise IncidentValidationError(_INCIDENT_ERROR)
        payloads.append(value)
        encoded_bytes += len(canonical)
    if encoded_bytes > DEFAULT_MAX_BYTES:
        raise IncidentValidationError(_INCIDENT_ERROR)
    return payloads, encoded_bytes


def _incident_payload(incident: DiagnosticIncident) -> dict[str, object]:
    if (
        incident.schema_version != INCIDENT_SCHEMA_VERSION
        or type(incident.schema_version) is not int
    ):
        raise IncidentValidationError(_INCIDENT_ERROR)
    report_id = _uuid_hex(incident.report_id)
    session_id = _uuid_hex(incident.session_id)
    if report_id == session_id:
        raise IncidentValidationError(_INCIDENT_ERROR)
    if not _bounded_integer(incident.created_at_ms, MAX_UNIX_MS):
        raise IncidentValidationError(_INCIDENT_ERROR)
    if incident.native_stack != "unavailable" or type(incident.native_stack) is not str:
        raise IncidentValidationError(_INCIDENT_ERROR)
    event_payloads, _encoded_bytes = _event_payloads(incident.events, session_id)
    loss_payload = _loss_payload(incident.ring_loss)
    rejected_input_fields = (
        "invalid_events",
        "sequence_rejected_events",
        "normal_count_dropped_events",
        "normal_byte_dropped_events",
        "terminal_dropped_events",
    )
    ring_input_loss_observed = any(loss_payload[key] != 0 for key in rejected_input_fields)
    source_loss_observed = incident.observation.source_dropped > 0
    if incident.observation.channel is ChannelState.COMPLETE:
        if ring_input_loss_observed or source_loss_observed:
            raise IncidentValidationError(_INCIDENT_ERROR)
    elif incident.observation.channel is ChannelState.LOSS_OBSERVED:
        if not (ring_input_loss_observed or source_loss_observed):
            raise IncidentValidationError(_INCIDENT_ERROR)
    return {
        "schema_version": INCIDENT_SCHEMA_VERSION,
        "report_id": report_id,
        "session_id": session_id,
        "created_at_ms": incident.created_at_ms,
        "build_git_sha": _build_sha(incident.build_git_sha),
        "observation": _observation_payload(incident.observation),
        "events": event_payloads,
        "ring_loss": loss_payload,
        "native_stack": "unavailable",
    }


def build_incident(
    *,
    session_id: uuid.UUID,
    created_at_ms: int,
    build_git_sha: str,
    observation: IncidentObservation,
    history: RingSnapshot,
    report_id: uuid.UUID | None = None,
) -> DiagnosticIncident:
    """Project validated primitive observation and recorder state into an incident."""
    if type(history) is not RingSnapshot:
        raise IncidentValidationError(_INCIDENT_ERROR)
    if history.total_bytes != sum(len(event) for event in history.events) + LOSS_ACCOUNTING_BYTES:
        raise IncidentValidationError(_INCIDENT_ERROR)
    return DiagnosticIncident(
        schema_version=INCIDENT_SCHEMA_VERSION,
        report_id=uuid.uuid4() if report_id is None else report_id,
        session_id=session_id,
        created_at_ms=created_at_ms,
        build_git_sha=build_git_sha,
        observation=observation,
        events=history.events,
        ring_loss=history.loss,
    )


def encode_incident(incident: DiagnosticIncident) -> bytes:
    """Encode one exact closed incident without fallback string conversion."""
    try:
        payload = _incident_payload(incident)
        encoded = json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
    except IncidentValidationError:
        raise
    except (AttributeError, TypeError, ValueError, UnicodeEncodeError):
        raise IncidentValidationError(_INCIDENT_ERROR) from None
    if not encoded or len(encoded) > MAX_INCIDENT_BYTES:
        raise IncidentValidationError(_INCIDENT_ERROR)
    return encoded


def _exact_dict(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(keys):
        raise IncidentValidationError(_INCIDENT_ERROR)
    return value


def _enum(enum_type: type[Enum], value: object) -> Enum:
    if type(value) is not str:
        raise IncidentValidationError(_INCIDENT_ERROR)
    try:
        return enum_type(value)
    except ValueError:
        raise IncidentValidationError(_INCIDENT_ERROR) from None


def _parse_uuid(value: object) -> uuid.UUID:
    if type(value) is not str or _UUID_HEX.fullmatch(value) is None:
        raise IncidentValidationError(_INCIDENT_ERROR)
    return uuid.UUID(hex=value)


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IncidentValidationError(_INCIDENT_ERROR)
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise IncidentValidationError(_INCIDENT_ERROR)


def decode_incident(data: bytes) -> DiagnosticIncident:
    """Revalidate one bounded canonical incident from untrusted storage."""
    if type(data) is not bytes or not data or len(data) > MAX_INCIDENT_BYTES:
        raise IncidentValidationError(_INCIDENT_ERROR)
    try:
        payload = json.loads(
            data.decode("ascii"),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
        values = _exact_dict(
            payload,
            (
                "schema_version",
                "report_id",
                "session_id",
                "created_at_ms",
                "build_git_sha",
                "observation",
                "events",
                "ring_loss",
                "native_stack",
            ),
        )
        observed = _exact_dict(
            values["observation"],
            (
                "launch",
                "handshake",
                "channel",
                "exit_code",
                "termination",
                "clean_terminal_received",
                "source_dropped",
                "source_loss_known",
                "elapsed_ms",
            ),
        )
        loss_values = _exact_dict(values["ring_loss"], tuple(RingLoss.__dataclass_fields__))
        raw_events = values["events"]
        if type(raw_events) is not list or len(raw_events) > DEFAULT_MAX_EVENTS:
            raise IncidentValidationError(_INCIDENT_ERROR)
        events = tuple(
            json.dumps(event, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
                "ascii"
            )
            for event in raw_events
        )
        incident = DiagnosticIncident(
            schema_version=values["schema_version"],
            report_id=_parse_uuid(values["report_id"]),
            session_id=_parse_uuid(values["session_id"]),
            created_at_ms=values["created_at_ms"],
            build_git_sha=values["build_git_sha"],
            observation=IncidentObservation(
                launch=_enum(LaunchState, observed["launch"]),
                handshake=_enum(HandshakeState, observed["handshake"]),
                channel=_enum(ChannelState, observed["channel"]),
                exit_code=observed["exit_code"],
                termination=_enum(TerminationState, observed["termination"]),
                clean_terminal_received=observed["clean_terminal_received"],
                source_dropped=observed["source_dropped"],
                source_loss_known=observed["source_loss_known"],
                elapsed_ms=observed["elapsed_ms"],
            ),
            events=events,
            ring_loss=RingLoss(**loss_values),
            native_stack=values["native_stack"],
        )
        if encode_incident(incident) != data:
            raise IncidentValidationError(_INCIDENT_ERROR)
        return incident
    except IncidentValidationError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
        KeyError,
        AttributeError,
        OverflowError,
    ):
        raise IncidentValidationError(_INCIDENT_ERROR) from None
