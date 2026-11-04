"""Window command inventory; shared by menus, tooltips and manual checks."""

MAIN_SHORTCUTS = {
    "open_database": ("Ctrl+O", "Open database…"),
    "review_reports": ("Ctrl+R", "Review reports"),
    "import_reports": ("Ctrl+I", "Import selected reports"),
    "export_workbook": ("Ctrl+E", "Export Workbook"),
    "manual": ("F1", "Manual of the active window"),
}
PAGE_SHORTCUTS = tuple(f"Ctrl+{index}" for index in range(1, 10))


def plain_text(text):
    """Remove mnemonic markers from a caption (preserve escaped ampersands)."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def set_mnemonic(button, letter):
    """Keep the visible caption and accessible name when adding an Alt key."""
    text = plain_text(button.text())
    index = text.lower().find(letter.lower())
    escaped = text.replace("&", "&&")
    if index < 0:
        # Caption without that letter (e.g. a changed state): no mnemonic, never raise in a slot.
        button.setText(escaped)
    else:
        prefix = text[:index].replace("&", "&&")
        button.setText(prefix + "&" + escaped[len(prefix):])
    if not button.accessibleName():
        button.setAccessibleName(text)


def shortcut_tooltip(button, command):
    sequence = MAIN_SHORTCUTS[command][0]
    suffix = f" ({sequence})"
    if not button.toolTip().endswith(suffix):
        button.setToolTip(button.toolTip() + suffix)


def bind_shortcut(action, sequence):
    """Explicit window scope prevents commands crossing a modal boundary."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeySequence

    action.setShortcut(QKeySequence(sequence))
    action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
