# #1100 - Review and correct report metadata before import

Status: implemented on `feat/1100-metadata-review-before-import`.
Spec: GitHub Issue #1100 ("Agreed behaviour (PO)" and MUST sections).

## PO decision (2026-10-17): the review is the preview

The first implementation put the metadata step behind an optional
**Review metadata...** button and a separate dialog. The Product Owner reworked
the requirement: *metadata review opens automatically; ideally it is the same
interactive preview where the summary of reports to import is now.* The
separate step, its dialog and its button are therefore removed. The agreed
behaviour of the issue is unchanged: fast read first (file name plus what is
detected from the report header, no OCR), then the user fills or corrects the
table manually **or** runs OCR and still corrects manually afterwards; manual
values always win; nothing is written to the database before Import.

## Summary

The reviewed-reports table of the report planner (`ReportPlanner`, shared by the
standalone `ParsingDialog` and the embedded `ReportsWorkspace`) carries the
metadata inline:

* When a review completes, a background **fast read** (`light`) starts
  automatically for every selectable (READY) report, in the order the table
  shows them. There is no modal progress: a status line ("Reading metadata
  37/120...") and a **Stop** button appear in the planner; unread cells show a
  neutral `...` placeholder.
* Columns after *Status*: **Reference, Part name, Sample no., Date** (visible),
  **Time, Revision, Operator, Comment** (hidden by default, toggled from the
  header context menu "Columns"), then Parser, Confidence, Reason / warning.
  Metadata columns stay visible in compact mode (the table scrolls
  horizontally); parser, confidence and reason hide below 850 px as before.
* Cells of editable rows edit in place (double-click, F2, Enter; Space still
  toggles the row checkbox). Input goes through `ReviewRow.set_user_value`
  and `normalize_review_value`; an invalid value (for example a bad date) is
  rejected with an inline message and the old value stays.
* Toolbar: **Copy to checked** (current cell's value to the same field of every
  checked editable report), **Reset to detected** (current report), **Read with
  OCR** (checked reports, in the background with progress and Stop). OCR is
  disabled with the reason as tooltip when the OCR backend is switched off or
  the models are missing (`ocr_unavailable_reason()`).
* Import sends `build_overrides(rows of the CHECKED reports)`.

## Data flow

```text
ParsePreflightResult (review, unchanged)
        |  on_preflight_completed -> ReportPlannerModel.set_review(result, carry=...)
        |  one pending ReviewRow per selectable READY occurrence
        v
MetadataReviewThread (QThread)  ui/metadata_review_worker.py      one active worker
  - MetadataReviewReader        parsing/metadata_review.py, Qt-free, no DB
    re-resolves each file (directory, single file, or re-extracted archive
    member), checks the review fingerprint, builds the parser with the reviewed
    parser id/generation, no connection, then open_report() + extract_metadata()
        |  one queued signal per report (MetadataReading)
        v
ReportPlannerModel.apply_reading   ui/report_planner_model.py
        |  ReviewRow state: reports/report_metadata_review.py (Qt-free)
        |  cell text/tooltip/style: ui/report_planner_metadata.py (Qt-free)
        v  inline edits -> ReviewRow.set_user_value
_ReportOperations._import_reviewed_reports                          ui/parsing_dialog.py
        |  ImportPlan.from_preflight(..., metadata_overrides=build_overrides(checked rows))
        v
ParseReportsThread.run()  -> parser.metadata_review_override
        v  CMMReportParser.extract_metadata() -> apply_metadata_override()
ReportRepository.import_report_if_absent(...)   (unchanged, atomic)
```

Seam: the override is applied inside `CMMReportParser.extract_metadata()`,
right after the normal extraction and before `canonical_metadata` and the
identity hash are computed. Both the single-stage and the two-stage import
paths, and `to_sqlite()`, therefore persist the overridden selection result
through the unchanged repository call. No parsing is duplicated at import.
Rows that were only fast-read produce no override (`ReviewRow.to_override()`
emits only user and OCR values): the import re-extracts the same values itself.

## Ownership

| Concern | Owner |
| --- | --- |
| Rows, edits, OCR merge rule, overrides | `reports/report_metadata_review.py` (Qt-free) |
| Reading (fast/OCR), fingerprint check, OCR availability | `parsing/metadata_review.py` (Qt-free) |
| Worker thread | `ui/metadata_review_worker.py` |
| Cell text, tooltips, accessible text, details, attention reasons | `ui/report_planner_metadata.py` (Qt-free) |
| One `ReviewRow` per selectable report, roles, colours, filters | `ui/report_planner_model.py` |
| Toolbar, status line, header menu, column layout, keyboard | `ui/report_planner.py` |
| Worker lifetime, import hand-off, readiness | `ui/parsing_dialog.py` (`_ReportOperations`) |

The planner stays execution-free: it emits `ocr_requested` and `stop_requested`;
the host owns the worker, exactly as it owns the preflight and parse workers.

## No database write before Import

The reader never receives a connection and parsers are constructed without one;
the destination file is not even created (tests assert the file does not exist
after review, fast read, OCR, edits and cancel). Changing the source,
database or metadata mode, a new review (except a refresh of the same source,
below), a workspace snapshot change, an invalidation and a finished import stop
the worker and discard the rows.

**Refresh review keeps edits.** `scan_reports` offers the current rows to the
next review of the same source; `ReportPlannerModel.set_review(carry=...)`
keeps a row only when occurrence id, content fingerprint and parser id are
unchanged (its manual edits and OCR values stay). Rows that had failed or
changed are read again; all others are not re-read. Any source/database/mode
change discards every row.

## Override keying and plan boundary

`ReportMetadataOverride` carries `occurrence_id` and the content `fingerprint`
of the plan's `SelectedReportIdentity`; display names are never keys (a test
imports two files with the same name in different folders). `ImportPlan` gets
one defaulted field, `metadata_overrides`. `validate_import_plan` rejects an
override for an unselected report, a fingerprint different from the reviewed
one, duplicates and wrong types. The existing checks are untouched: a source
that changes after review fails the per-file fingerprint check in the executor
(counted as changed, nothing written, the override is not applied to other
content), duplicate rules and the single repository transaction are unchanged.
The thread fails closed (that file is a parser failure, no write) if an
override is present but the resolved parser does not declare
`supports_metadata_review_override`.

