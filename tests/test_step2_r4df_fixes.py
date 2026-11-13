"""Local regression proofs for STEP2 packet R4DF (#1148)."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metroliza.parsing import report_parser_factory as factory
from metroliza.parsing import review_pool
from tests.test_gc_policy import run_python
from tests.test_import_prepare_pool import _write_synthetic_reports
from tests.test_modifydb_record_model import current_dialog as current_dialog


@pytest.fixture
def portable_probe(tmp_path):
    path, = _write_synthetic_reports(tmp_path / "reports", 1)
    factory.reset_probe_cache()
    factory.resolve_parser_with_diagnostics(path)
    generation, fingerprint = review_pool.registry_state()
    entries = factory.export_probe_cache_entries((str(path),), generation_id=generation)
    assert len(entries) == 1
    factory.reset_probe_cache()
    yield path, entries, generation, fingerprint
    factory.reset_probe_cache()


def test_seeding_checks_stat_without_rehashing(portable_probe, monkeypatch):
    _path, entries, generation, fingerprint = portable_probe

    def no_hash(_self):
        pytest.fail("seeding rehashed a reviewed source")

    monkeypatch.setattr(factory.SourceInspectionContext, "sha256", property(no_hash))
    factory.seed_probe_cache_entries(entries, generation_id=generation, fingerprint=fingerprint)
    assert [key[2] for key in factory.PROBE_RESULT_CACHE] == [entries[0].source_identity]


def test_oversized_seeding_skips_identity_io(portable_probe, monkeypatch):
    _path, entries, generation, fingerprint = portable_probe
    monkeypatch.setattr(factory, "PROBE_RESULT_CACHE_MAX_ENTRIES", 0)

    def no_io(*_args, **_kwargs):
        pytest.fail("oversized seeding inspected a source")

    monkeypatch.setattr(factory.SourceInspectionContext, "from_path", no_io)
    factory.seed_probe_cache_entries(entries, generation_id=generation, fingerprint=fingerprint)
    assert not factory.PROBE_RESULT_CACHE


def test_identity_check_failure_does_not_abort_review(portable_probe, monkeypatch, caplog):
    _path, entries, generation, fingerprint = portable_probe

    def fail_identity(*_args, **_kwargs):
        raise RuntimeError("synthetic identity failure")

    monkeypatch.setattr(factory.SourceInspectionContext, "from_path", fail_identity)
    items = (SimpleNamespace(registry_generation_id=generation),)
    with caplog.at_level("DEBUG", logger=review_pool.__name__):
        accepted = review_pool._accepted(
            (fingerprint, generation, items, entries), fingerprint, generation, MagicMock(),
        )
    assert accepted is items
    assert "RuntimeError" in caplog.text
    assert not factory.PROBE_RESULT_CACHE


def test_cache_reset_during_seeding_skips_insert(portable_probe, monkeypatch):
    _path, entries, generation, fingerprint = portable_probe
    original = factory.SourceInspectionContext.from_path

    def resetting_identity(*args, **kwargs):
        context = original(*args, **kwargs)
        factory.reset_probe_cache()
        return context

    monkeypatch.setattr(factory.SourceInspectionContext, "from_path", resetting_identity)
    factory.seed_probe_cache_entries(entries, generation_id=generation, fingerprint=fingerprint)
    assert not factory.PROBE_RESULT_CACHE


def test_benchmark_harness_requests_session_application():
    from tests.test_step2_r4_fixes import test_benchmark_records_gc_policy_before_scenario_setup

    assert "qapplication_session" in inspect.signature(
        test_benchmark_records_gc_policy_before_scenario_setup,
    ).parameters


def test_progress_fallback_test_works_outside_repository(monkeypatch, tmp_path):
    from tests.test_step2_r4_fixes import test_lightweight_progress_fallback_ignores_delayed_keywords

    monkeypatch.chdir(tmp_path)
    test_lightweight_progress_fallback_ignores_delayed_keywords(monkeypatch, "industrial_analytics_dialog")


@pytest.mark.parametrize("uninstall", [False, True])
def test_gc_policy_does_not_retain_application(uninstall):
    run_python(f'''
        import gc
        import weakref
        from PyQt6.QtWidgets import QApplication
        from metroliza.app.gc_policy import install
        app = QApplication([])
        policy = install(app)
        reference = weakref.ref(app)
        if {uninstall!r}:
            policy.uninstall()
        gc.disable()
        del app
        assert reference() is None, 'policy kept QApplication alive'
    ''')


def test_gc_policy_rejects_mock_attribute_as_installed_policy():
    run_python('''
        from unittest.mock import MagicMock
        from metroliza.app.gc_policy import install
        try:
            install(MagicMock())
        except TypeError:
            pass
        else:
            raise AssertionError('mock attribute accepted as installed policy')
    ''')


def test_launch_ui_tears_down_after_exec_and_quit_handlers(qapplication_session, monkeypatch):
    from metroliza.app import bootstrap, gc_policy
    from metroliza.app import qt_teardown

    events = []
    app = SimpleNamespace(exec=lambda: events.extend(["quit_handlers", "exec_return"]) or 7)
    monkeypatch.setattr(bootstrap, "get_or_create_qapplication", lambda: app)
    monkeypatch.setattr(gc_policy, "install", lambda _app: None)
    monkeypatch.setattr(bootstrap, "create_startup_splash", lambda *a, **k: MagicMock())
    monkeypatch.setattr(bootstrap, "validate_license_bootstrap", lambda *_: SimpleNamespace(
        is_valid=True, days_until_expiration=7,
    ))
    monkeypatch.setattr(bootstrap, "_schedule_splash_finish_then_warmup", lambda *_: None)
    monkeypatch.setattr(qt_teardown, "shutdown_qt", lambda app: events.append("teardown"))
    result = bootstrap.launch_ui(
        bootstrap.StartupConfig(False, False, None, None, False),
        main_window_factory=lambda *_: SimpleNamespace(show=lambda: None),
    )
    assert result == 7
    assert events == ["quit_handlers", "exec_return", "teardown"]


@pytest.mark.parametrize("rejected", [False, True])
def test_industrial_progress_stub_can_dismiss(monkeypatch, rejected):
    import ast
    import sys
    from types import ModuleType

    path = Path(__file__).resolve().parents[1] / "src/metroliza/ui/industrial_analytics_dialog.py"
    tree = ast.parse(path.read_text())
    block = next(node for node in tree.body if isinstance(node, ast.Try) and any(
        isinstance(child, ast.ImportFrom) and child.module == "metroliza.ui.worker_progress_dialog"
        for child in node.body
    ))
    stub = ModuleType("metroliza.ui.worker_progress_dialog")
    stub.create_worker_progress_dialog = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, stub.__name__, stub)
    namespace = {}
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(path), "exec"), namespace)
    dialog = MagicMock()
    namespace["dismiss_worker_progress_dialog"](dialog, rejected=rejected)
    (dialog.reject if rejected else dialog.accept).assert_called_once_with()
    namespace["dismiss_worker_progress_dialog"](None)
    closed = []
    namespace["dismiss_worker_progress_dialog"](SimpleNamespace(close=lambda: closed.append(True)))
    assert closed == [True]


def test_record_install_failure_releases_before_log_and_allows_retry(
    qapplication_session, current_dialog, monkeypatch,
):
    from tests.test_modifydb_record_model import _pump

    dialog = current_dialog
    slot = dialog._record_slots[1]
    logged = []
    original = dialog._install_record_rows

    def fail_install(*_args):
        raise ValueError("synthetic install failure")

    def log(error):
        logged.append((error, slot.state, slot.progress_dialog, slot.banner.isVisibleTo(dialog)))

    monkeypatch.setattr(dialog, "_install_record_rows", fail_install)
    monkeypatch.setattr(dialog, "log_and_exit", log)
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    assert _pump(lambda: bool(logged))
    assert isinstance(logged[0][0], ValueError)
    assert logged[0][1:] == ("idle", None, False)
    assert slot.thread is None
    monkeypatch.setattr(dialog, "_install_record_rows", original)
    dialog.tab_widget.setCurrentWidget(dialog.report_records_tab)
    dialog.tab_widget.setCurrentWidget(dialog.measurement_rows_tab)
    assert _pump(lambda: slot.state == "loaded")
    assert dialog.measurement_records_table.rowCount() == 10
