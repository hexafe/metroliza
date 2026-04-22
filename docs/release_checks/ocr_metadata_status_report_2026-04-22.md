# OCR Metadata Extraction Status Report

Date: 2026-04-22

Scope: verify current Metroliza report metadata extraction against
`/home/hexaf/Projects/example_reports` and identify why a Windows desktop run can
produce only filename-derived metadata even though standalone OCR works.

## Summary

The current local repository does not reproduce the filename-only failure when the
normal parser path is used with OCR dependencies and vendored RapidOCR models
available.

Evidence:

- `python scripts/validate_packaged_pdf_parser.py --require-header-ocr` passed and
  validated all 3 vendored model files.
- The 5 original `example_reports/extracted` PDFs all used
  `header_extraction_mode="ocr"` and selected metadata from `position_cell`
  candidates, not from filename fallback.
- A deterministic 10-folder sample across the full 4,333-PDF `example_reports`
  tree had `10/10` reports enter OCR mode and `0/10` filename-only reports.
- Focused metadata/OCR tests passed: `39 passed`.

The filename-only symptom was reproduced only when the parser could not use OCR:

- `METROLIZA_HEADER_OCR_BACKEND=none`
- `METROLIZA_HEADER_OCR_MODEL_DIR=/tmp/metroliza-no-models`

Both cases produced only filename candidates for reference/date/part/stats/sample
and no header-derived revision, time, operator, or comment.

## Verified Parser Path

The production parser path is:

1. `CMMReportParser.open_report()`
2. `_extract_first_page_header_items()`
3. `_ocr_header_items_from_pixmap()`
4. `extract_report_metadata()`
5. `select_report_metadata()`

For raster-header CMM reports, PyMuPDF structured words are usually empty in the
header band, so the parser must use RapidOCR. On the checked reports the parser
located the top raster header image, rendered the crop, ran RapidOCR, converted
OCR boxes back into page coordinates, and selected normalized position-cell
metadata.

Example successful result from
`V29091150_Body_EA211_1.0L_2020.01.28_4_1.pdf`:

- extraction mode: `ocr`
- OCR items: `12`
- required header fields found: `6`
- selected sources: `position_cell` for reference, date, time, part name,
  revision, stats count, operator, and comment
- selected reference: `V29091150_001`
- selected date/time: `2020-01-28 13:41`
- selected revision: `D.01`
- selected operator: `REX_GAZDA`

## Sample Results

Original extracted sample:

| Sample set | Checked | OCR mode | Filename-only |
| --- | ---: | ---: | ---: |
| `example_reports/extracted` | 5 | 5 | 0 |

Stratified tree sample:

| Folder | Result |
| --- | --- |
| `DV5R` | OCR mode, non-filename metadata |
| `DV6` | OCR mode, non-filename metadata |
| `DeltaP` | OCR mode, non-filename metadata, but some field accuracy issues |
| `EA211` | OCR mode, non-filename metadata |
| `EA897` | OCR mode, non-filename metadata |
| `EB_EP` | OCR mode, non-filename metadata |
| `GW` | OCR mode, non-filename metadata |
| `PAM_Bearing` | OCR mode, non-filename metadata, but some field accuracy issues |
| `eSC_Jaguar` | OCR mode, non-filename metadata, but some field accuracy issues |
| `extracted` | OCR mode, non-filename metadata |

The broader sample shows that OCR activation works, but some older or nonstandard
families still need profile/normalization improvements. Those accuracy issues are
separate from the filename-only failure.

## Root Cause Assessment

Most likely root cause: the Windows desktop executable/runtime is not reaching a
working RapidOCR path, even though the standalone OCR script does.

Why this is the leading explanation:

- The same PDF becomes filename-only when OCR is disabled or model lookup fails.
- The current local app-level parser succeeds on the sample reports.
- Standalone scripts can succeed using the source checkout or a developer venv, while
  the packaged desktop app may be using a different embedded environment and a
  different model-file location.

Concrete runtime conditions that would produce the observed symptom:

- the `.exe` was built before RapidOCR/model bundling was added,
- the `.exe` was built with `-AllowMissingHeaderOcrBuild`,
- `rapidocr`, `onnxruntime`, `cv2`, or `numpy` were not bundled/importable,
- the three ONNX model files were not bundled under
  `modules/ocr_models/rapidocr`,
- `METROLIZA_HEADER_OCR_BACKEND` is set to `none`, `off`, or another unsupported
  value,
- `METROLIZA_HEADER_OCR_MODEL_DIR` points to a missing/stale directory,
- an older database contains filename-only rows and the desktop build predates the
  stale-metadata refresh change.

The current branch includes a stale metadata refresh change:

- `07e209e Refresh stale CMM OCR metadata`

That change is important when re-parsing reports already present in an older
database. Without it, a user can keep seeing old filename-only rows even after OCR
code exists.

## What To Check On Windows

Run the diagnostic script from the Metroliza repo root with the same Python
environment used by your parser run:

```powershell
python scripts/diagnose_header_ocr_metadata.py path\to\report.pdf --db-file path\to\reports.sqlite
```

The `--db-file` argument is optional. Use it when you want to confirm whether an
existing database row is being reused or skipped.

Inspect one affected row in the SQLite database, especially
`report_metadata.metadata_json`.

Look for:

- `header_extraction_mode`
- `header_ocr_error`
- `field_sources`

Expected healthy OCR row:

```json
{
  "header_extraction_mode": "ocr",
  "header_ocr_engine": "rapidocr_latin",
  "field_sources": {
    "reference": "position_cell",
    "report_date": "position_cell"
  }
}
```

Expected broken OCR/model row:

```json
{
  "header_extraction_mode": "none",
  "header_ocr_error": "header_ocr_models_missing:..."
}
```

Expected disabled OCR row:

```json
{
  "header_extraction_mode": "none",
  "header_ocr_error": "header_ocr_disabled"
}
```

If `header_ocr_error` is present, the metadata selector is not the root cause; the
desktop runtime could not run OCR.

## Validation Commands Run

```bash
python scripts/validate_packaged_pdf_parser.py --require-header-ocr
python -m pytest tests/test_report_metadata_extractor.py tests/test_header_ocr_backend.py tests/test_header_ocr_geometry.py tests/test_header_ocr_corrections.py tests/test_packaged_pdf_parser_validation.py -q
```

Additional one-off parser diagnostics were run against
`/home/hexaf/Projects/example_reports` using `CMMReportParser.open_report()` and
`CMMReportParser.extract_metadata()` directly.

## Recommendation

For the Windows desktop build, verify the exact executable artifact, not only the
source checkout:

1. Rebuild from the current branch without `-AllowMissingHeaderOcrBuild`.
2. Confirm build output runs `scripts/validate_packaged_pdf_parser.py
   --require-header-ocr` before packaging completes.
3. Delete or reparse the old database rows using the current branch so stale
   filename-only records are refreshed.
4. If the symptom persists, collect `metadata_json` from one affected report row;
   the `header_ocr_error` value should identify whether the issue is missing
   models, disabled backend, or import failure.
