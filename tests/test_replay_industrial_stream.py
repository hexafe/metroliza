import importlib.util
from pathlib import Path

import pytest

from modules.db import sqlite_connection_scope
from modules.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.replay import (
    ReplayRequest,
    replay_industrial_stream,
    rows_to_samples,
    run_detectors_for_samples,
)
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_contracts import IndustrialSample, SignalDefinition


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "event_id,event_time,cycle_time_s,station",
                "ROW-1,2026-06-13T10:00:00Z,10.0,S1",
                "ROW-2,2026-06-13T10:01:00Z,10.2,S1",
                "ROW-3,2026-06-13T10:02:00Z,13.5,S1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _source_profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )


def test_rows_to_samples_maps_process_context_and_skips_incomplete_rows():
    request = ReplayRequest(
        input_file="unused.csv",
        database="unused.db",
        source_profile_id=7,
        signal_key="cycle_time",
        metric_column="cycle_time_s",
        event_time_column="event_time",
        record_key_column="event_id",
    )
    rows = [
        {
            "event_id": "ROW-1",
            "event_time": "2026-06-13T10:00:00Z",
            "cycle_time_s": "10.25",
            "reference": "REF-1",
            "part_number": "PN-1",
            "revision": "A",
            "station": "S1",
            "line": "L1",
            "work_order": "WO-1",
            "batch_lot": "LOT-1",
            "operator": "OP-1",
        },
        {
            "event_id": "",
            "event_time": "2026-06-13T10:01:00Z",
            "cycle_time_s": "10.5",
        },
        {
            "event_id": "ROW-3",
            "event_time": "",
            "cycle_time_s": "10.5",
        },
        {
            "event_id": "ROW-4",
            "event_time": "2026-06-13T10:03:00Z",
            "cycle_time_s": "",
        },
    ]

    samples = rows_to_samples(rows, request, signal_id=99)

    assert len(samples) == 1
    sample = samples[0]
    assert sample.source_profile_id == 7
    assert sample.signal_id == 99
    assert sample.source_record_key == "ROW-1"
    assert sample.event_time == "2026-06-13T10:00:00.000000Z"
    assert sample.metric_name == "cycle_time_s"
    assert sample.value == 10.25
    assert sample.reference == "REF-1"
    assert sample.part_number == "PN-1"
    assert sample.revision == "A"
    assert sample.station == "S1"
    assert sample.line == "L1"
    assert sample.work_order == "WO-1"
    assert sample.batch_lot == "LOT-1"
    assert sample.raw_record == {
        "event_id": "ROW-1",
        "event_time": "2026-06-13T10:00:00Z",
        "cycle_time_s": "10.25",
        "reference": "REF-1",
        "part_number": "PN-1",
        "revision": "A",
        "station": "S1",
        "line": "L1",
        "work_order": "WO-1",
        "batch_lot": "LOT-1",
    }
    assert sample.segment_key == {
        "reference": "REF-1",
        "part_number": "PN-1",
        "revision": "A",
        "station": "S1",
        "line": "L1",
    }


def test_run_detectors_for_samples_carries_state_through_service_cycle():
    signal = SignalDefinition(
        id=42,
        source_profile_id=7,
        signal_key="cycle_time",
        metric_name="cycle_time_s",
    )
    stable_samples = [
        IndustrialSample(
            id=index + 1,
            source_profile_id=7,
            signal_id=signal.id,
            source_record_key=f"ROW-{index + 1}",
            event_time=f"2026-06-13T10:{index:02d}:00Z",
            metric_name="cycle_time_s",
            value=9.0 if index % 2 else 11.0,
        )
        for index in range(30)
    ]
    outlier = IndustrialSample(
        id=31,
        source_profile_id=7,
        signal_id=signal.id,
        source_record_key="ROW-31",
        event_time="2026-06-13T10:30:00Z",
        metric_name="cycle_time_s",
        value=20.0,
    )

    events = run_detectors_for_samples(
        [*stable_samples, outlier],
        signal=signal,
        detectors=("rolling_zscore",),
    )

    assert len(events) == 1
    event = events[0]
    assert event.detector_key == "rolling_zscore"
    assert event.sample_id == outlier.id
    assert event.signal_id == signal.id
    assert event.signal_key == signal.signal_key
    assert event.severity == "major"
    assert event.threshold["n"] == 30
    assert "rolling z-score" in event.explanation


