# Metroliza

Industrial metrology data analysis and automation tool built in Python.

## Overview

**Metroliza** is a Python-based tool designed to automate the processing and analysis of metrology and production measurement data used during component validation and quality investigations.

The project started as a learning exercise and gradually evolved into an internal tool used by Quality and R&D engineers to reduce manual analysis effort and improve insight generation.

## Problem Statement

In component validation and production quality analysis, measurement data is often delivered in:
- PDF measurement reports,
- compressed archives containing multiple reports,
- CSV exports from production databases.

Manual analysis of this data is:
- time-consuming,
- error-prone,
- difficult to compare across OK / NOK parts.

## Solution

Metroliza provides an end-to-end data processing pipeline that:

- Parses measurement data from **PDF files**, **ZIP archives** - for metrology data, and **CSV files** - for production parameters data
- Formats and stores processed data in a **SQLite database**
- Enables **grouping/labeling** of parts (e.g. OK vs NOK)
- Generates **Excel reports** with:
  - statistical summaries (min, max, standard deviation, Cp, Cpk, USL and LSL automatically read from report)
  - violin plots for grouped comparisons (OK vs NOK)
  - scatter and line charts for all measured characteristics - sample number or timestamp as X-axis
- Allows filtering and hiding columns with OK parts - for non-conformities analysis and supporting root cause investigations

The output is a clear, visual, and engineer-friendly report that supports decision-making during validation, quality reviews, and process investigations.

## Key Features

- PDF parsing of metrology reports  
- Batch processing from directories and compressed archives  
- SQLite-based data storage and manipulation  
- Data grouping/labeling (OK / NOK logic)  
- Automated Excel report generation with statistics and visualizations  
- Statistical analysis and visualization of production parameters
- Standalone executable generation using PyInstaller (one-file build) for non-technical stakeholders

## Technologies Used

- **Python**
- **Pandas**
- **NumPy**
- **SQLite**
- **Matplotlib**
- **Excel automation**
- **CSV processing**
- **PDF parsing libraries**
- **PyInstaller** (one-file executable packaging)

## Typical Use Case

1. Collect metrology measurement reports (PDF/compressed) from validation or production
2. Run Parser to extract the data
3. Store results in SQLite for structured access
4. Optionally: Group parts (for example as OK/NOK) and/or filter by parts reference/measurement/date
5. Generate Excel reports with visual and statistical comparisons
6. Use insights to support quality decisions and root cause analysis (PDCA/FTA)

## Users

- Quality Engineers  
- R&D Engineers  
- Validation Engineers  

The tool was actively used to support component validation and production quality analysis.

## Deployment & Usability

To enable usage by non-technical stakeholders (e.g. Quality or Validation teams), the project includes a **PyInstaller configuration** for building a standalone, one-file executable.

This allows running the tool without:
- Python installation
- virtual environments
- dependency management

The executable can be distributed as a single file and executed locally on Windows machines.

## Implementation Roadmap Status

The execution roadmap is tracked in `IMPLEMENTATION_PLAN.md`. Current highlights:

- **Phase 0 (safety hotfixes):** completed.
- **Phase 1 (reliability and cancellation):** completed, including cooperative cancellation, non-blocking cancel behavior, and non-reraising user-facing logger behavior.
- **Phase 2:** in progress; grouping/plot mismatch fixes are now completed and covered by regression tests, with structural decomposition/performance tasks still pending.
- **Phase 3–4:** still in progress (docs/CI baseline and broader integration coverage).
- **Latest Phase 2 increments:** parse/export worker entrypoints use validated request dataclasses (`ParseRequest`, `ExportRequest`) end-to-end from dialog/UI call sites, and summary violin plotting now hardens label/value alignment by removing NaN-only buckets before rendering.
- **Next structural increment (Phase 2):** initial shared DB utilities were added in `modules/db.py` (connection defaults, retryable query helper, DataFrame query helper) and integrated into grouping/filter data-loading paths, with remaining parse/export/modify call-sites queued for migration.

## Tests

Current regression tests are in `tests/` and can be run with:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```


### Contract validation quick check

To run the contract and export-grouping focused tests only:

```bash
PYTHONPATH=. python -m unittest tests.test_contracts tests.test_export_grouping_and_sorting tests.test_db_utils -v
```

## Project Status

This project reflects an iterative learning process and real-world usage.  
Some parts of the codebase are experimental or could be refactored further, but the tool successfully delivered value in an industrial environment.
