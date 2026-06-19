from pathlib import Path

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import StaleSourceDetector
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.replay import ReplayRequest, replay_industrial_stream
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "industrial_realtime"


def _source_profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )


def test_end_to_end_replay_normal_process_creates_no_events(tmp_path):
    db_path = str(tmp_path / "normal.db")
    profile = _source_profile(db_path)

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(FIXTURE_DIR / "normal_stable_process.csv"),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            lsl=8.0,
            usl=12.0,
        )
    )

    assert summary.samples_processed == 5
    assert summary.detector_events_created == 0
    assert summary.event_counts == {}


def test_end_to_end_replay_spec_limit_breach_has_explainable_event(tmp_path):
    db_path = str(tmp_path / "spec.db")
    profile = _source_profile(db_path)

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(FIXTURE_DIR / "spec_limit_breach.csv"),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            lsl=8.0,
            usl=12.0,
        )
    )
    events = AnomalyEventRepository(db_path).list_events()

    assert summary.samples_inserted == 3
    assert summary.detector_events_created == 1
    assert summary.event_counts == {"spec_limits/critical": 1}
    assert len(events) == 1
    assert events[0].observed_value == 13.5
    assert events[0].threshold["usl"] == 12.0
    assert "Observed value 13.5 is above USL 12" in events[0].explanation


def test_end_to_end_replay_stale_source_event_attaches_to_last_sample(tmp_path):
    db_path = str(tmp_path / "stale.db")
    profile = _source_profile(db_path)
    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(FIXTURE_DIR / "missing_stale_data.csv"),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            lsl=8.0,
            usl=12.0,
        )
    )
    assert summary.samples_inserted == 2
    sample_repository = RealtimeSampleRepository(db_path)
    signal = sample_repository.get_signal_definition(
        source_profile_id=profile.id,
        signal_key="cycle_time",
    )
    assert signal is not None
    samples = sample_repository.list_samples(signal_id=signal.id)
    last_sample = samples[-1]

    stale_event = StaleSourceDetector(warning_seconds=300, major_seconds=900).score_one(
        last_sample,
        DetectorContext(signal=signal, now="2026-06-13T10:20:00Z"),
    )
    assert stale_event is not None
    event_result = AnomalyEventRepository(db_path).insert_events([stale_event])
    events = AnomalyEventRepository(db_path).list_events(detector_key="stale_source")

    assert event_result.inserted == 1
    assert len(events) == 1
    assert events[0].sample_id == last_sample.id
    assert events[0].context["source_level"] is True
    assert events[0].context["last_event_time"] == "2026-06-13T10:01:00Z"
    assert "No new samples" in events[0].explanation


def test_end_to_end_replay_single_point_outlier_fixture_creates_one_event(tmp_path):
    db_path = str(tmp_path / "outlier.db")
    profile = _source_profile(db_path)

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(FIXTURE_DIR / "single_point_outlier.csv"),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            usl=20.0,
        )
    )
    events = AnomalyEventRepository(db_path).list_events()

    assert summary.samples_processed == 5
    assert summary.detector_events_created == 1
    assert summary.event_counts == {"spec_limits/critical": 1}
    assert events[0].observed_value == 25.0
    assert "Observed value 25 is above USL 20" in events[0].explanation


def test_end_to_end_replay_gradual_drift_fixture_creates_warning_event(tmp_path):
    db_path = str(tmp_path / "drift.db")
    profile = _source_profile(db_path)

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(FIXTURE_DIR / "gradual_drift.csv"),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("spec_limits",),
            usl=20.0,
            upper_warning=11.5,
        )
    )
    events = AnomalyEventRepository(db_path).list_events()

    assert summary.samples_processed == 5
    assert summary.detector_events_created == 1
    assert summary.event_counts == {"spec_limits/warning": 1}
    assert events[0].severity == "warning"
    assert events[0].observed_value == 11.8
    assert "above warning limit 11.5" in events[0].explanation


def test_end_to_end_replay_stuck_value_fixture_creates_no_statistical_false_positive(tmp_path):
    db_path = str(tmp_path / "stuck.db")
    profile = _source_profile(db_path)

    summary = replay_industrial_stream(
        ReplayRequest(
            input_file=str(FIXTURE_DIR / "stuck_value.csv"),
            database=db_path,
            source_profile_id=profile.id,
            signal_key="cycle_time",
            metric_column="cycle_time_s",
            event_time_column="event_time",
            record_key_column="event_id",
            detectors=("rolling_zscore",),
        )
    )

    assert summary.samples_processed == 5
    assert summary.detector_events_created == 0
    assert summary.event_counts == {}
