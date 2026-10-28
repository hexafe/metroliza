"""Parsing dialog for selecting input sources and running report ingestion."""

from metroliza.parsing import report_parser_factory

from metroliza.shared.progress_status import build_three_line_status
from metroliza.parsing.parse_reports_thread import ParseReportsThread
from metroliza.parsing.metadata_review import (
    MODE_FAST,
    MODE_OCR,
    MetadataReviewReader,
    ocr_unavailable_reason,
)
from metroliza.parsing.preflight import ImportPlan, ParsePreflightStatus
from metroliza.reports.report_metadata_review import ROW_PENDING, build_overrides
try:
    from metroliza.ui.parser_preflight_worker import ParsePreflightThread
except ImportError:  # pragma: no cover - lightweight Qt test stubs.
    ParsePreflightThread = None
from metroliza.shared.custom_logger import CustomLogger
from PyQt6.QtCore import QEvent, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)
import logging
from functools import partial
import weakref
from dataclasses import dataclass
from metroliza.shared.parse_contracts import ParseRequest, validate_parse_request
try:
    from metroliza.ui.worker_progress_dialog import (
        create_delayed_worker_progress_dialog,
        create_delayed_worker_progress_dialog as create_worker_progress_dialog,
        dismiss_worker_progress_dialog,
    )
except ImportError:  # pragma: no cover - compatibility with lightweight test stubs.
    from metroliza.ui.worker_progress_dialog import create_worker_progress_dialog as _create_worker_progress_dialog

    def create_worker_progress_dialog(parent, *, window_title, initial_status_text, on_cancel, **_kwargs):
        return _create_worker_progress_dialog(
            parent, window_title=window_title, initial_status_text=initial_status_text, on_cancel=on_cancel,
        )

    create_delayed_worker_progress_dialog = create_worker_progress_dialog

    def dismiss_worker_progress_dialog(dialog, *, rejected: bool = False) -> None:
        if dialog is None:
            return
        close_method = getattr(dialog, "reject" if rejected else "accept", None)
        if callable(close_method):
            close_method()
            return
        close = getattr(dialog, "close", None)
        if callable(close):
            close()
from metroliza.ui.metadata_review_worker import MetadataReviewThread
from metroliza.ui.report_planner import PLANNER_ACTION_STYLE, ReportPlanner
from metroliza.ui.report_planner_metadata import summarize_rows
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_dialog_button_roles,
    configure_window_size,
    path_field,
    section_label,
    secondary_label,
    set_status_variant,
    status_chip,
    update_path_field,
)
import shutil
from time import monotonic


logger = logging.getLogger(__name__)

# Worker progress and metadata readings reach the table at most this often (about 20 Hz),
# so a burst from the review pool is applied in one pass instead of one restyle per file.
_UI_UPDATE_INTERVAL_S = 0.05

_METADATA_MODE_FAST = "fast"
_METADATA_MODE_FAST_THEN_ENRICH = "fast_then_enrich"
_METADATA_MODE_COMPLETE = "complete"
_METADATA_MODE_REQUEST_FIELDS = {
    _METADATA_MODE_FAST: ("light", False),
    _METADATA_MODE_FAST_THEN_ENRICH: ("light", False),
    _METADATA_MODE_COMPLETE: ("complete", False),
}
_MISSING_RESULT_FIELD = object()
_COMPLETION_COUNT_FIELDS = (
    "total_files",
    "parsed_files",
    "failed_files",
    "skipped_files",
    "preflight_duplicate_files",
    "preflight_unsupported_files",
    "preflight_ambiguous_files",
    "preflight_unreadable_files",
    "preflight_changed_files",
    "selected_files",
    "imported_files",
    "already_present_files",
    "intentionally_excluded_files",
    "cancelled_files",
)


def _normalized_completion_counts(result):
    raw_values = {
        field: getattr(result, field, _MISSING_RESULT_FIELD)
        for field in _COMPLETION_COUNT_FIELDS
    }
    counts = {
        field: max(0, int(0 if value is _MISSING_RESULT_FIELD else value or 0))
        for field, value in raw_values.items()
    }
    present = {
        field: value is not _MISSING_RESULT_FIELD
        for field, value in raw_values.items()
    }
    return counts, present


def _report_count_text(count):
    label = "report file" if count == 1 else "report files"
    return f"{count} {label}"


def _completion_title(counts, present):
    typed_outcomes = present["imported_files"] or present["already_present_files"]
    completed = (
        counts["imported_files"] + counts["already_present_files"]
        if typed_outcomes
        else counts["parsed_files"]
    )
    attention = any(
        counts[field]
        for field in (
            "failed_files",
            "skipped_files",
            "preflight_unsupported_files",
            "preflight_ambiguous_files",
            "preflight_unreadable_files",
            "preflight_changed_files",
            "cancelled_files",
        )
    )
    if attention:
        if counts["cancelled_files"] and not completed:
            return "warning", "Import cancelled"
        if completed:
            return "warning", "Parsing completed with warnings"
        if counts["failed_files"] or counts["preflight_changed_files"]:
            return "warning", "No reports imported"
        return "warning", "No compatible reports parsed"
    if present["selected_files"] and counts["selected_files"] == 0:
        return "info", "No reports selected"
    if typed_outcomes:
        if counts["imported_files"]:
            return "info", "Import successful"
        return "info", "No new reports saved"
    if counts["parsed_files"]:
        return "info", "Parsing successful"
    if counts["preflight_duplicate_files"]:
        return "info", "No new reports saved"
    return "info", "No reports selected"


def _primary_outcome_lines(counts, typed_outcomes):
    lines = []
    if typed_outcomes:
        categories = (
            ("imported_files", "Saved"),
            ("already_present_files", "Already present at import time"),
        )
        for field, label in categories:
            if counts[field]:
                lines.append(f"- {label}: {_report_count_text(counts[field])}.")
    elif counts["parsed_files"]:
        lines.append(
            "- Completed and available in the destination: "
            f"{_report_count_text(counts['parsed_files'])}."
        )
    return lines


def _additional_outcome_lines(counts):
    lines = []
    categories = (
        ("failed_files", "Failed", " could not be parsed"),
        ("cancelled_files", "Cancelled", ""),
        ("intentionally_excluded_files", "Intentionally not selected", ""),
    )
    for field, label, suffix in categories:
        if counts[field]:
            lines.append(f"- {label}: {_report_count_text(counts[field])}{suffix}.")
    if counts["skipped_files"]:
        lines.append(
            "- Runtime-skipped. Unsupported based on file contents and skipped: "
            f"{_report_count_text(counts['skipped_files'])}."
        )
        lines.append("- Parser recognition uses file contents, not filenames.")
    return lines


def _review_snapshot_group(counts):
    lines = ["Review snapshot:"]
    categories = (
        ("preflight_duplicate_files", "Matched the destination during review"),
        ("preflight_unsupported_files", "Unsupported during review"),
        ("preflight_ambiguous_files", "Ambiguous during review"),
        ("preflight_unreadable_files", "Unreadable during review"),
    )
    for field, label in categories:
        if counts[field]:
            lines.append(f"- {label}: {_report_count_text(counts[field])}.")
    return "\n".join(lines) if len(lines) > 1 else ""


def _changed_since_review_group(count):
    if not count:
        return ""
    return (
        "Changed since review:\n"
        "- Content or parser selection changed after scan; source content, occurrence, "
        "parser identity or parser generation no longer matched the reviewed state: "
        f"{_report_count_text(count)}."
    )


