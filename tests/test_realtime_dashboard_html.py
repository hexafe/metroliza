from pathlib import Path

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.realtime.realtime_dashboard_service import RealtimeDashboardService
from metroliza.industrial.realtime.realtime_dashboard_html import (
    DashboardAggregateRow,
    DashboardAnomalyEvent,
    DashboardSamplePoint,
    DashboardSignalSeries,
    DashboardSourceHealth,
    RealtimeDashboardSnapshot,
    render_realtime_dashboard_html,
)
from metroliza.industrial.realtime.replay import ReplayRequest, replay_industrial_stream


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "industrial_realtime"


def _snapshot() -> RealtimeDashboardSnapshot:
    return RealtimeDashboardSnapshot(
        generated_at="2026-06-13T10:05:00Z",
        source_health=(
            DashboardSourceHealth(
                source_name="Assembly MES",
                status="running",
                last_success_at="2026-06-13T10:04:50Z",
                last_event_time="2026-06-13T10:04:00Z",
                lag_seconds=6.5,
                open_events=1,
            ),
        ),
        signals=(
            DashboardSignalSeries(
                signal_id=10,
                signal_key="cycle_time",
                metric_name="cycle_time_s",
                unit="s",
                source_name="Assembly MES",
                samples=(
                    DashboardSamplePoint(
                        sample_id=1,
                        event_time="2026-06-13T10:00:00Z",
                        value=10.2,
                    ),
                    DashboardSamplePoint(
                        sample_id=2,
                        event_time="2026-06-13T10:01:00Z",
                        value=13.5,
                    ),
                ),
                events=(
                    DashboardAnomalyEvent(
                        event_id=90,
                        sample_id=2,
                        signal_id=10,
                        signal_key="cycle_time",
                        event_time="2026-06-13T10:01:00Z",
                        severity="critical",
                        detector_key="spec_limits",
                        observed_value=13.5,
                        expected_value=12.0,
                        explanation="Observed value is above USL.",
                    ),
                ),
            ),
        ),
    )


def test_static_dashboard_renders_required_sections_cards_tables_and_chart() -> None:
    html = render_realtime_dashboard_html(_snapshot())

    assert html.startswith("<!doctype html>")
    assert 'data-section="summary-cards"' in html
    assert 'data-section="open-events"' in html
    assert 'data-section="severity-timeline"' in html
    assert 'data-section="top-signals"' in html
    assert 'data-section="sample-aggregates"' in html
    assert 'data-section="source-health"' in html
    assert 'data-section="signal-charts"' in html
    assert "Open events" in html
    assert "cycle_time_s (s)" in html
    assert "spec_limits" in html
    assert "observed-line" in html
    assert "anomaly-marker severity-critical" in html
    assert "<script" not in html.lower()


def test_service_like_mapping_output_is_normalized_and_escaped() -> None:
    html = render_realtime_dashboard_html(
        {
            "title": "Realtime <Dashboard>",
            "generated_at": "2026-06-13T11:00:00Z",
            "source_health": [
                {
                    "source_name": "Assembly <Line>",
                    "status": "idle",
                    "last_error": "operator entered <unsafe>",
                }
            ],
            "signals": [
                {
                    "id": 20,
                    "signal_key": "pressure",
                    "metric_name": "press<ure>",
                    "unit": "bar",
                    "samples": [
                        {"id": 4, "event_time": "2026-06-13T11:00:00Z", "value": 4.2},
                    ],
                }
            ],
            "open_events": [
                {
                    "id": 99,
                    "sample_id": 4,
                    "signal_id": 20,
                    "signal_key": "pressure",
                    "event_time": "2026-06-13T11:00:00Z",
                    "severity": "warning",
                    "detector_key": "iqr",
                    "observed_value": 4.2,
                    "explanation": "<script>alert('x')</script>",
                    "status": "open",
                }
            ],
        }
    )

    assert "Realtime &lt;Dashboard&gt;" in html
    assert "Assembly &lt;Line&gt;" in html
    assert "press&lt;ure&gt; (bar)" in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert "<script>alert" not in html
    assert "anomaly-marker severity-warning" in html


