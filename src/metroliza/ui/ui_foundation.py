"""Small PyQt UI helpers shared by Metroliza workflow dialogs."""

from __future__ import annotations

import weakref

try:
    from PyQt6.QtCore import QEvent, QObject, QTimer
except (AttributeError, ImportError):  # pragma: no cover - lightweight Qt stubs
    QEvent = None
    QObject = None
    QTimer = None

try:
    from PyQt6.QtGui import QColor, QPalette
except (AttributeError, ImportError):  # pragma: no cover - lightweight Qt stubs
    QColor = None
    QPalette = None

from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

try:
    from PyQt6.QtWidgets import QWIDGETSIZE_MAX
except (AttributeError, ImportError):  # pragma: no cover - lightweight Qt stubs
    QWIDGETSIZE_MAX = 16777215

from metroliza.ui import ui_theme_tokens as tokens


BUTTON_ROLE_PRIMARY = "primary"
BUTTON_ROLE_SECONDARY = "secondary"
BUTTON_ROLE_QUIET = "quiet"
BUTTON_ROLE_DANGER = "danger"
BUTTON_ROLES = frozenset(
    {
        BUTTON_ROLE_PRIMARY,
        BUTTON_ROLE_SECONDARY,
        BUTTON_ROLE_QUIET,
        BUTTON_ROLE_DANGER,
    }
)


def _event_type(name):
    if QEvent is None or not hasattr(QEvent, "Type"):
        return None
    return getattr(QEvent.Type, name, None)


_ADAPTIVE_LAYOUT_EVENTS = {
    event_type
    for event_type in (
        _event_type("Show"),
        _event_type("LayoutRequest"),
    )
    if event_type is not None
}
_ADAPTIVE_FORCE_EVENTS = {
    event_type
    for event_type in (
        _event_type("FontChange"),
        _event_type("ApplicationFontChange"),
    )
    if event_type is not None
}


class _AdaptiveWindowEventFilter(QObject if QObject is not None else object):
    """Re-evaluate declared window sizing after layout and font changes."""

    def __init__(self, parent=None):
        if QObject is not None:
            super().__init__(parent)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type in _ADAPTIVE_LAYOUT_EVENTS:
            _schedule_window_size_finalization(watched)
        elif event_type in _ADAPTIVE_FORCE_EVENTS:
            _schedule_window_size_finalization(watched, force=True)
        return False


def _is_dark_widget_palette(widget):
    try:
        palette = widget.palette()
        if QPalette is not None:
            color = palette.color(QPalette.ColorRole.Window)
        else:  # pragma: no cover - lightweight Qt stubs
            role = widget.backgroundRole() if hasattr(widget, "backgroundRole") else None
            color = palette.color(role)
        color_name = color.name() if hasattr(color, "name") else ""
    except Exception:
        return False
    return tokens.is_dark_mode_base(color_name)


