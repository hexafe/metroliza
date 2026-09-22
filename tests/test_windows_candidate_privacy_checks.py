from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from metroliza.app.windows_candidate_privacy_checks import FACETS, run_privacy_checks


def test_privacy_controls_are_inert_without_both_gates(tmp_path, monkeypatch):
    monkeypatch.delenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", raising=False)
    result = run_privacy_checks(tmp_path)
    assert result["status"] == "failed"
    assert result["error_codes"] == ["privacy_qualification_gate_missing"]
    assert not list(tmp_path.iterdir())


def test_real_private_storage_denial_explicit_output_and_owned_cleanup(tmp_path, monkeypatch):
    from metroliza.app.bootstrap import get_or_create_qapplication

    app = get_or_create_qapplication()
    assert app is not None
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    result = run_privacy_checks(tmp_path)
    assert result["runtime_context"] == "source"
    assert result["error_codes"] == []
    assert result["status"] == ("passed" if os.name == "nt" else "partial")
    assert result["facets"] == {key: "passed" if os.name == "nt" or not key.endswith("cleanup_denial_retry")
                                else "not_assessed" for key in FACETS}


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
