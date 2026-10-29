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
from scripts.windows_candidate_exit_evidence import absent_fatal_observation

ROOT = Path(launcher.__file__).resolve().parents[3]


def _fatal(**fields):
    return dict(absent_fatal_observation(), **fields)


def _inventory(**fields):
    return {"qapp_alive": False, "qt_wrappers": 0, "qt_classes": [], "cpp_created_wrappers": 0, "py_owned_wrappers": 0,
            "threads_alive": 1, "daemon_threads": 0, "deleted_wrappers": 0, **fields}


def test_g_native_thread_recovers_main_stack_without_publishing_ident(tmp_path):
    from scripts import windows_candidate_exit_evidence as evidence

    (tmp_path / "child-main-thread-private.txt").write_bytes(b"main_thread=0x0000000000000123\n")
    (tmp_path / evidence.FATAL_FILE).write_bytes(
        b'Windows fatal exception: access violation\n\n'
        b'Thread 0x00000456 (most recent call first):\n'
        b'  File "C:\\PRIVATE\\worker.py", line 42 in worker\n\n'
        b'Thread 0x00000123 (most recent call first):\n'
        b'  File "C:\\PRIVATE\\shutdown.py", line 42 in finalize\n')
    observed = evidence.read_fatal_observation(tmp_path)
    assert observed["current_thread_marked"] is False
    assert observed["faulting_is_main"] == "unknown"
    assert observed["python_threads"] == 2
    assert observed["frames"] == []
    assert observed["main_frames"] == ["shutdown:finalize"]
    assert all(secret not in json.dumps(observed) for secret in ("PRIVATE", "0x", "worker:worker"))


def test_g_inventory_registered_before_marker_and_runs_last(monkeypatch, tmp_path):
    import gc

    callbacks = []
    monkeypatch.setattr(gc, "get_objects", lambda: [])
    _gates(monkeypatch, tmp_path)
    monkeypatch.setattr(atexit, "register", lambda *args: callbacks.append(args))
    monkeypatch.setitem(sys.modules, "metroliza.shared.diagnostic_transport", SimpleNamespace(
        attach_child_recorder=lambda: None, supervised_mode_requested=lambda: False))
    monkeypatch.setitem(sys.modules, "metroliza.app.bootstrap", SimpleNamespace(run_application=lambda: 7))
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(ROOT / "packaging/metroliza_package_entry.py"), run_name="__main__")
    assert caught.value.code == 7
    assert len(callbacks) == 2
    assert callbacks[1] == (probe.mark, "child_atexit_reached")
    for callback, *args in reversed(callbacks):
        callback(*args)
    inventory = json.loads((tmp_path / "child-exit-inventory-private.json").read_bytes())
    assert set(inventory) == {"qapp_alive", "qt_wrappers", "qt_classes", "cpp_created_wrappers", "py_owned_wrappers",
                              "threads_alive", "daemon_threads", "deleted_wrappers"}


