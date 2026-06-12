# Main Window

## What this window is

The main window is the launcher for the main Metroliza tools.

From here you can open:

- Parsing,
- Modify Database,
- Export,
- Characteristic Name Matching,
- Industrial data source setup, sync, and cached Oznak link refresh.
- Parser profile handoff for new supplier report templates.

It also gives you quick access to the **Tools** and **Help** menus from the menu bar.

The main window shows the current source, current database, and a **Next step** status
row. That row changes as you select reports or a database, so a new user can tell whether
to parse, select/create a database, clean existing data, or export.

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

Opens the compact [Industrial Data](industrial_data.md) launcher. It keeps cache storage
and production database access separate:

- **Active local cache**: a temporary SQLite cache, an opened Metroliza report database,
  or a persistent industrial cache database. This is where fetched production rows are
  stored.
- **Production line database**: an existing MySQL/MSSQL source that Oznak reads from. It belongs to the production line and can contain sensor/process rows for many years of assemblies.

Use this when you want to fetch assembly-process data from Oznak-supported production
line databases, then filter, group, export, or dashboard those rows in CSV Summary.
Choose an opened Metroliza report database only when you also need report-to-production
links or industrial context in the normal Metroliza export.

The launcher shows a simple progress strip:

```text
Source -> Access -> Cache -> CSV Summary
```

Use it as the non-technical path through the module:

1. configure or select a production source,
2. check production database access,
3. fetch rows into the active local industrial cache, and
4. open cached rows in CSV Summary.

The launcher also shows the last sync/cache outcome, including the source, status,
row count, timestamp, and a redacted warning/error detail when one exists.

The launcher opens separate workflows:

- **Temp**, **Open...**, and **Create...** choose where fetched rows are cached: a
  session temporary cache, an existing Metroliza report database, or a persistent
  industrial cache database.
- **Production sources...** edits non-secret production line connection setup such as database type, host, database name, table/view, columns, record key, and timestamp column. This stays available even before a Metroliza report database is selected.
- **Fetch to cache...** asks for the production database username/password for the current session, checks production database access with a one-row read that saves nothing, and can fetch rows by guided filters, row limit, explicit fetch-all confirmation, or a reviewed SQL query into the active local industrial cache.
- **Fetch to CSV Summary** in the fetch dialog runs the same fetch, stores the rows in the active local cache, and then opens them in CSV Summary for filtering, grouping, dashboards, and optional workbook output.
- **Production links...** lets you manually link a Metroliza report to a cached production row when both systems use different reference values.
- **Export workbook...** creates a workbook from cached industrial rows in the active local industrial cache.
- **CSV Summary...** opens cached production rows in the CSV Summary workflow without
  requiring CMM measurements. Use the CSV Summary filters, grouping, dashboards, workbook,
  and export options; the loaded table includes a **source** column for the configured
  production database that produced each row.
- **Refresh links** refreshes local report-to-process links before the main Metroliza export.
- **Diagnostics...** contains maintenance actions such as **Initialize cache**. Normal
  users usually do not need this button; Metroliza prompts for cache initialization when
  it is required.

There are two ways to configure production line databases:

- Edit the YAML config file directly. By default, Metroliza uses `~/.metroliza/industrial_sources.yaml` with the same top-level `databases:` format as Oznak.
- Use **Production sources...**. The dialog reads and writes that config file, and when a Metroliza report database is selected it also synchronizes the non-secret source profiles into the local cache tables.

Each production source can disable server-side `ORDER BY` for limited SQL reads. Leave it enabled for deterministic rows; turn it off when a low-memory SQL Server cannot run the sort.

Metroliza stores fetched rows and sync diagnostics in the active local industrial cache.
Report-to-production links are stored only when that cache is an opened Metroliza report
database. Metroliza does not store the production database username or password in the
report database, industrial cache database, or config file.

