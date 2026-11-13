"""Closed release identity; build timestamps and content keys are separate facts."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

_NUMBER = r"(?:0|[1-9][0-9]{0,4})"
VERSION_PATTERN = rf"{_NUMBER}\.{_NUMBER}\.{_NUMBER}(?:-(?:dev|rc)\.[1-9][0-9]{{0,4}})?"
_VERSION = re.compile(rf"(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})\.(?P<patch>{_NUMBER})"
                      r"(?:-(?P<channel>dev|rc)\.(?P<number>[1-9][0-9]{0,4}))?")
LEGACY_VERSION_PATTERN = r"[0-9]{4}\.[0-9]{2}rc[1-9][0-9]{0,2}"
LAUNCHER_NAME = re.compile(
    rf"(?:Metroliza-(?P<semver>{VERSION_PATTERN})-windows-x64|"
    rf"metroliza_(?P<version>{LEGACY_VERSION_PATTERN})_(?P<build>[0-9]{{6}})_launcher)\.exe"
)
_LEGACY_APP = re.compile(
    rf"(?:metroliza_p_{LEGACY_VERSION_PATTERN}\([0-9]{{6}}\)|"
    rf"metroliza_{LEGACY_VERSION_PATTERN}_[0-9]{{6}}(?:_launcher)?)\.exe"
)


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    major: int
    minor: int
    patch: int
    channel: str | None = None
    number: int | None = None

    def __post_init__(self) -> None:
        if (any(type(v) is not int or not 0 <= v <= 65535 for v in (self.major, self.minor, self.patch))
                or (self.channel is not None and type(self.channel) is not str)
                or self.channel not in (None, "dev", "rc")
                or (self.channel is None and self.number is not None)
                or (self.channel is not None and (type(self.number) is not int or not 1 <= self.number <= 19999))):
            raise ValueError("invalid release identity")

    @classmethod
    def parse(cls, value: object) -> ReleaseIdentity:
        if type(value) is not str or len(value) > 51 or (match := _VERSION.fullmatch(value)) is None:
            raise ValueError("invalid release identity")
        return cls(int(match["major"]), int(match["minor"]), int(match["patch"]), match["channel"],
                   int(match["number"]) if match["number"] else None)

    @property
    def label(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        return core if self.channel is None else f"{core}-{self.channel}.{self.number}"

    @property
    def pe_version(self) -> tuple[int, int, int, int]:
        if self.channel is None:
            revision = 65535
        else:
            assert self.number is not None  # Established by the closed constructor.
            revision = self.number + (20000 if self.channel == "rc" else 0)
        return self.major, self.minor, self.patch, revision

    @property
    def folder_name(self) -> str:
        return f"Metroliza-{self.label}-windows-x64"

    @property
    def launcher_name(self) -> str:
        return self.folder_name + ".exe"

    @property
    def zip_name(self) -> str:
        return self.folder_name + ".zip"

    @property
    def portable_name(self) -> str:
        return self.folder_name + "-portable.exe"

    @property
    def nuitka_name(self) -> str:
        return self.folder_name + "-nuitka.exe"

    @property
    def onedir_name(self) -> str:
        return f"metroliza_P_{self.label}_onedir"


def current_identity(root: Path) -> ReleaseIdentity:
    """Read one literal without importing the application or executing metadata."""
    for node in ast.parse((root / "src/metroliza/app/version.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RELEASE_VERSION" for t in node.targets):
            if isinstance(node.value, ast.Constant):
                return ReleaseIdentity.parse(node.value.value)
    raise ValueError("invalid release identity")


def launcher_identity(name: str) -> tuple[str, str]:
    """Strict new names plus immutable historical launcher names for archive verification."""
    match = LAUNCHER_NAME.fullmatch(name)
    if match is None:
        raise ValueError("invalid launcher identity")
    if match["semver"]:
        identity = ReleaseIdentity.parse(match["semver"])
        return identity.label, identity.folder_name
    return f"{match['version']}({match['build']})", f"metroliza_{match['version']}_{match['build']}"


def legacy_fault_app(name: str) -> bool:
    """Bounded historical executable class; no paths, arbitrary strings or current-version fallback."""
    return type(name) is str and len(name) <= 100 and _LEGACY_APP.fullmatch(name) is not None


def pe_resource_text(identity: ReleaseIdentity) -> str:
    """PyInstaller's owned version-resource text; only validated finite values enter it."""
    if type(identity) is not ReleaseIdentity:
        raise ValueError("invalid release identity")
    version = identity.pe_version
    flags = 0 if identity.channel is None else 2  # VS_FF_PRERELEASE
    return ("VSVersionInfo(ffi=FixedFileInfo("
            f"filevers={version!r}, prodvers={version!r}, mask=0x3f, flags={flags}, "
            "OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)), kids=["
            "StringFileInfo([StringTable('040904B0', ["
            "StringStruct('CompanyName', 'Hexafe'), StringStruct('ProductName', 'Metroliza'), "
            f"StringStruct('FileVersion', {identity.label!r}), "
            f"StringStruct('ProductVersion', {identity.label!r})])]), "
            "VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n")
