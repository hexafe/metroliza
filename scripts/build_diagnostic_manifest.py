"""Record exact launcher child/runtime component hashes after a Windows onedir build."""

from __future__ import annotations

import json
from pathlib import Path

from metroliza.shared.diagnostic_package import COMPONENTS, MANIFEST_NAME, component_hash


def write_supervision_manifest(directory: Path) -> Path:
    provenance = json.loads((directory / COMPONENTS[-1]).read_text(encoding="utf-8"))
    sha = provenance["git_sha"]
    import re

    if type(sha) is not str or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("exact_build_identity_required")
    manifest = {
        "schema_version": 1, "packager": "pyinstaller", "layout": "onedir",
        "git_sha": sha, "components": {name: component_hash(directory, name) for name in COMPONENTS},
    }
    destination = directory / MANIFEST_NAME
    with destination.open("x", encoding="ascii") as stream:
        stream.write(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    return destination
