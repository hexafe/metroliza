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


# Supplemental commands only: accepted primary bindings stay at their existing owners.
# Each entry targets the actual guarded button, not a parallel command/readiness state.
PRIMARY_BUTTON_COMMANDS = {
    "csv_summary": (
        ("browse_input_button", "Ctrl+D"), ("load_metrics_button", "Ctrl+R"),
        ("dashboard_button", "Ctrl+Shift+D"), ("workbook_button", "Ctrl+Shift+E"),
        ("filters_button", "Ctrl+Shift+F"), ("edit_groups_button", "Ctrl+G"),
        ("edit_limits_button", "Ctrl+Shift+G"), ("clear_filter_button", "Ctrl+Shift+R"),
        ("clear_groups_button", "Ctrl+Shift+Q"),
    ),
    "export": (
        ("select_db_button", "Ctrl+D"), ("select_excel_button", "Ctrl+Shift+E"),
        ("group_button", "Ctrl+G"), ("clear_filter_button", "Ctrl+Shift+R"),
        ("clear_group_button", "Ctrl+Shift+Q"),
    ),
    "csv_grouping": (
        ("assign_filtered_rows_button", "Ctrl+R"), ("clear_selection_button", "Ctrl+Q"),
        ("create_group_button", "Ctrl+G"), ("rename_group_button", "Ctrl+Shift+G"),
        ("delete_group_button", "Ctrl+Shift+D"), ("use_grouping_button", "Ctrl+S"),
        ("dont_use_grouping_button", "Ctrl+Shift+R"), ("cancel_button", "Ctrl+W"),
    ),
    "grouping": (
        ("create_group_button", "Ctrl+G"), ("rename_group_button", "Ctrl+Shift+G"),
        ("delete_group_button", "Ctrl+Shift+D"), ("remove_from_group_button", "Ctrl+D"),
        ("use_grouping_button", "Ctrl+S"), ("dont_use_grouping_button", "Ctrl+Shift+R"),
        ("cancel_button", "Ctrl+W"),
    ),
    "mapping": (
        ("select_db_button", "Ctrl+D"), ("add_from_selected_button", "Ctrl+R"),
        ("delete_button", "Ctrl+Shift+D"), ("import_button", "Ctrl+Shift+R"),
        ("export_button", "Ctrl+S"),
    ),
    "metrics": (("apply_button", "Ctrl+S"), ("cancel_button", "Ctrl+W")),
    "limits": (("apply_button", "Ctrl+S"), ("cancel_button", "Ctrl+W")),
    "industrial_sources": (
        ("new_source_button", "Ctrl+D"), ("browse_config_button", "Ctrl+Shift+D"),
        ("reload_config_button", "Ctrl+R"), ("save_source_button", "Ctrl+S"),
        ("close_button", "Ctrl+W"),
    ),
    "industrial_sql": (
        ("open_button", "Ctrl+D"), ("save_button", "Ctrl+S"),
        ("preview_button", "Ctrl+R"), ("close_button", "Ctrl+W"),
    ),
    "industrial_filter": (
        ("add_filter_button", "Ctrl+E"), ("apply_button", "Ctrl+S"),
        ("clear_button", "Ctrl+Shift+R"), ("cancel_button", "Ctrl+W"),
    ),
    "industrial_grouping": (
        ("apply_button", "Ctrl+S"), ("clear_button", "Ctrl+Shift+R"),
        ("cancel_button", "Ctrl+W"),
    ),
    "industrial_export": (
        ("output_button", "Ctrl+Shift+E"), ("edit_filter_button", "Ctrl+F"),
        ("edit_grouping_button", "Ctrl+G"), ("clear_filter_button", "Ctrl+Shift+R"),
        ("clear_grouping_button", "Ctrl+Shift+Q"), ("start_button", "Ctrl+S"),
        ("close_button", "Ctrl+W"),
    ),
}


def _active_command_window(window):
    from PyQt6.QtWidgets import QApplication

    return (window.isVisible() and window.isActiveWindow()
            and QApplication.activeModalWidget() in (None, window))


def _invoke_command_button(window, button):
    if (_active_command_window(window) and button.isVisibleTo(window) and button.isEnabled()):
        button.setFocus()  # Commit an active table delegate just as a mouse click does.
        button.click()


def refresh_button_command_hints(window, context):
    """Keep accepted dynamic captions/tooltips while restoring their primary hint."""
    installed = getattr(window, "_catalog_button_actions", {})
    for attribute, sequence in PRIMARY_BUTTON_COMMANDS[context]:
        if (context, attribute) not in installed:
            continue
        button = getattr(window, attribute)
        visible_shortcut(button, sequence)
        legacy = button.shortcut().toString()
        if legacy:
            _append_shortcut_tooltip(button, f"{sequence}; {legacy} (secondary)")


def install_button_commands(window, context):
    """Install once per window; controllers retain all availability/admission decisions."""
    from PyQt6.QtGui import QAction

    installed = getattr(window, "_catalog_button_actions", None)
    if installed is None:
        installed = window._catalog_button_actions = {}
    for attribute, sequence in PRIMARY_BUTTON_COMMANDS[context]:
        key = (context, attribute)
        if key in installed:
            continue
        button = getattr(window, attribute)
        action = QAction(plain_text(button.text()), window)
        bind_shortcut(action, sequence)
        action.setAutoRepeat(False)
        action.triggered.connect(lambda checked=False, target=button: _invoke_command_button(window, target))
        window.addAction(action)
        installed[key] = action
    refresh_button_command_hints(window, context)
    return tuple(installed[(context, attribute)] for attribute, _sequence in PRIMARY_BUTTON_COMMANDS[context])