def test_g2_census_uses_only_wrapper_flags(monkeypatch, tmp_path):
    import gc
    from metroliza.shared import diagnostic_fatal_probe as fatal

    dereferences, queries = [], []

    class Wrapper:
        def parent(self):
            dereferences.append("parent")
            raise RuntimeError("C++ object must not be accessed")

    objects = [Wrapper() for _ in range(8)]
    flags = {id(obj): (bool(i & 1), bool(i & 2), bool(i & 4)) for i, obj in enumerate(objects)}

    def query(obj, index):
        queries.append((id(obj), index))
        return flags[id(obj)][index]

    monkeypatch.setattr(gc, "get_objects", lambda: [object(), *objects])
    monkeypatch.setitem(sys.modules, "PyQt6.sip", SimpleNamespace(
        simplewrapper=Wrapper, isdeleted=lambda obj: query(obj, 0),
        ispyowned=lambda obj: query(obj, 1), ispycreated=lambda obj: query(obj, 2)))
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", SimpleNamespace(
        QObject=Wrapper, QCoreApplication=SimpleNamespace(instance=lambda: None)))
    fatal._write_exit_inventory(tmp_path)
    assert dereferences == []
    assert sorted(queries) == sorted((id(obj), flag) for obj in objects for flag in range(3))
    result = json.loads((tmp_path / fatal.INVENTORY_FILE).read_bytes())
    assert {key: result[key] for key in ("qt_wrappers", "deleted_wrappers", "cpp_created_wrappers",
                                       "py_owned_wrappers")} == {
        "qt_wrappers": 8, "deleted_wrappers": 4, "cpp_created_wrappers": 4, "py_owned_wrappers": 4,
    }
    assert "qobject_parentless" not in result


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("failure", [None, "heap", "write"])
def test_g2_census_disables_gc_and_restores_state(monkeypatch, tmp_path, enabled, failure):
    import gc
    from metroliza.shared import diagnostic_fatal_probe as fatal

    state, during = [enabled], []

    def toggle(value):
        state[0] = value

    def heap():
        during.append(state[0])
        if failure == "heap":
            raise KeyboardInterrupt("synthetic")
        return []

    def write(*_args):
        during.append(state[0])
        if failure == "write":
            raise SystemExit(7)

    monkeypatch.setattr(gc, "isenabled", lambda: state[0])
    monkeypatch.setattr(gc, "disable", lambda: toggle(False))
    monkeypatch.setattr(gc, "enable", lambda: toggle(True))
    monkeypatch.setattr(gc, "get_objects", heap)
    monkeypatch.setattr(fatal, "_write_private", write)
    fatal._write_exit_inventory(tmp_path)
    assert during and not any(during)
    assert state[0] is enabled


def test_g2_validator_accepts_overlapping_wrapper_flags_and_rejects_parentless():
    from scripts.windows_candidate_exit_evidence import valid_exit_inventory

    # Ownership, origin and deletion are independent wrapper flags.
    assert valid_exit_inventory(_inventory(qt_wrappers=1, deleted_wrappers=1,
                                          cpp_created_wrappers=1, py_owned_wrappers=1))
    legacy = _inventory()
    del legacy["cpp_created_wrappers"], legacy["py_owned_wrappers"]
    legacy["qobject_parentless"] = 0
    assert not valid_exit_inventory(legacy)


@pytest.mark.parametrize("current,main,is_main,main_frames", [
    ("123", "0000000000000123", True, []),
    ("456", "0000000000000123", False, ["module:main"]),
    (None, "0000000000000123", "unknown", ["module:main"]),
    ("456", None, "unknown", []),
])
def test_g_faulting_thread_identity_uses_only_last_block(tmp_path, current, main, is_main, main_frames):
    from metroliza.shared.diagnostic_fatal_probe import MAIN_THREAD_FILE
    from scripts import windows_candidate_exit_evidence as evidence

    if main is not None:
        (tmp_path / MAIN_THREAD_FILE).write_text(f"main_thread=0x{main}\n")
    header = "Current thread" if current == "123" else "Thread"
    raw = (_fatal_block("Windows fatal exception: stack overflow", "handled")
           + b"Windows fatal exception: access violation\n\n"
           + f'{header} 0x123 (most recent call first):\n  File "/PRIVATE/module.py", line 9 in main\n\n'.encode())
    if current == "456":
        raw += b'Current thread 0x456 (most recent call first):\n  <no Python frame>\n'
    (tmp_path / evidence.FATAL_FILE).write_bytes(raw)
    result = evidence.read_fatal_observation(tmp_path)
    assert result["current_thread_marked"] is (current is not None)
    assert result["faulting_is_main"] == is_main
    assert result["main_frames"] == main_frames
    assert result["python_threads"] == (2 if current == "456" else 1)
    assert result["multiple_blocks"] is True
    assert evidence.valid_fatal_observation(result)


