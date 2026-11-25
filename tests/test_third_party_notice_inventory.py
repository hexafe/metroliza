from __future__ import annotations

import json
from pathlib import Path
import shutil
import tomllib

import pytest

from scripts.third_party_inventory_contract import INVENTORY_PATH, REPO_ROOT, validate_inventory


def test_release_inventory_represents_all_resolved_dependencies() -> None:
    payload = validate_inventory(REPO_ROOT / INVENTORY_PATH, REPO_ROOT)
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
    lock_paths = [*Path("src/metroliza/native").glob("*/Cargo.lock"), Path("packaging/launcher/Cargo.lock")]
    for lock_path in lock_paths:
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

    assert "third_party_inventory.json" in notice
    assert "PyQt6 and PyMuPDF are dual-license components" in notice
    assert "validate_inventory(inventory_path, root_dir)" in pyinstaller_common
    assert "scripts/stage_release_notices.py" in windows_builder
    assert "scripts/stage_release_notices.py" in nuitka_builder


def test_release_notice_files_keep_lf_on_every_checkout() -> None:
    # The notices beside the EXE are compared byte-for-byte with Linux and Windows checkouts.
    attributes = Path(".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "THIRD_PARTY_NOTICES.md text eol=lf" in attributes
    assert f"{INVENTORY_PATH.as_posix()} text eol=lf" in attributes


@pytest.mark.parametrize(
    ("mutated", "failure"),
    [
        ("version", "release mismatch"),
        ("nested requirement", "dependency inputs changed"),
        ("Cargo.toml", "dependency inputs changed"),
        ("Cargo.lock", "dependency inputs changed"),
        ("records", "records changed"),
        ("missing", "No such file"),
    ],
)
def test_inventory_fails_closed_on_stale_inputs_or_bytes(tmp_path, mutated, failure):
    payload = validate_inventory(REPO_ROOT / INVENTORY_PATH, REPO_ROOT)
    version_path = Path("src/metroliza/app/version.py")
    for path in [INVENTORY_PATH, version_path, *map(Path, payload["provenance"]["dependency_inputs"])]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / path, tmp_path / path)
    inventory = tmp_path / INVENTORY_PATH
    assert validate_inventory(inventory, tmp_path) == payload

    if mutated == "version":
        (tmp_path / version_path).write_text('RELEASE_VERSION = "9.0.0-dev.1"\n', encoding="utf-8")
    elif mutated == "records":
        payload["python"]["packages"][0]["version"] = "0.0.0"
        inventory.write_text(json.dumps(payload), encoding="utf-8")
    elif mutated == "missing":
        inventory.unlink()
    else:
        name = "requirements.txt" if mutated == "nested requirement" else f"packaging/launcher/{mutated}"
        with (tmp_path / name).open("a", encoding="utf-8") as stream:
            stream.write("\n# changed dependency input\n")

    with pytest.raises((FileNotFoundError, ValueError), match=failure):
        validate_inventory(inventory, tmp_path)
