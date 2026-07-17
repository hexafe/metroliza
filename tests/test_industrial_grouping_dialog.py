from __future__ import annotations

import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QDialog

    import metroliza.ui.industrial_grouping_dialog as industrial_grouping_dialog
    from modules.industrial_grouping_dialog import IndustrialGroupingDialog
    from modules.industrial_workflow_state import IndustrialGroupingState
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    QDialog = None
    QTest = None
    Qt = None
    IndustrialGroupingDialog = None
    IndustrialGroupingState = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial grouping dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_grouping_dialog_preserves_defined_field_order():
    _app()
    dialog = IndustrialGroupingDialog(
        state=IndustrialGroupingState(fields=("process_status", "station"))
    )

    assert dialog.current_state().fields == ("station", "process_status")
    dialog.close()


def test_grouping_dialog_search_hides_non_matching_fields():
    _app()
    dialog = IndustrialGroupingDialog()

    dialog.search_input.setText("station")
    hidden = {
        dialog.field_list.item(index).text(): dialog.field_list.item(index).isHidden()
        for index in range(dialog.field_list.count())
    }

    assert hidden["Station"] is False
    assert hidden["Reference"] is True
    dialog.close()


def test_grouping_dialog_only_apply_uses_parent_callback():
    _app()
    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.state = None

        def set_industrial_grouping_state(self, state):
            self.state = state

    parent = _ParentDialog()
    dialog = IndustrialGroupingDialog(parent=parent)
    for index in range(dialog.field_list.count()):
        item = dialog.field_list.item(index)
        if item.text() in {"Station", "Process status"}:
            item.setSelected(True)

    dialog.apply_grouping()
    assert parent.state == IndustrialGroupingState(fields=("station", "process_status"))

    dialog = IndustrialGroupingDialog(parent=parent, state=parent.state)
    dialog.clear_grouping()
    assert parent.state == IndustrialGroupingState(fields=("station", "process_status"))

    dialog.apply_grouping()
    assert parent.state == IndustrialGroupingState()


def test_grouping_dialog_exposes_selection_count_and_semantic_actions():
    _app()
    dialog = IndustrialGroupingDialog(state=IndustrialGroupingState(fields=("station",)))

    assert dialog.summary_label.text().startswith("1 group field selected")
    assert dialog.summary_label.accessibleName() == "Industrial grouping draft summary"
    assert dialog.apply_button.property("buttonRole") == "primary"
    assert dialog.apply_button.isDefault()
    assert dialog.cancel_button.property("buttonRole") == "secondary"
    assert dialog.clear_button.property("buttonRole") == "quiet"
    assert dialog.clear_button.text() == "Reset grouping"
    dialog.close()


def test_grouping_reset_and_cancel_discard_only_confirmed_draft_changes(monkeypatch):
    _app()

    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_industrial_grouping_state(self, state):
            self.calls.append(state)

    committed = IndustrialGroupingState(fields=("station",))
    parent = _ParentDialog()
    dialog = IndustrialGroupingDialog(parent=parent, state=committed)
    for index in range(dialog.field_list.count()):
        item = dialog.field_list.item(index)
        if item.data(32) == "process_status":
            item.setSelected(True)

    answers = iter(
        (
            industrial_grouping_dialog.QMessageBox.StandardButton.No,
            industrial_grouping_dialog.QMessageBox.StandardButton.Yes,
            industrial_grouping_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    prompts = []
    monkeypatch.setattr(
        industrial_grouping_dialog.QMessageBox,
        "question",
        lambda *args: prompts.append(args) or next(answers),
    )

    dialog._request_reset_grouping()
    assert dialog.current_state().fields == ("station", "process_status")

    dialog._request_reset_grouping()
    assert dialog.current_state() == IndustrialGroupingState()
    assert parent.calls == []

    for index in range(dialog.field_list.count()):
        item = dialog.field_list.item(index)
        if item.data(32) == "process_status":
            item.setSelected(True)
    dialog.show()
    _app().processEvents()
    dialog._request_cancel()
    assert dialog.current_state() == committed
    assert parent.calls == []
    assert len(prompts) == 3


def test_grouping_clean_cancel_and_window_close_do_not_prompt(monkeypatch):
    _app()
    dialog = IndustrialGroupingDialog(state=IndustrialGroupingState(fields=("station",)))
    monkeypatch.setattr(
        industrial_grouping_dialog.QMessageBox,
        "question",
        lambda *_args: pytest.fail("clean cancel should not ask for confirmation"),
    )
    dialog._request_cancel()

    dialog = IndustrialGroupingDialog()
    dialog.field_list.item(0).setSelected(True)
    dialog.close()


def test_grouping_dirty_x_and_escape_restore_without_parent_commit(monkeypatch):
    app = _app()

    class _ParentDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.calls = []

        def set_industrial_grouping_state(self, state):
            self.calls.append(state)

    parent = _ParentDialog()
    committed = IndustrialGroupingState(fields=("station",))
    dialog = IndustrialGroupingDialog(parent=parent, state=committed)
    answers = iter(
        (
            industrial_grouping_dialog.QMessageBox.StandardButton.No,
            industrial_grouping_dialog.QMessageBox.StandardButton.Yes,
            industrial_grouping_dialog.QMessageBox.StandardButton.No,
            industrial_grouping_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    monkeypatch.setattr(
        industrial_grouping_dialog.QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )

    def select(field_name):
        for index in range(dialog.field_list.count()):
            item = dialog.field_list.item(index)
            if item.data(32) == field_name:
                item.setSelected(True)
                return
        raise AssertionError(f"Missing industrial grouping field: {field_name}")

    try:
        dialog.show()
        app.processEvents()
        select("process_status")

        assert dialog.close() is False
        assert dialog.isVisible()
        assert dialog.current_state().fields == ("station", "process_status")
        assert dialog.close() is True
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert parent.calls == []

        dialog.show()
        app.processEvents()
        select("line")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert dialog.isVisible()
        assert dialog.current_state().fields == ("station", "line")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert parent.calls == []
    finally:
        dialog.close()
        parent.close()
