from contextlib import closing
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    script_path = REPO_ROOT / "scripts" / "calibrate_realtime_anomaly_models.py"
    module_name = "test_calibrate_realtime_anomaly_models"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_calibration_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE industrial_signal_definitions (
                id INTEGER PRIMARY KEY,
                source_profile_id INTEGER NOT NULL,
                signal_key TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                unit TEXT,
                nominal REAL,
                lsl REAL,
                usl REAL,
                lower_warning REAL,
                upper_warning REAL
            );
            CREATE TABLE industrial_samples (
                id INTEGER PRIMARY KEY,
                source_profile_id INTEGER NOT NULL,
                signal_id INTEGER NOT NULL,
                source_record_key TEXT NOT NULL,
                event_time TEXT NOT NULL,
                value REAL NOT NULL
            );
            INSERT INTO industrial_signal_definitions (
                id,
                source_profile_id,
                signal_key,
                metric_name,
                unit,
                nominal,
                lsl,
                usl,
                lower_warning,
                upper_warning
            )
            VALUES (101, 7, 'cycle_time', 'cycle_time_s', 's', 10.0, 8.0, 12.0, 9.0, 11.0);
            """
        )
        samples = [
            (1, 7, 101, "TRAIN-1", "2026-06-13T00:00:00Z", 10.00),
            (2, 7, 101, "TRAIN-2", "2026-06-13T01:00:00Z", 10.05),
            (3, 7, 101, "TRAIN-3", "2026-06-13T02:00:00Z", 9.95),
            (4, 7, 101, "TRAIN-4", "2026-06-13T03:00:00Z", 10.10),
            (5, 7, 101, "TRAIN-5", "2026-06-13T04:00:00Z", 9.90),
            (6, 7, 101, "VALID-1", "2026-06-14T00:00:00Z", 10.00),
            (7, 7, 101, "VALID-2", "2026-06-14T01:00:00Z", 10.20),
            (8, 7, 101, "VALID-3", "2026-06-14T02:00:00Z", 12.80),
        ]
        connection.executemany(
            """
            INSERT INTO industrial_samples (
                id,
                source_profile_id,
                signal_id,
                source_record_key,
                event_time,
                value
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            samples,
        )


def test_calibration_script_help_lists_required_inputs(capsys):
    module = _load_script_module()

    with pytest.raises(SystemExit) as excinfo:
        module.main(["--help"])

    output = capsys.readouterr().out
    assert excinfo.value.code == 0
    assert "--db" in output
    assert "--signal-id" in output
    assert "--signal-key" in output
    assert "--training-start" in output
    assert "--validation-end" in output
    assert "--contamination-candidates" in output
    assert "--dry-run" in output


def test_calibration_script_dry_run_writes_report_without_optional_ml_deps(
    tmp_path,
    capsys,
    monkeypatch,
):
    module = _load_script_module()
    monkeypatch.setattr(
        module,
        "_ensure_optional_ml_dependencies",
        lambda: pytest.fail("dry-run should not check sklearn availability"),
    )
    db_path = tmp_path / "calibration.db"
    output_path = tmp_path / "calibration-report.json"
    _write_calibration_db(db_path)

    result = module.main(
        [
            "--db",
            str(db_path),
            "--signal-id",
            "101",
            "--training-start",
            "2026-06-13T00:00:00Z",
            "--training-end",
            "2026-06-14T00:00:00Z",
            "--validation-start",
            "2026-06-14T00:00:00Z",
            "--validation-end",
            "2026-06-15T00:00:00Z",
            "--contamination-candidates",
            "0.01,0.05",
            "--output",
            str(output_path),
            "--dry-run",
        ]
    )

    stdout = capsys.readouterr().out
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert "Dry-run report: cycle_time" in stdout
    assert report["mode"] == "dry_run"
    assert report["dry_run"] is True
    assert report["signal"]["id"] == 101
    assert report["windows"]["training"]["summary"]["count"] == 5
    assert report["windows"]["validation"]["summary"]["count"] == 3
    assert report["optional_dependency_guidance"]["package"] == "scikit-learn"
    assert len(report["candidate_summaries"]) == 2
    assert report["recommended_config"]["detector_type"] == "optional_ml_isolation_forest"
    assert report["recommended_config"]["enabled"] is False
