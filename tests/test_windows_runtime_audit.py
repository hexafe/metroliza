from __future__ import annotations

import ctypes
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from metroliza.shared import diagnostic_runtime_audit as audit
from scripts import qualify_windows_diagnostics as qualification
from scripts.windows_owned_process_probe import RuntimeEvidence, verified_runtime_order

ROOT = Path(__file__).resolve().parents[1]


def _frame(module, name, back=None):
    return SimpleNamespace(
        f_globals={"__name__": module}, f_code=SimpleNamespace(co_name=name), f_back=back
    )


def _journal(root, nonce, events):
    audit._write(root, "installed.json", {"schema_version": 1, "nonce": nonce, "installed": True})
    for ordinal, event in enumerate(events, 1):
        audit._write(
            root,
            f"event-{ordinal:02}.json",
            {"schema_version": 1, "nonce": nonce, "ordinal": ordinal, **event},
        )


def _proof(supervised=False, helpers=True):
    roles = (["package_launcher", "package_launcher"] if supervised else []) + [
        "package_application"
    ]
    if helpers:
        roles += ["system_cmd", "system_conhost"]
    members = [
        {
            "role": role,
            "identity": "fixed_file_verified",
            "first_phase": "startup",
            "last_phase": "startup",
            "parent_ordinal_advisory": index - 1 if index else "unknown",
            "lifecycle": "job_empty",
        }
        for index, role in enumerate(roles)
    ]
    return {
        "installed": True,
        "events": [{"kind": "platform_ver", "caller": "other", "phase": "startup"}]
        if helpers
        else [],
        "owned": {
            "schema_version": 1,
            "members": members,
            "assigned": len(roles),
            "unobserved": 0,
            "job_empty": True,
            "overflow": False,
            "observation_unavailable": False,
            "probe_effect": "extra_handle_queries_and_bounded_snapshot",
        },
        "probe_effect": "synchronous_private_prelaunch_journal_and_owned_handle_sampling",
    }


def test_command_and_required_frames_are_exact_not_basename_allowance():
    expected = r"C:\Windows\System32\cmd.exe"
    frame = _frame(
        "platform",
        "_syscmd_ver",
        _frame("platform", "win32_ver", _frame("setuptools.windows_support", "windows_only")),
    )
    assert audit.classify_call((expected, expected + ' /c "ver"'), frame, expected) == (
        "platform_ver",
        "setuptools",
    )
    for command in (
        "ver",
        expected + ' /c "ver & echo private"',
        expected + ' /c "echo synthetic"',
    ):
        assert audit.classify_call((expected, command), frame, expected)[0] == "other_command"
    assert (
        audit.classify_call((r"C:\private\cmd.exe", expected + ' /c "ver"'), frame, expected)[0]
        == "other_executable"
    )
    assert (
        audit.classify_call(
            (expected, expected + ' /c "ver"'), _frame("platform", "_syscmd_ver"), expected
        )[0]
        == "other_frames"
    )
    for _ in range(65):
        frame = _frame("private_module_name", "private_function", frame)
    assert audit.classify_call((expected, expected + ' /c "ver"'), frame, expected)[0] == "other_depth"


@pytest.mark.parametrize("signature_last_index", [1, 63, 64])
def test_platform_signature_must_be_proved_inside_unchanged_64_frame_window(signature_last_index):
    class OutsideObservationWindow:
        @property
        def f_globals(self):
            pytest.fail("classifier read beyond its 64-frame window")

    expected = r"C:\Windows\System32\cmd.exe"
    frame = OutsideObservationWindow()
    for index in reversed(range(64)):
        module, name = ("platform", "win32_ver") if index == signature_last_index else ("outer", "call")
        if index == 0:
            module, name = "platform", "_syscmd_ver"
        frame = _frame(module, name, frame)
    kind, _caller = audit.classify_call((expected, expected + ' /c "ver"'), frame, expected)
    assert kind == ("platform_ver" if signature_last_index < 64 else "other_depth")


