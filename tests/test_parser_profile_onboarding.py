"""Profiles presentation over the existing authoritative handoff/install services."""
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialog, QLineEdit

from metroliza.parsing.declarative_parser_profiles import list_profiles
from metroliza.ui.parser_plugin_wizard import ParserPluginWizardDialog
from tests.test_parser_plugin_wizard import _wait_validation, _write_pdf_text
from tests.qt_geometry_diagnostics import geometry_snapshot


def _valid_materials(window):
    workspace = window.last_handoff_workspace
    sample = workspace.root / "samples" / "sample.pdf"
    _write_pdf_text(sample, "SUPPLIER TEMPLATE MARKER\nReference: REF123\nDate: 2026-01-05\nSample: 0001\nDIM X 10.0 0.1 -0.1 - 10.02 0.02 0\n")
    workspace.expected_results_path.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
        "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n",
        encoding="utf-8",
    )
    return workspace


@pytest.fixture
def window(qapplication_session, tmp_path):
    dialog = ParserPluginWizardDialog(home=tmp_path)
    dialog.task_tabs.setCurrentIndex(1)
    yield dialog
    if dialog._validation_thread is not None:
        _wait_validation(dialog)
    dialog.close()


def test_valid_profile_walks_observed_stages_then_manage_enable_disable(window):
    assert window.task_tabs.tabText(0) == "Manage installed profiles"
    assert window.task_tabs.tabText(1) == "Add a new format"
    assert "not approval" in window.next_action_label.text()
    assert not window.repair_button.isEnabled()
    window.plugin_id_edit.setText("synthetic_valid")
    window.next_button.click()  # Prepare through actual existing handler
    assert window.last_handoff_workspace is not None
    assert "not run" in window.validation_status_label.text()
    _valid_materials(window)
    window.next_button.click()  # Check package
    assert "PASS" in window.package_status_label.text()
    assert window._next_control is window.validate_button
    window.next_button.click()  # Validate through actual worker lifecycle
    _wait_validation(window)
    assert "PASS" in window.validation_status_label.text()
    assert "observed result" in window.validation_status_label.text()
    assert "earlier PASS is not approval" in window.next_action_label.text()
    assert window._next_control is window.install_button
    assert not window.repair_button.isEnabled()
    window.next_button.click()  # Actual install revalidates current materials
    profiles = list_profiles(home=window.home)
    assert len(profiles) == 1 and profiles[0].enabled and profiles[0].approved
    window.task_tabs.setCurrentIndex(0)
    window.profile_list.setCurrentRow(0)
    assert window.disable_button.isEnabled()
    window.disable_button.click()
    assert not list_profiles(home=window.home)[0].enabled
    window.profile_list.setCurrentRow(0)
    assert window.enable_button.isEnabled()
    window.enable_button.click()
    assert list_profiles(home=window.home)[0].enabled
    window.profile_list.setCurrentRow(0)
    window.disable_button.click()
    installed = list_profiles(home=window.home)[0]
    installed.profile_path.write_text("{}\n", encoding="utf-8")
    window.refresh_status()
    window.profile_list.setCurrentRow(0)
    assert not window.enable_button.isEnabled()
    window.enable_button.click()
    assert not list_profiles(home=window.home)[0].enabled


def test_incomplete_package_and_validation_pass_never_approve_missing_samples(window):
    window.create_handoff_workspace()
    workspace = window.last_handoff_workspace
    manifest = workspace.root / "handoff_manifest.json"
    manifest.unlink()
    window.check_handoff_package()
    assert "FAIL" in window.package_status_label.text()
    assert window.repair_button.isEnabled()
    assert window._next_control is window.open_folder_button
    # Existing validation may pass the data-only template with no expected rows.
    # Installation's independent fresh evidence guards remain authoritative.
    window.validate_handoff_profile()
    _wait_validation(window)
    assert "PASS" in window.validation_status_label.text()
    window.install_handoff_profile()
    assert "Installation blocked" in window.stage_label.text()
    assert "at least one sample" in window.result_label.text()
    assert list_profiles(home=window.home) == ()
    assert window._next_control is window.open_folder_button


def test_invalid_profile_repair_is_contextual_and_install_rechecks_after_pass(window):
    window.create_handoff_workspace()
    workspace = _valid_materials(window)
    window.validate_handoff_profile()
    _wait_validation(window)
    assert "PASS" in window.validation_status_label.text()
    workspace.profile_path.write_text("{}\n", encoding="utf-8")
    window.install_handoff_profile()
    assert "Installation blocked" in window.stage_label.text()
    assert list_profiles(home=window.home) == ()
    window.validate_handoff_profile()
    _wait_validation(window)
    assert "FAIL" in window.validation_status_label.text()
    assert window.diagnose_button.isEnabled() and window.repair_button.isEnabled()
    window.create_repair_prompt()
    assert (workspace.root / "artifacts" / "profile_repair_prompt.md").is_file()
    assert list_profiles(home=window.home) == ()


