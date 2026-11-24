"""Private successful-run receipts and portable bundles of generated outputs."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from heapq import heappush, heappushpop
from html.parser import HTMLParser
from io import TextIOWrapper
import json
import os
import re
from pathlib import Path
import stat
import tempfile
from time import monotonic
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from metroliza.exporting.output_publication import publish_output
from metroliza.shared.local_app_paths import local_metroliza_directory


_OUTPUT_SUFFIXES = {".xlsx", ".html", ".htm"}
_ASSET_SUFFIXES = {".css", ".js", ".json", ".png", ".svg", ".webp", ".jpg", ".jpeg", ".woff2"}
_PLOTLY_NOTICE_FILENAME = "plotly.min.js.LICENSE.txt"
_PLOTLY_BUNDLE_FILENAME = "plotly-2.27.0.min.js"
_MAX_RECEIPT_BYTES = 2_000_000
_RECENT_LIMIT = 100
_MAX_LIST_ENTRIES = 20_000
_MAX_LIST_BYTES = 16 * 1024**2
_MAX_LIST_SECONDS = 3
# Listing limits never prune saved receipts. Storage retention is tracked by #949.


@dataclass(frozen=True)
class AnalysisListing:
    receipts: tuple[dict, ...]
    partial: bool = False


def _history_directory():
    return local_metroliza_directory() / "analysis-history"


def _file_stamp(path):
    entry = Path(path).stat()
    return [entry.st_dev, entry.st_ino, entry.st_size, entry.st_mtime_ns]


def capture_source_stamp(source):
    """Capture the input identity before reading it, including a live SQLite WAL."""
    try:
        path = Path(source)
        wal = path.with_name(path.name + "-wal")
        live = _file_stamp(wal) if wal.is_file() and wal.stat().st_size else None
        return [_file_stamp(path), live]
    except (TypeError, OSError):
        return None


def _asset_files(directory, outputs):
    if not any(path.parent == directory.parent and path.suffix.lower() in {".htm", ".html"}
               for path in outputs):
        raise ValueError("Dashboard resources must be next to the dashboard.")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("A dashboard resource points outside the result. Run the analysis again.")
        is_plotly_notice = (
            path.name == _PLOTLY_NOTICE_FILENAME and path.with_name(_PLOTLY_BUNDLE_FILENAME).is_file()
        )
        if path.is_file() and (path.suffix.lower() in _ASSET_SUFFIXES or is_plotly_notice):
            yield path.relative_to(directory.parent).as_posix(), str(path), _file_stamp(path)


def _output_entries(paths):
    values = tuple(dict.fromkeys(Path(path).absolute() for path in paths if path))
    if any(path.is_symlink() for path in values):
        raise ValueError("The result contains a shortcut instead of a published file.")
    files = [path for path in values if path.is_file() and path.suffix.lower() in _OUTPUT_SUFFIXES]
    entries = [(path.name, str(path), _file_stamp(path)) for path in files]
    for directory in (path for path in values if path.is_dir()):
        entries.extend(_asset_files(directory, files))
    return files, entries


def record_analysis(receipt, *, directory=None):
    files, entries = _output_entries((*receipt["artifacts"], *receipt.get("assets", ())))
    if not files:
        return None
    source = str(Path(receipt["source"]).absolute()) if receipt.get("source") else None
    current_stamp = None if "report_folder_revision" in receipt else capture_source_stamp(source)
    submitted_stamp = receipt.get("source_stamp", current_stamp)
    timestamp = datetime.now(timezone.utc)
    name = f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}.json"
    entry = {
        "version": 1,
        "at": timestamp.isoformat(),
        "kind": str(receipt["kind"]),
        "source": source,
        "source_stamp": submitted_stamp,
        "source_changed_during_run": bool(source and submitted_stamp and submitted_stamp != current_stamp),
        "settings": receipt.get("settings", {}),
        "files": [str(path) for path in files],
        "entries": entries,
    }
    if "report_folder_revision" in receipt:
        entry["report_folder_revision"] = receipt["report_folder_revision"]
    root = Path(directory) if directory is not None else _history_directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / name
    content = json.dumps(entry, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(content) > _MAX_RECEIPT_BYTES:
        raise ValueError("The result has too many entries to record in analysis history.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return entry


def _recent_receipt_names(root, interrupted):
    names = []
    try:
        with os.scandir(root) as children:
            for index, item in enumerate(children):
                if index >= _MAX_LIST_ENTRIES or interrupted():
                    return names, True
                if not item.name.endswith(".json") or not item.is_file(follow_symlinks=False):
                    continue
                if len(names) < _RECENT_LIMIT:
                    heappush(names, item.name)
                else:
                    heappushpop(names, item.name)
    except FileNotFoundError:
        return names, bool(names)
    except OSError:
        return names, True
    return names, False


def _read_receipt(path, budget):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        named = path.lstat()
        if (not stat.S_ISREG(named.st_mode) or not os.path.samestat(info, named)
                or info.st_size > _MAX_RECEIPT_BYTES):
            return b""
        return stream.read(min(budget, _MAX_RECEIPT_BYTES) + 1)


def load_recent_analyses(*, directory=None, cancelled=lambda: False):
    """List recent receipts within bounded read budgets, retaining all history on disk."""
    root = Path(directory) if directory is not None else _history_directory()
    deadline = monotonic() + _MAX_LIST_SECONDS

    def interrupted():
        return cancelled() or monotonic() >= deadline

    names, partial = _recent_receipt_names(root, interrupted)
    budget = _MAX_LIST_BYTES
    receipts = []
    for name in sorted(names, reverse=True):
        if interrupted() or budget <= 0:
            return AnalysisListing(tuple(receipts), partial=True)
        try:
            content = _read_receipt(root / name, budget)
            budget -= len(content)
            if budget < 0:
                return AnalysisListing(tuple(receipts), partial=True)
            if 0 < len(content) <= _MAX_RECEIPT_BYTES:
                receipt = json.loads(content)
                if _readable_receipt(receipt):
                    receipts.append(receipt)
        except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
            continue
    return AnalysisListing(tuple(receipts), partial or interrupted())


def recent_analyses(*, directory=None):
    yield from load_recent_analyses(directory=directory).receipts


def _readable_receipt(receipt):
    datetime.fromisoformat(receipt["at"]).astimezone()
    return (
        receipt["version"] == 1
        and isinstance(receipt["kind"], str)
        and isinstance(receipt["entries"], list)
        and isinstance(receipt["settings"], dict)
        and isinstance(receipt["files"], list)
        and bool(receipt["files"])
        and all(isinstance(path, str) for path in receipt["files"])
    )


def has_report_folder_revision(receipt):
    value = receipt.get("report_folder_revision")
    return bool(isinstance(receipt.get("source"), str) and receipt["source"]
                and isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value))


def analysis_is_stale(receipt, *, cancelled=lambda: False):
    """Return True for changed sources, False for current and None for unconfirmed folders."""
    source = receipt.get("source")
    if "report_folder_revision" in receipt:
        if not has_report_folder_revision(receipt):
            return None
        from metroliza.parsing.report_folder_revision import revision_from_folder

        current = revision_from_folder(source, outputs=receipt["files"], cancelled=cancelled)
        return None if current is None else current != receipt["report_folder_revision"]
    if receipt.get("kind") == "recipe" and source:
        try:
            if Path(source).is_dir():
                return None  # Older folder receipts contain only the parent directory stat.
        except (OSError, TypeError, ValueError):
            return None
    stored = receipt.get("source_stamp")
    return bool(receipt.get("source_changed_during_run") or (
        source and stored and stored != capture_source_stamp(source)
    ))


def result_still_matches(receipt, path):
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            return False
        stamp = _file_stamp(path)
        return any(raw_path == str(path) and expected == stamp for _, raw_path, expected in receipt["entries"])
    except (OSError, TypeError, ValueError):
        return False


def _archive_member(name, raw_path, stamp):
    path = Path(raw_path)
    parts = name.split("/")
    if (not all(part and part not in {".", ".."} and "\\" not in part and ":" not in part for part in parts)
            or path.is_symlink() or not path.is_file() or _file_stamp(path) != stamp):
        raise ValueError("A result or its resources changed after export. Run the analysis again to package it.")
    return path


def _copy_to_archive(archive, name, path):
    digest = hashlib.sha256()
    with path.open("rb") as data, archive.open(name, "w", force_zip64=True) as member:
        for block in iter(lambda: data.read(1024 * 1024), b""):
            digest.update(block)
            member.write(block)
    return digest.hexdigest()


class _DashboardResources(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"script", "img"} and attributes.get("src"):
            self.urls.add(attributes["src"])
        if tag == "link" and attributes.get("rel") == "stylesheet" and attributes.get("href"):
            self.urls.add(attributes["href"])


def _verify_dashboard_resources(archive, names):
    for name in names:
        if Path(name).suffix.lower() not in {".html", ".htm"}:
            continue
        parser = _DashboardResources()
        with archive.open(name) as binary:
            with TextIOWrapper(binary, encoding="utf-8") as html:
                for text in iter(lambda: html.read(65536), ""):
                    parser.feed(text)
        parser.close()
        for reference in parser.urls:
            url = urlsplit(reference)
            if url.scheme == "data":
                continue
            if url.scheme or url.netloc or unquote(url.path).removeprefix("./") not in names:
                raise ValueError("A dashboard resource is missing from the results. Run the analysis again to package it.")


def _write_bundle(staged, entries):
    manifest = {}
    with ZipFile(staged, "w", compression=ZIP_DEFLATED, compresslevel=3) as archive:
        names = {"metroliza-results.json"}
        for name, raw_path, stamp in entries:
            if name.casefold() in names:
                raise ValueError("Two results have the same name. Save them with different names before packaging.")
            path = _archive_member(name, raw_path, stamp)
            manifest[name] = _copy_to_archive(archive, name, path)
            _archive_member(name, raw_path, stamp)
            names.add(name.casefold())
        archive.writestr("metroliza-results.json", json.dumps({"version": 1, "sha256": manifest}, indent=2))
    with ZipFile(staged) as archive:
        if archive.testzip() is not None:
            raise ValueError("The packaged outputs could not be verified.")
        _verify_dashboard_resources(archive, manifest)


def bundle_analysis(receipt, destination, consents=()):
    target = Path(destination)
    entries = receipt["entries"]
    if not entries:
        raise ValueError("No published outputs are available for this analysis.")
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        _write_bundle(staged, entries)
        publish_output(staged, target, consents=consents)
    finally:
        staged.unlink(missing_ok=True)
    return target
