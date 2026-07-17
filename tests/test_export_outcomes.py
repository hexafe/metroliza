from metroliza.exporting.export_dialog_service import (
    build_export_completion_diagnostics,
    build_export_completion_message,
)
from metroliza.exporting.export_outcomes import (
    ExportArtifactStatus,
    ExportRunStatus,
    derive_export_run_result,
    sanitize_export_diagnostics,
)


def test_complete_workbook_outcome_uses_plain_path_without_file_uri(tmp_path):
    workbook = tmp_path / "report.xlsx"
    metadata = {
        "local_xlsx_path": str(workbook),
        "local_export_outcome": "completed",
    }

    result = derive_export_run_result(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=metadata,
    )
    level, title, message = build_export_completion_message(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=metadata,
        run_result=result,
    )

    assert result.status is ExportRunStatus.COMPLETE
    assert level == "info"
    assert title == "Export complete"
    assert str(workbook.resolve()) in message
    assert "file://" not in message


def test_summary_chart_exception_becomes_omission_with_raw_detail_only_in_diagnostics(tmp_path):
    workbook = tmp_path / "report.xlsx"
    raw_error = "TypeError: 'int' object is not iterable"
    metadata = {
        "local_xlsx_path": str(workbook),
        "local_export_outcome": "completed",
        "summary_sheet_requested": True,
        "summary_sheet_warnings": [
            "Summary chart H1 (iqr) could not be generated; other charts continued."
        ],
        "summary_sheet_warning_details": [
            {
                "chart": "iqr",
                "exception_class": "TypeError",
                "exception_message": "'int' object is not iterable",
                "header": "H1",
            }
        ],
    }

    result = derive_export_run_result(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=metadata,
    )
    level, title, message = build_export_completion_message(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=metadata,
        run_result=result,
    )
    diagnostics = build_export_completion_diagnostics(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=metadata,
        run_result=result,
    )

    assert result.status is ExportRunStatus.COMPLETE_WITH_OMISSIONS
    assert level == "warning"
    assert title == "Export complete with omissions"
    assert "Some summary charts could not be generated" in message
    assert raw_error not in message
    assert "'int' object is not iterable" not in diagnostics
    assert "summary_chart-1" in diagnostics
    assert "failure_type=TypeError" in diagnostics
    summary_artifact = next(
        artifact for artifact in result.artifacts if artifact.artifact_id == "summary_charts"
    )
    assert summary_artifact.status is ExportArtifactStatus.PARTIAL


def test_requested_dashboard_omission_always_promotes_overall_status(tmp_path):
    workbook = tmp_path / "report.xlsx"
    metadata = {
        "local_xlsx_path": str(workbook),
        "local_export_outcome": "completed",
        "html_dashboard_requested": True,
        "html_dashboard_warnings": [
            "HTML dashboard could not be generated; workbook export continued."
        ],
    }

    result = derive_export_run_result(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=metadata,
    )

    assert result.status is ExportRunStatus.COMPLETE_WITH_OMISSIONS
    dashboard = next(
        artifact for artifact in result.artifacts if artifact.artifact_id == "html_dashboard"
    )
    assert dashboard.status is ExportArtifactStatus.OMITTED


def test_missing_required_html_dashboard_is_failed(tmp_path):
    dashboard = tmp_path / "dashboard.html"
    metadata = {
        "html_dashboard_requested": True,
        "html_dashboard_warnings": ["HTML dashboard output was not created."],
    }

    result = derive_export_run_result(
        excel_file=dashboard,
        export_target="html_dashboard",
        completion_metadata=metadata,
    )

    assert result.status is ExportRunStatus.FAILED
    required_dashboard = next(
        artifact for artifact in result.artifacts if artifact.artifact_id == "html_dashboard"
    )
    assert required_dashboard.required
    assert required_dashboard.status is ExportArtifactStatus.FAILED


def test_google_conversion_fallback_is_omission_with_usable_workbook(tmp_path):
    workbook = tmp_path / "report.xlsx"
    metadata = {
        "local_xlsx_path": str(workbook),
        "local_export_outcome": "completed",
        "fallback_message": "authorization failed",
        "conversion_warnings": ["token rejected"],
    }

    result = derive_export_run_result(
        excel_file=workbook,
        export_target="google_sheets_drive_convert",
        completion_metadata=metadata,
    )

    assert result.status is ExportRunStatus.COMPLETE_WITH_OMISSIONS
    google = next(
        artifact for artifact in result.artifacts if artifact.artifact_id == "google_sheet"
    )
    assert google.status is ExportArtifactStatus.OMITTED
    assert any(
        artifact.artifact_id == "workbook"
        and artifact.status is ExportArtifactStatus.COMPLETE
        for artifact in result.artifacts
    )


