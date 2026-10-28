"""Bounded Qt models for reviewing a parser preflight result.

The models deliberately own only transient presentation and selection state.
They do not decide import eligibility: ``ImportPlan`` remains the authority at
the import boundary.  In particular, a destination duplicate may still be an
atomic import candidate there, but it is not selectable in this review UI.
"""

from __future__ import annotations

from dataclasses import replace

from collections.abc import Iterable
import re

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont

from metroliza.parsing.metadata_review import MODE_OCR, READING_OK, MetadataReading
from metroliza.parsing.preflight import (
    ParseFilePreflight,
    ParsePreflightResult,
    ParsePreflightStatus,
)
from metroliza.reports.report_metadata_review import (
    FIELD_LABELS,
    REVIEW_FIELDS,
    ROW_CHANGED,
    ROW_FAILED,
    ROW_PENDING,
    ROW_READY,
    ReviewRow,
    apply_value_to_rows,
    normalize_review_value,
)
from metroliza.ui import report_planner_metadata as meta
from metroliza.ui import ui_theme_tokens as tokens


# Parser identifiers use the same bounded wire format as parser registration.
# They are identifiers, never exception text or a source path.  This permits
# approved plugin/template ids without permitting an arbitrary diagnostic string.
_SAFE_PARSER_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_UNKNOWN_REASON_PLACEHOLDER = "review_reason_unavailable"
_UNKNOWN_WARNING_PLACEHOLDER = "review_warning"
_SAFE_REASON_CODES = frozenset(
    {
        "already_in_destination",
        "ambiguous_parser_match",
        "axis_value_marker",
        "canonical_measurements",
        "content_inspection_failed",
        "dimension_marker",
        "duplicate_in_selected_source",
        "detector_exception",
        "detector_invalid_probe_result",
        "empty_embedded_text",
        "invalid_probe_contract",
        "measurement_header_marker",
        "metadata_header_markers",
        "missing_cmm_markers",
        "missing_required_markers",
        "missing_template_markers",
        "no_canonical_measurements",
        "no_plugin_above_confidence_threshold",
        "no_plugin_can_parse",
        "no_semantic_measurements",
        "parser_inspection_exception",
        "parser_inspection_failed",
        "pdf_backend_text_probe",
        "pdf_backend_text_probe_empty",
        "pdf_extension",
        "probe_exception",
        "probe_invalid_probe_result",
        "partial_cmm_markers",
        "reject_marker_found",
        "required_markers_found",
        "semantic_measurements",
        "semantic_match_without_rows",
        "semantic_measurements_found",
        "semantic_preflight_failed",
        "source_unreadable",
        "source_reader_not_configured",
        "strong_cmm_marker",
        "template_markers",
        "nominal_marker",
        "tolerance_marker",
        "measured_marker",
        "deviation_marker",
        "out_of_tolerance_marker",
        "bonus_marker",
        "unsupported_extension",
        "unsupported_report_format",
        "unsupported_source_format",
    }
)
_STATUS_LABELS = {
    ParsePreflightStatus.READY: "Ready to import",
    ParsePreflightStatus.DUPLICATE: "Already imported",
    ParsePreflightStatus.UNSUPPORTED: "Unsupported format",
    ParsePreflightStatus.AMBIGUOUS: "Ambiguous parser",
    ParsePreflightStatus.UNREADABLE: "Unreadable",
}


def safe_parser_id(value: object) -> str:
    """Return a registered-format parser or template identifier."""

    return value if type(value) is str and _SAFE_PARSER_ID.fullmatch(value) else ""


def safe_review_detail(item: ParseFilePreflight) -> str:
    """Render allowlisted reason identifiers without exposing diagnostics."""

    return ", ".join(_safe_reason_codes(item.reason_codes))


def _safe_reason_codes(values: Iterable[object]) -> tuple[str, ...]:
    """Keep known protocol codes and represent unknown evidence without its text."""

    safe: list[str] = []
    has_unknown = False
    for value in values:
        if type(value) is str and value in _SAFE_REASON_CODES:
            safe.append(value)
        elif value:
            has_unknown = True
    if has_unknown:
        safe.append(_UNKNOWN_REASON_PLACEHOLDER)
    return tuple(dict.fromkeys(safe))


def _safe_candidate_warnings(values: Iterable[object]) -> tuple[str, ...]:
    """Keep warning presence useful without rendering raw plugin text."""

    values = tuple(values)
    safe = tuple(value for value in values if type(value) is str and value in _SAFE_REASON_CODES)
    return safe or ((_UNKNOWN_WARNING_PLACEHOLDER,) if values else ())


