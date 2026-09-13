from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from metroliza.app.diagnostic_supervisor import launch_supervised

ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "tests" / "fixtures" / "diagnostic_child.py"


def _command(scenario):
    return [sys.executable, str(CHILD), scenario]


@pytest.mark.parametrize("scenario,code,incident,handshake", [
    ("normal", 0, False, "accepted"),
    ("hard_exit", 9, True, "accepted"),
    ("numeric139", 139, True, "accepted"),
    ("early_exit", 7, True, "missing"),
    ("raw_output", 0, False, "accepted"),
])
def test_real_child_observation_and_surviving_history(scenario, code, incident, handshake):
    result = launch_supervised(_command(scenario))
    assert result.exit_code == code
    assert result.needs_incident is incident
    assert result.handshake == handshake
    assert result.termination == "observed_exit"
    if handshake == "accepted":
        assert len(result.history.events) == 1
        event = json.loads(result.history.events[0])
        assert event["invocation_id"] == result.session_id
        assert event["event_code"] == "startup_diagnostic"
        assert event["outcome"] == "invocation_started"
    assert "SYNTHETIC_RAW_SECRET" not in repr(asdict(result))


def test_missing_child_is_not_a_fabricated_process_exit(tmp_path):
    result = launch_supervised([str(tmp_path / "missing.exe")])
    assert result.launch == "failed"
    assert result.exit_code is None
    assert result.termination == "not_started"
    assert result.needs_incident


@pytest.mark.parametrize("scenario", ["duplicate", "dropped"])
def test_clean_process_return_cannot_erase_missing_event_evidence(scenario):
    result = launch_supervised(_command(scenario))
    assert result.exit_code == 0
    assert result.clean_terminal_received
    assert result.channel == "loss_observed"
    assert result.needs_incident


def test_supervisor_does_not_search_path():
    with pytest.raises(ValueError, match="absolute_child_required"):
        launch_supervised(["python"])


@pytest.mark.parametrize("failure_at", [1, 2])
def test_partial_channel_allocation_failure_closes_owned_handles(monkeypatch, failure_at):
    pipe = os.pipe
    opened = []
    calls = 0
    def failing_pipe():
        nonlocal calls
        calls += 1
        if calls == failure_at:
            raise OSError("SYNTHETIC_RESOURCE_FAILURE")
        pair = pipe()
        opened.extend(pair)
        return pair
    monkeypatch.setattr(os, "pipe", failing_pipe)
    result = launch_supervised(_command("normal"))
    assert result.launch == "failed"
    assert result.termination == "not_started"
    assert result.exit_code is None
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("scenario,handshake,channel", [
    ("wrong_peer", "rejected", "invalid"),
    ("cross_instance", "accepted", "invalid"),
    ("partial", "accepted", "invalid"),
    ("stalled", "accepted", "invalid"),
    ("flood", "accepted", "flooded"),
    ("dropped_terminal", "accepted", "incomplete"),
])
def test_owned_malformed_peer_never_produces_complete_evidence(scenario, handshake, channel):
    started = time.monotonic()
    result = launch_supervised([
        sys.executable, str(CHILD.with_name("diagnostic_protocol_child.py")), scenario,
    ])
    assert time.monotonic() - started < 4
    assert result.handshake == handshake
    assert result.channel == channel
    assert not result.clean_terminal_received
    assert result.needs_incident
    assert result.history.total_bytes <= 2 * 1024 * 1024
    if scenario in {"wrong_peer", "cross_instance"}:
        assert result.history.events == ()


def test_concurrent_real_instances_keep_their_own_event_history():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: launch_supervised(_command("hard_exit")), range(3)))
    assert len({result.session_id for result in results}) == 3
    for result in results:
        assert result.history.events
        assert {json.loads(event)["invocation_id"] for event in result.history.events} == {result.session_id}


def test_contended_source_counter_is_unknown_instead_of_a_fabricated_exact_zero():
    result = launch_supervised(_command("contended"))
    assert result.exit_code == 0
    assert result.channel == "incomplete"
    assert not result.source_loss_known
    assert not result.clean_terminal_received


def test_full_slow_pipe_cannot_hold_up_the_product_shutdown(monkeypatch):
    from metroliza.app.diagnostic_supervisor import _Receiver

    receive = _Receiver._receive
    def slow_receive(self, payload):
        time.sleep(0.02)
        return receive(self, payload)
    monkeypatch.setattr(_Receiver, "_receive", slow_receive)
    started = time.monotonic()
    result = launch_supervised(_command("full_queue"))
    assert time.monotonic() - started < 4
    assert result.exit_code == 0
    assert result.channel in {"incomplete", "loss_observed"}
    assert result.needs_incident
    assert result.history.total_bytes <= 2 * 1024 * 1024


def test_supervisor_loss_does_not_kill_or_replay_child_write(tmp_path):
    destination = tmp_path / "business-write.txt"
    command = _command("supervisor_loss") + [str(destination)]
    supervisor = subprocess.Popen(
        [sys.executable, "-c", "from metroliza.app.diagnostic_supervisor import launch_supervised; "
         "import json,sys; launch_supervised(json.loads(sys.argv[1]))", json.dumps(command)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT)))),
    )
    try:
        deadline = time.monotonic() + 5
        while not destination.with_suffix(".ready").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert destination.with_suffix(".ready").exists()
        supervisor.kill()  # Only this test-owned parent; product has no kill policy.
        supervisor.wait(timeout=3)
        deadline = time.monotonic() + 5
        while not destination.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert destination.read_text(encoding="ascii") == "one_commit\n"
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=3)


def test_platform_observed_status_is_separate_from_numeric_exit139():
    if os.name == "nt":
        script = "import os; os._exit(3)"
        expected = ("observed_exit", 3)
    else:
        script = "import os,signal; os.kill(os.getpid(), signal.SIGTERM)"
        expected = ("posix_signal", -15)
    result = launch_supervised([sys.executable, "-c", script])
    assert (result.termination, result.exit_code) == expected
