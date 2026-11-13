"""Reusable report review surface; execution stays with its owning host.

The table is also the metadata review (#1100): after a review the host reads the
metadata of the ready reports in the background and the cells fill in place.
Cells can be corrected inline; nothing is written before the host imports.
"""

from html import escape

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QTableView, QVBoxLayout, QWidget,
)

from metroliza.parsing.preflight import ParsePreflightStatus
from metroliza.reports.report_metadata_review import CORE_FIELDS, FIELD_LABELS, REVIEW_FIELDS
from metroliza.ui.report_planner_model import ReportPlannerFilterModel, ReportPlannerModel
from metroliza.ui import ui_theme_tokens as tokens
from metroliza.ui.ui_foundation import _is_dark_widget_palette, configure_accessibility


PLANNER_ACTION_STYLE = "QPushButton { padding: 3px 9px; min-height: 20px; }"
# The planner's own toolbar is slimmer so its three control rows stay within the
# compact (720x480) shell; the host's primary actions keep PLANNER_ACTION_STYLE.
PLANNER_TOOLBAR_STYLE = (
    "QPushButton { padding: 1px 6px; min-height: 18px; }"
    "QLineEdit, QComboBox { min-height: 18px; padding-top: 1px; padding-bottom: 1px; }"
)
COMPACT_WIDTH = 850
_DEFAULT_COLUMN_WIDTHS = {
    ReportPlannerModel.CHECKBOX_COLUMN: 60,
    ReportPlannerModel.LOCATION_COLUMN: 230,
    ReportPlannerModel.STATUS_COLUMN: 150,
    ReportPlannerModel.PARSER_COLUMN: 100,
    ReportPlannerModel.CONFIDENCE_COLUMN: 80,
    ReportPlannerModel.DETAIL_COLUMN: 240,
}
_DEFAULT_METADATA_WIDTHS = {
    "reference": 120,
    "part_name": 150,
    "sample_number": 80,
    "report_date": 95,
    "report_time": 70,
    "revision": 70,
    "operator_name": 110,
    "comment": 160,
}


class _ReportTable(QTableView):
    """Space operates the row checkbox; Enter edits the current metadata cell."""

    def keyPressEvent(self, event):
        editing = self.state() == QAbstractItemView.State.EditingState
        if not editing and event.key() == Qt.Key.Key_Space and self.currentIndex().isValid():
            index = self.currentIndex().siblingAtColumn(0)
            if self.model().flags(index) & Qt.ItemFlag.ItemIsUserCheckable:
                checked = self.model().data(index, Qt.ItemDataRole.CheckStateRole)
                self.model().setData(
                    index,
                    Qt.CheckState.Unchecked
                    if checked in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
                    else Qt.CheckState.Checked,
                    Qt.ItemDataRole.CheckStateRole,
                )
            event.accept()
            return
        if not editing and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid() and self.model().flags(index) & Qt.ItemFlag.ItemIsEditable:
                self.edit(index)
                event.accept()
                return
        super().keyPressEvent(event)


