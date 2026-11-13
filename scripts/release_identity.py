"""Canonical artifact names and owned Windows version resources (no build-date synthesis)."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from metroliza.app.release_identity import ReleaseIdentity, current_identity, pe_resource_text  # noqa: E402


def write_resource(path: Path, identity: ReleaseIdentity) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pe_resource_text(identity), encoding="utf-8")
    return path


def _verified_pe_strings(query, identity: ReleaseIdentity) -> dict[str, str]:
    strings = {}
    for name in ("FileVersion", "ProductVersion"):
        pointer, length = query("\\StringFileInfo\\040904B0\\" + name)
        if pointer.value is None or not 0 < length <= 128:
            raise ValueError("invalid PE version string")
        text = ctypes.wstring_at(pointer, length)
        if not text.endswith("\0"):
            raise ValueError("unterminated PE version string")
        strings[name] = text[:-1]
        if strings[name] != identity.label:
            raise ValueError("PE full version differs from canonical release")
    return strings


def _verify_pe_fixed(pointer, length: int, identity: ReleaseIdentity) -> None:
    if pointer.value is None or length < 52:
        raise ValueError("invalid PE fixed version")
    fixed = (ctypes.c_uint32 * 13).from_address(pointer.value)
    if fixed[0] != 0xFEEF04BD:
        raise ValueError("invalid PE fixed version signature")
    for ms, ls in ((fixed[2], fixed[3]), (fixed[4], fixed[5])):
        if (ms >> 16, ms & 65535, ls >> 16, ls & 65535) != identity.pe_version:
            raise ValueError("PE numeric projection differs from canonical release")


def verify_pe(path: Path, identity: ReleaseIdentity) -> dict:
    """Read the actual Windows PE resource; no fixture/fallback mode is accepted."""
    if os.name != "nt":
        raise RuntimeError("PE version verification requires Windows")
    from ctypes import wintypes

    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                  ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT)]
    api.VerQueryValueW.restype = wintypes.BOOL
    size = api.GetFileVersionInfoSizeW(str(path.resolve()), None)
    if not 0 < size <= 1024 * 1024:
        raise ValueError("missing or unbounded PE version resource")
    buffer = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path.resolve()), 0, size, buffer):
        raise ValueError("unreadable PE version resource")

    def query(key):
        pointer, length = wintypes.LPVOID(), wintypes.UINT()
        if not api.VerQueryValueW(buffer, key, ctypes.byref(pointer), ctypes.byref(length)):
            raise ValueError("required PE version field missing")
        return pointer, length.value

    strings = _verified_pe_strings(query, identity)
    pointer, length = query("\\")
    _verify_pe_fixed(pointer, length, identity)
    return {"status": "PASS", **strings, "numeric_version": list(identity.pe_version)}


def stamp_stub(source: Path, output: Path, identity: ReleaseIdentity) -> None:
    """Stamp a copied owned Rust stub BEFORE any payload/certificate is appended."""
    if os.name != "nt" or source.name != "metroliza-launcher.exe" or source.resolve() == output.resolve():
        raise ValueError("owned Windows stub copy required")
    with source.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("owned stub is not a PE")
        from scripts.release_zip import _trailer_end

        end = _trailer_end(stream, source.stat().st_size)
        stream.seek(max(0, end - 64))
        if stream.read(8) == b"MTRLZPL1":
            raise ValueError("cannot stamp an appended payload")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    resource = write_resource(output.with_suffix(".version.txt"), identity)
    from PyInstaller.utils.win32.versioninfo import (
        load_version_info_from_text_file,
        write_version_info_to_executable,
    )

    info = load_version_info_from_text_file(str(resource))
    write_version_info_to_executable(str(output), info)
    verify_pe(output, identity)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("names", "stamp-stub", "verify-pe"))
    parser.add_argument("--version")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    identity = ReleaseIdentity.parse(args.version) if args.version is not None else current_identity(ROOT)
    if args.command == "names":
        print(json.dumps({"version": identity.label, "launcher": identity.launcher_name,
                          "portable": identity.portable_name, "zip": identity.zip_name,
                          "folder": identity.folder_name, "onedir": identity.onedir_name,
                          "nuitka": identity.nuitka_name}))
    elif args.command == "stamp-stub":
        if args.input is None or args.output is None:
            parser.error("stamp-stub requires --input and --output")
        stamp_stub(args.input, args.output, identity)
    else:
        if args.input is None:
            parser.error("verify-pe requires --input")
        print(json.dumps(verify_pe(args.input, identity)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
