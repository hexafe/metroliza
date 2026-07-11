from __future__ import annotations

from pathlib import Path

from scripts.generate_third_party_inventory import requirement_roots


def test_requirement_roots_follow_nested_runtime_files(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.txt"
    extras = tmp_path / "extras.txt"
    runtime.write_text(
        "Example_Package>=1\ninternal-tool @ git+https://example.invalid/tool.git@abc\n",
        encoding="utf-8",
    )
    extras.write_text("-r runtime.txt\nPyYAML>=6\n", encoding="utf-8")

    assert requirement_roots((extras,)) == (
        "example-package",
        "internal-tool",
        "pyyaml",
    )


def test_every_native_manifest_has_a_release_lockfile() -> None:
    manifests = tuple(sorted(Path("src/metroliza/native").glob("*/Cargo.toml")))

    assert manifests
    assert all(manifest.with_name("Cargo.lock").is_file() for manifest in manifests)
