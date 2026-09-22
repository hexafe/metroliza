from pathlib import Path
from types import SimpleNamespace

import pytest

from metroliza.app import windows_candidate_lifecycle_checks as checks
from metroliza.app.windows_candidate_lifecycle_checks import FACETS, run_lifecycle_checks


FIXTURES = Path(__file__).parent / "fixtures" / "windows_candidate" / "reports"


def test_logical_digest_ignores_catalog_order_but_detects_data_and_schema_changes(tmp_path):
    from contextlib import closing
    import sqlite3

    path = tmp_path / "synthetic.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE measurements (value REAL); INSERT INTO measurements VALUES (10.02); "
                         "CREATE INDEX first_idx ON measurements(value); CREATE INDEX second_idx ON measurements(value);")
        original = checks._logical_sha256(path)
        db.executescript("DROP INDEX first_idx; CREATE INDEX first_idx ON measurements(value);")
        assert checks._logical_sha256(path) == original
        db.executescript("UPDATE measurements SET value = 20.04;")
        assert checks._logical_sha256(path) != original
        db.executescript("UPDATE measurements SET value = 10.02; DROP INDEX first_idx;")
        assert checks._logical_sha256(path) != original


def test_lifecycle_checks_reject_invalid_inputs(tmp_path):
    observation = run_lifecycle_checks(tmp_path / "missing", FIXTURES)

    assert observation["status"] == "failed"
    assert observation["runtime_context"] == "source"
    assert observation["error_codes"] == ["scratch_invalid"]
    assert tuple(observation["facets"]) == FACETS


def test_lifecycle_checks_reports_packaged_runtime_context(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.sys, "frozen", True, raising=False)

    observation = run_lifecycle_checks(tmp_path / "missing", FIXTURES)

    assert observation["runtime_context"] == "packaged"


def test_lifecycle_checks_use_real_workers_and_keep_native_claim_explicit(tmp_path):
    from metroliza.app.bootstrap import get_or_create_qapplication

    app = get_or_create_qapplication()
    native = checks.os.name == "nt" and app.platformName().casefold() == "windows"

    observation = run_lifecycle_checks(tmp_path, FIXTURES)

    assert observation["status"] == "passed", observation
    assert observation["runtime_context"] == "source"
    assert observation["error_codes"] == []
    assert set(observation["facets"].values()) == {"passed"}
    assert observation["evidence"]["qpa"] == app.platformName()
    assert observation["evidence"]["native_windows_assessed"] is native
    assert observation["evidence"]["review_database_created"] is False
    assert observation["evidence"]["export_status"] == "cancelled"
    assert observation["evidence"]["cancelled_export_published"] is False
    assert observation["evidence"]["dirty_close_deferred"] is False
    assert observation["evidence"]["dashboard_worker_class"] == "RealtimeDashboardWriterThread"
    assert observation["evidence"]["rebound_same_dialog"] is True


@pytest.mark.parametrize("join_kind", ("report", "export", "dashboard"))
def test_lifecycle_failed_joins_exit_unavailable_without_receipt(
    monkeypatch, join_kind,
):
    from metroliza.app import windows_candidate_native_check as control

    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION", "1")
    monkeypatch.setenv(control.MODE_ENV, "unavailable")
    bindings = control._bindings()
    originals = [(module, attr, getattr(module, attr)) for _, module, attr in bindings]
    retained_before = len(control._UNJOINED_OWNERS)
    waits, receipts = [], []
    worker = SimpleNamespace(
        isRunning=lambda: True,
        wait=lambda timeout: waits.append(timeout) or False,
    )
    owner = object()

    def operation():
        if join_kind == "report":
            report_owner = SimpleNamespace(_reports_workspace=SimpleNamespace(
                preflight_thread=None,
                parse_thread=worker,
                _request_active_worker_cancellation=lambda: None,
            ))
            nonlocal owner
            owner = report_owner
            checks._join_report_workers(
                owner,
                SimpleNamespace(processEvents=lambda: pytest.fail("failed join fell through")),
            )
        else:
            checks._join_owned_worker(worker, owner, f"{join_kind}_worker_join_deadline")
        receipts.append("passed")

    try:
        with pytest.raises(control._UnjoinedNativeOwner) as caught:
            control.run_with_native_mode(operation)
        assert caught.value.code == 22
        assert waits == [20000] and receipts == []
        assert control._UNJOINED_OWNERS[-1] is owner
    finally:
        for module, attr, original in originals:
            setattr(module, attr, original)
        del control._UNJOINED_OWNERS[retained_before:]


def test_lifecycle_seed_ordinary_cleanup_error_retains_exact_owner(monkeypatch):
    from metroliza.app import windows_candidate_native_check as control

    owner = object()
    retained_before = len(checks._RETAINED_WINDOWS)
    monkeypatch.setattr(control, "close_report_owner",
                        lambda *_args: (_ for _ in ()).throw(RuntimeError("synthetic")))
    try:
        with pytest.raises(checks.LifecycleChecksFailure, match="seed_window_cleanup_failed"):
            checks._close_seed_owner(owner, object())
        assert checks._RETAINED_WINDOWS[-1] is owner
    finally:
        del checks._RETAINED_WINDOWS[retained_before:]


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt(), SystemExit(22)))
def test_lifecycle_seed_finalizer_does_not_catch_process_interrupt(monkeypatch, interrupt):
    from metroliza.app import windows_candidate_native_check as control

    retained_before = len(checks._RETAINED_WINDOWS)
    monkeypatch.setattr(control, "close_report_owner",
                        lambda *_args: (_ for _ in ()).throw(interrupt))

    with pytest.raises(type(interrupt)) as caught:
        checks._close_seed_owner(object(), object())

    assert caught.value is interrupt
    assert len(checks._RETAINED_WINDOWS) == retained_before
