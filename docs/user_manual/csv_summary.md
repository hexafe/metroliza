# CSV Summary

## Keyboard shortcuts

**F1** opens this window's manual. In the CSV Summary launcher:

| Shortcut | Action |
|---|---|
| Alt+B | Browse for input files |
| Alt+M | Load or refresh data and metrics |
| Alt+F / Alt+T | Filter rows / Clear filter |
| Alt+O / Alt+L | Choose metrics / Edit limits |
| Alt+E / Alt+G | Edit groups / Clear groups |
| Alt+R / Alt+W | Browse for dashboard / workbook output |
| Alt+A | Show or hide advanced options |
| Alt+Y | Create analytics |
| Alt+C | Close |

Button tooltips also show these shortcuts. Disabled or hidden controls do nothing;
an open modal dialog owns its own keyboard commands. The launcher has no search
field, so it does not bind Ctrl+F. The Industrial cache presentation uses the same
visible button shortcuts and its own Industrial Data manual on F1.

In the **Filter rows** and **Edit groups** dialogs, **Ctrl+F** focuses and selects
the search for the list that has focus: available columns, selected columns, or
matching values/rows. From elsewhere it selects the available-columns search.
Searching keeps the existing rules: press Enter where the field requires it.
F1 opens this CSV Summary manual from either dialog.

| Dialog | Shortcut | Action |
|---|---|---|
| Filter rows | Alt+D / Alt+M / Alt+L | Add column / Remove selected column / Clear columns |
| Filter rows | Alt+V / Alt+R | Clear current values and dates / Reset draft |
| Filter rows | Alt+A / Alt+C | Apply filter / Cancel |
| Edit groups | Alt+F / Alt+A | Assign all filtered rows / Assign selected row values |
| Edit groups | Alt+R / Alt+D | Rename group / Delete group |
| Edit groups | Alt+L / Alt+S | Clear selection / Reset changes |
| Edit groups | Alt+U / Alt+C | Use grouping / Cancel |

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
- you opened cached production rows from [Industrial Data](industrial_data.md),
- you want a dashboard or optional summary workbook, or
- you do not need the main database-based reporting flow.

### When CSV Summary opens from Industrial Data

When you click **CSV Summary...** in the Industrial Data launcher, the table is already
loaded from cached production rows in the active industrial cache. You do not need to
pick a CSV file.

When you click **Fetch to CSV Summary** in the Industrial Data fetch dialog, Metroliza
first stores the fetched rows in the selected cache target, then opens those rows here.
That cache target can be temporary for a one-time review, an opened Metroliza report
database, or a newly created industrial cache database for later reuse.

Every cached row includes a **source** column that identifies the configured production
database that produced the row. Use that column like any other filter or grouping field.
For example:

- filter `source = Assembly line MES` to review one production source,
- group by `source | station` to compare stations across sources,
- group by `process_status` to compare OK/NOK or process states,
- select metrics such as `cycle_time_s`, `torque_nm`, or another numeric production
  column, then create the dashboard.

The cached rows stay in the active local cache chosen in Industrial Data. CSV Summary does
not connect to the production line database while creating the dashboard or optional
workbook.

## Full Workflow

The dialog is a compact analytics launcher.

The first screen is dashboard-first. It keeps the routine path visible and moves
rarely needed tuning into **Advanced**.

Main controls:

- **Select input file(s) (CSV or Excel)**
- **Review detected rows, files, metrics, time column, and Part / ID column**
- **Filter rows from the selected input**
- **Choose metrics**
- **Load CSV/Excel data and detect metrics** or reload the data when source or column choices change
- **Edit row groups**
- **Select the dashboard output path**
- **Create analytics**

Advanced controls:

- time bucket and aggregation method,
- chart and statistics output toggles,
- optional workbook output and separate parameter sheets,
- dashboard interactivity and dashboard size handling,
- large group static-layer settings, and
- dashboard style/custom visual tuning.

### 1. Select Input File

Choose the CSV or Excel file you want to analyze.
Supported file types are `.csv`, `.xlsx`, and `.xls`.

After a valid file is loaded:

- numeric-looking columns are loaded automatically as metrics,
- time and reference columns can be auto-detected or selected explicitly,
- grouping columns can be selected,
- dashboard and optional workbook output can be created.

The source status row tells you what Metroliza detected, including row count,
source file count, metric count, detected time column, detected Part / ID column,
and whether a large-file row store is being used.

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

The editor distinguishes **Values: All** from **Selected (n)** and reports matching
choices plus hidden selections. Search changes the choice list, never the data predicate;
SQLite value search still requires Enter. Clearing a search preserves hidden selections.
The draft/applied summary retains the last applied columns, dates and expression until Apply.

- **Clear searches** resets list visibility only.
- **Clear selection (All values)** removes value choices from the current column, preserving its dates.
- **Clear condition (values + dates)** removes both conditions from that column.
- **Clear expression** removes only the advanced expression.
- **Reset draft [Ctrl+Shift+R]** resets all draft conditions after confirmation.

Use **Ctrl+E / Ctrl+Shift+E** to add/remove the current column. E/R are quick alternatives
only while the corresponding column list has focus; typing and AltGr remain text input.
**Ctrl+S** applies, **Ctrl+W / Esc** cancels through the discard guard, and **Ctrl+F** searches.
Invalid expressions or reversed dates block Apply. Applying an unchanged predicate keeps
groups; a real narrowing still warns before dropping assignments. The body scrolls on short
screens while Apply/Cancel remain visible. Existing Alt mnemonics are secondary alternatives.

