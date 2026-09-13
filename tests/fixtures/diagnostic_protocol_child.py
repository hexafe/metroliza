"""Test-owned malformed peers using only their own inherited pipe handles."""

import os
from pathlib import Path
import struct
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from metroliza.shared.diagnostic_events import (
    StartupCallsite, StartupDiagnosticEvent, StartupMode, StartupOutcome,
)
from metroliza.shared.diagnostic_transport import (
    CHANNEL_ENV, _open_channel, control_bytes, parse_control, read_frame, write_frame,
)
from metroliza.shared.diagnostic_wire import encode_event


def main():
    scenario = sys.argv[1]
    incoming, outgoing = _open_channel(os.environ.pop(CHANNEL_ENV))
    challenge = parse_control(read_frame(incoming), "challenge", {"session_id", "token"})
    if scenario == "wrong_peer":
        challenge["token"] = "0" * 64
    write_frame(outgoing, control_bytes("hello", session_id=challenge["session_id"], token=challenge["token"]))
    if scenario == "wrong_peer":
        return 0
    read_frame(incoming)
    session = uuid.uuid4() if scenario == "cross_instance" else uuid.UUID(hex=challenge["session_id"])
    payload = encode_event(StartupDiagnosticEvent(
        session, uuid.uuid4(), 1, StartupMode.UNKNOWN, StartupCallsite.BOOTSTRAP,
        StartupOutcome.INVOCATION_STARTED,
    ))
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


if __name__ == "__main__":
    raise SystemExit(main())