def test_g_main_frames_and_thread_count_caps(tmp_path):
    from metroliza.shared.diagnostic_fatal_probe import MAIN_THREAD_FILE
    from scripts import windows_candidate_exit_evidence as evidence

    (tmp_path / MAIN_THREAD_FILE).write_bytes(b"main_thread=0x0000000000000123\n")
    raw = b'Windows fatal exception: access violation\nThread 0x123 (most recent call first):\n'
    raw += b'  File "C:\\PRIVATE\\ok.py", line 1 in function\n' * 8
    raw += b'  File "C:\\PRIVATE\\bad-name.py", line 1 in secret\n\n'
    raw += b'Thread 0x456 (most recent call first):\n  <no Python frame>\n\n' * 40
    (tmp_path / evidence.FATAL_FILE).write_bytes(raw)
    result = evidence.read_fatal_observation(tmp_path)
    assert result["python_threads"] == 32
    assert result["main_frames"] == ["ok:function"] * 6
    assert result["truncated"] is True
    assert "PRIVATE" not in json.dumps(result) and "secret" not in json.dumps(result)


@pytest.mark.parametrize("change", [
    {"current_thread_marked": 1}, {"faulting_is_main": 1}, {"faulting_is_main": "yes"},
    {"python_threads": True}, {"python_threads": 33}, {"python_threads": -1},
    {"main_frames": ["ok:f"] * 7}, {"main_frames": ["/PRIVATE:f"]},
    {"current_thread_marked": False, "faulting_is_main": True},
    {"current_thread_marked": True, "python_threads": 0},
    {"current_thread_marked": True, "python_threads": 1, "faulting_is_main": True, "main_frames": ["ok:f"]},
    {"python_threads": 0, "main_frames": ["ok:f"]},
    {"current_thread_marked": True, "python_threads": 2, "main_frames": ["ok:f"]},
    {"current_thread_marked": True, "faulting_is_main": False, "python_threads": 1, "main_frames": ["ok:f"]},
])
def test_g_thread_fields_are_closed(change):
    from scripts.windows_candidate_exit_evidence import valid_fatal_observation

    assert not valid_fatal_observation(_fatal(present=True, **change))


def test_g_sink_records_fixed_private_main_ident(monkeypatch, tmp_path):
    import threading
    from metroliza.shared import diagnostic_fatal_probe as fatal

    _gates(monkeypatch, tmp_path)
    _entry(monkeypatch, [])
    data = (tmp_path / fatal.MAIN_THREAD_FILE).read_bytes()
    assert data == f"main_thread=0x{threading.main_thread().ident:016x}\n".encode()
    assert len(data) == 31


@pytest.mark.parametrize("missing", ["METROLIZA_STARTUP_SMOKE", "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION",
                                    "METROLIZA_DIAGNOSTIC_STARTUP_PROBE", "METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"])
def test_g_inventory_requires_fatal_sink_gates(monkeypatch, tmp_path, missing):
    from metroliza.shared import diagnostic_fatal_probe as fatal

    _gates(monkeypatch, tmp_path)
    monkeypatch.delenv(missing)
    monkeypatch.setattr(atexit, "register", lambda *_a: pytest.fail("inventory gate bypassed"))
    fatal.register_private_exit_inventory()


