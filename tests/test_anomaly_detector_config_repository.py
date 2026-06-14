from metroliza.industrial.anomaly.contracts import DetectorConfig
from metroliza.industrial.anomaly.detector_config_repository import DetectorConfigRepository


def test_detector_config_repository_upserts_and_filters_enabled_configs(tmp_path):
    db_path = str(tmp_path / "detectors.db")
    repository = DetectorConfigRepository(db_path)

    first = repository.upsert_config(
        DetectorConfig(
            detector_key="cycle_time_spec",
            detector_type="spec_limits",
            parameters={"usl": 12.0},
            severity_map={"warning": "major"},
        )
    )
    updated = repository.upsert_config(
        DetectorConfig(
            detector_key="cycle_time_spec",
            detector_type="spec_limits",
            parameters={"usl": 13.0},
            enabled=False,
        )
    )

    assert first.id == updated.id
    assert updated.parameters == {"usl": 13.0}
    assert repository.list_configs() == []
    assert repository.list_configs(include_disabled=True)[0].detector_key == "cycle_time_spec"
