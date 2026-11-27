"""Versioned predicates and bounded previews for report-grain grouping."""

from contextlib import closing
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from time import monotonic
from unicodedata import normalize

from metroliza.analytics.grouping_labels import DEFAULT_GROUP_LABEL
from metroliza.reports.db import sqlite_readonly_connection_scope
from metroliza.reports.report_query_service import build_grouping_query, build_measurement_export_query
from metroliza.reports.report_typed_filter import (
    ReportTypedViewError, _database_stamp, require_report_typed_view,
)
from metroliza.shared.datetime_parsing import parse_datetime_literal
from metroliza.shared.grouping_filter_core import DataFrameFilterSpec
from metroliza.shared.typed_filter import (
    PandasFilterAdapter, dump_typed_filter, load_typed_filter, parse_typed_filter, FilterField,
)
from metroliza.tabular.contracts import GroupingAssignment, GroupingAssignments


PRESET_VERSION = 1
MAX_PRESET_BYTES = 64 * 1024
MAX_GROUPS = 12
MAX_REPORTS = 2_000
MAX_EXPRESSION_CHARS = 240
MAX_LABEL_CHARS = 80
MAX_FIELD_CHARS = 512
PREVIEW_SAMPLE_ROWS = 8
PREVIEW_SECONDS = 1.0
RULE_FIELDS = (
    FilterField("reference", "text", "Reference", "Reports grouping"),
    FilterField("part_name", "text", "Part", "Reports grouping"),
    FilterField("revision", "text", "Revision", "Reports grouping"),
    FilterField("template_variant", "text", "Template", "Reports grouping"),
    FilterField("sample_number", "text", "Sample", "Reports grouping"),
    FilterField("report_date", "date", "Date", "Reports grouping"),
)
_SCOPE_COLUMNS = ("REPORT_ID", "REFERENCE", "PART_NAME", "REVISION", "TEMPLATE_VARIANT", "SAMPLE_NUMBER", "DATE")
_PREVIEW_COLUMNS = ("report_id", *(rule_field.field_id for rule_field in RULE_FIELDS))
_REDRAFT = "The report database or export filter changed. Preview grouping rules again."
_PREVIEW_LIMIT = "The grouping preview took too long. Narrow the export filters or simplify the rules."


class ReportGroupingSourceChanged(ValueError):
    def __init__(self):
        super().__init__(_REDRAFT)


def _require_text(value, description, limit):
    if (type(value) is not str or not value or value != value.strip() or len(value) > limit
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)):
        raise ValueError(f"{description} must be 1–{limit} characters on one line.")
    value.encode("utf-8")
    return value


@dataclass(frozen=True)
class ReportGroupRule:
    group_id: str
    label: str
    color: str
    expression: str
    predicate: DataFrameFilterSpec = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self.group_id) is not str or not re.fullmatch(r"[a-f0-9]{32}", self.group_id):
            raise ValueError("A group has an invalid identifier.")
        _require_text(self.label, "Group name", MAX_LABEL_CHARS)
        if type(self.color) is not str or not re.fullmatch(r"#[a-fA-F0-9]{6}", self.color):
            raise ValueError(f"{self.label!r} needs a hexadecimal color such as #DAE9F6.")
        _require_text(self.expression, f"Rule for {self.label!r}", MAX_EXPRESSION_CHARS)
        try:
            predicate = parse_typed_filter(self.expression, RULE_FIELDS)
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"Rule for {self.label!r} is invalid. {exc}") from exc
        if predicate is None:
            raise ValueError(f"Enter a condition for {self.label!r}.")
        object.__setattr__(self, "predicate", predicate)


@dataclass(frozen=True)
class ReportGroupingPreset:
    name: str
    rules: tuple[ReportGroupRule, ...]

    def __post_init__(self):
        _require_text(self.name, "Preset name", MAX_LABEL_CHARS)
        if type(self.rules) is not tuple or not 1 <= len(self.rules) <= MAX_GROUPS:
            raise ValueError(f"A preset must contain 1–{MAX_GROUPS} groups.")
        ids = set()
        names = {DEFAULT_GROUP_LABEL.casefold(), "population points", "ungrouped"}
        for rule in self.rules:
            label = normalize("NFKC", rule.label).casefold()
            if rule.group_id in ids:
                raise ValueError("The preset contains duplicate group IDs.")
            if label in names:
                raise ValueError(f"Group name {rule.label!r} is duplicated or reserved.")
            ids.add(rule.group_id)
            names.add(label)


