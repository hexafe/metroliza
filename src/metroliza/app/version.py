RELEASE_VERSION = "2026.05rc4"
VERSION_DATE = "260609"
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
CURRENT_RELEASE_HIGHLIGHT = "Parser profile self-service, export reliability, CSV Summary file-name grouping, static POPULATION layers, dashboard-first Export group analysis, and release-gate audit hardening."
PUBLIC_VERSION_LABEL = "2026.05 RC4 (build 260609)"

release_notes = f"""
    <br><b>Current version {PUBLIC_VERSION_LABEL}:</b><br>
    - Saved report updates are safer if a database write fails partway through<br>
    - HTML dashboard-only exports now report a failure instead of success when dashboard creation fails<br>
    - CSV Summary filters and multi-file exports behave more consistently across regular and large-file paths<br>
    - Packaging, startup timing, and performance checks now fail when required release evidence is missing<br>
    - Parser profiles can now be prepared from Tools > Parser profiles... for new supplier report templates without writing Python code<br>
    - Google Sheets export now checks converted workbook tabs and warns when a local Excel fallback should be used<br>
    - Canceling long parsing, export, and metadata tasks is more reliable from progress windows<br>
    - Dashboard plot visuals can now be customized<br>
    - CSV Summary can auto-create one group per selected CSV file name without adding a POPULATION group<br>
    - CSV Summary dashboards can render dense POPULATION background layers as static images while keeping smaller groups interactive<br>
    - CSV Summary static POPULATION layers now remain visible when all selected rows belong to POPULATION and no random sampling is needed<br>
    - Oznak Check access no longer requests a reference column unless reference filtering is configured<br>
    - CSV Summary and Export dashboards now use clearer run notes, image snapshot wording, and group comparison takeaways<br>
    - CSV Summary now uses Edit groups for selected-reference comparisons and keeps dashboard rendering controls in Dashboard interactivity<br>
    - Grouped Export runs now add standard group analysis to the HTML dashboard instead of adding extra workbook sheets<br>

    <br><b>Archive:</b><br>

    <br><b>Version 2026.05rc2 (build 260517):</b><br>
    - CSV Summary can load multiple CSV files and handles large CSV files more reliably<br>
    - CSV Summary filters and grouping stay in sync with the loaded data, including date filters and numeric-looking group names<br>
    - Grouped statistics now compare groups overall and pair-by-pair instead of showing only separate group summaries<br>
    - HTML dashboards use clearer grouping labels and smaller datapoints for large datasets<br>
    - Oznak integration can fetch and export industrial database data directly without selecting a Metroliza database first<br>
    - Database credentials can be remembered locally after a successful Oznak export<br>
    - Export, parsing, filtering, and grouping screens were tightened so routine actions fit more cleanly in compact windows<br>

    <br><b>Version 2026.05rc1 (build 260512):</b><br>
    - CSV Summary revamp<br>
    - Oznak integration: connect and fetch data from industrial databases<br>
    - UI revamp<br>

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
