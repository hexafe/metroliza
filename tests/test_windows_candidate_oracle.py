"""Regression coverage for the independent SQLite acceptance comparator."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts import qualify_windows_candidate_core as driver
from scripts import verify_synthetic_oracle as verifier


ORACLE = Path(__file__).resolve().parents[1] / "scripts" / "synthetic-report-oracle.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecars(database: Path) -> tuple[Path, ...]:
    return tuple(
        database.with_name(database.name + suffix)
        for suffix in ("-wal", "-shm", "-journal")
        if database.with_name(database.name + suffix).exists()
    )


def _oracle_database(tmp_path: Path) -> Path:
    database = tmp_path / "reports.sqlite"
    verifier._create_synthetic_database(verifier._load_oracle(ORACLE), database)
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("PRAGMA user_version = 1")
        writer.commit()
    assert not _sidecars(database)
    return database


def test_database_comparator_preserves_fresh_database_bytes_and_sidecar_set(tmp_path):
    database = _oracle_database(tmp_path)
    before = _digest(database)

    verifier.assert_database(verifier._load_oracle(ORACLE), database)

    assert _digest(database) == before
    assert not _sidecars(database)


def test_database_comparator_rejects_and_preserves_active_wal(tmp_path):
    database = _oracle_database(tmp_path)
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("PRAGMA user_version = 1")
        writer.commit()
        sidecars = _sidecars(database)
        assert database.with_name(database.name + "-wal") in sidecars
        before = (_digest(database), {path.name: path.read_bytes() for path in sidecars})

        with pytest.raises(verifier.OracleMismatch, match="database.sidecars: active journal sidecar present"):
            verifier.assert_database(verifier._load_oracle(ORACLE), database)

        assert (_digest(database), {path.name: path.read_bytes() for path in sidecars}) == before


def _payload(child: Path) -> dict:
    paths = {
        "database": child / "reports.sqlite",
        "workbook": child / "report.xlsx",
        "grouping": child / "grouping.json",
        "tabular": child / "tabular.json",
        "literal_workbook": child / "literal.xlsx",
        "inference_database": child / "inference.sqlite",
        "group_inference": child / "inference.json",
    }
    for key, path in paths.items():
        path.write_bytes(key.encode("ascii"))
    return {
        "relative_artifact_dir": child.name,
        "artifacts": {key: {"path": path.name, "sha256": _digest(path)} for key, path in paths.items()},
    }


@pytest.mark.parametrize(
    ("phase", "expected"),
    (
        ("scenario", "scenario_database_sidecars_created_after_comparison"),
        ("retained", "retained_database_sidecars_created_after_comparison"),
    ),
)
def test_copy_rejects_sidecars_created_by_comparison(tmp_path, monkeypatch, phase, expected):
    child = tmp_path / ("core-" + "a" * 32)
    child.mkdir()
    payload = _payload(child)
    output = tmp_path / "retained"
    output.mkdir()
    calls = []

    def core_verifier(_oracle, database, *_unused):
        calls.append(database)
        if (phase == "scenario" and len(calls) == 1) or (phase == "retained" and len(calls) == 2):
            database.with_name(database.name + "-shm").write_bytes(b"comparator-sidecar")

    monkeypatch.setattr(driver, "_independent_verifier", lambda: core_verifier)
    monkeypatch.setattr(driver, "_independent_xlsx_verifier", lambda: lambda _workbook: None)
    monkeypatch.setattr(driver, "_independent_inference_verifier", lambda: lambda *_args: None)

    with pytest.raises(driver.CandidateFailure, match=expected):
        driver._copy_verified_results(tmp_path, payload, output, ORACLE)


@pytest.mark.parametrize(
    ("phase", "expected"),
    (
        ("scenario", "scenario_artifact_changed_after_comparison"),
        ("retained", "retained_artifact_changed_after_comparison"),
    ),
)
def test_copy_rejects_artifact_hash_drift_after_comparison(tmp_path, monkeypatch, phase, expected):
    child = tmp_path / ("core-" + "b" * 32)
    child.mkdir()
    payload = _payload(child)
    output = tmp_path / "retained"
    output.mkdir()
    calls = []

    def core_verifier(_oracle, _database, workbook, *_unused):
        calls.append(workbook)
        if (phase == "scenario" and len(calls) == 1) or (phase == "retained" and len(calls) == 2):
            workbook.write_bytes(b"changed-by-comparator")

    monkeypatch.setattr(driver, "_independent_verifier", lambda: core_verifier)
    monkeypatch.setattr(driver, "_independent_xlsx_verifier", lambda: lambda _workbook: None)
    monkeypatch.setattr(driver, "_independent_inference_verifier", lambda: lambda *_args: None)

    with pytest.raises(driver.CandidateFailure, match=expected):
        driver._copy_verified_results(tmp_path, payload, output, ORACLE)
