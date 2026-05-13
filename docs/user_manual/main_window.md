# Main Window

## What this window is

The main window is the launcher for the main Metroliza tools.

From here you can open:

- Parsing,
- Modify Database,
- Export,
- Characteristic Name Matching,
- Industrial data source setup, sync, and cached Oznak link refresh.

It also gives you quick access to the **Tools** and **Help** menus from the menu bar.

## What each button does

### Parse Reports

Opens the [Parsing](parsing.md) dialog.

Use this when you want to read report files and save their measurements into a **database file**. This is usually the first step for the main database-based workflow.

### Modify Database

Opens the [Modify Database](modify_database.md) dialog.

Use this when you want to rename stored values already saved in the database, such as:

- **REFERENCE** values,
- **SAMPLE NUMBER** values, or
- **HEADER** values.

This is optional. Use it when the database needs cleanup before export.

### Export Workbook

Opens the [Export overview](export_overview.md) dialog.

Use this when you already have a database file and want to create an **Excel file**. This is the main reporting/export workflow.

### Tools > CSV Summary...

Opens the [CSV Summary](csv_summary.md) workflow from the **Tools** menu.

This works directly from a CSV or Excel file and does **not** require the normal
parse-to-database workflow. It can create dashboards, grouped statistics, and optional
Excel workbooks with separate sheets for selected parameters.

### Tools > Industrial data...

Opens the compact industrial data launcher. It keeps two database concepts separate:

- **Metroliza report database**: the SQLite file Metroliza creates from CMM/metrology reports. This stores report metadata, measurements, local industrial cache rows, sync diagnostics, and report-to-production links. Use **Select DB...** in the Industrial data window when the launcher was opened before a report database was selected in the main window.
- **Production line database**: an existing MySQL/MSSQL source that Oznak reads from. It belongs to the production line and can contain sensor/process rows for many years of assemblies.

Use this when you want to connect assembly-process data from Oznak-supported production line databases to the metrology reports already saved in Metroliza.

The launcher opens separate workflows:

- **Production sources...** edits non-secret production line connection setup such as database type, host, database name, table/view, columns, record key, and timestamp column. This stays available even before a Metroliza report database is selected.
- **Connect / check / sync...** asks for the production database username/password for the current session, lets you edit the reference/ID values to fetch, checks production database access with a one-row read that saves nothing, syncs selected rows into the local Metroliza cache, and can cancel a running sync.
- **Production links...** lets you manually link a Metroliza report to a cached production row when both systems use different reference values.
- **Export...** creates a cached industrial workbook with filter/grouping summaries and an explicit **Include plots** option.
- **Analyze...** creates dashboards, grouped statistics, time-bucket summaries, and optional
  workbooks from cached production rows without requiring CMM measurements. The analytics
  setup includes production filters, pasted-reference cohorts, grouping, time buckets, and
  chart selection.
- **Refresh links** refreshes local report-to-process links before the main Metroliza export.

There are two ways to configure production line databases:

- Edit the YAML config file directly. By default, Metroliza uses `~/.metroliza/industrial_sources.yaml` with the same top-level `databases:` format as Oznak.
- Use **Production sources...**. The dialog reads and writes that config file, and when a Metroliza report database is selected it also synchronizes the non-secret source profiles into the local cache tables.

Metroliza stores the source setup, cache rows, sync diagnostics, and links in the selected Metroliza report database. It does not store the production database username or password in the report database or config file.

Export never connects to the production line database directly. Live production database access happens only when the user explicitly runs **Check access** or **Sync now** in the sync dialog opened from **Connect / check / sync...**.

**Check access** reads up to one production row to verify credentials, table, columns, and query access. It does not save rows into the Metroliza cache.

**Sync now** is reference-scoped. It requires at least one reference before it fetches production-line rows, so Metroliza does not pull an entire historical source table.

Use **Edit references...** in the sync dialog to paste reference/ID values quickly as a comma-separated, semicolon-separated, space-separated, tab-separated, or line-separated list. During sync, Metroliza batches long reference lists and uses Oznak chunked fetching when the source profile has a record key/pagination column.

If the Metroliza report reference and production reference are different, use **Production links...** after sync. Select one Metroliza report, select one cached production row, then click **Link selected**. Manual links take priority over automatic exact-reference links during export.

Use **Edit...** next to grouping in the industrial export dialog to choose production-line grouping fields such as station, line, work order, batch/lot, operator, or process status. The export dialog uses those fields for the summary sheet and optional plots.

### Match Characteristic Names

Opens the [Characteristic Name Matching](characteristic_name_matching.md) dialog.

Use this when the same characteristic appears under different names in different reports or references and you want export/grouped analysis to treat them as the same characteristic.

## Menu actions

### Tools > Enrich existing database metadata...

Runs OCR metadata enrichment on reports already saved in the selected database.

Use this as a maintenance action when an existing database was imported with fast metadata and you want to fill in richer report metadata later.

While enrichment runs, the main window shows progress and a **Cancel** button. If no database is selected, the main window shows a message asking you to select a database first.

### Help > About

Opens the [Help, startup, and license](help_startup_and_license.md) reference page’s **About** dialog.

This dialog shows version information and project attribution.

### Help > Release notes

Opens the [Help, startup, and license](help_startup_and_license.md) reference page’s **Release notes** dialog.

Use it when you want to see what changed in the current release.

## Recommended workflow

For a new user, the simplest workflow is:

1. Open **Parse Reports** and create or update a **database file**.
2. If needed, use **Modify Database** to clean up stored values.
3. If needed, use **Match Characteristic Names** so equivalent characteristics use a common name.
4. If needed, open **Tools > Industrial data...**, test/sync industrial data, and refresh links.
5. Open **Export Workbook** and create the final **Excel file**.

A practical version is:

- **Parse data** first.
- **Optionally modify the database**.
- **Optionally match characteristic names**.
- **Optionally sync industrial data**.
- **Export**.
- Use **Tools** for utility workflows such as **CSV Summary**, **Industrial data...**, or **Enrich existing database metadata...**.
- Use **Help** for manuals, **Release notes**, and **About**.

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