class ReportPlanner(QWidget):
    """One source model owns the selection, independently of visible filters."""

    selection_changed = pyqtSignal()
    ocr_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(PLANNER_TOOLBAR_STYLE)
        self._compact_columns = None
        self._column_widths = [
            _DEFAULT_COLUMN_WIDTHS.get(column)
            or _DEFAULT_METADATA_WIDTHS[ReportPlannerModel.field_for_column(column)]
            for column in range(ReportPlannerModel.COLUMN_COUNT)
        ]
        self._visible_fields = set(CORE_FIELDS)
        self._worker_mode = None
        self._ocr_reason = ""
        self._busy = False
        self._status_text = ""
        self._status_variant = "neutral"
        self.model = ReportPlannerModel(self)
        self.proxy = ReportPlannerFilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search reports and metadata")
        self.search.setAccessibleName("Search reports")
        self.search.textChanged.connect(self.proxy.set_text_filter)
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Report status filter")
        self.status_filter.addItem("All statuses", "")
        for status, label in (
            (ParsePreflightStatus.READY, "Ready to import"),
            (ParsePreflightStatus.DUPLICATE, "Already imported"),
            (ParsePreflightStatus.UNSUPPORTED, "Unsupported format"),
            (ParsePreflightStatus.AMBIGUOUS, "Ambiguous parser"),
            (ParsePreflightStatus.UNREADABLE, "Unreadable"),
        ):
            self.status_filter.addItem(label, status.value)
        self.status_filter.currentIndexChanged.connect(
            lambda: self.proxy.set_status_filter(self.status_filter.currentData())
        )
        self.parser_filter = QComboBox()
        self.parser_filter.setAccessibleName("Detected parser filter")
        self.parser_filter.addItem("All parsers", "")
        self.parser_filter.currentIndexChanged.connect(
            lambda: self.proxy.set_parser_filter(self.parser_filter.currentData() or "")
        )
        self.attention_filter = QCheckBox("Needs attention")
        self.attention_filter.setToolTip(
            "Show reports with a parser warning, a missing reference or core value, "
            "a low-confidence value or an OCR conflict."
        )
        self.attention_filter.toggled.connect(self.proxy.set_attention_only)
        self.select_ready = QPushButton("Select all ready")
        self.select_ready.setToolTip("Select every ready report, including hidden rows.")
        self.select_ready.clicked.connect(self.model.select_all_ready)
        self.clear = QPushButton("Clear selection")
        self.clear.setToolTip("Clear the selection for all reports, including hidden rows.")
        self.clear.clicked.connect(self.model.clear_selection)
        self.counts = QLabel()
        self.counts.setWordWrap(True)
        self.counts.setAccessibleName("Report selection status")
        self.table = _ReportTable()
        self.table.setAccessibleName("Reviewed reports, metadata and import selection")
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setTabKeyNavigation(False)
        # One line per report keeps many columns and rows readable; tooltips carry the rest.
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.table.setMinimumSize(0, 70)
        # The shared theme applies a control-sized minimum to all item views.
        # Preserve a usable report viewport after stylesheet polishing as well.
        self.table.setStyleSheet("QTableView { min-height: 60px; }")
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_columns_menu)
        self.details_button = QPushButton("Report details")
        self.details_button.setCheckable(True)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Reviewed report details")
        self.details.setMaximumHeight(110)
        self.details.hide()
        self.details_button.toggled.connect(self.details.setVisible)
        self.table.selectionModel().currentRowChanged.connect(self._show_details)
        self.table.selectionModel().currentChanged.connect(self._update_metadata_actions)
        self.outcome = QPlainTextEdit()
        self.outcome.setReadOnly(True)
        self.outcome.setAccessibleName("Last report import outcome")
        self.outcome.setMaximumHeight(110)
        self.outcome.hide()
        self.outcome_button = QPushButton("Import outcome")
        self.outcome_button.setToolTip("Show the outcome of the last import.")
        configure_accessibility(self.outcome_button, name="Last import outcome")
        self.outcome_button.setCheckable(True)
        self.outcome_button.hide()
        self.outcome_button.toggled.connect(self.outcome.setVisible)
        self.details_button.toggled.connect(
            lambda checked: self.outcome_button.setChecked(False) if checked else None
        )
        self.outcome_button.toggled.connect(
            lambda checked: self.details_button.setChecked(False) if checked else None
        )
        for pane in (self.details, self.outcome):
            # These are scrolling evidence panes, so native text-edit size hints
            # must not force the whole compact host taller at high DPI.
            pane.setStyleSheet("QPlainTextEdit { min-height: 32px; }")
            pane.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)

        self.ocr_button = QPushButton("Read with OCR")
        self.ocr_button.clicked.connect(self.ocr_requested)
        # The other metadata actions live in one menu so the toolbar keeps two rows.
        self.metadata_menu = QMenu(self)
        self.metadata_menu.setToolTipsVisible(True)
        self.metadata_menu.aboutToShow.connect(lambda: self._update_metadata_actions(include_copy_counts=True))
        self.copy_to_checked = self._add_menu_action("Copy to checked", self.copy_current_value_to_checked)
        self.undo_copy_action = self._add_menu_action("Undo copy to checked", self.undo_copy)
        self.reset_to_detected = self._add_menu_action("Reset to detected", self.reset_current_row)
        self.stop_action = self._add_menu_action("Stop metadata read", self.stop_requested.emit)
        self.stop_action.setToolTip("Stop after the current report. Values already read are kept.")
        self.metadata_button = QPushButton("Metadata")
        self.metadata_button.setMenu(self.metadata_menu)
        self.metadata_button.setToolTip(
            "Copy a value to the checked reports, reset a report to the detected values, "
            "or stop the metadata read."
        )
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_metadata_menu)
        configure_accessibility(self.ocr_button, name="Read checked reports with OCR")
        configure_accessibility(self.metadata_button, name="Metadata actions")

        # Two toolbar rows keep the planner inside the compact 720x480 shell, also at
        # its 704 px width when the "Last import outcome" button is visible.
        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(2)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.attention_filter)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.parser_filter)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(2)
        actions.addWidget(self.select_ready)
        actions.addWidget(self.clear)
        actions.addWidget(self.details_button)
        actions.addWidget(self.outcome_button)
        actions.addStretch(1)
        actions.addWidget(self.ocr_button)
        actions.addWidget(self.metadata_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(filters)
        layout.addLayout(actions)
        layout.addWidget(self.counts)
        layout.addWidget(self.table, 3)
        layout.addWidget(self.details, 1)
        layout.addWidget(self.outcome, 1)
        self.model.selection_changed.connect(self._selection_updated)
        self.model.metadata_changed.connect(self._metadata_updated)
        self.model.edit_rejected.connect(lambda text: self.set_metadata_status(text, "warning"))
        self.proxy.rowsInserted.connect(self._update_counts)
        self.proxy.rowsRemoved.connect(self._update_counts)
        self.proxy.modelReset.connect(self._update_counts)
        self.refresh_theme()
        self._update_counts()
        self._update_metadata_actions()

    # -- review lifecycle ---------------------------------------------------

    def set_review(self, result, *, carry=None):
        self._remember_column_widths()
        # Reset and clear the previous filters before sorting the replacement once.
        # Sorting during endResetModel otherwise rebuilds the proxy repeatedly as
        # the filter controls and metadata counts catch up with the new review.
        column, order = self.proxy.sortColumn(), self.proxy.sortOrder()
        dynamic = self.proxy.dynamicSortFilter()
        self.proxy.setDynamicSortFilter(False)
        self.proxy.sort(-1)
        try:
            self._set_review_contents(result, carry=carry)
        finally:
            self.proxy.setDynamicSortFilter(dynamic)
            self.proxy.sort(column, order)
        if self.proxy.rowCount():
            self.table.setCurrentIndex(self.proxy.index(0, 1))
        self._update_counts()
        self._update_metadata_actions()

    def _set_review_contents(self, result, *, carry):
        self.model.set_review(result, carry=carry)
        # Resetting an initially empty proxy also resets Qt's header sections.
        # Apply the review's starting widths after the columns actually exist.
        for column, width in enumerate(self._column_widths):
            self.table.setColumnWidth(column, width)
        self._configure_columns()
        self.parser_filter.clear()
        self.parser_filter.addItem("All parsers", "")
        for parser in self.model.parser_ids:
            self.parser_filter.addItem(parser, parser)
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        self.attention_filter.setChecked(False)

    def invalidate(self):
        self._remember_column_widths()
        self.model.invalidate()
        self.details.clear()
        self.clear_metadata_status()
        self._update_counts()
        self._update_metadata_actions()

    def set_busy(self, busy):
        self._busy = bool(busy)
        for control in (self.table, self.select_ready, self.clear):
            control.setEnabled(not busy)
        self._update_metadata_actions()

    def show_outcome(self, text):
        self.outcome.setPlainText(text)
        self.outcome_button.show()
        self.outcome_button.setChecked(True)

    def clear_outcome(self):
        """Drop the prior context's outcome when the shell accepts new inputs."""
        self.outcome_button.setChecked(False)
        self.outcome.clear()
        self.outcome_button.hide()

    # -- metadata (inline review) -------------------------------------------

    def metadata_read_order(self, occurrence_ids):
        """Return ``occurrence_ids`` in the order the table shows them, rest last."""

        wanted = set(occurrence_ids)
        visible = []
        for row in range(self.proxy.rowCount()):
            occurrence = self.proxy.data(self.proxy.index(row, 0), Qt.ItemDataRole.UserRole)
            if occurrence in wanted:
                visible.append(occurrence)
        seen = set(visible)
        return visible + [occurrence for occurrence in occurrence_ids if occurrence not in seen]

    def set_metadata_worker(self, mode, *, ocr_reason=""):
        """Host tells which worker mode is running (``None`` when idle) and why OCR is off."""

        self._worker_mode = mode
        self._ocr_reason = ocr_reason
        self._update_metadata_actions()

    @property
    def metadata_status_text(self):
        """Progress or message currently shown in front of the counts line."""

        return self._status_text

    def set_metadata_status(self, text, variant="neutral"):
        """Show progress ("Reading metadata 3/7...") or a message in the counts line."""

        self._status_text, self._status_variant = str(text or ""), variant
        self._update_counts()

    def clear_metadata_status(self):
        self.set_metadata_status("")

    def _add_menu_action(self, text, slot):
        action = QAction(text, self.metadata_menu)
        action.triggered.connect(lambda _checked=False: slot())
        self.metadata_menu.addAction(action)
        return action

    def _show_metadata_menu(self, position):
        self._update_metadata_actions()
        self.metadata_menu.exec(self.table.viewport().mapToGlobal(position))

    def current_metadata_cell(self):
        """Return ``(review_row, field_name)`` for the current cell, or ``(None, None)``."""

        index = self.table.currentIndex()
        if not index.isValid():
            return None, None
        source = self.proxy.mapToSource(index)
        item = self.model.item_at(source.row())
        field_name = self.model.field_for_column(source.column())
        if item is None or field_name is None:
            return None, None
        return self.model.metadata_row(item.stable_occurrence_id), field_name

    def copy_current_value_to_checked(self):
        row, field_name = self.current_metadata_cell()
        value = row.value(field_name) if row is not None else None
        if not value:
            self.set_metadata_status("The current cell is empty; there is nothing to copy.", "warning")
            return
        visible_ids = self._visible_report_ids()
        counts = self.model.copy_scope_counts(field_name, visible_ids, value)
        scope = self._choose_copy_scope(field_name, value, counts) if counts["hidden"] or counts["overwrites"] else "all"
        if scope == "cancel":
            return
        changed, error = self.model.copy_value_to_checked(
            field_name, value, occurrence_ids=visible_ids if scope == "visible" else None,
        )
        if error:
            self.set_metadata_status(error, "warning")
            return
        self.set_metadata_status(
            f"{FIELD_LABELS[field_name]} copied to {changed} checked report"
            f"{'' if changed == 1 else 's'}.",
            "success",
        )

    def _visible_report_ids(self):
        return {
            self.proxy.data(self.proxy.index(row, 0), Qt.ItemDataRole.UserRole)
            for row in range(self.proxy.rowCount())
        }

    def _choose_copy_scope(self, field_name, value, counts):
        prompt = QMessageBox(self)
        prompt.setWindowTitle("Copy metadata to checked reports")
        prompt.setTextFormat(Qt.TextFormat.PlainText)
        prompt.setText(
            f"{FIELD_LABELS[field_name]} (value preview): {str(value)[:300]}\n"
            f"{counts['checked']} checked, {counts['hidden']} hidden; "
            f"{counts['overwrites']} existing manual corrections may be overwritten.\n"
            "Choose which checked editable reports to update. Undo copy restores the previous values and markers."
        )
        all_rows = prompt.addButton(
            f"Copy to all {counts['checked']} checked ({counts['hidden']} hidden)",
            QMessageBox.ButtonRole.AcceptRole,
        )
        visible = prompt.addButton("Copy to visible checked only", QMessageBox.ButtonRole.ActionRole)
        cancel = prompt.addButton(QMessageBox.StandardButton.Cancel)
        prompt.setDefaultButton(cancel)
        prompt.setEscapeButton(cancel)
        prompt.exec()
        return "all" if prompt.clickedButton() is all_rows else "visible" if prompt.clickedButton() is visible else "cancel"

    def undo_copy(self):
        count = self.model.undo_copy()
        skipped = self.model.last_copy_undo_skipped
        self.set_metadata_status(
            f"Restored previous metadata for {count} reports; {skipped} skipped because they changed after copying."
        )

    def reset_current_row(self):
        row, _field = self.current_metadata_cell()
        if row is None:
            return
        count = self.model.reset_row(row.occurrence_id)
        self.set_metadata_status(
            f"Dropped {count} manual edit{'' if count == 1 else 's'}; the detected values are back.",
            "neutral",
        )

    @property
    def visible_metadata_fields(self):
        return tuple(name for name in REVIEW_FIELDS if name in self._visible_fields)

    def set_metadata_field_visible(self, field_name, visible):
        if field_name not in REVIEW_FIELDS:
            raise ValueError(f"Unsupported review field: {field_name}")
        before = set(self._visible_fields)
        (self._visible_fields.add if visible else self._visible_fields.discard)(field_name)
        if before != self._visible_fields:
            self._configure_columns()

    def build_columns_menu(self):
        menu = QMenu("Columns", self)
        for name in REVIEW_FIELDS:
            action = menu.addAction(FIELD_LABELS[name])
            action.setCheckable(True)
            action.setChecked(name in self._visible_fields)
            action.toggled.connect(lambda checked, field=name: self.set_metadata_field_visible(field, checked))
        return menu

    def _show_columns_menu(self, position):
        menu = self.build_columns_menu()
        menu.exec(self.table.horizontalHeader().mapToGlobal(position))

    def _update_metadata_actions(self, *_args, include_copy_counts=False):
        row, field_name = self.current_metadata_cell()
        usable = not self._busy and self.model.valid
        editable = row is not None and row.editable
        can_copy = usable and editable and self._worker_mode is None and bool(row.value(field_name))
        self.copy_to_checked.setEnabled(can_copy)
        self.undo_copy_action.setEnabled(usable and self._worker_mode is None and self.model.can_undo_copy)
        if can_copy and include_copy_counts:
            counts = self.model.copy_scope_counts(field_name, self._visible_report_ids(), row.value(field_name))
            self.copy_to_checked.setText(
                f"Copy {FIELD_LABELS[field_name]} '{str(row.value(field_name))[:60]}' to "
                f"{counts['checked']} checked ({counts['hidden']} hidden, {counts['overwrites']} manual)"
            )
        elif can_copy:
            self.copy_to_checked.setText(f"Copy {FIELD_LABELS[field_name]} to checked")
        else:
            self.copy_to_checked.setText("Copy to checked")
        self.copy_to_checked.setToolTip(
            "Copy this cell's value to the same field of every checked report "
            "(counts as a manual edit)."
            if can_copy
            else "Select a filled metadata cell of an editable report, then copy its value to all checked reports."
        )
        can_reset = usable and editable and bool(row.edited_fields or row.conflict_fields)
        self.reset_to_detected.setEnabled(can_reset)
        self.reset_to_detected.setToolTip(
            "Drop the manual edits of the current report and return to the detected values."
            if can_reset
            else "The current report has no manual edits."
        )
        self.stop_action.setEnabled(self._worker_mode is not None)
        checked_ready = self.model.has_checked_editable_rows()
        if self._ocr_reason:
            tooltip = self._ocr_reason
        elif self._worker_mode is not None:
            tooltip = "Wait for the metadata read to finish or use Metadata > Stop metadata read."
        elif not checked_ready:
            tooltip = "Check at least one editable ready report to read its header with OCR."
        else:
            tooltip = (
                "Read the report headers of the checked reports with OCR. "
                "Values you entered are kept; nothing is written before Import."
            )
        self.ocr_button.setEnabled(
            usable and checked_ready and self._worker_mode is None and not self._ocr_reason
        )
        self.ocr_button.setToolTip(tooltip)
        self.metadata_button.setEnabled(usable)

    def _metadata_updated(self):
        self._update_counts()
        self._update_metadata_actions()
        if self.details.isVisible():
            self._show_details(self.table.currentIndex())

    # -- selection and counts ------------------------------------------------

    def _selection_updated(self):
        self._update_counts()
        self._update_metadata_actions()
        self.selection_changed.emit()

    def _update_counts(self, *_args):
        counts = self.model.counts
        text = (
            f"{counts['selected']} selected overall · {self.proxy.rowCount()} visible / "
            f"{counts['total']} reviewed · {counts['ready']} ready · "
            f"{counts['excluded']} excluded · {counts['attention']} need attention"
        )
        missing_reference = self.model.missing_reference_count
        if missing_reference:
            text += f" · {missing_reference} missing reference"
        if not self._status_text:
            self.counts.setTextFormat(Qt.TextFormat.PlainText)
            self.counts.setText(text)
            self.counts.setAccessibleDescription(text)
            return
        # Progress and messages lead the existing line (bold, in the theme's status colour).
        color = tokens.theme_tokens(dark_mode=self.model._dark)["STATUS_COLORS"].get(
            self._status_variant, (None, None)
        )[0]
        style = f' style="color:{color}"' if color and not self.model._high_contrast else ""
        self.counts.setTextFormat(Qt.TextFormat.RichText)
        self.counts.setText(f"<b><span{style}>{escape(self._status_text)}</span></b> · {escape(text)}")
        self.counts.setAccessibleDescription(f"{self._status_text} · {text}")

    def _show_details(self, current, _previous=None):
        # The model is the sole sanitizer and never renders raw parser exceptions.
        index = self.proxy.mapToSource(current)
        self.details.setPlainText(
            self.model.details_text(index.row()) if index.isValid() else ""
        )

    # -- theme --------------------------------------------------------------

    def refresh_theme(self):
        """Re-read light/dark from the window; the host calls this when its palette changes.

        The planner carries its own style sheet, so its palette does not follow a
        theme applied to an ancestor; the top-level window's palette is the truth.
        """

        application = QApplication.instance()
        high_contrast = (
            application is not None and application.property("metrolizaThemeMode") == "high_contrast"
        )
        self.model.set_theme(dark=_is_dark_widget_palette(self.window()), high_contrast=high_contrast)
        if self._status_text:
            self._update_counts()


    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.refresh_theme()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_theme()

    # -- columns --------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._configure_columns()

    def _configure_columns(self):
        compact = self.width() < COMPACT_WIDTH
        model = ReportPlannerModel
        if compact and self._compact_columns is False:
            self._remember_column_widths()
        for column in (model.PARSER_COLUMN, model.CONFIDENCE_COLUMN, model.DETAIL_COLUMN):
            self.table.setColumnHidden(column, compact)
        # Metadata stays visible in compact mode; the table scrolls horizontally.
        for name in REVIEW_FIELDS:
            self.table.setColumnHidden(model.column_for_field(name), name not in self._visible_fields)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            model.DETAIL_COLUMN,
            QHeaderView.ResizeMode.Interactive if compact else QHeaderView.ResizeMode.Stretch,
        )
        self._compact_columns = compact

    def _remember_column_widths(self):
        if not self.model.rowCount():
            return
        header = self.table.horizontalHeader()
        for column in range(self.model.columnCount()):
            if (not self.table.isColumnHidden(column)
                    and header.sectionResizeMode(column) == QHeaderView.ResizeMode.Interactive):
                self._column_widths[column] = self.table.columnWidth(column)