def metroliza_stylesheet(dark_mode=False):
    """Return the restrained desktop QSS used by refreshed PyQt surfaces."""
    palette = tokens.theme_tokens(dark_mode=dark_mode)
    status_colors = palette["STATUS_COLORS"]
    return f"""
QWidget {{
    color: {palette["TEXT_PRIMARY"]};
}}
QDialog, QMainWindow {{
    background: {palette["WINDOW_BACKGROUND"]};
}}
QLabel[secondary="true"] {{
    color: {palette["TEXT_SECONDARY"]};
}}
QLabel[sectionLabel="true"] {{
    color: {palette["TEXT_PRIMARY"]};
    font-weight: 600;
    padding-top: 2px;
    padding-bottom: 2px;
}}
QLabel[linkLabel="true"] {{
    color: {palette["ACCENT_INFO"]};
    text-decoration: underline;
}}
QLabel[linkLabel="true"]:focus {{
    border: 2px solid {palette["FOCUS_RING"]};
    border-radius: {tokens.RADIUS_SM}px;
}}
QLabel[statusChip="true"] {{
    border: 1px solid {palette["BORDER_SUBTLE"]};
    border-radius: {tokens.RADIUS_MD}px;
    padding: 4px 8px;
    background: {palette["SURFACE_MUTED_BACKGROUND"]};
}}
QLabel[statusVariant="info"] {{
    color: {palette["ACCENT_INFO"]};
    background: {status_colors["info"][1]};
}}
QLabel[statusVariant="success"] {{
    color: {palette["ACCENT_SUCCESS"]};
    background: {status_colors["success"][1]};
}}
QLabel[statusVariant="warning"] {{
    color: {palette["ACCENT_WARNING"]};
    background: {status_colors["warning"][1]};
}}
QLabel[statusVariant="danger"] {{
    color: {palette["ACCENT_DANGER"]};
    background: {status_colors["danger"][1]};
}}
QPushButton {{
    color: {palette["TEXT_PRIMARY"]};
    background: {palette["SURFACE_BACKGROUND"]};
    border: 1px solid {palette["BORDER_STRONG"]};
    border-radius: {tokens.RADIUS_MD}px;
    padding: 5px 12px;
    min-height: 24px;
}}
QPushButton:hover {{
    border-color: {palette["ACCENT_PRIMARY"]};
    background: {palette["BUTTON_HOVER_BACKGROUND"]};
}}
QPushButton:focus {{
    border: 2px solid {palette["FOCUS_RING"]};
}}
QPushButton[buttonRole="primary"] {{
    color: {palette["DEFAULT_BUTTON_TEXT"]};
    background: {palette["ACCENT_PRIMARY"]};
    border-color: {palette["ACCENT_PRIMARY"]};
}}
QPushButton[buttonRole="primary"]:hover {{
    background: {palette["ACCENT_PRIMARY_HOVER"]};
    border-color: {palette["ACCENT_PRIMARY_HOVER"]};
}}
QPushButton[buttonRole="primary"]:focus {{
    border: 2px solid {palette["DEFAULT_BUTTON_TEXT"]};
}}
QPushButton[buttonRole="quiet"] {{
    background: transparent;
    border-color: transparent;
}}
QPushButton[buttonRole="danger"] {{
    color: {palette["ACCENT_DANGER"]};
    border-color: {palette["ACCENT_DANGER"]};
}}
QPushButton[buttonRole="danger"]:hover {{
    background: {status_colors["danger"][1]};
}}
QPushButton:disabled {{
    color: {palette["DISABLED_TEXT"]};
    background: {palette["SURFACE_MUTED_BACKGROUND"]};
    border-color: {palette["BORDER_SUBTLE"]};
}}
QToolButton {{
    color: {palette["TEXT_PRIMARY"]};
    background: transparent;
    border: 1px solid transparent;
    border-radius: {tokens.RADIUS_SM}px;
    padding: 3px;
}}
QToolButton:hover {{
    background: {palette["BUTTON_HOVER_BACKGROUND"]};
    border-color: {palette["BORDER_SUBTLE"]};
}}
QToolButton:focus {{
    border: 2px solid {palette["FOCUS_RING"]};
}}
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QTimeEdit,
QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QTextBrowser,
QListView, QListWidget, QTreeView, QTreeWidget, QTableView, QTableWidget {{
    color: {palette["TEXT_PRIMARY"]};
    background: {palette["SURFACE_BACKGROUND"]};
    border: 1px solid {palette["BORDER_SUBTLE"]};
    border-radius: {tokens.RADIUS_SM}px;
    padding: 3px;
    min-height: 22px;
    selection-background-color: {tokens.SELECTED_ROW_BACKGROUND_FALLBACK};
}}
QLineEdit:read-only, QPlainTextEdit:read-only, QTextEdit:read-only {{
    background: {palette["SURFACE_MUTED_BACKGROUND"]};
    color: {palette["TEXT_SECONDARY"]};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QTimeEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus,
QTextBrowser:focus, QListView:focus, QListWidget:focus, QTreeView:focus,
QTreeWidget:focus, QTableView:focus, QTableWidget:focus {{
    border: 2px solid {palette["FOCUS_RING"]};
}}
QTableWidget::item:selected, QListWidget::item:selected {{
    background: {tokens.selected_row_background_override(tokens.SELECTED_ROW_BACKGROUND_FALLBACK)};
    color: {tokens.selected_text_color(tokens.SELECTED_ROW_BACKGROUND_FALLBACK)};
}}
QHeaderView::section {{
    color: {palette["TEXT_PRIMARY"]};
    background: {palette["SURFACE_MUTED_BACKGROUND"]};
    border: 0;
    border-right: 1px solid {palette["BORDER_SUBTLE"]};
    border-bottom: 1px solid {palette["BORDER_SUBTLE"]};
    padding: 4px 6px;
    font-weight: 600;
}}
QGroupBox {{
    border: 1px solid {palette["BORDER_SUBTLE"]};
    border-radius: {tokens.RADIUS_MD}px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QTabWidget::pane {{
    border: 1px solid {palette["BORDER_SUBTLE"]};
    background: {palette["SURFACE_BACKGROUND"]};
}}
QTabBar::tab {{
    color: {palette["TEXT_SECONDARY"]};
    background: {palette["SURFACE_MUTED_BACKGROUND"]};
    border: 1px solid {palette["BORDER_SUBTLE"]};
    padding: 6px 10px;
}}
QTabBar::tab:selected {{
    color: {palette["TEXT_PRIMARY"]};
    background: {palette["SURFACE_BACKGROUND"]};
    border-bottom-color: {palette["ACCENT_PRIMARY"]};
}}
QTabBar::tab:focus {{
    border: 2px solid {palette["FOCUS_RING"]};
}}
QMenuBar {{
    color: {palette["TEXT_PRIMARY"]};
    background: {palette["WINDOW_BACKGROUND"]};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    color: {palette["DEFAULT_BUTTON_TEXT"]};
    background: {palette["ACCENT_PRIMARY"]};
}}
QMenu {{
    color: {palette["TEXT_PRIMARY"]};
    background: {palette["SURFACE_BACKGROUND"]};
    border: 1px solid {palette["BORDER_SUBTLE"]};
}}
QCheckBox:focus, QRadioButton:focus, QSlider:focus {{
    border: 2px solid {palette["FOCUS_RING"]};
    border-radius: {tokens.RADIUS_SM}px;
}}
QProgressBar {{
    color: {palette["TEXT_PRIMARY"]};
    background: {palette["SURFACE_MUTED_BACKGROUND"]};
    border: 1px solid {palette["BORDER_SUBTLE"]};
    border-radius: {tokens.RADIUS_SM}px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {palette["ACCENT_PRIMARY"]};
    border-radius: {tokens.RADIUS_SM}px;
}}
QFrame[separator="true"] {{
    color: {palette["BORDER_SUBTLE"]};
    background: {palette["BORDER_SUBTLE"]};
}}
"""


