from __future__ import annotations

import json
from pathlib import Path

from scripts import verify_third_party_inventory as verifier


def _inventory(python: dict[str, str], rust: set[tuple[str, str, str]]) -> dict:
    return {
        "python": {
            "packages": [{"canonical_name": name, "version": version} for name, version in python.items()],
            "missing_requirement_roots": [],
        },
        "rust": {"packages": [{"name": n, "version": v, "source": s} for n, v, s in sorted(rust)], "warnings": []},
        "review_status": {"metadata_reviewed": False, "release_owner_approved": False},
    }


def _dist_info(onedir: Path, name: str, version: str) -> None:
    folder = onedir / "_internal" / f"{name.replace('-', '_')}-{version}.dist-info"
    folder.mkdir(parents=True)
    (folder / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\nBody\n", encoding="utf-8")


RUST = {("sha2", "0.10.9", "registry+https://github.com/rust-lang/crates.io-index")}


def test_matching_inventory_passes_and_keeps_review_status() -> None:
    inventory = _inventory({"numpy": "2.4.6", "setuptools": "84.2.1"}, RUST)

    receipt = verifier.compare_inventories(inventory, inventory, {"numpy": "2.4.6", "setuptools": "84.2.1"})

    assert receipt["status"] == "PASS" and receipt["problems"] == []
    assert receipt["review_status"] == {"metadata_reviewed": False, "release_owner_approved": False}


def test_stale_inventory_reports_every_difference() -> None:
    committed = _inventory({"numpy": "2.4.6", "pandas": "3.0.3", "openvino": "2026.2.1"}, RUST)
    actual = _inventory(
        {"numpy": "2.4.6", "pandas": "3.1.0", "pluggy": "1.7.0"},
        RUST | {("tempfile", "3.20.0", "registry+https://github.com/rust-lang/crates.io-index")},
    )

    receipt = verifier.compare_inventories(committed, actual, {"pandas": "3.1.0", "pyqt6": "6.6.1"})

    assert receipt["status"] == "FAIL"
    assert receipt["python"]["missing_from_inventory"] == ["pluggy==1.7.0"]
    assert receipt["python"]["not_in_build"] == ["openvino==2026.2.1"]
    assert receipt["python"]["version_differs"] == ["pandas: inventory 3.0.3, build 3.1.0"]
    assert receipt["python"]["bundled_metadata_unexplained"] == ["pyqt6==6.6.1"]
    assert receipt["rust"]["missing_from_inventory"] == [
        "tempfile@3.20.0 (registry+https://github.com/rust-lang/crates.io-index)"
    ]
    assert len(receipt["problems"]) == 5


def test_bundled_dist_info_is_read_from_the_onedir(tmp_path: Path) -> None:
    _dist_info(tmp_path, "PyQt6-Qt6", "6.6.1")
    _dist_info(tmp_path, "importlib_metadata", "8.7.1")

    assert verifier.bundled_distributions(tmp_path) == {"pyqt6-qt6": "6.6.1", "importlib-metadata": "8.7.1"}


def test_cli_writes_receipt_and_generated_inventory_and_fails_on_drift(tmp_path: Path, monkeypatch) -> None:
    onedir = tmp_path / "onedir"
    _dist_info(onedir, "pluggy", "1.7.0")
    committed_path = tmp_path / "inventory.json"
    committed_path.write_text(json.dumps(_inventory({"numpy": "2.4.6"}, RUST)), encoding="utf-8")
    actual = _inventory({"numpy": "2.4.6", "pluggy": "1.7.0"}, RUST)
    monkeypatch.setattr(verifier, "generate_build_inventory", lambda **_kwargs: (actual, {"pluggy": "1.7.0"}))

    code = verifier.main([
        "--inventory", str(committed_path), "--onedir", str(onedir),
        "--receipt", str(tmp_path / "out/receipt.json"), "--generated", str(tmp_path / "out/generated.json"),
    ])

    assert code == 1
    assert json.loads((tmp_path / "out/generated.json").read_text(encoding="utf-8")) == actual
    assert json.loads((tmp_path / "out/receipt.json").read_text(encoding="utf-8"))["problems"] == [
        "python missing_from_inventory: pluggy==1.7.0"
    ]
    committed_path.write_text(json.dumps(actual), encoding="utf-8")
    assert verifier.main([
        "--inventory", str(committed_path), "--onedir", str(onedir), "--receipt", str(tmp_path / "pass.json"),
    ]) == 0


def test_default_rust_scope_includes_the_shipped_launcher() -> None:
    manifests = [path.relative_to(verifier.REPO_ROOT).as_posix() for path in verifier.default_cargo_manifests()]

    assert "packaging/launcher/Cargo.toml" in manifests
    assert any(path.startswith("src/metroliza/native/") for path in manifests)
