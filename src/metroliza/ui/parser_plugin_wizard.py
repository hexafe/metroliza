"""Small UI for declarative parser profile self-service."""

from __future__ import annotations

from pathlib import Path, PosixPath, WindowsPath
from time import monotonic
from types import MethodType

from PyQt6.QtCore import QThread, QUrl, Qt
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from metroliza.parsing.declarative_parser_profiles import disable_profile, enable_profile, list_profiles
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
from metroliza.ui.shortcuts import bind_shortcut, visible_shortcut
from metroliza.ui import detached_threads
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_accessibility,
    configure_window_size,
    secondary_label,
    section_label,
    set_status_variant,
    status_chip,
)
from metroliza.ui.worker_progress_dialog import (
    create_delayed_worker_progress_dialog,
    dismiss_worker_progress_dialog,
)


create_llm_handoff_workspace = create_profile_handoff_workspace


def _native_dialog_state(dialog):
    if type(dialog) is not ParserPluginWizardDialog:
        return None
    state = dialog.__dict__
    keys = tuple(state)
    return state if all(type(key) is str for key in keys) else None


def _native_validation_widget(widget, cls, methods):
    if type(widget) is not cls:
        return False
    state = widget.__dict__
    if any(type(key) is not str for key in tuple(state)):
        return False
    return not any(name in state for name in methods)


class _ProfileValidationThread(QThread):
    """Own one immutable workspace request through the unchanged artifact writer."""

    def __init__(self, workspace, source_workspace, writer):
        super().__init__()
        self.workspace = workspace
        self.source_workspace = source_workspace
        self.writer = writer
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.writer(self.workspace)
        except Exception as error:
            self.error = error

    def release(self):
        detached_threads.discard(self)
        self.deleteLater()


