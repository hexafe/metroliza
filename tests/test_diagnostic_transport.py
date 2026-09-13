import os
import struct

import pytest

from metroliza.shared.diagnostic_transport import (
    MAX_FRAME_BYTES, control_bytes, parse_control, read_frame, write_frame,
)


@pytest.mark.parametrize("payload", [b"{}", b"x" * MAX_FRAME_BYTES])
def test_pipe_round_trip(payload):
    import threading

    incoming, outgoing = os.pipe()
    worker = threading.Thread(target=write_frame, args=(outgoing, payload))
    try:
        worker.start()
        assert read_frame(incoming) == payload
        worker.join(1)
        assert not worker.is_alive()
    finally:
        os.close(incoming)
        os.close(outgoing)


@pytest.mark.parametrize("data", [b"\x00", struct.pack("!I", MAX_FRAME_BYTES + 1),
                                  struct.pack("!I", 0), struct.pack("!I", 4) + b"a"])
def test_partial_and_oversized_frames_fail_closed(data):
    incoming, outgoing = os.pipe()
    os.write(outgoing, data)
    os.close(outgoing)
    try:
        with pytest.raises(ValueError):
            read_frame(incoming)
    finally:
        os.close(incoming)


@pytest.mark.parametrize("data", [b'{"control":"ended","dropped":0,"path":"SECRET"}',
                                  b'{"control":"ended","dropped":0,"dropped":1}',
                                  b"x" * 513])
def test_control_rejects_extra_duplicate_and_oversized_payload(data):
    with pytest.raises(ValueError):
        parse_control(data, "ended", {"dropped"})


def test_control_round_trip():
    assert parse_control(control_bytes("ended", dropped=3), "ended", {"dropped"}) == {
        "control": "ended", "dropped": 3,
    }
