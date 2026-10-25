"""Compare exports with documented timestamps/generations and opt-in scoped CSV diagnostics."""

from __future__ import annotations

import argparse
import ast
from contextlib import closing, contextmanager
from datetime import datetime
import hashlib
import json
import html
from html.parser import HTMLParser
from itertools import zip_longest
from pathlib import Path, PurePosixPath, PureWindowsPath
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
SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CSV_SUMMARY_CODE = "tabular_sqlite_store_created"
# C01: the report-import v1 table declarations, including PK/FK/type/NOT NULL/CHECK
# constraints, as stored by SQLite. Serialize ordered (name, sql) pairs as compact
# ASCII JSON before hashing. This is a frozen contract, not a live product import;
# a new report schema requires a separately admitted comparator contract.
IMPORT_SCHEMA_TABLES = frozenset({
    "parsed_reports", "report_metadata", "report_measurements", "report_metadata_candidates",
    "report_metadata_warnings", "report_parse_state", "source_file_locations", "source_files",
})
IMPORT_SCHEMA_SHA256 = "b9026389095aa17b27269c3d51c34356bc49e729303b5b993791ee09bf441ce0"
IMPORT_RUNTIME_TIMESTAMPS = {
    "parsed_reports": frozenset({"created_at", "updated_at"}),
    "report_metadata_candidates": frozenset({"created_at"}),
    "report_metadata_warnings": frozenset({"created_at"}),
    "report_parse_state": frozenset({"updated_at"}),
    "source_file_locations": frozenset({"discovered_at"}),
    "source_files": frozenset({"discovered_at"}),
}
IMPORT_UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
# report_schema.upsert_report_parse_state uses SQLite CURRENT_TIMESTAMP (UTC),
# whereas the other six locations use report_repository.utc_timestamp().
IMPORT_SQLITE_UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\Z")


def _plain_shared_text(strings, index):
    node = strings[index]
    if (node.tag != SHEET_NS + "si" or len(node) != 1 or node[0].tag != SHEET_NS + "t"
            or len(node[0]) or node[0].text is None):
        raise ValueError("unsupported diagnostic shared string")
    return node[0].text