def dump_grouping_preset(preset: ReportGroupingPreset) -> bytes:
    document = {
        "version": PRESET_VERSION,
        "name": preset.name,
        "groups": [{
            "id": rule.group_id,
            "label": rule.label,
            "color": rule.color,
            "expression": rule.expression,
            "filter": dump_typed_filter(rule.predicate),
        } for rule in preset.rules],
    }
    raw = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) > MAX_PRESET_BYTES:
        raise ValueError("This grouping preset is too large to save.")
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("The grouping preset contains a duplicate key.")
        result[key] = value
    return result


def _decode_rule(raw):
    if type(raw) is not dict or set(raw) != {"id", "label", "color", "expression", "filter"}:
        raise ValueError("A group has unsupported preset fields.")
    rule = ReportGroupRule(raw["id"], raw["label"], raw["color"], raw["expression"])
    try:
        saved = load_typed_filter(raw["filter"], RULE_FIELDS)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Saved rule for {rule.label!r} is incompatible. {exc}") from exc
    if dump_typed_filter(saved) != dump_typed_filter(rule.predicate):
        raise ValueError(f"The expression and typed rule for {rule.label!r} differ. Restore the original preset.")
    return rule


def load_grouping_preset(raw: bytes) -> ReportGroupingPreset:
    if len(raw) > MAX_PRESET_BYTES:
        raise ValueError("The grouping preset exceeds the 64 KiB limit.")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Open a valid UTF-8 grouping preset JSON file.") from exc
    if type(document) is not dict or set(document) != {"version", "name", "groups"}:
        raise ValueError("This file is not a supported grouping preset.")
    if type(document["version"]) is not int or document["version"] != PRESET_VERSION:
        raise ValueError("This grouping preset version is unsupported.")
    if type(document["groups"]) is not list or not 1 <= len(document["groups"]) <= MAX_GROUPS:
        raise ValueError(f"A preset must contain 1–{MAX_GROUPS} groups.")
    return ReportGroupingPreset(document["name"], tuple(_decode_rule(raw) for raw in document["groups"]))


def _report_stamp(database):
    try:
        return _database_stamp(database)
    except ValueError as exc:
        raise ReportGroupingSourceChanged() from exc


@dataclass(frozen=True)
class ReportGroupingSource:
    database: Path = field(repr=False)
    filter_query: str | None = field(repr=False)
    stamp: tuple = field(repr=False)
    projection_digest: bytes | None = field(default=None, repr=False)
    report_ids: tuple[int, ...] = field(default=(), repr=False)

    @classmethod
    def capture(cls, database, filter_query):
        path = Path(database).resolve()
        return cls(path, filter_query, _report_stamp(path))

    def require_current(self, database, filter_query, *, exact_stamp=False):
        if Path(database).resolve() != self.database or filter_query != self.filter_query:
            raise ReportGroupingSourceChanged()
        stamp = _report_stamp(self.database)
        # Reopening the manual grouping view can update the file without changing report data.
        # For export, require_snapshot independently verifies the exact frozen report projection.
        if stamp[0][:2] != self.stamp[0][:2] or (exact_stamp and stamp != self.stamp):
            raise ReportGroupingSourceChanged()

    def begin_snapshot(self, connection, database, filter_query):
        """Bind the standard view and the export selection to the same read transaction."""
        self.require_current(database, filter_query)
        if not connection.in_transaction:
            connection.execute("BEGIN")
        try:
            require_report_typed_view(connection)
        except ReportTypedViewError as exc:
            raise ReportGroupingSourceChanged() from exc

    def require_snapshot(self, connection, snapshot_query):
        """Check the preview's report metadata against the frozen export selection."""
        try:
            with closing(connection.execute(build_grouping_query(snapshot_query))) as cursor:
                digest = _projection_digest(_project_reports(cursor))
        except (sqlite3.Error, ValueError) as exc:
            raise ReportGroupingSourceChanged() from exc
        if digest != self.projection_digest:
            raise ReportGroupingSourceChanged()

    def read_rows(self, *, deadline=None):
        selection = self.filter_query or build_measurement_export_query()
        if deadline is None:
            deadline = monotonic() + PREVIEW_SECONDS
        try:
            with sqlite_readonly_connection_scope(str(self.database), timeout_s=0.10) as connection:
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 128 * 1024)
                connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
                connection.execute("BEGIN")
                require_report_typed_view(connection)
                with closing(connection.execute(build_grouping_query(selection))) as cursor:
                    rows = _project_reports(cursor)
        except ReportTypedViewError as exc:
            raise ValueError("Grouping rules require the standard Reports measurement view.") from exc
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
                raise ValueError(_PREVIEW_LIMIT) from exc
            raise ValueError("Could not preview this report scope. Narrow the export filters and try again.") from exc
        self.require_current(self.database, self.filter_query, exact_stamp=True)
        return rows


