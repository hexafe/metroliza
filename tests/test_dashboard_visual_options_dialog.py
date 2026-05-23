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


def test_dashboard_visual_dialog_preview_uses_current_palette_color(monkeypatch) -> None:
    _qapp()
    try:
        from PyQt6.QtCore import Qt  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Full PyQt6 widgets are unavailable in this test order: {exc}")
    import modules.dashboard_visual_options_dialog as dialog_module

    captured_palette: list[str] = []

    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_spec",
        lambda _settings, *, chart_type: {"data": [], "layout": {}, "config": {}},
    )
    monkeypatch.setattr(dialog_module, "build_dashboard_visual_preview_html", lambda _spec: "")

    def fake_preview_png(settings, *, chart_type):
        captured_palette.append(settings["palette"][0])
        return None

    monkeypatch.setattr(dialog_module, "build_dashboard_visual_preview_png", fake_preview_png)
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

    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_spec",
        lambda _settings, *, chart_type: {"data": [], "layout": {}, "config": {}},
    )
    monkeypatch.setattr(dialog_module, "build_dashboard_visual_preview_html", lambda _spec: "")
    monkeypatch.setattr(dialog_module, "build_dashboard_visual_preview_png", lambda _settings, *, chart_type: None)
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
