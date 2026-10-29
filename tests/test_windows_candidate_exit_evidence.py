"""Exit fidelity and private fatal evidence; no Windows acceptance claim."""
from __future__ import annotations

import atexit
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import subprocess
from types import ModuleType, SimpleNamespace

import pytest

from tests.test_diagnostic_startup_probe import isolated_fatal_probe as isolated_fatal_probe

from metroliza.app import diagnostic_launcher as launcher
from metroliza.app import diagnostic_supervisor as supervisor
from metroliza.shared import diagnostic_startup_probe as probe
from metroliza.shared.diagnostic_store import StoreStatus
from scripts import qualify_windows_candidate_core as driver

ROOT = Path(launcher.__file__).resolve().parents[3]


def test_e1_launcher_returns_signed_windows_dword(monkeypatch):
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "IncidentStore", lambda: None)
    monkeypatch.setattr(launcher, "run_with_store", lambda *_a, **_kw: launcher.LaunchDelivery(
        SimpleNamespace(exit_code=0xC0000005), StoreStatus.SAVED,
    ))
    assert launcher.main() == -1073741819


@pytest.mark.parametrize("code", [0x80000000, 0xBFFFFFFF, 0xC0000000, 0xFFFFFFFE])
def test_e2_discriminating_child_phases(monkeypatch, code):
    marks = []
    monkeypatch.setattr(supervisor, "mark", marks.append)
    supervisor._mark_child_exit(code)
    phase = "child_wait_ntstatus_error" if code >= 0xC0000000 else "child_wait_high_bit_other"
    assert phase in marks
    assert phase in probe.PHASES
    assert driver._closed_phases(marks) == [p for p in probe.PHASES if p in marks]


@pytest.mark.parametrize("code", [0, 7, -1, 0x7FFFFFFF, 0xFFFFFFFF])
def test_child_high_bit_buckets_exclude_other_codes(monkeypatch, code):
    marks = []
    monkeypatch.setattr(supervisor, "mark", marks.append)
    supervisor._mark_child_exit(code)
    assert "child_wait_ntstatus_error" not in marks
    assert "child_wait_high_bit_other" not in marks


def test_e3_failed_receipt_has_exit_class():
    payload = driver._failed_diagnostic_payload(
        {"receipt_state": "valid_success", "observed_exit_code": 0xC0000005},
        {}, driver.CandidateFailure("closed"), "a" * 40,
    )
    assert payload["failure_category"] == "post_success_nonzero_exit"
    assert payload["observed_exit_code"] == 0xC0000005
    assert payload["observed_exit_class"] == "access_violation"


def _entry(monkeypatch, events):
    for name, fields in {
        "metroliza.shared.diagnostic_transport": {"attach_child_recorder": lambda: None,
                                                "supervised_mode_requested": lambda: False},
        "metroliza.app.bootstrap": {"run_application": lambda: events.append("application") or 7},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(fields)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(atexit, "register", lambda *_a: None)
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(ROOT / "packaging/metroliza_package_entry.py"), run_name="__main__")
    assert caught.value.code == 7


def _gates(monkeypatch, root):
    for name, value in {
        "METROLIZA_STARTUP_SMOKE": "1", "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION": "1",
        "METROLIZA_DIAGNOSTIC_STARTUP_PROBE": "1", "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT": str(root),
    }.items():
        monkeypatch.setenv(name, value)


def test_e4_package_enables_private_faulthandler_early(monkeypatch, tmp_path):
    import faulthandler

    events, handles = [], []
    from metroliza.shared import diagnostic_fatal_probe as fatal

    monkeypatch.setattr(fatal, "_fatal_stream", None)
    _gates(monkeypatch, tmp_path)

    def enable(*, file, all_threads):
        events.append("faulthandler")
        handles.append(file)
        assert all_threads is True
        assert type(file) is int
        assert not os.get_inheritable(file)

    monkeypatch.setattr(faulthandler, "enable", enable)
    try:
        _entry(monkeypatch, events)
        assert events == ["faulthandler", "application"]
        assert os.fstat(handles[0]).st_size == 0
        assert (tmp_path / fatal.FATAL_FILE).is_file()
    finally:
        for handle in handles:
            if type(handle) is int:
                os.close(handle)
            else:
                handle.close()
        if "metroliza.shared.diagnostic_fatal_probe" in sys.modules:
            monkeypatch.setattr(sys.modules["metroliza.shared.diagnostic_fatal_probe"], "_fatal_stream", None)


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("code", [-2**40, -2**31-1, -2**31, -1, 0, 3, 2**31-2, 2**31-1,
                                2**31, 2**31+1, 0xC0000005, 0xFFFFFFFE, 0xFFFFFFFF, 2**32, 2**40])
