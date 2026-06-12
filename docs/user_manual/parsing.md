# Parsing

## When to use Parsing

Use **Parsing** when you want to turn measurement report files into a Metroliza **database file**.

This is the normal starting point for the main database-based workflow. The database file created here is then used by [Export overview](export_overview.md), and it can also be cleaned up later in [Modify Database](modify_database.md).

## Before you start

Before you click **Parse reports**, you need:

- a source containing the reports you want to import, and
- a destination **database file**.

The source can be:

- a directory of report files, or
- a supported archive file.

## Buttons and fields

### Select a source (directory or archive file)

This area shows the current source selection.

- The text line shows either the selected path or **None selected**.
- Click **Browse folder** to choose a normal folder of report files.
- Click **Browse archive** to choose a supported archive file directly.

### How source selection works

Use **Browse folder** when your reports are already in a folder.

1. Click **Browse folder**.
2. Choose the folder that contains the reports.
3. The selected folder becomes the source.

If you cancel the folder picker, Metroliza asks:
   **“No directory was selected. Do you want to choose an archive file instead?”**

If you answer **Yes**, choose the archive file. If you answer **No**, the source stays unchanged.

Use **Browse archive** when you already know the reports are inside an archive. This skips the folder picker and opens the archive picker immediately.

### Select a database file

This area shows the current database destination.

- The text line shows either the selected file path or **None selected**.
- Click **Browse** to choose or create the destination **database file**.

The database button stays disabled until a source has been selected.

When the save dialog opens, Metroliza suggests a database name based on the selected source. If the suggested or typed name does not end in `.db`, Metroliza adds `.db` automatically. You can choose an existing `.db` file to add reports to it, or type a new filename to create a new database.

### Metadata mode

This controls how much report metadata Metroliza extracts during import.

- **Fast import - light metadata, no OCR**: imports quickly and skips OCR fallback for metadata fields.
- **Fast import, then enrich metadata**: imports quickly first, closes Parsing after the import succeeds, then starts a visible OCR metadata enrichment pass from the main window so you can keep using the app.
- **Complete import - OCR during parsing**: runs OCR fallback during parsing for stronger metadata coverage, but it is slower.

The default is **Fast import - light metadata, no OCR**.

### Parse reports

This starts the parsing job.

The **Parse reports** button is disabled until both of these are selected:

- a source, and
- a database file.

## Step-by-step example

Here is a simple example workflow.

1. Open **Parse Reports** from the main window.
2. Under **Reports directory or archive**, click **Browse folder**.
3. Choose a folder that contains the reports you want to import.
   - If the reports are in an archive, click **Browse archive** instead.
4. Under **Database file**, click **Browse**.
5. Choose a new or existing `.db` file. If you leave off `.db`, Metroliza adds it.
6. Choose the metadata mode you want.
7. Click **Parse reports**.
8. Wait for the progress dialog to finish.
9. After success, read the completion message and continue to [Export overview](export_overview.md).

## What happens while parsing runs

Parsing runs in a separate worker with a progress dialog.

While it runs, you will see:

- a progress bar,
- status text, and
- a **Cancel** button.

If you chose **Fast import, then enrich metadata** for a normal folder source, Parsing runs only the fast light import. After a successful import, the Parsing window closes and metadata enrichment continues from the main window.

Archive sources are the exception. Archives are unpacked into a temporary location while Parsing runs, so **Fast import, then enrich metadata** keeps the enrichment step inside the Parsing progress dialog for archive imports. This lets Metroliza read the extracted files before the temporary location is cleaned up.

### Cancel behavior

Cancel is **cooperative**, not an instant force-stop.

That means:

- clicking **Cancel** sends a stop request,
- the app then waits for the parser thread to stop safely,
- the dialog may briefly show a canceling message before it finishes.

This is expected. It helps the app stop cleanly instead of stopping mid-step.

## What happens after parsing

### If parsing succeeds

You get a success message telling you that the measurements were saved to the selected **database file**.

After that, the Parsing dialog closes.

Your next likely step is [Export overview](export_overview.md).

If some report files could not be parsed, the completion message says how many files were
saved and how many were skipped. Saved files remain available in the database. Skipped
files are listed in the log for follow-up.

If no supported report files were found in the selected source, the completion message says
that nothing was written. Choose a folder/archive that contains supported report files and
try again.

If the files are from a new supplier template that Metroliza does not recognize yet, do not try to fix that in Modify Database. Use **Tools > Parser profiles...** from the main window to prepare support for the new template, then parse again after the profile is approved and installed.

### If parsing is canceled

You get a message saying parsing was canceled.

The dialog then closes, and you can reopen Parsing if you want to try again.

### If parsing fails

You get a warning message with the error details that the parser returned.

After that, the Parsing dialog closes. Check the source files and selected destination, then try again.

## Troubleshooting / common mistakes

### “Parse reports” is disabled

This usually means one of the required selections is missing.

Check that you have selected both:

- a source, and
- a database file.

### I canceled the folder picker and nothing happened

That is normal if you answered **No** when the app asked whether to choose an archive file instead.

Click **Browse folder** again to choose a folder, or click **Browse archive** to choose an archive directly.

### My database filename changed to end in `.db`

That is expected.

Parsing writes to a SQLite database file. If the filename you typed does not already end in `.db`, Metroliza adds `.db` so the destination is clearly a database file.

### My supplier report template is not supported

Parsing can only import report templates that Metroliza knows how to read.

For a new supplier layout, open **Tools > Parser profiles...** and create a parser-profile handoff instead of editing the parsed database by hand.

### I expected a report file, but Parsing created a database file

That is the correct behavior.

Parsing creates or updates a **database file**. It does **not** create the final Excel report. To make the Excel report, use [Export overview](export_overview.md).

### Cancel did not stop instantly

That is expected.

Parsing uses a cooperative cancel flow, so the worker stops safely rather than being force-killed immediately.
