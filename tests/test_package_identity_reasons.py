"""Specific package-identity reasons, user notices and the self-repair exit (#1111).

The path policy itself (regular single-link files, no reparse points up to the
package root) is unchanged; these tests pin that a rejection by it is reported
as ``component_unsafe`` and that every other failure keeps its own reason. New
names are read through the module so that, on code without the change, each test
fails on its own assertion instead of at import.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from metroliza.shared import diagnostic_package as package
from metroliza.shared.diagnostic_package import COMPONENTS, MANIFEST_NAME, inspect_package
from scripts.build_diagnostic_manifest import write_supervision_manifest

PROVENANCE = COMPONENTS[-1]
ACTION = "Pobierz Metroliza ponownie i uruchom pobrany plik."


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "Metroliza próba ze spacjami"
    for name in (*COMPONENTS, "metroliza.exe"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-" + name.encode())
    (root / PROVENANCE).write_text(json.dumps({"git_sha": "a" * 40}), encoding="utf-8")
    write_supervision_manifest(root)
    return root


def _rewrite_manifest(root, change):
    path = root / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _windows_attributes(monkeypatch, attributes_by_path):
    """Make ``Path.lstat`` report Windows ``st_file_attributes`` for chosen paths."""
    real = Path.lstat

    def lstat(self, *args, **kwargs):
        info = real(self, *args, **kwargs)
        extra = attributes_by_path.get(self)
        if extra is None:
            return info
        values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        values.update(extra)
        return SimpleNamespace(**values)

    monkeypatch.setattr(Path, "lstat", lstat)


# --- every reason code -------------------------------------------------------

def test_verified_package_has_no_component_and_the_embedded_sha(root):
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.git_sha) == (True, "verified", "a" * 40)
    assert identity.component is None


def test_manifest_missing_is_its_own_reason(root):
    (root / MANIFEST_NAME).unlink()
    identity = inspect_package(root)
    assert (identity.valid, identity.reason) == (False, "manifest_missing")
    assert identity.component == MANIFEST_NAME


def test_missing_package_root_reports_the_missing_manifest(tmp_path):
    identity = inspect_package(tmp_path / "does-not-exist")
    assert (identity.valid, identity.reason) == (False, "manifest_missing")


@pytest.mark.parametrize("damage", ["garbage", "oversized", "extra_key", "bad_digest", "duplicate_key"])
def test_manifest_present_but_unusable_is_manifest_invalid(root, damage):
    path = root / MANIFEST_NAME
    if damage == "garbage":
        path.write_bytes(b"\xff\x00 not json")
    elif damage == "oversized":
        path.write_bytes(b" " * 5000)
    elif damage == "duplicate_key":
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"layout"', '"layout":"onedir","layout"', 1), encoding="utf-8")
    elif damage == "extra_key":
        _rewrite_manifest(root, lambda manifest: manifest.update(extra=1))
    else:
        _rewrite_manifest(root, lambda manifest: manifest["components"].update({COMPONENTS[0]: "zz"}))
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.component) == (
        False, "manifest_invalid", MANIFEST_NAME)


def test_manifest_that_is_a_symlink_is_manifest_invalid(root):
    try:
        (root / "other.json").write_bytes((root / MANIFEST_NAME).read_bytes())
        (root / MANIFEST_NAME).unlink()
        (root / MANIFEST_NAME).symlink_to(root / "other.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert inspect_package(root).reason == "manifest_invalid"


@pytest.mark.parametrize("component", COMPONENTS)
def test_missing_component_names_the_file(root, component):
    (root / component).unlink()
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.component) == (
        False, "component_missing", component)


def test_missing_parent_directory_of_a_component_is_component_missing(root):
    shutil.rmtree(root / "_internal")
    identity = inspect_package(root)
    assert (identity.reason, identity.component) == ("component_missing", "_internal/python311.dll")


@pytest.mark.parametrize("component", COMPONENTS)
def test_modified_component_names_the_file_and_keeps_the_manifest_sha(root, component):
    with (root / component).open("ab") as stream:
        stream.write(b"\x00")
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.component) == (
        False, "component_modified", component)
    assert identity.git_sha == "a" * 40


def test_oversized_component_is_component_modified(root, monkeypatch):
    monkeypatch.setattr(package, "MAX_COMPONENT_BYTES", 4)
    identity = inspect_package(root)
    assert (identity.reason, identity.component) == ("component_modified", COMPONENTS[0])


def test_provenance_of_another_build_is_a_mismatch_without_a_trusted_sha(root):
    provenance = root / PROVENANCE
    provenance.write_text(json.dumps({"git_sha": "b" * 40}), encoding="utf-8")
    # Keep the mix self-consistent: the manifest lists the new provenance hash.
    _rewrite_manifest(root, lambda manifest: manifest["components"].update(
        {PROVENANCE: package.component_hash(root, PROVENANCE)}))
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.component) == (
        False, "provenance_mismatch", PROVENANCE)
    assert identity.git_sha == "unknown"


def test_manifest_claiming_another_commit_is_a_provenance_mismatch(root):
    _rewrite_manifest(root, lambda manifest: manifest.update(git_sha="c" * 40))
    identity = inspect_package(root)
    assert (identity.reason, identity.git_sha) == ("provenance_mismatch", "unknown")


def test_unsafe_component_shapes_from_the_unchanged_policy(root):
    """A symlink, a hard link and a reparse-point component are all component_unsafe."""
    target = root / COMPONENTS[1]
    twin = root / "twin.bin"
    twin.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.link(twin, target)
    except OSError:
        pytest.skip("hard links unavailable")
    assert os.stat(target).st_nlink == 2
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.component) == (
        False, "component_unsafe", COMPONENTS[1])
    target.unlink()
    try:
        target.symlink_to(twin)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    identity = inspect_package(root)
    assert (identity.reason, identity.component) == ("component_unsafe", COMPONENTS[1])


@pytest.mark.parametrize("where", ["component", "parent_directory", "package_root"])
def test_windows_reparse_point_on_component_or_directories_is_component_unsafe(
    root, monkeypatch, where
):
    paths = {
        "component": root / COMPONENTS[2],
        "parent_directory": root / "_internal",
        "package_root": root,
    }
    flag = 0x400 | (0x10 if where != "component" else 0x20)
    _windows_attributes(monkeypatch, {paths[where]: {"st_file_attributes": flag}})
    identity = inspect_package(root)
    assert (identity.valid, identity.reason) == (False, "component_unsafe")
    assert identity.component in COMPONENTS


def test_unreadable_component_is_reported_as_such(root, monkeypatch):
    real_open = os.open

    def deny(path, *args, **kwargs):
        if os.fspath(path).endswith("python311.dll"):
            raise PermissionError(13, "denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny)
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.component) == (
        False, "component_unreadable", "_internal/python311.dll")


def test_component_changing_while_it_is_hashed_is_component_unreadable(root, monkeypatch):
    real_sha256 = hashlib.sha256

    class Growing:
        def __init__(self):
            self.inner = real_sha256()
            self.grown = False

        def update(self, block):
            self.inner.update(block)
            if not self.grown:
                self.grown = True
                with (root / COMPONENTS[0]).open("ab") as stream:
                    stream.write(b"x")

        def hexdigest(self):
            return self.inner.hexdigest()

    monkeypatch.setattr(package, "hashlib", SimpleNamespace(sha256=Growing))
    identity = inspect_package(root)
    assert (identity.reason, identity.component) == ("component_unreadable", COMPONENTS[0])


def test_component_hash_reports_the_same_reasons(root):
    (root / COMPONENTS[1]).unlink()
    with pytest.raises(ValueError) as missing:
        package.component_hash(root, COMPONENTS[1])
    assert (missing.value.reason, missing.value.component) == ("component_missing", COMPONENTS[1])
    with pytest.raises(ValueError, match="^invalid_component$"):
        package.component_hash(root, "../another.exe")


def test_unexpected_failure_keeps_the_generic_code(root, monkeypatch):
    def unexpected_os(_root, _name):
        raise OSError("unexpected")

    monkeypatch.setattr(package, "component_hash", unexpected_os)
    identity = inspect_package(root)
    assert (identity.valid, identity.reason, identity.component) == (
        False, "package_unavailable", None)


def test_reason_codes_are_a_closed_set_and_components_are_fixed_names(root):
    seen = set()
    for component in (*COMPONENTS, MANIFEST_NAME):
        copy = root.parent / ("copy-" + component.replace("/", "_"))
        shutil.copytree(root, copy)
        (copy / component).unlink()
        identity = inspect_package(copy)
        seen.add(identity.reason)
        assert identity.reason in package.REASONS
        assert identity.component in (*COMPONENTS, MANIFEST_NAME)
    assert seen == {"component_missing", "manifest_missing"}
    assert {"verified", "manifest_missing", "manifest_invalid", "component_missing",
            "component_modified", "component_unsafe", "component_unreadable",
            "provenance_mismatch", "package_unavailable"} == set(package.REASONS)


# --- notice text -------------------------------------------------------------

NOTICES = [
    ("component_missing", "metroliza_ocr_worker.exe",
     "brakuje pliku metroliza_ocr_worker.exe (mógł go usunąć program antywirusowy albo "
     "kopiowanie zostało przerwane)"),
    ("component_modified", "_internal/python311.dll",
     "plik python311.dll jest zmieniony lub uszkodzony"),
    ("component_unsafe", "_internal/base_library.zip",
     "plik base_library.zip jest dowiązaniem symbolicznym lub twardym albo leży w folderze "
     "będącym dowiązaniem"),
    ("component_unreadable", "metroliza_application.exe",
     "nie można odczytać pliku metroliza_application.exe"),
    ("provenance_mismatch", PROVENANCE, "pliki pochodzą z różnych wersji Metroliza"),
    ("manifest_missing", MANIFEST_NAME, "brakuje opisu pakietu (supervision_manifest.json)"),
    ("manifest_invalid", MANIFEST_NAME, "opis pakietu (supervision_manifest.json) jest uszkodzony"),
    ("package_unavailable", None, "brak lub niezgodność składników pakietu"),
]


@pytest.mark.parametrize("reason,component,expected", NOTICES)
def test_notice_names_the_file_and_ends_with_the_action(reason, component, expected):
    notice = package.package_notice(package.PackageIdentity(False, reason, component=component))
    assert notice.startswith("Nie można uruchomić aplikacji: ")
    assert expected in notice
    assert notice.endswith(ACTION)


@pytest.mark.parametrize("component", ["C:\\Users\\someone\\secret.exe", "../x", "", None, 3])
def test_notice_never_echoes_a_name_outside_the_fixed_list(component):
    for reason in ("component_missing", "component_modified", "component_unsafe",
                   "component_unreadable"):
        notice = package.package_notice(package.PackageIdentity(False, reason, component=component))
        assert "someone" not in notice and "../" not in notice
        assert "brak lub niezgodność składników pakietu" in notice and notice.endswith(ACTION)


def test_identity_code_is_path_free_and_allowlisted():
    code = package.identity_code
    assert code(package.PackageIdentity(False, "component_modified", component=COMPONENTS[2])) == (
        "component_modified:python311.dll")
    assert code(package.PackageIdentity(False, "manifest_missing", component=MANIFEST_NAME)) == (
        "manifest_missing:supervision_manifest.json")
    assert code(package.PackageIdentity(False, "weird reason with C:\\path", component="C:\\x")) == (
        "package_unavailable")


# --- supervisor: notice and exit code ----------------------------------------

@pytest.fixture
def supervisor(root, tmp_path, monkeypatch):
    from metroliza.app import diagnostic_launcher as launcher
    from metroliza.shared.diagnostic_store import IncidentStore

    # These tests assert stderr notices on every host; native-dialog tests below
    # explicitly select Windows and mock MessageBoxW before calling main().
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="posix", getenv=os.getenv))
    for name in ("METROLIZA_RUNTIME_REPAIR_AVAILABLE", "METROLIZA_STARTUP_SMOKE",
                 "METROLIZA_DIAGNOSTIC_QUALIFICATION"):
        monkeypatch.delenv(name, raising=False)
    store = IncidentStore(tmp_path / "state")
    monkeypatch.setattr(launcher, "IncidentStore", lambda: store)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(root / "metroliza.exe"))
    monkeypatch.setattr(sys, "argv", ["metroliza.exe"])
    return SimpleNamespace(launcher=launcher, store=store, root=root)


def _damage(root, kind):
    if kind == "component_missing":
        (root / COMPONENTS[1]).unlink()
    elif kind == "component_modified":
        (root / COMPONENTS[2]).write_bytes(b"other")
    elif kind == "manifest_missing":
        (root / MANIFEST_NAME).unlink()
    elif kind == "manifest_invalid":
        (root / MANIFEST_NAME).write_bytes(b"{")
    elif kind == "provenance_mismatch":
        _rewrite_manifest(root, lambda manifest: manifest.update(git_sha="c" * 40))


@pytest.mark.parametrize("kind,expected", [
    ("component_missing", "brakuje pliku metroliza_ocr_worker.exe"),
    ("component_modified", "plik python311.dll jest zmieniony lub uszkodzony"),
    ("manifest_missing", "brakuje opisu pakietu (supervision_manifest.json)"),
    ("manifest_invalid", "opis pakietu (supervision_manifest.json) jest uszkodzony"),
    ("provenance_mismatch", "pliki pochodzą z różnych wersji Metroliza"),
])
def test_supervisor_shows_the_precise_notice_and_exits_one(supervisor, capsys, kind, expected):
    _damage(supervisor.root, kind)
    assert supervisor.launcher.main() == 1
    error = capsys.readouterr().err
    assert expected in error and ACTION in error
    assert "brak lub niezgodność składników pakietu" not in error


def test_supervisor_exits_75_without_a_notice_when_native_repair_is_available(
    supervisor, capsys, monkeypatch
):
    launcher = supervisor.launcher
    assert launcher.EXIT_PACKAGE_REPAIR_REQUESTED == 75
    assert launcher.REPAIR_AVAILABLE_ENV == "METROLIZA_RUNTIME_REPAIR_AVAILABLE"
    _damage(supervisor.root, "component_modified")
    persisted = []
    real_persist = launcher._persist_unstarted_bounded

    def record(store, observed, git_sha):
        persisted.append((observed.launch, observed.handshake, observed.channel,
                          observed.exit_code, observed.termination, git_sha))
        return real_persist(store, observed, git_sha)

    monkeypatch.setattr(launcher, "_persist_unstarted_bounded", record)
    assert launcher.main() == 1
    plain = list(persisted)
    initial = capsys.readouterr()
    assert "plik python311.dll jest zmieniony lub uszkodzony" in initial.err
    assert initial.err.rstrip().endswith(ACTION) and initial.out == ""
    persisted.clear()
    monkeypatch.setenv("METROLIZA_RUNTIME_REPAIR_AVAILABLE", "1")
    assert launcher.main() == 75
    captured = capsys.readouterr()
    assert captured.err == "" and captured.out == ""
    assert persisted == plain and len(plain) == 1
    # The unstarted incident really reached the store in both runs.
    assert len(supervisor.store.list_reports().reports) == 2


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "2"])
def test_only_the_exact_repair_value_requests_exit_75(supervisor, capsys, monkeypatch, value):
    _damage(supervisor.root, "component_missing")
    monkeypatch.setenv("METROLIZA_RUNTIME_REPAIR_AVAILABLE", value)
    assert supervisor.launcher.main() == 1
    assert "brakuje pliku" in capsys.readouterr().err


def test_repair_variable_does_not_change_a_valid_package(supervisor, monkeypatch):
    launcher = supervisor.launcher
    monkeypatch.setenv("METROLIZA_RUNTIME_REPAIR_AVAILABLE", "1")
    started = []

    def fake_run(argv, *, store, git_sha, **_kwargs):
        started.append((argv, git_sha))
        return SimpleNamespace(
            observation=SimpleNamespace(exit_code=3),
            storage_status=launcher.StoreStatus.SAVED,
        )

    monkeypatch.setattr(launcher, "run_with_store", fake_run)
    assert launcher.main() == 3
    assert started[0][0][0].endswith("metroliza_application.exe") and started[0][1] == "a" * 40


def test_supervisor_shows_the_precise_notice_in_a_native_message_box(supervisor, monkeypatch):
    import ctypes

    launcher = supervisor.launcher
    boxes = []
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        MessageBoxW=lambda *args: boxes.append(args))), raising=False)
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="nt", getenv=os.getenv))
    _damage(supervisor.root, "component_missing")
    assert launcher.main() == 1
    assert len(boxes) == 1 and boxes[0][2:] == ("Metroliza", 0x10)
    assert "brakuje pliku metroliza_ocr_worker.exe" in boxes[0][1] and boxes[0][1].endswith(ACTION)
    boxes.clear()
    monkeypatch.setenv("METROLIZA_RUNTIME_REPAIR_AVAILABLE", "1")
    assert launcher.main() == 75
    assert boxes == []


def test_qualification_mode_still_suppresses_the_notice(supervisor, capsys, monkeypatch):
    import ctypes

    launcher = supervisor.launcher
    boxes = []
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        MessageBoxW=lambda *args: boxes.append(args))), raising=False)
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="nt", getenv=os.getenv))
    monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
    monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "normal")
    _damage(supervisor.root, "component_missing")
    assert launcher.main() == 1
    assert boxes == []


# --- OCR worker --------------------------------------------------------------

@pytest.fixture
def ocr(root, monkeypatch):
    from metroliza.parsing import frozen_ocr_worker

    application = root / "metroliza_application.exe"
    monkeypatch.setattr(sys, "executable", str(application))
    return frozen_ocr_worker


def test_ocr_worker_launch_accepts_only_a_verified_package(ocr, root):
    assert ocr._worker_executable() == root / "metroliza_ocr_worker.exe"


@pytest.mark.parametrize("kind,code", [
    ("component_missing", "ocr_package_identity_failed:component_missing:metroliza_ocr_worker.exe"),
    ("component_modified", "ocr_package_identity_failed:component_modified:python311.dll"),
    ("manifest_missing", "ocr_package_identity_failed:manifest_missing:supervision_manifest.json"),
    ("provenance_mismatch",
     "ocr_package_identity_failed:provenance_mismatch:build_provenance.json"),
])
def test_ocr_worker_fails_closed_with_the_same_reason(ocr, root, kind, code):
    _damage(root, kind)
    with pytest.raises(ocr.OcrWorkerFailure) as failure:
        ocr._worker_executable()
    assert str(failure.value) == code


def test_ocr_worker_failure_code_never_contains_a_path(ocr, root):
    _damage(root, "component_missing")
    with pytest.raises(ocr.OcrWorkerFailure) as failure:
        ocr._worker_executable()
    assert str(root) not in str(failure.value) and os.sep not in str(failure.value)


def test_ocr_worker_requires_the_application_image_name(ocr, root, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(root / "something_else.exe"))
    with pytest.raises(ocr.OcrWorkerFailure, match="^ocr_package_identity_failed$"):
        ocr._worker_executable()


# --- portable envelope -------------------------------------------------------

ENTRY = Path(__file__).resolve().parents[1] / "packaging/metroliza_portable_entry.py"


@pytest.fixture
def portable(root):
    from hashlib import sha256

    from metroliza.app.version import VERSION_LABEL

    spec = importlib.util.spec_from_file_location("metroliza_portable_entry_reasons", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    launcher = root / module.LAUNCHER_NAME
    (root / module.SIDECAR_NAME).write_text(json.dumps({
        "git_sha": "a" * 40, "release_label": VERSION_LABEL, "dirty": False,
        "artifact": {"name": launcher.name, "size_bytes": launcher.stat().st_size,
                     "sha256": sha256(launcher.read_bytes()).hexdigest()},
    }), encoding="utf-8")
    return module


def test_portable_launch_records_the_rejected_identity(portable, root, monkeypatch):
    monkeypatch.setattr(portable.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawned"))
    (root / COMPONENTS[1]).unlink()
    rejected = []
    assert portable._launch(root, [], rejected) is None
    assert [(item.reason, item.component) for item in rejected] == [
        ("component_missing", COMPONENTS[1])]
    assert portable._launch(root, []) is None  # the optional list stays optional


def test_portable_sidecar_failure_is_not_blamed_on_a_component(portable, root):
    (root / portable.SIDECAR_NAME).unlink()
    rejected = []
    assert portable._launch(root, [], rejected) is None
    assert rejected == []


def _portable_main(portable, root, monkeypatch, *, synthetic=False):
    boxes = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root.parent), raising=False)
    monkeypatch.setattr(sys, "argv", ["metroliza.exe"])
    monkeypatch.setattr(portable, "PAYLOAD_DIRECTORY", root.name)
    monkeypatch.setattr(portable, "os", SimpleNamespace(name="nt", getenv=os.getenv))
    monkeypatch.setattr(portable, "ctypes", SimpleNamespace(windll=SimpleNamespace(
        user32=SimpleNamespace(MessageBoxW=lambda *args: boxes.append(args)))))
    if synthetic:
        monkeypatch.setenv("METROLIZA_STARTUP_SMOKE", "1")
        monkeypatch.setenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", "normal")
    else:
        monkeypatch.delenv("METROLIZA_STARTUP_SMOKE", raising=False)
        monkeypatch.delenv("METROLIZA_DIAGNOSTIC_QUALIFICATION", raising=False)
    return portable.main(), boxes


def test_portable_envelope_names_the_damaged_file(portable, root, monkeypatch):
    with (root / COMPONENTS[2]).open("ab") as stream:
        stream.write(b"\x00")
    code, boxes = _portable_main(portable, root, monkeypatch)
    assert code == 1 and len(boxes) == 1
    assert "plik python311.dll jest zmieniony lub uszkodzony" in boxes[0][1]
    assert boxes[0][1].endswith(ACTION)


def test_portable_envelope_keeps_its_fixed_text_for_other_failures(portable, root, monkeypatch):
    (root / portable.SIDECAR_NAME).unlink()
    code, boxes = _portable_main(portable, root, monkeypatch)
    assert code == 1
    assert boxes[0][1] == "Nie można uruchomić Metrolizy lub sprawdzić jej składników."


def test_portable_envelope_stays_silent_in_synthetic_qualification(portable, root, monkeypatch):
    (root / COMPONENTS[1]).unlink()
    code, boxes = _portable_main(portable, root, monkeypatch, synthetic=True)
    assert code == 1 and boxes == []


# --- documentation contract --------------------------------------------------

def test_design_doc_documents_reasons_and_the_exit_75_contract():
    doc = (Path(__file__).resolve().parents[1] / "docs/engineering/supervised-diagnostics-v1.md"
           ).read_text(encoding="utf-8")
    for reason in package.REASONS - {"verified"}:
        assert f"`{reason}`" in doc, reason
    assert "METROLIZA_RUNTIME_REPAIR_AVAILABLE" in doc and "75" in doc
