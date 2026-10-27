from __future__ import annotations

import os
import json
import sys
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from metroliza.app.windows_candidate_privacy_checks import FACETS, run_privacy_checks


def _emit_privacy_diagnostic(event, stage, exception_type=None):
    sys.__stderr__.write(json.dumps({
        "schema_version": 1, "test": "privacy_checks", "event": event,
        "stage": stage, "exception_type": exception_type,
    }) + "\n")
    sys.__stderr__.flush()


def _privacy_breadcrumb(event, capfd):
    try:
        with capfd.disabled():
            _emit_privacy_diagnostic(event, "privacy_call")
    except Exception:
        pass  # With no active primary, real interrupts must still propagate.


def test_privacy_controls_are_inert_without_both_gates(tmp_path, monkeypatch):
    monkeypatch.delenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", raising=False)
    result = run_privacy_checks(tmp_path)
    assert result["status"] == "failed"
    assert result["error_codes"] == ["privacy_qualification_gate_missing"]
    assert not list(tmp_path.iterdir())


def test_real_private_storage_denial_explicit_output_and_owned_cleanup(tmp_path, monkeypatch, capfd):
    stage = "application"
    try:
        from metroliza.app.bootstrap import get_or_create_qapplication

        app = get_or_create_qapplication()
        assert app is not None
        stage = "privacy_prepare"
        monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
        monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
        stage = "privacy_call"
        _privacy_breadcrumb("begin", capfd)
        result = run_privacy_checks(tmp_path)
        _privacy_breadcrumb("end", capfd)
        stage = "privacy_assertions"
        assert result["runtime_context"] == "source"
        assert result["error_codes"] == []
        assert result["status"] == ("passed" if os.name == "nt" else "partial")
        assert result["facets"] == {key: "passed" if os.name == "nt" or not key.endswith("cleanup_denial_retry")
                                    else "not_assessed" for key in FACETS}
    except BaseException as error:
        try:
            with capfd.disabled():
                _emit_privacy_diagnostic("failure", stage, type(error).__name__[:80])
        except BaseException:
            pass  # Failure diagnostics cannot replace the primary exception.
        raise


@pytest.fixture
def privacy_diagnostic_control(tmp_path, monkeypatch, capfd):
    import io
    from metroliza.app import bootstrap

    stream = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", stream)
    app = object()
    monkeypatch.setattr(bootstrap, "get_or_create_qapplication", lambda: app)
    calls = []

    def invoke(primary=None, invalid=False):
        def run(path):
            calls.append(path)
            if primary is not None:
                raise primary
            return {"runtime_context": "PRIVATE_CONTEXT" if invalid else "source",
                    "error_codes": [], "status": "passed" if os.name == "nt" else "partial",
                    "facets": {key: "passed" if os.name == "nt" or not key.endswith("cleanup_denial_retry")
                               else "not_assessed" for key in FACETS}}

        monkeypatch.setattr(sys.modules[__name__], "run_privacy_checks", run)
        return test_real_private_storage_denial_explicit_output_and_owned_cleanup(tmp_path, monkeypatch, capfd)

    return invoke, calls, stream


@pytest.mark.parametrize("kind", [RuntimeError, KeyboardInterrupt, SystemExit, pytest.skip.Exception, pytest.fail.Exception])
def test_privacy_diagnostic_preserves_actual_primary_and_private_fields(privacy_diagnostic_control, kind):
    invoke, calls, stream = privacy_diagnostic_control
    primary = kind("PRIVATE_MESSAGE")
    primary.filename, primary.stdout, primary.stderr = "PRIVATE_FILENAME", "PRIVATE_STDOUT", "PRIVATE_STDERR"
    primary.payload = {"PRIVATE_PAYLOAD": "PRIVATE_VALUE"}
    with pytest.raises(kind) as caught:
        invoke(primary)
    assert caught.value is primary
    traceback = caught.value.__traceback__
    while traceback.tb_next:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "run"
    assert len(calls) == 1
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert events == [
        {"schema_version": 1, "test": "privacy_checks", "event": "begin", "stage": "privacy_call", "exception_type": None},
        {"schema_version": 1, "test": "privacy_checks", "event": "failure", "stage": "privacy_call", "exception_type": kind.__name__},
    ]
    for sentinel in ("PRIVATE_MESSAGE", "PRIVATE_FILENAME", "PRIVATE_STDOUT", "PRIVATE_STDERR",
                     "PRIVATE_PAYLOAD", "PRIVATE_VALUE"):
        assert sentinel not in stream.getvalue()


