"""Identify explicitly supplied scratch storage for the Windows cache tests."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile

from metroliza.shared.sqlite_snapshot import is_symlink_or_reparse


_DRIVE_LOCAL = {2, 3}  # DRIVE_REMOVABLE and DRIVE_FIXED
_DRIVE_REMOTE = 4
_FILE_SUPPORTS_HARD_LINKS = 0x00400000
_LOCAL_FILESYSTEMS = {"NTFS": {"NTFS"}, "FAT": {"FAT", "FAT32"}, "EXFAT": {"EXFAT"}}
_SMB_CONNECTION_QUERY = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$connections = @(Get-SmbConnection | Select-Object ServerName, ShareName, Dialect, NumOpens)
ConvertTo-Json -InputObject $connections -Compress
"""


def windows_scratch_root(value: str, storage: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.drive.startswith(("\\\\?\\", "\\\\.\\")):
        raise ValueError("Supply an absolute Win32 scratch directory")
    if path.drive.startswith("\\\\") != (storage == "SMB"):
        raise ValueError("Use explicit UNC for SMB and a local path for a local volume")
    status = path.lstat()
    if is_symlink_or_reparse(status) or not path.is_dir():
        raise ValueError("Supply an existing scratch directory without a reparse leaf")
    resolved = path.resolve(strict=True)
    if resolved.drive.casefold() != path.drive.casefold():
        raise ValueError("The scratch path must remain on its supplied drive or UNC share")
    return resolved


def _get_drive_type(kernel32, anchor: str) -> int:
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = [wintypes.LPCWSTR]
    get_drive_type.restype = wintypes.UINT
    return get_drive_type(anchor)


def _local_volume_identity(kernel32, scratch: Path, storage: str) -> dict[str, object]:
    get_volume_path = kernel32.GetVolumePathNameW
    get_volume_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_volume_path.restype = wintypes.BOOL
    volume = ctypes.create_unicode_buffer(32768)
    if not get_volume_path(str(scratch), volume, len(volume)):
        raise ctypes.WinError(ctypes.get_last_error())
    drive_type = _get_drive_type(kernel32, volume.value)
    if drive_type not in _DRIVE_LOCAL:
        raise ValueError(f"{storage} needs a local volume, got drive type {drive_type}")

    get_volume_info = kernel32.GetVolumeInformationW
    get_volume_info.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD,
    ]
    get_volume_info.restype = wintypes.BOOL
    flags = wintypes.DWORD()
    filesystem = ctypes.create_unicode_buffer(256)
    if not get_volume_info(
        volume.value, None, 0, None, None, ctypes.byref(flags), filesystem, len(filesystem),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if filesystem.value.upper() not in _LOCAL_FILESYSTEMS[storage]:
        raise ValueError(f"{storage} scratch reported filesystem {filesystem.value}")
    supports_hard_links = bool(flags.value & _FILE_SUPPORTS_HARD_LINKS)
    if supports_hard_links != (storage == "NTFS"):
        raise ValueError(f"{storage} reported unexpected hard-link support: {supports_hard_links}")
    return {
        "filesystem": filesystem.value,
        "drive_type": drive_type,
        "supports_hard_links": supports_hard_links,
    }


def _smb_identity(kernel32, scratch: Path) -> dict[str, object]:
    if _get_drive_type(kernel32, scratch.anchor) != _DRIVE_REMOTE:
        raise ValueError("The UNC scratch path did not report DRIVE_REMOTE")
    server, share = scratch.drive[2:].split("\\")
    powershell = (
        Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0"
        / "powershell.exe"
    )
    # Read the connection table while our own UNC handle is open.
    with tempfile.NamedTemporaryFile(prefix="smb-probe-", dir=scratch):
        completed = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", _SMB_CONNECTION_QUERY],
            capture_output=True, check=False, timeout=20, encoding="utf-8",
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Get-SmbConnection failed, exit code {completed.returncode}")
    matches = [
        str(row["Dialect"]) for row in json.loads(completed.stdout)
        if row["ServerName"].casefold() == server.casefold()
        and row["ShareName"].casefold() == share.casefold()
        and row["NumOpens"] > 0 and row["Dialect"]
    ]
    if len(matches) != 1:
        raise RuntimeError("The UNC path did not have one matching active SMB connection")
    return {"filesystem": "SMB", "drive_type": _DRIVE_REMOTE, "smb_dialect": matches[0]}


def windows_storage_identity(scratch: Path, storage: str) -> dict[str, object]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if storage == "SMB":
        return _smb_identity(kernel32, scratch)
    return _local_volume_identity(kernel32, scratch, storage)