def _themed_palette(base_palette, semantic_palette):
    if (
        base_palette is None
        or
        QPalette is None
        or QColor is None
        or not hasattr(QPalette, "ColorRole")
    ):  # pragma: no cover - lightweight Qt stubs
        return base_palette
    palette = QPalette(base_palette)
    role = QPalette.ColorRole
    palette.setColor(role.Window, QColor(semantic_palette["WINDOW_BACKGROUND"]))
    palette.setColor(role.WindowText, QColor(semantic_palette["TEXT_PRIMARY"]))
    palette.setColor(role.Base, QColor(semantic_palette["SURFACE_BACKGROUND"]))
    palette.setColor(role.AlternateBase, QColor(semantic_palette["SURFACE_MUTED_BACKGROUND"]))
    palette.setColor(role.Text, QColor(semantic_palette["TEXT_PRIMARY"]))
    palette.setColor(role.Button, QColor(semantic_palette["SURFACE_BACKGROUND"]))
    palette.setColor(role.ButtonText, QColor(semantic_palette["TEXT_PRIMARY"]))
    palette.setColor(role.Highlight, QColor(semantic_palette["ACCENT_PRIMARY"]))
    palette.setColor(role.HighlightedText, QColor(semantic_palette["DEFAULT_BUTTON_TEXT"]))
    palette.setColor(role.Link, QColor(semantic_palette["ACCENT_INFO"]))
    palette.setColor(role.LinkVisited, QColor(semantic_palette["ACCENT_PRIMARY_HOVER"]))
    palette.setColor(role.PlaceholderText, QColor(semantic_palette["TEXT_MUTED"]))
    disabled = QPalette.ColorGroup.Disabled
    disabled_color = QColor(semantic_palette["DISABLED_TEXT"])
    for text_role in (role.WindowText, role.Text, role.ButtonText, role.PlaceholderText):
        palette.setColor(disabled, text_role, disabled_color)
    return palette


