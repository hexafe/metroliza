"""Compare exports exactly except documented timestamps and the paired dashboard generation token."""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import html
from html.parser import HTMLParser
from itertools import zip_longest
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
from urllib.parse import quote
from defusedxml import ElementTree as ET
from zipfile import ZipFile
import zlib

ISO_TIMESTAMP = re.compile(rb"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")
HTML_GENERATED = re.compile(
    rb'("generated_at"\s*:\s*")([^"<>]+)(")|(<dt>Generated at</dt><dd>)(.*?)(</dd>)', re.DOTALL
)
CORE_TIME = re.compile(
    rb"(<dcterms:(created|modified)\b[^>]*>)([^<]*)(</dcterms:\2>)"
)
GENERATION_ASSET_BASES = ("export_dashboard_assets", "export_assets")
GENERATION_NAME = re.compile(r"(?P<asset_base>export(?:_dashboard)?_assets)\.generation-[0-9a-f]{32}\Z")
HTML_ATTRIBUTE = re.compile(r'''(?<!\S)([^\s/=>]+)\s*=\s*(["'])(.*?)\2''', re.DOTALL)


def _html_without_times(data: bytes) -> bytes:
    def replace(match):
        if match.group(1):
            return match.group(1) + ISO_TIMESTAMP.sub(b"TIMESTAMP", match.group(2)) + match.group(3)
        return match.group(4) + ISO_TIMESTAMP.sub(b"TIMESTAMP", match.group(5)) + match.group(6)
    return HTML_GENERATED.sub(replace, data)


def _core_without_times(data: bytes) -> bytes:
    root = ET.fromstring(data)  # Malformed packages must never compare equal.
    for tag in ("created", "modified"):
        for element in root.findall("{http://purl.org/dc/terms/}" + tag):
            if not ISO_TIMESTAMP.fullmatch((element.text or "").encode()):
                raise ValueError("invalid XLSX core timestamp")
    return CORE_TIME.sub(lambda match: match[1] + b"TIMESTAMP" + match[4]
                         if ISO_TIMESTAMP.fullmatch(match[3]) else match[0], data)


def _bytes_difference(left: bytes, right: bytes) -> str | None:
    if left == right:
        return None
    offset = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
    return f"bytes differ at offset {offset} (sizes {len(left)}, {len(right)})"


def _xlsx_difference(left: Path, right: Path) -> str | None:
    with ZipFile(left) as a, ZipFile(right) as b:
        names = a.namelist()
        if not names or not b.namelist():
            raise ValueError("empty XLSX package")
        if len(names) != len(set(names)) or len(b.namelist()) != len(set(b.namelist())):
            raise ValueError("duplicate XLSX member")
        if names != b.namelist():
            return "XLSX member names/order differ"
        for name in names:
            x, y = a.read(name), b.read(name)  # Reading verifies each stored CRC too.
            if name == "docProps/core.xml":
                x, y = _core_without_times(x), _core_without_times(y)
                crc_equal = zlib.crc32(x) == zlib.crc32(y)
            else:
                crc_equal = a.getinfo(name).CRC == b.getinfo(name).CRC
            difference = _bytes_difference(x, y)
            if not crc_equal or difference:
                return f"XLSX member {name}: {difference or 'CRC differs'}"
    return None


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _ordered_table_query(table: str, columns: list[str]) -> str:
    """Compose fixed SQL tokens with catalog identifiers quoted as indivisible names."""
    if not columns:
        raise ValueError("table has no ordering columns")
    return " ".join(("SELECT * FROM", _identifier(table), "ORDER BY",
                     ", ".join(_identifier(column) for column in columns)))


def _table_difference(a, b, name):
    columns = a.execute("SELECT * FROM pragma_table_info(?)", (name,)).fetchall()
    keys = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
    query = _ordered_table_query(name, keys or [row[1] for row in columns])
    missing = object()
    for index, (x, y) in enumerate(zip_longest(a.execute(query), b.execute(query), fillvalue=missing)):
        if x != y or (x is not missing and y is not missing
                      and tuple(map(type, x)) != tuple(map(type, y))):
            return f"SQLite table {name}: row {index} differs"
    return None


