from __future__ import annotations

import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    import metroliza.ui.industrial_analytics_filter_dialog as analytics_filter_dialog
    from metroliza.industrial.industrial_analytics_state import (
        DynamicFieldFilter,
        ProductionFilterState,
    )
    from metroliza.ui.industrial_analytics_filter_dialog import IndustrialAnalyticsFilterDialog
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    DynamicFieldFilter = None
    QTest = None
    Qt = None
    IndustrialAnalyticsFilterDialog = None
    ProductionFilterState = None
    analytics_filter_dialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 production analytics filter widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_filter_dialog_exposes_count_accessibility_and_semantic_actions():
    _app()
    state = ProductionFilterState(
        references=("REF-1",),
        stations=("S1",),
        dynamic_filters=(DynamicFieldFilter("cycle_time_s", "gt", "40"),),
    )
    dialog = IndustrialAnalyticsFilterDialog(filter_state=state)

    assert dialog.summary_label.text().startswith("3 active conditions.")
    assert dialog.summary_label.accessibleName() == "Production analytics filter draft summary"
    assert dialog.validation_error_label.accessibleName() == "Production analytics filter error"
    assert dialog.apply_button.property("buttonRole") == "primary"
    assert dialog.apply_button.isDefault()
    assert dialog.cancel_button.property("buttonRole") == "secondary"
    assert dialog.clear_button.property("buttonRole") == "quiet"
    assert dialog.clear_button.text() == "Reset filters"
    dialog.close()


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        ("source_profile_ids_field", "not-a-number", "must be a number"),
        ("dynamic_filters_edit", "cycle_time_s gt", "needs a value"),
    ),
)
def test_invalid_filter_draft_disables_apply_with_inline_error(field_name, value, message):
    _app()
    dialog = IndustrialAnalyticsFilterDialog()
    field = getattr(dialog, field_name)
    if field_name == "dynamic_filters_edit":
        field.setPlainText(value)
    else:
        field.setText(value)

    assert not dialog.apply_button.isEnabled()
    assert not dialog.validation_error_label.isHidden()
    assert message in dialog.validation_error_label.text()
    dialog.close()


def test_filter_reset_and_cancel_discard_only_confirmed_draft_changes(monkeypatch):
    _app()
    committed = ProductionFilterState(references=("REF-1",))
    dialog = IndustrialAnalyticsFilterDialog(filter_state=committed)
    answers = iter(
        (
            analytics_filter_dialog.QMessageBox.StandardButton.No,
            analytics_filter_dialog.QMessageBox.StandardButton.Yes,
            analytics_filter_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    prompts = []
    monkeypatch.setattr(
        analytics_filter_dialog.QMessageBox,
        "question",
        lambda *args: prompts.append(args) or next(answers),
    )

    dialog.text_fields["references"].setText("REF-2")
    dialog._request_reset_filters()
    assert dialog.current_state().references == ("REF-2",)

    dialog._request_reset_filters()
    assert dialog.current_state() == ProductionFilterState()
    assert dialog.filter_state == committed

    dialog.text_fields["references"].setText("REF-3")
    dialog.show()
    _app().processEvents()
    dialog._request_cancel()
    assert dialog.current_state() == committed
    assert dialog.filter_state == committed
    assert len(prompts) == 3


def test_filter_apply_is_the_only_commit_point():
    _app()
    committed = ProductionFilterState(references=("REF-1",))
    dialog = IndustrialAnalyticsFilterDialog(filter_state=committed)
    dialog.text_fields["references"].setText("REF-2")

    assert dialog.filter_state == committed
    dialog.accept()
    assert dialog.filter_state == ProductionFilterState(references=("REF-2",))


def test_clean_cancel_and_window_close_do_not_prompt(monkeypatch):
    _app()
    dialog = IndustrialAnalyticsFilterDialog(
        filter_state=ProductionFilterState(references=("REF-1",))
    )
    monkeypatch.setattr(
        analytics_filter_dialog.QMessageBox,
        "question",
        lambda *_args: pytest.fail("clean cancel should not ask for confirmation"),
    )
    dialog._request_cancel()

    dialog = IndustrialAnalyticsFilterDialog()
    dialog.text_fields["references"].setText("REF-2")
    dialog.close()


def test_filter_dirty_x_and_escape_restore_committed_state(monkeypatch):
    app = _app()
    committed = ProductionFilterState(references=("REF-1",))
    dialog = IndustrialAnalyticsFilterDialog(filter_state=committed)
    answers = iter(
        (
            analytics_filter_dialog.QMessageBox.StandardButton.No,
            analytics_filter_dialog.QMessageBox.StandardButton.Yes,
            analytics_filter_dialog.QMessageBox.StandardButton.No,
            analytics_filter_dialog.QMessageBox.StandardButton.Yes,
        )
    )
    monkeypatch.setattr(
        analytics_filter_dialog.QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )
    try:
        dialog.show()
        app.processEvents()
        dialog.text_fields["references"].setText("REF-2")

        assert dialog.close() is False
        assert dialog.isVisible()
        assert dialog.current_state().references == ("REF-2",)
        assert dialog.filter_state == committed
        assert dialog.close() is True
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert dialog.filter_state == committed

        dialog.show()
        app.processEvents()
        dialog.text_fields["references"].setText("REF-3")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert dialog.isVisible()
        assert dialog.current_state().references == ("REF-3",)
        assert dialog.filter_state == committed
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert not dialog.isVisible()
        assert dialog.current_state() == committed
        assert dialog.filter_state == committed
    finally:
        dialog.close()