def test_run_detectors_for_samples_can_warm_state_without_emitting_history():
    signal = SignalDefinition(
        id=42,
        source_profile_id=7,
        signal_key="cycle_time",
        metric_name="cycle_time_s",
    )
    history = [
        IndustrialSample(
            id=index + 1,
            source_profile_id=7,
            signal_id=signal.id,
            source_record_key=f"ROW-{index + 1}",
            event_time=f"2026-06-13T10:{index:02d}:00Z",
            metric_name="cycle_time_s",
            value=9.0 if index % 2 else 11.0,
        )
        for index in range(30)
    ]
    old_outlier = IndustrialSample(
        id=31,
        source_profile_id=7,
        signal_id=signal.id,
        source_record_key="ROW-31",
        event_time="2026-06-13T10:30:00Z",
        metric_name="cycle_time_s",
        value=20.0,
    )
    new_outlier = IndustrialSample(
        id=32,
        source_profile_id=7,
        signal_id=signal.id,
        source_record_key="ROW-32",
        event_time="2026-06-13T10:31:00Z",
        metric_name="cycle_time_s",
        value=21.0,
    )

    events = run_detectors_for_samples(
        [*history, old_outlier, new_outlier],
        signal=signal,
        detectors=("rolling_zscore",),
        score_sample_ids=(new_outlier.id,),
    )

    assert [event.sample_id for event in events] == [new_outlier.id]


def test_replay_csv_inserts_samples_and_persists_spec_event(tmp_path):
    db_path = str(tmp_path / "replay.db")
    profile = _source_profile(db_path)
    csv_path = _write_csv(tmp_path / "samples.csv")

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(csv_path),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            usl=12.0,
            batch_size=1,
        )
    )

    assert summary.samples_processed == 3
    assert summary.samples_inserted == 3
    assert summary.samples_skipped == 0
    assert summary.detector_events_created == 1
    assert summary.event_counts == {"spec_limits/critical": 1}
    with sqlite_connection_scope(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM industrial_samples").fetchone()[0] == 3
        event = conn.execute(
            "SELECT severity, explanation FROM industrial_anomaly_events"
        ).fetchone()
    assert event[0] == "critical"
    assert "above USL 12" in event[1]


@pytest.mark.parametrize("batch_size", [True, 1.5, 0, -1, 2**63])
def test_replay_rejects_non_exact_or_out_of_range_batch_size(tmp_path, batch_size):
    with pytest.raises(ValueError, match="Replay batch_size"):
        replay_industrial_stream(
            ReplayRequest(
                input_file=str(tmp_path / "unused.csv"),
                database=str(tmp_path / "unused.db"),
                source_profile_id=1,
                signal_key="cycle_time",
                metric_column="cycle_time_s",
                event_time_column="event_time",
                record_key_column="event_id",
                batch_size=batch_size,
            )
        )


def test_replay_streams_large_csv_in_bounded_batches(tmp_path, monkeypatch):
    import metroliza.industrial.realtime.replay as replay_module

    database = str(tmp_path / "streaming.db")
    profile = _source_profile(database)
    csv_path = tmp_path / "large.csv"
    csv_path.write_text(
        "event_id,event_time,cycle_time_s\n"
        + "\n".join(
            f"ROW-{index},2026-07-09T10:{index // 60:02d}:{index % 60:02d}Z,10.0"
            for index in range(1_205)
        )
        + "\n",
        encoding="utf-8",
    )
    observed_batch_sizes = []
    original_rows_to_samples = replay_module.rows_to_samples

    def tracked_rows_to_samples(rows, request, signal_id):
        row_batch = tuple(rows)
        observed_batch_sizes.append(len(row_batch))
        return original_rows_to_samples(row_batch, request, signal_id)

    def reject_full_scan(self, **kwargs):
        raise AssertionError("replay must not scan the full persisted signal history")

    monkeypatch.setattr(replay_module, "rows_to_samples", tracked_rows_to_samples)
    monkeypatch.setattr(RealtimeSampleRepository, "list_samples", reject_full_scan)

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(csv_path),
            database=database,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            batch_size=37,
        )
    )

    assert summary.samples_processed == 1_205
    assert summary.samples_inserted == 1_205
    assert len(observed_batch_sizes) > 1
    assert max(observed_batch_sizes) == 37


