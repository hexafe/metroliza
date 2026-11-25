from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import platform

import pytest

from metroliza.app import bootstrap
from metroliza.app.build_provenance import (
    BUILD_PROVENANCE_SCHEMA_VERSION,
    BuildProvenance,
    load_build_provenance,
)
from metroliza.app.version import VERSION_LABEL
from scripts import build_provenance


def _manifest_payload() -> dict[str, object]:
    return {
        "schema_version": BUILD_PROVENANCE_SCHEMA_VERSION,
        "release_label": VERSION_LABEL,
        "git_sha": "a" * 40,
        "dirty": False,
        "built_at_utc": "2026-07-16T10:00:00Z",
        "packager": "pyinstaller",
        "python_version": platform.python_version(),
    }


def test_load_build_provenance_reads_valid_embedded_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "build_provenance.json"
    manifest.write_text(json.dumps(_manifest_payload()), encoding="utf-8")

    provenance = load_build_provenance(manifest)

    assert provenance == BuildProvenance.from_mapping(_manifest_payload())


def test_invalid_build_provenance_falls_back_to_explicit_source_identity(tmp_path: Path) -> None:
    manifest = tmp_path / "build_provenance.json"
    manifest.write_text('{"schema_version": 99}', encoding="utf-8")

    provenance = load_build_provenance(manifest)

    assert provenance.packager == "source"
    assert provenance.git_sha == "unknown"
    assert provenance.dirty is None


def test_generate_manifest_records_full_git_identity_and_toolchain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(build_provenance.BUILD_GIT_SHA_ENV, "B" * 40)
    monkeypatch.setenv(build_provenance.BUILD_GIT_DIRTY_ENV, "true")
    monkeypatch.setenv(build_provenance.BUILD_TIMESTAMP_ENV, "2026-07-16T10:15:00Z")
    version = tmp_path / "src/metroliza/app/version.py"
    version.parent.mkdir(parents=True)
    version.write_text(f"RELEASE_VERSION = {VERSION_LABEL!r}\n", encoding="utf-8")
    output = tmp_path / "nested" / "build_provenance.json"

    build_provenance.generate_build_provenance(output, packager="pyinstaller", repo_root=tmp_path)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["git_sha"] == "b" * 40
    assert payload["dirty"] is True
    assert payload["built_at_utc"] == "2026-07-16T10:15:00Z"
    assert payload["packager"] == "pyinstaller"
    assert payload["python_version"]
    assert payload["release_label"]


