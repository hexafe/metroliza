"""Closed export failures retain one identity through UI and managed incidents."""

import json
import uuid
import time
from dataclasses import replace

import pytest

from metroliza.shared.diagnostic_events import (
    DiagnosticEventValidationError, ExceptionKind, ExportFailureBackend,
    ExportFailureCode, ExportFailureStage, WorkflowDiagnosticEvent, WorkflowError,
    WorkflowOperation, WorkflowOutcome, WorkflowStage, build_export_failure_diagnostic,
    export_failure_payload,
)
from metroliza.shared.diagnostic_wire import decode_event, encode_event, WireValidationError
from metroliza.exporting.export_outcomes import (
    ExportRunStatus, build_export_run_message, derive_export_run_result,
    format_export_diagnostics, sanitize_export_diagnostics,
)


PRIVATE = "C:/CUSTOMER_REPORT/MEASUREMENT_token=SECRET"


def _failure(exc=None, stage=ExportFailureStage.HTML_WRITE):
    return build_export_failure_diagnostic(
        exc if exc is not None else PermissionError(13, PRIVATE),
        invocation_id=uuid.uuid4(), operation_id=uuid.uuid4(), stage=stage,
        backend=ExportFailureBackend.HTML,
    )


def _event(failure=None):
    failure = failure or _failure()
    return WorkflowDiagnosticEvent(
        failure.invocation_id, failure.operation_id, 2, WorkflowOperation.LOCAL_EXPORT,
        WorkflowStage.FINISHED, WorkflowOutcome.FAILED, error=WorkflowError.OUTPUT_FAILED,
        export_failure=failure,
    )


def test_original_exception_and_os_codes_are_closed_without_payload():
    failure = _failure()
    assert failure.exception.exception_kind is ExceptionKind.PERMISSION_ERROR
    assert failure.code is ExportFailureCode.ACCESS_DENIED
    assert failure.errno == 13
    assert failure.winerror is None
    assert failure.recorder_connected is False
    assert PRIVATE not in json.dumps(export_failure_payload(failure))
    assert _failure(OSError(36, PRIVATE)).code is ExportFailureCode.PATH_TOO_LONG


def test_hostile_exception_attributes_text_and_subclass_identity_are_never_used():
    class CustomerSecretError(PermissionError):
        def __getattribute__(self, name):
            raise AssertionError("descriptor executed")

        def __str__(self):
            raise AssertionError("str executed")

        def __repr__(self):
            raise AssertionError("repr executed")

    failure = _failure(CustomerSecretError(13, PRIVATE))
    assert failure.exception.exception_kind is ExceptionKind.UNKNOWN_EXCEPTION
    assert failure.errno is None
    assert PRIVATE not in json.dumps(export_failure_payload(failure))


def test_wrapped_chained_grouped_and_cyclic_exceptions_stay_truthful_and_bounded():
    original = PermissionError(13, PRIVATE)
    wrapped = RuntimeError(PRIVATE)
    wrapped.__cause__ = original
    failure = _failure(wrapped)
    assert failure.exception.exception_kind is ExceptionKind.RUNTIME_ERROR
    assert failure.cause_kind is ExceptionKind.PERMISSION_ERROR
    assert failure.exception.cause_count == 1
    wrapped.__cause__ = wrapped
    cyclic = _failure(wrapped)
    assert cyclic.exception.structure_truncated
    assert cyclic.cause_kind is ExceptionKind.UNKNOWN_EXCEPTION
    group = ExceptionGroup(PRIVATE, [ValueError(PRIVATE) for _ in range(100)])
    bounded = _event(_failure(group))
    assert bounded.export_failure.exception.structure_truncated
    assert len(encode_event(bounded)) < 4096
    assert PRIVATE.encode() not in encode_event(bounded)


