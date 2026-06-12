"""Source-profile editor for Oznak production-line database connections."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository, IndustrialSourceProfile
from metroliza.industrial.industrial_source_config import (
    IndustrialSourceConfigError,
    build_source_profile,
    default_industrial_source_config_path,
    import_source_profiles_to_repository,
    load_source_profiles_from_config,
    upsert_source_profile_in_config,
    upsert_source_profile_to_repository,
)
from metroliza.ui.help_menu import attach_help_menu_to_layout
from metroliza.ui.ui_foundation import (
    apply_metroliza_theme,
    configure_window_size,
    path_field,
    section_label,
    status_chip,
    update_path_field,
)


class IndustrialSourceProfilesDialog(QDialog):
    """Create and edit non-secret production-line source profile metadata."""

    profile_saved = pyqtSignal(object)

    def __init__(
        self,
        parent=None,
        db_file: str | None = None,
        config_path: str | Path | None = None,
    ):
        super().__init__(parent)
        self.db_file = db_file
        self.config_path = Path(config_path or default_industrial_source_config_path()).expanduser()
        self._loading_profile = False
        self.setWindowTitle("Production line sources")
        configure_window_size(self, minimum=(620, 420), initial=(760, 600))

        self.status_label = status_chip("Select or create a production line source.", "neutral")
        self.config_path_field = path_field(str(self.config_path), empty_text="No config file selected")
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self.on_profile_selected)

        self.source_name_edit = QLineEdit()
        self.alias_edit = QLineEdit()
        self.db_type_combo = QComboBox()
        self.db_type_combo.addItem("Microsoft SQL Server", "mssql")
        self.db_type_combo.addItem("MySQL", "mysql")
        self.db_type_combo.currentIndexChanged.connect(self.on_database_type_changed)
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(1433)
        self.database_edit = QLineEdit()
        self.table_edit = QLineEdit()
        self.columns_edit = QLineEdit()
        self.record_key_edit = QLineEdit()
        self.timestamp_column_edit = QLineEdit()
        self.order_by_checkbox = QCheckBox("Use server-side ORDER BY")
        self.order_by_checkbox.setChecked(True)
        self.order_by_checkbox.setToolTip(
            "Sorts limited production reads on the SQL server. Turn this off if SQL Server fails "
            "with low-memory sort errors; fetched rows may then be unordered."
        )

        self.source_name_edit.setPlaceholderText("Assembly line MES")
        self.alias_edit.setPlaceholderText("assembly_mes")
        self.host_edit.setPlaceholderText("production database host")
        self.database_edit.setPlaceholderText("production database name")
        self.table_edit.setPlaceholderText("production table or view name")
        self.columns_edit.setPlaceholderText(
            "id, part_number, revision, serial, station, line, status"
        )
        self.record_key_edit.setPlaceholderText("id")
        self.timestamp_column_edit.setPlaceholderText("process_timestamp")

        self.new_source_button = QPushButton("New source")
        self.browse_config_button = QPushButton("Browse...")
        self.reload_config_button = QPushButton("Reload config")
        self.save_source_button = QPushButton("Save source")
        self.close_button = QPushButton("Close")
        self.new_source_button.clicked.connect(self.clear_form)
        self.browse_config_button.clicked.connect(self.browse_config_file)
        self.reload_config_button.clicked.connect(self.reload_profiles)
        self.save_source_button.clicked.connect(self.save_source)
        self.close_button.clicked.connect(self.accept)

        self._build_layout()
        self.reload_profiles()
        apply_metroliza_theme(self)

    def _build_layout(self) -> None:
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("Saved production source", self.profile_combo)
        form.addRow("Source name", self.source_name_edit)
        form.addRow("Source alias", self.alias_edit)
        form.addRow("Production DB type", self.db_type_combo)
        form.addRow("Production host", self.host_edit)
        form.addRow("Production port", self.port_spin)
        form.addRow("Production database", self.database_edit)
        form.addRow("Production table/view", self.table_edit)
        form.addRow("Production columns", self.columns_edit)
        form.addRow("Record key / paging column", self.record_key_edit)
        form.addRow("Timestamp column", self.timestamp_column_edit)
        form.addRow("Server ordering", self.order_by_checkbox)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        attach_help_menu_to_layout(layout, self, [("Industrial Data manual", "industrial_data")])
        layout.addWidget(section_label("Production line database configuration"))
        config_row = QHBoxLayout()
        config_row.setContentsMargins(0, 0, 0, 0)
        config_row.setSpacing(8)
        config_row.addWidget(section_label("Production source config file"))
        config_row.addWidget(self.config_path_field, 1)
        config_row.addWidget(self.browse_config_button)
        config_row.addWidget(self.reload_config_button)
        layout.addLayout(config_row)
        layout.addWidget(self.status_label)
        layout.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.new_source_button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        actions.addWidget(self.save_source_button)
        layout.addLayout(actions)

    def browse_config_file(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Production line source config",
            str(self.config_path),
            "YAML config (*.yaml *.yml);;All files (*)",
        )
        if not filename:
            return
        selected = Path(filename).expanduser()
        if selected.suffix.lower() not in {".yaml", ".yml"}:
            selected = selected.with_suffix(".yaml")
        self.config_path = selected
        update_path_field(
            self.config_path_field,
            str(self.config_path),
            empty_text="No config file selected",
        )
        self.reload_profiles()

    def reload_profiles(self) -> None:
        if self._loading_profile:
            return
        current_key = self.current_profile_key()
        self._loading_profile = True
        self.profile_combo.clear()
        self.profile_combo.addItem("New source", None)
        profiles_by_key: "OrderedDict[str, IndustrialSourceProfile]" = OrderedDict()
        loaded_from_config = 0
        config_error = ""
        try:
            config_profiles = load_source_profiles_from_config(self.config_path)
            loaded_from_config = len(config_profiles)
            if self.db_file and config_profiles:
                imported = import_source_profiles_to_repository(
                    self.config_path,
                    IndustrialDataRepository(self.db_file),
                )
                for profile in imported:
                    profiles_by_key[profile.profile_key] = profile
            else:
                for profile in config_profiles:
                    profiles_by_key[profile.profile_key] = profile
        except IndustrialSourceConfigError as exc:
            config_error = str(exc)
        except Exception as exc:
            config_error = f"Could not load config file: {exc}"

        db_profiles: list[IndustrialSourceProfile] = []
        if self.db_file:
            try:
                db_profiles = IndustrialDataRepository(self.db_file).list_source_profiles(
                    include_disabled=True
                )
            except Exception as exc:
                if config_error:
                    config_error = (
                        f"{config_error} Also could not load cached production sources "
                        f"from the active local cache: {exc}"
                    )
                else:
                    config_error = (
                        "Could not load cached production sources from the active local cache: "
                        f"{exc}"
                    )
        for profile in db_profiles:
            profiles_by_key.setdefault(profile.profile_key, profile)

        selected_index = 0
        for profile in profiles_by_key.values():
            self.profile_combo.addItem(profile.profile_name, profile)
            if profile.profile_key == current_key:
                selected_index = self.profile_combo.count() - 1
        self.profile_combo.setCurrentIndex(selected_index)
        self._loading_profile = False
        if config_error:
            self.status_label.setText(config_error)
        elif profiles_by_key:
            suffix = (
                " and synchronized with the active local cache"
                if self.db_file
                else ""
            )
            self.status_label.setText(
                f"Loaded {len(profiles_by_key)} production source(s) from config file/cache{suffix}."
            )
        elif loaded_from_config == 0:
            self.status_label.setText(
                "No production sources yet. Create one and save it to the config file."
            )
        self.on_profile_selected()

    def _select_profile_key(self, profile_key: str) -> None:
        for index in range(self.profile_combo.count()):
            profile = self.profile_combo.itemData(index)
            if isinstance(profile, IndustrialSourceProfile) and profile.profile_key == profile_key:
                self.profile_combo.setCurrentIndex(index)
                return

    def current_profile_key(self) -> str | None:
        profile = self.profile_combo.currentData()
        if isinstance(profile, IndustrialSourceProfile):
            return profile.profile_key
        alias = self.alias_edit.text().strip()
        return alias or None

    def on_profile_selected(self) -> None:
        if self._loading_profile:
            return
        profile = self.profile_combo.currentData()
        if not isinstance(profile, IndustrialSourceProfile):
            return
        self.source_name_edit.setText(profile.profile_name)
        self.alias_edit.setText(profile.source_db_alias)
        db_type_index = self.db_type_combo.findData(profile.database_type)
        if db_type_index >= 0:
            self.db_type_combo.setCurrentIndex(db_type_index)
        self.host_edit.setText(profile.host or "")
        if profile.port:
            self.port_spin.setValue(profile.port)
        self.database_edit.setText(profile.database_name or "")
        self.table_edit.setText(profile.source_object_name)
        self.columns_edit.setText(", ".join(profile.allowed_columns))
        self.record_key_edit.setText(profile.default_pagination_column or "")
        self.timestamp_column_edit.setText(profile.timestamp_column or "")
        self.order_by_checkbox.setChecked(profile.order_by_enabled)
        self.status_label.setText(f"Editing production source: {profile.profile_name}")

    def on_database_type_changed(self) -> None:
        selected_type = self.db_type_combo.currentData()
        if selected_type == "mysql" and self.port_spin.value() == 1433:
            self.port_spin.setValue(3306)
        elif selected_type == "mssql" and self.port_spin.value() == 3306:
            self.port_spin.setValue(1433)

    def clear_form(self) -> None:
        self.profile_combo.setCurrentIndex(0)
        for widget in (
            self.source_name_edit,
            self.alias_edit,
            self.host_edit,
            self.database_edit,
            self.table_edit,
            self.columns_edit,
            self.record_key_edit,
            self.timestamp_column_edit,
        ):
            widget.clear()
        self.port_spin.setValue(1433 if self.db_type_combo.currentData() == "mssql" else 3306)
        self.order_by_checkbox.setChecked(True)
        self.status_label.setText("New production source profile.")

    def save_source(self) -> None:
        try:
            profile = self.profile_from_form()
            upsert_source_profile_in_config(self.config_path, profile)
            saved_profile = profile
            if self.db_file:
                saved_profile = upsert_source_profile_to_repository(
                    IndustrialDataRepository(self.db_file),
                    profile,
                )
        except (IndustrialSourceConfigError, ValueError) as exc:
            QMessageBox.warning(self, "Production line source", str(exc))
            return
        self.profile_saved.emit(saved_profile)
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_status"):
            parent.refresh_status()
        self.reload_profiles()
        self._select_profile_key(saved_profile.profile_key)
        self.status_label.setText(self._saved_source_status(saved_profile))

    def _saved_source_status(self, profile: IndustrialSourceProfile) -> str:
        next_step = (
            "Use Fetch to cache in the Industrial data window to check access or fetch rows."
            if self.db_file
            else (
                "Select, create, or skip a local cache in the Industrial data window, then use "
                "Fetch to cache or Fetch to CSV Summary."
            )
        )
        return f"Saved production source: {profile.profile_name}. {next_step}"

    def profile_from_form(self) -> IndustrialSourceProfile:
        profile_name = self.source_name_edit.text().strip()
        alias = self.alias_edit.text().strip() or _slug_identifier(profile_name)
        columns = self._columns_from_form()

        return build_source_profile(
            profile_key=alias,
            profile_name=profile_name,
            source_db_alias=alias,
            database_type=str(self.db_type_combo.currentData()),
            source_object_name=self.table_edit.text().strip(),
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            database_name=self.database_edit.text().strip(),
            allowed_columns=columns,
            timestamp_column=self.timestamp_column_edit.text().strip() or None,
            default_pagination_column=self.record_key_edit.text().strip() or None,
            is_enabled=True,
            order_by_enabled=self.order_by_checkbox.isChecked(),
        )

    def _columns_from_form(self) -> tuple[str, ...]:
        columns = [column.strip() for column in self.columns_edit.text().split(",") if column.strip()]
        for required_column in (
            self.record_key_edit.text().strip(),
            self.timestamp_column_edit.text().strip(),
        ):
            if required_column and required_column not in columns:
                columns.append(required_column)
        return tuple(dict.fromkeys(columns))


def _slug_identifier(value: str) -> str:
    slug = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    if not slug:
        return ""
    if slug[0].isdigit():
        slug = f"source_{slug}"
    return slug
