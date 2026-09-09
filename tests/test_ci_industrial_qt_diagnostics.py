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
                        "qt998_workload_sha": diagnostic.FROZEN_SHA}}
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
    assert receipt == {"scaffolding_sha": "a" * 40, "workload_sha": diagnostic.FROZEN_SHA,
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
    assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == "25"
    assert "workflow_dispatch" in job["if"] and "== '1'" in job["if"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    for step in job["steps"]:
        action = step.get("uses", "")
        assert "upload-artifact" not in action and "actions/cache" not in action
        assert "${{" not in step.get("run", "")
        if "setup-python" in action:
            assert step["with"]["cache"] == ""
            assert step["with"]["python-version"] == "3.11.16"
        if "actions/checkout" in action:
            assert step["with"]["persist-credentials"] == "false"
    workload_checkout = next(step for step in job["steps"]
                             if step.get("with", {}).get("path") == "frozen-b10")
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
