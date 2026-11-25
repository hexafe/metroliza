"""Check the opt-in profile probe's source behavior and independent SQLite proof."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from metroliza.app.windows_candidate_profile import run_profile_probe
from metroliza.app.windows_candidate_qualification import ScenarioFailure
from metroliza.parsing.parser_plugin_paths import invalidate_parser_plugin_runtime
from metroliza.parsing.preflight import ParsePreflightService
from metroliza.ui.parser_preflight_worker import ParsePreflightThread
from scripts.qualify_windows_candidate_core import (
    CandidateFailure, SCENARIO_FILE, _child_failure_observation, _configure_profile_import_probe,
    _profile_import_probe_evidence, _verify_profile_import_probe,
)


@pytest.mark.parametrize("parent_alias", [False, True], ids=["direct", "aliased-parent"])
def test_real_reports_profile_probe_and_independent_oracle(qapplication_session, tmp_path, monkeypatch, parent_alias):
    private = tmp_path
    if parent_alias:
        real_parent = tmp_path / "real"
        real_parent.mkdir()
        alias = tmp_path / "parent alias"
        try:
            alias.symlink_to(real_parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("directory symlinks are unavailable")
        private = alias / "private"
        private.mkdir()
    work = private / "qualification"
    child = work / ("core-" + "b" * 32)
    child.mkdir(parents=True)
    profile_home = private / "profile-probe-home"
    profile_home.mkdir()
    scratch = child / "profile-import"
    with monkeypatch.context() as environment:
        environment.setattr(Path, "home", classmethod(lambda cls: profile_home))
        environment.delenv("PARSER_EXTERNAL_PLUGIN_PATHS", raising=False)
        environment.delenv("PARSER_DISABLED_PLUGIN_IDS", raising=False)
        try:
            probe = run_profile_probe(scratch, profile_home, qapplication_session)
        finally:
            invalidate_parser_plugin_runtime()
    payload = {"relative_artifact_dir": child.name, "profile_import_probe": probe}
    verified = _verify_profile_import_probe(work, payload)
    database = scratch / "profile-import.sqlite"
    assert verified["database_sha256"] == probe["database_sha256"]
    assert verified["observation"] == {
        "parser_id": "synthetic_package_profile", "parser_version": "0.1.0",
        "template_variant": "synthetic_package_template", "measurement_count": 2, "nok_count": 1,
    }
    assert str(tmp_path) not in repr(verified)

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE report_measurements SET meas = 999 WHERE ax = 'X'")
    probe["database_sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    with pytest.raises(CandidateFailure, match="profile_probe_report_or_rows_mismatch"):
        _verify_profile_import_probe(work, payload)


@pytest.mark.parametrize(
    ("fault", "failure"),
    [
        ("failed_scan", "profile_probe_unapproved_no_fresh_review"),
        ("different_source", "profile_probe_unapproved_source_path"),
        ("missing_source", "profile_probe_unapproved_source_unavailable"),
    ],
)
def test_failed_reports_scan_cannot_trigger_profile_approval(qapplication_session, tmp_path, monkeypatch, fault, failure):
    profile_home = tmp_path / "profile-probe-home"
    profile_home.mkdir()
    scratch = tmp_path / "qualification"
    scanned = []

    def fail_scan(self):
        scanned.append(Path(self.source_path))
        self.failed.emit("synthetic scanner failure")

    inspect = ParsePreflightService._inspect_file

    def change_inspected_source(path, **kwargs):
        scanned.append(path.parent)
        inspected = inspect(path, **kwargs)
        other = scratch / "different-location" / path.name
        if fault == "different_source":
            other.parent.mkdir()
            other.hardlink_to(path)
            assert other.samefile(path) and other.resolve(strict=True) != path.resolve(strict=True)
        return replace(inspected, source_path=str(other))

    def unexpected_approval(*args, **kwargs):
        pytest.fail("profile approval started after the Reports scan failed")

    with monkeypatch.context() as environment:
        environment.setattr(Path, "home", classmethod(lambda cls: profile_home))
        environment.delenv("PARSER_EXTERNAL_PLUGIN_PATHS", raising=False)
        environment.delenv("PARSER_DISABLED_PLUGIN_IDS", raising=False)
        if fault == "failed_scan":
            environment.setattr(ParsePreflightThread, "run", fail_scan)
        else:
            environment.setattr(ParsePreflightService, "_inspect_file", staticmethod(change_inspected_source))
        environment.setattr("metroliza.parsing.declarative_parser_profiles.install_profile", unexpected_approval)
        try:
            with pytest.raises(ScenarioFailure, match=f"^{failure}$"):
                run_profile_probe(scratch, profile_home, qapplication_session)
        finally:
            invalidate_parser_plugin_runtime()
    assert scanned == [scratch / "samples"]
    assert not (profile_home / ".metroliza" / "parser_plugins" / "profiles" / "approved").exists()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("profile_probe_unapproved_source_path", "valid_allowlisted"),
        ("profile_probe_approved_status_unreadable", "valid_allowlisted"),
        ("profile_probe_unapproved_C:/private/synthetic.pdf", "valid_unclassified"),
    ],
)
def test_host_retains_only_closed_profile_probe_failures(tmp_path, failure, expected):
    source = "a" * 40
    (tmp_path / SCENARIO_FILE).write_text(json.dumps({
        "schema": "metroliza-windows-candidate-core-v1", "schema_version": 1,
        "scenario": "core", "stage": "profile_import", "status": "failed",
        "source_sha": source, "failure": failure,
    }), encoding="ascii")
    observation = _child_failure_observation(tmp_path, source)
    assert observation["receipt_state"] == expected and observation["producer_stage"] == "profile_import"
    retained = failure if expected == "valid_allowlisted" else "unavailable"
    assert observation["allowlisted_failure"] == retained
    assert "C:/private/" not in json.dumps(observation)


@pytest.mark.parametrize("unsafe_override", ["ambient_home", "external_path", "disabled_profile"])
def test_probe_rejects_unowned_profile_resolution_before_creating_inputs(
    tmp_path, monkeypatch, unsafe_override,
):
    profile_home = tmp_path / "profile-probe-home"
    profile_home.mkdir()
    alternate = tmp_path / "unowned-default"
    monkeypatch.setattr(Path, "home", classmethod(
        lambda cls: alternate if unsafe_override == "ambient_home" else profile_home
    ))
    monkeypatch.delenv("PARSER_EXTERNAL_PLUGIN_PATHS", raising=False)
    monkeypatch.delenv("PARSER_DISABLED_PLUGIN_IDS", raising=False)
    if unsafe_override == "external_path":
        monkeypatch.setenv("PARSER_EXTERNAL_PLUGIN_PATHS", str(alternate))
    if unsafe_override == "disabled_profile":
        monkeypatch.setenv("PARSER_DISABLED_PLUGIN_IDS", "synthetic_package_profile")
    scratch = tmp_path / "inputs"
    with pytest.raises(ScenarioFailure, match="profile_probe_home_mismatch"):
        run_profile_probe(scratch, profile_home, None)
    assert not scratch.exists()
    assert not alternate.exists()
    assert not list(profile_home.iterdir())


def test_only_opt_in_launch_replaces_ambient_profile_and_requires_evidence(tmp_path):
    ambient = {
        "USERPROFILE": "ambient", "HOMEDRIVE": "C:", "HOMEPATH": "ambient-path",
        "PARSER_EXTERNAL_PLUGIN_PATHS": "external", "PARSER_DISABLED_PLUGIN_IDS": "disabled",
    }
    environment = ambient.copy()
    _configure_profile_import_probe(environment, tmp_path, False)
    assert environment == ambient
    assert not list(tmp_path.iterdir())
    assert _profile_import_probe_evidence(tmp_path, {}, False) == {}

    _configure_profile_import_probe(environment, tmp_path, True)
    isolated = tmp_path / "profile-probe-home"
    assert isolated.is_dir()
    assert environment == {
        "USERPROFILE": str(isolated), "HOMEDRIVE": isolated.drive,
        "HOMEPATH": str(isolated)[len(isolated.drive):], "METROLIZA_WINDOWS_CANDIDATE_PROFILE_IMPORT": "1",
    }
    with pytest.raises(CandidateFailure, match="profile_probe_runtime_evidence_missing"):
        _profile_import_probe_evidence(tmp_path, {}, True)
