import json
import os
import subprocess
import sys
import time
import types
from dataclasses import asdict
from pathlib import Path

import pytest

from metroliza.app.diagnostic_supervisor import launch_supervised

ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "tests" / "fixtures" / "diagnostic_child.py"


def _command(scenario):
    return [sys.executable, str(CHILD), scenario]


def _controlled_receiver_rate_window(monkeypatch, *, rollover_every=None):
    from metroliza.app import diagnostic_supervisor

    receiver_run = diagnostic_supervisor._Receiver._run.__code__

    class ReceiverRateTime:
        def __init__(self):
            self.window_time = time.monotonic()
            self.window_reads = 0

        def monotonic(self):
            if sys._getframe(1).f_code is receiver_run:
                self.window_reads += 1
                if rollover_every and self.window_reads > 1:
                    if (self.window_reads - 1) % rollover_every == 0:
                        self.window_time += 1.01
                return self.window_time
            return time.monotonic()

        def __getattr__(self, name):
            return getattr(time, name)

    controlled = ReceiverRateTime()
    monkeypatch.setattr(diagnostic_supervisor, "time", controlled)
    return controlled


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


@pytest.mark.skipif(os.name != "nt", reason="native Windows token and pipe contract")
def test_qualified_nonadmin_token_can_create_its_anonymous_pipe():
    # A separate child confines impersonation, including an adverse RevertToSelf
    # result. No application input, raw native error text, SID or ACL is emitted.
    program = r'''
import ctypes
import json
import os
from scripts.qualify_windows_diagnostics import _WindowsApi

result = {"baseline": False, "restricted": False, "error_class": None, "stage": "baseline", "cleanup": True}
api = _WindowsApi()
api.advapi.ImpersonateLoggedOnUser.argtypes = [api.wintypes.HANDLE]
api.advapi.ImpersonateLoggedOnUser.restype = api.wintypes.BOOL
api.advapi.RevertToSelf.argtypes = []
api.advapi.RevertToSelf.restype = api.wintypes.BOOL
token = None
impersonating = False
def pipe_roundtrip(prefix):
    pipes = []
    try:
        result["stage"] = prefix + "_first_pipe"
        pipes.append(os.pipe())
        result["stage"] = prefix + "_second_pipe"
        pipes.append(os.pipe())
        for read, write in pipes:
            os.write(write, b"closed-control")
            if os.read(read, 14) != b"closed-control":
                return False
        return True
    finally:
        for read, write in pipes:
            os.close(write)
            os.close(read)
try:
    result["baseline"] = pipe_roundtrip("baseline")
    token = api._restricted_token()
    if not api.advapi.ImpersonateLoggedOnUser(token):
        raise RuntimeError()
    impersonating = True
    try:
        result["restricted"] = pipe_roundtrip("restricted")
        result["stage"] = "complete"
    except OSError as error:
        native = getattr(error, "winerror", None)
        result["error_class"] = (
            "access_denied" if native == 5
            else "access_denied_mapped" if native is None and error.errno == 13
            else "resource_failure" if native in (8, 14) or error.errno in (12, 24)
            else "other"
        )
except Exception:
    result["cleanup"] = False
finally:
    if impersonating and not api.advapi.RevertToSelf():
        os._exit(3)
    if token and not api.kernel.CloseHandle(token):
        result["cleanup"] = False
print(json.dumps(result, sort_keys=True))
'''
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT)))),
        check=False,
    )
    assert result.returncode == 0
    observation = json.loads(result.stdout)
    assert observation == {
        "baseline": True, "restricted": True, "error_class": None,
        "stage": "complete", "cleanup": True,
    }


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
def test_owned_malformed_peer_never_produces_complete_evidence(
    scenario, handshake, channel, monkeypatch
):
    controlled = None
    if scenario == "flood":
        controlled = _controlled_receiver_rate_window(monkeypatch)
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
    if controlled is not None:
        assert controlled.window_reads >= 2001
        assert 0 < result.history.loss.sequence_rejected_events < 2000
    if scenario in {"wrong_peer", "cross_instance"}:
        assert result.history.events == ()


def test_receiver_rate_window_rollover_does_not_become_a_lifetime_cap(monkeypatch):
    controlled = _controlled_receiver_rate_window(monkeypatch, rollover_every=1000)
    result = launch_supervised([
        sys.executable, str(CHILD.with_name("diagnostic_protocol_child.py")), "flood",
    ])
    assert controlled.window_reads > 2001
    assert result.exit_code == 0
    assert result.handshake == "accepted"
    assert result.channel == "incomplete"
    assert not result.clean_terminal_received
    assert result.needs_incident
    assert result.history.loss.sequence_rejected_events > 2000
    assert result.history.total_bytes <= 2 * 1024 * 1024


def test_concurrent_real_instances_keep_their_own_event_history():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: launch_supervised(_command("hard_exit")), range(3)))
    assert len({result.session_id for result in results}) == 3
    for result in results:
        assert result.history.events
        assert {json.loads(event)["invocation_id"] for event in result.history.events} == {
            result.session_id
        }


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


@pytest.mark.parametrize("callback_fails", [False, True])
def test_windows_spawn_temporarily_cleans_and_restores_dll_directory(
    monkeypatch, callback_fails
):
    from metroliza.app import diagnostic_supervisor

    state = {"directory": "C:/synthetic bundle"}
    transitions: list[str | None] = []

    class Buffer:
        value = ""

        def __len__(self):
            return 32_768

    fake_ctypes = types.SimpleNamespace(
        create_unicode_buffer=lambda _size: Buffer(),
        get_last_error=lambda: 0,
        set_last_error=lambda _value: None,
    )

    def get_directory(_size, buffer):
        buffer.value = state["directory"] or ""
        return len(buffer.value)

    def set_directory(value):
        state["directory"] = value
        transitions.append(value)
        return 1

    monkeypatch.setattr(diagnostic_supervisor.os, "name", "nt")
    monkeypatch.setattr(
        diagnostic_supervisor,
        "_windows_dll_directory_api",
        lambda: (fake_ctypes, get_directory, set_directory),
    )
    calls = 0

    def callback():
        nonlocal calls
        calls += 1
        assert state["directory"] is None
        if callback_fails:
            raise OSError("synthetic_popen_failure")
        return "child"

    if callback_fails:
        with pytest.raises(OSError, match="synthetic_popen_failure"):
            diagnostic_supervisor._call_with_clean_windows_dll_directory(callback)
    else:
        assert diagnostic_supervisor._call_with_clean_windows_dll_directory(callback) == "child"
    assert calls == 1
    assert transitions == [None, "C:/synthetic bundle"]
    assert state["directory"] == "C:/synthetic bundle"


@pytest.mark.skipif(os.name != "nt", reason="native Windows DLL search state")
def test_native_windows_spawn_callback_observes_clean_dll_directory_and_restores_state():
    from metroliza.app import diagnostic_supervisor

    ctypes, get_directory, _set_directory = diagnostic_supervisor._windows_dll_directory_api()

    def current_directory():
        buffer = ctypes.create_unicode_buffer(32_768)
        length = get_directory(len(buffer), buffer)
        assert length < len(buffer)
        return buffer.value if length else None

    before = current_directory()

    def observe_clean():
        assert current_directory() is None
        return "observed"

    assert diagnostic_supervisor._call_with_clean_windows_dll_directory(observe_clean) == "observed"
    assert current_directory() == before
