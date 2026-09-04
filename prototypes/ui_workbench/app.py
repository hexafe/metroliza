"""Run with Python and the repository's existing PyQt6 environment."""

import argparse
import sys
from collections import Counter
from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from models import ReportsModel, ReportsProxy
from state import Destination, Outcome, SCENARIOS, Session
from theme import apply_theme


def label(text, kind=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if kind:
        widget.setObjectName(kind)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text, slot, *, primary=False):
    widget = QPushButton(text)
    widget.setProperty("primary", primary)
    widget.setAccessibleName(text.replace("&", ""))
    widget.clicked.connect(slot)
    return widget


def panel():
    widget = QFrame()
    widget.setObjectName("surface")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    return widget, layout


class ScopeDialog(QDialog):
    def __init__(self, session, hidden, parent):
        super().__init__(parent)
        self.session = session
        self.plan = session.make_plan()
        self.setWindowTitle("Confirm simulated scope")
        self.setMinimumWidth(510)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Confirm selected scope", "section"))
        layout.addWidget(
            label(
                f"SIMULATION ONLY · {len(self.plan.reports)} selected · {hidden} hidden by filters"
            )
        )
        layout.addWidget(
            label(
                f"Source: {self.plan.context.source}\nDestination: {self.plan.context.destination}\n"
                f"Review #{self.plan.review_version} · {self.plan.context.metadata}"
            )
        )
        counts = Counter(r.destination for r in self.plan.reports)
        layout.addWidget(
            label(
                f"Import new: {counts[Destination.NEW]}\n"
                f"Verify / preserve complete: {counts[Destination.COMPLETE]}\n"
                f"Known incomplete: {counts[Destination.INCOMPLETE]} · unknown completeness: {counts[Destination.UNKNOWN]}"
            )
        )
        names = QTextBrowser()
        names.setAccessibleName("Exact selected report scope")
        names.setPlainText("\n".join(f"{r.name} — {r.eligibility}" for r in self.plan.reports))
        names.setMaximumHeight(170)
        layout.addWidget(names)
        self.repair = QCheckBox("Allow repair of selected incomplete reports after verification")
        self.repair.setAccessibleName("Explicit repair permission for selected reports only")
        self.repair.setEnabled(bool(counts[Destination.INCOMPLETE] + counts[Destination.UNKNOWN]))
        layout.addWidget(self.repair)
        layout.addWidget(
            label(
                "Unchecked: matches are verified only. Incomplete reports stay unchanged and request a separate repair decision. "
                "Complete accepted reports are always preserved. Hidden unselected reports are never added.",
                "muted",
            )
        )
        self.ack = QCheckBox("I approve this exact selected scope and simulated destination")
        layout.addWidget(self.ack)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.run = buttons.addButton("Start simulation", QDialogButtonBox.ButtonRole.AcceptRole)
        self.run.setProperty("primary", True)
        self.run.setEnabled(False)
        self.ack.toggled.connect(self.run.setEnabled)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.confirm)
        layout.addWidget(buttons)
        self.ack.setFocus()

    def confirm(self):
        if self.ack.isChecked():
            # Compare the originally displayed snapshot, never silently refresh it.
            from dataclasses import replace

            self.plan = replace(self.plan, allow_repair=self.repair.isChecked())
            self.accept()


