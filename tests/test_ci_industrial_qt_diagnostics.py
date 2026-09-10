"""Hosted #998 guard/output regressions; never create a core or import Qt."""

import json
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import ci_industrial_qt_diagnostics as diagnostic


def test_ci_context_collects_core_without_starting_symbolizer(monkeypatch, tmp_path):
    core = tmp_path / "core.123"
    core.write_bytes(b"\x7fELF\x02\x01\x01" + bytes(9) + b"\x04\x00\x3e\x00" + bytes(44))
    core.chmod(0o600)
    monkeypatch.setattr(diagnostic, "_run_private", lambda *a, **k: pytest.fail("process during collection"))
    result = diagnostic._collect_core(tmp_path, {"pid": 123, "signal": 11})
    assert result["ok"] and result["capture"] == "collected_not_symbolized"
    assert core.exists()


def test_ci_context_missing_capture_is_not_a_symbolizer_probe(tmp_path):
    assert diagnostic._collect_core(tmp_path, {"pid": 123}) == {"capture": "missing_core", "ok": False}


@pytest.mark.parametrize("mutation", ["missing", "changed", "unrecorded"])
def test_ci_context_never_substitutes_unmatched_mapped_binary(tmp_path, mutation):
    source = tmp_path / "library.so"
    source.write_bytes(b"\x7fELFbefore")
    inventory = {str(source): diagnostic._file_identity(source)}
    if mutation == "missing":
        source.unlink()
    elif mutation == "changed":
        source.write_bytes(b"\x7fELFafter")
    else:
        inventory.clear()
    with pytest.raises((ValueError, OSError)):
        diagnostic._preserve_mapped_files(tmp_path, [str(source)], inventory)