def apply_metroliza_theme(widget, *, dark_mode=None):
    """Apply the shared visual layer to a top-level widget or dialog."""
    if widget is None or not hasattr(widget, "setStyleSheet"):
        return
    if not hasattr(widget, "_metroliza_base_stylesheet"):
        widget._metroliza_base_stylesheet = widget.styleSheet()
    application = QApplication.instance()
    high_contrast = (
        application is not None
        and widget is not application
        and application.property("metrolizaThemeMode") == "high_contrast"
    )
    if high_contrast:
        _restore_widget_system_theme(widget)
        return
    resolved_dark_mode = _is_dark_widget_palette(widget) if dark_mode is None else bool(dark_mode)
    semantic_palette = tokens.theme_tokens(dark_mode=resolved_dark_mode)
    # Replace QSS before resolving explicit palette roles; otherwise a previous
    # theme's style-sheet palette can overwrite link and placeholder roles.
    widget.setStyleSheet(metroliza_stylesheet(dark_mode=resolved_dark_mode))
    if hasattr(widget, "setPalette") and hasattr(widget, "palette"):
        widget.setPalette(_themed_palette(widget.palette(), semantic_palette))
    if hasattr(widget, "findChildren"):
        for link_label in widget.findChildren(QWidget) or ():
            if link_label.property("linkLabel") is True:
                link_label.setPalette(_themed_palette(link_label.palette(), semantic_palette))
    if hasattr(widget, "setProperty"):
        widget.setProperty("metrolizaThemeManaged", True)
        widget.setProperty("metrolizaDarkMode", resolved_dark_mode)


def _restore_widget_system_theme(widget):
    """Remove Metroliza palette overrides so platform high-contrast colors can propagate."""

    if widget is None:
        return
    if hasattr(widget, "setStyleSheet"):
        widget.setStyleSheet(getattr(widget, "_metroliza_base_stylesheet", ""))
    if hasattr(widget, "setPalette") and QPalette is not None:
        widget.setPalette(QPalette())
    if hasattr(widget, "findChildren") and QPalette is not None:
        for child in widget.findChildren(QWidget):
            if child.property("linkLabel") is True:
                child.setPalette(QPalette())
    if hasattr(widget, "setProperty"):
        widget.setProperty("metrolizaThemeManaged", True)
        widget.setProperty("metrolizaDarkMode", None)


def _refresh_open_window_themes(application, *, mode, dark_mode=False):
    if not hasattr(application, "topLevelWidgets"):
        return
    for widget in application.topLevelWidgets():
        if widget.property("metrolizaThemeManaged") is not True:
            continue
        if mode == "high_contrast":
            _restore_widget_system_theme(widget)
        else:
            apply_metroliza_theme(widget, dark_mode=dark_mode)


