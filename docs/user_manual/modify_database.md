# Modify Database

## What this tool changes

Use **Modify database** when you want to edit stored text values that are already inside a Metroliza **database file**.

This tool is for cleanup and normalization of saved values such as:

- **REFERENCE**,
- **SAMPLE NUMBER**, and
- **HEADER**.

These edits change the stored values in the database itself. They are not temporary display-only changes.

## Before you start

You must select a **database file** before you can apply changes.

If the dialog was opened from the main window with a database already selected, it may already be filled in. If not, use **Select DB file**.

## Table-by-table explanation

The dialog shows three editable tables side by side.

### REFERENCE

This table shows the distinct **REFERENCE** values stored in the database.

Use it when reference names need to be corrected or standardized.

### SAMPLE NUMBER

This table shows the distinct **SAMPLE NUMBER** values stored in the database.

Use it when part or sample identifiers need cleanup.

### HEADER

This table shows the distinct **HEADER** values stored in the database.

Use it when measurement headers need to be renamed or standardized.

## How editing works

Values are edited **in place**.

That means you click directly in a table cell and change the text there. You do not open a separate editor for normal one-by-one edits.

The tool supports row selection in all three tables.

## How to rename one value

1. Open **Modify database**.
2. Select the correct **database file** if needed.
3. Find the value you want to change in the correct table.
4. Edit the cell directly.
5. Repeat for any other values.
6. Click **Apply changes**.
7. Review the confirmation message.
8. Confirm to write the changes to the database.

## How to rename many values at once

This dialog also supports bulk renaming.

### Multi-selection

You can select multiple rows in a table.

Useful selection patterns include:

- selecting multiple separate rows, and
- using **Shift** to select a range.

### Bulk rename with Enter / Return

If you have multiple rows selected in one table:

1. Select the rows you want to rename.
2. Press **Enter** or **Return**.
3. A rename prompt appears.
4. Type the new value.
5. Confirm.

The selected rows in that table are updated to the same new value.

This is useful when several old labels should all become one standardized label.

## Applying changes safely

### Apply changes

**Apply changes** does not write each edit immediately as you type.

Instead, it:

1. collects the changes you made across all three tables,
2. shows a confirmation dialog listing the pending modifications, and
3. writes the changes in one batch if you confirm.

This makes it easier to review the full set of edits before saving them.

### Cancel

**Cancel** closes the dialog without applying the pending changes from the current session.

If you have typed edits but have not clicked **Apply changes**, those edits are not written to the database.

## Notes and cautions

### This updates stored values in the database

Be careful with broad renames. Once applied, these changes affect the stored data that later exports will use.

### Use this for cleanup, not for temporary filtering

If you only want to narrow what appears in one export, use [Export filtering](export_filtering.md) instead.

### This tool is different from Characteristic Name Matching

Use **Modify database** to directly rename stored values.

Use [Characteristic Name Matching](characteristic_name_matching.md) when you want the app to treat different characteristic names as the same characteristic during analysis/export without documenting this as a separate cleanup workflow.

### Do not rely on hidden controls

The dialog contains an internal **Undo** button in code, but it is not part of the active visible layout. Treat **Apply changes** and **Cancel** as the real user actions available in this tool.