def test_g_inventory_censuses_real_wrappers_without_collecting(monkeypatch, tmp_path, qapplication_session):
    import gc
    from PyQt6 import sip, QtCore, QtGui
    from metroliza.shared import diagnostic_fatal_probe as fatal
    from scripts.windows_candidate_exit_evidence import read_exit_inventory

    parent, child, orphan, deleted = (QtCore.QObject() for _ in range(4))
    child.setParent(parent)
    sip.delete(deleted)
    dispatcher = qapplication_session.eventDispatcher()
    objects = [parent, child, orphan, deleted, QtGui.QIcon(), QtGui.QPixmap(), qapplication_session, dispatcher]
    # Check the installed SIP API on known Python-/C++-created and transferred objects.
    assert all(sip.ispycreated(obj) for obj in objects[:-1])
    assert not sip.ispycreated(dispatcher) and not sip.ispyowned(dispatcher)
    assert sip.ispyowned(parent) and not sip.ispyowned(child)
    assert sip.isdeleted(deleted) and not sip.isdeleted(parent)
    owned = sum(sip.ispyowned(obj) for obj in objects)
    monkeypatch.setattr(gc, "get_objects", lambda: objects)
    monkeypatch.setattr(gc, "collect", lambda *_a: pytest.fail("probe collected"))
    calls = []
    real_instance = QtCore.QCoreApplication.instance
    monkeypatch.setattr(QtCore.QCoreApplication, "instance", staticmethod(lambda: calls.append(1) or real_instance()))
    fatal._write_exit_inventory(tmp_path)
    assert calls == []
    result = read_exit_inventory(tmp_path)
    assert result is not None
    assert {key: result[key] for key in ("qapp_alive", "qt_wrappers", "deleted_wrappers", "cpp_created_wrappers",
                                       "py_owned_wrappers", "qt_classes")} == {
        "qapp_alive": True, "qt_wrappers": 8, "deleted_wrappers": 1,
        "cpp_created_wrappers": 1, "py_owned_wrappers": owned,
        "qt_classes": [["QObject", 4], ["QAbstractEventDispatcher", 1], ["QApplication", 1], ["QIcon", 1],
                       ["QPixmap", 1]],
    }


def test_g_inventory_does_not_import_qt(monkeypatch, tmp_path):
    import builtins
    import gc
    import threading
    from metroliza.shared import diagnostic_fatal_probe as fatal
    from scripts.windows_candidate_exit_evidence import read_exit_inventory

    for name in list(sys.modules):
        if name == "PyQt6" or name.startswith("PyQt6."):
            monkeypatch.delitem(sys.modules, name)
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith("PyQt6")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(gc, "get_objects", lambda: [])
    monkeypatch.setattr(threading, "enumerate", lambda: [SimpleNamespace(daemon=False), SimpleNamespace(daemon=True)])
    fatal._write_exit_inventory(tmp_path)
    assert read_exit_inventory(tmp_path) == _inventory(threads_alive=2, daemon_threads=1)


@pytest.mark.parametrize("error", [OSError, RuntimeError, KeyboardInterrupt, SystemExit])
def test_g_inventory_swallows_all_callback_failures(monkeypatch, tmp_path, error):
    import gc
    from metroliza.shared import diagnostic_fatal_probe as fatal

    def fail():
        raise error("PRIVATE")

    monkeypatch.setattr(gc, "get_objects", fail)
    fatal._write_exit_inventory(tmp_path)
    assert not (tmp_path / fatal.INVENTORY_FILE).exists()


def test_g_application_liveness_uses_existing_wrappers_only():
    from metroliza.shared import diagnostic_fatal_probe as fatal

    class App:
        pass

    live, gone = App(), App()
    sip = SimpleNamespace(isdeleted=lambda obj: obj is gone)
    assert fatal._live_application_wrapper([object(), gone, live], sip, App) is True
    assert fatal._live_application_wrapper([gone], sip, App) is False
    assert fatal._live_application_wrapper([live], sip, ()) is False


def test_g_wrapper_class_allowlist_flags_and_top12():
    from metroliza.shared import diagnostic_fatal_probe as fatal

    class Wrapper:
        def parent(self):
            pytest.fail("deleted wrapper dereferenced")

    objects = [type(f"Class{i:02}", (Wrapper,), {})() for i in range(15)]
    objects += [type("PRIVATE-bad", (Wrapper,), {})(), type("x" * 50, (Wrapper,), {})()]
    result = fatal._wrapper_inventory(objects, SimpleNamespace(
        simplewrapper=Wrapper, isdeleted=lambda _obj: True, ispyowned=lambda _obj: True, ispycreated=lambda _obj: False))
    assert result == {"qt_wrappers": 17, "deleted_wrappers": 17, "cpp_created_wrappers": 17, "py_owned_wrappers": 17,
                      "qt_classes": [["other", 2]] + [[f"Class{i:02}", 1] for i in range(11)]}


