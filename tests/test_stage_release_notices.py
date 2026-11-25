from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from scripts.stage_release_notices import DEFAULT_INVENTORY, stage_release_notices
from scripts.vendored_plotly import PLOTLY_ASSET_HASHES, PLOTLY_NOTICE_FILENAME


def test_stage_release_notices_adds_visible_bundle_for_each_artifact(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    onedir = dist / "metroliza"
    onedir.mkdir(parents=True)
    onefile = dist / "metroliza_P_260711.exe"
    onedir_exe = onedir / "metroliza.exe"
    onefile.write_bytes(b"onefile")
    onedir_exe.write_bytes(b"onedir")
    notice = tmp_path / "THIRD_PARTY_NOTICES.md"
    inventory = tmp_path / "inventory.json"
    notice.write_text("notice\n", encoding="utf-8")
    shutil.copyfile(DEFAULT_INVENTORY, inventory)

    manifests = stage_release_notices(
        dist_dir=dist,
        notice_path=notice,
        inventory_path=inventory,
    )

    assert len(manifests) == 3
    for artifact in (onefile, onedir_exe):
        sidecar = artifact.with_name(f"{artifact.name}.licenses")
        assert (sidecar / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8") == "notice\n"
        payload = json.loads((sidecar / "NOTICE_MANIFEST.json").read_text(encoding="utf-8"))
        assert {entry["name"] for entry in payload["files"]} == {
            "THIRD_PARTY_NOTICES.md",
            "inventory.json",
            "plotly.min.js.LICENSE.txt",
        }
        notice_entry = next(entry for entry in payload["files"] if entry["name"] == PLOTLY_NOTICE_FILENAME)
        assert notice_entry["sha256"] == PLOTLY_ASSET_HASHES[PLOTLY_NOTICE_FILENAME]
        assert (sidecar / PLOTLY_NOTICE_FILENAME).is_file()


def test_stage_release_notices_fails_when_inventory_is_missing(tmp_path: Path) -> None:
    notice = tmp_path / "THIRD_PARTY_NOTICES.md"
    notice.write_text("notice\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Required release notice input"):
        stage_release_notices(
            dist_dir=tmp_path / "dist",
            notice_path=notice,
            inventory_path=tmp_path / "missing.json",
        )


def test_explicit_release_artifact_does_not_pick_up_stale_dist_outputs(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    exact_artifact = dist / "metroliza_P_current.exe"
    stale_artifact = dist / "metroliza_P_old.exe"
    exact_artifact.write_bytes(b"current")
    stale_artifact.write_bytes(b"old")
    notice = tmp_path / "THIRD_PARTY_NOTICES.md"
    inventory = tmp_path / "inventory.json"
    notice.write_text("notice\n", encoding="utf-8")
    shutil.copyfile(DEFAULT_INVENTORY, inventory)

    stage_release_notices(
        dist_dir=dist,
        artifacts=(exact_artifact,),
        notice_path=notice,
        inventory_path=inventory,
    )

    assert exact_artifact.with_name(f"{exact_artifact.name}.licenses").is_dir()
    assert not stale_artifact.with_name(f"{stale_artifact.name}.licenses").exists()


def test_stale_inventory_blocks_notice_staging(tmp_path: Path) -> None:
    stale = tmp_path / "inventory.json"
    stale.write_text('{"schema_version": 1}', encoding="utf-8")
    dist = tmp_path / "dist"

    with pytest.raises(ValueError, match="Unsupported third-party inventory schema"):
        stage_release_notices(dist_dir=dist, inventory_path=stale)

    assert not dist.exists()


def test_portable_notices_check_actual_outer_runtime_and_stage_its_terms(tmp_path, monkeypatch):
    import hashlib
    import sys
    from types import ModuleType

    from scripts import stage_release_notices as stage

    inventory = tmp_path / "portable-splash-inventory.json"
    runtime = {"tcl86t.dll": b"tcl", "tk86t.dll": b"tk"}
    files = {}
    for dll, content in runtime.items():
        terms = tmp_path / f"{dll[:2]}-license.terms"
        terms.write_text("test license", encoding="utf-8")
        files[dll] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "license_file": terms.name,
            "license_sha256_lf": hashlib.sha256(terms.read_bytes()).hexdigest(),
        }
    inventory.write_text(json.dumps({"files": files}))
    monkeypatch.setattr(stage, "PORTABLE_SPLASH_INVENTORY", inventory)

    class SyntheticArchive:
        toc = runtime

        def extract(self, name):
            return runtime[name]

    for name in ("PyInstaller", "PyInstaller.archive", "PyInstaller.archive.readers"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setattr(sys.modules["PyInstaller.archive.readers"], "CArchiveReader",
                        lambda _: SyntheticArchive(), raising=False)
    exe = tmp_path / "envelope.exe"
    exe.write_bytes(b"synthetic")

    _, manifest = stage_release_notices(dist_dir=tmp_path, artifacts=(exe,), portable_splash=True)
    assert {item["name"] for item in json.loads(manifest.read_text())["files"]} >= {
        inventory.name, *(item["license_file"] for item in files.values()),
    }

    runtime["tk86t.dll"] = b"other tk"
    with pytest.raises(ValueError, match="tk86t.dll does not match its notice inventory"):
        stage_release_notices(dist_dir=tmp_path, artifacts=(exe,), portable_splash=True)
