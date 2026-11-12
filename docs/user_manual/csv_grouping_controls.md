# CSV / Excel grouping controls

In **Edit groups**, use **Add column (Ctrl+E)** under Available columns and
**Remove column (Ctrl+Shift+E)** under Selected columns. Each command acts on the current
visible item in its own list. A search with no results disables that command.
Double-clicking remains available. Removing a selector column preserves drafted
row assignments.

Select a custom group, then one or more members, and use **Remove from group
(Ctrl+D)**. Those records return to the default group; their source measurements
remain intact. **Delete group** returns the whole group's members to the default
group. **Clear selection** clears the matching-row selection used for assignment.
Delete/Backspace remain additional member-removal keys when the member list has
focus. Text editing retains its standard Ctrl shortcuts.

Member labels use the **Part / ID column** and **Timestamp column** chosen in CSV
Summary, display missing values explicitly, and always include a stable Row ID
suffix to distinguish repeated labels. The preview shows at most the first 1000
members with a total-count notice; selector values have separate paging controls.
Changing the selector search does not change the identity of existing members.

**Use grouping** applies the draft. **Cancel** discards uncommitted changes after
confirmation. **Reset changes** restores the state from opening the dialog after
confirmation; it does not delete source measurements.

With focus directly in **Available columns**, **E** adds the current column.
With focus directly in **Selected columns**, **R** removes the current column.
With focus directly in the member list, **R** removes selected members. These
explicit command lists replace E/R type-ahead only in those contexts; search and
text fields keep normal typing. Repeated key events do not repeat these commands.