def test_ci_context_matching_binary_is_private_and_hash_verified(tmp_path):
    source = tmp_path / "library.so"
    source.write_bytes(b"\x7fELFbefore")
    inventory = {str(source): diagnostic._file_identity(source)}
    result = diagnostic._preserve_mapped_files(tmp_path, [str(source)], inventory)
    copied = tmp_path / "sysroot" / str(source).lstrip("/")
    assert copied.read_bytes() == source.read_bytes()
    assert copied.stat().st_mode & 0o077 == 0
    assert result[0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert str(tmp_path) not in repr(result)


def test_ci_context_readelf_requires_complete_nt_file_table():
    text = "  CORE 0x20 NT_FILE (mapped files)\n    Page size: 4096\n                 Start                 End         Page Offset\n    0x0000000010000000  0x0000000010001000  0x0000000000000000\n        /usr/lib/libc.so.6\n"
    assert diagnostic._mapped_files(text) == ["/usr/lib/libc.so.6"]
    with pytest.raises(ValueError):
        diagnostic._mapped_files(text.replace("/usr/lib/libc.so.6", "(deleted)"))
    with pytest.raises(ValueError):
        diagnostic._mapped_files("Cannot decode 64-bit note")


def test_ci_context_collection_failure_keeps139_and_stops(acquisition, monkeypatch):
    root, calls, outcomes, _ = acquisition
    outcomes["main"] = {"child_exit": -11, "signal": 11}
    monkeypatch.setattr(diagnostic, "_inspect_core", lambda *a: pytest.fail("early symbolization"))
    monkeypatch.setattr(diagnostic, "_collect_core", lambda *a: {"ok": False, "capture": "missing_core"})
    receipt = {"deferred_symbolization": True}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 139
    assert [call[0] for call in calls] == ["coverage_erase", "main"]
    assert receipt["stages"][-1]["capture"] == "missing_core"


def test_ci_context_workflow_never_provisions_debugger_before_workload():
    import yaml
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["industrial-postmortem"]
    provision = [step.get("run", "") for step in job["steps"]]
    assert not any("apt-get install -y gdb" in command or "install -y gcc" in command for command in provision)
    assert "PYTHONDONTWRITEBYTECODE" not in job["env"]
    assert diagnostic.FROZEN_SHA == "b451e7af3153da89c16d09f5b26a7f4799a82da3"


@pytest.mark.parametrize("failure", [None, "capture", "symbols", "timeout", "cancel"])
def test_ci_context_order_and_cleanup_on_each_boundary(monkeypatch, tmp_path, failure):
    admission = {"run_id": "500", "scaffolding_sha": "a" * 40, "phase": diagnostic.PHASE,
        "workload_sha": diagnostic.FROZEN_SHA, "workload_tree": diagnostic.FROZEN_TREE,
        "observation_deadline_epoch": diagnostic.time.time() + 2400}
    (tmp_path / "admission.json").write_text(json.dumps(admission))
    for key, value in {"GITHUB_RUN_ID": "500", "GITHUB_SHA": "a" * 40,
                       "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic, "_private_root", lambda: tmp_path)
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda *a: None)
    monkeypatch.setattr(diagnostic.signal, "alarm", lambda *a: None)
    monkeypatch.setattr(diagnostic, "_validate_runtime", lambda *a: None)
    events, emitted = [], []
    def prepare(*args):
        events.append("inventory")
        return {}
    def collect(*args):
        events.append("capture")
        if failure == "capture":
            raise ValueError("SYNTHETIC_SECRET")
    def execute(root, workload, receipt):
        events.append("workload_terminated")
        receipt["acquisition_exit"] = 139
        return 139
    def symbolize(root, receipt, result):
        assert result == 139
        events.append("symbols")
        if failure in ("symbols", "timeout", "cancel"):
            raise {"symbols": OSError, "timeout": TimeoutError, "cancel": InterruptedError}[failure]("SYNTHETIC_SECRET")
        return result
    def cleanup(root):
        events.append("cleanup")
        return {"ok": True}
    for name, function in {"_prepare_hosted_capture": prepare, "_prove_hosted_capture": collect,
        "_acquire_sequence": execute, "_symbolize_after_workload": symbolize,
        "_cleanup_hosted": cleanup, "_emit_hosted": emitted.append}.items():
        monkeypatch.setattr(diagnostic, name, function)
    assert diagnostic.hosted_observe() == (70 if failure == "capture" else 139)
    assert events == (["inventory", "capture", "cleanup"] if failure == "capture" else
                      ["inventory", "capture", "workload_terminated", "symbols", "cleanup"])
    assert "SYNTHETIC_SECRET" not in repr(emitted)


@pytest.fixture
def deferred_symbols(monkeypatch, tmp_path):
    events = []
    (tmp_path / "binaries.json").write_text("{}")
    (tmp_path / "system-packages.json").write_text("[]")
    receipt = {"synthetic_control": {"pid": 11, "signal": 11}, "observation": "CAPTURE INCOMPLETE",
        "stages": [{"stage": "industrial_1", "pid": 22, "signal": 11,
                    "python_context_status": "available", "python_context_receipt": "industrial_1"}]}
    monkeypatch.setattr(diagnostic, "_collect_core", lambda *a: {"ok": True})
    def preserve(root, child, executable, inventory):
        events.append(("preserve", child["pid"]))
        return [{"module": "binary", "sha256": "a" * 64}]
    def tools(root):
        events.append("prepare_symbolizer")
        return {"packages": []}
    def inspect(root, child, executable, **kwargs):
        assert str(root / "sysroot") in executable
        events.append(("symbolize", child["pid"]))
        return {"ok": True, "native": {"function": "qt998_crash_control"}}
    monkeypatch.setattr(diagnostic, "_preserve_core_binaries", preserve)
    monkeypatch.setattr(diagnostic, "_prepare_symbolizer", tools)
    monkeypatch.setattr(diagnostic, "_inspect_core", inspect)
    monkeypatch.setattr(diagnostic, "_system_packages", lambda *a: [])
    monkeypatch.setattr(diagnostic, "_emit_hosted", lambda *a: None)
    return tmp_path, receipt, events


def test_ci_context_preserves_both_process_binaries_before_provisioning(deferred_symbols):
    root, receipt, events = deferred_symbols
    assert diagnostic._symbolize_after_workload(root, receipt, 139) == 139
    assert events == [("preserve", 11), ("preserve", 22), "prepare_symbolizer", ("symbolize", 11), ("symbolize", 22)]
    assert receipt["observation"] == "CAPTURED" and receipt["paired_process"]["pid"] == 22


@pytest.mark.parametrize("fault", ["missing", "mismatch", "read", "python_missing", "publication", "cancel"])
def test_ci_context_unavailable_pair_never_reports_captured(deferred_symbols, monkeypatch, fault):
    root, receipt, events = deferred_symbols
    preserve = diagnostic._preserve_core_binaries
    def changed(root, child, executable, inventory):
        if child["pid"] == 22:
            raise OSError("SYNTHETIC_SECRET")
        return preserve(root, child, executable, inventory)
    if fault == "missing":
        monkeypatch.setattr(diagnostic, "_collect_core", lambda root, child: {"ok": child["pid"] == 11})
    elif fault in ("mismatch", "read"):
        monkeypatch.setattr(diagnostic, "_preserve_core_binaries", changed)
    elif fault == "python_missing":
        receipt["stages"][0]["python_context_status"] = "unavailable"
    elif fault == "cancel":
        receipt["stages"][0]["cancelled"] = True
    elif fault == "publication":
        def publish(value):
            if value.get("post_workload_native", {}).get("stage") == "industrial_1":
                raise OSError("SYNTHETIC_SECRET")
        monkeypatch.setattr(diagnostic, "_emit_hosted", publish)
    if fault == "publication":
        with pytest.raises(OSError):
            diagnostic._symbolize_after_workload(root, receipt, 139)
    else:
        assert diagnostic._symbolize_after_workload(root, receipt, 139) == 139
    assert receipt["observation"] == "CAPTURE INCOMPLETE"
    assert "SYNTHETIC_SECRET" not in repr(receipt)
    if fault == "cancel":
        assert events == []


def test_ci_context_safe_ordinary_environment_is_retained(monkeypatch, tmp_path):
    for name, value in {"LANG": "en_US.UTF-8", "QT_QPA_PLATFORMTHEME": "gtk3", "TMPDIR": "/tmp"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    child = diagnostic._child_environment(tmp_path)
    assert child["LANG"] == "en_US.UTF-8" and child["QT_QPA_PLATFORMTHEME"] == "gtk3"
    assert child["TMPDIR"] == "/tmp"
    assert "LC_ALL" not in child and "PYTHONDONTWRITEBYTECODE" not in child


def test_ci_context_tool_download_budget_failure_never_downloads(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(diagnostic, "_storage_ready", lambda *a: None)
    def run(command, cwd, root, label, **kwargs):
        calls.append(command)
        return {"child_exit": 1, "output_ok": True}
    monkeypatch.setattr(diagnostic, "_run_private", run)
    with pytest.raises(ValueError, match="package_budget"):
        diagnostic._prepare_symbolizer(tmp_path)
    assert len(calls) == 1 and calls[0][0] == "/usr/bin/apt-cache"


@pytest.mark.parametrize("available", [True, False])
def test_ci_context_synthetic_preflight_proves_only_collection(monkeypatch, tmp_path, available):
    (tmp_path / "binaries.json").write_text("{}")
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *a: None)
    monkeypatch.setattr(diagnostic, "_inspect_core", lambda *a, **k: pytest.fail("symbolizer before workload"))
    monkeypatch.setattr(diagnostic, "_preserve_core_binaries", lambda *a: [{"sha256": "a" * 64}])
    events = []
    def run(command, cwd, root, label, **kwargs):
        events.append(label)
        if label == "compiler":
            (root / "control").write_bytes(b"\x7fELFsynthetic executable fixture")
        if label == "synthetic" and available:
            core = root / "core.123"
            core.write_bytes(b"\x7fELF\x02\x01\x01" + bytes(9) + b"\x04\x00\x3e\x00" + bytes(44))
            core.chmod(0o600)
        return {"pid": 123, "child_exit": -11 if label == "synthetic" else 0,
                "signal": 11 if label == "synthetic" else None, "output_ok": True,
                "timed_out": False, "pytest_counts": []}
    monkeypatch.setattr(diagnostic, "_run_private", run)
    receipt = {}
    if available:
        diagnostic._prove_hosted_capture(tmp_path, receipt)
        assert receipt["capability"] == "collection_proven; symbolization_deferred"
        assert (tmp_path / "core.123").exists()
    else:
        with pytest.raises(ValueError, match="collection_capability_unproven"):
            diagnostic._prove_hosted_capture(tmp_path, receipt)
    assert events == ["success", "compiler", "synthetic"]


def test_ci_context_symbolizer_rejects_host_fallback_object(monkeypatch, tmp_path):
    from types import SimpleNamespace
    fake = SimpleNamespace(objfiles=lambda: [SimpleNamespace(filename="/usr/lib/libc.so.6")])
    monkeypatch.setitem(sys.modules, "gdb", fake)
    script = diagnostic._core_script(tmp_path / "stack.json", tmp_path / "sysroot")
    with pytest.raises(RuntimeError, match="outside_preserved"):
        exec(compile(script.removeprefix("python\n").removesuffix("end\n"), "inert-gdb", "exec"), {})
    assert not (tmp_path / "stack.json").exists()


def test_review_context_never_publishes_mapped_file_manifest(deferred_symbols, monkeypatch):
    root, receipt, _ = deferred_symbols
    emitted = []
    monkeypatch.setattr(diagnostic, "_emit_hosted", emitted.append)
    monkeypatch.setattr(diagnostic, "_preserve_core_binaries", lambda *a:
        [{"module": "SYNTHETIC_PRIVATE_MODULE.so", "sha256": "a" * 64}])
    assert diagnostic._symbolize_after_workload(root, receipt, 139) == 139
    assert "SYNTHETIC_PRIVATE_MODULE" not in repr(emitted)
    assert all("preserved_binary_hashes" not in row for row in emitted)
    assert emitted[-1]["post_workload_native"]["matching_binary_count"] == 1


@pytest.mark.parametrize("interruption", ["cancelled", "post_exit_interrupted"])
def test_review_context_mapping_interrupt_never_prepares_symbolizer(deferred_symbols, monkeypatch, interruption):
    root, receipt, events = deferred_symbols
    original = diagnostic._preserve_core_binaries
    # Reach the real new readelf wrapper for the natural failure only.
    real_preserve = _REAL_PRESERVE_CORE_BINARIES
    def preserve(root, child, executable, inventory):
        return (real_preserve(root, child, executable, inventory) if child["pid"] == 22
                else original(root, child, executable, inventory))
    monkeypatch.setattr(diagnostic, "_preserve_core_binaries", preserve)
    monkeypatch.setattr(diagnostic, "_run_private", lambda *a, **k:
        {"child_exit": -9, "signal": 9, "output_ok": False, interruption: True})
    with pytest.raises(InterruptedError):
        diagnostic._symbolize_after_workload(root, receipt, 139)
    assert "prepare_symbolizer" not in events
    assert not any(isinstance(event, tuple) and event[0] == "symbolize" for event in events)


_REAL_PRESERVE_CORE_BINARIES = diagnostic._preserve_core_binaries


@pytest.mark.parametrize("interruption", ["cancelled", "post_exit_interrupted"])
def test_mapping_interrupt_cleans_private_files_and_retains139(deferred_symbols, monkeypatch, interruption):
    root, pending, events = deferred_symbols
    (root / "admission.json").write_text(json.dumps({"run_id": "500", "phase": diagnostic.PHASE,
        "scaffolding_sha": "a" * 40, "workload_sha": diagnostic.FROZEN_SHA,
        "workload_tree": diagnostic.FROZEN_TREE, "observation_deadline_epoch": diagnostic.time.time() + 2400}))
    for key, value in {"GITHUB_RUN_ID": "500", "GITHUB_SHA": "a" * 40,
                       "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic, "_private_root", lambda: root)
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda *a: None)
    monkeypatch.setattr(diagnostic.signal, "alarm", lambda *a: None)
    monkeypatch.setattr(diagnostic, "_prepare_hosted_capture", lambda *a: {})
    monkeypatch.setattr(diagnostic, "_validate_runtime", lambda *a: None)
    monkeypatch.setattr(diagnostic, "_prove_hosted_capture", lambda *a: None)
    def acquire(root, workload, receipt):
        receipt.update(pending, acquisition_exit=139)
        return 139
    original = diagnostic._preserve_core_binaries
    def preserve(root, child, executable, inventory):
        return (_REAL_PRESERVE_CORE_BINARIES(root, child, executable, inventory) if child["pid"] == 22
                else original(root, child, executable, inventory))
    monkeypatch.setattr(diagnostic, "_preserve_core_binaries", preserve)
    monkeypatch.setattr(diagnostic, "_run_private", lambda *a, **k:
        {"child_exit": -9, "signal": 9, "output_ok": False, interruption: True})
    monkeypatch.setattr(diagnostic, "_acquire_sequence", acquire)
    emitted = []
    monkeypatch.setattr(diagnostic, "_emit_hosted", emitted.append)
    assert diagnostic.hosted_observe() == 139
    assert not root.exists() and emitted[-1]["cleanup"]["ok"]
    assert emitted[-1]["diagnostic_error"] == "InterruptedError"
    assert "prepare_symbolizer" not in events


def test_review_context_inventoried_elf_replaced_by_data_is_not_skipped(tmp_path):
    changed, intact = tmp_path / "changed.so", tmp_path / "intact.so"
    for path in (changed, intact):
        path.write_bytes(b"\x7fELFbefore")
    inventory = {str(path): diagnostic._file_identity(path) for path in (changed, intact)}
    changed.write_bytes(b"plain bytes after capture")
    with pytest.raises(ValueError):
        diagnostic._preserve_mapped_files(tmp_path, [str(changed), str(intact)], inventory)


def test_postmortem_keeps_child_signal_when_capture_fails():
    assert diagnostic._postmortem_exit(-11, False) == 139
    assert diagnostic._postmortem_exit(0, False) == 70


def test_postmortem_environment_excludes_runner_credentials(tmp_path):
    environment = diagnostic._child_environment(tmp_path)
    assert environment["QT_QPA_PLATFORM"] == "offscreen"
    assert environment["PYTHONPATH"] == "src:."
    assert not any("TOKEN" in key or key.startswith("GITHUB") for key in environment)


def test_safe_hosted_output_cannot_inject_workflow_commands():
    encoded = diagnostic._safe_json({"frames": ["\n::error::injected\x1b[31m"]})
    assert len(encoded.splitlines()) == 1
    assert "\x1b" not in encoded
    assert json.loads(encoded)["frames"]


def test_hosted_admission_rejects_missing_identity():
    with pytest.raises(ValueError):
        diagnostic._validate_admission({}, {}, {}, [], "", "")


@pytest.fixture
def admission():
    sha = "a" * 40
    event = {"inputs": {"run_industrial_postmortem": "1", "qt998_scaffolding_sha": sha,
                        "qt998_workload_sha": diagnostic.FROZEN_SHA, "qt998_phase": diagnostic.PHASE}}
    environment = {
        "GITHUB_REPOSITORY": "hexafe/metroliza", "GITHUB_REPOSITORY_ID": "478225616",
        "GITHUB_ACTOR": "hexafe", "GITHUB_ACTOR_ID": "100516322",
        "GITHUB_TRIGGERING_ACTOR": "hexafe", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/" + diagnostic.BRANCH, "GITHUB_REF_TYPE": "branch",
        "GITHUB_RUN_ATTEMPT": "1", "QT998_RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "GITHUB_RUN_ID": "500",
        "GITHUB_SHA": sha, "QT998_WORKFLOW_SHA": sha,
    }
    repository = {"id": 478225616, "private": False, "visibility": "public",
                  "full_name": "hexafe/metroliza"}
    current = {"id": 500, "head_sha": sha, "run_attempt": 1, "event": "workflow_dispatch",
               "head_branch": diagnostic.BRANCH, "created_at": diagnostic.APPROVAL_TIME}
    return [event, environment, repository, [current], sha, diagnostic.FROZEN_TREE]


def test_correct_first_owner_dispatch_is_admitted(admission):
    receipt = diagnostic._validate_admission(*admission)
    assert receipt == {"phase": diagnostic.PHASE, "scaffolding_sha": "a" * 40, "workload_sha": diagnostic.FROZEN_SHA,
                       "workload_tree": diagnostic.FROZEN_TREE, "run_id": "500", "run_attempt": 1}


@pytest.mark.parametrize(("key", "value"), [
    ("GITHUB_REPOSITORY", "fork/metroliza"), ("GITHUB_REPOSITORY_ID", "1"),
    ("GITHUB_ACTOR", "someone"), ("GITHUB_ACTOR_ID", "1"),
    ("GITHUB_TRIGGERING_ACTOR", "someone"), ("GITHUB_EVENT_NAME", "push"),
    ("GITHUB_REF", "refs/heads/develop"), ("GITHUB_REF_TYPE", "tag"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("QT998_RUNNER_ENVIRONMENT", "self-hosted"),
    ("RUNNER_OS", "Windows"), ("RUNNER_ARCH", "ARM64"),
    ("GITHUB_SHA", "b" * 40), ("QT998_WORKFLOW_SHA", "b" * 40),
    ("GITHUB_RUN_ID", ""), ("GITHUB_RUN_ID", "500; echo injected"),
])
def test_context_mutation_is_rejected(admission, key, value):
    admission[1][key] = value
    with pytest.raises(ValueError):
        diagnostic._validate_admission(*admission)


@pytest.mark.parametrize(("key", "value"), [
    ("run_industrial_postmortem", "0"), ("qt998_scaffolding_sha", ""),
    ("qt998_scaffolding_sha", "$(echo unsafe)"), ("qt998_workload_sha", "b" * 40),
    ("run_packaging_smoke", "1"), ("run_windows_startup_benchmark", "1"),
])
def test_input_mutation_is_rejected(admission, key, value):
    admission[0]["inputs"][key] = value
    with pytest.raises(ValueError):
        diagnostic._validate_admission(*admission)


@pytest.mark.parametrize(("key", "value"), [
    ("id", 1), ("private", True), ("private", "false"),
    ("visibility", "private"), ("full_name", "fork/metroliza"),
])
def test_cost_prerequisite_change_is_rejected(admission, key, value):
    admission[2][key] = value
    with pytest.raises(ValueError):
        diagnostic._validate_admission(*admission)


def test_wrong_workload_tree_and_unchecked_scaffolding_are_rejected(admission):
    admission[5] = "0" * 40
    with pytest.raises(ValueError):
        diagnostic._validate_admission(*admission)
    admission[5] = diagnostic.FROZEN_TREE
    admission[4] = "0" * 40
    with pytest.raises(ValueError):
        diagnostic._validate_admission(*admission)


def test_prior_attempt_spends_whole_approval_even_after_changed_sha_or_setup_failure(admission):
    admission[3] += [{"event": "workflow_dispatch", "head_branch": diagnostic.BRANCH,
                     "created_at": diagnostic.APPROVAL_TIME, "id": 499,
                     "head_sha": "b" * 40, "conclusion": "failure"}]
    with pytest.raises(ValueError, match="approval_already_spent"):
        diagnostic._validate_admission(*admission)


def test_first_run_is_not_rejected_for_its_own_record_or_later_queued_duplicate(admission):
    admission[3] += [{"event": "workflow_dispatch", "head_branch": diagnostic.BRANCH,
                      "created_at": diagnostic.APPROVAL_TIME, "id": 501}]
    assert diagnostic._validate_admission(*admission)["run_id"] == "500"


def test_missing_current_run_in_api_history_fails_closed(admission):
    admission[3] = []
    with pytest.raises(ValueError, match="current_run_not_verified_in_history"):
        diagnostic._validate_admission(*admission)


def test_parent_secrets_and_theme_are_not_inherited(monkeypatch, tmp_path):
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "QT_QPA_PLATFORMTHEME",
                "QT_STYLE_OVERRIDE", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONSTARTUP", "PYTHONPATH"):
        monkeypatch.setenv(key, "SYNTHETIC_SECRET")
    environment = diagnostic._child_environment(tmp_path)
    assert "SYNTHETIC_SECRET" not in repr(environment)
    assert environment["DEBUGINFOD_URLS"] == ""
    assert environment["LD_LIBRARY_PATH"] == str(Path(sys.base_prefix) / "lib")


def test_sanitizer_controls_are_json_safe_without_losing_escape_receipt():
    raw = "password=qt998-test-secret\n::error::fake\x1b[31m /home/builduser/private.c"
    encoded = diagnostic._safe_json({"message": diagnostic._sanitize(raw)})
    assert "qt998-test-secret" not in encoded
    assert "/home/builduser" not in encoded
    assert len(encoded.splitlines()) == 1
    assert "\x1b" not in encoded
    with pytest.raises(ValueError, match="safe_output_limit"):
        diagnostic._safe_json({"oversize": "x" * 60000})


def test_missing_and_unsafe_core_never_start_debugger(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(diagnostic, "_run_private", lambda *args: calls.append(args))
    child = {"pid": 123, "signal": 11}
    assert diagnostic._inspect_core(tmp_path, child, sys.executable)["capture"] == "missing_core"
    outside = tmp_path / "outside"
    outside.write_bytes(b"synthetic, not a core")
    (tmp_path / "core.123").symlink_to(outside)
    assert not diagnostic._inspect_core(tmp_path, child, sys.executable)["ok"]
    assert outside.read_bytes() == b"synthetic, not a core"
    assert not (tmp_path / "core.123").is_symlink()
    assert not calls


def test_core_cleanup_runs_when_symbolizer_fails(monkeypatch, tmp_path):
    core = tmp_path / "core.123"
    core.write_bytes(b"\x7fELFsynthetic test marker, not executable core data")
    core.chmod(0o600)
    def unavailable(*args):
        raise OSError("synthetic debugger unavailable")
    monkeypatch.setattr(diagnostic, "_run_private", unavailable)
    with pytest.raises(OSError):
        diagnostic._inspect_core(tmp_path, {"pid": 123, "signal": 11}, sys.executable)
    assert not core.exists()
    assert not (tmp_path / "postmortem.gdb").exists()


def test_cleanup_restores_route_before_deleting_raw_files(monkeypatch, tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    (root / "core-route.json").write_text(json.dumps({"original": "old-route"}))
    (root / "raw").write_text("synthetic")
    calls = []
    def restore(value):
        assert (root / "raw").exists()
        calls.append(value)
    monkeypatch.setattr(diagnostic, "_set_core_pattern", restore)
    assert diagnostic._cleanup_hosted(root) == {
        "core_route_restored": True, "private_storage_removed": True, "ok": True}
    assert calls == ["old-route"]
    assert not root.exists()
    # An always step cannot newly assert restoration after the original state is gone.
    assert diagnostic._cleanup_hosted(root)["core_route_restored"] is None


def test_failed_route_restoration_still_removes_raw_data_and_reports_failure(monkeypatch, tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    (root / "core-route.json").write_text(json.dumps({"original": "old-route"}))
    (root / "raw").write_text("synthetic")
    def failed(value):
        raise OSError("synthetic restore failure")
    monkeypatch.setattr(diagnostic, "_set_core_pattern", failed)
    receipt = diagnostic._cleanup_hosted(root)
    assert receipt == {"core_route_restored": False, "private_storage_removed": True, "ok": False}
    assert not root.exists()


def test_debugger_settings_precede_loading_core_and_no_live_attachment(monkeypatch, tmp_path):
    core = tmp_path / "core.123"
    core.write_bytes(b"\x7fELFsynthetic test marker")
    core.chmod(0o600)
    def debugger(command, cwd, root, label):
        assert command.index("set auto-load off") < command.index("-se")
        assert command.index("set debuginfod enabled off") < command.index("-c")
        assert "--args" not in command and "attach" not in command
        (root / "stack.json").write_text(json.dumps({"signal": 11, "pid": 123,
            "fault_thread": 1, "thread_count": 1, "truncated": False,
            "threads": [{"thread": 1, "frames": [{"function": "safe_function"}]}]}))
        return {"child_exit": 0, "timed_out": False, "output_truncated": False, "output_ok": True}
    monkeypatch.setattr(diagnostic, "_run_private", debugger)
    result = diagnostic._inspect_core(tmp_path, {"pid": 123, "signal": 11}, sys.executable)
    assert result["ok"] and result["native"]["fault_thread"] == 1
    assert not core.exists()


def test_original_workload_command_is_fixed():
    assert diagnostic.PYTEST_ARGUMENTS == [
        "tests/test_industrial_analytics_dialog.py", "-q", "--cov=src/metroliza",
        "--cov=modules", "--cov=scripts", "--cov-append", "--cov-report=",
        "--cov-fail-under=0",
    ]


@pytest.mark.parametrize("failed_operation", ["stat", "read", "unlink"])
def test_post_exit_output_failure_preserves_native_signal(monkeypatch, tmp_path, failed_operation):
    class TerminatedChild:
        pid = 123
        returncode = -11
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def wait(self, **kwargs):
            return self.returncode
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: TerminatedChild())
    method = {"stat": "stat", "read": "open", "unlink": "unlink"}[failed_operation]
    original = getattr(Path, method)
    def fail_after_exit(path, *args, **kwargs):
        if path.name == "industrial.raw" and (method != "open" or args == ("rb",)):
            raise OSError("synthetic post-exit file failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, method, fail_after_exit)
    receipt = diagnostic._run_private(["unused"], tmp_path, tmp_path, "industrial")
    assert receipt["child_exit"] == -11 and receipt["signal"] == 11
    assert receipt["output_capture_error"] == "OSError"
    assert not receipt["output_ok"]
    assert diagnostic._postmortem_exit(receipt["child_exit"], receipt["output_ok"]) == 139


@pytest.mark.parametrize("reason", ["timeout", "cancellation"])
def test_interrupted_child_is_reaped_before_output_processing(monkeypatch, tmp_path, reason):
    events = []
    class InterruptedChild:
        pid = 123
        returncode = None
        def __enter__(self):
            return self
        def __exit__(self, *args):
            assert self.returncode == -9
        def wait(self, **kwargs):
            if kwargs:
                if reason == "timeout":
                    raise subprocess.TimeoutExpired("unused", 120)
                raise InterruptedError("synthetic cancellation")
            events.append("reaped")
            self.returncode = -9
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: InterruptedChild())
    monkeypatch.setattr(diagnostic.os, "killpg", lambda pid, sig: events.append((pid, sig)))
    receipt = diagnostic._run_private(["unused"], tmp_path, tmp_path, "industrial")
    assert events == [(123, diagnostic.signal.SIGKILL), "reaped"]
    assert receipt["child_exit"] == -9
    assert receipt["timed_out"] == (reason == "timeout")
    assert receipt["cancelled"] == (reason == "cancellation")


def test_hosted_workflow_is_default_off_standard_guest_without_cache_or_artifact():
    import yaml

    workflow = yaml.load(Path(".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["run_industrial_postmortem"]["default"] == "0"
    assert inputs["qt998_scaffolding_sha"]["default"] == ""
    assert inputs["qt998_workload_sha"]["default"] == ""
    job = workflow["jobs"]["industrial-postmortem"]
    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert "github.run_id" in workflow["concurrency"]["group"]
    assert "format('ci-{0}-{1}', github.workflow, github.ref)" in workflow["concurrency"]["group"]
    assert job["concurrency"] == {"group": "qt998-postmortem-job-5624613947",
                                   "cancel-in-progress": "false"}
    assert job["concurrency"]["group"] not in workflow["concurrency"]["group"]
    # GitHub evaluates job env before assigning a runner; runner context is step-only.
    assert "runner." not in repr(job.get("env", {}))
    assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == "45"
    assert "workflow_dispatch" in job["if"] and "== '1'" in job["if"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    for step in job["steps"]:
        action = step.get("uses", "")
        assert "upload-artifact" not in action and "actions/cache" not in action
        assert "${{" not in step.get("run", "")
        if step.get("run", "").startswith("python scripts/ci_industrial_qt_diagnostics.py --hosted-"):
            assert step["env"]["QT998_RUNNER_ENVIRONMENT"] == "${{ runner.environment }}"
        if "setup-python" in action:
            assert step["with"]["cache"] == ""
            assert step["with"]["python-version"] == "3.11"
        if "actions/checkout" in action:
            assert step["with"]["persist-credentials"] == "false"
    workload_checkout = next(step for step in job["steps"]
                             if step.get("with", {}).get("path") == "frozen-workload")
    assert workload_checkout["with"]["ref"] == diagnostic.FROZEN_SHA
    assert job["steps"][-1]["if"] == "always()"
    assert job["steps"][-1]["run"].endswith("--hosted-cleanup")


@pytest.mark.parametrize("mode", ["--hosted-admit", "--hosted-observe", "--hosted-cleanup"])
def test_hosted_modes_refuse_local_host_before_any_side_effect(monkeypatch, mode):
    monkeypatch.delenv("QT998_RUNNER_ENVIRONMENT", raising=False)
    receipts = []
    monkeypatch.setattr(diagnostic, "_emit_hosted", receipts.append)
    def forbidden(*args):
        pytest.fail("local hosted mode crossed its environment gate")
    monkeypatch.setattr(diagnostic, "_github_json", forbidden)
    monkeypatch.setattr(diagnostic, "_private_root", forbidden)
    monkeypatch.setattr(diagnostic, "_set_core_pattern", forbidden)
    assert diagnostic.hosted_main(mode) == 70
    assert receipts[0]["hosted_diagnostic_error"] == "ValueError"


@pytest.mark.parametrize(("failure_stage", "expected_exit"), [("preparation", 70), ("capture", 139)])
def test_hosted_stage_failure_cleans_up_and_preserves_observed_signal(
    monkeypatch, tmp_path, failure_stage, expected_exit,
):
    admission = {"run_id": "500", "scaffolding_sha": "a" * 40, "phase": diagnostic.PHASE,
                 "workload_sha": diagnostic.FROZEN_SHA, "workload_tree": diagnostic.FROZEN_TREE,
                 "observation_deadline_epoch": diagnostic.time.time() + 1320}
    (tmp_path / "admission.json").write_text(json.dumps(admission))
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(diagnostic, "_private_root", lambda: tmp_path)
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda *args: None)
    monkeypatch.setattr(diagnostic.signal, "alarm", lambda *args: 0)
    events, receipts = [], []

    def prepare(*args):
        events.append("preparation")
        if failure_stage == "preparation":
            raise OSError("synthetic private preparation failure")
        return {}

    def prove(root, receipt):
        receipt["capability"] = "proven_by_synthetic_control_only"

    def run_private(command, cwd, root, label, **kwargs):
        events.append(label)
        return {"child_exit": -11, "signal": 11, "pid": 123, "output_ok": True}

    def inspect_core(root, child, executable):
        raise OSError("synthetic private capture failure")

    monkeypatch.setattr(diagnostic, "_prove_hosted_capture", prove)
    monkeypatch.setattr(diagnostic, "_verify_probe", lambda: "a" * 64)
    monkeypatch.setattr(diagnostic, "_verify_workload", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *args: None)

    def cleanup(root):
        events.append("cleanup")
        return {"ok": True}

    monkeypatch.setattr(diagnostic, "_prepare_hosted_capture", prepare)
    monkeypatch.setattr(diagnostic, "_validate_runtime", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_run_private", run_private)
    monkeypatch.setattr(diagnostic, "_inspect_core", inspect_core)
    monkeypatch.setattr(diagnostic, "_collect_core", lambda root, child: inspect_core(root, child, "unused"))
    monkeypatch.setattr(diagnostic, "_cleanup_hosted", cleanup)
    monkeypatch.setattr(diagnostic, "_emit_hosted", receipts.append)
    assert diagnostic.hosted_observe() == expected_exit
    assert events[-1] == "cleanup" and events.count("cleanup") == 1
    if failure_stage == "preparation":
        assert events == ["preparation", "cleanup"]
        assert receipts[-1]["observation"] == "not_started"
        assert receipts[-1]["diagnostic_error"] == "OSError"
    else:
        assert events.count("coverage_erase") == 1
        assert receipts[-1]["stages"][0]["child_exit"] == -11
        assert receipts[-1]["stages"][0]["diagnostic_error"] == "OSError"


def test_new_phase_has_fixed_failed_content_and_rejects_spent_phase(admission):
    assert diagnostic.FROZEN_SHA == "b451e7af3153da89c16d09f5b26a7f4799a82da3"
    assert diagnostic.FROZEN_TREE == "1936b583b3ba61b9466d61599b563aabdb3556e7"
    admission[0]["inputs"]["qt998_phase"] = "5604177526"
    with pytest.raises(ValueError, match="phase"):
        diagnostic._validate_admission(*admission)


@pytest.mark.parametrize("timeout", [60, 120, 1200])
def test_private_child_uses_declared_stage_timeout(monkeypatch, tmp_path, timeout):
    waits = []
    class Child:
        pid, returncode = 123, 0
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def wait(self, **kwargs):
            waits.append(kwargs)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: Child())
    diagnostic._run_private(["unused"], tmp_path, tmp_path, "stage", timeout=timeout)
    assert waits == [{"timeout": timeout}]


@pytest.fixture
def acquisition(monkeypatch, tmp_path):
    calls, emitted = [], []
    outcomes = {}
    def run(command, cwd, root, label, *, timeout=120):
        assert cwd == tmp_path / "workload" and root == tmp_path
        calls.append((label, command, timeout))
        counts = {"coverage_erase": [], "main": ["3903 passed", "62 skipped"],
                  "dashboard": ["24 passed"]}.get(label, ["42 passed"])
        return {"pid": len(calls), "child_exit": 0, "signal": None,
                "timed_out": False, "cancelled": False, "output_ok": True,
                "output_truncated": False, "pytest_counts": counts,
                "pytest_summary_complete": bool(counts), **outcomes.get(label, {})}
    monkeypatch.setattr(diagnostic, "_run_private", run)
    monkeypatch.setattr(diagnostic, "_verify_workload", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *args: None, raising=False)
    monkeypatch.setattr(diagnostic, "_emit_hosted", emitted.append)
    return tmp_path, calls, outcomes, emitted


def test_sequence_runs_prefix_once_then_one_complete_fresh_industrial_process(acquisition):
    root, calls, _, emitted = acquisition
    receipt = {}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 0
    assert [x[0] for x in calls] == ["coverage_erase", "main", "dashboard", "industrial_1"]
    assert calls[0][1] == [sys.executable, "-m", "coverage", "erase"]
    assert calls[1][1] == [sys.executable, "-m", "pytest", "tests", "-q",
                          "--cov=src/metroliza", "--cov=modules", "--cov=scripts",
                          "--cov-report=", "--cov-fail-under=0"]
    assert calls[1][2] == 1200 and calls[2][2] == 120
    assert calls[2][1][3] == "tests/test_dashboard_visual_options_dialog.py"
    for _, command, timeout in calls[3:]:
        assert command == [sys.executable, "-m", "pytest", *diagnostic.PYTEST_ARGUMENTS]
        assert 0 < timeout <= 120
    assert receipt["observation"] == "NON-REPRODUCTION"
    assert len(receipt["stages"]) == len(emitted) == 4


@pytest.mark.parametrize("stage", ["coverage_erase", "main", "dashboard",
                                  "industrial_1"])
@pytest.mark.parametrize("fault", ["signal", "counts", "truncated", "timeout", "cancelled"])
def test_first_failed_or_incomplete_stage_stops_all_further_work(acquisition, monkeypatch, stage, fault):
    root, calls, outcomes, _ = acquisition
    outcomes[stage] = {
        "signal": {"child_exit": -11, "signal": 11},
        "counts": {"pytest_counts": ["1 passed"], "pytest_summary_complete": False},
        "truncated": {"output_truncated": True},
        "timeout": {"child_exit": -9, "signal": 9, "timed_out": True},
        "cancelled": {"child_exit": -9, "signal": 9, "cancelled": True},
    }[fault]
    monkeypatch.setattr(diagnostic, "_inspect_core", lambda *args: {"ok": False, "capture": "missing_core"})
    receipt = {}
    code = diagnostic._acquire_sequence(root, root / "workload", receipt)
    assert code == {"signal": 139, "timeout": 137, "cancelled": 137}.get(fault, 70)
    assert calls[-1][0] == stage
    assert len(calls) == len(receipt["stages"])
    assert receipt["observation"] != "NON-REPRODUCTION"
    if fault in {"timeout", "cancelled"}:
        assert receipt["observation"] == "INCOMPLETE_WORKLOAD"


def test_capture_exception_does_not_hide_first_workload_signal(acquisition, monkeypatch):
    root, calls, outcomes, _ = acquisition
    outcomes["industrial_1"] = {"child_exit": -11, "signal": 11}
    def broken(*args):
        raise OSError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, "_inspect_core", broken)
    receipt = {}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 139
    assert calls[-1][0] == "industrial_1"
    assert "SYNTHETIC_SECRET" not in repr(receipt)
    assert receipt["stages"][-1]["child_exit"] == -11


def test_aggregate_expiry_never_starts_another_industrial_sample(acquisition, monkeypatch):
    root, calls, _, _ = acquisition
    clock = iter([0.0, 0.0, 0.0, 601.0])
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: next(clock))
    receipt = {}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 70
    assert [x[0] for x in calls] == ["coverage_erase", "main", "dashboard", "industrial_1"]
    assert receipt["observation"] == "INCOMPLETE_WORKLOAD"


def test_spent_old_phase_does_not_consume_the_explicit_new_allocation(admission):
    admission[3].append({"event": "workflow_dispatch", "head_branch": diagnostic.BRANCH,
                         "created_at": "2026-09-09T15:59:03Z", "id": 499})
    assert diagnostic._validate_admission(*admission)["phase"] == "5624613947"
    admission[0]["inputs"].pop("qt998_phase")
    with pytest.raises(ValueError, match="phase"):
        diagnostic._validate_admission(*admission)


@pytest.mark.parametrize("text", [
    "running 42 passed cases, no terminal receipt\n",
    "42 passed in ",
    "42 passed in 3.44s\n42 passed in 3.45s\n",
    "41 passed, 1 skipped in 3.44s\n",
    "42 passed, 1 xfailed in 3.44s\n",
])
def test_incomplete_or_unexpected_terminal_summary_cannot_qualify(text):
    child = {"child_exit": 0, "output_ok": True, **diagnostic._pytest_summary(text)}
    assert not diagnostic._complete_stage(child, ["42 passed"])


def test_real_main_and_industrial_terminal_summaries_have_controlled_counts():
    main = diagnostic._pytest_summary(
        "...\n==== 4183 passed, 62 skipped, 8 warnings, 119 subtests passed in 698.91s (0:11:38) ====\n")
    assert main == {"pytest_counts": ["4183 passed", "62 skipped"],
                    "pytest_summary_complete": True, "pytest_warning_counts": ["8 warnings"],
                    "pytest_subtest_counts": ["119 subtests passed"]}
    assert diagnostic._pytest_summary("42 passed in 3.44s\n")["pytest_counts"] == ["42 passed"]


@pytest.mark.parametrize("guard", ["_verify_workload", "_capture_ready"])
@pytest.mark.parametrize("failure_call", [1, 7, 8])
def test_source_or_capture_drift_stops_before_further_sampling(acquisition, monkeypatch, guard, failure_call):
    root, calls, _, _ = acquisition
    count = 0
    def check(*args):
        nonlocal count
        count += 1
        if count == failure_call:
            raise ValueError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, guard, check)
    receipt = {}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 70
    assert len(calls) == {1: 0, 7: 3, 8: 4}[failure_call]
    assert "SYNTHETIC_SECRET" not in repr(receipt)


@pytest.mark.parametrize("key", ["python", *diagnostic.RUNTIME_PACKAGES])
def test_material_runtime_mismatch_fails_closed(key):
    runtime = {"python": "3.11.16", "packages": dict(diagnostic.RUNTIME_PACKAGES)}
    diagnostic._validate_runtime(runtime)
    if key == "python":
        runtime[key] = "3.12.0"
    else:
        runtime["packages"][key] = "0.0"
    with pytest.raises(ValueError, match="material_runtime_mismatch"):
        diagnostic._validate_runtime(runtime)


@pytest.mark.parametrize("code", [0, 1, 139])
def test_publication_failure_preserves_nonzero_workload_exit(monkeypatch, capsys, code):
    def broken(*args):
        raise OSError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, "_emit_hosted", broken)
    assert diagnostic._emit_preserving_exit({}, code) == (code or 70)
    output = capsys.readouterr().out
    assert "SYNTHETIC_SECRET" not in output
    assert json.loads(output.removeprefix("QT998_JSON "))["launcher_exit"] == (code or 70)


@pytest.mark.parametrize("failure", ["runtime", "preflight", "cleanup", "budget", "after_native"])
def test_no_workload_after_failed_preflight_and_cleanup_retains139(monkeypatch, tmp_path, failure):
    admission = {"run_id": "500", "scaffolding_sha": "a" * 40, "phase": diagnostic.PHASE,
                 "workload_sha": diagnostic.FROZEN_SHA, "workload_tree": diagnostic.FROZEN_TREE,
                 "observation_deadline_epoch": diagnostic.time.time() + 1320}
    if failure == "budget":
        admission["observation_deadline_epoch"] = diagnostic.time.time() - 1
    (tmp_path / "admission.json").write_text(json.dumps(admission))
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(diagnostic, "_private_root", lambda: tmp_path)
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda *args: None)
    alarms = []
    monkeypatch.setattr(diagnostic.signal, "alarm", alarms.append)
    events, receipts = [], []
    monkeypatch.setattr(diagnostic, "_prepare_hosted_capture", lambda *args: {})
    def stage(name):
        events.append(name)
        if name == failure:
            raise OSError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, "_validate_runtime", lambda *args: stage("runtime"))
    monkeypatch.setattr(diagnostic, "_prove_hosted_capture", lambda *args: stage("preflight"))
    def acquire(root, workload, receipt):
        events.append("workload")
        receipt["acquisition_exit"] = 139
        if failure == "after_native":
            raise InterruptedError("SYNTHETIC_SECRET")
        return 139
    monkeypatch.setattr(diagnostic, "_acquire_sequence", acquire)
    monkeypatch.setattr(diagnostic, "_cleanup_hosted", lambda *args: stage("cleanup") or {"ok": True})
    monkeypatch.setattr(diagnostic, "_emit_hosted", receipts.append)
    assert diagnostic.hosted_observe() == (139 if failure in ("cleanup", "after_native") else 70)
    assert ("workload" in events) == (failure in ("cleanup", "after_native"))
    assert events[-1] == "cleanup"
    assert "SYNTHETIC_SECRET" not in repr(receipts)
    assert alarms[-1] == 0
    if failure == "budget":
        assert events == ["cleanup"] and alarms == [0]
        assert receipts[-1]["job_budget_expired"]
    else:
        assert 0 < alarms[0] <= 1320


def test_fault_first_extractor_bounds_realistic_multithreaded_unwinding(monkeypatch, tmp_path):
    from types import SimpleNamespace

    class Frame:
        def __init__(self, number=0):
            self.number = number
        def name(self):
            return "known_symbol" if self.number else None
        def pc(self):
            return 1
        def older(self):
            return Frame(self.number + 1)
    class Thread:
        def __init__(self, number):
            self.num = number
        def switch(self):
            pass
    inferior = SimpleNamespace(pid=123, threads=lambda: [Thread(n) for n in range(1, 11)])
    fake = SimpleNamespace(selected_thread=lambda: Thread(9), selected_inferior=lambda: inferior,
                           parse_and_eval=lambda _: 11, newest_frame=Frame,
                           solib_name=lambda _: "/synthetic/private/libQt6Core.so.6", error=RuntimeError)
    monkeypatch.setitem(sys.modules, "gdb", fake)
    path = tmp_path / "safe.json"
    script = diagnostic._core_script(path)
    exec(compile(script.removeprefix("python\n").removesuffix("end\n"), "synthetic-gdb", "exec"), {})
    native = json.loads(path.read_text())
    assert native["fault_thread"] == 9 and native["threads"][0]["thread"] == 9
    assert native["thread_count"] == 10 and len(native["threads"]) == 8
    assert native["truncated"] and all(t["frames_truncated"] for t in native["threads"])
    assert [len(t["frames"]) for t in native["threads"]] == [64] + [16] * 7
    assert "/synthetic/private" not in repr(native)
    assert native["threads"][0]["frames"][0]["function"] == "??"


@pytest.mark.parametrize("label", ["industrial_10", "async_reference"])
@pytest.mark.parametrize("function_length", [140, 144, 145])
@pytest.mark.parametrize("module_length", [80, 81])
def test_complete_native_stage_publication_preserves_size_reserve(
        monkeypatch, tmp_path, capsys, function_length, module_length, label):
    # Exercise the real sanitizer and full publication, including false flags at
    # exact caps, stage metadata and all176 frames. No native process is launched.
    native = {"fault_thread": 1, "pid": 4194304, "signal": 11, "thread_count": 10,
              "truncated": True, "threads": [
                  {"thread": index + 1, "frames_truncated": True, "unwind_error": False,
                   "frames": [{"function": "x" * function_length,
                               "module": "m" * module_length}
                              for _ in range(count)]}
                  for index, count in enumerate([64] + [16] * 7)]}
    def run(command, cwd, root, label, **kwargs):
        if label == "debugger":
            (root / "stack.json").write_text(json.dumps(native))
            return {"child_exit": 0, "timed_out": False, "output_ok": True}
        core = root / "core.4194304"
        core.write_bytes(b"\x7fELFsynthetic marker only")
        core.chmod(0o600)
        return {"child_exit": -11, "signal": 11, "pid": 4194304, "timed_out": False,
                "cancelled": False, "output_ok": True, "elapsed_seconds": 119.123456,
                "output_bytes": 8388608, "output_truncated": False, "pytest_counts": [],
                "pytest_summary_complete": False, "pytest_warning_counts": [],
                "pytest_subtest_counts": [],
                **({"python_context": {"status": "partial", "complete": False,
                    "threads": [{"ordinal": i + 1, "current": i == 0, "garbage_collecting": False,
                        "frames": [{"path": "tests/test_industrial_analytics_dialog.py", "line": 72,
                                    "function": "_wait_for_tabular_load"}] * 12,
                        "omitted_frames": 0, "frames_truncated": False} for i in range(8)],
                    "omitted_frames": 1, "omitted_threads": 0, "log_truncated": False}}
                   if label == "industrial_10" else {}),
                **(diagnostic._probe_summary(
                    _probe_markers("async_reference", 199, terminal=False)
                    + "QT998_PROBE async_reference 200 cycle_start\n"
                    + "QT998_PROBE async_reference 200 parent_constructed\n", "async_reference")
                    if label == "async_reference" else {})}
    monkeypatch.setattr(diagnostic, "_run_private", run)
    monkeypatch.setattr(diagnostic, "_verify_probe", lambda: "a" * 64)
    monkeypatch.setattr(diagnostic, "_verify_workload", lambda *_: None)
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *_: None)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert diagnostic._acquisition_stage(
        tmp_path, tmp_path, {"stages": [], "identity": {"run_id": "34407068328",
                              "scaffolding_sha": "a" * 40}}, label,
        ([sys.executable, "-m", "coverage", "run", "--append", "--source=src/metroliza,modules,scripts",
          str(diagnostic._probe_file()), "--variant", label, "--cycles", "200"]
         if label == "async_reference" else [sys.executable, "-m", "pytest", *diagnostic.PYTEST_ARGUMENTS]),
        [] if label == "async_reference" else ["42 passed"], 180 if label == "async_reference" else 120,
    ) == 139
    outputs = [line.removeprefix("QT998_JSON ") for line in capsys.readouterr().out.splitlines()]
    assert len(outputs) == (2 if label == "industrial_10" else 1)
    assert len(outputs[0].encode("utf-8")) < 59000
    stage = json.loads(outputs[0])["acquisition_stage"]
    if label == "industrial_10":
        assert len(outputs[1].encode("ascii")) <= 16384
        python = json.loads(outputs[1])["python_fault_context"]
        assert python["pid"] == stage["pid"] == 4194304
        assert python["signal"] == stage["signal"] == 11
        assert sum(len(t["frames"]) for t in python["context"]["threads"]) == 96
    assert stage["capture"] == "postmortem_stack" and stage["source_unchanged"]
    assert stage["launcher_exit"] == 139 and not stage["complete"]
    for thread in stage["native"]["threads"]:
        for frame in thread["frames"]:
            assert frame["name_truncated"] == (function_length > len(frame["function"]))
            assert frame["module_truncated"] == (module_length > len(frame["module"]))


