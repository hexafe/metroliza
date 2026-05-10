"""Oznak production-line connection test and reference-scoped sync dialog."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from modules.industrial_data_repository import IndustrialDataRepository, IndustrialSourceProfile
from modules.industrial_filter_dialog import IndustrialFilterDialog
from modules.industrial_workflow_state import IndustrialFilterState
from modules.industrial_workers import IndustrialOznakSyncThread
from modules.ui_foundation import (
    apply_metroliza_theme,
    configure_window_size,
    section_label,
    set_status_variant,
    status_chip,
)


class IndustrialSyncDialog(QDialog):
    """Run production-line connection checks and reference-scoped industrial syncs."""

    def __init__(
        self,
        parent=None,
        *,
        db_file: str | None = None,
        filter_state: IndustrialFilterState | None = None,
    ):
        super().__init__(parent)
        self.db_file = db_file
        self.filter_state = filter_state or IndustrialFilterState()
        self.filter_window = None
        self.oznak_sync_thread = None
        self._loading_profiles = False
        self.setWindowTitle("Sync industrial data")
        configure_window_size(self, minimum=(560, 360), initial=(680, 420))

        self.status_label = status_chip(
            "Select a production source and enter production database credentials.",
            "neutral",
        )
        self.profile_combo = QComboBox()
        self.filter_status_label = status_chip(self.filter_state.summary(), "neutral")

        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 1_000_000)
        self.limit_spin.setValue(5000)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 3600)
        self.timeout_spin.setValue(30)

        self.username_edit.setPlaceholderText("production database username")
        self.password_edit.setPlaceholderText("not stored")

        self.edit_filter_button = QPushButton("Edit filter...")
        self.test_connection_button = QPushButton("Test connection")
        self.sync_now_button = QPushButton("Sync now")
        self.cancel_sync_button = QPushButton("Cancel")
        self.close_button = QPushButton("Close")

        self.edit_filter_button.clicked.connect(self.open_filter_dialog)
        self.test_connection_button.clicked.connect(self.test_connection)
        self.sync_now_button.clicked.connect(self.sync_now)
        self.cancel_sync_button.clicked.connect(self.cancel_sync)
        self.close_button.clicked.connect(self.reject)
        self.cancel_sync_button.setEnabled(False)

        self._build_layout()
        self.reload_profiles()
        self._sync_filter_status()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(section_label("Production line connection test and sync"))
        layout.addWidget(self.status_label)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setSpacing(8)
        form.addRow("Production source", self.profile_combo)
        form.addRow("Production DB username", self.username_edit)
        form.addRow("Production DB password", self.password_edit)
        form.addRow("Production row limit", self.limit_spin)
        form.addRow("Query timeout seconds", self.timeout_spin)
        layout.addLayout(form)

        filter_row = QGridLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setHorizontalSpacing(8)
        filter_row.addWidget(self.filter_status_label, 0, 0)
        filter_row.addWidget(self.edit_filter_button, 0, 1)
        filter_row.setColumnStretch(0, 1)
        layout.addLayout(filter_row)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        actions.addWidget(self.test_connection_button)
        actions.addWidget(self.sync_now_button)
        actions.addWidget(self.cancel_sync_button)
        layout.addLayout(actions)

    def reload_profiles(self) -> None:
        if not self.db_file or self._loading_profiles:
            self._set_ready_state(
                False,
                "Select a Metroliza report database first so synced production rows have a local cache.",
            )
            return
        self._loading_profiles = True
        self.profile_combo.clear()
        try:
            profiles = IndustrialDataRepository(self.db_file).list_source_profiles()
        except Exception as exc:
            profiles = []
            self.status_label.setText(f"Could not load sources: {exc}")
            set_status_variant(self.status_label, "warning")
        for profile in profiles:
            self.profile_combo.addItem(profile.profile_name, profile)
        self._loading_profiles = False
        if profiles:
            self._set_ready_state(
                True,
                "Production source selected. Enter credentials for this session.",
            )
        else:
            self._set_ready_state(False, "Create a production source before syncing.")

    def _set_ready_state(self, enabled: bool, message: str) -> None:
        self.status_label.setText(message)
        set_status_variant(self.status_label, "neutral" if enabled else "warning")
        for button in (self.edit_filter_button, self.test_connection_button, self.sync_now_button):
            button.setEnabled(enabled)

    def current_profile(self) -> IndustrialSourceProfile | None:
        profile = self.profile_combo.currentData()
        return profile if isinstance(profile, IndustrialSourceProfile) else None

    def _profile_for_current_filter(self) -> IndustrialSourceProfile:
        profile = self.current_profile()
        if profile is None:
            raise ValueError("Create or select a production source before syncing.")
        filter_column = self.filter_state.reference_column
        if not filter_column or filter_column in profile.allowed_columns:
            return profile
        return replace(profile, allowed_columns=(*profile.allowed_columns, filter_column))

    def _read_credentials(self) -> tuple[str, str]:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username:
            raise ValueError("Enter the production database username for this session.")
        if not password:
            raise ValueError("Enter the production database password for this session.")
        return username, password

    def get_industrial_filter_state(self) -> IndustrialFilterState:
        return self.filter_state

    def set_industrial_filter_state(self, state: IndustrialFilterState) -> None:
        self.filter_state = state
        parent = self.parent()
        if parent is not None and hasattr(parent, "set_sync_filter_state"):
            parent.set_sync_filter_state(state)
        self._sync_filter_status()

    def _sync_filter_status(self) -> None:
        self.filter_status_label.setText(self.filter_state.summary())
        set_status_variant(
            self.filter_status_label,
            "success" if self.filter_state.is_applied else "warning",
        )

    def open_filter_dialog(self) -> None:
        self.filter_window = IndustrialFilterDialog(self, db_file=self.db_file, state=self.filter_state)
        self.filter_window.exec()

    def test_connection(self) -> None:
        self._start_oznak_operation(test_only=True)

    def sync_now(self) -> None:
        self._start_oznak_operation(test_only=False)

    def cancel_sync(self) -> None:
        thread = self.oznak_sync_thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            self.status_label.setText("Cancelling industrial sync...")
            set_status_variant(self.status_label, "neutral")

    def _start_oznak_operation(self, *, test_only: bool) -> None:
        if self.oznak_sync_thread is not None and self.oznak_sync_thread.isRunning():
            self.status_label.setText("Industrial sync already running")
            set_status_variant(self.status_label, "neutral")
            return
        try:
            profile = self._profile_for_current_filter()
            username, password = self._read_credentials()
            if not test_only:
                self.filter_state.validate_for_sync()
        except ValueError as exc:
            QMessageBox.warning(self, "Industrial sync", str(exc))
            return

        action = "Testing production database connection" if test_only else "Syncing production data"
        self.status_label.setText(f"{action}...")
        set_status_variant(self.status_label, "neutral")
        self._set_action_buttons_enabled(False)
        self.cancel_sync_button.setEnabled(True)
        self.oznak_sync_thread = IndustrialOznakSyncThread(
            db_file=str(self.db_file),
            profile=profile,
            username=username,
            password=password,
            limit=self.limit_spin.value(),
            timeout_seconds=self.timeout_spin.value(),
            reference_filter_column=self.filter_state.reference_column if self.filter_state.references else None,
            reference_values=self.filter_state.references,
            test_only=test_only,
        )
        self.oznak_sync_thread.progress_message.connect(self.on_oznak_progress)
        self.oznak_sync_thread.result_ready.connect(self.on_oznak_result)
        self.oznak_sync_thread.error_occurred.connect(self.on_oznak_error)
        self.oznak_sync_thread.finished.connect(self.on_oznak_thread_stopped)
        self.oznak_sync_thread.start()

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self.edit_filter_button,
            self.test_connection_button,
            self.sync_now_button,
            self.close_button,
        ):
            button.setEnabled(enabled)

    def on_oznak_progress(self, message: str) -> None:
        self.status_label.setText(str(message))
        set_status_variant(self.status_label, "neutral")

    def on_oznak_result(self, result: dict[str, Any]) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_status"):
            parent.refresh_status()
        if result["status"] != "succeeded":
            self.status_label.setText(
                "Connection test failed" if result["test_only"] else "Industrial sync failed"
            )
            set_status_variant(self.status_label, "danger")
            return
        if result["test_only"]:
            self.status_label.setText(f"Connection test passed ({result['row_count']} rows visible)")
            set_status_variant(self.status_label, "success")
            return
        upsert_summary = result.get("upsert_summary") or {}
        link_summary = result.get("link_summary")
        link_text = ""
        if link_summary is not None:
            link_text = (
                f", {link_summary.accepted_links} links, "
                f"{link_summary.ambiguous_reports} ambiguous"
            )
        self.status_label.setText(
            f"Sync complete: {upsert_summary.get('processed', result['row_count'])} rows{link_text}"
        )
        set_status_variant(self.status_label, "success")

    def on_oznak_error(self, message: str) -> None:
        QMessageBox.warning(self, "Industrial sync", f"Oznak operation failed: {message}")
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_status"):
            parent.refresh_status()

    def on_oznak_thread_stopped(self) -> None:
        has_source = self.current_profile() is not None
        self._set_action_buttons_enabled(has_source)
        self.cancel_sync_button.setEnabled(False)
        self.oznak_sync_thread = None

    def closeEvent(self, event) -> None:
        thread = self.oznak_sync_thread
        if thread is not None and thread.isRunning():
            QMessageBox.information(self, "Industrial sync", "Cancel or wait for the sync to finish.")
            event.ignore()
            return
        super().closeEvent(event)
