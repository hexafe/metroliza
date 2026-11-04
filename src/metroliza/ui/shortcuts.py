"""Window command inventory; shared by menus, tooltips and manual checks."""

MAIN_SHORTCUTS = {
    "open_database": ("Ctrl+O", "Open database…"),
    "review_reports": ("Ctrl+R", "Review reports"),
    "import_reports": ("Ctrl+I", "Import selected reports"),
    "export_workbook": ("Ctrl+E", "Export Workbook"),
    "manual": ("F1", "Manual of the active window"),
}
PAGE_SHORTCUTS = tuple(f"Ctrl+{index}" for index in range(1, 10))
DIALOG_SHORTCUTS = {"focus_search": ("Ctrl+F", "Focus and select the current search field")}
DIALOG_MNEMONICS = {
    "export": {
        "select_db_button": "b", "select_excel_button": "r", "filter_button": "e",
        "clear_filter_button": "f", "group_button": "d", "clear_group_button": "g",
        "export_button": "x", "close_button": "c", "dashboard_visuals_button": "n",
        "advanced_toggle_button": "a",
    },
    "filter": {
        "apply_button": "a", "reset_button": "s", "cancel_button": "c",
        "has_nok_button": "n", "select_today_button": "t", "select_beginning_button": "b",
    },
    "grouping": {
        "create_group_button": "a", "rename_group_button": "r", "remove_from_group_button": "m",
        "delete_group_button": "d", "use_grouping_button": "u",
        "dont_use_grouping_button": "s", "cancel_button": "c",
    },
}


def plain_text(text):
    """Remove mnemonic markers from a caption (preserve escaped ampersands)."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def set_mnemonic(button, letter):
    """Keep the visible caption and accessible name when adding an Alt key."""
    text = plain_text(button.text())
    index = text.lower().index(letter.lower())
    button.setText(text[:index] + "&" + text[index:])
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


def apply_dialog_mnemonics(window, kind):
    """Apply the window's inventory after captions/accessibility are configured."""
    for name, letter in DIALOG_MNEMONICS[kind].items():
        button = getattr(window, name)
        set_mnemonic(button, letter)
        _append_shortcut_tooltip(button, button.shortcut().toString())


def _append_shortcut_tooltip(widget, sequence):
    suffix = f" ({sequence})"
    if not widget.toolTip().endswith(suffix):
        widget.setToolTip((widget.toolTip() or plain_text(widget.text())) + suffix)


def bind_search_shortcut(window, pairs):
    """One window action selects the search belonging to the focused pane.

    Pairs contain a search edit and its associated view. With focus elsewhere,
    use the first enabled search on the visible tab. Disabled/hidden searches
    are never focused. Existing search/apply signals and local keys are untouched.
    """
    from PyQt6.QtGui import QAction

    sequence, label = DIALOG_SHORTCUTS["focus_search"]
    pairs = tuple(pairs)

    def focus_search():
        focused = window.focusWidget()
        available = [(edit, view) for edit, view in pairs
                     if edit.isVisibleTo(window) and edit.isEnabled()]
        if not available:
            return
        target = next((edit for edit, view in available
                       if focused is edit or focused is view or view.isAncestorOf(focused)),
                      available[0][0])
        target.setFocus()
        target.selectAll()

    action = QAction(label, window)
    bind_shortcut(action, sequence)
    action.triggered.connect(focus_search)
    window.addAction(action)
    for edit, _view in pairs:
        _append_shortcut_tooltip(edit, sequence)
    return action
