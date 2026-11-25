from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zipfile

import pytest

from scripts import release_zip
from scripts.stage_release_notices import stage_release_notices


GIT_SHA = "b" * 40
EXE_NAME = "metroliza_2026.09rc1_261031_launcher.exe"
ONEDIR_FILES = {
    "metroliza.exe": b"supervisor",
    "metroliza_application.exe": b"application",
    "_internal/base_library.zip": b"library",
}


def _write_onedir(root: Path) -> Path:
    onedir = root / "onedir"
    for relative, content in ONEDIR_FILES.items():
        path = onedir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return onedir


def _fake_launcher(path: Path, files: dict[str, bytes], *, git_sha: str = GIT_SHA, gap: int = 0,
                   version: str = "2026.09rc1_261031") -> None:
    """Write a stub + payload + trailer laid out like packaging/launcher/src/pack.rs (raw blobs)."""
    records, offset = [], 0
    for name, data in sorted(files.items()):
        records.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "compressed_size": len(data), "offset": offset})
        offset += len(data) + gap
    content = release_zip.content_sha256("metroliza.exe", [(r["path"], r["size"], r["sha256"]) for r in records])
    manifest = json.dumps(
        {"format": 1, "version": f"{version}-{content[:12]}", "git_sha": git_sha,
         "entry": "metroliza.exe", "chunk_size": 4194304, "files": records}
    ).encode()
    stub = b"MZ" + b"\0" * 62
    blobs = b"".join(files[name] + b"\0" * gap for name in sorted(files))
    trailer = (
        release_zip.TRAILER_MAGIC
        + struct.pack("<QQQ", len(stub), len(blobs) + len(manifest), len(manifest))
        + hashlib.sha256(manifest).digest()
    )
    path.write_bytes(stub + blobs + manifest + trailer)