def _build_completion_groups(counts, present, db_file):
    typed_outcomes = present["imported_files"] or present["already_present_files"]
    outcome_lines = ["Import outcome:"]
    outcome_lines.extend(_primary_outcome_lines(counts, typed_outcomes))
    outcome_lines.extend(_additional_outcome_lines(counts))

    saved_count = counts["imported_files"] if typed_outcomes else counts["parsed_files"]
    if not saved_count:
        outcome_lines.append(f"- Nothing new was saved to {db_file}.")
    else:
        outcome_lines.append(f"- Destination: {db_file}.")
    if present["selected_files"] and counts["selected_files"] == 0:
        outcome_lines.append(
            "- Reports were reviewed, but none were selected or approved for import."
        )

    groups = ["\n".join(outcome_lines)]
    review_group = _review_snapshot_group(counts)
    changed_group = _changed_since_review_group(counts["preflight_changed_files"])
    groups.extend(group for group in (review_group, changed_group) if group)
    return "\n\n".join(groups)


def _build_import_completion_summary(result, db_file):
    counts, present = _normalized_completion_counts(result)
    if counts["total_files"] == 0:
        return (
            "info",
            "No reports parsed",
            (
                "No supported report files were found in the selected source. "
                f"Nothing was written to {db_file}."
            ),
        )
    severity, title = _completion_title(counts, present)
    return severity, title, _build_completion_groups(counts, present, db_file)


def _enrichment_completion_group(result):
    lines = ["Metadata enrichment:"]
    if result is None:
        return True, "\n".join(lines + ["- Requested, but completion evidence is unavailable."])
    counts = {
        field: max(0, int(getattr(result, field, 0) or 0))
        for field in ("enriched_files", "failed_files", "skipped_files", "cancelled_files")
    }
    for field, label in (
        ("enriched_files", "Enriched"), ("failed_files", "Failed or rejected"),
        ("skipped_files", "Skipped"), ("cancelled_files", "Cancelled"),
    ):
        if counts[field]:
            lines.append(f"- {label}: {_report_count_text(counts[field])}.")
    total = getattr(result, "total_files", None)
    missing = total is None or total != sum(counts.values())
    cancelled_before_start = (
        not getattr(result, "started", True)
        and getattr(result, "cancellation_requested", False)
    )
    if cancelled_before_start:
        lines.append("- Cancelled before metadata enrichment started.")
    elif total == 0:
        lines.append("- No eligible accepted reports for the requested enrichment.")
    if missing:
        lines.append("- Requested, but complete outcome evidence is unavailable.")
    attention = missing or cancelled_before_start or any(
        counts[field] for field in ("failed_files", "skipped_files", "cancelled_files")
    )
    return attention, "\n".join(lines)


def _build_parse_completion_summary(result, db_file, enrichment_result=None, *, enrichment_requested=False):
    requested = enrichment_requested or enrichment_result is not None
    if result is None:
        severity, title, message = "info", "Parsing successful", f"Measurements data saved to {db_file}!"
        if requested:
            severity, title, message = "warning", "Completion evidence unavailable", "Import outcome unavailable."
    else:
        severity, title, message = _build_import_completion_summary(result, db_file)
    if not requested:
        return severity, title, message
    attention, enrichment_group = _enrichment_completion_group(enrichment_result)
    message = message.replace(f"Nothing was written to {db_file}.", f"No new reports were saved to {db_file}.")
    message = message.replace(f"Nothing new was saved to {db_file}.", f"No new reports were saved to {db_file}.")
    if attention and severity != "warning":
        severity, title = "warning", "Metadata enrichment incomplete"
    return severity, title, message + "\n\n" + enrichment_group


@dataclass
class _ImportOperation:
    """One accepted import, retained through queued start and terminal delivery."""

    worker: object = None
    result: object = None
    failed: bool = False
    cancelled: bool = False
    terminal: bool = False


class _UiThrottle:
    """Run ``apply`` at most every ``_UI_UPDATE_INTERVAL_S``; a skipped request runs on a timer.

    ``request()`` runs ``apply`` now when the interval has passed, otherwise once when it
    does (single-shot timer owned by ``parent``).  ``flush()`` runs it now and ``cancel()``
    drops a scheduled run.  GUI thread only.
    """

    def __init__(self, parent, apply):
        self._apply = apply
        self._last = None
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush)

    def request(self):
        now = monotonic()
        if self._last is None or now - self._last >= _UI_UPDATE_INTERVAL_S:
            self.flush()
        elif not self._timer.isActive():
            self._timer.start(max(1, round(1000 * (_UI_UPDATE_INTERVAL_S - (now - self._last)))))

    def flush(self):
        self._timer.stop()
        self._last = monotonic()
        self._apply()

    def cancel(self):
        self._timer.stop()


