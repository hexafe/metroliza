"""Oznak-backed source adapter for realtime industrial polling."""

from __future__ import annotations

from typing import Any, Callable

from metroliza.industrial.industrial_credentials import (
    IndustrialStoredCredentials,
    load_industrial_credentials,
)
from metroliza.industrial.industrial_data_repository import redact_sensitive_text
from metroliza.industrial.oznak_adapter import fetch_oznak_records_for_source_sql
from metroliza.industrial.realtime.db_poller import SourceReadRequest, SourceReadResult

CredentialLoader = Callable[[str], IndustrialStoredCredentials]


class OznakRealtimeSourceAdapter:
    """Read bounded realtime batches through the pinned Oznak integration."""

    def __init__(
        self,
        *,
        credential_loader: CredentialLoader = load_industrial_credentials,
        cancellation_token: Any = None,
        import_module: Any = None,
    ) -> None:
        self.credential_loader = credential_loader
        self.cancellation_token = cancellation_token
        self.import_module = import_module

    def fetch_rows(self, request: SourceReadRequest) -> SourceReadResult:
        """Fetch a parameterized, bounded SQL batch for one realtime stream."""

        credentials = self.credential_loader(request.profile.profile_key)
        if not credentials.username or not credentials.password:
            return SourceReadResult(
                error=(
                    "No saved industrial database credentials are available for source "
                    f"'{request.profile.profile_name}'."
                ),
                diagnostics={
                    "stage": "credentials",
                    "source_profile_id": request.profile.id,
                    "stream_key": request.config.stream_key,
                    "credentials_source": credentials.source or "missing",
                },
            )

        result = fetch_oznak_records_for_source_sql(
            request.profile,
            username=credentials.username,
            password=credentials.password,
            sql_text=request.query.sql_text,
            parameters=request.query.parameters,
            limit=request.query.limit,
            timeout_seconds=request.query.timeout_seconds,
            mode="fetch",
            cancellation_token=self.cancellation_token,
            import_module=self.import_module,
        )
        diagnostics = dict(result.diagnostics or {})
        diagnostics.setdefault("stage", "oznak_realtime_fetch")
        diagnostics.setdefault("source_profile_id", request.profile.id)
        diagnostics.setdefault("stream_key", request.config.stream_key)
        diagnostics.setdefault("row_count", result.row_count)
        if result.error:
            return SourceReadResult(
                rows=tuple(result.records or ()),
                diagnostics=diagnostics,
                error=redact_sensitive_text(result.error),
            )
        return SourceReadResult(
            rows=tuple(result.records or ()),
            diagnostics=diagnostics,
        )