def _project_reports(cursor):
    columns = [entry[0] for entry in cursor.description]
    if any(columns.count(name) != 1 for name in _SCOPE_COLUMNS):
        raise ValueError("Grouping requires the standard report fields. Check the selected Reports database.")
    positions = [columns.index(name) for name in _SCOPE_COLUMNS]
    seen = set()
    rows = []
    for raw_row in cursor:
        if len(rows) == MAX_REPORTS:
            raise ValueError(f"Grouping rules support up to {MAX_REPORTS:,} reports. Narrow the export filters.")
        report_id, *values = (raw_row[position] for position in positions)
        if type(report_id) is not int or report_id <= 0 or report_id in seen:
            raise ValueError("Grouping requires one row for each valid REPORT_ID. Check the Reports database.")
        seen.add(report_id)
        if any(value is not None and (type(value) is not str or len(value) > MAX_FIELD_CHARS) for value in values):
            raise ValueError("A report field has an unsupported type or length. Narrow the export filters.")
        rows.append((report_id, *values))
    return rows


def _projection_digest(rows):
    digest = sha256()
    for row in sorted(rows):
        digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    return digest.digest()


def _require_preview_time(deadline):
    if monotonic() >= deadline:
        raise ValueError(_PREVIEW_LIMIT)


def _normalized_date_rows(rows, deadline):
    dates = {}
    for *values, raw_date in rows:
        if raw_date not in dates:
            _require_preview_time(deadline)
            parsed = parse_datetime_literal(raw_date)
            dates[raw_date] = parsed.date() if parsed is not None else None
        yield (*values, dates[raw_date])


@dataclass(frozen=True)
class ReportGroupingPreview:
    source: ReportGroupingSource
    counts: tuple[tuple[str, int], ...]
    overlap_count: int
    unassigned_count: int
    overlap_sample: tuple[int, ...]
    unassigned_sample: tuple[int, ...]
    assignments: GroupingAssignments = field(repr=False)


def preview_grouping_preset(preset: ReportGroupingPreset, source: ReportGroupingSource) -> ReportGroupingPreview:
    from pandas import DataFrame

    deadline = monotonic() + PREVIEW_SECONDS
    rows = source.read_rows(deadline=deadline)
    if not rows:
        raise ValueError("The current export filters select no reports.")
    frame = DataFrame.from_records(_normalized_date_rows(rows, deadline), columns=_PREVIEW_COLUMNS)
    adapter = PandasFilterAdapter(frame, "report_id")
    matches = {report_id: [] for report_id, *_ in sorted(rows)}
    counts = []
    for rule in preset.rules:
        ids = tuple(adapter.prepare(rule.predicate).iter_row_ids())
        counts.append((rule.label, len(ids)))
        for report_id in ids:
            matches[report_id].append(rule)
        _require_preview_time(deadline)
    overlaps = tuple(report_id for report_id, rules in matches.items() if len(rules) > 1)
    unassigned = tuple(report_id for report_id, rules in matches.items() if not rules)
    assignments = tuple(
        GroupingAssignment(report_id=report_id, group=rules[0].label, group_color=rules[0].color)
        if rules else GroupingAssignment(report_id=report_id, group=DEFAULT_GROUP_LABEL)
        for report_id, rules in matches.items()
    ) if not overlaps else ()
    verified_source = replace(source, projection_digest=_projection_digest(rows), report_ids=tuple(matches))
    return ReportGroupingPreview(
        verified_source, tuple(counts), len(overlaps), len(unassigned),
        overlaps[:PREVIEW_SAMPLE_ROWS], unassigned[:PREVIEW_SAMPLE_ROWS], assignments,
    )