def _stage_release(tmp_path: Path, *, notices: bool = True, name: str = EXE_NAME,
                   label: str = "2026.09rc1(261031)", version: str = "2026.09rc1_261031",
                   git_sha: str = GIT_SHA) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    exe = dist / name
    _fake_launcher(exe, ONEDIR_FILES, version=version, git_sha=git_sha)
    provenance = {
        "artifact": {"name": exe.name, "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "size_bytes": exe.stat().st_size},
        "dirty": False,
        "git_sha": git_sha,
        "release_label": label,
        "schema_version": 1,
    }
    exe.with_name(f"{exe.name}.provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    if notices:
        stage_release_notices(dist_dir=dist, artifacts=(exe,))
    return exe


def _rewrite_zip(source: Path, target: Path, *, drop: str = "", replace: dict[str, bytes] | None = None,
                 add: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as rewritten:
        for info in original.infolist():
            if drop and drop in info.filename:
                continue
            data = original.read(info)
            for suffix, new_data in (replace or {}).items():
                if info.filename.endswith(suffix):
                    data = new_data
            rewritten.writestr(info, data)
        for name, data in (add or {}).items():
            rewritten.writestr(name, data)
    return target


@pytest.fixture
def release(tmp_path: Path) -> tuple[Path, str]:
    exe = _stage_release(tmp_path)
    expected = release_zip.content_sha256("metroliza.exe", release_zip.onedir_records(_write_onedir(tmp_path)))
    return release_zip.assemble(exe, tmp_path / "out" / "metroliza_2026.09rc1_261031_windows.zip"), expected


def test_content_hash_matches_the_packer_definition(tmp_path: Path) -> None:
    exe = tmp_path / EXE_NAME
    _fake_launcher(exe, ONEDIR_FILES)
    manifest = release_zip.read_payload_manifest(exe)

    onedir_hash = release_zip.content_sha256("metroliza.exe", release_zip.onedir_records(_write_onedir(tmp_path)))

    assert release_zip.payload_content_sha256(manifest) == onedir_hash
    assert manifest["version"].endswith(onedir_hash[:12])
    # Golden value: Rust Manifest::content_sha256 over one empty-entry file list.
    assert release_zip.content_sha256("a.exe", []) == hashlib.sha256(
        b"metroliza-onedir-content-v1\nentry\0a.exe\n"
    ).hexdigest()


def test_launcher_provenance_requires_matching_embedded_onedir(tmp_path, monkeypatch):
    from metroliza.app.version import VERSION_LABEL
    from scripts import build_provenance

    onedir = _write_onedir(tmp_path)
    embedded = onedir / build_provenance.ONEDIR_MANIFEST
    embedded.parent.mkdir(parents=True)
    embedded.write_text(json.dumps({
        "schema_version": 1, "release_label": VERSION_LABEL, "git_sha": GIT_SHA, "dirty": False,
        "built_at_utc": "2026-07-16T10:15:00Z", "packager": "pyinstaller", "python_version": "3.11.9",
    }))
    app = onedir / "metroliza.exe"
    sidecar = app.with_suffix(".exe.provenance.json")
    sidecar.write_text(json.dumps(json.loads(embedded.read_text()) | {
        "artifact": build_provenance._artifact_identity(app),
    }))
    files = ONEDIR_FILES | {
        build_provenance.ONEDIR_MANIFEST.as_posix(): embedded.read_bytes(),
        sidecar.name: sidecar.read_bytes(),
    }
    monkeypatch.setattr(build_provenance, "inspect_git_identity", lambda _: (GIT_SHA, False))
    exe = tmp_path / "renamed.exe"

    def stage():
        return build_provenance.stage_artifact_provenance(
            embedded, (exe,), onedir=onedir, wrapper_format="launcher",
        )

    exe.write_bytes(b"unrelated executable")
    with pytest.raises(release_zip.ReleaseZipError, match="payload trailer"):
        stage()
    _fake_launcher(exe, files | {"metroliza.exe": b"stale"})
    with pytest.raises(ValueError, match="payload files do not match"):
        stage()
    _fake_launcher(exe, files, git_sha="e" * 40)
    with pytest.raises(ValueError, match="payload source does not match"):
        stage()
    _fake_launcher(exe, files)
    sidecar, = stage()
    assert json.loads(sidecar.read_text())["artifact"]["sha256"] == hashlib.sha256(exe.read_bytes()).hexdigest()


def test_semver_zip_preserves_exact_label_names_hash_and_cache_identity(tmp_path: Path):
    name = "Metroliza-0.8.0-dev.1-windows-x64.exe"
    exe = _stage_release(tmp_path, name=name, label="0.8.0-dev.1", version="0.8.0-dev.1")
    archive = release_zip.assemble(exe, tmp_path / "Metroliza-0.8.0-dev.1-windows-x64.zip")
    receipt = release_zip.verify(archive, expected_source_sha=GIT_SHA,
                                 expected_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
    assert receipt["source"]["release_label"] == "0.8.0-dev.1"
    assert receipt["exe"]["name"] == name
    assert receipt["payload"]["runtime_dir"].startswith("0.8.0-dev.1-")
    with zipfile.ZipFile(archive) as zipped:
        assert all(n.startswith("Metroliza-0.8.0-dev.1-windows-x64/") for n in zipped.namelist())


@pytest.mark.parametrize("label,version", [
    ("0.8.0-rc.1", "0.8.0-dev.1"),
    ("0.8.0-dev.1", "0.8.0-rc.1"),
])
def test_semver_zip_rejects_conflicting_provenance_or_payload_identity(tmp_path: Path, label, version):
    exe = _stage_release(tmp_path, name="Metroliza-0.8.0-dev.1-windows-x64.exe",
                         label=label, version=version)
    with pytest.raises(release_zip.ReleaseZipError, match="release label|release identity"):
        archive = release_zip.assemble(exe, tmp_path / "out.zip")
        release_zip.verify(archive)


def test_assembled_zip_is_complete_and_verifies(release: tuple[Path, str], tmp_path: Path) -> None:
    zip_path, expected = release
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        readme = archive.read("metroliza_2026.09rc1_261031/README.txt").decode()

    assert names == [
        "metroliza_2026.09rc1_261031/README.txt",
        f"metroliza_2026.09rc1_261031/{EXE_NAME}",
        f"metroliza_2026.09rc1_261031/{EXE_NAME}.licenses/NOTICE_MANIFEST.json",
        f"metroliza_2026.09rc1_261031/{EXE_NAME}.licenses/THIRD_PARTY_NOTICES.md",
        f"metroliza_2026.09rc1_261031/{EXE_NAME}.licenses/plotly.min.js.LICENSE.txt",
        f"metroliza_2026.09rc1_261031/{EXE_NAME}.licenses/{release_zip_inventory_name()}",
        f"metroliza_2026.09rc1_261031/{EXE_NAME}.provenance.json",
    ]
    assert "Extract the whole ZIP" in readme and f"Double-click {EXE_NAME}" in readme
    receipt = release_zip.verify(
        zip_path, expected_content_sha256=expected, expected_source_sha=GIT_SHA,
        source_root=Path(__file__).resolve().parents[1],
    )
    assert receipt["status"] == "PASS"
    assert receipt["payload"]["content_sha256"] == expected
    assert receipt["payload"]["runtime_dir"] == f"2026.09rc1_261031-{expected[:12]}_{GIT_SHA[:8]}"
    assert release_zip.main(["verify", str(zip_path), "--expected-content-sha256", expected]) == 0


def release_zip_inventory_name() -> str:
    from scripts.stage_release_notices import DEFAULT_INVENTORY

    return DEFAULT_INVENTORY.name


def test_assembly_refuses_a_launcher_without_notices(tmp_path: Path) -> None:
    exe = _stage_release(tmp_path, notices=False)

    with pytest.raises(release_zip.ReleaseZipError, match="NOTICE_MANIFEST.json"):
        release_zip.assemble(exe, tmp_path / "out.zip")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"drop": ".licenses/"}, "notice directory"),
        ({"drop": "THIRD_PARTY_NOTICES.md"}, "notice listed in NOTICE_MANIFEST.json is missing"),
        ({"drop": "plotly.min.js.LICENSE.txt"}, "notice listed in NOTICE_MANIFEST.json is missing"),
        ({"replace": {"THIRD_PARTY_NOTICES.md": b"edited"}}, "notice hash differs"),
        ({"drop": ".provenance.json"}, "provenance.json is missing"),
        ({"drop": "README.txt"}, "README.txt is missing"),
        ({"add": {"metroliza_2026.09rc1_261031/extra.dll": b"x"}}, "unexpected file set"),
        ({"add": {"other/README.txt": b"x"}}, "exactly one top-level folder"),
        ({"add": {"metroliza_2026.09rc1_261031/../evil.txt": b"x"}}, "unsafe member name"),
        ({"replace": {"_launcher.exe": b"MZ not the qualified EXE"}}, "differs from its provenance"),
    ],
)
def test_incomplete_or_altered_zip_fails_the_gate(release: tuple[Path, str], tmp_path: Path, mutation, message) -> None:
    zip_path, _ = release
    altered = _rewrite_zip(zip_path, tmp_path / "altered.zip", **mutation)

    with pytest.raises(release_zip.ReleaseZipError, match=message):
        release_zip.verify(altered)
    assert release_zip.main(["verify", str(altered)]) == 1


