"""Small UI for declarative parser profile self-service."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from metroliza.parsing.declarative_parser_profiles import list_profiles
from metroliza.parsing.parser_profile_handoff import (
    HandoffWorkspace,
    create_profile_handoff_workspace,
    format_handoff_integrity_report,
    install_profile_handoff,
    safe_profile_id,
    summarize_profile_store,
    validate_handoff_workspace,
    write_profile_diagnose_artifact,
    write_profile_repair_prompt,
    write_profile_validation_artifact,
)
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    secondary_label,
    section_label,
    separator,
    set_status_variant,
    status_chip,
)


create_llm_handoff_workspace = create_profile_handoff_workspace


class ParserPluginWizardDialog(QDialog):
    """Non-technical launcher for declarative parser profile handoff work."""

    def __init__(self, parent=None, *, home: Path | None = None):
        super().__init__(parent)
        self.home = home
        self.last_handoff_workspace: HandoffWorkspace | None = None
        self.setWindowTitle("Parser Profiles")
        configure_window_size(self, minimum=(520, 420), initial=(620, 520))

        self.store_status_label = status_chip("", "neutral")
        self.store_path_label = secondary_label("")
        self.profile_list = QListWidget()
        self.profile_list.setMinimumHeight(120)

        self.plugin_id_edit = QLineEdit()
        self.plugin_id_edit.setPlaceholderText("supplier_alpha")
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setPlaceholderText("Supplier Alpha")
        self.source_format_combo = QComboBox()
        self.source_format_combo.addItems(["pdf", "excel", "csv"])
        self.create_button = QPushButton("Create Handoff Folder")
        self.open_folder_button = QPushButton("Open Folder")
        self.copy_path_button = QPushButton("Copy Path")
        self.check_package_button = QPushButton("Check Package")
        self.validate_button = QPushButton("Validate")
        self.diagnose_button = QPushButton("Diagnose")
        self.repair_button = QPushButton("Repair Prompt")
        self.install_button = QPushButton("Install")
        self.refresh_button = QPushButton("Refresh")
        self.close_button = QPushButton("Close")
        self.result_label = status_chip("No handoff folder created yet", "neutral")
        self._set_handoff_actions_enabled(False)

        self._build_layout()
        self.refresh_status()
        apply_metroliza_theme(self)

    def _build_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("Parser profiles manual", "parser_profiles")])

        layout.addWidget(section_label("Profile store"))
        layout.addWidget(self.store_status_label)
        layout.addWidget(self.store_path_label)
        layout.addWidget(self.profile_list)

        layout.addWidget(separator())
        layout.addWidget(section_label("New supplier template"))
        layout.addWidget(
            secondary_label(
                "Create a local handoff folder for samples, checked values, and a data-only profile template."
            )
        )

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("Profile id", self.plugin_id_edit)
        form.addRow("Display name", self.display_name_edit)
        form.addRow("Source type", self.source_format_combo)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addWidget(self.refresh_button)
        button_row.addStretch(1)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.copy_path_button)
        button_row.addWidget(self.create_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        validation_row = QHBoxLayout()
        validation_row.addStretch(1)
        validation_row.addWidget(self.check_package_button)
        validation_row.addWidget(self.validate_button)
        validation_row.addWidget(self.diagnose_button)
        validation_row.addWidget(self.repair_button)
        validation_row.addWidget(self.install_button)
        layout.addLayout(validation_row)
        layout.addWidget(self.result_label)

        self.refresh_button.clicked.connect(self.refresh_status)
        self.create_button.clicked.connect(self.create_handoff_workspace)
        self.open_folder_button.clicked.connect(self.open_handoff_folder)
        self.copy_path_button.clicked.connect(self.copy_handoff_path)
        self.check_package_button.clicked.connect(self.check_handoff_package)
        self.validate_button.clicked.connect(self.validate_handoff_profile)
        self.diagnose_button.clicked.connect(self.diagnose_handoff_profile)
        self.repair_button.clicked.connect(self.create_repair_prompt)
        self.install_button.clicked.connect(self.install_handoff_profile)
        self.close_button.clicked.connect(self.accept)

        configure_accessibility(self.plugin_id_edit, name="Parser profile id")
        configure_accessibility(self.display_name_edit, name="Parser profile display name")
        configure_accessibility(self.source_format_combo, name="Parser profile source type")
        configure_accessibility(self.create_button, name="Create parser profile handoff folder")
        configure_accessibility(self.open_folder_button, name="Open parser profile handoff folder")
        configure_accessibility(self.copy_path_button, name="Copy parser profile handoff folder path")
        configure_accessibility(self.check_package_button, name="Check parser profile handoff package")
        configure_accessibility(self.validate_button, name="Validate parser profile handoff")
        configure_accessibility(self.diagnose_button, name="Diagnose parser profile handoff")
        configure_accessibility(self.repair_button, name="Create parser profile repair prompt")
        configure_accessibility(self.install_button, name="Install approved parser profile")

    def _set_handoff_actions_enabled(self, enabled: bool):
        for button in (
            self.open_folder_button,
            self.copy_path_button,
            self.check_package_button,
            self.validate_button,
            self.diagnose_button,
            self.repair_button,
            self.install_button,
        ):
            button.setEnabled(enabled)

    def refresh_status(self):
        summary = summarize_profile_store(home=self.home)
        self.store_status_label.setText(
            f"{summary.enabled} enabled, {summary.disabled} disabled, {summary.total} total"
        )
        set_status_variant(self.store_status_label, "success" if summary.enabled else "neutral")
        self.store_path_label.setText(f"Store: {summary.root}")
        self.profile_list.clear()
        profiles = list_profiles(home=self.home)
        if not profiles:
            self.profile_list.addItem("No approved parser profiles yet")
            return
        for profile in profiles:
            state = "enabled" if profile.enabled else "disabled"
            approval = "approved" if profile.approved else "needs approval"
            detail = f" - {profile.detail}" if profile.detail and profile.detail != approval else ""
            self.profile_list.addItem(f"{profile.plugin_id}: {state}, {approval}{detail}")

    def create_handoff_workspace(self):
        plugin_id = safe_profile_id(self.plugin_id_edit.text())
        self.plugin_id_edit.setText(plugin_id)
        workspace = create_llm_handoff_workspace(
            plugin_id=plugin_id,
            display_name=self.display_name_edit.text(),
            source_format=self.source_format_combo.currentText(),
            home=self.home,
        )
        self.last_handoff_workspace = workspace
        self._set_handoff_actions_enabled(True)
        self.result_label.setText(f"Handoff folder ready. Add reports to samples/: {workspace.root}")
        set_status_variant(self.result_label, "success")
        self.refresh_status()

    def open_handoff_folder(self):
        if self.last_handoff_workspace is None:
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_handoff_workspace.root)))
        if not opened:
            self.result_label.setText(f"Could not open folder. Path: {self.last_handoff_workspace.root}")
            set_status_variant(self.result_label, "warning")

    def copy_handoff_path(self):
        if self.last_handoff_workspace is None:
            return
        QApplication.clipboard().setText(str(self.last_handoff_workspace.root))
        self.result_label.setText(f"Copied handoff folder path: {self.last_handoff_workspace.root}")
        set_status_variant(self.result_label, "success")

    def _current_workspace(self) -> HandoffWorkspace | None:
        if self.last_handoff_workspace is None:
            self.result_label.setText("No handoff folder created yet")
            set_status_variant(self.result_label, "neutral")
            return None
        return self.last_handoff_workspace

    def check_handoff_package(self):
        workspace = self._current_workspace()
        if workspace is None:
            return
        report = validate_handoff_workspace(workspace.root)
        output = workspace.root / "artifacts" / "handoff_integrity.txt"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(format_handoff_integrity_report(report) + "\n", encoding="utf-8")
        if report.passed:
            self.result_label.setText(f"Package check passed. Evidence: {output}")
            set_status_variant(self.result_label, "success")
        else:
            self.result_label.setText(f"Package check failed. Evidence: {output}")
            set_status_variant(self.result_label, "warning")

    def validate_handoff_profile(self):
        workspace = self._current_workspace()
        if workspace is None:
            return
        output, passed = write_profile_validation_artifact(workspace)
        if passed:
            self.result_label.setText(f"Validation passed. Evidence: {output}")
            set_status_variant(self.result_label, "success")
        else:
            self.result_label.setText(f"Validation failed. Evidence: {output}")
            set_status_variant(self.result_label, "warning")

    def diagnose_handoff_profile(self):
        workspace = self._current_workspace()
        if workspace is None:
            return
        try:
            output = write_profile_diagnose_artifact(workspace)
        except (FileNotFoundError, ValueError) as exc:
            self.result_label.setText(str(exc))
            set_status_variant(self.result_label, "warning")
            return
        self.result_label.setText(f"Diagnose evidence written: {output}")
        set_status_variant(self.result_label, "success")

    def create_repair_prompt(self):
        workspace = self._current_workspace()
        if workspace is None:
            return
        output = write_profile_repair_prompt(workspace)
        self.result_label.setText(f"Repair prompt written: {output}")
        set_status_variant(self.result_label, "success")

    def install_handoff_profile(self):
        workspace = self._current_workspace()
        if workspace is None:
            return
        try:
            result = install_profile_handoff(workspace, approved_by="wizard", home=self.home)
        except ValueError as exc:
            self.result_label.setText(str(exc))
            set_status_variant(self.result_label, "warning")
            return
        self.result_label.setText(f"Installed profile: {result.plugin_id}")
        set_status_variant(self.result_label, "success")
        self.refresh_status()
