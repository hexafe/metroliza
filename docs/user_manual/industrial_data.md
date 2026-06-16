# Industrial Data / Oznak

## When To Use Industrial Data

Use **Industrial data** when you want to bring production-line process data into
Metroliza and analyze it beside, or separately from, metrology reports.

Open it from **Tools > Industrial data...** in the main window.

This workflow is for production data that Oznak can read from a production line
database, such as an MES table with assembly results, station results, torque
values, operator names, work orders, or line status.

## The Simple Mental Model

Industrial Data follows one path:

```text
Source -> Access -> Cache -> CSV Summary
```

Use that strip as the mental model:

1. **Source** means the saved description of where the production data lives.
2. **Access** means Metroliza checks that your production database login can read it.
3. **Cache** means selected production rows are copied into the active local SQLite
   cache.
4. **CSV Summary** means the cached rows open in the normal CSV Summary tools for
   filtering, grouping, dashboards, statistics, and optional workbooks.

Metroliza does not change the production database. It reads production rows and stores a
local copy only when you run **Fetch to cache**.

## Storage And Databases

Industrial Data uses two storage ideas and one production database. Keep them separate.

The **active local cache** is where fetched production rows are stored. The Industrial
Data window can use three cache targets:

- **Temp** uses a temporary SQLite cache. This is the fastest start when you only want to
  fetch rows, filter, group, export, or make a dashboard now. The temp cache is removed
  when the Industrial Data window closes.
- **Open...** uses an existing Metroliza report database. Choose this when you want
  fetched production rows to stay with parsed metrology reports, when you need
  report-to-production links, or when the normal Metroliza export should include
  industrial context.
- **Create...** creates a persistent industrial cache database. Choose this when you want
  to keep fetched production rows for later CSV Summary or workbook work, but you are not
  linking them to parsed Metroliza reports.

The **Metroliza report database** is the local SQLite file that Metroliza creates from
parsed CMM or metrology reports. It stores the reports, measurements, industrial cache
rows, sync notes, and report-to-production links. This is the file you select in the main
window or with **Open...** in the Industrial Data window.

The **production line database** is the database owned by the production system, such as
an MES, SQL Server, or MySQL database. Oznak reads this database through the production
source setup. It may contain many years of line data and usually belongs to IT, MES
support, or the process owner.

Selecting or creating a local cache does not connect to the production line. Creating a
production source does not parse metrology reports. The bridge is the explicit
**Fetch to cache** action: production rows are read from the production source and saved
into the active local cache.

## Set Up A Production Source

Click **Production sources...** to create or edit the non-secret setup for a production
line database.

If your team already has an Oznak/Industrial Data config file, load that config instead
of retyping the source. Use the connection-check action in the source setup, or
**Check access** in the fetch dialog, before fetching data. Checking first confirms that
the host, database, table or view, selected columns, and read-only credentials work before
Metroliza copies rows into the local cache.

Ask IT, MES support, or the process owner for these values before you start:

- the production database type, for example **MSSQL** or MySQL,
- the production host name and port,
- the database name,
- the table or view name that is safe for Metroliza/Oznak to read,
- the allowed columns that Metroliza should request,
- the column that uniquely identifies each production row,
- the timestamp column for process time,
- the reference or ID column that operators use to find specific assemblies,
- whether limited reads may use server-side ordering, and
- whether your account has read-only access to this table or view.

For example, a fake assembly MES source could use:

- **Source name**: `Assembly line MES`
- **Source alias**: `assembly_mes`
- **Production DB type**: `MSSQL`
- **Production host**: `mes-db.example.local`
- **Production database**: `MES_PROD`
- **Production table/view**: `assembly_results`
- **Production columns**:
  `id, reference, part_number, revision, serial, station, line, status, process_timestamp, torque_nm`
- **Record key / paging column**: `id`
- **Timestamp column**: `process_timestamp`

Use a source name that ordinary users recognize, such as `Assembly line MES`. Use a short
source alias, such as `assembly_mes`, when you need a stable technical name for the same
source.

The **Production columns** list should include only fields that users need for filtering,
grouping, linking, or analysis. You can paste a plain comma-separated list or a copied CSV
header such as `"TimeStamp","OP100RetestNumber3"`. Leave the field empty, or enter only
`*`, when the reviewed source is allowed to read all simple columns from the table or view.
If the production table has hundreds of columns, ask the process owner for the small safe
list instead of copying everything.

The **Record key / paging column** should be a stable row ID. In the example, that is
`id`. The timestamp column should be the process time. In the example, that is
`process_timestamp`.

If your database normally writes this as something like `dbo.assembly_results`, ask IT
whether Oznak should receive a simple view name such as `assembly_results`, or use the
**SQL query** path with a reviewed query. Some connectors only accept simple table or
view names in the guided source setup.

If the app says a table, view, or column name is invalid, ask IT for the exact
Metroliza/Oznak-safe name or for a simple view prepared for this workflow.

## Check Access Safely