The filter dialog lets you add source columns, search column names, and select matching
value combinations such as `TraceCode | Batch`. Filtering is applied before grouping,
aggregation, charts, groupstats, dashboard output, and workbook output.

Use **Magic filter** in the same dialog when you need a typed expression instead of value
selection. The expression syntax supports `=`, `!=`, `<`, `<=`, `>`, `>=`, `IN`, `NOT IN`,
`AND`, `OR`, parentheses, and `*` wildcards. Field names and operators are not
case-sensitive, so `Param1`, `param1`, `AND`, `and`, `IN`, and `in` are interpreted the
same way. Text values are matched without case sensitivity by default. Repeated
comparisons after `AND` reuse the previous field name: `Param1 > 200 and < 150.2` is
accepted as `Param1 > 200 AND Param1 < 150.2`, which is valid syntax and returns zero rows
because the two limits conflict.

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
rows. Search for a source column, select it, and use **Add column (Ctrl+E)** to
choose a column such as `TraceCode`. **Remove column (Ctrl+Shift+E)** removes the
current visible selected column. Double-clicking remains available for both operations.
See [grouping controls](csv_grouping_controls.md) for focused E/R commands, member removal,
source identity/date labels and draft behavior. The
matching list shows each selected column chain as values like `TraceCode | Cavity`, so you
can select the rows for a named group and leave the remaining rows in **POPULATION** for
selected-vs-rest comparisons when you choose to create that population manually.

Use the matching-row search field either as a normal value search or as a row filter. Plain
text searches visible value labels. Expressions such as `Supplier=SUPPLIER AND Value > 1`
filter the source rows. Text filters support `*` wildcards, and `IN` lists can match
several values at once, such as `Part IN (body*, cap)` or `Sample IN (1, 2, 3)`.
Field names and operators in these expressions are not case-sensitive.
Press **Enter** to apply each changed search. Pending matching-row text blocks assignment;
pending Columns or Selected columns searches only affect their column lists. The status
shows **Not applied — press Enter**, the applied predicate and matching row count.
**Assign all filtered rows** applies that scope across all matching pages and shows its
row count in the group-name prompt. Reapplying an unchanged row filter keeps groups;
changing it keeps compatible members by row ID and asks before dropping memberships.

The selected groups are written as the `GROUP` column and are used by aggregation, charts,
groupstats, dashboard output, and optional workbook output. Choose a time bucket and
aggregation method in **Advanced** when the default raw-row view is not enough.

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

Choose an HTML dashboard path first. This is the routine CSV Summary output.

Use **Advanced** when you want to change chart/statistics outputs:

- time series,
- histogram,
- violin plot,
- box plot,
- groupstats.

Also use **Advanced** when you want to enable workbook output and
**Separate sheet per selected parameter**.

The saved page is titled **Metroliza CSV Summary Dashboard**. Its front-page cards show
the source, sheet when available, filters, groups, rows rendered into dashboard chart data,
and dashboard interactivity mode so reviewers can see when they are looking at all rows or
a bounded visual sample.

Use **Advanced > Dashboard style > Change...** when you want the CSV/Excel dashboard to use a saved
visual recipe, palette, marker emphasis, group/stat-line style, or selected-element
opacity. Start with the visible recipe and saved-theme controls; use **Customize...** for
detailed color, line, per-element opacity, or selected-element styling. See
[Dashboard visuals](dashboard_visuals.md) for the recipe names and examples. These choices
affect the interactive dashboard charts only; they do not change the source data or the
selected metrics.

Use **Advanced > Dashboard interactivity > Change...** when the selected input is large enough that
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

The CSV Summary window also includes **Advanced > Large group layers > Change...**. This controls
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
hover and point selection are unavailable for those pre-rendered layers. Static layers use
the dashboard style/group color resolved at export time; change the dashboard style and
regenerate the dashboard if a pre-rendered layer needs a different color. Smaller groups
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

- If **Create analytics** is disabled, check that a source is loaded, at least one metric
  is selected, at least one chart/statistics output is selected, and the required
  dashboard or workbook path is filled in.
- If you changed the Excel sheet, time column, or Part / ID column, click **Reload
  metrics** before creating analytics.
- If filtering leaves zero rows, clear or loosen the filter and try again.
- If multiple input files are needed, select multiple CSV files. Multi-file loading is
  not available for Excel workbooks.
- If groupstats is selected but no groupstats output appears, create at least two
  non-empty manual groups in **Edit groups**.
- If a filter expression is rejected, use simple value selection first, then retry the
  expression with one condition at a time.
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

If processing completes normally, the completion dialog shows the generated file names
as links and offers **Open workbook**, **Open dashboard**, and **Show in folder** for
produced files. Hover over a file link or button to see its full location.

After acknowledgement, the **Last run** row keeps the outcome, local time, file names,
row/metric/chart counts, and those actions until the next run starts in this window.
Cancelled and failed runs keep their outcome without actions for unproduced files.
Nothing is saved between sessions. Actions warn you if a file was moved or deleted;
locate it or run the analysis again.
Dashboard diagnostics, groupstats sections, detailed statistical-test tables, and chart
statistics are collapsed by default; open only the sections you need to inspect.
