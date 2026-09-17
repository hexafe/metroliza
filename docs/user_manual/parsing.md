# Import reports

Use **Reports** to review report files and import a chosen subset into a local SQLite
**database file**. The current main-window **Parse Reports** entry opens this planner.
Moving the planner into the main Reports page is the separate #1016 shell delivery.

## Review and select

1. Choose **Browse folder** or **Browse archive**. Supported report formats are recognized
   from their contents by the installed parsers. Cancelling the folder picker still offers
   the existing archive picker.
2. Choose an existing or new **Database file** with **Browse**. A destination is required
   before review; a missing `.db` suffix is added by the picker.
3. Choose **Metadata detail**.
4. Click **Review reports**. This inspects report contents without writing to the destination
   or running OCR. Review can be cancelled in its progress window.
5. Inspect the persistent table. Every fresh **Ready to import** report is selected by default.
   **Already imported**, **Unsupported format**, **Ambiguous parser** and **Unreadable** rows
   cannot be selected. An already-imported label records a match seen during review; the
   final import outcome separately reports what the database actually accepted.
6. Use search, status, parser or **Needs attention** filters to narrow the visible rows.
   Filtering and sorting never change selection. The counter distinguishes **selected overall**
   from **visible** rows. **Select all ready** and **Clear selection** always affect the whole
   review, including hidden rows.
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

## Progress, cancellation and outcomes

The progress window shows the current stage and cooperative **Cancel** action. Cancellation
waits for the active unit of work to finish safely; reports already committed remain saved.
Closing the planner while work is active requests cancellation and defers closing until the
worker stops. A second review or import cannot start during an active operation.

The completion message and persistent **Last import outcome** distinguish saved reports,
already-present reports, intentionally excluded reports, changed reports, failures and
cancellation. The review snapshot and metadata-enrichment result remain separate groups.
A successful import does not imply enrichment succeeded.

Changing the source, destination or metadata detail invalidates the complete review and
selection. After import, review again before another import. Source content and parser
approvals are checked again by the import worker; **Changed since review** items cannot be
silently imported using stale approval.

**Report details** shows parser identifiers, confidence, reason codes, competing parsers and
bounded technical evidence. It does not show raw report contents or raw parser exceptions.
At compact window sizes secondary columns are available through details; the table remains
the main scrolling region. Larger windows expose resizable parser/confidence/reason columns.

After checking the actual import outcome, continue to [Modify Database](modify_database.md)
or [Export overview](export_overview.md) using the existing main-window actions. The planner
remains open until you close it.