## Table fields (and why)

Location, Status, Reference, Part name, Sample no., Date, Time, Revision,
Operator, Comment, then the existing read-only Parser, Confidence and
Reason / warning.

* Reference, part name, sample number and date are the issue's required
  columns. `report_metadata` has no separate "part number" column: the
  *reference* is the part number and *part_name* the description.
* Time, revision, operator and comment are the other editable
  `REPORT_METADATA_EDITABLE_FIELDS` that make sense for a person to type; they
  are normally only produced by OCR, so they are opt-in columns (header menu).
* `stats_count_*`, `sample_number_kind`, `reference_raw` and identity data are
  derived/internal and not editable here.

### Cell presentation (no extra columns)

One semantic style per cell (`report_planner_metadata.cell_style`); the model
maps it to colours from the theme layer (`ui_theme_tokens.theme_tokens`, so the
light and dark token sets), never to fixed colours:

| Cell | Look | Tooltip |
| --- | --- | --- |
| pending (not read yet) | muted italic `...` | waiting for the read |
| missing core value | italic `missing`, warning tint | "Missing: double-click or press F2" |
| low confidence (< 0.7, detected) | italic warning text | "Source: file name (40%)", "Low confidence: check this value." |
| entered by you | bold, accent colour | "Source: entered by you", "Detected value: ..." |
| OCR value | info colour | "Source: OCR" |
| OCR differs from your value | info tint | "OCR suggests X; your value is kept." |
| read-only report | muted `n/a` | the reason (changed since review, parser not editable) |

Accessible text is `"<report>, <field>: <value or missing>"`. Sources are
phrased "file name", "report header", "report statistics", "report comment",
"OCR" and "entered by you". The "Report details" pane lists, per field, the
value, source, confidence, other candidates (from the fast and OCR readings),
OCR conflicts and the row's notes and warnings. In high-contrast mode the
tints are not applied (bold/italic and the text placeholders remain).
Light/dark is read from the window palette; the host forwards palette changes
because the planner's own style sheet decouples its palette from the ancestors.

"Missing" applies to the four core fields only (OCR-only fields are often
legitimately blank); pending cells never count as missing.

