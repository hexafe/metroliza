"""Assemble and verify the user-facing Windows release ZIP.

The ZIP holds one folder with exactly:

* the native launcher ``metroliza_<version>_<build>_launcher.exe``;
* its original ``.provenance.json`` sidecar;
* its visible ``.licenses`` notice directory: ``NOTICE_MANIFEST.json``, ``THIRD_PARTY_NOTICES.md`` and
  the dependency inventory, nothing else;
* ``README.txt``: extract everything, then start the EXE.

``verify`` checks a downloaded ZIP without trusting its contents: safe, unique member names, the
exact file set and README text, the EXE hash and size against provenance, the required notices
against their manifest (and, with ``--source-root``, against their exact source paths), and the
payload embedded in the EXE. The
payload's content hash uses the packer's definition (``Manifest::content_sha256`` in
``packaging/launcher/src/manifest.rs``), so ``onedir-hash`` on the qualified onedir and
``--expected-content-sha256`` prove that the EXE's manifest declares exactly the qualified files.
The compressed blobs are not decoded here (LZ4, not in the standard library); only their layout
is checked. The blob bytes are proven by the launcher itself, which verifies every file's size and
SHA-256 while unpacking (``archive.rs::decode_file``) during the cold-start smoke; pass that
smoked EXE's hash as ``--expected-exe-sha256`` to bind the ZIP to those exact bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tempfile
from typing import Any
import zipfile

try:
    from scripts.stage_release_notices import DEFAULT_INVENTORY, DEFAULT_NOTICE, REPO_ROOT
except ImportError:  # pragma: no cover - direct ``python scripts/release_zip.py`` execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.stage_release_notices import DEFAULT_INVENTORY, DEFAULT_NOTICE, REPO_ROOT


LAUNCHER_NAME = re.compile(r"metroliza_(?P<version>[0-9]{4}\.[0-9]{2}[a-z0-9]+)_(?P<build>[0-9]{6})_launcher\.exe")
TRAILER_MAGIC = b"MTRLZPL1"
TRAILER_LEN = 64
CONTENT_PREFIX = b"metroliza-onedir-content-v1\n"
NOTICE_MANIFEST = "NOTICE_MANIFEST.json"
README = "README.txt"
CHUNK = 1024 * 1024
# The notice files every release must carry, by name, and where each comes from in the source.
REQUIRED_NOTICES = {
    DEFAULT_NOTICE.name: DEFAULT_NOTICE.relative_to(REPO_ROOT),
    DEFAULT_INVENTORY.name: DEFAULT_INVENTORY.relative_to(REPO_ROOT),
}


class ReleaseZipError(Exception):
    """The release ZIP or one of its inputs is incomplete or inconsistent."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_sha256(entry: str, files: list[tuple[str, int, str]]) -> str:
    """Return the packer content hash for ``(path, size, sha256)`` records."""
    digest = hashlib.sha256(CONTENT_PREFIX)
    digest.update(f"entry\0{entry}\n".encode())
    for path, size, file_sha256 in sorted(files):
        digest.update(f"{path}\0{size}\0{file_sha256}\n".encode())
    return digest.hexdigest()


def onedir_records(onedir: Path) -> list[tuple[str, int, str]]:
    """Return ``(relative POSIX path, size, sha256)`` for every file below ``onedir``."""
    records = []
    for root, directories, names in os.walk(onedir):
        directories.sort()
        for name in sorted(names):
            path = Path(root, name)
            if path.is_symlink():
                raise ReleaseZipError(f"symlink in onedir: {path}")
            records.append((path.relative_to(onedir).as_posix(), path.stat().st_size, _sha256_file(path)))
    if not records:
        raise ReleaseZipError(f"onedir is empty: {onedir}")
    return records


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _trailer_end(handle: Any, length: int) -> int:
    """End of the trailer: the certificate table start of a signed PE, else the file end."""
    handle.seek(0)
    header = handle.read(4096)
    if len(header) < 0x40 or header[:2] != b"MZ":
        return length
    pe = _u32(header, 0x3C)
    if pe + 24 + 2 > len(header) or header[pe:pe + 4] != b"PE\0\0":
        return length
    optional = pe + 24
    magic = _u16(header, optional)
    if magic == 0x10B:
        count_at, dirs_at = optional + 92, optional + 96
    elif magic == 0x20B:
        count_at, dirs_at = optional + 108, optional + 112
    else:
        return length
    if dirs_at + 5 * 8 > len(header) or _u32(header, count_at) <= 4:
        return length
    offset, size = _u32(header, dirs_at + 32), _u32(header, dirs_at + 36)
    if not offset or not size:
        return length
    if offset + size > length:
        raise ReleaseZipError("certificate table outside the EXE")
    return offset


