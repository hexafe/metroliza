# CSV Summary

## When To Use CSV Summary

Use **CSV Summary** when you want to analyze a CSV or Excel file without first creating a
Metroliza database.

Open it from **Tools > CSV Summary...** in the main window.

This workflow is separate from the normal **Parsing -> database file -> Export** flow. It
uses the shared analytics workflow, so file data can use the same grouping, time buckets,
charts, statistics, and workbook output as cached production data.

Use CSV Summary when:

- your source is already a CSV or Excel file,
- you want a dashboard or summary workbook, or
- you do not need the main database-based reporting flow.

## Full Workflow

The dialog is a compact analytics launcher.

Main controls:

- **Select input file (CSV or Excel)**
- **Choose sheet, time, and reference columns**
- **Filter rows from the selected file**
- **Choose metrics**
- **Reload metrics** when source or column choices change
- **Edit row groups, then choose time bucket and aggregation**
- **Paste references or IDs to mark/filter/compare**
- **Choose charts and statistics**
- **Select dashboard and workbook output paths**
- **Create analytics**

### 1. Select Input File

Choose the CSV or Excel file you want to analyze.
Supported file types are `.csv`, `.xlsx`, and `.xls`.

After a valid file is loaded:

- numeric-looking columns are loaded automatically as metrics,
- time and reference columns can be auto-detected or selected explicitly,
- grouping columns can be selected,
- dashboard and workbook output can be created.

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

Click **Edit groups** when you want export-style groups for the CSV/Excel rows. The
grouping dialog starts empty and leaves every row in **POPULATION** until you create a
custom group. Search for a source column, click **Add column** to choose the first column
used to select parts, such as `TraceCode`, then add another column when you want to refine
the visible combinations. The
matching list shows each selected column chain as values like `TraceCode | Cavity`, so you
can select the rows for a named group and leave the remaining rows in **POPULATION** for
selected-vs-rest comparisons.

The selected groups are written as the `GROUP` column and are used by aggregation, charts,
groupstats, and workbook output. Choose a time bucket and aggregation method in the main
dialog.

Available time buckets:

- raw rows,
- hour,
- day,
- week,
- month,
- year.

Available aggregation choices include mean, median, count, sum, min, max, standard
deviation, and percentiles.

### 5. Paste References Or IDs

Paste references or IDs if you want those rows to stand out in charts and statistics.

Reference modes:

- highlight selected values,
- compare selected values against the rest,
- analyze selected values only,
- create a selected group.

### 6. Choose Outputs

Choose chart/statistics outputs:

- time series,
- histogram,
- violin plot,
- box plot,
- groupstats.

Choose an HTML dashboard path. Optionally enable workbook output and **Separate sheet per
selected parameter**.

Selected plots are included in the dashboard and in the workbook chart sheet. Grouped time
series use separate marker-only scatter traces. Multi-group histograms are normalized to
show each group's share, so smaller selected groups remain visible next to larger
populations. Histograms include export-style statistics tables. Workbook time series and
multi-group histograms use Excel charts where that keeps the data editable; single-group
histograms, violin plots, and box plots use Metroliza/plotstats-rendered plot images.

### 7. Create Analytics

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

## Progress And Cancel Behavior

When processing starts, Metroliza shows a worker/progress dialog with:

- status text,
- a progress bar,
- a **Cancel** button.

If processing completes normally, the app shows where the dashboard and workbook were saved.
The completion dialog links the generated dashboard and workbook files.
Dashboard diagnostics are collapsed by default; open the diagnostics section when you need
technical details.