def test_profiles_keys_are_contextual_disabled_aware_and_leave_text_and_children(window, qapplication_session):
    creations = []
    window.create_button.clicked.connect(lambda: creations.append(True))
    window.show()
    window.activateWindow()
    window.plugin_id_edit.setFocus()
    qapplication_session.processEvents()
    QTest.keyClicks(window.plugin_id_edit, "left_hand")
    QTest.keyClick(window.plugin_id_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert window.plugin_id_edit.selectedText() == "left_hand"
    QTest.keyClick(window.plugin_id_edit, Qt.Key.Key_Tab)
    assert window.display_name_edit.hasFocus()
    QTest.keyClick(window.display_name_edit, Qt.Key.Key_Backtab)
    assert window.plugin_id_edit.hasFocus()
    QTest.keyClick(window.plugin_id_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert creations == [True]
    assert window.last_handoff_workspace is not None
    root = window.last_handoff_workspace.root
    assert "[Ctrl+S]" in window.next_button.text()
    child = QDialog(window)
    edit = QLineEdit(child)
    child.setWindowModality(Qt.WindowModality.WindowModal)
    child.show()
    child.activateWindow()
    edit.setFocus()
    qapplication_session.processEvents()
    QTest.keyClick(edit, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert window.last_handoff_workspace.root == root
    assert creations == [True]
    assert "not run" in window.package_status_label.text()
    child.close()
    window.activateWindow()
    qapplication_session.processEvents()
    QTest.keyClick(window.plugin_id_edit, Qt.Key.Key_D,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert window.task_tabs.currentIndex() == 0
    QTest.keyClick(window.profile_list, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert window.last_handoff_workspace.root == root  # hidden creation action never runs
    assert creations == [True]
    QTest.keyClick(window.profile_list, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert list_profiles(home=window.home) == ()  # disabled Enable is inert


@pytest.mark.parametrize("tab", [0, 1])
def test_profiles_small_window_keeps_status_next_and_close_accessible(window, qapplication_session, monkeypatch, tab):
    from metroliza.ui import ui_foundation

    monkeypatch.setattr(ui_foundation, "_available_window_size", lambda *_a: (1240, 680))
    if tab == 1:
        window.create_handoff_workspace()
        window.check_handoff_package()
    window.task_tabs.setCurrentIndex(tab)
    window.show()
    qapplication_session.processEvents()
    window.resize(620, 560)
    qapplication_session.processEvents()
    assert (window.width(), window.height()) == (620, 560), geometry_snapshot(
        window, requested=(620, 560), pinned=(
            ("close_button", "manage_status_label", "refresh_button") if tab == 0 else
            ("close_button", "stage_label", "validation_status_label", "next_action_label", "result_label", "next_button")
        ),
    )
    screen = qapplication_session.primaryScreen().availableGeometry()
    print(f"profiles_geometry tab={tab} size=620x560 screen={screen.width()}x{screen.height()} dpr={window.devicePixelRatioF()}")
    assert window.devicePixelRatioF() > 0
    controls = (window.close_button, window.manage_status_label, window.refresh_button) if tab == 0 else (
        window.close_button, window.stage_label, window.validation_status_label,
        window.next_action_label, window.result_label, window.next_button,
    )
    for control in controls:
        assert control.isVisibleTo(window)
        assert window.rect().contains(control.rect().translated(control.mapTo(window, QPoint())))
        if tab == 1:
            assert not window.add_scroll_area.isAncestorOf(control)


@pytest.mark.parametrize('tab', [0, 1])
def test_profiles_compact_window_keeps_wrapped_status_pinned_while_form_scrolls(
        window, qapplication_session, tab):
    from PyQt6.QtCore import QRect

    window.create_handoff_workspace()
    window.check_handoff_package()
    # A genuinely tall form must consume scroll range, including when its tab
    # is inactive; it must not raise the surrounding window's minimum height.
    window.add_scroll_area.widget().setMinimumHeight(1200)
    window.task_tabs.setCurrentIndex(tab)
    window.show()
    qapplication_session.processEvents()
    window.resize(620, 560)
    qapplication_session.processEvents()
    try:
        assert (window.width(), window.height()) == (620, 560)
        controls = (window.manage_status_label, window.refresh_button) if tab == 0 else (
            window.stage_label, window.validation_status_label, window.next_action_label,
            window.result_label, window.next_button,
        )
        for control in (*controls, window.close_button):
            assert control.isVisibleTo(window)
            assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))
        if tab == 1:
            for label in (window.stage_label, window.validation_status_label,
                          window.next_action_label, window.result_label):
                assert label.height() >= label.heightForWidth(label.width())
            scroll = window.add_scroll_area
            assert scroll.verticalScrollBar().maximum() > 0
            scroll.ensureWidgetVisible(window.repair_button)
            qapplication_session.processEvents()
            assert scroll.viewport().rect().contains(QRect(
                window.repair_button.mapTo(scroll.viewport(), QPoint()), window.repair_button.size()))
            assert window.repair_button.height() >= 36
            assert window.next_button.height() >= 36
        assert window.close_button.height() >= 36
    finally:
        window.close()
