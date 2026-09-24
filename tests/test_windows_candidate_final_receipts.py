"""Protocol fixtures only: mixed heads, altered packages and partial runs fail closed."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from scripts import finalize_windows_candidate_receipts as final
from tests.test_windows_candidate_closeout import closeout_observation
from scripts import qualify_windows_candidate_core as core
from scripts import qualify_windows_diagnostics as diag
from tests.test_windows_diagnostic_qualification import _success_payload
from tests.test_windows_candidate_core_protocol import native_observation, ocr_observation
from tests.test_windows_candidate_dashboard import _source_receipt
from tests.test_windows_runtime_audit import _proof
from scripts.windows_owned_process_probe import verified_runtime_order

HEAD = "a" * 40
TREE = "b" * 40


def _write(path, value):
    path.write_text(json.dumps(value), encoding="ascii")


def _verified_ocr_topology(*, defect=None):
    proof = _proof(supervised=True, helpers=True, ocr_worker=True)
    proof["events"][0].update(caller="numpy", phase="after_ready")
    for member in proof["owned"]["members"][-3:-1]:
        member.update(first_phase="running", last_phase="running")
    order = verified_runtime_order(proof, supervised=True, allow_ocr_worker=True)
    record = {
        "launcher_processes_observed": 2, "application_processes_observed": 1,
        "unexpected_processes_observed": 0, "assigned_processes": len(order),
        "max_active_processes": len(order), "creation_order": list(order),
        "all_processes_exited": True, "runtime_evidence": proof,
    }
    if defect == "unknown_worker":
        proof["owned"]["members"][-1]["identity"] = "unknown"
    elif defect == "extra_event":
        proof["events"].append({"kind": "other_arguments", "caller": "other", "phase": "after_ready"})
    return record


def _prepared(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "metroliza.exe").write_bytes(b"synthetic protocol package")
    root = tmp_path / "receipts"
    root.mkdir()
    diagnostics = root / "diagnostics"
    diagnostics.mkdir()
    receipt = _success_payload()
    receipt["package"].update(diag._write_development_artifacts(package, package, diagnostics))
    receipt["package"]["git_sha"] = HEAD
    _write(diagnostics / "windows-diagnostic-qualification.json", receipt)
    for name, scale, mode in final.RUNS:
        directory = root / name
        directory.mkdir()
        artifacts = {}
        for key in sorted(final.ARTIFACT_KEYS):
            path = directory / (key + ".json")
            value = {}
            if key == "closeout_evidence":
                value = closeout_observation(scale=float(scale))
            elif key == "native_evidence":
                value = native_observation(mode=mode)
            elif key == "ocr_evidence":
                value = ocr_observation()
            elif key == "process_evidence":
                value = _verified_ocr_topology()
            if key in {"database", "before_reopen_database"}:
                with closing(sqlite3.connect(path)) as connection, connection:
                    connection.execute("CREATE TABLE synthetic_protocol (value INTEGER)")
                    connection.execute("INSERT INTO synthetic_protocol VALUES (1)")
            else:
                _write(path, value)
            artifacts[key] = {"path": path.name, "sha256": core._hash(path)}
        browser = _source_receipt()
        browser["evidence"].update(host_platform="win32", input_sha256=artifacts["private_dashboard"]["sha256"])
        browser_path = directory / artifacts["browser_evidence"]["path"]
        _write(browser_path, browser)
        artifacts["browser_evidence"]["sha256"] = core._hash(browser_path)
        from tests.test_windows_candidate_fresh_reopen import runtime_receipt
        fresh = {"schema_version": 1, "status": "passed",
                 "process_boundary": "new_owned_job_after_initial_job_drained",
                 "observation": runtime_receipt(artifacts["database"]["sha256"], HEAD),
                 "topology": receipt["topology"]["supervised"][0]}
        fresh["observation"]["observation"]["database"].update(core._assert_reopen_databases_preserved(
            directory / artifacts["before_reopen_database"]["path"], directory / artifacts["database"]["path"],
            before_hash=artifacts["before_reopen_database"]["sha256"], after_hash=artifacts["database"]["sha256"]))
        fresh_path = directory / artifacts["fresh_reopen_evidence"]["path"]
        _write(fresh_path, fresh)
        artifacts["fresh_reopen_evidence"]["sha256"] = core._hash(fresh_path)
        p = receipt["package"]
        value = {
            "schema_version": 1, "status": "passed", "source_sha": HEAD, "source_tree": TREE,
            "ui_scale": scale, "native_mode": mode, "package_tree_sha256": p["tested_tree_sha256"],
            "launcher_sha256": p["launcher_sha256"], "application_sha256": p["application_sha256"],
            "supervision_manifest_sha256": p["manifest_sha256"], "notice_hashes": p["notice_hashes"],
            "scope": [*core.REQUIRED_CHECKS, *core.CLOSEOUT_CHECKS, "offline_browser_dom_and_layout", "fresh_process_reopen_preserves_completed_import"],
            "facets": dict.fromkeys((*core.REQUIRED_CHECKS, *core.CLOSEOUT_CHECKS, "offline_browser_dom_and_layout", "fresh_process_reopen_preserves_completed_import"), "passed"),
            "native_geometry": "passed", "offline_browser_rendering": "passed", "independent_oracle": "passed",
            "launch": "restricted_ordinary_user_native_windows_outside_checkout",
            "provenance_validated": True, "notices_validated": True, "artifacts": artifacts,
            "limits": list(core.RESULT_LIMITS), **final._expected_host_identity(),
        }
        _write(directory / "core-driver-receipt.json", value)
    return root


def _with_verified_ocr_topology(root, *, defect=None):
    directory = root / "core-dpr-1.0"
    path = directory / "process_evidence.json"
    _write(path, _verified_ocr_topology(defect=defect))
    receipt_path = directory / "core-driver-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["artifacts"]["process_evidence"]["sha256"] = core._hash(path)
    _write(receipt_path, receipt)


def test_same_package_protocol_fixture_binds_archive_and_all_four_runs(tmp_path):
    root = _prepared(tmp_path)
    result = final.finalize(root, HEAD, TREE)
    assert set(result["receipts"]) == {name for name, _, _ in final.RUNS} | {"diagnostics"}
    assert result["source_sha"] == HEAD
    assert result["scope"] == "same_package_diagnostics_and_core_four_runs"
    assert json.loads((root / "combined-candidate-receipt.json").read_bytes()) == result


def test_finalizer_accepts_only_verified_ocr_worker_in_core_topology(tmp_path):
    root = _prepared(tmp_path)
    _with_verified_ocr_topology(root)
    result = final.finalize(root, HEAD, TREE)
    assert result["status"] == "passed"


@pytest.mark.parametrize("defect", ["unknown_worker", "extra_event"])
def test_finalizer_rejects_unverified_ocr_topology(tmp_path, defect):
    root = _prepared(tmp_path)
    _with_verified_ocr_topology(root, defect=defect)
    with pytest.raises(diag.QualificationFailure, match="output_failed"):
        final.finalize(root, HEAD, TREE)
    assert not (root / "combined-candidate-receipt.json").exists()


@pytest.mark.parametrize("field,value", [
    ("source_sha", "c" * 40), ("source_tree", "d" * 40),
    ("package_tree_sha256", "e" * 64), ("launcher_sha256", "f" * 64),
    ("application_sha256", "0" * 64), ("native_mode", "unavailable"),
    ("ui_scale", "1.5"), ("schema_version", True), ("facets", {}),
    ("notices_validated", 1), ("native_geometry", "not_assessed"), ("scope", []),
    ("driver_sha256", "0" * 64), ("oracle_sha256", "0" * 64),
    ("closeout_verifier_sha256", "0" * 64), ("unrecognized_extra", True),
])
def test_mixed_or_partial_run_never_publishes_combined_pass(tmp_path, field, value):
    root = _prepared(tmp_path)
    path = root / "core-dpr-1.0/core-driver-receipt.json"
    payload = json.loads(path.read_bytes())
    payload[field] = value
    _write(path, payload)
    with pytest.raises(core.CandidateFailure):
        final.finalize(root, HEAD, TREE)
    assert not (root / "combined-candidate-receipt.json").exists()


@pytest.mark.parametrize("defect", ["missing_run", "archive_changed", "artifact_changed", "unsafe_artifact", "source_browser", "source_native", "source_closeout", "live_job"])
def test_combined_gate_rechecks_retained_bytes_and_native_proofs(tmp_path, defect):
    root = _prepared(tmp_path)
    directory = root / "core-native-unavailable"
    path = directory / "core-driver-receipt.json"
    payload = json.loads(path.read_bytes())
    if defect == "missing_run":
        path.unlink()
    elif defect == "archive_changed":
        (root / "diagnostics" / diag.PACKAGE_ARCHIVE_NAME).write_bytes(b"changed")
    elif defect == "artifact_changed":
        (directory / "database.json").write_bytes(b"changed")
    elif defect == "unsafe_artifact":
        payload["artifacts"]["database"]["path"] = "../private.json"
        _write(path, payload)
    else:
        key = {"source_browser": "browser_evidence", "source_native": "native_evidence", "source_closeout": "closeout_evidence", "live_job": "process_evidence"}[defect]
        evidence = directory / payload["artifacts"][key]["path"]
        value = json.loads(evidence.read_bytes())
        if defect == "source_browser":
            value["evidence"]["host_platform"] = "linux"
        elif defect == "source_native":
            value["runtime_context"] = "source"
        elif defect == "source_closeout":
            value = closeout_observation("source")
        else:
            value["all_processes_exited"] = False
        _write(evidence, value)
        payload["artifacts"][key]["sha256"] = core._hash(evidence)
        _write(path, payload)
    with pytest.raises((ValueError, OSError, RuntimeError)):
        final.finalize(root, HEAD, TREE)
    assert not (root / "combined-candidate-receipt.json").exists()


@pytest.mark.parametrize("field", ["schema_sha256", "logical_dump_sha256"])
def test_final_reopen_rejects_declared_digest_not_bound_to_retained_database(tmp_path, field):
    root = _prepared(tmp_path)
    directory = root / "core-dpr-1.0"
    receipt_path = directory / "core-driver-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    path = directory / receipt["artifacts"]["fresh_reopen_evidence"]["path"]
    value = json.loads(path.read_bytes())
    value["observation"]["observation"]["database"][field] = "f" * 64
    _write(path, value)
    receipt["artifacts"]["fresh_reopen_evidence"]["sha256"] = core._hash(path)
    _write(receipt_path, receipt)
    with pytest.raises(core.CandidateFailure, match="fresh_reopen_database_digest_mismatch"):
        final.finalize(root, HEAD, TREE)
    assert not (root / "combined-candidate-receipt.json").exists()


@pytest.mark.parametrize("target", ["before_reopen_database", "database"])
def test_final_reopen_rejects_database_change_during_semantic_observation(tmp_path, monkeypatch, target):
    root = _prepared(tmp_path)
    path = root / "core-dpr-1.0" / (target + ".json")
    observe = core._reopen_database_semantics

    def replacing_observer(database):
        value = observe(database)
        if database == path:
            # Preserve SQLite logical contents, but replace the bytes after the
            # first identity check and semantic read. A later recheck must fail.
            with database.open("ab") as stream:
                stream.write(b"changed retained bytes")
        return value

    monkeypatch.setattr(core, "_reopen_database_semantics", replacing_observer)
    with pytest.raises(core.CandidateFailure, match="fresh_reopen_database_identity_changed"):
        final.finalize(root, HEAD, TREE)
    assert not (root / "combined-candidate-receipt.json").exists()
