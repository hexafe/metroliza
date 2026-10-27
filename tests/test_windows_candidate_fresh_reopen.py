"""Fresh-process reopen and fail-closed protocol controls; source is not EXE proof."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import sqlite3
import shutil
from contextlib import closing
from types import SimpleNamespace

import pytest

from metroliza.app import windows_candidate_qualification as application
from metroliza.app import windows_candidate_reopen as reopen
from metroliza.app.bootstrap import get_or_create_qapplication
from scripts import qualify_windows_candidate_core as core
from scripts import qualify_windows_diagnostics as diag
from scripts import verify_synthetic_oracle as oracle_verifier
from tests.test_windows_candidate_reopen import _seed_completed_import
from tests.test_windows_candidate_launch_ownership import _interrupt_after_launch_before_store


def runtime_receipt(database_hash="a" * 64, source="b" * 40):
    return {"schema_version": 1, "scenario": "reopen", "status": "passed", "packaged": True,
            "qpa": "windows", "ordinary_user": True, "source_sha": source,
            "observation": {"schema_version": 1, "status": "passed",
                "facets": {"reopen_preserves_completed_import": "passed"},
                "database": {"sha256": database_hash, "before_sha256": database_hash,
                    "schema_sha256": "c" * 64, "logical_dump_sha256": "d" * 64,
                    "counts": dict.fromkeys(("source_files", "active_locations", "parsed_reports", "metadata", "measurements"), 2)},
                "source_hashes": {f"REF001_2024-01-01_{i}.pdf": core.PUBLIC_FIXTURE_HASHES[f"report-{i}.pdf"] for i in range(5)}}}


@pytest.fixture(scope="session")
def retained_reopen_application():
    # The Qt application outlives every window and subsequent test module.
    # A source subprocess is used for the actual fresh application boundary.
    return get_or_create_qapplication()


def _emit_fresh_reopen_failure(stage, error):
    # Fixed fields only: never serialize the exception's message or attributes.
    sys.__stderr__.write(json.dumps({
        "schema_version": 1, "test": "fresh_reopen", "event": "failure",
        "stage": stage, "exception_type": type(error).__name__[:80],
    }) + "\n")
    sys.__stderr__.flush()


def test_actual_separate_source_process_reopens_completed_import_without_data_changes(tmp_path, retained_reopen_application, capfd):
    stage = "seed_import"
    try:
        app = retained_reopen_application
        first = tmp_path / "core scenario" / ("core-" + "a" * 32)
        first.mkdir(parents=True)
        database, reports, hashes = _seed_completed_import(app, first)
        stage = "prior_validation"
        prior = reopen.run_reopen_checks(database, reports, hashes)
        assert prior["status"] == "passed"
        stage = "child_prepare"
        root = tmp_path / "fresh reopen"
        root.mkdir()
        state = tmp_path / "isolated state"
        state.mkdir()
        checkout = Path(__file__).resolve().parents[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith("METROLIZA_")}
        env.update({name: "1" for name in application.GATES})
        env.update({application.ROOT_ENV: str(root), "METROLIZA_WINDOWS_CANDIDATE_PHASE": "reopen",
                    "METROLIZA_WINDOWS_CANDIDATE_REOPEN_INPUT": str(first),
                    "METROLIZA_WINDOWS_CANDIDATE_REOPEN_SHA256": core._hash(database),
                    "PYTHONPATH": str(checkout / "src"), "GSETTINGS_BACKEND": "memory",
                    "QT_QPA_PLATFORM": app.platformName(), "QT_STYLE_OVERRIDE": "Fusion",
                    "XDG_STATE_HOME": str(state), "XDG_CONFIG_HOME": str(state), "XDG_CACHE_HOME": str(state),
                    "LOCALAPPDATA": str(state), "APPDATA": str(state)})
        stage = "child_run"
        result = subprocess.run([sys.executable, str(checkout / "packaging/metroliza_package_entry.py")],
                                cwd=state, env=env, capture_output=True, timeout=45)
        stage = "receipt_read"
        payload = json.loads((root / "fresh-reopen-result.json").read_bytes())
        stage = "receipt_assertions"
        assert result.returncode == 0, payload
        assert payload["status"] == "passed" and payload["packaged"] is False
        assert payload["qpa"] == app.platformName()
        assert payload["observation"]["database"] == dict(prior["database"], before_sha256=prior["database"]["sha256"], sha256=core._hash(database))
        assert payload["observation"]["source_hashes"] == hashes
    except BaseException as error:
        try:
            with capfd.disabled():
                _emit_fresh_reopen_failure(stage, error)
        except BaseException:
            pass  # Even a secondary logger interrupt must preserve the active primary.
        raise


@pytest.fixture
def reopen_diagnostic_control(tmp_path, monkeypatch, capfd):
    """Reach the real test body with synthetic input and a controlled child seam."""
    import io

    calls = []
    primary = RuntimeError("PRIVATE_MESSAGE")
    primary.filename = "PRIVATE_FILENAME"
    primary.stdout = "PRIVATE_STDOUT"
    primary.stderr = "PRIVATE_STDERR"
    primary.payload = {"PRIVATE_PAYLOAD": "PRIVATE_VALUE"}
    stream = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", stream)

    def invoke(fault):
        def seed(app, first):
            calls.append("seed")
            if fault == "seed":
                raise primary
            database = first / "synthetic.sqlite"
            database.write_bytes(b"synthetic")
            return database, first, {"public": "hash"}

        def validate(*args):
            calls.append("validate")
            if fault == "prior":
                raise primary
            return {"status": "passed", "database": {"sha256": "old"}}

        def run(*args, **kwargs):
            calls.append("child")
            if fault == "child":
                raise primary
            payload = {"status": "passed", "packaged": False, "qpa": "offscreen",
                       "observation": {"database": {"sha256": "hash", "before_sha256": "old"},
                                       "source_hashes": {"public": "hash"}}}
            if fault != "receipt":
                (tmp_path / "fresh reopen" / "fresh-reopen-result.json").write_text(json.dumps(payload))
            return SimpleNamespace(returncode=1 if fault == "assert" else 0)

        monkeypatch.setattr(sys.modules[__name__], "_seed_completed_import", seed)
        monkeypatch.setattr(reopen, "run_reopen_checks", validate)
        monkeypatch.setattr(core, "_hash", lambda _: "hash")
        monkeypatch.setattr(subprocess, "run", run)
        return test_actual_separate_source_process_reopens_completed_import_without_data_changes(
            tmp_path, SimpleNamespace(platformName=lambda: "offscreen"), capfd,
        )

    return invoke, calls, primary, stream


@pytest.mark.parametrize("fault,stage,exception_type", [
    ("seed", "seed_import", "RuntimeError"),
    ("prior", "prior_validation", "RuntimeError"),
    ("child", "child_run", "RuntimeError"),
    ("receipt", "receipt_read", "FileNotFoundError"),
    ("assert", "receipt_assertions", "AssertionError"),
])
def test_fresh_reopen_diagnostic_reaches_actual_failure_stage(reopen_diagnostic_control, fault, stage, exception_type):
    invoke, calls, primary, stream = reopen_diagnostic_control
    with pytest.raises(BaseException) as caught:
        invoke(fault)
    if exception_type == "RuntimeError":
        assert caught.value is primary
    assert calls == (["seed"] if fault == "seed" else ["seed", "validate"] if fault == "prior"
                     else ["seed", "validate", "child"])
    event = json.loads(stream.getvalue())
    assert event == {"schema_version": 1, "test": "fresh_reopen", "event": "failure",
                     "stage": stage, "exception_type": exception_type}
    assert len(stream.getvalue().splitlines()) == 1
    for sentinel in ("PRIVATE_MESSAGE", "PRIVATE_FILENAME", "PRIVATE_STDOUT", "PRIVATE_STDERR",
                     "PRIVATE_PAYLOAD", "PRIVATE_VALUE"):
        assert sentinel not in stream.getvalue()


@pytest.mark.parametrize("secondary", [RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("operation", ["write", "flush"])
def test_fresh_reopen_diagnostic_preserves_primary_when_stream_fails(
    reopen_diagnostic_control, monkeypatch, secondary, operation,
):
    invoke, calls, primary, stream = reopen_diagnostic_control

    def fail(*args):
        raise secondary("PRIVATE_LOGGER")

    monkeypatch.setattr(stream, operation, fail)
    with pytest.raises(RuntimeError) as caught:
        invoke("child")
    assert caught.value is primary
    traceback = caught.value.__traceback__
    while traceback.tb_next:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "run"
    assert calls == ["seed", "validate", "child"]


def test_fresh_reopen_diagnostic_success_has_no_failure_event(reopen_diagnostic_control):
    invoke, calls, _, stream = reopen_diagnostic_control
    assert invoke("success") is None
    assert calls == ["seed", "validate", "child"]
    assert stream.getvalue() == ""


@pytest.mark.parametrize("failure", ["missing", "closed", "format"])
def test_fresh_reopen_diagnostic_unavailable_output_preserves_failure(reopen_diagnostic_control, monkeypatch, failure):
    invoke, _, primary, stream = reopen_diagnostic_control
    if failure == "missing":
        monkeypatch.setattr(sys, "__stderr__", None)
    elif failure == "closed":
        stream.close()
    else:
        def fail(*args):
            raise SystemExit("PRIVATE_FORMAT")

        monkeypatch.setattr(json, "dumps", fail)
    with pytest.raises(RuntimeError) as caught:
        invoke("child")
    assert caught.value is primary


def test_fresh_reopen_diagnostic_flushes_before_reraise(reopen_diagnostic_control, monkeypatch):
    invoke, _, primary, stream = reopen_diagnostic_control
    flushed = []
    monkeypatch.setattr(stream, "flush", lambda: flushed.append(stream.getvalue()))
    with pytest.raises(RuntimeError) as caught:
        invoke("child")
    assert caught.value is primary
    assert len(flushed) == 1
    assert json.loads(flushed[0])["stage"] == "child_run"


@pytest.mark.parametrize("secondary", [RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("operation", ["enter", "exit"])
def test_fresh_reopen_capture_context_failure_preserves_primary(
    reopen_diagnostic_control, monkeypatch, capfd, secondary, operation,
):
    invoke, _, primary, _ = reopen_diagnostic_control

    class BrokenCapture:
        def __enter__(self):
            if operation == "enter":
                raise secondary("PRIVATE_CONTEXT_ENTER")

        def __exit__(self, *args):
            raise secondary("PRIVATE_CONTEXT_EXIT")

    monkeypatch.setattr(capfd, "disabled", BrokenCapture)
    with pytest.raises(RuntimeError) as caught:
        invoke("child")
    assert caught.value is primary
    traceback = caught.value.__traceback__
    while traceback.tb_next:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "run"


def test_fresh_reopen_diagnostic_survives_default_fd_capture_and_abrupt_child_exit(tmp_path):
    probe = tmp_path / "test_capture_probe.py"
    probe.write_text('''import os
import sys
from tests.test_windows_candidate_fresh_reopen import reopen_diagnostic_control
ORIGINAL_STDERR = sys.__stderr__

def test_probe(reopen_diagnostic_control, monkeypatch):
    invoke, _, _, _ = reopen_diagnostic_control
    monkeypatch.setattr(sys, "__stderr__", ORIGINAL_STDERR)
    print("PRIVATE_CAPTURED_STDOUT")
    sys.stderr.write("PRIVATE_CAPTURED_STDERR")
    try:
        invoke("child")
    except RuntimeError:
        os._exit(23)  # Only this controlled synthetic subprocess exits.
    raise AssertionError("controlled primary was not raised")
''')
    checkout = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(checkout / "src"), str(checkout))))
    environment.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "-v", str(probe)],
                            env=environment, cwd=tmp_path, capture_output=True, timeout=45)
    assert result.returncode == 23
    events = [json.loads(line) for line in result.stderr.decode().splitlines() if line.startswith('{"schema_version"')]
    assert events == [{"schema_version": 1, "test": "fresh_reopen", "event": "failure",
                       "stage": "child_run", "exception_type": "RuntimeError"}]
    output = result.stdout + result.stderr
    assert b"PRIVATE_CAPTURED_STDOUT" not in output
    assert b"PRIVATE_CAPTURED_STDERR" not in output


@pytest.mark.parametrize("fault", ["source", "qpa", "head", "database", "source_files", "not_completed"])
def test_fresh_reopen_rejects_wrong_runtime_or_input(fault):
    value = runtime_receipt()
    prior = {"artifacts": {"database": {"sha256": "a" * 64}},
             "reopen_database": copy.deepcopy(value["observation"]["database"]),
             "source_hashes": copy.deepcopy(value["observation"]["source_hashes"])}
    if fault == "source":
        value["packaged"] = False
    elif fault == "qpa":
        value["qpa"] = "offscreen"
    elif fault == "head":
        value["source_sha"] = "e" * 40
    elif fault == "database":
        value["observation"]["database"]["sha256"] = "e" * 64
    elif fault == "source_files":
        value["observation"]["source_hashes"] = {}
    else:
        value["status"] = "failed"
    with pytest.raises(core.CandidateFailure):
        core._validate_fresh_reopen(value, prior, "b" * 40)


def test_fresh_reopen_refuses_input_outside_owned_prior_sibling(tmp_path, monkeypatch):
    root = tmp_path / "fresh reopen"
    root.mkdir()
    monkeypatch.setenv("METROLIZA_WINDOWS_CANDIDATE_REOPEN_INPUT", str(tmp_path / "user data"))
    with pytest.raises(reopen.ReopenScenarioFailure, match="fresh_reopen_input_not_owned_sibling"):
        reopen._fresh_input(root)


def test_fresh_reopen_real_oracle_reaches_new_process_boundary(tmp_path, monkeypatch):
    work = tmp_path / "core scenario"
    child = work / "core-synthetic"
    child.mkdir(parents=True)
    database = child / "reports.sqlite"
    oracle_path = Path(__file__).resolve().parents[1] / "scripts" / "synthetic-report-oracle.json"
    oracle_verifier._create_synthetic_database(oracle_verifier._load_oracle(oracle_path), database)
    expected_hash = core._hash(database)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(core, "_validate_reopen_sources", lambda _reports: None)

    class ReachedLaunch(Exception):
        pass

    class Api:
        def launch(self, *_args, **_kwargs):
            raise ReachedLaunch

    dependency = SimpleNamespace(
        _WindowsApi=Api, _close_owned_processes=lambda *_args, **_kwargs: None,
    )
    stage = {"name": "fresh_reopen"}
    with pytest.raises(ReachedLaunch):
        core._run_fresh_reopen(
            tmp_path, diag=dependency, relocated=tmp_path, environment={}, work=work,
            prior={"relative_artifact_dir": child.name,
                   "artifacts": {"database": {"sha256": expected_hash}}},
            args=SimpleNamespace(oracle=oracle_path), deadline=time.monotonic() + 1,
            output=output, stage=stage,
        )
    assert stage["name"] == "fresh_reopen"
    assert core._hash(output / "before-reopen.sqlite") == expected_hash


@pytest.mark.parametrize("fault,expected_stage", [
    ("prepare", "fresh_reopen_prepare"),
    ("input", "fresh_reopen_input"),
    ("copy", "fresh_reopen_copy"),
    ("oracle", "fresh_reopen_oracle"),
])
def test_fresh_reopen_prelaunch_failure_keeps_fixed_stage_and_valid_core_receipt(
    tmp_path, monkeypatch, fault, expected_stage,
):
    work = tmp_path / "core scenario"
    child = work / "core-synthetic"
    child.mkdir(parents=True)
    database = child / "reports.sqlite"
    database.write_bytes(b"synthetic completed import")
    expected_hash = core._hash(database)
    output = tmp_path / "output"
    output.mkdir()
    if fault == "prepare":
        (tmp_path / "fresh reopen").mkdir()
    else:
        def validate_sources(_reports):
            if fault == "input":
                raise RuntimeError("PRIVATE_SOURCE")

        monkeypatch.setattr(core, "_validate_reopen_sources", validate_sources)
    if fault == "copy":
        monkeypatch.setattr(core.shutil, "copyfileobj", lambda *_: (_ for _ in ()).throw(OSError("PRIVATE_COPY")))
    if fault == "oracle":
        def reject_oracle(*_args):
            raise ValueError("PRIVATE_DATABASE")

        monkeypatch.setattr(core, "_independent_verifier", lambda: SimpleNamespace(
            _load_oracle=lambda _path: {}, assert_database=reject_oracle,
        ))
    prior = {"relative_artifact_dir": child.name, "artifacts": {"database": {"sha256": expected_hash}}}
    observation = {
        "observed_process": "requested_launcher_handle", "observed_exit_code": 0,
        "receipt_state": "valid_success", "producer_stage": "complete",
        "owned_cleanup": "complete", "private_cleanup": "complete",
    }
    stage = {"name": "fresh_reopen"}
    with pytest.raises((OSError, ValueError, RuntimeError)):
        core._run_fresh_reopen(
            tmp_path, diag=SimpleNamespace(_WindowsApi=lambda: pytest.fail("reopen must not launch")),
            relocated=tmp_path, environment={}, work=work, prior=prior,
            args=SimpleNamespace(oracle=tmp_path / "oracle.json"),
            deadline=time.monotonic() + 1, output=output, stage=stage,
            failure_observation=observation,
        )
    assert stage == {"name": expected_stage}
    payload = core._failed_diagnostic_payload(
        observation, stage, core._closed_unexpected_stage(stage["name"]), "a" * 40,
    )
    assert payload["host_stage"] == expected_stage
    assert payload["observed_process"] == "requested_launcher_handle"
    assert payload["observed_exit_code"] == 0
    assert payload["receipt_state"] == "valid_success"
    assert payload["producer_stage"] == "complete"
    assert payload["owned_cleanup"] == payload["private_cleanup"] == "complete"
    assert database.read_bytes() == b"synthetic completed import"
    serialized = json.dumps(payload)
    assert "PRIVATE_" not in serialized and str(tmp_path) not in serialized


def test_fresh_process_launch_transfer_interrupt_closes_registered_job(tmp_path, monkeypatch):
    root = tmp_path / "core scenario"
    child = root / ("core-" + "a" * 32)
    child.mkdir(parents=True)
    database = child / "reports.sqlite"
    database.write_bytes(b"synthetic launch boundary fixture")
    calls = []
    primary = KeyboardInterrupt("primary")
    class Process:
        def close(self, *, terminate):
            calls.append(terminate)
            raise SystemExit("secondary")
    class Api:
        def launch(self, executable, env, cwd, owned=None, expected_images=None):
            assert env["METROLIZA_WINDOWS_CANDIDATE_PHASE"] == "reopen"
            assert env["METROLIZA_WINDOWS_CANDIDATE_REOPEN_SHA256"] == core._hash(database)
            assert cwd != Path(env[application.ROOT_ENV])
            owned.append(Process())
            return owned[-1]
    monkeypatch.setattr(core, "_validate_reopen_sources", lambda _reports: None)
    monkeypatch.setattr(core, "_independent_verifier", lambda: SimpleNamespace(
        _load_oracle=lambda _path: {}, assert_database=lambda *args: None,
    ))
    dependency = SimpleNamespace(
        QualificationFailure=diag.QualificationFailure,
        _WindowsApi=Api, _close_owned_processes=diag._close_owned_processes,
    )
    prior = {"relative_artifact_dir": child.name, "artifacts": {"database": {"sha256": core._hash(database)}}}
    stage = {"name": "fresh_reopen"}
    with pytest.raises(KeyboardInterrupt) as caught:
        _interrupt_after_launch_before_store(core._run_fresh_reopen.__code__, primary,
            lambda: core._run_fresh_reopen(tmp_path, diag=dependency, relocated=tmp_path,
                environment={}, work=root, prior=prior, args=SimpleNamespace(expected_source_sha="b" * 40, oracle=tmp_path / "oracle.json"),
                deadline=time.monotonic() + 1, output=tmp_path, stage=stage))
    assert caught.value is primary
    assert calls == [True]
    assert stage["name"] == "fresh_reopen"


def test_fresh_reopen_keeps_closed_primary_after_real_cleanup_wrapper(tmp_path, monkeypatch):
    root = tmp_path / "core scenario"
    child = root / ("core-" + "a" * 32)
    child.mkdir(parents=True)
    database = child / "reports.sqlite"
    database.write_bytes(b"synthetic reopen boundary fixture")
    closed = []

    class Process:
        def observe(self):
            raise core.CandidateFailure("fresh_reopen_process_failed")

        def close(self, *, terminate):
            closed.append(terminate)
            diag._attempt_cleanup(lambda: None)

    class Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            process = Process()
            owned.append(process)
            return process

    monkeypatch.setattr(core, "_validate_reopen_sources", lambda _reports: None)
    monkeypatch.setattr(core, "_independent_verifier", lambda: SimpleNamespace(
        _load_oracle=lambda _path: {}, assert_database=lambda *args: None,
    ))
    dependency = SimpleNamespace(
        QualificationFailure=diag.QualificationFailure,
        _WindowsApi=Api, _close_owned_processes=diag._close_owned_processes,
    )
    prior = {"relative_artifact_dir": child.name, "artifacts": {"database": {"sha256": core._hash(database)}}}
    stage = {"name": "fresh_reopen"}
    with pytest.raises(core.CandidateFailure, match="^fresh_reopen_process_failed$"):
        core._run_fresh_reopen(
            tmp_path, diag=dependency, relocated=tmp_path, environment={}, work=root,
            prior=prior, args=SimpleNamespace(oracle=tmp_path / "oracle.json"),
            deadline=time.monotonic() + 1, output=tmp_path, stage=stage,
        )
    assert closed == [True]
    assert stage == {"name": "fresh_reopen"}


def test_reopen_failure_producer_reader_and_nonzero_launcher_observation(tmp_path, monkeypatch):
    source_sha = "b" * 40
    core_root = tmp_path / "core scenario"
    child = core_root / ("core-" + "a" * 32)
    child.mkdir(parents=True)
    database = child / "reports.sqlite"
    database.write_bytes(b"synthetic completed import")
    reopen_root = tmp_path / "fresh reopen"
    monkeypatch.setattr(application, "requested_scenario", lambda: "reopen")
    monkeypatch.setattr(application, "_root", lambda: reopen_root)
    monkeypatch.setattr(application, "_ordinary_user", lambda: True)
    monkeypatch.setattr(application, "_runtime_provenance", lambda: {"source_sha": source_sha})

    def fail_input(_root):
        raise reopen.ReopenScenarioFailure("synthetic input rejection")

    monkeypatch.setattr(reopen, "_fresh_input", fail_input)
    reopen_root.mkdir()
    assert reopen.run_fresh_qualification() == 21
    receipt_path = reopen_root / "fresh-reopen-result.json"
    assert receipt_path.stat().st_size < core.MAX_RECEIPT_BYTES
    assert core._reopen_failure_observation(reopen_root, source_sha) == {
        "receipt_state": "valid_reopen_failed", "producer_stage": "input",
    }
    assert core._reopen_failure_observation(reopen_root, "c" * 40)["receipt_state"] == "invalid"
    receipt_path.unlink()
    assert core._reopen_failure_observation(reopen_root, source_sha)["receipt_state"] == "missing"
    reopen_root.rmdir()

    closed = []
    ready = []

    class Process:
        def observe(self):
            application._atomic_json(reopen_root / "core-startup.json", {
                "schema_version": 1, "scenario": "reopen", "stage": "startup_ready",
            })
            application._atomic_json(receipt_path, {
                "schema_version": 1, "scenario": "reopen", "status": "failed",
                "source_sha": source_sha, "failure_stage": "reopen",
            })

        def mark_runtime_ready(self):
            ready.append(True)

        def poll(self):
            return 7

        def close(self, *, terminate):
            closed.append(terminate)
            diag._attempt_cleanup(lambda: None)

    class Api:
        def launch(self, _executable, _environment, _cwd, owned=None, expected_images=None):
            process = Process()
            owned.append(process)
            return process

    monkeypatch.setattr(core, "_validate_reopen_sources", lambda _reports: None)
    monkeypatch.setattr(core, "_independent_verifier", lambda: SimpleNamespace(
        _load_oracle=lambda _path: {}, assert_database=lambda *args: None,
    ))
    dependency = SimpleNamespace(
        QualificationFailure=diag.QualificationFailure,
        _WindowsApi=Api, _close_owned_processes=diag._close_owned_processes,
    )
    prior = {"relative_artifact_dir": child.name, "artifacts": {"database": {"sha256": core._hash(database)}}}
    observation = {"owned_cleanup": "not_attempted", "private_cleanup": "not_attempted"}
    stage = {"name": "fresh_reopen"}
    with pytest.raises(core.CandidateFailure, match="^fresh_reopen_process_failed$"):
        core._run_fresh_reopen(
            tmp_path, diag=dependency, relocated=tmp_path, environment={}, work=core_root,
            prior=prior, args=SimpleNamespace(expected_source_sha=source_sha, oracle=tmp_path / "oracle.json"),
            deadline=time.monotonic() + 1, output=tmp_path, stage=stage,
            failure_observation=observation,
        )
    assert observation["observed_process"] == "fresh_reopen_launcher_handle"
    assert observation["observed_exit_code"] == 7
    assert observation["startup_marker"] == "observed"
    assert observation["receipt_state"] == "valid_reopen_failed"
    assert observation["producer_stage"] == "reopen"
    assert observation["owned_cleanup"] == "complete"
    assert ready == [True] and closed == [True]


@pytest.mark.parametrize("fault", ["row", "schema", "user_version", "application_id", "baseline_copy", "post_replaced"])
def test_host_reopen_oracle_rejects_actual_database_mutation(tmp_path, fault):
    before, after = tmp_path / "before.sqlite", tmp_path / "after.sqlite"
    with closing(sqlite3.connect(before)) as connection, connection:
        connection.execute("CREATE TABLE measurements (value INTEGER)")
        connection.execute("INSERT INTO measurements VALUES (12)")
    shutil.copyfile(before, after)
    baseline_hash, original_hash = core._hash(before), core._hash(after)
    target = before if fault == "baseline_copy" else after
    if fault == "post_replaced":
        after.write_bytes(b"substituted")
    else:
        with closing(sqlite3.connect(target)) as connection, connection:
            if fault in {"row", "baseline_copy"}:
                connection.execute("UPDATE measurements SET value = 13")
            elif fault == "schema":
                connection.execute("CREATE INDEX changed_schema ON measurements(value)")
            elif fault == "user_version":
                connection.execute("PRAGMA user_version=42")
            else:
                connection.execute("PRAGMA application_id=42")
    with pytest.raises(core.CandidateFailure):
        core._assert_reopen_databases_preserved(before, after, before_hash=baseline_hash,
            after_hash=original_hash if fault == "post_replaced" else core._hash(after))


def test_host_reopen_sources_rejects_changed_public_input(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    fixtures = Path(__file__).parent / "fixtures/windows_candidate/reports"
    for i in range(5):
        shutil.copyfile(fixtures / f"report-{i}.pdf", reports / f"REF001_2024-01-01_{i}.pdf")
    core._validate_reopen_sources(reports)
    (reports / "REF001_2024-01-01_1.pdf").write_bytes(b"changed public input")
    with pytest.raises(core.CandidateFailure, match="fresh_reopen_sources_changed"):
        core._validate_reopen_sources(reports)


def test_host_reopen_oracle_rejects_invalid_sqlite_with_closed_failure(tmp_path):
    database = tmp_path / "invalid.sqlite"
    database.write_bytes(b"not a SQLite database" * 32)
    with pytest.raises(core.CandidateFailure, match="fresh_reopen_database_invalid"):
        core._reopen_database_semantics(database)
