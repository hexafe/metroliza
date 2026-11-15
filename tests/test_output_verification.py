"""Synthetic metadata receipts at the final output publication boundaries."""

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from metroliza.shared import output_verification, safe_bugreport
from metroliza.shared.output_verification import OutputVerificationError
from metroliza.shared.safe_bugreport_context import OutputVerificationKind


@pytest.fixture
def receipts(monkeypatch):
    calls = []
    monkeypatch.setattr(safe_bugreport, "recorder", SimpleNamespace(
        record_output_verification=lambda *args, **kwargs: calls.append((args, kwargs)),
    ))
    return calls


@pytest.mark.parametrize("state,passed", [
    ("nonempty", True), ("empty", False), ("missing", False), ("directory", False),
    ("stat_error", False), ("size_stat_error", False),
])
def test_receipt_uses_only_file_metadata_and_closed_fields(tmp_path, monkeypatch, receipts, state, passed):
    target = tmp_path / "SYNTHETIC_PRIVATE_OUTPUT.xlsx"
    if state in {"nonempty", "stat_error", "size_stat_error"}:
        target.write_bytes(b"SYNTHETIC_PRIVATE_CONTENT")
    elif state == "empty":
        target.touch()
    elif state == "directory":
        target.mkdir()

    def no_content_access(*args, **kwargs):
        raise AssertionError("generated content was opened")

    monkeypatch.setattr(Path, "open", no_content_access)
    if state in {"stat_error", "size_stat_error"}:
        original_stat = Path.stat
        target_stat_calls = []

        def fail_target_stat(path, *args, **kwargs):
            if path == target:
                target_stat_calls.append(None)
                if len(target_stat_calls) >= (2 if state == "size_stat_error" else 1):
                    raise PermissionError("SYNTHETIC_PRIVATE_EXCEPTION")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", fail_target_stat)
    operation_id = uuid4()
    if passed:
        output_verification.verify_published_output(
            target, OutputVerificationKind.REPORT_WORKBOOK, operation_id=operation_id,
        )
    else:
        with pytest.raises(OutputVerificationError) as error:
            output_verification.verify_published_output(
                target, OutputVerificationKind.REPORT_WORKBOOK, operation_id=operation_id,
            )
        assert str(error.value) == "Published output file is missing or empty."
        assert error.value.__context__ is None
    assert receipts == [
        ((OutputVerificationKind.REPORT_WORKBOOK, passed), {"operation_id": operation_id}),
    ]
    assert "SYNTHETIC_PRIVATE" not in repr(receipts)


def test_only_an_actual_uuid_can_correlate_a_receipt(tmp_path, receipts):
    target = tmp_path / "output.xlsx"
    target.write_bytes(b"output")
    output_verification.verify_published_output(
        target, OutputVerificationKind.REPORT_WORKBOOK, operation_id=str(uuid4()),
    )
    assert receipts[0][1] == {"operation_id": None}