def test_deep_outer_stack_does_not_discard_already_proved_exact_signature():
    outer = None
    for _ in range(80):
        outer = _frame("outer", "call", outer)
    frame = _frame("platform", "_syscmd_ver", _frame("platform", "win32_ver", outer))
    expected = r"C:\Windows\System32\cmd.exe"
    assert audit.classify_call((expected, expected + ' /c "ver"'), frame, expected)[0] == "platform_ver"
    assert audit.classify_call((expected, expected + ' /c "ver & echo synthetic"'), frame, expected)[0] == "other_command"
    assert audit.classify_call((r"C:\private\cmd.exe", expected + ' /c "ver"'), frame, expected)[0] == "other_executable"


def test_exactly_exhausted_64_frame_stack_reports_missing_signature_not_truncation():
    frame = None
    for _ in range(64):
        frame = _frame("outer", "call", frame)
    expected = r"C:\Windows\System32\cmd.exe"
    assert audit.classify_call((expected, expected + ' /c "ver"'), frame, expected) == (
        "other_frames", "other"
    )


@pytest.mark.parametrize("kind", sorted(audit.KINDS - {"platform_ver"}))
def test_closed_rejection_discriminator_never_admits_unknown_command(tmp_path, kind):
    nonce = "1" * 32
    event = {"kind": kind, "caller": "other", "phase": "startup"}
    _journal(tmp_path, nonce, [event])
    assert audit.read_evidence(tmp_path, nonce) == [event]
    proof = _proof(False)
    proof["events"] = [event]
    with pytest.raises(ValueError, match="runtime_evidence_invalid"):
        verified_runtime_order(proof, supervised=False)


@pytest.mark.parametrize("arguments", [(), ("private",), (None, "private"), ("private", ["private"])])
def test_runtime_audit_exposes_only_closed_argument_failure(arguments):
    assert audit.classify_call(arguments, None, "expected") == ("other_arguments", "other")


def test_gate_off_installs_nothing(monkeypatch):
    monkeypatch.delenv(audit.GATE, raising=False)
    monkeypatch.setattr(audit, "_install", lambda: pytest.fail("ordinary launch must not install"))
    audit.install()


@pytest.mark.parametrize(
    "defect",
    ["nonce", "missing", "gap", "partial", "extra", "symlink", "hardlink", "overflow", "duplicate"],
)
def test_private_journal_rejects_missing_stale_or_unbounded_evidence(tmp_path, defect):
    nonce = "1" * 32
    event = {"kind": "platform_ver", "caller": "other", "phase": "startup"}
    _journal(tmp_path, nonce, [event])
    assert audit.read_evidence(tmp_path, nonce) == [event]
    if defect == "nonce":
        nonce = "2" * 32
    elif defect == "missing":
        (tmp_path / "installed.json").unlink()
    elif defect == "gap":
        (tmp_path / "event-01.json").rename(tmp_path / "event-02.json")
    elif defect == "partial":
        (tmp_path / "event-01.json").write_text('{"nonce":')
    elif defect == "extra":
        (tmp_path / "private-unexpected").touch()
    elif defect in {"symlink", "hardlink"}:
        original = tmp_path / "event-01.json"
        outside = tmp_path.parent / (tmp_path.name + "-outside")
        original.rename(outside)
        if defect == "symlink":
            try:
                original.symlink_to(outside)
            except OSError:
                pytest.skip("symlink unavailable for native ordinary user")
        else:
            os.link(outside, original)
    elif defect == "overflow":
        for index in range(2, 18):
            audit._write(
                tmp_path,
                f"event-{index:02}.json",
                {"schema_version": 1, "nonce": nonce, "ordinal": index, **event},
            )
    elif defect == "duplicate":
        with pytest.raises(FileExistsError):
            audit._write(tmp_path, "event-01.json", {})
        return
    with pytest.raises((ValueError, OSError)):
        audit.read_evidence(tmp_path, nonce)