def test_service_source_health_prefers_operator_health_over_raw_status() -> None:
    html = render_realtime_dashboard_html(
        {
            "generated_at": "2026-06-13T11:30:00Z",
            "source_health": [
                {
                    "profile_name": "Assembly",
                    "stream_key": "cycle_time",
                    "status": "running",
                    "health": "lagging",
                    "lag_seconds": 999.0,
                    "last_success_at": "2026-06-13T11:00:00Z",
                }
            ],
        }
    )

    assert "<th>Health</th>" in html
    assert "status-lagging" in html
    assert ">lagging</span>" in html
    assert '<span class="status status-running">' not in html


def test_static_dashboard_renders_sample_aggregates_without_open_events() -> None:
    html = render_realtime_dashboard_html(
        RealtimeDashboardSnapshot(
            generated_at="2026-06-13T12:30:00Z",
            signals=(
                DashboardSignalSeries(
                    signal_id=10,
                    signal_key="cycle_time",
                    metric_name="cycle_time_s",
                    unit="s",
                    source_name="Assembly MES",
                    samples=(
                        DashboardSamplePoint(
                            sample_id=1,
                            event_time="2026-06-13T12:00:00Z",
                            value=10.0,
                        ),
                        DashboardSamplePoint(
                            sample_id=2,
                            event_time="2026-06-13T12:01:00Z",
                            value=13.5,
                        ),
                    ),
                ),
            ),
            aggregate_rows=(
                DashboardAggregateRow(
                    signal_id=10,
                    signal_key="cycle_time",
                    metric_name="cycle_time_s",
                    unit="s",
                    source_name="Assembly MES",
                    sample_count=3,
                    minimum=10.0,
                    average=12.0,
                    maximum=13.5,
                    latest_value=13.5,
                    nominal=10.0,
                    lsl=8.0,
                    usl=12.0,
                    above_usl_count=2,
                    nok_count=2,
                    nok_pct=2 / 3,
                    first_event_time="2026-06-13T12:00:00Z",
                    last_event_time="2026-06-13T12:02:00Z",
                ),
            ),
        )
    )

    assert "No open persisted anomaly events in this snapshot." in html
    assert "Sample Aggregates" in html
    assert "cycle_time_s (s)" in html
    assert "2 (66.7%)" in html
    assert "LSL 8 / NOM 10 / USL 12" in html
    assert "2026-06-13T12:00:00Z to 2026-06-13T12:02:00Z" in html
    assert "observed-line" in html


def test_secret_like_text_is_redacted_before_rendering() -> None:
    html = render_realtime_dashboard_html(
        RealtimeDashboardSnapshot(
            title="Ops dashboard password=hunter2",
            generated_at="2026-06-13T12:00:00Z",
            source_health=(
                DashboardSourceHealth(
                    source_name="Server=sql01;User Id=metroliza;Password=hunter2;Database=ops",
                    status="error",
                    last_error="token=abc123 Bearer rawtoken",
                ),
            ),
            signals=(
                DashboardSignalSeries(
                    signal_key="temperature",
                    metric_name="postgresql://operator:dbpass@db.internal/ops",
                    samples=(
                        DashboardSamplePoint(
                            event_time="2026-06-13T12:00:00Z",
                            value=31.0,
                            sample_id=1,
                        ),
                    ),
                    events=(
                        DashboardAnomalyEvent(
                            event_time="2026-06-13T12:00:00Z",
                            severity="major",
                            detector_key="mad_zscore",
                            observed_value=31.0,
                            explanation=(
                                "api_key=KEY-123 "
                                "connection_string=Server=prod;Password=secret;"
                            ),
                            sample_id=1,
                            signal_key="temperature",
                        ),
                    ),
                ),
            ),
        )
    )

    assert "hunter2" not in html
    assert "abc123" not in html
    assert "rawtoken" not in html
    assert "KEY-123" not in html
    assert "dbpass" not in html
    assert "Server=sql01" not in html
    assert "Password=hunter2" not in html
    assert "operator:dbpass" not in html
    assert "[redacted" in html


def test_static_dashboard_renders_from_replay_populated_database(tmp_path) -> None:
    db_path = str(tmp_path / "replay-dashboard.db")
    profile = IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly",
        profile_name="Assembly",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="dbo.events",
    )
    replay_industrial_stream(
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

    html = render_realtime_dashboard_html(RealtimeDashboardService(db_path).dashboard_snapshot())

    assert "Real-time Industrial Monitoring" in html
    assert "spec_limits" in html
    assert "critical" in html
    assert "Observed value 13.5 is above USL 12" in html
    assert 'data-section="signal-charts"' in html