def apply_metroliza_application_theme(app=None, *, dark_mode=None, mode=None):
    """Apply a system, light, dark, or system-high-contrast application theme."""
    application = app or QApplication.instance()
    if application is None:
        return
    if not hasattr(application, "_metroliza_system_palette"):
        application._metroliza_system_palette = QPalette(application.palette())
        application._metroliza_system_stylesheet = application.styleSheet()

    resolved_mode = mode
    if resolved_mode is None:
        if dark_mode is None:
            resolved_mode = "system"
        else:
            resolved_mode = "dark" if dark_mode else "light"
    if resolved_mode not in {"system", "light", "dark", "high_contrast"}:
        raise ValueError(f"Unknown application theme mode: {resolved_mode}")

    system_palette = QPalette(application._metroliza_system_palette)
    if resolved_mode == "high_contrast":
        application.setStyleSheet(application._metroliza_system_stylesheet)
        application.setPalette(system_palette)
        application.setProperty("metrolizaThemeMode", resolved_mode)
        _refresh_open_window_themes(application, mode=resolved_mode)
        return

    system_window = system_palette.color(QPalette.ColorRole.Window).name()
    resolved_dark = (
        tokens.is_dark_mode_base(system_window)
        if resolved_mode == "system"
        else resolved_mode == "dark"
    )
    application.setPalette(system_palette)
    apply_metroliza_theme(application, dark_mode=resolved_dark)
    application.setProperty("metrolizaThemeMode", resolved_mode)
    _refresh_open_window_themes(
        application,
        mode=resolved_mode,
        dark_mode=resolved_dark,
    )


def _available_window_size(widget, screen_margin):
    screen = widget.screen() if hasattr(widget, "screen") else None
    if screen is None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None and hasattr(app, "primaryScreen") else None
    if screen is None or not hasattr(screen, "availableGeometry"):
        return None
    available = screen.availableGeometry()
    return (
        max(320, available.width() - screen_margin),
        max(240, available.height() - screen_margin),
    )


def _bounded_dimensions(width, height, available):
    if available is None:
        return width, height
    return min(width, available[0]), min(height, available[1])


def configure_window_size(widget, *, minimum=(420, 260), initial=(640, 420), screen_margin=40):
    """Declare adaptive window sizing without imposing a permanent screen maximum."""
    config = {
        "minimum": tuple(minimum),
        "initial": tuple(initial),
        "screen_margin": max(0, int(screen_margin)),
        "finalized": False,
        "scheduled": False,
    }
    widget._metroliza_window_size_config = config
    available = _available_window_size(widget, config["screen_margin"])
    min_width, min_height = _bounded_dimensions(*minimum, available)
    initial_width, initial_height = _bounded_dimensions(*initial, available)
    if hasattr(widget, "setMaximumSize"):
        widget.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
    if hasattr(widget, "setMinimumSize"):
        widget.setMinimumSize(min_width, min_height)
    if hasattr(widget, "resize"):
        widget.resize(initial_width, initial_height)
    if hasattr(widget, "installEventFilter") and not hasattr(
        widget,
        "_metroliza_window_event_filter",
    ):
        event_filter = _AdaptiveWindowEventFilter(widget)
        widget._metroliza_window_event_filter = event_filter
        widget.installEventFilter(event_filter)
    _schedule_window_size_finalization(widget)


def _size_hint_dimensions(widget):
    widths = []
    heights = []
    layout_getter = getattr(widget, "layout", None)
    layout = layout_getter() if callable(layout_getter) else layout_getter
    if layout is not None:
        if hasattr(layout, "activate"):
            layout.activate()
        if hasattr(layout, "minimumSize"):
            layout_minimum = layout.minimumSize()
            widths.append(layout_minimum.width())
            heights.append(layout_minimum.height())
    if hasattr(widget, "minimumSizeHint"):
        minimum_hint = widget.minimumSizeHint()
        widths.append(minimum_hint.width())
        heights.append(minimum_hint.height())
    return max(widths, default=0), max(heights, default=0)


