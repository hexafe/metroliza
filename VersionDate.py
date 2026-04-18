RELEASE_VERSION = "2026.04rc3"
VERSION_DATE = "260418"
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
CURRENT_RELEASE_HIGHLIGHT = (
    "Filtering now uses grouped scrollable sections and refreshes metadata views before loading filter choices."
)

release_notes = f"""
    <br><b>Current version {VERSION_LABEL}:</b><br>
    - Filtering is grouped into Measurement, Report metadata, and Source sections so the dialog fits laptop screens<br>
    - Filter choices refresh report metadata views before loading, preventing stale-view measurement ID errors<br>
    - Report-scoped filters are translated safely back to measurement export rows when export data is loaded<br>
    - Filter layout and metadata-query regressions now have focused test coverage<br>

    <br><b>Archive:</b><br>

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