def read_payload_manifest(exe: Path) -> dict[str, Any]:
    """Return the validated payload manifest embedded in a packed launcher EXE."""
    length = exe.stat().st_size
    with exe.open("rb") as handle:
        end = _trailer_end(handle, length)
        if end < TRAILER_LEN:
            raise ReleaseZipError("EXE too small for a payload trailer")
        handle.seek(end - TRAILER_LEN)
        trailer = handle.read(TRAILER_LEN)
        if trailer[:8] != TRAILER_MAGIC:
            raise ReleaseZipError("launcher payload trailer not found")
        payload_offset, payload_len, manifest_len = struct.unpack_from("<QQQ", trailer, 8)
        if manifest_len > payload_len or payload_offset + payload_len > end - TRAILER_LEN:
            raise ReleaseZipError("launcher payload trailer is inconsistent")
        handle.seek(payload_offset + payload_len - manifest_len)
        manifest_bytes = handle.read(manifest_len)
    if hashlib.sha256(manifest_bytes).digest() != trailer[32:64]:
        raise ReleaseZipError("launcher payload manifest hash mismatch")
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest.get("files"), list) or not isinstance(manifest.get("entry"), str):
        raise ReleaseZipError("launcher payload manifest has no file list or entry")
    _check_blob_layout(manifest["files"], payload_len - manifest_len)
    return manifest


def _check_blob_layout(files: list[dict[str, Any]], blob_region_len: int) -> None:
    """Require the blobs to tile the blob region exactly, in order, as the packer writes them."""
    position = 0
    for item in files:
        if int(item["offset"]) != position or int(item["compressed_size"]) < 0:
            raise ReleaseZipError(f"launcher payload blob layout is inconsistent at {item.get('path')!r}")
        position += int(item["compressed_size"])
    if position != blob_region_len:
        raise ReleaseZipError("launcher payload blobs do not fill the blob region")


def payload_content_sha256(manifest: dict[str, Any]) -> str:
    return content_sha256(
        manifest["entry"],
        [(item["path"], int(item["size"]), item["sha256"]) for item in manifest["files"]],
    )