@pytest.mark.parametrize("secondary", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_privacy_diagnostic_secondary_failure_preserves_primary(privacy_diagnostic_control, monkeypatch, secondary):
    invoke, calls, stream = privacy_diagnostic_control
    primary = ValueError("PRIVATE_PRIMARY")
    write = stream.write

    def fail_only_failure_event(value):
        if json.loads(value)["event"] == "failure":
            raise secondary("PRIVATE_LOGGER")
        return write(value)

    monkeypatch.setattr(stream, "write", fail_only_failure_event)
    with pytest.raises(ValueError) as caught:
        invoke(primary)
    assert caught.value is primary
    assert len(calls) == 1
    traceback = caught.value.__traceback__
    while traceback.tb_next:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "run"


@pytest.mark.parametrize("invalid", [False, True])
def test_privacy_diagnostic_success_and_assertion_events(privacy_diagnostic_control, invalid):
    invoke, calls, stream = privacy_diagnostic_control
    if invalid:
        with pytest.raises(AssertionError):
            invoke(invalid=True)
    else:
        assert invoke() is None
    assert len(calls) == 1
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [event["event"] for event in events] == (["begin", "end", "failure"] if invalid else ["begin", "end"])
    if invalid:
        assert events[-1]["stage"] == "privacy_assertions"
        assert events[-1]["exception_type"] == "AssertionError"
    assert "PRIVATE_CONTEXT" not in stream.getvalue()


@pytest.mark.parametrize("failure", ["missing", "closed", "format"])
def test_privacy_diagnostic_unavailable_output_preserves_failure(privacy_diagnostic_control, monkeypatch, failure):
    invoke, calls, stream = privacy_diagnostic_control
    primary = ValueError("PRIVATE_PRIMARY")
    if failure == "missing":
        monkeypatch.setattr(sys, "__stderr__", None)
    elif failure == "closed":
        stream.close()
    else:
        def fail(*args):
            raise RuntimeError("PRIVATE_FORMAT")

        monkeypatch.setattr(json, "dumps", fail)
    with pytest.raises(ValueError) as caught:
        invoke(primary)
    assert caught.value is primary
    assert len(calls) == 1


@pytest.mark.parametrize("secondary", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("event", ["begin", "end"])
def test_privacy_breadcrumb_does_not_swallow_real_interrupt(privacy_diagnostic_control, monkeypatch, secondary, event):
    invoke, calls, stream = privacy_diagnostic_control
    primary = secondary("PRIVATE_INTERRUPT")
    write = stream.write

    def interrupt(value):
        if json.loads(value)["event"] == event:
            raise primary
        return write(value)

    monkeypatch.setattr(stream, "write", interrupt)
    with pytest.raises(secondary) as caught:
        invoke()
    assert caught.value is primary
    assert len(calls) == (0 if event == "begin" else 1)


def test_privacy_breadcrumbs_flush_at_actual_call_boundary(privacy_diagnostic_control, monkeypatch):
    invoke, calls, stream = privacy_diagnostic_control
    flushed = []
    monkeypatch.setattr(stream, "flush", lambda: flushed.append((len(calls), stream.getvalue())))
    assert invoke() is None
    assert [count for count, _ in flushed] == [0, 1]
    assert json.loads(flushed[0][1])["event"] == "begin"
    assert [json.loads(line)["event"] for line in flushed[1][1].splitlines()] == ["begin", "end"]


@pytest.mark.parametrize("secondary", [RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("operation", ["enter", "exit"])
def test_privacy_capture_context_failure_preserves_primary(
    privacy_diagnostic_control, monkeypatch, capfd, secondary, operation,
):
    from contextlib import nullcontext

    invoke, _, _ = privacy_diagnostic_control
    primary = ValueError("PRIVATE_PRIMARY")
    contexts = []

    class BrokenCapture:
        def __enter__(self):
            if operation == "enter":
                raise secondary("PRIVATE_CONTEXT_ENTER")

        def __exit__(self, *args):
            raise secondary("PRIVATE_CONTEXT_EXIT")

    def disabled():
        contexts.append(True)
        return nullcontext() if len(contexts) == 1 else BrokenCapture()

    monkeypatch.setattr(capfd, "disabled", disabled)
    with pytest.raises(ValueError) as caught:
        invoke(primary)
    assert caught.value is primary
    traceback = caught.value.__traceback__
    while traceback.tb_next:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "run"


@pytest.mark.parametrize("secondary", [KeyboardInterrupt, SystemExit])
def test_privacy_capture_context_interrupt_without_primary_propagates(
    privacy_diagnostic_control, monkeypatch, capfd, secondary,
):
    invoke, calls, _ = privacy_diagnostic_control
    primary = secondary("PRIVATE_CONTEXT")

    def disabled():
        raise primary

    monkeypatch.setattr(capfd, "disabled", disabled)
    with pytest.raises(secondary) as caught:
        invoke()
    assert caught.value is primary
    assert calls == []


def test_privacy_breadcrumbs_survive_default_fd_capture_and_abrupt_child_exit(tmp_path):
    probe = tmp_path / "test_capture_probe.py"
    probe.write_text('''import os
import sys
from tests.test_windows_candidate_privacy_checks import privacy_diagnostic_control
ORIGINAL_STDERR = sys.__stderr__

def test_probe(privacy_diagnostic_control, monkeypatch):
    from metroliza.app import bootstrap
    invoke, _, _ = privacy_diagnostic_control
    monkeypatch.setattr(sys, "__stderr__", ORIGINAL_STDERR)
    def application():
        print("PRIVATE_CAPTURED_STDOUT")
        sys.stderr.write("PRIVATE_CAPTURED_STDERR")
        return object()
    monkeypatch.setattr(bootstrap, "get_or_create_qapplication", application)
    invoke()
    os._exit(23)  # Only this controlled synthetic subprocess exits.
''')
    checkout = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(checkout / "src"), str(checkout))))
    environment.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "-v", str(probe)],
                            env=environment, cwd=tmp_path, capture_output=True, timeout=45)
    assert result.returncode == 23
    events = [json.loads(line) for line in result.stderr.decode().splitlines() if line.startswith('{"schema_version"')]
    assert events == [
        {"schema_version": 1, "test": "privacy_checks", "event": "begin", "stage": "privacy_call", "exception_type": None},
        {"schema_version": 1, "test": "privacy_checks", "event": "end", "stage": "privacy_call", "exception_type": None},
    ]
    output = result.stdout + result.stderr
    assert b"PRIVATE_CAPTURED_STDOUT" not in output
    assert b"PRIVATE_CAPTURED_STDERR" not in output