def test_payload_other_than_the_qualified_onedir_fails(release: tuple[Path, str]) -> None:
    zip_path, expected = release

    with pytest.raises(release_zip.ReleaseZipError, match="differs from the qualified onedir"):
        release_zip.verify(zip_path, expected_content_sha256="0" * 64)
    with pytest.raises(release_zip.ReleaseZipError, match="not the expected"):
        release_zip.verify(zip_path, expected_content_sha256=expected, expected_source_sha="c" * 40)


def test_notices_must_match_the_source_checkout(release: tuple[Path, str], tmp_path: Path) -> None:
    zip_path, _ = release
    source = tmp_path / "source"
    (source / "docs/release_checks").mkdir(parents=True)
    (source / "THIRD_PARTY_NOTICES.md").write_text("different notice\n", encoding="utf-8")

    with pytest.raises(release_zip.ReleaseZipError, match="does not match THIRD_PARTY_NOTICES.md in the source checkout"):
        release_zip.verify(zip_path, source_root=source)


def test_tampered_payload_manifest_is_rejected(tmp_path: Path) -> None:
    exe = tmp_path / EXE_NAME
    _fake_launcher(exe, ONEDIR_FILES)
    data = bytearray(exe.read_bytes())
    data[-TRAILER_MANIFEST_BYTE] ^= 0x01
    exe.write_bytes(bytes(data))

    with pytest.raises(release_zip.ReleaseZipError, match="manifest hash mismatch"):
        release_zip.read_payload_manifest(exe)