class _ReportOperations:
    """One implementation of report state, controls and worker ownership."""

    def _initialize_report_operations(self, directory=None, db_file=None, *, external_context=False):
        self._external_context = external_context
        self.operation_start_allowed = None
        self._operation_progress = 0
        # Initialize variables
        self.directory = directory
        self.db_file = db_file
        self.preflight_thread = None
        self._preflight_result = None
        self._preflight_error_detail = ""
        self._review_status = ""
        self._approval_cache_key = None
        self._approval_cache = (False, False, "")
        self._close_requested = False
        # Background metadata read (#1100). ``metadata_thread`` is the worker whose
        # results are shown; every live worker stays in ``_metadata_threads`` until
        # its finished signal so no running QThread is ever destroyed.
        self.metadata_thread = None
        self._metadata_threads = []
        self._metadata_carryover = {}
        self._metadata_ocr_notes = set()
        # PyMuPDF must not run in two threads at once, so a scan, an import or a new
        # metadata read queues behind any metadata worker that is still stopping.
        self._after_metadata_idle = []
        self._start_pending = False
        # Throttled worker feedback: the latest scan progress and the metadata readings
        # that arrived since the last table update (with the worker that sent them).
        self._scan_feedback = {}
        self._scan_feedback_throttle = _UiThrottle(self, self._apply_scan_feedback)
        self._pending_readings = []
        self._pending_metadata_progress = None
        self._metadata_feedback_throttle = _UiThrottle(self, self._apply_metadata_feedback)

        # Initialize the widgets
        self.source_section_label = section_label("Source")
        self.directory_label = QLabel("Reports directory or archive:")
        self.directory_button = QPushButton("Browse folder")
        self.directory_button.clicked.connect(self.select_directory)
        self.archive_button = QPushButton("Browse archive")
        self.archive_button.clicked.connect(self.select_archive)
        self.directory_label.setToolTip("Folder with PDF reports, or a supported archive file.")
        self.directory_button.setToolTip("Choose a folder with PDF reports.")
        self.archive_button.setToolTip("Choose a supported archive file with PDF reports.")

        self.database_section_label = section_label("Destination")
        self.database_label = QLabel("Database file:")
        self.database_button = QPushButton("Browse")
        self.database_button.clicked.connect(self.select_database)
        self.database_label.setToolTip("SQLite database that will receive parsed measurements.")
        self.database_button.setToolTip("Choose or create the SQLite database for parsed measurements.")

        self.import_section_label = section_label("Import behavior")
        self.metadata_mode_label = QLabel("Metadata detail:")
        self.metadata_mode_combo = QComboBox()
        fast_tooltip = (
            "Light metadata skips OCR fallback and uses filename or embedded text metadata. "
            "Use this for the fastest import."
        )
        enrich_tooltip = (
            "Import quickly with light metadata first, then run a visible OCR metadata enrichment pass."
        )
        complete_tooltip = (
            "Run OCR fallback during import for stronger header metadata coverage. "
            "This is slower on large imports."
        )
        self.metadata_mode_combo.addItem("Fast import - light metadata, no OCR", _METADATA_MODE_FAST)
        self.metadata_mode_combo.setItemData(0, fast_tooltip, Qt.ItemDataRole.ToolTipRole)
        self.metadata_mode_combo.addItem(
            "Fast import, then enrich metadata",
            _METADATA_MODE_FAST_THEN_ENRICH,
        )
        self.metadata_mode_combo.setItemData(1, enrich_tooltip, Qt.ItemDataRole.ToolTipRole)
        self.metadata_mode_combo.addItem("Complete import - OCR during parsing", _METADATA_MODE_COMPLETE)
        self.metadata_mode_combo.setItemData(2, complete_tooltip, Qt.ItemDataRole.ToolTipRole)
        self.metadata_mode_combo.setCurrentIndex(self.metadata_mode_combo.findData(_METADATA_MODE_FAST))
        self.metadata_mode_label.setToolTip(f"{fast_tooltip} {enrich_tooltip} {complete_tooltip}")
        self.metadata_mode_combo.setToolTip(f"{fast_tooltip} {enrich_tooltip} {complete_tooltip}")

        self.scan_button = QPushButton("Review reports")
        self.scan_button.clicked.connect(self.scan_reports)
        self.scan_button.setEnabled(False)
        self.scan_button.setToolTip(
            "Inspect report contents and parser evidence without writing to the database."
        )

        self.review_scan_button = QPushButton("Report details")
        self.review_scan_button.clicked.connect(self.show_preflight_details)
        self.review_scan_button.setEnabled(False)

        self.parse_button = QPushButton("Import 0 selected reports")
        self.parse_button.clicked.connect(self._import_reviewed_reports)
        self.parse_button.setEnabled(False)
        self.parse_button.setToolTip(
            "Import only the exact report contents approved by the latest scan."
        )

        self.readiness_label = status_chip(
            "Select a source and database to review reports.",
            "warning",
        )

        self.mode_guidance_label = secondary_label(
            "Fast import stays light by default. OCR metadata can run after import or during complete import."
        )

        if self.directory:
            self.directory_text_label = path_field(self.directory)
            self.database_button.setEnabled(True)
        else:
            self.directory_text_label = path_field("")
            self.database_button.setEnabled(False)

        if self.db_file:
            self.database_text_label = path_field(self.db_file)
            if self.directory:
                self.parse_button.setEnabled(True)
        else:
            self.database_text_label = path_field("")
            self.parse_button.setEnabled(False)

        # Initialize thread and flag
        self.parse_thread = None
        self.import_operation = None
        self.parsing_canceled = False
        self.parse_error_message = None
        self._pending_modeless_metadata_enrichment = False
        current_index_changed = getattr(self.metadata_mode_combo, "currentIndexChanged", None)
        if current_index_changed is not None and hasattr(current_index_changed, "connect"):
            current_index_changed.connect(self._on_parse_inputs_changed)

        # Initialize the layout
        self.layout = QGridLayout()
        attach_help_menu_to_layout(self.layout, self, [("Parsing manual", 'parsing')])
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setHorizontalSpacing(10)
        self.layout.setVerticalSpacing(2)
        self.layout.setColumnStretch(1, 1)

        # Keep one expanding table region usable at compact desktop sizes.
        self.layout.addWidget(self.directory_label, 0, 0)
        self.layout.addWidget(self.directory_text_label, 0, 1)
        self.layout.addWidget(self.directory_button, 0, 2)
        self.layout.addWidget(self.archive_button, 0, 3)
        self.layout.addWidget(self.database_label, 1, 0)
        self.layout.addWidget(self.database_text_label, 1, 1, 1, 2)
        self.layout.addWidget(self.database_button, 1, 3)
        self.layout.addWidget(self.metadata_mode_label, 2, 0)
        self.layout.addWidget(self.metadata_mode_combo, 2, 1, 1, 3)
        self.layout.addWidget(self.readiness_label, 3, 0, 1, 4)
        self.report_planner = ReportPlanner(self)
        self.layout.addWidget(self.report_planner, 4, 0, 1, 4)
        self.layout.setRowStretch(4, 1)
        self.layout.addWidget(self.scan_button, 5, 2)
        self.layout.addWidget(self.parse_button, 5, 3)
        self.report_planner.selection_changed.connect(self._sync_readiness_state)
        self.report_planner.ocr_requested.connect(self.start_metadata_ocr)
        self.report_planner.stop_requested.connect(self.stop_metadata_read)
        self.report_planner.model.metadata_changed.connect(self._on_metadata_model_changed)
        # Retain the public details action for compatibility without a second UI.
        self.review_scan_button.hide()

        self.setLayout(self.layout)
        self._sync_readiness_state()
        configure_accessibility(self.directory_button, name="Browse parse source")
        configure_accessibility(self.archive_button, name="Browse parse archive source")
        configure_accessibility(self.database_button, name="Browse parse database")
        configure_accessibility(self.metadata_mode_combo, name="Metadata detail")
        configure_accessibility(self.scan_button, name="Review reports")
        configure_accessibility(self.review_scan_button, name="Report details")
        configure_accessibility(self.parse_button, name="Import selected reports")
        self.readiness_label.setAccessibleName("Report review status")
        focus_order = (
            self.directory_button, self.archive_button, self.database_button,
            self.metadata_mode_combo, self.scan_button, self.report_planner.search,
            self.report_planner.status_filter, self.report_planner.parser_filter,
            self.report_planner.attention_filter, self.report_planner.select_ready,
            self.report_planner.clear, self.report_planner.table,
            self.report_planner.ocr_button, self.report_planner.metadata_button, self.parse_button,
        )
        for first, second in zip(focus_order, focus_order[1:]):
            self.setTabOrder(first, second)
        # The embedded Reports owner inherits the application's live semantic
        # theme. A full local stylesheet would retain its creation-time colors
        # when the main window switches theme; only standalone dialogs own one.
        if not external_context:
            apply_metroliza_theme(self)
        for button in (self.directory_button, self.archive_button, self.database_button,
                       self.scan_button, self.parse_button):
            button.setStyleSheet(PLANNER_ACTION_STYLE)

    def _selected_metadata_request_fields(self):
        selected_mode = self.metadata_mode_combo.currentData() or _METADATA_MODE_FAST
        return _METADATA_MODE_REQUEST_FIELDS.get(selected_mode, _METADATA_MODE_REQUEST_FIELDS[_METADATA_MODE_FAST])

    @staticmethod
    def _archive_extension_set():
        return {ext.lower() for _, extensions, _ in shutil.get_unpack_formats() for ext in extensions}

    @staticmethod
    def _archive_file_filter():
        archive_patterns = sorted({
            f"*{ext}"
            for _, extensions, _ in shutil.get_unpack_formats()
            for ext in extensions
        })
        if not archive_patterns:
            return "All Files (*)"
        return "Supported archives (" + " ".join(archive_patterns) + ")"

    def _selected_metadata_mode(self):
        return self.metadata_mode_combo.currentData() or _METADATA_MODE_FAST

    def _source_is_archive(self):
        if not self.directory:
            return False
        return str(self.directory).lower().endswith(tuple(self._archive_extension_set()))

    def _build_parse_request_fields(self):
        selected_mode = self._selected_metadata_mode()
        metadata_parsing_mode, run_background_metadata_enrichment = _METADATA_MODE_REQUEST_FIELDS.get(
            selected_mode,
            _METADATA_MODE_REQUEST_FIELDS[_METADATA_MODE_FAST],
        )
        request_modeless_enrichment = selected_mode == _METADATA_MODE_FAST_THEN_ENRICH

        if request_modeless_enrichment:
            # Keep enrichment bound to the selected import plan and its source
            # approvals. The database-wide modeless launcher cannot carry them.
            run_background_metadata_enrichment = True
            request_modeless_enrichment = False

        return metadata_parsing_mode, run_background_metadata_enrichment, request_modeless_enrichment

    def _sync_readiness_state(self, *, refresh_registry=False):
        inputs_ready = bool(self.directory and self.db_file)
        busy = self.preflight_thread is not None or self.parse_thread is not None
        current, selectable_approved, summary = self._review_approval(refresh_registry=refresh_registry)
        count = self.report_planner.model.selected_count
        if current and count and not selectable_approved:
            self._invalidate_preflight("Changed since review. Review reports again before importing.")
            return self._sync_readiness_state()
        approved = current and bool(count) and selectable_approved
        ocr_running = self._metadata_mode() == MODE_OCR
        stopping = self._start_pending
        caption = f"Import {count} selected report{'s' if count != 1 else ''}"
        self.parse_button.setText(caption)
        self.parse_button.setAccessibleName(caption)
        self.parse_button.setEnabled(bool(approved and not busy and not ocr_running and not stopping))
        self.scan_button.setText("Refresh review" if self._preflight_result else "Review reports")
        self.scan_button.setAccessibleName(self.scan_button.text())
        self.scan_button.setEnabled(inputs_ready and not busy and not stopping)
        self.report_planner.set_busy(busy)
        self.report_planner.set_metadata_worker(
            self._metadata_mode(), ocr_reason=self._ocr_unavailable_reason()
        )
        for control in (self.directory_button, self.archive_button, self.metadata_mode_combo):
            control.setEnabled(not busy)
        self.database_button.setEnabled(bool(self.directory) and not busy)
        self.review_scan_button.setEnabled(bool(self._preflight_result))
        message = self._readiness_message(
            busy=busy, current=current, count=count, inputs_ready=inputs_ready,
            ocr_running=ocr_running, stopping=stopping,
        )
        self.readiness_label.setText(message)
        self.readiness_label.setAccessibleDescription(message)
        self.readiness_label.setToolTip(summary if current else message)
        self.parse_button.setToolTip(
            f"Import exactly {count} selected reports, including selected rows hidden by filters."
            if approved and not busy and not ocr_running and not stopping else message
        )
        set_status_variant(self.readiness_label, "success" if approved else "warning")
        configure_dialog_button_roles(
            primary=self.parse_button if approved else self.scan_button,
            secondary=(self.scan_button if approved else self.parse_button,
                       self.directory_button, self.archive_button, self.database_button),
            quiet=(self.review_scan_button,),
        )
        self.state_changed.emit()

    def _readiness_message(self, *, busy, current, count, inputs_ready, ocr_running, stopping):
        if busy:
            return "Report operation in progress. Use Cancel in the progress window."
        if current:
            return self._review_message(count, ocr_running=ocr_running, stopping=stopping)
        if self._review_status:
            return self._review_status
        if inputs_ready:
            return "Ready to review. No database changes are made until you import."
        if self.directory:
            return "Select or create a database before reviewing reports."
        return "Select a source and database to review reports."

    def _review_message(self, count, *, ocr_running, stopping):
        ready = self.report_planner.model.counts["ready"]
        message = f"Review complete: {ready} ready. No database changes were made."
        if not count:
            return message + " Select ready reports to enable import."
        if ocr_running:
            return "Reading checked reports with OCR. Import is available when it finishes or after Stop."
        if stopping:
            return "Stopping the metadata read. The requested operation starts right after."
        if self._metadata_review_complete():
            message += " Metadata: " + self._metadata_summary_text() + "."
        return message

    def apply_workspace_snapshot(self, snapshot):
        """Apply accepted context without creating an independent selection owner."""
        paths = (snapshot.source_directory, snapshot.database_file)
        if paths == (self.directory, self.db_file):
            return
        if not self.can_change_workspace():
            raise RuntimeError("Report operation must finish before context changes")
        self._invalidate_preflight()
        self.report_planner.clear_outcome()
        self.directory, self.db_file = paths
        update_path_field(self.directory_text_label, self.directory)
        update_path_field(self.database_text_label, self.db_file)
        self._sync_readiness_state()

    def can_change_workspace(self):
        return self.preflight_thread is None and self.parse_thread is None

    def pdf_workers_idle(self):
        """Include retired readers until their QThreads have actually stopped."""
        return self.can_change_workspace() and not self._metadata_workers_running()

    def focus_primary_action(self):
        if not self.directory:
            control = self.directory_button
        elif not self.db_file:
            control = self.database_button
        elif self.parse_button.isEnabled():
            control = self.parse_button
        elif self.can_change_workspace():
            control = self.scan_button
        else:
            control = self.report_planner.search
        control.setFocus()

    def request_shutdown(self):
        if self.can_change_workspace() and not self._metadata_workers_running():
            return True
        self._close_requested = True
        self._request_active_worker_cancellation()
        return False

    @pyqtSlot(int)
    def _on_operation_progress(self, value):
        if value == self._operation_progress:
            return  # the shell restyles on every change; an equal value changes nothing
        self._operation_progress = value
        self.state_changed.emit()

    def _review_approval(self, *, refresh_registry=False):
        """Cache immutable review approval; selection edits only change the count."""
        if self._preflight_result is None:
            return False, False, ""
        metadata_mode, _background, _modeless = self._build_parse_request_fields()
        # Always refresh at the import boundary, before consulting the cache.
        generation = report_parser_factory.get_registry_snapshot(refresh=refresh_registry).generation_id
        key = (id(self._preflight_result), self.directory, self.db_file, metadata_mode, generation)
        if key == self._approval_cache_key:
            return self._approval_cache
        current = self._preflight_is_current()
        eligible = self._preflight_result.atomic_import_candidates(
            source_path=self.directory,
            database_path=self.db_file,
            metadata_parsing_mode=metadata_mode,
            registry_generation_id=generation,
        )
        # The model restricts every selection to these immutable READY IDs.
        approved = self.report_planner.model.selectable_ids.issubset(
            item.stable_occurrence_id for item in eligible
        )
        summary = self._preflight_summary_text(self._preflight_result) if current else ""
        self._approval_cache_key = key
        self._approval_cache = (current, approved, summary)
        return self._approval_cache

    def _preflight_is_current(self):
        if not self.directory or not self.db_file:
            return False
        if self._preflight_result is None or self._preflight_result.cancelled:
            return False
        metadata_parsing_mode, _background, _modeless = self._build_parse_request_fields()
        return self._preflight_result.matches_request(
            source_path=self.directory,
            database_path=self.db_file,
            metadata_parsing_mode=metadata_parsing_mode,
        )

    @staticmethod
    def _preflight_summary_text(result):
        counts = result.status_counts
        return (
            f"Review complete: {counts[ParsePreflightStatus.READY]} ready, "
            f"{counts[ParsePreflightStatus.DUPLICATE]} matched destination during review, "
            f"{counts[ParsePreflightStatus.UNSUPPORTED]} unsupported, "
            f"{counts[ParsePreflightStatus.AMBIGUOUS]} ambiguous, "
            f"{counts[ParsePreflightStatus.UNREADABLE]} unreadable."
        )

    def _invalidate_preflight(self, reason=None, *, keep_metadata=False):
        """Drop the review; ``keep_metadata`` offers its metadata rows to the next review."""
        if reason is None:
            reason = (
                "Review invalidated. Review reports again before importing."
                if self._preflight_result is not None else ""
            )
        carried = (
            self.report_planner.model.metadata_rows
            if keep_metadata and self._preflight_result is not None else {}
        )
        self._retire_metadata_worker()
        self._drop_pending_starts()
        self._metadata_carryover = carried
        self._preflight_result = None
        self._approval_cache_key = None
        self._preflight_error_detail = ""
        self._review_status = reason
        self.report_planner.invalidate()

    @pyqtSlot()
    def _on_parse_inputs_changed(self, *_args):
        self._invalidate_preflight()
        self._sync_readiness_state()

    def _set_parse_source(self, selected_source):
        if not selected_source:
            return
        if self._external_context:
            self.source_change_requested.emit(selected_source)
            return
        logger.info("Selected parse source: %s", selected_source)
        self._invalidate_preflight()
        self.directory = selected_source
        update_path_field(self.directory_text_label, selected_source)
        self.database_button.setEnabled(True)
        if self.parent() is not None and hasattr(self.parent(), "set_directory"):
            self.parent().set_directory(selected_source)
        self._sync_readiness_state()

    @pyqtSlot()
    def select_directory(self):
        """Choose a parse source, with a fallback path for archive selection."""
        try:
            # Open a dialog to select a directory first.
            selected_source = QFileDialog.getExistingDirectory(self, "Select directory")
            if not selected_source:
                choose_archive = QMessageBox.question(
                    self,
                    "No directory selected",
                    "No directory was selected. Do you want to choose an archive file instead?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if choose_archive != QMessageBox.StandardButton.Yes:
                    return

                selected_source, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select archive",
                    "",
                    f"{self._archive_file_filter()};;All Files (*)",
                )

            self._set_parse_source(selected_source)
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def select_archive(self):
        """Choose an archive parse source directly without first opening folder selection."""
        try:
            selected_source, _ = QFileDialog.getOpenFileName(
                self,
                "Select archive",
                "",
                f"{self._archive_file_filter()};;All Files (*)",
            )
            self._set_parse_source(selected_source)
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def select_database(self):
        """Select or create the destination database and update parent state."""
        from metroliza.shared.sqlite_paths import SQLITE_FILE_FILTER, sqlite_database_path

        try:
            # Open a dialog to select a database file
            # options = QFileDialog.Options()
            # options |= QFileDialog.DontUseNativeDialog
            default_name = self.directory # + "/" + [part for part in self.directory.split("/") if part][-1]
            default_name = sqlite_database_path(default_name, creating=True)
            filename, _ = QFileDialog.getSaveFileName(self, "Select database", f"{default_name}",
                                                    SQLITE_FILE_FILTER)
            if filename:
                filename = sqlite_database_path(filename, creating=True)
                if self._external_context:
                    self.database_change_requested.emit(filename)
                    return
                logger.info("Selected parse database file: %s", filename)
                self._invalidate_preflight()
                self.db_file = filename
                update_path_field(self.database_text_label, filename)
                if self.parent() is not None and hasattr(self.parent(), "set_db_file"):
                    self.parent().set_db_file(filename)

                self._sync_readiness_state()
        except Exception as e:
            self.log_and_exit(e)

    @pyqtSlot()
    def scan_reports(self, *, action_started_at=None):
        """Start a non-mutating content/parser recognition pass."""

        action_started_at = monotonic() if action_started_at is None else action_started_at
        if self.preflight_thread is not None or self.parse_thread is not None:
            return
        if self.operation_start_allowed is not None and not self.operation_start_allowed():
            return
        if self._defer_until_metadata_idle(
            partial(self.scan_reports, action_started_at=action_started_at), user_started=True
        ):
            return
        self._operation_progress = 0
        try:
            metadata_parsing_mode, _background, _modeless = self._build_parse_request_fields()
            request = validate_parse_request(
                ParseRequest(
                    source_directory=self.directory,
                    db_file=self.db_file,
                    metadata_parsing_mode=metadata_parsing_mode,
                )
            )
            if ParsePreflightThread is None:
                raise RuntimeError("Parser scan worker is unavailable in this runtime.")

            self._invalidate_preflight(keep_metadata=True)
            (
                self.scan_loading_dialog,
                self.scan_loading_label,
                self.scan_loading_bar,
                self.scan_loading_gif,
            ) = create_worker_progress_dialog(
                self,
                window_title="Reviewing reports...",
                initial_status_text=build_three_line_status(
                    "Reviewing reports...",
                    "Discovering report files and parser evidence",
                    "No database changes are being made",
                ),
                on_cancel=self.stop_scanning,
                action_started_at=action_started_at,
            )
            if self._external_context:
                self.scan_loading_dialog.setWindowModality(Qt.WindowModality.NonModal)
            self.scan_button.setEnabled(False)
            self.parse_button.setEnabled(False)
            self.preflight_thread = ParsePreflightThread(
                source_path=request.source_directory,
                database_path=request.db_file,
                metadata_parsing_mode=request.metadata_parsing_mode,
            )
            thread_ref = weakref.ref(self.preflight_thread)
            self.preflight_thread.finished.connect(
                partial(self._on_preflight_thread_stopped, thread_ref)
            )
            self._scan_feedback = {}
            self.preflight_thread.update_label.connect(
                partial(self._on_scan_feedback, thread_ref, "label")
            )
            self.preflight_thread.update_progress.connect(
                partial(self._on_scan_feedback, thread_ref, "progress")
            )
            self.preflight_thread.completed.connect(self.on_preflight_completed)
            self.preflight_thread.failed.connect(self.on_preflight_failed)
            self.preflight_thread.start()
            self._sync_readiness_state()
            self.scan_loading_dialog.show()
        except Exception as exc:
            self._dismiss_progress("scan_loading", rejected=True)
            self._recover_worker_start_failure("preflight_thread", "stop_scan")
            self._invalidate_preflight("Review could not start. Review reports again to retry.")
            self._sync_readiness_state()
            self.scan_button.setFocus()
            self.log_and_exit(exc)

    def _on_scan_feedback(self, thread_ref, kind, value):
        thread = thread_ref()
        if thread is None or thread is not self.preflight_thread:
            return
        self._scan_feedback[kind] = value
        self._scan_feedback_throttle.request()

    def _apply_scan_feedback(self):
        feedback, self._scan_feedback = self._scan_feedback, {}
        if "label" in feedback and getattr(self, "scan_loading_label", None) is not None:
            self.scan_loading_label.setText(feedback["label"])
        if "progress" in feedback:
            if getattr(self, "scan_loading_bar", None) is not None:
                self.scan_loading_bar.setValue(feedback["progress"])
            self._on_operation_progress(feedback["progress"])

    @pyqtSlot()
    def stop_scanning(self):
        thread = self.preflight_thread
        if thread is not None and thread.isRunning():
            thread.stop_scan()
            self._scan_feedback_throttle.cancel()
            self._scan_feedback = {}
            loading_label = getattr(self, "scan_loading_label", None)
            if loading_label is not None:
                loading_label.setText(
                    build_three_line_status(
                        "Canceling scan...",
                        "Waiting for the current content inspection to stop",
                        "No database changes were made",
                    )
                )

    def _on_preflight_thread_stopped(self, thread_ref):
        stopped_thread = thread_ref()
        if stopped_thread is not None and stopped_thread is self.preflight_thread:
            self.preflight_thread = None
        self._sync_readiness_state()
        if not self._close_requested:
            if self._preflight_result is not None:
                self.report_planner.table.setFocus()
            else:
                self.scan_button.setFocus()
        self._complete_deferred_close_if_idle()

    @pyqtSlot(object)
    def on_preflight_completed(self, result):
        # The indicator stays until the review is applied to the table.
        self._scan_feedback_throttle.cancel()
        self._scan_feedback = {}
        try:
            self._apply_preflight_result(result)
        finally:
            self._dismiss_progress(
                "scan_loading",
                rejected=bool(result.cancelled),
            )

    def _dismiss_progress(self, prefix, *, rejected=False):
        dialog = getattr(self, prefix + "_dialog", None)
        dismiss_worker_progress_dialog(dialog, rejected=rejected)
        if callable(getattr(dialog, "deleteLater", None)):
            for suffix in ("dialog", "label", "bar", "gif"):
                setattr(self, prefix + "_" + suffix, None)

    def _apply_preflight_result(self, result):
        if result.cancelled:
            self._invalidate_preflight("Review cancelled. No database changes were made.")
        elif not result.matches_request(
            source_path=self.directory, database_path=self.db_file,
            metadata_parsing_mode=self._build_parse_request_fields()[0],
        ):
            self._invalidate_preflight("Inputs changed. Review reports again before importing.")
        else:
            self._preflight_result = result
            self._preflight_error_detail = ""
            self._review_status = ""
            carried, self._metadata_carryover = self._metadata_carryover, {}
            self.report_planner.set_review(result, carry=carried)
            self._start_metadata_fast_read()
        self._sync_readiness_state()

    @pyqtSlot(str)
    def on_preflight_failed(self, detail):
        self._scan_feedback_throttle.cancel()
        self._scan_feedback = {}
        self._dismiss_progress("scan_loading", rejected=True)
        # Arbitrary exception strings can contain confidential document content.
        self._invalidate_preflight("Review failed. Check the source and destination, then retry.")
        self._sync_readiness_state()

    @pyqtSlot()
    def show_preflight_details(self):
        self.report_planner.details_button.setChecked(True)
        self.report_planner.table.setFocus()

    # -- inline metadata review (#1100) ------------------------------------------
    #
    # The review table itself carries the metadata: after a successful review a
    # background fast read fills the cells, the user corrects them in place and may
    # run OCR on the checked reports.  Nothing here touches the database; the
    # overrides of the checked reports travel in the ImportPlan.

    def _create_metadata_reader(self):
        return MetadataReviewReader(self._preflight_result)

    @staticmethod
    def _ocr_unavailable_reason():
        return ocr_unavailable_reason()

    def _metadata_mode(self):
        thread = self.metadata_thread
        return thread.mode if thread is not None else None

    def _metadata_workers_running(self):
        return any(self._thread_is_running(thread) for thread in self._metadata_threads)

    def _metadata_summary_text(self):
        return summarize_rows(self.report_planner.model.selected_metadata_rows())

    def _metadata_review_complete(self):
        rows = self.report_planner.model.selected_metadata_rows()
        return bool(rows) and all(row.state != ROW_PENDING for row in rows)

    def _on_metadata_model_changed(self):
        # Reads report their own progress; an edit (or a new review) refreshes the summary.
        if self.metadata_thread is None and self._preflight_result is not None:
            self._sync_readiness_state()

    def _start_metadata_fast_read(self):
        if self._defer_until_metadata_idle(self._start_metadata_fast_read):
            return True  # starts after a retired worker has ended
        model = self.report_planner.model
        ordered = self.report_planner.metadata_read_order(model.pending_metadata_ids())
        return self._start_metadata_read(MODE_FAST, ordered)

    @pyqtSlot()
    def start_metadata_ocr(self):
        """Read the header of the checked, editable reports with OCR."""
        reason = self._ocr_unavailable_reason()
        if reason:
            self.report_planner.set_metadata_status(reason, "warning")
            return False
        rows = [row for row in self.report_planner.model.selected_metadata_rows() if row.editable]
        ordered = self.report_planner.metadata_read_order([row.occurrence_id for row in rows])
        if not ordered:
            self.report_planner.set_metadata_status(
                "Check at least one editable ready report to read it with OCR.", "warning"
            )
            return False
        return self._start_metadata_read(MODE_OCR, ordered)

    def _start_metadata_read(self, mode, occurrence_ids):
        action_started_at = monotonic()
        ids = tuple(occurrence_ids)
        if not ids or self._preflight_result is None or self.metadata_thread is not None:
            return False
        if self.operation_start_allowed is not None and not self.operation_start_allowed():
            return False
        if self._metadata_workers_running():
            # A retired worker is still inside a report: start after it has ended.
            return self._defer_until_metadata_idle(lambda: self._start_metadata_read(mode, ids))
        try:
            thread = MetadataReviewThread(self._create_metadata_reader(), ids, mode=mode)
        except Exception:  # noqa: BLE001 - the review stays usable without the metadata read
            # Exception text can carry report content, so only the fact is logged.
            logger.warning("Metadata reader could not be created.")
            self.report_planner.set_metadata_status("Metadata could not be read.", "warning")
            return False
        if mode == MODE_FAST:
            dialog, _label, bar, _movie = create_delayed_worker_progress_dialog(
                self, window_title="Reading report metadata...",
                initial_status_text="Reading report metadata...\nFilling the review table\nETA --",
                on_cancel=lambda: None, cancellable=False, action_started_at=action_started_at,
            )
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            bar.setRange(0, 0)
            self._metadata_loading_dialog = dialog
            dialog.show()
        self._metadata_ocr_notes = set()
        self.metadata_thread = thread
        self._metadata_threads.append(thread)
        thread.reading_ready.connect(lambda reading, t=thread: self._on_metadata_reading(t, reading))
        thread.update_counts.connect(lambda done, total, t=thread: self._on_metadata_progress(t, done, total))
        thread.completed.connect(lambda summary, t=thread: self._on_metadata_completed(t, summary))
        thread.failed.connect(lambda text, t=thread: self._on_metadata_failed(t, text))
        thread.finished.connect(lambda t=thread: self._on_metadata_thread_stopped(t))
        self.report_planner.set_metadata_status(self._metadata_progress_text(mode, 0, len(ids)))
        thread.start()
        self._sync_readiness_state()
        return True

    @staticmethod
    def _metadata_progress_text(mode, done, total):
        action = "Reading with OCR" if mode == MODE_OCR else "Reading metadata"
        return f"{action} {done}/{total}\u2026"

    def _on_metadata_progress(self, thread, done, total):
        if thread is self.metadata_thread and not thread.cancel_requested:
            self._pending_metadata_progress = (thread, done, total)
            self._metadata_feedback_throttle.request()

    def _on_metadata_reading(self, thread, reading):
        if thread is not self.metadata_thread:
            return  # a retired worker's late result must not touch the next review
        self._pending_readings.append((thread, reading))
        self._metadata_feedback_throttle.request()

    def _apply_metadata_feedback(self):
        """Apply the readings and the latest progress that arrived since the last update."""
        readings, self._pending_readings = self._pending_readings, []
        progress, self._pending_metadata_progress = self._pending_metadata_progress, None
        for thread, reading in readings:
            if thread is not self.metadata_thread:
                continue  # retired while queued
            self.report_planner.model.apply_reading(reading)
            note = getattr(reading, "ocr_note", "")
            if reading.mode == MODE_OCR and note and "not needed" not in note and note != "Header read with OCR.":
                self._metadata_ocr_notes.add(note)
        if progress is not None:
            thread, done, total = progress
            if thread is self.metadata_thread and not thread.cancel_requested:
                self.report_planner.set_metadata_status(self._metadata_progress_text(thread.mode, done, total))

    def _drop_metadata_feedback(self):
        self._metadata_feedback_throttle.cancel()
        self._pending_readings = []
        self._pending_metadata_progress = None

    def _on_metadata_completed(self, thread, summary):
        if thread is not self.metadata_thread:
            return
        # Every reading of the batch is in the table before the summary replaces the progress.
        self._pending_metadata_progress = None
        self._metadata_feedback_throttle.flush()
        verb = "OCR" if thread.mode == MODE_OCR else "Metadata read"
        if summary.cancelled:
            text = f"{verb} stopped: {summary.read} of {summary.total} done; the rest was not read."
        else:
            text = f"{verb} finished for {summary.read} of {summary.total} report{'s' if summary.total != 1 else ''}."
        if summary.failed:
            text += f" {summary.failed} could not be read."
        if self._metadata_ocr_notes:
            text += " " + " ".join(sorted(self._metadata_ocr_notes))
        attention = bool(summary.failed or self._metadata_ocr_notes)
        if thread.mode == MODE_FAST and not summary.cancelled and not attention:
            self.report_planner.clear_metadata_status()  # the filled cells are the feedback
            return
        self.report_planner.set_metadata_status(text, "warning" if attention else "neutral")

    def _on_metadata_failed(self, thread, text):
        if thread is self.metadata_thread:
            self._pending_metadata_progress = None
            self._metadata_feedback_throttle.flush()
            self.report_planner.set_metadata_status(text, "warning")

    def _on_metadata_thread_stopped(self, stopped_thread):
        if stopped_thread is self.metadata_thread and self._pending_readings:
            self._pending_metadata_progress = None
            self._metadata_feedback_throttle.flush()
        self._release_metadata_thread(stopped_thread)
        queued = []
        if not self._metadata_workers_running() and not self._close_requested:
            queued, self._after_metadata_idle = self._after_metadata_idle, []
            self._start_pending = False
        self._sync_readiness_state()
        for callback in queued:
            callback()
        self._complete_deferred_close_if_idle()

    def _release_metadata_thread(self, thread):
        if thread is self.metadata_thread:
            self._dismiss_progress("_metadata_loading")
        if thread in self._metadata_threads:
            self._metadata_threads.remove(thread)
            thread.deleteLater()
        if thread is self.metadata_thread:
            self.metadata_thread = None

    def _defer_until_metadata_idle(self, callback, *, user_started=False):
        """Queue ``callback`` behind running metadata workers (True when it was queued).

        PyMuPDF must not run in two threads at once, and the GUI thread must not
        block: the workers are asked to stop and ``callback`` starts from the
        finished signal of the last one.
        """
        if not self._metadata_workers_running():
            return False
        self._after_metadata_idle.append(callback)
        self._start_pending = self._start_pending or user_started
        self._cancel_metadata_workers()
        self._sync_readiness_state()
        return True

    @pyqtSlot()
    def stop_metadata_read(self):
        """Ask the running metadata read to stop after its current report."""
        thread = self.metadata_thread
        if thread is not None and self._thread_is_running(thread):
            thread.stop_reading()
            self.report_planner.set_metadata_status("Stopping after the current report\u2026")

    def _retire_metadata_worker(self):
        """Stop showing the active worker's results; it ends on its own (cooperative cancel)."""
        thread = self.metadata_thread
        if thread is None:
            return
        self.metadata_thread = None
        self._dismiss_progress("_metadata_loading")
        self._drop_metadata_feedback()
        if self._thread_is_running(thread):
            thread.stop_reading()
        else:
            self._release_metadata_thread(thread)
        self.report_planner.set_metadata_worker(None, ocr_reason=self._ocr_unavailable_reason())
        self.report_planner.clear_metadata_status()

    def _cancel_metadata_workers(self):
        for thread in self._metadata_threads:
            if self._thread_is_running(thread):
                thread.stop_reading()

    @pyqtSlot()
    def _import_reviewed_reports(self):
        """Dispatch the exact global selection through the accepted import contract."""
        action_started_at = monotonic()
        self._sync_readiness_state(refresh_registry=True)
        if not self.parse_button.isEnabled():
            return
        # A still-running fast read is stopped by show_loading_screen (cooperative
        # cancel, never awaited): the import does not depend on it.
        metadata, enrich, _modeless = self._build_parse_request_fields()
        request = ParseRequest(
            source_directory=self.directory, db_file=self.db_file,
            metadata_parsing_mode=metadata, run_background_metadata_enrichment=enrich,
        )
        try:
            plan = ImportPlan.from_preflight(
                request, self._preflight_result,
                selected_occurrence_ids=self.report_planner.model.selected_ids,
                # Only the checked reports: edits on unchecked rows are never imported.
                metadata_overrides=build_overrides(self.report_planner.model.selected_metadata_rows()),
            )
        except ValueError:
            self._invalidate_preflight("Changed since review. Review reports again before importing.")
            self._sync_readiness_state()
            return
        self.show_loading_screen(import_plan=plan, action_started_at=action_started_at)

    def _accept_import_operation(self, operation):
        if self._close_requested or (operation is not None and operation.terminal):
            return None
        if operation is None:
            if self._start_pending:
                return None
            operation = self.import_operation = _ImportOperation()
        return operation

    @pyqtSlot()
    def show_loading_screen(self, *, import_plan=None, action_started_at=None, _operation=None):
        """Start a plan; direct legacy callers retain the atomic compatibility adapter."""
        action_started_at = monotonic() if action_started_at is None else action_started_at
        if self.preflight_thread is not None or self.parse_thread is not None:
            return
        if self.operation_start_allowed is not None and not self.operation_start_allowed():
            return
        _operation = self._accept_import_operation(_operation)
        if _operation is None:
            return
        if self._defer_until_metadata_idle(
            lambda: self.show_loading_screen(
                import_plan=import_plan, action_started_at=action_started_at, _operation=_operation
            ), user_started=True
        ):
            return
        self._operation_progress = 0
        self._retire_metadata_worker()
        self.report_planner.clear_metadata_status()
        try:
            (
                metadata_parsing_mode,
                run_background_metadata_enrichment,
                self._pending_modeless_metadata_enrichment,
            ) = self._build_parse_request_fields()
            request = validate_parse_request(
                ParseRequest(
                    source_directory=self.directory,
                    db_file=self.db_file,
                    metadata_parsing_mode=metadata_parsing_mode,
                    run_background_metadata_enrichment=run_background_metadata_enrichment,
                )
            )

            self.loading_dialog, self.loading_label, self.loading_bar, self.loading_gif = create_worker_progress_dialog(
                self,
                window_title="Importing reviewed reports...",
                initial_status_text=build_three_line_status(
                    "Importing reviewed reports...",
                    "Preparing parser thread",
                    "ETA --",
                ),
                on_cancel=self.stop_parsing,
                action_started_at=action_started_at,
            )
            if self._external_context:
                self.loading_dialog.setWindowModality(Qt.WindowModality.NonModal)

            # Disable the parse button before the worker starts.
            self.parse_button.setEnabled(False)
            self.scan_button.setEnabled(False)
            self.parsing_canceled = False
            self.parse_error_message = None

            # The import action supplies a review. Legacy direct loading-screen
            # calls still reach the worker's fail-closed missing-plan validation.
            execution_request = request
            if import_plan is not None:
                execution_request = import_plan
            elif self._preflight_result is not None:
                execution_request = ImportPlan.all_atomic_candidates(request, self._preflight_result)
            self.parse_thread = ParseReportsThread(execution_request)
            _operation.worker = self.parse_thread
            self.parse_thread.finished.connect(self.on_parse_finished)
            self.parse_thread.finished.connect(
                lambda thread=self.parse_thread: self._on_parse_thread_stopped(thread)
            )
            self.parse_thread.update_label.connect(self.loading_label.setText)
            self.parse_thread.update_progress.connect(self.loading_bar.setValue)
            self.parse_thread.update_progress.connect(self._on_operation_progress)
            self.parse_thread.error_occurred.connect(self.on_parse_error)
            self.parse_thread.start()
            self._sync_readiness_state()
            self.loading_dialog.show()
        except Exception as e:
            _operation.failed = True
            self._dismiss_progress("loading", rejected=True)
            self._recover_worker_start_failure("parse_thread", "stop_parsing")
            _operation.terminal = self.parse_thread is None
            if _operation.terminal:
                _operation.worker = None
            self._invalidate_preflight("Import could not start. Review reports again before retrying.")
            self._sync_readiness_state()
            self.scan_button.setFocus()
            self.log_and_exit(e)

    def _recover_worker_start_failure(self, attribute, cancel_method):
        thread = getattr(self, attribute)
        if thread is None:
            return
        if self._thread_is_running(thread):
            # A partially started operation keeps its lifetime owner and the
            # finished cleanup connected above. Never block the GUI waiting.
            getattr(thread, cancel_method)()
        else:
            setattr(self, attribute, None)
            thread.deleteLater()

    @pyqtSlot()
    def stop_parsing(self):
        """Request cooperative parser cancellation without blocking the UI."""
        try:
            self._drop_pending_starts()
            # Request cooperative cancellation and return immediately to keep UI responsive
            self.parsing_canceled = True
            self._sync_readiness_state()
            if self.parse_thread is not None and self.parse_thread.isRunning():
                self.parse_thread.stop_parsing()
                loading_label = getattr(self, "loading_label", None)
                if loading_label is not None:
                    loading_label.setText(
                        build_three_line_status(
                            "Canceling parsing...",
                            "Waiting for parser thread to stop",
                            "ETA --",
                        )
                    )
        except Exception as e:
            self.log_and_exit(e)

    def _on_parse_thread_stopped(self, stopped_thread):
        operation = getattr(self, "import_operation", None)
        if operation is not None and operation.worker is stopped_thread:
            operation.terminal = True
        if stopped_thread is self.parse_thread:
            self.parse_thread = None
        self._sync_readiness_state()
        if not self._close_requested:
            self.scan_button.setFocus()
        self._complete_deferred_close_if_idle()


    @staticmethod
    def _report_file_label(count):
        return "report file" if count == 1 else "report files"

    def _build_parse_completion_feedback(self):
        return _build_parse_completion_summary(
            getattr(self.parse_thread, "last_parse_result", None), self.db_file,
            getattr(self.parse_thread, "last_enrichment_result", None),
            enrichment_requested=ParsingDialog._embedded_enrichment_requested(self),
        )

    def _embedded_enrichment_requested(self):
        return bool(
            getattr(self.parse_thread, "run_background_metadata_enrichment", False)
            and getattr(self.parse_thread, "metadata_parsing_mode", "light") == "light"
        )


    @pyqtSlot(str)
    def on_parse_error(self, message):
        """Capture parse errors for final summary when the worker finishes."""
        self.parse_error_message = message
        self.loading_label.setText(build_three_line_status("Parsing failed.", "See error details for context", "ETA --"))

    @pyqtSlot()
    def on_parse_finished(self):
        """Handle parse completion, including cancellation and error paths."""
        try:
            close_requested = getattr(self, "_close_requested", False)
            # Retain both stage outcomes before stopped-thread cleanup or flag resets.
            result = getattr(self.parse_thread, "last_parse_result", None)
            self._record_import_outcome(result)
            enrichment_result = getattr(self.parse_thread, "last_enrichment_result", None)
            enrichment_requested = self._embedded_enrichment_requested()
            feedback = _build_parse_completion_summary(
                result, self.db_file, enrichment_result, enrichment_requested=enrichment_requested,
            )
            should_request_modeless_enrichment = (
                not close_requested
                and not self.parse_error_message
                and not self.parsing_canceled
                and self._pending_modeless_metadata_enrichment
                and not enrichment_requested
            )
            self._dismiss_progress("loading")

            outcome_title, outcome_message = feedback[1:]
            if result is None:
                outcome_title = "Completion evidence unavailable"
                outcome_message = "Import outcome unavailable. Review the destination before retrying."
                if enrichment_requested:
                    outcome_message += "\n\n" + _enrichment_completion_group(enrichment_result)[1]
            if self.parse_error_message:
                outcome_title = "Import failed"
            elif self.parsing_canceled and result is None:
                outcome_title = "Import cancelled"
            self.report_planner.show_outcome(outcome_title + "\n\n" + outcome_message)
            if not close_requested and not self._external_context:
                self._show_parse_completion(feedback, enrichment_requested, should_request_modeless_enrichment)

            # Reset parse state flags
            self.parsing_canceled = False
            self.parse_error_message = None
            self._pending_modeless_metadata_enrichment = False

            if should_request_modeless_enrichment and not self._external_context:
                parent = self.parent()
                if parent is not None and hasattr(parent, "set_db_file"):
                    parent.set_db_file(self.db_file)

            # The destination changed, so require a fresh duplicate/content scan
            # before another import while keeping this dialog open for review.
            self._invalidate_preflight("Import finished. Refresh review before another import.")
            self._sync_readiness_state()

            if should_request_modeless_enrichment:
                self.metadata_enrichment_requested.emit(self.db_file)
        except Exception as e:
            self.log_and_exit(e)

    def _record_import_outcome(self, result):
        operation = getattr(self, "import_operation", None)
        if operation is not None and operation.worker is self.parse_thread:
            operation.result = result
            operation.failed = operation.failed or bool(self.parse_error_message) or bool(getattr(result, "failed_files", 0))
            operation.cancelled = self.parsing_canceled or bool(getattr(result, "cancelled_files", 0))

    def _show_parse_completion(self, feedback, enrichment_requested, should_request_modeless_enrichment):
        if self.parse_error_message:
            message = self.parse_error_message
            if enrichment_requested:
                message += "\n\n" + feedback[2]
            QMessageBox.warning(self, "Parsing failed", message)
        elif self.parsing_canceled and not enrichment_requested and (
            getattr(self.parse_thread, "last_parse_result", None) is None
            or getattr(
                self.parse_thread.last_parse_result,
                "cancelled_files",
                _MISSING_RESULT_FIELD,
            )
            is _MISSING_RESULT_FIELD
        ):
            QMessageBox.information(self, "Parsing canceled", "Parsing has been canceled")
        elif not should_request_modeless_enrichment:
            severity, title, message = feedback
            if severity == "warning":
                QMessageBox.warning(self, title, message)
            else:
                QMessageBox.information(self, title, message)

    @staticmethod
    def _thread_is_running(thread):
        if thread is None:
            return False
        try:
            return bool(thread.isRunning())
        except (AttributeError, RuntimeError):
            return False

    def _workers_running(self):
        return any(
            self._thread_is_running(thread)
            for thread in (self.preflight_thread, self.parse_thread, *self._metadata_threads)
        )

    def _drop_pending_starts(self):
        self._after_metadata_idle = []
        self._start_pending = False
        operation = getattr(self, "import_operation", None)
        if operation is not None and operation.worker is None and not operation.terminal and not operation.failed:
            operation.cancelled = operation.terminal = True

    def _request_active_worker_cancellation(self):
        self._drop_pending_starts()
        if self._thread_is_running(self.preflight_thread):
            self.stop_scanning()
        if self._thread_is_running(self.parse_thread):
            self.stop_parsing()
        self._cancel_metadata_workers()

    def _defer_close_for_active_workers(self):
        self._drop_pending_starts()
        if not self._workers_running():
            return False
        self._close_requested = True
        self._request_active_worker_cancellation()
        return True

    def is_close_deferred(self):
        """Return whether an active worker has accepted a deferred close request."""

        return bool(getattr(self, "_close_requested", False))

    def _complete_deferred_close_if_idle(self):
        if not getattr(self, "_close_requested", False) or self._workers_running():
            return
        self._close_requested = False
        self.shutdown_ready.emit()

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)

    def changeEvent(self, event):
        super().changeEvent(event)
        planner = getattr(self, "report_planner", None)
        if planner is not None and event.type() in (
            QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
        ):
            planner.refresh_theme()  # cell colours come from the live theme tokens


