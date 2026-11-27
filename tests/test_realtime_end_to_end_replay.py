from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from metroliza.industrial.anomaly.baseline_repository import BaselineRepository, IndustrialBaseline
from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import StaleSourceDetector
from metroliza.industrial.anomaly.event_repository import AnomalyEventRepository
from metroliza.industrial.realtime.replay import ReplayRequest, replay_industrial_stream
from metroliza.industrial.realtime.sample_repository import RealtimeSampleRepository
from metroliza.industrial.realtime.stream_contracts import SignalDefinition


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "industrial_realtime"
OUTLIER_SEGMENT = {"part_number": "PN-100", "revision": "A", "station": "S1", "line": "L1"}


def _source_profile(db_path: str):
    return IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )


def _statistical_replay(database, *, batch_size=7, segment_fields=tuple(OUTLIER_SEGMENT), enabled=True):
    profile = _source_profile(database)
    signal = RealtimeSampleRepository(database).upsert_signal_definition(SignalDefinition(
        source_profile_id=profile.id, signal_key="cycle_time", metric_name="cycle_time_s",
        unit="s", nominal=100, segment_fields=segment_fields, enabled=enabled,
    ))
    request = ReplayRequest(
        input_file=str(FIXTURE_DIR / "single_high_outlier.csv"),
        database=database,
        source_profile_id=profile.id,
        signal_key="cycle_time",
        metric_column="cycle_time_s",
        event_time_column="event_time",
        record_key_column="event_id",
        detectors=("iqr", "mad_zscore"),
        batch_size=batch_size,
    )
    return request, IndustrialBaseline(
        signal_id=signal.id, segment_key={field: OUTLIER_SEGMENT[field] for field in segment_fields},
        baseline_version="exact-segment-v1",
        n=40, q1=99, q3=101, iqr=2, median=100, mad=1,
        window_start="2026-06-12T09:00:00Z", window_end="2026-06-12T10:00:00Z",
        created_at="2026-06-12T11:00:00Z",
    )


@pytest.mark.parametrize("batch_size", [1, 7, 500])
def test_replay_uses_exact_stored_baseline_and_persists_explainable_events(tmp_path, batch_size):
    database = tmp_path / "statistical.db"
    request, baseline = _statistical_replay(str(database), batch_size=batch_size)
    repository = BaselineRepository(str(database))
    # Equal created_at chooses the larger baseline ID. A newer unrelated segment
    # or signal-wide row must never override the exact match.
    repository.insert_baseline(replace(baseline, baseline_version="prior", iqr=50, mad=50))
    expected_id = repository.insert_baseline(baseline)
    for segment in ({}, dict(OUTLIER_SEGMENT, station="S2")):
        repository.insert_baseline(replace(
            baseline, segment_key=segment, iqr=50, mad=50, created_at="2026-06-13T11:00:00Z",
        ))

    expected_counts = {"iqr/major": 1, "mad_zscore/major": 1}
    before = database.read_bytes()
    predicted = replay_industrial_stream(replace(request, dry_run=True))
    assert predicted.samples_processed == 36 and predicted.event_counts == expected_counts
    assert predicted.samples_inserted == predicted.detector_events_created == 0
    assert database.read_bytes() == before

    actual = replay_industrial_stream(request)
    assert actual.samples_inserted == 36 and actual.event_counts == expected_counts
    assert actual.detector_events_created == 2
    stored_signal = RealtimeSampleRepository(str(database)).get_signal_definition(
        source_profile_id=request.source_profile_id, signal_key=request.signal_key,
    )
    assert (stored_signal.unit, stored_signal.nominal, stored_signal.segment_fields) == (
        "s", 100, tuple(OUTLIER_SEGMENT),
    )
    events = sorted(AnomalyEventRepository(str(database)).list_events(), key=lambda event: event.id)
    assert [event.detector_key for event in events] == ["iqr", "mad_zscore"]
    for event in events:
        assert event.observed_value == 120 and event.signal_id == baseline.signal_id
        assert event.context["baseline_id"] == expected_id
        assert event.context["baseline_version"] == "exact-segment-v1"
        assert event.context["baseline_window_start"] == "2026-06-12T09:00:00.000000Z"
        assert event.context["baseline_window_end"] == "2026-06-12T10:00:00.000000Z"
        assert event.threshold["n"] == 40
        evidence = event.context["detector_evidence"]
        assert evidence["configuration"]["detector"] == event.detector_key
        assert evidence["window"]["kind"] == "stored_baseline"
        assert evidence["window"]["id"] == expected_id
        assert evidence["window"]["version"] == "exact-segment-v1"
    repeat = replay_industrial_stream(request)
    assert repeat.samples_inserted == repeat.detector_events_created == 0
    assert repeat.samples_skipped == 36 and repeat.event_counts == expected_counts
    assert sorted(AnomalyEventRepository(str(database)).list_events(), key=lambda event: event.id) == events


