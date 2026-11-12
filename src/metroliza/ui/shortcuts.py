"""Window command inventory; shared by menus, tooltips and manual checks."""

MAIN_SHORTCUTS = {
    "open_database": ("Ctrl+O", "Open database…"),
    "report_database": ("Ctrl+D", "Select/create database in Reports; open database elsewhere"),
    "choose_source": ("Ctrl+Shift+D", "Choose Reports source…"),
    "cancel_reports": ("Ctrl+Shift+S", "Cancel report operation"),
    "review_reports": ("Ctrl+R", "Review reports"),
    "import_reports": ("Ctrl+S", "Import selected reports"),
    "export_workbook": ("Ctrl+E", "Export Workbook"),
    "manual": ("F1", "Manual of the active window"),
}
PAGE_SHORTCUTS = tuple(f"Ctrl+{index}" for index in range(1, 6))
WORKSPACE_SHORTCUTS = dict(zip(
    ("home", "reports", "csv_summary", "industrial_data", "realtime_monitor"), PAGE_SHORTCUTS,
)) | {"parser_profiles": "Ctrl+Shift+F", "tools": "Ctrl+Shift+T"}
LEGACY_MAIN_SHORTCUTS = {"import_reports": "Ctrl+I"}
DIALOG_SHORTCUTS = {"focus_search": ("Ctrl+F", "Focus and select the current search field")}
DIALOG_MNEMONICS = {
    "csv_filter": {
        "add_column_button": "d", "remove_column_button": "m", "clear_columns_button": "l",
        "clear_selection_button": "v", "clear_filter_button": "r", "cancel_button": "c",
        "apply_button": "a",
    },
    "csv_grouping": {
        "assign_filtered_rows_button": "f", "create_group_button": "a", "rename_group_button": "r",
        "delete_group_button": "d", "clear_selection_button": "l", "use_grouping_button": "u",
        "dont_use_grouping_button": "s", "cancel_button": "c",
    },
    "modify": {
        "select_db_button": "b", "apply_button": "a", "cancel_button": "c",
    },
    "csv_summary": {
        "browse_input_button": "b", "filters_button": "f", "clear_filter_button": "t",
        "load_metrics_button": "m", "choose_metrics_button": "o", "edit_limits_button": "l",
        "edit_groups_button": "e", "clear_groups_button": "g", "dashboard_button": "r",
        "workbook_button": "w", "close_button": "c", "start_button": "y",
        "advanced_toggle_button": "a",
    },
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
    _append_shortcut_tooltip(button, MAIN_SHORTCUTS[command][0])


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
    """Show the key in the tooltip; the base text is kept so dynamic captions stay current."""
    if not sequence:
        return
    current = widget.toolTip()
    previous = widget.property("metrolizaShortcutTooltipRendered")
    automatic = bool(widget.property("metrolizaShortcutTooltipAutomatic")) if current == previous else not current
    base = widget.property("metrolizaShortcutTooltipBase") if current == previous else current
    if automatic:
        base = ""
    if not base:
        if hasattr(widget, "placeholderText"):
            base = widget.placeholderText() or widget.accessibleName()
        else:
            base = plain_text(widget.text())
            hint = widget.property("metrolizaVisibleShortcut")
            if hint and base.endswith(f" [{hint}]"):
                base = base[:-(len(hint) + 3)]
    rendered = f"{base} ({sequence})" if base else sequence
    widget.setProperty("metrolizaShortcutTooltipAutomatic", automatic)
    widget.setProperty("metrolizaShortcutTooltipBase", base)
    widget.setProperty("metrolizaShortcutTooltipRendered", rendered)
    widget.setToolTip(rendered)


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


def visible_shortcut(button, sequence):
    """Append a persistent key hint while keeping dynamic captions and names clean."""
    previous = button.property("metrolizaVisibleShortcut")
    text = button.text()
    if previous and text.endswith(f" [{previous}]"):
        text = text[:-(len(previous) + 3)]
    button.setText(f"{text} [{sequence}]")
    button.setProperty("metrolizaVisibleShortcut", sequence)
    _append_shortcut_tooltip(button, sequence)
