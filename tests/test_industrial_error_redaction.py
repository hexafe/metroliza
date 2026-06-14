from __future__ import annotations

from types import SimpleNamespace

from modules import industrial_workers, oznak_adapter
from modules.industrial_data_repository import redact_sensitive_text
from modules.industrial_workers import IndustrialLinkRefreshThread


def _capture_signal(signal, values: list[object]) -> None:
    if hasattr(signal, "connect"):
        signal.connect(values.append)
    else:
        signal.emit = values.append


def test_redact_sensitive_text_handles_exception_uri_credentials_and_tokens():
    message = (
        "connect failed "
        "mssql+pyodbc://operator:secret123@db.internal/plant "
        "password=secret123 token=tok_abc host=db.internal"
    )

    redacted = redact_sensitive_text(RuntimeError(message), max_len=None)

    assert "secret123" not in redacted
    assert "tok_abc" not in redacted
    assert "operator" not in redacted
    assert "db.internal" not in redacted
    assert redacted.count("<redacted>") >= 4
    assert (
        redact_sensitive_text("Operator note: Line 2 paused for gauge calibration.")
        == "Operator note: Line 2 paused for gauge calibration."
    )


def test_redact_sensitive_text_redacts_unquoted_sql_values_to_end_of_message():
    redacted = redact_sensitive_text(
        "source failed sql=SELECT * FROM raw_events WHERE token=sql-token"
    )

    assert redacted == "source failed sql=<redacted>"
    assert "raw_events" not in redacted
    assert "sql-token" not in redacted


def test_industrial_link_refresh_thread_redacts_exception_before_ui_emit(monkeypatch):
    def raise_secret_error(_db_file):
        raise RuntimeError(
            "link refresh failed password=secret123 "
            "postgresql://operator:uri-secret@db.internal/plant token=abc123"
        )

    monkeypatch.setattr(
        industrial_workers,
        "materialize_industrial_report_links",
        raise_secret_error,
    )
    thread = IndustrialLinkRefreshThread("reports.db")
    emitted: list[str] = []
    _capture_signal(thread.error_occurred, emitted)

    thread.run()

    assert emitted
    assert "secret123" not in emitted[0]
    assert "uri-secret" not in emitted[0]
    assert "operator" not in emitted[0]
    assert "db.internal" not in emitted[0]
    assert "abc123" not in emitted[0]
    assert "<redacted>" in emitted[0]


def test_oznak_source_result_diagnostics_redact_free_form_payloads():
    payload = SimpleNamespace(
        row_count=0,
        has_errors=True,
        partial_success=False,
        warnings=("secondary warning password=warn-secret",),
        errors=("driver error token=error-token",),
        source_results=(
            SimpleNamespace(
                source_alias="assembly_mes",
                status="failed",
                message=(
                    "connection failed "
                    "mssql+pyodbc://operator:source-secret@db.internal/plant "
                    "password=message-secret"
                ),
                query_summary="SELECT * FROM raw_events WHERE password='query-secret'",
                metadata={
                    "apiKey": "metadata-key",
                    "note": "token=metadata-token",
                    "nested": [{"connection_string": "Server=db;Pwd=secret"}],
                },
            ),
        ),
    )

    diagnostics = oznak_adapter._fetch_result_diagnostics(payload)
    source_result = diagnostics["source_results"][0]

    serialized = repr(diagnostics)
    assert "warn-secret" not in serialized
    assert "error-token" not in serialized
    assert "source-secret" not in serialized
    assert "message-secret" not in serialized
    assert "query-secret" not in serialized
    assert "metadata-key" not in serialized
    assert "metadata-token" not in serialized
    assert source_result["source_alias"] == "assembly_mes"
    assert source_result["query_summary"] == "<redacted>"
    assert source_result["metadata"]["apiKey"] == "<redacted>"
    assert source_result["metadata"]["nested"][0]["connection_string"] == "<redacted>"


def test_oznak_progress_diagnostics_redact_mapping_payloads_for_ui_callbacks():
    emitted: list[str] = []
    callback = oznak_adapter._sanitize_progress_callback(
        lambda diagnostic: emitted.append(diagnostic.message)
    )

    callback(
        {
            "message": "fetch retry password=secret123 token=progress-token",
            "metadata": {"host": "db.internal"},
        }
    )

    assert emitted == ["fetch retry password=<redacted> token=<redacted>"]