Click **Fetch to cache...** and select a production source. Enter your production database
username and password. For normal single-source checks, use the **Production source** field.
For a guided batch fetch, check multiple entries in **Fetch sources**.

Use **Check access** before fetching rows.

**Check access** is safe:

- it reads up to one production row,
- it checks the login, host, database, table or view, columns, and query access,
- it saves no production rows into the Metroliza cache,
- it creates no report links, and
- it does not write to the production database.

If the check passes, Metroliza tells you how many rows were visible, usually `1 row(s)`
or `0 row(s)`. A result of zero rows means the database was reached, but the selected
source and filters did not show a row.

## Credentials

The production database username and password are not stored in the Metroliza report
database and are not written into the production source config file.

If you check **Remember on this computer**, Metroliza saves the credentials only after
**Check access** or **Fetch to cache** succeeds, or completes with warnings. If the login
fails, the credentials are not saved.

The dialog shows where saved credentials are stored for the selected source. Use
**Forget saved credentials** when a password changes, when a shared workstation should no
longer remember the login, or when the wrong credentials were saved.

## Fetch Rows To The Local Cache

After **Check access** passes, choose what to fetch. The fetch dialog has two practical
paths:

- **Guided filters** for normal use. Pick filters, a row limit, or explicit fetch-all.
- **SQL query** when IT, MES support, or an advanced user gives you the exact SQL query to
  run.

Both paths copy the returned rows into the active local cache. Neither path writes to the
production database.

For large guided or SQL fetches, Metroliza can save rows into the local cache while the
production read is still running. The progress text shows when rows are being saved, when
report links are refreshed, and when the cache summary is updated.

### Guided Filters

Use **Edit filters...** when you already know the assembly IDs, references, or simple
source-column filters. Choose the production reference column and paste the values.
Use **Fetch sources** to check more than one configured source when the same guided
filters should be fetched sequentially into the local cache.

Example:

```text
Reference/ID column in production data: reference
Reference/ID values to fetch:
REF-1001; REF-1002; REF-1003
```

You can paste values separated by commas, semicolons, spaces, tabs, or new lines. For
example, these all mean the same thing:

```text
REF-1001, REF-1002, REF-1003
REF-1001; REF-1002; REF-1003
REF-1001
REF-1002
REF-1003
```

Use **Use report DB values** when an opened Metroliza report database already contains the
report references you want to fetch from production. This shortcut is not available for a
temporary cache or a persistent industrial-only cache; paste the reference values instead.

You can also add simple extra filters, one per line, such as:

```text
station = ST-20
status IN OK, NOK
process_timestamp >= 2026-01-01
```

If you do not set a reference filter, **Fetch to cache** uses the **Fetch row limit**. The
default limit is `5000` rows. This is the safer first fetch when you are checking a new
source.

Use **Fetch all rows** only when you really need the full visible production table or
view. Metroliza warns first because a production source can contain many historical rows,
the fetch can take a long time, and the local SQLite cache can become large.

When more than one source is checked, Metroliza fetches them one by one and reports the
batch result at the end. Leave **Use entered credentials for all checked sources** enabled
when the same login works for every checked source. Turn it off only when each source
already has saved credentials in the local credential store.

### SQL Query

Use the **SQL query** tab when guided filters are not enough or when IT/MES support gives
you a reviewed query. Paste the query into the SQL editor, or click **Open SQL editor...**
for a larger editor and preview table in a separate window.

Before a full fetch, click **Preview SQL**. The preview reads only a small sample so you
can check whether the query runs and whether the returned columns look right. The default
preview size is `5` rows; increase it only when five rows are not enough to confirm the
result.

Use **Open recipe...** to load a saved SQL query and **Save recipe...** to keep a query for
later reuse. Recipes are useful for common tasks such as "last shift", "one work order",
or "one station and date range".

Keep SQL recipes simple and read-only. If a query returns too many rows, add a date,
station, work-order, or serial/reference condition before fetching. If you choose to fetch
all rows from a SQL query, Metroliza shows the same large-fetch warning as guided mode.
When multiple sources are checked, the same reviewed SQL query runs once per checked
source and the final status reports which sources succeeded, warned, or failed.

### Send The Fetch To CSV Summary

Use **Fetch to CSV Summary** when the next step is filtering, grouping, dashboards, or an
optional Excel workbook. Metroliza fetches the rows into the active local cache and then
opens those cached rows in CSV Summary.

Use **Fetch to cache** when you only want to update the local cache first and decide later
whether to open CSV Summary, export a cached workbook, or refresh report links.

## What The Local Cache Does

The local industrial cache is a copy of the production rows you fetched, not a live
connection to production.

The cache lets you:

- review the same production rows later without reconnecting to the production database,
- open cached production rows in CSV Summary,
- create a cached industrial workbook,
- link production rows to Metroliza reports when the cache is an opened Metroliza report
  database, and
- add industrial context to a normal Metroliza export when report links exist.

The cache also stores the source identity and sync outcome, so users can see which
production source produced the rows and when the fetch last ran.

