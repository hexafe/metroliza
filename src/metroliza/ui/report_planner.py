"""Reusable report review surface; execution stays with its owning host."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QHeaderView, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy, QTableView, QVBoxLayout, QWidget,
)

from metroliza.parsing.preflight import ParsePreflightStatus
from metroliza.ui.report_planner_model import ReportPlannerFilterModel, ReportPlannerModel


class _ReportTable(QTableView):
    """Space operates the row checkbox even when a text column has focus."""

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.currentIndex().isValid():
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
        super().keyPressEvent(event)


class ReportPlanner(QWidget):
    """One source model owns the selection, independently of visible filters."""

    selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = ReportPlannerModel(self)
        self.proxy = ReportPlannerFilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search report names or locations")
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
        self.table.setAccessibleName("Reviewed reports and import selection")
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setTabKeyNavigation(False)
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
        self.table.setColumnWidth(0, 38)
        self.table.setColumnWidth(1, 205)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 210)
        self.details_button = QPushButton("Report details")
        self.details_button.setCheckable(True)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Reviewed report details")
        self.details.setMaximumHeight(110)
        self.details.hide()
        self.details_button.toggled.connect(self.details.setVisible)
        self.table.selectionModel().currentRowChanged.connect(self._show_details)
        self.outcome = QPlainTextEdit()
        self.outcome.setReadOnly(True)
        self.outcome.setAccessibleName("Last report import outcome")
        self.outcome.setMaximumHeight(110)
        self.outcome.hide()
        self.outcome_button = QPushButton("Last import outcome")
        self.outcome_button.setCheckable(True)
        self.outcome_button.hide()
        self.outcome_button.toggled.connect(self.outcome.setVisible)
        self.details_button.toggled.connect(
            lambda checked: self.outcome_button.setChecked(False) if checked else None
        )
        self.outcome_button.toggled.connect(
            lambda checked: self.details_button.setChecked(False) if checked else None
        )
        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.search, 0, 0, 1, 2)
        controls.addWidget(self.status_filter, 0, 2, 1, 2)
        controls.addWidget(self.parser_filter, 1, 0, 1, 2)
        controls.addWidget(self.attention_filter, 1, 2, 1, 2)
        controls.addWidget(self.select_ready, 2, 0)
        controls.addWidget(self.clear, 2, 1)
        controls.addWidget(self.details_button, 2, 2)
        controls.addWidget(self.outcome_button, 2, 3)
        controls.setColumnStretch(0, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(controls)
        layout.addWidget(self.counts)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.details)
        layout.addWidget(self.outcome)
        self.model.selection_changed.connect(self._selection_updated)
        self.proxy.rowsInserted.connect(self._update_counts)
        self.proxy.rowsRemoved.connect(self._update_counts)
        self.proxy.modelReset.connect(self._update_counts)
        self._update_counts()

    def set_review(self, result):
        self.model.set_review(result)
        self.parser_filter.clear()
        self.parser_filter.addItem("All parsers", "")
        for parser in self.model.parser_ids:
            self.parser_filter.addItem(parser, parser)
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        self.attention_filter.setChecked(False)
        if self.proxy.rowCount():
            self.table.setCurrentIndex(self.proxy.index(0, 1))
        self._update_counts()

    def invalidate(self):
        self.model.invalidate()
        self.details.clear()
        self._update_counts()

    def set_busy(self, busy):
        for control in (self.table, self.select_ready, self.clear):
            control.setEnabled(not busy)

    def show_outcome(self, text):
        self.outcome.setPlainText(text)
        self.outcome_button.show()
        self.outcome_button.setChecked(True)

    def _selection_updated(self):
        self._update_counts()
        self.selection_changed.emit()

    def _update_counts(self, *_args):
        counts = self.model.counts
        text = (
            f"{counts['selected']} selected overall · {self.proxy.rowCount()} visible / "
            f"{counts['total']} reviewed · {counts['ready']} ready · "
            f"{counts['excluded']} excluded · {counts['attention']} need attention"
        )
        self.counts.setText(text)
        self.counts.setAccessibleDescription(text)

    def _show_details(self, current, _previous=None):
        # The model is the sole sanitizer and never renders raw parser exceptions.
        index = self.proxy.mapToSource(current)
        self.details.setPlainText(
            self.model.details_text(index.row()) if index.isValid() else ""
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 850
        for column in (3, 4, 5):
            self.table.setColumnHidden(column, compact)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch if compact else QHeaderView.ResizeMode.Interactive
        )