@pytest.mark.parametrize("segment_fields", [("station",), ()])
def test_statistical_replay_uses_configured_segment_fields(tmp_path, segment_fields):
    database = str(tmp_path / "configured-segment.db")
    request, baseline = _statistical_replay(database, segment_fields=segment_fields)
    baselines = BaselineRepository(database)
    expected_id = baselines.insert_baseline(baseline)
    baselines.insert_baseline(replace(baseline, segment_key=OUTLIER_SEGMENT, iqr=50, mad=50))

    expected_counts = {"iqr/major": 1, "mad_zscore/major": 1}
    assert replay_industrial_stream(replace(request, dry_run=True)).event_counts == expected_counts
    actual = replay_industrial_stream(request)
    assert actual.samples_inserted == 36 and actual.detector_events_created == 2
    samples = RealtimeSampleRepository(database).list_recent_samples(signal_id=baseline.signal_id)
    assert len(samples) == 36 and all(sample.segment_key == baseline.segment_key for sample in samples)
    assert all(sample.part_number == "PN-100" and sample.line == "L1" for sample in samples)
    assert {event.context["baseline_id"] for event in AnomalyEventRepository(database).list_events()} == {expected_id}


def test_default_replay_preserves_signal_for_next_statistical_replay(tmp_path):
    database = str(tmp_path / "default-then-statistical.db")
    request, baseline = _statistical_replay(database, segment_fields=("station",), enabled=False)
    baselines = BaselineRepository(database)
    station_baseline_id = baselines.insert_baseline(baseline)
    baselines.insert_baseline(replace(baseline, segment_key={}, iqr=50, mad=50))
    source = tmp_path / "spec-only.csv"
    source.write_text(
        "event_id,event_time,cycle_time_s,station,part_number\n"
        "SPEC1,2026-06-13T09:00:00Z,115,S1,PN-100\n",
        encoding="utf-8",
    )
    default_request = ReplayRequest(
        input_file=str(source),
        database=database,
        source_profile_id=request.source_profile_id,
        signal_key=request.signal_key,
        metric_column=request.metric_column,
        event_time_column=request.event_time_column,
        record_key_column=request.record_key_column,
        usl=110,
    )
    default_summary = replay_industrial_stream(default_request)
    assert default_summary.samples_inserted == 1 and default_summary.event_counts == {"spec_limits/critical": 1}
    repository = RealtimeSampleRepository(database)
    after_default = repository.get_signal_definition(
        source_profile_id=request.source_profile_id, signal_key=request.signal_key,
    )
    spec_event, = AnomalyEventRepository(database).list_events()
    assert spec_event.expected_value is None
    assert spec_event.score == 5 and spec_event.threshold["usl"] == 110

    statistical_summary = replay_industrial_stream(request)
    assert statistical_summary.samples_inserted == 36
    assert statistical_summary.event_counts == {"iqr/major": 1, "mad_zscore/major": 1}
    scored = [event for event in AnomalyEventRepository(database).list_events() if event.id != spec_event.id]
    assert len(scored) == 2 and {event.context["baseline_id"] for event in scored} == {station_baseline_id}
    after_statistical = repository.get_signal_definition(
        source_profile_id=request.source_profile_id, signal_key=request.signal_key,
    )
    for signal in (after_default, after_statistical):
        assert (signal.unit, signal.nominal, signal.segment_fields, signal.enabled) == ("s", 100, ("station",), False)
        assert signal.usl == 110
    for sample in repository.list_recent_samples(signal_id=baseline.signal_id):
        expected_segment = {"station": "S1"}
        if sample.source_record_key == "SPEC1":
            expected_segment["part_number"] = "PN-100"
        assert sample.segment_key == expected_segment