@pytest.mark.parametrize("field,value", [
    ("stage", "customer_stage"), ("code", "private_reason"), ("backend", "private_backend"),
    ("cause_kind", "CustomerSecretError"), ("errno", True), ("winerror", 65536),
    ("operation_id", "not-a-uuid"), ("extra", PRIVATE), ("recorder_connected", "yes"),
])
def test_nested_wire_rejects_unknown_values_and_extra_fields(field, value):
    payload = json.loads(encode_event(_event()))
    payload["export_failure"][field] = value
    with pytest.raises(WireValidationError):
        decode_event(json.dumps(payload, separators=(",", ":")).encode())


def test_record_identity_and_terminal_state_are_validated_again_at_sink():
    event = _event()
    with pytest.raises(DiagnosticEventValidationError):
        replace(event, operation_id=uuid.uuid4())
    with pytest.raises(DiagnosticEventValidationError):
        replace(event, outcome=WorkflowOutcome.COMPLETED, error=WorkflowError.NONE)
    failure = event.export_failure
    object.__setattr__(failure, "stage", "customer_stage")
    with pytest.raises(WireValidationError):
        encode_event(event)


def test_v1_wire_without_nested_failure_keeps_exact_original_shape():
    event = replace(_event(), export_failure=None)
    old = encode_event(event)
    assert "export_failure" not in json.loads(old)
    assert encode_event(decode_event(old)) == old


def test_same_record_reaches_result_human_copy_ring_incident_store_and_viewer(tmp_path, qapplication_session):
    from metroliza.shared.diagnostic_incident import (
        ChannelState, HandshakeState, IncidentObservation, LaunchState,
        TerminationState, build_incident, decode_incident, encode_incident,
    )
    from metroliza.shared.diagnostic_ring import DiagnosticRing
    from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus
    from metroliza.ui.incident_dialog import IncidentDialog

    failure = _failure()
    result = derive_export_run_result(
        excel_file=tmp_path / "report.html", export_target="html_dashboard",
        completion_metadata={"export_failure": failure}, terminal_failure="failed",
    )
    assert result.failure_diagnostic is failure
    details = format_export_diagnostics(result)
    assert sanitize_export_diagnostics(details) == details
    assert PRIVATE not in details
    assert failure.exception.correlation_id.hex in details
    assert "Access was denied" in build_export_run_message(result)[2]
    assert "html write" in build_export_run_message(result)[2]
    ring = DiagnosticRing()
    wire = encode_event(_event(failure))
    assert ring.add(wire, 0.0)
    observation = IncidentObservation(
        launch=LaunchState.STARTED, handshake=HandshakeState.ACCEPTED,
        channel=ChannelState.COMPLETE, exit_code=1, termination=TerminationState.OBSERVED_EXIT,
        clean_terminal_received=True, source_dropped=0, source_loss_known=True, elapsed_ms=25,
    )
    incident = build_incident(
        session_id=failure.invocation_id, report_id=uuid.uuid4(), created_at_ms=time.time_ns() // 1_000_000,
        build_git_sha="unknown", observation=observation, history=ring.snapshot(0.0),
    )
    encoded = encode_incident(incident)
    assert encode_incident(decode_incident(encoded)) == encoded
    store = IncidentStore(tmp_path / "incidents")
    assert store.publish(incident).status is StoreStatus.SAVED
    loaded = store.load(incident.report_id).incident
    event = decode_event(loaded.events[0])
    assert export_failure_payload(event.export_failure) == export_failure_payload(failure)
    dialog = IncidentDialog(store=store)
    try:
        assert failure.exception.correlation_id.hex in "\n".join(dialog._latest_event_lines([event]))
    finally:
        dialog.close()
    assert qapplication_session is not None


def test_details_and_copy_use_identical_validated_record(monkeypatch, tmp_path):
    import metroliza.ui.export_dialog as ui

    captured = {}
    class Dialog:
        def exec(self):
            return None
    monkeypatch.setattr(ui, "QMessageBox", lambda parent: Dialog())
    monkeypatch.setattr(ui, "_configure_export_result_dialog", lambda dialog, **kw: captured.update(details=kw["diagnostics"]))
    monkeypatch.setattr(ui, "_add_export_result_actions", lambda *args, **kw: (None, None))
    monkeypatch.setattr(ui, "_connect_export_result_links", lambda *args, **kw: None)
    monkeypatch.setattr(ui, "_handle_export_result_action", lambda dialog, **kw: captured.update(copy=kw["diagnostics"]))
    result = derive_export_run_result(excel_file=tmp_path / "report.html", export_target="html_dashboard",
                                     completion_metadata={"export_failure": _failure()}, terminal_failure="failed")
    ui.show_export_result_message(None, "error", "Export failed", "Export failed", diagnostics=format_export_diagnostics(result))
    assert captured["details"] == captured["copy"] == format_export_diagnostics(result)


