"""Qt-free presentation rules for the metadata cells of the report planner (#1100).

The planner shows the metadata of every reviewed report inline.  This module
turns a ``ReviewRow`` into display text, tooltips, accessible text, a semantic
cell style and the "needs attention" reasons.  Every rule about values (what is
missing, low confidence, manual or an OCR conflict) stays in
``metroliza.reports.report_metadata_review``; colours are mapped from the
semantic ``kind`` by the Qt model through the shared theme tokens.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from metroliza.reports.report_metadata_review import (
    FIELD_LABELS,
    ORIGIN_OCR,
    ORIGIN_USER,
    REVIEW_FIELDS,
    ROW_CHANGED,
    ROW_FAILED,
    ROW_PENDING,
    ROW_UNSUPPORTED,
    ReviewRow,
)

KIND_NORMAL = "normal"
KIND_PENDING = "pending"
KIND_READONLY = "readonly"
KIND_MISSING = "missing"
KIND_LOW_CONFIDENCE = "low_confidence"
KIND_CONFLICT = "conflict"
KIND_MANUAL = "manual"
KIND_OCR = "ocr"

PENDING_TEXT = "…"
MISSING_TEXT = "missing"
READONLY_TEXT = "n/a"

_SOURCE_LABELS = {
    "filename_candidate": "file name",
    "header_exact": "report header",
    "header_alias": "report header",
    "position_cell": "report header",
    "explicit_sample_number": "report header",
    "projected_from_stats_count": "report statistics",
    "comment_derived": "report comment",
    "user_manual": "entered by you",
    "ocr_review": "OCR",
}
_ROW_STATE_NOTES = {
    ROW_CHANGED: "Changed since review. Review reports again before importing.",
    ROW_FAILED: "Metadata could not be read from this report.",
    ROW_UNSUPPORTED: "This parser's metadata is imported as detected and cannot be edited here.",
}
_MAX_ALTERNATIVES = 4


@dataclass(frozen=True)
class CellStyle:
    """Semantic styling of one metadata cell; the model maps it to theme colours."""

    kind: str = KIND_NORMAL
    bold: bool = False
    italic: bool = False


def source_label(source: str | None, origin: str) -> str:
    """Human wording for where a value came from."""

    if origin == ORIGIN_USER:
        return _SOURCE_LABELS["user_manual"]
    if origin == ORIGIN_OCR:
        return "OCR"
    return _SOURCE_LABELS.get(source or "", "")


def _percent(confidence: float | None) -> str:
    return f" ({round(confidence * 100)}%)" if confidence is not None else ""


def _is_pending(row: ReviewRow) -> bool:
    return row.state == ROW_PENDING


def is_missing(row: ReviewRow | None, field_name: str) -> bool:
    """A core value is missing; pending (not yet read) cells never count."""

    return row is not None and not _is_pending(row) and row.is_missing(field_name)


def is_low_confidence(row: ReviewRow | None, field_name: str) -> bool:
    return row is not None and not _is_pending(row) and row.is_low_confidence(field_name)


def has_conflict(row: ReviewRow | None, field_name: str) -> bool:
    return row is not None and row.cells[field_name].ocr_suggestion is not None


def cell_style(row: ReviewRow | None, field_name: str) -> CellStyle:
    """Classify a cell; precedence is read-only, pending, missing, conflict, manual, ..."""

    if row is None or not row.editable:
        return CellStyle(KIND_READONLY)
    cell = row.cells[field_name]
    manual = bool(cell.user_set)
    if _is_pending(row) and not manual:
        return CellStyle(KIND_PENDING, italic=True)
    if is_missing(row, field_name):
        return CellStyle(KIND_MISSING, italic=True)
    if has_conflict(row, field_name):
        return CellStyle(KIND_CONFLICT, bold=manual)
    if manual:
        return CellStyle(KIND_MANUAL, bold=True)
    if is_low_confidence(row, field_name):
        return CellStyle(KIND_LOW_CONFIDENCE, italic=True)
    if cell.origin == ORIGIN_OCR:
        return CellStyle(KIND_OCR)
    return CellStyle(KIND_NORMAL)


def edit_text(row: ReviewRow, field_name: str) -> str:
    return row.value(field_name) or ""


def display_text(row: ReviewRow | None, field_name: str) -> str:
    """Cell text; placeholders are only shown for rows that take part in the review."""

    if row is None:
        return ""
    style = cell_style(row, field_name)
    if style.kind == KIND_READONLY:
        return READONLY_TEXT
    if style.kind == KIND_PENDING:
        return PENDING_TEXT
    if style.kind == KIND_MISSING:
        return MISSING_TEXT
    return row.value(field_name) or ""


def accessible_text(row: ReviewRow | None, report_name: str, field_name: str) -> str:
    """``"<report>, <field>: <value or missing>"`` for assistive technology."""

    if row is None:
        value = "not available"
    elif not row.editable:
        value = "not editable"
    elif _is_pending(row) and not row.cells[field_name].user_set:
        value = "not read yet"
    else:
        value = row.value(field_name) or "missing"
    return f"{report_name}, {FIELD_LABELS[field_name]}: {value}"


def _value_tooltip_lines(row: ReviewRow, field_name: str) -> list[str]:
    cell = row.cells[field_name]
    if _is_pending(row) and not cell.user_set:
        return ["Not read yet (still reading, or the read was stopped). Values you enter are kept."]
    if cell.user_set:
        return [
            f"Source: {source_label(None, ORIGIN_USER)}",
            f"Detected value: {cell.auto_value}" if cell.auto_value else "Nothing was detected for this field.",
        ]
    if cell.value:
        lines = [f"Source: {source_label(cell.source, cell.origin) or 'unknown'}{_percent(cell.confidence)}"]
        if is_low_confidence(row, field_name):
            lines.append("Low confidence: check this value.")
        return lines
    if is_missing(row, field_name):
        return ["Missing: double-click or press F2 to enter a value."]
    return []


def cell_tooltip(row: ReviewRow | None, report_name: str, field_name: str, *, status_note: str = "") -> str:
    """Tooltip with source, confidence, conflict and read-only explanations."""

    lines = [f"{FIELD_LABELS[field_name]} - {report_name}"]
    if row is None:
        lines.append(status_note or "Metadata is not reviewed for this report.")
    elif not row.editable:
        lines.append(row.note or _ROW_STATE_NOTES.get(row.state, ""))
    else:
        lines.extend(_value_tooltip_lines(row, field_name))
        suggestion = row.cells[field_name].ocr_suggestion
        if suggestion is not None:
            lines.append(f"OCR suggests {suggestion}; your value is kept.")
        if not _is_pending(row):
            lines.append("Double-click or press F2 to edit.")
    return "\n".join(line for line in lines if line)


def metadata_attention_reasons(row: ReviewRow | None) -> tuple[str, ...]:
    """Short phrases explaining why the metadata of a report needs attention."""

    if row is None or (_is_pending(row) and not row.edited_fields):
        return ()
    if row.state in (ROW_FAILED, ROW_CHANGED):
        return (row.note or _ROW_STATE_NOTES[row.state],)
    if not row.editable:
        return ()
    reasons = [f"missing {FIELD_LABELS[name].lower()}" for name in REVIEW_FIELDS if is_missing(row, name)]
    reasons += [
        f"low confidence {FIELD_LABELS[name].lower()}"
        for name in REVIEW_FIELDS
        if is_low_confidence(row, name)
    ]
    reasons += [
        f"OCR differs for {FIELD_LABELS[name].lower()}"
        for name in REVIEW_FIELDS
        if has_conflict(row, name)
    ]
    return tuple(reasons)


def needs_metadata_attention(row: ReviewRow | None) -> bool:
    return bool(metadata_attention_reasons(row))


def reference_missing(row: ReviewRow | None) -> bool:
    return is_missing(row, "reference") and row is not None and row.editable


def _alternatives(row: ReviewRow, field_name: str) -> list[str]:
    current = row.value(field_name)
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for candidate in (*row.fast_candidates, *row.ocr_candidates):
        value = candidate.normalized_value
        if candidate.field_name != field_name or not value or value == current:
            continue
        key = (str(value), candidate.source_type)
        if key in seen:
            continue
        seen.add(key)
        origin = ORIGIN_OCR if candidate in row.ocr_candidates else "detected"
        lines.append(
            f"{value} ({source_label(candidate.source_type, origin) or candidate.source_type}"
            f"{_percent(candidate.confidence)})"
        )
        if len(lines) >= _MAX_ALTERNATIVES:
            break
    return lines


def _field_detail_line(row: ReviewRow, name: str) -> str:
    cell = row.cells[name]
    value = row.value(name) or ("missing" if is_missing(row, name) else "-")
    parts = [f"  {FIELD_LABELS[name]}: {value}"]
    if row.value(name):
        source = source_label(cell.source, cell.origin)
        if source:
            parts.append(f"source {source}")
        if cell.confidence is not None and cell.origin != ORIGIN_USER:
            parts.append(f"confidence {round(cell.confidence * 100)}%")
        if is_low_confidence(row, name):
            parts.append("low confidence")
    if cell.user_set and cell.auto_value:
        parts.append(f"detected {cell.auto_value}")
    if cell.ocr_suggestion is not None:
        parts.append(f"OCR suggests {cell.ocr_suggestion}; your value is kept")
    alternatives = _alternatives(row, name)
    if alternatives:
        parts.append("other candidates: " + ", ".join(alternatives))
    return " \u00b7 ".join(parts)


def details_lines(row: ReviewRow | None) -> list[str]:
    """Per-field value, source, confidence, alternatives and notes for the details pane."""

    if row is None:
        return []
    lines = ["Metadata:"]
    if not row.editable or _is_pending(row):
        note = row.note or _ROW_STATE_NOTES.get(row.state, "")
        lines.append("  " + (note or "Not read yet (still reading, or the read was stopped)."))
        if not row.editable:
            return lines
    lines.extend(_field_detail_line(row, name) for name in REVIEW_FIELDS)
    if row.ocr_state != "none":
        lines.append("  OCR: " + (row.ocr_note or ("done" if row.ocr_state == "done" else "failed")))
    lines.extend(
        f"  Warning: {message}" for severity, message in row.warnings if severity != "info" and message
    )
    return lines


def summarize_rows(rows: Sequence[ReviewRow] | Iterable[ReviewRow]) -> str:
    """One-line summary used by the readiness message."""

    rows = list(rows)
    edited = sum(1 for row in rows if row.editable and row.edited_fields)
    missing = sum(1 for row in rows if reference_missing(row))
    parts = [f"{len(rows)} report{'s' if len(rows) != 1 else ''}", f"{edited} edited"]
    parts.append(f"{missing} missing a reference" if missing else "all have a reference")
    return ", ".join(parts)


__all__ = [
    "CellStyle",
    "KIND_CONFLICT",
    "KIND_LOW_CONFIDENCE",
    "KIND_MANUAL",
    "KIND_MISSING",
    "KIND_NORMAL",
    "KIND_OCR",
    "KIND_PENDING",
    "KIND_READONLY",
    "accessible_text",
    "cell_style",
    "cell_tooltip",
    "details_lines",
    "display_text",
    "edit_text",
    "has_conflict",
    "is_low_confidence",
    "is_missing",
    "metadata_attention_reasons",
    "needs_metadata_attention",
    "reference_missing",
    "source_label",
    "summarize_rows",
]
