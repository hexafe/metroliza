"""Qt dialog for dashboard visual settings with a sample preview."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
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
    dashboard_visual_settings_summary,
    dashboard_visual_swatch_palette,
    default_dashboard_visual_settings,
    normalize_dashboard_visual_settings,
    save_dashboard_visual_settings,
)
from modules.ui_foundation import apply_metroliza_theme, configure_accessibility, configure_window_size

try:  # Optional. PyQt WebEngine is intentionally not a hard runtime dependency.
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - depends on local Qt installation.
    QWebEngineView = None


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
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.setWindowTitle("Dashboard visuals")
        configure_window_size(self, minimum=(860, 560), initial=(1040, 720))

        self._build_controls()
        self._populate_from_settings(self._settings)
        self._sync_custom_controls()
        self._schedule_preview()
        apply_metroliza_theme(self)

    def visual_settings(self) -> dict[str, Any]:
        """Return normalized settings represented by the current controls."""

        settings = default_dashboard_visual_settings()
        settings["preset"] = str(self.preset_combo.currentData() or "auto")
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
        }
        settings["marker_size"] = self.marker_size_spin.value()
        settings["stat_lines"] = {
            "accent_by_stat": self.stat_accent_combo.currentData() == "accent",
            "width": self.stat_width_spin.value(),
        }
        settings["reference_lines"] = {
            "lsl": {
                "color": str(self.lsl_color_button.property("color") or "#b91c1c"),
                "dash": str(self.lsl_dash_combo.currentData() or "dash"),
                "width": self.reference_width_spin.value(),
            },
            "usl": {
                "color": str(self.usl_color_button.property("color") or "#b91c1c"),
                "dash": str(self.usl_dash_combo.currentData() or "dash"),
                "width": self.reference_width_spin.value(),
            },
            "nominal": {
                "color": str(self.nominal_color_button.property("color") or "#0f766e"),
                "dash": str(self.nominal_dash_combo.currentData() or "solid"),
                "width": self.reference_width_spin.value(),
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

        self.preset_combo = self._combo(_PRESET_ITEMS)
        self.preset_combo.currentIndexChanged.connect(self._handle_control_changed)
        preset_group = QGroupBox("Mode")
        preset_form = QFormLayout(preset_group)
        preset_form.addRow("Preset", self.preset_combo)
        controls_layout.addWidget(preset_group)

        palette_group = QGroupBox("Palette")
        palette_layout = QGridLayout(palette_group)
        self.palette_mode_combo = self._combo(_PALETTE_MODE_ITEMS)
        self.gradient_spread_combo = self._combo(_SPREAD_ITEMS)
        self.anchor_color_button = self._color_button("#facc15")
        self.palette_mode_combo.currentIndexChanged.connect(self._handle_control_changed)
        self.gradient_spread_combo.currentIndexChanged.connect(self._handle_control_changed)
        self.anchor_color_button.clicked.connect(lambda: self._choose_color(self.anchor_color_button))
        palette_layout.addWidget(QLabel("Mode"), 0, 0)
        palette_layout.addWidget(self.palette_mode_combo, 0, 1, 1, 3)
        palette_layout.addWidget(QLabel("Anchor"), 1, 0)
        palette_layout.addWidget(self.anchor_color_button, 1, 1)
        palette_layout.addWidget(QLabel("Spread"), 1, 2)
        palette_layout.addWidget(self.gradient_spread_combo, 1, 3)
        for index, color in enumerate(DEFAULT_DASHBOARD_PALETTE):
            button = self._color_button(color)
            button.clicked.connect(lambda _checked=False, button=button: self._choose_color(button))
            self._palette_buttons.append(button)
            palette_layout.addWidget(button, 2 + index // 3, index % 3)
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
        for slider in (
            self.histogram_opacity_slider,
            self.grouped_histogram_opacity_slider,
            self.distribution_opacity_slider,
            self.iqr_opacity_slider,
            self.scatter_opacity_slider,
            self.trend_opacity_slider,
        ):
            slider.valueChanged.connect(lambda _value: self._schedule_preview())
        opacity_form.addRow("Histogram", self.histogram_opacity_slider)
        opacity_form.addRow("Grouped histogram", self.grouped_histogram_opacity_slider)
        opacity_form.addRow("Violin", self.distribution_opacity_slider)
        opacity_form.addRow("IQR", self.iqr_opacity_slider)
        opacity_form.addRow("Scatter", self.scatter_opacity_slider)
        opacity_form.addRow("Trend", self.trend_opacity_slider)
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
        self._set_combo_data(self.preset_combo, settings["preset"])
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
        self.marker_size_spin.setValue(float(settings["marker_size"]))
        self.stat_width_spin.setValue(float(settings["stat_lines"]["width"]))
        reference = settings["reference_lines"]
        self.reference_width_spin.setValue(float(reference["lsl"]["width"]))
        self._set_button_color(self.lsl_color_button, reference["lsl"]["color"])
        self._set_button_color(self.usl_color_button, reference["usl"]["color"])
        self._set_button_color(self.nominal_color_button, reference["nominal"]["color"])
        self._set_combo_data(self.lsl_dash_combo, reference["lsl"]["dash"])
        self._set_combo_data(self.usl_dash_combo, reference["usl"]["dash"])
        self._set_combo_data(self.nominal_dash_combo, reference["nominal"]["dash"])

    def _refresh_preview(self) -> None:
        settings = self.visual_settings()
        chart_type = str(self.chart_type_combo.currentData() or "histogram")
        self.summary_label.setText(dashboard_visual_settings_summary(settings))
        spec = build_dashboard_visual_preview_spec(settings, chart_type=chart_type)
        if spec and self.web_view is not None:
            self.web_view.setHtml(build_dashboard_visual_preview_html(spec), QUrl("about:blank"))
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
            self.palette_mode_combo,
            self.gradient_spread_combo,
            self.anchor_color_button,
            self.distinguish_combo,
            self.marker_size_spin,
        ):
            widget.setEnabled(not is_auto)
        for button in self._palette_buttons:
            button.setEnabled(is_custom and self.palette_mode_combo.currentData() == "fixed")
        gradient_enabled = is_custom and self.palette_mode_combo.currentData() in {
            "auto_gradient",
            "highlight_gradient",
        }
        self.gradient_spread_combo.setEnabled(gradient_enabled)
        self.anchor_color_button.setEnabled(gradient_enabled)

    def _schedule_preview(self) -> None:
        self._preview_timer.start(180)

    def _choose_color(self, button: QPushButton) -> None:
        initial = QColor(str(button.property("color") or "#ffffff"))
        color = QColorDialog.getColor(initial, self, "Choose color")
        if color.isValid():
            self._set_button_color(button, color.name())
            self._handle_control_changed()

    def _reset_defaults(self) -> None:
        self._populate_from_settings(default_dashboard_visual_settings())
        self._handle_control_changed()

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
