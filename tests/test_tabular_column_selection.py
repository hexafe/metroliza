from __future__ import annotations

import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QListWidget
    from modules.tabular_column_selection import (
        column_sequence_text,
        current_column_from_list,
        populate_column_list,
        set_current_column,
    )
except ImportError as exc:  # pragma: no cover - depends on PyQt collection order
    Qt = None
    QApplication = None
    QListWidget = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

_APP = None


def _app():
    if QApplication is None:
        pytest.skip(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def test_populate_column_list_filters_and_preserves_current_item() -> None:
    _app()
    list_widget = QListWidget()

    populate_column_list(
        list_widget,
        ["tracecode", "cavity", "fixture"],
        label_for=lambda column: {"tracecode": "TraceCode"}.get(column, column.title()),
        search_text="trace",
        current_column="tracecode",
    )

    assert list_widget.count() == 1
    assert current_column_from_list(list_widget) == "tracecode"
    assert list_widget.item(0).data(Qt.ItemDataRole.UserRole) == "tracecode"


def test_populate_column_list_can_fallback_to_last_item() -> None:
    _app()
    list_widget = QListWidget()

    populate_column_list(
        list_widget,
        ["tracecode", "cavity"],
        label_for=str.upper,
        current_column="missing",
        fallback="last",
    )

    assert current_column_from_list(list_widget) == "cavity"
    set_current_column(list_widget, "tracecode")
    assert current_column_from_list(list_widget) == "tracecode"


def test_column_sequence_text_uses_labels() -> None:
    _app()
    text = column_sequence_text(["tracecode", "cavity"], label_for=str.upper)

    assert text == "TRACECODE | CAVITY"
