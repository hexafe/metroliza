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
        assert print_swatches == [
            style["color"]
            for style in dialog_module.dashboard_visual_effective_series_styles(
                print_settings,
                labels=dialog_module._PREVIEW_SERIES_LABELS,
                chart_type="grouped_histogram",
            )
        ]
        assert print_swatches != initial_swatches

        dialog._set_combo_data(dialog.preset_combo, "colorblind_distinct")
        distinct_settings = dialog.visual_settings()
        distinct_swatches = [button.property("color") for button in dialog._preview_color_buttons]
        assert distinct_settings["recipe"] == "colorblind_distinct"
        assert distinct_settings["preset"] == "custom"
        assert dialog.palette_preset_combo.currentData() == "okabe_ito"
        assert distinct_settings["distinguish"] == "when_similar"
        assert distinct_swatches == [
            style["color"]
            for style in dialog_module.dashboard_visual_effective_series_styles(
                distinct_settings,
                labels=dialog_module._PREVIEW_SERIES_LABELS,
                chart_type="grouped_histogram",
            )
        ]
        assert distinct_swatches != print_swatches

        dialog._set_combo_data(dialog.preset_combo, "toned_report")
        toned_settings = dialog.visual_settings()
        assert toned_settings["recipe"] == "toned_report"
        assert toned_settings["preset"] == "custom"
        assert toned_settings["population_baseline"]["marker_size"] < toned_settings["comparison_focus"]["marker_size"]
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


