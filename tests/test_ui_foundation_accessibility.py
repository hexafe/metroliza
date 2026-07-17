from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QPalette
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QPushButton,
        QSizePolicy,
        QVBoxLayout,
        QWIDGETSIZE_MAX,
    )

    from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
    from metroliza.ui.ui_foundation import (
        apply_metroliza_application_theme,
        apply_metroliza_theme,
        configure_window_size,
        finalize_window_size,
        metroliza_stylesheet,
        status_chip,
    )
    from metroliza.ui import ui_theme_tokens
except Exception as exc:  # pragma: no cover - depends on the local Qt runtime.
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 accessibility checks are unavailable: {PYQT_IMPORT_ERROR}",
)

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


@pytest.fixture(autouse=True)
def _ensure_qapplication():
    _app()


def test_effective_light_theme_text_and_focus_pairs_meet_wcag_contrast():
    palette = ui_theme_tokens.theme_tokens(dark_mode=False)
    status_colors = palette["STATUS_COLORS"]
    assert status_colors["warning"][0] == palette["ACCENT_WARNING"]
    text_pairs = (
        (palette["TEXT_PRIMARY"], palette["WINDOW_BACKGROUND"]),
        (palette["TEXT_SECONDARY"], palette["WINDOW_BACKGROUND"]),
        (palette["TEXT_MUTED"], palette["WINDOW_BACKGROUND"]),
        (palette["DEFAULT_BUTTON_TEXT"], palette["ACCENT_PRIMARY"]),
        (palette["ACCENT_INFO"], status_colors["info"][1]),
        (palette["ACCENT_SUCCESS"], status_colors["success"][1]),
        (palette["ACCENT_WARNING"], status_colors["warning"][1]),
        (palette["ACCENT_DANGER"], status_colors["danger"][1]),
    )
    for foreground, background in text_pairs:
        assert ui_theme_tokens.contrast_ratio(foreground, background) >= 4.5

    for background in (palette["WINDOW_BACKGROUND"], palette["SURFACE_BACKGROUND"]):
        assert ui_theme_tokens.contrast_ratio(palette["FOCUS_RING"], background) >= 3.0

    selected_background = ui_theme_tokens.SELECTED_ROW_BACKGROUND_FALLBACK
    selected_text = ui_theme_tokens.selected_text_color(selected_background)
    assert ui_theme_tokens.contrast_ratio(selected_text, selected_background) >= 4.5


def test_stylesheet_uses_semantic_button_roles_and_covers_common_focusable_widgets():
    stylesheet = metroliza_stylesheet(dark_mode=False)

    assert 'QPushButton[buttonRole="primary"]' in stylesheet
    assert 'QPushButton[buttonRole="danger"]' in stylesheet
    assert "QPushButton:default {" not in stylesheet
    for selector in (
        "QPlainTextEdit:focus",
        "QDoubleSpinBox:focus",
        "QTextBrowser:focus",
        "QTreeView:focus",
        "QTabBar::tab:focus",
        "QCheckBox:focus",
    ):
        assert selector in stylesheet


def test_application_theme_helper_sets_semantic_palette_and_stylesheet():
    app = _app()
    original_palette = QPalette(app.palette())
    original_stylesheet = app.styleSheet()
    try:
        apply_metroliza_application_theme(app, dark_mode=True)
        palette = ui_theme_tokens.theme_tokens(dark_mode=True)
        assert app.palette().color(QPalette.ColorRole.Window).name().upper() == (
            palette["WINDOW_BACKGROUND"]
        )
        assert app.palette().color(QPalette.ColorRole.Link).name().upper() == (
            palette["ACCENT_INFO"]
        )
        assert 'QPushButton[buttonRole="primary"]' in app.styleSheet()
    finally:
        app.setStyleSheet(original_stylesheet)
        app.setPalette(original_palette)


def test_theme_switch_restyles_open_windows_and_high_contrast_restores_system_palette():
    app = _app()
    original_palette = QPalette(app.palette())
    original_stylesheet = app.styleSheet()
    original_mode = app.property("metrolizaThemeMode")
    dialog = QDialog()
    try:
        apply_metroliza_theme(dialog, dark_mode=False)
        dialog.show()
        app.processEvents()

        apply_metroliza_application_theme(app, mode="dark")
        dark = ui_theme_tokens.theme_tokens(dark_mode=True)
        assert dialog.palette().color(QPalette.ColorRole.Window).name().upper() == (
            dark["WINDOW_BACKGROUND"]
        )
        assert dialog.property("metrolizaDarkMode") is True

        apply_metroliza_application_theme(app, mode="high_contrast")
        assert dialog.styleSheet() == ""
        assert dialog.palette().color(QPalette.ColorRole.Window) == app.palette().color(
            QPalette.ColorRole.Window
        )
        assert dialog.property("metrolizaDarkMode") is None

        new_dialog = QDialog()
        try:
            apply_metroliza_theme(new_dialog)
            assert new_dialog.styleSheet() == ""
        finally:
            new_dialog.close()
    finally:
        dialog.close()
        app.setStyleSheet(original_stylesheet)
        app.setPalette(original_palette)
        app.setProperty("metrolizaThemeMode", original_mode)


