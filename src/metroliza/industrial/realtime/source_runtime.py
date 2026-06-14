"""Runtime boundary for one-shot realtime industrial polling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.db_poller import SourceDbAdapter
from metroliza.industrial.realtime.realtime_service import PollingCycleResult, run_polling_cycle
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
                results.append(
                    PollingCycleResult(
                        source_profile_id=config.source_profile_id,
                        stream_key=config.stream_key,
                        status="failed",
                        error="Source profile is not available in the local Metroliza database.",
                    )
                )
                continue
            results.append(
                run_polling_cycle(
                    database=self.database,
                    profile=profile,
                    config=config,
                    adapter=self.adapter,
                )
            )
        return tuple(results)