If you check **Remember on this computer** in the fetch/access dialog, Metroliza saves
the production database username/password only after the access check or fetch succeeds
or completes with warnings. The dialog shows where remembered credentials are stored and
includes **Forget saved credentials** for the selected source.

Industrial export from cached data does not connect directly to the production line database. Live production database access happens only when the user explicitly runs **Check access** or **Fetch to cache** in the fetch dialog opened from **Fetch to cache...**.

**Check access** reads up to one production row to verify credentials, table, columns, and query access. It does not save rows into the Metroliza cache.

**Fetch to cache** can fetch by guided reference/source-column filters, by a row limit, by a reviewed SQL query, or by explicit fetch-all confirmation. Fetch-all shows a warning first because a production source may contain a large historical table.

Use **Edit filters...** in the fetch dialog to paste reference/ID values quickly as a comma-separated, semicolon-separated, space-separated, tab-separated, or line-separated list. You can also add simple source-column filters such as station, status, work order, or date. If no guided filter is set, **Fetch to cache** uses the configured row limit by default.

Use the **SQL query** tab only when guided filters are not enough or when IT/MES support gives you a reviewed read-only query. **Preview SQL** reads a small sample first; the default preview is `5` rows. Use **Open recipe...** and **Save recipe...** for reusable SQL queries such as a shift, station, work order, or date range.

If the Metroliza report reference and production reference are different, use **Production links...** after sync. Select one Metroliza report, select one cached production row, then click **Link selected**. Manual links take priority over automatic exact-reference links during export.

Use **CSV Summary...** when you need production-line grouping fields such as station, line, work order, batch/lot, operator, process status, or source. It opens all cached rows or the selected cached source in CSV Summary, where every fetched source column can be used for filtering and grouping.

### Tools > Parser profiles...

Opens the [Parser Profiles](parser_profiles.md) handoff dialog.

Use this when a new supplier report template needs parser support. The dialog shows the local profile store status and can create a local handoff folder with:

- a `profile.yaml` template,
- a `samples/` folder,
- an `expected_results.csv` file for every parsed row checked by hand,
- an `llm_handoff.md` note for an approved external LLM or human review workflow,
- `contracts/`, compact contract snippets, microtask prompts, a manifest, and a privacy-redaction checklist.

Metroliza does not call an LLM from this dialog. It only prepares local files. After creating a folder, use **Open Folder** or **Copy Path** to get to the hidden profile workspace. Use **Check Package**, **Validate**, **Diagnose**, and **Repair Prompt** before **Install**. A parser profile is not active until an operator validates and approves it.

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
- Use **Tools > Parser profiles...** when a supplier sends a report layout that Metroliza does not recognize yet.
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

### A supplier sent a report layout Metroliza does not recognize

Use:

1. [Parser Profiles](parser_profiles.md)
2. Create a handoff folder.
3. Add sample reports and checked expected values.
4. Send the handoff folder through the approved review process.

## Common confusion points

### Some dialogs are modal and some are not

Metroliza uses both modal and modeless dialogs.

- **Modal dialogs** stay in front and block other app interaction until you close them. Examples include **About**, **Release notes**, **CSV Summary**, and **Characteristic Name Matching**.
- **Modeless major workflow windows** such as **Parsing** and **Export** can be opened from the launcher window and then used as their own working dialog.

In practice, this means some windows behave like a temporary popup, while others behave more like a separate workspace. **Modify Database** is opened as a focused editing dialog so you finish or cancel that cleanup before returning to other workflows.

### Opening one major workflow can close another one

The app tries to keep only one major database workflow open at a time.

For example:

- opening **Parsing** closes an open **Export** or **Modify Database** window,
- opening **Modify Database** closes an open **Parsing** or **Export** window,
- opening **Export** closes an open **Parsing** or **Modify Database** window.

This is normal behavior. It helps avoid working in two conflicting major workflows at once.

### The launcher remembers some recent context

When you choose a source folder or database file in one workflow, that file path can carry into another workflow. This saves clicks, but you should still check that the selected path is the one you want before starting work.