@pytest.mark.parametrize("supervised", [False, True])
@pytest.mark.parametrize("helpers", [False, True])
def test_runtime_proof_keeps_physical_counts_and_exact_launcher_order(supervised, helpers):
    proof = _proof(supervised, helpers)
    order = verified_runtime_order(proof, supervised=supervised)
    size = (3 if supervised else 1) + (2 if helpers else 0)
    assert len(order) == size
    topology = qualification.ProcessTopology(
        2 if supervised else 0, 1, 0, size, size, order, True, proof
    )
    qualification._validate_topology_record(
        qualification._topology_record(topology), supervised=supervised
    )
    assert topology.assigned_processes == size


@pytest.mark.parametrize("supervised", [False, True])
def test_lazy_numpy_version_query_after_ready_keeps_exact_owned_chain(supervised):
    proof = _proof(supervised)
    proof["events"][0].update(caller="numpy", phase="after_ready")
    for member in proof["owned"]["members"][-2:]:
        member.update(first_phase="running", last_phase="running")
    order = verified_runtime_order(proof, supervised=supervised)
    assert len(order) == (5 if supervised else 3)
    assert order[-2:] == ("windows_version_command", "windows_version_console")
    topology = qualification.ProcessTopology(
        2 if supervised else 0, 1, 0, len(order), len(order), order, True, proof
    )
    qualification._validate_topology_record(
        qualification._topology_record(topology), supervised=supervised,
        require_runtime_evidence=True,
    )


@pytest.mark.parametrize("defect", [
    "other_caller", "setuptools_caller", "other_command", "other_frames", "unknown_phase", "event_startup",
    "cmd_first_startup", "cmd_last_startup", "console_first_startup", "console_last_startup",
    "helper_drain", "wrong_parent", "unknown_parent", "unknown_image", "extra_event", "live", "gap", "unavailable",
])
def test_after_ready_numpy_query_still_requires_matching_phase_and_complete_proof(defect):
    proof = _proof()
    proof["events"][0].update(caller="numpy", phase="after_ready")
    members = proof["owned"]["members"]
    for member in members[-2:]:
        member.update(first_phase="running", last_phase="running")
    if defect in {"other_caller", "setuptools_caller"}:
        proof["events"][0]["caller"] = defect.removesuffix("_caller")
    elif defect in {"other_command", "other_frames"}:
        proof["events"][0]["kind"] = defect
    elif defect == "unknown_phase":
        proof["events"][0]["phase"] = "unknown"
    elif defect == "event_startup":
        proof["events"][0]["phase"] = "startup"
    elif defect.startswith(("cmd_", "console_")):
        helper, boundary, _ = defect.split("_")
        members[-2 if helper == "cmd" else -1][boundary + "_phase"] = "startup"
    elif defect == "wrong_parent":
        members[-1]["parent_ordinal_advisory"] = 0
    elif defect == "unknown_parent":
        members[-1]["parent_ordinal_advisory"] = "unknown"
    elif defect == "helper_drain":
        members[-1]["last_phase"] = "drain"
    elif defect == "unknown_image":
        members[-1]["identity"] = "unknown"
    elif defect == "extra_event":
        proof["events"] *= 2
    elif defect == "live":
        proof["owned"]["job_empty"] = False
    elif defect == "gap":
        proof["owned"]["unobserved"] = 1
    elif defect == "unavailable":
        proof["owned"]["observation_unavailable"] = True
    with pytest.raises(ValueError, match="runtime_evidence_invalid"):
        verified_runtime_order(proof, supervised=False)


