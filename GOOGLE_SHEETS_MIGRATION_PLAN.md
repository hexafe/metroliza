# Google Sheets Migration Plan (from Excel `.xlsx` export)

## Goal
Migrate Metroliza export output from Excel-first (`xlsxwriter`) to Google Sheets-compatible export while keeping all current analytical output:
- raw measurement tables,
- computed statistics,
- per-header trend charts,
- summary matplotlib/seaborn plots.

---

## Current-state constraints to address
The current export path writes `.xlsx` files with `xlsxwriter` and injects chart series (including USL/LSL) using Excel-specific chart APIs and in-memory array literals. These constructs are not directly portable to Google Sheets API chart definitions and can break compatibility.

Key constraints in current implementation:
1. Horizontal-sheet export is tightly coupled to `xlsxwriter` workbook/worksheet/chart calls.
2. USL/LSL chart series are generated via per-row in-memory list literals (`={1,1,1...}` style), which are Excel-oriented.
3. Formulas and chart ranges are built using Excel A1 ranges and helper utilities.
4. Summary images are generated via matplotlib/seaborn and inserted into worksheets; Google Sheets needs explicit image insertion strategy.

---

## Proposed target architecture
Introduce an **export backend abstraction** with two writers:
- `ExcelExportBackend` (existing behavior retained).
- `GoogleSheetsExportBackend` (new behavior using Google Sheets API).

Shared data prep logic should remain backend-agnostic:
- grouping/sorting,
- statistics calculations,
- USL/LSL/NOM resolution,
- plot rendering to PNG buffers.

Only output mechanics (sheet creation, cells, formulas, charts, image placement) should differ by backend.

---

## Implementation phases

### Phase 0 — Contract & UX changes
1. Add export target option in UI/contracts:
   - `excel_xlsx` (default),
   - `google_sheets`.
2. Extend `ExportOptions` validation to include target backend and Google destination metadata (spreadsheet id or create-new flag).
3. Keep current `.xlsx` flow unchanged for backwards compatibility.

Deliverable: no behavior change for Excel users, but request payload can select Google Sheets.

---

### Phase 1 — **First requested step**: explicit max/min limits + USL/LSL series columns (Google-compatible)
This phase implements exactly what you described as first priority.

#### 1.1 Data layout update per header block
In the measurement table area (same region as measurement values, adjacent to statistics header), add two new columns:
- `USL_SERIES`
- `LSL_SERIES`

Populate each row with constant values:
- `USL_SERIES[row] = NOM + +TOL`
- `LSL_SERIES[row] = NOM + -TOL`

Also write explicit scalar helper cells near stats header:
- `USL_MAX`, `USL_MIN` (both equal to USL),
- `LSL_MAX`, `LSL_MIN` (both equal to LSL).

Why include these pairs:
- they provide deterministic anchor values for downstream chart construction,
- they allow both line-series and 2-point trendline style generation in Google Sheets,
- they satisfy your requirement of “2x USL and 2x LSL next to statistics header.”

#### 1.2 Series construction update
Replace array-literal based chart series with **cell-range based series** only.

- Measurement series: existing measurement column range.
- USL series: `USL_SERIES` column range.
- LSL series: `LSL_SERIES` column range.

This structure is portable to Google Sheets chart specs because all series are explicit grid ranges.

#### 1.3 Trendline/limit line behavior
Create upper/lower spec limit visuals from the two-point anchors (`USL_MAX/MIN`, `LSL_MAX/MIN`) and/or from full constant columns:
- preferred: full constant columns as dedicated line series,
- optional fallback: 2-point helper data with chart trendline enabled (if needed by chart type).

Acceptance criteria for Phase 1:
- USL/LSL visible as separate chart series using ranges (not array literals),
- helper cells contain 2x USL + 2x LSL near stats header,
- chart output equivalent in Excel and mappable to Google Sheets.

---

### Phase 2 — Backend abstraction and writer split
1. Refactor current `add_measurements_horizontal_sheet` into:
   - shared “layout + data model builder” function,
   - backend-specific renderer.
2. Implement `ExcelExportBackend` as thin wrapper around current worksheet/chart calls.
3. Implement `GoogleSheetsExportBackend` with batched API operations:
   - sheet creation,
   - batch cell writes,
   - formulas/ranges,
   - chart specs.

Acceptance criteria:
- no duplication of grouping/stat logic,
- backend unit tests confirm equivalent grid content for core stats/series.

---

### Phase 3 — Google Sheets charts parity
For each header chart, generate Google Sheets BasicChartSpec (line or scatter parity with current option):
- categories: Sample # / x-axis range,
- series 1: measurements,
- series 2: USL,
- series 3: LSL.

Set style rules:
- USL/LSL red lines,
- no markers on limit lines,
- hide legend optionally to match current compact layout.

Acceptance criteria:
- charts render correctly in Google Sheets with persistent USL/LSL lines,
- no Excel-only formula/literal dependency.

---

### Phase 4 — Matplotlib/seaborn summary plots in Google Sheets
Current summary plots are rendered to PNG buffers. For Google Sheets:
1. Persist PNGs to temporary files or in-memory upload staging.
2. Upload/host images in a retrievable location (Drive file, public URL, or app-managed storage).
3. Insert images into target sheet using Google Sheets image insertion method (`=IMAGE(url)` or AddImageRequest equivalent based on chosen API path).
4. Maintain row spacing/layout so each header keeps the same visual grouping as current summary sheet.

Acceptance criteria:
- all 4 summary plot types preserved (scatter/group, histogram+density+stats table, trend plot with USL/LSL, violin where applicable),
- images anchored consistently and reproducibly.

---

### Phase 5 — Security, auth, and operations
1. Add Google OAuth/service-account configuration path.
2. Define scopes minimally (`spreadsheets`, optional `drive.file` for image handling).
3. Add retry/backoff for API quotas and transient errors.
4. Add progress labels for “uploading sheet/charts/images”.

---

### Phase 6 — Testing strategy
1. Unit tests
   - series column generation (USL/LSL constants),
   - helper anchor cells (2x USL/2x LSL),
   - backend-neutral layout model.
2. Integration tests
   - Excel export unchanged,
   - Google Sheets export smoke test with mock API,
   - chart spec validation for measurement+USL+LSL series.
3. Visual regression checks
   - compare generated PNG plots baseline hashes,
   - spot-check chart data ranges.

---

## Detailed task list for your requested first step
1. Extend header-block writer to allocate two additional data columns (`USL_SERIES`, `LSL_SERIES`).
2. Write 2x USL and 2x LSL helper values near current stats header cells.
3. Update chart series source from inline arrays to sheet cell ranges.
4. Validate limit lines visually in Excel backend (parity check before Google backend).
5. Add tests for:
   - series columns filled for all rows,
   - helper cells populated,
   - chart series config references ranges.

---

## Risks and mitigations
- **Risk:** Google Sheets chart feature gaps vs Excel chart options.
  - **Mitigation:** normalize on supported subset (line/scatter + fixed styling).
- **Risk:** image insertion complexity for matplotlib outputs.
  - **Mitigation:** phase-gate with URL-based insertion first, then optimize storage flow.
- **Risk:** large exports hitting API limits.
  - **Mitigation:** batchUpdate chunking + exponential backoff + resumable progress states.

---

## Success definition
Migration is complete when:
1. User can choose Google Sheets export target.
2. Raw and summary sheets are generated with equivalent data/statistics.
3. All charts include measurement, USL, and LSL series.
4. USL/LSL are represented via Google-compatible sheet ranges.
5. Matplotlib/seaborn summary plots are visible in Google Sheets.