@pytest.mark.parametrize("change", [
    {"qapp_alive": 1}, {"qt_wrappers": True}, {"qt_wrappers": 10**6 + 1}, {"deleted_wrappers": -1},
    {"cpp_created_wrappers": 1}, {"py_owned_wrappers": 1}, {"daemon_threads": 2}, {"threads_alive": 1.0},
    {"cpp_created_wrappers": True}, {"py_owned_wrappers": -1}, {"qobject_parentless": 0},
    {"qt_classes": [["QObject", 1]]}, {"qt_classes": [["PRIVATE-bad", 1]]},
    {"qt_classes": [["other", True]]}, {"raw": "PRIVATE"},
    {"qt_wrappers": 2, "qt_classes": [["other", 1], ["other", 1]]},
    {"qt_wrappers": 2, "qt_classes": [["Z", 1], ["A", 1]]},
    {"qt_wrappers": 2, "deleted_wrappers": 3},
])
def test_g_inventory_validator_rejects_unclosed_values(tmp_path, change):
    from scripts.windows_candidate_exit_evidence import valid_exit_inventory

    invalid = _inventory(**change)
    assert not valid_exit_inventory(invalid)
    payload = driver._failed_diagnostic_payload({}, {}, driver.CandidateFailure("closed"), "a" * 40)
    payload["exit_inventory"] = invalid
    with pytest.raises(driver.CandidateFailure, match="invalid_exit_evidence"):
        driver._write_failed_diagnostic(tmp_path, payload)


@pytest.mark.parametrize("name", ["child-exit-inventory-private.json", "child-main-thread-private.txt"])
@pytest.mark.parametrize("fault", ["symlink", "hardlink", "size", "fstat"])
def test_g_private_sidecars_require_checked_regular_files(tmp_path, monkeypatch, name, fault):
    from scripts import windows_candidate_exit_evidence as evidence

    target = tmp_path / name
    data = json.dumps(_inventory()).encode() if name.endswith("json") else b"main_thread=0x0000000000000123\n"
    other = tmp_path / "other"
    other.write_bytes(data)
    if fault == "symlink":
        target.symlink_to(other)
    elif fault == "hardlink":
        os.link(other, target)
    else:
        target.write_bytes(data + b" " * 4096 if fault == "size" else data)
    if fault == "fstat":
        real_fstat = os.fstat
        target_ino = target.stat().st_ino

        def replaced(descriptor):
            info = real_fstat(descriptor)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1) if info.st_ino == target_ino else info

        monkeypatch.setattr(evidence.os, "fstat", replaced)
    if name.endswith("json"):
        assert evidence.read_exit_inventory(tmp_path) is None
    else:
        (tmp_path / evidence.FATAL_FILE).write_bytes(_fatal_block("Windows fatal exception: access violation", "main"))
        assert evidence.read_fatal_observation(tmp_path)["faulting_is_main"] == "unknown"


@pytest.mark.parametrize("raw", [b"{}", b"null", b"[]", b"{", b"\xff", b'{"qapp_alive":false,"qapp_alive":true}'])
def test_g_invalid_inventory_bytes_are_unavailable(tmp_path, raw):
    from metroliza.shared.diagnostic_fatal_probe import INVENTORY_FILE
    from scripts.windows_candidate_exit_evidence import read_exit_inventory

    (tmp_path / INVENTORY_FILE).write_bytes(raw)
    assert read_exit_inventory(tmp_path) is None