def test_expiry_during_guards_prevents_launch_with_stale_timeout(acquisition, monkeypatch):
    root, calls, _, _ = acquisition
    now = [0.0]
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: now[0])
    checks = [0]
    def guard(*args):
        checks[0] += 1
        if checks[0] == 8:
            now[0] = 599.0
        elif checks[0] == 9:
            now[0] = 601.0
    monkeypatch.setattr(diagnostic, "_capture_ready", guard)
    receipt = {}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 70
    assert calls[-1][0] == "industrial_1"
    assert len(calls) == 4


@pytest.mark.parametrize("length", [80, 81])
def test_module_identifier_truncation_is_explicit(monkeypatch, tmp_path, length):
    core = tmp_path / "core.123"
    core.write_bytes(b"\x7fELFsynthetic marker only")
    core.chmod(0o600)
    def debugger(command, cwd, root, label):
        (root / "stack.json").write_text(json.dumps({"signal": 11, "pid": 123,
            "fault_thread": 1, "thread_count": 1, "truncated": False,
            "threads": [{"thread": 1, "frames": [{"function": "safe", "module": "m" * length}]}]}))
        return {"child_exit": 0, "timed_out": False, "output_truncated": False, "output_ok": True}
    monkeypatch.setattr(diagnostic, "_run_private", debugger)
    capture = diagnostic._inspect_core(tmp_path, {"pid": 123, "signal": 11}, sys.executable)
    frame = capture["native"]["threads"][0]["frames"][0]
    assert frame["module"] == "m" * 80
    assert frame["module_truncated"] == (length > 80)


