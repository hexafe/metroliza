from __future__ import annotations

import json
from pathlib import Path
import tomllib


INVENTORY_PATH = Path("docs/release_checks/third_party_inventory_260711.json")


def test_release_inventory_represents_all_resolved_dependencies() -> None:
    payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    python = payload["python"]
    rust = payload["rust"]

    assert python["missing_requirement_roots"] == []
    python_names = [record["canonical_name"] for record in python["packages"]]
    assert len(python_names) == len(set(python_names))
    assert set(python["requirement_roots"]) <= set(python_names)
    assert all(record["license_metadata"] != "UNDECLARED" for record in python["packages"])

    rust_keys = [
        (record["name"], record["version"], record["source"])
        for record in rust["packages"]
    ]
    assert rust["warnings"] == []
    assert len(rust_keys) == len(set(rust_keys))
    assert all(
        record["license"] != "UNDECLARED"
        for record in rust["packages"]
        if record["source"] != "workspace"
    )

    locked_packages = set()
    for lock_path in Path("src/metroliza/native").glob("*/Cargo.lock"):
        lock_payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        locked_packages.update(
            (record["name"], record["version"])
            for record in lock_payload["package"]
            if record.get("source")
        )
    inventory_packages = {
        (record["name"], record["version"])
        for record in rust["packages"]
        if record["source"] != "workspace"
    }
    assert inventory_packages == locked_packages


def test_notice_and_packagers_require_inventory_sidecars() -> None:
    notice = Path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    pyinstaller_common = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")
    windows_builder = Path("build_windows_exe.ps1").read_text(encoding="utf-8")
    nuitka_builder = Path("packaging/build_nuitka.ps1").read_text(encoding="utf-8")

    assert "third_party_inventory_260711.json" in notice
    assert "PyQt6 and PyMuPDF are dual-license components" in notice
    assert "third_party_inventory_260711.json" in pyinstaller_common
    assert "scripts/stage_release_notices.py" in windows_builder
    assert "scripts/stage_release_notices.py" in nuitka_builder
