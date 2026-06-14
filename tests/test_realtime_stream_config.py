from __future__ import annotations

import pytest

from metroliza.industrial.industrial_source_config import build_source_profile
from metroliza.industrial.realtime.stream_config import (
    RealtimeStreamConfig,
    RealtimeStreamConfigError,
    StreamPollPolicy,
    load_realtime_stream_configs,
    realtime_source_columns,
    signal_definition_from_stream,
    validate_stream_config,
)


def _profile():
    return build_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a",
        database_type="mysql",
        host="db.example.invalid",
        port=3306,
        database_name="process",
        source_object_name="measurements",
        allowed_columns=(
            "record_id",
            "process_timestamp",
            "metric_value",
            "station",
            "line",
            "part_number",
        ),
        timestamp_column="process_timestamp",
        default_pagination_column="record_id",
    )


def test_load_realtime_stream_config_from_yaml_and_build_signal_definition(tmp_path):
    config_path = tmp_path / "streams.yaml"
    config_path.write_text(
        """
realtime_streams:
  diameter_line_a:
    source_profile_id: 1
    signal_key: diameter
    metric_column: metric_value
    event_time_column: process_timestamp
    record_key_column: record_id
    metric_name: Diameter
    unit: mm
    nominal: 10.0
    lsl: 9.8
    usl: 10.2
    lower_warning: 9.9
    upper_warning: 10.1
    segment_fields:
      - station
      - line
    context_columns:
      - part_number
    detectors:
      - spec_limits
      - rolling_zscore
    policy:
      batch_limit: 250
      timeout_seconds: 12
      max_lag_seconds: 90
      history_limit: 400
""".strip(),
        encoding="utf-8",
    )

    configs = load_realtime_stream_configs(config_path)
    validated = validate_stream_config(configs[0], _profile())
    signal = signal_definition_from_stream(validated)

    assert len(configs) == 1
    assert validated.stream_key == "diameter_line_a"
    assert validated.policy.batch_limit == 250
    assert validated.context_columns == ("part_number",)
    assert realtime_source_columns(validated) == (
        "record_id",
        "process_timestamp",
        "metric_value",
        "station",
        "line",
        "part_number",
    )
    assert signal.signal_key == "diameter"
    assert signal.metric_name == "Diameter"
    assert signal.segment_fields == ("station", "line")


def test_realtime_stream_config_rejects_credential_like_yaml_keys(tmp_path):
    config_path = tmp_path / "streams.yaml"
    config_path.write_text(
        """
realtime_streams:
  line_a:
    source_profile_id: 1
    signal_key: diameter
    metric_column: metric_value
    event_time_column: process_timestamp
    record_key_column: record_id
    password: should-not-be-here
    nested:
      apiKey: secret
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RealtimeStreamConfigError) as excinfo:
        load_realtime_stream_configs(config_path)

    message = str(excinfo.value)
    assert "password" in message
    assert "nested.apiKey" in message


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("metric_column", "metric-value", "metric column"),
        ("event_time_column", "event time", "event time column"),
        ("record_key_column", "id; drop table x", "record key column"),
    ],
)
def test_realtime_stream_config_rejects_unsafe_identifiers(field, value, match):
    kwargs = {
        "source_profile_id": 1,
        "stream_key": "diameter",
        "signal_key": "diameter",
        "metric_column": "metric_value",
        "event_time_column": "process_timestamp",
        "record_key_column": "record_id",
    }
    kwargs[field] = value

    with pytest.raises(RealtimeStreamConfigError, match=match):
        RealtimeStreamConfig(**kwargs).validated()


def test_realtime_stream_config_rejects_columns_outside_source_allowlist():
    config = RealtimeStreamConfig(
        source_profile_id=1,
        stream_key="diameter",
        signal_key="diameter",
        metric_column="metric_value",
        event_time_column="process_timestamp",
        record_key_column="record_id",
        context_columns=("operator_name",),
    )

    with pytest.raises(RealtimeStreamConfigError, match="outside the source profile allowlist"):
        validate_stream_config(config, _profile())


@pytest.mark.parametrize(
    "policy,match",
    [
        (StreamPollPolicy(batch_limit=0), "batch limit"),
        (StreamPollPolicy(timeout_seconds=0), "timeout"),
        (StreamPollPolicy(max_lag_seconds=-1), "max lag"),
        (StreamPollPolicy(history_limit=-1), "history"),
        (StreamPollPolicy(allow_initial_poll_without_cursor="yes"), "initial cursor"),
    ],
)
def test_realtime_stream_policy_rejects_unbounded_or_invalid_values(policy, match):
    with pytest.raises(RealtimeStreamConfigError, match=match):
        policy.validated()
