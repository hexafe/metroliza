"""Qt dialog for dashboard visual settings with a sample preview."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import json

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from metroliza.charts.dashboard_visual_options import (
    DEFAULT_DASHBOARD_PALETTE,
    DASHBOARD_VISUAL_MARKER_SYMBOLS,
    build_dashboard_visual_preview_html,
    build_dashboard_visual_preview_png,
    build_dashboard_visual_preview_spec,
    dashboard_visual_effective_series_styles,
    dashboard_visual_palette_presets,
    dashboard_visual_preview_labels,
    dashboard_visual_recipe_choices,
    dashboard_visual_recipe_settings,
    dashboard_visual_settings_summary,
    dashboard_visual_swatch_palette,
    default_dashboard_visual_settings,
    load_dashboard_visual_theme_library,
    normalize_dashboard_visual_settings,
    remove_dashboard_visual_theme,
    save_dashboard_visual_settings,
    save_dashboard_visual_theme_library,
    upsert_dashboard_visual_theme,
)
from metroliza.charts.plotly_stat_helpers import normalize_group_label_key
from metroliza.ui.ui_foundation import apply_metroliza_theme, configure_accessibility, configure_window_size

try:  # Optional. PyQt WebEngine is intentionally not a hard runtime dependency.
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - depends on local Qt installation.
    QWebEngineView = None

try:  # Optional bridge for click-to-select preview editing.
    from PyQt6.QtWebChannel import QWebChannel
except Exception:  # pragma: no cover - depends on local Qt installation.
    QWebChannel = None


_PRESET_ITEMS = dashboard_visual_recipe_choices()
_PALETTE_MODE_ITEMS = (
    ("Fixed palette", "fixed"),
    ("Auto gradient", "auto_gradient"),
    ("Highlight gradient", "highlight_gradient"),
)
_SPREAD_ITEMS = (("Narrow", "narrow"), ("Normal", "normal"), ("Wide", "wide"))
_DISTINGUISH_ITEMS = (
    ("Color only", "color_only"),
    ("When similar", "when_similar"),
    ("Always", "always"),
)
_CHART_ITEMS = (
    ("Histogram", "histogram"),
    ("Violin", "violin"),
    ("IQR", "iqr"),
    ("Scatter", "scatter"),
)
_DASH_ITEMS = (("Solid", "solid"), ("Dash", "dash"), ("Dot", "dot"), ("Dash-dot", "dashdot"))
_PREVIEW_SERIES_LABELS = dashboard_visual_preview_labels()
_PREVIEW_PALETTE_LABELS = _PREVIEW_SERIES_LABELS[1:]
_MARKER_SYMBOL_ITEMS = tuple(
    (str(symbol).replace("-", " ").title(), symbol)
    for symbol in DASHBOARD_VISUAL_MARKER_SYMBOLS
)
_OUTLINE_COLOR_MODE_ITEMS = (("Auto contrast", "auto"), ("Custom color", "custom"))


def _preview_label_key(label: str) -> str:
    return normalize_group_label_key(label)


def _is_population_preview_label(label: str, population: Mapping[str, Any]) -> bool:
    aliases = population.get("aliases") if isinstance(population, Mapping) else None
    alias_values = aliases if isinstance(aliases, list) else ["population", "population points"]
    label_key = _preview_label_key(label)
    return any(label_key == _preview_label_key(str(alias)) for alias in alias_values)


def _preview_palette_index_for_label(
    label: str,
    palette_labels: tuple[str, ...] = _PREVIEW_PALETTE_LABELS,
) -> int | None:
    label_key = _preview_label_key(label)
    for index, preview_label in enumerate(palette_labels):
        if label_key == _preview_label_key(preview_label):
            return index
    return None


def _first_style_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


class _PreviewSelectionBridge(QObject):
    target_selected = pyqtSignal(str)

    @pyqtSlot(str)
    def selectTarget(self, payload: str) -> None:  # noqa: N802 - Qt slot exposed to JS.
        self.target_selected.emit(str(payload or ""))


class DashboardVisualOptionsDialog(QDialog):
    """Edit dashboard visual settings and preview them on static sample data."""

    def __init__(
        self,
        parent=None,
        *,
        settings: Mapping[str, Any] | None = None,
        preview_group_names: Any = None,
        persist_on_accept: bool = True,
    ):
        super().__init__(parent)
        self._settings = normalize_dashboard_visual_settings(settings)
        self._persist_on_accept = bool(persist_on_accept)
        self._palette_buttons: list[QPushButton] = []
        self._preview_color_buttons: list[QPushButton] = []
        self._series_overrides = dict(self._settings.get("series_overrides") or {})
        self._stat_line_overrides = dict(self._settings.get("stat_line_overrides") or {})
        self._population_baseline = dict(self._settings.get("population_baseline") or {})
        self._comparison_focus = dict(self._settings.get("comparison_focus") or {})
        self._preview_group_names = (
            (str(preview_group_names),)
            if isinstance(preview_group_names, (str, bytes))
            else tuple(preview_group_names or ())
        )
        self._preview_series_labels = dashboard_visual_preview_labels(self._preview_group_names)
        self._preview_palette_labels = tuple(
            label
            for label in self._preview_series_labels
            if not _is_population_preview_label(label, self._population_baseline)
        )
        self._theme_library = load_dashboard_visual_theme_library()
        self._palette_presets = dashboard_visual_palette_presets()
        self._preview_targets: list[dict[str, Any]] = []
        self._selected_target: dict[str, Any] | None = None
        self._populating_controls = False
        self._updating_selection_controls = False
        self._prefer_resolved_selection_style = False
        self._reference_width_source = {
            key: float(value["width"])
            for key, value in self._settings["reference_lines"].items()
        }
        self._reference_opacity_source = {
            key: float(value.get("opacity", 1.0))
            for key, value in self._settings["reference_lines"].items()
        }
        self._reference_width_control_value = float(
            self._settings["reference_lines"]["lsl"]["width"]
        )
        self._preview_source_pixmap: QPixmap | None = None
        self._suppress_preview_schedule = False
        self._preview_timer = self._new_preview_timer()
        self._preview_bridge: _PreviewSelectionBridge | None = None
        self._preview_channel = None
        self.setWindowTitle("Dashboard visuals")
        configure_window_size(self, minimum=(980, 620), initial=(1180, 780))

        self._build_controls()
        self._populate_from_settings(self._settings)
        self._sync_custom_controls()
        self._schedule_preview()
        apply_metroliza_theme(self)

    def visual_settings(self) -> dict[str, Any]:
        """Return normalized settings represented by the current controls."""

        settings = default_dashboard_visual_settings()
        settings.pop("color_source", None)
        settings["theme_id"] = str(self.theme_combo.currentData() or "")
        settings["theme_name"] = self.theme_name_edit.text().strip()
        recipe = str(self.preset_combo.currentData() or "auto")
        settings["recipe"] = recipe
        settings["preset"] = recipe if recipe in {"auto", "distinct", "print", "custom"} else "custom"
        settings["palette_preset"] = str(self.palette_preset_combo.currentData() or "metroliza")
        settings["palette_mode"] = str(self.palette_mode_combo.currentData() or "fixed")
        settings["palette"] = [button.property("color") for button in self._palette_buttons]
        settings["anchor_color"] = str(self.anchor_color_button.property("color") or "#facc15")
        settings["gradient_spread"] = str(self.gradient_spread_combo.currentData() or "normal")
        settings["distinguish"] = str(self.distinguish_combo.currentData() or "when_similar")
        settings["marker_size"] = self.marker_size_spin.value()
        settings["stat_lines"] = {
            "accent_by_stat": self.stat_accent_combo.currentData() == "accent",
            "width": self.stat_width_spin.value(),
        }
        settings["population_baseline"] = dict(self._population_baseline)
        settings["comparison_focus"] = dict(self._comparison_focus)
        settings["series_overrides"] = dict(self._series_overrides)
        settings["stat_line_overrides"] = dict(self._stat_line_overrides)
        reference_width = self.reference_width_spin.value()
        preserve_reference_widths = (
            abs(reference_width - self._reference_width_control_value) <= 1e-9
        )
        settings["reference_lines"] = {
            "lsl": {
                "color": str(self.lsl_color_button.property("color") or "#b91c1c"),
                "dash": str(self.lsl_dash_combo.currentData() or "dash"),
                "width": self._reference_line_width(
                    "lsl",
                    fallback=reference_width,
                    preserve=preserve_reference_widths,
                ),
                "opacity": self._reference_line_opacity("lsl"),
            },
            "usl": {
                "color": str(self.usl_color_button.property("color") or "#b91c1c"),
                "dash": str(self.usl_dash_combo.currentData() or "dash"),
                "width": self._reference_line_width(
                    "usl",
                    fallback=reference_width,
                    preserve=preserve_reference_widths,
                ),
                "opacity": self._reference_line_opacity("usl"),
            },
            "nominal": {
                "color": str(self.nominal_color_button.property("color") or "#0f766e"),
                "dash": str(self.nominal_dash_combo.currentData() or "solid"),
                "width": self._reference_line_width(
                    "nominal",
                    fallback=reference_width,
                    preserve=preserve_reference_widths,
                ),
                "opacity": self._reference_line_opacity("nominal"),
            },
        }
        return normalize_dashboard_visual_settings(settings)

    def accept(self) -> None:
        self._settings = self.visual_settings()
        if self._persist_on_accept:
            save_dashboard_visual_settings(self._settings)
        super().accept()

    def _build_controls(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        root.addLayout(body, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)
        scroll.setWidget(controls)
        body.addWidget(scroll, 0)

        theme_group = QGroupBox("Saved themes")
        theme_form = QFormLayout(theme_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Current settings", "")
        self._populate_theme_combo()
        self.theme_combo.currentIndexChanged.connect(self._handle_theme_selected)
        self.theme_name_edit = QLineEdit()
        self.theme_name_edit.setPlaceholderText("Theme name")
        theme_actions = QWidget()
        theme_actions_layout = QHBoxLayout(theme_actions)
        theme_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.save_theme_button = QPushButton("Save")
        self.update_theme_button = QPushButton("Update")
        self.delete_theme_button = QPushButton("Delete")
        self.save_theme_button.clicked.connect(self._save_theme_as)
        self.update_theme_button.clicked.connect(self._update_theme)
        self.delete_theme_button.clicked.connect(self._delete_theme)
        theme_actions_layout.addWidget(self.save_theme_button)
        theme_actions_layout.addWidget(self.update_theme_button)
        theme_actions_layout.addWidget(self.delete_theme_button)
        theme_form.addRow("Theme", self.theme_combo)
        theme_form.addRow("Name", self.theme_name_edit)
        theme_form.addRow("", theme_actions)
        controls_layout.addWidget(theme_group)

        self.preset_combo = self._combo(_PRESET_ITEMS)
        self.preset_combo.currentIndexChanged.connect(self._handle_preset_changed)
        preset_group = QGroupBox("Mode")
        preset_layout = QVBoxLayout(preset_group)
        preset_form = QFormLayout()
        preset_form.addRow("Visual preset", self.preset_combo)
        preset_layout.addLayout(preset_form)
        preview_colors = QGridLayout()
        preview_colors.setContentsMargins(0, 0, 0, 0)
        for index, label in enumerate(self._preview_series_labels):
            chip = self._color_button(DEFAULT_DASHBOARD_PALETTE[index % len(DEFAULT_DASHBOARD_PALETTE)])
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.clicked.connect(lambda _checked=False, index=index: self._select_preview_series(index))
            self._preview_color_buttons.append(chip)
            preview_colors.addWidget(QLabel(label), index, 0)
            preview_colors.addWidget(chip, index, 1)
        preset_layout.addLayout(preview_colors)
        controls_layout.addWidget(preset_group)

        self.customize_button = QPushButton("Customize...")
        self.customize_button.setCheckable(True)
        self.customize_button.setToolTip(
            "Show detailed color, line, marker, and selected-element controls."
        )
        controls_layout.addWidget(self.customize_button)

        self.customize_controls_container = QWidget()
        customize_layout = QVBoxLayout(self.customize_controls_container)
        customize_layout.setContentsMargins(0, 0, 0, 0)
        customize_layout.setSpacing(10)
        controls_layout.addWidget(self.customize_controls_container)

        palette_group = QGroupBox("Advanced palette")
        palette_layout = QGridLayout(palette_group)
        self.palette_preset_combo = QComboBox()
        self._populate_palette_preset_combo()
        self.palette_mode_combo = self._combo(_PALETTE_MODE_ITEMS)
        self.gradient_spread_combo = self._combo(_SPREAD_ITEMS)
        self.anchor_color_button = self._color_button("#facc15")
        self.palette_preset_combo.currentIndexChanged.connect(self._handle_palette_preset_changed)
        self.palette_mode_combo.currentIndexChanged.connect(self._handle_control_changed)
        self.gradient_spread_combo.currentIndexChanged.connect(self._handle_control_changed)
        self.anchor_color_button.clicked.connect(lambda: self._choose_color(self.anchor_color_button))
        palette_layout.addWidget(QLabel("Preset"), 0, 0)
        palette_layout.addWidget(self.palette_preset_combo, 0, 1, 1, 3)
        palette_layout.addWidget(QLabel("Mode"), 1, 0)
        palette_layout.addWidget(self.palette_mode_combo, 1, 1, 1, 3)
        palette_layout.addWidget(QLabel("Anchor"), 2, 0)
        palette_layout.addWidget(self.anchor_color_button, 2, 1)
        palette_layout.addWidget(QLabel("Spread"), 2, 2)
        palette_layout.addWidget(self.gradient_spread_combo, 2, 3)
        for index, color in enumerate(DEFAULT_DASHBOARD_PALETTE):
            button = self._color_button(color)
            button.clicked.connect(lambda _checked=False, button=button: self._choose_color(button))
            self._palette_buttons.append(button)
            palette_layout.addWidget(button, 3 + index // 3, index % 3)
        customize_layout.addWidget(palette_group)

        series_group = QGroupBox("Series")
        series_form = QFormLayout(series_group)
        self.distinguish_combo = self._combo(_DISTINGUISH_ITEMS)
        self.marker_size_spin = QDoubleSpinBox()
        self.marker_size_spin.setRange(2.0, 18.0)
        self.marker_size_spin.setSingleStep(0.5)
        self.marker_size_spin.valueChanged.connect(lambda _value: self._handle_control_changed())
        self.distinguish_combo.currentIndexChanged.connect(self._handle_control_changed)
        series_form.addRow("Differentiate", self.distinguish_combo)
        series_form.addRow("Default marker size", self.marker_size_spin)
        customize_layout.addWidget(series_group)

        line_group = QGroupBox("Lines")
        line_form = QFormLayout(line_group)
        self.stat_accent_combo = self._combo((("Group color", "group"), ("Accent by stat", "accent")))
        self.stat_width_spin = self._line_width_spin()
        self.reference_width_spin = self._line_width_spin()
        self.lsl_color_button = self._color_button("#b91c1c")
        self.usl_color_button = self._color_button("#b91c1c")
        self.nominal_color_button = self._color_button("#0f766e")
        self.lsl_dash_combo = self._dash_combo()
        self.usl_dash_combo = self._dash_combo()
        self.nominal_dash_combo = self._dash_combo()
        for widget in (
            self.stat_accent_combo,
            self.lsl_dash_combo,
            self.usl_dash_combo,
            self.nominal_dash_combo,
        ):
            widget.currentIndexChanged.connect(self._handle_control_changed)
        for spin in (self.stat_width_spin, self.reference_width_spin):
            spin.valueChanged.connect(lambda _value: self._handle_control_changed())
        for button in (self.lsl_color_button, self.usl_color_button, self.nominal_color_button):
            button.clicked.connect(lambda _checked=False, button=button: self._choose_color(button))
        line_form.addRow("Stats", self.stat_accent_combo)
        line_form.addRow("Stat width", self.stat_width_spin)
        line_form.addRow("Reference width", self.reference_width_spin)
        line_form.addRow("LSL", self._line_style_row(self.lsl_color_button, self.lsl_dash_combo))
        line_form.addRow("USL", self._line_style_row(self.usl_color_button, self.usl_dash_combo))
        line_form.addRow("Nominal", self._line_style_row(self.nominal_color_button, self.nominal_dash_combo))
        customize_layout.addWidget(line_group)
        customize_layout.addStretch(1)
        controls_layout.addStretch(1)

        self.selection_group = QGroupBox("Selection inspector")
        self.selection_group.setObjectName("selectionInspector")
        selection_form = QFormLayout(self.selection_group)
        self.element_combo = QComboBox()
        self.element_combo.addItem("Click a plot element or choose one", "")
        self.element_combo.currentIndexChanged.connect(self._handle_element_combo_changed)
        self._selection_rows: dict[str, list[QWidget]] = {}
        self.element_color_button = self._color_button("#245a5a")
        self.element_color_button.clicked.connect(lambda: self._choose_color(self.element_color_button))
        self.element_opacity_slider = self._opacity_slider()
        self.element_opacity_spin = self._opacity_spin()
        self._bind_opacity_controls(
            self.element_opacity_slider,
            self.element_opacity_spin,
            changed=self._mark_custom_from_element_controls,
        )
        self.element_width_spin = self._line_width_spin()
        self.element_dash_combo = self._dash_combo()
        self.element_marker_size_spin = QDoubleSpinBox()
        self.element_marker_size_spin.setRange(2.0, 18.0)
        self.element_marker_size_spin.setSingleStep(0.5)
        self.element_marker_symbol_combo = self._combo(_MARKER_SYMBOL_ITEMS)
        self.element_outline_checkbox = QCheckBox("Marker border")
        self.element_outline_width_spin = QDoubleSpinBox()
        self.element_outline_width_spin.setRange(0.0, 6.0)
        self.element_outline_width_spin.setSingleStep(0.25)
        self.element_outline_color_mode_combo = self._combo(_OUTLINE_COLOR_MODE_ITEMS)
        self.element_outline_color_button = self._color_button("#111827")
        self.element_outline_color_button.clicked.connect(
            lambda: self._choose_color(self.element_outline_color_button)
        )
        self.element_pattern_combo = self._combo(
            (("None", ""), ("Diagonal", "/"), ("Back diagonal", "\\"), ("Cross", "x"), ("Dots", "."), ("Horizontal", "-"))
        )
        self.element_stat_accent_checkbox = QCheckBox("Use stat accent")
        self.reset_element_button = QPushButton("Clear selected style")
        self.reset_element_button.clicked.connect(self._reset_selected_element_style)
        for widget in (
            self.element_width_spin,
            self.element_dash_combo,
            self.element_marker_size_spin,
            self.element_marker_symbol_combo,
            self.element_outline_checkbox,
            self.element_outline_width_spin,
            self.element_outline_color_mode_combo,
            self.element_pattern_combo,
            self.element_stat_accent_checkbox,
        ):
            signal = getattr(widget, "valueChanged", None) or getattr(widget, "currentIndexChanged", None) or getattr(widget, "stateChanged", None)
            if signal is not None:
                signal.connect(lambda *_args: self._mark_custom_from_element_controls())
        selection_actions = QWidget()
        selection_actions_layout = QHBoxLayout(selection_actions)
        selection_actions_layout.setContentsMargins(0, 0, 0, 0)
        selection_actions_layout.addWidget(self.reset_element_button)
        self._add_selection_row(selection_form, "element", "Element", self.element_combo)
        self._add_selection_row(selection_form, "color", "Color", self.element_color_button)
        self._add_selection_row(
            selection_form,
            "opacity",
            "Opacity",
            self._slider_spin_row(self.element_opacity_slider, self.element_opacity_spin),
        )
        self._add_selection_row(selection_form, "line", "Width", self.element_width_spin)
        self._add_selection_row(selection_form, "dash", "Dash", self.element_dash_combo)
        self._add_selection_row(selection_form, "marker_size", "Marker size", self.element_marker_size_spin)
        self._add_selection_row(selection_form, "marker_symbol", "Shape", self.element_marker_symbol_combo)
        self._add_selection_row(selection_form, "outline", "", self.element_outline_checkbox)
        self._add_selection_row(selection_form, "outline_width", "Border width", self.element_outline_width_spin)
        self._add_selection_row(
            selection_form,
            "outline_color",
            "Border color",
            self._line_style_row(self.element_outline_color_button, self.element_outline_color_mode_combo),
        )
        self._add_selection_row(selection_form, "pattern", "Pattern", self.element_pattern_combo)
        self._add_selection_row(selection_form, "stat_accent", "", self.element_stat_accent_checkbox)
        self._add_selection_row(selection_form, "actions", "", selection_actions)

        preview_panel = QVBoxLayout()
        preview_panel.setContentsMargins(0, 0, 0, 0)
        preview_panel.setSpacing(8)
        body.addLayout(preview_panel, 1)
        preview_header = QHBoxLayout()
        self.chart_type_combo = self._combo(_CHART_ITEMS)
        self.chart_type_combo.currentIndexChanged.connect(lambda _index: self._schedule_preview())
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        preview_header.addWidget(QLabel("Preview"))
        preview_header.addWidget(self.chart_type_combo)
        preview_header.addStretch(1)
        preview_header.addWidget(self.summary_label)
        preview_panel.addLayout(preview_header)
        self.preview_tabs = QTabWidget()
        preview_panel.addWidget(self.preview_tabs, 1)

        self.web_view = QWebEngineView() if QWebEngineView is not None else None
        if self.web_view is not None:
            if QWebChannel is not None:
                self._preview_bridge = _PreviewSelectionBridge(self)
                self._preview_bridge.target_selected.connect(self._handle_preview_target_payload)
                self._preview_channel = QWebChannel(self.web_view.page())
                self._preview_channel.registerObject("metrolizaVisualBridge", self._preview_bridge)
                self.web_view.page().setWebChannel(self._preview_channel)
            self.preview_tabs.addTab(self.web_view, "Plotly")
        self.preview_image_label = QLabel("Preview will appear here.")
        self.preview_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image_label.setMinimumSize(520, 360)
        self.preview_image_label.setScaledContents(False)
        self.preview_tabs.addTab(self.preview_image_label, "Static")
        preview_panel.addWidget(self.selection_group, 0)
        self.customize_button.toggled.connect(self._set_customize_controls_visible)
        self._set_customize_controls_visible(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self._reset_defaults)
        root.addWidget(buttons)
        configure_accessibility(self.preset_combo, name="Dashboard visual preset")
        configure_accessibility(self.customize_button, name="Show dashboard visual customization")
        configure_accessibility(self.chart_type_combo, name="Dashboard visual preview chart")
        configure_accessibility(self.element_combo, name="Dashboard visual selected element")
        configure_accessibility(self.element_opacity_slider, name="Selected element opacity")
        configure_accessibility(self.element_opacity_spin, name="Selected element opacity percent")

        self.setTabOrder(self.chart_type_combo, self.preview_tabs)
        self.setTabOrder(self.preview_tabs, self.element_combo)
        self.setTabOrder(self.element_combo, self.element_color_button)
        self.setTabOrder(self.element_color_button, self.element_opacity_slider)
        self.setTabOrder(self.element_opacity_slider, self.element_opacity_spin)

    def _add_selection_row(
        self,
        layout: QFormLayout,
        row_key: str,
        label: str,
        widget: QWidget,
    ) -> None:
        layout.addRow(label, widget)
        row_widgets = [widget]
        label_widget = layout.labelForField(widget)
        if label_widget is not None:
            row_widgets.append(label_widget)
        self._selection_rows[row_key] = row_widgets

    def _set_customize_controls_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.customize_controls_container.setVisible(visible)
        self.selection_group.setVisible(visible)
        self.customize_button.setChecked(visible)
        self.customize_button.setText("Hide customization" if visible else "Customize...")

    def _populate_from_settings(self, settings: Mapping[str, Any]) -> None:
        self._populating_controls = True
        try:
            self._populate_from_settings_unchecked(settings)
        finally:
            self._populating_controls = False
        if self._selected_target:
            self._load_selected_element_controls()
        else:
            self._sync_custom_controls()

    def _populate_from_settings_unchecked(self, settings: Mapping[str, Any]) -> None:
        self._series_overrides = dict(settings.get("series_overrides") or {})
        self._stat_line_overrides = dict(settings.get("stat_line_overrides") or {})
        self._population_baseline = dict(settings.get("population_baseline") or {})
        self._comparison_focus = dict(settings.get("comparison_focus") or {})
        self.theme_name_edit.setText(str(settings.get("theme_name") or ""))
        self.theme_combo.blockSignals(True)
        self._set_combo_data(self.theme_combo, str(settings.get("theme_id") or ""))
        self.theme_combo.blockSignals(False)
        recipe_id = str(settings.get("recipe") or settings["preset"])
        if recipe_id == "distinct":
            recipe_id = "colorblind_distinct"
        self._set_combo_data(self.preset_combo, recipe_id)
        self._set_combo_data(self.palette_preset_combo, settings["palette_preset"])
        self._set_combo_data(self.palette_mode_combo, settings["palette_mode"])
        self._set_combo_data(self.gradient_spread_combo, settings["gradient_spread"])
        self._set_combo_data(self.distinguish_combo, settings["distinguish"])
        self._set_combo_data(self.stat_accent_combo, "accent" if settings["stat_lines"]["accent_by_stat"] else "group")
        palette = list(settings["palette"])
        for index, button in enumerate(self._palette_buttons):
            self._set_button_color(button, palette[index % len(palette)])
        self._set_button_color(self.anchor_color_button, settings["anchor_color"])
        self.marker_size_spin.setValue(float(settings["marker_size"]))
        self.stat_width_spin.setValue(float(settings["stat_lines"]["width"]))
        reference = settings["reference_lines"]
        self._reference_width_source = {
            key: float(reference[key]["width"])
            for key in ("lsl", "usl", "nominal")
        }
        self._reference_opacity_source = {
            key: float(reference[key].get("opacity", 1.0))
            for key in ("lsl", "usl", "nominal")
        }
        self._reference_width_control_value = float(reference["lsl"]["width"])
        self.reference_width_spin.setValue(self._reference_width_control_value)
        self._set_button_color(self.lsl_color_button, reference["lsl"]["color"])
        self._set_button_color(self.usl_color_button, reference["usl"]["color"])
        self._set_button_color(self.nominal_color_button, reference["nominal"]["color"])
        self._set_combo_data(self.lsl_dash_combo, reference["lsl"]["dash"])
        self._set_combo_data(self.usl_dash_combo, reference["usl"]["dash"])
        self._set_combo_data(self.nominal_dash_combo, reference["nominal"]["dash"])
        self._populate_element_combo()

    def _refresh_preview(self) -> None:
        settings = self.visual_settings()
        chart_type = str(self.chart_type_combo.currentData() or "histogram")
        self.summary_label.setText(dashboard_visual_settings_summary(settings))
        spec = build_dashboard_visual_preview_spec(
            settings,
            chart_type=chart_type,
            preview_group_names=self._preview_group_names,
        )
        self._preview_targets = self._extract_visual_targets(spec)
        if self._selected_target:
            selected_id = self._selected_target.get("target")
            refreshed = next(
                (target for target in self._preview_targets if target.get("target") == selected_id),
                None,
            )
            self._selected_target = dict(refreshed) if refreshed is not None else None
        self._populate_element_combo()
        if self._selected_target:
            self._load_selected_element_controls()
        self._sync_custom_controls()
        if spec and self.web_view is not None:
            self.web_view.setHtml(
                build_dashboard_visual_preview_html(
                    spec,
                    enable_selection_bridge=self._preview_bridge is not None,
                ),
                QUrl("about:blank"),
            )
        image_bytes = build_dashboard_visual_preview_png(
            settings,
            chart_type=chart_type,
            preview_group_names=self._preview_group_names,
        )
        if image_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(image_bytes):
                self._preview_source_pixmap = pixmap
                self._update_static_preview_pixmap()
                return
        self._preview_source_pixmap = None
        palette = ", ".join(dashboard_visual_swatch_palette(settings, count=5))
        self.preview_image_label.setText(f"Preview spec ready. Palette: {palette}")

    def _handle_control_changed(self, *_args) -> None:
        if self._populating_controls:
            return
        self._switch_to_custom_preserving_effective_style()
        self._sync_custom_controls()
        self._schedule_preview()

    def _handle_preset_changed(self, *_args) -> None:
        if self._populating_controls:
            return
        preset = str(self.preset_combo.currentData() or "auto")
        settings = dashboard_visual_recipe_settings(preset, base=self.visual_settings())
        self._prefer_resolved_selection_style = True
        try:
            self._populate_from_settings(settings)
        finally:
            self._prefer_resolved_selection_style = False
        self._schedule_preview()

    def _sync_custom_controls(self) -> None:
        settings = self.visual_settings()
        recipe = str(settings.get("recipe") or settings.get("preset") or "auto")
        is_auto = recipe == "auto"
        is_custom = recipe == "custom"
        palette = dashboard_visual_swatch_palette(
            settings,
            count=max(6, len(self._preview_palette_labels)),
        )
        preview_styles = dashboard_visual_effective_series_styles(
            settings,
            labels=self._preview_series_labels,
            chart_type=str(self.chart_type_combo.currentData() or "grouped_histogram")
            if hasattr(self, "chart_type_combo")
            else "grouped_histogram",
        )
        custom_swatches_enabled = (
            is_custom
            and self.palette_mode_combo.currentData() == "fixed"
            and self.palette_preset_combo.currentData() == "custom"
        )
        for index, button in enumerate(self._preview_color_buttons):
            style = preview_styles[index % len(preview_styles)]
            color = str(style.get("color") or palette[index % len(palette)])
            label = str(style.get("label") or self._preview_series_labels[index])
            self._set_button_color(button, color)
            button.setToolTip(f"{label}: {color}")
        if not custom_swatches_enabled:
            for index, button in enumerate(self._palette_buttons):
                self._set_button_color(button, palette[index % len(palette)])
        for widget in (
            self.palette_preset_combo,
            self.palette_mode_combo,
            self.gradient_spread_combo,
            self.anchor_color_button,
            self.distinguish_combo,
            self.marker_size_spin,
        ):
            widget.setEnabled(not is_auto)
        for button in self._palette_buttons:
            button.setEnabled(custom_swatches_enabled)
        gradient_enabled = is_custom and self.palette_mode_combo.currentData() in {
            "auto_gradient",
            "highlight_gradient",
        }
        self.gradient_spread_combo.setEnabled(gradient_enabled)
        self.anchor_color_button.setEnabled(gradient_enabled)
        has_selection = self._selected_target is not None
        for widget in (
            self.element_color_button,
            self.element_opacity_slider,
            self.element_opacity_spin,
            self.element_stat_accent_checkbox,
            self.reset_element_button,
        ):
            widget.setEnabled(has_selection)
        role = str((self._selected_target or {}).get("role") or "")
        capabilities = self._selected_target_capabilities(self._selected_target)
        self._set_selection_row_visible("color", has_selection)
        self._set_selection_row_visible("opacity", has_selection)
        self._set_selection_row_visible("line", has_selection and capabilities["line"])
        self._set_selection_row_visible("dash", has_selection and capabilities["line"])
        self._set_selection_row_visible("marker_size", has_selection and capabilities["marker_size"])
        self._set_selection_row_visible("marker_symbol", has_selection and capabilities["marker_symbol"])
        self._set_selection_row_visible("outline", has_selection and capabilities["outline"])
        self.element_width_spin.setEnabled(has_selection and capabilities["line"])
        self.element_dash_combo.setEnabled(has_selection and capabilities["line"])
        self.element_marker_size_spin.setEnabled(has_selection and capabilities["marker_size"])
        self.element_marker_symbol_combo.setEnabled(has_selection and capabilities["marker_symbol"])
        self.element_outline_checkbox.setEnabled(has_selection and capabilities["outline"])
        outline_enabled = (
            has_selection
            and capabilities["outline"]
            and self.element_outline_checkbox.isChecked()
        )
        self._set_selection_row_visible("outline_width", outline_enabled)
        self._set_selection_row_visible("outline_color", outline_enabled)
        self.element_outline_width_spin.setEnabled(outline_enabled)
        self.element_outline_color_mode_combo.setEnabled(outline_enabled)
        self.element_outline_color_button.setEnabled(
            outline_enabled and self.element_outline_color_mode_combo.currentData() == "custom"
        )
        self._set_selection_row_visible("pattern", has_selection and capabilities["pattern"])
        self.element_pattern_combo.setEnabled(has_selection and capabilities["pattern"])
        self._set_selection_row_visible("stat_accent", has_selection and role == "stat")
        self.element_stat_accent_checkbox.setEnabled(has_selection and role == "stat")

    def _set_selection_row_visible(self, row_key: str, visible: bool) -> None:
        for widget in self._selection_rows.get(row_key, []):
            widget.setVisible(bool(visible))

    def _populate_theme_combo(self) -> None:
        current = self.theme_combo.currentData() if hasattr(self, "theme_combo") else ""
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItem("Current settings", "")
        for theme in self._theme_library.get("themes", []):
            if not isinstance(theme, Mapping):
                continue
            self.theme_combo.addItem(str(theme.get("name") or "Theme"), str(theme.get("id") or ""))
        self._set_combo_data(self.theme_combo, str(current or ""))
        self.theme_combo.blockSignals(False)

    def _populate_palette_preset_combo(self) -> None:
        self.palette_preset_combo.clear()
        for key, meta in self._palette_presets.items():
            self.palette_preset_combo.addItem(str(meta.get("label") or key), key)
        self.palette_preset_combo.addItem("Custom swatches", "custom")

    def _handle_theme_selected(self, *_args) -> None:
        theme_id = str(self.theme_combo.currentData() or "")
        if not theme_id:
            self._sync_custom_controls()
            return
        for theme in self._theme_library.get("themes", []):
            if isinstance(theme, Mapping) and theme.get("id") == theme_id:
                settings = normalize_dashboard_visual_settings(theme.get("settings"))
                self._prefer_resolved_selection_style = True
                try:
                    self._populate_from_settings(settings)
                finally:
                    self._prefer_resolved_selection_style = False
                self._schedule_preview()
                return

    def _save_theme_as(self) -> None:
        name = self.theme_name_edit.text().strip() or dashboard_visual_settings_summary(
            self.visual_settings()
        )
        library, theme = upsert_dashboard_visual_theme(
            self._theme_library,
            name=name,
            settings=self.visual_settings(),
            set_default=True,
        )
        self._theme_library = save_dashboard_visual_theme_library(library)
        self._populate_theme_combo()
        self._set_combo_data(self.theme_combo, str(theme["id"]))
        self.theme_name_edit.setText(str(theme["name"]))

    def _update_theme(self) -> None:
        theme_id = str(self.theme_combo.currentData() or "")
        if not theme_id:
            self._save_theme_as()
            return
        name = self.theme_name_edit.text().strip() or dashboard_visual_settings_summary(
            self.visual_settings()
        )
        library, theme = upsert_dashboard_visual_theme(
            self._theme_library,
            name=name,
            settings=self.visual_settings(),
            theme_id=theme_id,
            set_default=True,
        )
        self._theme_library = save_dashboard_visual_theme_library(library)
        self._populate_theme_combo()
        self._set_combo_data(self.theme_combo, str(theme["id"]))

    def _delete_theme(self) -> None:
        theme_id = str(self.theme_combo.currentData() or "")
        if not theme_id:
            return
        self._theme_library = save_dashboard_visual_theme_library(
            remove_dashboard_visual_theme(self._theme_library, theme_id=theme_id)
        )
        self._populate_theme_combo()
        self.theme_name_edit.clear()
        self._handle_control_changed()

    def _handle_palette_preset_changed(self, *_args) -> None:
        if self._populating_controls:
            return
        self.preset_combo.blockSignals(True)
        self._set_combo_data(self.preset_combo, "custom")
        self.preset_combo.blockSignals(False)
        self._handle_control_changed()

    def _mark_custom_from_element_controls(self) -> None:
        if self._updating_selection_controls:
            return
        if self._selected_target is not None:
            self._apply_selected_element_style()
        else:
            self._switch_to_custom_preserving_effective_style()

    def _switch_to_custom_preserving_effective_style(
        self,
        *,
        reload_selection_controls: bool = True,
    ) -> None:
        if self.preset_combo.currentData() == "custom":
            return
        selected_target = dict(self._selected_target) if self._selected_target else None
        base_settings = self.visual_settings()
        effective_palette = dashboard_visual_swatch_palette(
            base_settings,
            count=max(6, len(self._preview_series_labels)),
        )
        settings = dashboard_visual_recipe_settings("custom", base=base_settings)
        settings["palette_preset"] = "custom"
        settings["palette_mode"] = "fixed"
        settings["palette"] = effective_palette
        if reload_selection_controls:
            self._populate_from_settings(settings)
        else:
            self._populating_controls = True
            try:
                self._populate_from_settings_unchecked(settings)
            finally:
                self._populating_controls = False
            self._sync_custom_controls()
        self._selected_target = selected_target
        self._populate_element_combo()

    def _extract_visual_targets(self, spec: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(spec, Mapping):
            return []
        traces = spec.get("data")
        if not isinstance(traces, list):
            return []
        targets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, trace in enumerate(traces):
            if not isinstance(trace, Mapping):
                continue
            target = self._target_from_trace(trace, index)
            if not target or target["target"] in seen:
                continue
            seen.add(target["target"])
            targets.append(target)
        return targets

    def _target_from_trace(self, trace: Mapping[str, Any], index: int) -> dict[str, Any] | None:
        meta = trace.get("meta") if isinstance(trace.get("meta"), Mapping) else {}
        target_id = str(meta.get("metroliza_target_id") or meta.get("dashboard_visual_target") or "")
        role = str(meta.get("metroliza_role") or meta.get("dashboard_visual_role") or "")
        chart_kind = str(meta.get("metroliza_chart_kind") or meta.get("dashboard_visual_chart_kind") or "")
        name = str(trace.get("name") or "").strip()
        line = trace.get("line") if isinstance(trace.get("line"), Mapping) else {}
        marker = trace.get("marker") if isinstance(trace.get("marker"), Mapping) else {}
        capabilities = (
            meta.get("metroliza_style_capabilities")
            or meta.get("dashboard_visual_capabilities")
            or meta.get("metroliza_visual_capabilities")
        )
        if not isinstance(capabilities, list):
            capabilities = []
        target_style = {
            "color": str(
                marker.get("color")
                or line.get("color")
                or trace.get("fillcolor")
                or ""
            ),
            "opacity": trace.get("opacity"),
            "width": line.get("width"),
            "dash": line.get("dash"),
            "marker_size": marker.get("size"),
            "marker_symbol": marker.get("symbol"),
            "outline_width": (
                marker.get("line", {}).get("width")
                if isinstance(marker.get("line"), Mapping)
                else None
            ),
            "outline_color": (
                marker.get("line", {}).get("color")
                if isinstance(marker.get("line"), Mapping)
                else None
            ),
            "pattern_shape": (
                marker.get("pattern", {}).get("shape")
                if isinstance(marker.get("pattern"), Mapping)
                else ""
            ),
        }
        if target_id:
            target_role = role or "series"
            return {
                "target": target_id,
                "role": target_role,
                "label": str(meta.get("metroliza_legend_label") or name or target_id),
                "trace": index,
                "chart_kind": chart_kind,
                "trace_type": str(trace.get("type") or ""),
                "mode": str(trace.get("mode") or ""),
                "group": str(meta.get("metroliza_series_id") or ""),
                "stat": str(meta.get("metroliza_stat_id") or ""),
                "key": str(meta.get("metroliza_reference_id") or ""),
                "capabilities": (
                    [str(item) for item in capabilities]
                    or self._trace_capabilities(trace, target_role)
                ),
                "style": target_style,
            }
        reference = name.split("=", 1)[0].strip().casefold()
        if reference in {"lsl", "usl", "nominal"}:
            return {
                "target": f"reference:{reference}",
                "role": "reference",
                "key": reference,
                "label": name,
                "trace": index,
                "chart_kind": chart_kind,
                "trace_type": str(trace.get("type") or ""),
                "mode": str(trace.get("mode") or ""),
                "capabilities": self._trace_capabilities(trace, "reference"),
                "style": target_style,
            }
        match = name and re.match(r"^(?:\((.+?)\)\s*)?(Min|Q1|Median|Mean|Q3|Max)=", name, re.IGNORECASE)
        if match:
            group = str(match.group(1) or "")
            stat = str(match.group(2) or "").casefold()
            key = f"{group.casefold()}::{stat}" if group else stat
            return {
                "target": f"stat:{key}",
                "role": "stat",
                "group": group,
                "stat": stat,
                "label": name,
                "trace": index,
                "chart_kind": chart_kind,
                "trace_type": str(trace.get("type") or ""),
                "mode": str(trace.get("mode") or ""),
                "capabilities": self._trace_capabilities(trace, "stat"),
                "style": target_style,
            }
        if name:
            role = "model_curve" if "curve" in name.casefold() or "kde" in name.casefold() else "series"
            return {
                "target": f"{role}:{name.casefold()}",
                "role": role,
                "label": name,
                "trace": index,
                "chart_kind": chart_kind,
                "trace_type": str(trace.get("type") or ""),
                "mode": str(trace.get("mode") or ""),
                "capabilities": self._trace_capabilities(trace, role),
                "style": target_style,
            }
        return None

    def _selected_target_capabilities(self, target: Mapping[str, Any] | None) -> dict[str, bool]:
        values = target.get("capabilities") if isinstance(target, Mapping) else []
        capabilities = {str(item) for item in values} if isinstance(values, list) else set()
        return {
            "line": bool(capabilities & {"width", "dash"}),
            "marker_size": "marker_size" in capabilities,
            "marker_symbol": "marker_symbol" in capabilities,
            "outline": bool(capabilities & {"outline_width", "outline_color", "outline_color_mode"}),
            "pattern": "pattern_shape" in capabilities,
        }

    def _selected_target_chart_kind(self, target: Mapping[str, Any]) -> str:
        chart = str(
            self.chart_type_combo.currentData() if hasattr(self, "chart_type_combo") else ""
        ).casefold()
        raw = str(target.get("chart_kind") or "").strip().casefold()
        if raw == "violin":
            raw = "distribution"
        if raw == "histogram" and chart == "histogram":
            raw = "grouped_histogram"
        if raw in {
            "histogram",
            "grouped_histogram",
            "distribution",
            "iqr",
            "scatter",
            "trend",
            "model_curve",
        }:
            return raw
        role = str(target.get("role") or "").casefold()
        if role in {"trend", "model_curve"}:
            return role
        trace_type = str(target.get("trace_type") or "").casefold()
        if trace_type in {"bar", "histogram"}:
            return "grouped_histogram" if chart == "histogram" else "histogram"
        if chart == "violin":
            return "distribution"
        if chart in {"histogram", "iqr", "scatter"}:
            return "grouped_histogram" if chart == "histogram" else chart
        return "grouped_histogram"

    def _resolved_preview_series_style(
        self,
        label: str,
        target: Mapping[str, Any],
    ) -> dict[str, Any]:
        labels = list(self._preview_series_labels)
        if _preview_label_key(label) not in {_preview_label_key(item) for item in labels}:
            labels.append(label)
        styles = dashboard_visual_effective_series_styles(
            self.visual_settings(),
            labels=labels,
            chart_type=self._selected_target_chart_kind(target),
        )
        key = _preview_label_key(label)
        for style in styles:
            if _preview_label_key(str(style.get("label") or "")) == key:
                return dict(style)
        return {}

    @staticmethod
    def _trace_capabilities(trace: Mapping[str, Any], role: str) -> list[str]:
        role = str(role or "").casefold()
        if role in {"reference", "stat", "trend", "model_curve"}:
            return ["color", "opacity", "width", "dash"]
        trace_type = str(trace.get("type") or "").casefold()
        mode = str(trace.get("mode") or "").casefold()
        capabilities = ["color", "opacity"]
        if "lines" in mode:
            capabilities.extend(["width", "dash"])
        if trace_type == "scatter" and "markers" in mode:
            capabilities.extend(["marker_size", "marker_symbol", "outline_width", "outline_color", "outline_color_mode"])
        if trace_type in {"bar", "histogram"}:
            capabilities.append("pattern_shape")
        return capabilities

    def _populate_element_combo(self) -> None:
        if not hasattr(self, "element_combo"):
            return
        current = self._selected_target["target"] if self._selected_target else ""
        self.element_combo.blockSignals(True)
        self.element_combo.clear()
        self.element_combo.addItem("Click a plot element or choose one", "")
        for target in self._preview_targets:
            self.element_combo.addItem(str(target.get("label") or target["target"]), target["target"])
        self._set_combo_data(self.element_combo, current)
        self.element_combo.blockSignals(False)

    def _handle_element_combo_changed(self, *_args) -> None:
        target_id = str(self.element_combo.currentData() or "")
        if not target_id:
            self._selected_target = None
            self._sync_custom_controls()
            return
        for target in self._preview_targets:
            if target.get("target") == target_id:
                self._selected_target = dict(target)
                self._load_selected_element_controls()
                self._sync_custom_controls()
                return

    def _select_preview_series(self, index: int) -> None:
        series_targets = [
            target
            for target in self._preview_targets
            if str(target.get("role") or "") == "series"
        ]
        target = series_targets[index] if 0 <= index < len(series_targets) else None
        if target is None and 0 <= index < len(self._preview_targets):
            target = self._preview_targets[index]
        if target is None:
            return
        self._selected_target = dict(target)
        self._populate_element_combo()
        self._load_selected_element_controls()
        self._sync_custom_controls()

    def _handle_preview_target_payload(self, payload: str) -> None:
        try:
            target = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(target, Mapping):
            return
        target_id = str(target.get("target") or "")
        if not target_id:
            return
        matching = next((item for item in self._preview_targets if item.get("target") == target_id), None)
        self._selected_target = dict(matching or target)
        self._populate_element_combo()
        self._load_selected_element_controls()
        self._sync_custom_controls()

    def _load_selected_element_controls(self) -> None:
        target = self._selected_target or {}
        role = str(target.get("role") or "")
        style = self._selected_element_style(target)
        self._updating_selection_controls = True
        try:
            self._set_button_color(self.element_color_button, str(style.get("color") or "#245a5a"))
            self.element_opacity_slider.setValue(round(float(style.get("opacity", 1.0)) * 100))
            self.element_width_spin.setValue(float(style.get("width", 2.0)))
            self._set_combo_data(self.element_dash_combo, str(style.get("dash") or "solid"))
            self.element_marker_size_spin.setValue(float(style.get("marker_size", self.marker_size_spin.value())))
            self._set_combo_data(self.element_marker_symbol_combo, str(style.get("marker_symbol") or "circle"))
            outline_width = float(style.get("outline_width", 0.0) or 0.0)
            outline_color_mode = str(style.get("outline_color_mode") or "auto")
            self.element_outline_checkbox.setChecked(outline_width > 0)
            self.element_outline_width_spin.setValue(outline_width if outline_width > 0 else 1.25)
            self._set_combo_data(self.element_outline_color_mode_combo, outline_color_mode)
            self._set_button_color(self.element_outline_color_button, str(style.get("outline_color") or "#111827"))
            self._set_combo_data(self.element_pattern_combo, str(style.get("pattern_shape") or ""))
            self.element_stat_accent_checkbox.setChecked(role == "stat" and self.stat_accent_combo.currentData() == "accent")
        finally:
            self._updating_selection_controls = False
        self._sync_custom_controls()

    def _selected_element_style(self, target: Mapping[str, Any]) -> dict[str, Any]:
        role = str(target.get("role") or "")
        trace_style = target.get("style") if isinstance(target.get("style"), Mapping) else {}
        if role == "reference":
            key = str(target.get("key") or "").casefold()
            reference = self.visual_settings()["reference_lines"].get(key, {})
            style = dict(reference)
            style.setdefault("color", trace_style.get("color") or "#245a5a")
            style.setdefault("opacity", trace_style.get("opacity") or 1.0)
            style.setdefault("width", trace_style.get("width") or 2.0)
            style.setdefault("dash", trace_style.get("dash") or "solid")
            return style
        if role == "stat":
            key = self._stat_override_key(target)
            style = dict(self._stat_line_overrides.get(key) or {})
            settings = self.visual_settings()
            style.setdefault("width", settings["stat_lines"]["width"])
            style.setdefault("dash", trace_style.get("dash") or "solid")
            style.setdefault("opacity", trace_style.get("opacity") or 1.0)
            style.setdefault(
                "color",
                trace_style.get("color") or dashboard_visual_swatch_palette(settings, count=1)[0],
            )
            return style
        label = str(target.get("label") or "")
        if role == "series" and _is_population_preview_label(label, self._population_baseline):
            style = dict(self._population_baseline)
            resolved_style = self._resolved_preview_series_style(label, target)
            raw_opacity = style.get("opacity")
            trace_opacity = trace_style.get("opacity")
            if isinstance(raw_opacity, Mapping):
                chart_kind = self._selected_target_chart_kind(target)
                mapped_opacity = raw_opacity.get(chart_kind)
                if mapped_opacity is None:
                    mapped_opacity = raw_opacity.get("grouped_histogram")
                if mapped_opacity is None:
                    mapped_opacity = raw_opacity.get("scatter")
                style["opacity"] = trace_opacity if trace_opacity is not None else mapped_opacity
            style.setdefault(
                "color",
                _first_style_value(resolved_style.get("color"), trace_style.get("color"), "#8a949e"),
            )
            if style.get("opacity") is None:
                style["opacity"] = trace_opacity if trace_opacity is not None else 0.35
            style.setdefault("marker_size", trace_style.get("marker_size") or 4.5)
            style.setdefault("marker_symbol", trace_style.get("marker_symbol") or "circle")
            style.setdefault("outline_width", trace_style.get("outline_width") or 0.0)
            style.setdefault("outline_color_mode", style.get("outline_color_mode") or "auto")
            style.setdefault("outline_color", trace_style.get("outline_color") or "#111827")
            style.setdefault("pattern_shape", trace_style.get("pattern_shape") or "")
            return style
        key = _preview_label_key(label)
        style = dict(self._series_overrides.get(key) or {})
        settings = self.visual_settings()
        resolved_style = self._resolved_preview_series_style(label, target)
        first_style = resolved_style if self._prefer_resolved_selection_style else trace_style
        second_style = trace_style if self._prefer_resolved_selection_style else resolved_style
        style.setdefault(
            "color",
            _first_style_value(
                first_style.get("color"),
                second_style.get("color"),
                dashboard_visual_swatch_palette(settings, count=1)[0],
            ),
        )
        style.setdefault(
            "opacity",
            _first_style_value(
                first_style.get("opacity"),
                second_style.get("opacity"),
                1.0,
            ),
        )
        style.setdefault("width", _first_style_value(first_style.get("width"), second_style.get("width"), 2.0))
        style.setdefault("dash", _first_style_value(first_style.get("dash"), second_style.get("dash"), "solid"))
        style.setdefault(
            "marker_size",
            _first_style_value(
                first_style.get("marker_size"),
                second_style.get("marker_size"),
                settings["marker_size"],
            ),
        )
        style.setdefault(
            "marker_symbol",
            _first_style_value(
                first_style.get("marker_symbol"),
                second_style.get("marker_symbol"),
                "circle",
            ),
        )
        style.setdefault(
            "outline_width",
            _first_style_value(
                first_style.get("outline_width"),
                second_style.get("outline_width"),
                0.0,
            ),
        )
        style.setdefault(
            "outline_color_mode",
            _first_style_value(
                style.get("outline_color_mode"),
                first_style.get("outline_color_mode"),
                second_style.get("outline_color_mode"),
                "auto",
            ),
        )
        style.setdefault(
            "outline_color",
            _first_style_value(
                first_style.get("outline_color"),
                second_style.get("outline_color"),
                "#111827",
            ),
        )
        style.setdefault(
            "pattern_shape",
            _first_style_value(
                first_style.get("pattern_shape"),
                second_style.get("pattern_shape"),
                "",
            ),
        )
        return style

    def _apply_selected_element_style(self) -> None:
        target = self._selected_target
        if not target:
            return
        role = str(target.get("role") or "")
        capabilities = self._selected_target_capabilities(target)
        color = str(self.element_color_button.property("color") or "#245a5a")
        style = {
            "color": color,
            "opacity": self.element_opacity_slider.value() / 100.0,
        }
        if capabilities["line"]:
            style["width"] = self.element_width_spin.value()
            style["dash"] = str(self.element_dash_combo.currentData() or "solid")
        self._switch_to_custom_preserving_effective_style(reload_selection_controls=False)
        if role == "reference":
            key = str(target.get("key") or "").casefold()
            width = float(style.get("width", self.reference_width_spin.value()))
            dash = str(style.get("dash") or "solid")
            if key in self._reference_opacity_source:
                self._reference_opacity_source[key] = style["opacity"]
                self._reference_width_source[key] = width
                self._reference_width_control_value = width
            if key == "lsl":
                self._set_button_color(self.lsl_color_button, color)
                self._set_combo_data(self.lsl_dash_combo, dash)
            elif key == "usl":
                self._set_button_color(self.usl_color_button, color)
                self._set_combo_data(self.usl_dash_combo, dash)
            elif key == "nominal":
                self._set_button_color(self.nominal_color_button, color)
                self._set_combo_data(self.nominal_dash_combo, dash)
            self.reference_width_spin.setValue(width)
        elif role == "stat":
            if self.element_stat_accent_checkbox.isChecked():
                self._set_combo_data(self.stat_accent_combo, "accent")
            self._stat_line_overrides[self._stat_override_key(target)] = style
        else:
            label = str(target.get("label") or "")
            if label:
                is_population = _is_population_preview_label(label, self._population_baseline)
                if capabilities["marker_size"]:
                    style["marker_size"] = self.element_marker_size_spin.value()
                if capabilities["marker_symbol"]:
                    style["marker_symbol"] = str(self.element_marker_symbol_combo.currentData() or "circle")
                if capabilities["outline"]:
                    style["outline_width"] = (
                        self.element_outline_width_spin.value()
                        if self.element_outline_checkbox.isChecked()
                        else 0.0
                    )
                    style["outline_color_mode"] = str(
                        self.element_outline_color_mode_combo.currentData() or "auto"
                    )
                    if style["outline_color_mode"] == "custom":
                        style["outline_color"] = str(
                            self.element_outline_color_button.property("color") or "#111827"
                        )
                    else:
                        style.pop("outline_color", None)
                if capabilities["pattern"]:
                    style["pattern_shape"] = str(self.element_pattern_combo.currentData() or "")
                key = _preview_label_key(label)
                if is_population:
                    population_style = dict(style)
                    opacity_value = population_style.pop("opacity", None)
                    if opacity_value is not None:
                        raw_opacity = self._population_baseline.get("opacity")
                        opacity_map = dict(raw_opacity) if isinstance(raw_opacity, Mapping) else {}
                        opacity_map[self._selected_target_chart_kind(target)] = float(opacity_value)
                        population_style["opacity"] = opacity_map
                    self._population_baseline.update(population_style)
                    self._series_overrides.pop(key, None)
                else:
                    palette_index = _preview_palette_index_for_label(
                        label,
                        self._preview_palette_labels,
                    )
                    if palette_index is not None and "color" in style:
                        self._set_button_color(self._palette_buttons[palette_index], str(style["color"]))
                        style = dict(style)
                        style.pop("color", None)
                    if style:
                        self._series_overrides[key] = style
                    else:
                        self._series_overrides.pop(key, None)
        self._handle_control_changed()

    def _reset_selected_element_style(self) -> None:
        target = self._selected_target
        if not target:
            return
        role = str(target.get("role") or "")
        if role == "stat":
            self._stat_line_overrides.pop(self._stat_override_key(target), None)
        elif role in {"series", "trend", "model_curve"}:
            label = str(target.get("label") or "")
            key = _preview_label_key(label)
            if role == "series" and _is_population_preview_label(label, self._population_baseline):
                self._population_baseline = dict(default_dashboard_visual_settings()["population_baseline"])
            elif role == "series":
                self._reset_selected_series_palette_entry(label)
            self._series_overrides.pop(key, None)
        elif role == "reference":
            defaults = default_dashboard_visual_settings()["reference_lines"]
            key = str(target.get("key") or "").casefold()
            if key in defaults:
                if key == "lsl":
                    self._set_button_color(self.lsl_color_button, defaults[key]["color"])
                    self._set_combo_data(self.lsl_dash_combo, defaults[key]["dash"])
                elif key == "usl":
                    self._set_button_color(self.usl_color_button, defaults[key]["color"])
                    self._set_combo_data(self.usl_dash_combo, defaults[key]["dash"])
                elif key == "nominal":
                    self._set_button_color(self.nominal_color_button, defaults[key]["color"])
                    self._set_combo_data(self.nominal_dash_combo, defaults[key]["dash"])
                self._reference_opacity_source[key] = float(defaults[key].get("opacity", 1.0))
                self._reference_width_source[key] = float(defaults[key].get("width", 1.5))
                self._reference_width_control_value = float(defaults[key].get("width", 1.5))
                self.reference_width_spin.setValue(self._reference_width_control_value)
        self._handle_control_changed()

    def _reset_selected_series_palette_entry(self, label: str) -> None:
        palette_index = _preview_palette_index_for_label(label, self._preview_palette_labels)
        if palette_index is None or palette_index >= len(self._palette_buttons):
            return
        reset_palette = dashboard_visual_swatch_palette(
            self._settings,
            count=max(6, len(self._preview_palette_labels)),
        )
        if not reset_palette:
            reset_palette = list(DEFAULT_DASHBOARD_PALETTE)
        self._set_button_color(
            self._palette_buttons[palette_index],
            reset_palette[palette_index % len(reset_palette)],
        )

    def _stat_override_key(self, target: Mapping[str, Any]) -> str:
        stat = str(target.get("stat") or "").casefold()
        group = str(target.get("group") or "").casefold()
        return f"{group}::{stat}" if group else stat

    def _schedule_preview(self) -> None:
        if self._suppress_preview_schedule:
            self._preview_timer.stop()
            return
        self._preview_timer.start(180)

    def _new_preview_timer(self) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._refresh_preview)
        return timer

    def _release_preview_schedule_suppression(self) -> None:
        self._suppress_preview_schedule = False

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method.
        super().resizeEvent(event)
        self._update_static_preview_pixmap()

    def _update_static_preview_pixmap(self) -> None:
        if self._preview_source_pixmap is None or self._preview_source_pixmap.isNull():
            return
        target_size = self.preview_image_label.size()
        if not target_size.isValid() or target_size.width() <= 0 or target_size.height() <= 0:
            return
        self.preview_image_label.setPixmap(
            self._preview_source_pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _choose_color(self, button: QPushButton) -> None:
        initial = QColor(str(button.property("color") or "#ffffff"))
        color = QColorDialog.getColor(initial, self, "Choose color")
        if not self._color_dialog_result_is_valid(color):
            self._suppress_preview_schedule = True
            self._preview_timer.stop()
            self._preview_timer.deleteLater()
            self._preview_timer = self._new_preview_timer()
            QTimer.singleShot(250, self._release_preview_schedule_suppression)
            return
        self._set_button_color(button, color.name().lower())
        if button in {
            getattr(self, "element_color_button", None),
            getattr(self, "element_outline_color_button", None),
        } and self._selected_target:
            self._apply_selected_element_style()
            return
        self._handle_control_changed()

    @staticmethod
    def _color_dialog_result_is_valid(color: Any) -> bool:
        is_valid = getattr(color, "isValid", None)
        if not callable(is_valid) or not is_valid():
            return False
        name = getattr(color, "name", None)
        if not callable(name):
            return False
        color_name = str(name()).strip().lower()
        if not color_name.startswith("#") or len(color_name) != 7:
            return False
        if color_name == "#000000" and color.__class__ is not QColor:
            return False
        return True

    def _reset_defaults(self) -> None:
        self._suppress_preview_schedule = False
        self._populate_from_settings(default_dashboard_visual_settings())
        self._handle_control_changed()

    def _reference_line_width(self, key: str, *, fallback: float, preserve: bool) -> float:
        if preserve:
            return float(self._reference_width_source.get(key, fallback))
        return float(fallback)

    def _reference_line_opacity(self, key: str) -> float:
        return float(self._reference_opacity_source.get(key, 1.0))

    @staticmethod
    def _combo(items: tuple[tuple[str, str], ...]) -> QComboBox:
        combo = QComboBox()
        for label, value in items:
            combo.addItem(label, value)
        return combo

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _color_button(color: str) -> QPushButton:
        button = QPushButton()
        button.setFixedSize(44, 24)
        DashboardVisualOptionsDialog._set_button_color(button, color)
        return button

    @staticmethod
    def _set_button_color(button: QPushButton, color: str) -> None:
        button.setProperty("color", color)
        button.setStyleSheet(f"QPushButton {{ background: {color}; border: 1px solid #8a93a3; }}")
        button.setToolTip(color)

    @staticmethod
    def _opacity_slider() -> QSlider:
        slider = QSlider()
        slider.setOrientation(Qt.Orientation.Horizontal)
        slider.setRange(5, 100)
        slider.setTickInterval(5)
        return slider

    @staticmethod
    def _opacity_spin() -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(5, 100)
        spin.setSingleStep(5)
        spin.setSuffix("%")
        spin.setFixedWidth(72)
        return spin

    @staticmethod
    def _slider_spin_row(slider: QSlider, spin: QSpinBox) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider, 1)
        layout.addWidget(spin, 0)
        return widget

    @staticmethod
    def _bind_opacity_controls(slider: QSlider, spin: QSpinBox, *, changed) -> None:
        def slider_changed(value: int) -> None:
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
            changed()

        def spin_changed(value: int) -> None:
            slider.setValue(value)

        slider.valueChanged.connect(slider_changed)
        spin.valueChanged.connect(spin_changed)

    @staticmethod
    def _line_width_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.5, 6.0)
        spin.setSingleStep(0.25)
        return spin

    @staticmethod
    def _dash_combo() -> QComboBox:
        return DashboardVisualOptionsDialog._combo(
            (("Solid", "solid"), ("Dash", "dash"), ("Dot", "dot"), ("Dash-dot", "dashdot"))
        )

    @staticmethod
    def _line_style_row(color_button: QPushButton, dash_combo: QComboBox) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(color_button)
        layout.addWidget(dash_combo)
        return widget


__all__ = ["DashboardVisualOptionsDialog"]