# A byte inside the manifest JSON, just before the 64-byte trailer.
TRAILER_MANIFEST_BYTE = release_zip.TRAILER_LEN + 3


# Produced by the real packer (packaging/launcher, `metroliza-packer --input <these files>`) on
# 2026-10-30; any ordering, separator or encoding difference from Rust changes it.
RUST_PACKER_GOLDEN = "300545a11b5bbef38d4ad1b990a1f6a61d5ae0574e9574eee7dd26ea6303aaab"
GOLDEN_FILES = {
    "metroliza.exe": b"supervisor",
    "a": b"A",
    "b.txt": b"lower-b",
    "a b.txt": b"",
    "_internal/sub/z.pyd": b"x",
    "B/c": b"upper",
    "_internal/Ä.dat": b"\x00\x01",
}


def test_content_hash_equals_the_rust_packer_golden(tmp_path: Path) -> None:
    for relative, content in GOLDEN_FILES.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    assert release_zip.content_sha256("metroliza.exe", release_zip.onedir_records(tmp_path)) == RUST_PACKER_GOLDEN


def test_signed_pe_trailer_is_read_before_the_certificate_table(tmp_path: Path) -> None:
    exe = tmp_path / EXE_NAME
    _fake_launcher(exe, ONEDIR_FILES)
    unsigned = exe.read_bytes()
    pe = 0x80
    header = bytearray(unsigned[:2] + b"\0" * (pe - 2))
    struct.pack_into("<I", header, 0x3C, pe)
    optional = bytearray(b"PE\0\0" + b"\0" * 20) + bytearray(240)
    struct.pack_into("<H", optional, 24, 0x20B)
    struct.pack_into("<I", optional, 24 + 108, 16)
    certificate = b"\x30\x82fake-certificate"
    signed_body = bytes(header + optional)
    # Rebuild the payload after the larger PE header, then append a certificate table.
    shift = len(signed_body) - 64
    trailer = unsigned[-release_zip.TRAILER_LEN:]
    offset, length, manifest_len = struct.unpack_from("<QQQ", trailer, 8)
    payload = unsigned[64:-release_zip.TRAILER_LEN]
    new_trailer = trailer[:8] + struct.pack("<QQQ", offset + shift, length, manifest_len) + trailer[32:]
    body = signed_body + payload + new_trailer
    struct.pack_into("<II", optional, 24 + 112 + 32, len(body), len(certificate))
    exe.write_bytes(bytes(header + optional) + payload + new_trailer + certificate)

    with exe.open("rb") as handle:
        assert release_zip._trailer_end(handle, exe.stat().st_size) == exe.stat().st_size - len(certificate)
    manifest = release_zip.read_payload_manifest(exe)

    assert release_zip.payload_content_sha256(manifest) == release_zip.content_sha256(
        "metroliza.exe", [(r["path"], r["size"], r["sha256"]) for r in manifest["files"]]
    )
    assert manifest["git_sha"] == GIT_SHA


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"replace": {"README.txt": b"Run anything.\r\n"}}, "README.txt is not the release instruction"),
        ({"add": {f"metroliza_2026.09rc1_261031/{EXE_NAME.upper()}": b"x"}}, "duplicate member name"),
    ],
)
def test_readme_and_duplicate_members_are_checked(release: tuple[Path, str], tmp_path: Path, mutation, message) -> None:
    zip_path, _ = release
    altered = _rewrite_zip(zip_path, tmp_path / "altered.zip", **mutation)

    with pytest.raises(release_zip.ReleaseZipError, match=message):
        release_zip.verify(altered)