def test_statistical_replay_reuses_a_legacy_superset_without_rewriting_samples(tmp_path):
    database = str(tmp_path / "legacy-segment.db")
    request, baseline = _statistical_replay(database, segment_fields=("station",))
    samples = RealtimeSampleRepository(database)
    signal = samples.get_signal_definition(source_profile_id=request.source_profile_id, signal_key=request.signal_key)
    assert replay_industrial_stream(replace(request, detectors=("spec_limits",))).samples_inserted == 36
    before = samples.list_recent_samples(signal_id=signal.id)
    assert len(before) == 36 and all(sample.segment_key == OUTLIER_SEGMENT for sample in before)
    baseline_id = BaselineRepository(database).insert_baseline(baseline)

    actual = replay_industrial_stream(request)
    assert actual.samples_inserted == 0 and actual.samples_skipped == 36
    assert actual.detector_events_created == 2
    events = AnomalyEventRepository(database).list_events()
    assert {event.context["baseline_id"] for event in events} == {baseline_id}
    assert samples.list_recent_samples(signal_id=signal.id) == before
    assert replay_industrial_stream(request).detector_events_created == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_statistical_replay_rejects_missing_configured_segment_columns(tmp_path, dry_run):
    database = tmp_path / "missing-column.db"
    request, baseline = _statistical_replay(str(database), segment_fields=("station",))
    BaselineRepository(str(database)).insert_baseline(replace(baseline, segment_key={}))
    path = tmp_path / "missing-station.csv"
    path.write_text("event_id,event_time,cycle_time_s\nID1,2026-06-13T10:00:00Z,120\n", encoding="utf-8")
    before = database.read_bytes()
    with pytest.raises(ValueError, match="missing configured segment columns: station"):
        replay_industrial_stream(replace(request, input_file=str(path), dry_run=dry_run))
    assert database.read_bytes() == before


def test_statistical_replay_does_not_guess_missing_legacy_or_blank_segment_values(tmp_path):
    database = str(tmp_path / "missing-value.db")
    request, baseline = _statistical_replay(database, segment_fields=("station",))
    source = tmp_path / "missing-station-value.csv"
    source.write_text(
        "event_id,event_time,cycle_time_s,station\nID1,2026-06-13T10:00:00Z,120,\n",
        encoding="utf-8",
    )
    request = replace(request, input_file=str(source))
    samples = RealtimeSampleRepository(database)
    signal = samples.get_signal_definition(source_profile_id=request.source_profile_id, signal_key=request.signal_key)
    assert replay_industrial_stream(replace(request, detectors=("spec_limits",))).samples_inserted == 1
    baselines = BaselineRepository(database)
    baselines.insert_baseline(baseline)
    baselines.insert_baseline(replace(baseline, segment_key={}))
    assert replay_industrial_stream(replace(request, dry_run=True)).event_counts == {}

    source.write_text(source.read_text(encoding="utf-8").replace(",120,\n", ",120,S1\n"), encoding="utf-8")
    assert replay_industrial_stream(replace(request, dry_run=True)).event_counts == {"iqr/major": 1, "mad_zscore/major": 1}
    assert replay_industrial_stream(request).event_counts == {}
    assert samples.list_recent_samples(signal_id=signal.id)[0].segment_key == {}
    assert AnomalyEventRepository(database).list_events() == []


def test_replay_does_not_fall_back_to_a_wrong_or_unsegmented_baseline(tmp_path):
    database = str(tmp_path / "no-exact.db")
    request, baseline = _statistical_replay(database)
    for segment in ({}, dict(OUTLIER_SEGMENT, station="S2")):
        BaselineRepository(database).insert_baseline(replace(baseline, segment_key=segment))
    assert replay_industrial_stream(replace(request, dry_run=True)).event_counts == {}
    assert replay_industrial_stream(request).event_counts == {}
    assert AnomalyEventRepository(database).list_events() == []


def test_dry_run_can_read_a_committed_baseline_in_the_wal(tmp_path):
    database = tmp_path / "active-wal.db"
    request, baseline = _statistical_replay(str(database))
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        BaselineRepository(str(database), connection=writer).insert_baseline(baseline)
        wal = database.with_name(database.name + "-wal")
        before = (database.read_bytes(), wal.read_bytes())
        assert before[1], "the fixture must have a pending WAL"
        assert replay_industrial_stream(replace(request, dry_run=True)).event_counts == {
            "iqr/major": 1, "mad_zscore/major": 1,
        }
        assert (database.read_bytes(), wal.read_bytes()) == before


