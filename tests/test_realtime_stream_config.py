import pytest

from metroliza.industrial.realtime.stream_config import (
    RealtimePollConfig,
    RealtimeStreamConfigError,
    reject_sensitive_config_payload,
)


def _config(**overrides):
    values = {
        "source_profile_id": 1,
        "stream_key": "cycle_time",
        "cursor_column": "event_id",
        "event_time_column": "process_timestamp",
        "record_key_column": "record_id",
        "signal_keys": ("cycle_time",),
        "signal_columns": {"cycle_time": "cycle_time_s"},
    }
    values.update(overrides)
    return RealtimePollConfig(**values)


def test_realtime_poll_config_normalizes_bounds_and_signal_columns():
    config = _config(
        signal_keys=("cycle_time", "cycle_time"),
        chunk_size=100,
        max_catchup_rows_per_cycle=200,
    ).validated()

    assert config.signal_keys == ("cycle_time",)
    assert config.signal_columns == {"cycle_time": "cycle_time_s"}
    assert config.cycle_limit == 100


def test_realtime_poll_config_normalizes_and_deduplicates_detector_keys():
    config = _config(detectors=(" Rolling_ZScore ", "rolling_zscore", "SPEC_LIMITS")).validated()

    assert config.detectors == ("rolling_zscore", "spec_limits")


def test_realtime_poll_config_rejects_unknown_detector_and_timezone():
    with pytest.raises(RealtimeStreamConfigError, match="Unsupported realtime detector"):
        _config(detectors=("not_implemented",)).validated()
    with pytest.raises(RealtimeStreamConfigError, match="Unknown source timezone"):
        _config(source_timezone="Mars/Olympus_Mons").validated()


@pytest.mark.parametrize(
    "overrides",
    [
        {"cursor_column": "events.id"},
        {"event_time_column": "process timestamp"},
        {"record_key_column": "1record"},
        {"chunk_size": 0},
        {"max_catchup_rows_per_cycle": 10, "chunk_size": 20},
        {"timeout_seconds": 0},
        {"timeout_seconds": 61, "polling_interval_seconds": 60},
        {"allowed_lateness_seconds": -1},
        {"allowed_lateness_seconds": float("nan")},
        {"allowed_lateness_seconds": float("inf")},
        {"polling_interval_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"source_profile_id": True},
        {"source_profile_id": 1.5},
        {"source_profile_id": 2**63},
        {"chunk_size": True},
        {"chunk_size": 1.5},
        {"max_catchup_rows_per_cycle": 2**63},
        {"signal_keys": ()},
        {"fetch_all_confirmed": True},
    ],
)
def test_realtime_poll_config_rejects_unsafe_or_unbounded_settings(overrides):
    with pytest.raises(RealtimeStreamConfigError):
        _config(**overrides).validated()


def test_realtime_stream_config_rejects_nested_credentials():
    payload = {
        "streaming": {
            "enabled": True,
            "sources": [
                {
                    "stream_key": "cycle_time",
                    "password": "secret",
                    "nested": {"apiToken": "token"},
                }
            ],
        }
    }

    with pytest.raises(RealtimeStreamConfigError) as exc:
        reject_sensitive_config_payload(payload)

    message = str(exc.value)
    assert "streaming.sources[0].password" in message
    assert "streaming.sources[0].nested.apiToken" in message
