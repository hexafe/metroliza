"""Small runtime wrapper for polling configured realtime industrial streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from metroliza.industrial.industrial_data_repository import IndustrialSourceProfile
from metroliza.industrial.realtime.db_poller import SourceDbReader
from metroliza.industrial.realtime.realtime_service import (
    PollingCycleResult,
    RealtimeIndustrialService,
    RealtimeMonitorStatus,
    summarize_monitor_results,
)
from metroliza.industrial.realtime.stream_config import RealtimeStreamConfig


@dataclass(frozen=True)
class RealtimeRuntimeSettings:
    """Runtime toggles for a caller-owned realtime polling loop."""

    stop_on_error: bool = False


class RealtimeSourceRuntime:
    """Poll a collection of streams once; external schedulers own retry loops."""

    def __init__(
        self,
        database: str,
        *,
        service: RealtimeIndustrialService | None = None,
        settings: RealtimeRuntimeSettings | None = None,
    ):
        self.database = database
        self.service = service or RealtimeIndustrialService(database)
        self.settings = settings or RealtimeRuntimeSettings()

    def poll_once(
        self,
        *,
        profile: IndustrialSourceProfile,
        configs: Iterable[RealtimeStreamConfig],
        reader: SourceDbReader,
        now: str | None = None,
    ) -> tuple[list[PollingCycleResult], RealtimeMonitorStatus]:
        """Poll enabled configs once without sleeping or owning a background thread."""

        results: list[PollingCycleResult] = []
        for config in configs:
            if not config.enabled:
                continue
            result = self.service.poll_stream(
                profile=profile,
                config=config,
                reader=reader,
                now=now,
            )
            results.append(result)
            if result.status == "error" and self.settings.stop_on_error:
                break
        return results, summarize_monitor_results(results)