def test_replay_uses_one_baseline_ceiling_across_batches(tmp_path, monkeypatch):
    from metroliza.industrial.realtime.replay import _ReplayDetectorSession

    database = str(tmp_path / "new-baseline.db")
    request, baseline = _statistical_replay(database, batch_size=7)
    repository = BaselineRepository(database)
    initial_id = repository.insert_baseline(baseline)
    delivered = []
    selected = []
    score = _ReplayDetectorSession.score
    read_baseline = BaselineRepository.read_latest_baseline

    def record_baseline(cursor, *, signal_id, segment_json, maximum_id):
        found = read_baseline(cursor, signal_id=signal_id, segment_json=segment_json, maximum_id=maximum_id)
        selected.append((maximum_id, found["id"]))
        return found

    def append_after_first_batch(session, samples):
        events = score(session, samples)
        if not delivered:
            delivered.append(repository.insert_baseline(replace(
                baseline, baseline_version="newer", iqr=50, mad=50,
                created_at="2026-06-13T11:00:00Z",
            )))
        return events

    monkeypatch.setattr(_ReplayDetectorSession, "score", append_after_first_batch)
    monkeypatch.setattr(BaselineRepository, "read_latest_baseline", staticmethod(record_baseline))
    assert replay_industrial_stream(request).event_counts == {"iqr/major": 1, "mad_zscore/major": 1}
    assert delivered[0] > initial_id
    assert selected == [(initial_id, initial_id)] * 6  # one lookup per seven-row batch
    assert {event.context["baseline_id"] for event in AnomalyEventRepository(database).list_events()} == {initial_id}
    assert replay_industrial_stream(replace(request, dry_run=True)).event_counts == {}
    assert selected[6:] == [(delivered[0], delivered[0])] * 6


