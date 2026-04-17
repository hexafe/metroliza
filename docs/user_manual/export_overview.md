# Export Overview

## What Export is for

Use **Export** to create the main Metroliza **Excel file** from a Metroliza **database file**.

This is the main reporting step after [Parsing](parsing.md). It can also use optional filtering, optional grouping, and a preset before the export runs.

If you are new to the app, think of Export like this:

- choose the source **database file**,
- choose the output **.xlsx file**,
- optionally filter the data,
- optionally group the data,
- choose the export preset,
- choose the output options,
- run the export.

## Before you start

Before export, you usually need:

- a database created by [Parsing](parsing.md), and
- an output location for the final **Excel file**.

Optional preparation steps:

- [Modify Database](modify_database.md) if labels in the database need cleanup,
- [Characteristic Name Matching](characteristic_name_matching.md) if characteristic names need normalization before grouped analysis,
- [Export filtering](export_filtering.md) if you only want part of the database in the export,
- [Export grouping](export_grouping.md) if you want grouped analysis/reporting.

## Files

### Select a database file

Choose the database you want to export from.

Important behavior: selecting a new database resets the export’s current filter and grouping context.

In practical terms, when you change the database:

- previous filter selections are cleared,
- previous grouping selections are cleared,
- the Export dialog goes back to **not applied** for those optional steps.

This helps prevent accidentally reusing filters or groups from a different database.

The dialog keeps the selected database in a compact read-only field so long file paths do not stretch the window.

### Select an Excel file

Choose where the output **.xlsx file** should be saved.

The **Export** button stays disabled until an output Excel file is selected.

Even if you also use Google Sheets export, the local **.xlsx file** is still required and is always kept.

The selected output path is shown in the dialog in a compact field with the full path available on hover.

## Data

This section controls which data is included before the workbook is built. In the Export dialog, the status rows show whether each step is **Applied** or **Not applied**.

### Select filters (optional)

Click **Edit...** next to **Filters** to open the dedicated filtering dialog.

Use this when you want to limit the export by:

- **AX**,
- **REFERENCE**,
- **HEADER**,
- part/revision/template metadata,
- sample number and sample number kind,
- operator,
- status code,
- filename,
- parser/template family, and/or
- measurement date range.

See [Export filtering](export_filtering.md) for details.

### Group data (optional)

Click **Edit...** next to **Grouping** to open the grouping dialog.

Use this when you want to assign parts into named groups for grouped reporting and the **Group Analysis worksheet**.

See [Export grouping](export_grouping.md) for details.

Important behavior: if grouping is applied, the Export dialog automatically switches **Group analysis** to **Standard** if it was previously **Off**.

## Output

This section controls the overall export style and optional sidecar outputs.

### Export preset

The preset is shown first in the dialog and changes several other export option fields for you.

Available presets are:

- **Main plots**
- **Extended plots**

#### Main plots

Use **Main plots** when you want the core charts for faster day-to-day review.

This is the simpler preset for regular use.

#### Extended plots

Use **Extended plots** when you want a deeper report with extra summary output.

This is better when you want a more analysis-heavy workbook.

Because presets update other fields in the dialog, do not be surprised if chart-related settings change when you switch presets.

### Google Sheets version

You can optionally check **Google Sheets version**.

This means:

- Metroliza still creates the local **.xlsx file**, and
- it also tries to create a Google Sheets version.

This option is optional. The local Excel workbook remains the base output.

### HTML dashboard

You can optionally check **HTML dashboard**.

This adds a local `*_dashboard.html` file and a matching asset folder next to the exported workbook.

Use it when you want:

- a browser view of the exported charts,
- larger click-to-enlarge chart viewing, and
- a simpler way to review results without opening Excel first.

Extended summary sections include compact report metadata when available, such as part, revision, template, operator, date range, sample count, and source file context.

This option does not replace the workbook. It adds an extra review file alongside it.

### Chart type

Available chart types are:

- **Line**
- **Scatter**

Use **Line** when you want charts that keep the sample number sequence visible.

Use **Scatter** when you want points shown in a simpler sequential order.

### Sort by

You can sort by:

- **Date**, or
- **Sample #**.

Choose the option that best matches how you want to read the workbook.

## Group analysis

This section controls whether the exported workbook includes the **Group Analysis worksheet**.

### Group analysis level

Available levels are:

- **Off**
- **Light**
- **Standard**

#### Off

Do not add the Group Analysis worksheet.

#### Light

Adds the Group Analysis worksheet in a more compact form.

#### Standard

Adds the same worksheet with more supported on-sheet detail, including plot support when available.

### Group analysis scope

Available scopes are:

- **Auto**
- **Single-reference**
- **Multi-reference**

This setting appears only when **Group analysis** is not **Off**.

A simple way to think about scope:

- **Auto** lets the export decide based on the filtered/grouped data.
- **Single-reference** is for exports that should be treated as one-reference analysis.
- **Multi-reference** is for exports that should be treated as multi-reference analysis.

There is a dependency between the level and scope:

- if level is **Off**, scope is effectively inactive,
- if level is **Light** or **Standard**, scope becomes available.

For help reading the finished worksheet, see [Group Analysis worksheet manual](group_analysis/user_manual.md).

## Advanced options

These settings fine-tune chart behavior. They are collapsed by default in the Export dialog, so you only open them when you need them.

### Min samplesize to generate violin plot instead of scatter

This controls when the extended report prefers a violin plot rather than a simpler scatter style.

A practical reading:

- lower values allow violin plots more often,
- higher values require more data before those plots are used.

### Increase the limits on the y-axis by as many times

This controls how much extra vertical space is added to summary-plot y-axis limits.

A practical reading:

- **0** keeps automatic limits,
- larger numbers increase the visual margin.

### Hide OK results?

Use this if you want the workbook to hide columns that only show OK results.

This can help reduce clutter when you mainly want to focus on results that need attention.

## Running the export

1. Select the **database file**.
2. Select the output **Excel file**.
3. Optionally click **Edit...** next to **Filters**.
4. Optionally click **Edit...** next to **Grouping**.
5. Choose the preset and output options.
6. Choose **Group analysis** settings if needed.
7. Expand **Show advanced options** if needed.
8. Click **Export**.

While export runs, Metroliza shows a progress dialog with:

- status text,
- a progress bar, and
- **Cancel**.

### Cancel behavior

Cancel is cooperative.

When you click **Cancel**, the app sends a cancel request and waits for the export thread to confirm the stop. It is not an instant force-stop.

If the worker confirms cancellation, you get an **Export canceled** message.

## What files/results you get

### Local Excel output

A local **.xlsx file** is always part of the result.

### Optional Google Sheets output

If you enabled Google Sheets export, Metroliza also attempts that extra output, but the local Excel file still remains the primary saved file on your machine.

### Completion message

When export finishes, Metroliza shows a completion message. Depending on the result, this message can include clickable links for the exported output or its location.

## Which manual to read next

Use these follow-up pages based on what you need:

- [Export filtering](export_filtering.md) — how filtering choices work.
- [Export grouping](export_grouping.md) — how to create and save groups.
- [Group Analysis worksheet manual](group_analysis/user_manual.md) — how to read the exported worksheet.
