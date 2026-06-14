"""One-cycle realtime industrial polling service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from metroliza.industrial.anomaly.baseline_repository import BaselineRepository
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.industrial_data_repository import (
    IndustrialSourceProfile,
    redact_sensitive_text,
)
from metroliza.industrial.realtime.db_poller import (
    SourceDbReader,
    SourceReadRequest,
    build_poll_query,
    with_computed_watermarks,
)
from metroliza.industrial.realtime.offset_store import StreamOffsetStore
from metroliza.industrial.realtime.replay import run_detectors_for_samples
from metroliza.industrial.realtime.sample_mapper import (
    SignalSampleMapping,
    map_rows_to_samples,
)
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository, utc_timestamp
from metroliza.industrial.realtime.stream_config import (
    RealtimeStreamConfig,
    redact_stream_diagnostics,
    signal_definition_from_stream,
    validate_stream_config,
)
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, StreamOffset


@dataclass(frozen=True)
class PollingCycleResult:
    """Result of one bounded realtime polling cycle."""

    status: str
    rows_fetched: int = 0
    samples_processed: int = 0
    samples_inserted: int = 0
    samples_skipped: int = 0
    events_created: int = 0
    cursor_value: str | None = None
    event_time_watermark: str | None = None
    lag_seconds: float | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class RealtimeMonitorStatus:
    """Compact aggregate status for a realtime monitor run."""

    cycles: int
    succeeded: int
    failed: int
    partial: int
    rows_fetched: int
    events_created: int


class RealtimeIndustrialService:
    """Coordinate one safe realtime source polling cycle."""

    def __init__(
        self,
        database: str,
        *,
        sample_repository: RealtimeSampleRepository | None = None,
        offset_store: StreamOffsetStore | None = None,
        event_repository: AnomalyEventRepository | None = None,
        baseline_repository: BaselineRepository | None = None,
    ):
        self.database = database
        self.sample_repository = sample_repository or RealtimeSampleRepository(database)
        self.offset_store = offset_store or StreamOffsetStore(database)
        self.event_repository = event_repository or AnomalyEventRepository(database)
        self.baseline_repository = baseline_repository or BaselineRepository(database)

    def poll_stream(
        self,
        *,
        profile: IndustrialSourceProfile,
        config: RealtimeStreamConfig,
        reader: SourceDbReader,
        now: str | None = None,
    ) -> PollingCycleResult:
        """Run one bounded poll and advance offset only after local writes succeed."""

        now_text = now or utc_timestamp()
        try:
            config = validate_stream_config(config, profile)
            signal = self.sample_repository.upsert_signal_definition(
                signal_definition_from_stream(config)
            )
            assert signal.id is not None
            offset = self.offset_store.get_offset(
                source_profile_id=config.source_profile_id,
                stream_key=config.stream_key,
            )
            query = build_poll_query(profile, config, offset)
            read_result = with_computed_watermarks(
                reader.fetch_rows(
                    SourceReadRequest(
                        profile=profile,
                        config=config,
                        offset=offset,
                        query=query,
                    )
                ),
                config,
            )
        except Exception as exc:
            return PollingCycleResult(
                status="error",
                diagnostics={"stage": "request"},
                error=redact_sensitive_text(exc),
            )

        if read_result.error:
            self._record_error_offset(
                config=config,
                offset=offset,
                error=read_result.error,
                diagnostics=read_result.diagnostics,
            )
            return PollingCycleResult(
                status="error",
                rows_fetched=read_result.row_count,
                diagnostics=redact_stream_diagnostics(read_result.diagnostics or {}),
                error=redact_sensitive_text(read_result.error),
            )

        mapping_result = map_rows_to_samples(
            read_result.rows,
            SignalSampleMapping(config=config, signal=signal),
            ingest_time=now_text,
        )
        diagnostics: dict[str, Any] = {
            "source": redact_stream_diagnostics(read_result.diagnostics or {}),
            "mapping": {
                "rows_processed": mapping_result.stats.rows_processed,
                "samples_mapped": mapping_result.stats.samples_mapped,
                "samples_skipped": mapping_result.stats.samples_skipped,
                "missing_required": mapping_result.stats.missing_required,
                "non_numeric": mapping_result.stats.non_numeric,
                "invalid_timestamp": mapping_result.stats.invalid_timestamp,
            },
        }
        try:
            batch_result = self.sample_repository.insert_samples(mapping_result.samples)
            persisted_samples = self._load_current_samples(
                signal_id=signal.id,
                sample_ids=batch_result.sample_ids,
            )
            events_created, detector_diagnostics = self._detect_and_persist_events(
                signal_id=signal.id,
                signal=signal,
                current_samples=persisted_samples,
                config=config,
                now=now_text,
            )
            diagnostics["detectors"] = detector_diagnostics
            lag_seconds = _lag_seconds(read_result.event_time_watermark, now_text)
            final_offset = self.offset_store.upsert_offset(
                StreamOffset(
                    source_profile_id=config.source_profile_id,
                    stream_key=config.stream_key,
                    cursor_column=config.record_key_column,
                    cursor_value=read_result.cursor_value or _offset_value(offset),
                    event_time_watermark=read_result.event_time_watermark
                    or _offset_watermark(offset),
                    last_success_at=now_text,
                    last_error=None,
                    lag_seconds=lag_seconds,
                    status="idle",
                )
            )
        except Exception as exc:
            return PollingCycleResult(
                status="error",
                rows_fetched=read_result.row_count,
                samples_processed=mapping_result.stats.samples_mapped,
                diagnostics=diagnostics,
                error=redact_sensitive_text(exc),
            )

        status = "idle" if read_result.row_count == 0 else "success"
        if diagnostics.get("detectors", {}).get("errors"):
            status = "partial"
        return PollingCycleResult(
            status=status,
            rows_fetched=read_result.row_count,
            samples_processed=batch_result.processed,
            samples_inserted=batch_result.inserted,
            samples_skipped=batch_result.skipped + mapping_result.stats.samples_skipped,
            events_created=events_created,
            cursor_value=final_offset.cursor_value,
            event_time_watermark=final_offset.event_time_watermark,
            lag_seconds=final_offset.lag_seconds,
            diagnostics=diagnostics,
        )

    def _load_current_samples(
        self,
        *,
        signal_id: int,
        sample_ids: tuple[int, ...],
    ) -> list[IndustrialSample]:
        if not sample_ids:
            return []
        samples_by_id = {
            sample.id: sample
            for sample in self.sample_repository.list_samples(signal_id=signal_id)
            if sample.id is not None
        }
        return [samples_by_id[sample_id] for sample_id in sample_ids if sample_id in samples_by_id]

    def _detect_and_persist_events(
        self,
        *,
        signal_id: int,
        signal,
        current_samples: list[IndustrialSample],
        config: RealtimeStreamConfig,
        now: str,
    ) -> tuple[int, dict[str, Any]]:
        if not current_samples:
            return 0, {"events_created": 0}
        current_ids = {sample.id for sample in current_samples if sample.id is not None}
        history_limit = max(len(current_samples), int(config.policy.history_limit or 0))
        history = self.sample_repository.list_recent_samples(
            signal_id=signal_id,
            limit=max(history_limit, len(current_samples)),
        )
        baseline = self.baseline_repository.latest_baseline(signal_id=signal_id) or {}
        diagnostics: dict[str, Any] = {"events_created": 0, "errors": []}
        try:
            events = [
                event
                for event in run_detectors_for_samples(
                    history,
                    signal=signal,
                    detectors=config.detectors,
                    baseline=baseline,
                    now=now,
                )
                if event.sample_id in current_ids
            ]
        except Exception as exc:
            diagnostics["errors"].append(redact_sensitive_text(exc))
            return 0, diagnostics
        if not events:
            return 0, diagnostics
        event_result = self.event_repository.insert_events(events)
        diagnostics["events_created"] = event_result.inserted
        return event_result.inserted, diagnostics

    def _record_error_offset(
        self,
        *,
        config: RealtimeStreamConfig,
        offset: StreamOffset | None,
        error: str,
        diagnostics: Mapping[str, Any] | None,
    ) -> None:
        self.offset_store.upsert_offset(
            StreamOffset(
                source_profile_id=config.source_profile_id,
                stream_key=config.stream_key,
                cursor_column=config.record_key_column,
                cursor_value=_offset_value(offset),
                event_time_watermark=_offset_watermark(offset),
                last_success_at=offset.last_success_at if offset is not None else None,
                last_error=redact_sensitive_text(error),
                lag_seconds=offset.lag_seconds if offset is not None else None,
                status="error",
            )
        )


def summarize_monitor_results(results: list[PollingCycleResult]) -> RealtimeMonitorStatus:
    """Summarize multiple stream cycle results."""

    return RealtimeMonitorStatus(
        cycles=len(results),
        succeeded=sum(1 for result in results if result.status in {"success", "idle"}),
        failed=sum(1 for result in results if result.status == "error"),
        partial=sum(1 for result in results if result.status == "partial"),
        rows_fetched=sum(result.rows_fetched for result in results),
        events_created=sum(result.events_created for result in results),
    )


def _offset_value(offset: StreamOffset | None) -> str | None:
    return offset.cursor_value if offset is not None else None


def _offset_watermark(offset: StreamOffset | None) -> str | None:
    return offset.event_time_watermark if offset is not None else None


def _lag_seconds(event_time: str | None, now: str) -> float | None:
    if not event_time:
        return None
    try:
        event_dt = _parse_time(event_time)
        now_dt = _parse_time(now)
    except ValueError:
        return None
    return max(0.0, (now_dt - event_dt).total_seconds())


def _parse_time(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