class ReportsWorkspace(_ReportOperations, QWidget):
    """Persistent embedded owner; the shell supplies authoritative context."""

    metadata_enrichment_requested = pyqtSignal(str)
    source_change_requested = pyqtSignal(str)
    database_change_requested = pyqtSignal(str)
    state_changed = pyqtSignal()
    shutdown_ready = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._initialize_report_operations(external_context=True)
        self.layout.setContentsMargins(0, 0, 0, 0)


class ParsingDialog(_ReportOperations, QDialog):
    """Standalone compatibility chrome over the same report operation host."""

    metadata_enrichment_requested = pyqtSignal(str)
    source_change_requested = pyqtSignal(str)
    database_change_requested = pyqtSignal(str)
    state_changed = pyqtSignal()
    shutdown_ready = pyqtSignal()

    def __init__(self, parent=None, directory=None, db_file=None):
        super().__init__(parent)
        self.setWindowTitle("Import reports")
        configure_window_size(self, minimum=(620, 440), initial=(1000, 680), screen_margin=32)
        self._initialize_report_operations(directory, db_file)
        self.shutdown_ready.connect(self.reject)

    def reject(self):
        if not self._defer_close_for_active_workers():
            super().reject()

    def closeEvent(self, event):
        if self._defer_close_for_active_workers():
            event.ignore()
            return
        super().closeEvent(event)
