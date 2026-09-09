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
    assert job["concurrency"] == {"group": "qt998-postmortem-job-5608262552",
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
                 "workload_sha": diagnostic.FROZEN_SHA, "workload_tree": diagnostic.FROZEN_TREE}
    (tmp_path / "admission.json").write_text(json.dumps(admission))
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(diagnostic, "_private_root", lambda: tmp_path)
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda *args: None)
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
        assert events.count("coverage_erase") == 1
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
    clock = iter([0.0, 0.0, 601.0])
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: next(clock))
    receipt = {}
    assert diagnostic._acquire_sequence(root, root / "workload", receipt) == 70
    assert [x[0] for x in calls] == ["coverage_erase", "main", "dashboard", "industrial_1"]
    assert receipt["observation"] == "INCOMPLETE_WORKLOAD"


def test_spent_old_phase_does_not_consume_the_explicit_new_allocation(admission):
    admission[3].append({"event": "workflow_dispatch", "head_branch": diagnostic.BRANCH,
                         "created_at": "2026-09-09T15:59:03Z", "id": 499})
    assert diagnostic._validate_admission(*admission)["phase"] == "5608262552"
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


@pytest.mark.parametrize("failure", ["runtime", "preflight", "cleanup"])
def test_no_workload_after_failed_preflight_and_cleanup_retains139(monkeypatch, tmp_path, failure):
    admission = {"run_id": "500", "scaffolding_sha": "a" * 40, "phase": diagnostic.PHASE,
                 "workload_sha": diagnostic.FROZEN_SHA, "workload_tree": diagnostic.FROZEN_TREE}
    (tmp_path / "admission.json").write_text(json.dumps(admission))
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(diagnostic, "_private_root", lambda: tmp_path)
    monkeypatch.setattr(diagnostic.os, "getuid", lambda: 1000)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda *args: None)
    events, receipts = [], []
    monkeypatch.setattr(diagnostic, "_prepare_hosted_capture", lambda *args: {})
    def stage(name):
        events.append(name)
        if name == failure:
            raise OSError("SYNTHETIC_SECRET")
    monkeypatch.setattr(diagnostic, "_validate_runtime", lambda *args: stage("runtime"))
    monkeypatch.setattr(diagnostic, "_prove_hosted_capture", lambda *args: stage("preflight"))
    def acquire(*args):
        events.append("workload")
        return 139
    monkeypatch.setattr(diagnostic, "_acquire_sequence", acquire)
    monkeypatch.setattr(diagnostic, "_cleanup_hosted", lambda *args: stage("cleanup") or {"ok": True})
    monkeypatch.setattr(diagnostic, "_emit_hosted", receipts.append)
    assert diagnostic.hosted_observe() == (139 if failure == "cleanup" else 70)
    assert ("workload" in events) == (failure == "cleanup")
    assert events[-1] == "cleanup"
    assert "SYNTHETIC_SECRET" not in repr(receipts)


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
    # Worst permitted frame names/modules plus flags fit one bounded stage log.
    for thread in native["threads"]:
        for frame in thread["frames"]:
            frame.update(function="x" * 160, module="m" * 80, name_truncated=True, unresolved=False)
    assert len(diagnostic._safe_json({"acquisition_stage": {"native": native}})) < 59000