def readme_text(exe_name: str, provenance: dict[str, Any]) -> str:
    label = provenance.get("release_label", "")
    git_sha = provenance.get("git_sha", "")
    return (
        f"Metroliza {label} for Windows (source {git_sha})\n"
        "\n"
        "1. Extract the whole ZIP to a folder (right-click > Extract All).\n"
        "   Do not start the EXE from inside the ZIP.\n"
        f"2. Double-click {exe_name}.\n"
        "\n"
        "No installer and no environment variables are needed. The first start unpacks the\n"
        "application once into your local app data folder; later starts are faster.\n"
        "\n"
        "Keep these files together:\n"
        f"- {exe_name}.provenance.json: build identity (SHA-256 of the EXE, source commit).\n"
        f"- {exe_name}.licenses\\: third-party notices and the dependency inventory.\n"
        "\n"
        "PL: Rozpakuj cale archiwum ZIP do folderu (prawy przycisk > Wyodrebnij wszystkie),\n"
        f"a potem uruchom dwuklikiem {exe_name}. Nie uruchamiaj EXE z wnetrza ZIP.\n"
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseZipError(f"{path.name} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseZipError(f"{path.name} is not a JSON object")
    return payload


def assemble(exe: Path, output: Path) -> Path:
    """Write the release ZIP for ``exe`` and its staged sidecars."""
    match = LAUNCHER_NAME.fullmatch(exe.name)
    if not match:
        raise ReleaseZipError(f"not a versioned launcher EXE name: {exe.name}")
    provenance_path = exe.with_name(f"{exe.name}.provenance.json")
    licenses = exe.with_name(f"{exe.name}.licenses")
    for required, kind in ((exe, "file"), (provenance_path, "file"), (licenses / NOTICE_MANIFEST, "file")):
        if not required.is_file():
            raise ReleaseZipError(f"required {kind} is missing: {required}")
    folder = f"metroliza_{match['version']}_{match['build']}"
    if output.exists():
        raise ReleaseZipError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    provenance = _load_json(provenance_path)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr(f"{folder}/{README}", readme_text(exe.name, provenance).replace("\n", "\r\n"))
        archive.write(exe, f"{folder}/{exe.name}")
        archive.write(provenance_path, f"{folder}/{provenance_path.name}")
        for notice in sorted(path for path in licenses.rglob("*") if path.is_file()):
            archive.write(notice, f"{folder}/{licenses.name}/{notice.relative_to(licenses).as_posix()}")
    return output


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    seen: set[str] = set()
    for info in archive.infolist():
        if info.filename.casefold() in seen:
            raise ReleaseZipError(f"duplicate member name: {info.filename!r}")
        seen.add(info.filename.casefold())
        name = PurePosixPath(info.filename)
        if info.filename.startswith(("/", "\\")) or "\\" in info.filename or ".." in name.parts or ":" in info.filename:
            raise ReleaseZipError(f"unsafe member name: {info.filename!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ReleaseZipError(f"symlink member: {info.filename!r}")
        if not info.is_dir():
            members.append(info)
    return members


def verify(
    zip_path: Path,
    *,
    expected_content_sha256: str | None = None,
    expected_source_sha: str | None = None,
    expected_exe_sha256: str | None = None,
    source_root: Path | None = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Verify a downloaded release ZIP; return the receipt or raise ``ReleaseZipError``."""
    with zipfile.ZipFile(zip_path) as archive:
        members = _safe_members(archive)
        tops = {PurePosixPath(info.filename).parts[0] for info in members}
        if len(tops) != 1 or any(len(PurePosixPath(info.filename).parts) < 2 for info in members):
            raise ReleaseZipError(f"expected exactly one top-level folder, found {sorted(tops)}")
        folder = tops.pop()
        names = {PurePosixPath(info.filename).relative_to(folder).as_posix() for info in members}
        exes = sorted(name for name in names if LAUNCHER_NAME.fullmatch(name))
        if len(exes) != 1:
            raise ReleaseZipError(f"expected exactly one launcher EXE, found {exes}")
        exe_name = exes[0]
        licenses = f"{exe_name}.licenses"
        if f"{licenses}/{NOTICE_MANIFEST}" not in names:
            raise ReleaseZipError(f"notice directory {licenses}/ with {NOTICE_MANIFEST} is missing")
        for required in (README, f"{exe_name}.provenance.json"):
            if required not in names:
                raise ReleaseZipError(f"{required} is missing")
        provenance = json.loads(archive.read(f"{folder}/{exe_name}.provenance.json"))
        if archive.read(f"{folder}/{README}").decode("utf-8") != readme_text(exe_name, provenance).replace("\n", "\r\n"):
            raise ReleaseZipError(f"{README} is not the release instruction for {exe_name}")
        with tempfile.TemporaryDirectory(dir=work_dir) as temporary:
            root = Path(temporary)
            archive.extractall(root, members)
            receipt = _verify_extracted(
                root / folder,
                exe_name,
                names,
                expected_content_sha256=expected_content_sha256,
                expected_source_sha=expected_source_sha,
                source_root=source_root,
            )
            if expected_exe_sha256 is not None and receipt["exe"]["sha256"] != expected_exe_sha256:
                raise ReleaseZipError("EXE differs from the smoke-tested launcher")
            return receipt | {"zip": {"name": zip_path.name, "sha256": _sha256_file(zip_path), "size_bytes": zip_path.stat().st_size}}


def _listed_notices(folder: Path, licenses: str) -> dict[str, str]:
    """Return ``name -> sha256`` of the notices, checked against ``NOTICE_MANIFEST.json``."""
    listed = _load_json(folder / licenses / NOTICE_MANIFEST).get("files")
    if not isinstance(listed, list) or not listed:
        raise ReleaseZipError(f"{NOTICE_MANIFEST} lists no files")
    notices: dict[str, str] = {}
    for item in listed:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or "/" in name or name in notices:
            raise ReleaseZipError(f"invalid {NOTICE_MANIFEST} entry: {item!r}")
        path = folder / licenses / name
        if not path.is_file():
            raise ReleaseZipError(f"notice listed in {NOTICE_MANIFEST} is missing: {name}")
        notices[name] = _sha256_file(path)
        if notices[name] != item.get("sha256"):
            raise ReleaseZipError(f"notice hash differs from {NOTICE_MANIFEST}: {name}")
    return notices


def _verify_notices(folder: Path, exe_name: str, names: set[str], source_root: Path | None) -> dict[str, str]:
    """Check the notice directory against its manifest, the exact file set and the source."""
    licenses = f"{exe_name}.licenses"
    notices = _listed_notices(folder, licenses)
    if set(notices) != set(REQUIRED_NOTICES):
        raise ReleaseZipError(f"notices must be exactly {sorted(REQUIRED_NOTICES)}, found {sorted(notices)}")
    expected = {README, exe_name, f"{exe_name}.provenance.json", f"{licenses}/{NOTICE_MANIFEST}"}
    expected.update(f"{licenses}/{name}" for name in notices)
    if names != expected:
        raise ReleaseZipError(f"unexpected file set: extra {sorted(names - expected)}, missing {sorted(expected - names)}")
    if source_root is not None:
        for name, digest in notices.items():
            source = source_root / REQUIRED_NOTICES[name]
            if not source.is_file() or _sha256_file(source) != digest:
                raise ReleaseZipError(f"notice {name} does not match {REQUIRED_NOTICES[name].as_posix()} in the source checkout")
    return notices


def _verify_provenance(exe: Path, provenance: dict[str, Any], expected_source_sha: str | None) -> str:
    """Check the EXE bytes and name against provenance; return the bound source commit."""
    artifact = provenance.get("artifact") or {}
    actual = {"name": exe.name, "sha256": _sha256_file(exe), "size_bytes": exe.stat().st_size}
    if {key: artifact.get(key) for key in actual} != actual:
        raise ReleaseZipError("EXE name, SHA-256 or size differs from its provenance")
    git_sha = provenance.get("git_sha")
    if not isinstance(git_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", git_sha) or provenance.get("dirty") is not False:
        raise ReleaseZipError("provenance does not bind a clean full source commit")
    if expected_source_sha is not None and git_sha != expected_source_sha:
        raise ReleaseZipError(f"provenance source {git_sha} is not the expected {expected_source_sha}")
    match = LAUNCHER_NAME.fullmatch(exe.name)
    if provenance.get("release_label") != f"{match['version']}({match['build']})":
        raise ReleaseZipError("EXE name differs from the provenance release label")
    return git_sha


def _verify_payload(exe: Path, git_sha: str, expected_content_sha256: str | None) -> dict[str, Any]:
    """Check the embedded payload against the provenance commit and the qualified onedir."""
    manifest = read_payload_manifest(exe)
    payload_sha256 = payload_content_sha256(manifest)
    if manifest.get("git_sha") != git_sha:
        raise ReleaseZipError("embedded payload commit differs from provenance")
    if not str(manifest.get("version", "")).endswith(payload_sha256[:12]):
        raise ReleaseZipError("embedded payload version does not carry its content key")
    if expected_content_sha256 is not None and payload_sha256 != expected_content_sha256:
        raise ReleaseZipError("embedded payload differs from the qualified onedir")
    return {
        "entry": manifest["entry"],
        "file_count": len(manifest["files"]),
        "content_sha256": payload_sha256,
        "runtime_dir": f"{manifest['version']}_{git_sha[:8]}",
    }


def _verify_extracted(
    folder: Path,
    exe_name: str,
    names: set[str],
    *,
    expected_content_sha256: str | None,
    expected_source_sha: str | None,
    source_root: Path | None,
) -> dict[str, Any]:
    exe = folder / exe_name
    notices = _verify_notices(folder, exe_name, names, source_root)
    provenance = _load_json(folder / f"{exe_name}.provenance.json")
    git_sha = _verify_provenance(exe, provenance, expected_source_sha)
    return {
        "status": "PASS",
        "exe": {"name": exe_name, "sha256": provenance["artifact"]["sha256"], "size_bytes": exe.stat().st_size},
        "source": {"git_sha": git_sha, "release_label": provenance["release_label"]},
        "payload": _verify_payload(exe, git_sha, expected_content_sha256),
        "notices": notices,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    hashed = commands.add_parser("onedir-hash", help="Print the packer content hash of an onedir.")
    hashed.add_argument("onedir", type=Path)
    hashed.add_argument("--entry", default="metroliza.exe")
    built = commands.add_parser("assemble")
    built.add_argument("--exe", required=True, type=Path)
    built.add_argument("--output", required=True, type=Path)
    checked = commands.add_parser("verify")
    checked.add_argument("zip", type=Path)
    checked.add_argument("--expected-content-sha256")
    checked.add_argument("--expected-source-sha")
    checked.add_argument("--expected-exe-sha256", help="SHA-256 of the EXE that passed the launcher smoke.")
    checked.add_argument("--source-root", type=Path)
    checked.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "onedir-hash":
            print(content_sha256(args.entry, onedir_records(args.onedir)))
        elif args.command == "assemble":
            print(assemble(args.exe, args.output))
        else:
            receipt = verify(
                args.zip,
                expected_content_sha256=args.expected_content_sha256,
                expected_source_sha=args.expected_source_sha,
                expected_exe_sha256=args.expected_exe_sha256,
                source_root=args.source_root,
            )
            text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            if args.receipt:
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(text, encoding="utf-8")
            print(text, end="")
    except (ReleaseZipError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