@pytest.mark.parametrize(
    "defect",
    [
        "no_event",
        "no_helpers",
        "other_event",
        "late",
        "two_events",
        "wrong_role",
        "unknown_image",
        "wrong_parent",
        "parent_reused",
        "late_helper",
        "live",
        "gap",
        "unavailable",
        "overflow",
        "wrong_count",
    ],
)
@pytest.mark.parametrize("supervised", [False, True])
def test_event_and_native_chain_must_agree_both_directions(supervised, defect):
    proof = _proof(supervised)
    owned = proof["owned"]
    if defect == "no_event":
        proof["events"] = []
    elif defect == "no_helpers":
        owned["members"] = owned["members"][:-2]
        owned["assigned"] -= 2
    elif defect == "other_event":
        proof["events"][0]["kind"] = "other"
    elif defect == "late":
        proof["events"][0]["phase"] = "after_ready"
    elif defect == "two_events":
        proof["events"] *= 2
    elif defect == "wrong_role":
        owned["members"][-1]["role"] = "system_powershell"
    elif defect == "unknown_image":
        owned["members"][-1]["identity"] = "unknown"
    elif defect == "wrong_parent":
        owned["members"][-1]["parent_ordinal_advisory"] = 0
    elif defect == "parent_reused":
        owned["members"][-1]["parent_ordinal_advisory"] = "unknown"
    elif defect == "late_helper":
        owned["members"][-1]["last_phase"] = "running"
    elif defect == "live":
        owned["job_empty"] = False
    elif defect == "gap":
        owned["unobserved"] = 1
    elif defect == "unavailable":
        owned["observation_unavailable"] = True
    elif defect == "overflow":
        owned["overflow"] = True
    elif defect == "wrong_count":
        owned["assigned"] += 1
    with pytest.raises(ValueError):
        verified_runtime_order(proof, supervised=supervised)