def test_artifact_sidecar_hashes_only_explicit_binary(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "build_provenance.json"
    manifest.write_text(json.dumps(_manifest_payload()), encoding="utf-8")
    exact = tmp_path / "metroliza.exe"
    embedded = exact.parent / build_provenance.ONEDIR_MANIFEST
    embedded.parent.mkdir(parents=True)
    embedded.write_bytes(manifest.read_bytes())
    stale = tmp_path / "metroliza-old.exe"
    exact.write_bytes(b"exact artifact bytes")
    stale.write_bytes(b"stale artifact bytes")
    monkeypatch.setattr(build_provenance, "inspect_git_identity", lambda _root: ("a" * 40, False))
    monkeypatch.delenv(build_provenance.BUILD_TIMESTAMP_ENV, raising=False)

    sidecars = build_provenance.stage_artifact_provenance(manifest, (exact,))

    assert sidecars == (exact.with_name(f"{exact.name}.provenance.json"),)
    payload = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert payload["artifact"] == {
        "name": exact.name,
        "sha256": hashlib.sha256(exact.read_bytes()).hexdigest(),
        "size_bytes": exact.stat().st_size,
    }
    assert not stale.with_name(f"{stale.name}.provenance.json").exists()

    # A same-source manifest from another attempt cannot be attached to this onedir.
    manifest.write_text(json.dumps(_manifest_payload() | {"built_at_utc": "2026-07-16T10:00:10Z"}))
    with pytest.raises(ValueError, match="does not match the embedded"):
        build_provenance.stage_artifact_provenance(manifest, (exact,))

    with pytest.raises(ValueError, match="explicit format"):
        build_provenance.stage_artifact_provenance(embedded, (stale,), onedir=exact.parent)


def test_portable_wrapper_stage_binds_contents_independent_of_filename(tmp_path, monkeypatch):
    import sys
    from types import ModuleType

    onedir = tmp_path / "payload"
    embedded = onedir / build_provenance.ONEDIR_MANIFEST
    embedded.parent.mkdir(parents=True)
    embedded.write_text(json.dumps(_manifest_payload()))
    app = onedir / "metroliza.exe"
    app.write_bytes(b"current application")
    sidecar = app.with_suffix(".exe.provenance.json")
    sidecar.write_text(json.dumps(_manifest_payload() | {"artifact": build_provenance._artifact_identity(app)}))
    artifact = tmp_path / "renamed.exe"
    artifact.write_bytes(b"synthetic portable")
    manifest_name = f"metroliza_payload/{build_provenance.ONEDIR_MANIFEST.as_posix()}"
    files = {
        manifest_name: embedded.read_bytes(),
        "metroliza_payload/metroliza.exe": app.read_bytes(),
        "metroliza_payload/metroliza.exe.provenance.json": sidecar.read_bytes(),
    }

    class SyntheticArchive:
        toc = files

        def extract(self, name):
            return files[name]

    for name in ("PyInstaller", "PyInstaller.archive", "PyInstaller.archive.readers"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setattr(sys.modules["PyInstaller.archive.readers"], "CArchiveReader",
                        lambda _: SyntheticArchive(), raising=False)
    monkeypatch.setattr(build_provenance, "inspect_git_identity", lambda _: ("a" * 40, False))
    monkeypatch.setenv(build_provenance.BUILD_TIMESTAMP_ENV, "2026-07-16T11:00:00Z")

    wrapped = build_provenance.stage_artifact_provenance(
        embedded, (artifact,), onedir=onedir, wrapper_format="portable",
    )
    assert json.loads(wrapped[0].read_text())["built_at_utc"] == _manifest_payload()["built_at_utc"]
    files["metroliza_payload/metroliza.exe"] = b"stale application"
    with pytest.raises(ValueError, match="does not match the supplied onedir: metroliza.exe"):
        build_provenance.stage_artifact_provenance(
            embedded, (artifact,), onedir=onedir, wrapper_format="portable",
        )
    files.pop("metroliza_payload/metroliza.exe")
    with pytest.raises(ValueError, match="file list"):
        build_provenance.stage_artifact_provenance(
            embedded, (artifact,), onedir=onedir, wrapper_format="portable",
        )


def test_artifact_sidecar_requires_an_explicit_artifact(tmp_path: Path) -> None:
    manifest = tmp_path / "build_provenance.json"
    manifest.write_text(json.dumps(_manifest_payload()), encoding="utf-8")

    with pytest.raises(ValueError, match="explicit artifact"):
        build_provenance.stage_artifact_provenance(manifest, ())


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("release_label", "stale-release", "release mismatch"),
        ("packager", "nuitka", "packager mismatch"),
    ],
)
def test_build_manifest_validation_rejects_stale_build_identity(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    payload = _manifest_payload()
    payload[field] = value
    manifest = tmp_path / "build_provenance.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        build_provenance.validate_build_provenance_manifest(
            manifest,
            expected_packager="pyinstaller",
            expected_release_label=VERSION_LABEL,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("git_sha", "b" * 40, "Git SHA mismatch"),
        ("dirty", True, "dirty state mismatch"),
        ("built_at_utc", "2026-07-16T09:59:59Z", "timestamp does not match"),
        ("python_version", "3.10.0", "Python version mismatch"),
    ],
)
def test_supplied_pyinstaller_manifest_must_match_the_build_attempt(tmp_path, monkeypatch, field, value, match):
    from tests.test_packaging_payload_exclusions import common

    root = build_provenance.REPO_ROOT

    payload = _manifest_payload()
    manifest = tmp_path / "build_provenance.json"
    monkeypatch.setenv(build_provenance.BUILD_PROVENANCE_PATH_ENV, str(manifest))
    monkeypatch.setenv(build_provenance.BUILD_TIMESTAMP_ENV, str(payload["built_at_utc"]))
    monkeypatch.setattr(build_provenance, "inspect_git_identity", lambda _root: ("a" * 40, False))
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert common.prepare_build_provenance_manifest(root) == manifest
    manifest.write_text(json.dumps(payload | {field: value}), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        common.prepare_build_provenance_manifest(root)

    monkeypatch.delenv(build_provenance.BUILD_TIMESTAMP_ENV)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Current PyInstaller build requires"):
        common.prepare_build_provenance_manifest(root)


def test_checkout_identity_cannot_be_replaced_by_snapshot_overrides(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(
        build_provenance, "_run_git",
        lambda _root, command, *_args: "a" * 40 if command == "rev-parse" else "M tracked.py",
    )
    monkeypatch.setenv(build_provenance.BUILD_GIT_SHA_ENV, "b" * 40)
    with pytest.raises(ValueError, match="SHA.*disagrees"):
        build_provenance.inspect_git_identity(tmp_path)
    monkeypatch.setenv(build_provenance.BUILD_GIT_SHA_ENV, "a" * 40)
    monkeypatch.setenv(build_provenance.BUILD_GIT_DIRTY_ENV, "false")
    with pytest.raises(ValueError, match="DIRTY.*disagrees"):
        build_provenance.inspect_git_identity(tmp_path)


def test_startup_log_contains_only_typed_build_identity(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    from metroliza.app.version import RELEASE_VERSION
    from metroliza.shared.logging_utils import ManagedSafeFormatter

    logger = logging.getLogger("metroliza.provenance-test")
    provenance = BuildProvenance.from_mapping(_manifest_payload())
    monkeypatch.setattr(bootstrap, "load_build_provenance", lambda: provenance)
    monkeypatch.setattr(bootstrap, "runtime_mode", lambda: "frozen")

    with caplog.at_level(logging.INFO, logger=logger.name):
        bootstrap.log_runtime_provenance(logger)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.INFO
    output = ManagedSafeFormatter().format(caplog.records[0])
    event = json.loads(output.split(" ", 2)[2])
    assert event["event_code"] == "runtime_provenance"
    assert event["release_version"] == RELEASE_VERSION
    assert event["runtime"] == "frozen"
    assert event["git_sha"] == "a" * 40
    assert event["dirty"] is False
    assert event["packager"] == "pyinstaller"
    for key in ("invocation_id", "startup_id"):
        identifier = UUID(hex=event[key])
        assert identifier.version == 4
        assert identifier.hex == event[key]
    assert event["invocation_id"] != event["startup_id"]
    assert type(event["sequence"]) is int
    assert event["sequence"] == 1
    assert set(event) == {
        "event_code", "invocation_id", "startup_id", "sequence", "release_version",
        "git_sha", "runtime", "packager", "dirty",
    }


def test_pyinstaller_build_embeds_manifest_and_selects_exact_artifacts() -> None:
    common = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")
    builder = Path("build_windows_exe.ps1").read_text(encoding="utf-8")

    assert '"metroliza/app"' in common
    assert "prepare_build_provenance_manifest" in common
    assert "validate_active_pyinstaller_provenance" in common
    assert "Get-ExpectedPyInstallerArtifacts" in builder
    assert "scripts/build_provenance.py" in builder
    assert "'validate'" in builder
    assert "Removing previous exact output EXEs" in builder
    assert "Get-ChildItem -LiteralPath $distDir -Recurse" not in builder