def _sqlite_family_state(path):
    state = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        member = path.with_name(path.name + suffix)
        if member.exists():
            info = member.stat()
            state[member] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return state


@contextmanager
def _sqlite_read_copy(path):
    # Even mode=ro can create or update WAL sidecars. SQLite must see only disposable copies.
    path = path.resolve()
    with TemporaryDirectory(prefix="compare-export-sqlite-") as directory:
        family = _sqlite_family_state(path)
        for member in family:
            shutil.copyfile(member, Path(directory) / member.name)
        if _sqlite_family_state(path) != family:
            raise ValueError("SQLite input family changed during copy")
        copy = Path(directory) / path.name
        with closing(sqlite3.connect(f"file:{quote(str(copy))}?mode=ro", uri=True)) as connection:
            yield connection


def _sqlite_difference(left: Path, right: Path) -> str | None:
    with _sqlite_read_copy(left) as a, _sqlite_read_copy(right) as b:
        a.execute("BEGIN")
        b.execute("BEGIN")
        catalog = ("SELECT type, name, tbl_name, sql FROM sqlite_master "
                   "WHERE type IN ('table', 'index', 'view', 'trigger') ORDER BY type, name")
        schema = a.execute(catalog).fetchall()
        for index, (x, y) in enumerate(zip_longest(schema, b.execute(catalog).fetchall())):
            if x != y:
                return f"SQLite schema object {index} differs: {x[:3] if x else None}, {y[:3] if y else None}"
        for kind, name, _table, _sql in schema:
            difference = _table_difference(a, b, name) if kind == "table" else None
            if difference:
                return difference
    return None


def _generation_directory(root):
    candidates = [path for base in GENERATION_ASSET_BASES for path in root.rglob(base + ".generation-*")
                  if path.is_dir() or path.is_symlink()]
    if not candidates:
        return None
    if len(candidates) != 1 or candidates[0].is_symlink() or not candidates[0].is_dir():
        raise ValueError("missing or ambiguous dashboard generation directory")
    if not GENERATION_NAME.fullmatch(candidates[0].name):
        raise ValueError("invalid dashboard generation directory name")
    return candidates[0]


def _generation_pair(left, right):
    a, b = _generation_directory(left), _generation_directory(right)
    if (a is None) != (b is None):
        raise ValueError("dashboard generation directory missing on one side")
    if a is not None and a.relative_to(left).parent != b.relative_to(right).parent:
        raise ValueError("dashboard generation directory location differs")
    if a is not None and a.name.rsplit(".generation-", 1)[0] != b.name.rsplit(".generation-", 1)[0]:
        raise ValueError("dashboard generation asset base name differs")
    return (a, b) if a is not None else None


def _asset_entries(directory):
    entries = {}
    for path in directory.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("unsupported dashboard asset entry")
        entries[path.relative_to(directory)] = "directory" if path.is_dir() else "file"
    if "file" not in entries.values():
        raise ValueError("dashboard generation has no assets")
    return entries


def _asset_difference(pair):
    if pair is None:
        return None
    a, b = pair
    entries = _asset_entries(a)
    if entries != _asset_entries(b):
        return "dashboard relative asset names/types differ"
    for name in sorted(entries):
        if entries[name] == "file":
            difference = _bytes_difference((a / name).read_bytes(), (b / name).read_bytes())
            if difference:
                return f"dashboard asset {name}: {difference}"
    return None


