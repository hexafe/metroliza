"""Runtime access to provenance embedded by release packaging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Mapping

from metroliza.app.version import VERSION_LABEL


BUILD_PROVENANCE_FILENAME = "build_provenance.json"
BUILD_PROVENANCE_SCHEMA_VERSION = 1
UNKNOWN_GIT_SHA = "unknown"
_FULL_GIT_SHA = re.compile(r"[0-9a-f]{40,64}")


@dataclass(frozen=True)
class BuildProvenance:
    """Identity of the source tree and toolchain used for one packaged build."""

    release_label: str
    git_sha: str
    dirty: bool | None
    built_at_utc: str | None
    packager: str
    python_version: str
    schema_version: int = BUILD_PROVENANCE_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> BuildProvenance:
        """Validate and construct provenance loaded from an embedded manifest."""

        schema_version = payload.get("schema_version")
        if schema_version != BUILD_PROVENANCE_SCHEMA_VERSION:
            raise ValueError(f"Unsupported build provenance schema: {schema_version!r}")

        dirty = payload.get("dirty")
        if not isinstance(dirty, bool):
            raise ValueError("Build provenance field 'dirty' must be a boolean")

        required_strings = {
            field: payload.get(field)
            for field in (
                "release_label",
                "git_sha",
                "built_at_utc",
                "packager",
                "python_version",
            )
        }
        invalid = [field for field, value in required_strings.items() if not isinstance(value, str) or not value]
        if invalid:
            raise ValueError(
                "Build provenance fields must be non-empty strings: " + ", ".join(sorted(invalid))
            )

        git_sha = required_strings["git_sha"].lower()
        if _FULL_GIT_SHA.fullmatch(git_sha) is None:
            raise ValueError("Build provenance field 'git_sha' must contain a full commit hash")
        if required_strings["packager"] not in {"pyinstaller", "nuitka"}:
            raise ValueError("Build provenance field 'packager' is unsupported")
        try:
            built_at = datetime.fromisoformat(required_strings["built_at_utc"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Build provenance field 'built_at_utc' is not ISO-8601") from exc
        if built_at.utcoffset() != timezone.utc.utcoffset(built_at):
            raise ValueError("Build provenance field 'built_at_utc' must use UTC")

        return cls(
            release_label=required_strings["release_label"],
            git_sha=git_sha,
            dirty=dirty,
            built_at_utc=required_strings["built_at_utc"],
            packager=required_strings["packager"],
            python_version=required_strings["python_version"],
            schema_version=schema_version,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the stable JSON representation shared with build tooling."""

        return {
            "schema_version": self.schema_version,
            "release_label": self.release_label,
            "git_sha": self.git_sha,
            "dirty": self.dirty,
            "built_at_utc": self.built_at_utc,
            "packager": self.packager,
            "python_version": self.python_version,
        }


def source_build_provenance() -> BuildProvenance:
    """Return an explicit fallback for a source checkout without an embedded manifest."""

    return BuildProvenance(
        release_label=VERSION_LABEL,
        git_sha=UNKNOWN_GIT_SHA,
        dirty=None,
        built_at_utc=None,
        packager="source",
        python_version=platform.python_version(),
    )


def load_build_provenance(manifest_path: str | Path | None = None) -> BuildProvenance:
    """Load embedded provenance, falling back safely for normal source execution."""

    path = (
        Path(manifest_path)
        if manifest_path is not None
        else Path(__file__).with_name(BUILD_PROVENANCE_FILENAME)
    )
    if not path.is_file():
        return source_build_provenance()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Build provenance manifest must contain a JSON object")
        return BuildProvenance.from_mapping(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return source_build_provenance()


def runtime_mode() -> str:
    """Return the concise execution mode used in startup diagnostics."""

    if bool(getattr(sys, "frozen", False)) or "__compiled__" in globals():
        return "frozen"
    return "source"
