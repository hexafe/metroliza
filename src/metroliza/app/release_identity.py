"""Compatibility exports for the neutral shared release identity contract."""
from metroliza.shared.release_identity import (
    LAUNCHER_NAME,
    LEGACY_VERSION_PATTERN,
    VERSION_PATTERN,
    ReleaseIdentity,
    current_identity,
    launcher_identity,
    legacy_fault_app,
    pe_resource_text,
)

__all__ = [
    "LAUNCHER_NAME",
    "LEGACY_VERSION_PATTERN",
    "VERSION_PATTERN",
    "ReleaseIdentity",
    "current_identity",
    "launcher_identity",
    "legacy_fault_app",
    "pe_resource_text",
]