def _short_digest(value: object) -> str:
    if type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return f"sha256:{value[7:19]}..."
    return ""


def _needs_attention(item: ParseFilePreflight) -> bool:
    return item.status is not ParsePreflightStatus.READY or any(
        candidate.warnings for candidate in item.candidates
    )


def _coalesced_row_ranges(rows: Iterable[int]) -> tuple[tuple[int, int], ...]:
    """Return adjacent model rows as minimal inclusive repaint ranges."""

    ordered_rows = tuple(sorted(rows))
    if not ordered_rows:
        return ()
    ranges: list[tuple[int, int]] = []
    first = last = ordered_rows[0]
    for row in ordered_rows[1:]:
        if row == last + 1:
            last = row
            continue
        ranges.append((first, last))
        first = last = row
    ranges.append((first, last))
    return tuple(ranges)


class ReportPlannerModel(QAbstractTableModel):
    """One persistent table model over the latest parser preflight result.

    Besides the review itself the model owns one ``ReviewRow`` per selectable
    (READY) report: the metadata cells shown inline, their manual edits and the
    results of the background reads.  Rows never reach the database from here;
    the host collects overrides for the checked reports at import time.
    """

    selection_changed = pyqtSignal()
    metadata_changed = pyqtSignal()
    edit_rejected = pyqtSignal(str)

    CHECKBOX_COLUMN = 0
    LOCATION_COLUMN = 1
    STATUS_COLUMN = 2
    METADATA_FIRST_COLUMN = 3
    PARSER_COLUMN = METADATA_FIRST_COLUMN + len(REVIEW_FIELDS)
    CONFIDENCE_COLUMN = PARSER_COLUMN + 1
    DETAIL_COLUMN = PARSER_COLUMN + 2
    COLUMN_COUNT = DETAIL_COLUMN + 1
    # Sorting uses the raw value (so "missing"/"..." placeholders group as empty).
    SORT_ROLE = Qt.ItemDataRole.UserRole + 1
    STYLE_ROLE = Qt.ItemDataRole.UserRole + 2

    _HEADERS = (
        "Import",
        "Location",
        "Status",
        *(FIELD_LABELS[name] for name in REVIEW_FIELDS),
        "Parser",
        "Confidence",
        "Reason / warning",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._review: ParsePreflightResult | None = None
        self._selected_occurrence_ids: set[str] = set()
        self._selectable_occurrence_ids: frozenset[str] = frozenset()
        self._ready_count = 0
        self._attention_count = 0
        self._base_attention_selectable_ids: frozenset[str] = frozenset()
        self._total_count = 0
        self._valid = False
        self._location_sort_keys: tuple[bytes, ...] = ()
        self._location_indexes: tuple[QModelIndex, ...] = ()
        self._meta_rows: dict[str, ReviewRow] = {}
        self._copy_undo = None
        self.last_copy_undo_skipped = 0
        self._row_by_occurrence: dict[str, int] = {}
        self._meta_attention_ids: set[str] = set()
        self._meta_missing_reference_ids: set[str] = set()
        self._palette = tokens.theme_tokens(dark_mode=False)
        self._dark = False
        self._high_contrast = False

    @property
    def valid(self) -> bool:
        """Whether the selection belongs to a current review result."""

        return self._valid and self._review is not None

    @property
    def selected_ids(self) -> tuple[str, ...]:
        """Selected occurrence ids in immutable preflight-review order."""

        if not self.valid:
            return ()
        return tuple(
            item.stable_occurrence_id
            for item in self._review.files
            if item.stable_occurrence_id in self._selected_occurrence_ids
        )

    @property
    def selected_count(self) -> int:
        """Return the current selected count without walking review rows."""

        return len(self._selected_occurrence_ids)

    @property
    def selectable_ids(self) -> frozenset[str]:
        """Return immutable cached READY IDs eligible for review selection."""

        return self._selectable_occurrence_ids if self.valid else frozenset()

    @property
    def parser_ids(self) -> tuple[str, ...]:
        """Safe parser identifiers available for presentation filters."""

        if not self.valid:
            return ()
        return tuple(sorted({safe_parser_id(item.parser_id) for item in self._review.files} - {""}))

    @property
    def counts(self) -> dict[str, int]:
        """Return review counts independent of proxy filtering or sorting."""

        selected = self.selected_count
        return {
            "selected": selected,
            "ready": self._ready_count,
            "excluded": self._total_count - selected,
            "attention": self._attention_count
            + len(self._meta_attention_ids - self._base_attention_selectable_ids),
            "total": self._total_count,
        }

    @property
    def missing_reference_count(self) -> int:
        """Reviewed reports whose reference is missing; independent of filters."""

        return len(self._meta_missing_reference_ids)

    @property
    def metadata_counts(self) -> dict[str, int]:
        """Metadata facts of the reviewed reports; independent of filters."""

        return {
            "missing_reference": self.missing_reference_count,
            "pending": sum(1 for row in self._meta_rows.values() if row.state == ROW_PENDING),
        }

    def has_checked_editable_rows(self) -> bool:
        """Whether any checked report can take OCR or manual values (short-circuits)."""

        selected = self._selected_occurrence_ids
        return any(row.editable for occ, row in self._meta_rows.items() if occ in selected)

    # -- metadata rows ----------------------------------------------------

    @property
    def metadata_rows(self) -> dict[str, ReviewRow]:
        """Review rows keyed by occurrence id, in review order (a copy)."""

        return dict(self._meta_rows)

    def metadata_row(self, occurrence_id: str) -> ReviewRow | None:
        return self._meta_rows.get(occurrence_id)

    def pending_metadata_ids(self) -> tuple[str, ...]:
        return tuple(occ for occ, row in self._meta_rows.items() if row.state == ROW_PENDING)

    def selected_metadata_rows(self) -> list[ReviewRow]:
        """Rows of the checked reports, in review order (what an import applies)."""

        return [row for occ, row in self._meta_rows.items() if occ in self._selected_occurrence_ids]

    def set_theme(self, *, dark: bool, high_contrast: bool = False) -> None:
        """Select the semantic token set used for the cell colours."""

        dark, high_contrast = bool(dark), bool(high_contrast)
        if (dark, high_contrast) == (self._dark, self._high_contrast):
            return
        self._dark, self._high_contrast = dark, high_contrast
        self._palette = tokens.theme_tokens(dark_mode=dark)
        self._emit_metadata_cells(self._row_by_occurrence.values())

    @staticmethod
    def field_for_column(column: int) -> str | None:
        index = column - ReportPlannerModel.METADATA_FIRST_COLUMN
        return REVIEW_FIELDS[index] if 0 <= index < len(REVIEW_FIELDS) else None

    @staticmethod
    def column_for_field(field_name: str) -> int:
        return ReportPlannerModel.METADATA_FIRST_COLUMN + REVIEW_FIELDS.index(field_name)

    def apply_reading(self, reading: MetadataReading) -> tuple[str, ...]:
        """Merge one worker reading into its row; returns the fields OCR changed."""

        row = self._meta_rows.get(reading.occurrence_id)
        if row is None:
            return ()
        changed: tuple[str, ...] = ()
        if reading.status != READING_OK or reading.selection is None:
            if reading.mode == MODE_OCR and row.state == ROW_READY and reading.status != ROW_CHANGED:
                row.mark_ocr_failed(reading.note)
            else:
                row.mark_failed(reading.note, state=reading.status)
        elif reading.mode == MODE_OCR:
            changed = row.apply_ocr(reading.selection, note=reading.ocr_note)
        else:
            row.apply_fast(reading.selection)
        self._row_changed(reading.occurrence_id)
        return changed

    def reset_row(self, occurrence_id: str) -> int:
        """Drop the manual edits of one report; returns how many were dropped."""

        row = self._meta_rows.get(occurrence_id)
        if row is None:
            return 0
        count = row.reset_user_edits()
        self._row_changed(occurrence_id)
        return count

    def copy_scope_counts(self, field_name, visible_ids, text):
        """Describe the checked editable scope using the same normalization as copy."""
        rows = [row for row in self.selected_metadata_rows() if row.editable]
        selected = {row.occurrence_id for row in rows}
        value, _error = normalize_review_value(field_name, text)
        return {
            "checked": len(selected),
            "hidden": len(selected - set(visible_ids)),
            "overwrites": sum(
                row.cells[field_name].user_set and row.cells[field_name].user_value != value
                for row in rows
            ),
        }

    @property
    def can_undo_copy(self):
        return self._copy_undo is not None

    def undo_copy(self):
        """Restore manual fields only where the post-copy cell is still unchanged."""
        self.last_copy_undo_skipped = 0
        if self._copy_undo is None:
            return 0
        field_name, previous = self._copy_undo
        self._copy_undo = None
        restored = 0
        for occurrence_id, (manual_before, after) in previous.items():
            row = self._meta_rows.get(occurrence_id)
            if row is None or row.cells[field_name] != after:
                self.last_copy_undo_skipped += 1
                continue
            cell = row.cells[field_name]
            # The copy may clear a conflicting OCR suggestion; restore it with the manual value.
            cell.user_set, cell.user_value, cell.ocr_suggestion = manual_before
            restored += 1
            self._row_changed(occurrence_id, notify=False)
        self.metadata_changed.emit()
        return restored

    def copy_value_to_checked(self, field_name: str, text: str, *, occurrence_ids=None) -> tuple[int, str | None]:
        """Set ``text`` as a manual value on every checked, editable report."""

        allowed = self._selected_occurrence_ids if occurrence_ids is None else set(occurrence_ids)
        rows = [row for row in self.selected_metadata_rows() if row.editable and row.occurrence_id in allowed]
        previous = {
            row.occurrence_id: (
                row.cells[field_name].user_set,
                row.cells[field_name].user_value,
                row.cells[field_name].ocr_suggestion,
            )
            for row in rows
        }
        changed, error = apply_value_to_rows(rows, field_name, text)
        if not error:
            snapshots = {
                row.occurrence_id: (previous[row.occurrence_id], replace(row.cells[field_name]))
                for row in rows
                if previous[row.occurrence_id][:2] != (row.cells[field_name].user_set, row.cells[field_name].user_value)
            }
            self._copy_undo = (field_name, snapshots) if snapshots else None
            for row in rows:
                self._row_changed(row.occurrence_id, notify=False)
            self.metadata_changed.emit()
        return changed, error

    def _row_changed(self, occurrence_id: str, *, notify: bool = True) -> None:
        row = self._meta_rows.get(occurrence_id)
        if row is None:
            return
        if meta.needs_metadata_attention(row):
            self._meta_attention_ids.add(occurrence_id)
        else:
            self._meta_attention_ids.discard(occurrence_id)
        if meta.reference_missing(row):
            self._meta_missing_reference_ids.add(occurrence_id)
        else:
            self._meta_missing_reference_ids.discard(occurrence_id)
        self._emit_metadata_cells((self._row_by_occurrence[occurrence_id],))
        if notify:
            self.metadata_changed.emit()

    def _emit_metadata_cells(self, rows: Iterable[int]) -> None:
        # Whole-row ranges so a proxy re-evaluates its filter whatever its key column.
        for first, last in _coalesced_row_ranges(rows):
            self.dataChanged.emit(self.index(first, 0), self.index(last, self.COLUMN_COUNT - 1))

    def _rebuild_metadata_rows(self, carry: dict[str, ReviewRow] | None) -> None:
        """Create one pending row per selectable report; reuse unchanged carried rows."""

        self._meta_rows = {}
        self._row_by_occurrence = {}
        self._meta_attention_ids = set()
        self._meta_missing_reference_ids = set()
        if not self.valid:
            return
        carry = carry or {}
        for position, item in enumerate(self._review.files):
            occurrence_id = item.stable_occurrence_id
            if occurrence_id not in self._selectable_occurrence_ids:
                continue
            previous = carry.get(occurrence_id)
            if (
                previous is not None
                and previous.fingerprint == item.fingerprint
                and previous.parser_id == item.parser_id
            ):
                row = previous
                if row.state in (ROW_FAILED, ROW_CHANGED):
                    row.state, row.note = ROW_PENDING, ""  # read again; edits stay
            else:
                row = ReviewRow(occurrence_id, item.fingerprint, item.display_name, item.parser_id)
            self._meta_rows[occurrence_id] = row
            self._row_by_occurrence[occurrence_id] = position
            if meta.needs_metadata_attention(row):
                self._meta_attention_ids.add(occurrence_id)
            if meta.reference_missing(row):
                self._meta_missing_reference_ids.add(occurrence_id)

    def item_needs_attention(self, item: ParseFilePreflight) -> bool:
        return _needs_attention(item) or item.stable_occurrence_id in self._meta_attention_ids

    def search_values(self, item: ParseFilePreflight) -> tuple[str, ...]:
        row = self._meta_rows.get(item.stable_occurrence_id)
        if row is None:
            return ()
        return tuple(value for name in REVIEW_FIELDS if (value := row.value(name)))

    # -- review -----------------------------------------------------------

    def set_review(
        self, result: ParsePreflightResult, *, carry: dict[str, ReviewRow] | None = None
    ) -> None:
        """Replace the review and select every fresh READY occurrence.

        ``carry`` offers rows of the previous review of the same source; only
        rows whose occurrence id, fingerprint and parser are unchanged are kept.
        """

        if not isinstance(result, ParsePreflightResult):
            raise TypeError("result must be a ParsePreflightResult")
        self.beginResetModel()
        self._copy_undo = None
        self._review = result
        # QString's default case-sensitive ordering compares UTF-16 code units.
        # The location is immutable for this review; avoid thousands of Python/Qt
        # data()/QVariant round trips during the proxy's initial sort.
        self._location_sort_keys = tuple(
            str(item.display_name).encode("utf-16-be", errors="surrogatepass")
            for item in result.files
        )
        self._location_indexes = tuple(
            self.createIndex(row, self.LOCATION_COLUMN) for row in range(len(result.files))
        )
        self._valid = not result.cancelled
        self._cache_review_summary()
        self._selected_occurrence_ids = set(self._selectable_occurrence_ids)
        self._rebuild_metadata_rows(carry)
        self.endResetModel()
        self.selection_changed.emit()
        self.metadata_changed.emit()

    def invalidate(self) -> None:
        """Drop a stale review and all selections before its inputs change."""

        self._copy_undo = None
        had_selection = bool(self._selected_occurrence_ids)
        had_review = self._review is not None
        if had_review:
            self.beginResetModel()
        self._review = None
        self._location_sort_keys = ()
        self._location_indexes = ()
        self._valid = False
        self._selected_occurrence_ids.clear()
        self._selectable_occurrence_ids = frozenset()
        self._base_attention_selectable_ids = frozenset()
        self._ready_count = 0
        self._attention_count = 0
        self._total_count = 0
        self._meta_rows = {}
        self._row_by_occurrence = {}
        self._meta_attention_ids = set()
        self._meta_missing_reference_ids = set()
        if had_review:
            self.endResetModel()
        if had_selection:
            self.selection_changed.emit()
        if had_review:
            self.metadata_changed.emit()

    def select_all_ready(self) -> None:
        """Select every READY occurrence, regardless of the active proxy filter."""

        if not self.valid:
            return
        self._replace_selection(self._selectable_occurrence_ids)

    def clear_selection(self) -> None:
        """Clear selection without changing the current review result."""

        self._replace_selection(set())

    def item_at(self, row: int) -> ParseFilePreflight | None:
        """Return the preflight item at a source-model row, if present."""

        if not self.valid or row < 0 or row >= len(self._review.files):
            return None
        return self._review.files[row]

    def details_text(self, row: int) -> str:
        """Return sanitized detail text for the host-owned details pane."""

        item = self.item_at(row)
        if item is None:
            return ""
        summary = (
            ("Location", self._display_value(item, self.LOCATION_COLUMN)),
            ("Status", self._display_value(item, self.STATUS_COLUMN)),
            ("Parser", self._display_value(item, self.PARSER_COLUMN)),
            ("Confidence", self._display_value(item, self.CONFIDENCE_COLUMN)),
            ("Reason / warning", self._display_value(item, self.DETAIL_COLUMN)),
        )
        evidence = (
            ("Digest", _short_digest(item.fingerprint)),
            ("Competing parsers", ", ".join(
                value for value in (safe_parser_id(parser) for parser in item.competing_parser_ids) if value
            )),
        )
        lines = [f"{label}: {value}" for label, value in summary if value]
        # The metadata block follows the summary: the small pane scrolls, evidence comes last.
        metadata = meta.details_lines(self._meta_rows.get(item.stable_occurrence_id))
        lines.extend(metadata)
        lines.extend(f"{label}: {value}" for label, value in evidence if value)
        for candidate in item.candidates[:32]:
            parser_id = safe_parser_id(candidate.parser_id)
            if not parser_id:
                continue
            outcome = (
                candidate.outcome if candidate.outcome in
                {"match", "no_match", "inspection_error", "legacy"} else "unavailable"
            )
            parts = [parser_id, outcome]
            if type(candidate.confidence) is int:
                parts.append(f"confidence {candidate.confidence}")
            reasons = ", ".join(_safe_reason_codes(candidate.reasons))
            warnings = ", ".join(_safe_candidate_warnings(candidate.warnings))
            if reasons:
                parts.append(f"reasons {reasons}")
            if warnings:
                parts.append(f"warnings {warnings}")
            lines.append("Candidate: " + " · ".join(parts))
        if item.status is ParsePreflightStatus.DUPLICATE:
            lines.append(
                "Review snapshot: a matching report was found during review; "
                "this row is excluded from the planner import."
            )
        return "\n".join(lines)[:12288]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or not self.valid:
            return 0
        return len(self._review.files)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else self.COLUMN_COUNT

    def index(self, row, column, parent=QModelIndex()):
        # QAbstractTableModel.index() dispatches through rowCount/columnCount for
        # every comparison in the proxy sort. Validate the same flat-table bounds
        # directly, avoiding two extra C++/Python round trips per index.
        if (parent.isValid() or not self.valid or row < 0 or column < 0
                or row >= len(self._review.files) or column >= self.COLUMN_COUNT):
            return QModelIndex()
        if column == self.LOCATION_COLUMN:
            return self._location_indexes[row]
        return self.createIndex(row, column)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < self.COLUMN_COUNT:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        if role == Qt.ItemDataRole.ToolTipRole and self.field_for_column(section) is not None:
            return f"{self._HEADERS[section]}: double-click or press F2 on a cell to edit it."
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        item = self.item_at(index.row()) if index.isValid() else None
        if item is None:
            return None

        if role == Qt.ItemDataRole.UserRole:
            return item.stable_occurrence_id
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == self.CHECKBOX_COLUMN:
            return (
                Qt.CheckState.Checked
                if item.stable_occurrence_id in self._selected_occurrence_ids
                else Qt.CheckState.Unchecked
            )
        field_name = self.field_for_column(index.column())
        if field_name is not None:
            return self._metadata_data(item, field_name, role)
        if role == self.SORT_ROLE:
            role = Qt.ItemDataRole.DisplayRole
        if role in (Qt.ItemDataRole.AccessibleTextRole, Qt.ItemDataRole.AccessibleDescriptionRole):
            return f"{item.display_name}: {_STATUS_LABELS[item.status]}"
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None

        value = self._display_value(item, index.column())
        return value if role == Qt.ItemDataRole.DisplayRole else (value or None)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        item = self.item_at(index.row()) if index.isValid() else None
        if item is None:
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if (
            index.column() == self.CHECKBOX_COLUMN
            and self._is_current_item_selectable(item)
        ):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        elif self.field_for_column(index.column()) is not None:
            row = self._meta_rows.get(item.stable_occurrence_id)
            if row is not None and row.editable:
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        item = self.item_at(index.row()) if index.isValid() else None
        if item is None:
            return False
        field_name = self.field_for_column(index.column())
        if field_name is not None and role == Qt.ItemDataRole.EditRole:
            return self._set_metadata_value(item, field_name, value)
        if (
            index.column() != self.CHECKBOX_COLUMN
            or role != Qt.ItemDataRole.CheckStateRole
            or not self._is_current_item_selectable(item)
        ):
            return False
        checked = value == Qt.CheckState.Checked or value == int(Qt.CheckState.Checked.value)
        self._set_selected(item.stable_occurrence_id, checked, index.row())
        return True

    def _set_metadata_value(self, item: ParseFilePreflight, field_name: str, value) -> bool:
        row = self._meta_rows.get(item.stable_occurrence_id)
        if row is None or not row.editable:
            self.edit_rejected.emit("This report cannot be edited.")
            return False
        accepted, error = row.set_user_value(field_name, value)
        if not accepted:
            self.edit_rejected.emit(f"{FIELD_LABELS[field_name]}: {error or 'The value was not accepted.'}")
            return False
        self._row_changed(item.stable_occurrence_id)
        return True

    # -- metadata cell presentation ----------------------------------------

    def _metadata_data(self, item: ParseFilePreflight, field_name: str, role):
        row = self._meta_rows.get(item.stable_occurrence_id)
        name = str(item.display_name)
        if role == Qt.ItemDataRole.DisplayRole:
            return meta.display_text(row, field_name)
        if role in (Qt.ItemDataRole.EditRole, self.SORT_ROLE):
            return meta.edit_text(row, field_name) if row is not None else ""
        if role == Qt.ItemDataRole.ToolTipRole:
            return meta.cell_tooltip(
                row, name, field_name, status_note=f"{_STATUS_LABELS[item.status]}: not part of the metadata review."
            )
        if role in (Qt.ItemDataRole.AccessibleTextRole, Qt.ItemDataRole.AccessibleDescriptionRole):
            return meta.accessible_text(row, name, field_name)
        style = meta.cell_style(row, field_name)
        if role == self.STYLE_ROLE:
            return style.kind
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(style)
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background(style)
        if role == Qt.ItemDataRole.FontRole and (style.bold or style.italic):
            font = QFont()
            font.setBold(style.bold)
            font.setItalic(style.italic)
            return font
        return None

    def _foreground(self, style: meta.CellStyle):
        if self._high_contrast:
            return None
        status = self._palette["STATUS_COLORS"]
        color = {
            meta.KIND_READONLY: self._palette["TEXT_MUTED"],
            meta.KIND_PENDING: self._palette["TEXT_MUTED"],
            meta.KIND_MISSING: status["warning"][0],
            meta.KIND_LOW_CONFIDENCE: status["warning"][0],
            meta.KIND_MANUAL: self._palette["ACCENT_PRIMARY"],
            meta.KIND_OCR: status["info"][0],
        }.get(style.kind)
        return QBrush(QColor(color)) if color else None

    def _background(self, style: meta.CellStyle):
        if self._high_contrast:
            return None
        status = self._palette["STATUS_COLORS"]
        color = {
            meta.KIND_MISSING: status["warning"][1],
            meta.KIND_CONFLICT: status["info"][1],
        }.get(style.kind)
        return QBrush(QColor(color)) if color else None

    def _replace_selection(self, selected_ids: Iterable[str]) -> None:
        """Apply a bulk selection and repaint only rows whose state changed."""

        selected = set(selected_ids)
        if not self.valid:
            selected.clear()
        else:
            selected.intersection_update(self._selectable_occurrence_ids)
        if selected == self._selected_occurrence_ids:
            return
        changed_ids = selected.symmetric_difference(self._selected_occurrence_ids)
        self._selected_occurrence_ids = selected
        self._emit_checkbox_changes_for_ids(changed_ids)
        self.selection_changed.emit()

    def _set_selected(self, occurrence_id: str, checked: bool, row: int) -> None:
        """Toggle one known selectable ID in place and repaint its exact row."""

        is_selected = occurrence_id in self._selected_occurrence_ids
        if is_selected == checked:
            return
        if checked:
            self._selected_occurrence_ids.add(occurrence_id)
        else:
            self._selected_occurrence_ids.remove(occurrence_id)
        self._emit_checkbox_ranges(((row, row),))
        self.selection_changed.emit()

    def _emit_checkbox_changes_for_ids(self, changed_ids: set[str]) -> None:
        if not changed_ids or not self.valid:
            return
        changed_rows = (
            row
            for row, item in enumerate(self._review.files)
            if item.stable_occurrence_id in changed_ids
        )
        self._emit_checkbox_ranges(_coalesced_row_ranges(changed_rows))

    def _emit_checkbox_ranges(self, ranges: Iterable[tuple[int, int]]) -> None:
        for first_row, last_row in ranges:
            self.dataChanged.emit(
                self.index(first_row, self.CHECKBOX_COLUMN),
                self.index(last_row, self.CHECKBOX_COLUMN),
                [Qt.ItemDataRole.CheckStateRole],
            )

    def _display_value(self, item: ParseFilePreflight, column: int) -> str:
        if column == ReportPlannerModel.LOCATION_COLUMN:
            # display_name is the source-relative or archive-member identity;
            # source_path can instead point into a temporary extraction tree.
            return str(item.display_name)
        if column == ReportPlannerModel.STATUS_COLUMN:
            return _STATUS_LABELS[item.status]
        if column == ReportPlannerModel.PARSER_COLUMN:
            return safe_parser_id(item.parser_id)
        if column == ReportPlannerModel.CONFIDENCE_COLUMN:
            return str(item.confidence) if type(item.confidence) is int else ""
        if column == ReportPlannerModel.DETAIL_COLUMN:
            detail = safe_review_detail(item)
            if any(candidate.warnings for candidate in item.candidates):
                detail += ("; " if detail else "") + "Parser warnings — see details"
            reasons = meta.metadata_attention_reasons(self._meta_rows.get(item.stable_occurrence_id))
            if reasons:
                detail += ("; " if detail else "") + "Metadata: " + ", ".join(reasons)
            return detail
        return ""

    def _cache_review_summary(self) -> None:
        """Calculate immutable review-wide facts once, when the review is replaced."""

        self._ready_count = 0
        self._attention_count = 0
        self._base_attention_selectable_ids = frozenset()
        self._total_count = 0
        self._selectable_occurrence_ids = frozenset()
        if not self.valid:
            return

        occurrence_counts: dict[str, int] = {}
        for item in self._review.files:
            self._total_count += 1
            if item.status is ParsePreflightStatus.READY:
                self._ready_count += 1
            if _needs_attention(item):
                self._attention_count += 1
            occurrence_id = item.stable_occurrence_id
            occurrence_counts[occurrence_id] = occurrence_counts.get(occurrence_id, 0) + 1
        self._selectable_occurrence_ids = frozenset(
            item.stable_occurrence_id
            for item in self._review.files
            if self._is_selectable(item, occurrence_counts=occurrence_counts)
        )
        self._base_attention_selectable_ids = frozenset(
            item.stable_occurrence_id
            for item in self._review.files
            if item.stable_occurrence_id in self._selectable_occurrence_ids and _needs_attention(item)
        )

    def _is_current_item_selectable(self, item: ParseFilePreflight | None) -> bool:
        return item is not None and item.stable_occurrence_id in self._selectable_occurrence_ids

    @staticmethod
    def _is_selectable(
        item: ParseFilePreflight | None,
        *,
        occurrence_counts: dict[str, int] | None = None,
    ) -> bool:
        """Keep incomplete/ambiguous review evidence out of UI selection."""

        if item is None or item.status is not ParsePreflightStatus.READY:
            return False
        if not item.fingerprint or not item.parser_id or item.registry_generation_id is None:
            return False
        return occurrence_counts is None or occurrence_counts.get(item.stable_occurrence_id) == 1


class ReportPlannerFilterModel(QSortFilterProxyModel):
    """A filter-only proxy; selection remains in :class:`ReportPlannerModel`."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text_filter = ""
        self._status_filter = ""
        self._parser_filter = ""
        self._attention_only = False
        self._planner_source = None
        self._default_location_order = True
        self.setDynamicSortFilter(True)
        self.setFilterKeyColumn(-1)
        self.setSortRole(ReportPlannerModel.SORT_ROLE)

    def setSourceModel(self, source):  # noqa: N802 - Qt API
        self._planner_source = source if isinstance(source, ReportPlannerModel) else None
        super().setSourceModel(source)

    def setSortCaseSensitivity(self, sensitivity):  # noqa: N802 - Qt API
        self._default_location_order = (
            sensitivity == Qt.CaseSensitivity.CaseSensitive and not self.isSortLocaleAware()
            and self.sortRole() == ReportPlannerModel.SORT_ROLE
        )
        super().setSortCaseSensitivity(sensitivity)

    def setSortLocaleAware(self, enabled):  # noqa: N802 - Qt API
        self._default_location_order = (
            not enabled and self.sortCaseSensitivity() == Qt.CaseSensitivity.CaseSensitive
            and self.sortRole() == ReportPlannerModel.SORT_ROLE
        )
        super().setSortLocaleAware(enabled)

    def setSortRole(self, role):  # noqa: N802 - Qt API
        self._default_location_order = (
            role == ReportPlannerModel.SORT_ROLE and not self.isSortLocaleAware()
            and self.sortCaseSensitivity() == Qt.CaseSensitivity.CaseSensitive
        )
        super().setSortRole(role)

    def lessThan(self, left, right):  # noqa: N802 - Qt override
        source = self._planner_source
        if (source is not None and self._default_location_order
                and left.column() == source.LOCATION_COLUMN):
            keys = source._location_sort_keys
            return keys[left.row()] < keys[right.row()]
        return super().lessThan(left, right)

    def set_text_filter(self, value: str) -> None:
        normalized = str(value or "").casefold().strip()
        if normalized != self._text_filter:
            self._text_filter = normalized
            self.invalidateFilter()

    def set_status_filter(self, value: str | ParsePreflightStatus) -> None:
        normalized = value.value if isinstance(value, ParsePreflightStatus) else str(value or "")
        if normalized != self._status_filter:
            self._status_filter = normalized
            self.invalidateFilter()

    def set_parser_filter(self, value: str) -> None:
        normalized = str(value or "")
        if normalized != self._parser_filter:
            self._parser_filter = normalized
            self.invalidateFilter()

    def set_attention_only(self, value: bool) -> None:
        normalized = bool(value)
        if normalized != self._attention_only:
            self._attention_only = normalized
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        source = self.sourceModel()
        if not isinstance(source, ReportPlannerModel):
            return False
        item = source.item_at(source_row)
        if item is None:
            return False
        if self._status_filter and item.status.value != self._status_filter:
            return False
        if self._parser_filter and safe_parser_id(item.parser_id) != self._parser_filter:
            return False
        if self._attention_only and not source.item_needs_attention(item):
            return False
        if self._text_filter:
            searchable = (
                str(item.display_name),
                item.status.value,
                safe_parser_id(item.parser_id),
                safe_review_detail(item),
                *source.search_values(item),
            )
            if not any(self._text_filter in value.casefold() for value in searchable):
                return False
        return True
