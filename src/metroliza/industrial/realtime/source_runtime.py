"""Runtime boundary for one-shot realtime industrial polling."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from metroliza.industrial.industrial_data_repository import (
    IndustrialDataRepository,
    redact_sensitive_text,
)
from metroliza.industrial.realtime.db_poller import SourceDbAdapter
from metroliza.industrial.realtime.realtime_service import PollingCycleResult, run_polling_cycle
from metroliza.industrial.realtime.source_health_service import RealtimeSourceHealthService
from metroliza.industrial.realtime.stream_config import RealtimePollConfig


@dataclass(frozen=True)
class RealtimeMonitorStatus:
    """Compact status for a configured realtime stream."""

    source_profile_id: int
    stream_key: str
    enabled: bool


class RealtimeSourceRuntime:
    """Small non-GUI orchestration boundary for configured realtime streams."""

    def __init__(
        self,
        *,
        database: str,
        configs: Iterable[RealtimePollConfig],
        adapter: SourceDbAdapter,
    ) -> None:
        self.database = database
        self.configs = tuple(config.validated() for config in configs)
        self.adapter = adapter
        self.source_health_service = RealtimeSourceHealthService(database)

    def list_statuses(self) -> tuple[RealtimeMonitorStatus, ...]:
        return tuple(
            RealtimeMonitorStatus(
                source_profile_id=config.source_profile_id,
                stream_key=config.stream_key,
                enabled=config.enabled,
            )
            for config in self.configs
        )

    def poll_once(self) -> tuple[PollingCycleResult, ...]:
        repository = IndustrialDataRepository(self.database)
        profiles = {profile.id: profile for profile in repository.list_source_profiles(include_disabled=True)}
        results: list[PollingCycleResult] = []
        for config in self.configs:
            if not config.enabled:
                continue
            profile = profiles.get(config.source_profile_id)
            if profile is None:
                error = "Source profile is not available in the local Metroliza database."
                results.append(
                    PollingCycleResult(
                        source_profile_id=config.source_profile_id,
                        stream_key=config.stream_key,
                        status="failed",
                        error=error,
                        diagnostics={
                            "stage": "source_profile_lookup",
                            "error": redact_sensitive_text(error, max_len=500),
                        },
                    )
                )
                continue
            if not profile.is_enabled:
                error = "Source profile is disabled in the local Metroliza database."
                results.append(
                    PollingCycleResult(
                        source_profile_id=config.source_profile_id,
                        stream_key=config.stream_key,
                        status="failed",
                        error=error,
                        diagnostics={
                            "stage": "source_profile_disabled",
                            "error": redact_sensitive_text(error, max_len=500),
                        },
                    )
                )
                continue
            result = run_polling_cycle(
                database=self.database,
                profile=profile,
                config=config,
                adapter=self.adapter,
            )
            try:
                health = self.source_health_service.evaluate(config)
                diagnostics = dict(result.diagnostics)
                diagnostics["source_health"] = {
                    "status": health.status,
                    "evaluated_at": health.evaluated_at,
                    "lag_seconds": health.lag_seconds,
                }
                result = replace(result, diagnostics=diagnostics, lag_seconds=health.lag_seconds)
            except Exception as exc:
                diagnostics = dict(result.diagnostics)
                diagnostics.setdefault("warnings", [])
                diagnostics["warnings"] = [
                    *diagnostics["warnings"],
                    f"source health evaluation failed: {redact_sensitive_text(exc)}",
                ]
                result = replace(result, diagnostics=diagnostics)
            results.append(result)
        return tuple(results)