@pytest.mark.parametrize("nonempty", [True, False])
def test_recorder_failure_never_changes_file_verdict(tmp_path, monkeypatch, nonempty):
    target = tmp_path / "output.xlsx"
    target.write_bytes(b"output" if nonempty else b"")

    def fail_recorder(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE_RECORDER_ERROR")

    monkeypatch.setattr(safe_bugreport, "recorder", SimpleNamespace(
        record_output_verification=fail_recorder,
    ))
    if nonempty:
        output_verification.verify_published_output(target, OutputVerificationKind.ANALYTICS_WORKBOOK)
    else:
        with pytest.raises(OutputVerificationError, match="^Published output file is missing or empty\\.$"):
            output_verification.verify_published_output(target, OutputVerificationKind.ANALYTICS_WORKBOOK)


@dataclass(frozen=True)
class _WorkbookResult:
    output_file: str


def _analytics_boundary(monkeypatch, target, boundary, payload, *, cancel_check=None):
    from metroliza.industrial import industrial_analytics_workflow as workflow

    if boundary == "dashboard":
        monkeypatch.setattr(workflow, "build_production_dashboard_manifest", lambda **kwargs: {})

        def write_dashboard(manifest, output_file, **kwargs):
            if payload is not None:
                Path(output_file).write_bytes(payload)
            return {"html_dashboard_path": str(output_file)}

        monkeypatch.setattr(workflow, "write_production_dashboard", write_dashboard)
        return lambda: workflow._write_dashboard(
            frame=SimpleNamespace(index=()), metrics=(), aggregation=None, aggregated=None, groupstats=None,
            charts=None, cohort=None, diagnostics=(), output_dashboard_file=str(target),
            dashboard_title="", dashboard_subtitle="", cancel_check=cancel_check,
        )

    def write_workbook(*, output_file, **kwargs):
        if payload is not None:
            Path(output_file).write_bytes(payload)
        return _WorkbookResult(str(output_file))

    kwargs = dict(
        output_workbook_file=str(target), dataframe=None, aggregation_result=None,
        groupstats_result=None, diagnostics=(), separate_parameter_sheets=False,
        chart_selection=None, group_fields=(), cancel_check=cancel_check,
    )
    if boundary == "production":
        from metroliza.industrial import industrial_analytics_workbook as workbook
        monkeypatch.setattr(workbook, "export_production_analytics_workbook", write_workbook)
        return lambda: workflow._export_production_workbook_with_temp(metric_selection=(), **kwargs)
    monkeypatch.setattr(workflow, "export_tabular_analytics_workbook", write_workbook)
    return lambda: workflow._export_tabular_workbook_with_temp(metric_candidates=(), **kwargs)


@pytest.mark.parametrize("boundary", ["dashboard", "production", "tabular"])
@pytest.mark.parametrize("payload", [None, b""])
def test_invalid_staged_analytics_preserves_last_complete_output(tmp_path, monkeypatch, receipts, boundary, payload):
    target = tmp_path / ("output.html" if boundary == "dashboard" else "output.xlsx")
    target.write_bytes(b"previous complete output")
    publish = _analytics_boundary(monkeypatch, target, boundary, payload)
    with pytest.raises(OutputVerificationError):
        publish()
    assert target.read_bytes() == b"previous complete output"
    assert not list(tmp_path.glob(".metroliza-analytics-*"))
    assert receipts == []


@pytest.mark.parametrize("boundary", ["dashboard", "production", "tabular"])
def test_analytics_records_final_target_after_atomic_replace(tmp_path, monkeypatch, receipts, boundary):
    target = tmp_path / ("output.html" if boundary == "dashboard" else "output.xlsx")
    publish = _analytics_boundary(monkeypatch, target, boundary, b"complete output")
    seen = []
    original_verify = output_verification.verify_published_output

    def verify(path, kind, **kwargs):
        assert path == target
        assert target.read_bytes() == b"complete output"
        assert not list(tmp_path.glob(".metroliza-analytics-*"))
        seen.append(path)
        return original_verify(path, kind, **kwargs)

    from metroliza.industrial import industrial_analytics_workflow as workflow
    monkeypatch.setattr(workflow, "verify_published_output", verify)
    result = publish()
    assert seen == [target]
    result_path = result["html_dashboard_path"] if boundary == "dashboard" else result.output_file
    assert result_path == str(target)
    kind = (OutputVerificationKind.ANALYTICS_DASHBOARD if boundary == "dashboard"
            else OutputVerificationKind.ANALYTICS_WORKBOOK)
    assert receipts == [((kind, True), {"operation_id": None})]


@pytest.mark.parametrize("boundary", ["dashboard", "production", "tabular"])
def test_analytics_final_target_failure_cannot_return_success(tmp_path, monkeypatch, receipts, boundary):
    target = tmp_path / ("output.html" if boundary == "dashboard" else "output.xlsx")
    publish = _analytics_boundary(monkeypatch, target, boundary, b"complete output")

    def lose_publication(path, destination):
        path.unlink()
        return Path(destination)

    monkeypatch.setattr(Path, "replace", lose_publication)
    with pytest.raises(OutputVerificationError):
        publish()
    assert not target.exists()
    assert len(receipts) == 1
    assert receipts[0][0][1] is False


@pytest.mark.parametrize("boundary", ["dashboard", "production", "tabular"])
def test_analytics_cancel_precedes_empty_staging_verification(tmp_path, monkeypatch, receipts, boundary):
    from metroliza.industrial.industrial_analytics_workflow import AnalyticsCancelled

    target = tmp_path / ("output.html" if boundary == "dashboard" else "output.xlsx")
    target.write_bytes(b"previous complete output")
    calls = []

    def cancel_after_writer():
        calls.append(None)
        return len(calls) >= (2 if boundary == "dashboard" else 1)

    publish = _analytics_boundary(monkeypatch, target, boundary, b"", cancel_check=cancel_after_writer)
    with pytest.raises(AnalyticsCancelled):
        publish()
    assert target.read_bytes() == b"previous complete output"
    assert not list(tmp_path.glob(".metroliza-analytics-*"))
    assert receipts == []


@pytest.mark.parametrize("target_kind", ["excel_xlsx", "google_sheets_drive_convert"])
@pytest.mark.parametrize("state", ["missing", "empty", "cancelled", "nonempty"])
def test_report_receipt_gates_published_stage_and_cloud_conversion(
    tmp_path, monkeypatch, receipts, target_kind, state,
):
    from metroliza.exporting import export_data_thread as export
    from metroliza.exporting.export_outcomes import ExportArtifactStatus, ExportRunStatus
    from metroliza.shared import workflow_diagnostics
    from metroliza.shared.diagnostic_events import WorkflowStage

    target = tmp_path / "report.xlsx"
    if state in {"empty", "nonempty"}:
        target.write_bytes(b"workbook" if state == "nonempty" else b"")
    stages, terminal, errors, completed, conversions = [], [], [], [], []
    operation_id = uuid4()
    trace = SimpleNamespace(
        operation_id=operation_id, stage=stages.append,
        finish_export=lambda **kwargs: terminal.append(kwargs),
    )
    monkeypatch.setattr(workflow_diagnostics, "start_workflow_trace", lambda operation: trace)
    monkeypatch.setattr(export, "sqlite_connection_scope", lambda path: nullcontext(None))
    monkeypatch.setattr(export, "ensure_report_schema", lambda *args, **kwargs: None)
    monkeypatch.setattr(export.QCoreApplication, "processEvents", lambda: None)

    def convert(*args, **kwargs):
        conversions.append(None)
        return SimpleNamespace(warnings=(), fallback_message="", web_url="https://example.invalid/sheet", file_id="")

    monkeypatch.setattr(export, "upload_and_convert_workbook", convert)
    monkeypatch.setattr(export, "build_google_conversion_metadata", lambda result: {"converted_url": result.web_url})
    worker = SimpleNamespace(
        db_file="unused", excel_file=str(target), _primary_output_file=str(target), export_target=target_kind,
        completion_metadata={}, export_canceled=False, export_run_result=None, _export_failure=None,
        _check_canceled=lambda: False, _ensure_chart_executor=lambda: None,
        _prepare_export_snapshot=lambda: None, _emit_stage_progress=lambda *args: None,
        update_label=SimpleNamespace(emit=lambda *args: None),
        _log_export_stage=lambda *args, **kwargs: None,
        _emit_google_stage=lambda *args, **kwargs: None,
        get_export_backend=lambda: SimpleNamespace(run=lambda thread: state != "cancelled"),
        _observe_export_failure_stage=lambda *args, **kwargs: None,
        _build_expected_sheet_names=lambda: (),
        _update_completion_chart_telemetry=lambda: None,
        _write_html_dashboard_if_requested=lambda: None,
        _cleanup_export_resources=lambda: None,
        error_occurred=SimpleNamespace(emit=lambda message: None),
        completed=SimpleNamespace(emit=lambda: completed.append(None)),
    )

    def log_and_exit(error):
        errors.append(error)
        export.ExportDataThread.log_and_exit(worker, error)

    worker.log_and_exit = log_and_exit
    worker._set_export_run_result = lambda **kwargs: export.ExportDataThread._set_export_run_result(worker, **kwargs)
    export.ExportDataThread.run(worker)
    if state == "nonempty":
        assert WorkflowStage.OUTPUT_PUBLISHED in stages
        assert not errors
        assert completed == [None]
        assert terminal[0]["completed"] is True
        assert worker.export_run_result.status is ExportRunStatus.COMPLETE
        assert conversions == ([None] if target_kind == "google_sheets_drive_convert" else [])
    else:
        assert WorkflowStage.OUTPUT_PUBLISHED not in stages
        assert not completed
        assert not conversions
        assert terminal[0]["completed"] is False
        assert terminal[0]["cancelled"] is (state == "cancelled")
        assert len(errors) == (0 if state == "cancelled" else 1)
        if errors:
            assert isinstance(errors[0], OutputVerificationError)
            assert worker.export_run_result.status is ExportRunStatus.FAILED
            workbook = next(item for item in worker.export_run_result.artifacts if item.artifact_id == "workbook")
            assert workbook.status is ExportArtifactStatus.FAILED
            assert workbook.location == ""
    assert receipts == ([] if state == "cancelled" else [
        ((OutputVerificationKind.REPORT_WORKBOOK, state == "nonempty"), {"operation_id": operation_id}),
    ])