def test_replay_rejects_unordered_input_before_persisting_any_replay_state(tmp_path):
    database = str(tmp_path / "unordered.db")
    profile = _source_profile(database)
    csv_path = tmp_path / "unordered.csv"
    csv_path.write_text(
        "event_id,event_time,cycle_time_s\n"
        "ROW-1,2026-07-09T10:01:00Z,10.0\n"
        "ROW-2,2026-07-09T10:02:00Z,10.1\n"
        "ROW-3,2026-07-09T10:00:00Z,10.2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be ordered by event time"):
        replay_industrial_stream(
            ReplayRequest(
                input_file=str(csv_path),
                database=database,
                source_profile_id=profile.id,
                signal_key="cycle_time",
                metric_column="cycle_time_s",
                event_time_column="event_time",
                record_key_column="event_id",
                detectors=("spec_limits",),
                batch_size=2,
            )
        )

    with sqlite_connection_scope(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM industrial_signal_definitions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM industrial_samples").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM industrial_anomaly_events").fetchone()[0] == 0


def test_replay_summary_counts_current_generated_events_not_existing_history(tmp_path):
    db_path = str(tmp_path / "rerun.db")
    profile = _source_profile(db_path)
    csv_path = _write_csv(tmp_path / "samples.csv")
    request = ReplayRequest(
        input_file=str(csv_path),
        database=db_path,
        source_profile_id=profile.id,
        signal_key="cycle_time",
        metric_column="cycle_time_s",
        event_time_column="event_time",
        record_key_column="event_id",
        detectors=("spec_limits",),
        usl=12.0,
    )

    first = replay_industrial_stream(request)
    second = replay_industrial_stream(request)

    assert first.detector_events_created == 1
    assert first.event_counts == {"spec_limits/critical": 1}
    assert second.samples_inserted == 0
    assert second.samples_skipped == 3
    assert second.detector_events_created == 0
    assert second.event_counts == {"spec_limits/critical": 1}


def test_replay_csv_dry_run_writes_no_samples_or_events(tmp_path):
    db_path = str(tmp_path / "dry_run.db")
    profile = _source_profile(db_path)
    csv_path = _write_csv(tmp_path / "samples.csv")

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(csv_path),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            dry_run=True,
            usl=12.0,
        )
    )

    assert summary.samples_processed == 3
    assert summary.samples_inserted == 0
    assert summary.detector_events_created == 0
    assert summary.event_counts == {"spec_limits/critical": 1}
    with sqlite_connection_scope(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM industrial_signal_definitions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM industrial_samples").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM industrial_anomaly_events").fetchone()[0] == 0


def test_replay_script_prints_compact_summary(tmp_path, capsys):
    db_path = str(tmp_path / "script.db")
    profile = _source_profile(db_path)
    csv_path = _write_csv(tmp_path / "samples.csv")
    script_path = REPO_ROOT / "scripts" / "replay_industrial_stream.py"
    spec = importlib.util.spec_from_file_location("test_replay_industrial_stream_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)

    result = module.main(
        [
            "--input",
            str(csv_path),
            "--db",
            db_path,
            "--source-profile-id",
            str(profile.id),
            "--signal-key",
            "cycle_time",
            "--metric-column",
            "cycle_time_s",
            "--event-time-column",
            "event_time",
            "--record-key-column",
            "event_id",
            "--detectors",
            "spec_limits",
            "--source-timezone",
            "Europe/Warsaw",
            "--batch-size",
            "1",
            "--usl",
            "12",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "samples processed: 3" in output
    assert "detector events created: 1" in output
    parsed = module.build_parser().parse_args(
        [
            "--input",
            str(csv_path),
            "--db",
            db_path,
            "--source-profile-id",
            str(profile.id),
            "--signal-key",
            "cycle_time",
            "--metric-column",
            "cycle_time_s",
            "--event-time-column",
            "event_time",
            "--record-key-column",
            "event_id",
            "--source-timezone",
            "Europe/Warsaw",
            "--batch-size",
            "17",
        ]
    )
    assert parsed.source_timezone == "Europe/Warsaw"
    assert parsed.batch_size == 17