class _DashboardReferences(HTMLParser):
    """Patch only literal asset-reference attributes, preserving all other HTML bytes."""

    def __init__(self, text, document, generation):
        super().__init__(convert_charrefs=False)
        self.text, self.document, self.generation = text, document, generation
        self.offsets = [0]
        for line in text.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.edits = []

    def _reference(self, value):
        decoded = html.unescape(value)
        if not any(base + ".generation-" in decoded for base in GENERATION_ASSET_BASES):
            return value
        generation = self.generation
        if generation is None or generation.name not in decoded.split("/"):
            raise ValueError("HTML references an unpaired dashboard generation")
        target = (self.document.parent / decoded).resolve()
        if not target.is_relative_to(generation.resolve()) or not target.is_file():
            raise ValueError("HTML dashboard asset reference is missing or escapes its generation")
        # Replace the exact directory token once. A UUID in a filename or any other location stays literal.
        return value.replace(generation.name + "/", generation.name[:-32] + "PAIRED/", 1)

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()

        def replace(match):
            if (tag, match[1].lower()) not in {("script", "src"), ("img", "src"), ("button", "data-image-src")}:
                return match[0]
            value = self._reference(match[3])
            start = match.start(3) - match.start()
            return match[0][:start] + value + match[0][start + len(match[3]):]

        changed = HTML_ATTRIBUTE.sub(replace, raw)
        if changed != raw:
            line, column = self.getpos()
            self.edits.append((self.offsets[line - 1] + column, len(raw), changed))

    handle_startendtag = handle_starttag

    def normalized(self):
        self.feed(self.text)
        self.close()
        text = self.text
        for offset, length, changed in reversed(self.edits):
            text = text[:offset] + changed + text[offset + length:]
        return text.encode("utf-8")


def _html_difference(left, right, pair):
    generations = pair or (None, None)
    values = [_DashboardReferences(path.read_bytes().decode("utf-8"), path, generation).normalized()
              for path, generation in zip((left, right), generations)]
    return _bytes_difference(*(_html_without_times(value) for value in values))


def _directory_difference(left, right, *, sqlite):
    pair = _generation_pair(left, right)
    difference = _asset_difference(pair)
    if difference:
        return difference
    a, b = [_ordinary_files(root, generation) for root, generation in
            zip((left, right), pair or (None, None))]
    if a != b:
        return "output file names differ"
    if not a:
        raise ValueError("no outputs to compare")
    for name in a:
        difference = _file_difference(left / name, right / name, sqlite=sqlite, pair=pair)
        if difference:
            return f"{name}: {difference}"
    return None


def _ordinary_files(root, generation):
    return sorted(path.relative_to(root) for path in root.rglob("*")
                  if path.is_file() and (generation is None or not path.is_relative_to(generation)))


def compare_outputs(left: Path, right: Path, *, sqlite: bool = False) -> str | None:
    """Return the first difference; errors propagate to the fail-closed CLI."""
    if not left.exists() or not right.exists():
        raise FileNotFoundError("both comparison inputs must exist")
    if left.is_dir() != right.is_dir():
        return "input types differ"
    if left.is_dir():
        return _directory_difference(left, right, sqlite=sqlite)
    pair = _generation_pair(left.parent, right.parent) if left.suffix.lower() in {".html", ".htm"} else None
    difference = _asset_difference(pair)
    return difference or _file_difference(left, right, sqlite=sqlite, pair=pair)


def _file_difference(left, right, *, sqlite, pair):
    if left.suffix.lower() != right.suffix.lower():
        return "output formats differ"
    suffix = left.suffix.lower()
    if suffix == ".xlsx":
        return _xlsx_difference(left, right)
    if sqlite and suffix in {".sqlite", ".sqlite3", ".db"}:
        return _sqlite_difference(left, right)
    if suffix in {".html", ".htm"}:
        return _html_difference(left, right, pair)
    return _bytes_difference(left.read_bytes(), right.read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--sqlite", action="store_true",
                        help="compare SQLite schema objects and table rows in primary-key order")
    parser.add_argument("--baseline-control", action="store_true",
                        help="label only: independently generated baseline pair; source identity is caller-owned")
    args = parser.parse_args(argv)
    try:
        difference = compare_outputs(args.left, args.right, sqlite=args.sqlite)
    except Exception as error:  # noqa: BLE001 - comparison errors are failures, never equality
        print(f"comparison failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(("baseline control: " if args.baseline_control else "") + (difference or "outputs equal"))
    return 1 if difference else 0


if __name__ == "__main__":
    raise SystemExit(main())