def _diagnostics_part(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    if workbook.tag != SHEET_NS + "workbook" or len(workbook.findall(SHEET_NS + "sheets")) != 1:
        raise ValueError("unsupported workbook sheets")
    sheets = workbook.findall(SHEET_NS + "sheets/" + SHEET_NS + "sheet")
    matches = [sheet for sheet in sheets if sheet.get("name") == "Diagnostics"]
    sheet_ids = [sheet.get("{" + OFFICE_REL[:-1] + "}id") for sheet in sheets]
    if (len(matches) != 1 or len({sheet.get("name") for sheet in sheets}) != len(sheets)
            or len(sheet_ids) != len(set(sheet_ids))):
        raise ValueError("ambiguous Diagnostics worksheet")
    relationship_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    if relationship_root.tag != REL_NS + "Relationships":
        raise ValueError("unsupported workbook relationships")
    relationships = list(relationship_root)
    ids = [item.get("Id") for item in relationships]
    targets = [item.get("Target") for item in relationships if item.get("Type") == OFFICE_REL + "worksheet"]
    if any(not re.fullmatch(r"worksheets/[A-Za-z0-9_.-]+\.xml", target or "") for target in targets):
        raise ValueError("unsupported worksheet relationship target")
    if None in ids or len(ids) != len(set(ids)) or len(targets) != len(set(targets)):
        raise ValueError("ambiguous workbook relationship")
    rid = matches[0].get("{" + OFFICE_REL[:-1] + "}id")
    links = [item for item in relationships if item.tag == REL_NS + "Relationship" and item.get("Id") == rid]
    if (len(links) != 1 or links[0].get("Type") != OFFICE_REL + "worksheet"
            or links[0].get("TargetMode") is not None
            or not re.fullmatch(r"worksheets/[A-Za-z0-9_.-]+\.xml", links[0].get("Target") or "")):
        raise ValueError("unsupported Diagnostics relationship")
    return "xl/" + links[0].get("Target")


def _diagnostic_cell(archive, part, strings):
    rows, addresses = [], set()
    sheet = ET.fromstring(archive.read(part))
    if sheet.tag != SHEET_NS + "worksheet" or len(sheet.findall(SHEET_NS + "sheetData")) != 1:
        raise ValueError("unsupported Diagnostics sheet data")
    for row in sheet.findall(SHEET_NS + "sheetData/" + SHEET_NS + "row"):
        cells = {}
        for cell in row.findall(SHEET_NS + "c"):
            address = cell.get("r") or ""
            match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", address)
            if (match is None or address in addresses or match[2] != row.get("r")
                    or cell.get("t") != "s" or len(cell) != 1 or cell[0].tag != SHEET_NS + "v"):
                raise ValueError("unsupported diagnostic cell")
            addresses.add(address)
            index = int(cell[0].text)
            if index < 0:
                raise ValueError("invalid shared string index")
            cells[match[1]] = (index, _plain_shared_text(strings, index), address)
        rows.append(cells)
    headers = [row for row in rows if any(value[1] in {"code", "context"} for value in row.values())]
    if len(headers) != 1:
        raise ValueError("ambiguous diagnostic headers")
    columns = [[key for key, value in headers[0].items() if value[1] == name] for name in ("code", "context")]
    if any(len(values) != 1 for values in columns):
        raise ValueError("ambiguous diagnostic columns")
    matches = [row for row in rows if row.get(columns[0][0], (None, None))[1] == CSV_SUMMARY_CODE]
    if len(matches) != 1:
        raise ValueError("ambiguous diagnostic code")
    return matches[0][columns[1][0]]


def _sole_shared_reference(archive, index, expected):
    count, location = 0, None
    for name in archive.namelist():
        if not (name.startswith("xl/worksheets/") and name.endswith(".xml")):
            continue
        with archive.open(name) as stream:
            stack = []
            for event, node in ET.iterparse(stream, events=("start", "end")):
                if event == "start":
                    if not stack and node.tag != SHEET_NS + "worksheet":
                        raise ValueError("unsupported worksheet root")
                    stack.append(node)
                    continue
                if node.tag == SHEET_NS + "c" and node.get("t") == "s":
                    values = node.findall(SHEET_NS + "v")
                    if len(values) != 1:
                        raise ValueError("ambiguous shared string reference")
                    if int(values[0].text) == index:
                        count, location = count + 1, (name, node.get("r"))
                if node.tag == SHEET_NS + "row":
                    stack[-2].remove(node)
                    node.clear()
                stack.pop()
    return count == 1 and location == expected


def _recorded_temp_prefix(temp_root):
    root = str(temp_root)
    if PurePosixPath(root).is_absolute():
        separator = "/"
    elif PureWindowsPath(root).is_absolute() and not ("/" in root and "\\" in root):
        separator = "\\" if "\\" in root else "/"
    else:
        raise ValueError("recorded temporary root must be unambiguous and absolute")
    return root if root.endswith(separator) else root + separator


def _csv_summary_token(archive, data, temp_root):
    """Prove one plain diagnostic SST entry; keep its original raw byte offset."""
    strings = ET.fromstring(data)
    if strings.tag != SHEET_NS + "sst":
        raise ValueError("unsupported shared string table")
    part = _diagnostics_part(archive)
    index, text, address = _diagnostic_cell(archive, part, strings)
    literal = ast.parse(text, mode="eval").body
    fields = ("row_count", "source_file_count", "sqlite_path")
    if (not isinstance(literal, ast.Dict) or len(literal.keys) != 3
            or any(not isinstance(key, ast.Constant) or type(key.value) is not str for key in literal.keys)
            or {key.value for key in literal.keys} != set(fields)):
        raise ValueError("unsupported diagnostic context fields")
    context = ast.literal_eval(literal)
    if (type(context["row_count"]) is not int or type(context["source_file_count"]) is not int
            or type(context["sqlite_path"]) is not str):
        raise ValueError("unsupported diagnostic context types/root")
    match = re.fullmatch(re.escape(_recorded_temp_prefix(temp_root)) + r"(metroliza_csv_summary_[a-z0-9_]{8}\.sqlite)", context["sqlite_path"])
    if match is None or not _sole_shared_reference(archive, index, (part, address)):
        raise ValueError("diagnostic path/root/reference outside named scope")
    token = match[1].encode("ascii")
    entries = list(re.finditer(rb"<si(?:\s[^>]*)?>.*?</si>", data, re.DOTALL))
    if len(entries) != len(strings):
        raise ValueError("unsupported shared string serialization")
    entry = entries[index]
    if (entry[0] != b"<si><t>" + html.escape(text, quote=False).encode() + b"</t></si>"
            or entry[0].count(token) != 1):
        raise ValueError("unsupported plain context serialization")
    return token, (part, index, address), entry.start() + entry[0].index(token)


def _csv_summary_shared_pair(a, b, x, y, temp_root):
    try:
        left, scope_a, _offset = _csv_summary_token(a, x, temp_root)
        right, scope_b, offset = _csv_summary_token(b, y, temp_root)
    except (ValueError, TypeError, KeyError, IndexError, SyntaxError, ET.ParseError, RecursionError):
        return x, y  # Unsupported scope keeps the original literal comparison.
    normalized = y[:offset] + left + y[offset + len(right):]
    if (scope_a == scope_b and normalized == x and len(normalized) == len(x)
            and zlib.crc32(normalized) == a.getinfo("xl/sharedStrings.xml").CRC):
        return x, normalized
    return x, y


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


def _xlsx_difference(left: Path, right: Path, *, csv_summary_temp_root=None) -> str | None:
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
            if name == "xl/sharedStrings.xml" and x != y and csv_summary_temp_root is not None:
                x, y = _csv_summary_shared_pair(a, b, x, y, csv_summary_temp_root)
            if name == "docProps/core.xml":
                x, y = _core_without_times(x), _core_without_times(y)
                crc_equal = zlib.crc32(x) == zlib.crc32(y)
            else:
                crc_equal = (zlib.crc32(x) == zlib.crc32(y) if name == "xl/sharedStrings.xml"
                             and csv_summary_temp_root is not None else a.getinfo(name).CRC == b.getinfo(name).CRC)
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


def _import_schema_scope(schema):
    tables = sorted((name, sql) for kind, name, _table, sql in schema
                    if kind == "table" and name in IMPORT_SCHEMA_TABLES)
    encoded = json.dumps(tables, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if hashlib.sha256(encoded).hexdigest() != IMPORT_SCHEMA_SHA256:
        raise ValueError("import runtime timestamps require the canonical report-import v1 schema")


def _import_row_values(row, timestamp_columns):
    for index, name in timestamp_columns.items():
        value = row[index]
        pattern = (IMPORT_SQLITE_UTC_TIMESTAMP if name == "report_parse_state.updated_at"
                   else IMPORT_UTC_TIMESTAMP)
        if type(value) is not str or not pattern.fullmatch(value):
            raise ValueError(f"invalid import runtime timestamp at {name}: unexpected UTC text format")
        # Regex enforces each writer's exact format; datetime rejects impossible dates/times.
        datetime.fromisoformat(value.removesuffix("Z"))
    return tuple(value for index, value in enumerate(row) if index not in timestamp_columns)


def _table_difference(a, b, name, *, import_runtime_timestamps=False):
    columns = a.execute("SELECT * FROM pragma_table_info(?)", (name,)).fetchall()
    keys = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
    query = _ordered_table_query(name, keys or [row[1] for row in columns])
    allowed = IMPORT_RUNTIME_TIMESTAMPS.get(name, ()) if import_runtime_timestamps else ()
    timestamp_columns = {row[0]: f"{name}.{row[1]}" for row in columns if row[1] in allowed}
    missing = object()
    for index, (x, y) in enumerate(zip_longest(a.execute(query), b.execute(query), fillvalue=missing)):
        if x is missing or y is missing:
            return f"SQLite table {name}: row {index} differs"
        if timestamp_columns:
            x, y = (_import_row_values(row, timestamp_columns) for row in (x, y))
        if x != y or tuple(map(type, x)) != tuple(map(type, y)):
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


def _sqlite_difference(left: Path, right: Path, *, import_runtime_timestamps=False) -> str | None:
    with _sqlite_read_copy(left) as a, _sqlite_read_copy(right) as b:
        a.execute("BEGIN")
        b.execute("BEGIN")
        catalog = ("SELECT type, name, tbl_name, sql FROM sqlite_master "
                   "WHERE type IN ('table', 'index', 'view', 'trigger') ORDER BY type, name")
        schema = a.execute(catalog).fetchall()
        for index, (x, y) in enumerate(zip_longest(schema, b.execute(catalog).fetchall())):
            if x != y:
                return f"SQLite schema object {index} differs: {x[:3] if x else None}, {y[:3] if y else None}"
        if import_runtime_timestamps:
            _import_schema_scope(schema)
        for kind, name, _table, _sql in schema:
            difference = _table_difference(a, b, name,
                import_runtime_timestamps=import_runtime_timestamps) if kind == "table" else None
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


def _directory_difference(left, right, *, sqlite, csv_summary_temp_root=None,
                          import_runtime_timestamps=False):
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
        difference = _file_difference(left / name, right / name, sqlite=sqlite, pair=pair,
                                      csv_summary_temp_root=csv_summary_temp_root,
                                      import_runtime_timestamps=import_runtime_timestamps and name == Path("import.sqlite"))
        if difference:
            return f"{name}: {difference}"
    return None


def _ordinary_files(root, generation):
    return sorted(path.relative_to(root) for path in root.rglob("*")
                  if path.is_file() and (generation is None or not path.is_relative_to(generation)))


def compare_outputs(left: Path, right: Path, *, sqlite: bool = False,
                    csv_summary_temp_root: str | Path | None = None,
                    import_runtime_timestamps: bool = False) -> str | None:
    """Return the first difference; errors propagate to the fail-closed CLI."""
    if import_runtime_timestamps:
        if not sqlite:
            raise ValueError("import runtime timestamps require SQLite comparison")
        imports = [path / "import.sqlite" if path.is_dir() else path for path in (left, right)]
        if any(path.name != "import.sqlite" or not path.is_file() for path in imports):
            raise ValueError("import runtime timestamps require paired import.sqlite files at the comparison root")
    if not left.exists() or not right.exists():
        raise FileNotFoundError("both comparison inputs must exist")
    if left.is_dir() != right.is_dir():
        return "input types differ"
    if left.is_dir():
        return _directory_difference(left, right, sqlite=sqlite, csv_summary_temp_root=csv_summary_temp_root,
                                     import_runtime_timestamps=import_runtime_timestamps)
    pair = _generation_pair(left.parent, right.parent) if left.suffix.lower() in {".html", ".htm"} else None
    difference = _asset_difference(pair)
    return difference or _file_difference(left, right, sqlite=sqlite, pair=pair,
                                          csv_summary_temp_root=csv_summary_temp_root,
                                          import_runtime_timestamps=import_runtime_timestamps)


def _file_difference(left, right, *, sqlite, pair, csv_summary_temp_root=None,
                     import_runtime_timestamps=False):
    if left.suffix.lower() != right.suffix.lower():
        return "output formats differ"
    suffix = left.suffix.lower()
    if suffix == ".xlsx":
        return _xlsx_difference(left, right, csv_summary_temp_root=csv_summary_temp_root)
    if sqlite and suffix in {".sqlite", ".sqlite3", ".db"}:
        return _sqlite_difference(left, right, import_runtime_timestamps=import_runtime_timestamps)
    if suffix in {".html", ".htm"}:
        return _html_difference(left, right, pair)
    return _bytes_difference(left.read_bytes(), right.read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--sqlite", action="store_true",
                        help="compare SQLite schema objects and table rows in primary-key order")
    parser.add_argument("--import-runtime-timestamps", action="store_true",
                        help="C01 opt-in: validate and ignore only seven import runtime UTC fields in "
                             "paired import.sqlite files with canonical report-import v1 tables; requires --sqlite")
    parser.add_argument("--csv-summary-temp-root",
                        help="recorded common temp root for the single CSV Summary Diagnostics context basename")
    parser.add_argument("--baseline-control", action="store_true",
                        help="label only: independently generated baseline pair; source identity is caller-owned")
    args = parser.parse_args(argv)
    try:
        difference = compare_outputs(args.left, args.right, sqlite=args.sqlite,
                                     csv_summary_temp_root=args.csv_summary_temp_root,
                                     import_runtime_timestamps=args.import_runtime_timestamps)
    except Exception as error:  # noqa: BLE001 - comparison errors are failures, never equality
        print(f"comparison failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(("baseline control: " if args.baseline_control else "") + (difference or "outputs equal"))
    return 1 if difference else 0


if __name__ == "__main__":
    raise SystemExit(main())
