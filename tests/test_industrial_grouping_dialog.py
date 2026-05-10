from __future__ import annotations

import pytest

try:
    from PyQt6.QtWidgets import QApplication, QDialog

    from modules.industrial_grouping_dialog import IndustrialGroupingDialog
    from modules.industrial_workflow_state import IndustrialGroupingState
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    QDialog = None
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


def test_grouping_dialog_apply_and_clear_use_parent_callback():
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
    assert parent.state == IndustrialGroupingState()