@pytest.mark.parametrize("spent", ["5604177526", "5608262552", "5614139597", "5618809967"])
def test_reduction_admission_never_revives_either_spent_allocation(admission, spent):
    assert diagnostic.PHASE == "5624613947"
    admission[0]["inputs"]["qt998_phase"] = spent
    with pytest.raises(ValueError, match="phase"):
        diagnostic._validate_admission(*admission)


@pytest.fixture
def reduction(monkeypatch, tmp_path):
    calls, outcomes = [], {}
    def stage(root, workload, receipt, label, command, expected, timeout, deadline=None):
        calls.append((label, command, timeout, deadline))
        entry = {"stage": label, "child_exit": 0, "signal": None, "complete": True,
                 "ok": True, "output_ok": True, "output_truncated": False,
                 "timed_out": False, "cancelled": False, "source_unchanged": True,
                 "variant_private_cleanup": True, "probe_valid": True,
                 **outcomes.get(label, {})}
        receipt["stages"].append(entry)
        return diagnostic._postmortem_exit(entry["child_exit"], entry["complete"])
    monkeypatch.setattr(diagnostic, "_acquisition_stage", stage)
    return tmp_path, calls, outcomes


def test_reduction_runs_only_two_declared_variants_with_frozen_bounds(reduction):
    root, calls, _ = reduction
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 0
    assert [x[0] for x in calls] == [
        "async_reference", "async_owned_teardown"]
    assert all(0 < x[2] <= 180 and x[1][-2:] == ["--cycles", "200"] for x in calls)
    assert len({x[3] for x in calls}) == 1
    assert receipt["observation"] == "REDUCTION_NON_REPRODUCTION"
    assert receipt["variant_limit"] == 2 and receipt["aggregate_limit_seconds"] == 360


