"""Fresh-process reopen and fail-closed protocol controls; source is not EXE proof."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import sqlite3
import shutil
from contextlib import closing
from types import SimpleNamespace

import pytest

from metroliza.app import windows_candidate_qualification as application
from metroliza.app import windows_candidate_reopen as reopen
from metroliza.app.bootstrap import get_or_create_qapplication
from scripts import qualify_windows_candidate_core as core
from scripts import qualify_windows_diagnostics as diag
from tests.test_windows_candidate_reopen import _seed_completed_import
from tests.test_windows_candidate_launch_ownership import _interrupt_after_launch_before_store


def runtime_receipt(database_hash="a" * 64, source="b" * 40):
    return {"schema_version": 1, "scenario": "reopen", "status": "passed", "packaged": True,
            "qpa": "windows", "ordinary_user": True, "source_sha": source,
            "observation": {"schema_version": 1, "status": "passed",
                "facets": {"reopen_preserves_completed_import": "passed"},
                "database": {"sha256": database_hash, "before_sha256": database_hash,
                    "schema_sha256": "c" * 64, "logical_dump_sha256": "d" * 64,
                    "counts": dict.fromkeys(("source_files", "active_locations", "parsed_reports", "metadata", "measurements"), 2)},
                "source_hashes": {f"REF001_2024-01-01_{i}.pdf": core.PUBLIC_FIXTURE_HASHES[f"report-{i}.pdf"] for i in range(5)}}}


@pytest.fixture(scope="session")
def retained_reopen_application():
    # The Qt application outlives every window and subsequent test module.
    # A source subprocess is used for the actual fresh application boundary.
    return get_or_create_qapplication()


def test_actual_separate_source_process_reopens_completed_import_without_data_changes(tmp_path, retained_reopen_application):
    app = retained_reopen_application
    first = tmp_path / "core scenario" / ("core-" + "a" * 32)
    first.mkdir(parents=True)
    database, reports, hashes = _seed_completed_import(app, first)
    prior = reopen.run_reopen_checks(database, reports, hashes)
    assert prior["status"] == "passed"
    root = tmp_path / "fresh reopen"
    root.mkdir()
    state = tmp_path / "isolated state"
    state.mkdir()
    checkout = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("METROLIZA_")}
    env.update({name: "1" for name in application.GATES})
    env.update({application.ROOT_ENV: str(root), "METROLIZA_WINDOWS_CANDIDATE_PHASE": "reopen",
                "METROLIZA_WINDOWS_CANDIDATE_REOPEN_INPUT": str(first),
                "METROLIZA_WINDOWS_CANDIDATE_REOPEN_SHA256": core._hash(database),
                "PYTHONPATH": str(checkout / "src"), "GSETTINGS_BACKEND": "memory",
                "QT_QPA_PLATFORM": app.platformName(), "QT_STYLE_OVERRIDE": "Fusion",
                "XDG_STATE_HOME": str(state), "XDG_CONFIG_HOME": str(state), "XDG_CACHE_HOME": str(state),
                "LOCALAPPDATA": str(state), "APPDATA": str(state)})
    result = subprocess.run([sys.executable, str(checkout / "packaging/metroliza_package_entry.py")],
                            cwd=state, env=env, capture_output=True, timeout=45)
    payload = json.loads((root / "fresh-reopen-result.json").read_bytes())
    assert result.returncode == 0, payload
    assert payload["status"] == "passed" and payload["packaged"] is False
    assert payload["qpa"] == app.platformName()
    assert payload["observation"]["database"] == dict(prior["database"], before_sha256=prior["database"]["sha256"], sha256=core._hash(database))
    assert payload["observation"]["source_hashes"] == hashes


@pytest.mark.parametrize("fault", ["source", "qpa", "head", "database", "source_files", "not_completed"])
def test_fresh_reopen_rejects_wrong_runtime_or_input(fault):
    value = runtime_receipt()
    prior = {"artifacts": {"database": {"sha256": "a" * 64}},
             "reopen_database": copy.deepcopy(value["observation"]["database"]),
             "source_hashes": copy.deepcopy(value["observation"]["source_hashes"])}
    if fault == "source":
        value["packaged"] = False
    elif fault == "qpa":
        value["qpa"] = "offscreen"
    elif fault == "head":
        value["source_sha"] = "e" * 40
    elif fault == "database":
        value["observation"]["database"]["sha256"] = "e" * 64
    elif fault == "source_files":
        value["observation"]["source_hashes"] = {}
    else:
        value["status"] = "failed"
    with pytest.raises(core.CandidateFailure):
        core._validate_fresh_reopen(value, prior, "b" * 40)


def test_fresh_reopen_refuses_input_outside_owned_prior_sibling(tmp_path, monkeypatch):
    root = tmp_path / "fresh reopen"
    root.mkdir()
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_REOPEN_INPUT", str(tmp_path / "user data"))
    with pytest.raises(reopen.ReopenScenarioFailure, match="fresh_reopen_input_not_owned_sibling"):
        reopen._fresh_input(root)


def test_fresh_process_launch_transfer_interrupt_closes_registered_job(tmp_path, monkeypatch):
    root = tmp_path / "core scenario"
    child = root / ("core-" + "a" * 32)
    child.mkdir(parents=True)
    database = child / "reports.sqlite"
    database.write_bytes(b"synthetic launch boundary fixture")
    calls = []
    primary = KeyboardInterrupt("primary")
    class Process:
        def close(self, *, terminate):
            calls.append(terminate)
            raise SystemExit("secondary")
    class Api:
        def launch(self, executable, env, cwd, owned=None, expected_images=None):
            assert env["METROLIZA_WINDOWS_CANDIDATE_PHASE"] == "reopen"
            assert env["METROLIZA_WINDOWS_CANDIDATE_REOPEN_SHA256"] == core._hash(database)
            assert cwd != Path(env[application.ROOT_ENV])
            owned.append(Process())
            return owned[-1]
    monkeypatch.setattr(core, "_validate_reopen_sources", lambda _reports: None)
    monkeypatch.setattr(core, "_independent_verifier", lambda: SimpleNamespace(
        _load_oracle=lambda _path: {}, assert_database=lambda *args: None,
    ))
    dependency = SimpleNamespace(_WindowsApi=Api, _close_owned_processes=diag._close_owned_processes)
    prior = {"relative_artifact_dir": child.name, "artifacts": {"database": {"sha256": core._hash(database)}}}
    stage = {"name": "fresh_reopen"}
    with pytest.raises(KeyboardInterrupt) as caught:
        _interrupt_after_launch_before_store(core._run_fresh_reopen.__code__, primary,
            lambda: core._run_fresh_reopen(tmp_path, diag=dependency, relocated=tmp_path,
                environment={}, work=root, prior=prior, args=SimpleNamespace(expected_source_sha="b" * 40, oracle=tmp_path / "oracle.json"),
                deadline=time.monotonic() + 1, output=tmp_path, stage=stage))
    assert caught.value is primary
    assert calls == [True]
    assert stage["name"] == "fresh_reopen"


def test_fresh_reopen_keeps_closed_primary_after_real_cleanup_wrapper(tmp_path, monkeypatch):
    root = tmp_path / "core scenario"
    child = root / ("core-" + "a" * 32)
    child.mkdir(parents=True)
    database = child / "reports.sqlite"
    database.write_bytes(b"synthetic reopen boundary fixture")
    closed = []

    class Process:
        def observe(self):
            raise core.CandidateFailure("fresh_reopen_process_failed")

        def close(self, *, terminate):
            closed.append(terminate)
            diag._attempt_cleanup(lambda: None)

    class Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            process = Process()
            owned.append(process)
            return process

    monkeypatch.setattr(core, "_validate_reopen_sources", lambda _reports: None)
    monkeypatch.setattr(core, "_independent_verifier", lambda: SimpleNamespace(
        _load_oracle=lambda _path: {}, assert_database=lambda *args: None,
    ))
    dependency = SimpleNamespace(
        QualificationFailure=diag.QualificationFailure,
        _WindowsApi=Api, _close_owned_processes=diag._close_owned_processes,
    )
    prior = {"relative_artifact_dir": child.name, "artifacts": {"database": {"sha256": core._hash(database)}}}
    stage = {"name": "fresh_reopen"}
    with pytest.raises(core.CandidateFailure, match="^fresh_reopen_process_failed$"):
        core._run_fresh_reopen(
            tmp_path, diag=dependency, relocated=tmp_path, environment={}, work=root,
            prior=prior, args=SimpleNamespace(oracle=tmp_path / "oracle.json"),
            deadline=time.monotonic() + 1, output=tmp_path, stage=stage,
        )
    assert closed == [True]
    assert stage == {"name": "fresh_reopen"}


@pytest.mark.parametrize("fault", ["row", "schema", "user_version", "application_id", "baseline_copy", "post_replaced"])
def test_host_reopen_oracle_rejects_actual_database_mutation(tmp_path, fault):
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    with closing(sqlite3.connect(before)) as connection, connection:
        connection.execute("CREATE TABLE measurements (value INTEGER)")
        connection.execute("INSERT INTO measurements VALUES (12)")
    shutil.copyfile(before, after)
    baseline_hash, original_hash = core._hash(before), core._hash(after)
    target = before if fault == "baseline_copy" else after
    if fault == "post_replaced":
        after.write_bytes(b"substituted")
    else:
        with closing(sqlite3.connect(target)) as connection, connection:
            if fault in {"row", "baseline_copy"}:
                connection.execute("UPDATE measurements SET value = 13")
            elif fault == "schema":
                connection.execute("CREATE INDEX changed_schema ON measurements(value)")
            elif fault == "user_version":
                connection.execute("PRAGMA user_version=42")
            else:
                connection.execute("PRAGMA application_id=42")
    with pytest.raises(core.CandidateFailure):
        core._assert_reopen_databases_preserved(before, after, before_hash=baseline_hash,
            after_hash=original_hash if fault == "post_replaced" else core._hash(after))


def test_host_reopen_sources_rejects_changed_public_input(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    fixtures = Path(__file__).parent / "fixtures/windows_candidate/reports"
    for i in range(5):
        shutil.copyfile(fixtures / f"report-{i}.pdf", reports / f"REF001_2024-01-01_{i}.pdf")
    core._validate_reopen_sources(reports)
    (reports / "REF001_2024-01-01_1.pdf").write_bytes(b"changed public input")
    with pytest.raises(core.CandidateFailure, match="fresh_reopen_sources_changed"):
        core._validate_reopen_sources(reports)


def test_host_reopen_oracle_rejects_invalid_sqlite_with_closed_failure(tmp_path):
    database = tmp_path / "invalid.sqlite"
    database.write_bytes(b"not a SQLite database" * 32)
    with pytest.raises(core.CandidateFailure, match="fresh_reopen_database_invalid"):
        core._reopen_database_semantics(database)