@pytest.mark.parametrize("scenario", ["core", "reopen"])
@pytest.mark.parametrize("cleanup", ["complete", "failed"])
def test_g_inventory_output_waits_for_cleanup_and_keeps_roots_distinct(tmp_path, monkeypatch, capsys, scenario, cleanup):
    from metroliza.shared.diagnostic_fatal_probe import INVENTORY_FILE
    from scripts import windows_candidate_exit_evidence as evidence

    core, reopen = tmp_path / "core", tmp_path / "reopen"
    for index, root in enumerate((core, reopen)):
        root.mkdir()
        (root / INVENTORY_FILE).write_text(json.dumps(_inventory(threads_alive=index + 1)))
    if cleanup == "failed":
        monkeypatch.setattr(evidence, "read_exit_inventory", lambda *_a: pytest.fail("live writer read"))
    observation = {"owned_cleanup": cleanup}
    evidence.retain_exit_inventory(observation, core if scenario == "core" else reopen, scenario=scenario)
    expected = _inventory(threads_alive=1 if scenario == "core" else 2) if cleanup == "complete" else None
    assert observation["exit_inventory"] == expected
    assert capsys.readouterr().out == scenario + "_exit_inventory=" + json.dumps(expected, separators=(",", ":")) + "\n"


def test_g_successful_core_collects_once_before_fresh_reopen(tmp_path, monkeypatch, capsys):
    from metroliza.shared.diagnostic_fatal_probe import INVENTORY_FILE

    closed, roots = [], []

    class Process:
        def close(self, *, terminate):
            closed.append(terminate)
            (roots[0] / INVENTORY_FILE).write_text(json.dumps(_inventory()))

    class Api:
        def launch(self, _exe, environment, _cwd, *, owned, expected_images):
            roots.append(Path(environment["METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT"]))
            process = Process()
            owned.append(process)
            return process

    diag = SimpleNamespace(_relocate_package=lambda *_a: tmp_path, _sanitized_environment=lambda *_a: {},
                           _WindowsApi=Api, _wait_for_job_exit=lambda *_a: True,
                           _close_owned_processes=lambda owned, **kwargs: [p.close(**kwargs) for p in owned])
    monkeypatch.setattr(driver, "_stage_known_fixtures", lambda *_a: tmp_path)
    monkeypatch.setattr(driver, "_stage_ocr_fixture", lambda *_a: tmp_path)
    monkeypatch.setattr(driver, "_wait_for_launcher_exit", lambda *_a, **_kw: (0, True))
    monkeypatch.setattr(driver, "_validated_core_payload", lambda *_a: {})
    monkeypatch.setattr(driver, "_validate_ui_observation", lambda *_a, **_kw: None)
    monkeypatch.setattr(driver, "_validate_closeout_observation", lambda *_a, **_kw: None)
    monkeypatch.setattr(driver, "_verified_core_topology", lambda *_a: {})
    observation = {"owned_cleanup": "not_attempted"}

    def reached_reopen(*_a, **_kw):
        assert closed == [False]
        assert observation["exit_inventory"] == _inventory()
        assert capsys.readouterr().out == 'core_exit_inventory=' + json.dumps(_inventory(), separators=(",", ":")) + '\n'
        raise driver.CandidateFailure("fresh_reopen_process_failed")

    monkeypatch.setattr(driver, "_run_fresh_reopen", reached_reopen)
    with pytest.raises(driver.CandidateFailure, match="^fresh_reopen_process_failed$"):
        driver._run_private_core(tmp_path, args=SimpleNamespace(source_checkout=tmp_path, dpi_scale="1.0", native_mode="default"),
                                 diag=diag, artifact=tmp_path, fixtures=tmp_path, output=tmp_path, deadline=0,
                                 before="synthetic", stage={}, failure_observation=observation)
    assert closed == [False] and capsys.readouterr().out == ""