@pytest.mark.parametrize("html_only", [True, False])
@pytest.mark.parametrize("stage", [ExportFailureStage.PNG_WRITE, ExportFailureStage.PLOTLY_JSON,
                                  ExportFailureStage.HTML_WRITE, ExportFailureStage.ASSET_PUBLICATION,
                                  ExportFailureStage.HTML_PUBLICATION])
def test_worker_captures_actual_failure_before_wrapper_and_keeps_usable_workbook(monkeypatch, tmp_path, html_only, stage):
    from metroliza.exporting import export_data_thread as module
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.shared.workflow_diagnostics import start_workflow_trace

    target = "html_dashboard" if html_only else "excel_xlsx"
    worker = module.ExportDataThread(ExportRequest(
        AppPaths(str(tmp_path / "data.sqlite"), None if html_only else str(tmp_path / "out.xlsx"),
                 str(tmp_path / "out.html") if html_only else None),
        ExportOptions(export_target=target, generate_html_dashboard=True),
    ))
    worker._export_diagnostic_trace = start_workflow_trace(WorkflowOperation.LOCAL_EXPORT)
    worker.completion_metadata["local_export_outcome"] = "completed"
    original = PermissionError(13, PRIVATE)
    def fail(writer, **kwargs):
        kwargs["diagnostic_stage"](stage)
        raise original
    monkeypatch.setattr(module, "write_dashboard_safely", fail)
    if html_only:
        with pytest.raises(RuntimeError) as wrapped:
            worker._write_html_dashboard_if_requested()
        worker.log_and_exit(wrapped.value)
    else:
        worker._write_html_dashboard_if_requested()
        worker._set_export_run_result()
    failure = worker.export_run_result.failure_diagnostic
    assert failure is worker._export_failure
    assert failure.stage is stage
    assert failure.exception.exception_kind is ExceptionKind.PERMISSION_ERROR
    worker._observe_export_failure_stage(ExportFailureStage.CLEANUP, ValueError(PRIVATE))
    assert worker._export_failure is failure
    expected = ExportRunStatus.FAILED if html_only else ExportRunStatus.COMPLETE_WITH_OMISSIONS
    assert worker.export_run_result.status is expected
    if not html_only:
        assert any(a.artifact_id == "workbook" and a.status.value == "complete" for a in worker.export_run_result.artifacts)
    assert PRIVATE not in format_export_diagnostics(worker.export_run_result)