@pytest.mark.parametrize("existing_database", [False, True])
def test_dry_run_never_opens_a_writable_connection_or_initializes_schema(tmp_path, monkeypatch, existing_database):
    database = tmp_path / "uninitialized.db"
    connect = sqlite3.connect
    if existing_database:
        with closing(connect(database)) as connection, connection:
            connection.execute("CREATE TABLE unrelated_sentinel (value TEXT)")
            connection.execute("INSERT INTO unrelated_sentinel VALUES ('unchanged')")
    before = database.read_bytes() if existing_database else None
    opened = []

    def read_only_connect(location, *args, **kwargs):
        opened.append(location)
        assert kwargs.get("uri") and parse_qs(urlsplit(location).query)["mode"] == ["ro"]
        return connect(location, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", read_only_connect)
    summary = replay_industrial_stream(ReplayRequest(
        input_file=str(FIXTURE_DIR / "single_high_outlier.csv"), database=str(database),
        source_profile_id=1, signal_key="cycle_time", metric_column="cycle_time_s",
        event_time_column="event_time", record_key_column="event_id",
        detectors=("iqr", "mad_zscore", "spec_limits"), dry_run=True, usl=110,
    ))
    assert summary.event_counts == {"spec_limits/critical": 1}
    assert bool(opened) == existing_database
    assert (database.read_bytes() if database.exists() else None) == before
    assert {file.name for file in tmp_path.iterdir()} == ({database.name} if existing_database else set())


def test_statistical_replay_does_not_reassign_a_signal_to_another_metric(tmp_path):
    database = tmp_path / "wrong-metric.db"
    request, baseline = _statistical_replay(str(database))
    BaselineRepository(str(database)).insert_baseline(baseline)
    before = database.read_bytes()
    with pytest.raises(ValueError, match="stored signal metric"):
        replay_industrial_stream(replace(request, metric_column="metric_value"))
    assert database.read_bytes() == before


@pytest.mark.parametrize("batch_size", [1, 7, 50])
@pytest.mark.parametrize("existing_ids_reversed", [False, True])
def test_replay_keeps_csv_order_for_timestamp_ties(tmp_path, batch_size, existing_ids_reversed):
    database = str(tmp_path / "replay.sqlite")
    profile = _source_profile(database)
    path = tmp_path / "ties.csv"
    header = "record_id,event_time,cycle_time_s\n"
    warmup = "".join(
        f"warm-{index:02d},2026-06-12T09:00:{index:02d}Z,{99 if index % 2 == 0 else 101}\n"
        for index in range(29)
    )
    normal = "z-warmup,2026-06-12T09:00:29Z,101\n"
    step = "a-shift,2026-06-12T09:00:29Z,103.5\n"
    request = ReplayRequest(
        input_file=str(path), database=database, source_profile_id=profile.id, signal_key="cycle_time",
        metric_column="cycle_time_s", event_time_column="event_time", record_key_column="record_id",
        detectors=("rolling_zscore",), batch_size=batch_size,
    )
    if existing_ids_reversed:
        path.write_text(header + step + normal, encoding="utf-8")
        assert replay_industrial_stream(replace(request, detectors=("spec_limits",))).samples_inserted == 2
    path.write_text(header + warmup + normal + step, encoding="utf-8")

    expected = {"rolling_zscore/major": 1}
    preview = replay_industrial_stream(replace(request, dry_run=True))
    result = replay_industrial_stream(request)
    assert (preview.event_counts, result.event_counts) == (expected, expected)
    event, = AnomalyEventRepository(database).list_events()
    assert event.observed_value == 103.5
    assert replay_industrial_stream(request).detector_events_created == 0


def _rolling_replay(tmp_path, *, batch_size=7):
    database = tmp_path / "rolling-segments.sqlite"
    profile = _source_profile(str(database))
    signal = RealtimeSampleRepository(str(database)).upsert_signal_definition(SignalDefinition(
        source_profile_id=profile.id, signal_key="cycle_time",
        metric_name="cycle_time_s", segment_fields=("station",),
    ))
    csv_path = tmp_path / "rolling-segments.csv"
    return database, csv_path, signal, ReplayRequest(
        input_file=str(csv_path), database=str(database), source_profile_id=profile.id,
        signal_key=signal.signal_key, metric_column=signal.metric_name, event_time_column="event_time",
        record_key_column="record_id", detectors=("rolling_zscore",), batch_size=batch_size,
    )


@pytest.mark.parametrize("batch_size", [1, 7, 500])
def test_rolling_replay_isolates_configured_segments_across_batches(tmp_path, batch_size):
    database, csv_path, signal, request = _rolling_replay(tmp_path, batch_size=batch_size)
    start = datetime(2026, 6, 12, 9, tzinfo=timezone.utc)
    warmup = []
    for index in range(60):
        station = "A" if index % 2 == 0 else "B"
        nominal = 100 if station == "A" else 200
        value = nominal + (-1 if index % 4 < 2 else 1)
        timestamp = (start + timedelta(seconds=index)).isoformat()
        warmup.append(f"row-{index},{timestamp},{value},{station}")
    csv_path.write_text("\n".join([
        "record_id,event_time,cycle_time_s,station",
        *warmup,
        "missing-station,2026-06-12T09:01:00Z,1000,",
        "station-B-outlier,2026-06-12T09:01:01Z,203.5,B",
        "",
    ]), encoding="utf-8")

    expected = {"rolling_zscore/major": 1}
    before = database.read_bytes()
    preview = replay_industrial_stream(replace(request, dry_run=True))
    assert preview.event_counts == expected and database.read_bytes() == before
    persisted = replay_industrial_stream(request)
    assert persisted.samples_inserted == 62 and persisted.event_counts == expected
    event, = AnomalyEventRepository(str(database)).list_events()
    assert event.observed_value == 203.5 and event.expected_value == 200
    assert event.threshold["n"] == 30 and event.signal_id == signal.id
    evidence = event.context["detector_evidence"]
    assert evidence["source_profile_id"] == request.source_profile_id
    assert evidence["configuration"] == {
        "detector": "rolling_zscore", "algorithm_version": 1,
        "parameters": {"min_n": 30, "threshold": 3.0, "max_window": 500, "segment_fields": ["station"]},
    }
    assert evidence["window"]["kind"] == "prior_samples"
    assert evidence["window"]["count"] == 30
    assert evidence["window"]["last_event_time"] == "2026-06-12T09:00:59.000000Z"
    history_end, = RealtimeSampleRepository(str(database)).list_samples_by_ids(
        (evidence["window"]["last_sample_id"],),
    )
    assert history_end.source_record_key == "row-59" and history_end.segment_key == {"station": "B"}
    expected_history = json.dumps([199.0, 201.0] * 15, separators=(",", ":")).encode()
    assert evidence["window"]["values_sha256"] == sha256(expected_history).hexdigest()
    assert evidence["window"]["segment_sha256"] == sha256(b'{"station":"B"}').hexdigest()
    assert "values" not in evidence["window"] and "segment_key" not in evidence["window"]
    assert replay_industrial_stream(request).detector_events_created == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_rolling_replay_rejects_excess_segments_before_writes(tmp_path, dry_run):
    database, csv_path, _signal, request = _rolling_replay(tmp_path)
    csv_path.write_text(
        "record_id,event_time,cycle_time_s,station\n"
        + "".join(f"row-{index},2026-06-12T09:00:00Z,100,station-{index}\n" for index in range(257)),
        encoding="utf-8",
    )
    before = database.read_bytes()
    assert replay_industrial_stream(replace(request, dry_run=True, limit=256)).samples_processed == 256
    with pytest.raises(ValueError, match="supports up to 256 segments"):
        replay_industrial_stream(replace(request, dry_run=dry_run))
    assert database.read_bytes() == before


@pytest.mark.parametrize(("change", "message"), [
    ("metric", "does not match the stored signal metric"),
    ("segment", "missing configured segment columns: station"),
])
@pytest.mark.parametrize("dry_run", [False, True])
def test_rolling_replay_rejects_incompatible_input_without_changing_database(tmp_path, change, message, dry_run):
    database, csv_path, _signal, request = _rolling_replay(tmp_path)
    if change == "metric":
        request = replace(request, metric_column="other")
        csv_path.write_text("record_id,event_time,other,station\none,2026-06-12T09:00:00Z,100,A\n", encoding="utf-8")
    else:
        csv_path.write_text("record_id,event_time,cycle_time_s\none,2026-06-12T09:00:00Z,100\n", encoding="utf-8")
    before = database.read_bytes()
    with pytest.raises(ValueError, match=message):
        replay_industrial_stream(replace(request, dry_run=dry_run))
    assert database.read_bytes() == before


def test_equal_time_replay_keeps_the_existing_source_health_event(tmp_path):
    database = str(tmp_path / "stale-replay.sqlite")
    profile = _source_profile(database)
    path = tmp_path / "ties.csv"
    header = "record_id,event_time,cycle_time_s\n"
    older_id = "earlier-in-database,2026-06-12T09:00:00Z,101\n"
    newer_id = "later-in-database,2026-06-12T09:00:00Z,102\n"
    request = ReplayRequest(
        input_file=str(path), database=database, source_profile_id=profile.id, signal_key="cycle_time",
        metric_column="cycle_time_s", event_time_column="event_time", record_key_column="record_id",
        detectors=("stale_source",), now="2026-06-12T09:30:00Z", batch_size=50,
    )
    path.write_text(header + older_id + newer_id, encoding="utf-8")
    assert replay_industrial_stream(request).detector_events_created == 1
    repository = AnomalyEventRepository(database)
    existing, = repository.list_events()
    assert existing.observed_value == 102
    evidence = existing.context["detector_evidence"]
    assert evidence["configuration"]["parameters"] == {"warning_seconds": 300.0, "major_seconds": 900.0}
    assert evidence["window"] == {
        "kind": "elapsed_since_last_sample", "last_event_time": "2026-06-12T09:00:00.000000Z",
        "evaluated_at": "2026-06-12T09:30:00.000000Z",
    }

    path.write_text(header + newer_id + older_id, encoding="utf-8")
    assert replay_industrial_stream(request).detector_events_created == 0
    assert repository.list_events() == [existing]

    # Existing alert identity continues to be sample + detector when the
    # previously stored event predates the new evidence document.
    old_context = {"source_level": True, "last_sample_id": existing.sample_id}
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE industrial_anomaly_events SET context_json = ? WHERE id = ?",
            (json.dumps(old_context), existing.id),
        )
    assert replay_industrial_stream(request).detector_events_created == 0
    assert repository.list_events() == [replace(existing, context=old_context)]


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
    assert events[0].context["last_event_time"] == "2026-06-13T10:01:00.000000Z"
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
