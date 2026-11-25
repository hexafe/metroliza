from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from metroliza.charts import plotly_runtime_assets
from metroliza.charts.plotly_runtime_assets import copy_plotly_runtime_assets
from scripts.third_party_inventory_contract import INVENTORY_PATH
from scripts.vendored_plotly import (
    PLOTLY_ASSET_DIRECTORY,
    PLOTLY_ASSET_HASHES,
    PLOTLY_NOTICE_FILENAME,
    plotly_inventory,
    verified_plotly_files,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ASSETS = ROOT / "src" / PLOTLY_ASSET_DIRECTORY


def test_release_inventory_matches_the_vendored_plotly_distribution():
    inventory = json.loads((ROOT / INVENTORY_PATH).read_bytes())

    assert inventory["vendored_plotly"] == plotly_inventory(SOURCE_ASSETS)


@pytest.mark.parametrize("missing", [True, False])
def test_packaging_requires_the_verified_companion_notice(tmp_path, missing):
    bundle_name = next(name for name in PLOTLY_ASSET_HASHES if name.endswith(".js"))
    shutil.copyfile(SOURCE_ASSETS / bundle_name, tmp_path / bundle_name)
    if not missing:
        (tmp_path / PLOTLY_NOTICE_FILENAME).write_text("different notice", encoding="utf-8")

    error = FileNotFoundError if missing else ValueError
    with pytest.raises(error, match=r"plotly\.min\.js\.LICENSE\.txt"):
        verified_plotly_files(tmp_path)


def test_offline_runtime_needs_notice_and_copies_the_exact_pair(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    bundle_name = next(name for name in PLOTLY_ASSET_HASHES if name.endswith(".js"))
    source = tmp_path / bundle_name
    shutil.copyfile(SOURCE_ASSETS / bundle_name, source)

    assert copy_plotly_runtime_assets(source, assets) is None
    assert list(assets.iterdir()) == []

    shutil.copyfile(SOURCE_ASSETS / PLOTLY_NOTICE_FILENAME, tmp_path / PLOTLY_NOTICE_FILENAME)

    assert copy_plotly_runtime_assets(source, assets) == f"assets/{bundle_name}"
    assert plotly_inventory(assets) == plotly_inventory(SOURCE_ASSETS)


def test_failed_runtime_refresh_keeps_live_dashboard_assets(tmp_path, monkeypatch):
    source = tmp_path / "plotly-2.27.0.min.js"
    source.write_bytes(b"new runtime")
    source.with_name(PLOTLY_NOTICE_FILENAME).write_bytes(b"new notice")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / source.name).write_bytes(b"complete runtime")
    (assets / PLOTLY_NOTICE_FILENAME).write_bytes(b"complete notice")

    def fail_script_copy(origin, target):
        if origin == source:
            target.write_bytes(b"interrupted runtime")
            raise OSError("simulated interrupted copy")
        shutil.copyfile(origin, target)

    monkeypatch.setattr(plotly_runtime_assets, "copyfile", fail_script_copy)

    with pytest.raises(OSError, match="interrupted copy"):
        copy_plotly_runtime_assets(source, assets)
    assert (assets / source.name).read_bytes() == b"complete runtime"
    assert (assets / PLOTLY_NOTICE_FILENAME).read_bytes() == b"complete notice"
    assert {path.name for path in assets.iterdir()} == {source.name, PLOTLY_NOTICE_FILENAME}