@pytest.mark.parametrize("failed", ["async_reference", "async_owned_teardown"])
def test_reduction_crash_allows_only_remaining_predeclared_comparisons_and_retains139(reduction, failed):
    root, calls, outcomes = reduction
    outcomes[failed] = {"child_exit": -11, "signal": 11, "complete": False}
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 139
    assert len(calls) == 2 and len({x[0] for x in calls}) == 2
    assert receipt["observation"] == "REDUCTION_FAILED_WORKLOAD"


@pytest.mark.parametrize("bad", [
    {"ok": False}, {"variant_private_cleanup": False}, {"source_unchanged": False},
    {"probe_valid": False}, {"output_ok": False}, {"output_truncated": True},
    {"timed_out": True}, {"cancelled": True}, {"diagnostic_error": "OSError"},
])
def test_reduction_capture_or_harness_incompleteness_stops_all_remaining_work(reduction, bad):
    root, calls, outcomes = reduction
    outcomes["async_reference"] = {"child_exit": -11, "signal": 11, "complete": False, **bad}
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 139
    assert len(calls) == 1
    assert receipt["observation"] == "REDUCTION_INCOMPLETE"


def test_reduction_later_harness_error_does_not_erase_earlier139(reduction):
    root, calls, outcomes = reduction
    outcomes["async_reference"] = {"child_exit": -11, "signal": 11, "complete": False}
    outcomes["async_owned_teardown"] = {"child_exit": 70, "complete": False}
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 139
    assert len(calls) == 2 and receipt["observation"] == "REDUCTION_INCOMPLETE"


def test_reduction_budget_expiry_prevents_first_variant(reduction, monkeypatch):
    root, calls, _ = reduction
    clock = iter([0.0, 721.0])
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: next(clock))
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 70
    assert calls == [] and receipt["observation"] == "REDUCTION_INCOMPLETE"


def _lifetime_data(variant, cycle):
    owned = variant == "async_owned_teardown"
    return {"variant": variant, "cycle": cycle, "shown": False,
            "parent_deleted": owned, "thread_deleted": owned, "subtree_verified": owned,
            "load_rows": 4, "store_removed": True, "gc": [0, 0, 0, 0],
            "wrappers": [0, 0, 0, 0, 0, 0]}


def _probe_markers(variant, cycles=200, terminal=True):
    phases = ["cycle_start", "parent_constructed", "load_started", "ownership_checked",
              "worker_terminal", "load_checked", "parent_close", "boundary", "release",
              "lifetime", "complete"]
    rows = [f"QT998_PROBE {variant} 0 startup", f"QT998_PROBE {variant} 0 application"]
    for cycle in range(1, cycles + 1):
        for phase in phases:
            rows.append("QT998_LIFETIME " + json.dumps(_lifetime_data(variant, cycle))
                        if phase == "lifetime" else f"QT998_PROBE {variant} {cycle} {phase}")
    if terminal:
        rows.append(f"QT998_PROBE {variant} {cycles} process_exit")
    return "\n".join(rows) + "\n"


@pytest.mark.parametrize("variant", ["async_reference", "async_owned_teardown"])
def test_probe_reports_complete_cycles_and_honest_partial_prefix(variant):
    result = diagnostic._probe_summary(_probe_markers(variant), variant)
    assert {key: result[key] for key in ("probe_valid", "probe_complete", "variant",
                                        "completed_cycles", "interrupted_cycles",
                                        "last_completed_phase", "last_cycle")} == {
                      "probe_valid": True, "probe_complete": True, "variant": variant,
                      "completed_cycles": 200, "interrupted_cycles": 0,
                      "last_completed_phase": "process_exit", "last_cycle": 200}
    partial = _probe_markers(variant, 3, terminal=False) + f"QT998_PROBE {variant} 4 cycle_start\n"
    partial += "Fatal Python error: Segmentation fault\nSYNTHETIC_SECRET\n"
    result = diagnostic._probe_summary(partial, variant)
    assert result["probe_valid"] and not result["probe_complete"]
    assert result["completed_cycles"] == 3 and result["interrupted_cycles"] == 1
    assert result["last_completed_phase"] == "cycle_start" and result["last_cycle"] == 4
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("bad", [
    "QT998_PROBE", "QT998_PROBE\tasync_owned_teardown 1 complete", "QT998_PROBE async_owned_teardown 201 complete",
    "QT998_PROBE async_owned_teardown 200 SYNTHETIC_SECRET", "QT998_PROBE other 200 complete",
    "QT998_PROBE async_owned_teardown 200 process_exit", "QT998_PROBE async_owned_teardown -1 complete",
])
def test_malformed_or_duplicate_probe_markers_invalidate_attribution(bad):
    result = diagnostic._probe_summary(_probe_markers("async_owned_teardown") + bad, "async_owned_teardown")
    assert not result["probe_valid"] and not result["probe_complete"]
    assert result["last_completed_phase"] == "unavailable"
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("text", ["", "Qt warning only", "QT998_PROBE async_owned_teardown 1 cycle_start\n"])
def test_missing_startup_or_out_of_order_markers_cannot_qualify(text):
    result = diagnostic._probe_summary(text, "async_owned_teardown")
    assert not result["probe_valid"] and result["last_cycle"] is None


def test_context_history_cutoff_remains_new_authority_not_renewal(admission):
    assert diagnostic.APPROVAL_TIME == "2026-09-10T19:56:21Z"
    admission[3].append({"event": "workflow_dispatch", "head_branch": diagnostic.BRANCH,
                         "created_at": "2026-09-10T19:56:22Z", "id": 499})
    with pytest.raises(ValueError, match="approval_already_spent"):
        diagnostic._validate_admission(*admission)


@pytest.fixture
def probe_stage(monkeypatch, tmp_path):
    receipts = []
    monkeypatch.setattr(diagnostic, "_verify_workload", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_verify_probe", lambda: "a" * 64)
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_emit_hosted", receipts.append)
    monkeypatch.setattr(diagnostic, "_inspect_core", lambda *args: {"ok": True})
    return tmp_path, receipts


@pytest.mark.parametrize("code", [0, -11])
@pytest.mark.parametrize("condition", ["complete", "partial", "malformed", "private_leftover"])
def test_real_stage_separates_exit_capture_markers_and_private_cleanup(probe_stage, monkeypatch, code, condition):
    root, published = probe_stage
    text = _probe_markers("async_owned_teardown")
    if condition == "partial":
        text = _probe_markers("async_owned_teardown", 3, terminal=False)
    if condition == "malformed":
        text += "QT998_PROBE"
    if condition == "private_leftover":
        (root / "core.123").write_bytes(b"synthetic marker only")
    child = {"child_exit": code, "signal": 11 if code == -11 else None, "pid": 123,
             "output_ok": True, "output_truncated": False, "pytest_counts": [],
             **diagnostic._probe_summary(text, "async_owned_teardown")}
    monkeypatch.setattr(diagnostic, "_run_private", lambda *args, **kwargs: child)
    receipt = {"stages": []}
    result = diagnostic._acquisition_stage(root, root, receipt, "async_owned_teardown",
                                         [sys.executable, str(diagnostic._probe_file())], [], 180)
    assert result == (139 if code == -11 else (0 if condition == "complete" else 70))
    entry = receipt["stages"][0]
    assert entry["complete"] == (code == 0 and condition == "complete")
    assert entry["variant_private_cleanup"] == (condition != "private_leftover")
    assert diagnostic._usable_probe_failure(entry) == (code == -11 and condition in ("complete", "partial"))
    assert str(diagnostic._probe_file()) not in repr(published)


def test_probe_guard_error_never_exports_tooling_path(probe_stage, monkeypatch):
    root, published = probe_stage
    def fail():
        raise ValueError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, "_verify_probe", fail)
    receipt = {"stages": []}
    assert diagnostic._acquisition_stage(root, root, receipt, "async_owned_teardown",
                                        [sys.executable, str(diagnostic._probe_file())], [], 180) == 70
    assert not receipt["stages"][0]["started"]
    assert "SYNTHETIC_SECRET" not in repr(published)
    assert str(diagnostic._probe_file()) not in repr(published)


