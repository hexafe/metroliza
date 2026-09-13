# Main Window

## What this window is

The main window groups work into **Home**, **Reports**, the domain workspaces and
**Tools**. Use the sidebar in a large window or the workspace selector in a compact window.

**Home** shows the current source and database, the active report task or last result,
and one recommended next action. That action opens the same Reports workspace and focuses
the next available control. It does not start an import without a reviewed selection.

**Reports** contains the [report planner](parsing.md): choose the source and database,
review the files, select ready reports and import exactly that selection. Changing pages
preserves the review, filters, selection, task and outcome. Source/database changes take
effect only when accepted; they clear the old review. Changes are rejected while a report
operation is active. Database workflow actions wait for the report operation to finish, while
navigation and cancellation remain available. Open Export and Database editor windows keep
their current work; changing their database also waits until Reports is idle. The editor
opened from Reports allows navigation back to the main window. Finish or close a same-database editing/export
or industrial window before starting another report operation; its work is preserved.
Closing the main window requests cancellation and waits for the worker.

**CSV Analytics**, **Industrial Data**, **Realtime Monitor** and **Parser Profiles** keep
their own primary pages. Their **Tools** menu shortcuts navigate to those same pages;
the page action opens the corresponding workflow. **Tools** also offers metadata enrichment
for the current database. **Help** provides manuals, release notes and support actions.

## Report preparation and output

The actions below the Reports planner open the existing database workflows.

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

Selects **CSV Analytics**; choose **Open CSV Summary** to open the [CSV Summary](csv_summary.md) workflow.

This works directly from a CSV or Excel file and does **not** require the normal
parse-to-database workflow. It can create dashboards, grouped statistics, and optional
Excel workbooks with separate sheets for selected parameters.

### Tools > Industrial data...

Selects **Industrial Data**; choose **Open Industrial Data** to open the compact [Industrial Data](industrial_data.md) launcher. It keeps cache storage
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

### Tools > Real-time Industrial Monitoring...

Selects **Realtime Monitor**; **Open Realtime Monitor** opens the read-only
[Realtime Industrial Monitoring](realtime_industrial_monitoring.md) dashboard from the local realtime sample/event store. Selecting a Metroliza report
database first is optional. If no database is selected, Metroliza creates a temporary
session SQLite store so the dashboard and future monitoring setup can open without
changing a report database. Select or create a persistent database only when you want
the realtime samples and anomaly events to remain available after the session.

Use the **SQL query** tab only when guided filters are not enough or when IT/MES support gives you a reviewed read-only query. **Preview SQL** reads a small sample first; the default preview is `5` rows. Use **Open recipe...** and **Save recipe...** for reusable SQL queries such as a shift, station, work order, or date range.

If the Metroliza report reference and production reference are different, use **Production links...** after sync. Select one Metroliza report, select one cached production row, then click **Link selected**. Manual links take priority over automatic exact-reference links during export.

Use **CSV Summary...** when you need production-line grouping fields such as station, line, work order, batch/lot, operator, process status, or source. It opens all cached rows or the selected cached source in CSV Summary, where every fetched source column can be used for filtering and grouping.

### Tools > Real-time Industrial Monitoring...

Selects **Realtime Monitor**; choose **Open Realtime Monitor** to open the
[Realtime Industrial Monitoring](realtime_industrial_monitoring.md) dialog.

Use this when production sources are already configured and you want Metroliza to poll
one or more enabled sources on a timer, record samples/events, and refresh a local
operator dashboard. For normal monitoring, select a persistent database before opening
the monitor so saved source configs and events remain available after the session.

### Tools > Parser profiles...

Selects **Parser Profiles**; choose **Manage Parser Profiles** to open the
[Parser Profiles](parser_profiles.md) handoff dialog.

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

### Help > Diagnostic incidents…

Opens the local diagnostic viewer when this build includes it. The action is disabled
when the feature is unavailable. A problem loading an installed viewer produces an error
message. Diagnostic preview and selected export are provided by that separate viewer.

### Help > About

Opens the [Help, startup, and license](help_startup_and_license.md) reference page’s **About** dialog.

This dialog shows version information and project attribution.

### Help > Release notes

Opens the [Help, startup, and license](help_startup_and_license.md) reference page’s **Release notes** dialog.

Use it when you want to see what changed in the current release.

## Recommended workflow

For a new user, the simplest workflow is:

1. Open **Reports**, review the files and import the selected reports into a **database file**.
2. If needed, use **Modify Database** to clean up stored values.
3. If needed, use **Match Characteristic Names** so equivalent characteristics use a common name.
4. If needed, open **Tools > Industrial data...**, test/sync industrial data, and refresh links.
5. If needed, open **Tools > Real-time Industrial Monitoring...** after production sources are configured.
6. Open **Export Workbook** and create the final **Excel file**.

A practical version is:

- **Parse data** first.
- **Optionally modify the database**.
- **Optionally match characteristic names**.
- **Optionally sync industrial data**.
- **Optionally monitor enabled production sources**.
- **Export**.
- Use **Tools** for utility workflows such as **CSV Summary**, **Industrial data...**, **Real-time Industrial Monitoring...**, or **Enrich existing database metadata...**.
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
- **Reports** remains embedded in the main window. **Export** and other modeless workflows can stay open while you navigate.

In practice, this means some windows behave like a temporary popup, while others behave more like a separate workspace. **Modify Database** is opened as a focused editing dialog so you finish or cancel that cleanup before returning to other workflows.

### Working across pages and windows

Opening another workspace does not close or recreate Reports. Review and selection stay
with its current source/database. When the selected database changes, already-open export
or editing windows may keep their previous database; the main window identifies those
windows. Check their displayed database before continuing.

### Context and navigation during a session

The main window and Reports share accepted source/database changes. Navigation preferences remember the chosen page; report selection and active operations remain session state. Check the current paths before starting work.