def _connect_screen_geometry_changes(widget, screen):
    if screen is None or not hasattr(screen, "availableGeometryChanged"):
        return
    previous_screen = getattr(widget, "_metroliza_window_geometry_screen", None)
    if previous_screen is screen:
        return
    previous_callback = getattr(widget, "_metroliza_window_geometry_callback", None)
    if previous_screen is not None and previous_callback is not None:
        try:
            previous_screen.availableGeometryChanged.disconnect(previous_callback)
        except (RuntimeError, TypeError):
            pass
    widget_ref = weakref.ref(widget)

    def _geometry_changed(_geometry):
        target = widget_ref()
        if target is not None:
            _schedule_window_size_finalization(target, force=True)

    screen.availableGeometryChanged.connect(_geometry_changed)
    widget._metroliza_window_geometry_callback = _geometry_changed
    widget._metroliza_window_geometry_screen = screen


def _connect_window_screen_changes(widget):
    current_screen = widget.screen() if hasattr(widget, "screen") else None
    _connect_screen_geometry_changes(widget, current_screen)
    if getattr(widget, "_metroliza_window_screen_connected", False):
        return
    handle = widget.windowHandle() if hasattr(widget, "windowHandle") else None
    if handle is None or not hasattr(handle, "screenChanged"):
        return
    widget_ref = weakref.ref(widget)

    def _screen_changed(screen):
        target = widget_ref()
        if target is not None:
            _connect_screen_geometry_changes(target, screen)
            _schedule_window_size_finalization(target, force=True)

    handle.screenChanged.connect(_screen_changed)
    widget._metroliza_window_screen_callback = _screen_changed
    widget._metroliza_window_screen_connected = True


def _ensure_window_reachable(widget):
    """Move a restored window back on-screen only when no useful area is reachable."""

    app = QApplication.instance()
    if app is None or not hasattr(app, "screens") or not hasattr(widget, "frameGeometry"):
        return
    if hasattr(widget, "isMaximized") and (widget.isMaximized() or widget.isFullScreen()):
        return
    frame = widget.frameGeometry()
    screens = tuple(app.screens())
    for screen in screens:
        available = screen.availableGeometry()
        visible = frame.intersected(available)
        if visible.width() >= min(120, frame.width()) and visible.height() >= min(40, frame.height()):
            return

    screen = widget.screen() if hasattr(widget, "screen") else None
    if screen not in screens:
        screen = app.primaryScreen() if hasattr(app, "primaryScreen") else None
    if screen is None:
        return
    available = screen.availableGeometry()
    width = min(widget.width(), available.width())
    height = min(widget.height(), available.height())
    x = max(available.left(), min(widget.x(), available.right() - width + 1))
    y = max(available.top(), min(widget.y(), available.bottom() - height + 1))
    widget.move(x, y)


def finalize_window_size(widget, *, force=False, shrink=False):
    """Reconcile declared sizing with final layout metrics and the current screen."""
    config = getattr(widget, "_metroliza_window_size_config", None)
    if not config:
        return
    available = _available_window_size(widget, config["screen_margin"])
    min_width, min_height = _bounded_dimensions(*config["minimum"], available)
    if hasattr(widget, "setMinimumSize"):
        widget.setMinimumSize(min_width, min_height)

    hint_width, hint_height = _size_hint_dimensions(widget)
    base_width, base_height = config["minimum"] if shrink else config["initial"]
    desired_width = max(base_width, hint_width)
    desired_height = max(base_height, hint_height)
    desired_width, desired_height = _bounded_dimensions(
        desired_width,
        desired_height,
        available,
    )

    first_finalization = not config["finalized"]
    config["finalized"] = True
    current_width = widget.width() if hasattr(widget, "width") else desired_width
    current_height = widget.height() if hasattr(widget, "height") else desired_height
    if available is not None:
        current_width = min(current_width, available[0])
        current_height = min(current_height, available[1])
    if first_finalization or force or shrink:
        current_width = desired_width if shrink else max(current_width, desired_width)
        current_height = desired_height if shrink else max(current_height, desired_height)
        if available is not None:
            current_width = min(current_width, available[0])
            current_height = min(current_height, available[1])

    should_resize = (current_width, current_height) != (
        widget.width() if hasattr(widget, "width") else current_width,
        widget.height() if hasattr(widget, "height") else current_height,
    )
    if should_resize and hasattr(widget, "resize") and not (
        hasattr(widget, "isMaximized") and (widget.isMaximized() or widget.isFullScreen())
    ):
        widget.resize(current_width, current_height)
    _ensure_window_reachable(widget)
    _connect_window_screen_changes(widget)