def test_failed_stage_publication_stops_remaining_controls_after139(probe_stage, monkeypatch):
    root, _ = probe_stage
    child = {"child_exit": -11, "signal": 11, "pid": 123, "output_ok": True,
             **diagnostic._probe_summary(_probe_markers("async_reference", 2, terminal=False), "async_reference")}
    monkeypatch.setattr(diagnostic, "_run_private", lambda *args, **kwargs: child)
    def fail(*args):
        raise OSError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, "_emit_hosted", fail)
    receipt = {}
    assert diagnostic._acquire_reduction(root, root, receipt) == 139
    assert len(receipt["stages"]) == 1
    assert receipt["observation"] == "REDUCTION_INCOMPLETE"


def test_probe_import_and_normal_collection_are_inert(tmp_path):
    probe = diagnostic._probe_file()
    # A clean interpreter denies every non-stdlib application/Qt import. This
    # exercises the actual file without importing or executing a Qt workload.
    code = """
import importlib.abc, runpy, sys
class RejectQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PyQt', 'metroliza', 'modules')):
            raise AssertionError('probe imported application or Qt')
sys.meta_path.insert(0, RejectQt())
module = runpy.run_path(sys.argv[1], run_name='inert_probe_import')
assert module['_APP'] is None
print('INERT_IMPORT')
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(probe)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and result.stdout.strip() == "INERT_IMPORT", result.stderr
    # Use real pytest default discovery on the exact filename/content, with the
    # repository's pytest settings and no application conftest/plugin effects.
    (tmp_path / probe.name).write_bytes(probe.read_bytes())
    (tmp_path / "pyproject.toml").write_bytes(Path("pyproject.toml").read_bytes())
    collection = """