def test_dword_conversion_bounds(code, windows):
    expected = code - 2**32 if windows and 2**31 <= code <= 2**32-1 else code
    assert launcher.system_exit_code(code, windows=windows) == expected
    if 0 <= code <= 2**32-1:
        assert launcher.system_exit_code(code, windows=windows) & 0xFFFFFFFF == code
        if windows:
            assert -2**31 <= launcher.system_exit_code(code, windows=True) < 2**31


def test_portable_entry_propagates_signed_dword(monkeypatch):
    spec = importlib.util.spec_from_file_location("portable_test", ROOT / "packaging/metroliza_portable_entry.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(entry, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "synthetic", raising=False)
    monkeypatch.setattr(entry, "_launch", lambda *_a: 0xC0000409)
    assert entry.main() == -1073740791


@pytest.mark.parametrize("code,kind", [
    (0xC0000005, "access_violation"), (0xC0000409, "stack_buffer_overrun"),
    (0xC0000374, "heap_corruption"), (0xC00000FD, "stack_overflow"),
    (0xC000001D, "illegal_instruction"), (0xC0000008, "invalid_handle"),
    (0xC0000142, "dll_init_failed"), (0xC000013A, "control_c_exit"),
    (0xE06D7363, "cpp_exception"), (3, "abort_3"), (0xFFFFFFFF, "all_ones"),
    (0xC0000000, "other_ntstatus_error"), (0xFFFFFFFE, "other_ntstatus_error"),
    (0x80000000, "other_nonzero"), (7, "other_nonzero"),
])
def test_closed_class_and_validator(tmp_path, code, kind):
    payload = driver._failed_diagnostic_payload({"observed_exit_code": code}, {}, driver.CandidateFailure("closed"), "a"*40)
    assert payload["observed_exit_class"] == kind
    driver._write_failed_diagnostic(tmp_path, payload)
    for invalid in ("PRIVATE", "other_nonzero" if kind != "other_nonzero" else "access_violation", True, None):
        payload["observed_exit_class"] = invalid
        with pytest.raises(driver.CandidateFailure, match="invalid_exit_evidence"):
            driver._write_failed_diagnostic(tmp_path, payload)


@pytest.mark.parametrize("missing", ["METROLIZA_STARTUP_SMOKE", "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION",
                                    "METROLIZA_DIAGNOSTIC_STARTUP_PROBE", "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"])
def test_fatal_capture_requires_all_gates(monkeypatch, tmp_path, missing):
    import faulthandler
    from metroliza.shared import diagnostic_fatal_probe as fatal

    _gates(monkeypatch, tmp_path)
    monkeypatch.setattr(fatal, "_fatal_stream", None)
    monkeypatch.delenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", raising=False)
    monkeypatch.delenv(missing)
    monkeypatch.setattr(faulthandler, "enable", lambda **_kw: pytest.fail("ordinary capture enabled"))
    fatal.enable_private_fatal_probe()
    assert list(tmp_path.iterdir()) == []


def test_fatal_parser_current_thread_only_and_bounded(tmp_path):
    from metroliza.shared.diagnostic_fatal_probe import FATAL_FILE
    from scripts.windows_candidate_exit_evidence import read_fatal_observation

    raw = ('Windows fatal exception: access violation\n\nThread 0x123 (most recent call first):\n'
           '  File "C:\\PRIVATE\\other.py", line 9 in secret\n\n'
           'Current thread 0x456 (most recent call first):\n'
           '  File "C:\\PRIVATE\\module.py", line 99 in <module>\n'
           '  File "/PRIVATE/bad-name.py", line 5 in bad-name\n'
           + '  File "/PRIVATE/' + 'a'*64 + '.py", line 3 in ' + 'b'*64 + '\n')
    raw += ('  File "/PRIVATE/frame.py", line 1 in function\n') * 15
    raw += '\nThread 0x789 (most recent call first):\n  File "/PRIVATE/other.py", line 1 in secret\n'
    (tmp_path / FATAL_FILE).write_text(raw)
    observed = read_fatal_observation(tmp_path)
    assert observed["present"] is True
    assert observed["kind"] == "access_violation"
    assert observed["frames"][:2] == ["module:<module>", "a"*64 + ":" + "b"*64]
    assert len(observed["frames"]) == 12
    assert observed["truncated"] is True
    assert "PRIVATE" not in json.dumps(observed)
    assert "secret" not in json.dumps(observed)


@pytest.mark.parametrize("line,kind", [
    ("Windows fatal exception: stack overflow", "stack_overflow"),
    ("Windows fatal exception: code 0xDEADBEEF", "code_0xdeadbeef"),
    ("Fatal Python error: Aborted", "fatal_python_error"), ("PRIVATE", "other"),
])
def test_fatal_first_line_closed(tmp_path, line, kind):
    from metroliza.shared.diagnostic_fatal_probe import FATAL_FILE
    from scripts.windows_candidate_exit_evidence import read_fatal_observation

    (tmp_path / FATAL_FILE).write_text(line)
    assert read_fatal_observation(tmp_path) == {
        "present": True, "kind": kind, "frames": [], "truncated": False, "multiple_blocks": False,
    }


def test_maximum_fatal_frames_and_all_phases_fit(tmp_path):
    fatal = {"present": True, "kind": "fatal_python_error", "frames": ["a"*64 + ":" + "b"*64]*12,
             "truncated": True, "multiple_blocks": True}
    payload = driver._failed_diagnostic_payload(
        {"startup_phases": list(probe.PHASES), "child_fatal_observation": fatal, "observed_exit_code": 0xC0000409},
        {}, driver.CandidateFailure("closed"), "a"*40,
    )
    assert payload["child_fatal_observation"] == fatal
    driver._write_failed_diagnostic(tmp_path, payload)
    assert (tmp_path / driver.FAILED_DIAGNOSTIC_FILE).stat().st_size <= 4096


def test_absent_fatal_and_rejected_private_file(tmp_path):
    from metroliza.shared.diagnostic_fatal_probe import FATAL_FILE
    from scripts.windows_candidate_exit_evidence import read_fatal_observation

    empty = {"present": False, "kind": "other", "frames": [], "truncated": False, "multiple_blocks": False}
    assert read_fatal_observation(tmp_path) == empty
    private = tmp_path / "private"
    private.write_text("PRIVATE")
    (tmp_path / FATAL_FILE).symlink_to(private)
    assert read_fatal_observation(tmp_path) == empty


@pytest.mark.parametrize("change", [
    {"kind": "PRIVATE"}, {"frames": ["/PRIVATE:secret"]}, {"frames": ["ok:f"]*13},
    {"present": 1}, {"truncated": 0}, {"raw": "PRIVATE"},
    {"present": False, "frames": ["ok:f"]},
    {"multiple_blocks": 1}, {"multiple_blocks": None}, {"present": False, "multiple_blocks": True},
])
def test_fatal_validator_rejects_unclosed_fields(tmp_path, change):
    payload = driver._failed_diagnostic_payload({}, {}, driver.CandidateFailure("closed"), "a"*40)
    payload["child_fatal_observation"] = dict(present=True, kind="other", frames=[], truncated=False, multiple_blocks=False)
    payload["child_fatal_observation"].update(change)
    with pytest.raises(driver.CandidateFailure, match="invalid_exit_evidence"):
        driver._write_failed_diagnostic(tmp_path, payload)


@pytest.mark.skipif(sys.platform != "win32", reason="Real fatal child is Windows-only; POSIX uses byte fixtures")
def test_real_fatal_child_remains_nonzero_and_private(tmp_path, monkeypatch):
    """One native Windows access violation; never crash a POSIX process."""
    from metroliza.shared.diagnostic_fatal_probe import FATAL_FILE
    from scripts.windows_candidate_exit_evidence import read_fatal_observation

    _gates(monkeypatch, tmp_path)
    code = '''
import faulthandler, runpy, sys, types
transport = types.ModuleType("metroliza.shared.diagnostic_transport")
transport.attach_child_recorder = lambda: None
transport.supervised_mode_requested = lambda: False
sys.modules[transport.__name__] = transport
bootstrap = types.ModuleType("metroliza.app.bootstrap")
def synthetic_fatal():
    faulthandler._read_null()
bootstrap.run_application = synthetic_fatal
sys.modules[bootstrap.__name__] = bootstrap
runpy.run_path(sys.argv[1], run_name="__main__")
'''
    result = subprocess.run([sys.executable, "-c",
                             "import sys; exec(compile(sys.argv.pop(1), 'synthetic_fatal.py', 'exec'))",
                             code, str(ROOT / "packaging/metroliza_package_entry.py")],
                            env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=15)
    assert result.returncode != 0
    observed = read_fatal_observation(tmp_path)
    assert observed["present"] is True
    assert observed["kind"] == "access_violation"
    assert any(frame.endswith(":synthetic_fatal") for frame in observed["frames"])
    assert str(ROOT) not in json.dumps(observed)
    assert (tmp_path / FATAL_FILE).is_file()


def test_private_sink_refuses_existing_file_and_symlink(monkeypatch, tmp_path):
    import faulthandler
    from metroliza.shared import diagnostic_fatal_probe as fatal

    _gates(monkeypatch, tmp_path)
    monkeypatch.setattr(fatal, "_fatal_stream", None)
    monkeypatch.setattr(faulthandler, "enable", lambda **_kw: pytest.fail("sink reused"))
    sink = tmp_path / fatal.FATAL_FILE
    sink.write_text("PRIVATE")
    fatal.enable_private_fatal_probe()
    assert sink.read_text() == "PRIVATE"
    sink.unlink()
    other = tmp_path / "other"
    other.write_text("PRIVATE")
    sink.symlink_to(other)
    fatal.enable_private_fatal_probe()
    assert other.read_text() == "PRIVATE"


def test_unfinished_job_never_reads_private_sink(monkeypatch, tmp_path):
    from scripts import windows_candidate_exit_evidence as evidence

    monkeypatch.setattr(evidence, "read_fatal_observation", lambda *_a: pytest.fail("job not closed"))
    observation = {"owned_cleanup": "failed"}
    evidence.retain_fatal_observation(observation, tmp_path)
    assert observation["child_fatal_observation"] == evidence.absent_fatal_observation()


def test_worst_closed_fields_bound_frames_without_losing_exit_or_phases(tmp_path):
    from scripts.windows_owned_process_probe import UNAVAILABLE_SOURCES
    from metroliza.app.windows_candidate_xlsx import _SAFE_FAILURE_CODES, _SAFE_FAILURE_STAGES
    from metroliza.app.windows_candidate_inference import FAILURE_CODES, FAILURE_STAGES

    def longest(values):
        return max(values, key=len)
    fatal = {"present": True, "kind": "fatal_python_error", "frames": ["a"*64 + ":" + "b"*64]*12,
             "truncated": False, "multiple_blocks": True}
    observation = {
        "startup_phases": list(probe.PHASES), "child_fatal_observation": fatal,
        "observed_exit_code": 0xC0000409, "observed_process": "fresh_reopen_launcher_handle",
        "receipt_state": "valid_success", "startup_marker": "not_observed",
        "producer_stage": longest(driver._CHILD_FAILURE_STAGES | driver._REOPEN_FAILURE_STAGES),
        "allowlisted_failure": longest(driver._CLOSED_CHILD_FAILURES),
        "xlsx_failure": longest(_SAFE_FAILURE_CODES), "xlsx_failure_stage": longest(_SAFE_FAILURE_STAGES),
        "inference_failure": longest(FAILURE_CODES | driver.IMPORT_FAILURES | driver.CLEANUP_FAILURES),
        "inference_failure_stage": longest(FAILURE_STAGES), "cleanup_failure": longest(driver.CLEANUP_FAILURES),
        "probe_unavailable_sources": list(UNAVAILABLE_SOURCES),
    }
    payload = driver._failed_diagnostic_payload(observation, {"name": longest(driver._PRIVATE_CORE_STAGES)},
                                                driver.CandidateFailure("closed"), "a"*40)
    assert len(fatal["frames"]) == 12  # No mutation of the collected evidence.
    assert payload["startup_phases"] == list(probe.PHASES)
    assert payload["observed_exit_code"] == 0xC0000409
    assert payload["observed_exit_class"] == "stack_buffer_overrun"
    assert payload["child_fatal_observation"]["truncated"] is True
    assert payload["child_fatal_observation"]["multiple_blocks"] is True
    driver._write_failed_diagnostic(tmp_path, payload)
    assert (tmp_path / driver.FAILED_DIAGNOSTIC_FILE).stat().st_size <= 4096


def test_byte_limit_never_publishes_a_partial_function_name(tmp_path):
    from metroliza.shared.diagnostic_fatal_probe import FATAL_FILE
    from scripts.windows_candidate_exit_evidence import MAX_FATAL_BYTES, read_fatal_observation

    first = "Windows fatal exception: access violation\n"
    current = "Current thread 0x123 (most recent call first):\n"
    frame = '  File "/PRIVATE/module.py", line 12 in '
    padding = "\n" * (MAX_FATAL_BYTES - len(first + current + frame) - 3)
    (tmp_path / FATAL_FILE).write_text(first + padding + current + frame + "function_must_not_be_cut\n")
    observed = read_fatal_observation(tmp_path)
    assert observed == {"present": True, "kind": "other", "frames": [], "truncated": True, "multiple_blocks": False}


def _fatal_block(kind, function=None, *, current=True):
    header = "Current thread" if current else "Thread"
    stack = ('  <no Python frame>\n' if function is None else
             f'  File "C:\\PRIVATE\\module.py", line 12 in {function}\n')
    return (f"{kind}\n\n{header} 0x123 (most recent call first):\n" + stack + "\n").encode("ascii")


@pytest.mark.parametrize("first,last,current,frames", [
    ("Windows fatal exception: access violation", "Windows fatal exception: access violation", True, ["module:fatal"]),
    ("Windows fatal exception: access violation", "Windows fatal exception: stack overflow", True, ["module:fatal"]),
    ("Windows fatal exception: access violation", "Fatal Python error: Aborted", True, ["module:fatal"]),
    ("Windows fatal exception: access violation", "Windows fatal exception: stack overflow", False, []),
])
def test_e2_last_block_owns_kind_and_frames(tmp_path, first, last, current, frames):
    from scripts import windows_candidate_exit_evidence as evidence

    (tmp_path / evidence.FATAL_FILE).write_bytes(
        _fatal_block(first, "handled") + _fatal_block(last, "fatal", current=current))
    observed = evidence.read_fatal_observation(tmp_path)
    assert observed["kind"] == evidence._fatal_kind(last)
    assert observed["frames"] == frames
    assert observed["multiple_blocks"] is True
    assert observed["truncated"] is False


def test_e2_native_leading_block_cannot_borrow_later_frames(tmp_path):
    from scripts import windows_candidate_exit_evidence as evidence

    (tmp_path / evidence.FATAL_FILE).write_bytes(
        _fatal_block("Windows fatal exception: stack overflow", "native", current=False)
        + _fatal_block("Windows fatal exception: access violation", "fatal"))
    observed = evidence.read_fatal_observation(tmp_path)
    assert observed["kind"] == "access_violation"
    assert observed["frames"] == ["module:fatal"]
    assert observed["multiple_blocks"] is True


def test_e2_native_single_block_has_no_current_frames(tmp_path):
    from scripts import windows_candidate_exit_evidence as evidence

    (tmp_path / evidence.FATAL_FILE).write_bytes(
        _fatal_block("Windows fatal exception: access violation", "native", current=False))
    assert evidence.read_fatal_observation(tmp_path) == dict(
        present=True, kind="access_violation", frames=[], truncated=False, multiple_blocks=False)


@pytest.mark.parametrize("kind", ["Windows fatal exception: access violation", "Fatal Python error: Aborted"])
def test_e2_no_python_frame_is_complete_empty_stack(tmp_path, kind):
    from scripts import windows_candidate_exit_evidence as evidence

    (tmp_path / evidence.FATAL_FILE).write_bytes(_fatal_block(kind))
    observed = evidence.read_fatal_observation(tmp_path)
    assert observed["frames"] == []
    assert observed["truncated"] is False
    assert observed["multiple_blocks"] is False


def test_e2_tail_reads_at_most_64k_and_discards_partial_leading_block(tmp_path, monkeypatch):
    import builtins
    from scripts import windows_candidate_exit_evidence as evidence

    earlier = _fatal_block("Windows fatal exception: access violation", "handled")
    (tmp_path / evidence.FATAL_FILE).write_bytes(
        earlier * (evidence.MAX_FATAL_BYTES // len(earlier) + 10)
        + _fatal_block("Windows fatal exception: stack overflow", "fatal"))
    real_open, reads = builtins.open, []

    class Reader:
        def __init__(self, *args, **kwargs):
            self.stream = real_open(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size):
            reads.append((self.stream.tell(), size))
            assert 0 < size <= evidence.MAX_FATAL_BYTES
            return self.stream.read(size)

    monkeypatch.setattr(builtins, "open", Reader)
    observed = evidence.read_fatal_observation(tmp_path)
    assert reads[0][0] > 0
    assert observed == dict(present=True, kind="stack_overflow", frames=["module:fatal"],
                            truncated=True, multiple_blocks=True)


@pytest.mark.parametrize("mode", ["normal", "concurrent"])
def test_e2_diagnostic_modes_never_enable_fatal_sink(monkeypatch, tmp_path, mode):
    import faulthandler
    from metroliza.shared import diagnostic_fatal_probe as fatal

    _gates(monkeypatch, tmp_path)
    monkeypatch.delenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", mode)
    monkeypatch.setattr(faulthandler, "enable", lambda **_kw: pytest.fail("diagnostic-only sink enabled"))
    fatal.enable_private_fatal_probe()
    assert fatal._fatal_stream is None
    assert not (tmp_path / fatal.FATAL_FILE).exists()


def test_e2_portable_import_does_not_load_diagnostic_launcher():
    program = '''
import runpy, sys
runpy.run_path(sys.argv[1], run_name="portable_import_test")
assert "metroliza.app.diagnostic_launcher" not in sys.modules
from metroliza.shared.exit_code import system_exit_code
assert "metroliza.app.diagnostic_supervisor" not in sys.modules
assert system_exit_code(0xC0000005, windows=True) == -1073741819
'''
    result = subprocess.run([sys.executable, "-c", program, str(ROOT / "packaging/metroliza_portable_entry.py")],
                            cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                            capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_entry_fatal_fixture_keeps_real_handler_and_resets_sink(monkeypatch, tmp_path):
    import faulthandler
    from metroliza.shared import diagnostic_fatal_probe as fatal

    enabled_before = faulthandler.is_enabled()
    real_enable = faulthandler.enable
    isolation = isolated_fatal_probe.__wrapped__()
    next(isolation)
    try:
        assert faulthandler.enable is not real_enable
        _gates(monkeypatch, tmp_path)
        _entry(monkeypatch, [])
        handle = fatal._fatal_stream
        assert type(handle) is int
        # The entry never retargeted pytest's handler.
        assert faulthandler.is_enabled() is enabled_before
    finally:
        isolation.close()
    assert faulthandler.enable is real_enable
    assert faulthandler.is_enabled() is enabled_before
    assert fatal._fatal_stream is None
    with pytest.raises(OSError):
        os.fstat(handle)


def test_e2_exit_evidence_is_in_native_windows_pytest_selection():
    import yaml

    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    steps = [step for step in workflow["jobs"]["windows-core-smoke"]["steps"]
             if "tests/test_windows_candidate_exit_evidence.py" in step.get("run", "").split()]
    assert len(steps) == 1
    assert steps[0]["env"]["QT_QPA_PLATFORM"] == "windows"
    assert steps[0]["env"]["METROLIZA_EXPECT_QT_PLATFORM"] == "windows"
    assert "if" not in steps[0] and "continue-on-error" not in steps[0]