@pytest.mark.parametrize("primary", [None, KeyboardInterrupt(), SystemExit(22)])
def test_sharing_handle_close_failure_preserves_active_interrupt(tmp_path, monkeypatch, primary):
    import metroliza.app.windows_candidate_privacy_checks as checks

    calls = []

    def create(*args):
        calls.append("create")
        return 41

    def close(handle):
        calls.append(("close", handle))
        return 0

    kernel = SimpleNamespace(CreateFileW=create, CloseHandle=close)
    monkeypatch.setattr(checks, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(checks.ctypes, "WinDLL", lambda *a, **kw: kernel, raising=False)
    with pytest.raises(type(primary) if primary is not None else ValueError) as caught:
        with checks._hold_without_delete_share(tmp_path / "synthetic.txt"):
            if primary is not None:
                raise primary
    assert calls == ["create", ("close", 41)]
    if primary is not None:
        assert caught.value is primary
    else:
        assert str(caught.value) == "sharing_control_handle_close_failed"


def test_privacy_writer_failed_join_keeps_unavailable_owner_and_cannot_return_pass(tmp_path, monkeypatch):
    import metroliza.app.windows_candidate_privacy_checks as checks
    from metroliza.app import windows_candidate_native_check as control

    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    monkeypatch.setenv(control.MODE_ENV, "unavailable")
    bindings = control._bindings()
    originals = [(module, attr, getattr(module, attr)) for _, module, attr in bindings]
    retained_before = len(control._UNJOINED_OWNERS)
    waits, receipts = [], []
    owner = object()
    worker = SimpleNamespace(isRunning=lambda: True,
                             wait=lambda timeout: waits.append(timeout) or False)
    dialog = SimpleNamespace(dashboard_thread=worker, _dashboard_temp_dir=owner,
                             _schedule_dashboard_write=lambda **kw: None)
    app = SimpleNamespace(processEvents=lambda: pytest.fail("failed join fell through"))
    monkeypatch.setattr(checks, "_wait", lambda *a, **kw: None)

    def creation(*args):
        with checks._active_writer(app, dialog, True):
            pass

    monkeypatch.setattr(checks, "_creation_and_explicit_output", creation)
    try:
        with pytest.raises(control._UnjoinedNativeOwner) as caught:
            control.run_with_native_mode(lambda: receipts.append(checks.run_privacy_checks(tmp_path)))
        assert caught.value.code == 22
        assert waits == [20000] and receipts == []
        assert control._UNJOINED_OWNERS[-1] is dialog
        assert dialog._dashboard_temp_dir is owner
        assert all(getattr(module, attr) is None for _, module, attr in bindings)
        assert control._UNAVAILABLE_ACTIVE.get() is False
    finally:
        for module, attr, original in originals:
            setattr(module, attr, original)
        del control._UNJOINED_OWNERS[retained_before:]
