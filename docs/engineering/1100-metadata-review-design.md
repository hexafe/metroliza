# #1100 - Review and correct report metadata before import

Status: implemented on `feat/1100-metadata-review-before-import`.
Spec: GitHub Issue #1100 ("Agreed behaviour (PO)" and MUST sections).

## Summary

After **Review reports**, the selected READY reports can go through an optional
**Review metadata...** step in the import dialog. Metadata is read in fast mode
(`light`: file name plus embedded header text) without any database access and
is shown in an editable table. The user fills or corrects values, applies one
value to many rows and may run OCR (`complete` mode) on selected or all rows,
off the GUI thread, with progress and Stop. Import then writes the values shown
in the table. Detected values stay as candidates; user values are added as
selected `user_manual` candidates.

## Data flow

```text
ParsePreflightResult (review, unchanged)
        |  selected READY occurrence ids
        v
MetadataReviewReader            parsing/metadata_review.py, Qt-free, no DB
  - re-resolves each file (directory, single file, or re-extracted archive member)
  - checks the review fingerprint, builds the parser with the reviewed parser
    id/generation, no connection, then open_report() + extract_metadata()
        |  MetadataReading (MetadataSelectionResult, coarse notes)
        v
MetadataReviewThread (QThread)  ui/metadata_review_worker.py
        |  signal per report, cancel flag checked between reports
        v
MetadataReviewModel/Panel/Dialog   ui/metadata_review_{model,dialog}.py
        |  ReviewRow state: reports/report_metadata_review.py (Qt-free)
        v  ReviewRow.to_override() -> ReportMetadataOverride
ParsingDialog._import_reviewed_reports
        |  ImportPlan.from_preflight(..., metadata_overrides=...)
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

## No database write before Import

The reader never receives a connection and parsers are constructed without one;
the destination file is not even created (tests assert the file does not exist
after fast read, OCR, edits and cancel). Cancelling the dialog discards the
session's edits: the dialog works on deep copies of the stored rows and the
caller only keeps them on Accept. Any change to the source/database/mode,
a new review or a finished import clears the stored rows (`_invalidate_preflight`).

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

Report, Reference, Part name, Sample no., Date, Time, Revision, Operator,
Comment, plus read-only Source, Confidence and Warnings.

* Reference, part name, sample number and date are the issue's required
  columns. `report_metadata` has no separate "part number" column: the
  *reference* is the part number and *part_name* the description.
* Time, revision, operator and comment are the other editable
  `REPORT_METADATA_EDITABLE_FIELDS` that make sense for a person to type; they
  are normally only produced by OCR, so the table shows what OCR adds.
* `stats_count_*`, `sample_number_kind`, `reference_raw` and identity data are
  derived/internal and not editable here.

"Missing" (highlighted, counted, filterable) applies to the four core fields.
"Low confidence" means a detected core value whose selected candidate has
confidence below 0.7 (filename-only part name/sample number qualify by design
of the existing scoring). The filter "Only missing / low confidence" shows rows
with either. Column widths and the filter are remembered through
`UiPreferences` (`presentation/metadata_review/*`) when the host provides it.

## Missing reference: one definition

`is_missing_reference()` in `reports/report_metadata_normalizers.py`: `None`,
NaN, or empty after `str.strip()` (all Unicode whitespace) - the definition
Group Analysis uses in Python. The known SQL variant
(`NULLIF(TRIM(reference), '')`) trims only spaces, so tab/NBSP-only references
differ; the helper's docstring documents this. Existing callers are not
refactored; the new step uses the helper for highlighting, counts and the import
dialog summary.

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

## Threading

Fast read and OCR run in `MetadataReviewThread` (QThread) using the Qt-free
reader; results come back as one queued signal per report and are merged on the
GUI thread. Progress is an inline bar; **Stop** sets a flag checked between
reports (a single report's OCR call cannot be interrupted). Everything already
read stays. Closing the dialog while a worker runs stops it and closes when it
has finished; "Use these values" is disabled while busy. Failure text from the
worker/reader is a fixed vocabulary, never exception text (document content
can leak through exceptions); OCR diagnostics are reduced to coarse notes.

## OCR versus manual edits

Per cell the row keeps the auto value (fast or OCR) and an optional user value.

* Manual edit: value is normalized/validated per field (date/time must parse;
  invalid input is rejected with a message); typing the detected value again
  returns the cell to "detected".
* OCR: user-set cells are never changed. If OCR read a different value it is
  held as a suggestion (cell tinted, tooltip) and replaced only after the user
  confirms **Use OCR values for edited cells...** (default answer No). For
  other cells OCR replaces the fast value only when its selected source is not
  the filename and the value differs; otherwise the fast detection and its
  provenance stay. Repeated OCR runs follow the same rules, so edits made after
  an OCR run survive the next one. The user can edit again after OCR.
* A late fast reading never replaces OCR or user values.

## Scope decisions and deferred

* The step is **optional**: Import still works directly (identical to today
  when no override exists). A mandatory step would change the existing flow
  and its tests; the readiness line shows "Metadata: N reports, N edited, N
  missing a reference" once the step was used. A missing reference does not
  block import (highlighted and counted only).
* Only parsers that declare `supports_metadata_review_override` (the built-in
  CMM parser) are editable. Rows for other parsers (declarative/profile or
  plugin parsers that produce `ParseResultV2` without selection candidates) are
  shown read-only, "imported as detected". Seam for later: add an override hook
  to `build_persistence_payload()` and let those parsers declare support.
  Owner/target: follow-up to #1100.
* OCR in the Metadata step uses the same `complete` extraction path as the
  post-import enrichment; it requires the OCR runtime and models. With
  "Complete import - OCR during parsing" selected the import repeats OCR.
  Archive sources are re-extracted for each read (the review scan's temporary
  extraction is gone).
* Deferred per the issue: learning rules from corrections, editing
  measurement rows, embedding in the unified Reports workspace (the panel
  `MetadataReviewPanel` is host-agnostic for that).
* Not verified here: real OCR runtime (rapidocr/onnxruntime) and Windows; OCR
  is tested through the existing `_ocr_header_items_from_pixmap` fake seam.

## Tests

* `tests/test_metadata_review_core.py`: shared missing-reference rule, fast
  prefill without a DB, missing flags, changed source, archives, cancel,
  manual edit, bulk apply, OCR merge rules, plan validation and keying,
  repository read-back of imported values and provenance rows, cancel, plan
  invalidation on source change, fail-closed unsupported parser.
* `tests/test_metadata_review_ui.py`: model editing/validation/highlighting,
  off-GUI-thread read and OCR, bulk apply/reset, OCR confirmation, OCR cancel
  keeping results, deferred close, ParsingDialog hand-off into the plan,
  cancelled step discards edits, UiPreferences.
