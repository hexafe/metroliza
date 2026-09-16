"""Adverse protocol controls only; these do not execute or qualify an EXE."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import qualify_windows_candidate_core as driver

REPO = Path(__file__).resolve().parents[1]
ORACLE = REPO / "scripts/synthetic-report-oracle.json"
PROTOCOL_FIXTURES = REPO / "tests/fixtures/windows_candidate_protocol"
PUBLIC_FIXTURES = REPO / "tests/fixtures/windows_candidate"

SHA = "1" * 40


def payload():
    return {
        "schema_version": 1, "stage": "complete", "status": "passed",
        "packaged": True, "qpa": "windows", "ordinary_user": True,
        "source_sha": SHA, "relative_artifact_dir": "core-" + "a" * 32,
        "facets": {**{key: "passed" for key in driver.REQUIRED_CHECKS}, "group_analysis_status": "insufficient_groups"},
        "artifacts": {
            key: {"path": key + extension, "sha256": "2" * 64}
            for key, extension in zip(driver.ARTIFACTS, (".sqlite", ".xlsx", ".json", ".json", ".xlsx", ".sqlite", ".json"), strict=True)
        },
    }


def test_protocol_accepts_only_declared_native_complete_identity():
    sample = payload()
    assert driver.validate_runtime_receipt(sample, SHA) is sample


@pytest.mark.parametrize(("key", "value", "reason"), [
    ("schema_version", True, "invalid_runtime_receipt"),
    ("schema_version", 2, "invalid_runtime_receipt"),
    ("stage", "source_engineering_ready", "scenario_incomplete"),
    ("status", "failed", "scenario_incomplete"),
    ("packaged", False, "source_execution_is_not_package_evidence"),
    ("packaged", 1, "source_execution_is_not_package_evidence"),
    ("qpa", "offscreen", "native_ordinary_user_evidence_missing"),
    ("ordinary_user", False, "native_ordinary_user_evidence_missing"),
    ("ordinary_user", 1, "native_ordinary_user_evidence_missing"),
    ("source_sha", "0" * 40, "runtime_source_mismatch"),
    ("relative_artifact_dir", "../escape", "invalid_artifact_directory"),
    ("relative_artifact_dir", "C:\\escape", "invalid_artifact_directory"),
])
def test_rejects_nonqualifying_observation(key, value, reason):
    sample = payload()
    sample[key] = value
    with pytest.raises(driver.CandidateFailure, match="^" + reason + "$"):
        driver.validate_runtime_receipt(sample, SHA)


@pytest.mark.parametrize("key", driver.REQUIRED_CHECKS)
def test_missing_or_pending_facet_cannot_pass(key):
    sample = payload()
    for status in (None, "not_executed", "failed"):
        sample["facets"][key] = status
        with pytest.raises(driver.CandidateFailure, match="required_core_check_incomplete"):
            driver.validate_runtime_receipt(sample, SHA)


def test_missing_or_extra_artifact_cannot_pass():
    original = payload()
    for key in driver.ARTIFACTS:
        sample = copy.deepcopy(original)
        del sample["artifacts"][key]
        with pytest.raises(driver.CandidateFailure, match="missing_scenario_artifact"):
            driver.validate_runtime_receipt(sample, SHA)
    original["artifacts"]["unverified"] = {"path": "extra.json", "sha256": "2" * 64}
    with pytest.raises(driver.CandidateFailure, match="missing_scenario_artifact"):
        driver.validate_runtime_receipt(original, SHA)


@pytest.mark.parametrize("name", ["../escape.json", "/escape.json", "C:\\escape.json", "grouping.json:stream", "grouping.json"])
def test_rejects_escape_stream_or_duplicate_artifact_name(name):
    sample = payload()
    sample["artifacts"]["database"]["path"] = name
    with pytest.raises(driver.CandidateFailure, match="invalid_artifact_record"):
        driver.validate_runtime_receipt(sample, SHA)


def test_rejects_malformed_digest_and_record():
    sample = payload()
    sample["artifacts"]["database"]["sha256"] = "not_a_digest"
    with pytest.raises(driver.CandidateFailure, match="invalid_artifact_record"):
        driver.validate_runtime_receipt(sample, SHA)
    sample = payload()
    sample["artifacts"]["database"]["extra"] = "unverified"
    with pytest.raises(driver.CandidateFailure, match="invalid_artifact_record"):
        driver.validate_runtime_receipt(sample, SHA)


def test_rejects_duplicate_json_and_oversized_receipt(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"packaged":false,"packaged":true}')
    with pytest.raises(driver.CandidateFailure, match="duplicate_receipt_field"):
        driver._json(receipt)
    receipt.write_bytes(b" " * (driver.MAX_RECEIPT_BYTES + 1))
    with pytest.raises(driver.CandidateFailure, match="unsafe_or_oversized_receipt"):
        driver._json(receipt)


def test_rejects_artifact_mutation_before_comparison_or_copy(tmp_path):
    sample = payload()
    child = tmp_path / sample["relative_artifact_dir"]
    child.mkdir()
    (child / "database.sqlite").write_bytes(b"different actual database")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(driver.CandidateFailure, match="scenario_artifact_hash_mismatch"):
        driver._copy_verified_results(tmp_path, sample, output, tmp_path / "unused-oracle.json")
    assert list(output.iterdir()) == []


def test_rejects_symlink_and_hardlink_artifact(tmp_path):
    original = tmp_path / "original.json"
    original.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(original)
    with pytest.raises(driver.CandidateFailure, match="unsafe_or_oversized_scenario_artifact"):
        driver._hash(link)
    link.unlink()
    link.hardlink_to(original)
    with pytest.raises(driver.CandidateFailure, match="unsafe_or_oversized_scenario_artifact"):
        driver._hash(link)


def test_rejects_directory_symlink_before_resolving(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(driver.CandidateFailure, match="unsafe_scenario_directory"):
        driver._input_directory(link)


def test_preserved_source_engineering_receipt_is_not_package_proof():
    actual = json.loads((PROTOCOL_FIXTURES / "core-source-engineering-receipt.json").read_text())
    with pytest.raises(driver.CandidateFailure):
        driver.validate_runtime_receipt(actual, SHA)


def test_independent_tabular_oracle_accepts_real_source_snapshot_and_rejects_corruption(tmp_path):
    from scripts.verify_synthetic_oracle import OracleMismatch, assert_tabular

    root = PROTOCOL_FIXTURES
    oracle = json.loads(ORACLE.read_text())
    original = json.loads((root / "w05-numeric-source-tabular.json").read_text())
    assert_tabular(oracle, root / "w05-numeric-source-tabular.json")
    mutations = []
    changed = copy.deepcopy(original)
    changed["files"]["finite-source.csv"]["filters"]["eq_zero"].append(4)
    mutations.append(changed)
    changed = copy.deepcopy(original)
    changed["files"]["integer-precision.csv"]["filters"]["9007199254740993"] = [1]
    mutations.append(changed)
    changed = copy.deepcopy(original)
    changed["files"]["integer-precision.csv"]["source_rows"][1][1] = 9007199254740992.0
    mutations.append(changed)
    changed = copy.deepcopy(original)
    changed["files"]["integer-precision.csv"]["source_rows"][0][0] = True
    mutations.append(changed)
    changed = copy.deepcopy(original)
    changed["files"]["finite-source.csv"]["sha256"] = "0" * 64
    mutations.append(changed)
    for changed in mutations:
        actual = tmp_path / "changed.json"
        actual.write_text(json.dumps(changed))
        with pytest.raises(OracleMismatch, match="tabular"):
            assert_tabular(oracle, actual)


def test_persisted_oracle_rejects_inactive_extra_location(tmp_path):
    import sqlite3
    from scripts.verify_synthetic_oracle import OracleMismatch, _create_synthetic_database, assert_database

    oracle = json.loads(ORACLE.read_text())
    database = tmp_path / "scratch.sqlite"
    _create_synthetic_database(oracle, database)
    assert_database(oracle, database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO source_file_locations VALUES (1, 'inactive.pdf', 0)")
    with pytest.raises(OracleMismatch, match="database.locations"):
        assert_database(oracle, database)


def test_original_nested_fixture_bundle_stages_only_reviewed_bytes(tmp_path):
    root = PUBLIC_FIXTURES
    staged = driver._stage_known_fixtures(root, tmp_path)
    assert {p.name for p in staged.iterdir()} == {
        "finite-source.csv", "integer-precision.csv", *(f"report-{i}.pdf" for i in range(5))
    }
    for target in staged.iterdir():
        original = root / ("reports" if target.suffix == ".pdf" else "") / target.name
        assert target.read_bytes() == original.read_bytes()


def test_mutated_public_fixture_is_rejected_before_launch(tmp_path):
    import shutil
    root = PUBLIC_FIXTURES
    prepared = tmp_path / "prepared"
    shutil.copytree(root, prepared)
    (prepared / "finite-source.csv").write_bytes(b"unexpected input")
    private = tmp_path / "private"
    private.mkdir()
    with pytest.raises(driver.CandidateFailure, match="prepared_fixture_hash_mismatch"):
        driver._stage_known_fixtures(prepared, private)


def test_independent_verifier_is_not_shadowed_by_source_checkout(tmp_path, monkeypatch):
    shadow = tmp_path / "verify_synthetic_oracle.py"
    shadow.write_text("raise AssertionError('unexpected shadow import')")
    monkeypatch.syspath_prepend(str(tmp_path))
    verify = driver._independent_verifier()
    assert Path(verify.__code__.co_filename).resolve() == (REPO / "scripts/verify_synthetic_oracle.py").resolve()


def test_unknown_facet_cannot_extend_acceptance_claim():
    sample = payload()
    sample["facets"]["unobserved_feature"] = "passed"
    with pytest.raises(driver.CandidateFailure, match="required_core_check_incomplete"):
        driver.validate_runtime_receipt(sample, SHA)


def _complete_synthetic_artifacts(tmp_path):
    from scripts.verify_synthetic_oracle import _create_synthetic_database, _create_synthetic_workbook
    from tests.windows_candidate_inference_cases import create_inference_case
    oracle_path = ORACLE
    oracle = json.loads(oracle_path.read_text())
    sample = payload()
    child = tmp_path / sample["relative_artifact_dir"]
    child.mkdir()
    _create_synthetic_database(oracle, child / "database.sqlite")
    _create_synthetic_workbook(oracle, child / "workbook.xlsx")
    (child / "grouping.json").write_text(json.dumps(oracle["grouping_output"]))
    (child / "tabular.json").write_text(json.dumps(oracle["tabular_output"]))
    import shutil
    retained = PROTOCOL_FIXTURES / "literal-measurement-labels.xlsx"
    shutil.copyfile(retained, child / "literal_workbook.xlsx")
    create_inference_case(child / "inference_database.sqlite", child / "group_inference.json")
    for record in sample["artifacts"].values():
        record["sha256"] = driver._hash(child / record["path"])
    output = tmp_path / "output"
    output.mkdir()
    return sample, child, output, oracle_path


def test_verified_preserved_copy_remains_readable_and_matches_oracle(tmp_path):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    copied = driver._copy_verified_results(tmp_path, sample, output, oracle)
    assert copied == sample["artifacts"]
    assert len(list(output.iterdir())) == 7


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("name", ["database.sqlite", "inference_database.sqlite"])
def test_uncheckpointed_database_sidecars_cannot_be_lost_from_receipt(tmp_path, suffix, name):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    (child / (name + suffix)).write_bytes(b"uncheckpointed state")
    with pytest.raises(driver.CandidateFailure, match="database_sidecars_remain"):
        driver._copy_verified_results(tmp_path, sample, output, oracle)
    assert not list(output.iterdir())


def test_valid_digest_does_not_substitute_for_correct_persisted_measurement(tmp_path):
    import sqlite3
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    with sqlite3.connect(child / "database.sqlite") as connection:
        connection.execute("UPDATE report_measurements SET meas=999 WHERE id=1")
    sample["artifacts"]["database"]["sha256"] = driver._hash(child / "database.sqlite")
    with pytest.raises(driver.CandidateFailure, match="independent_core_oracle_failed"):
        driver._copy_verified_results(tmp_path, sample, output, oracle)
    assert not list(output.iterdir())
