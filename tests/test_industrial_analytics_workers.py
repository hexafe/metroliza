from __future__ import annotations

import pandas as pd

try:
    from modules import industrial_workers
    from modules.industrial_analytics_workflow import AnalyticsCancelled
    from modules.industrial_workers import IndustrialAnalyticsThread
    from modules.tabular_analytics_service import TabularAnalyticsLoadResult, TabularColumnFilter
except ImportError as exc:  # pragma: no cover - environment/order dependent
    industrial_workers = None
    AnalyticsCancelled = None
    IndustrialAnalyticsThread = None
    TabularAnalyticsLoadResult = None
    TabularColumnFilter = None
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


def test_industrial_analytics_thread_rejects_unknown_source_kind(tmp_path) -> None:
    _skip_if_pyqt_unavailable()
    import pytest

    with pytest.raises(ValueError, match="Unsupported analytics source kind"):
        IndustrialAnalyticsThread(
            source_kind="unknown",
            output_dashboard_file=str(tmp_path / "analytics.html"),
        )


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


def test_industrial_analytics_thread_relays_workflow_status_updates(
    monkeypatch,
    tmp_path,
) -> None:
    _skip_if_pyqt_unavailable()

    result = object()

    def emit_progress(**kwargs):
        progress_callback = kwargs["progress_callback"]
        assert callable(progress_callback)
        progress_callback("Loading production data...\nReading cached rows (1/5)\nETA --")
        return result

    monkeypatch.setattr(industrial_workers, "run_production_cache_analytics", emit_progress)
    thread = IndustrialAnalyticsThread(
        source_kind="production_cache",
        db_file=str(tmp_path / "production.db"),
        output_dashboard_file=str(tmp_path / "analytics.html"),
    )
    labels: list[str] = []
    results: list[object] = []
    errors: list[str] = []
    _capture_signal(thread.update_label, labels)
    _capture_signal(thread.result_ready, results)
    _capture_signal(thread.error_occurred, errors)

    thread.run()

    assert labels == ["Loading production data...\nReading cached rows (1/5)\nETA --"]
    assert results == [result]
    assert errors == []


def test_industrial_analytics_thread_passes_tabular_grouping_to_workflow(
    monkeypatch,
    tmp_path,
) -> None:
    _skip_if_pyqt_unavailable()

    result = object()
    grouping_df = pd.DataFrame({"REPORT_ID": [1], "GROUP": ["POPULATION"]})
    tabular_load_result = TabularAnalyticsLoadResult(
        dataframe=pd.DataFrame({"length_mm": [10.0]}),
        metric_candidates=(),
    )
    captured = {}

    def run_tabular(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(industrial_workers, "run_tabular_file_analytics", run_tabular)
    thread = IndustrialAnalyticsThread(
        source_kind="tabular_file",
        input_file=str(tmp_path / "table.csv"),
        output_dashboard_file=str(tmp_path / "analytics.html"),
        grouping_df=grouping_df,
        tabular_load_result=tabular_load_result,
        tabular_filter_columns=("tracecode",),
        tabular_filter_keys=(("TC-001",),),
        tabular_column_filters=(TabularColumnFilter("line", selected_values=("L1",)),),
        dashboard_detail_mode="full",
        sheet_name="Measurements",
        timestamp_column="time_stamp",
        reference_column="reference_id",
    )
    results: list[object] = []
    errors: list[str] = []
    _capture_signal(thread.result_ready, results)
    _capture_signal(thread.error_occurred, errors)

    thread.run()

    assert results == [result]
    assert errors == []
    assert captured["grouping_df"] is not grouping_df
    assert captured["grouping_df"].equals(grouping_df)
    assert captured["tabular_load_result"] is tabular_load_result
    assert captured["tabular_filter_columns"] == ("tracecode",)
    assert captured["tabular_filter_keys"] == (("TC-001",),)
    assert captured["tabular_column_filters"] == (TabularColumnFilter("line", selected_values=("L1",)),)
    assert captured["dashboard_detail_mode"] == "full"
    assert captured["sheet_name"] == "Measurements"
    assert captured["timestamp_column"] == "time_stamp"
    assert captured["reference_column"] == "reference_id"
