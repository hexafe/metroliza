"""Manual report-to-production row linking for cached industrial data."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from time import monotonic
from typing import Any

from PyQt6.QtCore import QSignalBlocker, QThread, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from metroliza.reports.db import (
    selected_reports_worker_options,
    sqlite_connection_scope,
    sqlite_report_schema_connection_scope,
    sqlite_selected_reports_connection_scope,
)
from metroliza.industrial.industrial_join_service import (
    clear_manual_industrial_report_link,
    materialize_industrial_report_links,
    set_manual_industrial_report_link,
)
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.ui import detached_threads
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.worker_progress_dialog import (
    create_delayed_worker_progress_dialog,
    dismiss_worker_progress_dialog,
)
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_table,
    configure_window_size,
    section_label,
    set_status_variant,
    status_chip,
)


_DEFAULT_MATERIALIZE_LINKS = materialize_industrial_report_links


class _AutoLinkThread(QThread):
    """Own the unchanged service call and its literal error until native finish."""

    def __init__(self, db_file: str, *, connection_scope=nullcontext):
        super().__init__()
        self.db_file = db_file
        self._connection_scope = connection_scope
        self.summary = None
        self.error = None
        self.discard_result = False

    def run(self):
        try:
            with self._connection_scope() as connection:
                options = {"connection": connection} if connection is not None else {}
                self.summary = _DEFAULT_MATERIALIZE_LINKS(self.db_file, **options)
        except Exception as exc:
            self.error = str(exc)


REPORT_COLUMNS = (
    ("report_id", "Report ID"),
    ("reference", "Metroliza reference"),
    ("part_name", "Part"),
    ("revision", "Revision"),
    ("report_date", "Report date"),
    ("sample_number", "Sample"),
    ("file_name", "Report file"),
    ("linked_summary", "Current production link"),
)

PRODUCTION_COLUMNS = (
    ("industrial_record_id", "Record ID"),
    ("source_profile", "Source"),
    ("source_record_key", "Production key"),
    ("reference", "Production reference"),
    ("part_number", "Part number"),
    ("serial", "Serial"),
    ("station", "Station"),
    ("line", "Line"),
    ("process_timestamp", "Process time"),
)


def _search_pattern(search_text: str) -> str:
    return f"%{str(search_text or '').strip()}%"


def list_reports_for_manual_linking(db_file: str, *, search_text: str = "", connection=None) -> list[dict[str, Any]]:
    """Return Metroliza reports with their current accepted production link summary."""

    search = str(search_text or "").strip()
    scope = nullcontext(connection) if connection is not None else sqlite_report_schema_connection_scope(db_file)
    with scope as conn:
        ensure_report_schema(db_file, connection=conn)
        rows = conn.execute(
            """
            SELECT
                report.report_id AS report_id,
                COALESCE(report.reference, '') AS reference,
                COALESCE(report.part_name, '') AS part_name,
                COALESCE(report.revision, '') AS revision,
                COALESCE(report.report_date, '') AS report_date,
                COALESCE(report.sample_number, '') AS sample_number,
                COALESCE(report.file_name, '') AS file_name,
                COALESCE(isp.profile_name, '') AS source_profile,
                COALESCE(ir.source_record_key, '') AS source_record_key,
                COALESCE(ir.reference, '') AS production_reference,
                COALESCE(ir.station, '') AS station,
                COALESCE(ijr.rule_name, '') AS link_rule
            FROM vw_report_overview report
            LEFT JOIN industrial_link_candidates ilc ON ilc.id = (
                SELECT selected_candidate.id
                FROM industrial_link_candidates selected_candidate
                LEFT JOIN industrial_join_rules selected_rule
                    ON selected_rule.id = selected_candidate.join_rule_id
                WHERE selected_candidate.report_id = report.report_id
                  AND selected_candidate.measurement_id IS NULL
                  AND selected_candidate.status = 'accepted'
                ORDER BY
                    COALESCE(selected_rule.priority, 100),
                    selected_candidate.confidence DESC,
                    selected_candidate.id
                LIMIT 1
            )
            LEFT JOIN industrial_records ir ON ir.id = ilc.industrial_record_id
            LEFT JOIN industrial_source_profiles isp ON isp.id = ir.source_profile_id
            LEFT JOIN industrial_join_rules ijr ON ijr.id = ilc.join_rule_id
            WHERE :search = ''
               OR instr(lower(report.reference), lower(:search)) > 0
               OR instr(lower(report.part_name), lower(:search)) > 0
               OR instr(lower(report.revision), lower(:search)) > 0
               OR instr(lower(report.sample_number), lower(:search)) > 0
               OR instr(lower(report.file_name), lower(:search)) > 0
            ORDER BY report.reference COLLATE NOCASE, report.report_id
            LIMIT 500
            """,
            {"search": search},
        ).fetchall()
    reports: list[dict[str, Any]] = []
    for row in rows:
        link_parts = [str(item).strip() for item in row[7:12] if str(item or "").strip()]
        reports.append(
            {
                "report_id": int(row[0]),
                "reference": row[1],
                "part_name": row[2],
                "revision": row[3],
                "report_date": row[4],
                "sample_number": row[5],
                "file_name": row[6],
                "linked_summary": " | ".join(link_parts) if link_parts else "",
            }
        )
    return reports


def list_production_records_for_manual_linking(
    db_file: str,
    *,
    search_text: str = "",
    connection=None,
) -> list[dict[str, Any]]:
    """Return cached production rows available for manual linking."""

    pattern = _search_pattern(search_text)
    where_clause = ""
    params: tuple[Any, ...] = ()
    if str(search_text or "").strip():
        where_clause = """
            WHERE COALESCE(ir.source_record_key, '') LIKE ?
               OR COALESCE(ir.reference, '') LIKE ?
               OR COALESCE(ir.part_number, '') LIKE ?
               OR COALESCE(ir.part_name, '') LIKE ?
               OR COALESCE(ir.serial, '') LIKE ?
               OR COALESCE(ir.batch_lot, '') LIKE ?
               OR COALESCE(ir.work_order, '') LIKE ?
               OR COALESCE(ir.station, '') LIKE ?
               OR COALESCE(ir.line, '') LIKE ?
               OR COALESCE(isp.profile_name, '') LIKE ?
        """
        params = (pattern,) * 10
    scope = nullcontext(connection) if connection is not None else sqlite_connection_scope(db_file)
    with scope as conn:
        rows = conn.execute(
            f"""
            SELECT
                ir.id,
                COALESCE(isp.profile_name, ''),
                COALESCE(ir.source_record_key, ''),
                COALESCE(ir.reference, ''),
                COALESCE(ir.part_number, ''),
                COALESCE(ir.serial, ''),
                COALESCE(ir.station, ''),
                COALESCE(ir.line, ''),
                COALESCE(ir.process_timestamp, '')
            FROM industrial_records ir
            LEFT JOIN industrial_source_profiles isp ON isp.id = ir.source_profile_id
            {where_clause}
            ORDER BY ir.process_timestamp DESC, ir.id DESC
            LIMIT 500
            """,
            params,
        ).fetchall()
    return [
        {
            "industrial_record_id": int(row[0]),
            "source_profile": row[1],
            "source_record_key": row[2],
            "reference": row[3],
            "part_number": row[4],
            "serial": row[5],
            "station": row[6],
            "line": row[7],
            "process_timestamp": row[8],
        }
        for row in rows
    ]


class IndustrialLinkingDialog(QDialog):
    """Let users manually link cached production rows to Metroliza reports."""

    def __init__(self, parent=None, *, db_file: str | None = None, source_binding=None):
        super().__init__(parent)
        self.db_file = db_file
        self._source_binding = source_binding
        self._loaded_searches = None
        if type(self) is IndustrialLinkingDialog:
            self._auto_link_thread = None
            self._auto_link_progress = None
        self.setWindowTitle("Production links")
        configure_window_size(self, minimum=(760, 520), initial=(980, 680))

        self.status_label = status_chip("Select one report and one cached production row.", "neutral")
        self.report_search_edit = QLineEdit()
        self.report_search_edit.setPlaceholderText("Search Metroliza reports")
        self.production_search_edit = QLineEdit()
        self.production_search_edit.setPlaceholderText("Search cached production rows")

        self.report_table = QTableWidget(0, len(REPORT_COLUMNS))
        self.production_table = QTableWidget(0, len(PRODUCTION_COLUMNS))
        self.report_table.setHorizontalHeaderLabels([label for _, label in REPORT_COLUMNS])
        self.production_table.setHorizontalHeaderLabels([label for _, label in PRODUCTION_COLUMNS])
        self._configure_selection_table(self.report_table)
        self._configure_selection_table(self.production_table)
        self.report_table.setColumnHidden(0, True)
        self.production_table.setColumnHidden(0, True)

        self.refresh_button = QPushButton("Refresh")
        self.auto_link_button = QPushButton("Refresh auto links")
        self.link_button = QPushButton("Link selected")
        self.clear_button = QPushButton("Clear manual link")
        self.close_button = QPushButton("Close")

        self.report_search_edit.textChanged.connect(self.reload_data)
        self.production_search_edit.textChanged.connect(self.reload_data)
        self.report_table.itemSelectionChanged.connect(self._sync_button_state)
        self.production_table.itemSelectionChanged.connect(self._sync_button_state)
        self.refresh_button.clicked.connect(self.reload_data)
        self.auto_link_button.clicked.connect(self.refresh_auto_links)
        self.link_button.clicked.connect(self.link_selected_records)
        self.clear_button.clicked.connect(self.clear_selected_manual_link)
        self.close_button.clicked.connect(self.accept)

        self._build_layout()
        self.reload_data()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("Industrial Data manual", "industrial_data")])
        layout.addWidget(section_label("Manual report-to-production links"))
        layout.addWidget(self.status_label)

        search_layout = QGridLayout()
        search_layout.setHorizontalSpacing(8)
        search_layout.addWidget(section_label("Metroliza reports"), 0, 0)
        search_layout.addWidget(self.report_search_edit, 0, 1)
        search_layout.addWidget(section_label("Cached production rows"), 0, 2)
        search_layout.addWidget(self.production_search_edit, 0, 3)
        search_layout.setColumnStretch(1, 1)
        search_layout.setColumnStretch(3, 1)
        layout.addLayout(search_layout)

        tables = QGridLayout()
        tables.setHorizontalSpacing(10)
        tables.addWidget(self.report_table, 0, 0)
        tables.addWidget(self.production_table, 0, 1)
        tables.setColumnStretch(0, 1)
        tables.setColumnStretch(1, 1)
        layout.addLayout(tables, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.auto_link_button)
        actions.addStretch(1)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.close_button)
        actions.addWidget(self.link_button)
        layout.addLayout(actions)

    @staticmethod
    def _configure_selection_table(table: QTableWidget) -> None:
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        configure_table(table, stretch_column=1, resize_to_contents=(0,))

    @contextmanager
    def _database_options(self):
        with sqlite_selected_reports_connection_scope(self.db_file, getattr(self, "_source_binding", None)) as connection:
            yield {"connection": connection} if connection is not None else {}

    def reload_data(self) -> None:
        if type(self) is IndustrialLinkingDialog and self._auto_link_thread is not None:
            return
        searches = self.report_search_edit.text(), self.production_search_edit.text()
        previous = self._loaded_searches
        self._loaded_searches = None
        if not self.db_file:
            self._invalidate_rows("Select a Metroliza report database before linking.", "warning")
            return
        try:
            with self._database_options() as options:
                reports = list_reports_for_manual_linking(self.db_file, search_text=searches[0], **options)
                production_rows = list_production_records_for_manual_linking(
                    self.db_file, search_text=searches[1], **options,
                )
        except Exception:
            self._invalidate_rows("Could not load link data. Check the database and refresh.", "danger")
            return

        self._replace_search_rows(self.report_table, REPORT_COLUMNS, reports, previous and previous[0] == searches[0])
        self._replace_search_rows(
            self.production_table, PRODUCTION_COLUMNS, production_rows, previous and previous[1] == searches[1],
        )
        self._loaded_searches = searches
        self.status_label.setText(
            f"Loaded {len(reports)} report(s) and {len(production_rows)} cached production row(s)."
        )
        set_status_variant(self.status_label, "neutral")
        self._sync_button_state()

    def _invalidate_rows(self, message, variant):
        self.report_table.setRowCount(0)
        self.production_table.setRowCount(0)
        self.status_label.setText(message)
        set_status_variant(self.status_label, variant)
        self._sync_button_state()

    def _replace_search_rows(self, table, columns, rows, keep_selection):
        selected_id = self._selected_id(table) if keep_selection else None
        with QSignalBlocker(table):
            table.clearSelection()
            self._populate_table(table, columns, rows)
            if selected_id is not None:
                for index, row in enumerate(rows):
                    if row[columns[0][0]] == selected_id:
                        table.selectRow(index)
                        break

    @staticmethod
    def _populate_table(
        table: QTableWidget,
        columns: tuple[tuple[str, str], ...],
        rows: list[dict[str, Any]],
    ) -> None:
        table.setRowCount(len(rows))
        id_key = columns[0][0]
        for row_index, row in enumerate(rows):
            for column_index, (key, _label) in enumerate(columns):
                item = QTableWidgetItem(str(row.get(key) or ""))
                if column_index == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row[id_key]))
                table.setItem(row_index, column_index, item)

    def selected_report_id(self) -> int | None:
        return self._selected_id(self.report_table)

    def selected_production_record_id(self) -> int | None:
        return self._selected_id(self.production_table)

    @staticmethod
    def _selected_id(table: QTableWidget) -> int | None:
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not selected_rows:
            return None
        item = table.item(selected_rows[0].row(), 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _sync_button_state(self) -> None:
        has_db = bool(self.db_file) and (type(self) is not IndustrialLinkingDialog or self._auto_link_thread is None)
        has_report = self.selected_report_id() is not None
        has_production = self.selected_production_record_id() is not None
        has_current_rows = self._loaded_searches is not None
        self.link_button.setEnabled(has_db and has_current_rows and has_report and has_production)
        self.clear_button.setEnabled(has_db and has_current_rows and has_report)
        self.auto_link_button.setEnabled(has_db and (self._source_binding is None or has_current_rows))

    def link_selected_records(self) -> None:
        if type(self) is IndustrialLinkingDialog and self._auto_link_thread is not None:
            return
        report_id = self.selected_report_id()
        production_record_id = self.selected_production_record_id()
        if report_id is None or production_record_id is None:
            QMessageBox.warning(
                self,
                "Production links",
                "Select one Metroliza report and one cached production row.",
            )
            return
        try:
            with self._database_options() as options:
                set_manual_industrial_report_link(
                    str(self.db_file),
                    report_id=report_id,
                    industrial_record_id=production_record_id,
                    **options,
                )
        except Exception as exc:
            QMessageBox.warning(self, "Production links", f"Could not save manual link: {exc}")
            return
        self.reload_data()
        self.status_label.setText("Manual production link saved.")
        set_status_variant(self.status_label, "success")

    def clear_selected_manual_link(self) -> None:
        if type(self) is IndustrialLinkingDialog and self._auto_link_thread is not None:
            return
        report_id = self.selected_report_id()
        if report_id is None:
            QMessageBox.warning(self, "Production links", "Select one Metroliza report.")
            return
        try:
            with self._database_options() as options:
                removed = clear_manual_industrial_report_link(str(self.db_file), report_id=report_id, **options)
        except Exception as exc:
            QMessageBox.warning(self, "Production links", f"Could not clear manual link: {exc}")
            return
        self.reload_data()
        self.status_label.setText(
            "Manual production link cleared." if removed else "No manual production link existed."
        )
        set_status_variant(self.status_label, "success" if removed else "neutral")

    def refresh_auto_links(self) -> None:
        started_at = monotonic()
        if type(self) is IndustrialLinkingDialog and self._auto_link_thread is not None:
            return
        if not self.db_file:
            return
        if (type(self) is IndustrialLinkingDialog and type(self.db_file) is str
                and materialize_industrial_report_links is _DEFAULT_MATERIALIZE_LINKS):
            self._start_auto_links(started_at)
            return
        try:
            # Lightweight compatibility owners used by callers do not own a workspace binding.
            with IndustrialLinkingDialog._database_options(self) as options:
                summary = materialize_industrial_report_links(str(self.db_file), **options)
        except Exception as exc:
            QMessageBox.warning(self, "Production links", f"Could not refresh auto links: {exc}")
            return
        IndustrialLinkingDialog._apply_auto_link_summary(self, summary)

    def _apply_auto_link_summary(self, summary) -> None:
        self.reload_data()
        self.status_label.setText(
            "Auto links refreshed: "
            f"{summary.accepted_links} accepted, "
            f"{summary.ambiguous_reports} ambiguous, "
            f"{summary.unmatched_reports} unmatched."
        )
        set_status_variant(self.status_label, "success")

    def _start_auto_links(self, started_at) -> None:
        thread = None
        try:
            thread = _AutoLinkThread(
                self.db_file, **selected_reports_worker_options(self.db_file, self._source_binding),
            )
            self._auto_link_thread = thread
            detached_threads.register(thread, defer_quit=True, owner=self, on_finished=IndustrialLinkingDialog._auto_links_finished)
            detached_threads.run_when_finished([thread], thread.deleteLater)
            self._auto_link_progress, _, bar, _ = create_delayed_worker_progress_dialog(
                self, window_title="Production links", initial_status_text="Refreshing auto links…",
                on_cancel=lambda: None, action_started_at=started_at, cancellable=False,
            )
            bar.setRange(0, 0)
            self._sync_button_state()
            self._auto_link_progress.show()
            thread.start()
        except Exception as exc:
            if thread is None or not thread.isRunning():
                self._release_auto_links()
                if thread is not None:
                    registered = detached_threads.is_registered(thread)
                    detached_threads.discard(thread)
                    if not registered:
                        thread.deleteLater()
            else:
                thread.discard_result = True
            QMessageBox.warning(self, "Production links", f"Could not refresh auto links: {exc}")

    def _release_auto_links(self) -> None:
        self._auto_link_thread = None
        dismiss_worker_progress_dialog(self._auto_link_progress)
        self._auto_link_progress = None
        self._sync_button_state()

    def _auto_links_finished(self, thread) -> None:
        if thread is not self._auto_link_thread:
            return
        self._release_auto_links()
        if thread is None or thread.discard_result or type(self.db_file) is not str or self.db_file != thread.db_file:
            return
        if thread.error is not None:
            QMessageBox.warning(self, "Production links", f"Could not refresh auto links: {thread.error}")
        else:
            self._apply_auto_link_summary(thread.summary)

    def done(self, result) -> None:
        # A running write is durable work, not a cancellable operation. Keep the modal
        # owner in place rather than allow its caller to navigate or remove the DB.
        if type(self) is not IndustrialLinkingDialog or self._auto_link_thread is None:
            super().done(result)

    def closeEvent(self, event) -> None:
        if type(self) is IndustrialLinkingDialog and self._auto_link_thread is not None:
            event.ignore()
            return
        super().closeEvent(event)
