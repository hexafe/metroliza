from __future__ import annotations

import pytest

try:
    from PyQt6.QtWidgets import QApplication
except Exception as exc:  # pragma: no cover - depends on optional Qt runtime.
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


_APP = None


def _qapp():
    global _APP
    if QApplication is None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def _stub_preview_builders(monkeypatch, dialog_module, captured_settings: list[dict] | None = None):
    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_spec",
        lambda settings, *, chart_type: {"data": [], "layout": {}, "config": {}},
    )
    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_html",
        lambda _spec, **_kwargs: "",
    )

    def fake_preview_png(settings, *, chart_type):
        if captured_settings is not None:
            captured_settings.append(settings)
        return None

    monkeypatch.setattr(dialog_module, "build_dashboard_visual_preview_png", fake_preview_png)


def test_dashboard_visual_dialog_preview_uses_current_palette_color(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    captured_palette: list[str] = []

    _stub_preview_builders(monkeypatch, dialog_module)
    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_png",
        lambda settings, *, chart_type: captured_palette.append(settings["palette"][0]) or None,
    )
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={
            "preset": "custom",
            "palette": ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666"],
        },
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        dialog._set_button_color(dialog._palette_buttons[0], "#abcdef")
        dialog._handle_control_changed()

        assert dialog._preview_timer.isActive()
        dialog._preview_timer.stop()
        dialog._refresh_preview()
        assert captured_palette[-1] == "#abcdef"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_preserves_per_reference_widths_when_unchanged(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={
            "preset": "custom",
            "reference_lines": {
                "lsl": {"color": "#111111", "dash": "dash", "width": 1.0},
                "usl": {"color": "#222222", "dash": "dot", "width": 3.0},
                "nominal": {"color": "#333333", "dash": "solid", "width": 5.0},
            },
        },
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        settings = dialog.visual_settings()
        assert settings["reference_lines"]["lsl"]["width"] == 1.0
        assert settings["reference_lines"]["usl"]["width"] == 3.0
        assert settings["reference_lines"]["nominal"]["width"] == 5.0

        dialog.reference_width_spin.setValue(2.0)
        settings = dialog.visual_settings()
        assert settings["reference_lines"]["lsl"]["width"] == 2.0
        assert settings["reference_lines"]["usl"]["width"] == 2.0
        assert settings["reference_lines"]["nominal"]["width"] == 2.0
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_recipe_updates_controls_and_preview_swatches(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(persist_on_accept=False)
    try:
        dialog._preview_timer.stop()
        initial_swatches = [button.property("color") for button in dialog._preview_color_buttons]

        dialog._set_combo_data(dialog.preset_combo, "print")
        print_settings = dialog.visual_settings()
        print_swatches = [button.property("color") for button in dialog._preview_color_buttons]
        assert print_settings["preset"] == "print"
        assert dialog.palette_preset_combo.currentData() == "custom"
        assert dialog.distinguish_combo.currentData() == "always"
        assert print_swatches == dialog_module.dashboard_visual_swatch_palette(
            print_settings,
            count=len(dialog._preview_color_buttons),
        )
        assert print_swatches != initial_swatches

        dialog._set_combo_data(dialog.preset_combo, "distinct")
        distinct_settings = dialog.visual_settings()
        distinct_swatches = [button.property("color") for button in dialog._preview_color_buttons]
        assert distinct_settings["preset"] == "distinct"
        assert dialog.palette_preset_combo.currentData() == "okabe_ito"
        assert distinct_swatches == dialog_module.dashboard_visual_swatch_palette(
            distinct_settings,
            count=len(dialog._preview_color_buttons),
        )
        assert distinct_swatches != print_swatches
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_manual_edit_switches_recipe_to_custom(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={"preset": "print"},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        assert dialog.visual_settings()["preset"] == "print"
        print_swatches = [button.property("color") for button in dialog._preview_color_buttons]

        dialog.marker_size_spin.setValue(dialog.marker_size_spin.value() + 0.5)

        assert dialog.preset_combo.currentData() == "custom"
        assert dialog.visual_settings()["preset"] == "custom"
        assert dialog.palette_preset_combo.currentData() == "custom"
        assert [button.property("color") for button in dialog._preview_color_buttons] == print_swatches
        assert dialog._preview_timer.isActive()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_selected_controls_are_role_aware(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={"preset": "custom"},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        dialog._preview_targets = [
            {
                "target": "series:histogram",
                "role": "series",
                "label": "Histogram",
                "capabilities": ["color", "opacity", "pattern_shape"],
                "style": {"color": "#123456", "opacity": 0.5},
            },
            {
                "target": "model_curve:kde",
                "role": "model_curve",
                "label": "KDE",
                "capabilities": ["color", "opacity", "width", "dash"],
                "style": {"color": "#654321", "opacity": 0.75, "width": 3.0, "dash": "dot"},
            },
            {
                "target": "stat:group 1::mean",
                "role": "stat",
                "group": "Group 1",
                "stat": "mean",
                "label": "(Group 1) Mean=6.5",
                "capabilities": ["color", "opacity", "width", "dash"],
                "style": {"color": "#abcdef"},
            },
        ]
        dialog._populate_element_combo()

        dialog._set_combo_data(dialog.element_combo, "series:histogram")
        assert dialog.element_color_button.property("color") == "#123456"
        assert not dialog.element_width_spin.isEnabled()
        assert not dialog.element_dash_combo.isEnabled()
        assert not dialog.element_marker_size_spin.isEnabled()
        assert dialog.element_pattern_combo.isEnabled()

        dialog._set_combo_data(dialog.element_combo, "model_curve:kde")
        assert dialog.element_color_button.property("color") == "#654321"
        assert dialog.element_width_spin.isEnabled()
        assert dialog.element_dash_combo.isEnabled()
        assert not dialog.element_marker_size_spin.isEnabled()
        assert not dialog.element_pattern_combo.isEnabled()

        dialog._set_combo_data(dialog.element_combo, "stat:group 1::mean")
        assert dialog.element_stat_accent_checkbox.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_selected_series_override_only_writes_supported_styles(
    monkeypatch,
) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={"preset": "custom"},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        dialog._selected_target = {
            "target": "series:histogram",
            "role": "series",
            "label": "Histogram",
            "capabilities": ["color", "opacity", "pattern_shape"],
            "style": {"color": "#123456"},
        }
        dialog._load_selected_element_controls()
        dialog._sync_custom_controls()
        dialog._set_button_color(dialog.element_color_button, "#abcdef")
        dialog.element_width_spin.setValue(4.0)
        dialog._set_combo_data(dialog.element_dash_combo, "dash")
        dialog.element_marker_size_spin.setValue(12.0)
        dialog._set_combo_data(dialog.element_pattern_combo, "/")

        dialog._apply_selected_element_style()

        override = dialog.visual_settings()["series_overrides"]["histogram"]
        assert override["color"] == "#abcdef"
        assert override["pattern_shape"] == "/"
        assert "width" not in override
        assert "dash" not in override
        assert "marker_size" not in override
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_selected_marker_controls_write_series_outline(
    monkeypatch,
) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={"preset": "custom"},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        dialog._selected_target = {
            "target": "series:measurements",
            "role": "series",
            "label": "Measurements",
            "capabilities": [
                "color",
                "opacity",
                "marker_size",
                "marker_symbol",
                "outline_width",
                "outline_color",
                "outline_color_mode",
            ],
            "style": {
                "color": "#123456",
                "marker_size": 9,
                "marker_symbol": "square",
                "outline_width": 1.25,
                "outline_color": "#ffffff",
            },
        }
        dialog._load_selected_element_controls()
        dialog._sync_custom_controls()

        assert dialog.element_marker_size_spin.isEnabled()
        assert dialog.element_marker_symbol_combo.isEnabled()
        assert dialog.element_outline_checkbox.isEnabled()
        assert dialog.element_outline_width_spin.isEnabled()
        assert dialog.element_outline_color_mode_combo.isEnabled()
        assert dialog.element_marker_symbol_combo.currentData() == "square"

        dialog.element_marker_size_spin.setValue(14.0)
        dialog._set_combo_data(dialog.element_marker_symbol_combo, "diamond")
        dialog.element_outline_checkbox.setChecked(True)
        dialog.element_outline_width_spin.setValue(2.0)
        dialog._set_combo_data(dialog.element_outline_color_mode_combo, "custom")
        dialog._set_button_color(dialog.element_outline_color_button, "#abcdef")
        dialog._apply_selected_element_style()

        override = dialog.visual_settings()["series_overrides"]["measurements"]
        assert override["marker_size"] == 14.0
        assert override["marker_symbol"] == "diamond"
        assert override["outline_width"] == 2.0
        assert override["outline_color_mode"] == "custom"
        assert override["outline_color"] == "#abcdef"
    finally:
        dialog.close()
        dialog.deleteLater()
