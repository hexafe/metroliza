# CSV Summary

## When to use CSV Summary

Use **CSV Summary** when you want to create an Excel summary directly from a CSV file.

This workflow is separate from the normal **Parsing → database file → Export** flow.

Use CSV Summary when:

- your source is already a CSV,
- you want a quick summary workbook, or
- you do not need the main database-based reporting flow.

## Full workflow

The dialog is a simple step-by-step launcher.

Main controls:

- **Select input file (CSV)**
- **Filter columns (optional)**
- **Set spec limits (optional)**
- **Clear saved presets (optional)**
- **Include histogram and boxplot charts**
- **Summary-only mode (skip per-column sheets/charts)**
- **Select output file (xlsx)**
- **START**

### 1. Select input file (CSV)

Choose the CSV file you want to summarize.

After a valid CSV is loaded:

- the column filter button is enabled,
- the spec limits button is enabled,
- the output button is enabled.

Metroliza also tries to restore saved presets for that CSV file pattern.

### 2. Filter columns (optional)

Open the column filter dialog if you want to control which columns are treated as index columns and which are treated as data columns.

See [Column filtering](#column-filtering) below.

### 3. Set spec limits (optional)

Open the spec limits dialog if you want to enter per-column:

- **NOM**,
- **USL**, and
- **LSL**.

See [Spec limits](#spec-limits) below.

### 4. Choose plot options

You can choose whether to include chart-heavy output.

See [Plot options](#plot-options) below.

### 5. Select output file (xlsx)

Choose where the output **Excel file** should be saved.

After you choose an output file, **START** becomes enabled.

### 6. Click START

This saves the current preset choices and starts the background export.

## Column filtering

The column filter dialog is called **Filter Columns**.

It has two selection lists:

- index columns,
- data columns.

### Default first-column index option

The index list includes:

**SELECT DEFAULT (FIRST COLUMN)**

If you use this option, Metroliza treats the first CSV column as the index column.

### Select all data columns

The data list includes:

**SELECT ALL**

If you use this option, Metroliza selects all columns except the chosen index columns as data columns.

This is the fastest option for a standard CSV layout.

## Spec limits

The spec limits dialog is called **Column spec limits**.

For each selected data column, you can enter:

- **NOM**,
- **USL**,
- **LSL**.

Blank or invalid values are treated safely and normalized by the app, so this dialog is mainly for users who want explicit target/spec values in the summary output.

## Plot options

### Include histogram and boxplot charts

When enabled, the summary can include histogram and boxplot-style chart output.

This gives a richer workbook, but it can be slower for large files or many columns.

### Summary-only mode

**Summary-only mode (skip per-column sheets/charts)** creates a lighter output.

Use this when you want a faster workbook that focuses on summary information instead of detailed per-column chart pages.

### Large file / many chart guidance

If the current settings would create a very large number of charts, Metroliza shows a warning.

It can offer a faster **Quick-look mode** by disabling charts.

This is helpful when:

- the CSV has many data columns,
- chart generation would be slow,
- you want a quick first pass before creating a full chart-heavy workbook.

## Output and presets

### What output you get

CSV Summary creates an **Excel file** (`.xlsx`).

This output is separate from the main Parse/Export database workflow.

### How presets are remembered

CSV Summary remembers settings in saved presets under your user profile.

These presets can include:

- selected index columns,
- selected data columns,
- CSV loading config,
- spec limits,
- chart settings,
- summary-only choice.

When you reopen a similar CSV later, Metroliza may restore those saved choices automatically.

### Clear saved presets

Use **Clear saved presets (optional)** if you want to remove the stored CSV Summary presets.

This clears the saved preset file for the CSV Summary workflow.

## Progress and cancel behavior

When processing starts, Metroliza shows a worker/progress dialog with:

- status text,
- a progress bar,
- a **Cancel** button.

If you cancel, the worker is asked to stop and the app shows a **Processing canceled** message when the worker finishes canceling.

If processing completes normally, the app shows **Processing complete** and tells you where the Excel file was saved.