def test_source_profile_dialog_has_one_stable_primary_enter_action(tmp_path):
    app = _app()
    dialog = IndustrialSourceProfilesDialog(
        db_file=None,
        config_path=tmp_path / "industrial_sources.yaml",
    )
    dialog.show()
    app.processEvents()

    buttons = dialog.findChildren(QPushButton)
    assert [button.text() for button in buttons if button.isDefault()] == ["Save source"]
    assert dialog.save_source_button.property("buttonRole") == "primary"
    assert dialog.save_source_button.autoDefault()
    for button in (
        dialog.new_source_button,
        dialog.browse_config_button,
        dialog.reload_config_button,
        dialog.close_button,
    ):
        assert not button.autoDefault(), button.text()
        assert not button.isDefault(), button.text()

    triggered = []
    for button in buttons:
        try:
            button.clicked.disconnect()
        except TypeError:
            pass
        button.clicked.connect(lambda _checked=False, text=button.text(): triggered.append(text))

    dialog.source_name_edit.setFocus()
    app.processEvents()
    QTest.keyClick(dialog.source_name_edit, Qt.Key.Key_Return)
    app.processEvents()

    assert triggered == ["Save source"]
    assert dialog.save_source_button.isDefault()
    dialog.close()


def test_wrapped_status_and_post_layout_sizing_remain_adaptive():
    app = _app()
    dialog = QDialog()
    configure_window_size(
        dialog,
        minimum=(420, 260),
        initial=(5000, 5000),
        screen_margin=40,
    )
    enlarged_font = QFont(dialog.font())
    enlarged_font.setPointSizeF(max(18.0, enlarged_font.pointSizeF() * 2.0))
    dialog.setFont(enlarged_font)
    label = status_chip(
        "A long status message must wrap onto additional lines without being clipped at "
        "large application font sizes or on a compact display."
    )
    layout = QVBoxLayout(dialog)
    layout.addWidget(label)
    finalize_window_size(dialog, force=True)
    dialog.show()
    app.processEvents()

    available = app.primaryScreen().availableGeometry()
    assert dialog.width() <= available.width() - 40
    assert dialog.height() <= available.height() - 40
    assert dialog.maximumWidth() == QWIDGETSIZE_MAX
    assert dialog.maximumHeight() == QWIDGETSIZE_MAX
    assert label.sizePolicy().verticalPolicy() != QSizePolicy.Policy.Fixed
    assert label.sizePolicy().hasHeightForWidth()
    assert label.height() >= label.heightForWidth(label.width())
    dialog.close()


def test_post_layout_sizing_recovers_unreachable_restored_window():
    app = _app()
    dialog = QDialog()
    configure_window_size(dialog, minimum=(420, 260), initial=(640, 420))
    dialog.move(100_000, 100_000)

    finalize_window_size(dialog, force=True)
    dialog.show()
    app.processEvents()

    assert any(
        screen.availableGeometry().intersects(dialog.frameGeometry())
        for screen in app.screens()
    )
    dialog.close()


def test_about_support_link_is_keyboard_accessible_and_dark_theme_safe():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import json
                from PyQt6.QtCore import Qt
                from PyQt6.QtGui import QPalette
                from PyQt6.QtTest import QTest
                from PyQt6.QtWidgets import QApplication
                from metroliza.ui import about_window, ui_theme_tokens
                from metroliza.ui.ui_foundation import apply_metroliza_theme

                app = QApplication([])
                opened_urls = []
                about_window.QDesktopServices.openUrl = (
                    lambda url: opened_urls.append(url.toString()) or True
                )
                dialog = about_window.AboutWindow()
                apply_metroliza_theme(dialog, dark_mode=True)
                dialog.show()
                app.processEvents()
                link = dialog.support_link_label
                link.setFocus()
                QTest.keyClick(link, Qt.Key.Key_Return)
                app.processEvents()
                print(json.dumps({
                    "accessible_name": link.accessibleName(),
                    "expected_name": f"GitHub: {about_window.SUPPORT_URL}",
                    "focus_policy": link.focusPolicy() == Qt.FocusPolicy.StrongFocus,
                    "link_role": link.property("linkLabel") is True,
                    "inline_style": link.styleSheet(),
                    "link_color": link.palette().color(QPalette.ColorRole.Link).name().upper(),
                    "expected_color": ui_theme_tokens.DARK_ACCENT_INFO,
                    "opened_urls": opened_urls,
                    "expected_url": about_window.SUPPORT_URL,
                }, sort_keys=True))
                dialog.close()
                """
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(probe.stdout.strip().splitlines()[-1])
    assert payload["focus_policy"]
    assert payload["accessible_name"] == payload["expected_name"]
    assert payload["link_role"]
    assert payload["inline_style"] == ""
    assert payload["link_color"] == payload["expected_color"]
    assert payload["opened_urls"] == [payload["expected_url"]]
