RELEASE_VERSION = "2026.05rc1"
VERSION_DATE = "260512"
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
CURRENT_RELEASE_HIGHLIGHT = (
    "Industrial analytics and CSV Summary now create grouped dashboards, row-filtered summaries, and Excel workbooks with export-matching plots."
)
PUBLIC_VERSION_LABEL = "2026.05 RC1 (build 260512)"

release_notes = f"""
    <br><b>Current version {PUBLIC_VERSION_LABEL}:</b><br>
    - CSV Summary now uses the shared analytics workflow for CSV and Excel files<br>
    - CSV Summary can filter CSV or Excel rows, including unique trace codes, before grouping, charts, dashboard output, and workbook output<br>
    - Metrics load automatically after choosing a CSV or Excel file, with a larger picker for selecting columns and search<br>
    - Excel files now show the available sheet names after selection<br>
    - CSV and Excel analytics can use a separate Groups dialog, with unassigned rows kept in POPULATION<br>
    - Grouped charts show selected groups separately, use marker-only time-series scatter plots, and normalize histograms so small groups remain visible<br>
    - Histogram outputs include export-style statistics tables<br>
    - Dashboards and Excel workbooks include the selected plots with the same chart style and histogram binning used in Export<br>
    - After analytics finishes, the result window links directly to the created dashboard and workbook files<br>
    - Detailed diagnostics are collapsed by default, while progress messages stay visible during dashboard and workbook creation<br>
    - Industrial data can select the report database directly before connecting, syncing, exporting, or analyzing production-line records<br>
    - The older CSV Summary workbook path has been retired; CSV Summary now opens the shared CSV/Excel analytics workflow<br>

    <br><b>Archive:</b><br>

    <br><b>Version 2026.04 (build 260421):</b><br>
    - Re-running parsing on an existing database refreshes older CMM report rows so OCR header metadata can replace filename-only values<br>
    - Packaged builds include OCR model files, so the executable does not depend on runtime model downloads<br>
    - HTML dashboard histograms now use the same bin range as the workbook/native histogram snapshots<br>
    - Plotly scatter and trend views show points only, without connecting lines between samples<br>
    - Metric sections include return buttons back to the dashboard jump list, and grouped metrics return to Group Analysis<br>
    - Dashboard documentation now describes the richer report metadata panel shown beside summary charts<br>
    - Filtering now uses tabs and grouped sections for Measurement, Report metadata, and Source so the dialog stays compact and fits laptop screens<br>
    - Filter choices refresh report metadata views before loading, preventing stale-view measurement ID errors<br>
    - Report-scoped filters are translated safely back to measurement export rows when export data is loaded<br>

    <br><b>Version 2026.04rc2 (build 260415):</b><br>
    - Export setup is more compact on smaller laptops and keeps the main choices visible in one window<br>
    - Database, Excel, filter, and grouping rows fit more cleanly, even when file paths are long<br>
    - Advanced export settings are collapsed by default, so routine exports need less scrolling<br>
    - Filters and grouping use clearer in-dialog actions, and dependent options only appear when they apply<br>

    <br><b>Version 2026.04rc1 (build 260414):</b><br>
    - Group Analysis exports are easier to review during routine checks<br>
    - Standard exports now keep plots on a separate Group Analysis Plots sheet so the main results sheet stays cleaner<br>
    - Grouped comparison and capability summaries are shown more consistently across the workbook<br>
    - When a capability confidence interval cannot be shown from a small sample, the worksheet now says so more clearly<br>

    <br><b>Version 2026.03rc3 (build 260329):</b><br>
    - Faster export/report generation<br>
    - Export setup screens are easier to use, with fewer layout issues in common window sizes<br>
    - Saved export presets now load more reliably for repeat workflows<br>
    - The updated Group Analysis sheet is easier to scan, compare, and interpret during routine review<br>
    - Added optional HTML dashboard output with extended plots and group analysis, when selected<br>

    <br><b>Version 2026.03rc2 (build 260322):</b><br>
    - Group Analysis became easier to read and interpret in grouped export workflows<br>
    - User manuals were expanded for clearer grouped export setup and worksheet reading<br>

    <br><b>Version 2026.03rc1 (build 260319):</b><br>
    - Histogram tables and chart layouts became easier to read in dense views<br>
    - Capability results and caution messages became clearer during grouped analysis<br>
    - Low-sample safeguards and quality warnings were improved to reduce misleading conclusions<br>
    - Group names can be renamed more easily during grouped export preparation<br>

    <br><b>Version 2026.03 (build 260301):</b><br>
    - Google Sheets export implementation with safe `.xlsx` fallback<br>
    - Performance optimizations across reporting and CSV Summary workflows<br>

    <br><b>Version 2026.02 (build 260223):</b><br>
    - Performance improvements<br>

    <br><b>Version 2026.02 (build 260216):</b><br>
    - Bug fixes and module-level integration improvements<br>

    <br><b>Version 2024.02 (build 240225):</b><br>
    - Added CSV Summary module (prototype release)<br>

    <br><b>Version 2024.02 (build 240218):</b><br>
    - First release<br>
    """