### Needs attention and counts

The "Needs attention" filter and the counts line cover metadata attention in
addition to parser attention: a missing core value (in particular reference), a
low-confidence value, an OCR conflict, a failed read or a report that changed
since review. The line gains " - N missing reference". `model.counts` keeps its
five keys; metadata facts are in `model.metadata_counts`. Search also matches
metadata values (including hidden columns); sorting a metadata column orders by
the raw value.

## Missing reference: one definition

`is_missing_reference()` in `reports/report_metadata_normalizers.py`: `None`,
NaN, or empty after `str.strip()` (all Unicode whitespace) - the definition
Group Analysis uses in Python. The known SQL variant
(`NULLIF(TRIM(reference), '')`) trims only spaces, so tab/NBSP-only references
differ; the helper's docstring documents this. Existing callers are not
refactored; the planner uses the helper for highlighting, counts and the import
readiness summary.

## Provenance representation

At import, for every overridden field `apply_metadata_override`:

* sets the selected metadata value (`report_metadata.<field>`); `reference_raw`
  keeps the detected raw text;
* unselects the previously selected candidates of that field (they remain in
  `report_metadata_candidates` as detected values);
* user value: adds a selected candidate `source_type='user_manual'`,
  `source_detail='metadata_review'`, `confidence=1.0`; records
  `metadata_json.manual_overrides[field]` (`value`, `source='metadata_review'`,
  `updated_at`), the same structure Modify Database writes, so later OCR
  enrichment will not overwrite it; `field_sources[field]='user_manual'`;
* OCR value: selects the matching OCR candidate that the review's OCR run saw
  (its original `source_type` such as `position_cell`/`header_alias` is kept);
  without a matching candidate a synthetic `ocr_review` candidate is used;
* persists all candidates the OCR run saw as unselected detected candidates;
* writes `metadata_json.metadata_review` (`edited_fields`, `ocr_fields`,
  `ocr_run`, `detected_values` before the override, `applied_at`).

A user-cleared field imports as empty with no selected candidate. No warning
row is added (an info warning would flip `parse_status` to
`parsed_with_warnings`). Schema is unchanged; `sample_number_kind` stays within
the existing CHECK values (`unknown` for typed values).

## Threading and lifecycle

Fast read and OCR run in `MetadataReviewThread` using the Qt-free reader; results
come back as one queued signal per report and are merged on the GUI thread.
**Stop** sets a flag checked between reports (a single report's read or OCR call
cannot be interrupted); everything already read stays. One worker is active at a
time (OCR is disabled while the fast read runs).

* `ReportPlanner` never owns a thread; `_ReportOperations` (shared by
  `ParsingDialog` and `ReportsWorkspace`) holds `metadata_thread` (the worker
  whose results are shown) and `_metadata_threads` (every live worker). A thread
  stays referenced until its `finished` signal, so no running QThread is
  destroyed.
* Source/database/mode change, a new review, a snapshot change, invalidation and
  a finished import *retire* the active worker: cooperative stop, rows
  discarded, late readings of a retired worker are ignored (they carry the
  worker identity). `can_change_workspace()` is **not** blocked by the
  background read.
* `_workers_running()` and `_sync_readiness_state()` account for all metadata
  workers. `reject`, `closeEvent` and `request_shutdown` cancel them and defer
  until they stopped (the existing `_close_requested` / `shutdown_ready`
  pattern); `_request_active_worker_cancellation()` includes them.
* **Import never blocks on the fast read, and never runs beside it.** PyMuPDF
  must not run in two threads at once, so a scan, an import and a new metadata
  read are not started while a metadata worker is still alive. Clicking Import
  (or Refresh review) asks the worker to stop (cooperative cancel) and returns at
  once: the GUI thread never blocks (the repository guardrail forbids `.wait(` in
  the dialog). If the worker has already left its report the operation starts
  immediately; otherwise (a slow report, an archive being unpacked) it starts
  from the `finished` signal of the last metadata worker
  (`_defer_until_metadata_idle`), and the Import/Refresh buttons are disabled
  with "Stopping the metadata read..." meanwhile. The overrides are taken from the
  **checked** reports at the moment of the click, so an edit on an unchecked row is
  never imported. A new fast read after a review likewise waits for a retired
  worker of the previous review.
