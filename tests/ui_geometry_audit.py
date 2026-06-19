"""Reusable PyQt geometry assertions for visible UI layout audits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class WidgetRect:
    widget_class: str
    widget_name: str
    text: str
    rect: tuple[int, int, int, int]
    parent_class: str
    parent_name: str


@dataclass(frozen=True)
class OverlapFinding:
    first: WidgetRect
    second: WidgetRect
    intersection: tuple[int, int, int, int]


def _qt_classes():
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QAbstractScrollArea,
        QCheckBox,
        QComboBox,
        QDateEdit,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFrame,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidget,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QTabWidget,
        QTableWidget,
        QTextEdit,
        QWidget,
    )

    control_types = (
        QAbstractButton,
        QCheckBox,
        QComboBox,
        QDateEdit,
        QDoubleSpinBox,
        QLabel,
        QLineEdit,
        QListWidget,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTextEdit,
    )
    container_types = (
        QAbstractScrollArea,
        QDialogButtonBox,
        QFrame,
        QGroupBox,
        QScrollArea,
        QTabWidget,
    )
    return Qt, QWidget, QScrollArea, control_types, container_types


def _direct_widget_children(widget) -> list:
    Qt, QWidget, _scroll_area_type, _control_types, _container_types = _qt_classes()
    return widget.findChildren(
        QWidget,
        options=Qt.FindChildOption.FindDirectChildrenOnly,
    )


def _visible_to_root(widget, root) -> bool:
    if widget is root:
        return False
    if not widget.isVisibleTo(root):
        return False
    geometry = widget.geometry()
    return geometry.width() > 0 and geometry.height() > 0


def _widget_text(widget) -> str:
    text_getter = getattr(widget, "text", None)
    if callable(text_getter):
        try:
            text = str(text_getter())
        except TypeError:
            text = ""
        return text[:80]
    placeholder_getter = getattr(widget, "placeholderText", None)
    if callable(placeholder_getter):
        return str(placeholder_getter())[:80]
    return ""


def _describe_widget(widget) -> WidgetRect:
    parent = widget.parentWidget()
    geometry = widget.geometry()
    return WidgetRect(
        widget_class=type(widget).__name__,
        widget_name=widget.objectName() or "",
        text=_widget_text(widget),
        rect=(geometry.x(), geometry.y(), geometry.width(), geometry.height()),
        parent_class=type(parent).__name__ if parent is not None else "",
        parent_name=parent.objectName() if parent is not None else "",
    )


def _is_audit_control(widget) -> bool:
    _Qt, _QWidget, _scroll_area_type, control_types, container_types = _qt_classes()
    if isinstance(widget, container_types):
        return False
    return isinstance(widget, control_types)


def iter_visible_audit_controls(root) -> Iterable:
    """Yield visible leaf controls that should obey parent geometry."""

    _Qt, QWidget, _scroll_area_type, _control_types, _container_types = _qt_classes()
    for widget in root.findChildren(QWidget):
        if _visible_to_root(widget, root) and _is_audit_control(widget):
            yield widget


def collect_parent_bounds_violations(root, *, tolerance: int = 1) -> list[WidgetRect]:
    findings: list[WidgetRect] = []
    for widget in iter_visible_audit_controls(root):
        parent = widget.parentWidget()
        if parent is None:
            continue
        rect = widget.geometry()
        parent_rect = parent.rect().adjusted(-tolerance, -tolerance, tolerance, tolerance)
        if not parent_rect.contains(rect):
            findings.append(_describe_widget(widget))
    return findings


def collect_sibling_overlaps(root, *, min_area: int = 24) -> list[OverlapFinding]:
    """Return visible direct sibling control overlaps.

    Parent/child intersections are expected in Qt layouts, so this only compares
    direct sibling controls. That keeps the check focused on real layout
    collisions caused by bad fixed sizes, offsets, or stacked controls.
    """

    findings: list[OverlapFinding] = []
    _Qt, QWidget, _scroll_area_type, _control_types, _container_types = _qt_classes()
    for parent in [root, *root.findChildren(QWidget)]:
        if parent is not root and not parent.isVisibleTo(root):
            continue
        children = [
            child
            for child in _direct_widget_children(parent)
            if _visible_to_root(child, root) and _is_audit_control(child)
        ]
        for index, first in enumerate(children):
            first_rect = first.geometry()
            for second in children[index + 1 :]:
                intersection = first_rect.intersected(second.geometry())
                if intersection.isEmpty():
                    continue
                area = intersection.width() * intersection.height()
                if area < min_area:
                    continue
                findings.append(
                    OverlapFinding(
                        first=_describe_widget(first),
                        second=_describe_widget(second),
                        intersection=(
                            intersection.x(),
                            intersection.y(),
                            intersection.width(),
                            intersection.height(),
                        ),
                    )
                )
    return findings


def collect_hidden_horizontal_scroll_violations(root, *, tolerance: int = 2) -> list[dict[str, int | str]]:
    from PyQt6.QtCore import Qt

    _Qt, _QWidget, scroll_area_type, _control_types, _container_types = _qt_classes()
    findings: list[dict[str, int | str]] = []
    for scroll_area in root.findChildren(scroll_area_type):
        if not _visible_to_root(scroll_area, root):
            continue
        if scroll_area.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
            continue
        content = scroll_area.widget()
        if content is None:
            continue
        content_width = content.minimumSizeHint().width()
        viewport_width = scroll_area.viewport().width()
        if content_width > viewport_width + tolerance:
            findings.append(
                {
                    "scroll_class": type(scroll_area).__name__,
                    "scroll_name": scroll_area.objectName() or "",
                    "content_min_width": content_width,
                    "viewport_width": viewport_width,
                }
            )
    return findings


def assert_dialog_geometry_clean(dialog, app) -> None:
    """Assert a shown dialog has no obvious visible overlap or horizontal clipping."""

    dialog.show()
    app.processEvents()
    available = app.primaryScreen().availableGeometry()
    assert dialog.width() <= available.width()
    assert dialog.height() <= available.height()

    bounds = collect_parent_bounds_violations(dialog)
    assert bounds == []

    overlaps = collect_sibling_overlaps(dialog)
    assert overlaps == []

    hidden_horizontal_scroll = collect_hidden_horizontal_scroll_violations(dialog)
    assert hidden_horizontal_scroll == []
