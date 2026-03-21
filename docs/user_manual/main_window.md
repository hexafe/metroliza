# Main Window

## What this window is

The main window is the launcher for the main Metroliza tools.

From here you can open:

- Parsing,
- Modify Database,
- Export,
- CSV Summary, and
- Characteristic Name Matching.

It also gives you quick access to **About** and **Release notes** from the menu bar.

## What each button does

### Launch Parsing

Opens the [Parsing](parsing.md) dialog.

Use this when you want to read report files and save their measurements into a **database file**. This is usually the first step for the main database-based workflow.

### Launch Modify Database

Opens the [Modify Database](modify_database.md) dialog.

Use this when you want to rename stored values already saved in the database, such as:

- **REFERENCE** values,
- **SAMPLE NUMBER** values, or
- **HEADER** values.

This is optional. Use it when the database needs cleanup before export.

### Launch Export

Opens the [Export overview](export_overview.md) dialog.

Use this when you already have a database file and want to create an **Excel file**. This is the main reporting/export workflow.

### CSV Summary

Opens the [CSV Summary](csv_summary.md) workflow.

This is a separate mini-app inside Metroliza. It works directly from a CSV file and does **not** require the normal parse-to-database workflow.

### Match Characteristic Names

Opens the [Characteristic Name Matching](characteristic_name_matching.md) dialog.

Use this when the same characteristic appears under different names in different reports or references and you want export/grouped analysis to treat them as the same characteristic.

## Menu actions

### About

Opens the [Help, startup, and license](help_startup_and_license.md) reference page’s **About** dialog.

This dialog shows version information and project attribution.

### Release notes

Opens the [Help, startup, and license](help_startup_and_license.md) reference page’s **Release notes** dialog.

Use it when you want to see what changed in the current release.

## Recommended workflow

For a new user, the simplest workflow is:

1. Open **Launch Parsing** and create or update a **database file**.
2. If needed, use **Launch Modify Database** to clean up stored values.
3. If needed, use **Match Characteristic Names** so equivalent characteristics use a common name.
4. Open **Launch Export** and create the final **Excel file**.

A practical version is:

- **Parse data** first.
- **Optionally modify the database**.
- **Optionally match characteristic names**.
- **Export**.

## Typical user journeys

### I just received new measurement reports

Use:

1. [Parsing](parsing.md)
2. [Export overview](export_overview.md)

### My references or headers are inconsistent

Use:

1. [Parsing](parsing.md)
2. [Modify Database](modify_database.md)
3. [Export overview](export_overview.md)

### The same characteristic has different names in different reports

Use:

1. [Parsing](parsing.md)
2. [Characteristic Name Matching](characteristic_name_matching.md)
3. [Export overview](export_overview.md)

### I only have a CSV and want a quick Excel summary

Use:

1. [CSV Summary](csv_summary.md)

## Common confusion points

### Some dialogs are modal and some are not

Metroliza uses both modal and modeless dialogs.

- **Modal dialogs** stay in front and block other app interaction until you close them. Examples include **About**, **Release notes**, **CSV Summary**, and **Characteristic Name Matching**.
- **Modeless major workflow windows** such as **Parsing**, **Modify Database**, and **Export** can be opened from the launcher window and then used as their own working dialog.

In practice, this means some windows behave like a temporary popup, while others behave more like a separate workspace.

### Opening one major workflow can close another one

The app tries to keep only one major database workflow open at a time.

For example:

- opening **Parsing** closes an open **Export** or **Modify Database** window,
- opening **Modify Database** closes an open **Parsing** or **Export** window,
- opening **Export** closes an open **Parsing** or **Modify Database** window.

This is normal behavior. It helps avoid working in two conflicting major workflows at once.

### The launcher remembers some recent context

When you choose a source folder or database file in one workflow, that file path can carry into another workflow. This saves clicks, but you should still check that the selected path is the one you want before starting work.