class Workbench(QMainWindow):
    destinations = ("Comparison lab · simulated", "Validation archive · simulated")

    def __init__(self, session=None, *, theme="dark"):
        super().__init__()
        self.session = session or Session(self)
        if self.session.parent() is None:
            self.session.setParent(self)
        self.theme = theme
        self.current_identity = None
        self.setWindowTitle("Metroliza · Native workbench · SYNTHETIC ONLY")
        self.resize(1280, 800)
        self.setMinimumSize(850, 600)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(188)
        nav_layout = QVBoxLayout(self.sidebar)
        nav_layout.setContentsMargins(14, 24, 14, 16)
        nav_layout.addWidget(label("metroliza", "section"))
        nav_layout.addWidget(label("ENGINEERING WORKSPACE", "muted"))
        nav_layout.addSpacing(22)
        self.nav = QListWidget()
        self.nav.setAccessibleName("Workspace navigation")
        self.nav.setWordWrap(True)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        items = (
            "Overview",
            "Reports",
            "Tabular analysis",
            "Industrial data",
            "Realtime monitor",
            "Parser profiles",
            "Task details",
        )
        icons = (
            QStyle.StandardPixmap.SP_ComputerIcon,
            QStyle.StandardPixmap.SP_FileIcon,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            QStyle.StandardPixmap.SP_DriveHDIcon,
            QStyle.StandardPixmap.SP_MediaPlay,
            QStyle.StandardPixmap.SP_FileDialogContentsView,
            QStyle.StandardPixmap.SP_DialogApplyButton,
        )
        for text, icon in zip(items, icons, strict=True):
            self.nav.addItem(text)
            self.nav.item(self.nav.count() - 1).setIcon(self.style().standardIcon(icon))
        nav_layout.addWidget(self.nav, 1)
        nav_layout.addWidget(
            label("LOCAL SIMULATION\nNo report file access\nNo database or network", "muted")
        )
        outer.addWidget(self.sidebar)
        main = QVBoxLayout()
        main.setContentsMargins(20, 16, 20, 12)
        main.setSpacing(12)
        outer.addLayout(main, 1)
        bar = QHBoxLayout()
        self.breadcrumb = label("Validation lab  /  Native workbench", "muted")
        bar.addWidget(self.breadcrumb, 1)
        bar.addWidget(label("SYNTHETIC PROTOTYPE", "muted"))
        self.theme_button = button("Light theme", self.toggle_theme)
        bar.addWidget(self.theme_button)
        main.addLayout(bar)
        context, ctx = panel()
        ctx.setContentsMargins(12, 10, 12, 10)
        context_row = QHBoxLayout()
        self.workspace = QComboBox()
        self.workspace.addItems(("Validation lab", "Training workspace"))
        self.source = QComboBox()
        self.source.addItems(SCENARIOS)
        self.destination = QComboBox()
        self.destination.addItems(self.destinations)
        self.metadata = QComboBox()
        self.metadata.addItems(("Fast · no OCR", "Detailed · simulated"))
        for title, widget in (
            ("&Workspace", self.workspace),
            ("&Source · fixture", self.source),
            ("&Destination · simulated", self.destination),
            ("&Metadata", self.metadata),
        ):
            col = QVBoxLayout()
            caption = label(title, "muted")
            caption.setBuddy(widget)
            widget.setAccessibleName(title.replace("&", ""))
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            col.addWidget(caption)
            col.addWidget(widget)
            context_row.addLayout(col, 1 if widget is self.workspace else 2)
        ctx.addLayout(context_row)
        main.addWidget(context)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_overview())
        self.pages.addWidget(self.build_reports())
        domains = (
            (
                "Tabular analysis",
                "CSV / Excel · filter, group and analyse",
                "Existing tabular services and row-store contracts remain available in the application. "
                "A workspace adapter for source scope, units, table and chart handoff is deferred. No computed statistics are shown here.",
            ),
            (
                "Industrial data",
                "Sources · cache · synchronization",
                "Existing industrial workflows retain their own connection and cache lifecycle. "
                "Credentials, queries, synchronization and production sources are disabled in this prototype.",
            ),
            (
                "Realtime monitor",
                "Session · replay · monitoring",
                "Existing realtime services need explicit session ownership, retention and stop/rebind coordination. "
                "This page is a navigation placeholder. No live connection, telemetry or polling is active.",
            ),
            (
                "Parser profiles",
                "Profiles · validation · handoff",
                "Existing declarative profiles and validation remain a separate capability. "
                "Profile editing, real parser execution and registry changes are deferred. Reports use fixed synthetic parser evidence.",
            ),
        )
        for title, subtitle, description in domains:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addWidget(label(title, "title"))
            layout.addWidget(label(subtitle, "section"))
            card, body = panel()
            body.addWidget(label("Existing domain · adapter deferred", "section"))
            body.addWidget(label(description))
            body.addWidget(
                label("This prototype demonstrates navigation and shared context only.", "muted")
            )
            layout.addWidget(card)
            layout.addStretch()
            self.pages.addWidget(page)
        self.pages.addWidget(self.build_tasks())
        main.addWidget(self.pages, 1)
        self.banner = label("", "muted")
        self.banner.setAccessibleName("Workflow status")
        main.addWidget(self.banner)
        task_bar = QHBoxLayout()
        self.task_status = label("No active task")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(190)
        self.progress.setAccessibleName("Persistent simulated task progress")
        self.progress.setFormat("%v / %m processed")
        self.cancel_button = button("&Cancel task", self.session.cancel)
        self.details_button = button("Task details →", lambda: self.navigate(6))
        task_bar.addWidget(self.task_status, 1)
        task_bar.addWidget(self.progress)
        task_bar.addWidget(self.cancel_button)
        task_bar.addWidget(self.details_button)
        main.addLayout(task_bar)
        self.workspace.currentTextChanged.connect(
            lambda value: self.context_changed(workspace=value)
        )
        self.source.currentTextChanged.connect(lambda value: self.context_changed(source=value))
        self.destination.currentTextChanged.connect(
            lambda value: self.context_changed(destination=value)
        )
        self.metadata.currentTextChanged.connect(lambda value: self.context_changed(metadata=value))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.session.changed.connect(self.sync)
        self.session.rows_changed.connect(self.restore_current)
        self.nav.setCurrentRow(0)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.navigate(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.navigate(1))
        QShortcut(QKeySequence("Ctrl+J"), self, activated=lambda: self.navigate(6))
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        self.sync()
        self.set_theme(theme)

    def build_overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(label("Overview", "title"))
        layout.addWidget(label("Your active context, current work and next decision.", "muted"))
        card, body = panel()
        body.addWidget(label("Continue your workspace", "section"))
        self.overview_context = label("")
        body.addWidget(self.overview_context)
        self.overview_next = button("Review reports →", self.next_action, primary=True)
        body.addWidget(self.overview_next, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)
        attention, body = panel()
        body.addWidget(label("Attention & activity", "section"))
        self.attention = label("")
        body.addWidget(self.attention)
        layout.addWidget(attention)
        layout.addWidget(
            label(
                "Reports owns review, scope and import outcomes. Other domains keep their own primary destinations. "
                "All operations in this workspace are deterministic simulations.",
                "muted",
            )
        )
        layout.addStretch()
        return page

    def build_reports(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(label("Reports", "title"), 1)
        self.review_button = button("&Review reports", self.session.review)
        top.addWidget(self.review_button)
        layout.addLayout(top)
        self.review_status = label(
            "Review the source. Choose the scope. Import only what you approve.", "muted"
        )
        layout.addWidget(self.review_status)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search report or folder…   Ctrl+F")
        self.search.setAccessibleName("Search reports or folders")
        self.status_filter = QComboBox()
        self.status_filter.addItems(
            ("All reports", "New reports", "Destination matches", "Needs attention", "Selected")
        )
        self.status_filter.setAccessibleName("Report status filter")
        self.parser_filter = QComboBox()
        self.parser_filter.addItems(("All parsers", "CMM PDF", "CSV profile"))
        self.parser_filter.setAccessibleName("Parser filter")
        filters.addWidget(self.search, 1)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.parser_filter)
        layout.addLayout(filters)
        self.model = ReportsModel(self.session)
        self.proxy = ReportsProxy(self.model)
        self.table = QTableView()
        self.table.setAccessibleName(
            "Synthetic reports. Space toggles the current report selection."
        )
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTabKeyNavigation(False)
        self.table.setToolTip(
            "Arrow keys move between rows. Space selects the current report. Tab leaves the table."
        )
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, width in enumerate((52, 230, 115, 150, 180, 100, 90, 140)):
            self.table.setColumnWidth(i, width)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.selectionModel().currentChanged.connect(self.inspect_current)
        QShortcut(
            QKeySequence("Space"),
            self.table,
            activated=self.toggle_current,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)
        detail, body = panel()
        detail.setMinimumWidth(215)
        body.addWidget(label("Decision & evidence", "section"))
        self.evidence = QTextBrowser()
        self.evidence.setAccessibleName("Report decision and evidence")
        self.evidence.setOpenExternalLinks(False)
        body.addWidget(self.evidence, 1)
        self.drift_button = button("Simulate source change", self.change_current)
        body.addWidget(self.drift_button)
        self.splitter.addWidget(detail)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([760, 270])
        layout.addWidget(self.splitter, 1)
        selection = QHBoxLayout()
        self.selection_label = label("")
        selection.addWidget(self.selection_label, 1)
        self.select_button = button("Select visible eligible", self.select_visible)
        self.clear_button = button("Clear selection", self.session.clear_selection)
        selection.addWidget(self.select_button)
        selection.addWidget(self.clear_button)
        layout.addLayout(selection)
        footer = QHBoxLayout()
        footer.addWidget(
            label(
                "Matches can be verified independently.\nRepair requires explicit scope approval; complete reports stay unchanged.",
                "muted",
            ),
            1,
        )
        self.import_button = button("Confirm 0 selected…", self.confirm_scope, primary=True)
        footer.addWidget(self.import_button)
        layout.addLayout(footer)
        self.search.textChanged.connect(self.filter_changed)
        self.status_filter.currentTextChanged.connect(self.filter_changed)
        self.parser_filter.currentTextChanged.connect(self.filter_changed)
        return page

    def build_tasks(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Task details", "title"))
        layout.addWidget(
            label("Persistent evidence · navigation never starts or duplicates work", "muted")
        )
        self.task_evidence = QTextBrowser()
        self.task_evidence.setAccessibleName(
            "Import outcomes, review snapshot and changed-since-review evidence"
        )
        layout.addWidget(self.task_evidence, 1)
        return page

    def navigate(self, index):
        self.nav.setCurrentRow(index)
        if index == 1:
            self.search.setFocus()
        elif index == 0:
            self.overview_next.setFocus()
        else:
            self.pages.currentWidget().setFocus()

    def focus_search(self):
        self.navigate(1)
        self.search.setFocus()

    def context_changed(self, **fields):
        self.session.change_context(**fields)
        self.current_identity = None
        self.filter_changed()

    def filter_changed(self, *_args):
        identity = self.current_identity
        self.proxy.configure(
            self.search.text(), self.status_filter.currentText(), self.parser_filter.currentText()
        )
        self.current_identity = identity
        self.restore_current()
        self.sync()

    def restore_current(self):
        found = False
        for i in range(self.proxy.rowCount()):
            if self.proxy.index(i, 0).data(Qt.ItemDataRole.UserRole) == self.current_identity:
                self.table.setCurrentIndex(self.proxy.index(i, 1))
                found = True
                break
        if not found:
            if self.proxy.rowCount():
                index = self.proxy.index(0, 1)
                self.current_identity = index.data(Qt.ItemDataRole.UserRole)
                self.table.setCurrentIndex(index)
            else:
                self.current_identity = None
        self.update_evidence()

    def inspect_current(self, current, _previous):
        if current.isValid():
            self.current_identity = current.data(Qt.ItemDataRole.UserRole)
        self.update_evidence()

    def update_evidence(self):
        row = next((r for r in self.session.reports if r.identity == self.current_identity), None)
        self.drift_button.setEnabled(bool(row) and not self.session.busy)
        if not row:
            self.evidence.setPlainText(
                "Choose a row to inspect its recognition, destination, eligibility and source evidence.\n\nAll values are synthetic. No report preview is loaded."
            )
            return
        outcome = (
            self.session.results.get(row.identity)
            if self.session.plan
            and self.session.plan.context == self.session.context
            and self.session.plan.review_version == self.session.review_version
            else None
        )
        self.evidence.setHtml(
            f"<h3>{escape(row.name)}</h3><p>{escape(row.folder)}</p>"
            f"<p><b>Recognition</b><br>{row.recognition.value} · {row.confidence}% demo score</p>"
            f"<p><b>Destination completeness</b><br>{row.destination.value}<br>Fixture-only classification</p>"
            f"<p><b>Eligibility</b><br>{'Rejected · refresh review' if outcome == Outcome.CHANGED else row.eligibility}</p><p><b>Selection</b><br>"
            f"{'Selected explicitly' if row.identity in self.session.selected else 'Not selected'}</p>"
            f"<p><b>Execution outcome</b><br>{outcome.value if outcome else 'Not executed'}</p>"
            f"<p><b>Reviewed evidence · synthetic</b><br>{row.parser}<br>{row.fingerprint}<br>Parser generation: demo-1</p>"
            f"<p>Source-copy exclusion: {'yes' if row.same_source else 'no'}<br>"
            f"Changed since review: {'yes' if row.stale or outcome == Outcome.CHANGED else 'no'}<br>"
            f"Simulated failure fixture: {'yes' if row.fail else 'no'}</p>"
        )

    def toggle_current(self):
        index = self.table.currentIndex()
        if index.isValid():
            identity = index.data(Qt.ItemDataRole.UserRole)
            self.session.select(identity, identity not in self.session.selected)

    def change_current(self):
        if self.current_identity and not self.session.busy:
            self.session.simulate_drift(self.current_identity)

    def select_visible(self):
        self.session.select_visible(self.proxy.visible_ids())

    def confirm_scope(self):
        hidden = len(self.session.selected - self.proxy.visible_ids())
        dialog = ScopeDialog(self.session, hidden, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.session.start(dialog.plan)
            except ValueError as exc:
                self.session.message = str(exc)
                self.sync()
        self.import_button.setFocus()

    def next_action(self):
        if self.session.busy or self.current_task_matches_review():
            self.navigate(6)
        else:
            self.navigate(1)

    def current_task_matches_review(self):
        s = self.session
        return bool(
            s.review_current
            and s.plan
            and s.plan.context == s.context
            and s.plan.review_version == s.review_version
        )

    def task_title(self):
        s = self.session
        if s.running:
            return "Running"
        if Outcome.CANCELLED in s.results.values():
            return "Cancelled"
        if any(
            value in (Outcome.FAILED, Outcome.CHANGED, Outcome.REPAIR_NEEDED)
            for value in s.results.values()
        ):
            return "Completed · attention needed"
        return "Completed"

    def sync(self):
        s = self.session
        if self.proxy.status == "Selected":
            self.proxy.invalidateFilter()
        for widget in (
            self.source,
            self.destination,
            self.metadata,
            self.workspace,
            self.review_button,
        ):
            widget.setEnabled(not s.busy)
        self.select_button.setEnabled(s.review_current and not s.busy)
        self.clear_button.setEnabled(bool(s.selected) and not s.busy)
        self.import_button.setEnabled(s.review_current and bool(s.selected) and not s.busy)
        self.import_button.setText(f"Confirm {len(s.selected)} selected…")
        self.cancel_button.setEnabled(s.busy)
        self.drift_button.setEnabled(not s.busy and bool(self.current_identity))
        visible = self.proxy.visible_ids()
        self.selection_label.setText(
            f"{len(visible):,} shown / {len(s.reports):,} · {len(s.selected):,} selected\n"
            f"{len(s.selected - visible):,} selected hidden by filters"
        )
        self.review_status.setText(
            f"Review #{s.review_version} · {'current' if s.review_current else 'approval needed'} · "
            "all operations simulated"
        )
        self.banner.setText(s.message)
        self.breadcrumb.setText(f"{s.context.workspace}  /  Native workbench")
        self.overview_context.setText(
            f"{s.context.workspace}\n{s.context.source} → {s.context.destination}\n"
            f"{len(s.reports):,} synthetic reports · {len(s.selected):,} selected"
        )
        self.attention.setText(
            s.message
            + f"\n{sum(not r.selectable for r in s.reports)} source records need attention or are excluded."
        )
        self.overview_next.setText(
            "View active task →"
            if s.busy
            else "Review task outcome →"
            if self.current_task_matches_review()
            else "Continue selection →"
            if s.review_current
            else "Review reports →"
        )
        self.progress.setRange(0, len(s.plan.reports) if s.plan else 1)
        processed = sum(value != Outcome.CANCELLED for value in s.results.values())
        self.progress.setValue(processed)
        self.task_status.setText(
            "Reviewing · simulated"
            if s.reviewing
            else f"{self.task_title()} · {processed} / {len(s.plan.reports)} processed"
            if s.plan
            else "No active task · simulation only"
        )
        self.update_evidence()
        self.update_tasks()

    def update_tasks(self):
        s = self.session
        if not s.plan:
            self.task_evidence.setPlainText(
                "No import task yet. Review reports, choose a subset and confirm its exact scope.\n\n"
                "Review and import are simulated; no database is accessed."
            )
            return
        counts = Counter(s.results.values())
        outcomes = " · ".join(
            f"{outcome.value}: {counts[outcome]}"
            for outcome in Outcome
            if outcome != Outcome.CHANGED
        )
        report_rows = "".join(
            f"<tr><td>{escape(r.name)}</td><td>{s.results[r.identity].value if r.identity in s.results else 'Pending'}</td></tr>"
            for r in s.plan.reports[:500]
        )
        self.task_evidence.setHtml(
            f"<h3>SIMULATED TASK · {self.task_title()}</h3>"
            f"<p><b>Frozen scope:</b> {len(s.plan.reports)} reports · {escape(s.plan.context.source)} → "
            f"{escape(s.plan.context.destination)}<br>Review #{s.plan.review_version} · "
            f"Repair permission: {'explicitly granted' if s.plan.allow_repair else 'not granted'}</p>"
            f"<h3>Import outcomes</h3><p>{outcomes}</p>"
            f"<h3>Review snapshot · historical evidence</h3><p>{s.plan.review_discovered} discovered · "
            f"{s.plan.review_matches} matched the destination during review. These overlap execution outcomes.</p>"
            f"<h3>Changed since review · separate evidence</h3><p>{counts[Outcome.CHANGED]} selected reports rejected. "
            "A changed report is never also counted as cancelled.</p>"
            f"<h3>Per-report ledger</h3><table cellspacing='8'>{report_rows}</table>"
            f"<p>{'First 500 rows shown; all results retained in memory.' if len(s.plan.reports) > 500 else ''}</p>"
            f"<p>{len(s.history)} earlier simulated tasks retained for this session. "
            "Session state is in memory; closing the prototype resets it.</p>"
        )

    def set_theme(self, mode):
        self.theme = mode
        apply_theme(QApplication.instance(), mode)
        self.theme_button.setText("Light theme" if mode == "dark" else "Dark theme")
        self.update_columns()

    def toggle_theme(self):
        self.set_theme("light" if self.theme == "dark" else "dark")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_columns()

    def update_columns(self):
        compact = self.width() < 1150
        self.sidebar.setFixedWidth(188)
        for column in (2, 5, 6, 7):
            self.table.setColumnHidden(column, self.width() < 1500)
        self.table.setColumnHidden(4, compact)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column, width in enumerate((50, 230, 105, 148, 172, 96, 100, 122)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def closeEvent(self, event):
        if self.session.busy:
            self.session.message = (
                "A simulated task is active. Cancel it or wait before closing this workspace."
            )
            self.sync()
            event.ignore()
        else:
            event.accept()


def install_safety_guard():
    """Fail closed if an accidental Python network/DB call is introduced."""

    def guard(event, _args):
        if event.startswith(("socket.", "sqlite3.connect")):
            raise RuntimeError(f"Synthetic prototype forbids {event}")

    sys.addaudithook(guard)


def main():
    parser = argparse.ArgumentParser(
        description="Synthetic native Metroliza workbench; no backend access"
    )
    parser.add_argument("--theme", choices=("light", "dark"), default="dark")
    args = parser.parse_args()
    install_safety_guard()
    app = QApplication(sys.argv[:1])
    window = Workbench(theme=args.theme)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