def test_notice_manifest_must_list_exactly_the_required_notices(tmp_path: Path) -> None:
    exe = _stage_release(tmp_path)
    licenses = exe.with_name(f"{exe.name}.licenses")
    inventory = licenses / release_zip_inventory_name()
    inventory.unlink()
    manifest = json.loads((licenses / "NOTICE_MANIFEST.json").read_text(encoding="utf-8"))
    manifest["files"] = [item for item in manifest["files"] if item["name"] != inventory.name]
    (licenses / "NOTICE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    zip_path = release_zip.assemble(exe, tmp_path / "out.zip")

    with pytest.raises(release_zip.ReleaseZipError, match="notices must be exactly"):
        release_zip.verify(zip_path)


def test_archived_zip_without_companion_requires_bound_legacy_evidence(tmp_path: Path) -> None:
    notice_name = release_zip.PLOTLY_NOTICE_FILENAME
    source_root = tmp_path / "historic-source"
    loose_notice_directory = tmp_path / "unbound-source"
    for name, relative in release_zip.REQUIRED_NOTICES.items():
        if name == notice_name:
            continue
        for directory in (source_root, loose_notice_directory):
            source_file = directory / relative
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_bytes((release_zip.REPO_ROOT / relative).read_bytes())
    git = ("git", "-C", str(source_root))
    subprocess.run((*git, "init", "-q"), check=True)
    subprocess.run((*git, "add", "."), check=True)
    subprocess.run((*git, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "Historical notices"), check=True)
    source_sha = subprocess.check_output((*git, "rev-parse", "HEAD"), text=True).strip()
    exe = _stage_release(tmp_path, git_sha=source_sha)
    licenses = exe.with_name(f"{exe.name}.licenses")
    manifest_path = licenses / release_zip.NOTICE_MANIFEST
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"] = [item for item in manifest["files"] if item["name"] != notice_name]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (licenses / notice_name).unlink()
    archive = release_zip.assemble(exe, tmp_path / "legacy.zip")
    pins = {"expected_source_sha": source_sha, "expected_exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest()}
    receipt = release_zip.verify(archive, source_root=source_root, **pins)
    assert receipt["status"] == "PASS"
    assert set(receipt["notices"]) == set(release_zip.REQUIRED_NOTICES) - {notice_name}
    with pytest.raises(release_zip.ReleaseZipError, match="notices must be exactly"):
        release_zip.verify(archive, source_root=source_root, expected_source_sha=source_sha)
    with pytest.raises(release_zip.ReleaseZipError, match="notices must be exactly"):
        release_zip.verify(archive, source_root=release_zip.REPO_ROOT, **pins)
    with pytest.raises(release_zip.ReleaseZipError, match="notices must be exactly"):
        release_zip.verify(archive, source_root=loose_notice_directory, **pins)

    modern_root = tmp_path / "modern"
    modern_root.mkdir()
    modern = _stage_release(
        modern_root, git_sha=source_sha, name="Metroliza-0.8.0-dev.1-windows-x64.exe",
        label="0.8.0-dev.1", version="0.8.0-dev.1",
    )
    modern_licenses = modern.with_name(f"{modern.name}.licenses")
    (modern_licenses / release_zip.NOTICE_MANIFEST).write_bytes(manifest_path.read_bytes())
    (modern_licenses / notice_name).unlink()
    modern_archive = release_zip.assemble(modern, tmp_path / "modern.zip")
    with pytest.raises(release_zip.ReleaseZipError, match="notices must be exactly"):
        release_zip.verify(
            modern_archive, source_root=source_root, expected_source_sha=source_sha,
            expected_exe_sha256=hashlib.sha256(modern.read_bytes()).hexdigest(),
        )


def test_blob_layout_must_tile_the_blob_region(tmp_path: Path) -> None:
    exe = tmp_path / EXE_NAME
    _fake_launcher(exe, ONEDIR_FILES, gap=1)

    with pytest.raises(release_zip.ReleaseZipError, match="blob layout is inconsistent"):
        release_zip.read_payload_manifest(exe)


def test_zip_must_carry_the_smoke_tested_exe(release: tuple[Path, str]) -> None:
    zip_path, expected = release
    receipt = release_zip.verify(zip_path)

    assert release_zip.verify(zip_path, expected_exe_sha256=receipt["exe"]["sha256"])["status"] == "PASS"
    with pytest.raises(release_zip.ReleaseZipError, match="smoke-tested launcher"):
        release_zip.verify(zip_path, expected_exe_sha256="0" * 64)