* **Import is disabled while OCR runs** (tooltip: Stop or wait).
* Failure text from the worker/reader is a fixed vocabulary, never exception
  text (document content can leak through exceptions); OCR diagnostics are
  reduced to coarse notes.

## OCR versus manual edits

Per cell the row keeps the auto value (fast or OCR) and an optional user value.

* Manual edit: value is normalized/validated per field (date/time must parse;
  invalid input is rejected with a message); typing the detected value again
  returns the cell to "detected".
* OCR: user-set cells are never changed. If OCR read a different value it is
  held as a suggestion (cell tinted, tooltip "OCR suggests X; your value is
  kept.", listed in the details pane); the user value is imported. For other
  cells OCR replaces the fast value only when its selected source is not the
  filename and the value differs; otherwise the fast detection and its
  provenance stay. Repeated OCR runs follow the same rules, so edits made after
  an OCR run survive the next one. The user can edit again after OCR.
* A late fast reading never replaces OCR or user values.

## Scope decisions and deferred

* The review is no longer a separate step: it is always on. Import still works
  immediately (identical to before when nothing is edited); a missing reference
  does not block import (highlighted, counted and filterable only). The
  readiness line shows "Metadata: N reports, N edited, N missing a reference"
  once every checked report has been read.
* Only parsers that declare `supports_metadata_review_override` (the built-in
  CMM parser) are editable. Rows for other parsers (declarative/profile or
  plugin parsers that produce `ParseResultV2` without selection candidates) are
  shown read-only (`n/a`, "imported as detected"). Seam for later: add an
  override hook to `build_persistence_payload()` and let those parsers declare
  support. Owner/target: follow-up to #1100.
* OCR uses the same `complete` extraction path as the post-import enrichment; it
  requires the OCR runtime and models. `ocr_unavailable_reason()` mirrors the
  checks made before the engine is imported (backend setting, model files); the
  engine import itself is not probed because packaged builds run it in a private
  worker, so a missing runtime shows up as a coarse OCR note after a run. With
  "Complete import - OCR during parsing" selected the import repeats OCR.
  Archive sources are re-extracted for each read (the review scan's temporary
  extraction is gone).
* The old "Use OCR values for edited cells..." bulk replacement is gone: manual
  values always win, a conflict is shown on the cell and "Reset to detected"
  drops the manual edit. Column widths, visibility of optional columns and the
  attention filter are not persisted (the separate dialog persisted widths).
* Deferred per the issue: learning rules from corrections, editing measurement
  rows.
* Not verified here: real OCR runtime (rapidocr/onnxruntime) and Windows; OCR
  is tested through the existing `_ocr_header_items_from_pixmap` fake seam.

## Tests

* `tests/test_metadata_review_core.py`: shared missing-reference rule, fast
  prefill without a DB, missing flags, changed source, archives, cancel, manual
  edit, bulk apply, OCR merge rules, plan validation and keying, repository
  read-back of imported values and provenance rows, cancel, plan invalidation on
  source change, fail-closed unsupported parser.
* `tests/test_metadata_review_ui.py` (for `ParsingDialog` and `ReportsWorkspace`,
  with `tests/metadata_review_fakes.py` for a deterministic reader): automatic
  fast read in table order with pending placeholders, read-only rows, inline and
  keyboard editing, invalid date rejected, copy to checked / reset, optional
  columns, OCR (non-edited fields filled, manual kept, conflict in tooltip and
  details, unavailable reason), import with overrides for checked rows only,
  import stopping a running read (fast and slow report), refresh review and a new
  read queued behind a stopping worker, import disabled during
  OCR, context/mode change, retired worker, refresh keeping edits (also through
  `scan_reports`), deferred close/shutdown, attention filter, search, sorting,
  readiness summary, light/dark colours from the theme tokens with contrast
  checks, a real-reader run off the GUI thread proving the destination is never
  created before import, and the Qt-free presentation helpers.
* `tests/test_report_planner_model.py`: per-report rows, carry rules, counts.
* `tests/test_report_planner_geometry.py` / `tests/test_report_workspace_geometry.py`:
  the toolbar and the metadata columns fit the compact and large layouts.
