"""A real synthetic export worker produces a safe copyable report trace."""

import time

from metroliza.reports.report_schema import ensure_report_schema
from metroliza.reports.report_repository import ReportRepository
from metroliza.shared import safe_bugreport
from metroliza.shared.safe_bugreport import (
    BugReportCategory,
    SafeBugReportRecorder,
    build_bug_report_markdown,
)
from metroliza.ui import export_dialog as export_ui


def test_real_export_dialog_worker_trace_can_be_copied_without_private_input(
    qapplication_session, monkeypatch, tmp_path
):
    marker = "synthetic_private_report_marker_936c"
    db_path = tmp_path / "private-source.sqlite"
    source_path = tmp_path / f"{marker}.pdf"
    source_path.write_bytes(marker.encode("ascii"))
    ensure_report_schema(str(db_path))
    ReportRepository(str(db_path)).persist_parsed_report(
        source_path=source_path,
        parser_id="cmm",
        parser_version="1.0",
        template_family="cmm_pdf_header_box",
        template_variant="cmm_pdf_header_box_serial_variant",
        parse_status="parsed",
        metadata={
            "reference": marker,
            "reference_raw": marker,
            "report_date": "2026-11-14",
            "part_name": marker,
            "revision": "A",
            "sample_number": "1",
            "sample_number_kind": "explicit_sample_number",
            "stats_count_raw": "1",
            "stats_count_int": 1,
            "operator_name": marker,
            "comment": None,
        },
        measurements=[
            {
                "page_number": 1,
                "row_order": 1,
                "header": marker,
                "section_name": marker,
                "feature_label": marker,
                "characteristic_name": "LOC",
                "characteristic_family": "LOC",
                "description": marker,
                "ax": "X",
                "nominal": 10.0,
                "tol_plus": 0.5,
                "tol_minus": -0.5,
                "bonus": 0.0,
                "meas": 10.1,
                "dev": 0.1,
                "outtol": 0,
                "is_nok": False,
                "status_code": "ok",
            }
        ],
        candidates=[],
        warnings=[],
        metadata_version="report_metadata_v1",
        metadata_profile_id="cmm_pdf_header_box",
        metadata_profile_version="1",
        page_count=1,
        measurement_count=1,
        has_nok=False,
        nok_count=0,
        metadata_confidence=0.9,
        identity_hash="synthetic-safe-workflow-test",
    )

    recorder = SafeBugReportRecorder()
    monkeypatch.setattr(safe_bugreport, "recorder", recorder)
    monkeypatch.setattr(export_ui, "_bugreport_recorder", recorder)
    monkeypatch.setattr(export_ui.ExportDialog, "_load_dialog_config", lambda _self: {"selected_preset": "fast_diagnostics"})
    monkeypatch.setattr(export_ui.ExportDialog, "_save_dialog_config", lambda _self: None)
    monkeypatch.setattr(export_ui, "save_export_dialog_config", lambda *_args: None)
    monkeypatch.setattr(export_ui, "show_export_result_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(export_ui, "load_dashboard_visual_settings", lambda: {})

    output_path = tmp_path / "private-export.xlsx"
    dialog = export_ui.ExportDialog(parent=None, db_file=str(db_path))
    try:
        dialog.show()
        dialog.excel_file = output_path
        dialog._set_path_field_value(dialog.excel_file_text_label, output_path)
        dialog._update_export_button_enabled_state()
        qapplication_session.processEvents()

        assert dialog.export_button.isEnabled()
        dialog.export_button.click()

        deadline = time.monotonic() + 60
        while dialog.export_thread is not None and time.monotonic() < deadline:
            qapplication_session.processEvents()
            time.sleep(0.01)
        assert dialog.export_thread is None, "real export worker did not reach its terminal UI callback"
        assert output_path.is_file()

        report = build_bug_report_markdown(
            BugReportCategory.WRONG_OUTPUT,
            recorder.snapshot(),
        )
        assert "workflow_report_export_started" in report
        assert (
            "workflow_report_export_completed" in report
            or "workflow_report_export_completed_with_fallback" in report
            or "workflow_report_export_completed_with_omissions" in report
        )
        assert marker not in report
        assert str(tmp_path) not in report
    finally:
        dialog.close()
