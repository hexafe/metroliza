# CSV Summary

## When To Use CSV Summary

Use **CSV Summary** when you want to analyze a CSV or Excel file without first creating a
Metroliza database.

Open it from **Tools > CSV Summary...** in the main window.

This workflow is separate from the normal **Parsing -> database file -> Export** flow. It
uses the shared analytics workflow, so file data can use the same grouping, time buckets,
charts, statistics, dashboard output, and optional workbook output as cached production
data.

Use CSV Summary when:

- your source is already a CSV or Excel file,
- you want a dashboard or optional summary workbook, or
- you do not need the main database-based reporting flow.

## Full Workflow

The dialog is a compact analytics launcher.

Main controls:

- **Select input file(s) (CSV or Excel)**
- **Choose sheet, time, and reference columns**
- **Filter rows from the selected input**
- **Choose metrics**
- **Reload metrics** when source or column choices change
- **Edit row groups, then choose time bucket and aggregation**
- **Choose charts and statistics**
- **Select dashboard and optional workbook output paths**
- **Create analytics**

### 1. Select Input File

Choose the CSV or Excel file you want to analyze.
Supported file types are `.csv`, `.xlsx`, and `.xls`.

After a valid file is loaded:

- numeric-looking columns are loaded automatically as metrics,
- time and reference columns can be auto-detected or selected explicitly,
- grouping columns can be selected,
- dashboard and optional workbook output can be created.

You can select more than one CSV file at the same time. When multiple CSV files
are loaded, Metroliza asks whether to auto-create one group per file name. For
example, selecting `dataset1.csv`, `supplier1.csv`, and `test123.csv` can create
the groups `dataset1`, `supplier1`, and `test123`, with every row from each file
assigned to its matching group.

Auto-created file groups do not include a **POPULATION** group. If you want a
population-style comparison later, open **Edit groups** and rename or add groups
manually after the files are loaded.

For Excel files, Metroliza lists workbook sheets after file selection. Choose a different
sheet and click **Reload metrics** when needed. If automatic detection does not pick the
correct time or reference column, choose those columns and click **Reload metrics** again
before creating analytics.

### 2. Filter Rows

Click **Filter rows** when you want the summary to use only part of the selected file.
The filter dialog lets you add source columns, search column names, and select matching
value combinations such as `TraceCode | Batch`. Filtering is applied before grouping,
aggregation, charts, groupstats, dashboard output, and workbook output.

### 3. Review And Choose Metrics

Metroliza detects numeric-looking columns automatically after you choose the input file.
Click **Choose metrics** to open the larger metrics selection dialog. Use the search field
when a file contains many numeric columns.

Select the parameters you want to analyze. Use **Select all** or **Clear** in that dialog
when you need to adjust many metrics at once. These selected parameters can also be written
to separate workbook sheets.

### 4. Choose Grouping And Aggregation

Click **Edit groups** when you want export-style groups for the CSV/Excel rows. For a
single input file, the grouping dialog starts empty and leaves every row in
**POPULATION** until you create a custom group. For multiple CSV files, accepting the
auto-create prompt starts the dialog with one group per file name and no **POPULATION**
rows. Search for a source column and double-click it to choose the first column used to
select parts, such as `TraceCode`. Double-click another available column when you want to
refine the visible combinations, or double-click a selected column to remove it. The
matching list shows each selected column chain as values like `TraceCode | Cavity`, so you
can select the rows for a named group and leave the remaining rows in **POPULATION** for
selected-vs-rest comparisons when you choose to create that population manually.

Use the matching-row search field either as a normal value search or as a row filter. Plain
text searches visible value labels. Expressions such as `Supplier=SUPPLIER AND Value > 1`
filter the source rows. Text filters support `*` wildcards, and `IN` lists can match
several values at once, such as `Part IN (body*, cap)` or `Sample IN (1, 2, 3)`.
**Assign all filtered rows** applies that current search or filter across all matching pages.

The selected groups are written as the `GROUP` column and are used by aggregation, charts,
groupstats, dashboard output, and optional workbook output. Choose a time bucket and
aggregation method in the main dialog.

To make specific references, IDs, batches, or other row values stand out, use **Edit
groups** instead of a separate references field. Select the source column that identifies
those rows, assign the matching values to a named group, and leave the remaining rows in
**POPULATION** when you want a selected-vs-rest view.

Available time buckets:

- raw rows,
- hour,
- day,
- week,
- month,
- year.

Available aggregation choices include mean, median, count, sum, min, max, standard
deviation, and percentiles.

### 5. Choose Outputs

Choose chart/statistics outputs:

- time series,
- histogram,
- violin plot,
- box plot,
- groupstats.

Choose an HTML dashboard path first. Optionally enable workbook output and
**Separate sheet per selected parameter**.

The saved page is titled **Metroliza CSV Summary Dashboard**. Its front-page cards show
the source, sheet when available, filters, groups, rows rendered into dashboard chart data,
and dashboard interactivity mode so reviewers can see when they are looking at all rows or
a bounded visual sample.

