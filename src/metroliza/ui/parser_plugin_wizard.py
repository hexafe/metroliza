"""Small UI for declarative parser profile self-service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

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

from metroliza.parsing.declarative_parser_profiles import (
    ensure_profile_store_dirs,
    list_profiles,
    profile_store_root,
    render_profile_template,
)
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


@dataclass(frozen=True)
class ProfileStoreSummary:
    root: Path
    total: int
    enabled: int
    approved: int
    disabled: int


@dataclass(frozen=True)
class HandoffWorkspace:
    root: Path
    profile_path: Path
    handoff_path: Path
    expected_results_path: Path


def safe_profile_id(value: str) -> str:
    """Return the filesystem/profile id used for a new handoff workspace."""
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().casefold()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"supplier_{normalized or 'profile'}"
    if len(normalized) < 3:
        normalized = f"{normalized}_profile"
    return normalized[:64]


def summarize_profile_store(*, home: Path | None = None) -> ProfileStoreSummary:
    ensure_profile_store_dirs(home=home)
    profiles = list_profiles(home=home)
    enabled = sum(1 for profile in profiles if profile.enabled)
    approved = sum(1 for profile in profiles if profile.approved)
    disabled = sum(1 for profile in profiles if not profile.enabled)
    return ProfileStoreSummary(
        root=profile_store_root(home=home),
        total=len(profiles),
        enabled=enabled,
        approved=approved,
        disabled=disabled,
    )


def create_llm_handoff_workspace(
    *,
    plugin_id: str,
    display_name: str,
    source_format: str,
    home: Path | None = None,
) -> HandoffWorkspace:
    """Create a data-only profile handoff folder for an external LLM workflow."""
    safe_id = safe_profile_id(plugin_id)
    readable_name = display_name.strip() or safe_id.replace("_", " ").title()
    root = profile_store_root(home=home) / "incoming" / safe_id
    samples_dir = root / "samples"
    root.mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(exist_ok=True)

    profile_path = root / "profile.yaml"
    expected_results_path = root / "expected_results.csv"
    handoff_path = root / "llm_handoff.md"

    if not profile_path.exists():
        profile_path.write_text(
            render_profile_template(
                plugin_id=safe_id,
                display_name=readable_name,
                source_format=source_format,
            ),
            encoding="utf-8",
        )
    if not expected_results_path.exists():
        expected_results_path.write_text(
            "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
            "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n",
            encoding="utf-8",
        )
    expected_columns = (
        "sample_file, reference, report_date, sample_number, block_index, header_normalized, "
        "axis_code, nominal, tol_plus, tol_minus, bonus, measured, deviation, out_of_tolerance"
    )
    handoff_path.write_text(
        "\n".join(
            [
                f"# Parser Profile Handoff: {readable_name}",
                "",
                "Use an approved external LLM workflow or manual review to complete profile.yaml.",
                "Do not paste private reports into an external tool unless your release owner approves it.",
                "",
                "Give the reviewer or assistant:",
                "",
                "- profile.yaml",
                "- 3-5 reports from samples/",
                "- expected_results.csv with manually checked values",
                "- supplier/template notes, including visible labels, date format, and decimal separator",
                "",
                "Ask for a declarative Metroliza parser profile only.",
                "Do not ask for Python code, package changes, network calls, or installer changes.",
                "",
                "Required profile contract:",
                "",
                "- schema_version: 1",
                "- plugin.plugin_id must stay as " + safe_id,
                "- plugin.source_format must stay as " + source_format,
                "- probe.required_markers must contain supplier/template text visible in every sample",
                "- extraction.report_fields must extract reference, report_date, and sample_number",
                "- extraction.blocks[].pattern must be line-anchored with ^",
                "- measurement row capture names: axis_code, nominal, tol_plus, tol_minus, bonus, measured, deviation, out_of_tolerance",
                "- regexes must avoid Python code, backreferences, nested repeats, and unbounded dot wildcards",
                "",
                "expected_results.csv columns:",
                "",
                expected_columns,
                "",
                "Validation and install commands from the Metroliza source checkout:",
                "",
                (
                    f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py validate "{profile_path}" '
                    f'--expected-results "{expected_results_path}" --workspace "{root}"'
                ),
                (
                    f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py diagnose "{profile_path}" '
                    f'"{samples_dir}/<sample-file>"'
                ),
                (
                    f'PYTHONPATH=src:. python scripts/parser_plugin_self_service.py install "{profile_path}" '
                    f'--expected-results "{expected_results_path}" --workspace "{root}" --approved-by <approver>'
                ),
                "PYTHONPATH=src:. python scripts/parser_plugin_self_service.py evidence " + safe_id,
                "",
                "Acceptance criteria:",
                "",
                "- validation passes with at least one sample report and expected_results.csv",
                "- diagnose selects this profile and shows the expected reference/date/sample values",
                "- the profile stays data-only YAML",
                "- approval evidence records validation_passed=true, sample_count greater than zero, and matching checksums",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return HandoffWorkspace(
        root=root,
        profile_path=profile_path,
        handoff_path=handoff_path,
        expected_results_path=expected_results_path,
    )


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
        self.refresh_button = QPushButton("Refresh")
        self.close_button = QPushButton("Close")
        self.result_label = status_chip("No handoff folder created yet", "neutral")
        self.open_folder_button.setEnabled(False)
        self.copy_path_button.setEnabled(False)

        self._build_layout()
        self.refresh_status()
        apply_metroliza_theme(self)

    def _build_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

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
        layout.addWidget(self.result_label)

        self.refresh_button.clicked.connect(self.refresh_status)
        self.create_button.clicked.connect(self.create_handoff_workspace)
        self.open_folder_button.clicked.connect(self.open_handoff_folder)
        self.copy_path_button.clicked.connect(self.copy_handoff_path)
        self.close_button.clicked.connect(self.accept)

        configure_accessibility(self.plugin_id_edit, name="Parser profile id")
        configure_accessibility(self.display_name_edit, name="Parser profile display name")
        configure_accessibility(self.source_format_combo, name="Parser profile source type")
        configure_accessibility(self.create_button, name="Create parser profile handoff folder")
        configure_accessibility(self.open_folder_button, name="Open parser profile handoff folder")
        configure_accessibility(self.copy_path_button, name="Copy parser profile handoff folder path")

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
        self.open_folder_button.setEnabled(True)
        self.copy_path_button.setEnabled(True)
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
