"""Bounded, text-free Qt geometry data for an already failing assertion."""

from __future__ import annotations

import json


def geometry_snapshot(window, *, requested: tuple[int, int], pinned: tuple[str, ...]) -> str:
    """Read geometry only; never pump events, activate layouts or alter the outcome."""
    try:
        return json.dumps(_snapshot(window, requested, pinned), separators=(",", ":"), sort_keys=True)
    except Exception as error:
        # Keep the original assertion failure even when diagnostics are unavailable.
        # Exception messages can contain paths or user input, so retain only the type.
        return json.dumps({"geometry_diagnostic_error": type(error).__name__})


def _snapshot(window, requested, pinned):
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QPoint, QRect
    from PyQt6.QtGui import QFontInfo
    from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QTabWidget

    def size(value):
        return [value.width(), value.height()]

    def rectangle(value):
        return [value.x(), value.y(), value.width(), value.height()]

    def layout_info(widget):
        value = getattr(widget, "layout", None)
        layout = value() if callable(value) else value
        if layout is None:
            return None
        width = widget.width()
        return {
            "minimum": size(layout.minimumSize()),
            "total_minimum": size(layout.totalMinimumSize()),
            "hint": size(layout.sizeHint()),
            "geometry": rectangle(layout.geometry()),
            "constraint": layout.sizeConstraint().name,
            "has_hfw": layout.hasHeightForWidth(),
            "hfw": layout.heightForWidth(width),
            "total_hfw": layout.totalHeightForWidth(width),
        }

    def widget_info(widget):
        try:
            geometry = QRect(widget.mapTo(window, QPoint()), widget.size())
            policy = widget.sizePolicy()
            result = {
                "class": type(widget).__name__[:64],
                "geometry": rectangle(geometry),
                "visible": widget.isVisibleTo(window),
                "minimum": size(widget.minimumSize()),
                "minimum_hint": size(widget.minimumSizeHint()),
                "hint": size(widget.sizeHint()),
                "has_hfw": widget.hasHeightForWidth(),
                "hfw": widget.heightForWidth(widget.width()),
                "policy": [policy.horizontalPolicy().name, policy.verticalPolicy().name],
                "layout": layout_info(widget),
                "within_actual": window.rect().contains(geometry),
                "within_requested": QRect(0, 0, *requested).contains(geometry),
            }
            if isinstance(widget, QLabel):
                result["text_length"] = len(widget.text())
            return result
        except Exception as error:
            return {"geometry_diagnostic_error": type(error).__name__}

    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    font = QFontInfo(window.font())
    config = getattr(window, "_metroliza_window_size_config", {})
    finalization = {}
    for key in ("minimum", "initial", "screen_margin", "finalized", "scheduled", "force_scheduled"):
        value = config.get(key)
        if type(value) in (bool, int) or value is None:
            finalization[key] = value
        elif isinstance(value, (tuple, list)) and len(value) == 2 and all(type(n) is int for n in value):
            finalization[key] = list(value)
        else:
            finalization[key] = {"unexpected_type": type(value).__name__[:64]}
    result = {
        "requested": list(requested),
        "size": size(window.size()),
        "frame": rectangle(window.frameGeometry()),
        "root": widget_info(window),
        "finalization": finalization,
        "qt": QT_VERSION_STR,
        "pyqt": PYQT_VERSION_STR,
        "platform": app.platformName()[:64] if app is not None else None,
        "style": app.style().objectName()[:64] if app is not None else None,
        "font": {"family": font.family()[:64], "points": font.pointSizeF(), "pixels": font.pixelSize()},
        "dpr": window.devicePixelRatioF(),
        "screen": rectangle(screen.geometry()) if screen is not None else None,
        "available": rectangle(screen.availableGeometry()) if screen is not None else None,
        "logical_dpi": screen.logicalDotsPerInch() if screen is not None else None,
        "pinned": [],
        "tabs": [],
        "scrolls": [],
    }
    for name in pinned[:16]:
        widget = getattr(window, name, None)
        result["pinned"].append({
            "attribute": name[:64],
            **({"missing": True} if widget is None else widget_info(widget)),
        })
    tabs = window.findChildren(QTabWidget)
    result["tab_count"] = len(tabs)
    for tab in tabs[:2]:
        result["tabs"].append({
            **widget_info(tab), "current": tab.currentIndex(), "page_count": tab.count(),
            "pages": [widget_info(tab.widget(index)) for index in range(min(tab.count(), 4))],
        })
    scrolls = window.findChildren(QScrollArea)
    result["scroll_count"] = len(scrolls)
    for scroll in scrolls[:4]:
        result["scrolls"].append({
            **widget_info(scroll),
            "viewport": rectangle(scroll.viewport().geometry()),
            "vertical_range": [scroll.verticalScrollBar().minimum(), scroll.verticalScrollBar().maximum()],
            "content": widget_info(scroll.widget()) if scroll.widget() is not None else None,
        })
    labels = window.findChildren(QLabel)
    result["label_count"] = len(labels)
    # Include the largest HFW/minimum contributors; retain lengths, never text.
    measured = [widget_info(label) for label in labels[:128]]
    result["labels"] = sorted(measured, key=lambda row: (
        max(row.get("hfw", -1), 0), row.get("minimum_hint", [0, 0])[1], row.get("text_length", 0)
    ), reverse=True)[:12]
    result["labels_not_measured"] = max(0, len(labels) - 128)
    return result