def test_cancelled_and_failed_are_derived_centrally(tmp_path):
    workbook = tmp_path / "report.xlsx"
    base = {
        "local_xlsx_path": str(workbook),
        "local_export_outcome": "completed",
    }

    cancelled = derive_export_run_result(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=base,
        cancelled=True,
    )
    failed = derive_export_run_result(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=base,
        terminal_failure="disk full",
    )

    assert cancelled.status is ExportRunStatus.CANCELLED
    assert failed.status is ExportRunStatus.FAILED
    _level, _title, failed_message = build_export_completion_message(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=base,
        run_result=failed,
    )
    failed_diagnostics = build_export_completion_diagnostics(
        excel_file=workbook,
        export_target="excel_xlsx",
        completion_metadata=base,
        run_result=failed,
    )
    assert "disk full" not in failed_message
    assert "disk full" not in failed_diagnostics
    assert "terminal_failure" in failed_diagnostics
    assert "failure_type=ExportError" in failed_diagnostics


def test_copyable_diagnostics_redact_secrets_dsns_and_raw_exception_messages(tmp_path):
    workbook = tmp_path / "report.xlsx"
    secret = "super-secret-password"
    dsn = f"postgresql://operator:{secret}@production.example/reports"
    metadata = {
        "local_xlsx_path": str(workbook),
        "local_export_outcome": "completed",
        "summary_sheet_requested": True,
        "summary_sheet_warnings": [f"RuntimeError: failed with {dsn}"],
        "summary_sheet_warning_details": [
            {
                "chart": "iqr",
                "exception_class": "RuntimeError",
                "exception_message": f"token={secret}; dsn={dsn}",
            }
        ],
        "conversion_warnings": [f"Bearer {secret}"],
        "fallback_message": f"OAuth token {secret} rejected",
    }

    result = derive_export_run_result(
        excel_file=workbook,
        export_target="google_sheets_drive_convert",
        completion_metadata=metadata,
        terminal_failure=f"RuntimeError: connection failed for {dsn}",
    )
    diagnostics = build_export_completion_diagnostics(
        excel_file=workbook,
        export_target="google_sheets_drive_convert",
        completion_metadata=metadata,
        run_result=result,
    )

    assert secret not in diagnostics
    assert dsn not in diagnostics
    assert "connection failed" not in diagnostics
    assert "terminal_failure" in diagnostics
    assert "summary_chart-1" in diagnostics
    assert "failure_type=RuntimeError" in diagnostics
    assert "chart=iqr" in diagnostics
    assert "detail=redacted" in diagnostics

    defensive_boundary = sanitize_export_diagnostics(
        f"postgresql://operator:{secret}@host/db\nTypeError: raw secret {secret}"
    )
    assert secret not in defensive_boundary
    assert "postgresql://" not in defensive_boundary
    assert "failure_type=TypeError" not in defensive_boundary

    adversarial_type_names = sanitize_export_diagnostics(
        "password=TOPSECRETError token=BearerException"
    )
    assert "TOPSECRETError" not in adversarial_type_names
    assert "BearerException" not in adversarial_type_names
    assert "password" not in adversarial_type_names
    assert "token" not in adversarial_type_names


def test_late_cancellation_preserves_completed_workbook_and_cancels_pending_cloud(tmp_path):
    workbook = tmp_path / "report.xlsx"
    metadata = {
        "local_xlsx_path": str(workbook),
        "local_export_outcome": "completed",
        "converted_url": "",
        "conversion_warnings": [],
        "fallback_message": "",
    }

    result = derive_export_run_result(
        excel_file=workbook,
        export_target="google_sheets_drive_convert",
        completion_metadata=metadata,
        cancelled=True,
    )

    assert result.status is ExportRunStatus.CANCELLED
    workbook_result = next(
        artifact for artifact in result.artifacts if artifact.artifact_id == "workbook"
    )
    google_result = next(
        artifact for artifact in result.artifacts if artifact.artifact_id == "google_sheet"
    )
    assert workbook_result.status is ExportArtifactStatus.COMPLETE
    assert workbook_result.location == str(workbook.resolve())
    assert google_result.status is ExportArtifactStatus.CANCELLED
