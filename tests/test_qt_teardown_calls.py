"""Scenario-level finally blocks preserve qualification return values."""
from types import SimpleNamespace
import sys

import pytest


@pytest.mark.parametrize("failed", [False, True])
def test_core_finally_calls_teardown_and_preserves_exit(tmp_path, monkeypatch, qt_shutdown_spy, failed):
    from metroliza.app import windows_candidate_qualification as core, windows_candidate_native_check as native
    from metroliza.shared import diagnostic_runtime_audit as audit

    monkeypatch.setattr(core, "requested_scenario", lambda: "core")
    monkeypatch.setattr(core, "_ordinary_user", lambda: True)
    monkeypatch.setattr(core, "_runtime_provenance", lambda: {"source_sha": "1" * 40})
    monkeypatch.setattr(core, "_root", lambda: tmp_path)
    monkeypatch.setattr(core, "_fixture_dir", lambda: tmp_path)
    monkeypatch.setattr(core, "_ocr_fixture", lambda: tmp_path)
    monkeypatch.setattr(audit, "wait_for_host_ready", lambda: None)

    def execute(callback):
        if failed:
            raise RuntimeError("private")
        return {}

    monkeypatch.setattr(native, "run_with_native_mode", execute)
    assert core.run_qualification() == (21 if failed else 0)
    qt_shutdown_spy.assert_called_once_with()


@pytest.mark.parametrize("failed", [False, True])
def test_reopen_finally_calls_teardown_and_preserves_exit(tmp_path, monkeypatch, qt_shutdown_spy, failed):
    from metroliza.app import bootstrap, windows_candidate_qualification as core, windows_candidate_reopen as reopen
    from metroliza.shared import diagnostic_runtime_audit as audit

    monkeypatch.setattr(core, "requested_scenario", lambda: "reopen")
    monkeypatch.setattr(core, "_ordinary_user", lambda: True)
    monkeypatch.setattr(core, "_runtime_provenance", lambda: {"source_sha": "1" * 40})
    monkeypatch.setattr(core, "_root", lambda: tmp_path)
    monkeypatch.setattr(reopen, "_fresh_input", lambda root: (root, {}, "expected"))
    monkeypatch.setattr(audit, "wait_for_host_ready", lambda: None)
    monkeypatch.setattr(bootstrap, "get_or_create_qapplication", lambda: SimpleNamespace(platformName=lambda: "offscreen"))

    def execute(*args):
        if failed:
            raise RuntimeError("private")
        return {"status": "passed", "database": {"before_sha256": "expected"}}

    monkeypatch.setattr(reopen, "run_reopen_checks", execute)
    assert reopen.run_fresh_qualification() == (21 if failed else 0)
    qt_shutdown_spy.assert_called_once_with()


@pytest.mark.parametrize("failed", [False, True])
def test_compute_finally_preserves_result_or_exception(monkeypatch, qt_shutdown_spy, failed):
    from metroliza.app import compute_worker_qualification as compute

    app = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", SimpleNamespace(
        QApplication=SimpleNamespace(instance=lambda: app)))
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv(compute.GATE, "synthetic")
    def execute(app):
        if failed:
            raise ValueError("synthetic")
        return 17
    monkeypatch.setattr(compute, "_run_with_application", execute)
    if failed:
        with pytest.raises(ValueError, match="synthetic"):
            compute.run_qualification()
    else:
        assert compute.run_qualification() == 17
    qt_shutdown_spy.assert_called_once_with(app)


@pytest.mark.parametrize("failed", [False, True])
def test_diagnostic_finally_preserves_exit(tmp_path, monkeypatch, qt_shutdown_spy, failed):
    from metroliza.app import bootstrap, diagnostic_qualification as diagnostic
    from metroliza.shared import diagnostic_runtime_audit as audit

    monkeypatch.setattr(diagnostic, "requested_scenario", lambda: "normal")
    monkeypatch.setattr(diagnostic, "_root", lambda: tmp_path)
    monkeypatch.setattr(diagnostic, "write_receipt", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_write_failure", lambda *args: None)
    monkeypatch.setattr(audit, "wait_for_host_ready", lambda: None)
    monkeypatch.setattr(bootstrap, "get_or_create_qapplication", lambda: SimpleNamespace(processEvents=lambda: None))
    def execute(*args):
        if failed:
            raise RuntimeError("private")
    monkeypatch.setattr(diagnostic, "_run_work", execute)
    assert diagnostic.run_qualification("normal") == (21 if failed else 0)
    qt_shutdown_spy.assert_called_once_with()
