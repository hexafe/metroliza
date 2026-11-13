"""Local viewer for validated, privacy-bounded diagnostic incidents."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from metroliza.shared.diagnostic_events import (
    StartupCallsite,
    StartupDiagnosticEvent,
    StartupOutcome,
    ValidationStatus,
    WorkflowDiagnosticEvent,
    WorkflowError,
    WorkflowOperation,
    WorkflowOutcome,
    WorkflowStage,
)
from metroliza.shared.diagnostic_incident import (
    MAX_COUNTER,
    MAX_ELAPSED_MS,
    ChannelState,
    DiagnosticIncident,
    HandshakeState,
    LaunchState,
    TerminationState,
)
from metroliza.shared.diagnostic_ring import RingLoss
from metroliza.shared.diagnostic_store import (
    IncidentStore,
    ReportRecord,
    StoreStatus,
)
from metroliza.shared.diagnostic_wire import WireValidationError, decode_event
from metroliza.ui.ui_foundation import apply_metroliza_theme, configure_window_size


_LOSS_REJECTED_FIELDS = (
    "invalid_events",
    "sequence_rejected_events",
    "normal_count_dropped_events",
    "normal_byte_dropped_events",
    "terminal_dropped_events",
)
_LOSS_EVICTED_FIELDS = (
    "count_evicted_events",
    "byte_evicted_events",
    "age_evicted_events",
    "operation_evicted_events",
)


class IncidentDialog(QDialog):
    """Render only closed fields from the validated local incident store."""

    def __init__(
        self,
        parent=None,
        *,
        store: IncidentStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = IncidentStore() if store is None else store
        self.setWindowTitle(self.tr("Diagnostic incidents"))
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())

        self.reports_table = QTableWidget(0, 5, self)
        self.reports_table.setHorizontalHeaderLabels(
            (
                self.tr("Incident"),
                self.tr("Recorded (UTC)"),
                self.tr("Build"),
                self.tr("History"),
                self.tr("Size"),
            )
        )
        self.reports_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.reports_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.reports_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.reports_table.verticalHeader().setVisible(False)
        header = self.reports_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(self.tr("Select a saved incident to see its safe summary."))

        self.unclean_list = QListWidget(self)
        self.unclean_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.unclean_list.setMaximumHeight(120)
        self.unclean_status_label = QLabel(self)
        self.unclean_status_label.setWordWrap(True)
        self.unclean_status_label.setProperty("secondary", True)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("secondary", True)
        self.refresh_button = QPushButton(self.tr("Refresh"), self)
        self.export_button = QPushButton(self.tr("Export selected"), self)
        self.export_button.setEnabled(False)
        close_button = QPushButton(self.tr("Close"), self)

        report_panel = QWidget(self)
        report_layout = QVBoxLayout(report_panel)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.addWidget(self._section_label(self.tr("Saved incidents")))
        report_layout.addWidget(self.reports_table, stretch=1)

        preview_panel = QWidget(self)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self._section_label(self.tr("Safe summary")))
        preview_layout.addWidget(self.preview, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(report_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        help_text = QLabel(
            self.tr(
                "Supervised launches can record bounded startup and workflow states. "
                "Direct launches do not create supervised incident reports. Exports contain "
                "only the selected safe incident and stay on this computer unless you share them."
            ),
            self,
        )
        help_text.setWordWrap(True)
        help_text.setProperty("secondary", True)

        footer = QHBoxLayout()
        footer.addWidget(self.status_label, stretch=1)
        footer.addWidget(self.refresh_button)
        footer.addWidget(self.export_button)
        footer.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(help_text)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self._section_label(self.tr("Sessions without a clean end marker")))
        layout.addWidget(self.unclean_status_label)
        layout.addWidget(self.unclean_list)
        layout.addLayout(footer)

        self.reports_table.itemSelectionChanged.connect(self._load_selected)
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button.clicked.connect(self._export_selected)
        close_button.clicked.connect(self.close)

        configure_window_size(self, minimum=(720, 520), initial=(920, 640))
        apply_metroliza_theme(self)
        self.refresh()

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setProperty("sectionLabel", True)
        return label

    def refresh(self) -> None:
        """Reload validated incident and marker metadata from private storage."""
        selected = self._selected_report_id()
        self.reports_table.blockSignals(True)
        self.reports_table.clearContents()
        self.reports_table.setRowCount(0)
        self.reports_table.blockSignals(False)
        self.preview.clear()
        self.export_button.setEnabled(False)

        try:
            listing = self.store.list_reports()
        except Exception:
            self.status_label.setText(self.tr("Incident storage is unavailable."))
        else:
            if listing.status is StoreStatus.AVAILABLE:
                self._populate_reports(listing.reports, selected)
                if not listing.reports:
                    self.status_label.setText(self.tr("No saved diagnostic incidents."))
            else:
                self.status_label.setText(self._list_status_text(listing.status))

        self._refresh_unclean_sessions()

    def _populate_reports(
        self,
        records: tuple[ReportRecord, ...],
        previous_selection: uuid.UUID | None,
    ) -> None:
        self.reports_table.blockSignals(True)
        self.reports_table.setRowCount(len(records))
        selected_row = 0
        for row, record in enumerate(records):
            identifier = QTableWidgetItem(record.report_id.hex)
            identifier.setData(Qt.ItemDataRole.UserRole, record.report_id)
            values = (
                identifier,
                QTableWidgetItem(self._utc_text(record.created_at_ms)),
                QTableWidgetItem(self._build_text(record.build_git_sha)),
                QTableWidgetItem(
                    self.tr("Incomplete") if record.lost_history else self.tr("Complete")
                ),
                QTableWidgetItem(self.tr("{count} bytes").format(count=record.size_bytes)),
            )
            for column, item in enumerate(values):
                self.reports_table.setItem(row, column, item)
            if previous_selection == record.report_id:
                selected_row = row
        self.reports_table.blockSignals(False)
        if records:
            self.reports_table.selectRow(selected_row)
            self._load_selected()

    def _refresh_unclean_sessions(self) -> None:
        self.unclean_list.clear()
        try:
            listing = self.store.list_unclean_sessions()
        except Exception:
            self.unclean_status_label.setText(
                self.tr("Session marker storage is unavailable.")
            )
            return
        if listing.status is not StoreStatus.AVAILABLE:
            self.unclean_status_label.setText(self._marker_status_text(listing.status))
            return
        if not listing.sessions:
            self.unclean_status_label.setText(self.tr("No unresolved session markers."))
            return
        self.unclean_status_label.setText(
            self.tr(
                "These sessions lack a verified clean end. Their cause is unknown; this is not "
                "proof that Metroliza crashed."
            )
        )
        for session in listing.sessions:
            self.unclean_list.addItem(
                self.tr("Session {session} — {time} — build {build}").format(
                    session=session.session_id.hex,
                    time=self._utc_text(session.created_at_ms),
                    build=self._build_text(session.build_git_sha),
                )
            )

    def _selected_report_id(self) -> uuid.UUID | None:
        row = self.reports_table.currentRow()
        if row < 0:
            return None
        item = self.reports_table.item(row, 0)
        if item is None:
            return None
        identifier = item.data(Qt.ItemDataRole.UserRole)
        return identifier if type(identifier) is uuid.UUID else None

    def _load_selected(self) -> None:
        identifier = self._selected_report_id()
        if identifier is None:
            self.preview.clear()
            self.export_button.setEnabled(False)
            return
        try:
            result = self.store.load(identifier)
        except Exception:
            self.preview.setPlainText(self.tr("The selected incident could not be validated."))
            self.status_label.setText(self.tr("Incident storage is unavailable."))
            self.export_button.setEnabled(False)
            return
        if result.status is not StoreStatus.AVAILABLE or result.incident is None:
            self.preview.setPlainText(self._load_status_text(result.status))
            self.status_label.setText(self._load_status_text(result.status))
            self.export_button.setEnabled(False)
            return
        rendered = self._render_incident(result.incident)
        if rendered is None:
            self.preview.setPlainText(self.tr("The selected incident could not be validated."))
            self.status_label.setText(self.tr("The selected incident is invalid."))
            self.export_button.setEnabled(False)
            return
        self.preview.setPlainText(rendered)
        self.status_label.setText(self.tr("Selected incident loaded."))
        self.export_button.setEnabled(True)

    def _render_incident(self, incident: DiagnosticIncident) -> str | None:
        event_objects: list[object] = []
        try:
            for payload in incident.events:
                event_objects.append(decode_event(payload))
        except (WireValidationError, TypeError, ValueError):
            return None

        observation = incident.observation
        launch = self._launch_text(observation.launch)
        handshake = self._handshake_text(observation.handshake)
        channel = self._channel_text(observation.channel)
        termination = self._termination_text(observation.termination)
        if None in (launch, handshake, channel, termination):
            return None

        lines = [
            self.tr("Incident: {identifier}").format(identifier=incident.report_id.hex),
            self.tr("Session: {identifier}").format(identifier=incident.session_id.hex),
            self.tr("Recorded: {time}").format(time=self._utc_text(incident.created_at_ms)),
            self.tr("Build: {build}").format(build=self._build_text(incident.build_git_sha)),
            "",
            self.tr("Launch: {state}").format(state=launch),
            self.tr("Handshake: {state}").format(state=handshake),
            self.tr("Diagnostic channel: {state}").format(state=channel),
            self.tr("Termination: {state}").format(state=termination),
            self.tr("Exit code: {value}").format(
                value=(
                    self.tr("Unavailable")
                    if observation.exit_code is None
                    else str(observation.exit_code)
                )
            ),
            self.tr("Elapsed: {count} ms").format(
                count=self._bounded_count(observation.elapsed_ms, MAX_ELAPSED_MS)
            ),
            self.tr("Clean terminal record: {value}").format(
                value=self.tr("Yes") if observation.clean_terminal_received else self.tr("No")
            ),
            self.tr("Source queue drops: {count}").format(
                count=self._bounded_count(observation.source_dropped, MAX_COUNTER)
            ),
            self.tr("Source loss known: {value}").format(
                value=self.tr("Yes") if observation.source_loss_known else self.tr("No")
            ),
            "",
        ]
        lines.extend(self._history_lines(incident.ring_loss, observation.channel, len(event_objects)))
        lines.extend(("", self.tr("Native stack: Unavailable")))
        lines.extend(("", *self._latest_event_lines(event_objects)))
        return "\n".join(lines)

    def _bounded_count(self, value: int, maximum: int) -> str:
        # V1 reserves each timing/source-loss ceiling as a lower bound. The
        # same interpretation applies to the raw values in the selected export.
        return self.tr("At least {count}").format(count=value) if value >= maximum else str(value)

    def _history_lines(
        self,
        loss: RingLoss,
        channel: ChannelState,
        event_count: int,
    ) -> list[str]:
        rejected = sum(getattr(loss, field) for field in _LOSS_REJECTED_FIELDS)
        evicted = sum(getattr(loss, field) for field in _LOSS_EVICTED_FIELDS)
        coalesced = loss.coalesced_events
        incomplete = (
            channel is not ChannelState.COMPLETE
            or rejected > 0
            or evicted > 0
            or coalesced > 0
            or loss.counters_saturated
        )
        return [
            self.tr("Recorded events: {count}").format(count=event_count),
            self.tr("Recording history: {state}").format(
                state=self.tr("Incomplete") if incomplete else self.tr("Complete")
            ),
            self.tr("Recorder rejected or dropped: {count}").format(count=rejected),
            self.tr("Recorder evicted by limits: {count}").format(count=evicted),
            self.tr("Progress events coalesced: {count}").format(count=coalesced),
            self.tr("Loss counters saturated: {value}").format(
                value=self.tr("Yes") if loss.counters_saturated else self.tr("No")
            ),
        ]

    def _latest_event_lines(self, events: list[object]) -> list[str]:
        workflow = next(
            (event for event in reversed(events) if type(event) is WorkflowDiagnosticEvent),
            None,
        )
        if workflow is not None:
            operation = self._workflow_operation_text(workflow.operation)
            stage = self._workflow_stage_text(workflow.stage)
            outcome = self._workflow_outcome_text(workflow.outcome)
            validation = self._validation_text(workflow.validation_status)
            error = self._workflow_error_text(workflow.error)
            if None in (operation, stage, outcome, validation, error):
                return [self.tr("Latest workflow state could not be validated.")]
            lines = [
                self.tr("Latest workflow: {operation}").format(operation=operation),
                self.tr("Workflow stage: {stage}").format(stage=stage),
                self.tr("Workflow outcome: {outcome}").format(outcome=outcome),
                self.tr("Workflow issue: {error}").format(error=error),
                self.tr("Domain validation: {status}").format(status=validation),
            ]
            if workflow.selected_report_count is not None:
                lines.append(
                    self.tr("Selected reports: {count}").format(
                        count=workflow.selected_report_count
                    )
                )
            if workflow.imported_report_count is not None:
                lines.append(
                    self.tr("Imported reports: {count}").format(
                        count=workflow.imported_report_count
                    )
                )
            if workflow.published_artifact_count is not None:
                lines.append(
                    self.tr("Published artifacts: {count}").format(
                        count=workflow.published_artifact_count
                    )
                )
            if workflow.duration_ms is not None:
                lines.append(
                    self.tr("Workflow duration: {count} ms").format(
                        count=self._bounded_count(workflow.duration_ms, MAX_ELAPSED_MS)
                    )
                )
            return lines

        startup = next(
            (event for event in reversed(events) if type(event) is StartupDiagnosticEvent),
            None,
        )
        if startup is not None:
            callsite = self._startup_callsite_text(startup.callsite)
            outcome = self._startup_outcome_text(startup.outcome)
            if callsite is None or outcome is None:
                return [self.tr("Latest startup state could not be validated.")]
            return [
                self.tr("Latest startup boundary: {boundary}").format(boundary=callsite),
                self.tr("Startup outcome: {outcome}").format(outcome=outcome),
                self.tr("Domain validation: No workflow validation result recorded"),
            ]
        return [
            self.tr("No startup or workflow boundary is available."),
            self.tr("Domain validation: No workflow validation result recorded"),
        ]

    def _export_selected(self) -> None:
        identifier = self._selected_report_id()
        if identifier is None:
            self.status_label.setText(self.tr("Select an incident before exporting."))
            return
        suggested = f"metroliza-incident-{identifier.hex}.zip"
        filename, _filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Export selected incident"),
            suggested,
            self.tr("ZIP archive (*.zip)"),
        )
        destination = Path(filename) if filename else None
        try:
            result = self.store.export(identifier, destination)
        except Exception:
            self.status_label.setText(self.tr("The incident could not be exported."))
            return
        self.status_label.setText(self._export_status_text(result.status))

    def _utc_text(self, created_at_ms: int) -> str:
        try:
            value = datetime.fromtimestamp(created_at_ms / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError, TypeError):
            return self.tr("Unavailable")
        return value.strftime("%Y-%m-%d %H:%M:%S UTC")

    def _build_text(self, build_git_sha: str) -> str:
        if build_git_sha == "unknown":
            return self.tr("Unknown")
        if len(build_git_sha) in (40, 64) and all(char in "0123456789abcdef" for char in build_git_sha):
            return build_git_sha
        return self.tr("Unavailable")

    def _launch_text(self, value: LaunchState) -> str | None:
        return {
            LaunchState.STARTED: self.tr("Started"),
            LaunchState.FAILED: self.tr("Failed to start"),
        }.get(value)

    def _handshake_text(self, value: HandshakeState) -> str | None:
        return {
            HandshakeState.MISSING: self.tr("Missing"),
            HandshakeState.REJECTED: self.tr("Rejected"),
            HandshakeState.ACCEPTED: self.tr("Accepted"),
        }.get(value)

    def _channel_text(self, value: ChannelState) -> str | None:
        return {
            ChannelState.COMPLETE: self.tr("Complete"),
            ChannelState.INCOMPLETE: self.tr("Incomplete"),
            ChannelState.INVALID: self.tr("Invalid"),
            ChannelState.FLOODED: self.tr("Flooded"),
            ChannelState.LOSS_OBSERVED: self.tr("Complete terminal record with recording loss"),
        }.get(value)

    def _termination_text(self, value: TerminationState) -> str | None:
        return {
            TerminationState.NOT_STARTED: self.tr("Not started"),
            TerminationState.OBSERVED_EXIT: self.tr("Exit observed"),
            TerminationState.POSIX_SIGNAL: self.tr("POSIX signal observed"),
            TerminationState.STILL_RUNNING: self.tr("Still running when captured"),
        }.get(value)

    def _workflow_operation_text(self, value: WorkflowOperation) -> str | None:
        return {
            WorkflowOperation.SELECTED_IMPORT: self.tr("Selected report import"),
            WorkflowOperation.LOCAL_EXPORT: self.tr("Local export"),
        }.get(value)

    def _workflow_stage_text(self, value: WorkflowStage) -> str | None:
        return {
            WorkflowStage.STARTED: self.tr("Started"),
            WorkflowStage.PREFLIGHT_COMPLETE: self.tr("Preflight complete"),
            WorkflowStage.PROCESSING: self.tr("Processing"),
            WorkflowStage.PERSISTENCE_COMPLETE: self.tr("Persistence complete"),
            WorkflowStage.OUTPUT_STAGING: self.tr("Output staging"),
            WorkflowStage.OUTPUT_PUBLISHED: self.tr("Output published"),
            WorkflowStage.FINISHED: self.tr("Finished"),
        }.get(value)

    def _workflow_outcome_text(self, value: WorkflowOutcome) -> str | None:
        return {
            WorkflowOutcome.STARTED: self.tr("Started"),
            WorkflowOutcome.MILESTONE: self.tr("Milestone observed"),
            WorkflowOutcome.COMPLETED: self.tr("Completed"),
            WorkflowOutcome.COMPLETED_WITH_FALLBACK: self.tr("Completed with fallback"),
            WorkflowOutcome.COMPLETED_WITH_OMISSIONS: self.tr("Completed with omissions"),
            WorkflowOutcome.COMPLETED_WITH_WARNINGS: self.tr("Completed with warnings"),
            WorkflowOutcome.CANCELLED: self.tr("Cancelled"),
            WorkflowOutcome.FAILED: self.tr("Failed"),
        }.get(value)

    def _validation_text(self, value: ValidationStatus) -> str | None:
        return {
            ValidationStatus.NOT_PERFORMED: self.tr("Not performed"),
            ValidationStatus.PASSED: self.tr("Passed"),
            ValidationStatus.FAILED: self.tr("Failed"),
        }.get(value)

    def _workflow_error_text(self, value: WorkflowError) -> str | None:
        return {
            WorkflowError.NONE: self.tr("None recorded"),
            WorkflowError.INPUT_REJECTED: self.tr("Input rejected"),
            WorkflowError.PROCESSING_FAILED: self.tr("Processing failed"),
            WorkflowError.PERSISTENCE_FAILED: self.tr("Persistence failed"),
            WorkflowError.OUTPUT_FAILED: self.tr("Output failed"),
            WorkflowError.UNKNOWN: self.tr("Unknown fixed error category"),
        }.get(value)

    def _startup_callsite_text(self, value: StartupCallsite) -> str | None:
        return {
            StartupCallsite.BOOTSTRAP: self.tr("Bootstrap"),
            StartupCallsite.LOGGING_INITIALIZE: self.tr("Logging initialization"),
            StartupCallsite.LOGGING_READY: self.tr("Logging ready"),
            StartupCallsite.CONFIG_LOAD: self.tr("Configuration load"),
            StartupCallsite.CONFIG_READY: self.tr("Configuration ready"),
            StartupCallsite.QAPPLICATION_REQUEST: self.tr("Application request"),
            StartupCallsite.QAPPLICATION_READY: self.tr("Application ready"),
            StartupCallsite.LICENSE_CHECK: self.tr("License check"),
            StartupCallsite.LICENSE_REJECTED: self.tr("License rejected"),
            StartupCallsite.MAIN_WINDOW_FACTORY: self.tr("Main window factory"),
            StartupCallsite.MAIN_WINDOW_CONSTRUCT: self.tr("Main window construction"),
            StartupCallsite.MAIN_WINDOW_SHOW_REQUEST: self.tr("Main window show request"),
            StartupCallsite.MAIN_WINDOW_SHOW_RETURNED: self.tr("Main window shown"),
            StartupCallsite.EVENT_LOOP_EXEC_REQUEST: self.tr("Event loop request"),
            StartupCallsite.SMOKE_WORK: self.tr("Smoke task"),
            StartupCallsite.SMOKE_RETURN: self.tr("Smoke task return"),
            StartupCallsite.APPLICATION_RETURN: self.tr("Application return"),
        }.get(value)

    def _startup_outcome_text(self, value: StartupOutcome) -> str | None:
        return {
            StartupOutcome.INVOCATION_STARTED: self.tr("Invocation started"),
            StartupOutcome.MILESTONE: self.tr("Milestone observed"),
            StartupOutcome.STARTUP_COMPLETED: self.tr("Startup completed"),
            StartupOutcome.STARTUP_REJECTED: self.tr("Startup rejected"),
            StartupOutcome.STARTUP_FAILED: self.tr("Startup failed"),
            StartupOutcome.APPLICATION_RETURNED: self.tr("Application returned"),
            StartupOutcome.APPLICATION_FAILED: self.tr("Application failed"),
        }.get(value)

    def _list_status_text(self, status: StoreStatus) -> str:
        return {
            StoreStatus.LOCK_UNAVAILABLE: self.tr("Incident storage is busy. Try again."),
            StoreStatus.ROOT_UNAVAILABLE: self.tr("Incident storage is unavailable."),
            StoreStatus.INVALID: self.tr("Incident storage failed validation."),
        }.get(status, self.tr("Incident storage is unavailable."))

    def _marker_status_text(self, status: StoreStatus) -> str:
        return {
            StoreStatus.LOCK_UNAVAILABLE: self.tr("Session marker storage is busy. Try again."),
            StoreStatus.ROOT_UNAVAILABLE: self.tr("Session marker storage is unavailable."),
            StoreStatus.INVALID: self.tr("Session marker storage failed validation."),
        }.get(status, self.tr("Session marker storage is unavailable."))

    def _load_status_text(self, status: StoreStatus) -> str:
        return {
            StoreStatus.NOT_FOUND: self.tr("The selected incident is no longer available."),
            StoreStatus.LOCK_UNAVAILABLE: self.tr("Incident storage is busy. Try again."),
            StoreStatus.ROOT_UNAVAILABLE: self.tr("Incident storage is unavailable."),
            StoreStatus.INVALID: self.tr("The selected incident could not be validated."),
        }.get(status, self.tr("The selected incident is unavailable."))

    def _export_status_text(self, status: StoreStatus) -> str:
        return {
            StoreStatus.EXPORTED: self.tr("The selected incident was exported locally."),
            StoreStatus.CANCELLED: self.tr("Export cancelled."),
            StoreStatus.DESTINATION_EXISTS: self.tr(
                "The destination already exists; no file was replaced."
            ),
            StoreStatus.LOCK_UNAVAILABLE: self.tr("Incident storage is busy. Try again."),
            StoreStatus.ROOT_UNAVAILABLE: self.tr("The export destination is unavailable."),
            StoreStatus.NOT_FOUND: self.tr("The selected incident is no longer available."),
            StoreStatus.INVALID: self.tr("The selected incident could not be validated."),
            StoreStatus.IO_FAILED: self.tr("The incident could not be exported."),
        }.get(status, self.tr("The incident could not be exported."))


def open_incident_viewer(
    parent=None,
    *,
    store: IncidentStore | None = None,
) -> IncidentDialog:
    """Show and return the local diagnostic incident viewer."""
    dialog = IncidentDialog(parent, store=store)
    dialog.show()
    return dialog
