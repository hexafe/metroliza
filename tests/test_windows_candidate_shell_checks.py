from pathlib import Path
from types import SimpleNamespace

import pytest

from metroliza.app import windows_candidate_shell_checks as checks
from metroliza.app.windows_candidate_shell_checks import FACETS, run_shell_checks


FIXTURES = Path(__file__).parent / "fixtures" / "windows_candidate" / "reports"


def test_shell_checks_reject_invalid_inputs(tmp_path):
    observation = run_shell_checks(tmp_path / "missing", FIXTURES)

    assert observation["status"] == "failed"
    assert observation["runtime_context"] == "source"
    assert observation["error_codes"] == ["scratch_invalid"]
    assert tuple(observation["facets"]) == FACETS


def test_shell_checks_reports_packaged_runtime_context(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.sys, "frozen", True, raising=False)

    observation = run_shell_checks(tmp_path / "missing", FIXTURES)

    assert observation["runtime_context"] == "packaged"


def test_shell_checks_run_real_ui_flow_with_actual_platform_claim(tmp_path):
    from metroliza.app.bootstrap import get_or_create_qapplication

    app = get_or_create_qapplication()
    native = checks.os.name == "nt" and app.platformName().casefold() == "windows"
    observation = run_shell_checks(tmp_path, FIXTURES, expected_dpr=float(app.primaryScreen().devicePixelRatio()))

    assert observation["status"] == ("passed" if native else "partial"), observation
    assert observation["runtime_context"] == "source"
    assert observation["error_codes"] == []
    assert observation["facets"] == {
        "single_planner_owner": "passed",
        "real_review_import": "passed",
        "native_shell_layout": "passed" if native else "not_assessed",
        "windows_qt_planner_keyboard": "passed" if native else "not_assessed",
    }
    assert observation["evidence"]["qpa"] == app.platformName()
    assert observation["evidence"]["fixture_count"] == 5
    assert observation["evidence"]["imported_count"] == 2
    assert observation["evidence"]["excluded_count"] == 3
    assert observation["evidence"]["import_oracle"]["table_counts"] == {
        "source_files": 2,
        "active_locations": 2,
        "parsed_reports": 2,
        "metadata": 2,
        "measurements": 2,
    }
    assert observation["evidence"]["import_oracle"]["file_names"] == [
        "REF001_2024-01-01_1.pdf",
        "REF001_2024-01-01_3.pdf",
    ]
    assert observation["evidence"]["import_oracle"]["measurement_values"] == [10.02, 10.02]


def test_windows_os_with_offscreen_qpa_cannot_claim_native_pass(tmp_path, monkeypatch):
    from metroliza.app import bootstrap

    monkeypatch.setattr(checks, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(bootstrap, "get_or_create_qapplication",
                        lambda: SimpleNamespace(platformName=lambda: "offscreen"))

    def source_only(_scratch, _fixtures, _app, _dpr, result):
        result["facets"]["single_planner_owner"] = "passed"
        result["facets"]["real_review_import"] = "passed"

    monkeypatch.setattr(checks, "_run", source_only)
    observation = checks.run_shell_checks(tmp_path, FIXTURES, expected_dpr=1.0)

    assert observation["status"] == "partial"
    assert observation["facets"]["native_shell_layout"] == "not_assessed"
    assert observation["facets"]["windows_qt_planner_keyboard"] == "not_assessed"


def test_shell_owner_failed_join_exits_unavailable_without_receipt(monkeypatch):
    from metroliza.app import windows_candidate_native_check as control

    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    monkeypatch.setenv(control.MODE_ENV, "unavailable")
    bindings = control._bindings()
    originals = [(module, attr, getattr(module, attr)) for _, module, attr in bindings]
    retained_before = len(control._UNJOINED_OWNERS)
    waits, receipts = [], []
    worker = SimpleNamespace(wait=lambda timeout: waits.append(timeout) or False)
    owner = SimpleNamespace(
        _reports_workspace=SimpleNamespace(
            preflight_thread=None,
            parse_thread=worker,
            _request_active_worker_cancellation=lambda: None,
        ),
        close=lambda: pytest.fail("unjoined shell owner was closed"),
    )
    try:
        with pytest.raises(control._UnjoinedNativeOwner) as caught:
            control.run_with_native_mode(
                lambda: (checks._close_shell_owner(owner, SimpleNamespace(
                    processEvents=lambda: pytest.fail("failed join fell through")
                )), receipts.append("passed"))
            )
        assert caught.value.code == 22
        assert waits == [20000] and receipts == []
        assert control._UNJOINED_OWNERS[-1] is owner
    finally:
        for module, attr, original in originals:
            setattr(module, attr, original)
        del control._UNJOINED_OWNERS[retained_before:]


def test_shell_owner_ordinary_cleanup_error_retains_exact_owner(monkeypatch):
    from metroliza.app import windows_candidate_native_check as control

    owner = object()
    retained_before = len(checks._RETAINED_WINDOWS)
    monkeypatch.setattr(control, "close_report_owner",
                        lambda *_args: (_ for _ in ()).throw(RuntimeError("synthetic")))
    try:
        with pytest.raises(checks.ShellChecksFailure, match="window_owner_cleanup_failed"):
            checks._close_shell_owner(owner, object())
        assert checks._RETAINED_WINDOWS[-1] is owner
    finally:
        del checks._RETAINED_WINDOWS[retained_before:]


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt(), SystemExit(22)))
def test_shell_owner_finalizer_does_not_catch_process_interrupt(monkeypatch, interrupt):
    from metroliza.app import windows_candidate_native_check as control

    retained_before = len(checks._RETAINED_WINDOWS)
    monkeypatch.setattr(control, "close_report_owner",
                        lambda *_args: (_ for _ in ()).throw(interrupt))

    with pytest.raises(type(interrupt)) as caught:
        checks._close_shell_owner(object(), object())

    assert caught.value is interrupt
    assert len(checks._RETAINED_WINDOWS) == retained_before
