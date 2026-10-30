from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
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


def _fake_launcher(path: Path, files: dict[str, bytes], *, git_sha: str = GIT_SHA) -> None:
    """Write a stub + payload + trailer laid out like packaging/launcher/src/pack.rs."""
    records = [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "compressed_size": len(data), "offset": 0}
        for name, data in sorted(files.items())
    ]
    content = release_zip.content_sha256("metroliza.exe", [(r["path"], r["size"], r["sha256"]) for r in records])
    manifest = json.dumps(
        {"format": 1, "version": f"2026.09rc1_261031-{content[:12]}", "git_sha": git_sha,
         "entry": "metroliza.exe", "chunk_size": 4194304, "files": records}
    ).encode()
    stub = b"MZ" + b"\0" * 62
    blobs = b"".join(files[name] for name in sorted(files))
    trailer = (
        release_zip.TRAILER_MAGIC
        + struct.pack("<QQQ", len(stub), len(blobs) + len(manifest), len(manifest))
        + hashlib.sha256(manifest).digest()
    )
    path.write_bytes(stub + blobs + manifest + trailer)


def _stage_release(tmp_path: Path, *, notices: bool = True) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    exe = dist / EXE_NAME
    _fake_launcher(exe, ONEDIR_FILES)
    provenance = {
        "artifact": {"name": exe.name, "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "size_bytes": exe.stat().st_size},
        "dirty": False,
        "git_sha": GIT_SHA,
        "release_label": "2026.09rc1(261031)",
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

    with pytest.raises(release_zip.ReleaseZipError, match="does not match the source checkout"):
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