Cached rows are snapshots. If production data changes after the fetch, run **Fetch to
cache** again to refresh the local copy.

## The Source Column

Every cached row opened in CSV Summary includes a **source** column. Use it when more than
one production source has been cached in the same local cache.

For example, if rows were fetched from `Assembly line MES`, CSV Summary can filter or
group on:

```text
source = Assembly line MES
```

The cached table also keeps the source alias, such as `assembly_mes`, so exported data
remains traceable to the production source setup.

## Manual Production Links

Manual links are available only when Industrial Data is using an opened Metroliza report
database. They are not available for the temporary cache or a persistent industrial-only
cache because those cache targets do not contain parsed metrology reports.

Metroliza can often link a metrology report to a production row when the report reference
and production reference are the same value.

Use **Production links...** when they are not the same.

For example:

- the Metroliza report reference is `REF-1001`,
- the production row uses serial `SN-A-00091`, and
- the MES row with `SN-A-00091` is the correct production record for that report.

In **Production links...**:

1. select one Metroliza report,
2. select one cached production row,
3. click **Link selected**.

Manual links take priority over automatic exact-reference links during export. They are
local links stored in the Metroliza report database. They do not change the production
line database.

Use **Refresh links** after fetching new rows or changing manual links, especially before
creating a normal Metroliza export with industrial context.

## Cached Workbook Export

Use **Export workbook...** when you want an Excel workbook from cached industrial rows.

The workbook uses the rows already stored in the active local industrial cache. It does
not query the production line database while the workbook is being created.

Use filters when you want a smaller workbook. Use grouping when reviewers need separate
views by fields such as source, station, line, work order, batch, operator, or process
status. Include plots when the workbook should contain chart output as well as tables.

## Open Cached Rows In CSV Summary

Use **CSV Summary...** when you want the most flexible analysis path. It opens cached
production rows in the same workflow used for CSV and Excel files.

CSV Summary can use fetched production columns as filters, grouping fields, time fields,
and metrics. In the assembly MES example:

- `process_timestamp` is the time column,
- `reference` identifies assemblies such as `REF-1001`,
- `station` and `line` describe where the row was produced,
- `status` from the source can appear as `process_status` in the cached data,
- `torque_nm` is a numeric metric that can be plotted and summarized, and
- `source` identifies the production source, such as `Assembly line MES`.

Practical CSV Summary examples:

- Filter `source` to `Assembly line MES`, filter `station` to `ST-20`, choose
  `torque_nm` as the metric, and group by `line` to compare assembly lines at one
  station.
- Filter `reference` to `REF-1001`, `REF-1002`, and `REF-1003`, then group by
  `process_status` to see which fetched assemblies passed, failed, or need review.
- Filter `work_order` to `WO-2026-0412`, group by `station`, and chart `torque_nm` over
  `process_timestamp` to review one work order through the line.
- Filter `batch_lot` to `LOT-A17`, group by `operator_name`, and compare the metric
  summary for each operator.
- Group by `source` first when the same report database contains cached rows from more
  than one production source.
- Group by `line` and `process_status` when you need a dashboard that separates normal
  production from rework, scrap, or incomplete rows.

When CSV Summary creates a dashboard or optional workbook, it uses the cached rows. It
does not connect back to the production line database.

## Troubleshooting

- If you only need a quick analysis, use **Temp**, fetch the rows, then open CSV Summary.
  Remember that the temporary cache is deleted when the Industrial Data window closes.
- If you need report-to-production links or industrial context in the normal Metroliza
  export, use **Open...** and choose the Metroliza report database before fetching rows.
- If you want to keep fetched production rows without linking to parsed reports, use
  **Create...** to create a persistent industrial cache database.
- If no production source is listed, open **Production sources...**, check the config file
  path, and save at least one source.
- If **Check access** fails, confirm the host, port, database, table or view, production
  username, password, VPN/network access, and read-only permission with IT.
- If **Check access** reaches the database but shows zero rows, the table may be empty,
  the account may see only a filtered view, or the current reference filter may not match
  any row.
- If **Fetch to cache** returns no rows, check the reference column name and pasted
  values. `reference` with `REF-1001; REF-1002; REF-1003` is different from filtering the
  record key `id`.
- If a fetch is slow or the cache becomes too large, cancel it and fetch by references or
  a smaller row limit before trying **Fetch all rows** again.
- If CSV Summary does not show expected grouping fields, ask whether the source setup
  included those columns. Fields such as `work_order`, `batch_lot`, `operator_name`, and
  `process_status` must be present in the fetched data before CSV Summary can use them.
- If the dashboard mixes rows from different production sources, filter or group by the
  `source` column.
- If an industrial workbook or normal Metroliza export has no production context, refresh
  links and check whether the Metroliza report reference matches the production reference.
  Use **Production links...** when manual matching is needed.
- If saved credentials do not reappear, remember that Metroliza stores them only after a
  successful access check or fetch. Re-enter the username and password, check **Remember
  on this computer**, and run **Check access** again.