Use **Dashboard style > Change...** when you want the CSV/Excel dashboard to use a saved
visual recipe, palette, marker emphasis, group/stat-line style, or selected-element
opacity. Start with the visible recipe and saved-theme controls; use **Customize...** for
detailed color, line, per-element opacity, or selected-element styling. These choices
affect the interactive dashboard charts only; they do not change the source data or the
selected metrics.

Use **Dashboard interactivity > Change...** when the selected input is large enough that
fully interactive charts may make the saved dashboard too heavy for a browser. **Auto** is
the default: small selections stay fully interactive, while large selections use the
configured in-window dashboard interactivity settings before processing. Statistics, group
comparison, aggregate tables, and workbook output continue to use all selected rows even
when dashboard charts use a bounded visual sample.

Practical choices for large datasets:

- **Auto** is the safest first choice. It keeps small files interactive and applies the
  configured browser-safety limits when a large file may create a slow or oversized
  dashboard.
- **Interactive random sample** keeps Plotly hover/zoom/legend interactions by drawing a
  reproducible random visual sample, defaulting to 50,000 rows. Use it for exploration
  when you need responsive charts but do not need every source point drawn in the browser.
- **Snapshots only** writes image snapshots instead of interactive charts and uses the
  same bounded visual sample for very large selections. Use it for review packages that
  must open reliably on ordinary computers.
- **All rows** attempts to draw every selected row interactively. Use it only when the row
  count is manageable or the reviewer has a browser/computer that can handle the file.
  Metroliza can still replace individual interactive charts with snapshots if the
  dashboard would otherwise exceed the configured size budget.

When a visual sample is used, the dashboard run notes state how many rows were rendered
into dashboard charts and how many selected source rows were included in the statistics.
If a reviewer questions why the plotted point count is lower than the selected row count,
check those run notes first.

The **Dashboard size limit** control in the same dialog defines when oversized Plotly
payloads are replaced with image snapshots. **Default limit** uses Metroliza's normal
browser-safety budget. **Custom limit** lets you enter a larger MB budget when reviewers
need more interactive charts and can handle a larger HTML file. **No size limit** keeps all
generated interactive Plotly charts even when the resulting HTML file may be very large or
slow to open. Use the no-limit option only when the receiving computer and browser can
handle the exported dashboard size.

The CSV Summary window also includes **Large group layers > Change...**. This controls
when very large grouped time-series point layers are kept interactive or pre-rendered as
static image layers:

- **Auto** renders a group as a static image when that group is above the configured
  threshold, and can pre-render every supported group layer when the selected dashboard
  data is above the total threshold. The default thresholds are 5,000 rows per group and
  50,000 rows in total.
- **Interactive** keeps group layers as normal Plotly points. Use it when reviewers need
  hover labels or point selection and the row count is small enough.
- **Static image** uses image-backed group layers whenever the chart supports it. Use it
  when process backgrounds and large comparison groups should remain visible but the
  dashboard needs to stay responsive.

Static large-group layers keep the process background and large comparisons visible, but
hover and point selection are unavailable for those pre-rendered layers. Smaller groups
remain interactive where Plotly is enabled.

Selected plots are included in the dashboard and in the workbook chart sheet. Grouped time
series use separate marker-only scatter traces. Multi-group histograms are normalized to
show each group's share, so smaller selected groups remain visible next to larger
populations. Histograms include export-style statistics tables. Workbook time series and
multi-group histograms use Excel charts where that keeps the data editable; single-group
histograms, violin plots, and box plots use plotstats-first rendered images with
Metroliza/native fallback.

### 6. Create Analytics

Metroliza creates the dashboard and optional workbook in the background.

## Output

CSV Summary creates an **HTML dashboard** and, when selected, an **Excel workbook** (`.xlsx`).

This output is separate from the main Parse/Export database workflow.

The workbook can include:

- table data,
- aggregated rows,
- metric summaries,
- diagnostics,
- selected charts,
- separate sheets for each selected parameter.

## Troubleshooting

- If the dashboard is slow to open, recreate it with **Auto** or **Snapshots only** and
  keep the default dashboard size limit.
- If the dashboard file is too large to share, use **Snapshots only**, reduce the selected
  metrics, filter the rows before processing, or keep workbook output for detailed tables.
- If a reviewer needs hover labels for every point in a large group, use **Interactive**
  large group layers and avoid **Snapshots only**, but expect larger and slower
  dashboards.
- If the plotted point count looks lower than the selected row count, check the dashboard
  run notes. Random sampling and snapshots limit visual chart rows; statistics and tables
  still use all selected rows.
- If a chart appears as an image instead of an interactive Plotly chart, the selected
  interactivity mode or dashboard size limit likely converted that chart to a snapshot.
- If a workbook value does not appear to match a sampled dashboard view, trust the workbook,
  aggregate tables, and statistical sections for all-row calculations; the sampled chart is
  only a visual representation.

## Progress And Cancel Behavior

When processing starts, Metroliza shows a worker/progress dialog with:

- status text,
- a progress bar,
- a **Cancel** button.

If processing completes normally, the app shows where the dashboard and workbook were saved.
The completion dialog links the generated dashboard and workbook files.
Dashboard diagnostics, groupstats sections, detailed statistical-test tables, and chart
statistics are collapsed by default; open only the sections you need to inspect.
