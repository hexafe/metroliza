"""Bind the completed diagnostic/core runs to one immutable engineering package.

This closes the executable receipt set, not release or clean-machine acceptance.
All inputs are bounded synthetic artifacts from the current workflow job.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from scripts import qualify_windows_candidate_core as core
from scripts import qualify_windows_diagnostics as diagnostics

RUNS = (("core-dpr-1.0", "1.0", "default"), ("core-dpr-1.25", "1.25", "default"),
        ("core-dpr-1.5", "1.5", "default"), ("core-native-unavailable", "1.0", "unavailable"))
ARTIFACT_KEYS = set(core.ARTIFACTS) | {
    "import_guards_database", "private_dashboard", "ocr_evidence", "native_evidence",
    "browser_evidence", "process_evidence", "closeout_evidence", "fresh_reopen_evidence", "before_reopen_database",
}


def _artifact_paths(directory, records):
    if type(records) is not dict or set(records) != ARTIFACT_KEYS:
        raise core.CandidateFailure("combined_artifact_set_mismatch")
    result = {}
    seen = set()
    for key, record in records.items():
        if (type(record) is not dict or set(record) != {"path", "sha256"}
                or type(record["path"]) is not str
                or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}\.(json|sqlite|xlsx|html)", record["path"]) is None
                or record["path"] in seen):
            raise core.CandidateFailure("combined_artifact_path_invalid")
        seen.add(record["path"])
        path = directory / record["path"]
        if core._hash(path) != record["sha256"]:
            raise core.CandidateFailure("combined_artifact_hash_mismatch")
        result[key] = path
    return result


def _expected_host_identity():
    folder = Path(__file__).resolve().parent
    files = {
        "oracle_sha256": "synthetic-report-oracle.json",
        "verifier_sha256": "verify_synthetic_oracle.py",
        "driver_sha256": "qualify_windows_candidate_core.py",
        "ocr_verifier_sha256": "verify_windows_candidate_ocr.py",
        "browser_verifier_sha256": "verify_windows_candidate_dashboard.py",
        "closeout_verifier_sha256": "verify_windows_candidate_closeout.py",
        "literal_xlsx_verifier_sha256": "windows_candidate_xlsx.py",
        "inference_oracle_sha256": "synthetic-inference-oracle.json",
        "inference_verifier_sha256": "verify_group_inference.py",
    }
    return {**{key: core._hash(folder / name) for key, name in files.items()},
            "ocr_fixture_sha256": core._ocr_oracle().FIXTURE_SHA256}


def _validate_run_identity(value, package, head, tree, scale, mode):
    expected = {
        "schema_version": 1, "status": "passed", "source_sha": head, "source_tree": tree,
        "ui_scale": scale, "native_mode": mode,
        "package_tree_sha256": package["tested_tree_sha256"],
        "launcher_sha256": package["launcher_sha256"], "application_sha256": package["application_sha256"],
        "supervision_manifest_sha256": package["manifest_sha256"], "notice_hashes": package["notice_hashes"],
        "scope": [*core.REQUIRED_CHECKS, *core.CLOSEOUT_CHECKS, "offline_browser_dom_and_layout", "fresh_process_reopen_preserves_completed_import"],
        "facets": dict.fromkeys((*core.REQUIRED_CHECKS, *core.CLOSEOUT_CHECKS, "offline_browser_dom_and_layout", "fresh_process_reopen_preserves_completed_import"), "passed"),
        "native_geometry": "passed", "offline_browser_rendering": "passed", "independent_oracle": "passed",
        "launch": "restricted_ordinary_user_native_windows_outside_checkout",
        "provenance_validated": True, "notices_validated": True,
        "limits": list(core.RESULT_LIMITS), **_expected_host_identity(),
    }
    if (type(value) is not dict or set(value) != set(expected) | {"artifacts"}
            or type(value.get("schema_version")) is not int
            or any(type(value.get(key)) is not type(wanted) or value.get(key) != wanted
                   for key, wanted in expected.items())):
        raise core.CandidateFailure("combined_source_package_or_scope_mismatch")


def _validate_run(directory, package, head, tree, scale, mode):
    core._directory(directory)
    path = directory / "core-driver-receipt.json"
    value = core._json(path)
    _validate_run_identity(value, package, head, tree, scale, mode)
    artifacts = _artifact_paths(directory, value.get("artifacts"))
    core._validate_native_observation(core._json(artifacts["native_evidence"]), packaged=True, expected_mode=mode)
    core._validate_ocr_observation(core._json(artifacts["ocr_evidence"]), packaged=True)
    core._validate_closeout_observation(core._json(artifacts["closeout_evidence"]), packaged=True, expected_dpr=float(scale))
    before_hash = value["artifacts"]["before_reopen_database"]["sha256"]
    after_hash = value["artifacts"]["database"]["sha256"]
    fresh = core._json(artifacts["fresh_reopen_evidence"])
    core._validate_fresh_reopen_evidence(fresh, before_hash, after_hash, head, diagnostics)
    core._assert_reopen_databases_preserved(artifacts["before_reopen_database"], artifacts["database"],
        before_hash=before_hash, after_hash=after_hash, observation=fresh["observation"]["observation"]["database"])
    browser = core._adjacent_module("verify_windows_candidate_dashboard.py", "_metroliza_final_browser")
    browser.validate_receipt(core._json(artifacts["browser_evidence"]),
                             core._hash(artifacts["private_dashboard"]), require_windows=True)
    diagnostics._validate_topology_record(core._json(artifacts["process_evidence"]),
                                          supervised=True, require_runtime_evidence=True)
    return {"path": str(Path(directory.name) / path.name).replace("\\", "/"), "sha256": core._hash(path)}


def finalize(root: Path, head: str, tree: str):
    if any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in (head, tree)):
        raise core.CandidateFailure("combined_source_identity_invalid")
    core._input_directory(root)
    diag_root = root / "diagnostics"
    core._directory(diag_root)
    diag_path = diag_root / "windows-diagnostic-qualification.json"
    receipt = core._json(diag_path)
    diagnostics._validate_output_payload(receipt)
    if receipt["status"] != "passed" or receipt["package"]["git_sha"] != head:
        raise core.CandidateFailure("combined_diagnostics_not_current_pass")
    if receipt["operational_cost"]["status"] != "within_budget":
        raise core.CandidateFailure("combined_operational_cost_unresolved")
    package = receipt["package"]
    diagnostics._validate_development_artifacts(diag_root, package)
    records = {name: _validate_run(root / name, package, head, tree, scale, mode)
               for name, scale, mode in RUNS}
    records["diagnostics"] = {"path": "diagnostics/" + diag_path.name, "sha256": core._hash(diag_path)}
    result = {"schema_version": 1, "status": "passed", "source_sha": head, "source_tree": tree,
              "package_tree_sha256": package["tested_tree_sha256"],
              "archive_sha256": package["archive_sha256"], "receipts": records,
              "scope": "same_package_diagnostics_and_core_four_runs",
              "limits": ["Not clean-machine, physical Excel, representative-data or release acceptance.",
                         "Remaining W01-W16 facets retain their own execution receipts."]}
    with (root / "combined-candidate-receipt.json").open("x", encoding="ascii") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    args = parser.parse_args()
    try:
        finalize(args.receipt_root, args.expected_source_sha, args.expected_source_tree)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        print('{"status":"failed","reason":"combined_candidate_receipts_invalid"}')
        return 1
    print('{"status":"passed","scope":"same_package_diagnostics_and_core_four_runs"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