def test_g_inventory_counter_caps_without_allocating_a_million_objects(monkeypatch, tmp_path):
    import gc
    import itertools
    import threading
    from metroliza.shared import diagnostic_fatal_probe as fatal
    from scripts.windows_candidate_exit_evidence import read_exit_inventory

    class Wrapper:
        pass

    sip = SimpleNamespace(simplewrapper=Wrapper, isdeleted=lambda _obj: True,
                          ispyowned=lambda _obj: False, ispycreated=lambda _obj: False)
    result = fatal._wrapper_inventory(itertools.repeat(Wrapper(), 10**6 + 1), sip)
    assert result == {"qt_wrappers": 10**6, "deleted_wrappers": 10**6,
                      "cpp_created_wrappers": 10**6, "py_owned_wrappers": 0,
                      "qt_classes": [["Wrapper", 10**6]]}

    class Threads:
        def __len__(self):
            return 10**6 + 1

        def __iter__(self):
            return itertools.repeat(SimpleNamespace(daemon=True), 10**6 + 1)

    monkeypatch.setattr(gc, "get_objects", lambda: [])
    monkeypatch.setattr(threading, "enumerate", Threads)
    fatal._write_exit_inventory(tmp_path)
    result = read_exit_inventory(tmp_path)
    assert result["threads_alive"] == result["daemon_threads"] == 10**6


@pytest.mark.parametrize("opened", [False, True])
def test_g_inventory_rejects_reparse_attributes_even_after_open(tmp_path, monkeypatch, opened):
    from metroliza.shared.diagnostic_fatal_probe import INVENTORY_FILE
    from scripts import windows_candidate_exit_evidence as evidence

    target = tmp_path / INVENTORY_FILE
    target.write_text(json.dumps(_inventory()))
    real_stat, real_fstat = Path.lstat, os.fstat

    def reparse(info):
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_nlink=1, st_mode=info.st_mode,
                               st_size=info.st_size, st_file_attributes=0x400)

    if opened:
        monkeypatch.setattr(os, "fstat", lambda descriptor: reparse(real_fstat(descriptor)))
    else:
        monkeypatch.setattr(Path, "lstat", lambda path: reparse(real_stat(path)) if path == target else real_stat(path))
    assert evidence.read_exit_inventory(tmp_path) is None


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
    assert read_fatal_observation(tmp_path) == _fatal(present=True, kind=kind)


def test_maximum_fatal_frames_and_all_phases_fit(tmp_path):
    fatal = _fatal(present=True, kind="fatal_python_error", frames=["a"*64 + ":" + "b"*64]*12,
                   truncated=True, multiple_blocks=True, current_thread_marked=True, python_threads=1)
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

    empty = _fatal()
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
    payload["child_fatal_observation"] = _fatal(present=True)
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
    fatal = _fatal(present=True, kind="fatal_python_error", frames=["a"*64 + ":" + "b"*64]*12,
                   main_frames=["c"*64 + ":" + "d"*64]*6, faulting_is_main=False,
                   multiple_blocks=True, current_thread_marked=True, python_threads=32)
    inventory = _inventory(qt_wrappers=10**6, deleted_wrappers=10**6,
                           cpp_created_wrappers=10**6, py_owned_wrappers=10**6, threads_alive=10**6,
                           daemon_threads=10**6, qt_classes=[[f"C{i:048}", 1000] for i in range(12)])
    observation = {
        "startup_phases": list(probe.PHASES), "child_fatal_observation": fatal,
        "exit_inventory": inventory,
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
    assert payload["child_fatal_observation"]["faulting_is_main"] is False
    assert payload["exit_inventory"]["qt_classes"] == []  # Classes trimmed before either stack.
    assert len(inventory["qt_classes"]) == 12 and len(fatal["main_frames"]) == 6
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
    assert observed == _fatal(present=True, truncated=True)


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
    assert evidence.read_fatal_observation(tmp_path) == _fatal(
        present=True, kind="access_violation", python_threads=1)


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
    assert observed == _fatal(present=True, kind="stack_overflow", frames=["module:fatal"],
                             truncated=True, multiple_blocks=True, current_thread_marked=True, python_threads=1)


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
