"""Settings and row boundaries for retrying a committed detector batch."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from metroliza.industrial.realtime.numeric_validation import exact_integral, finite_number
from metroliza.industrial.realtime.stream_contracts import SignalDefinition


DETECTOR_BATCH_KEY = "detector_batch"
_FORMAT_VERSION = 1
_LIMIT_FIELDS = ("nominal", "lsl", "usl", "lower_warning", "upper_warning")


def capture_detector_batch(cursor, signals: Iterable[SignalDefinition]) -> dict[str, Any]:
    """Capture limits used for this batch and bounds on append-only history."""
    return {
        "version": _FORMAT_VERSION,
        "maximum_sample_id": cursor.execute(
            "SELECT COALESCE(MAX(id), 0) FROM industrial_samples"
        ).fetchone()[0],
        "maximum_baseline_id": cursor.execute(
            "SELECT COALESCE(MAX(id), 0) FROM industrial_baselines"
        ).fetchone()[0],
        "signals": {
            str(signal.id): {
                **{name: getattr(signal, name) for name in _LIMIT_FIELDS},
                "segment_fields": list(signal.segment_fields),
            }
            for signal in signals
        },
    }


@dataclass(frozen=True)
class DetectorBatch:
    signals: tuple[SignalDefinition, ...]
    maximum_sample_id: int | None = None
    maximum_baseline_id: int | None = None

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], signals: Iterable[SignalDefinition], sample_ids: tuple[int, ...],
    ) -> DetectorBatch:
        signals = tuple(signals)
        if DETECTOR_BATCH_KEY not in payload:
            # Older producers stored IDs and detector names, without a settings snapshot.
            return cls(signals)

        snapshot = payload[DETECTOR_BATCH_KEY]
        if not isinstance(snapshot, dict) or type(snapshot.get("version")) is not int:
            raise ValueError("detector batch is missing a valid settings version")
        if snapshot["version"] != _FORMAT_VERSION:
            raise ValueError("detector batch has an unsupported settings version")
        maximum_sample_id = exact_integral(
            snapshot.get("maximum_sample_id"), field_name="detector batch sample boundary",
            minimum=max(sample_ids),
        )
        maximum_baseline_id = exact_integral(
            snapshot.get("maximum_baseline_id"), field_name="detector batch baseline boundary",
        )
        settings = snapshot.get("signals")
        if not isinstance(settings, dict) or settings.keys() != {str(signal.id) for signal in signals}:
            raise ValueError("detector batch settings do not match its signal IDs")
        frozen_signals = tuple(_restore_signal(signal, settings[str(signal.id)]) for signal in signals)
        return cls(frozen_signals, maximum_sample_id, maximum_baseline_id)


def _restore_signal(signal: SignalDefinition, raw: Any) -> SignalDefinition:
    if not isinstance(raw, dict) or any(name not in raw for name in _LIMIT_FIELDS):
        raise ValueError("detector batch is missing signal limits")
    segments = raw.get("segment_fields")
    if not isinstance(segments, list) or not all(isinstance(name, str) and name for name in segments):
        raise ValueError("detector batch has invalid signal segment fields")
    limits = {
        name: None if raw[name] is None else finite_number(raw[name], field_name=f"detector batch {name}")
        for name in _LIMIT_FIELDS
    }
    return replace(signal, segment_fields=tuple(segments), **limits)
