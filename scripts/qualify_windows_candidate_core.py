"""Run the closed synthetic core scenario in the actual Windows onedir.

The build host uses its checked-out driver/runtime; the relocated application
uses only its bundled runtime. This is not a clean-machine claim. The existing
diagnostics driver owns restricted-token launch, Job containment and private
temporary-directory handling. No product worker or data service is substituted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

SCENARIO_FILE = "windows-candidate-result.json"
REQUIRED_CHECKS = (
    "selected_import", "zero_selection_no_write", "finite_precision_filters", "persisted_measurements",
    "group_membership", "workbook_cells",
    "literal_chart_titles_series_caches_references", "value_limit_order",
    "local_chart_cells_and_negative_control", "pre_cancelled_export_preserves_workbook",
    "oversized_label_rejection_preserves_workbook",
)
ARTIFACTS = ("database", "workbook", "grouping", "tabular", "literal_workbook")
MAX_RECEIPT_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_SECONDS = 900


class CandidateFailure(RuntimeError):
    """Only fixed identifiers from this driver are exposed in its receipt."""


def _regular(path: Path) -> bool:
    info = path.lstat()
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and not getattr(info, "st_file_attributes", 0) & 0x400
    )


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CandidateFailure("duplicate_receipt_field")
        result[key] = value
    return result


def _json(path: Path, maximum: int = MAX_RECEIPT_BYTES):
    if not _regular(path) or path.stat().st_size > maximum:
        raise CandidateFailure("unsafe_or_oversized_receipt")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise CandidateFailure("unsafe_or_oversized_receipt")
    return json.loads(data, object_pairs_hook=_unique)


def _hash(path: Path) -> str:
    if not _regular(path) or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise CandidateFailure("unsafe_or_oversized_scenario_artifact")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = MAX_ARTIFACT_BYTES + 1
        while remaining:
            block = stream.read(min(65536, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    if not remaining:
        raise CandidateFailure("unsafe_or_oversized_scenario_artifact")
    return digest.hexdigest()


def _directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise CandidateFailure("unsafe_scenario_directory")


def _input_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise CandidateFailure("absolute_input_directory_required")
    # Check the supplied path before resolving it so a junction/symlink in any
    # parent cannot be hidden by Path.resolve().
    for component in (path, *path.parents):
        _directory(component)
    return path.resolve(strict=True)


def _validate_core_result(payload: object) -> dict:
    """Validate the closed scenario payload independently of runtime identity."""
    if type(payload) is not dict or type(payload.get("schema_version")) is not int:
        raise CandidateFailure("invalid_runtime_receipt")
    if payload["schema_version"] != 1:
        raise CandidateFailure("invalid_runtime_receipt")
    if payload.get("stage") != "complete" or payload.get("status") != "passed":
        raise CandidateFailure("scenario_incomplete")
    relative = payload.get("relative_artifact_dir")
    if type(relative) is not str or re.fullmatch(r"core-[0-9a-f]{32}", relative) is None:
        raise CandidateFailure("invalid_artifact_directory")
    checks = payload.get("facets")
    if (
        type(checks) is not dict
        or set(checks) != set(REQUIRED_CHECKS) | {"group_analysis_status"}
        or checks.get("group_analysis_status") != "insufficient_groups"
        or any(checks.get(key) != "passed" for key in REQUIRED_CHECKS)
    ):
        raise CandidateFailure("required_core_check_incomplete")
    artifacts = payload.get("artifacts")
    if type(artifacts) is not dict or set(artifacts) != set(ARTIFACTS):
        raise CandidateFailure("missing_scenario_artifact")
    seen = set()
    for record in artifacts.values():
        if type(record) is not dict or set(record) != {"path", "sha256"}:
            raise CandidateFailure("invalid_artifact_record")
        name, digest = record["path"], record["sha256"]
        if (
            type(name) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}\.(sqlite|xlsx|json)", name) is None
            or name in seen
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise CandidateFailure("invalid_artifact_record")
        seen.add(name)
    return payload


def validate_runtime_receipt(payload: object, expected_source: str) -> dict:
    """Reject source-only, partial, stale, elevated and offscreen observations."""
    result = _validate_core_result(payload)
    if result.get("packaged") is not True:
        raise CandidateFailure("source_execution_is_not_package_evidence")
    if result.get("qpa") != "windows" or result.get("ordinary_user") is not True:
        raise CandidateFailure("native_ordinary_user_evidence_missing")
    if result.get("source_sha") != expected_source:
        raise CandidateFailure("runtime_source_mismatch")
    return result


def _source_driver(checkout: Path, source_sha: str):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout, text=True).strip()

    if git("rev-parse", "HEAD") != source_sha or git("status", "--porcelain"):
        raise CandidateFailure("source_checkout_not_exact_and_clean")
    module_path = checkout / "scripts" / "qualify_windows_diagnostics.py"
    if not module_path.is_file():
        raise CandidateFailure("required_diagnostics_driver_not_integrated")
    sys.path[:0] = [str(checkout / "src"), str(checkout)]
    module = importlib.import_module("scripts.qualify_windows_diagnostics")
    if Path(module.__file__).resolve() != module_path.resolve():
        raise CandidateFailure("driver_import_identity_mismatch")
    return module



def _stage_known_fixtures(fixtures: Path, private: Path) -> Path:
    """Copy only the previously authored public byte set into the private job."""
    expected = {'finite-source.csv': 'de2724bd3b6b55d362016423a2f78168235d3833d7a89298a7fdf4a5ec747938', 'integer-precision.csv': '8e2c837472d6465d319b37b4afe09998f9c45680edc27d1a169f33e145a70508', 'report-0.pdf': '183b46650a7e37113927f7a99eb6a66484d07126d3134b3a6056defaef21af3f', 'report-1.pdf': '315032987a656191260945242c89996976640f3629c4499c428f44ac9b3679ad', 'report-2.pdf': '7a6fe37457385188f9b466a8f9c3061bf7d118290b0c8e74583dba5e76f29048', 'report-3.pdf': 'cb801c452d9608c227606a4c10325d19d7d8a095fe80976fa60338fd6bfd0849', 'report-4.pdf': 'b9f83ee23a191eccfa3515594e6ba85ede670a2163444cd0daf7b9bb5edd83d9'}
    if {p.name for p in fixtures.iterdir()} != {"reports", "finite-source.csv", "integer-precision.csv"}:
        raise CandidateFailure("prepared_fixture_set_mismatch")
    reports = _input_directory(fixtures / "reports")
    if {p.name for p in reports.iterdir()} != {f"report-{i}.pdf" for i in range(5)}:
        raise CandidateFailure("prepared_fixture_set_mismatch")
    output = private / "known public fixtures"
    output.mkdir()
    for name, digest in expected.items():
        source = (reports if name.endswith(".pdf") else fixtures) / name
        if _hash(source) != digest:
            raise CandidateFailure("prepared_fixture_hash_mismatch")
        target = output / name
        with source.open("rb") as original, target.open("xb") as copied:
            shutil.copyfileobj(original, copied)
        if _hash(target) != digest:
            raise CandidateFailure("prepared_fixture_copy_mismatch")
    return output


def _adjacent_module(filename: str, name: str):
    path = Path(__file__).with_name(filename).resolve(strict=True)
    digest = _hash(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateFailure("independent_verifier_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != path or _hash(path) != digest:
        raise CandidateFailure("independent_verifier_identity_changed")
    return module


def _independent_verifier():
    return _adjacent_module("verify_synthetic_oracle.py", "_metroliza_independent_candidate_oracle").verify


def _independent_xlsx_verifier():
    # Only the standalone standard-library OOXML comparator is called here.
    return _adjacent_module("windows_candidate_xlsx.py", "_metroliza_independent_xlsx_oracle")._verify_workbook


def _assert_artifact_hashes(paths: dict, payload: dict, reason: str) -> None:
    if any(_hash(paths[key]) != payload["artifacts"][key]["sha256"] for key in ARTIFACTS):
        raise CandidateFailure(reason)


def _assert_database_sidecars_absent(database: Path, reason: str) -> None:
    if any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise CandidateFailure(reason)


def _copy_verified_results(work: Path, payload: dict, output: Path, oracle: Path) -> dict:
    child = work / payload["relative_artifact_dir"]
    _directory(child)
    actual = {}
    for key, record in payload["artifacts"].items():
        source = child / record["path"]
        if _hash(source) != record["sha256"]:
            raise CandidateFailure("scenario_artifact_hash_mismatch")
        actual[key] = source
    _assert_database_sidecars_absent(actual["database"], "database_sidecars_remain")
    # This verifier imports no Metroliza and does not derive expected values
    # from application output. Its independent expected inputs were reviewed.
    verify = _independent_verifier()
    try:
        verify(oracle, actual["database"], actual["workbook"], actual["grouping"], actual["tabular"])
    except Exception:
        raise CandidateFailure("independent_core_oracle_failed") from None
    verify_xlsx = _independent_xlsx_verifier()
    try:
        verify_xlsx(actual["literal_workbook"])
    except Exception:
        raise CandidateFailure("independent_literal_workbook_oracle_failed") from None
    _assert_artifact_hashes(actual, payload, "scenario_artifact_changed_after_comparison")
    _assert_database_sidecars_absent(actual["database"], "scenario_database_sidecars_created_after_comparison")
    copied = {}
    for key, source in actual.items():
        destination = output / payload["artifacts"][key]["path"]
        with source.open("rb") as original, destination.open("xb") as target:
            shutil.copyfileobj(original, target, length=65536)
        digest = _hash(destination)
        if digest != payload["artifacts"][key]["sha256"]:
            raise CandidateFailure("copied_artifact_hash_mismatch")
        copied[key] = {"path": destination.name, "sha256": digest}
    try:
        verify(oracle, *(output / copied[key]["path"] for key in ARTIFACTS[:4]))
        verify_xlsx(output / copied["literal_workbook"]["path"])
    except Exception:
        raise CandidateFailure("retained_outputs_oracle_failed") from None
    retained = {key: output / copied[key]["path"] for key in ARTIFACTS}
    _assert_artifact_hashes(retained, payload, "retained_artifact_changed_after_comparison")
    _assert_database_sidecars_absent(
        retained["database"], "retained_database_sidecars_created_after_comparison"
    )
    return copied


def _prepare_paths(args) -> tuple[Path, Path, Path, Path]:
    checkout = _input_directory(args.source_checkout)
    artifact = _input_directory(args.artifact_dir)
    fixtures = _input_directory(args.fixture_dir)
    if not args.output_dir.is_absolute():
        raise CandidateFailure("absolute_output_directory_required")
    output = args.output_dir
    if output.exists():
        raise CandidateFailure("output_must_be_new")
    for parent in (artifact, checkout, fixtures):
        if output == parent or parent in output.parents:
            raise CandidateFailure("output_must_be_outside_inputs")
    _input_directory(output.parent)
    return checkout, artifact, fixtures, output


def _run_private_core(private: Path, *, args, diag, artifact: Path, fixtures: Path,
                      output: Path, deadline: float, before: str) -> dict:
    relocated = diag._relocate_package(artifact, private, deadline)
    staged_fixtures = _stage_known_fixtures(fixtures, private)
    work = private / "core scenario"
    state = private / "ordinary user state"
    work.mkdir()
    (state / "Roaming").mkdir(parents=True)
    environment = diag._sanitized_environment(relocated, work, state, "idle")
    environment.pop("METROLIZA_DIAGNOSTIC_QUALIFICATION", None)
    environment.pop("METROLIZA_DIAGNOSTIC_QUALIFICATION_ROOT", None)
    environment.update({
        "QT_QPA_PLATFORM": "windows",
        "METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION": "1",
        "METROLIZA_WINDOWS_CANDIDATE_ROOT": str(work),
        "METROLIZA_WINDOWS_CANDIDATE_FIXTURE_DIR": str(staged_fixtures),
    })
    owned = []
    terminate = True
    try:
        process = diag._WindowsApi().launch(
            relocated / "metroliza.exe", environment, work, owned=owned
        )
        while time.monotonic() < deadline:
            process.observe()
            code = process.poll()
            if code is not None:
                break
            time.sleep(0.02)
        else:
            raise CandidateFailure("owned_package_scenario_timeout")
        if code != 0:
            raise CandidateFailure("package_scenario_nonzero_exit")
        result_path = work / SCENARIO_FILE
        if not result_path.exists():
            raise CandidateFailure("package_core_hook_or_receipt_missing")
        payload = validate_runtime_receipt(_json(result_path), args.expected_source_sha)
        if not diag._wait_for_job_exit(process, deadline):
            raise CandidateFailure("owned_processes_remain")
        topology = process.topology(relocated, all_exited=True)
        # Use the accepted dependency's complete onefile-supervisor /
        # onedir-child topology contract, including both launcher processes.
        diag._validate_topology_record(diag._topology_record(topology), supervised=True)
        after = diag._tree_digest(diag._package_inventory(relocated))
        if after != before:
            raise CandidateFailure("package_tree_changed_during_scenario")
        artifacts = _copy_verified_results(work, payload, output, args.oracle)
        terminate = False
        return artifacts
    finally:
        diag._close_owned_processes(owned, terminate=terminate)


def qualify(args) -> dict:
    if os.name != "nt":
        raise CandidateFailure("native_windows_required")
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_source_sha) is None:
        raise CandidateFailure("invalid_expected_source_sha")
    checkout, artifact, fixtures, output = _prepare_paths(args)
    diag = _source_driver(checkout, args.expected_source_sha)
    identity = diag._validate_package(artifact)
    # The declared build writes the launcher sidecar; the adjacent child is
    # bound through the supervision manifest and its embedded provenance.
    if identity.get("git_sha") != args.expected_source_sha:
        raise CandidateFailure("package_source_mismatch")
    diag._validate_sidecar(artifact / "metroliza.exe", args.expected_source_sha)
    sidecar = _json(artifact / "metroliza.exe.provenance.json", 16 * 1024)
    if sidecar.get("dirty") is not False:
        raise CandidateFailure("dirty_package_provenance")
    notices = diag._validate_notices(artifact / "metroliza.exe")
    before = diag._tree_digest(diag._package_inventory(artifact))
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    deadline = time.monotonic() + MAX_SECONDS

    # Keep our closed failure identifier across the dependency's wrapper, which
    # intentionally replaces unknown exception text. Cleanup still has to pass.
    failures = []

    def guarded_run(private):
        try:
            return _run_private_core(
                private, args=args, diag=diag, artifact=artifact, fixtures=fixtures,
                output=output, deadline=deadline, before=before,
            )
        except CandidateFailure as error:
            failures.append(error)
            return None

    try:
        artifacts = diag._run_in_private_directory(guarded_run)
        if failures:
            raise failures[0]
        result = {
            "schema_version": 1,
            "status": "passed",
            "scope": list(REQUIRED_CHECKS),
            "source_sha": args.expected_source_sha,
            "source_tree": subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=checkout, text=True
            ).strip(),
            "package_tree_sha256": before,
            "launcher_sha256": identity["launcher_sha256"],
            "application_sha256": identity["application_sha256"],
            "artifacts": artifacts,
            "facets": {key: "passed" for key in REQUIRED_CHECKS},
            "independent_oracle": "passed",
            "launch": "restricted_ordinary_user_native_windows_outside_checkout",
            "provenance_validated": bool(identity),
            "notices_validated": bool(notices),
            "notice_hashes": notices,
            "supervision_manifest_sha256": identity["manifest_sha256"],
            "oracle_sha256": _hash(args.oracle),
            "verifier_sha256": _hash(Path(__file__).with_name("verify_synthetic_oracle.py")),
            "driver_sha256": _hash(Path(__file__)),
            "literal_xlsx_verifier_sha256": _hash(Path(__file__).with_name("windows_candidate_xlsx.py")),
            "limits": [
                "Observed core facets only; no complete W01-W16 gate is implied.",
                "Pre-cancel and oversized-label rejection observed; active cancellation and inferential analysis remain unqualified.",
                "Build-host automation is not clean-machine evidence.",
                "No representative operator data or release acceptance.",
            ],
        }
        with (output / "core-driver-receipt.json").open("x", encoding="ascii") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        return result
    except BaseException:
        shutil.rmtree(output)
        raise



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-checkout", "artifact-dir", "fixture-dir", "output-dir", "oracle"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--expected-source-sha", required=True)
    args = parser.parse_args()
    try:
        qualify(args)
        print(json.dumps({"status": "passed", "scope": list(REQUIRED_CHECKS)}))
        return 0
    except CandidateFailure as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
        return 1
    except Exception:
        # Never echo child output, file contents, exception messages or paths.
        print(json.dumps({"status": "failed", "reason": "unexpected_driver_error"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
