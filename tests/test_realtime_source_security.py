from __future__ import annotations

from metroliza.industrial.realtime.stream_config import (
    hash_sql_text,
    redact_stream_diagnostics,
    safe_query_diagnostics,
)


def test_realtime_stream_diagnostics_redact_nested_credentials_and_sql():
    payload = {
        "status": "failed",
        "password": "secret123",
        "nested": {
            "apiToken": "token-secret",
            "sql_text": "select * from production where password='secret123'",
            "message": "connection failed for mysql://user:secret123@db.example.invalid/prod",
        },
        "items": [{"connection_string": "Driver=SQL;PWD=secret123"}],
    }

    redacted = redact_stream_diagnostics(payload)

    assert redacted["status"] == "failed"
    assert redacted["password"] == "<redacted>"
    assert redacted["nested"]["apiToken"] == "<redacted>"
    assert redacted["nested"]["sql_text"] == "<redacted>"
    assert redacted["items"][0]["connection_string"] == "<redacted>"
    assert "secret123" not in repr(redacted)
    assert "db.example.invalid" not in repr(redacted)


def test_realtime_safe_query_diagnostics_store_hash_not_raw_sql():
    sql_text = "select record_id, metric_value from measurements where token = 'secret123'"
    diagnostics = safe_query_diagnostics(
        sql_text=sql_text,
        query_summary={
            "source": "line_a",
            "row_limit": 100,
            "query": sql_text,
            "message": "password=secret123",
        },
    )

    assert diagnostics["sql_hash"] == hash_sql_text(sql_text)
    assert diagnostics["query_summary"]["source"] == "line_a"
    assert diagnostics["query_summary"]["row_limit"] == 100
    assert diagnostics["query_summary"]["query"] == "<redacted>"
    assert "select record_id" not in repr(diagnostics).lower()
    assert "secret123" not in repr(diagnostics)