class ParserPluginWizardDialog(QDialog):
    """Non-technical launcher for declarative parser profile handoff work."""

    def __init__(self, parent=None, *, home: Path | None = None):
        super().__init__(parent)
        self.home = home
        self.last_handoff_workspace: HandoffWorkspace | None = None
        self._validation_thread = None
        self._validation_progress = None
        self._validation_closed = False
        self.setWindowTitle("Parser Profiles")
        configure_window_size(self, minimum=(560, 480), initial=(760, 680))

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
        self.result_label.setWordWrap(True)
        self.stage_label = status_chip("1 · Prepare a new format", "info")
        self.validation_status_label = status_chip("Last validation: not run", "neutral")
        self.package_status_label = secondary_label("Last package check: not run")
        self.next_action_label = secondary_label("Prepare local materials; a handoff folder is not approval.")
        self.next_action_label.setWordWrap(True)
        self.next_button = QPushButton("Next: Prepare folder")
        self._next_control = self.create_button
        self.enable_button = QPushButton("Enable selected")
        self.disable_button = QPushButton("Disable selected")
        self.manage_status_label = status_chip("Select an installed profile to manage its enabled state.", "neutral")
        self.manage_status_label.setWordWrap(True)
        self._set_handoff_actions_enabled(False)

        self._build_layout()
        self.refresh_status()
        apply_metroliza_theme(self)

    def _build_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        attach_help_menu_to_layout(layout, self, [("Parser profiles manual", "parser_profiles")])
        self.task_tabs = QTabWidget()
        manage = QWidget()
        manage_layout = QVBoxLayout(manage)
        manage_layout.addWidget(section_label("Manage installed profiles"))
        manage_layout.addWidget(self.store_status_label)
        self.store_path_label.setWordWrap(True)
        manage_layout.addWidget(self.store_path_label)
        manage_layout.addWidget(self.profile_list, 1)
        manage_layout.addWidget(self.manage_status_label)
        manage_actions = QGridLayout()
        manage_actions.addWidget(self.enable_button, 0, 0)
        manage_actions.addWidget(self.disable_button, 0, 1)
        manage_actions.addWidget(self.refresh_button, 1, 0, 1, 2)
        manage_layout.addLayout(manage_actions)
        self.task_tabs.addTab(manage, "Manage installed profiles")

        add = QWidget()
        add_layout = QVBoxLayout(add)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        form_layout = QVBoxLayout(body)
        required = secondary_label(
            "Required: sanitized samples in samples/, completed profile.yaml, checked rows in "
            "expected_results.csv, and template notes (language, date/decimal formats, units). "
            "Keep contract/manifest files intact. Share samples only with explicit authorization."
        )
        required.setWordWrap(True)
        form_layout.addWidget(section_label("Add a new format · Prepare → Check / Validate → Install / Enable"))
        form_layout.addWidget(required)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("Profile id", self.plugin_id_edit)
        form.addRow("Display name", self.display_name_edit)
        form.addRow("Source type", self.source_format_combo)
        form_layout.addLayout(form)
        actions = QGridLayout()
        for index, button in enumerate((self.create_button, self.open_folder_button, self.copy_path_button,
                                        self.check_package_button, self.validate_button, self.install_button,
                                        self.diagnose_button, self.repair_button)):
            actions.addWidget(button, index // 2, index % 2)
        form_layout.addLayout(actions)
        form_layout.addStretch(1)
        scroll.setWidget(body)
        self.add_scroll_area = scroll
        add_layout.addWidget(scroll, 1)
        for label in (self.stage_label, self.package_status_label, self.validation_status_label,
                      self.next_action_label, self.result_label):
            add_layout.addWidget(label)
        add_layout.addWidget(self.next_button)
        self.task_tabs.addTab(add, "Add a new format")
        layout.addWidget(self.task_tabs, 1)
        footer = QHBoxLayout()
        legend = secondary_label("Manage Ctrl+Shift+D · Add Ctrl+Shift+A · Next Ctrl+S")
        legend.setWordWrap(True)
        footer.addWidget(legend, 1)
        footer.addStretch(1)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)

        self.refresh_button.clicked.connect(self.refresh_status)
        self.create_button.clicked.connect(self.create_handoff_workspace)
        self.open_folder_button.clicked.connect(self.open_handoff_folder)
        self.copy_path_button.clicked.connect(self.copy_handoff_path)
        self.check_package_button.clicked.connect(self.check_handoff_package)
        self.validate_button.clicked.connect(self.validate_handoff_profile)
        self.diagnose_button.clicked.connect(self.diagnose_handoff_profile)
        self.repair_button.clicked.connect(self.create_repair_prompt)
        self.install_button.clicked.connect(self.install_handoff_profile)
        self.enable_button.clicked.connect(lambda: self._change_installed_state(True))
        self.disable_button.clicked.connect(lambda: self._change_installed_state(False))
        self.profile_list.currentItemChanged.connect(self._sync_manage_actions)
        self.next_button.clicked.connect(lambda: self._next_control.click())
        self.close_button.clicked.connect(self.accept)
        order = (self.profile_list, self.enable_button, self.disable_button, self.refresh_button,
                 self.plugin_id_edit, self.display_name_edit, self.source_format_combo, self.create_button,
                 self.open_folder_button, self.copy_path_button, self.check_package_button, self.validate_button,
                 self.install_button, self.diagnose_button, self.repair_button, self.next_button, self.close_button)
        for first, second in zip(order, order[1:]):
            self.setTabOrder(first, second)
        self._configure_commands()
        self._configure_accessibility()
        self._show_stage("1 · Prepare a new format", self.create_button,
                         "Prepare local materials; a handoff folder is not approval.")

    def _configure_accessibility(self):
        for widget, name in (
            (self.plugin_id_edit, "Parser profile id"), (self.display_name_edit, "Parser profile display name"),
            (self.source_format_combo, "Parser profile source type"), (self.profile_list, "Installed parser profiles"),
            (self.stage_label, "Current new-format stage"), (self.validation_status_label, "Last observed profile validation"),
            (self.next_button, "Next parser profile action"), (self.enable_button, "Enable selected installed profile"),
            (self.disable_button, "Disable selected installed profile"),
        ):
            configure_accessibility(widget, name=name)
        for button in (self.create_button, self.open_folder_button, self.copy_path_button, self.check_package_button,
                       self.validate_button, self.diagnose_button, self.repair_button, self.install_button):
            configure_accessibility(button, name=button.text().split(" [")[0])
        self.install_button.setToolTip("Install explicitly revalidates current samples and checked results. Earlier PASS is not approval.")

    def _configure_commands(self):
        commands = (
            ("Ctrl+D", self.create_button), ("Ctrl+R", self.check_package_button),
            ("Ctrl+Shift+R", self.validate_button), ("Ctrl+Shift+F", self.open_folder_button),
            ("Ctrl+Shift+C", self.copy_path_button), ("Ctrl+Shift+S", self.repair_button),
            ("Ctrl+Shift+E", self.disable_button), ("Ctrl+Shift+Q", self.diagnose_button),
        )
        for sequence, button in commands:
            self._bind_command(sequence, lambda _checked=False, control=button: self._click_visible(control))
            visible_shortcut(button, sequence)
        self._bind_command("Ctrl+E", self._install_or_enable)
        visible_shortcut(self.install_button, "Ctrl+E")
        visible_shortcut(self.enable_button, "Ctrl+E")
        self._bind_command("Ctrl+S", self._run_next_action)
        self._bind_command("Ctrl+W", self.accept)
        visible_shortcut(self.close_button, "Ctrl+W / Esc")
        self._bind_command("Ctrl+Shift+D", lambda: self.task_tabs.setCurrentIndex(0))
        self._bind_command("Ctrl+Shift+A", lambda: self.task_tabs.setCurrentIndex(1))
        visible_shortcut(self.refresh_button, "Ctrl+S")

    def _bind_command(self, sequence, callback):
        action = QAction(self)
        bind_shortcut(action, sequence)
        action.setAutoRepeat(False)
        action.triggered.connect(callback)
        self.addAction(action)

    def _click_visible(self, button):
        if button.isVisibleTo(self):
            button.click()

    def _install_or_enable(self):
        self._click_visible(self.enable_button if self.task_tabs.currentIndex() == 0 else self.install_button)

    def _run_next_action(self):
        self._click_visible(self.refresh_button if self.task_tabs.currentIndex() == 0 else self.next_button)

    def _show_stage(self, title, next_control, instruction, *, problem=False):
        self.stage_label.setText(title)
        self.next_action_label.setText(instruction)
        self._next_control = next_control
        name = next_control.text().split(" [")[0]
        self.next_button.setText(f"Next: {name} [Ctrl+S]")
        self.next_button.setEnabled(next_control.isEnabled())
        ready = self.last_handoff_workspace is not None
        self.diagnose_button.setEnabled(ready and problem)
        self.repair_button.setEnabled(ready and problem)

    def _sync_manage_actions(self, *_args):
        item = self.profile_list.currentItem()
        profile = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self.enable_button.setEnabled(bool(profile and not profile.enabled and profile.approved))
        self.disable_button.setEnabled(bool(profile and profile.enabled))
        if profile is not None:
            self.manage_status_label.setText(
                f"{profile.plugin_id}: {'enabled' if profile.enabled else 'disabled'}; "
                + ("integrity/approval valid" if profile.approved else f"needs review: {profile.detail}")
            )
        else:
            self.manage_status_label.setText("Select an installed profile; enable requires valid approval/integrity.")

    def _change_installed_state(self, enabled):
        item = self.profile_list.currentItem()
        profile = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        button = self.enable_button if enabled else self.disable_button
        if profile is None or not button.isEnabled():
            return
        try:
            (enable_profile if enabled else disable_profile)(profile.plugin_id, home=self.home)
        except (OSError, ValueError) as exc:
            self.manage_status_label.setText(str(exc))
            set_status_variant(self.manage_status_label, "warning")
            return
        self.refresh_status()

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
            self._sync_manage_actions()
            return
        for profile in profiles:
            state = "enabled" if profile.enabled else "disabled"
            approval = "approved" if profile.approved else "needs approval"
            detail = f" - {profile.detail}" if profile.detail and profile.detail != approval else ""
            item = QListWidgetItem(f"{profile.plugin_id}: {state}, {approval}{detail}")
            item.setData(Qt.ItemDataRole.UserRole, profile)
            self.profile_list.addItem(item)
        self._sync_manage_actions()

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
        self.package_status_label.setText("Last package check: not run for this folder")
        self.validation_status_label.setText("Last validation: not run for this folder")
        self._show_stage("1 · Prepare contents", self.check_package_button,
                         "Add sanitized samples, checked expected rows and the completed profile. Check Package verifies structure, not approval.")

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
        self.package_status_label.setText(f"Last package check: {'PASS' if report.passed else 'FAIL'}")
        self._show_stage("2 · Check / validate", self.validate_button if report.passed else self.open_folder_button,
                         "Validate the current profile and expected rows; package PASS is not profile approval."
                         if report.passed else "Open the folder and restore the missing package materials; then Check Package again.",
                         problem=not report.passed)
        if report.passed:
            self.result_label.setText(f"Package check passed. Evidence: {output}")
            set_status_variant(self.result_label, "success")
        else:
            self.result_label.setText(f"Package check failed. Evidence: {output}")
            set_status_variant(self.result_label, "warning")

    def _validation_snapshot(
        self, workspace, getter, writer, *,
        _default_getter=_current_workspace, _default_writer=write_profile_validation_artifact,
    ):
        state = _native_dialog_state(self)
        if state is None or type(workspace) is not HandoffWorkspace:
            return None
        if type(getter) is not MethodType or getter.__self__ is not self or getter.__func__ is not _default_getter:
            return None
        if writer is not _default_writer or not _native_validation_widget(
            state.get("result_label"), QLabel, ("setText", "property", "setProperty"),
        ):
            return None
        controls = ("create_button", "check_package_button", "validate_button",
                    "diagnose_button", "repair_button", "install_button")
        if any(not _native_validation_widget(state.get(name), QPushButton, ("isEnabled", "setEnabled"))
               for name in controls):
            return None
        fields = workspace.__dict__
        if any(type(key) is not str for key in tuple(fields)):
            return None
        paths = tuple(fields.get(name) for name in ("root", "profile_path", "handoff_path", "expected_results_path"))
        if any(type(path) is not PosixPath and type(path) is not WindowsPath for path in paths):
            return None
        return HandoffWorkspace(*paths)

    def validate_handoff_profile(self):
        action_started_at = monotonic()
        state = _native_dialog_state(self)
        if state is not None and state.get("_validation_thread") is not None:
            return
        getter = self._current_workspace
        workspace = getter()
        if workspace is None:
            return
        writer = write_profile_validation_artifact
        self.validation_status_label.setText("Last validation: running")
        snapshot = ParserPluginWizardDialog._validation_snapshot(self, workspace, getter, writer)
        if snapshot is not None:
            ParserPluginWizardDialog._start_validation(self, snapshot, workspace, writer, action_started_at)
            return
        output, passed = writer(workspace)
        ParserPluginWizardDialog._apply_validation_result(self, output, passed)

    def _apply_validation_result(self, output, passed):
        self.validation_status_label.setText(f"Last validation: {'PASS' if passed else 'FAIL'} (observed result)")
        self._show_stage("3 · Install / enable" if passed else "2 · Correct validation problems",
                         self.install_button if passed else self.open_folder_button,
                         "Review the evidence, then install. Installation rechecks current samples/expected rows; earlier PASS is not approval."
                         if passed else "Open the folder to correct materials. Diagnose / Repair Prompt are available for this problem; validate again.",
                         problem=not passed)
        if passed:
            self.result_label.setText(f"Validation passed. Evidence: {output}")
            set_status_variant(self.result_label, "success")
        else:
            self.result_label.setText(f"Validation failed. Evidence: {output}")
            set_status_variant(self.result_label, "warning")

    def _start_validation(self, snapshot, workspace, writer, action_started_at):
        thread = _ProfileValidationThread(snapshot, workspace, writer)
        progress, _label, bar, _movie = create_delayed_worker_progress_dialog(
            self, window_title="Validate parser profile", initial_status_text="Validating parser profile...",
            on_cancel=lambda: None, action_started_at=action_started_at, cancellable=False,
        )
        bar.setRange(0, 0)
        self._validation_thread = thread
        self._validation_progress = progress
        self._validation_closed = False
        self._validation_controls = tuple((widget, widget.isEnabled()) for widget in (
            self.create_button, self.check_package_button, self.validate_button,
            self.diagnose_button, self.repair_button, self.install_button, self.next_button,
        ))
        for widget, _enabled in self._validation_controls:
            widget.setEnabled(False)
        detached_threads.register(thread, defer_quit=True, owner=self, on_finished=ParserPluginWizardDialog._finish_validation)
        detached_threads.run_when_finished([thread], thread.release)
        try:
            thread.start()
        except Exception:
            detached_threads.discard(thread)
            ParserPluginWizardDialog._release_validation(self)
            raise
        progress.show()

    def _release_validation(self):
        self._validation_thread = None
        dismiss_worker_progress_dialog(self._validation_progress)
        self._validation_progress = None
        for widget, enabled in self._validation_controls:
            widget.setEnabled(enabled)
        self._validation_controls = ()

    def _finish_validation(self, thread):
        if thread is not self._validation_thread:
            return
        ParserPluginWizardDialog._release_validation(self)
        if self._validation_closed or self.last_handoff_workspace is not thread.source_workspace:
            return
        if thread.error is not None:
            self.validation_status_label.setText("Last validation: error (no passing result)")
            self._show_stage("2 · Correct validation problems", self.open_folder_button,
                             "Inspect the error and materials, then validate again.", problem=True)
            self.result_label.setText(str(thread.error))
            set_status_variant(self.result_label, "warning")
        else:
            ParserPluginWizardDialog._apply_validation_result(self, *thread.result)

    def _mark_validation_closed(self):
        if self._validation_thread is not None:
            self.validation_status_label.setText("Validation result is not adopted after closing; validate again when idle.")
            self._show_stage("2 · Validation result not adopted", self.validate_button,
                             "The existing validation worker retains its cleanup ownership after close.")

    def done(self, result):
        self._mark_validation_closed()
        self._validation_closed = True
        dismiss_worker_progress_dialog(self._validation_progress)
        self._validation_progress = None
        super().done(result)

    def closeEvent(self, event):
        self._mark_validation_closed()
        self._validation_closed = True
        dismiss_worker_progress_dialog(self._validation_progress)
        self._validation_progress = None
        super().closeEvent(event)

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
            self._show_stage("3 · Installation blocked", self.open_folder_button,
                             "Open the folder and correct current samples/checked results. Diagnose or repair this problem, then validate again.", problem=True)
            self.result_label.setText(str(exc))
            set_status_variant(self.result_label, "warning")
            return
        self._show_stage("3 · Installed / enabled", self.refresh_button,
                         "Manage installed profiles shows the observed enabled and integrity state.")
        self.result_label.setText(f"Installed profile: {result.plugin_id}")
        set_status_variant(self.result_label, "success")
        self.refresh_status()
        self.task_tabs.setCurrentIndex(0)
