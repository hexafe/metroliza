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
- a supported archive file, if you do not choose a directory first.

## Buttons and fields

### Select a source (directory or archive file)

This area shows the current source selection.

- The text line shows either the selected path or **None selected**.
- Click **Browse** to choose where Parsing should read reports from.

### How source selection works

The dialog tries **directory selection first**.

1. Click **Browse**.
2. The app first asks you to select a directory.
3. If you do select a directory, that becomes the source.
4. If you do **not** select a directory, the app asks:
   **“No directory was selected. Do you want to choose an archive file instead?”**
5. If you answer **Yes**, you can choose a supported archive file.
6. If you answer **No**, the source stays unchanged.

This means the normal path is folder-first, with archive selection as a fallback.

### Select a database file

This area shows the current database destination.

- The text line shows either the selected file path or **None selected**.
- Click **Browse** to choose or create the destination **database file**.

The database button stays disabled until a source has been selected.

### Parse reports

This starts the parsing job.

The **Parse reports** button is disabled until both of these are selected:

- a source, and
- a database file.

## Step-by-step example

Here is a simple example workflow.

1. Open **Launch Parsing** from the main window.
2. Under **Select a source (directory or archive file)**, click **Browse**.
3. Choose a folder that contains the reports you want to import.
   - If you cancel directory selection, you can choose a supported archive instead.
4. Under **Select a database file**, click **Browse**.
5. Choose a new or existing `.db` file.
6. Click **Parse reports**.
7. Wait for the progress dialog to finish.
8. After success, read the completion message and continue to [Export overview](export_overview.md).

## What happens while parsing runs

Parsing runs in a separate worker with a progress dialog.

While it runs, you will see:

- a progress bar,
- status text, and
- a **Cancel** button.

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

Click **Browse** again if you want to choose a source.

### I expected a report file, but Parsing created a database file

That is the correct behavior.

Parsing creates or updates a **database file**. It does **not** create the final Excel report. To make the Excel report, use [Export overview](export_overview.md).

### Cancel did not stop instantly

That is expected.

Parsing uses a cooperative cancel flow, so the worker stops safely rather than being force-killed immediately.
