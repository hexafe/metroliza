# Import reports

Use **Reports** to review report files and import a chosen subset into a local SQLite
**database file**. The planner lives in the main **Reports** workspace. From **Home**, choose
**Wybierz folder raportów…** or **Wybierz archiwum…** to open the planner with that source.
Moving between Home, Reports and Tools preserves the review, global selection, filters,
active operation and last outcome during the session.

## Review and select

1. Choose **Browse folder** or **Browse archive**. Supported report formats are recognized
   from their contents by the installed parsers. Cancelling either picker keeps the current source.
2. Choose an existing or new **Database file** with **Browse**. A destination is required
   before review. Existing file names are kept exactly, including `.sqlite`, `.sqlite3`
   and uppercase extensions. Only a new name without an extension receives `.db`.
3. Choose **Metadata detail**.
4. Click **Review reports**. This inspects report contents without writing to the destination
   or running OCR. Review can be cancelled in its progress window.
5. Inspect the persistent table. Every fresh **Ready to import** report is selected by default.
   **Already imported**, **Unsupported format**, **Ambiguous parser** and **Unreadable** rows
   cannot be selected. An already-imported label records a match seen during review; the
   final import outcome separately reports what the database actually accepted.
6. Use search, status, parser or **Needs attention** filters to narrow the visible rows.
   The counter shows the total selection and how many selected reports are hidden.
   To import only matching rows, use **Clear selection**, then click **Zaznacz widoczne (N)**.
   Adding visible reports preserves any earlier checks outside the filter.
7. Click **Import N selected reports**. The number includes selected rows hidden by filters.
   An empty selection starts no import and makes no database changes.

For a small batch, review and import the default selection. For a large mixed batch, filter,
inspect **Report details**, and choose a subset first. Space toggles the focused ready row,
including when focus is in a text column. Non-ready rows remain uncheckable. Archive locations
are stable member-relative paths, rather than temporary extraction folders.

## Metadata detail

- **Fast import - light metadata, no OCR** is the default. Import uses light metadata without
  OCR fallback.
- **Fast import, then enrich metadata** imports first, then performs a visible enrichment
  stage in the same owned operation. Enrichment covers only selected reports accepted by the
  import, including a selected report that another operation saved before this import reached
  it. It does not launch a database-wide enrichment pass.
- **Complete import - OCR during parsing** enables OCR fallback during import. It can take
  longer. Review itself still does not execute OCR.

In the review table, **Read with OCR** can supply missing metadata. If OCR differs from a
value you entered or accepted, the cell keeps that value and shows the suggestion in its
tooltip and report details. Compare it with the report, select the cell, then open **Metadata**.

- **Use OCR suggestion** replaces the current value with the suggestion.
- **Keep current value** rejects this reading. A different reading can still offer a new suggestion.
- **Review later** keeps the current value and marks the suggestion as deferred. Select the cell
  again to use or reject the suggestion before importing. A different reading appears as a new suggestion.

Import saves accepted values with their OCR source and records deferred or rejected suggestions
with their source details. Later metadata enrichment keeps reviewed values and records different
readings as alternatives. You can still correct the value before import or in **Modify Database**.
After import, select a report in **Modify Database** and open **Report details** to read its saved
deferred or rejected suggestions and their OCR sources.
To accept a deferred suggestion, select its field, choose **Use OCR suggestion**, and confirm
the value. Finish pending table edits first. If the saved suggestion changed, reopen **Report
details** before deciding again.

## Progress, cancellation and outcomes

The progress window shows the current stage and cooperative **Cancel** action while the main
workspaces remain available. New database workflows wait until the report operation finishes.
An idle Export Workbook form can stay open during import. Finish an active export and close
other workflows that hold the same database before starting a review or import. Cancellation
waits for the active unit of work to finish safely; reports already committed remain saved.
Closing the main window while work is active requests cancellation and defers closing until
the worker stops. Home also shows the active report stage and a cancellation button.
A second review or import cannot start during an active operation. Source and database
changes are rejected while work is active, so the displayed context stays with that operation.

The persistent **Last import outcome** and its Home summary distinguish saved reports,
already-present reports, intentionally excluded reports, changed reports, failures and
cancellation. The review snapshot and metadata-enrichment result remain separate groups.
A successful import does not imply enrichment succeeded.

After import the table switches to read-only **last import results**, one row per reviewed
occurrence. **Saved** and **Already present** require that report's persistence receipt.
**Skipped** means it was not submitted. **Failed** identifies a report-processing failure.
**Cancelled** identifies a report confirmed to be unfinished when import stopped. **Unknown**
means the outcome for that report could not be confirmed. Check the destination before retrying.
Reports with the same filename in different folders keep their separate source-relative identities.

Counters describe results, and **Needs attention**, status, parser and search filters still
work. Historical rows cannot be checked or edited. Use **Eksportuj partię (N)** to export the
reports saved by the latest attempt, or **Eksportuj całą bazę** to work with the full database.

### Resume import

When the planner can verify which selected reports finished, **Resume import (N)** retries
the cancelled or failed reports from that selection, including their approved metadata
edits. Reports already saved or confirmed present are left untouched. The outcome includes
the reports completed in earlier attempts. A resumed attempt runs the chosen metadata mode
for its own reports.

The worker rechecks the remaining source files and parser approvals, and verifies that the
destination is still the same file. Choose **Review again** if the source or parser has changed,
the destination was replaced, or the previous outcome could not be confirmed. Changing the
source, destination or metadata detail clears the resume action. The action is available in
the current session after cancellation or a report failure.

**Report details** shows parser identifiers, confidence, reason codes, competing parsers and
bounded technical evidence. It does not show raw report contents or raw parser exceptions.
At compact window sizes secondary columns are available through details; the table remains
the main scrolling region. Larger windows expose resizable parser/confidence/reason columns.

After checking the actual import outcome, continue to [Modify Database](modify_database.md)
or [Export overview](export_overview.md) using the actions below the Reports planner.
The standalone Parsing window used by older entry points shares the same report controls
and operation behavior; the main application does not open a second report window.