def _schedule_window_size_finalization(widget, *, force=False):
    config = getattr(widget, "_metroliza_window_size_config", None)
    if not config:
        return
    if QTimer is None or not hasattr(QTimer, "singleShot"):  # pragma: no cover - Qt stubs
        return
    if config["scheduled"]:
        config["force_scheduled"] = config.get("force_scheduled", False) or force
        return
    config["scheduled"] = True
    config["force_scheduled"] = force
    widget_ref = weakref.ref(widget)

    def _finalize():
        target = widget_ref()
        if target is None:
            return
        target_config = getattr(target, "_metroliza_window_size_config", None)
        if not target_config:
            return
        target_config["scheduled"] = False
        scheduled_force = target_config.pop("force_scheduled", False)
        try:
            finalize_window_size(target, force=scheduled_force)
        except RuntimeError:
            return

    QTimer.singleShot(0, _finalize)


def _refresh_widget_style(widget):
    style = widget.style() if hasattr(widget, "style") else None
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    if hasattr(widget, "update"):
        widget.update()


def set_button_role(button, role=BUTTON_ROLE_SECONDARY, *, default=False):
    """Assign a semantic visual role and explicit Qt default behavior."""
    if role not in BUTTON_ROLES:
        raise ValueError(f"Unknown button role: {role}")
    if default and role != BUTTON_ROLE_PRIMARY:
        raise ValueError("Only a primary button can be the dialog default")
    if hasattr(button, "setProperty"):
        button.setProperty("buttonRole", role)
    if hasattr(button, "setAutoDefault"):
        button.setAutoDefault(bool(default))
    if hasattr(button, "setDefault"):
        button.setDefault(bool(default))
    _refresh_widget_style(button)
    return button


def configure_dialog_button_roles(
    *,
    primary=None,
    secondary=(),
    quiet=(),
    danger=(),
):
    """Configure one stable primary action and explicit roles for peer buttons."""
    assignments = (
        (primary, BUTTON_ROLE_PRIMARY, True),
        *((button, BUTTON_ROLE_SECONDARY, False) for button in secondary),
        *((button, BUTTON_ROLE_QUIET, False) for button in quiet),
        *((button, BUTTON_ROLE_DANGER, False) for button in danger),
    )
    seen = set()
    for button, role, default in assignments:
        if button is None:
            continue
        identity = id(button)
        if identity in seen:
            raise ValueError("A dialog button cannot have multiple semantic roles")
        seen.add(identity)
        set_button_role(button, role, default=default)


def _label(text):
    try:
        label = QLabel(text)
    except TypeError:
        label = QLabel()
        if hasattr(label, "setText"):
            label.setText(text)
    return label


def section_label(text):
    label = _label(text)
    if hasattr(label, "setProperty"):
        label.setProperty("sectionLabel", True)
    if hasattr(label, "setSizePolicy"):
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return label


def secondary_label(text):
    label = _label(text)
    if hasattr(label, "setProperty"):
        label.setProperty("secondary", True)
    if hasattr(label, "setWordWrap"):
        label.setWordWrap(True)
    if hasattr(label, "setSizePolicy"):
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
    return label


