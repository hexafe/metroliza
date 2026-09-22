"""Independent W06 comparator controls; synthetic rows do not qualify an EXE."""

from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from scripts import qualify_windows_candidate_core as driver
from scripts.verify_group_inference import InferenceMismatch, verify
from tests.test_windows_candidate_core_protocol import _complete_synthetic_artifacts
from tests.windows_candidate_inference_cases import create_inference_case


def test_comparison_preserves_closed_wal_database_and_rejects_active_writer(tmp_path):
    database, artifact = tmp_path / "inference.sqlite", tmp_path / "inference.json"
    create_inference_case(database, artifact)
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    before = database.read_bytes()
    verify(database, artifact)
    assert database.read_bytes() == before
    assert not any(
        database.with_name(database.name + suffix).exists()
        for suffix in ("-wal", "-shm", "-journal")
    )
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA user_version=1")
        writer.commit()
        wal = database.with_name(database.name + "-wal")
        before = (database.read_bytes(), wal.read_bytes())
        with pytest.raises(InferenceMismatch, match="^database_sidecars$"):
            verify(database, artifact)
        assert (database.read_bytes(), wal.read_bytes()) == before


@pytest.mark.parametrize("change", ["measurement", "assignment", "p_value", "effect_size"])
def test_updated_digest_cannot_hide_semantically_changed_inference(tmp_path, change):
    payload, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    key = "inference_database" if change == "measurement" else "group_inference"
    path = child / payload["artifacts"][key]["path"]
    if change == "measurement":
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE report_measurements SET meas=10.5 WHERE id=1")
            connection.commit()
    else:
        data = json.loads(path.read_text())
        if change == "assignment":
            data["assignments"]["REF001_2024-01-01_1.pdf"] = "B"
        else:
            data["analysis"]["metric_rows"][0]["pairwise_rows"][0][change] = 0.9
        path.write_text(json.dumps(data))
    payload["artifacts"][key]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(driver.CandidateFailure, match="^independent_inference_oracle_failed$"):
        driver._copy_verified_results(tmp_path, payload, output, oracle)
    assert not list(output.iterdir())


@pytest.mark.parametrize("phase", ["scenario", "retained"])
def test_inference_comparison_cannot_create_hidden_sidecar(tmp_path, monkeypatch, phase):
    payload, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    calls = []

    def adverse_verifier(database, artifact):
        verify(database, artifact)
        calls.append(database)
        if len(calls) == (1 if phase == "scenario" else 2):
            database.with_name(database.name + "-shm").write_bytes(b"side effect")

    monkeypatch.setattr(driver, "_independent_inference_verifier", lambda: adverse_verifier)
    with pytest.raises(
        driver.CandidateFailure, match=f"^{phase}_database_sidecars_created_after_comparison$"
    ):
        driver._copy_verified_results(tmp_path, payload, output, oracle)


@pytest.mark.parametrize("reader", ["_report_ids_by_filename", "_database_counts"])
def test_application_inference_snapshot_read_creates_no_sidecars_and_rejects_live_writer(tmp_path, reader):
    from metroliza.app import windows_candidate_inference as application

    database = tmp_path / "inference.sqlite"
    create_inference_case(database, tmp_path / "inference.json")
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    before = database.read_bytes()
    assert not any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    assert getattr(application, reader)(database)
    assert database.read_bytes() == before
    assert not any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA user_version=7")
        writer.commit()
        wal = database.with_name(database.name + "-wal")
        before = (database.read_bytes(), wal.read_bytes())
        with pytest.raises(application.InferenceFailure, match="^database_snapshot_not_closed$"):
            getattr(application, reader)(database)
        assert (database.read_bytes(), wal.read_bytes()) == before
