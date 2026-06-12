# Modify Database

## What this tool changes

Use **Modify database** when you want to edit stored metadata values that are already inside a Metroliza **database file**.

This tool supports two kinds of cleanup:

- normalizing repeated text values across the database, and
- correcting individual report or measurement records.

Use it for saved values such as:

- **REFERENCE**,
- **SAMPLE NUMBER**, and
- **HEADER**,
- report date/time,
- part name and revision,
- operator and comment fields,
- measurement characteristics, and
- measurement values/tolerances/status.

These edits change the stored values in the database itself. They are not temporary display-only changes.

## Before you start

You must select a **database file** before you can apply changes.

If the dialog was opened from the main window with a database already selected, it may already be filled in. If not, use **Select DB file**.

Choose the `.db` file that was created or updated by [Parsing](parsing.md). If you select the wrong file, the tables may be empty or may show values from another job.

## Tabs

The dialog has three tabs.

### Normalize values

This tab keeps the original global cleanup workflow.

It is split into three field tabs:

#### REFERENCE

This table shows the distinct **REFERENCE** values stored in the database.

Use it when reference names need to be corrected or standardized.

#### SAMPLE NUMBER

This table shows the distinct **SAMPLE NUMBER** values stored in the database.

Use it when part or sample identifiers need cleanup.

#### HEADER

This table shows the distinct **HEADER** values stored in the database.

Use it when measurement headers need to be renamed or standardized.

Each field tab has:

- a search box,
- **Original value**,
- **New value**, and
- **Occurrences**.

Edit **New value**. **Original value** stays read-only, and **Occurrences** shows how many rows currently use that value.

Because this tab edits distinct values, a change applies everywhere that old value appears.

### Report records

This tab edits one report row at a time.

Editable fields include:

- **REFERENCE**,
- **DATE**,
- **TIME**,
- **PART_NAME**,
- **REVISION**,
- **SAMPLE_NUMBER**,
- **OPERATOR_NAME**, and
- **COMMENT**.

Read-only context columns such as **REPORT_ID**, **FILENAME**, and **TEMPLATE_VARIANT** help identify the row.

Changing report identity fields such as reference, date, time, part name, revision, or sample number also refreshes the report identity hash used for duplicate detection.

### Measurement rows

This tab edits one measurement row at a time.

Editable fields include:

- **HEADER**,
- **SECTION_NAME**,
- **FEATURE_LABEL**,
- **CHARACTERISTIC_NAME**,
- **CHARACTERISTIC_FAMILY**,
- **DESCRIPTION**,
- **AX**,
- **NOM**,
- **+TOL**,
- **-TOL**,
- **BONUS**,
- **MEAS**,
- **DEV**,
- **OUTTOL**, and
- **STATUS_CODE**.

Read-only **MEASUREMENT_ID** and **REPORT_ID** columns identify the measurement and its report.

Changing **OUTTOL** or **STATUS_CODE** refreshes the stored NOK/status summary for the owning report.

The report and measurement tabs also include a search field above the table.

## How editing works

Values are edited **in place**.

That means you click directly in a table cell and change the text there. You do not open a separate editor for normal one-by-one edits.

The tool supports row selection in the visible table.

### Empty cells and numeric fields

In **Report records** and **Measurement rows**, clearing an editable cell saves that value as empty/`NULL`.

In **Normalize values**, an empty **New value** means "rename this stored text to blank" for every matching occurrence. Use that only when you really want the stored text cleared everywhere.

For numeric measurement fields such as **NOM**, **+TOL**, **-TOL**, **BONUS**, **MEAS**, **DEV**, and **OUTTOL**, enter plain numbers. A blank numeric cell clears the value. Do not type units, comments, commas as thousands separators, or words into numeric cells.

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

The selected rows in that normalization table are updated to the same new value.

This is useful when several old labels should all become one standardized label.

Bulk rename is intended for the **Normalize values** tab. Use direct cell edits for report and measurement record corrections.

## Applying changes safely

### Apply changes

**Apply changes** does not write each edit immediately as you type.

Instead, it:

1. collects the changes you made across the normalization and record tabs,
2. shows a confirmation dialog listing the pending modifications, and
3. writes the changes if you confirm.

This makes it easier to review the full set of edits before saving them.

### Cancel

**Cancel** closes the dialog without applying the pending changes from the current session.

If you have typed edits but have not clicked **Apply changes**, those edits are not written to the database.

## Recovery and validation

### I selected the wrong database

Click **Select DB file** and choose the correct `.db` file. Check that the values in the tables match the reports you meant to edit before applying changes.

If you already applied changes to the wrong database, close the dialog, reopen the correct database, and restore the wrong database from a backup or re-parse the original reports if needed.

### The database is invalid or cannot be read

Select the `.db` file created by Metroliza Parsing. Do not select an Excel workbook, CSV file, archive, report PDF, or unrelated SQLite file.

If the file should be a Metroliza database but still will not load, close the dialog and try opening the database from the main window workflow. If it still fails, keep the file unchanged and contact support with the error message.

### The tables are empty

Empty tables usually mean one of these:

- the selected database has no parsed reports yet,
- the search box is filtering all rows out,
- the selected file is not the database you intended to edit, or
- the selected database contains a schema Metroliza cannot use for these tables.

Clear the search box first. If the tables are still empty, choose the database created by Parsing or parse reports into a new `.db` file.

### Apply changes says there are no changes

This means Metroliza did not detect any edited cells.

Check that you changed an editable cell, not a read-only identifier column such as **REPORT_ID** or **MEASUREMENT_ID**. If you changed a value and then changed it back to the original text, there is nothing to save.

### Saving changes fails

Do not keep editing the same open dialog after a failed save. Note the error message, close the dialog, and reopen the database to check what was saved.

Common causes are a read-only database file, a database opened by another process, an invalid value such as an unsupported **STATUS_CODE**, or a file that is not a Metroliza report database.

## Notes and cautions

### This updates stored values in the database

Be careful with broad renames and record edits. Once applied, these changes affect the stored data that later exports, filtering, grouping, workbook output, and HTML dashboard output will use.

### Use this for cleanup, not for temporary filtering

If you only want to narrow what appears in one export, use [Export filtering](export_filtering.md) instead.

### This tool is different from Characteristic Name Matching

Use **Modify database** to directly rename stored values.

Use [Characteristic Name Matching](characteristic_name_matching.md) when you want the app to treat different characteristic names as the same characteristic during analysis/export without documenting this as a separate cleanup workflow.

### Do not rely on hidden controls

The dialog contains an internal **Undo** button in code, but it is not part of the active visible layout. Treat **Apply changes** and **Cancel** as the real user actions available in this tool.
