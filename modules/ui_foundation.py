"""Small PyQt UI helpers shared by Metroliza workflow dialogs."""

from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

from modules import ui_theme_tokens as tokens


def metroliza_stylesheet():
    """Return the restrained desktop QSS used by refreshed PyQt surfaces."""
    return f"""
QWidget {{
    color: {tokens.TEXT_PRIMARY};
    background: {tokens.WINDOW_BACKGROUND};
}}
QDialog, QMainWindow {{
    background: {tokens.WINDOW_BACKGROUND};
}}
QLabel[secondary="true"] {{
    color: {tokens.TEXT_SECONDARY};
}}
QLabel[sectionLabel="true"] {{
    color: {tokens.TEXT_PRIMARY};
    font-weight: 600;
    padding-top: 2px;
    padding-bottom: 2px;
}}
QLabel[statusChip="true"] {{
    border: 1px solid {tokens.BORDER_SUBTLE};
    border-radius: {tokens.RADIUS_MD}px;
    padding: 4px 8px;
    background: {tokens.SURFACE_MUTED_BACKGROUND};
}}
QLabel[statusVariant="info"] {{
    color: {tokens.ACCENT_INFO};
    background: {tokens.STATUS_COLORS["info"][1]};
}}
QLabel[statusVariant="success"] {{
    color: {tokens.ACCENT_SUCCESS};
    background: {tokens.STATUS_COLORS["success"][1]};
}}
QLabel[statusVariant="warning"] {{
    color: {tokens.ACCENT_WARNING};
    background: {tokens.STATUS_COLORS["warning"][1]};
}}
QLabel[statusVariant="danger"] {{
    color: {tokens.ACCENT_DANGER};
    background: {tokens.STATUS_COLORS["danger"][1]};
}}
QPushButton {{
    background: {tokens.SURFACE_BACKGROUND};
    border: 1px solid {tokens.BORDER_STRONG};
    border-radius: {tokens.RADIUS_MD}px;
    padding: 5px 12px;
    min-height: 24px;
}}
QPushButton:hover {{
    border-color: {tokens.ACCENT_PRIMARY};
    background: #F9FCFD;
}}
QPushButton:focus {{
    border: 1px solid {tokens.FOCUS_RING};
}}
QPushButton:default {{
    color: #FFFFFF;
    background: {tokens.ACCENT_PRIMARY};
    border-color: {tokens.ACCENT_PRIMARY};
}}
QPushButton:default:hover {{
    background: {tokens.ACCENT_PRIMARY_HOVER};
    border-color: {tokens.ACCENT_PRIMARY_HOVER};
}}
QPushButton:disabled {{
    color: {tokens.DISABLED_TEXT};
    background: {tokens.SURFACE_MUTED_BACKGROUND};
    border-color: {tokens.BORDER_SUBTLE};
}}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QTextBrowser, QListWidget, QTableWidget {{
    background: {tokens.SURFACE_BACKGROUND};
    border: 1px solid {tokens.BORDER_SUBTLE};
    border-radius: {tokens.RADIUS_SM}px;
    padding: 3px;
    min-height: 22px;
    selection-background-color: {tokens.SELECTED_ROW_BACKGROUND_FALLBACK};
}}
QLineEdit:read-only {{
    background: {tokens.SURFACE_MUTED_BACKGROUND};
    color: {tokens.TEXT_SECONDARY};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QListWidget:focus, QTableWidget:focus {{
    border: 1px solid {tokens.FOCUS_RING};
}}
QTableWidget::item:selected, QListWidget::item:selected {{
    background: {tokens.selected_row_background_override(tokens.SELECTED_ROW_BACKGROUND_FALLBACK)};
    color: {tokens.selected_text_color(tokens.SELECTED_ROW_BACKGROUND_FALLBACK)};
}}
QHeaderView::section {{
    background: {tokens.SURFACE_MUTED_BACKGROUND};
    border: 0;
    border-right: 1px solid {tokens.BORDER_SUBTLE};
    border-bottom: 1px solid {tokens.BORDER_SUBTLE};
    padding: 4px 6px;
    font-weight: 600;
}}
QProgressBar {{
    background: {tokens.SURFACE_MUTED_BACKGROUND};
    border: 1px solid {tokens.BORDER_SUBTLE};
    border-radius: {tokens.RADIUS_SM}px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {tokens.ACCENT_PRIMARY};
    border-radius: {tokens.RADIUS_SM}px;
}}
QFrame[separator="true"] {{
    color: {tokens.BORDER_SUBTLE};
    background: {tokens.BORDER_SUBTLE};
}}
"""


def apply_metroliza_theme(widget):
    """Apply the shared visual layer to a top-level widget or dialog."""
    if widget is None or not hasattr(widget, "setStyleSheet"):
        return
    widget.setStyleSheet(metroliza_stylesheet())


def configure_window_size(widget, *, minimum=(420, 260), initial=(640, 420), screen_margin=40):
    """Set elastic minimum/initial size bounded by the available screen."""
    min_width, min_height = minimum
    initial_width, initial_height = initial
    if hasattr(widget, "setMinimumSize"):
        widget.setMinimumSize(min_width, min_height)

    available = None
    screen = widget.screen() if hasattr(widget, "screen") else None
    if screen is None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None and hasattr(app, "primaryScreen") else None
    if screen is not None and hasattr(screen, "availableGeometry"):
        available = screen.availableGeometry()

    if available is not None:
        max_width = max(min_width, available.width() - screen_margin)
        max_height = max(min_height, available.height() - screen_margin)
        if hasattr(widget, "setMaximumSize"):
            widget.setMaximumSize(max_width, max_height)
        initial_width = min(initial_width, max_width)
        initial_height = min(initial_height, max_height)

    if hasattr(widget, "resize"):
        widget.resize(initial_width, initial_height)


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
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return label


def status_chip(text, variant="neutral"):
    label = _label(text)
    if hasattr(label, "setProperty"):
        label.setProperty("statusChip", True)
        label.setProperty("statusVariant", variant)
    if hasattr(label, "setWordWrap"):
        label.setWordWrap(True)
    if hasattr(label, "setSizePolicy"):
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
    if widget is None or not isinstance(widget, QWidget):
        return
    widget.setProperty("statusVariant", variant)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
