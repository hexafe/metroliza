"""Qt table model over the pre-import metadata review rows (#1100).

The model is a thin presentation layer: every rule (normalization, manual vs OCR
precedence, missing/low-confidence) lives in ``metroliza.reports.report_metadata_review``.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QFont

from metroliza.parsing.metadata_review import MetadataReading, READING_OK
from metroliza.reports.report_metadata_review import (
    FIELD_LABELS,
    ORIGIN_OCR,
    ORIGIN_USER,
    REVIEW_FIELDS,
    ReviewRow,
)
from metroliza.ui import ui_theme_tokens as tokens

_SOURCE_LABELS = {
    "filename_candidate": "filename",
    "header_exact": "header",
    "header_alias": "header",
    "position_cell": "header",
    "explicit_sample_number": "header",
    "projected_from_stats_count": "stats count",
    "comment_derived": "comment",
    "user_manual": "manual",
    "ocr_review": "OCR",
}
_STATE_LABELS = {
    "pending": "Reading...",
    "failed": "Could not read",
    "changed": "Changed since review",
    "unsupported": "Not editable",
}


def source_label(source: str | None, origin: str) -> str:
    if origin == ORIGIN_USER:
        return "manual"
    label = _SOURCE_LABELS.get(source or "", "")
    return f"OCR/{label}" if origin == ORIGIN_OCR and label and label != "OCR" else (
        label or ("OCR" if origin == ORIGIN_OCR else "")
    )


class MetadataReviewModel(QAbstractTableModel):
    """Editable model: file | reference ... comment | source | confidence | warnings."""

    FILE_COLUMN = 0
    FIRST_FIELD_COLUMN = 1
    SOURCE_COLUMN = FIRST_FIELD_COLUMN + len(REVIEW_FIELDS)
    CONFIDENCE_COLUMN = SOURCE_COLUMN + 1
    WARNING_COLUMN = SOURCE_COLUMN + 2
    COLUMN_COUNT = WARNING_COLUMN + 1
    OCCURRENCE_ROLE = Qt.ItemDataRole.UserRole
    ATTENTION_ROLE = Qt.ItemDataRole.UserRole + 1

    changed = pyqtSignal()
    edit_rejected = pyqtSignal(str)

    def __init__(self, rows: Sequence[ReviewRow], parent=None) -> None:
        super().__init__(parent)
        self._rows = list(rows)
        self._index_by_occurrence = {row.occurrence_id: i for i, row in enumerate(self._rows)}
        self._dark = False

    # -- accessors ---------------------------------------------------------

    @property
    def rows(self) -> tuple[ReviewRow, ...]:
        return tuple(self._rows)

    def row_at(self, row: int) -> ReviewRow | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def set_dark_mode(self, dark: bool) -> None:
        self._dark = bool(dark)
        self._emit_all()

    @staticmethod
    def field_for_column(column: int) -> str | None:
        index = column - MetadataReviewModel.FIRST_FIELD_COLUMN
        return REVIEW_FIELDS[index] if 0 <= index < len(REVIEW_FIELDS) else None

    @staticmethod
    def column_for_field(field_name: str) -> int:
        return MetadataReviewModel.FIRST_FIELD_COLUMN + REVIEW_FIELDS.index(field_name)

    # -- mutation (always on the GUI thread) -------------------------------

    def apply_reading(self, reading: MetadataReading) -> tuple[str, ...]:
        """Merge a worker reading into its row; returns fields OCR changed."""

        position = self._index_by_occurrence.get(reading.occurrence_id)
        if position is None:
            return ()
        row = self._rows[position]
        changed: tuple[str, ...] = ()
        if reading.status != READING_OK or reading.selection is None:
            if reading.mode == "complete" and row.state == "ready":
                row.mark_ocr_failed(reading.note)
            else:
                row.mark_failed(reading.note, state=reading.status)
        elif reading.mode == "complete":
            changed = row.apply_ocr(reading.selection, note=reading.ocr_note)
        else:
            row.apply_fast(reading.selection)
        self._emit_row(position)
        return changed

    def notify_rows_changed(self, rows: Sequence[ReviewRow]) -> None:
        for row in rows:
            position = self._index_by_occurrence.get(row.occurrence_id)
            if position is not None:
                self._emit_row(position)

    def _emit_row(self, position: int) -> None:
        self.dataChanged.emit(self.index(position, 0), self.index(position, self.COLUMN_COUNT - 1))
        self.changed.emit()

    def _emit_all(self) -> None:
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rows) - 1, self.COLUMN_COUNT - 1)
            )
        self.changed.emit()

    # -- Qt model interface ------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else self.COLUMN_COUNT

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        if section == self.FILE_COLUMN:
            return "Report"
        field_name = self.field_for_column(section)
        if field_name is not None:
            return FIELD_LABELS[field_name]
        return {
            self.SOURCE_COLUMN: "Source",
            self.CONFIDENCE_COLUMN: "Confidence",
            self.WARNING_COLUMN: "Warnings",
        }.get(section)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        row = self.row_at(index.row()) if index.isValid() else None
        if row is None:
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.field_for_column(index.column()) is not None and row.editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        row = self.row_at(index.row()) if index.isValid() else None
        field_name = self.field_for_column(index.column()) if row is not None else None
        if row is None or field_name is None or role != Qt.ItemDataRole.EditRole:
            return False
        accepted, error = row.set_user_value(field_name, value)
        if not accepted:
            self.edit_rejected.emit(error or "The value was not accepted.")
            return False
        self._emit_row(index.row())
        return True

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        row = self.row_at(index.row()) if index.isValid() else None
        if row is None:
            return None
        column = index.column()
        field_name = self.field_for_column(column)
        if role == self.OCCURRENCE_ROLE:
            return row.occurrence_id
        if role == self.ATTENTION_ROLE:
            return row.needs_attention
        if field_name is not None:
            return self._field_data(row, field_name, role)
        if role == Qt.ItemDataRole.DisplayRole:
            return self._summary_text(row, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._summary_tooltip(row, column)
        return None

    # -- presentation ------------------------------------------------------

    def _status_color(self, variant: str) -> tuple[str, str]:
        palette = tokens.DARK_STATUS_COLORS if self._dark else tokens.STATUS_COLORS
        return palette[variant]

    def _field_data(self, row: ReviewRow, field_name: str, role):
        cell = row.cells[field_name]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if role == Qt.ItemDataRole.DisplayRole and not cell.value and row.is_missing(field_name):
                return "(missing)"
            return cell.value or ""
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._field_brush(row, field_name, background=True)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._field_brush(row, field_name, background=False)
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setBold(cell.user_set)
            font.setItalic(row.is_low_confidence(field_name))
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._field_tooltip(row, field_name)
        if role in (Qt.ItemDataRole.AccessibleTextRole, Qt.ItemDataRole.AccessibleDescriptionRole):
            return f"{row.display_name}, {FIELD_LABELS[field_name]}: {cell.value or 'missing'}"
        return None

    def _field_brush(self, row: ReviewRow, field_name: str, *, background: bool):
        cell = row.cells[field_name]
        index = 1 if background else 0
        if row.is_missing(field_name):
            return QBrush(QColor(self._status_color("warning")[index]))
        if background and cell.ocr_suggestion is not None:
            return QBrush(QColor(self._status_color("info")[1]))
        if not background and cell.origin == ORIGIN_OCR:
            return QBrush(QColor(self._status_color("info")[0]))
        return None

    def _field_tooltip(self, row: ReviewRow, field_name: str) -> str:
        cell = row.cells[field_name]
        lines = [f"{FIELD_LABELS[field_name]} - {row.display_name}"]
        if not row.editable:
            lines.append(row.note)
        elif row.is_missing(field_name):
            lines.append("Missing: enter a value or apply one to the selected rows.")
        if cell.user_set:
            lines.append("Edited manually.")
            if cell.auto_value:
                lines.append(f"Detected value: {cell.auto_value}")
        elif cell.value:
            source = source_label(cell.source, cell.origin) or "unknown"
            confidence = (
                f" ({round(cell.confidence * 100)}%)" if cell.confidence is not None else ""
            )
            lines.append(f"Detected from: {source}{confidence}")
            if row.is_low_confidence(field_name):
                lines.append("Low confidence: check this value.")
        if cell.ocr_suggestion is not None:
            lines.append(
                f"OCR read '{cell.ocr_suggestion}', which differs from your value. "
                "Your value is kept unless you accept the OCR values."
            )
        return "\n".join(line for line in lines if line)

    def _summary_text(self, row: ReviewRow, column: int) -> str:
        if column == self.FILE_COLUMN:
            return row.display_name
        if column == self.SOURCE_COLUMN:
            labels = []
            for name in REVIEW_FIELDS:
                cell = row.cells[name]
                if cell.value:
                    label = source_label(cell.source, cell.origin)
                    if label and label not in labels:
                        labels.append(label)
            return ", ".join(labels)
        if column == self.CONFIDENCE_COLUMN:
            confidence = row.metadata_confidence
            return f"{round(confidence * 100)}%" if confidence is not None else ""
        parts = []
        if row.state in _STATE_LABELS and row.state != "pending":
            parts.append(row.note or _STATE_LABELS[row.state])
        elif row.state == "pending":
            parts.append(_STATE_LABELS["pending"])
        parts.extend(message for severity, message in row.warnings if severity != "info")
        if row.ocr_state == "failed" and row.ocr_note:
            parts.append(row.ocr_note)
        return "; ".join(dict.fromkeys(part for part in parts if part))

    def _summary_tooltip(self, row: ReviewRow, column: int) -> str:
        if column == self.FILE_COLUMN:
            return row.display_name
        lines = [message for _severity, message in row.warnings]
        if row.note:
            lines.insert(0, row.note)
        if row.ocr_note:
            lines.append(f"OCR: {row.ocr_note}")
        if column == self.CONFIDENCE_COLUMN:
            lines.insert(0, "Overall detection confidence of the latest read.")
        return "\n".join(dict.fromkeys(line for line in lines if line))


class MetadataReviewFilterModel(QSortFilterProxyModel):
    """Presentation-only filter: text search and "only missing / low confidence"."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._attention_only = False
        self.setDynamicSortFilter(True)

    @property
    def attention_only(self) -> bool:
        return self._attention_only

    def set_text_filter(self, value: str) -> None:
        normalized = str(value or "").casefold().strip()
        if normalized != self._text:
            self._text = normalized
            self.invalidateFilter()

    def set_attention_only(self, value: bool) -> None:
        if bool(value) != self._attention_only:
            self._attention_only = bool(value)
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        source = self.sourceModel()
        row = source.row_at(source_row) if isinstance(source, MetadataReviewModel) else None
        if row is None:
            return False
        if self._attention_only and not row.needs_attention:
            return False
        if self._text:
            haystack = [row.display_name.casefold()]
            haystack.extend((row.value(name) or "").casefold() for name in REVIEW_FIELDS)
            return any(self._text in value for value in haystack)
        return True