import importlib.abc, os, sys
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
class RejectProbe(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if 'qt_dialog_lifecycle_probe' in fullname or fullname.startswith(('PyQt', 'metroliza')):
            raise AssertionError('ordinary discovery imported the probe or Qt')
sys.meta_path.insert(0, RejectProbe())
import pytest
raise SystemExit(pytest.main(['--collect-only', '-q', '.']))
"""
    result = subprocess.run([sys.executable, "-I", "-c", collection], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 5 and "no tests collected" in result.stdout, result.stdout + result.stderr
    assert "QT998_PROBE" not in result.stdout


@pytest.fixture
def inert_probe():
    import runpy
    import types
    module = types.SimpleNamespace(**runpy.run_path(str(diagnostic._probe_file()), run_name="inert_probe"))
    return module


@pytest.mark.parametrize("reason", ["host", "phase", "attempt", "hash", "source", "tree", "git", "mode", "accepted"])
def test_probe_admission_rejects_before_qt_entry(inert_probe, monkeypatch, tmp_path, capsys, reason):
    probe = inert_probe
    root = tmp_path / "qt998-500"
    root.mkdir(mode=0o700)
    admission = {"phase": "5618809967", "run_attempt": 1, "run_id": "500",
                 "workload_sha": probe.SOURCE_SHA, "workload_tree": probe.SOURCE_TREE,
                 "probe_sha256": diagnostic.hashlib.sha256(diagnostic._probe_file().read_bytes()).hexdigest()}
    changes = {"phase": ("phase", "5608262552"), "attempt": ("run_attempt", 2),
               "hash": ("probe_sha256", "0" * 64), "source": ("workload_sha", "0" * 40),
               "tree": ("workload_tree", "0" * 40)}
    if reason in changes:
        key, value = changes[reason]
        admission[key] = value
    (root / "admission.json").write_text(json.dumps(admission))
    if reason == "mode":
        root.chmod(0o755)
    monkeypatch.setenv("TMPDIR", str(root / "temporary"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(probe.platform, "system", lambda: "Windows" if reason == "host" else "Linux")
    monkeypatch.setattr(probe.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(probe.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"})
    monkeypatch.setattr(probe.os, "getuid", lambda: root.stat().st_uid)
    identity = "bad\n" if reason == "git" else probe.SOURCE_SHA + "\n" + probe.SOURCE_TREE + "\n"
    monkeypatch.setattr(probe.subprocess, "check_output", lambda *args, **kwargs: identity)
    entered = []
    monkeypatch.setitem(probe.main.__globals__, "_run", lambda *args: entered.append(True))
    assert probe.main(["--variant", "async_owned_teardown", "--cycles", "200"]) == (0 if reason == "accepted" else 70)
    assert bool(entered) == (reason == "accepted")  # _run is an inert recording stub, never Qt.
    assert capsys.readouterr().out == ("QT998_PROBE async_owned_teardown 0 startup\n" if reason == "accepted"
                                     else "QT998_PROBE_ERROR ValueError\n")


@pytest.mark.parametrize("args", [
    ["--variant", "fifth", "--cycles", "200"], ["--variant", "async_owned_teardown", "--cycles", "0"],
    ["--variant", "async_owned_teardown", "--cycles", "201"], [],
])
def test_probe_invalid_cli_never_reaches_admission_or_qt(inert_probe, monkeypatch, args):
    def forbidden():
        pytest.fail("invalid CLI reached admission")
    monkeypatch.setitem(inert_probe.main.__globals__, "_admitted", forbidden)
    with pytest.raises(SystemExit) as result:
        inert_probe.main(args)
    assert result.value.code == 2


def test_reduction_records139_before_between_variant_controller_error(reduction, monkeypatch):
    root, calls, outcomes = reduction
    outcomes["async_reference"] = {"child_exit": -11, "signal": 11, "complete": False}
    ticks = iter([0, 1])
    def clock():
        try:
            return next(ticks)
        except StopIteration:
            raise InterruptedError("synthetic cancellation") from None
    monkeypatch.setattr(diagnostic.time, "monotonic", clock)
    receipt = {}
    with pytest.raises(InterruptedError):
        diagnostic._acquire_reduction(root, root, receipt)
    assert len(calls) == 1 and receipt["reduction_exit"] == 139


@pytest.mark.parametrize("drift", ["head", "worktree", "index_flags", "blob", "none"])
def test_reviewed_probe_guard_checks_exact_committed_bytes(monkeypatch, drift):
    path = diagnostic._probe_file()
    relative = "tests/qt_dialog_lifecycle_probe.py"
    answers = {("rev-parse", "HEAD"): "a" * 40, ("status", "--porcelain=v1"): "",
               ("ls-files", "-v", relative): "H " + relative,
               ("hash-object", relative): "b" * 40, ("rev-parse", "HEAD:" + relative): "b" * 40}
    changes = {"head": (("rev-parse", "HEAD"), "c" * 40),
               "worktree": (("status", "--porcelain=v1"), " M " + relative),
               "index_flags": (("ls-files", "-v", relative), "h " + relative),
               "blob": (("hash-object", relative), "c" * 40)}
    if drift in changes:
        key, value = changes[drift]
        answers[key] = value
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setattr(diagnostic, "_git", lambda root, *args: answers[args])
    if drift == "none":
        assert diagnostic._verify_probe() == diagnostic.hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        with pytest.raises(ValueError, match="reviewed_probe_not_clean"):
            diagnostic._verify_probe()


@pytest.mark.parametrize("failure_call", [1, 2])
def test_probe_drift_before_or_after_child_stops_session(probe_stage, monkeypatch, failure_call):
    root, _ = probe_stage
    calls = []
    count = 0
    def guard():
        nonlocal count
        count += 1
        if count == failure_call:
            raise ValueError("SYNTHETIC_SECRET")
        return "a" * 64
    def child(*args, **kwargs):
        calls.append(1)
        return {"child_exit": -11, "signal": 11, "pid": 123, "output_ok": True,
                **diagnostic._probe_summary(_probe_markers("async_reference", 3, False), "async_reference")}
    monkeypatch.setattr(diagnostic, "_verify_probe", guard)
    monkeypatch.setattr(diagnostic, "_run_private", child)
    receipt = {}
    assert diagnostic._acquire_reduction(root, root, receipt) == (70 if failure_call == 1 else 139)
    assert len(calls) == failure_call - 1 and len(receipt["stages"]) == 1
    assert receipt["observation"] == "REDUCTION_INCOMPLETE"


def test_private_probe_output_extracts_partial_cycles_and_removes_raw_file(monkeypatch, tmp_path):
    class TerminatedChild:
        pid = 123
        returncode = -11
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def wait(self, **kwargs):
            return self.returncode
    def child(*args, **kwargs):
        text = _probe_markers("async_reference", 3, False) + "QT998_PROBE async_reference 4 cycle_start\n"
        kwargs["stdout"].write((text + "SYNTHETIC_SECRET\n").encode())
        return TerminatedChild()
    monkeypatch.setattr(diagnostic.subprocess, "Popen", child)
    result = diagnostic._run_private(["unused"], tmp_path, tmp_path, "async_reference", timeout=180)
    assert result["child_exit"] == -11 and result["signal"] == 11
    assert result["completed_cycles"] == 3 and result["interrupted_cycles"] == 1
    assert result["probe_valid"] and not result["probe_complete"] and result["output_ok"]
    assert not (tmp_path / "async_reference.raw").exists()
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("change", [
    {"extra": "SYNTHETIC_SECRET"}, {"shown": 1}, {"load_rows": 3}, {"store_removed": False},
    {"gc": [0, 0, 0]}, {"gc": [0, -1, 0, 0]}, {"gc": [0, 0, True, 0]},
    {"wrappers": [0, 0, 0, 0, 201, 0]}, {"parent_deleted": False},
    {"thread_deleted": False}, {"subtree_verified": False},
])
def test_async_lifetime_receipts_reject_unsafe_or_unproven_control(change):
    variant = "async_owned_teardown"
    text = _probe_markers(variant)
    old = "QT998_LIFETIME " + json.dumps(_lifetime_data(variant, 200))
    changed = {**_lifetime_data(variant, 200), **change}
    result = diagnostic._probe_summary(text.replace(old, "QT998_LIFETIME " + json.dumps(changed)), variant)
    assert not result["probe_valid"] and not result["probe_complete"]
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("variant", ["async_reference", "async_owned_teardown"])
def test_async_lifetime_receipts_summarize_actual_boundary_not_wrapper_release(variant):
    result = diagnostic._probe_summary(_probe_markers(variant), variant)
    assert result["lifetime_snapshots"] == 200
    assert result["shown_observed_cycles"] == 0
    assert result["store_removed_cycles"] == 200
    assert result["parent_cpp_deleted_cycles"] == (200 if variant == "async_owned_teardown" else 0)
    assert result["gc_counts"] == [0, 0, 0, 0]
    assert result["wrapper_release_counts"] == [0, 0, 0, 0, 0, 0]


def test_async_lifetime_receipt_cannot_be_missing_duplicated_or_go_backwards():
    variant = "async_reference"
    text = _probe_markers(variant)
    row = "QT998_LIFETIME " + json.dumps(_lifetime_data(variant, 1))
    for changed in (text.replace(row + "\n", ""), text.replace(row, row + "\n" + row),
                    text.replace(row, "QT998_LIFETIME " + json.dumps(
                        {**_lifetime_data(variant, 1), "gc": [1, 0, 0, 0]}))):
        assert not diagnostic._probe_summary(changed, variant)["probe_valid"]


def test_async_probe_keeps_spent_variants_inadmissible(inert_probe):
    assert inert_probe.PHASE == "5618809967"
    assert inert_probe.VARIANTS == ("async_reference", "async_owned_teardown")


def test_async_fixture_has_exact_source_test_bytes(inert_probe, tmp_path):
    expected = ("Time Stamp,Reference ID,Line,Length mm,Width mm\n"
                "2026-05-10 08:00:00,R1,L1,10.0,5.0\n"
                "2026-05-10 09:00:00,R1,L2,10.2,5.2\n"
                "2026-05-10 10:00:00,R2,L1,10.1,5.1\n"
                "2026-05-10 11:00:00,R2,L2,10.4,5.4\n")
    assert inert_probe._write_fixture(tmp_path).read_bytes() == expected.encode()


def test_async_python_observers_do_not_retain_or_inspect_referents(inert_probe, monkeypatch):
    role = [101]
    monkeypatch.setattr(inert_probe.threading, "get_ident", lambda: role[0])
    counts, refs, callback, watch = inert_probe._python_observers()
    class Referent:
        def __repr__(self):
            pytest.fail("observer inspected referent")
    for kind in range(3):
        item = Referent()
        watch(item, kind)
        assert refs[-1]() is item
        role[0] = 101 if kind == 0 else 202
        del item  # Plain Python refcount release; no Qt and no forced collection.
        assert refs[-1]() is None
    callback("start", object())
    callback("stop", object())
    assert counts == {"gc": [0, 1, 0, 1], "wrappers": [1, 0, 0, 1, 0, 1]}


@pytest.mark.parametrize("state", ["terminal", "running", "already_deleted", "parent_deleted"])
def test_async_owned_teardown_checks_terminal_before_receiver_deletion(inert_probe, monkeypatch, state):
    import types
    events = []
    class Object:
        def __init__(self, name):
            self.name, self.deleted = name, False
        def isFinished(self):
            assert not self.deleted
            return state != "running"
        def isRunning(self):
            assert not self.deleted
            return state == "running"
        def deleteLater(self):
            assert not self.deleted
            events.append(self.name + "_schedule")
    parent, thread = Object("parent"), Object("thread")
    parent._metroliza_window_event_filter = Object("parent_filter")
    parent.loading_dialog = Object("progress")
    parent.loading_dialog._metroliza_window_event_filter = Object("progress_filter")
    parent.loading_dialog._loading_gif_buffer = Object("buffer")
    parent.loading_dialog._delayed_show_timer = Object("timer")
    parent.loading_gif = Object("movie")
    children = [parent._metroliza_window_event_filter, parent.loading_dialog,
                parent.loading_dialog._metroliza_window_event_filter, parent.loading_gif,
                parent.loading_dialog._loading_gif_buffer, parent.loading_dialog._delayed_show_timer]
    thread.deleted = state == "already_deleted"
    parent.deleted = state == "parent_deleted"
    def send(receiver, event):
        assert not receiver.deleted and event == "deferred"
        events.append(receiver.name + "_dispatch")
        receiver.deleted = True
        if receiver is parent:
            for child in children:
                child.deleted = True
    app = types.SimpleNamespace(thread=lambda: "gui")
    qt = types.ModuleType("PyQt6")
    qt.sip = types.SimpleNamespace(isdeleted=lambda obj: obj.deleted)
    core = types.ModuleType("PyQt6.QtCore")
    core.QCoreApplication = types.SimpleNamespace(sendPostedEvents=send)
    core.QEvent = types.SimpleNamespace(Type=types.SimpleNamespace(DeferredDelete="deferred"))
    core.QThread = types.SimpleNamespace(currentThread=lambda: "gui")
    monkeypatch.setitem(sys.modules, "PyQt6", qt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", core)
    if state == "running":
        with pytest.raises(AssertionError, match="terminal_before_deletion"):
            inert_probe._owned_teardown(parent, thread, app)
        assert events == [] and not parent.deleted
    else:
        verified = inert_probe._owned_teardown(parent, thread, app)
        assert verified == (state != "parent_deleted")
        assert events == ([] if state == "already_deleted" else ["thread_dispatch"]) + (
            [] if state == "parent_deleted" else ["parent_schedule", "parent_dispatch"])
        assert parent.deleted and thread.deleted
        if verified:
            assert all(child.deleted for child in children)


def test_async_probe_timeout_never_reaches_owned_teardown(inert_probe, monkeypatch, tmp_path):
    # Inert stand-ins exercise the real controller error path, never Qt or a loader.
    import types
    app = types.SimpleNamespace(thread=lambda: "gui")
    qt = types.ModuleType("PyQt6.QtWidgets")
    qt.QApplication = lambda args: app
    core = types.ModuleType("PyQt6.QtCore")
    core.QThread = types.SimpleNamespace(currentThread=lambda: "gui")
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", core)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qt)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    callbacks = list(inert_probe.gc.callbacks)
    def fail(*args):
        raise AssertionError("loader_deadline")
    monkeypatch.setitem(inert_probe._run.__globals__, "_async_cycle", fail)
    with pytest.raises(AssertionError, match="loader_deadline"):
        inert_probe._run("async_owned_teardown", 200)
    assert inert_probe.gc.callbacks == callbacks


@pytest.fixture
def fault_source(tmp_path, monkeypatch):
    checkout = tmp_path / "frozen"
    checkout.mkdir()
    (checkout / "tests").mkdir()
    (checkout / "tests/test_case.py").write_text(
        "def test_case():\n    return worker()\n\ndef worker():\n    return 1\n")
    for args in (["init", "-q"], ["add", "."],
                 ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                  "commit", "-qm", "synthetic frozen source"]):
        subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True)
    monkeypatch.setattr(diagnostic, "FROZEN_SHA", diagnostic._git(checkout, "rev-parse", "HEAD"))
    monkeypatch.setattr(diagnostic, "FROZEN_TREE", diagnostic._git(checkout, "rev-parse", "HEAD^{tree}"))
    return checkout


def _fatal_text(path="tests/test_case.py", line=2, function="test_case"):
    return ('Fatal Python error: Segmentation fault\n\n'
            'Current thread 0x00001234 (most recent call first):\n'
            f'  File "{path}", line {line} in {function}\n\n'
            'Extension modules: SYNTHETIC_SECRET (total: 1)\n')


def _fault(text, checkout, **changes):
    child = {"child_exit": -11, "signal": 11, "pid": 123,
             "timed_out": False, "cancelled": False, **changes}
    return diagnostic._python_fault_context(text, checkout, child, "industrial_10")


def test_python_fault_validates_exact_frozen_coordinates(fault_source):
    result = _fault(_fatal_text(str(fault_source / "tests/test_case.py")), fault_source)
    assert result["status"] == "available" and result["complete"]
    assert result["threads"] == [{"ordinal": 1, "current": True, "garbage_collecting": False,
        "frames": [{"path": "tests/test_case.py", "line": 2, "function": "test_case"}],
        "omitted_frames": 0, "frames_truncated": False}]
    assert "SYNTHETIC_SECRET" not in repr(result) and str(fault_source) not in repr(result)
    assert "1234" not in repr(result)


@pytest.mark.parametrize("changes", [
    {"child_exit": 0, "signal": None}, {"child_exit": 139, "signal": None},
    {"child_exit": -6, "signal": 6}, {"timed_out": True}, {"cancelled": True},
])
def test_python_fault_never_attributes_success_or_wrong_terminal_signal(fault_source, changes):
    result = _fault(_fatal_text(), fault_source, **changes)
    assert result["status"] == "unavailable" and result["threads"] == []


@pytest.mark.parametrize("path,line,function", [
    ("/private/SYNTHETIC_SECRET/test_case.py", 2, "test_case"),
    ("../tests/test_case.py", 2, "test_case"), ("./tests/test_case.py", 2, "test_case"),
    ("tests//test_case.py", 2, "test_case"), ("tests\\test_case.py", 2, "test_case"),
    ("tests/test_case.py", 5, "test_case"), ("tests/test_case.py", 999, "test_case"),
    ("tests/test_case.py", 2, "SYNTHETIC_SECRET"),
    ("tests/test_case.py\x1b[31mSYNTHETIC_SECRET", 2, "test_case"),
])
def test_python_fault_omits_untrusted_source_path_scope_line_and_controls(fault_source, path, line, function):
    result = _fault(_fatal_text(path, line, function), fault_source)
    assert not any(t["frames"] for t in result["threads"])
    assert result["omitted_frames"] == 1 and result["status"] == "unavailable"
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("text", ["", "42 passed in 1.0s\n", _fatal_text() + _fatal_text(),
    _fatal_text().replace('  File', '  SYNTHETIC_SECRET File'),
    _fatal_text().replace('line 2', 'line ???'),
    _fatal_text().replace('Extension modules:', 'Current thread 0x5678 (most recent call first):\nExtension modules:')])
def test_python_fault_missing_ambiguous_or_malformed_is_explicit(fault_source, text):
    result = _fault(text, fault_source)
    assert result["status"] == "unavailable" and not result["complete"]
    assert result["threads"] == [] and "SYNTHETIC_SECRET" not in repr(result)


def test_python_fault_eof_truncation_retains_only_validated_partial_frames(fault_source):
    text = _fatal_text().split("Extension modules:")[0] + "  ...\n"
    result = _fault(text, fault_source)
    assert result["status"] == "partial" and not result["complete"]
    assert result["threads"][0]["frames_truncated"]
    assert result["threads"][0]["frames"][0]["function"] == "test_case"


def test_python_fault_current_first_and_all_output_limits(fault_source):
    text = "Fatal Python error: Segmentation fault\n\n"
    for ordinal in range(10):
        text += ("Current thread" if ordinal == 9 else "Thread") + f" 0x{ordinal + 1:08x} (most recent call first):\n"
        text += '  File "tests/test_case.py", line 2 in test_case\n' * 100 + "\n"
    result = _fault(text + "Extension modules: SYNTHETIC_SECRET\n", fault_source)
    assert result["threads"][0]["current"] and result["threads"][0]["ordinal"] == 10
    assert len(result["threads"]) <= 8
    assert sum(len(t["frames"]) for t in result["threads"]) <= 96
    assert result["omitted_frames"] >= 904 and result["omitted_threads"] >= 2
    assert not result["complete"] and len(json.dumps(result)) < 15000


def test_python_fault_source_drift_fails_closed(fault_source):
    (fault_source / "tests/test_case.py").write_text("SYNTHETIC_SECRET")
    result = _fault(_fatal_text(), fault_source)
    assert result["status"] == "unavailable" and result["reason"] == "source_unverified"
    assert result["threads"] == []


@pytest.mark.parametrize("parser_fails", [False, True])
def test_python_fault_extracts_only_after_exit_before_private_log_removal(monkeypatch, tmp_path, parser_fails):
    events = []
    class Child:
        pid, returncode = 123, -11
        def __enter__(self):
            return self
        def __exit__(self, *args):
            events.append("reaped")
        def wait(self, **kwargs):
            events.append("terminal")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: Child())
    def extract(text, checkout, child, label):
        assert events == ["terminal", "reaped"]
        assert (tmp_path / "industrial_1.raw").exists()
        assert child["child_exit"] == -11 and child["pid"] == 123
        events.append("extract")
        if parser_fails:
            raise RuntimeError("SYNTHETIC_SECRET")
        return {"status": "partial"}
    monkeypatch.setattr(diagnostic, "_python_fault_context", extract)
    result = diagnostic._run_private(["unused"], tmp_path, tmp_path, "industrial_1")
    assert events[-1] == "extract" and result["child_exit"] == -11
    assert result["output_ok"] and not (tmp_path / "industrial_1.raw").exists()
    assert result["python_context"]["status"] == ("unavailable" if parser_fails else "partial")
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("publication_fails", [False, True])
def test_python_native_publication_binds_same_child_and_preserves139(acquisition, monkeypatch, publication_fails):
    root, calls, outcomes, emitted = acquisition
    context = {"status": "partial", "threads": [], "complete": False}
    outcomes["industrial_1"] = {"child_exit": -11, "signal": 11, "python_context": context}
    inspected = []
    def inspect(root, child, executable):
        inspected.append(child["pid"])
        return {"ok": True, "capture": "postmortem_stack", "native": {"pid": child["pid"], "signal": 11}}
    monkeypatch.setattr(diagnostic, "_inspect_core", inspect)
    if publication_fails:
        def publish(value):
            if "python_fault_context" in value:
                raise OSError("SYNTHETIC_SECRET")
            emitted.append(value)
        monkeypatch.setattr(diagnostic, "_emit_hosted", publish)
    receipt = {"identity": {"run_id": "500", "scaffolding_sha": "a" * 40}}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 139
    assert receipt["acquisition_exit"] == 139 and inspected == [4]
    assert calls[-1][0] == "industrial_1"
    if publication_fails:
        assert receipt["stages"][-1]["python_context_publication_error"]
        assert "python_context_receipt" not in receipt["stages"][-1]
    if not publication_fails:
        paired = next(v["python_fault_context"] for v in emitted if "python_fault_context" in v)
        assert paired["pid"] == 4 and paired["signal"] == 11 and paired["run_id"] == "500"
        assert paired["workload_sha"] == diagnostic.FROZEN_SHA and paired["stage"] == "industrial_1"
    assert "SYNTHETIC_SECRET" not in repr(receipt)


def test_absolute_budget_is_recomputed_after_guards_before_prefix_launch(acquisition, monkeypatch):
    root, calls, _, _ = acquisition
    now = [0.0]
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(diagnostic.time, "time", lambda: now[0])
    def guard(*args):
        now[0] = 11
    monkeypatch.setattr(diagnostic, "_capture_ready", guard)
    receipt = {"identity": {"observation_deadline_epoch": 10}}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 70
    assert calls == [] and not receipt["stages"][0]["started"]


@pytest.mark.parametrize("before", [True, False])
def test_python_fault_empty_thread_cannot_claim_complete(fault_source, before):
    empty = "Thread 0x5678 (most recent call first):\n\n"
    text = _fatal_text()
    anchor = "Current thread" if before else "Extension modules:"
    text = text.replace(anchor, empty + anchor)
    result = _fault(text, fault_source)
    assert result["status"] == "unavailable" and not result["complete"]


def test_python_fault_combined_full_python_native_record_has_independent_limits(fault_source):
    threads = [{"ordinal": i, "current": i == 8, "garbage_collecting": False,
                "frames_truncated": False,
                "raw_frames": [("tests/test_case.py", 2, "test_case")] * 100} for i in range(1, 9)]
    context = diagnostic._bounded_python_threads(threads, fault_source, {"tests/test_case.py"})
    paired = diagnostic._python_context_receipt(context, {"pid": 4194304, "signal": 11}, "industrial_10",
        {"identity": {"run_id": "34407068328", "scaffolding_sha": "a" * 40}})
    assert len(diagnostic._safe_json(paired).encode("ascii")) <= 16384
    assert sum(len(t["frames"]) for t in context["threads"]) == 96
    assert context["threads"][0]["current"]


def test_python_fault_unavailable_retains_observed_truncation(fault_source):
    result = _fault(_fatal_text().replace("line 2", "line ???"), fault_source, output_truncated=True)
    assert result["status"] == "unavailable" and result["log_truncated"]


@pytest.mark.parametrize("collecting", [False, True])
def test_python_fault_reconstructed_historical_frames_use_real_frozen_blobs(fault_source, monkeypatch, collecting):
    # These tracked files match the declared frozen blobs. Ordinary CI is
    # shallow: this fixture must not require the historical commit object.
    frozen_hashes = {'tests/test_industrial_analytics_dialog.py': '966aa2cc34e79475b735d68065dd1396c52592d8c2897cfd5931a1b3df7108d2', 'src/metroliza/industrial/industrial_workers.py': '8e8feed039ec08e03919dd032e6563347dfce4da774715c46c3d72836cf7aa08'}
    paths = list(frozen_hashes)
    for relative in paths:
        content = Path(relative).read_bytes()
        assert hashlib.sha256(content).hexdigest() == frozen_hashes[relative]
        target = fault_source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    subprocess.run(["git", "-C", str(fault_source), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(fault_source), "-c", "user.name=fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "historical source fixture"],
                   check=True, capture_output=True)
    monkeypatch.setattr(diagnostic, "FROZEN_SHA", diagnostic._git(fault_source, "rev-parse", "HEAD"))
    monkeypatch.setattr(diagnostic, "FROZEN_TREE", diagnostic._git(fault_source, "rev-parse", "HEAD^{tree}"))
    text = ('Fatal Python error: Segmentation fault\n\n'
            'Thread 0xaaaa (most recent call first):\n'
            f'  File "{fault_source}/{paths[1]}", line 513 in run\n\n'
            'Current thread 0xbbbb (most recent call first):\n'
            + ('  Garbage-collecting\n' if collecting else '')
            + f'  File "{fault_source}/{paths[0]}", line 72 in _wait_for_tabular_load\n'
            + f'  File "{fault_source}/{paths[0]}", line 1472 in test_tabular_grouping_dialog_reopens_with_existing_groups_and_column_labels\n'
            + '  File "/private/SYNTHETIC_SECRET/pytest/runner.py", line 99 in call\n\n'
            + 'Extension modules: SYNTHETIC_SECRET (total: 1)\n')
    context = _fault(text, fault_source)
    assert context["status"] == "partial" and context["omitted_frames"] == 1
    assert context["threads"][0]["garbage_collecting"] is collecting
    assert [f["line"] for f in context["threads"][0]["frames"]] == [72, 1472]
    assert context["threads"][1]["frames"] == [{"path": paths[1], "line": 513, "function": "run"}]
    assert "SYNTHETIC_SECRET" not in repr(context) and str(fault_source) not in repr(context)


def test_python_fault_byte_cap_trims_long_validated_frames(fault_source, monkeypatch):
    function = "source_function_" + "x" * 220
    relative = "/".join(["tests", "a" * 120, "b" * 120, "long_file.py"])
    target = fault_source / relative
    target.parent.mkdir(parents=True)
    target.write_text(f"def {function}():\n    return 1\n")
    subprocess.run(["git", "-C", str(fault_source), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(fault_source), "-c", "user.name=fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "long valid source"],
                   check=True, capture_output=True)
    monkeypatch.setattr(diagnostic, "FROZEN_SHA", diagnostic._git(fault_source, "rev-parse", "HEAD"))
    monkeypatch.setattr(diagnostic, "FROZEN_TREE", diagnostic._git(fault_source, "rev-parse", "HEAD^{tree}"))
    text = ("Fatal Python error: Segmentation fault\n\n"
            "Current thread 0x1234 (most recent call first):\n"
            + f'  File "{relative}", line 2 in {function}\n' * 96
            + "Extension modules: SYNTHETIC_SECRET\n")
    result = _fault(text, fault_source)
    assert result["status"] == "partial" and 0 < len(result["threads"][0]["frames"]) < 96
    paired = diagnostic._python_context_receipt(result, {"pid": 123, "signal": 11}, "industrial_10",
        {"identity": {"run_id": "34407068328", "scaffolding_sha": "a" * 40}})
    assert len(diagnostic._safe_json(paired)) <= 16384


@pytest.mark.parametrize("marker", ["  <no Python frame>", "  <tstate is freed>"])
def test_python_fault_explicit_absent_frame_is_partial_not_invented(fault_source, marker):
    text = _fatal_text().replace("Current thread", "Thread 0x5678 (most recent call first):\n" + marker + "\n\nCurrent thread")
    result = _fault(text, fault_source)
    assert result["status"] == "partial" and not result["complete"]
    assert result["threads"][0]["current"] and result["threads"][1]["frames"] == []


def test_fault_helper_import_does_not_activate_any_child_or_qt():
    program = """
import importlib.abc, runpy, subprocess, sys
class RejectQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PyQt', 'metroliza', 'modules')):
            raise AssertionError('unexpected application import')
sys.meta_path.insert(0, RejectQt())
def forbidden(*args, **kwargs):
    raise AssertionError('unexpected child launch')
subprocess.Popen = forbidden
runpy.run_path(sys.argv[1], run_name='inert_fault_helper')
"""
    result = subprocess.run([sys.executable, "-I", "-c", program, str(Path(diagnostic.__file__).resolve())],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and not result.stdout and not result.stderr


@pytest.mark.parametrize("where", ["_verify_workload", "_fatal_threads", "_source_scopes"])
def test_python_fault_cancellation_escapes_source_and_parser_catches(fault_source, monkeypatch, where):
    def interrupted(*args):
        raise InterruptedError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, where, interrupted)
    with pytest.raises(InterruptedError):
        _fault(_fatal_text(), fault_source)


@pytest.mark.parametrize("crashed,wait_cancel", [(True, False), (False, False), (True, True)])
def test_hosted_post_exit_interrupt_skips_debugger_and_cleans_owned_raw_data(
        monkeypatch, tmp_path, crashed, wait_cancel):
    root = tmp_path / "owned"
    root.mkdir()
    identity = {"run_id": "500", "scaffolding_sha": "a" * 40, "phase": diagnostic.PHASE,
                "workload_sha": diagnostic.FROZEN_SHA, "workload_tree": diagnostic.FROZEN_TREE,
                "observation_deadline_epoch": diagnostic.time.time() + 1000}
    (root / "admission.json").write_text(json.dumps(identity))
    for key, value in {"GITHUB_RUN_ID": "500", "GITHUB_SHA": "a" * 40,
                       "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(diagnostic, "_private_root", lambda: root)
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda *args: None)
    monkeypatch.setattr(diagnostic.signal, "alarm", lambda *args: 0)
    monkeypatch.setattr(diagnostic, "_prepare_hosted_capture", lambda *args: {})
    monkeypatch.setattr(diagnostic, "_validate_runtime", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_prove_hosted_capture", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_verify_workload", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *args: None)
    events, outputs = [], []
    monkeypatch.setattr(diagnostic, "_emit_hosted", outputs.append)
    def inspect(*args):
        events.append("debugger")
        return {"ok": False, "capture": "missing_core"}
    monkeypatch.setattr(diagnostic, "_inspect_core", inspect)
    def no_host_change(*args):
        raise AssertionError("unit test must not change any host route")
    monkeypatch.setattr(diagnostic, "_set_core_pattern", no_host_change)
    class Child:
        pid = 123
        def __init__(self, code):
            self.returncode = code
            self.waits = 0
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def wait(self, **kwargs):
            self.waits += 1
            if wait_cancel and self.returncode == -11 and self.waits == 1:
                events.append("wait_interrupted")
                raise InterruptedError("SYNTHETIC_SECRET")
            events.append("terminal")
    def already_finished(pid, sig):
        assert pid == 123 and sig == diagnostic.signal.SIGKILL
        events.append("already_finished")
        raise ProcessLookupError
    monkeypatch.setattr(diagnostic.os, "killpg", already_finished)
    def popen(command, **kwargs):
        events.append(command[2])
        code = -11 if crashed and command[2] == "pytest" else 0
        if code:
            kwargs["stdout"].write(_fatal_text().encode())
            (root / "core.123").write_bytes(b"synthetic core sentinel; not a native dump")
        return Child(code)
    monkeypatch.setattr(subprocess, "Popen", popen)
    def interrupted(*args):
        raise InterruptedError("SYNTHETIC_SECRET")
    if crashed and not wait_cancel:
        monkeypatch.setattr(diagnostic, "_python_fault_context", interrupted)
    elif not crashed:
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == root / "coverage_erase.raw":
                raise InterruptedError("SYNTHETIC_SECRET")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", unlink)
    assert diagnostic.hosted_observe() == (139 if crashed else 70)
    assert "debugger" not in events
    expected_events = (["coverage", "terminal", "pytest", "terminal"] if crashed
                       else ["coverage", "terminal"])
    if wait_cancel:
        expected_events = ["coverage", "terminal", "pytest", "wait_interrupted", "already_finished", "terminal"]
    assert events == expected_events
    final = outputs[-1]
    stage = final["stages"][-1]
    assert stage["pid"] == 123 and stage["child_exit"] == (-11 if crashed else 0)
    assert bool(stage.get("post_exit_interrupted")) is (not wait_cancel)
    assert not stage["timed_out"] and stage["cancelled"] is wait_cancel
    assert stage["capture"] == "not_inspected_after_interrupt"
    assert final["cleanup"]["ok"] and final["cleanup"]["private_storage_removed"]
    assert not root.exists() and "SYNTHETIC_SECRET" not in repr(outputs)
    if crashed:
        context = next(row["python_fault_context"]["context"] for row in outputs if "python_fault_context" in row)
        assert context["status"] == "unavailable"
        assert context["reason"] == ("not_an_eligible_native_failure" if wait_cancel else "extraction_interrupted")


@pytest.mark.parametrize("interrupt_kind", ["post_exit_interrupted", "cancelled"])
def test_capability_control_post_exit_interrupt_does_not_start_debugger(monkeypatch, tmp_path, interrupt_kind):
    (tmp_path / "binaries.json").write_text("{}")
    monkeypatch.setattr(diagnostic, "_file_identity", lambda *args: {"sha256": "a" * 64})
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *args: None)
    monkeypatch.setattr(diagnostic, "_sanitize", lambda *args: "safe synthetic control")
    def run(command, cwd, root, label):
        return {"child_exit": -11 if label == "synthetic" else 0, "signal": 11 if label == "synthetic" else None,
                "pid": 123, "output_ok": label != "synthetic", "timed_out": False,
                interrupt_kind: label == "synthetic", "pytest_counts": []}
    monkeypatch.setattr(diagnostic, "_run_private", run)
    inspected = []
    def inspect(root, child, executable):
        inspected.append(child["pid"])
        return {"ok": False, "capture": "missing_core"}
    monkeypatch.setattr(diagnostic, "_inspect_core", inspect)
    receipt = {}
    with pytest.raises(InterruptedError):
        diagnostic._prove_hosted_capture(tmp_path, receipt)
    assert inspected == [] and receipt["synthetic_control"]["child_exit"] == -11