def status_chip(text, variant="neutral"):
    label = _label(text)
    if hasattr(label, "setProperty"):
        label.setProperty("statusChip", True)
        label.setProperty("statusVariant", variant)
    if hasattr(label, "setWordWrap"):
        label.setWordWrap(True)
    if hasattr(label, "setSizePolicy"):
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
    return label


def separator():
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.HLine)
    frame.setFrameShadow(QFrame.Shadow.Plain)
    frame.setProperty("separator", True)
    frame.setFixedHeight(1)
    return frame


def path_field(value="", *, empty_text="None selected"):
    field = QLineEdit()
    field.setReadOnly(True)
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    field.setMinimumWidth(120)
    update_path_field(field, value, empty_text=empty_text)
    return field


def update_path_field(field, value, *, empty_text="None selected"):
    text = str(value or "").strip()
    field.setText(text if text else empty_text)
    field.setToolTip(text if text else "")
    if text and hasattr(field, "setCursorPosition"):
        field.setCursorPosition(0)


def configure_table(table, *, stretch_column=0, resize_to_contents=(), min_height=None):
    """Apply consistent table behavior without changing the data model."""
    if table is None:
        return
    if min_height is not None and hasattr(table, "setMinimumHeight"):
        table.setMinimumHeight(min_height)
    if hasattr(table, "setAlternatingRowColors"):
        table.setAlternatingRowColors(True)
    if hasattr(table, "setSizePolicy"):
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    header = table.horizontalHeader() if hasattr(table, "horizontalHeader") else None
    if header is None or not hasattr(header, "setSectionResizeMode"):
        return
    if hasattr(header, "setStretchLastSection"):
        header.setStretchLastSection(False)
    for column in range(table.columnCount() if hasattr(table, "columnCount") else 0):
        mode = QHeaderView.ResizeMode.Interactive
        if column == stretch_column:
            mode = QHeaderView.ResizeMode.Stretch
        elif column in resize_to_contents:
            mode = QHeaderView.ResizeMode.ResizeToContents
        header.setSectionResizeMode(column, mode)


def configure_accessibility(widget, *, name, description=""):
    if hasattr(widget, "setAccessibleName"):
        widget.setAccessibleName(name)
    if description and hasattr(widget, "setAccessibleDescription"):
        widget.setAccessibleDescription(description)


def info_button(tooltip_text, *, name="More information", size=24):
    """Create a compact supplemental help target with accessible metadata."""
    try:
        from PyQt6.QtWidgets import QToolButton

        button = QToolButton()
        button.setAutoRaise(True)
    except (ImportError, AttributeError):  # pragma: no cover - lightweight Qt stubs
        button = QPushButton()
    button.setText("?")
    button.setToolTip(str(tooltip_text or ""))
    configure_accessibility(button, name=name, description=str(tooltip_text or ""))
    if hasattr(button, "setFixedSize"):
        button.setFixedSize(size, size)
    return button


def apply_list_selection_style(list_widget):
    """Keep selected list rows readable under platform themes."""
    if list_widget is None or not hasattr(list_widget, "setStyleSheet"):
        return
    highlight_name = tokens.SELECTED_ROW_BACKGROUND_FALLBACK
    palette = list_widget.palette() if hasattr(list_widget, "palette") else None
    highlight_color = palette.highlight().color() if palette is not None and hasattr(palette, "highlight") else None
    if highlight_color is not None and hasattr(highlight_color, "isValid") and highlight_color.isValid():
        highlight_name = highlight_color.name()
    selected_background = tokens.selected_row_background_override(highlight_name)
    selected_text = tokens.selected_text_color(selected_background)
    list_widget.setStyleSheet(
        "QListWidget::item:selected {"
        f" background-color: {selected_background};"
        f" color: {selected_text};"
        " }"
    )


def set_status_variant(widget, variant):
    """Update a status chip's semantic variant and refresh its QSS state."""
    if widget is None or not isinstance(widget, QWidget):
        return
    widget.setProperty("statusVariant", variant)
    _refresh_widget_style(widget)
