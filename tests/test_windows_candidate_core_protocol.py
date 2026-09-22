"""Adverse protocol controls only; these do not execute or qualify an EXE."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import qualify_windows_candidate_core as driver
from tests.test_windows_candidate_closeout import closeout_observation

REPO = Path(__file__).resolve().parents[1]
ORACLE = REPO / "scripts/synthetic-report-oracle.json"
PROTOCOL_FIXTURES = REPO / "tests/fixtures/windows_candidate_protocol"
PUBLIC_FIXTURES = REPO / "tests/fixtures/windows_candidate"

SHA = "1" * 40


def import_guard_evidence():
    import hashlib

    return {
        "relative_artifact_dir": "import-guards-" + "b" * 32,
        "initial_imported": 2, "duplicate_count": 2, "drift_rejected": 1,
        "cancelled_files": 1, "cancel_barrier_stage": "real_parse_batch_entry",
        "committed_database_sha256": "2" * 64, "committed_logical_sha256": "3" * 64,
        "database_sha256_after_close": "2" * 64, "sidecars_after_window_close": [],
        "source_hashes": {
            f"REF001_2024-01-01_{i}.pdf": hashlib.sha256((PUBLIC_FIXTURES / "reports" / f"report-{i}.pdf").read_bytes()).hexdigest()
            for i in range(5)
        },
    }


def ui_observation():
    return {
        "schema_version": 1, "status": "passed", "error_codes": [],
        "facets": {"private_dashboard_generation": "passed", "offline_html_source": "passed",
                   "industrial_geometry": "passed", "browser_rendering": "not_assessed"},
        "evidence": {
            "relative_artifact_dir": "ui-checks-" + "c" * 32,
            "screen": {"qpa": "windows", "dpr": 1.0, "physical_screen": [1920, 1080],
                       "logical_screen": [1920, 1080]},
            "sample_count": 2, "dashboard_sha256": "2" * 64, "retained_html": "dashboard.html",
            "owned_handle_observed": True, "private_directory_removed_after_close": True,
            "dialog_geometry": {key: {"client": [760, 480], "frame": [770, 520]} for key in (
                "industrial_data", "source_profiles", "industrial_sync")},
            "browser_rendered": False,
        },
    }


def ocr_observation(runtime_context="packaged"):
    from scripts.verify_windows_candidate_ocr import EXPECTED, FACETS
    return {
        "schema_version": 1, "status": "passed", "error_codes": [],
        "facets": {key: "passed" for key in FACETS},
        "evidence": {**copy.deepcopy(EXPECTED), "runtime_context": runtime_context,
                     "recognized_header_sha256": "a" * 64},
    }


def payload():
    return {
        "schema_version": 1, "stage": "complete", "status": "passed",
        "packaged": True, "qpa": "windows", "ordinary_user": True,
        "source_sha": SHA, "relative_artifact_dir": "core-" + "a" * 32,
        "checks": {"W03": "passed", "W04": "passed", "W05": "passed", "W06": "passed", "W07": "passed"},
        "import_guard_evidence": import_guard_evidence(),
        "closeout_observation": closeout_observation("packaged"),
        "ui_observation": ui_observation(),
        "ocr_observation": ocr_observation(),
        "native_observation": native_observation(),
        "facets": {**{key: "passed" for key in driver.REQUIRED_CHECKS}, "group_analysis_status": "insufficient_groups"},
        "artifacts": {
            key: {"path": key + extension, "sha256": "2" * 64}
            for key, extension in zip(driver.ARTIFACTS, (".sqlite", ".xlsx", ".json", ".json", ".xlsx", ".sqlite", ".json"), strict=True)
        },
    }


def native_observation(runtime_context="packaged", mode="default"):
    return {
        "mode": mode, "runtime_context": runtime_context, "bindings": list(driver.NATIVE_BINDINGS),
        "available_before": 16, "forced_unavailable": 16 if mode == "unavailable" else 0, "restored": True,
    }


def test_protocol_accepts_only_declared_native_complete_identity():
    sample = payload()
    assert driver.validate_runtime_receipt(sample, SHA) is sample


@pytest.mark.parametrize("checks", [
    {},
    {"W03": "passed", "W04": "not_executed", "W05": "passed", "W06": "not_executed", "W07": "passed"},
    {"W03": "passed", "W04": "not_executed", "W05": "passed", "W06": "passed", "W07": "passed"},
    {"W03": "passed", "W04": "not_executed", "W05": "passed", "W06": "passed", "W07": "not_executed"},
])
def test_core_observations_cannot_contradict_completed_facets_or_claim_unexecuted_scope(checks):
    sample = payload()
    sample["checks"] = checks
    with pytest.raises(driver.CandidateFailure, match="^core_observation_state_mismatch$"):
        driver.validate_runtime_receipt(sample, SHA)


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
    import hashlib
    import sqlite3
    from contextlib import closing
    guard = child / sample["import_guard_evidence"]["relative_artifact_dir"]
    (guard / "reports").mkdir(parents=True)
    for i in range(5):
        shutil.copyfile(PUBLIC_FIXTURES / "reports" / f"report-{i}.pdf", guard / "reports" / f"REF001_2024-01-01_{i}.pdf")
    shutil.copyfile(child / "database.sqlite", guard / "reports.sqlite")
    with closing(sqlite3.connect(guard / "reports.sqlite")) as db:
        logical = hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
    sample["import_guard_evidence"]["committed_logical_sha256"] = logical
    ui = child / sample["ui_observation"]["evidence"]["relative_artifact_dir"]
    ui.mkdir()
    html = ui / "dashboard.html"
    html.write_text('<!doctype html><div data-section="signal-charts">cycle_time_s 10.25</div>')
    sample["ui_observation"]["evidence"]["dashboard_sha256"] = driver._hash(html)
    output = tmp_path / "output"
    output.mkdir()
    return sample, child, output, oracle_path


def test_verified_preserved_copy_remains_readable_and_matches_oracle(tmp_path):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    copied = driver._copy_verified_results(tmp_path, sample, output, oracle)
    assert copied == {
        **sample["artifacts"],
        "import_guards_database": {
            "path": "import-guards.sqlite",
            "sha256": driver._hash(child / sample["import_guard_evidence"]["relative_artifact_dir"] / "reports.sqlite"),
        },
        "private_dashboard": {
            "path": "dashboard.html", "sha256": sample["ui_observation"]["evidence"]["dashboard_sha256"],
        },
    }
    assert len(list(output.iterdir())) == 9


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


@pytest.mark.parametrize(("field", "value"), [
    ("relative_artifact_dir", "../escape"), ("initial_imported", True),
    ("cancelled_files", 0), ("cancel_barrier_stage", "after_commit"),
    ("source_hashes", {}), ("sidecars_after_window_close", ["-wal", "-wal"]),
    ("sidecars_after_window_close", ["-journal"]),
])
def test_import_guard_receipt_rejects_false_or_unbounded_evidence(field, value):
    sample = payload()
    sample["import_guard_evidence"][field] = value
    with pytest.raises(driver.CandidateFailure, match="invalid_import_guard_evidence"):
        driver._validate_core_result(sample)


def test_import_guard_cannot_be_missing_from_completed_core():
    sample = payload()
    del sample["import_guard_evidence"]
    with pytest.raises(driver.CandidateFailure, match="invalid_import_guard_evidence"):
        driver._validate_core_result(sample)


@pytest.mark.parametrize("mutation", ["source", "sidecar", "logical"])
def test_import_guard_postprocess_verification_rejects_changes(tmp_path, mutation):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    record = sample["import_guard_evidence"]
    guard = child / record["relative_artifact_dir"]
    if mutation == "source":
        (guard / "reports" / "REF001_2024-01-01_0.pdf").write_bytes(b"changed after close")
        reason = "import_guard_sources_changed"
    elif mutation == "sidecar":
        (guard / "reports.sqlite-wal").write_bytes(b"")
        reason = "import_guard_database_sidecars_remain"
    else:
        record["committed_logical_sha256"] = "0" * 64
        reason = "import_guard_committed_database_changed"
    with pytest.raises(driver.CandidateFailure, match=reason):
        driver._verify_import_guard_outputs(child, sample, output, oracle)
    assert not (output / "import-guards.sqlite").exists()


def test_import_guard_accepts_only_inert_closed_wal_pair(tmp_path):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    database = child / sample["import_guard_evidence"]["relative_artifact_dir"] / "reports.sqlite"
    database.with_name(database.name + "-wal").write_bytes(b"")
    database.with_name(database.name + "-shm").write_bytes(bytes(32768))

    copied = driver._verify_import_guard_outputs(child, sample, output, oracle)

    assert copied == {"path": "import-guards.sqlite", "sha256": driver._hash(database)}
    assert (output / copied["path"]).is_file()
    assert database.with_name(database.name + "-wal").stat().st_size == 0
    assert database.with_name(database.name + "-shm").stat().st_size == 32768


@pytest.mark.parametrize("kind", ("nonempty_wal", "journal", "wrong_shm", "hardlink", "symlink"))
def test_import_guard_rejects_unsafe_final_sidecars(tmp_path, kind):
    import os

    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    database = child / sample["import_guard_evidence"]["relative_artifact_dir"] / "reports.sqlite"
    wal = database.with_name(database.name + "-wal")
    shm = database.with_name(database.name + "-shm")
    wal.write_bytes(b"")
    shm.write_bytes(bytes(32768))
    if kind == "nonempty_wal":
        wal.write_bytes(b"uncheckpointed page")
    elif kind == "journal":
        database.with_name(database.name + "-journal").write_bytes(b"")
    elif kind == "wrong_shm":
        shm.write_bytes(bytes(32767))
    elif kind == "hardlink":
        wal.unlink()
        os.link(shm, wal)
    else:
        wal.unlink()
        wal.symlink_to(shm)

    with pytest.raises(driver.CandidateFailure, match="^import_guard_database_sidecars_remain$"):
        driver._verify_import_guard_outputs(child, sample, output, oracle)
    assert not (output / "import-guards.sqlite").exists()


def test_import_guard_detects_sidecar_mutation_during_observation(tmp_path, monkeypatch):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    database = child / sample["import_guard_evidence"]["relative_artifact_dir"] / "reports.sqlite"
    database.with_name(database.name + "-wal").write_bytes(b"")
    shm = database.with_name(database.name + "-shm")
    shm.write_bytes(bytes(32768))
    original = driver._adjacent_module

    def mutate_on_oracle_load(*args, **kwargs):
        module = original(*args, **kwargs)
        shm.write_bytes(b"x" + bytes(32767))
        return module

    monkeypatch.setattr(driver, "_adjacent_module", mutate_on_oracle_load)
    with pytest.raises(driver.CandidateFailure, match="^import_guard_observation_changed_database$"):
        driver._verify_import_guard_outputs(child, sample, output, oracle)


def test_import_guard_rejects_live_uncheckpointed_wal(tmp_path):
    import sqlite3

    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    database = child / sample["import_guard_evidence"]["relative_artifact_dir"] / "reports.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE live_uncheckpointed_marker (id INTEGER)")
        connection.commit()
        assert database.with_name(database.name + "-wal").stat().st_size > 0
        with pytest.raises(driver.CandidateFailure, match="^import_guard_database_sidecars_remain$"):
            driver._verify_import_guard_outputs(child, sample, output, oracle)
    finally:
        connection.close()


def test_import_guard_rejects_reparse_attribute(tmp_path, monkeypatch):
    from types import SimpleNamespace

    target = tmp_path / "reports.sqlite-wal"
    target.write_bytes(b"")
    actual_lstat = Path.lstat

    def lstat_with_reparse(path):
        info = actual_lstat(path)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink,
                                   st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", lstat_with_reparse)
    assert not driver._regular(target)


def test_import_guard_detects_database_mutation_during_observation(tmp_path, monkeypatch):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    database = child / sample["import_guard_evidence"]["relative_artifact_dir"] / "reports.sqlite"
    original = driver._adjacent_module

    def mutate_on_oracle_load(*args, **kwargs):
        module = original(*args, **kwargs)
        with database.open("ab") as stream:
            stream.write(b"changed after immutable observation")
        return module

    monkeypatch.setattr(driver, "_adjacent_module", mutate_on_oracle_load)
    with pytest.raises(driver.CandidateFailure, match="^import_guard_observation_changed_database$"):
        driver._verify_import_guard_outputs(child, sample, output, oracle)


@pytest.mark.parametrize("field,value", [
    ("owned_handle_observed", False),
    ("private_directory_removed_after_close", False),
    ("relative_artifact_dir", "../escape"),
    ("retained_html", "../escape.html"),
    ("browser_rendered", True),
    ("sample_count", True),
    ("screen", {"qpa": "offscreen", "dpr": 1.0, "physical_screen": [1920, 1080], "logical_screen": [1920, 1080]}),
])
def test_ui_receipt_rejects_missing_ownership_geometry_or_unperformed_claim(field, value):
    record = ui_observation()
    record["evidence"][field] = value
    with pytest.raises(driver.CandidateFailure):
        driver._validate_ui_observation(record, expected_dpr=1.0)


def test_partial_source_ui_observation_is_never_native_geometry():
    record = ui_observation()
    record["status"] = "partial"
    record["facets"]["industrial_geometry"] = "not_assessed"
    driver._validate_ui_observation(record)
    with pytest.raises(driver.CandidateFailure, match="native_ui_observation_incomplete"):
        driver._validate_ui_observation(record, expected_dpr=1.0)


@pytest.mark.parametrize("content", [b"https://private.invalid", b"<script>alert(1)</script>"])
def test_dashboard_retention_rejects_external_resources_even_with_matching_hash(tmp_path, content):
    sample, child, output, oracle = _complete_synthetic_artifacts(tmp_path)
    evidence = sample["ui_observation"]["evidence"]
    html = child / evidence["relative_artifact_dir"] / "dashboard.html"
    html.write_bytes(html.read_bytes() + content)
    evidence["dashboard_sha256"] = driver._hash(html)
    with pytest.raises(driver.CandidateFailure, match="dashboard_source_invalid"):
        driver._retain_ui_dashboard(child, sample, output)


@pytest.mark.parametrize("dimensions", [[True, 1080], [1920, "private"], [1920, 0], [1920]])
def test_native_ui_receipt_rejects_invalid_logical_screen_dimensions(dimensions):
    record = ui_observation()
    record["evidence"]["screen"]["logical_screen"] = dimensions
    with pytest.raises(driver.CandidateFailure, match="native_ui_observation_incomplete"):
        driver._validate_ui_observation(record, expected_dpr=1.0)
