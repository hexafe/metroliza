from __future__ import annotations

try:
    from modules import industrial_workers
    from modules.industrial_analytics_workflow import AnalyticsCancelled
    from modules.industrial_workers import IndustrialAnalyticsThread
except ImportError as exc:  # pragma: no cover - environment/order dependent
    industrial_workers = None
    AnalyticsCancelled = None
    IndustrialAnalyticsThread = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


def _skip_if_pyqt_unavailable() -> None:
    if PYQT_IMPORT_ERROR is not None:
        import pytest

        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")


def _capture_signal(signal, values: list[object]) -> None:
    if hasattr(signal, "connect"):
        signal.connect(values.append)
        return
    signal.emit = values.append


def test_industrial_analytics_thread_emits_cancelled_for_cancelled_workflow(
    monkeypatch,
    tmp_path,
) -> None:
    _skip_if_pyqt_unavailable()

    def raise_cancelled(**kwargs):
        cancel_check = kwargs["cancel_check"]
        assert callable(cancel_check)
        raise AnalyticsCancelled("Analytics generation was canceled.")

    monkeypatch.setattr(industrial_workers, "run_production_cache_analytics", raise_cancelled)
    thread = IndustrialAnalyticsThread(
        source_kind="production_cache",
        db_file=str(tmp_path / "production.db"),
        output_dashboard_file=str(tmp_path / "analytics.html"),
    )
    cancelled_messages: list[str] = []
    errors: list[str] = []
    results: list[object] = []
    _capture_signal(thread.cancelled, cancelled_messages)
    _capture_signal(thread.error_occurred, errors)
    _capture_signal(thread.result_ready, results)

    thread.run()

    assert cancelled_messages == ["Analytics generation was canceled."]
    assert errors == []
    assert results == []