@pytest.mark.parametrize("seam,stage", [
    ("png", ExportFailureStage.PNG_WRITE),
    ("spec", ExportFailureStage.PLOTLY_SPEC),
    ("json", ExportFailureStage.PLOTLY_JSON),
    ("html", ExportFailureStage.HTML_WRITE),
    ("assets", ExportFailureStage.ASSET_PUBLICATION),
    ("publish", ExportFailureStage.HTML_PUBLICATION),
])
def test_real_writer_and_publication_seams_capture_original_before_cleanup(monkeypatch, tmp_path, seam, stage):
    from pathlib import Path
    from metroliza.charts import export_html_dashboard as html
    from metroliza.exporting import output_publication as publication
    from metroliza.exporting import export_data_thread as module
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest

    worker = module.ExportDataThread(ExportRequest(
        AppPaths(str(tmp_path / "data.sqlite"), html_dashboard_file=str(tmp_path / "out.html")),
        ExportOptions(export_target="html_dashboard", generate_html_dashboard=True),
    ))
    worker._html_dashboard_sections = [{"header": PRIVATE, "charts": [{"image_buffer": b"PNG", "payload": {}}]}]
    original = PermissionError(13, PRIVATE)
    def fail(*args, **kwargs):
        raise original
    if seam in ("png", "html"):
        monkeypatch.setattr(Path, "write_bytes" if seam == "png" else "write_text", fail)
    else:
        owner, name = {
            "spec": (html, "_build_plotly_chart_spec_bundle"),
            "json": (html, "_measure_plotly_specs_json_bytes"),
            "assets": (publication, "_move_dashboard_assets"),
            "publish": (publication, "publish_output"),
        }[seam]
        monkeypatch.setattr(owner, name, fail)
    with pytest.raises(RuntimeError) as caught:
        worker._write_html_dashboard_if_requested()
    assert caught.value.__cause__ is original
    assert worker._export_failure.stage is stage
    assert worker._export_failure.exception.exception_kind is ExceptionKind.PERMISSION_ERROR
    assert not (tmp_path / "out.html").exists()
    assert not list(tmp_path.glob(".metroliza-export-*"))


def test_managed_trace_keeps_identical_record_and_logger_failure_is_nonfatal(caplog, monkeypatch):
    import logging
    from metroliza.shared.workflow_diagnostics import start_workflow_trace

    caplog.set_level(logging.INFO)
    trace = start_workflow_trace(WorkflowOperation.LOCAL_EXPORT)
    failure = build_export_failure_diagnostic(
        ValueError(PRIVATE), invocation_id=trace.invocation_id, operation_id=trace.operation_id,
        stage=ExportFailureStage.PLOTLY_JSON, backend=ExportFailureBackend.HTML,
    )
    trace.finish_export(completed=False, cancelled=False, export_failure=failure)
    events = [record.msg for record in caplog.records if type(record.msg) is WorkflowDiagnosticEvent]
    assert events[-1].export_failure is failure
    assert decode_event(encode_event(events[-1])).export_failure == failure
    def fail(*args, **kwargs):
        raise RuntimeError(PRIVATE)
    monkeypatch.setattr(logging.getLogger("metroliza.shared.workflow_diagnostics"), "log", fail)
    broken = start_workflow_trace(WorkflowOperation.LOCAL_EXPORT)
    assert broken.finish_export(completed=False, cancelled=False) is None


def test_invalid_or_smuggled_rendered_failures_fail_closed(tmp_path):
    result = derive_export_run_result(excel_file=tmp_path / "out.html", export_target="html_dashboard",
                                     completion_metadata={"export_failure": _failure()}, terminal_failure="failed")
    canonical = format_export_diagnostics(result).splitlines()[-1]
    for bad in (canonical + PRIVATE, canonical.replace('"html_write"', '"customer_stage"'),
                canonical.replace('"errno":13', '"errno":true')):
        safe = sanitize_export_diagnostics(bad)
        assert "export_failure:" not in safe
        assert PRIVATE not in safe
        assert "customer_stage" not in safe


