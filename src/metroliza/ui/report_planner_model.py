"""Bounded Qt models for reviewing a parser preflight result.

The models deliberately own only transient presentation and selection state.
They do not decide import eligibility: ``ImportPlan`` remains the authority at
the import boundary.  In particular, a destination duplicate may still be an
atomic import candidate there, but it is not selectable in this review UI.
"""

from __future__ import annotations

from collections.abc import Iterable
import re

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal

from metroliza.parsing.preflight import (
    ParseFilePreflight,
    ParsePreflightResult,
    ParsePreflightStatus,
)


# Parser identifiers use the same bounded wire format as parser registration.
# They are identifiers, never exception text or a source path.  This permits
# approved plugin/template ids without permitting an arbitrary diagnostic string.
_SAFE_PARSER_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SAFE_REASON_CODES = frozenset(
    {
        "already_in_destination",
        "ambiguous_parser_match",
        "axis_value_marker",
        "canonical_measurements",
        "content_inspection_failed",
        "dimension_marker",
        "duplicate_in_selected_source",
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

    return ", ".join(
        reason
        for reason in item.reason_codes
        if type(reason) is str and reason in _SAFE_REASON_CODES
    )


def _safe_candidate_warnings(values: Iterable[object]) -> tuple[str, ...]:
    """Keep warning presence useful without rendering raw plugin text."""

    safe = tuple(
        value for value in values if type(value) is str and value in _SAFE_REASON_CODES
    )
    return safe or (("review_warning",) if tuple(values) else ())


def _short_digest(value: object) -> str:
    if type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return f"sha256:{value[7:19]}..."
    return ""


def _needs_attention(item: ParseFilePreflight) -> bool:
    return item.status is not ParsePreflightStatus.READY or any(
        candidate.warnings for candidate in item.candidates
    )


class ReportPlannerModel(QAbstractTableModel):
    """One persistent table model over the latest parser preflight result."""

    selection_changed = pyqtSignal()

    CHECKBOX_COLUMN = 0
    LOCATION_COLUMN = 1
    STATUS_COLUMN = 2
    PARSER_COLUMN = 3
    CONFIDENCE_COLUMN = 4
    DETAIL_COLUMN = 5
    COLUMN_COUNT = 6

    _HEADERS = (
        "Import",
        "Location",
        "Status",
        "Parser",
        "Confidence",
        "Reason / warning",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._review: ParsePreflightResult | None = None
        self._selected_occurrence_ids: set[str] = set()
        self._selectable_occurrence_ids: set[str] = set()
        self._valid = False

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
    def parser_ids(self) -> tuple[str, ...]:
        """Safe parser identifiers available for presentation filters."""

        if not self.valid:
            return ()
        return tuple(sorted({safe_parser_id(item.parser_id) for item in self._review.files} - {""}))

    @property
    def counts(self) -> dict[str, int]:
        """Return review counts independent of proxy filtering or sorting."""

        files = self._review.files if self.valid else ()
        ready = sum(item.status is ParsePreflightStatus.READY for item in files)
        attention = sum(_needs_attention(item) for item in files)
        selected = len(self.selected_ids)
        return {
            "selected": selected,
            "ready": ready,
            "excluded": len(files) - selected,
            "attention": attention,
            "total": len(files),
        }

    def set_review(self, result: ParsePreflightResult) -> None:
        """Replace the review and select every fresh READY occurrence."""

        if not isinstance(result, ParsePreflightResult):
            raise TypeError("result must be a ParsePreflightResult")
        self.beginResetModel()
        self._review = result
        self._valid = not result.cancelled
        self._selectable_occurrence_ids = self._calculate_selectable_ids() if self._valid else set()
        self._selected_occurrence_ids = set(self._selectable_occurrence_ids)
        self.endResetModel()
        self.selection_changed.emit()

    def invalidate(self) -> None:
        """Drop a stale review and all selections before its inputs change."""

        had_selection = bool(self._selected_occurrence_ids)
        had_review = self._review is not None
        if had_review:
            self.beginResetModel()
        self._review = None
        self._valid = False
        self._selected_occurrence_ids.clear()
        self._selectable_occurrence_ids.clear()
        if had_review:
            self.endResetModel()
        if had_selection:
            self.selection_changed.emit()

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
        values = (
            ("Location", self._display_value(item, self.LOCATION_COLUMN)),
            ("Status", self._display_value(item, self.STATUS_COLUMN)),
            ("Parser", self._display_value(item, self.PARSER_COLUMN)),
            ("Confidence", self._display_value(item, self.CONFIDENCE_COLUMN)),
            ("Reason / warning", self._display_value(item, self.DETAIL_COLUMN)),
            ("Digest", _short_digest(item.fingerprint)),
            ("Competing parsers", ", ".join(
                value for value in (safe_parser_id(parser) for parser in item.competing_parser_ids) if value
            )),
        )
        lines = [f"{label}: {value}" for label, value in values if value]
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
            reasons = ", ".join(
                value for value in candidate.reasons
                if type(value) is str and value in _SAFE_REASON_CODES
            )
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
        return "\n".join(lines)[:8192]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or not self.valid:
            return 0
        return len(self._review.files)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else self.COLUMN_COUNT

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and 0 <= section < self.COLUMN_COUNT
        ):
            return self._HEADERS[section]
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
        if role in (Qt.ItemDataRole.AccessibleTextRole, Qt.ItemDataRole.AccessibleDescriptionRole):
            return f"{item.display_name}: {_STATUS_LABELS[item.status]}"
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None

        value = self._display_value(item, index.column())
        return value if role == Qt.ItemDataRole.DisplayRole else (value or None)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid() or self.item_at(index.row()) is None:
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if (
            index.column() == self.CHECKBOX_COLUMN
            and self._is_current_item_selectable(self.item_at(index.row()))
        ):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        item = self.item_at(index.row()) if index.isValid() else None
        if (
            item is None
            or index.column() != self.CHECKBOX_COLUMN
            or role != Qt.ItemDataRole.CheckStateRole
            or not self._is_current_item_selectable(item)
        ):
            return False
        checked = value == Qt.CheckState.Checked or value == int(Qt.CheckState.Checked.value)
        selected = set(self._selected_occurrence_ids)
        if checked:
            selected.add(item.stable_occurrence_id)
        else:
            selected.discard(item.stable_occurrence_id)
        self._replace_selection(selected)
        return True

    def _replace_selection(self, selected_ids: Iterable[str]) -> None:
        selected = set(selected_ids)
        if not self.valid:
            selected.clear()
        else:
            selected.intersection_update(self._selectable_occurrence_ids)
        if selected == self._selected_occurrence_ids:
            return
        self._selected_occurrence_ids = selected
        if self.rowCount():
            top_left = self.index(0, self.CHECKBOX_COLUMN)
            bottom_right = self.index(self.rowCount() - 1, self.CHECKBOX_COLUMN)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.CheckStateRole])
        self.selection_changed.emit()

    @staticmethod
    def _display_value(item: ParseFilePreflight, column: int) -> str:
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
            return detail
        return ""

    def _calculate_selectable_ids(self) -> set[str]:
        if not self.valid:
            return set()
        occurrence_counts: dict[str, int] = {}
        for item in self._review.files:
            occurrence_id = item.stable_occurrence_id
            occurrence_counts[occurrence_id] = occurrence_counts.get(occurrence_id, 0) + 1
        return {
            item.stable_occurrence_id
            for item in self._review.files
            if self._is_selectable(item, occurrence_counts=occurrence_counts)
        }

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
        self.setDynamicSortFilter(True)

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
        if self._attention_only and not _needs_attention(item):
            return False
        if self._text_filter:
            searchable = (
                str(item.display_name),
                item.status.value,
                safe_parser_id(item.parser_id),
                safe_review_detail(item),
            )
            if not any(self._text_filter in value.casefold() for value in searchable):
                return False
        return True
