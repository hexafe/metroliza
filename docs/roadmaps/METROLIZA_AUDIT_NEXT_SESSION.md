# Metroliza Audit Next Session

Last updated: 2026-04-29

## Start Here

Branch: `codex/report-metadata-redesign`

The current audit pass has validated, uncommitted changes in:

- `docs/perf_baseline.md`
- `modules/distribution_fit_service.py`
- `modules/report_schema.py`
- `scripts/benchmark_paths.py`
- `tests/test_distribution_fit_service.py`
- `tests/test_schema_index_query_plans.py`

All benchmark and test additions use synthetic data only. Do not add real reports,
real report-derived filenames, customer names, or customer-derived values to the
repository, including benchmark artifacts.

## Completed In This Pass

1. Added export benchmark stage timing for workbook close, write-vs-shape,
   high-header distribution/histogram/trend payloads, and CSV summary writes.
2. Added Monte Carlo AD p-value caching for repeated distribution-fit spec
   refits using the existing `memoization_cache`.
3. Added `idx_source_file_locations_latest_active` for latest active source file
   location lookups.
4. Audited OCR packaging/confidentiality posture. Source-level OCR validation
   passed and tracked files had no exact hits against ignored 272-PDF manifest
   filename/stem tokens.

## Validation Already Run

```bash
python -m pytest tests/test_benchmark_paths.py tests/test_distribution_fit_service.py tests/test_schema_index_query_plans.py tests/test_report_schema_repository.py -q
python -m ruff check scripts/benchmark_paths.py modules/distribution_fit_service.py modules/report_schema.py tests/test_benchmark_paths.py tests/test_distribution_fit_service.py tests/test_schema_index_query_plans.py
git diff --check
python scripts/validate_packaged_pdf_parser.py --require-header-ocr
```

Result: focused tests passed (`45 passed`), ruff passed, diff check passed, and
packaged OCR dependency/model validation passed.

Integrated synthetic benchmark:

```bash
python -m scripts.benchmark_paths \
  --output-dir /tmp/metroliza_audit_integrated \
  --scenarios excel_export_path excel_export_write_vs_shape_path excel_export_high_header_cardinality_compare csv_summary_export_path distribution_fit_monte_carlo_path \
  --report-count 12 \
  --headers-per-report 8 \
  --csv-rows 120 \
  --csv-columns 3 \
  --fit-group-count 6 \
  --fit-sample-size 60 \
  --fit-monte-carlo-samples 60
```

Output:

- `/tmp/metroliza_audit_integrated/benchmark-20260429-080233.json`
- `/tmp/metroliza_audit_integrated/benchmark-20260429-080233.csv`

Key readings:

- High-header export: `before_refactor=1.323s`, `after_refactor=1.320s`,
  `speedup_ratio=1.00x`.
- High-header distribution payload dominates: about `1.13s` to `1.14s`.
- Monte Carlo path: uncached `0.480s`, cached spec refit `0.266s`,
  cached/uncached ratio `0.55`.
- CSV summary: `0.113s` wall, workbook write `0.060s`.
- Excel write-vs-shape: shaping `0.121s`, worksheet ops `0.038s`.

## Next Priority Order

1. Commit the current validated improvements.
2. Optimize high-header export distribution payload generation. The current
   benchmark shows worksheet mechanics are not the bottleneck for that path.
   Start with violin/distribution payload construction, sampling policy, repeated
   group/category work, and payload caching.
3. Add a non-blocking export performance trend check using the new stage keys.
   Do not make it a hard CI gate until the baseline is stable.
4. Run clean-machine Windows packaged EXE smoke. Source OCR validation is green,
   but release confidence still needs packaged artifact launch/parser evidence.
5. Return to DB bulk-update APIs for Modify DB flows after export and Windows
   release evidence are handled.

## Do Not Rerun By Default

- Do not rerun the full 272-PDF OCR benchmark unless OCR/parser behavior changes.
- Do not reopen broad test deletion; the test cleanup roadmap is frozen except
  for named stale/duplicate tests with explicit replacement coverage.
- Do not add Rust/native work for workbook writing, dashboard HTML, or UI paths.