def test_analysis_requires_exact_earliest_hook_source(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "runtime_audit_packaging", ROOT / "packaging/pyinstaller_common.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks = ROOT / "packaging/hooks/windows"
    hook = (
        "metroliza_rth_runtime_audit",
        str(hooks / "rthooks/metroliza_rth_runtime_audit.py"),
        "PYSOURCE",
    )
    implied = ("pyi_rth_setuptools", str(tmp_path / "pyi_rth_setuptools.py"), "PYSOURCE")
    module.validate_runtime_audit_hook([hook, implied], hooks)
    for scripts in (
        [],
        [implied, hook],
        [hook, hook],
        [(hook[0], str(tmp_path / Path(hook[1]).name), hook[2])],
    ):
        with pytest.raises(RuntimeError, match="hook order"):
            module.validate_runtime_audit_hook(scripts, hooks)


@pytest.mark.parametrize("supervised", [False, True])
def test_final_success_record_requires_audit_even_without_helpers(supervised):
    proof = _proof(supervised, helpers=False)
    order = verified_runtime_order(proof, supervised=supervised)
    topology = qualification.ProcessTopology(2 if supervised else 0, 1, 0, len(order), len(order), order, True, proof)
    record = qualification._topology_record(topology)
    qualification._validate_topology_record(record, supervised=supervised, require_runtime_evidence=True)
    record.pop("runtime_evidence")
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_topology_record(record, supervised=supervised, require_runtime_evidence=True)
    package = {"launcher_sha256": "a" * 64, "application_sha256": "b" * 64}
    payload = {"launcher_image_sha256": package["launcher_sha256"],
               "application_image_sha256": package["application_sha256"],
               "direct": [], "supervised": []}
    for kind, is_supervised in (("direct", False), ("supervised", True)):
        for _ in range(2):
            paired = _proof(is_supervised, helpers=False)
            paired_order = verified_runtime_order(paired, supervised=is_supervised)
            item = qualification.ProcessTopology(2 if is_supervised else 0, 1, 0, len(paired_order),
                                                 len(paired_order), paired_order, True, paired)
            payload[kind].append(qualification._topology_record(item))
    qualification._validate_topology(payload, package)
    payload["supervised" if supervised else "direct"][1].pop("runtime_evidence")
    with pytest.raises(qualification.QualificationFailure):
        qualification._validate_topology(payload, package)


def _local_evidence(root):
    root.mkdir()
    evidence = object.__new__(RuntimeEvidence)
    evidence.root = root
    evidence.nonce = "f" * 32
    evidence.failure_factory = lambda: qualification.QualificationFailure("output_failed")
    evidence.root_identity = evidence._identity()
    evidence.probe = SimpleNamespace(phase="startup", emit=lambda: None)
    return evidence


def test_runtime_cleanup_removes_only_its_bounded_regular_journal(tmp_path):
    evidence = _local_evidence(tmp_path / "owned")
    _journal(evidence.root, evidence.nonce, [])
    evidence.ready()
    evidence.close()
    assert not evidence.root.exists()


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("point", ["partial_unlink", "after_rmdir"])
def test_interrupted_journal_cleanup_retains_owner_until_actual_removal(
    tmp_path, monkeypatch, interrupt_type, point,
):
    evidence = _local_evidence(tmp_path / "owned")
    _journal(evidence.root, evidence.nonce, [{"kind": "platform_ver", "caller": "other", "phase": "startup"}])
    primary = interrupt_type("synthetic cleanup interruption")
    closed = []
    api = SimpleNamespace(close_process=lambda *_args, **_kwargs: closed.append(True))
    initial = qualification._ProcessObservation(1, 1, "application")
    process = qualification._WindowsProcess(api, 11, 12, 0.0, initial, ())
    process.runtime_evidence = evidence
    original = Path.unlink if point == "partial_unlink" else Path.rmdir
    interrupted = False

    def interrupt_path(path, *args, **kwargs):
        nonlocal interrupted
        result = original(path, *args, **kwargs)
        if not interrupted and (path.parent == evidence.root if point == "partial_unlink" else path == evidence.root):
            interrupted = True
            raise primary
        return result

    monkeypatch.setattr(Path, "unlink" if point == "partial_unlink" else "rmdir", interrupt_path)
    with pytest.raises(interrupt_type) as caught:
        process.close(terminate=True)
    assert caught.value is primary
    assert process.runtime_evidence is evidence
    process.close(terminate=True)
    assert not evidence.root.exists()
    assert process.runtime_evidence is None
    process.close(terminate=True)
    assert closed == [True]


@pytest.mark.parametrize("hardlink", [False, True])
def test_runtime_cleanup_uses_full_metadata_when_directory_cache_has_no_link_count(
    tmp_path, monkeypatch, hardlink
):
    evidence = _local_evidence(tmp_path / "owned")
    _journal(evidence.root, evidence.nonce, [])
    protected = tmp_path / "protected"
    if hardlink:
        os.link(evidence.root / "installed.json", protected)
    original_scandir = os.scandir

    @contextmanager
    def windows_directory_cache(path):
        with original_scandir(path) as entries:
            cached = []
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                incomplete = SimpleNamespace(
                    st_mode=info.st_mode, st_size=info.st_size, st_nlink=0,
                    st_ino=0, st_dev=0, st_file_attributes=0,
                )
                cached.append(SimpleNamespace(
                    name=entry.name, stat=lambda *, follow_symlinks, value=incomplete: value
                ))
            yield iter(cached)

    monkeypatch.setattr(os, "scandir", windows_directory_cache)
    if hardlink:
        before = protected.read_bytes()
        with pytest.raises(qualification.QualificationFailure):
            evidence._remove_journal()
        assert protected.read_bytes() == before and evidence.root.is_dir()
    else:
        evidence._remove_journal()
        assert not evidence.root.exists()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_runtime_constructor_owns_empty_root_even_when_identity_query_fails(tmp_path, monkeypatch, cleanup_fails):
    from scripts import windows_owned_process_probe as probe_module

    monkeypatch.setattr(probe_module, "OwnedProcessProbe", lambda *_: SimpleNamespace(phase="startup"))
    def no_identity(_self):
        raise OSError("synthetic identity failure")
    monkeypatch.setattr(RuntimeEvidence, "_identity", no_identity)
    if cleanup_fails:
        def no_cleanup(_self):
            raise OSError("synthetic cleanup failure")
        monkeypatch.setattr(Path, "rmdir", no_cleanup)
    environment = {}
    with pytest.raises(qualification.QualificationFailure) as caught:
        RuntimeEvidence(None, tmp_path, tmp_path, environment,
                        lambda: qualification.QualificationFailure("output_failed"))
    assert caught.value.qualification_cleanup == ("failed" if cleanup_fails else "complete")
    assert len(list(tmp_path.iterdir())) == (1 if cleanup_fails else 0)
    assert environment == {}


@pytest.mark.parametrize("defect", ["replace", "nested", "oversized", "unrecognized", "symlink", "hardlink"])
def test_runtime_cleanup_refuses_replaced_root_or_unknown_content(tmp_path, defect):
    evidence = _local_evidence(tmp_path / "owned")
    protected = tmp_path / "protected"
    protected.write_bytes(b"synthetic preserved")
    if defect == "replace":
        evidence.root.rename(tmp_path / "previous")
        evidence.root.mkdir()
    elif defect == "nested":
        (evidence.root / "event-01.json").mkdir()
        (evidence.root / "event-01.json" / "nested").write_bytes(b"keep")
    elif defect == "oversized":
        (evidence.root / "event-01.json").write_bytes(b"x" * 1025)
    elif defect == "unrecognized":
        (evidence.root / "unknown").write_bytes(b"keep")
    elif defect == "hardlink":
        os.link(protected, evidence.root / "event-01.json")
    else:
        try:
            (evidence.root / "event-01.json").symlink_to(protected)
        except OSError:
            pytest.skip("symlink unavailable for native ordinary user")
    with pytest.raises(qualification.QualificationFailure):
        evidence.close()
    assert evidence.root.is_dir() and protected.read_bytes() == b"synthetic preserved"


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows owned process and audit control")
@pytest.mark.parametrize(
    "mode", ["none", "ver", "deep_ver", "late_numpy", "late_ver", "late_other", "hard", "other", "write_failure", "blocked_install", "outer", "concurrent"]
)
def test_native_journal_correlates_owned_roles_and_survives_hard_exit(tmp_path, monkeypatch, mode):
    api = qualification._WindowsApi()
    advapi = api.advapi
    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
    assert qualification._pe_subsystem(pythonw) == 2
    launcher = pythonw.with_name("python.exe")
    if mode == "outer":
        # Two distinct fixed GUI images model the package's two GUI PEs. A
        # console interpreter creates unrelated conhosts in this native control.
        runtime = tmp_path / "control-runtime"
        runtime.mkdir()
        launcher = runtime / "control-launcher.exe"
        application = runtime / "control-application.exe"
        for target in (launcher, application):
            shutil.copyfile(pythonw, target)
            assert qualification._pe_subsystem(target) == 2
        for name in (f"python{sys.version_info.major}{sys.version_info.minor}.dll",
                     "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            dependency = Path(sys.base_prefix) / name
            if dependency.is_file():
                shutil.copyfile(dependency, runtime / name)
        pythonw = application
    fixture = ROOT / "tests/fixtures/windows_runtime_audit_control.py"
    script_mode = "ver" if mode == "concurrent" else mode
    executable = launcher if mode == "outer" else pythonw
    command = subprocess.list2cmdline([str(executable), str(fixture), script_mode])

    class FixedControl:
        def __getattr__(self, name):
            return getattr(advapi, name)

        def CreateProcessAsUserW(self, *args):
            values = list(args)
            values[2] = ctypes.create_unicode_buffer(command)
            return advapi.CreateProcessAsUserW(*values)

        def CreateProcessWithTokenW(self, *args):
            values = list(args)
            values[3] = ctypes.create_unicode_buffer(command)
            return advapi.CreateProcessWithTokenW(*values)

    monkeypatch.setattr(api, "advapi", FixedControl())
    owned = []
    evidences = []
    complete = False
    failure = None
    proofs = []
    expected_exit = 97 if mode in {"write_failure", "blocked_install"} else 9 if mode == "hard" else 0
    try:
        for index in range(2 if mode == "concurrent" else 1):
            root = tmp_path / str(index)
            root.mkdir()
            environment = qualification._sanitized_environment(root, root, root / "state", "normal")
            if mode == "outer":
                environment["PYTHONHOME"] = sys.base_prefix
            evidence = RuntimeEvidence(
                api,
                root,
                root,
                environment,
                lambda: qualification.QualificationFailure("output_failed"),
            )
            evidence.probe.images = (
                ("package_launcher", launcher),
                ("package_application", pythonw),
            ) + evidence.probe.images[2:]
            evidences.append(evidence)
            api.launch(
                executable,
                environment,
                root,
                owned=owned,
                runtime_evidence=evidence,
                expected_images=(launcher, pythonw),
                defer_resume=True,
            )
        assert all(
            process.runtime_evidence is evidence for process, evidence in zip(owned, evidences)
        )
        for process in owned:
            process.resume()
        deadline = time.monotonic() + 30
        concurrent_released = False
        while time.monotonic() < deadline:
            if mode == "concurrent":
                # Keep both controlled applications alive throughout the two
                # Job observations. This case proves journal separation, not
                # image-query behavior while a peer is exiting; the other
                # modes and the negative identity controls cover that edge.
                if not concurrent_released:
                    for process in owned:
                        process.observe()
                    if all(
                        (tmp_path / str(index) / "control-ready").exists()
                        for index in range(len(owned))
                    ):
                        for index in range(len(owned)):
                            (tmp_path / str(index) / "control-finish").touch()
                        concurrent_released = True
            else:
                for index, process in enumerate(owned):
                    process.observe()
                    if (tmp_path / str(index) / "control-ready").exists():
                        if mode.startswith("late_"):
                            process.mark_runtime_ready()
                        (tmp_path / str(index) / "control-finish").touch()
            if all(
                process.poll() is not None and process.active_processes() == 0 for process in owned
            ):
                break
            time.sleep(0.005)
        assert all(
            process.poll() == expected_exit and process.active_processes() == 0 for process in owned
        )
        for process, evidence in zip(owned, evidences):
            if mode in {"write_failure", "blocked_install"}:
                with pytest.raises(qualification.QualificationFailure):
                    evidence.proof()
            else:
                proof = evidence.proof()
                proofs.append(proof)
                if mode in {"other", "late_ver", "late_other"}:
                    with pytest.raises(ValueError):
                        verified_runtime_order(proof, supervised=False)
                else:
                    order = verified_runtime_order(proof, supervised=mode == "outer")
                    assert process._assigned_processes == len(order)
                    if mode == "late_numpy":
                        assert proof["events"] == [{"kind": "platform_ver", "caller": "numpy", "phase": "after_ready"}]
                        assert len(order) == 3
        if mode == "concurrent":
            assert (
                evidences[0].nonce != evidences[1].nonce and evidences[0].root != evidences[1].root
            )
            assert not set(evidences[0].probe.records) & set(evidences[1].probe.records)
            with pytest.raises(ValueError):
                audit.read_evidence(evidences[0].root, evidences[1].nonce)
        serialized = json.dumps(proofs)
        assert all(
            evidence.nonce not in serialized and str(evidence.root) not in serialized
            for evidence in evidences
        )
        complete = True
    except Exception as error:
        # Cleanup must run outside this handled assertion/proof exception, so
        # its failure projection cannot hide the native control's first cause.
        failure = error
    finally:
        qualification._close_owned_processes(owned, terminate=not complete)
    if failure is not None:
        if isinstance(failure, qualification.QualificationFailure):
            native = failure.native_observation
            raise AssertionError(json.dumps({
                "failure_id": failure.failure_id,
                "reason": failure.qualification_reason,
                "cleanup": failure.qualification_cleanup,
                "native": native.receipt() if native is not None else None,
            }, sort_keys=True)) from failure
        raise failure
    assert all(not evidence.root.exists() for evidence in evidences)


def test_runtime_ready_wait_is_inert_outside_opt_in(monkeypatch):
    monkeypatch.delenv(audit.GATE, raising=False)
    monkeypatch.setattr(audit, "_wait_for_host_ready", lambda *_: pytest.fail("ordinary startup waited"))
    audit.wait_for_host_ready()


@pytest.mark.parametrize("delivery_time", [0.5, 1.0, 1.1])
def test_runtime_ready_wait_accepts_only_ack_before_deadline(tmp_path, monkeypatch, delivery_time):
    nonce = "a" * 32
    _journal(tmp_path, nonce, [])
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(tmp_path))
    monkeypatch.setenv(audit.NONCE, nonce)
    clock = [0.0]
    monkeypatch.setattr(audit.time, "monotonic", lambda: clock[0])

    def deliver(_seconds):
        (tmp_path / "ready").touch(exist_ok=False)
        clock[0] = delivery_time

    monkeypatch.setattr(audit.time, "sleep", deliver)
    if delivery_time < 1:
        audit.wait_for_host_ready(seconds=1)
    else:
        with pytest.raises(ValueError, match="^runtime_ready_timeout$"):
            audit.wait_for_host_ready(seconds=1)


@pytest.mark.parametrize("defect", ["directory", "nonempty", "hardlink", "symlink", "nonce", "missing_install"])
def test_runtime_ready_wait_rejects_unsafe_or_stale_ack(tmp_path, monkeypatch, defect):
    nonce = "a" * 32
    _journal(tmp_path, nonce, [])
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(tmp_path))
    monkeypatch.setenv(audit.NONCE, nonce)
    marker = tmp_path / "ready"
    if defect == "directory":
        marker.mkdir()
    elif defect in {"hardlink", "symlink"}:
        other = tmp_path / "unrelated"
        other.touch()
        if defect == "hardlink":
            os.link(other, marker)
        else:
            try:
                marker.symlink_to(other)
            except OSError:
                pytest.skip("symlink unavailable for native ordinary user")
    else:
        marker.write_bytes(b"invalid" if defect == "nonempty" else b"")
        if defect == "nonce":
            monkeypatch.setenv(audit.NONCE, "b" * 32)
        if defect == "missing_install":
            (tmp_path / "installed.json").unlink()
    with pytest.raises(ValueError, match="^runtime_audit_invalid$"):
        audit.wait_for_host_ready(seconds=1)