def test_dashboard_visual_dialog_group_color_edit_updates_palette_and_chips(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={"recipe": "toned_report"},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        dialog._selected_target = {
            "target": "series:group 2",
            "role": "series",
            "label": "Group 2",
            "capabilities": ["color", "opacity", "pattern_shape"],
            "style": {"color": "#d66e2f", "opacity": 0.50},
        }
        dialog._load_selected_element_controls()
        dialog._set_button_color(dialog.element_color_button, "#abcdef")

        dialog._apply_selected_element_style()

        settings = dialog.visual_settings()
        assert dialog.preset_combo.currentData() == "custom"
        assert settings["palette"][1] == "#abcdef"
        assert dialog._palette_buttons[1].property("color") == "#abcdef"
        assert dialog._preview_color_buttons[2].property("color") == "#abcdef"
        assert settings["population_baseline"]["draw_first"] is True
        assert settings["population_baseline"]["color"] == "#8a949e"
        assert settings["comparison_focus"]["outline_width"] > 0
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_population_color_edit_updates_baseline_not_palette(
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
        settings={"recipe": "toned_report"},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        original_palette = [button.property("color") for button in dialog._palette_buttons]
        dialog._selected_target = {
            "target": "series:population points",
            "role": "series",
            "label": "Population points",
            "capabilities": ["color", "opacity", "marker_size", "marker_symbol"],
            "style": {"color": "#8a949e", "opacity": 0.32, "marker_size": 4.5},
        }
        dialog._load_selected_element_controls()
        dialog._set_button_color(dialog.element_color_button, "#aabbcc")

        dialog._apply_selected_element_style()

        settings = dialog.visual_settings()
        assert settings["population_baseline"]["color"] == "#aabbcc"
        assert settings["population_baseline"]["draw_first"] is True
        assert [button.property("color") for button in dialog._palette_buttons] == original_palette
        assert dialog._preview_color_buttons[0].property("color") == "#aabbcc"
        assert "population points" not in settings["series_overrides"]
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_group_edit_keeps_population_first_in_histogram(
    monkeypatch,
) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options as visual_options
    import modules.dashboard_visual_options_dialog as dialog_module

    _stub_preview_builders(monkeypatch, dialog_module)
    dialog = dialog_module.DashboardVisualOptionsDialog(
        settings={"recipe": "toned_report"},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()
        dialog._selected_target = {
            "target": "series:group 1",
            "role": "series",
            "label": "Group 1",
            "capabilities": ["color", "opacity"],
            "style": {"color": "#245a5a", "opacity": 0.50},
        }
        dialog._load_selected_element_controls()
        dialog._set_button_color(dialog.element_color_button, "#ff0000")
        dialog._apply_selected_element_style()

        spec = visual_options.build_dashboard_visual_preview_spec(
            dialog.visual_settings(),
            chart_type="histogram",
        )

        series_traces = [
            trace
            for trace in spec["data"]
            if trace.get("meta", {}).get("dashboard_visual_role") == "series"
        ]
        assert series_traces[0]["name"] == "Population points"
        assert series_traces[0]["marker"]["color"] == "#8a949e"
        assert next(trace for trace in series_traces if trace["name"] == "Group 1")[
            "marker"
        ]["color"] == "#ff0000"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_opacity_controls_show_synced_numeric_companions(
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
        settings={"preset": "custom", "opacity": {"histogram": 0.42}},
        persist_on_accept=False,
    )
    try:
        dialog._preview_timer.stop()

        assert dialog.histogram_opacity_slider.value() == 42
        assert dialog.histogram_opacity_spin.value() == 42

        dialog.histogram_opacity_slider.setValue(67)
        assert dialog.histogram_opacity_spin.value() == 67
        assert dialog.visual_settings()["opacity"]["histogram"] == 0.67

        dialog.histogram_opacity_spin.setValue(85)
        assert dialog.histogram_opacity_slider.value() == 85
        assert dialog.visual_settings()["opacity"]["histogram"] == 0.85
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_selection_inspector_sits_below_preview_and_starts_disabled(
    monkeypatch,
) -> None:
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
        body_layout = dialog.layout().itemAt(0).layout()
        preview_layout = body_layout.itemAt(1).layout()

        assert preview_layout.itemAt(1).widget() is dialog.preview_tabs
        assert preview_layout.itemAt(2).widget() is dialog.selection_group
        assert dialog.selection_group.objectName() == "selectionInspector"
        assert dialog.customize_button.text() == "Customize..."
        assert dialog.customize_controls_container.isHidden()
        assert dialog.selection_group.isHidden()

        dialog.customize_button.setChecked(True)

        assert dialog.customize_button.text() == "Hide customization"
        assert not dialog.customize_controls_container.isHidden()
        assert not dialog.selection_group.isHidden()
        assert not dialog.element_opacity_slider.isEnabled()
        assert not dialog.element_opacity_spin.isEnabled()
        assert dialog.element_opacity_slider.parentWidget().isHidden()
        assert not dialog.apply_element_button.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_selection_opacity_numeric_syncs_and_writes_override(
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
            "capabilities": ["color", "opacity", "marker_size"],
            "style": {"color": "#123456", "opacity": 0.55, "marker_size": 8},
        }
        dialog._load_selected_element_controls()

        assert dialog.element_opacity_slider.value() == 55
        assert dialog.element_opacity_spin.value() == 55

        dialog.element_opacity_spin.setValue(73)
        assert dialog.element_opacity_slider.value() == 73
        assert dialog.visual_settings()["series_overrides"]["measurements"]["opacity"] == 0.73

        dialog.element_opacity_slider.setValue(64)
        assert dialog.element_opacity_spin.value() == 64
        assert dialog.visual_settings()["series_overrides"]["measurements"]["opacity"] == 0.64
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_selection_accessibility_and_tab_order(monkeypatch) -> None:
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

        assert dialog.element_combo.accessibleName() == "Dashboard visual selected element"
        assert dialog.element_opacity_slider.accessibleName() == "Selected element opacity"
        assert dialog.element_opacity_spin.accessibleName() == "Selected element opacity percent"
        assert dialog.element_opacity_slider.nextInFocusChain() is dialog.element_opacity_spin
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dashboard_visual_dialog_static_preview_rescales_existing_pixmap(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import QBuffer, QIODevice
        from PyQt6.QtGui import QImage
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    image = QImage(320, 160, QImage.Format.Format_RGB32)
    image.fill(0x245A5A)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    png_bytes = bytes(buffer.data())

    _stub_preview_builders(monkeypatch, dialog_module)
    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_png",
        lambda _settings, *, chart_type: png_bytes,
    )
    dialog = dialog_module.DashboardVisualOptionsDialog(persist_on_accept=False)
    try:
        dialog._preview_timer.stop()
        dialog.preview_image_label.resize(700, 400)
        dialog._refresh_preview()

        assert dialog._preview_source_pixmap is not None
        assert dialog._preview_source_pixmap.size().width() == 320
        assert dialog.preview_image_label.pixmap().size().width() <= 700

        dialog.preview_image_label.resize(560, 360)
        dialog._update_static_preview_pixmap()

        assert dialog.preview_image_label.pixmap().size().width() <= 560
        assert dialog.preview_image_label.pixmap().size().height() <= 360
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
        assert dialog.element_width_spin.isHidden()
        assert not dialog.element_dash_combo.isEnabled()
        assert dialog.element_dash_combo.isHidden()
        assert not dialog.element_marker_size_spin.isEnabled()
        assert dialog.element_marker_size_spin.isHidden()
        assert dialog.element_outline_checkbox.isHidden()
        assert dialog.element_pattern_combo.isEnabled()
        assert not dialog.element_pattern_combo.isHidden()

        dialog._set_combo_data(dialog.element_combo, "model_curve:kde")
        assert dialog.element_color_button.property("color") == "#654321"
        assert dialog.element_width_spin.isEnabled()
        assert not dialog.element_width_spin.isHidden()
        assert dialog.element_dash_combo.isEnabled()
        assert not dialog.element_marker_size_spin.isEnabled()
        assert dialog.element_marker_size_spin.isHidden()
        assert not dialog.element_pattern_combo.isEnabled()
        assert dialog.element_pattern_combo.isHidden()

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
        assert not dialog.element_marker_size_spin.isHidden()
        assert dialog.element_marker_symbol_combo.isEnabled()
        assert dialog.element_outline_checkbox.isEnabled()
        assert not dialog.element_outline_checkbox.isHidden()
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