def test_primary_failure_survives_cleanup_failure_and_all_cleanup_runs(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from metroliza.exporting import export_data_thread as module
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest

    output = tmp_path / "out.html"
    output.write_text("previous complete output")
    worker = module.ExportDataThread(ExportRequest(
        AppPaths(str(tmp_path / "data.sqlite"), html_dashboard_file=str(output)),
        ExportOptions(export_target="html_dashboard", generate_html_dashboard=True),
    ))
    original = PermissionError(13, PRIVATE)
    def fail_backend(thread):
        raise original
    def fail_cleanup():
        raise ValueError(PRIVATE)
    monkeypatch.setattr(worker, "_ensure_chart_executor", lambda: None)
    monkeypatch.setattr(worker, "_prepare_export_snapshot", lambda: None)
    monkeypatch.setattr(worker, "get_export_backend", lambda: SimpleNamespace(run=fail_backend))
    monkeypatch.setattr(worker, "_cleanup_export_snapshot", fail_cleanup)
    cleaned = []
    for name in ("_shutdown_chart_executor", "_shutdown_summary_prep_executor",
                 "_cleanup_chart_images", "_cleanup_dashboard_payloads"):
        monkeypatch.setattr(worker, name, lambda name=name: cleaned.append(name))
    errors, completions = [], []
    worker.error_occurred.connect(errors.append)
    worker.completed.connect(lambda: completions.append(True))
    worker.run()
    assert len(cleaned) == 4
    assert len(errors) == 1
    assert not completions
    assert worker.export_run_result.status is ExportRunStatus.FAILED
    assert worker._export_failure.exception.exception_kind is ExceptionKind.PERMISSION_ERROR
    assert worker._export_failure.stage is ExportFailureStage.LOCAL_OUTPUT
    assert output.read_text() == "previous complete output"
    assert PRIVATE not in errors[0]


def test_diagnostic_capture_and_logger_failure_do_not_replace_export_result(monkeypatch, tmp_path):
    from metroliza.exporting import export_data_thread as module
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest

    worker = module.ExportDataThread(ExportRequest(
        AppPaths(str(tmp_path / "data.sqlite"), str(tmp_path / "out.xlsx")), ExportOptions(),
    ))
    def fail(*args, **kwargs):
        raise RuntimeError(PRIVATE)
    monkeypatch.setattr(module, "build_export_failure_diagnostic", fail)
    monkeypatch.setattr(module.custom_logger, "handle_exception", fail)
    errors = []
    worker.error_occurred.connect(errors.append)
    worker.log_and_exit(PermissionError(13, PRIVATE))
    assert worker.export_run_result.status is ExportRunStatus.FAILED
    assert worker.export_run_result.failure_diagnostic is None
    assert len(errors) == 1 and "capture is unavailable" in errors[0]
    assert PRIVATE not in errors[0]


def test_legacy_token_shaped_private_values_and_partial_attributes_are_redacted():
    for text in ("dashboard-1: stage=PRIVATE_STAGE; code=PRIVATE_CODE; chart=PRIVATE_LABEL",
                 "dashboard-1: stage=html_write/private; code=output_access_denied#private"):
        assert sanitize_export_diagnostics(text) == "dashboard-1: detail=redacted"


def _copy_retry_worker(tmp_path, html_only):
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest

    original = tmp_path / ("out.html" if html_only else "out.xlsx")
    original.write_bytes(b"previous complete output")
    candidate = tmp_path / ("out (2).html" if html_only else "out (2).xlsx")
    if not html_only:
        candidate.write_bytes(b"completed copy workbook")
    worker = ExportDataThread(ExportRequest(
        AppPaths(str(tmp_path / "data.sqlite"), None if html_only else str(candidate),
                 str(candidate) if html_only else None),
        ExportOptions(export_target="html_dashboard" if html_only else "excel_xlsx",
                      generate_html_dashboard=True),
        copy_output_from=str(original),
    ))
    worker.completion_metadata["local_export_outcome"] = "completed"
    return worker, original


@pytest.mark.parametrize("html_only,with_previous_failure", [(True, False), (False, False), (False, True)])
@pytest.mark.parametrize("second_attempt", ["denied", "success", "cancelled"])
def test_copy_retry_discards_handled_collision_before_observing_next_attempt(
    monkeypatch, tmp_path, html_only, with_previous_failure, second_attempt,
):
    from pathlib import Path
    from metroliza.exporting import output_publication as publication

    worker, original = _copy_retry_worker(tmp_path, html_only)
    previous_failure = None
    if with_previous_failure:
        previous_failure = _failure(TypeError(PRIVATE), ExportFailureStage.PLOTLY_SPEC)
        worker._export_failure = previous_failure
        worker.completion_metadata.update({
            "export_failure": previous_failure, "summary_sheet_requested": True,
            "summary_sheet_warnings": ["A previous summary chart was omitted."],
        })
    publish_new = publication._publish_new_output
    calls = []
    denied = PermissionError(13, PRIVATE)
    def race_then_publish(temporary, target):
        calls.append(Path(target))
        if len(calls) == 1:
            target.write_text("complete competing output")
        elif second_attempt == "denied":
            raise denied
        elif second_attempt == "cancelled":
            raise publication.OutputPublicationCanceled()
        return publish_new(temporary, target)
    monkeypatch.setattr(publication, "_publish_new_output", race_then_publish)
    if second_attempt == "denied" and html_only:
        with pytest.raises(RuntimeError) as caught:
            worker._write_html_dashboard_if_requested()
        assert caught.value.__cause__.__cause__ is denied
        worker.log_and_exit(caught.value)
    elif second_attempt == "cancelled":
        with pytest.raises(publication.OutputPublicationCanceled):
            worker._write_html_dashboard_if_requested()
        worker._set_export_run_result(cancelled=True)
    else:
        worker._write_html_dashboard_if_requested()
        worker._set_export_run_result()
    assert len(calls) == 2 and calls[0] != calls[1]
    assert calls[0].read_text() == "complete competing output"
    assert original.read_bytes() == b"previous complete output"
    assert not list(tmp_path.glob(".metroliza-export-*"))
    result = worker.export_run_result
    if second_attempt == "denied":
        failure = result.failure_diagnostic
        assert failure is worker._export_failure
        if previous_failure is None:
            assert failure.exception.exception_kind is ExceptionKind.PERMISSION_ERROR
            assert failure.cause_kind is ExceptionKind.PERMISSION_ERROR
            assert failure.code is ExportFailureCode.ACCESS_DENIED
            assert failure.stage is ExportFailureStage.HTML_PUBLICATION
        else:
            assert failure is previous_failure
        expected = ExportRunStatus.FAILED if html_only else ExportRunStatus.COMPLETE_WITH_OMISSIONS
        assert result.status is expected
        assert not calls[1].exists()
    elif second_attempt == "success":
        expected = ExportRunStatus.COMPLETE if previous_failure is None else ExportRunStatus.COMPLETE_WITH_OMISSIONS
        assert result.status is expected
        assert result.failure_diagnostic is previous_failure
        assert worker._export_failure is previous_failure
        assert worker.completion_metadata.get("export_failure") is previous_failure
        assert calls[1].is_file()
    else:
        assert result.status is ExportRunStatus.CANCELLED
        assert result.failure_diagnostic is previous_failure
        assert worker._export_failure is previous_failure
        assert not calls[1].exists()
    if not html_only:
        assert Path(worker.excel_file).read_bytes() == b"completed copy workbook"
        assert any(artifact.artifact_id == "workbook" and artifact.status.value == "complete"
                   for artifact in result.artifacts)


def test_error_after_successful_html_validation_does_not_claim_output_missing(monkeypatch, tmp_path):
    from pathlib import Path

    worker, _original = _copy_retry_worker(tmp_path, True)
    original = ValueError(PRIVATE)
    log_stage = worker._log_export_stage
    def fail_after_validation(message, **kwargs):
        if kwargs.get("stage") == "dashboard_completed":
            raise original
        return log_stage(message, **kwargs)
    monkeypatch.setattr(worker, "_log_export_stage", fail_after_validation)
    with pytest.raises(ValueError) as caught:
        worker._write_html_dashboard_if_requested()
    assert caught.value is original
    assert Path(worker.html_dashboard_file).is_file()
    worker.log_and_exit(caught.value)
    failure = worker.export_run_result.failure_diagnostic
    assert failure.exception.exception_kind is ExceptionKind.VALUE_ERROR
    assert failure.stage is ExportFailureStage.UNKNOWN
    assert failure.code is ExportFailureCode.UNEXPECTED


@pytest.mark.parametrize("fail_width", [True, False])
def test_column_width_failure_rethrows_through_real_caller_and_finishes_failed(monkeypatch, tmp_path, caplog, fail_width):
    import logging
    from types import SimpleNamespace
    from metroliza.exporting.execution import ExportStageOutcome

    worker, _original = _copy_retry_worker(tmp_path, False)
    worker.generate_html_dashboard = False
    worker.completion_metadata["html_dashboard_requested"] = False
    original = PermissionError(13, PRIVATE)
    class Value:
        def __str__(self):
            if fail_width:
                raise original
            return "Synthetic"
    class Table:
        columns = ["synthetic"]
        shape = (1, 1)
        def __getitem__(self, key):
            return [Value()]
    widths = []
    worksheet = SimpleNamespace(
        autofilter=lambda *args: None, freeze_panes=lambda *args: None,
        set_column=lambda first, last, width: widths.append(width),
    )
    def run_backend(thread):
        thread.write_data_to_excel(Table(), "Synthetic", object())
        return ExportStageOutcome.completed()
    backend = SimpleNamespace(run=run_backend, list_sheet_names=lambda writer: set(),
                              write_dataframe=lambda *args: None, get_worksheet=lambda *args: worksheet)
    monkeypatch.setattr(worker, "get_export_backend", lambda: backend)
    monkeypatch.setattr(worker, "_ensure_chart_executor", lambda: None)
    monkeypatch.setattr(worker, "_prepare_export_snapshot", lambda: None)
    monkeypatch.setattr(worker, "_write_html_dashboard_if_requested", lambda: None)
    caplog.set_level(logging.INFO, logger="metroliza.shared.workflow_diagnostics")
    completed = []
    worker.completed.connect(lambda: completed.append(True))
    worker.run()
    terminal = [record.msg for record in caplog.records
                if type(record.msg) is WorkflowDiagnosticEvent and record.msg.stage is WorkflowStage.FINISHED]
    assert len(terminal) == 1
    if fail_width:
        assert not widths
        assert not completed
        assert worker.export_run_result.status is ExportRunStatus.FAILED
        assert terminal[0].outcome is WorkflowOutcome.FAILED
        assert terminal[0].export_failure is worker._export_failure
        assert terminal[0].export_failure.exception.exception_kind is ExceptionKind.PERMISSION_ERROR
    else:
        assert widths == [12]
        assert completed == [True]
        assert worker.export_run_result.status is ExportRunStatus.COMPLETE
        assert terminal[0].outcome is WorkflowOutcome.COMPLETED
        assert terminal[0].export_failure is None
        assert worker.calculate_column_width([]) == 12


def test_before_attempt_diagnostic_failure_is_best_effort_and_not_forwarded(tmp_path):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard, resolve_html_dashboard_assets_dir
    from metroliza.exporting.output_publication import write_dashboard_safely

    target = tmp_path / "out.html"
    def broken_diagnostics():
        raise RuntimeError(PRIVATE)
    result = write_dashboard_safely(
        write_export_html_dashboard, output_path=target, assets_dir=resolve_html_dashboard_assets_dir(target),
        sections=[], before_attempt=broken_diagnostics,
    )
    assert target.is_file()
    assert result["html_dashboard_path"] == str(target)


def test_actual_publication_permission_wrapper_retains_trusted_os_code(monkeypatch, tmp_path):
    from metroliza.exporting import output_publication as publication

    temporary = tmp_path / "staged.html"
    target = tmp_path / "out.html"
    temporary.write_bytes(b"complete staged output")
    original = PermissionError(13, PRIVATE)
    def deny(*args, **kwargs):
        raise original
    monkeypatch.setattr(publication, "_publish_new_output", deny)
    with pytest.raises(PermissionError) as caught:
        publication.publish_output(temporary, target)
    assert caught.value is not original
    assert caught.value.__cause__ is original
    assert caught.value.errno is None
    failure = _failure(caught.value, ExportFailureStage.HTML_PUBLICATION)
    assert failure.exception.exception_kind is ExceptionKind.PERMISSION_ERROR
    assert failure.cause_kind is ExceptionKind.PERMISSION_ERROR
    assert failure.code is ExportFailureCode.ACCESS_DENIED
    assert failure.errno == 13
    assert failure.winerror is None
    assert PRIVATE not in json.dumps(export_failure_payload(failure))
    assert not target.exists()
    assert temporary.read_bytes() == b"complete staged output"


def test_os_code_extraction_keeps_outer_pair_and_obeys_explicit_cause_depth_bound():
    outer = OSError(22, PRIVATE)
    outer.__cause__ = PermissionError(13, PRIVATE)
    assert _failure(outer).errno == 22
    assert _failure(outer).winerror is None
    for wrappers, expected in ((8, 13), (9, None)):
        exception = PermissionError(13, PRIVATE)
        for _ in range(wrappers):
            wrapped = RuntimeError(PRIVATE)
            wrapped.__cause__ = exception
            exception = wrapped
        failure = _failure(exception)
        assert failure.exception.exception_kind is ExceptionKind.RUNTIME_ERROR
        assert failure.errno == expected
    cyclic = RuntimeError(PRIVATE)
    cyclic.__cause__ = cyclic
    assert _failure(cyclic).errno is None
    assert _failure(cyclic).exception.structure_truncated
    contextual = RuntimeError(PRIVATE)
    contextual.__context__ = PermissionError(13, PRIVATE)
    assert _failure(contextual).errno is None
    grouped = ExceptionGroup(PRIVATE, [PermissionError(13, PRIVATE)])
    assert _failure(grouped).errno is None


def test_os_cause_extraction_never_reads_hostile_attributes_or_class_comparisons():
    class HostileType(type):
        def __eq__(cls, other):
            raise AssertionError("class equality executed")
        def __hash__(cls):
            raise AssertionError("class hash executed")
    class Hostile(PermissionError, metaclass=HostileType):
        def __getattribute__(self, name):
            raise AssertionError("attribute executed")
        def __str__(self):
            raise AssertionError("str executed")
        def __repr__(self):
            raise AssertionError("repr executed")
    hostile = Hostile(13, PRIVATE)
    wrapped = RuntimeError(PRIVATE)
    wrapped.__cause__ = hostile
    failure = _failure(wrapped)
    assert failure.errno is None
    assert failure.winerror is None
    assert failure.cause_kind is ExceptionKind.UNKNOWN_EXCEPTION
    assert PRIVATE not in json.dumps(export_failure_payload(failure))


@pytest.mark.skipif(__import__("os").name != "nt", reason="native builtin winerror requires Windows")
@pytest.mark.parametrize("winerror", [32, 5, 206])
def test_native_windows_publication_os_codes_survive_wrapper(monkeypatch, tmp_path, winerror):
    from metroliza.exporting import output_publication as publication

    temporary = tmp_path / "staged.html"
    temporary.write_bytes(b"complete staged output")
    target = tmp_path / "out.html"
    original = OSError(0, PRIVATE, None, winerror)
    assert original.winerror == winerror
    original_codes = (original.errno, original.winerror)
    def deny(*args, **kwargs):
        raise original
    monkeypatch.setattr(publication, "_publish_new_output", deny)
    with pytest.raises(OSError) as caught:
        publication.publish_output(temporary, target)
    if winerror in (32, 5):
        assert type(original) is PermissionError
        assert caught.value.__cause__ is original
    else:
        assert caught.value is original
    failure = _failure(caught.value, ExportFailureStage.HTML_PUBLICATION)
    assert (failure.errno, failure.winerror) == original_codes
    expected = ExportFailureCode.PATH_TOO_LONG if winerror == 206 else ExportFailureCode.ACCESS_DENIED
    assert failure.code is expected
    assert PRIVATE not in json.dumps(export_failure_payload(failure))
    assert not target.exists()
    assert temporary.read_bytes() == b"complete staged output"


@pytest.mark.skipif(__import__("os").name != "nt", reason="native builtin winerror requires Windows")
def test_native_windows_os_code_pair_precedence_does_not_splice_cause_fields():
    cause = PermissionError(13, PRIVATE, None, 32)
    for outer in (PermissionError(13, PRIVATE), PermissionError(13, PRIVATE, None, 5)):
        outer.__cause__ = cause
        failure = _failure(outer)
        assert failure.errno == outer.errno
        assert failure.winerror == getattr(outer, "winerror", None)
        assert failure.winerror != cause.winerror