def test_runtime_ready_wait_rejects_replaced_root(tmp_path, monkeypatch):
    root = tmp_path / "owned"
    root.mkdir()
    nonce = "a" * 32
    _journal(root, nonce, [])
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(root))
    monkeypatch.setenv(audit.NONCE, nonce)

    def replace(_seconds):
        root.rename(tmp_path / "old")
        root.mkdir()
        (root / "ready").touch()

    monkeypatch.setattr(audit.time, "sleep", replace)
    with pytest.raises(ValueError, match="^runtime_audit_invalid$"):
        audit.wait_for_host_ready(seconds=1)


def test_runtime_ready_wait_rechecks_deadline_after_marker_observation(tmp_path, monkeypatch):
    nonce = "a" * 32
    _journal(tmp_path, nonce, [])
    marker = tmp_path / "ready"
    marker.touch()
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(tmp_path))
    monkeypatch.setenv(audit.NONCE, nonce)
    clock = [0.0]
    original = Path.lstat
    monkeypatch.setattr(audit.time, "monotonic", lambda: clock[0])

    def delayed_stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == marker:
            clock[0] = 2.0
        return result

    monkeypatch.setattr(Path, "lstat", delayed_stat)
    with pytest.raises(ValueError, match="^runtime_ready_timeout$"):
        audit.wait_for_host_ready(seconds=1)


def test_runtime_ready_accepts_host_ack_delivered_before_wait(tmp_path, monkeypatch):
    nonce = "a" * 32
    _journal(tmp_path, nonce, [])
    (tmp_path / "ready").touch()
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(tmp_path))
    monkeypatch.setenv(audit.NONCE, nonce)
    audit.wait_for_host_ready(seconds=1)


@pytest.mark.parametrize("missing", [audit.ROOT, audit.NONCE])
def test_runtime_ready_missing_environment_is_closed(tmp_path, monkeypatch, missing):
    monkeypatch.setenv(audit.GATE, "1")
    monkeypatch.setenv(audit.ROOT, str(tmp_path))
    monkeypatch.setenv(audit.NONCE, "a" * 32)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(ValueError, match="^runtime_audit_invalid$"):
        audit.wait_for_host_ready()
