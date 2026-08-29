from __future__ import annotations

import copy
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import time
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "quality" / "audit_build_delivery.py"

SPEC = importlib.util.spec_from_file_location("audit_build_delivery", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _evidence_or_skip() -> dict[str, Any]:
    if not AUDIT.exact_input_objects_available():
        pytest.skip(
            "exact baseline/PR input regeneration unavailable; baseline-independent artifact checks still run and #991 owns history"
        )
    return AUDIT.build_evidence()


def _archived_evidence() -> dict[str, Any]:
    payload = json.loads(AUDIT.EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _canonical_target_sha256(value: Any) -> str:
    payload = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _successful_validation_observations() -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for spec in AUDIT._validation_invocation_specs():
        stdout = AUDIT.SECURITY_SIBLING_PREFLIGHT_EXPECTED_STDOUT.get(spec["argv_display"], b"")
        observations.append(
            {
                **spec,
                "exit_code": 0,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stdout_bytes": len(stdout),
                "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_bytes": 0,
            }
        )
    return observations


def _synthetic_parser_smoke_ref() -> dict[str, Any]:
    profile = b"plugin_id: ci_smoke\n"
    approval = b'{"approved_by":"ci"}\n'
    directory_refs = [
        {"path": ".", "file_type": "directory", "mode": "0700"},
        {"path": "workspace", "file_type": "directory", "mode": "0500"},
        {"path": "workspace/samples", "file_type": "directory", "mode": "0500"},
    ]
    input_refs = [
        {
            "path": "workspace/expected_results.csv",
            "file_type": "regular",
            "mode": "0400",
            "link_count": 1,
            "size_bytes": len(AUDIT.PARSER_EXPECTED_RESULTS_CONTENT),
            "content_sha256": hashlib.sha256(AUDIT.PARSER_EXPECTED_RESULTS_CONTENT).hexdigest(),
        },
        {
            "path": "workspace/samples/sample_report_01.csv",
            "file_type": "regular",
            "mode": "0400",
            "link_count": 1,
            "size_bytes": len(AUDIT.PARSER_SAMPLE_REPORT_CONTENT),
            "content_sha256": hashlib.sha256(AUDIT.PARSER_SAMPLE_REPORT_CONTENT).hexdigest(),
        },
        {
            "path": "workspace/profile.yaml",
            "file_type": "regular",
            "mode": "0400",
            "link_count": 1,
            "size_bytes": len(profile),
            "content_sha256": hashlib.sha256(profile).hexdigest(),
        },
    ]
    evidence_input_refs = [
        {
            "path": "home/.metroliza/parser_plugins/profiles/approved/ci_smoke/profile.yaml",
            "file_type": "regular",
            "mode": "0400",
            "link_count": 1,
            "size_bytes": len(profile),
            "content_sha256": hashlib.sha256(profile).hexdigest(),
        },
        {
            "path": "home/.metroliza/parser_plugins/profiles/approved/ci_smoke/approval.json",
            "file_type": "regular",
            "mode": "0400",
            "link_count": 1,
            "size_bytes": len(approval),
            "content_sha256": hashlib.sha256(approval).hexdigest(),
        },
    ]
    portable_records = [*directory_refs, *input_refs, *evidence_input_refs]
    return {
        "schema_version": 1,
        "materialized_root": str(AUDIT.CAPTURE_PARSER_SMOKE_ROOT),
        "directory_refs": directory_refs,
        "input_refs": input_refs,
        "evidence_input_refs": evidence_input_refs,
        "profile_lifecycle": {
            "initial_state": "exclusive empty output slot",
            "generated_by_invocation_index": 0,
            "consumed_by_invocation_indices": [1, 2, 3],
        },
        "install_output_lifecycle": {
            "generated_by_invocation_index": 3,
            "consumed_by_invocation_index": 4,
            "protection": "held descriptors plus mode-0500 ancestor directories and mode-0400 installed profile/approval",
        },
        "binding": "held descriptor aliases supplied to every parser child; derived samples stay beneath held mode-0500 workspace/sample directories; live inode and byte guards surround each invocation; installed evidence inputs are frozen and retained",
        "filesystem_manifest_sha256": AUDIT._canonical_json_value_sha256(portable_records),
        "filesystem_entry_count": len(portable_records),
    }


def _populate_parser_smoke_install_outputs(parser_root: Path, profile: Path) -> Path:
    home = parser_root / "home"
    installed = home / ".metroliza" / "parser_plugins" / "profiles" / "approved" / "ci_smoke"
    installed.mkdir(parents=True)
    (installed.parent.parent.parent / ".profile-store.lock").write_bytes(b"")
    (installed / "profile.yaml").write_bytes(profile.read_bytes())
    (installed / "approval.json").write_text('{"approved_by":"ci"}\n', encoding="utf-8")
    return installed


def _successful_validation_execution() -> dict[str, Any]:
    security_materializations = [
        {
            **row,
            "filesystem_manifest_sha256": "a" * 64,
            "filesystem_identity_sha256": "1" * 64,
            "filesystem_entry_count": 1,
            "standalone": "no remotes, alternates, ignored files or untracked files",
        }
        for row in AUDIT._expected_security_materialization_refs()
    ]
    validation_checkout = {
        "materialized_root": str(AUDIT.CAPTURE_AUDIT_CWD),
        "commit": AUDIT.BASELINE_SHA,
        "tree": AUDIT.BASELINE_TREE,
        "head_state": "detached",
        "worktree_status": "exact two authorized untracked implementation overlays",
        "overlay_refs": AUDIT._audit_implementation_refs(),
        "filesystem_manifest_sha256": "b" * 64,
        "filesystem_identity_sha256": "2" * 64,
        "filesystem_entry_count": 1,
        "test_output_root_identity": {"device": 1, "inode": 2},
        "test_db_identity": {"device": 1, "inode": 3},
        "mode": "private 0700 root with recursively read-only .git; standalone no-hardlink clone with exact portable and identity manifests plus one identity-bound external test.db symlink and target",
        "standalone": "no remotes or alternates; only an exact ignored test.db symlink to the private external output root",
    }
    expected_inventory = AUDIT._expected_python_runtime_inventory()
    python_runtime = {
        "materialized_root": str(AUDIT.CAPTURE_VALIDATION_RUNTIME),
        "source_base": str(AUDIT.CAPTURE_RUNTIME_SOURCE_BASE),
        "source_venv": str(AUDIT.CAPTURE_RUNTIME_SOURCE_VENV),
        "python_version": "3.11.16",
        **AUDIT._expected_python_runtime_closure(),
        "distribution_inventory": expected_inventory,
        "distribution_inventory_sha256": AUDIT._expected_python_runtime_inventory_sha256(),
        "tool_versions": {
            "mypy": "2.2.0",
            "pip": "26.2.1",
            "pytest": "9.1.1",
            "ruff": "0.15.10",
        },
        "runtime_probe": AUDIT._expected_python_runtime_probe(),
        "executable_ref": dict(AUDIT.BOUND_EXECUTABLES[1]),
        "filesystem_identity_sha256": "3" * 64,
        "mode": "private 0500 root; recursively read-only no-hardlink runtime closure matching the exact complete portable-manifest pin",
        "user_site": "disabled by PYTHONNOUSERSITE=1",
        "pth_policy": "executable files require exact path/content allowlisting; non-code entries resolve strictly within the runtime; effective sys.path is probed",
    }
    return {
        "tested_implementation_refs": AUDIT._audit_implementation_refs(),
        "tested_execution_tool_refs": [dict(row) for row in AUDIT.BOUND_EXECUTABLES],
        "tested_security_materializations": security_materializations,
        "tested_validation_checkout": validation_checkout,
        "tested_python_runtime": python_runtime,
        "tested_parser_smoke_inputs": _synthetic_parser_smoke_ref(),
        "observations": _successful_validation_observations(),
    }


def _install_live_validation_refs(
    monkeypatch: pytest.MonkeyPatch,
    execution: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        AUDIT,
        "_execution_tool_refs",
        lambda: execution["tested_execution_tool_refs"],
    )
    monkeypatch.setattr(
        AUDIT,
        "_security_materialization_refs",
        lambda: execution["tested_security_materializations"],
    )
    monkeypatch.setattr(
        AUDIT,
        "_validation_checkout_ref",
        lambda: execution["tested_validation_checkout"],
    )
    monkeypatch.setattr(
        AUDIT,
        "_python_runtime_ref",
        lambda: execution["tested_python_runtime"],
    )
    monkeypatch.setattr(
        AUDIT,
        "_parser_smoke_input_ref",
        lambda: execution["tested_parser_smoke_inputs"],
    )


def _successful_validation_receipt(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    execution = _successful_validation_execution()
    _install_live_validation_refs(monkeypatch, execution)
    return AUDIT.create_validation_receipt(execution)


def _assert_archived_structured_provenance(evidence: dict[str, Any]) -> None:
    registry = evidence["evidence_registry"]
    structured = {reference: registry[reference] for reference in AUDIT.EVIDENCE_POINTERS}
    assert set(structured) == set(AUDIT.EVIDENCE_POINTERS)
    assert all(row["provenance_refs"] for row in structured.values())
    assert all(
        provenance.get("kind")
        for row in structured.values()
        for provenance in row["provenance_refs"]
    )
    assert all("baseline_ref" not in row for row in structured.values())

    def refs(reference: str) -> list[dict[str, Any]]:
        return structured[reference]["provenance_refs"]

    assert {(row.get("commit"), row.get("tree")) for row in refs("EV-PR972")} >= {
        (AUDIT.PR_INPUT_PARENT_SHA, AUDIT.PR_INPUT_PARENT_TREE),
        (AUDIT.PR972_SHA, AUDIT.PR972_TREE),
    }
    assert {row.get("run_id") for row in refs("EV-PR972")} >= {
        32932158352,
        32932162551,
    }
    assert {(row.get("commit"), row.get("tree")) for row in refs("EV-PR973")} >= {
        (AUDIT.PR_INPUT_PARENT_SHA, AUDIT.PR_INPUT_PARENT_TREE),
        (AUDIT.BASELINE_SHA, AUDIT.BASELINE_TREE),
        (AUDIT.PR973_SHA, AUDIT.PR973_TREE),
    }
    assert {row.get("run_id") for row in refs("EV-PR973")} >= {
        32932367574,
        32932363678,
    }
    assert {row.get("run_id") for row in refs("EV-CI")} == {None, 33151703847}
    assert {row["kind"] for row in refs("EV-ENVIRONMENT")} == {
        "git_tree",
        "phase_a_local_capture",
    }
    assert {row["kind"] for row in refs("EV-AUDIT-HARNESS")} == {"phase_a_content"}
    assert {row["kind"] for row in refs("EV-PLATFORM")} >= {
        "git_tree",
        "public_github_actions_run",
        "phase_a_local_capture",
        "phase_a_content",
    }


def _local_history(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "history"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Build Delivery Audit")
    _git(repo, "config", "user.email", "build-delivery@example.invalid")
    (repo / "tracked.txt").write_text("sanitized\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "sanitized history")
    return repo, _git(repo, "rev-parse", "HEAD")


def _implementation_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "implementation-root"
    audit_path = root / "scripts" / "quality" / "audit_build_delivery.py"
    test_path = root / "tests" / "test_build_delivery_audit.py"
    audit_path.parent.mkdir(parents=True)
    test_path.parent.mkdir(parents=True)
    audit_path.write_bytes(b"audit A\n")
    test_path.write_bytes(b"test A\n")
    audit_path.chmod(0o644)
    test_path.chmod(0o644)
    return root, audit_path, test_path


def test_archived_artifacts_have_baseline_independent_structure_and_content_binding() -> None:
    evidence = _archived_evidence()
    report = AUDIT.REPORT_PATH.read_text(encoding="utf-8")

    assert evidence["schema_version"] == 1
    assert evidence["audit"]["baseline_sha"] == AUDIT.BASELINE_SHA
    assert evidence["audit"]["baseline_tree"] == AUDIT.BASELINE_TREE
    assert evidence["scope"]["rule_count"] == 12
    assert evidence["scope"]["path_count"] == 58
    assert len(evidence["scope"]["paths"]) == 58
    assert AUDIT.canonical_json(evidence) == AUDIT.EVIDENCE_PATH.read_text(encoding="utf-8")
    assert AUDIT.render_report(evidence) == report
    assert "PHASE A PARKED — LEDGER/CI/PR DEFERRED" in report

    implementation_refs = evidence["audit_implementation"]
    assert {ref["path"] for ref in implementation_refs} == {
        "scripts/quality/audit_build_delivery.py",
        "tests/test_build_delivery_audit.py",
    }
    for ref in implementation_refs:
        content = (REPO_ROOT / ref["path"]).read_bytes()
        assert ref["content_sha256"] == hashlib.sha256(content).hexdigest()
        assert ref["git_blob_sha1"] == AUDIT._git_blob_sha1(content)
        assert ref["size_bytes"] == len(content)

    for control in evidence["falsification"]["controls"]:
        assert control["audit_mutation_refs"] == implementation_refs
    for probe in evidence["discovery_probes"]:
        assert probe["audit_record_refs"] == implementation_refs

    registry = evidence["evidence_registry"]
    assert AUDIT._collect_evidence_refs(evidence) <= set(registry)
    for record in registry.values():
        target = AUDIT.resolve_json_pointer(evidence, record["json_pointer"])
        assert record["resolved_target_type"] == type(target).__name__
        assert record["resolved_target_sha256"] == _canonical_target_sha256(target)
    _assert_archived_structured_provenance(evidence)


def test_exact_baseline_and_owned_expansion_are_stable() -> None:
    evidence = _evidence_or_skip()

    assert evidence["audit"]["baseline_sha"] == AUDIT.BASELINE_SHA
    assert evidence["audit"]["baseline_tree"] == AUDIT.BASELINE_TREE
    assert evidence["scope"]["rule_count"] == 12
    assert evidence["scope"]["path_count"] == 58
    paths = [record["path"] for record in evidence["scope"]["paths"]]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    assert all(len(record["git_blob_sha1"]) == 40 for record in evidence["scope"]["paths"])
    assert all(len(record["content_sha256"]) == 64 for record in evidence["scope"]["paths"])
    assert all(rule["phase_a_status"].endswith("deferred") for rule in evidence["scope"]["rules"])


def test_validation_receipt_binds_exact_invocations_and_tested_audit_bytes() -> None:
    evidence = _archived_evidence()
    implementation_refs = evidence["audit_implementation"]
    receipt = evidence["validation_receipt"]

    assert receipt["tested_implementation_refs"] == implementation_refs
    assert evidence["validation"] == receipt["validation_records"]
    assert (
        evidence["validation_receipt_sha256"]
        == hashlib.sha256(AUDIT.canonical_json(receipt).encode("utf-8")).hexdigest()
    )
    for row in evidence["validation"]:
        assert row["argv"] and all(isinstance(argv, str) and argv for argv in row["argv"])
        assert row["cwd"] == "/tmp/metroliza-976-validation-checkout-v5"
        assert row["observed_at"] == AUDIT.VALIDATION_GATE_DATE
        assert row["exit_code"] == 0
        assert row["result"]
        if row["command"] != "pinned-sibling security audit":
            assert row["subject_refs"] == [AUDIT.BASELINE_SUBJECT_REF]
        assert "current_implementation_refs" not in row
        assert "validation_receipt.tested_implementation_refs" in row["binding"]
        assert row["invocations"]
        assert all(invocation["exit_code"] == 0 for invocation in row["invocations"])
        assert all(isinstance(invocation["argv"], list) for invocation in row["invocations"])
        assert all(len(invocation["stdout_sha256"]) == 64 for invocation in row["invocations"])
        assert all(len(invocation["stderr_sha256"]) == 64 for invocation in row["invocations"])
    assert sum(len(row["invocations"]) for row in evidence["validation"]) == len(
        AUDIT._validation_invocation_specs()
    )

    security = next(
        row for row in evidence["validation"] if row["command"] == "pinned-sibling security audit"
    )
    assert security["subject_refs"] == [
        AUDIT.BASELINE_SUBJECT_REF,
        *[
            f"{row['repository']} HEAD@{row['commit']} tree={row['tree']} "
            f"status={row['worktree_status']}"
            for row in AUDIT.SECURITY_SIBLING_SUBJECTS
        ],
    ]
    assert security["sibling_checkout_preflight"]["observed"] == list(
        AUDIT.SECURITY_SIBLING_SUBJECTS
    )
    assert len(security["sibling_checkout_preflight"]["argv"]) == 9
    assert all(
        row["worktree_status"] == "clean; empty porcelain including untracked files"
        for row in security["sibling_checkout_preflight"]["observed"]
    )


def test_validation_receipt_rejects_stale_implementation_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _successful_validation_receipt(monkeypatch)
    receipt["tested_implementation_refs"][0]["content_sha256"] = "0" * 64

    with pytest.raises(AUDIT.AuditError, match="tested-byte refs are stale"):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


def test_validation_receipt_creator_uses_current_implementation_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _successful_validation_execution()
    _install_live_validation_refs(monkeypatch, execution)
    receipt = AUDIT.create_validation_receipt(execution)

    assert receipt["tested_implementation_refs"] == AUDIT._audit_implementation_refs()
    assert sum(len(row["invocations"]) for row in receipt["validation_records"]) == len(
        execution["observations"]
    )
    assert receipt["receipt_origin"]["automatic_retargeting"] is False
    assert receipt["observed_at"] == AUDIT.VALIDATION_GATE_DATE
    assert receipt["observed_at"] != AUDIT.CAPTURE_DATE
    assert all(
        row["observed_at"] == AUDIT.VALIDATION_GATE_DATE for row in receipt["validation_records"]
    )
    assert all(
        invocation["observed_at"] == AUDIT.VALIDATION_GATE_DATE
        for row in receipt["validation_records"]
        for invocation in row["invocations"]
    )


@pytest.mark.parametrize("observed_at", (None, "2026-8-29", "2026-08-29T00:00:00"))
def test_validation_receipt_rejects_noncanonical_observation_date(
    monkeypatch: pytest.MonkeyPatch,
    observed_at: object,
) -> None:
    receipt = _successful_validation_receipt(monkeypatch)
    receipt["observed_at"] = observed_at

    with pytest.raises(AUDIT.AuditError, match="exact ISO calendar date"):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


def test_validation_receipt_rejects_historical_capture_date_as_backdated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _successful_validation_receipt(monkeypatch)
    receipt["observed_at"] = AUDIT.CAPTURE_DATE

    with pytest.raises(AUDIT.AuditError, match="observation date drifted"):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


def test_validation_receipt_creator_rejects_between_execution_ref_retarget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _successful_validation_execution()
    _install_live_validation_refs(monkeypatch, execution)
    changed_refs = copy.deepcopy(execution["tested_implementation_refs"])
    changed_refs[0]["content_sha256"] = "0" * 64
    monkeypatch.setattr(AUDIT, "_audit_implementation_refs", lambda: changed_refs)

    with pytest.raises(AUDIT.AuditError, match="tested-byte refs"):
        AUDIT.create_validation_receipt(execution)


def test_validation_receipt_creator_rejects_missing_execution_results() -> None:
    with pytest.raises(AUDIT.AuditError, match="execution result object"):
        AUDIT.create_validation_receipt()


@pytest.mark.parametrize(
    "field",
    ("pyvenv_cfg_sha256", "filesystem_manifest_sha256", "distribution_inventory_sha256"),
)
def test_validation_python_runtime_ref_rejects_valid_format_unapproved_pin(field: str) -> None:
    runtime_ref = copy.deepcopy(_successful_validation_execution()["tested_python_runtime"])
    runtime_ref[field] = "f" * 64

    with pytest.raises(AUDIT.AuditError, match="validation Python runtime ref"):
        AUDIT._validate_python_runtime_ref(runtime_ref)


def test_validation_python_runtime_ref_rejects_unapproved_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_ref = copy.deepcopy(_successful_validation_execution()["tested_python_runtime"])
    runtime_ref["distribution_inventory"].append({"name": "unapproved", "version": "1.0"})
    runtime_ref["distribution_inventory_sha256"] = AUDIT._canonical_json_value_sha256(
        runtime_ref["distribution_inventory"]
    )
    monkeypatch.setattr(
        AUDIT,
        "_expected_python_runtime_inventory_sha256",
        lambda: runtime_ref["distribution_inventory_sha256"],
    )

    with pytest.raises(AUDIT.AuditError, match="independently pinned distribution inventory"):
        AUDIT._validate_python_runtime_ref(runtime_ref)


def test_validation_receipt_creator_rejects_nonzero_child_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _successful_validation_execution()
    _install_live_validation_refs(monkeypatch, execution)
    execution["observations"][1]["exit_code"] = 7

    with pytest.raises(AUDIT.AuditError, match="did not exit zero"):
        AUDIT.create_validation_receipt(execution)


def test_validation_receipt_rejects_extra_child_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _successful_validation_receipt(monkeypatch)
    receipt["validation_records"][0]["invocations"][0]["unexpected"] = True

    with pytest.raises(AUDIT.AuditError, match="schema keys drifted"):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


def test_validation_receipt_rejects_plan_hash_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _successful_validation_receipt(monkeypatch)
    receipt["validation_plan_sha256"] = "0" * 64

    with pytest.raises(AUDIT.AuditError, match="execution plan drifted"):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


@pytest.mark.parametrize(
    ("live_function", "execution_key", "error"),
    (
        (
            "_security_materialization_refs",
            "tested_security_materializations",
            "security materializations are stale",
        ),
        (
            "_validation_checkout_ref",
            "tested_validation_checkout",
            "checkout materialization is stale",
        ),
        (
            "_python_runtime_ref",
            "tested_python_runtime",
            "Python runtime is stale",
        ),
        (
            "_parser_smoke_input_ref",
            "tested_parser_smoke_inputs",
            "parser-smoke inputs are stale",
        ),
    ),
)
def test_validation_receipt_rejects_live_materialization_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    live_function: str,
    execution_key: str,
    error: str,
) -> None:
    execution = _successful_validation_execution()
    _install_live_validation_refs(monkeypatch, execution)
    receipt = AUDIT.create_validation_receipt(execution)
    changed = copy.deepcopy(execution[execution_key])
    if isinstance(changed, list):
        changed[0]["filesystem_identity_sha256"] = "f" * 64
    elif execution_key == "tested_parser_smoke_inputs":
        changed["evidence_input_refs"][1]["content_sha256"] = "f" * 64
        changed["filesystem_manifest_sha256"] = AUDIT._canonical_json_value_sha256(
            [
                *changed["directory_refs"],
                *changed["input_refs"],
                *changed["evidence_input_refs"],
            ]
        )
    else:
        changed["filesystem_identity_sha256"] = "f" * 64
    monkeypatch.setattr(AUDIT, live_function, lambda: changed)

    with pytest.raises(AUDIT.AuditError, match=error):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


def test_validation_receipt_rejects_boolean_child_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _successful_validation_execution()
    _install_live_validation_refs(monkeypatch, execution)
    execution["observations"][0]["exit_code"] = False

    with pytest.raises(AUDIT.AuditError, match="did not exit zero"):
        AUDIT.create_validation_receipt(execution)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("sequence", True),
        ("sequence", 1.0),
        ("group_index", False),
        ("group_index", 0.0),
        ("invocation_index", False),
        ("invocation_index", 0.0),
    ),
)
def test_validation_receipt_rejects_numeric_identity_type_confusion(
    field: str,
    replacement: bool | float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _successful_validation_execution()
    _install_live_validation_refs(monkeypatch, execution)
    execution["observations"][0][field] = replacement

    with pytest.raises(AUDIT.AuditError, match="exact JSON type drifted"):
        AUDIT.create_validation_receipt(execution)


def test_validation_receipt_rejects_float_implementation_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _successful_validation_receipt(monkeypatch)
    receipt["tested_implementation_refs"][0]["size_bytes"] = float(
        receipt["tested_implementation_refs"][0]["size_bytes"]
    )

    with pytest.raises(AUDIT.AuditError, match="tested-byte refs are stale"):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


@pytest.mark.parametrize("replacement", (0, 0.0))
def test_validation_receipt_rejects_numeric_false_origin(
    replacement: int | float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _successful_validation_receipt(monkeypatch)
    receipt["receipt_origin"]["automatic_retargeting"] = replacement

    with pytest.raises(AUDIT.AuditError, match="origin/retargeting contract drifted"):
        AUDIT._validate_validation_receipt(receipt, AUDIT._audit_implementation_refs())


def test_validation_git_environment_disables_replace_refs(tmp_path: Path) -> None:
    repo = tmp_path / "replace-ref"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Build Delivery Audit")
    _git(repo, "config", "user.email", "build-delivery@example.invalid")
    tracked = repo / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "original")
    original = _git(repo, "rev-parse", "HEAD")
    tracked.write_text("replacement\n", encoding="utf-8")
    _git(repo, "commit", "-am", "replacement")
    replacement = _git(repo, "rev-parse", "HEAD")
    _git(repo, "replace", original, replacement)

    normal = subprocess.run(
        ["git", "show", f"{original}:tracked.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    isolated = subprocess.run(
        ["git", "show", f"{original}:tracked.txt"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=dict(AUDIT.VALIDATION_EXECUTION_ENV),
    )

    assert normal.stdout == b"replacement\n"
    assert isolated.stdout == b"original\n"
    assert AUDIT.VALIDATION_EXECUTION_ENV["GIT_ATTR_NOSYSTEM"] == "1"
    assert AUDIT.VALIDATION_EXECUTION_ENV["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert AUDIT.VALIDATION_EXECUTION_ENV["GIT_NO_LAZY_FETCH"] == "1"
    assert AUDIT.VALIDATION_EXECUTION_ENV["GIT_TERMINAL_PROMPT"] == "0"
    assert AUDIT.VALIDATION_EXECUTION_ENV["PYTHONNOUSERSITE"] == "1"
    assert AUDIT.VALIDATION_EXECUTION_ENV["PYTHONSAFEPATH"] == "1"
    assert AUDIT.VALIDATION_EXECUTION_ENV["VIRTUAL_ENV"] == str(
        AUDIT.CAPTURE_VALIDATION_RUNTIME_VENV
    )
    python_argv = {
        spec["argv"][0]
        for spec in AUDIT._validation_invocation_specs()
        if spec["argv"][0] != "/usr/bin/git"
    }
    assert python_argv == {str(AUDIT.CAPTURE_VALIDATION_PYTHON)}


def test_security_audit_materialization_is_detached_from_mutable_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "sources"
    source = source_root / "sibling"
    materialized_root = tmp_path / "materialized"
    source.mkdir(parents=True)
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Build Delivery Audit")
    _git(source, "config", "user.email", "build-delivery@example.invalid")
    (source / "pyproject.toml").write_text("[project]\nname='sibling'\n", encoding="utf-8")
    (source / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
    _git(source, "add", "pyproject.toml", ".gitignore")
    _git(source, "commit", "-m", "pinned")
    commit = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    subjects = (
        {
            "repository": "example/sibling",
            "directory": "sibling",
            "commit": commit,
            "tree": tree,
            "worktree_status": "clean; empty porcelain including untracked files",
        },
    )
    monkeypatch.setattr(AUDIT, "CAPTURE_SECURITY_SIBLINGS", source_root)
    monkeypatch.setattr(AUDIT, "CAPTURE_SECURITY_MATERIALIZED", materialized_root)
    monkeypatch.setattr(AUDIT, "SECURITY_SIBLING_SUBJECTS", subjects)

    try:
        refs = AUDIT._materialize_security_siblings()
        (source / "pyproject.toml").write_text("mutated source\n", encoding="utf-8")

        assert refs == AUDIT._security_materialization_refs()
        assert (materialized_root / "sibling" / "pyproject.toml").read_text(
            encoding="utf-8"
        ) == "[project]\nname='sibling'\n"
        assert _git(materialized_root / "sibling", "remote") == ""
        assert stat.S_IMODE(materialized_root.stat().st_mode) == 0o500

        materialized_repo = materialized_root / "sibling"
        tracked = materialized_repo / "pyproject.toml"
        tracked.chmod(0o644)
        with pytest.raises(AUDIT.AuditError, match="mode drifted"):
            AUDIT._security_materialization_refs()
        tracked.chmod(0o444)

        materialized_repo.chmod(0o755)
        ignored = materialized_repo / "probe.ignored"
        ignored.write_bytes(b"ignored\n")
        ignored.chmod(0o444)
        materialized_repo.chmod(0o555)
        with pytest.raises(AUDIT.AuditError, match="ignored or untracked"):
            AUDIT._security_materialization_refs()
        materialized_repo.chmod(0o755)
        ignored.unlink()
        materialized_repo.chmod(0o555)

        git_dir = materialized_repo / ".git"
        git_dir.chmod(0o755)
        head = git_dir / "HEAD"
        hardlink = git_dir / "HEAD.link"
        os.link(head, hardlink)
        git_dir.chmod(0o555)
        with pytest.raises(AUDIT.AuditError, match="hard-linked"):
            AUDIT._security_materialization_refs()
        git_dir.chmod(0o755)
        hardlink.unlink()
        git_dir.chmod(0o555)

        info = git_dir / "objects" / "info"
        info.chmod(0o755)
        alternates = info / "alternates"
        alternates.write_text("/tmp/attacker-objects\n", encoding="utf-8")
        alternates.chmod(0o444)
        info.chmod(0o555)
        with pytest.raises(AUDIT.AuditError, match="alternates"):
            AUDIT._security_materialization_refs()
    finally:
        if materialized_root.exists():
            materialized_root.chmod(0o700)
            for path in materialized_root.rglob("*"):
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)


def test_validation_executor_hashes_raw_streams_and_stops_at_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = AUDIT._validation_invocation_specs()[:3]
    calls: list[list[str]] = []
    refs = [{"path": "audit.py", "content_sha256": "a" * 64}]
    successful = _successful_validation_execution()
    materializations = successful["tested_security_materializations"]
    validation_checkout = successful["tested_validation_checkout"]
    python_runtime = successful["tested_python_runtime"]
    parser_smoke_inputs = successful["tested_parser_smoke_inputs"]
    parser_smoke_state: dict[str, Any] = {}
    monkeypatch.setattr(
        AUDIT,
        "_prepare_validation_environment",
        lambda: (
            materializations,
            validation_checkout,
            python_runtime,
            parser_smoke_state,
        ),
    )
    monkeypatch.setattr(AUDIT, "_security_materialization_refs", lambda: materializations)
    monkeypatch.setattr(AUDIT, "_validation_checkout_ref", lambda: validation_checkout)
    monkeypatch.setattr(AUDIT, "_python_runtime_ref", lambda: python_runtime)
    monkeypatch.setattr(
        AUDIT,
        "_parser_smoke_state_ref",
        lambda _state: parser_smoke_inputs,
    )
    monkeypatch.setattr(AUDIT, "_parser_smoke_input_ref", lambda: parser_smoke_inputs)
    monkeypatch.setattr(AUDIT, "_audit_implementation_refs", lambda: refs)
    monkeypatch.setattr(AUDIT, "_validation_invocation_specs", lambda: specs)

    @contextmanager
    def fake_bound_executable(argv_path: str):
        descriptor = os.open("/usr/bin/true", os.O_RDONLY)
        observed = next(
            dict(row) for row in AUDIT.BOUND_EXECUTABLES if row["argv_path"] == argv_path
        )
        try:
            yield descriptor, observed
        finally:
            os.close(descriptor)

    monkeypatch.setattr(AUDIT, "_bound_executable", fake_bound_executable)
    monkeypatch.setattr(
        AUDIT,
        "_observe_bound_executable_descriptor",
        lambda _descriptor, *, argv_path, resolved_path: next(
            dict(row) for row in AUDIT.BOUND_EXECUTABLES if row["argv_path"] == argv_path
        ),
    )

    def run_child(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["env"] == specs[len(calls) - 1]["environment"]
        assert kwargs["executable"].startswith("/proc/self/fd/")
        assert int(kwargs["executable"].rsplit("/", 1)[1]) in kwargs["pass_fds"]
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout=b"\xff\x00", stderr=b"\xfe")
        return subprocess.CompletedProcess(argv, 9, stdout=b"failed", stderr=b"boom")

    monkeypatch.setattr(AUDIT.subprocess, "run", run_child)
    with pytest.raises(AUDIT.AuditError, match="child 2 exited 9"):
        AUDIT._execute_validation_suite()
    assert calls == [specs[0]["argv"], specs[1]["argv"]]


def test_parser_smoke_inputs_are_exclusively_published_beneath_private_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)

    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        workspace = parser_root / "workspace"
        samples = workspace / "samples"
        expected_results = workspace / "expected_results.csv"
        sample_report = samples / "sample_report_01.csv"
        profile = workspace / "profile.yaml"
        home = parser_root / "home"
        for directory, expected_mode in (
            (parser_root, 0o700),
            (workspace, 0o500),
            (samples, 0o500),
            (home, 0o700),
        ):
            metadata = directory.stat(follow_symlinks=False)
            assert stat.S_ISDIR(metadata.st_mode)
            assert metadata.st_uid == os.getuid()
            assert stat.S_IMODE(metadata.st_mode) == expected_mode
        for fixture in (expected_results, sample_report):
            metadata = fixture.stat(follow_symlinks=False)
            assert stat.S_ISREG(metadata.st_mode)
            assert metadata.st_uid == os.getuid()
            assert metadata.st_nlink == 1
            assert stat.S_IMODE(metadata.st_mode) == 0o400
        assert expected_results.read_text(encoding="utf-8").startswith(
            "sample_file,reference,report_date"
        )
        assert sample_report.read_text(encoding="utf-8").startswith("SUPPLIER TEMPLATE MARKER\n")
        assert profile.read_bytes() == b""
        assert stat.S_IMODE(profile.stat().st_mode) == 0o600
        for descriptor in (state["expected_results_fd"], state["sample_report_fd"]):
            assert os.get_blocking(descriptor) is False
            with pytest.raises(OSError) as raised:
                os.write(descriptor, b"mutation")
            assert raised.value.errno == errno.EBADF
        AUDIT._verify_parser_smoke_state(state, require_profile=False)
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_guard_rejects_zero_exit_style_fixture_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        expected_results = parser_root / "workspace" / "expected_results.csv"
        expected_results.chmod(0o600)
        expected_results.write_bytes(b"attacker-controlled oracle\n")

        with pytest.raises(AUDIT.AuditError, match="expected-results fixture"):
            AUDIT._verify_parser_smoke_state(state, require_profile=False)
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_guard_rejects_same_bytes_inode_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        sample_report = parser_root / "workspace" / "samples" / "sample_report_01.csv"
        sample_report.parent.chmod(0o700)
        sample_report.unlink()
        sample_report.write_bytes(AUDIT.PARSER_SAMPLE_REPORT_CONTENT)
        sample_report.chmod(0o600)

        with pytest.raises(AUDIT.AuditError, match="samples directory|sample-report fixture"):
            AUDIT._verify_parser_smoke_state(state, require_profile=False)
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_guard_rejects_workspace_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        workspace = parser_root / "workspace"
        workspace.rename(parser_root / "workspace.saved")
        workspace.mkdir(mode=0o700)

        with pytest.raises(AUDIT.AuditError, match="workspace lexical identity drifted"):
            AUDIT._verify_parser_smoke_state(state, require_profile=False)
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_guard_binds_profile_and_allows_intended_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        profile = parser_root / "workspace" / "profile.yaml"
        profile.write_text("plugin_id: ci_smoke\n", encoding="utf-8")

        AUDIT._capture_parser_smoke_profile(state)
        assert os.get_blocking(state["profile_fd"]) is False
        _populate_parser_smoke_install_outputs(parser_root, profile)
        AUDIT._capture_parser_smoke_install_outputs(state)
        AUDIT._verify_parser_smoke_state(state, require_profile=True)
        parser_ref = AUDIT._parser_smoke_state_ref(state)

        assert [row["path"] for row in parser_ref["input_refs"]] == [
            "workspace/expected_results.csv",
            "workspace/samples/sample_report_01.csv",
            "workspace/profile.yaml",
        ]
        assert stat.S_IMODE(profile.stat().st_mode) == 0o400
        assert parser_ref["filesystem_entry_count"] == 8
        assert len(parser_ref["evidence_input_refs"]) == 2
        assert AUDIT._parser_smoke_input_ref() == parser_ref
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_install_capture_rejects_home_mode_drift_before_freeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        profile = parser_root / "workspace" / "profile.yaml"
        profile.write_text("plugin_id: ci_smoke\n", encoding="utf-8")
        AUDIT._capture_parser_smoke_profile(state)
        installed = _populate_parser_smoke_install_outputs(parser_root, profile)
        home = parser_root / "home"
        home.chmod(0o777)

        with pytest.raises(AUDIT.AuditError, match="home directory"):
            AUDIT._capture_parser_smoke_install_outputs(state)

        assert stat.S_IMODE(home.stat().st_mode) == 0o777
        assert stat.S_IMODE((installed / "profile.yaml").stat().st_mode) == 0o644
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_install_capture_rejects_fifo_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        profile = parser_root / "workspace" / "profile.yaml"
        profile.write_text("plugin_id: ci_smoke\n", encoding="utf-8")
        AUDIT._capture_parser_smoke_profile(state)
        installed = (
            parser_root
            / "home"
            / ".metroliza"
            / "parser_plugins"
            / "profiles"
            / "approved"
            / "ci_smoke"
        )
        installed.mkdir(parents=True)
        (installed.parent.parent.parent / ".profile-store.lock").write_bytes(b"")
        os.mkfifo(installed / "profile.yaml")
        (installed / "approval.json").write_text('{"approved_by":"ci"}\n', encoding="utf-8")
        real_open = AUDIT.os.open

        def require_nonblocking_open(
            path: os.PathLike[str] | str,
            flags: int,
            *args: object,
            **kwargs: object,
        ) -> int:
            if path == "profile.yaml":
                assert flags & os.O_NONBLOCK
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(AUDIT.os, "open", require_nonblocking_open)

        with pytest.raises(AUDIT.AuditError, match="single-link regular file"):
            AUDIT._capture_parser_smoke_install_outputs(state)

        assert stat.S_IMODE((parser_root / "home").stat().st_mode) == 0o700
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_install_capture_rejects_hardlink_before_mode_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        profile = parser_root / "workspace" / "profile.yaml"
        profile.write_text("plugin_id: ci_smoke\n", encoding="utf-8")
        AUDIT._capture_parser_smoke_profile(state)
        installed = (
            parser_root
            / "home"
            / ".metroliza"
            / "parser_plugins"
            / "profiles"
            / "approved"
            / "ci_smoke"
        )
        installed.mkdir(parents=True)
        (installed.parent.parent.parent / ".profile-store.lock").write_bytes(b"")
        victim = tmp_path / "victim.txt"
        victim.write_text("must remain unchanged\n", encoding="utf-8")
        victim.chmod(0o644)
        os.link(victim, installed / "profile.yaml")
        (installed / "approval.json").write_text('{"approved_by":"ci"}\n', encoding="utf-8")

        with pytest.raises(AUDIT.AuditError, match="single-link regular file"):
            AUDIT._capture_parser_smoke_install_outputs(state)

        assert stat.S_IMODE(victim.stat().st_mode) == 0o644
        assert victim.stat().st_nlink == 2
    finally:
        AUDIT._close_parser_smoke_state(state)


@pytest.mark.parametrize(
    ("relative_path", "drift_mode"),
    (
        (
            "home/.metroliza/parser_plugins/profiles/approved/ci_smoke/profile.yaml",
            0o600,
        ),
        ("home/.metroliza/parser_plugins/.profile-store.lock", 0o400),
        ("home", 0o700),
        ("home/.metroliza/parser_plugins", 0o700),
    ),
)
def test_parser_smoke_live_ref_rejects_mode_drift_without_normalizing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    drift_mode: int,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        profile = parser_root / "workspace" / "profile.yaml"
        profile.write_text("plugin_id: ci_smoke\n", encoding="utf-8")
        AUDIT._capture_parser_smoke_profile(state)
        _populate_parser_smoke_install_outputs(parser_root, profile)
        AUDIT._capture_parser_smoke_install_outputs(state)
        AUDIT._verify_parser_smoke_state(state, require_profile=True)
    finally:
        AUDIT._close_parser_smoke_state(state)

    target = parser_root / relative_path
    target.chmod(drift_mode)
    drifted = target.stat()

    def reject_live_fchmod(_descriptor: int, _mode: int) -> None:
        raise AssertionError("live parser-ref reopen must not call fchmod")

    monkeypatch.setattr(AUDIT.os, "fchmod", reject_live_fchmod)
    with pytest.raises(AUDIT.AuditError, match="mode"):
        AUDIT._parser_smoke_input_ref()

    after = target.stat()
    assert stat.S_IMODE(after.st_mode) == drift_mode
    assert after.st_ctime_ns == drifted.st_ctime_ns


def test_parser_smoke_live_ref_rejects_persisted_fifo_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        profile = parser_root / "workspace" / "profile.yaml"
        profile.write_text("plugin_id: ci_smoke\n", encoding="utf-8")
        AUDIT._capture_parser_smoke_profile(state)
        _populate_parser_smoke_install_outputs(parser_root, profile)
        AUDIT._capture_parser_smoke_install_outputs(state)
    finally:
        AUDIT._close_parser_smoke_state(state)

    workspace = parser_root / "workspace"
    expected_results = workspace / "expected_results.csv"
    workspace.chmod(0o700)
    expected_results.unlink()
    os.mkfifo(expected_results)
    workspace.chmod(0o500)
    real_open = AUDIT.os.open

    def require_nonblocking_open(
        path: os.PathLike[str] | str,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        if path == "expected_results.csv":
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(AUDIT.os, "open", require_nonblocking_open)
    with pytest.raises(AUDIT.AuditError, match="single-link regular file"):
        AUDIT._parser_smoke_input_ref()

    assert stat.S_ISFIFO(expected_results.stat(follow_symlinks=False).st_mode)


def test_parser_smoke_plan_uses_bound_workspace_for_derived_samples() -> None:
    parser_group = next(
        group for group in AUDIT.CAPTURED_VALIDATION if group["command"] == "parser smoke"
    )

    for invocation_index in (1, 3):
        argv = parser_group["argv"][invocation_index]
        assert " --sample " not in argv
        assert f"--workspace {AUDIT.CAPTURE_PARSER_SMOKE_ROOT}/workspace" in argv


def test_parser_smoke_every_runtime_operand_is_a_held_descriptor_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_root = str(AUDIT.CAPTURE_PARSER_SMOKE_ROOT)
    specs = [
        {
            **spec,
            "argv": [
                token.replace(original_root, str(tmp_path / "parser-smoke"))
                for token in spec["argv"]
            ],
        }
        for spec in AUDIT._validation_invocation_specs()
        if spec["command"] == "parser smoke"
    ]
    parser_root = tmp_path / "parser-smoke"
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        runtime_argv, retained = AUDIT._bound_parser_smoke_invocation(specs[0], state)
        assert runtime_argv != specs[0]["argv"]
        assert retained == (state["profile_fd"],)
        assert all(str(parser_root) not in token for token in runtime_argv)

        (parser_root / "workspace" / "profile.yaml").write_text(
            "plugin_id: ci_smoke\n", encoding="utf-8"
        )
        AUDIT._capture_parser_smoke_profile(state)
        expected_role_counts = {1: 3, 2: 2, 3: 4, 4: 1}
        for spec in specs[1:]:
            runtime_argv, retained = AUDIT._bound_parser_smoke_invocation(spec, state)
            assert len(retained) == expected_role_counts[spec["invocation_index"]]
            assert all(str(parser_root) not in token for token in runtime_argv)
            aliases = [token for token in runtime_argv if token.startswith("/proc/self/fd/")]
            assert len(aliases) == len(retained)
            assert {int(alias.split("/")[4]) for alias in aliases} == set(retained)
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_descriptor_aliases_survive_workspace_lexical_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_root = str(AUDIT.CAPTURE_PARSER_SMOKE_ROOT)
    parser_root = tmp_path / "parser-smoke"
    validate_spec = next(
        {
            **spec,
            "argv": [token.replace(original_root, str(parser_root)) for token in spec["argv"]],
        }
        for spec in AUDIT._validation_invocation_specs()
        if spec["command"] == "parser smoke" and spec["invocation_index"] == 1
    )
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        (parser_root / "workspace" / "profile.yaml").write_text(
            "plugin_id: ci_smoke\n", encoding="utf-8"
        )
        AUDIT._capture_parser_smoke_profile(state)
        runtime_argv, retained = AUDIT._bound_parser_smoke_invocation(validate_spec, state)
        workspace = parser_root / "workspace"
        saved = parser_root / "workspace.saved"
        workspace.rename(saved)
        workspace.mkdir(mode=0o700)
        (workspace / "expected_results.csv").write_text("replacement\n", encoding="utf-8")

        expected_alias = f"/proc/self/fd/{state['expected_results_fd']}"
        workspace_alias = f"/proc/self/fd/{state['workspace_fd']}"
        profile_alias = f"/proc/self/fd/{state['profile_fd']}"
        assert expected_alias in runtime_argv
        assert workspace_alias in runtime_argv
        assert profile_alias in runtime_argv
        assert state["expected_results_fd"] in retained
        assert Path(expected_alias).read_bytes() == AUDIT.PARSER_EXPECTED_RESULTS_CONTENT
        assert (
            Path(workspace_alias, "samples", "sample_report_01.csv").read_bytes()
            == AUDIT.PARSER_SAMPLE_REPORT_CONTENT
        )
        assert Path(profile_alias).read_text(encoding="utf-8") == "plugin_id: ci_smoke\n"
        assert (workspace / "expected_results.csv").read_text(encoding="utf-8") == "replacement\n"
    finally:
        AUDIT._close_parser_smoke_state(state)


def test_parser_smoke_descriptor_bound_sequence_executes_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_root = str(AUDIT.CAPTURE_PARSER_SMOKE_ROOT)
    parser_root = tmp_path / "parser-smoke"
    specs = [
        {
            **spec,
            "argv": [
                sys.executable,
                *[token.replace(original_root, str(parser_root)) for token in spec["argv"][1:]],
            ],
        }
        for spec in AUDIT._validation_invocation_specs()
        if spec["command"] == "parser smoke"
    ]
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    state = AUDIT._prepare_parser_smoke_inputs()
    try:
        for spec in specs:
            AUDIT._verify_parser_smoke_state(
                state,
                require_profile=spec["invocation_index"] > 0,
            )
            runtime_argv, retained = AUDIT._bound_parser_smoke_invocation(spec, state)
            environment = dict(spec["environment"])
            environment["PYTHONPATH"] = f"{REPO_ROOT / 'src'}:{REPO_ROOT}"
            completed = subprocess.run(
                runtime_argv,
                cwd=REPO_ROOT,
                env=environment,
                pass_fds=retained,
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, (completed.stdout, completed.stderr)
            if spec["invocation_index"] == 0:
                AUDIT._capture_parser_smoke_profile(state)
            elif spec["invocation_index"] == 3:
                AUDIT._capture_parser_smoke_install_outputs(state)
            AUDIT._verify_parser_smoke_state(state, require_profile=True)

        parser_ref = AUDIT._parser_smoke_state_ref(state)
        assert AUDIT._validate_parser_smoke_input_ref(parser_ref) == parser_ref
        assert stat.S_IMODE((parser_root / "home").stat().st_mode) == 0o500
    finally:
        AUDIT._close_parser_smoke_state(state)


@pytest.mark.parametrize("extra_key", ("filesystem_identity_sha256", "descriptor"))
def test_parser_smoke_portable_ref_rejects_ephemeral_or_descriptor_fields(
    extra_key: str,
) -> None:
    parser_ref = _synthetic_parser_smoke_ref()
    parser_ref[extra_key] = "f" * 64 if extra_key.endswith("sha256") else 7

    with pytest.raises(AUDIT.AuditError, match="schema keys drifted"):
        AUDIT._validate_parser_smoke_input_ref(parser_ref)


def test_parser_smoke_root_preclaim_race_fails_closed_and_preserves_victim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_root = tmp_path / "parser-smoke"
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "sentinel.txt"
    sentinel.write_text("preserve me\n", encoding="utf-8")
    monkeypatch.setattr(AUDIT, "CAPTURE_PARSER_SMOKE_ROOT", parser_root)
    real_mkdir = Path.mkdir
    injected = False

    def inject_preclaimer(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal injected
        if path == parser_root and not injected:
            injected = True
            path.symlink_to(victim, target_is_directory=True)
        real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", inject_preclaimer)

    with pytest.raises(AUDIT.AuditError, match="fresh and exclusively created"):
        AUDIT._prepare_parser_smoke_inputs()

    assert injected is True
    assert parser_root.is_symlink()
    assert parser_root.readlink() == victim
    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"
    assert sorted(path.name for path in victim.iterdir()) == ["sentinel.txt"]


@pytest.mark.parametrize("config_kind", ("remote", "include"))
def test_standalone_materialization_rejects_remote_and_include_config(
    tmp_path: Path,
    config_kind: str,
) -> None:
    repo, _commit = _local_history(tmp_path)
    if config_kind == "remote":
        _git(repo, "remote", "add", "origin", "/tmp/untrusted-origin")
        expected = "retains a Git remote"
    else:
        included = tmp_path / "untrusted-git-config"
        included.write_text("[user]\n\tname = attacker\n", encoding="utf-8")
        _git(repo, "config", "include.path", str(included))
        expected = "unsafe local Git configuration"

    with pytest.raises(AUDIT.AuditError, match=expected):
        AUDIT._require_standalone_materialization(repo, label="synthetic materialization")


def test_validation_receipt_cli_failure_publishes_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "validation-receipt.json"
    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", lambda: None)

    def fail_execution() -> list[dict[str, Any]]:
        raise AUDIT.AuditError("synthetic validation child failure")

    monkeypatch.setattr(AUDIT, "_execute_validation_suite", fail_execution)
    with pytest.raises(AUDIT.AuditError, match="synthetic validation child failure"):
        AUDIT.main(["--create-validation-receipt", str(output)])
    assert not output.exists()


def test_validation_receipt_cli_writes_only_to_fresh_isolated_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "validation-receipt.json"
    execution = _successful_validation_execution()
    monkeypatch.setattr(AUDIT, "_execute_validation_suite", lambda: execution)
    _install_live_validation_refs(monkeypatch, execution)
    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", lambda: None)

    assert AUDIT.main(["--create-validation-receipt", str(output)]) == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["tested_implementation_refs"] == AUDIT._audit_implementation_refs()
    with pytest.raises(AUDIT.AuditError, match="already exists"):
        AUDIT.main(["--create-validation-receipt", str(output)])


def test_exact_pr_inputs_are_tree_parent_path_and_content_verified() -> None:
    if not AUDIT.exact_input_objects_available():
        pytest.skip("exact PR input objects unavailable in this checkout")
    verified = AUDIT.require_exact_pr_inputs()

    assert verified["common_parent"] == {
        "commit": AUDIT.PR_INPUT_PARENT_SHA,
        "tree": AUDIT.PR_INPUT_PARENT_TREE,
    }
    assert {row["action"] for row in verified["pr_972_action_transitions"]} == {
        "actions/checkout",
        "actions/setup-python",
        "actions/upload-artifact",
    }
    assert set(verified["pr_973_declaration_transitions"]) == {
        row["path"] for row in AUDIT.PR973_DECLARATION_EDITS
    }


def test_exact_pr_input_verification_rejects_wrong_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not AUDIT.exact_input_objects_available():
        pytest.skip("exact PR input objects unavailable in this checkout")
    monkeypatch.setattr(AUDIT, "PR972_TREE", "0" * 40)
    with pytest.raises(AUDIT.AuditError, match="tree mismatch"):
        AUDIT.require_exact_pr_inputs()


def test_exact_pr_input_verification_rejects_wrong_declaration_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not AUDIT.exact_input_objects_available():
        pytest.skip("exact PR input objects unavailable in this checkout")
    rows = [dict(row) for row in AUDIT.PR973_DECLARATION_EDITS]
    rows[0]["new"] = "scikit-learn>=999,<1000"
    monkeypatch.setattr(AUDIT, "PR973_DECLARATION_EDITS", tuple(rows))
    with pytest.raises(AUDIT.AuditError, match="declaration matrix drifted"):
        AUDIT.require_exact_pr_inputs()


def test_ledger_rules_are_loaded_from_the_authorized_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def fake_read(path: str) -> bytes:
        observed.append(path)
        return b'{"rules": []}'

    monkeypatch.setattr(AUDIT, "_read_at_baseline", fake_read)

    assert AUDIT._baseline_ledger() == {"rules": []}
    assert observed == ["docs/quality/bug_sweep/coverage.json"]


def test_execution_checkout_rejects_paths_outside_phase_a(tmp_path: Path) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    (repo / "unauthorized.txt").write_text("drift\n", encoding="utf-8")

    with pytest.raises(AUDIT.AuditError, match="outside the Phase-A boundary"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


@pytest.mark.parametrize(
    "relative",
    (
        ".coverage",
        ".coverage.worker",
        "coverage.xml",
        "test.db",
        ".mypy_cache/state.json",
        ".pytest_cache/state.json",
        ".ruff_cache/state.json",
        "__pycache__/module.pyc",
        "nested/module.pyo",
    ),
)
def test_execution_checkout_rejects_generated_paths_outside_exact_packet(
    tmp_path: Path,
    relative: str,
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    generated = repo / relative
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_bytes(b"generated residue\n")

    with pytest.raises(AUDIT.AuditError, match="outside the Phase-A boundary"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


def test_execution_checkout_ignores_hostile_ambient_git_selectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    decoy = tmp_path / "clean-decoy"
    _git(tmp_path, "clone", str(repo), str(decoy))
    (repo / "unauthorized.txt").write_text("drift\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))

    with pytest.raises(AUDIT.AuditError, match="outside the Phase-A boundary"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


def test_bound_git_ignores_hostile_path_and_loader_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "fake-git-ran"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\nprintf fake > {marker}\nexit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setenv("LD_LIBRARY_PATH", str(fake_bin))
    monkeypatch.setenv("PYTHONPATH", str(fake_bin))

    assert AUDIT._run_git(["--version"]).startswith(b"git version ")
    assert not marker.exists()
    assert AUDIT._git_environment()["PATH"] == "/usr/bin:/bin"
    assert "LD_LIBRARY_PATH" not in AUDIT._git_environment()
    assert all(Path(spec["argv"][0]).is_absolute() for spec in AUDIT._validation_invocation_specs())
    assert {row["argv_path"] for row in AUDIT.BOUND_EXECUTABLES} == {
        "/usr/bin/git",
        str(AUDIT.CAPTURE_VALIDATION_PYTHON),
    }


def test_validation_child_executes_retained_descriptor_across_lexical_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lexical = tmp_path / "bound-tool"
    saved = tmp_path / "bound-tool.saved"
    true_bytes = Path("/usr/bin/true").read_bytes()
    false_bytes = Path("/usr/bin/false").read_bytes()
    lexical.write_bytes(true_bytes)
    lexical.chmod(0o755)
    tool_ref = {
        "argv_path": str(lexical),
        "resolved_path": str(lexical),
        "content_sha256": hashlib.sha256(true_bytes).hexdigest(),
        "size_bytes": len(true_bytes),
        "file_type": "regular",
        "mode": "0755",
        "execution_binding": "held descriptor supplied as subprocess executable",
    }
    spec = {
        "sequence": 1,
        "group_index": 0,
        "invocation_index": 0,
        "command": "descriptor ABA control",
        "argv": [str(lexical)],
        "argv_display": str(lexical),
        "cwd": str(tmp_path),
        "environment": dict(AUDIT.VALIDATION_EXECUTION_ENV),
        "executable_ref": tool_ref,
        "observed_at": AUDIT.VALIDATION_GATE_DATE,
    }
    refs = [{"path": "audit.py", "content_sha256": "a" * 64}]
    successful = _successful_validation_execution()
    materializations = successful["tested_security_materializations"]
    checkout = successful["tested_validation_checkout"]
    python_runtime = successful["tested_python_runtime"]
    parser_smoke_inputs = successful["tested_parser_smoke_inputs"]
    parser_smoke_state: dict[str, Any] = {}
    monkeypatch.setattr(AUDIT, "BOUND_EXECUTABLES", (tool_ref,))
    monkeypatch.setattr(AUDIT, "_validation_invocation_specs", lambda: [spec])
    monkeypatch.setattr(AUDIT, "_audit_implementation_refs", lambda: refs)
    monkeypatch.setattr(
        AUDIT,
        "_prepare_validation_environment",
        lambda: (materializations, checkout, python_runtime, parser_smoke_state),
    )
    monkeypatch.setattr(AUDIT, "_security_materialization_refs", lambda: materializations)
    monkeypatch.setattr(AUDIT, "_validation_checkout_ref", lambda: checkout)
    monkeypatch.setattr(AUDIT, "_python_runtime_ref", lambda: python_runtime)
    monkeypatch.setattr(
        AUDIT,
        "_parser_smoke_state_ref",
        lambda _state: parser_smoke_inputs,
    )
    monkeypatch.setattr(AUDIT, "_parser_smoke_input_ref", lambda: parser_smoke_inputs)
    real_run = subprocess.run
    swapped = False

    def aba_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal swapped
        lexical.rename(saved)
        lexical.write_bytes(false_bytes)
        lexical.chmod(0o755)
        try:
            completed = real_run(argv, **kwargs)
        finally:
            os.replace(saved, lexical)
        swapped = True
        return completed

    monkeypatch.setattr(AUDIT.subprocess, "run", aba_run)
    execution = AUDIT._execute_validation_suite()

    assert swapped is True
    assert execution["observations"][0]["exit_code"] == 0
    assert lexical.read_bytes() == true_bytes


def test_bound_git_disables_repository_local_fsmonitor(
    tmp_path: Path,
) -> None:
    repo, _baseline = _local_history(tmp_path)
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "fsmonitor-hook"
    hook.write_text(
        f"#!/bin/sh\nprintf ran > {marker}\nprintf 'token\\n'\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    _git(repo, "config", "core.fsmonitor", str(hook))

    subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert marker.exists()
    marker.unlink()

    AUDIT._run_git(["status", "--porcelain=v1"], cwd=repo)
    assert not marker.exists()


@pytest.mark.parametrize("replacement_kind", ("symlink", "fifo", "mode"))
def test_implementation_refs_reject_nonregular_or_wrong_mode_sources(
    tmp_path: Path,
    replacement_kind: str,
) -> None:
    root, audit_path, _test_path = _implementation_fixture(tmp_path)
    if replacement_kind == "symlink":
        outside = tmp_path / "outside.py"
        outside.write_bytes(b"audit A\n")
        audit_path.unlink()
        audit_path.symlink_to(outside)
    elif replacement_kind == "fifo":
        audit_path.unlink()
        os.mkfifo(audit_path)
    else:
        audit_path.chmod(0o600)

    with pytest.raises(AUDIT.AuditError):
        AUDIT._implementation_refs_at_root(root)


def test_implementation_refs_reject_same_inode_content_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, audit_path, _test_path = _implementation_fixture(tmp_path)
    real_read = AUDIT._read_stable_descriptor
    mutated = False

    def mutate_after_read(descriptor: int, *, label: str) -> bytes:
        nonlocal mutated
        content = real_read(descriptor, label=label)
        if not mutated and label.endswith("audit_build_delivery.py"):
            audit_path.write_bytes(b"audit B\n")
            mutated = True
        return content

    monkeypatch.setattr(AUDIT, "_read_stable_descriptor", mutate_after_read)
    with pytest.raises(AUDIT.AuditError, match="changed"):
        AUDIT._implementation_refs_at_root(root)


def test_implementation_refs_reject_identical_rename_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, audit_path, _test_path = _implementation_fixture(tmp_path)
    replacement = root / "replacement.py"
    replacement.write_bytes(audit_path.read_bytes())
    replacement.chmod(0o644)
    real_read = AUDIT._read_stable_descriptor
    swapped = False

    def replace_after_read(descriptor: int, *, label: str) -> bytes:
        nonlocal swapped
        content = real_read(descriptor, label=label)
        if not swapped and label.endswith("audit_build_delivery.py"):
            os.replace(replacement, audit_path)
            swapped = True
        return content

    monkeypatch.setattr(AUDIT, "_read_stable_descriptor", replace_after_read)
    with pytest.raises(AUDIT.AuditError, match="identity or metadata changed|final rooted entry"):
        AUDIT._implementation_refs_at_root(root)


def test_validation_checkout_is_detached_from_source_checkout_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "materialized"
    (source / "scripts" / "quality").mkdir(parents=True)
    (source / "tests").mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Build Delivery Audit")
    _git(source, "config", "user.email", "build-delivery@example.invalid")
    (source / "scripts" / "quality" / ".keep").write_text("tracked\n", encoding="utf-8")
    (source / "tests" / ".keep").write_text("tracked\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "baseline")
    baseline = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    output_root = tmp_path / "test-output"
    output_root.mkdir(mode=0o700)
    output_db = output_root / "test.db"
    output_db.write_bytes(b"")
    output_db.chmod(0o600)
    audit_path = source / "scripts" / "quality" / "audit_build_delivery.py"
    test_path = source / "tests" / "test_build_delivery_audit.py"
    audit_path.write_text("A audit\n", encoding="utf-8")
    test_path.write_text("A test\n", encoding="utf-8")
    monkeypatch.setattr(AUDIT, "ROOT", source)
    monkeypatch.setattr(AUDIT, "BASELINE_SHA", baseline)
    monkeypatch.setattr(AUDIT, "BASELINE_TREE", tree)
    monkeypatch.setattr(AUDIT, "CAPTURE_AUDIT_CWD", destination)
    monkeypatch.setattr(AUDIT, "CAPTURE_VALIDATION_TEST_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(AUDIT, "CAPTURE_VALIDATION_TEST_DB", output_db)

    materialized_ref = AUDIT._materialize_validation_checkout()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / ".git").stat().st_mode) == 0o500
    assert stat.S_IMODE((destination / ".git/index").stat().st_mode) == 0o444
    assert (destination / "test.db").is_symlink()
    assert os.readlink(destination / "test.db") == str(output_db)
    assert (
        stat.S_IMODE((destination / "scripts/quality/audit_build_delivery.py").stat().st_mode)
        == 0o644
    )
    source_audit = audit_path.read_bytes()
    audit_path.write_bytes(b"B audit\n")
    assert (
        destination / "scripts" / "quality" / "audit_build_delivery.py"
    ).read_bytes() == source_audit
    audit_path.write_bytes(source_audit)
    assert AUDIT._validation_checkout_ref() == materialized_ref
    output_db.write_bytes(b"mutable SQLite output\n")
    assert AUDIT._validation_checkout_ref() == materialized_ref

    replacement_db = output_root / "replacement.db"
    replacement_db.write_bytes(b"replacement SQLite output\n")
    replacement_db.chmod(0o600)
    os.replace(replacement_db, output_db)
    replaced_output_ref = AUDIT._validation_checkout_ref()
    assert replaced_output_ref["test_db_identity"] != materialized_ref["test_db_identity"]
    assert replaced_output_ref != materialized_ref

    (destination / "test.db").unlink()
    (destination / "test.db").symlink_to(tmp_path / "wrong.db")
    with pytest.raises(AUDIT.AuditError, match="external symlink target drifted"):
        AUDIT._validation_checkout_ref()

    destination.chmod(0o700)
    for path in destination.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o700 if path.is_dir() else 0o600)


def test_filesystem_manifests_separate_portable_content_from_ephemeral_identity(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / "copy-a", tmp_path / "copy-b"]
    for root in roots:
        root.mkdir(mode=0o700)
        payload = root / "payload.bin"
        payload.write_bytes(b"A\n")
        payload.chmod(0o600)

    first = AUDIT._filesystem_manifests(roots[0], label="copy A", root_mode=0o700, immutable=False)
    second = AUDIT._filesystem_manifests(roots[1], label="copy B", root_mode=0o700, immutable=False)
    assert first[:2] == second[:2]
    assert first[2] != second[2]

    payload = roots[0] / "payload.bin"
    time.sleep(0.002)
    payload.write_bytes(b"B\n")
    payload.write_bytes(b"A\n")
    restored = AUDIT._filesystem_manifests(
        roots[0], label="restored A", root_mode=0o700, immutable=False
    )
    assert restored[:2] == first[:2]
    assert restored[2] != first[2]

    replacement = roots[0] / "replacement.bin"
    replacement.write_bytes(b"A\n")
    replacement.chmod(0o600)
    os.replace(replacement, payload)
    replaced = AUDIT._filesystem_manifests(
        roots[0], label="replaced A", root_mode=0o700, immutable=False
    )
    assert replaced[:2] == first[:2]
    assert replaced[2] != restored[2]


def test_filesystem_manifest_rejects_indirect_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    nested = root / "nested"
    nested.mkdir(parents=True)
    root.chmod(0o700)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside\n")
    outside.chmod(0o600)
    (nested / "relay").symlink_to("../../outside.bin")
    (root / "inside").symlink_to("nested/relay")

    with pytest.raises(AUDIT.AuditError, match="escaping symlink refused"):
        AUDIT._filesystem_manifests(
            root,
            label="indirect escape",
            root_mode=0o700,
            immutable=False,
        )


def test_python_runtime_materialization_copies_and_binds_complete_private_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_base = tmp_path / "source-base"
    source_venv = tmp_path / "source-venv"
    runtime = tmp_path / "runtime"
    runtime_base = runtime / "base"
    runtime_venv = runtime / "venv"
    runtime_python = runtime_venv / "bin/python"
    (source_base / "bin").mkdir(parents=True)
    source_python = source_base / "bin/python3.11"
    source_python.write_bytes(Path("/usr/bin/true").read_bytes())
    source_python.chmod(0o755)
    (source_venv / "bin").mkdir(parents=True)
    (source_venv / "bin/python").symlink_to(source_python)
    (source_venv / "pyvenv.cfg").write_text(
        f"home = {source_base}/bin\n"
        "implementation = CPython\n"
        "uv = 0.12.5\n"
        "version_info = 3.11.16\n"
        "include-system-site-packages = false\n"
        "seed = true\n",
        encoding="utf-8",
    )
    site_packages = source_venv / "lib/python3.11/site-packages"
    for name, version in (
        ("mypy", "2.2.0"),
        ("pip", "26.2.1"),
        ("pytest", "9.1.1"),
        ("ruff", "0.15.10"),
    ):
        metadata = site_packages / f"{name}-synthetic.dist-info/METADATA"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(f"Name: {name}\nVersion: {version}\n", encoding="utf-8")
    pytest_module = site_packages / "pytest/__init__.py"
    pytest_module.parent.mkdir(parents=True)
    pytest_module.write_text("SYNTHETIC = True\n", encoding="utf-8")
    sitecustomize = site_packages / "sitecustomize.py"
    sitecustomize.write_text("SYNTHETIC_SITE = True\n", encoding="utf-8")
    stdlib_module = source_base / "lib/python3.11/json/__init__.py"
    stdlib_module.parent.mkdir(parents=True)
    stdlib_module.write_text("SYNTHETIC_JSON = True\n", encoding="utf-8")

    python_bytes = source_python.read_bytes()
    python_ref = {
        "argv_path": str(runtime_python),
        "resolved_path": str(runtime_base / "bin/python3.11"),
        "content_sha256": hashlib.sha256(python_bytes).hexdigest(),
        "size_bytes": len(python_bytes),
        "file_type": "regular",
        "mode": "0555",
        "execution_binding": "held descriptor supplied as subprocess executable",
    }
    monkeypatch.setattr(AUDIT, "CAPTURE_RUNTIME_SOURCE_BASE", source_base)
    monkeypatch.setattr(AUDIT, "CAPTURE_RUNTIME_SOURCE_VENV", source_venv)
    monkeypatch.setattr(AUDIT, "CAPTURE_VALIDATION_RUNTIME", runtime)
    monkeypatch.setattr(AUDIT, "CAPTURE_VALIDATION_RUNTIME_BASE", runtime_base)
    monkeypatch.setattr(AUDIT, "CAPTURE_VALIDATION_RUNTIME_VENV", runtime_venv)
    monkeypatch.setattr(AUDIT, "CAPTURE_VALIDATION_PYTHON", runtime_python)
    monkeypatch.setattr(AUDIT, "BOUND_EXECUTABLES", (AUDIT.BOUND_EXECUTABLES[0], python_ref))
    monkeypatch.setattr(
        AUDIT,
        "_probe_python_runtime",
        lambda _root: AUDIT._expected_python_runtime_probe(),
    )
    pinned_synthetic_closure: dict[str, Any] = {}

    def synthetic_closure() -> dict[str, Any]:
        if not pinned_synthetic_closure:
            manifest = AUDIT._read_only_filesystem_manifest(
                runtime,
                label="synthetic validation Python runtime",
            )
            pyvenv_content = (runtime_venv / "pyvenv.cfg").read_bytes()
            pinned_synthetic_closure.update(
                {
                    "pyvenv_cfg_sha256": hashlib.sha256(pyvenv_content).hexdigest(),
                    "filesystem_manifest_sha256": manifest[0],
                    "filesystem_entry_count": manifest[1],
                }
            )
        return dict(pinned_synthetic_closure)

    monkeypatch.setattr(AUDIT, "_expected_python_runtime_closure", synthetic_closure)

    def synthetic_inventory() -> list[dict[str, str]]:
        return AUDIT._python_distribution_inventory(runtime)

    monkeypatch.setattr(AUDIT, "_expected_python_runtime_inventory", synthetic_inventory)
    monkeypatch.setattr(
        AUDIT,
        "_expected_python_runtime_inventory_sha256",
        lambda: AUDIT._canonical_json_value_sha256(synthetic_inventory()),
    )

    try:
        runtime_ref = AUDIT._materialize_python_runtime()
        assert stat.S_IMODE(runtime.stat().st_mode) == 0o500
        assert os.readlink(runtime_python) == "../../base/bin/python3.11"
        assert (
            (runtime_venv / "pyvenv.cfg")
            .read_text(encoding="utf-8")
            .startswith(f"home = {runtime_base}/bin\n")
        )
        assert all(
            path.lstat().st_nlink == 1
            for path in runtime.rglob("*")
            if path.is_file() and not path.is_symlink()
        )

        source_python.write_bytes(b"source drift\n")
        assert (runtime_base / "bin/python3.11").read_bytes() == python_bytes
        assert AUDIT._python_runtime_ref() == runtime_ref

        for runtime_module in (
            runtime_venv / "lib/python3.11/site-packages/pytest/__init__.py",
            runtime_venv / "lib/python3.11/site-packages/sitecustomize.py",
            runtime_base / "lib/python3.11/json/__init__.py",
        ):
            original_module = runtime_module.read_bytes()
            runtime_module.chmod(0o644)
            runtime_module.write_bytes(original_module + b"MALICIOUS_DRIFT = True\n")
            runtime_module.chmod(0o444)
            with pytest.raises(AUDIT.AuditError, match="independently pinned complete closure"):
                AUDIT._python_runtime_ref()
            runtime_module.chmod(0o644)
            runtime_module.write_bytes(original_module)
            runtime_module.chmod(0o444)

        pyvenv = runtime_venv / "pyvenv.cfg"
        pyvenv.chmod(0o644)
        pyvenv.write_text(
            pyvenv.read_text(encoding="utf-8").replace("seed = true", "seed = false"),
            encoding="utf-8",
        )
        pyvenv.chmod(0o444)
        with pytest.raises(AUDIT.AuditError, match="independently pinned complete closure"):
            AUDIT._python_runtime_ref()
    finally:
        if runtime.exists():
            runtime.chmod(0o700)
            for path in runtime.rglob("*"):
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)


def test_python_runtime_rejects_absolute_or_escaping_pth_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    runtime_venv = runtime / "venv"
    site_packages = runtime_venv / "lib/python3.11/site-packages"
    site_packages.mkdir(parents=True)
    pth = site_packages / "untrusted.pth"
    pth.write_text("/tmp/outside\n", encoding="utf-8")
    pth.chmod(0o444)
    monkeypatch.setattr(AUDIT, "CAPTURE_VALIDATION_RUNTIME_VENV", runtime_venv)

    with pytest.raises(AUDIT.AuditError, match="absolute path refused"):
        AUDIT._require_safe_runtime_pth_files(runtime)

    pth.chmod(0o644)
    pth.write_text("../../../../../../outside\n", encoding="utf-8")
    pth.chmod(0o444)
    with pytest.raises(AUDIT.AuditError, match="escape refused"):
        AUDIT._require_safe_runtime_pth_files(runtime)

    pth.chmod(0o644)
    pth.write_text("import sys; sys.path.append('/tmp/outside')\n", encoding="utf-8")
    pth.chmod(0o444)
    with pytest.raises(AUDIT.AuditError, match="executable .pth content is not allowlisted"):
        AUDIT._require_safe_runtime_pth_files(runtime)


@pytest.mark.parametrize(
    "suffix",
    (
        "home = /tmp/outside/bin\n",
        "include-system-site-packages = true\n",
    ),
)
def test_python_runtime_rejects_duplicate_effective_pyvenv_configuration(
    suffix: str,
) -> None:
    expected_home = Path("/tmp/private-runtime/base/bin")
    content = (
        f"home = {expected_home}\n"
        "implementation = CPython\n"
        "version_info = 3.11.16\n"
        "include-system-site-packages = false\n" + suffix
    ).encode("utf-8")

    with pytest.raises(AUDIT.AuditError, match="duplicate key"):
        AUDIT._parse_pyvenv_config(
            content,
            expected_home=expected_home,
            label="synthetic pyvenv.cfg",
        )


@pytest.mark.parametrize(
    "drift",
    (
        "home",
        "include-system-site-packages",
        "external-path-value",
    ),
)
def test_python_runtime_rejects_effective_pyvenv_configuration_drift(drift: str) -> None:
    expected_home = Path("/tmp/private-runtime/base/bin")
    home = "/tmp/outside/bin" if drift == "home" else str(expected_home)
    include_system = "true" if drift == "include-system-site-packages" else "false"
    extra = "executable = /tmp/outside/python\n" if drift == "external-path-value" else ""
    content = (
        f"home = {home}\n"
        "implementation = CPython\n"
        "version_info = 3.11.16\n"
        f"include-system-site-packages = {include_system}\n"
        f"{extra}"
    ).encode("utf-8")

    with pytest.raises(
        AUDIT.AuditError,
        match="effective configuration drifted|external path-bearing value",
    ):
        AUDIT._parse_pyvenv_config(
            content,
            expected_home=expected_home,
            label="synthetic pyvenv.cfg",
        )


def test_execution_checkout_accepts_only_authorized_paths(tmp_path: Path) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    allowed = repo / "audit.json"
    allowed.write_text("{}\n", encoding="utf-8")

    AUDIT.require_execution_checkout(
        repo,
        baseline_sha=baseline_sha,
        expected_branch="main",
        allowed_paths=frozenset({"audit.json"}),
    )


def test_execution_checkout_rejects_descendant_even_with_only_authorized_commit(
    tmp_path: Path,
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    allowed = repo / "audit.json"
    allowed.write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "audit.json")
    _git(repo, "commit", "-m", "later audit bytes")

    with pytest.raises(AUDIT.AuditError, match="exact baseline"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset({"audit.json"}),
        )


def test_execution_checkout_rejects_wrong_branch(tmp_path: Path) -> None:
    repo, baseline_sha = _local_history(tmp_path)

    with pytest.raises(AUDIT.AuditError, match="branch drifted"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="research/976-build-packaging-audit",
            allowed_paths=frozenset(),
        )


def test_execution_checkout_rejects_detached_head(tmp_path: Path) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    _git(repo, "checkout", "--detach", baseline_sha)

    with pytest.raises(AUDIT.AuditError, match="detached HEAD is not authorized"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="research/976-build-packaging-audit",
            allowed_paths=frozenset(),
        )


@pytest.mark.parametrize("flag", ("--assume-unchanged", "--skip-worktree"))
@pytest.mark.parametrize("mutate", (False, True))
def test_execution_checkout_rejects_masking_index_flags(
    tmp_path: Path,
    flag: str,
    mutate: bool,
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    _git(repo, "update-index", flag, "tracked.txt")
    if mutate:
        (repo / "tracked.txt").write_text("masked drift\n", encoding="utf-8")

    with pytest.raises(AUDIT.AuditError, match="special index flags"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


def test_execution_checkout_rejects_staged_index_drift_with_restored_worktree(
    tmp_path: Path,
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("staged drift\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    tracked.write_text("sanitized\n", encoding="utf-8")

    with pytest.raises(AUDIT.AuditError, match="index does not exactly match"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


def test_execution_checkout_rejects_core_filemode_false_and_mode_drift(
    tmp_path: Path,
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    _git(repo, "config", "core.fileMode", "false")

    with pytest.raises(AUDIT.AuditError, match="core.fileMode=true"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )

    _git(repo, "config", "core.fileMode", "true")
    (repo / "tracked.txt").chmod(0o755)
    with pytest.raises(AUDIT.AuditError, match="differs from exact baseline"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("includeIf.onbranch:never.path", "/tmp/untrusted-config"),
        ("core.worktree", "/tmp/untrusted-worktree"),
        ("core.excludesFile", "/tmp/untrusted-excludes"),
        ("filter.untrusted.clean", "/tmp/untrusted-filter"),
        ("diff.untrusted.textconv", "/tmp/untrusted-textconv"),
        ("extensions.worktreeConfig", "true"),
    ),
)
def test_execution_checkout_rejects_unsafe_local_git_configuration_before_status(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    _git(repo, "config", key, value)

    with pytest.raises(AUDIT.AuditError, match="unsafe local Git configuration"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


def test_execution_checkout_rejects_redirected_git_common_directory(tmp_path: Path) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    external_common = tmp_path / "external-common.git"
    _git(tmp_path, "clone", "--bare", str(repo), str(external_common))
    (repo / ".git/commondir").write_text(str(external_common) + "\n", encoding="utf-8")

    with pytest.raises(AUDIT.AuditError, match="Git/common directory drifted"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


def test_execution_checkout_rejects_linked_worktree(tmp_path: Path) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-b", "linked", str(linked))

    with pytest.raises(AUDIT.AuditError, match="rooted .git directory"):
        AUDIT.require_execution_checkout(
            linked,
            baseline_sha=baseline_sha,
            expected_branch="linked",
            allowed_paths=frozenset(),
        )


@pytest.mark.parametrize("relative", (".git/info/exclude", ".git/info/attributes"))
def test_execution_checkout_rejects_active_info_excludes_or_attributes(
    tmp_path: Path,
    relative: str,
) -> None:
    repo, baseline_sha = _local_history(tmp_path)
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("*.hidden\n", encoding="utf-8")

    with pytest.raises(AUDIT.AuditError, match="active repository-local"):
        AUDIT.require_execution_checkout(
            repo,
            baseline_sha=baseline_sha,
            expected_branch="main",
            allowed_paths=frozenset(),
        )


def test_generated_json_and_report_are_current() -> None:
    evidence = _evidence_or_skip()

    assert AUDIT.EVIDENCE_PATH.read_text(encoding="utf-8") == AUDIT.canonical_json(evidence)
    report = AUDIT.REPORT_PATH.read_text(encoding="utf-8")
    assert report == AUDIT.render_report(evidence)
    assert "PHASE A PARKED — LEDGER/CI/PR DEFERRED" in report
    assert "ledger terminalization deferred" in report


def test_two_isolated_json_generations_are_byte_identical(tmp_path: Path) -> None:
    if not AUDIT.exact_input_objects_available():
        pytest.skip(
            "exact archived baseline object unavailable in this checkout; #991 owns history"
        )
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    for output in (first, second):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--output", str(output)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr

    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8"))["scope"]["path_count"] == 58


def test_historical_capture_paths_are_deterministic_across_tmpdir_values(
    tmp_path: Path,
) -> None:
    if not AUDIT.exact_input_objects_available():
        pytest.skip(
            "exact archived baseline object unavailable in this checkout; #991 owns history"
        )
    outputs: list[bytes] = []
    for name in ("runtime-temp-a", "runtime-temp-b"):
        runtime_temp = tmp_path / name
        runtime_temp.mkdir()
        output = runtime_temp / "evidence.json"
        environment = {**os.environ, "TMPDIR": str(runtime_temp)}
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--output", str(output)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(output.read_bytes())

    assert outputs[0] == outputs[1]
    evidence = json.loads(outputs[0])
    assert evidence["pr_973"]["windows_resolution_capture"]["cache"].startswith(
        "/tmp/metroliza-976-uv-cache"
    )


def test_missing_required_packaged_asset_is_detected(tmp_path: Path) -> None:
    (tmp_path / "present.bin").write_bytes(b"present")

    with pytest.raises(AUDIT.AuditError, match="missing required packaged asset"):
        AUDIT.required_paths_exist(tmp_path, ["present.bin", "missing.bin"])


def test_required_packaged_assets_pass_when_present(tmp_path: Path) -> None:
    for relative in ("asset.bin", "nested/model.onnx"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"sanitized")

    AUDIT.required_paths_exist(tmp_path, ["asset.bin", "nested/model.onnx"])


@pytest.mark.parametrize(
    ("source_root_ok", "isolated_cwd_ok"),
    [(True, False), (False, True), (False, False)],
)
def test_repository_root_only_import_or_resource_is_detected(
    source_root_ok: bool, isolated_cwd_ok: bool
) -> None:
    with pytest.raises(AUDIT.AuditError, match="repository-root state"):
        AUDIT.require_portable_import(
            source_root_ok=source_root_ok,
            isolated_cwd_ok=isolated_cwd_ok,
        )


def test_portable_import_requires_both_contexts() -> None:
    AUDIT.require_portable_import(source_root_ok=True, isolated_cwd_ok=True)


def test_required_native_backend_cannot_hide_behind_importable_fallback() -> None:
    with pytest.raises(AUDIT.AuditError, match="required native backend is unavailable"):
        AUDIT.require_native_truth(required=True, import_ok=True, native_available=False)


def test_optional_native_backend_can_report_truthful_fallback() -> None:
    AUDIT.require_native_truth(required=False, import_ok=True, native_available=False)


@pytest.mark.parametrize("gate", ["ruff", "mypy", "security"])
def test_new_static_finding_is_detected(gate: str) -> None:
    with pytest.raises(AUDIT.AuditError, match=gate):
        AUDIT.require_static_gates({"compile": 0, gate: 1})


def test_zero_exit_without_required_artifact_is_detected(tmp_path: Path) -> None:
    with pytest.raises(AUDIT.AuditError, match="zero-exit build produced no required artifact"):
        AUDIT.require_current_artifact(
            tmp_path / "missing.exe",
            output_root=tmp_path,
            command_exit_code=0,
            attempt_started_ns=time.time_ns(),
            prior_state=None,
        )


def test_nonzero_build_cannot_be_reported_as_artifact_success(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.exe"
    artifact.write_bytes(b"prior")
    prior = AUDIT.capture_artifact_state(artifact, output_root=tmp_path)

    with pytest.raises(AUDIT.AuditError, match="build command failed"):
        AUDIT.require_current_artifact(
            artifact,
            output_root=tmp_path,
            command_exit_code=7,
            attempt_started_ns=0,
            prior_state=prior,
        )


def test_stale_artifact_is_detected_even_after_zero_exit(tmp_path: Path) -> None:
    artifact = tmp_path / "stale.exe"
    artifact.write_bytes(b"old artifact")
    old_ns = 1_700_000_000_000_000_000
    os.utime(artifact, ns=(old_ns, old_ns))
    prior = AUDIT.capture_artifact_state(artifact, output_root=tmp_path)

    with pytest.raises(AUDIT.AuditError, match="predates current build attempt"):
        AUDIT.require_current_artifact(
            artifact,
            output_root=tmp_path,
            command_exit_code=0,
            attempt_started_ns=old_ns + 1,
            prior_state=prior,
        )


def test_future_dated_unchanged_artifact_is_detected_after_zero_exit(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "future-stale.exe"
    artifact.write_bytes(b"pre-existing artifact")
    future_ns = time.time_ns() + 60_000_000_000
    os.utime(artifact, ns=(future_ns, future_ns))
    prior = AUDIT.capture_artifact_state(artifact, output_root=tmp_path)

    with pytest.raises(AUDIT.AuditError, match="unchanged from pre-build state"):
        AUDIT.require_current_artifact(
            artifact,
            output_root=tmp_path,
            command_exit_code=0,
            attempt_started_ns=time.time_ns(),
            prior_state=prior,
        )


def test_touched_but_byte_identical_artifact_is_not_current_build_evidence(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "touched-stale.exe"
    artifact.write_bytes(b"pre-existing artifact")
    prior = AUDIT.capture_artifact_state(artifact, output_root=tmp_path)
    started = time.time_ns()
    os.utime(artifact, ns=(started + 1, started + 1))

    with pytest.raises(AUDIT.AuditError, match="unchanged from pre-build state"):
        AUDIT.require_current_artifact(
            artifact,
            output_root=tmp_path,
            command_exit_code=0,
            attempt_started_ns=started,
            prior_state=prior,
        )


def test_partial_artifact_is_detected(tmp_path: Path) -> None:
    artifact = tmp_path / "partial.exe"
    artifact.write_bytes(b"x")

    with pytest.raises(AUDIT.AuditError, match="partial or undersized"):
        AUDIT.require_current_artifact(
            artifact,
            output_root=tmp_path,
            command_exit_code=0,
            attempt_started_ns=0,
            prior_state=None,
            minimum_size=2,
        )


def test_artifact_state_rejects_external_symlink(tmp_path: Path) -> None:
    external = tmp_path / "external.bin"
    external.write_bytes(b"external artifact\n")
    artifact = tmp_path / "artifact.exe"
    artifact.symlink_to(external)

    with pytest.raises(AUDIT.AuditError, match="indirect symlink"):
        AUDIT.capture_artifact_state(artifact, output_root=tmp_path)


def test_artifact_state_rejects_intermediate_ancestor_symlink(tmp_path: Path) -> None:
    trusted_root = tmp_path / "trusted"
    outside = tmp_path / "outside"
    trusted_root.mkdir()
    (outside / "nested").mkdir(parents=True)
    artifact = outside / "nested/artifact.exe"
    artifact.write_bytes(b"external artifact\n")
    (trusted_root / "redirect").symlink_to(outside, target_is_directory=True)
    redirected_artifact = trusted_root / "redirect/nested/artifact.exe"

    with pytest.raises(AUDIT.AuditError, match="escaped or crossed a symlink"):
        AUDIT.capture_artifact_state(redirected_artifact, output_root=trusted_root)


def test_artifact_state_rejects_same_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact.exe"
    artifact.write_bytes(b"original artifact\n")
    replacement = tmp_path / "replacement.exe"
    replacement.write_bytes(b"replacement artifact\n")
    real_read = AUDIT._read_stable_descriptor

    def swap_after_read(descriptor: int, *, label: str) -> bytes:
        content = real_read(descriptor, label=label)
        os.replace(replacement, artifact)
        return content

    monkeypatch.setattr(AUDIT, "_read_stable_descriptor", swap_after_read)
    with pytest.raises(AUDIT.AuditError, match="identity changed during capture"):
        AUDIT.capture_artifact_state(artifact, output_root=tmp_path)


def test_artifact_state_rejects_intermediate_ancestor_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_root = tmp_path / "trusted"
    ancestor = trusted_root / "build"
    parent = ancestor / "nested"
    parent.mkdir(parents=True)
    artifact = parent / "artifact.exe"
    artifact.write_bytes(b"original artifact\n")
    relocated = trusted_root / "relocated"
    real_read = AUDIT._read_stable_descriptor

    def swap_ancestor_after_read(descriptor: int, *, label: str) -> bytes:
        content = real_read(descriptor, label=label)
        ancestor.rename(relocated)
        parent.mkdir(parents=True)
        artifact.write_bytes(b"replacement artifact\n")
        return content

    monkeypatch.setattr(AUDIT, "_read_stable_descriptor", swap_ancestor_after_read)
    with pytest.raises(AUDIT.AuditError, match="publication parent identity changed while held"):
        AUDIT.capture_artifact_state(artifact, output_root=trusted_root)


def test_fresh_artifact_is_accepted(tmp_path: Path) -> None:
    started = time.time_ns()
    artifact = tmp_path / "fresh.exe"
    artifact.write_bytes(b"fresh sanitized artifact")

    AUDIT.require_current_artifact(
        artifact,
        output_root=tmp_path,
        command_exit_code=0,
        attempt_started_ns=started,
        prior_state=None,
        minimum_size=8,
    )


def test_import_green_workflow_broken_family_is_detected() -> None:
    with pytest.raises(AUDIT.AuditError, match="passed imports but failed"):
        AUDIT.require_family_workflow(import_ok=True, workflow_ok=False)


def test_dependency_family_requires_import_and_workflow() -> None:
    AUDIT.require_family_workflow(import_ok=True, workflow_ok=True)


@pytest.mark.parametrize("conclusion", ["skipped", "cancelled", "failure"])
def test_upstream_skip_or_failure_is_not_required_job_success(conclusion: str) -> None:
    with pytest.raises(AUDIT.AuditError, match="required CI job"):
        AUDIT.require_job_result(required=True, conclusion=conclusion)


def test_nonblocking_job_can_be_truthfully_skipped() -> None:
    AUDIT.require_job_result(required=False, conclusion="skipped")


@pytest.mark.parametrize(
    ("cold_ok", "warm_ok", "key_matches", "message"),
    [
        (False, True, True, "warm cache"),
        (True, True, False, "cache key"),
        (True, False, True, "cache key"),
    ],
)
def test_wrong_or_warm_only_cache_is_detected(
    cold_ok: bool, warm_ok: bool, key_matches: bool, message: str
) -> None:
    with pytest.raises(AUDIT.AuditError, match=message):
        AUDIT.require_cache_independence(
            cold_ok=cold_ok,
            warm_ok=warm_ok,
            key_matches=key_matches,
        )


def test_cold_and_warm_cache_paths_must_both_succeed() -> None:
    AUDIT.require_cache_independence(cold_ok=True, warm_ok=True, key_matches=True)


def test_missing_historical_commit_fails_closed(tmp_path: Path) -> None:
    repo, commit_sha = _local_history(tmp_path)
    AUDIT.require_commit_available(repo, commit_sha)

    with pytest.raises(AUDIT.AuditError, match="audited commit is unavailable"):
        AUDIT.require_commit_available(repo, "f" * 40)


def test_spaces_non_ascii_and_long_path_round_trip(tmp_path: Path) -> None:
    result = AUDIT.probe_path_permissions(tmp_path)

    assert result["portable_path"] == "pass"


def test_read_only_output_is_detected_from_mode_bits(tmp_path: Path) -> None:
    target_dir = tmp_path / "read only Zażółć"
    target_dir.mkdir()
    target_dir.chmod(0o555)
    try:
        with pytest.raises(AUDIT.AuditError, match="read-only"):
            AUDIT.require_writable_output(target_dir / "artifact.bin")
    finally:
        target_dir.chmod(0o755)


def test_writable_output_parent_is_accepted(tmp_path: Path) -> None:
    AUDIT.require_writable_output(tmp_path / "nested" / "artifact.bin")


def test_isolated_output_requires_new_file_below_explicit_temp_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    repo.mkdir()
    temp_root.mkdir()

    accepted = temp_root / "nested" / "evidence.json"
    accepted.parent.mkdir()
    assert AUDIT.require_isolated_output(accepted, repo_root=repo, temp_root=temp_root) == accepted

    with pytest.raises(AUDIT.AuditError, match="outside the repository"):
        AUDIT.require_isolated_output(repo / "tracked.json", repo_root=repo, temp_root=tmp_path)
    with pytest.raises(AUDIT.AuditError, match="below"):
        AUDIT.require_isolated_output(
            tmp_path.parent / "outside.json", repo_root=repo, temp_root=temp_root
        )

    existing = temp_root / "existing.json"
    existing.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(AUDIT.AuditError, match="refusing overwrite"):
        AUDIT.require_isolated_output(existing, repo_root=repo, temp_root=temp_root)
    assert existing.read_text(encoding="utf-8") == "preserve\n"


def test_isolated_output_rejects_missing_parent_without_creating_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    repo.mkdir()
    temp_root.mkdir()
    target = temp_root / "missing" / "packet.json"

    with pytest.raises(AUDIT.AuditError, match="parent must preexist"):
        AUDIT.write_new_isolated_output(
            target,
            "payload\n",
            repo_root=repo,
            temp_root=temp_root,
        )
    assert not target.parent.exists()


def test_phase_a_artifact_target_guard_rejects_symlink_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    evidence_dir = repo / "docs" / "evidence"
    evidence_dir.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("preserve\n", encoding="utf-8")
    target = evidence_dir / "packet.json"
    target.symlink_to(outside)

    with pytest.raises(AUDIT.AuditError, match="symlink component"):
        AUDIT.require_safe_artifact_targets(
            repo,
            [target],
            frozenset({"docs/evidence/packet.json"}),
        )
    assert outside.read_text(encoding="utf-8") == "preserve\n"


def test_phase_a_artifact_target_guard_rejects_symlink_parent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / "docs").symlink_to(outside, target_is_directory=True)
    target = repo / "docs" / "evidence" / "packet.json"

    with pytest.raises(AUDIT.AuditError, match="symlink component"):
        AUDIT.require_safe_artifact_targets(
            repo,
            [target],
            frozenset({"docs/evidence/packet.json"}),
        )


def test_isolated_output_no_clobber_preserves_concurrent_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    repo.mkdir()
    temp_root.mkdir()
    target = temp_root / "nested" / "packet.json"
    target.parent.mkdir()
    real_openat2 = AUDIT._openat2_beneath
    raced = False

    def race(root_fd: int, relative: str, *, flags: int, mode: int = 0) -> int:
        nonlocal raced
        if flags & os.O_CREAT and not raced:
            raced = True
            target.write_bytes(b"concurrent-owner\n")
        return real_openat2(root_fd, relative, flags=flags, mode=mode)

    monkeypatch.setattr(AUDIT, "_openat2_beneath", race)
    with pytest.raises(AUDIT.AuditError, match="already exists"):
        AUDIT.write_new_isolated_output(
            target,
            "new content\n",
            repo_root=repo,
            temp_root=temp_root,
        )
    assert target.read_bytes() == b"concurrent-owner\n"


def test_direct_publication_interrupt_retains_detectable_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "packet.json"

    def interrupt(_descriptor: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(AUDIT.os, "fsync", interrupt)
    with pytest.raises(KeyboardInterrupt):
        AUDIT._publish_new_text(tmp_path, target, "payload\n")
    assert target.read_bytes() == b"payload\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_direct_publication_fsyncs_again_after_exact_payload_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "packet.json"
    real_fchmod = AUDIT.os.fchmod
    real_fsync = AUDIT.os.fsync
    payload_fd: int | None = None
    events: list[str] = []

    def observe_fchmod(descriptor: int, mode: int) -> None:
        nonlocal payload_fd
        if mode == 0o644:
            payload_fd = descriptor
            events.append("payload-chmod")
        real_fchmod(descriptor, mode)

    def observe_fsync(descriptor: int) -> None:
        if descriptor == payload_fd:
            events.append("payload-fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(AUDIT.os, "fchmod", observe_fchmod)
    monkeypatch.setattr(AUDIT.os, "fsync", observe_fsync)
    published = AUDIT._publish_new_text(tmp_path, target, "payload\n")
    assert published.mode == 0o644
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    chmod_index = events.index("payload-chmod")
    assert events[chmod_index : chmod_index + 2] == ["payload-chmod", "payload-fsync"]


def test_direct_publication_failure_never_unlinks_or_removes_public_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "packet.json"
    unlink_calls = 0
    rmdir_calls = 0
    real_verify = AUDIT._read_published_state

    def reject_unlink(*_args: Any, **_kwargs: Any) -> None:
        nonlocal unlink_calls
        unlink_calls += 1
        raise AssertionError("anonymous cleanup must not unlink")

    def reject_rmdir(*_args: Any, **_kwargs: Any) -> None:
        nonlocal rmdir_calls
        rmdir_calls += 1
        raise AssertionError("anonymous cleanup must not rmdir")

    monkeypatch.setattr(AUDIT.os, "unlink", reject_unlink)
    monkeypatch.setattr(AUDIT.os, "rmdir", reject_rmdir)

    def reject_after_publish(*args: Any, **kwargs: Any) -> Any:
        real_verify(*args, **kwargs)
        raise AUDIT.AuditError("synthetic post-publication failure")

    monkeypatch.setattr(AUDIT, "_read_published_state", reject_after_publish)
    with pytest.raises(AUDIT.AuditError, match="synthetic post-publication failure"):
        AUDIT._publish_new_text(tmp_path, target, "owned\n")
    assert unlink_calls == 0
    assert rmdir_calls == 0
    assert target.read_bytes() == b"owned\n"


def test_isolated_output_fifo_race_is_never_opened_or_clobbered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    repo.mkdir()
    temp_root.mkdir()
    target = temp_root / "packet.json"
    real_openat2 = AUDIT._openat2_beneath
    raced = False

    def race_with_fifo(root_fd: int, relative: str, *, flags: int, mode: int = 0) -> int:
        nonlocal raced
        if flags & os.O_CREAT and not raced:
            raced = True
            AUDIT.os.mkfifo(target)
        return real_openat2(root_fd, relative, flags=flags, mode=mode)

    monkeypatch.setattr(AUDIT, "_openat2_beneath", race_with_fifo)
    with pytest.raises(AUDIT.AuditError, match="already exists"):
        AUDIT.write_new_isolated_output(
            target,
            "generated content\n",
            repo_root=repo,
            temp_root=temp_root,
        )
    assert stat.S_ISFIFO(target.lstat().st_mode)


def test_public_state_capture_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    target = tmp_path / "packet.json"
    os.mkfifo(target)
    parent_fd, _identity = AUDIT._open_publication_directory(tmp_path)
    try:
        with pytest.raises(AUDIT.AuditError, match="not a regular file"):
            AUDIT._capture_public_state(target, parent_fd)
    finally:
        os.close(parent_fd)


def test_public_state_capture_rejects_same_inode_mode_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "packet.json"
    target.write_bytes(b"stable\n")
    target.chmod(0o644)
    real_read = AUDIT._read_stable_descriptor
    changed = False

    def chmod_after_read(descriptor: int, *, label: str) -> bytes:
        nonlocal changed
        content = real_read(descriptor, label=label)
        if not changed:
            os.fchmod(descriptor, 0o600)
            changed = True
        return content

    monkeypatch.setattr(AUDIT, "_read_stable_descriptor", chmod_after_read)
    parent_fd, _identity = AUDIT._open_publication_directory(tmp_path)
    try:
        with pytest.raises(AUDIT.AuditError, match="metadata changed"):
            AUDIT._capture_public_state(target, parent_fd)
    finally:
        os.close(parent_fd)


def test_openat2_publication_rejects_intermediate_ancestor_relocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    parent = temp_root / "nested"
    relocated = temp_root / "relocated"
    outside = tmp_path / "outside"
    repo.mkdir()
    parent.mkdir(parents=True)
    outside.mkdir()
    target = parent / "packet.json"
    real_openat2 = AUDIT._openat2_beneath
    raced = False

    def relocate(root_fd: int, relative: str, *, flags: int, mode: int = 0) -> int:
        nonlocal raced
        if flags & os.O_CREAT and not raced:
            raced = True
            parent.rename(relocated)
            parent.symlink_to(outside, target_is_directory=True)
        return real_openat2(root_fd, relative, flags=flags, mode=mode)

    monkeypatch.setattr(AUDIT, "_openat2_beneath", relocate)
    with pytest.raises(AUDIT.AuditError, match="symlink"):
        AUDIT.write_new_isolated_output(
            target,
            "generated content\n",
            repo_root=repo,
            temp_root=temp_root,
        )
    assert not (outside / "packet.json").exists()
    assert not (relocated / "packet.json").exists()


def test_direct_publication_rejects_concurrent_mode_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "packet.json"
    real_read = AUDIT._read_published_state

    def chmod_before_verify(*args: Any, **kwargs: Any) -> Any:
        target.chmod(0o666)
        return real_read(*args, **kwargs)

    monkeypatch.setattr(AUDIT, "_read_published_state", chmod_before_verify)
    with pytest.raises(AUDIT.AuditError, match="mode is not exact 0644"):
        AUDIT._publish_new_text(tmp_path, target, "payload\n")
    assert stat.S_IMODE(target.stat().st_mode) == 0o666


@pytest.mark.parametrize("error_number", (errno.EOPNOTSUPP, errno.EPERM))
def test_openat2_operational_support_failure_is_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    class UnsupportedLibc:
        def syscall(self, *_args: Any) -> int:
            ctypes.set_errno(error_number)
            return -1

    monkeypatch.setattr(AUDIT.ctypes, "CDLL", lambda *_args, **_kwargs: UnsupportedLibc())
    target = tmp_path / "packet.json"
    with pytest.raises(AUDIT.AuditError, match="unsupported by this Linux filesystem/kernel"):
        AUDIT._publish_new_text(tmp_path, target, "payload\n")
    assert not target.exists()


def test_isolated_output_post_create_swap_preserves_replacement_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    repo.mkdir()
    temp_root.mkdir()
    target = temp_root / "packet.json"
    replacement = temp_root / "replacement.json"
    replacement.write_bytes(b"replacement-owner\n")
    real_verify = AUDIT._verify_isolated_publication

    def swap_after_create(target_path: Path, published: Any, **kwargs: Any) -> None:
        AUDIT.os.replace(replacement, target)
        real_verify(target_path, published, **kwargs)

    monkeypatch.setattr(AUDIT, "_verify_isolated_publication", swap_after_create)
    with pytest.raises(AUDIT.AuditError, match="identity changed"):
        AUDIT.write_new_isolated_output(
            target,
            "generated content\n",
            repo_root=repo,
            temp_root=temp_root,
        )
    assert target.read_bytes() == b"replacement-owner\n"


def test_isolated_output_parent_swap_after_create_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    parent = temp_root / "nested"
    relocated = temp_root / "relocated"
    repo.mkdir()
    parent.mkdir(parents=True)
    target = parent / "packet.json"
    real_verify = AUDIT._verify_isolated_publication

    def swap_parent_after_create(target_path: Path, published: Any, **kwargs: Any) -> None:
        parent.rename(relocated)
        parent.mkdir()
        target.write_bytes(b"replacement-owner\n")
        real_verify(target_path, published, **kwargs)

    monkeypatch.setattr(AUDIT, "_verify_isolated_publication", swap_parent_after_create)
    with pytest.raises(AUDIT.AuditError, match="identity changed"):
        AUDIT.write_new_isolated_output(
            target,
            "generated content\n",
            repo_root=repo,
            temp_root=temp_root,
        )
    assert target.read_bytes() == b"replacement-owner\n"
    assert (relocated / "packet.json").read_bytes() == b"generated content\n"
    assert not list(relocated.glob(".*.tmp"))


def test_isolated_output_failure_never_unlinks_public_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    temp_root = tmp_path / "isolated"
    repo.mkdir()
    temp_root.mkdir()
    target = temp_root / "packet.json"
    real_unlink = AUDIT.os.unlink
    public_unlink_attempts = 0

    def reject_verification(*_args: Any, **_kwargs: Any) -> None:
        raise AUDIT.AuditError("synthetic post-create failure")

    def swap_if_public_unlink(path: str | bytes, *args: Any, **kwargs: Any) -> None:
        nonlocal public_unlink_attempts
        if os.fsdecode(path) == target.name and kwargs.get("dir_fd") is not None:
            public_unlink_attempts += 1
            target.write_bytes(b"concurrent-owner\n")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(AUDIT, "_verify_isolated_publication", reject_verification)
    monkeypatch.setattr(AUDIT.os, "unlink", swap_if_public_unlink)
    with pytest.raises(AUDIT.AuditError, match="synthetic post-create failure"):
        AUDIT.write_new_isolated_output(
            target,
            "generated content\n",
            repo_root=repo,
            temp_root=temp_root,
        )
    assert public_unlink_attempts == 0
    assert target.read_bytes() == b"generated content\n"


def _configure_temp_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, list[dict[str, str]]]:
    root = tmp_path / "repo"
    evidence = root / "docs" / "evidence" / "packet.json"
    report = root / "docs" / "waves" / "packet.md"
    evidence.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    refs = [{"path": "audit.py", "content_sha256": "a" * 64}]
    monkeypatch.setattr(AUDIT, "ROOT", root)
    monkeypatch.setattr(AUDIT, "EVIDENCE_PATH", evidence)
    monkeypatch.setattr(AUDIT, "REPORT_PATH", report)
    monkeypatch.setattr(
        AUDIT,
        "AUTHORIZED_PHASE_A_PATHS",
        frozenset({"docs/evidence/packet.json", "docs/waves/packet.md"}),
    )
    monkeypatch.setattr(AUDIT, "_audit_implementation_refs", lambda: refs)
    return evidence, report, refs


def _write_temp_packet(evidence: dict[str, Any], json_text: str, report_text: str) -> None:
    with AUDIT._packet_publication_lock(AUDIT.ROOT):
        states = AUDIT._capture_packet_target_states()
        AUDIT._write_phase_a_artifacts_locked(evidence, json_text, report_text, states)


def _clean_review_receipt(
    evidence_path: Path, report_path: Path, refs: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "issue": 976,
        "phase": "A",
        "reviewed_at": AUDIT.REVIEW_GATE_DATE,
        "review_origin": {
            "reviewer_role": "independent clean-slate static reviewer",
            "reviewer_identity": "not visible",
            "requested_model": "GPT-5.6 Sol",
            "requested_reasoning": "Ultra",
            "runtime_model": "not visible",
            "runtime_reasoning": "not visible",
        },
        "reviewed_implementation_refs": copy.deepcopy(refs),
        "reviewed_packet_refs": [
            {
                "path": str(path.relative_to(AUDIT.ROOT)),
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in (evidence_path, report_path)
        ],
        "status_only_stamp_authorized": True,
        "review": {
            "requested_model": "GPT-5.6 Sol",
            "requested_reasoning": "Ultra",
            "runtime_model": "not visible",
            "runtime_reasoning": "not visible",
            "status": AUDIT.CLEAN_REVIEW_STATUS,
            "unresolved_p0_p1_p2": 0,
        },
    }


def test_review_receipt_binds_exact_current_pre_stamp_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)

    validated, review, reviewed_packet = AUDIT._validate_review_receipt(
        receipt, refs, verify_current_packet=True
    )

    assert validated == receipt
    assert validated["reviewed_at"] == "2026-08-29"
    assert validated["reviewed_at"] != AUDIT.CAPTURE_DATE
    assert review["unresolved_p0_p1_p2"] == 0
    assert reviewed_packet is not None


@pytest.mark.parametrize(
    "reviewed_at",
    (None, "not-a-date", "2026-8-29", "2026-08-29T00:00:00Z"),
)
def test_review_receipt_rejects_malformed_review_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reviewed_at: str | None,
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["reviewed_at"] = reviewed_at

    with pytest.raises(AUDIT.AuditError, match="exact ISO calendar date"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


def test_review_receipt_rejects_review_date_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["reviewed_at"] = "2026-08-27"

    with pytest.raises(AUDIT.AuditError, match="predates the evidence capture"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


def test_review_receipt_rejects_capture_date_as_backdated_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["reviewed_at"] = AUDIT.CAPTURE_DATE

    with pytest.raises(AUDIT.AuditError, match="does not equal the exact review gate date"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


def test_review_receipt_rejects_review_date_after_exact_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["reviewed_at"] = "2026-08-30"

    with pytest.raises(AUDIT.AuditError, match="exceeds the exact review gate date"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


def test_review_receipt_rejects_pre_stamp_packet_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    report_path.write_bytes(b"changed after review\n")

    with pytest.raises(AUDIT.AuditError, match="exact current pre-stamp packet"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


def test_review_receipt_rejects_duplicate_packet_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["reviewed_packet_refs"] = [receipt["reviewed_packet_refs"][0]] * 2

    with pytest.raises(AUDIT.AuditError, match="incomplete or duplicated"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=False)


def test_review_receipt_rejects_extra_schema_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["unexpected"] = "not authorized"

    with pytest.raises(AUDIT.AuditError, match="schema keys drifted"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=False)


@pytest.mark.parametrize("status", ("unclean", "not clean"))
def test_review_receipt_rejects_ambiguous_clean_substrings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["review"]["status"] = status

    with pytest.raises(AUDIT.AuditError, match="not a clean zero-unresolved verdict"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


@pytest.mark.parametrize("unresolved", (False, 0.0))
def test_review_receipt_rejects_non_integer_zero_unresolved_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unresolved: bool | float
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["review"]["unresolved_p0_p1_p2"] = unresolved

    with pytest.raises(AUDIT.AuditError, match="not a clean zero-unresolved verdict"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


def test_review_receipt_rejects_float_implementation_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    refs[0]["size_bytes"] = 8
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    receipt["reviewed_implementation_refs"][0]["size_bytes"] = 8.0

    with pytest.raises(AUDIT.AuditError, match="implementation refs are stale"):
        AUDIT._validate_review_receipt(receipt, refs, verify_current_packet=True)


def test_write_transition_rejects_archived_review_without_explicit_receipt() -> None:
    archived = {"review": {"status": AUDIT.CLEAN_REVIEW_STATUS}}

    with pytest.raises(AUDIT.AuditError, match="cannot reuse an archived clean review"):
        AUDIT._select_review_receipt(None, archived, for_write=True)
    assert AUDIT._select_review_receipt(None, archived, for_write=False) is archived


def test_json_receipt_reader_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"issue":976,"issue":975}\n', encoding="utf-8")
    with pytest.raises(AUDIT.AuditError, match="duplicate JSON object key"):
        AUDIT._read_json_mapping(duplicate, label="test receipt")

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
    with pytest.raises(AUDIT.AuditError, match="non-finite JSON number"):
        AUDIT._read_json_mapping(nonfinite, label="test receipt")


def test_review_receipt_binds_exact_preserved_temp_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    evidence_path.write_bytes(b"reviewed json\n")
    report_path.write_bytes(b"reviewed report\n")
    receipt = _clean_review_receipt(evidence_path, report_path, refs)
    preserved = tmp_path / "preserved"
    preserved.mkdir()
    preserved_evidence = preserved / "pending.json"
    preserved_report = preserved / "pending.md"
    preserved_evidence.write_bytes(evidence_path.read_bytes())
    preserved_report.write_bytes(report_path.read_bytes())
    sources = {
        str(evidence_path.relative_to(AUDIT.ROOT)): preserved_evidence,
        str(report_path.relative_to(AUDIT.ROOT)): preserved_report,
    }

    validated, review, reviewed_packet = AUDIT._validate_review_receipt(
        receipt,
        refs,
        verify_current_packet=True,
        reviewed_packet_sources=sources,
    )
    assert validated == receipt
    assert review["unresolved_p0_p1_p2"] == 0
    assert reviewed_packet is not None

    preserved_report.write_bytes(b"tampered\n")
    with pytest.raises(AUDIT.AuditError, match="exact current pre-stamp packet"):
        AUDIT._validate_review_receipt(
            receipt,
            refs,
            verify_current_packet=True,
            reviewed_packet_sources=sources,
        )


def test_reviewed_source_openat2_rejects_parent_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    parent = tmp_path / "preserved"
    relocated = tmp_path / "relocated"
    outside = tmp_path / "outside"
    repo.mkdir()
    parent.mkdir()
    outside.mkdir()
    source = parent / "pending.json"
    source.write_bytes(b"reviewed\n")
    (outside / "pending.json").write_bytes(b"attacker\n")
    real_openat2 = AUDIT._openat2_beneath
    raced = False

    def swap(root_fd: int, relative: str, *, flags: int, mode: int = 0) -> int:
        nonlocal raced
        if not raced:
            raced = True
            parent.rename(relocated)
            parent.symlink_to(outside, target_is_directory=True)
        return real_openat2(root_fd, relative, flags=flags, mode=mode)

    monkeypatch.setattr(AUDIT, "_openat2_beneath", swap)
    with pytest.raises(AUDIT.AuditError, match="symlink"):
        AUDIT._read_reviewed_packet_source(source, repo_root=repo)
    assert (outside / "pending.json").read_bytes() == b"attacker\n"


def test_status_only_transform_rejects_substituted_validation_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, _refs = _configure_temp_packet(tmp_path, monkeypatch)
    pending = {
        "validation_receipt": {"receipt": "A"},
        "review_receipt": None,
        "review": {"status": "pending final gate"},
    }
    monkeypatch.setattr(
        AUDIT,
        "render_report",
        lambda evidence: f"validation={evidence['validation_receipt']['receipt']}\n",
    )
    reviewed = {
        str(evidence_path.relative_to(AUDIT.ROOT)): AUDIT.canonical_json(pending).encode(),
        str(report_path.relative_to(AUDIT.ROOT)): b"validation=A\n",
    }
    AUDIT._require_status_only_review_transform(pending, reviewed)

    substituted = copy.deepcopy(pending)
    substituted["validation_receipt"] = {"receipt": "B"}
    with pytest.raises(AUDIT.AuditError, match="status-only review stamp refused"):
        AUDIT._require_status_only_review_transform(substituted, reviewed)


def test_archived_review_refs_reject_validation_b_with_review_from_pending_a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, _refs = _configure_temp_packet(tmp_path, monkeypatch)
    pending_a = {
        "validation_receipt": {"receipt": "A"},
        "review_receipt": None,
        "review": {"status": "pending final gate"},
    }
    monkeypatch.setattr(
        AUDIT,
        "render_report",
        lambda evidence: f"validation={evidence['validation_receipt']['receipt']}\n",
    )
    packet_refs = [
        {
            "path": str(evidence_path.relative_to(AUDIT.ROOT)),
            "content_sha256": hashlib.sha256(AUDIT.canonical_json(pending_a).encode()).hexdigest(),
        },
        {
            "path": str(report_path.relative_to(AUDIT.ROOT)),
            "content_sha256": hashlib.sha256(b"validation=A\n").hexdigest(),
        },
    ]
    AUDIT._require_review_refs_bind_regenerated_pending(pending_a, packet_refs)

    pending_b = copy.deepcopy(pending_a)
    pending_b["validation_receipt"] = {"receipt": "B"}
    with pytest.raises(AUDIT.AuditError, match="selected validation receipt"):
        AUDIT._require_review_refs_bind_regenerated_pending(pending_b, packet_refs)


def test_packet_publication_refuses_existing_targets_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    old_evidence = b"\xff\x00old-json"
    old_report = b"old report\n"
    evidence_path.write_bytes(old_evidence)
    report_path.write_bytes(old_report)
    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", lambda: None)
    with pytest.raises(AUDIT.AuditError, match="canonical artifact exists"):
        _write_temp_packet({"audit_implementation": refs}, "new json\n", "new report\n")
    assert evidence_path.read_bytes() == old_evidence
    assert report_path.read_bytes() == old_report


def test_packet_capture_rejects_missing_parents_without_creating_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    evidence = root / "docs" / "evidence" / "packet.json"
    report = root / "docs" / "waves" / "packet.md"
    monkeypatch.setattr(AUDIT, "ROOT", root)
    monkeypatch.setattr(AUDIT, "EVIDENCE_PATH", evidence)
    monkeypatch.setattr(AUDIT, "REPORT_PATH", report)
    monkeypatch.setattr(
        AUDIT,
        "AUTHORIZED_PHASE_A_PATHS",
        frozenset({"docs/evidence/packet.json", "docs/waves/packet.md"}),
    )

    with pytest.raises(AUDIT.AuditError):
        AUDIT._capture_packet_target_states()
    assert not (root / "docs").exists()


def test_packet_publication_lock_is_inode_bound_releasable_and_pathless(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")

    with AUDIT._packet_publication_lock(repo):
        with pytest.raises(AUDIT.AuditError, match="lock is already held"):
            with AUDIT._packet_publication_lock(repo):
                raise AssertionError("nested lock must not be acquired")
        assert not list((repo / ".git").glob(".metroliza-976*"))
    with AUDIT._packet_publication_lock(repo):
        assert not list((repo / ".git").glob(".metroliza-976*"))


def test_packet_initial_writer_before_first_publish_is_not_clobbered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", lambda: None)
    real_publish = AUDIT._publish_new_text
    raced = False

    def introduce_owner(root: Path, target: Path, content: str) -> Any:
        nonlocal raced
        if target == evidence_path and not raced:
            raced = True
            evidence_path.write_bytes(b"concurrent-initial-owner\n")
        return real_publish(root, target, content)

    monkeypatch.setattr(AUDIT, "_publish_new_text", introduce_owner)
    with pytest.raises(AUDIT.AuditError, match="already exists"):
        _write_temp_packet({"audit_implementation": refs}, "new json\n", "new report\n")
    assert evidence_path.read_bytes() == b"concurrent-initial-owner\n"
    assert not report_path.exists()


def test_packet_first_all_absent_write_passes_actual_scope_postguard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    sentinel = AUDIT.ROOT / "sentinel.txt"
    sentinel.write_text("tracked\n", encoding="utf-8")
    _git(AUDIT.ROOT, "config", "user.name", "Build Delivery Audit")
    _git(AUDIT.ROOT, "config", "user.email", "build-delivery@example.invalid")
    _git(AUDIT.ROOT, "add", "sentinel.txt")
    _git(AUDIT.ROOT, "commit", "-m", "baseline")
    baseline = _git(AUDIT.ROOT, "rev-parse", "HEAD")

    def actual_guard() -> None:
        AUDIT.require_execution_checkout(
            AUDIT.ROOT,
            baseline_sha=baseline,
            expected_branch="main",
            allowed_paths=AUDIT.AUTHORIZED_PHASE_A_PATHS,
        )

    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", actual_guard)
    _write_temp_packet({"audit_implementation": refs}, "new json\n", "new report\n")

    assert evidence_path.read_bytes() == b"new json\n"
    assert report_path.read_bytes() == b"new report\n"
    assert not list(AUDIT.ROOT.rglob(".metroliza-976-stage-*"))
    assert set(_git(AUDIT.ROOT, "status", "--porcelain", "--untracked-files=all").splitlines()) == {
        "?? docs/evidence/packet.json",
        "?? docs/waves/packet.md",
    }


def test_packet_publication_failure_leaves_detectable_partial_pair_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", lambda: None)
    real_publish = AUDIT._publish_new_text

    def fail_second(root: Path, target: Path, content: str) -> Any:
        if Path(target) == report_path:
            raise OSError("synthetic second publication failure")
        return real_publish(root, target, content)

    monkeypatch.setattr(AUDIT, "_publish_new_text", fail_second)
    with pytest.raises(AUDIT.AuditError, match="safely"):
        _write_temp_packet({"audit_implementation": refs}, "new json\n", "new report\n")
    assert evidence_path.read_bytes() == b"new json\n"
    assert not report_path.exists()


def test_packet_publication_postguard_failure_leaves_new_pair_for_check_to_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    calls = 0

    def guarded() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AUDIT.AuditError("synthetic post-publication scope drift")

    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", guarded)
    with pytest.raises(AUDIT.AuditError, match="scope drift"):
        _write_temp_packet({"audit_implementation": refs}, "new json\n", "new report\n")
    assert calls == 2
    assert evidence_path.read_bytes() == b"new json\n"
    assert report_path.read_bytes() == b"new report\n"


def test_packet_publication_interrupt_never_rolls_back_public_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", lambda: None)
    real_publish = AUDIT._publish_new_text
    interrupted = False

    def interrupt_second(root: Path, target: Path, content: str) -> Any:
        nonlocal interrupted
        if Path(target) == report_path and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return real_publish(root, target, content)

    monkeypatch.setattr(AUDIT, "_publish_new_text", interrupt_second)
    with pytest.raises(KeyboardInterrupt):
        _write_temp_packet({"audit_implementation": refs}, "new json\n", "new report\n")
    assert evidence_path.read_bytes() == b"new json\n"
    assert not report_path.exists()


def test_packet_publication_recovery_preserves_concurrent_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path, report_path, refs = _configure_temp_packet(tmp_path, monkeypatch)
    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", lambda: None)
    real_publish = AUDIT._publish_new_text

    def fail_second(root: Path, target: Path, content: str) -> Any:
        if Path(target) == report_path:
            evidence_path.write_bytes(b"concurrent-owner\n")
            raise OSError("synthetic second replace failure")
        return real_publish(root, target, content)

    monkeypatch.setattr(AUDIT, "_publish_new_text", fail_second)
    with pytest.raises(AUDIT.AuditError, match="safely"):
        _write_temp_packet({"audit_implementation": refs}, "new json\n", "new report\n")
    assert evidence_path.read_bytes() == b"concurrent-owner\n"
    assert not report_path.exists()


def test_missing_required_tool_has_truthful_diagnostic() -> None:
    with pytest.raises(AUDIT.AuditError, match="required tool/dependency.*cargo"):
        AUDIT.require_tool(name="cargo", available=False, required=True)


def test_missing_optional_dependency_is_not_misreported_as_available() -> None:
    assert (
        AUDIT.require_tool(name="optional-ocr", available=False, required=False)
        == "optional capability unavailable"
    )


@pytest.mark.parametrize(
    ("manifest_git_sha", "manifest_built_at_ns", "diagnostic"),
    [
        ("b" * 40, 200, "Git identity"),
        ("a" * 40, 99, "predates"),
    ],
)
def test_same_release_stale_git_or_timestamp_provenance_is_detected(
    manifest_git_sha: str,
    manifest_built_at_ns: int,
    diagnostic: str,
) -> None:
    with pytest.raises(AUDIT.AuditError, match=diagnostic):
        AUDIT.require_current_build_provenance(
            manifest_git_sha=manifest_git_sha,
            expected_git_sha="a" * 40,
            manifest_built_at_ns=manifest_built_at_ns,
            attempt_started_ns=100,
        )


def test_sensitive_diagnostic_values_require_redaction() -> None:
    payload = {
        "environment": {
            "cwd": "/home/alice/private-repo",
            "path_head": ["C:\\Users\\Alice\\secret-tools"],
        },
        "parser_diagnostic": {
            "header_text": "Customer secret header",
            "database_rows": [{"operator": "Alice"}],
        },
    }
    with pytest.raises(AUDIT.AuditError, match="retains sensitive value"):
        AUDIT.require_redacted_diagnostic(
            payload,
            sensitive_values=[
                "/home/alice/private-repo",
                "C:\\Users\\Alice\\secret-tools",
                "Customer secret header",
                "Alice",
            ],
        )


def test_interrupted_model_fetch_temp_residue_is_detected(tmp_path: Path) -> None:
    (tmp_path / "detector.onnx.tmp").write_bytes(b"partial")

    with pytest.raises(AUDIT.AuditError, match="partial model-fetch temporary file"):
        AUDIT.require_no_partial_fetch_temps(tmp_path)


def test_phase_a_never_claims_ledger_ci_pr_or_windows_completion() -> None:
    evidence = _evidence_or_skip()

    assert evidence["audit"]["ledger_terminalized"] is False
    assert evidence["phase_boundaries"] == {
        "ledger": "deferred to Phase B",
        "actions_ci": "not dispatched or rerun; no new/current-packet result claimed; existing exact-base run inspected read-only",
        "pull_request": "not opened or finalized",
        "release_artifact": "not created or published",
    }
    assert evidence["platform_evidence"]["windows_packaged"].startswith("not executed")
    linux_source = evidence["platform_evidence"]["linux_source"]
    assert "external post-publication parking gates" in linux_source
    assert "not embedded as pass claims" in linux_source
    linux_row = next(row for row in evidence["platform_failure_matrix"] if row["id"] == "PF-01")
    assert "external full-packet pytest and combined coverage" in linux_row["result"]
    assert "not claimed" in linux_row["result"]
    assert evidence["confidentiality"]["credentials_accessed"] is False
    assert evidence["confidentiality"]["public_hosted_ci_logs_accessed"] is True
    assert evidence["confidentiality"]["nonpublic_or_proprietary_logs_accessed"] is False
    assert evidence["confidentiality"]["local_windows_ocr_diagnostic_payload_accessed"] is False
    assert (
        "potentially sensitive raw JSON"
        in evidence["confidentiality"]["windows_ocr_diagnostic_publication_boundary"]
    )


def test_every_finding_has_one_severity_disposition_and_authoritative_issue() -> None:
    findings = _evidence_or_skip()["findings"]

    assert len({finding["id"] for finding in findings}) == len(findings)
    for finding in findings:
        assert finding["severity"] in {"P0", "P1", "P2", "P3"}
        assert finding["disposition"]
        assert finding["issue"].startswith("https://github.com/hexafe/metroliza/issues/")


def test_all_required_falsifiers_are_bound_and_honest() -> None:
    controls = _evidence_or_skip()["falsification"]["controls"]

    assert len(controls) == 15
    assert {control["id"] for control in controls} == {
        "missing-packaged-asset",
        "repository-root-only-import",
        "misleading-native-fallback",
        "new-static-finding",
        "zero-exit-no-artifact",
        "stale-partial-artifact",
        "import-green-workflow-broken",
        "upstream-required-job-skip",
        "warm-cache-only",
        "shallow-history",
        "path-permission-boundary",
        "missing-tool-optional-dependency",
        "stale-same-release-provenance",
        "sensitive-diagnostic-output",
        "interrupted-model-fetch-cleanup",
    }
    assert all(control["harness_exit_code"] == 0 for control in controls)
    assert all(control["command"] and control["negative_control"] for control in controls)
    assert all(control["control_class"] and control["subject_outcome"] for control in controls)
    assert all(control["subject_refs"] for control in controls)
    assert all(control["production_blob_refs"] for control in controls)
    assert all(len(control["audit_mutation_refs"]) == 2 for control in controls)
    assert all(
        len(ref["git_blob_sha1"]) == 40 and len(ref["content_sha256"]) == 64
        for control in controls
        for ref in (*control["production_blob_refs"], *control["audit_mutation_refs"])
    )
    new_static = next(control for control in controls if control["id"] == "new-static-finding")
    assert any("PR #973" in ref for ref in new_static["subject_refs"])
    warm = next(control for control in controls if control["id"] == "warm-cache-only")
    assert warm["result"].startswith("not independently reproduced")
    assert warm["production_gate"].startswith("unavailable:")


def test_per_path_dispositions_are_explicit_nonterminal_and_resolvable() -> None:
    evidence = _evidence_or_skip()
    paths = evidence["scope"]["paths"]
    registry = evidence["evidence_registry"]

    assert len(paths) == 58
    assert {row["disposition"] for row in paths} == {
        "confirmed_finding_surface",
        "deferred_residual_risk",
        "audited_no_confirmed_finding",
    }
    for row in paths:
        assert row["phase_a_status"] == "audited"
        assert row["evidence_refs"]
        assert all(reference in registry for reference in row["evidence_refs"])
        assert row["snapshot_status"] == "deferred_to_phase_b"
        assert row["terminal_snapshot"] is None
        if row["disposition"] == "deferred_residual_risk":
            assert row["residual_risk"] is not None
            assert row["residual_risk"]["accountable_owner"]
            assert row["residual_risk"]["reason"]
            assert row["residual_risk"]["next_gate"]
        else:
            assert row["residual_risk"] is None


def test_new_primary_path_without_explicit_disposition_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not AUDIT.exact_input_objects_available():
        pytest.skip(
            "exact archived baseline object unavailable in this checkout; #991 owns history"
        )
    mapping = dict(AUDIT.PATH_AUDIT)
    mapping.pop(next(iter(mapping)))
    monkeypatch.setattr(AUDIT, "PATH_AUDIT", mapping)

    with pytest.raises(AUDIT.AuditError, match="explicit per-path audit map drifted"):
        AUDIT._owned_rules_and_paths()


def test_secondary_inventory_is_bounded_hashed_and_does_not_transfer_ownership() -> None:
    evidence = _evidence_or_skip()
    primary = {row["path"] for row in evidence["scope"]["paths"]}
    secondary = evidence["scope"]["secondary_paths"]

    assert len(secondary) == 124
    assert sum(row["tracked"] for row in secondary) == 122
    assert not primary & {row["path"] for row in secondary}
    assert [row["path"] for row in secondary] == sorted(row["path"] for row in secondary)
    assert len({row["path"] for row in secondary}) == len(secondary)
    for row in secondary:
        assert row["relationship"] == (
            "secondary evidence only; primary ownership is not transferred"
        )
        assert row["evidence_refs"]
        if row["tracked"]:
            assert len(row["git_blob_sha1"]) == 40
            assert len(row["content_sha256"]) == 64
            assert row["primary_owner_at_baseline"]["rule"]
        else:
            assert row["primary_owner_at_baseline"] is None
            assert row["missing_reason"]


def test_every_evidence_reference_resolves_once_to_a_stable_object() -> None:
    evidence = _evidence_or_skip()
    registry = evidence["evidence_registry"]
    referenced = AUDIT._collect_evidence_refs(
        {key: value for key, value in evidence.items() if key != "evidence_registry"}
    )

    assert referenced <= set(registry)
    assert len(registry) == len(set(registry))
    for reference, row in registry.items():
        assert row["id"] == reference
        assert row["json_pointer"].startswith("/")
        assert row["report_anchor"] == AUDIT._evidence_anchor(reference)
        assert row["binding"]
        target = AUDIT.resolve_json_pointer(evidence, row["json_pointer"])
        assert row["resolved_target_type"] == type(target).__name__
        assert row["resolved_target_sha256"] == _canonical_target_sha256(target)

    structured = {reference: registry[reference] for reference in AUDIT.EVIDENCE_POINTERS}
    assert set(structured) == set(AUDIT._structured_provenance_map(evidence))
    assert all(row["provenance_refs"] for row in structured.values())
    assert all(
        provenance["kind"] for row in structured.values() for provenance in row["provenance_refs"]
    )
    assert all("baseline_ref" not in row for row in structured.values())
    assert AUDIT.resolve_json_pointer(evidence, "/pr_973") is evidence["pr_973"]
    assert AUDIT.resolve_json_pointer(evidence, "/ci/jobs") is evidence["ci"]["jobs"]

    def refs(reference: str) -> list[dict[str, Any]]:
        return structured[reference]["provenance_refs"]

    assert {(row.get("commit"), row.get("tree")) for row in refs("EV-PR972")} >= {
        (AUDIT.PR_INPUT_PARENT_SHA, AUDIT.PR_INPUT_PARENT_TREE),
        (AUDIT.PR972_SHA, AUDIT.PR972_TREE),
    }
    assert {row.get("run_id") for row in refs("EV-PR972")} >= {
        32932158352,
        32932162551,
    }
    assert {(row.get("commit"), row.get("tree")) for row in refs("EV-PR973")} >= {
        (AUDIT.PR_INPUT_PARENT_SHA, AUDIT.PR_INPUT_PARENT_TREE),
        (AUDIT.BASELINE_SHA, AUDIT.BASELINE_TREE),
        (AUDIT.PR973_SHA, AUDIT.PR973_TREE),
    }
    assert {row.get("run_id") for row in refs("EV-PR973")} >= {
        32932367574,
        32932363678,
    }
    assert {row.get("run_id") for row in refs("EV-CI")} == {None, 33151703847}
    assert {row["kind"] for row in refs("EV-ENVIRONMENT")} == {
        "git_tree",
        "phase_a_local_capture",
    }
    assert {row["kind"] for row in refs("EV-AUDIT-HARNESS")} == {"phase_a_content"}
    assert {row["kind"] for row in refs("EV-PLATFORM")} >= {
        "git_tree",
        "public_github_actions_run",
        "phase_a_local_capture",
        "phase_a_content",
    }


@pytest.mark.parametrize(
    "pointer",
    ["not/a/pointer", "/missing", "/ci/jobs/00", "/ci/jobs/999", "/ci/jobs/0~2"],
)
def test_json_pointer_resolution_rejects_invalid_or_missing_targets(pointer: str) -> None:
    with pytest.raises(AUDIT.AuditError, match="JSON pointer|invalid"):
        AUDIT.resolve_json_pointer({"ci": {"jobs": []}}, pointer)


def test_lossless_workflow_inventory_preserves_all_jobs_and_steps() -> None:
    workflow = _evidence_or_skip()["ci"]["exact_baseline_inventory"]

    assert workflow["path"] == ".github/workflows/ci.yml"
    assert len(workflow["baseline_blob"]) == 40
    assert len(workflow["content_sha256"]) == 64
    assert len(workflow["jobs"]) == 8
    steps = [step for job in workflow["jobs"] for step in job["steps"]]
    assert len(steps) == 71
    assert all(len(step["source_yaml_sha256"]) == 64 for step in steps)
    assert all("id" in step and "shell" in step for step in steps)
    assert all(bool(step["uses"]) ^ bool(step["run"]) for step in steps)
    assert all(step["effective_if"] for step in steps)
    assert any("cache_semantics" in step for step in steps)
    assert any("artifact_semantics" in step for step in steps)


def test_pr973_matrix_preserves_exact_edits_resolutions_and_family_boundaries() -> None:
    proposal = _evidence_or_skip()["pr_973"]

    assert proposal["manifest_edit_count"] == len(proposal["declaration_edits"]) == 36
    assert proposal["proposal_count"] == len(proposal["resolution_rows"]) == 35
    assert proposal["resolved_change_count"] == 6
    assert sum(row["resolved_changed"] for row in proposal["resolution_rows"]) == 6
    assert len(proposal["families"]) == 9
    required = {
        "family",
        "names",
        "python_311",
        "linux_artifacts",
        "windows_evidence",
        "api_risks",
        "conflicts",
        "commands",
        "downstream_waves",
        "decision",
        "owner",
    }
    assert all(set(family) == required for family in proposal["families"])
    assert all(family["commands"] for family in proposal["families"])
    assert all(
        command["cwd"] == AUDIT.PR973_PROPOSAL_CWD
        for family in proposal["families"]
        for command in family["commands"]
    )
    assert len(proposal["windows_resolution_rows"]) == 7
    capture = proposal["resolution_capture"]
    assert capture["opaque_capture_raw_stream_retained"] is False
    assert capture["opaque_capture_digest_verified"] is False
    assert capture["pip_check"].startswith("observational pass")
    assert {row["subject_ref"] for row in capture["pip_check_observations"]} == {
        AUDIT.BASELINE_SUBJECT_REF,
        AUDIT.PR973_SUBJECT_REF,
    }
    assert all(
        row["exit_code"] == 0
        and row["exact_argv_retained"] is False
        and row["raw_output_retained"] is False
        for row in capture["pip_check_observations"]
    )
    for side in ("baseline", "proposal"):
        rows = capture[f"{side}_retained_rows"]
        assert len(rows) == 35
        payload = (
            json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        assert capture[f"{side}_retained_rows_sha256"] == hashlib.sha256(payload).hexdigest()
    for row in proposal["windows_resolution_rows"]:
        assert row["normalized_stream_retained"] is False
        assert row["row_count_recomputed"] is False
        assert row["digest_recomputed"] is False
        if row["opaque_capture_sha256"] is None:
            assert row["input"] == "proposal build"
            assert row["opaque_capture_digest_well_formed"] is False
            assert len(row["malformed_opaque_capture_commitment"]) == 63
        else:
            assert len(row["opaque_capture_sha256"]) == 64
            assert row["opaque_capture_digest_well_formed"] is True
    policies = [row["binary_policy"] for row in proposal["windows_resolution_rows"]]
    assert policies.count("--only-binary :all:") == 4
    assert policies.count("--only-binary :all: --no-binary nuitka") == 1
    assert policies.count("ordinary compile policy; not wheel-only evidence") == 2


def test_rust_lock_variants_are_not_overwritten_between_five_locks() -> None:
    rust = _evidence_or_skip()["dependencies"]["rust"]

    assert len(rust["manifests"]) == 5
    assert len(rust["lock_packages"]) == 5
    assert all(rust["lock_packages"][path] for path in rust["lock_packages"])
    assert rust["coordinates_with_multiple_dependency_variants"] == [
        "num-traits@0.2.19|registry+https://github.com/rust-lang/crates.io-index",
        "pyo3-macros-backend@0.21.2|registry+https://github.com/rust-lang/crates.io-index",
        "pyo3-macros@0.21.2|registry+https://github.com/rust-lang/crates.io-index",
        "zerocopy-derive@0.8.48|registry+https://github.com/rust-lang/crates.io-index",
    ]
    assert len(rust["unique_locked_package_variants"]) == 87


def test_build_command_inventory_is_the_exact_25_entrypoint_closure() -> None:
    rows = _evidence_or_skip()["build_command_inventory"]
    paths = {row["path"] for row in rows}

    assert len(rows) == len(paths) == 25
    assert paths == {
        "build_windows_exe.bat",
        "build_windows_exe.ps1",
        "diagnose_windows_ocr.bat",
        "diagnose_windows_ocr.ps1",
        "setup_windows_runtime.bat",
        "setup_windows_runtime.ps1",
        "packaging/build_native_and_package.ps1",
        "packaging/build_nuitka.ps1",
        "packaging/metroliza_onedir.spec",
        "packaging/metroliza_onefile.spec",
        "packaging/metroliza_package_entry.py",
        "scripts/benchmark_paths.py",
        "scripts/benchmark_trend_compare.py",
        "scripts/build_provenance.py",
        "scripts/check_release_hygiene.py",
        "scripts/fetch_rapidocr_models.py",
        "scripts/generate_third_party_inventory.py",
        "scripts/measure_windows_startup.ps1",
        "scripts/release_only_google_conversion_smoke.py",
        "scripts/stage_release_notices.py",
        "scripts/summarize_startup_profile.py",
        "scripts/sync_release_metadata.py",
        "scripts/validate_packaged_pdf_parser.py",
        "scripts/validate_qt_runtime.py",
        "scripts/windows_ocr_runtime_diagnostics.py",
    }
    assert all(row["callers"] and row["output_contract"] for row in rows)
    assert all(row["failure_contract"] and row["status"] for row in rows)
    assert all(len(row["git_blob_sha1"]) == 40 for row in rows)
    by_path = {row["path"]: row for row in rows}
    assert by_path["setup_windows_runtime.bat"]["callers"] == ["operator"]
    assert by_path["setup_windows_runtime.ps1"]["callers"] == [
        "setup_windows_runtime.bat",
        "README Windows setup guidance",
        "operator",
    ]
    assert by_path["diagnose_windows_ocr.bat"]["callers"] == ["operator"]
    assert by_path["build_windows_exe.bat"]["callers"] == [
        "README Windows build guidance",
        "operator",
    ]
    assert by_path["build_windows_exe.ps1"]["callers"] == [
        "build_windows_exe.bat",
        "README Windows build guidance",
        ".github/workflows/ci.yml",
        "operator",
    ]
    assert (
        "OCR diagnostic child currently returns zero"
        in by_path["setup_windows_runtime.ps1"]["failure_contract"]
    )
    assert (
        "diagnostic smoke-row failures"
        in by_path["scripts/windows_ocr_runtime_diagnostics.py"]["failure_contract"]
    )
    assert "normalized to 1" in by_path["build_windows_exe.bat"]["output_contract"]
    assert (
        "partial inventory file is written"
        in by_path["scripts/generate_third_party_inventory.py"]["failure_contract"]
    )
    assert by_path["scripts/summarize_startup_profile.py"]["callers"] == [
        "README/manual documentation",
        "operator",
    ]
    assert (
        "event_count=0 and nullable metrics"
        in by_path["scripts/summarize_startup_profile.py"]["output_contract"]
    )
    assert (
        "presence/loadability is not validated"
        in by_path["scripts/validate_qt_runtime.py"]["failure_contract"]
    )
    assert (
        "can leave a partial .tmp file"
        in by_path["scripts/fetch_rapidocr_models.py"]["failure_contract"]
    )
    assert (
        "successful remote Google Sheet persists"
        in by_path["scripts/release_only_google_conversion_smoke.py"]["output_contract"]
    )
    assert (
        "best-effort remote deletion only for exceptions"
        in by_path["scripts/release_only_google_conversion_smoke.py"]["failure_contract"]
    )
    assert by_path["packaging/metroliza_package_entry.py"]["output_contract"].endswith(
        "metroliza.app.bootstrap.run_application"
    )
    assert (
        "passed to SystemExit"
        in by_path["packaging/metroliza_package_entry.py"]["failure_contract"]
    )
    assert (
        "not sanitized for publication"
        in by_path["scripts/windows_ocr_runtime_diagnostics.py"]["output_contract"]
    )
    stage_callers = by_path["scripts/stage_release_notices.py"]["callers"]
    assert "setup_windows_runtime.ps1" not in stage_callers
    assert (
        "always creates a root dist/release-notices bundle"
        in by_path["scripts/stage_release_notices.py"]["output_contract"]
    )
    assert (
        "no candidate still succeeds"
        in by_path["scripts/stage_release_notices.py"]["output_contract"]
    )
    assert (
        "initially missing dist with no candidates succeeds"
        in by_path["scripts/stage_release_notices.py"]["failure_contract"]
    )
    assert {"README.md"} <= {
        edge["path"] for edge in by_path["build_windows_exe.bat"]["baseline_reference_edges"]
    }
    assert {
        "README.md",
        "build_windows_exe.bat",
        ".github/workflows/ci.yml",
    } <= {edge["path"] for edge in by_path["build_windows_exe.ps1"]["baseline_reference_edges"]}
    assert by_path["scripts/build_provenance.py"]["declared_options"] == [
        "--artifact",
        "--manifest",
        "--output",
        "--packager",
        "--repo-root",
        "generate",
        "stage",
        "validate",
    ]
    assert by_path["scripts/validate_packaged_pdf_parser.py"]["declared_options"] == [
        "--allow-broken-pdf-parser-build",
        "--allow-missing-header-ocr-build",
        "--header-ocr-model-dir",
        "--report",
        "--require-header-ocr",
    ]
    assert "PSScriptRoot" not in by_path["packaging/build_nuitka.ps1"]["declared_options"]
    assert "true" not in by_path["scripts/measure_windows_startup.ps1"]["declared_options"]
    ocr_callers = {
        edge["path"]
        for edge in by_path["scripts/windows_ocr_runtime_diagnostics.py"][
            "baseline_reference_edges"
        ]
    }
    assert {"diagnose_windows_ocr.ps1", "setup_windows_runtime.ps1"} <= ocr_callers
    pdf_callers = {
        edge["path"]
        for edge in by_path["scripts/validate_packaged_pdf_parser.py"]["baseline_reference_edges"]
    }
    assert {
        ".github/workflows/ci.yml",
        "build_windows_exe.ps1",
        "packaging/build_native_and_package.ps1",
        "packaging/build_nuitka.ps1",
        "setup_windows_runtime.ps1",
    } <= pdf_callers

    executor_rows = _evidence_or_skip()["external_executor_inventory"]
    executors = {row["id"] for row in executor_rows}
    assert executors == {"EXEC-PIP", "EXEC-MATURIN", "EXEC-PYINSTALLER", "EXEC-NUITKA"}
    assert all(
        contract["argv"] and contract["callers"]
        for row in executor_rows
        for contract in row["argv_contracts"]
    )
    pip = next(row for row in executor_rows if row["id"] == "EXEC-PIP")
    anomaly = next(
        contract
        for contract in pip["argv_contracts"]
        if contract["argv"].endswith("requirements-anomaly.txt")
    )
    assert anomaly["callers"] == [
        "src/metroliza/industrial/anomaly/optional_dependencies.py user recommendation"
    ]


def test_package_inventory_has_disjoint_exact_nuitka_categories_and_resource_rows() -> None:
    packaging = _evidence_or_skip()["packaging"]
    nuitka = packaging["nuitka"]

    assert len(nuitka["conditional_pdf_modules"]) == 8
    assert len(nuitka["conditional_ocr_arguments"]) == 15
    assert len(nuitka["token_exclusions"]) == 4
    assert not set(nuitka["conditional_pdf_modules"]) & set(nuitka["conditional_ocr_arguments"])
    assert not set(nuitka["conditional_ocr_arguments"]) & set(nuitka["token_exclusions"])
    models = [row for row in packaging["resources"] if row["kind"] == "RapidOCR model"]
    assert len(models) == 3
    assert len(packaging["ocr_model_hashes"]) == 3
    assert all(row["match"] for row in packaging["ocr_model_hashes"])
    assert all(
        row["expected_sha256"] == row["actual_sha256"] for row in packaging["ocr_model_hashes"]
    )
    assert all(
        set(row["packagers_and_modes"])
        == {
            "pyinstaller_onefile",
            "pyinstaller_onedir",
            "nuitka_onefile",
            "nuitka_standalone",
        }
        for row in packaging["resources"]
    )


def test_version_platform_routing_and_residual_schemas_are_complete() -> None:
    evidence = _evidence_or_skip()

    assert evidence["audit"]["capture_date"] == "2026-08-28"
    assert evidence["audit"]["runtime_identity"]["runtime_model"] == "not visible"
    assert len(evidence["audit"]["routing"]) == 5
    assert len(evidence["version_identity_matrix"]) == 18
    assert len(evidence["platform_failure_matrix"]) == 14
    assert any(
        "Nuitka" in row["channel"] and "no generated/embedded" in row["limitation"]
        for row in evidence["version_identity_matrix"]
    )
    assert any(
        row["channel"] == "missing/corrupt embedded provenance fallback"
        and "source/unknown" in row["result"]
        and "frozen" in row["value"]
        for row in evidence["version_identity_matrix"]
    )
    assert (
        "ephemeral operating-system-temp artifact" in evidence["lifecycle"]["evidence_construction"]
    )
    for risk in evidence["residual_risks"]:
        assert {
            "id",
            "severity",
            "taxonomy",
            "classification",
            "reason",
            "accountable_owner",
            "target_issue_or_phase",
            "next_gate",
            "preserved_seam",
        } == set(risk)


def test_discovery_probe_exit_semantics_are_not_conflated() -> None:
    probes = {row["id"]: row for row in _evidence_or_skip()["discovery_probes"]}

    assert len(probes) == 12
    assert probes["DP-HISTORY-SHALLOW"]["harness_exit_code"] == 0
    assert probes["DP-HISTORY-SHALLOW"]["subject_exit_code"] == 1
    assert probes["DP-OCR-HASH-DELETE"]["subject_exit_code"] is None
    assert probes["DP-PATH-BOUNDARIES"]["subject_exit_code"] is None
    assert probes["DP-PR973-POLICY"]["harness_exit_code"] == 1
    assert all(probe["subject_refs"] for probe in probes.values())
    assert all(len(probe["audit_record_refs"]) == 2 for probe in probes.values())
    assert any("PR #973" in ref for ref in probes["DP-PR973-POLICY"]["subject_refs"])
    assert all("PR #973" not in ref for ref in probes["DP-OCR-HASH-DELETE"]["subject_refs"])
    assert (
        "validate_packaged_pdf_parser.py --require-header-ocr"
        in probes["DP-OCR-HASH-DELETE"]["command"]
    )
    assert "rejects_missing_assets" in probes["DP-OCR-HASH-DELETE"]["negative_control_command"]
    assert probes["DP-PR973-FAMILY"]["exact_argv_retained"] is False
    assert probes["DP-PR973-QT"]["exact_argv_retained"] is False
    assert probes["DP-PR973-QT"]["subject_refs"] == [
        AUDIT.BASELINE_SUBJECT_REF,
        AUDIT.PR973_SUBJECT_REF,
    ]
    assert probes["DP-WINDOWS-WHEEL-RESOLUTION"]["subject_refs"] == [
        AUDIT.BASELINE_SUBJECT_REF,
        AUDIT.PR973_SUBJECT_REF,
    ]
    assert "four strict wheel-only" in probes["DP-WINDOWS-WHEEL-RESOLUTION"]["result"]
    assert all(probe["durably_reproducible"] is False for probe in probes.values())


def test_evidence_construction_does_not_run_one_shot_packet_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not AUDIT.exact_input_objects_available():
        pytest.skip(
            "exact archived baseline object unavailable in this checkout; #991 owns history"
        )

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("one-shot checkout preflight leaked into pure evidence construction")

    monkeypatch.setattr(AUDIT, "require_execution_checkout", fail_if_called)
    evidence = AUDIT.build_evidence()
    assert evidence["lifecycle"]["phase_a_packet_preflight"].startswith("mandatory for --write")


def test_packet_preflight_delegates_to_exact_branch_scope_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def capture(repo: Path, **kwargs: object) -> None:
        observed["repo"] = repo
        observed.update(kwargs)

    monkeypatch.setattr(AUDIT, "require_execution_checkout", capture)
    AUDIT.require_phase_a_packet_checkout()

    assert observed == {
        "repo": AUDIT.ROOT,
        "baseline_sha": AUDIT.BASELINE_SHA,
        "expected_branch": AUDIT.BRANCH,
        "allowed_paths": AUDIT.AUTHORIZED_PHASE_A_PATHS,
    }


def test_write_mode_cannot_bypass_packet_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject() -> None:
        raise AUDIT.AuditError("synthetic wrong-branch preflight")

    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", reject)

    with pytest.raises(AUDIT.AuditError, match="wrong-branch preflight"):
        AUDIT.main(
            [
                "--write",
                "--validation-receipt",
                "/tmp/metroliza-976-synthetic-validation-receipt.json",
            ]
        )


def test_write_cli_requires_explicit_receipt_and_complete_review_sources() -> None:
    with pytest.raises(SystemExit):
        AUDIT._parse_cli_args(["--write"])
    with pytest.raises(SystemExit):
        AUDIT._parse_cli_args(
            [
                "--write",
                "--validation-receipt",
                "/tmp/validation.json",
                "--review-receipt",
                "/tmp/review.json",
            ]
        )


def test_plain_packet_check_repeats_checkout_guard_after_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = [{"path": "audit.py", "content_sha256": "a" * 64}]
    evidence = {
        "audit_implementation": refs,
        "scope": {"rules": [], "paths": []},
    }
    calls = 0

    def guarded() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AUDIT.AuditError("synthetic late packet drift")

    monkeypatch.setattr(AUDIT, "require_phase_a_packet_checkout", guarded)
    monkeypatch.setattr(AUDIT, "build_evidence", lambda **_kwargs: evidence)
    monkeypatch.setattr(AUDIT, "canonical_json", lambda _evidence: "{}\n")
    monkeypatch.setattr(AUDIT, "render_report", lambda _evidence: "report\n")
    monkeypatch.setattr(AUDIT, "_compare", lambda _path, _text: None)
    monkeypatch.setattr(AUDIT, "_audit_implementation_refs", lambda: refs)

    with pytest.raises(AUDIT.AuditError, match="late packet drift"):
        AUDIT.main(["--check"])
    assert calls == 2


def test_plain_check_rejects_implementation_change_after_evidence_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = [{"path": "audit.py", "content_sha256": "a" * 64}]
    changed = [{"path": "audit.py", "content_sha256": "b" * 64}]
    evidence = {
        "audit_implementation": captured,
        "scope": {"rules": [], "paths": []},
    }
    monkeypatch.setattr(AUDIT, "build_evidence", lambda **_kwargs: evidence)
    monkeypatch.setattr(AUDIT, "canonical_json", lambda _evidence: "{}\n")
    monkeypatch.setattr(AUDIT, "render_report", lambda _evidence: "report\n")
    monkeypatch.setattr(AUDIT, "_compare", lambda _path, _text: None)
    monkeypatch.setattr(AUDIT, "_audit_implementation_refs", lambda: changed)

    with pytest.raises(AUDIT.AuditError, match="implementation changed"):
        AUDIT.main(["--check"])


def test_report_renders_all_structured_evidence_sections() -> None:
    evidence = _evidence_or_skip()
    report = AUDIT.render_report(evidence)

    for heading in (
        "## Relevant secondary paths",
        "### Lossless baseline workflow inventory",
        "## Version and build identity matrix",
        "### PyInstaller exact contract",
        "### Nuitka exact contract",
        "### Resource, destination and discovery matrix",
        "### Platform and failure matrix",
        "## Evidence reference index",
    ):
        assert heading in report
    assert "Requiredness" in report
    assert "HD-976-R001" in report
    assert "DP-HISTORY-SHALLOW" in report
    assert "not independently reproduced; synthetic detection seam only" in report
    assert "| Command/gate | Captured display command(s) |" in report
    assert (
        "The per-invocation table above is authoritative for receipt-retained portable logical "
        "argv, environment and cwd" in report
    )
    assert "Parser logical operands execute only through unretained role-checked" in report
