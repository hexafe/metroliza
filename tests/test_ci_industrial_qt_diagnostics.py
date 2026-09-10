"""Hosted #998 guard/output regressions; never create a core or import Qt."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import ci_industrial_qt_diagnostics as diagnostic


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
    assert job["concurrency"] == {"group": "qt998-postmortem-job-5614139597",
                                   "cancel-in-progress": "false"}
    assert job["concurrency"]["group"] not in workflow["concurrency"]["group"]
    # GitHub evaluates job env before assigning a runner; runner context is step-only.
    assert "runner." not in repr(job.get("env", {}))
    assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == "25"
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
            assert step["with"]["python-version"] == "3.11.16"
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
    monkeypatch.setattr(diagnostic, "_cleanup_hosted", cleanup)
    monkeypatch.setattr(diagnostic, "_emit_hosted", receipts.append)
    assert diagnostic.hosted_observe() == expected_exit
    assert events[-1] == "cleanup" and events.count("cleanup") == 1
    if failure_stage == "preparation":
        assert events == ["preparation", "cleanup"]
        assert receipts[-1]["observation"] == "not_started"
        assert receipts[-1]["diagnostic_error"] == "OSError"
    else:
        assert events.count("industrial_ui") == 1
        assert receipts[-1]["stages"][0]["child_exit"] == -11
        assert receipts[-1]["stages"][0]["diagnostic_error"] == "OSError"


def test_new_phase_has_fixed_failed_content_and_rejects_spent_phase(admission):
    assert diagnostic.FROZEN_SHA == "216877364752c20bcdc65752382da470c4f363d5"
    assert diagnostic.FROZEN_TREE == "719b80423271ff59c6fe08ace819fee2ae151fa0"
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
        counts = {"coverage_erase": [], "main": ["4183 passed", "62 skipped"],
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


def test_sequence_runs_prefix_once_then_ten_complete_fresh_industrial_processes(acquisition):
    root, calls, _, emitted = acquisition
    receipt = {}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 0
    assert [x[0] for x in calls] == ["coverage_erase", "main", "dashboard"] + [
        f"industrial_{i}" for i in range(1, 11)]
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
    assert len(receipt["stages"]) == len(emitted) == 13


@pytest.mark.parametrize("stage", ["coverage_erase", "main", "dashboard",
                                  "industrial_1", "industrial_4", "industrial_10"])
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
    assert diagnostic._validate_admission(*admission)["phase"] == "5614139597"
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
@pytest.mark.parametrize("failure_call", [1, 8, 9])
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
    assert len(calls) == {1: 0, 8: 4, 9: 4}[failure_call]
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
        receipt["reduction_exit"] = 139
        if failure == "after_native":
            raise InterruptedError("SYNTHETIC_SECRET")
        return 139
    monkeypatch.setattr(diagnostic, "_acquire_reduction", acquire)
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


@pytest.mark.parametrize("label", ["industrial_10", "industrial_ui"])
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
                "pytest_subtest_counts": [], **(diagnostic._probe_summary(
                    _probe_markers("industrial_ui", 199, terminal=False)
                    + "QT998_PROBE industrial_ui 200 cycle_start\n"
                    + "QT998_PROBE industrial_ui 200 parent_constructed\n", "industrial_ui")
                    if label == "industrial_ui" else {})}
    monkeypatch.setattr(diagnostic, "_run_private", run)
    monkeypatch.setattr(diagnostic, "_verify_probe", lambda: "a" * 64)
    monkeypatch.setattr(diagnostic, "_verify_workload", lambda *_: None)
    monkeypatch.setattr(diagnostic, "_capture_ready", lambda *_: None)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert diagnostic._acquisition_stage(
        tmp_path, tmp_path, {"stages": []}, label,
        ([sys.executable, "-m", "coverage", "run", "--append", "--source=src/metroliza,modules,scripts",
          str(diagnostic._probe_file()), "--variant", label, "--cycles", "200"]
         if label == "industrial_ui" else [sys.executable, "-m", "pytest", *diagnostic.PYTEST_ARGUMENTS]),
        [] if label == "industrial_ui" else ["42 passed"], 180 if label == "industrial_ui" else 120,
    ) == 139
    output = capsys.readouterr().out.removeprefix("QT998_JSON ").strip()
    assert len(output.encode("utf-8")) < 59000
    stage = json.loads(output)["acquisition_stage"]
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


@pytest.mark.parametrize("spent", ["5604177526", "5608262552"])
def test_reduction_admission_never_revives_either_spent_allocation(admission, spent):
    assert diagnostic.PHASE == "5614139597"
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


def test_reduction_runs_only_four_declared_variants_with_frozen_bounds(reduction):
    root, calls, _ = reduction
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 0
    assert [x[0] for x in calls] == [
        "industrial_ui", "plain_ui", "minimal_filter", "uninstalled_filter"]
    assert all(0 < x[2] <= 180 and x[1][-2:] == ["--cycles", "200"] for x in calls)
    assert len({x[3] for x in calls}) == 1
    assert receipt["observation"] == "REDUCTION_NON_REPRODUCTION"
    assert receipt["variant_limit"] == 4 and receipt["aggregate_limit_seconds"] == 720


@pytest.mark.parametrize("failed", ["industrial_ui", "plain_ui", "minimal_filter", "uninstalled_filter"])
def test_reduction_crash_allows_only_remaining_predeclared_comparisons_and_retains139(reduction, failed):
    root, calls, outcomes = reduction
    outcomes[failed] = {"child_exit": -11, "signal": 11, "complete": False}
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 139
    assert len(calls) == 4 and len({x[0] for x in calls}) == 4
    assert receipt["observation"] == "REDUCTION_FAILED_WORKLOAD"


@pytest.mark.parametrize("bad", [
    {"ok": False}, {"variant_private_cleanup": False}, {"source_unchanged": False},
    {"probe_valid": False}, {"output_ok": False}, {"output_truncated": True},
    {"timed_out": True}, {"cancelled": True}, {"diagnostic_error": "OSError"},
])
def test_reduction_capture_or_harness_incompleteness_stops_all_remaining_work(reduction, bad):
    root, calls, outcomes = reduction
    outcomes["industrial_ui"] = {"child_exit": -11, "signal": 11, "complete": False, **bad}
    receipt = {}
    assert diagnostic._acquire_reduction(root, root / "workload", receipt) == 139
    assert len(calls) == 1
    assert receipt["observation"] == "REDUCTION_INCOMPLETE"


def test_reduction_later_harness_error_does_not_erase_earlier139(reduction):
    root, calls, outcomes = reduction
    outcomes["industrial_ui"] = {"child_exit": -11, "signal": 11, "complete": False}
    outcomes["plain_ui"] = {"child_exit": 70, "complete": False}
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


def _probe_markers(variant, cycles=200, terminal=True):
    phases = (["cycle_start", "parent_constructed", "parent_show", "progress_constructed",
               "progress_show", "ownership_checked", "events", "progress_close", "parent_close",
               "release", "complete"] if variant == "industrial_ui" else
              ["cycle_start", "constructed", "configured", "layout", "themed", "ownership_checked",
               "show", "events", "close", "release", "complete"])
    rows = [(0, "startup"), (0, "application")]
    rows.extend((cycle, phase) for cycle in range(1, cycles + 1) for phase in phases)
    if terminal:
        rows.append((cycles, "process_exit"))
    return "\n".join(f"QT998_PROBE {variant} {cycle} {phase}" for cycle, phase in rows) + "\n"


@pytest.mark.parametrize("variant", ["industrial_ui", "plain_ui", "minimal_filter", "uninstalled_filter"])
def test_probe_reports_complete_cycles_and_honest_partial_prefix(variant):
    result = diagnostic._probe_summary(_probe_markers(variant), variant)
    assert result == {"probe_valid": True, "probe_complete": True, "variant": variant,
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
    "QT998_PROBE", "QT998_PROBE\tplain_ui 1 complete", "QT998_PROBE plain_ui 201 complete",
    "QT998_PROBE plain_ui 200 SYNTHETIC_SECRET", "QT998_PROBE other 200 complete",
    "QT998_PROBE plain_ui 200 process_exit", "QT998_PROBE plain_ui -1 complete",
])
def test_malformed_or_duplicate_probe_markers_invalidate_attribution(bad):
    result = diagnostic._probe_summary(_probe_markers("plain_ui") + bad, "plain_ui")
    assert not result["probe_valid"] and not result["probe_complete"]
    assert result["last_completed_phase"] == "unavailable"
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("text", ["", "Qt warning only", "QT998_PROBE plain_ui 1 cycle_start\n"])
def test_missing_startup_or_out_of_order_markers_cannot_qualify(text):
    result = diagnostic._probe_summary(text, "plain_ui")
    assert not result["probe_valid"] and result["last_cycle"] is None


def test_probe_history_cutoff_remains_original_authority_not_renewal(admission):
    assert diagnostic.APPROVAL_TIME == "2026-09-10T06:24:21Z"
    admission[3].append({"event": "workflow_dispatch", "head_branch": diagnostic.BRANCH,
                         "created_at": "2026-09-10T07:00:00Z", "id": 499})
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
    text = _probe_markers("plain_ui")
    if condition == "partial":
        text = _probe_markers("plain_ui", 3, terminal=False)
    if condition == "malformed":
        text += "QT998_PROBE"
    if condition == "private_leftover":
        (root / "core.123").write_bytes(b"synthetic marker only")
    child = {"child_exit": code, "signal": 11 if code == -11 else None, "pid": 123,
             "output_ok": True, "output_truncated": False, "pytest_counts": [],
             **diagnostic._probe_summary(text, "plain_ui")}
    monkeypatch.setattr(diagnostic, "_run_private", lambda *args, **kwargs: child)
    receipt = {"stages": []}
    result = diagnostic._acquisition_stage(root, root, receipt, "plain_ui",
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
    assert diagnostic._acquisition_stage(root, root, receipt, "plain_ui",
                                        [sys.executable, str(diagnostic._probe_file())], [], 180) == 70
    assert not receipt["stages"][0]["started"]
    assert "SYNTHETIC_SECRET" not in repr(published)
    assert str(diagnostic._probe_file()) not in repr(published)


def test_failed_stage_publication_stops_remaining_controls_after139(probe_stage, monkeypatch):
    root, _ = probe_stage
    child = {"child_exit": -11, "signal": 11, "pid": 123, "output_ok": True,
             **diagnostic._probe_summary(_probe_markers("industrial_ui", 2, terminal=False), "industrial_ui")}
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
    admission = {"phase": "5614139597", "run_attempt": 1, "run_id": "500",
                 "workload_sha": diagnostic.FROZEN_SHA, "workload_tree": diagnostic.FROZEN_TREE,
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
    identity = "bad\n" if reason == "git" else diagnostic.FROZEN_SHA + "\n" + diagnostic.FROZEN_TREE + "\n"
    monkeypatch.setattr(probe.subprocess, "check_output", lambda *args, **kwargs: identity)
    entered = []
    monkeypatch.setitem(probe.main.__globals__, "_run", lambda *args: entered.append(True))
    assert probe.main(["--variant", "plain_ui", "--cycles", "200"]) == (0 if reason == "accepted" else 70)
    assert bool(entered) == (reason == "accepted")  # _run is an inert recording stub, never Qt.
    assert capsys.readouterr().out == ("QT998_PROBE plain_ui 0 startup\n" if reason == "accepted"
                                     else "QT998_PROBE_ERROR ValueError\n")


@pytest.mark.parametrize("args", [
    ["--variant", "fifth", "--cycles", "200"], ["--variant", "plain_ui", "--cycles", "0"],
    ["--variant", "plain_ui", "--cycles", "201"], [],
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
    outcomes["industrial_ui"] = {"child_exit": -11, "signal": 11, "complete": False}
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
                **diagnostic._probe_summary(_probe_markers("industrial_ui", 3, False), "industrial_ui")}
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
        text = _probe_markers("industrial_ui", 3, False) + "QT998_PROBE industrial_ui 4 cycle_start\n"
        kwargs["stdout"].write((text + "SYNTHETIC_SECRET\n").encode())
        return TerminatedChild()
    monkeypatch.setattr(diagnostic.subprocess, "Popen", child)
    result = diagnostic._run_private(["unused"], tmp_path, tmp_path, "industrial_ui", timeout=180)
    assert result["child_exit"] == -11 and result["signal"] == 11
    assert result["completed_cycles"] == 3 and result["interrupted_cycles"] == 1
    assert result["probe_valid"] and not result["probe_complete"] and result["output_ok"]
    assert not (tmp_path / "industrial_ui.raw").exists()
    assert "SYNTHETIC_SECRET" not in repr(result)
