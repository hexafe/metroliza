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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.dashboard_visual_options import (
    DEFAULT_DASHBOARD_PALETTE,
    build_dashboard_visual_preview_html,
    build_dashboard_visual_preview_png,
    build_dashboard_visual_preview_spec,
    dashboard_visual_palette_presets,
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
from modules.ui_foundation import apply_metroliza_theme, configure_accessibility, configure_window_size

try:  # Optional. PyQt WebEngine is intentionally not a hard runtime dependency.
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - depends on local Qt installation.
    QWebEngineView = None

try:  # Optional bridge for click-to-select preview editing.
    from PyQt6.QtWebChannel import QWebChannel
except Exception:  # pragma: no cover - depends on local Qt installation.
    QWebChannel = None


_PRESET_ITEMS = (
    ("Auto", "auto"),
    ("Distinct groups", "distinct"),
    ("Print friendly", "print"),
    ("Custom", "custom"),
)
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
        persist_on_accept: bool = True,
    ):
        super().__init__(parent)
        self._settings = normalize_dashboard_visual_settings(settings)
        self._persist_on_accept = bool(persist_on_accept)
        self._palette_buttons: list[QPushButton] = []
        self._series_overrides = dict(self._settings.get("series_overrides") or {})
        self._stat_line_overrides = dict(self._settings.get("stat_line_overrides") or {})
        self._theme_library = load_dashboard_visual_theme_library()
        self._palette_presets = dashboard_visual_palette_presets()
        self._preview_targets: list[dict[str, Any]] = []
        self._selected_target: dict[str, Any] | None = None
        self._updating_selection_controls = False
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
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)
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
        settings["theme_id"] = str(self.theme_combo.currentData() or "")
        settings["theme_name"] = self.theme_name_edit.text().strip()
        settings["preset"] = str(self.preset_combo.currentData() or "auto")
        settings["palette_preset"] = str(self.palette_preset_combo.currentData() or "metroliza")
        settings["palette_mode"] = str(self.palette_mode_combo.currentData() or "fixed")
        settings["palette"] = [button.property("color") for button in self._palette_buttons]
        settings["anchor_color"] = str(self.anchor_color_button.property("color") or "#facc15")
        settings["gradient_spread"] = str(self.gradient_spread_combo.currentData() or "normal")
        settings["distinguish"] = str(self.distinguish_combo.currentData() or "when_similar")
        settings["opacity"] = {
            "histogram": self.histogram_opacity_slider.value() / 100.0,
            "grouped_histogram": self.grouped_histogram_opacity_slider.value() / 100.0,
            "distribution": self.distribution_opacity_slider.value() / 100.0,
            "iqr": self.iqr_opacity_slider.value() / 100.0,
            "scatter": self.scatter_opacity_slider.value() / 100.0,
            "trend": self.trend_opacity_slider.value() / 100.0,
            "model_curve": self.model_curve_opacity_slider.value() / 100.0,
        }
        settings["marker_size"] = self.marker_size_spin.value()
        settings["stat_lines"] = {
            "accent_by_stat": self.stat_accent_combo.currentData() == "accent",
            "width": self.stat_width_spin.value(),
        }
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
        self.preset_combo.currentIndexChanged.connect(self._handle_control_changed)
        preset_group = QGroupBox("Mode")
        preset_form = QFormLayout(preset_group)
        preset_form.addRow("Preset", self.preset_combo)
        controls_layout.addWidget(preset_group)

        palette_group = QGroupBox("Palette")
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
        controls_layout.addWidget(palette_group)

        series_group = QGroupBox("Series")
        series_form = QFormLayout(series_group)
        self.distinguish_combo = self._combo(_DISTINGUISH_ITEMS)
        self.marker_size_spin = QDoubleSpinBox()
        self.marker_size_spin.setRange(2.0, 18.0)
        self.marker_size_spin.setSingleStep(0.5)
        self.marker_size_spin.valueChanged.connect(lambda _value: self._handle_control_changed())
        self.distinguish_combo.currentIndexChanged.connect(self._handle_control_changed)
        series_form.addRow("Distinguish", self.distinguish_combo)
        series_form.addRow("Marker size", self.marker_size_spin)
        controls_layout.addWidget(series_group)

        opacity_group = QGroupBox("Opacity")
        opacity_form = QFormLayout(opacity_group)
        self.histogram_opacity_slider = self._opacity_slider()
        self.grouped_histogram_opacity_slider = self._opacity_slider()
        self.distribution_opacity_slider = self._opacity_slider()
        self.iqr_opacity_slider = self._opacity_slider()
        self.scatter_opacity_slider = self._opacity_slider()
        self.trend_opacity_slider = self._opacity_slider()
        self.model_curve_opacity_slider = self._opacity_slider()
        for slider in (
            self.histogram_opacity_slider,
            self.grouped_histogram_opacity_slider,
            self.distribution_opacity_slider,
            self.iqr_opacity_slider,
            self.scatter_opacity_slider,
            self.trend_opacity_slider,
            self.model_curve_opacity_slider,
        ):
            slider.valueChanged.connect(lambda _value: self._schedule_preview())
        opacity_form.addRow("Histogram", self.histogram_opacity_slider)
        opacity_form.addRow("Grouped histogram", self.grouped_histogram_opacity_slider)
        opacity_form.addRow("Violin", self.distribution_opacity_slider)
        opacity_form.addRow("IQR", self.iqr_opacity_slider)
        opacity_form.addRow("Scatter", self.scatter_opacity_slider)
        opacity_form.addRow("Trend", self.trend_opacity_slider)
        opacity_form.addRow("Model curve", self.model_curve_opacity_slider)
        controls_layout.addWidget(opacity_group)

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
        controls_layout.addWidget(line_group)

        selection_group = QGroupBox("Selected element")
        selection_form = QFormLayout(selection_group)
        self.element_combo = QComboBox()
        self.element_combo.addItem("Click a plot element or choose one", "")
        self.element_combo.currentIndexChanged.connect(self._handle_element_combo_changed)
        self.element_color_button = self._color_button("#245a5a")
        self.element_color_button.clicked.connect(lambda: self._choose_color(self.element_color_button))
        self.element_opacity_slider = self._opacity_slider()
        self.element_width_spin = self._line_width_spin()
        self.element_dash_combo = self._dash_combo()
        self.element_marker_size_spin = QDoubleSpinBox()
        self.element_marker_size_spin.setRange(2.0, 18.0)
        self.element_marker_size_spin.setSingleStep(0.5)
        self.element_pattern_combo = self._combo(
            (("None", ""), ("Diagonal", "/"), ("Back diagonal", "\\"), ("Cross", "x"), ("Dots", "."), ("Horizontal", "-"))
        )
        self.element_stat_accent_checkbox = QCheckBox("Use stat accent")
        self.apply_element_button = QPushButton("Apply to selection")
        self.reset_element_button = QPushButton("Reset selection")
        self.apply_element_button.clicked.connect(self._apply_selected_element_style)
        self.reset_element_button.clicked.connect(self._reset_selected_element_style)
        for widget in (
            self.element_opacity_slider,
            self.element_width_spin,
            self.element_dash_combo,
            self.element_marker_size_spin,
            self.element_pattern_combo,
            self.element_stat_accent_checkbox,
        ):
            signal = getattr(widget, "valueChanged", None) or getattr(widget, "currentIndexChanged", None) or getattr(widget, "stateChanged", None)
            if signal is not None:
                signal.connect(lambda *_args: self._mark_custom_from_element_controls())
        selection_actions = QWidget()
        selection_actions_layout = QHBoxLayout(selection_actions)
        selection_actions_layout.setContentsMargins(0, 0, 0, 0)
        selection_actions_layout.addWidget(self.apply_element_button)
        selection_actions_layout.addWidget(self.reset_element_button)
        selection_form.addRow("Element", self.element_combo)
        selection_form.addRow("Color", self.element_color_button)
        selection_form.addRow("Opacity", self.element_opacity_slider)
        selection_form.addRow("Width", self.element_width_spin)
        selection_form.addRow("Dash", self.element_dash_combo)
        selection_form.addRow("Marker size", self.element_marker_size_spin)
        selection_form.addRow("Pattern", self.element_pattern_combo)
        selection_form.addRow("", self.element_stat_accent_checkbox)
        selection_form.addRow("", selection_actions)
        controls_layout.addWidget(selection_group)
        controls_layout.addStretch(1)

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
        configure_accessibility(self.chart_type_combo, name="Dashboard visual preview chart")

    def _populate_from_settings(self, settings: Mapping[str, Any]) -> None:
        self._series_overrides = dict(settings.get("series_overrides") or {})
        self._stat_line_overrides = dict(settings.get("stat_line_overrides") or {})
        self.theme_name_edit.setText(str(settings.get("theme_name") or ""))
        self.theme_combo.blockSignals(True)
        self._set_combo_data(self.theme_combo, str(settings.get("theme_id") or ""))
        self.theme_combo.blockSignals(False)
        self._set_combo_data(self.preset_combo, settings["preset"])
        self._set_combo_data(self.palette_preset_combo, settings["palette_preset"])
        self._set_combo_data(self.palette_mode_combo, settings["palette_mode"])
        self._set_combo_data(self.gradient_spread_combo, settings["gradient_spread"])
        self._set_combo_data(self.distinguish_combo, settings["distinguish"])
        self._set_combo_data(self.stat_accent_combo, "accent" if settings["stat_lines"]["accent_by_stat"] else "group")
        palette = list(settings["palette"])
        for index, button in enumerate(self._palette_buttons):
            self._set_button_color(button, palette[index % len(palette)])
        self._set_button_color(self.anchor_color_button, settings["anchor_color"])
        opacity = settings["opacity"]
        self.histogram_opacity_slider.setValue(round(opacity["histogram"] * 100))
        self.grouped_histogram_opacity_slider.setValue(round(opacity["grouped_histogram"] * 100))
        self.distribution_opacity_slider.setValue(round(opacity["distribution"] * 100))
        self.iqr_opacity_slider.setValue(round(opacity["iqr"] * 100))
        self.scatter_opacity_slider.setValue(round(opacity["scatter"] * 100))
        self.trend_opacity_slider.setValue(round(opacity["trend"] * 100))
        self.model_curve_opacity_slider.setValue(round(opacity["model_curve"] * 100))
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
        spec = build_dashboard_visual_preview_spec(settings, chart_type=chart_type)
        self._preview_targets = self._extract_visual_targets(spec)
        self._populate_element_combo()
        if spec and self.web_view is not None:
            self.web_view.setHtml(
                build_dashboard_visual_preview_html(
                    spec,
                    enable_selection_bridge=self._preview_bridge is not None,
                ),
                QUrl("about:blank"),
            )
        image_bytes = build_dashboard_visual_preview_png(settings, chart_type=chart_type)
        if image_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(image_bytes):
                self.preview_image_label.setPixmap(
                    pixmap.scaled(
                        self.preview_image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        palette = ", ".join(dashboard_visual_swatch_palette(settings, count=5))
        self.preview_image_label.setText(f"Preview spec ready. Palette: {palette}")

    def _handle_control_changed(self, *_args) -> None:
        self._sync_custom_controls()
        self._schedule_preview()

    def _sync_custom_controls(self) -> None:
        is_auto = self.preset_combo.currentData() == "auto"
        is_custom = self.preset_combo.currentData() == "custom"
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
            button.setEnabled(
                is_custom
                and self.palette_mode_combo.currentData() == "fixed"
                and self.palette_preset_combo.currentData() == "custom"
            )
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
            self.element_width_spin,
            self.element_dash_combo,
            self.element_stat_accent_checkbox,
            self.apply_element_button,
            self.reset_element_button,
        ):
            widget.setEnabled(has_selection)
        role = str((self._selected_target or {}).get("role") or "")
        self.element_marker_size_spin.setEnabled(has_selection and role == "series")
        self.element_pattern_combo.setEnabled(has_selection and role == "series")
        self.element_stat_accent_checkbox.setEnabled(has_selection and role == "stat")

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
                self._populate_from_settings(settings)
                self._handle_control_changed()
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
        self._set_combo_data(self.preset_combo, "custom")
        self._handle_control_changed()

    def _mark_custom_from_element_controls(self) -> None:
        if self._updating_selection_controls:
            return
        self._set_combo_data(self.preset_combo, "custom")
        if self._selected_target is not None:
            self._apply_selected_element_style()

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
        name = str(trace.get("name") or "").strip()
        if target_id:
            return {
                "target": target_id,
                "role": role or "series",
                "label": str(meta.get("metroliza_legend_label") or name or target_id),
                "trace": index,
                "group": str(meta.get("metroliza_series_id") or ""),
                "stat": str(meta.get("metroliza_stat_id") or ""),
                "key": str(meta.get("metroliza_reference_id") or ""),
            }
        reference = name.split("=", 1)[0].strip().casefold()
        if reference in {"lsl", "usl", "nominal"}:
            return {"target": f"reference:{reference}", "role": "reference", "key": reference, "label": name, "trace": index}
        match = name and re.match(r"^(?:\((.+?)\)\s*)?(Min|Q1|Median|Mean|Q3|Max)=", name, re.IGNORECASE)
        if match:
            group = str(match.group(1) or "")
            stat = str(match.group(2) or "").casefold()
            key = f"{group.casefold()}::{stat}" if group else stat
            return {"target": f"stat:{key}", "role": "stat", "group": group, "stat": stat, "label": name, "trace": index}
        if name:
            role = "model_curve" if "curve" in name.casefold() or "kde" in name.casefold() else "series"
            return {"target": f"{role}:{name.casefold()}", "role": role, "label": name, "trace": index}
        return None

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
            self._set_combo_data(self.element_pattern_combo, str(style.get("pattern_shape") or ""))
            self.element_stat_accent_checkbox.setChecked(role == "stat" and self.stat_accent_combo.currentData() == "accent")
            self.element_marker_size_spin.setEnabled(role in {"series"})
            self.element_pattern_combo.setEnabled(role in {"series"})
            self.element_stat_accent_checkbox.setEnabled(role == "stat")
        finally:
            self._updating_selection_controls = False

    def _selected_element_style(self, target: Mapping[str, Any]) -> dict[str, Any]:
        role = str(target.get("role") or "")
        if role == "reference":
            key = str(target.get("key") or "").casefold()
            reference = self.visual_settings()["reference_lines"].get(key, {})
            return dict(reference)
        if role == "stat":
            key = self._stat_override_key(target)
            style = dict(self._stat_line_overrides.get(key) or {})
            settings = self.visual_settings()
            style.setdefault("width", settings["stat_lines"]["width"])
            style.setdefault("dash", "solid")
            style.setdefault("opacity", 1.0)
            style.setdefault("color", dashboard_visual_swatch_palette(settings, count=1)[0])
            return style
        label = str(target.get("label") or "")
        key = label.casefold()
        style = dict(self._series_overrides.get(key) or {})
        settings = self.visual_settings()
        style.setdefault("color", dashboard_visual_swatch_palette(settings, count=1)[0])
        style.setdefault("opacity", settings["opacity"].get("model_curve" if role == "model_curve" else role, 0.85))
        style.setdefault("width", 2.0)
        style.setdefault("dash", "solid")
        style.setdefault("marker_size", settings["marker_size"])
        style.setdefault("pattern_shape", "")
        return style

    def _apply_selected_element_style(self) -> None:
        target = self._selected_target
        if not target:
            return
        self._set_combo_data(self.preset_combo, "custom")
        role = str(target.get("role") or "")
        color = str(self.element_color_button.property("color") or "#245a5a")
        style = {
            "color": color,
            "opacity": self.element_opacity_slider.value() / 100.0,
            "width": self.element_width_spin.value(),
            "dash": str(self.element_dash_combo.currentData() or "solid"),
        }
        if role == "reference":
            key = str(target.get("key") or "").casefold()
            if key in self._reference_opacity_source:
                self._reference_opacity_source[key] = style["opacity"]
                self._reference_width_source[key] = style["width"]
                self._reference_width_control_value = style["width"]
            if key == "lsl":
                self._set_button_color(self.lsl_color_button, color)
                self._set_combo_data(self.lsl_dash_combo, style["dash"])
            elif key == "usl":
                self._set_button_color(self.usl_color_button, color)
                self._set_combo_data(self.usl_dash_combo, style["dash"])
            elif key == "nominal":
                self._set_button_color(self.nominal_color_button, color)
                self._set_combo_data(self.nominal_dash_combo, style["dash"])
            self.reference_width_spin.setValue(style["width"])
        elif role == "stat":
            if self.element_stat_accent_checkbox.isChecked():
                self._set_combo_data(self.stat_accent_combo, "accent")
            self._stat_line_overrides[self._stat_override_key(target)] = style
        else:
            label = str(target.get("label") or "")
            if label:
                style["marker_size"] = self.element_marker_size_spin.value()
                style["pattern_shape"] = str(self.element_pattern_combo.currentData() or "")
                self._series_overrides[label.casefold()] = style
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
            self._series_overrides.pop(label.casefold(), None)
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

    def _stat_override_key(self, target: Mapping[str, Any]) -> str:
        stat = str(target.get("stat") or "").casefold()
        group = str(target.get("group") or "").casefold()
        return f"{group}::{stat}" if group else stat

    def _schedule_preview(self) -> None:
        self._preview_timer.start(180)

    def _choose_color(self, button: QPushButton) -> None:
        initial = QColor(str(button.property("color") or "#ffffff"))
        color = QColorDialog.getColor(initial, self, "Choose color")
        if color.isValid():
            self._set_button_color(button, color.name())
            if button is getattr(self, "element_color_button", None) and self._selected_target:
                self._apply_selected_element_style()
                return
            self._handle_control_changed()

    def _reset_defaults(self) -> None:
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
