"""Test-owned malformed peers using only their own inherited pipe handles."""

import os
import struct
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from metroliza.shared.diagnostic_events import (
    StartupCallsite,
    StartupDiagnosticEvent,
    StartupMode,
    StartupOutcome,
    WorkflowDiagnosticEvent,
    WorkflowError,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_transport import (
    CHANNEL_ENV,
    _open_channel,
    control_bytes,
    parse_control,
    read_frame,
    write_frame,
)
from metroliza.shared.diagnostic_wire import encode_event


def _authenticate(scenario, incoming, outgoing):
    challenge = parse_control(read_frame(incoming), "challenge", {"session_id", "token"})
    if scenario == "wrong_peer":
        challenge["token"] = "0" * 64
    write_frame(
        outgoing,
        control_bytes(
            "hello", session_id=challenge["session_id"], token=challenge["token"]
        ),
    )
    if scenario == "wrong_peer":
        return None
    read_frame(incoming)
    return challenge


def _send_failure_backlog(outgoing, session, scratch):
    for suffix in (1, 2):
        payload = encode_event(
            WorkflowDiagnosticEvent(
                session,
                uuid.UUID(f"0000000{suffix}-0000-4000-8000-000000000000"),
                1,
                WorkflowOperation.LOCAL_EXPORT,
                WorkflowStage.FINISHED,
                WorkflowOutcome.FAILED,
                WorkflowError.OUTPUT_FAILED,
            )
        )
        write_frame(outgoing, payload)
        if suffix == 1:
            deadline = time.monotonic() + 5
            while not (scratch / "live_publish_entered").exists():
                if time.monotonic() >= deadline:
                    return 15
                time.sleep(0.01)
    write_frame(outgoing, control_bytes("ended", dropped=0))
    (scratch / "child_finished").touch()
    return 0


def _send_generic_scenario(scenario, outgoing, payload):
    if scenario in {"partial", "stalled"}:
        os.write(outgoing, struct.pack("!I", 100) + b"{")
        if scenario == "stalled":
            time.sleep(0.5)
        return 0
    if scenario == "flood":
        try:
            for _ in range(20000):
                write_frame(outgoing, payload)
        except OSError:
            pass
        return 0
    write_frame(outgoing, payload)
    if scenario != "dropped_terminal":
        write_frame(outgoing, control_bytes("ended", dropped=0))
    return 0


def main():
    scenario = sys.argv[1]
    incoming, outgoing = _open_channel(os.environ.pop(CHANNEL_ENV))
    challenge = _authenticate(scenario, incoming, outgoing)
    if challenge is None:
        return 0
    session = (
        uuid.uuid4()
        if scenario == "cross_instance"
        else uuid.UUID(hex=challenge["session_id"])
    )
    if scenario == "failure_backlog":
        return _send_failure_backlog(outgoing, session, Path(sys.argv[2]))
    payload = encode_event(
        StartupDiagnosticEvent(
            session,
            uuid.uuid4(),
            1,
            StartupMode.UNKNOWN,
            StartupCallsite.BOOTSTRAP,
            StartupOutcome.INVOCATION_STARTED,
        )
    )
    return _send_generic_scenario(scenario, outgoing, payload)


if __name__ == "__main__":
    raise SystemExit(main())
