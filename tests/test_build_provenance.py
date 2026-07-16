from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

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
        "python_version": "3.11.9",
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
    output = tmp_path / "nested" / "build_provenance.json"

    build_provenance.generate_build_provenance(output, packager="pyinstaller")

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["git_sha"] == "b" * 40
    assert payload["dirty"] is True
    assert payload["built_at_utc"] == "2026-07-16T10:15:00Z"
    assert payload["packager"] == "pyinstaller"
    assert payload["python_version"]
    assert payload["release_label"]


def test_artifact_sidecar_hashes_only_explicit_binary(tmp_path: Path) -> None:
    manifest = tmp_path / "build_provenance.json"
    manifest.write_text(json.dumps(_manifest_payload()), encoding="utf-8")
    exact = tmp_path / "metroliza-current.exe"
    stale = tmp_path / "metroliza-old.exe"
    exact.write_bytes(b"exact artifact bytes")
    stale.write_bytes(b"stale artifact bytes")

    sidecars = build_provenance.stage_artifact_provenance(manifest, (exact,))

    assert sidecars == (exact.with_name(f"{exact.name}.provenance.json"),)
    payload = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert payload["artifact"] == {
        "name": exact.name,
        "sha256": hashlib.sha256(exact.read_bytes()).hexdigest(),
        "size_bytes": exact.stat().st_size,
    }
    assert not stale.with_name(f"{stale.name}.provenance.json").exists()


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


def test_startup_log_includes_process_build_and_parser_identity(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = logging.getLogger("metroliza.provenance-test")
    provenance = BuildProvenance.from_mapping(_manifest_payload())
    monkeypatch.setattr(bootstrap, "load_build_provenance", lambda: provenance)
    monkeypatch.setattr(bootstrap, "runtime_mode", lambda: "frozen")
    monkeypatch.setenv(bootstrap.PARSER_STRICT_MATCHING_ENV, "0")

    with caplog.at_level(logging.INFO, logger=logger.name):
        bootstrap.log_runtime_provenance(logger)

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "Runtime provenance pid=" in message
    assert "executable=" in message
    assert "mode=frozen" in message
    assert f"git_sha={provenance.git_sha}" in message
    assert "dirty=false" in message
    assert "packager=pyinstaller" in message
    assert "parser_strict_matching=false" in message


def test_pyinstaller_build_embeds_manifest_and_selects_exact_artifacts() -> None:
    common = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")
    builder = Path("build_windows_exe.ps1").read_text(encoding="utf-8")

    assert '"metroliza/app"' in common
    assert "prepare_build_provenance_manifest" in common
    assert "validate_build_provenance_manifest" in common
    assert "Get-ExpectedPyInstallerArtifacts" in builder
    assert "scripts/build_provenance.py" in builder
    assert "'validate'" in builder
    assert "Removing previous exact output EXEs" in builder
    assert "Get-ChildItem -LiteralPath $distDir -Recurse" not in builder
