from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.stage_release_notices import stage_release_notices


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
    inventory.write_text('{"packages": []}\n', encoding="utf-8")

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
        }


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
    inventory.write_text('{"packages": []}\n', encoding="utf-8")

    stage_release_notices(
        dist_dir=dist,
        artifacts=(exact_artifact,),
        notice_path=notice,
        inventory_path=inventory,
    )

    assert exact_artifact.with_name(f"{exact_artifact.name}.licenses").is_dir()
    assert not stale_artifact.with_name(f"{stale_artifact.name}.licenses").exists()
