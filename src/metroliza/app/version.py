RELEASE_VERSION = "2026.06rc1"
VERSION_DATE = "260617"
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
CURRENT_RELEASE_HIGHLIGHT = "Industrial Data performance release with indexed cache filtering, faster CSV Summary handoff, raw workbook export, realtime diagnostics, and dashboard point marking."
PUBLIC_VERSION_LABEL = "2026.06 RC1 (build 260617)"

release_notes = f"""
    <br><b>Current version {PUBLIC_VERSION_LABEL}:</b><br>
    - Industrial Data now opens cached rows in CSV Summary from indexed local metadata, so filter lists and simple grouping previews respond faster on large production caches<br>
    - Industrial Data workbook export can now include raw cached data directly without first loading the full cache into the interactive table<br>
    - Industrial export filters now apply consistently to cached and live exports, including additional production-field filters entered in the filter dialog<br>
    - Industrial cache updates now refresh same-session filter lists more reliably, even when rows and production field values change within the same second<br>
    - Industrial Data now clears abandoned temporary tabular views before preparing a new cache handoff, keeping long sessions lighter<br>
    - Large SQL fetches now report saved rows clearly when rows were already streamed before a later read or save warning occurs<br>
    - Realtime monitoring now reloads only newly inserted sample rows for anomaly review, keeping polling cycles quicker as monitoring history grows<br>
    - Realtime diagnostics now keep source status messages more specific when a polling or dashboard refresh step fails<br>
    - Realtime Industrial Monitoring now has a separate foundation for append-only samples, signal definitions, stream offsets, explainable anomaly events, replay, and dashboard review<br>
    - Deterministic anomaly detectors now cover specification limits, warning limits, IQR fences, MAD robust z-score, rolling z-score, and stale-source checks with operator-readable explanations<br>
    - Realtime polling now uses generated bounded queries, cursor offsets, chunk limits, safe diagnostics, and offset advancement only after local persistence succeeds<br>
    - Industrial Data fetches can now save rows into the local cache while large guided or SQL reads are still running, with clearer progress for saving rows, refreshing links, and updating summaries<br>
    - Industrial Data can now run the same guided filters or SQL query across checked production sources, then report one batch result for all successful and failed sources<br>
    - Industrial source setup now accepts copied CSV headers or an approved all-columns marker when a reviewed table or view is allowed to expose simple columns<br>
    - SQL query work now has a larger editor with a preview table for reviewed production queries before fetching rows<br>
    - Realtime Industrial Monitoring now opens an operator dialog with checked-source selection, polling interval and timeout settings, row limits, status, diagnostics, and dashboard output controls<br>
    - Realtime source selection now keeps disabled production sources out of polling and separates saving one source from intentionally applying settings to all checked sources<br>
    - Realtime Industrial Monitoring can now import the shared production source YAML file, reload source changes, and open the shared source editor from the monitor<br>
    - Realtime dashboard snapshots now refresh in the background after polling, and Open Dashboard queues safely when a refresh is already running<br>
    - Interactive HTML dashboards can now find points by TraceCode, record key, series, axis value, or point details, then save browser-local point marks without changing source data<br>
    - Realtime dashboard review can open without selecting a Metroliza report database first; the app uses a temporary session SQLite store unless a persistent database is selected<br>
    - Synthetic realtime fixtures and replay validation are available for pre-live testing without a production database<br>
    - Optional advanced anomaly tooling stays separate from normal app startup, so standard users do not need extra ML packages<br>
    - Industrial diagnostics now redact nested credentials, URI passwords, token-like fields, and raw SQL text from operator-facing status and persisted diagnostics<br>
    - CMM parser probing now uses marker-based confidence so generic PDFs no longer look like perfect CMM report matches<br>
    - Parser plugin handoff packages now have stronger tests that require local API contract content and small step-by-step prompts for LLM-assisted plugin work<br>
    - Realtime rollout docs now include operator concepts, production safety checks, synthetic replay evidence, source lag review, and rollback steps<br>
    - The About dialog now stays focused on the duck animation, version, author, and GitHub project link<br>

    <br><b>Archive:</b><br>

    <br><b>Version 2026.05rc5 (build 260612):</b><br>
    - Saved report updates are safer if a database write fails partway through<br>
    - HTML dashboard-only exports now report a failure instead of success when dashboard creation fails<br>
    - CSV Summary filters and multi-file exports behave more consistently across regular and large-file paths<br>
    - Packaging, startup timing, and performance checks now fail when required release evidence is missing<br>
    - Parser profiles can now be prepared from Tools > Parser profiles... for new supplier report templates without writing Python code<br>
    - Parser profile handoff folders now include self-contained LLM contracts, small step-by-step prompts, and a manifest for local or inexpensive model workflows<br>
    - Parser profile workflows now include package integrity checks, validation evidence, diagnose output, repair prompts, and install actions in the app and CLI<br>
    - Parser handoff instructions now require expected results for every parsed approval row and include a privacy-redaction checklist for external LLM use<br>
    - CSV and Excel parser profiles are now discovered by normal report import, and parser persistence failures are isolated to the failed file instead of stopping the batch<br>
    - Advanced generated parser plugins now persist ParseResultV2 output through Metroliza's existing SQLite repository path<br>
    - Google Sheets export now checks converted workbook tabs and warns when a local Excel fallback should be used<br>
    - Canceling long parsing, export, and metadata tasks is more reliable from progress windows<br>
    - Dashboard plot visuals can now be customized<br>
    - CSV Summary dashboards can turn very large group point layers into static images automatically, with thresholds still adjustable in Dashboard interactivity<br>
    - CSV Summary and Export dashboard visual settings now focus on per-element styling instead of one shared opacity control<br>
    - CSV Summary can auto-create one group per selected CSV file name without adding a POPULATION group<br>
    - CSV Summary dashboards can render dense POPULATION background layers as static images while keeping smaller groups interactive<br>
    - CSV Summary static POPULATION layers now remain visible when all selected rows belong to POPULATION and no random sampling is needed<br>
    - Oznak Check access no longer requests a reference column unless reference filtering is configured<br>
    - Industrial data sync can fetch by filters, row limits, or explicit fetch-all confirmation, then analyze cached rows through the CSV Summary tools<br>
    - Industrial data now presents Oznak access as fetch-to-cache first, then opens cached source rows in CSV Summary for filtering, grouping, dashboards, and optional workbooks<br>
    - Industrial data dashboards can group and filter by fetched columns plus source, so rows from multiple production databases stay traceable<br>
    - Industrial SQL recipes now reject unsafe read-lock and write-output queries, and large SQL fetch-all operations save rows to the local cache in chunks<br>
    - Industrial-only temporary caches no longer create report-link tables unless an opened Metroliza report database is the active target<br>
    - Guided Industrial source setup now uses simple table/view names for Oznak compatibility; two-part database object names belong in SQL recipes or IT-provided views<br>
    - Industrial Data and grouping release checks now include extra large-data performance probes for cache loading, CSV Summary handoff, static multi-group rendering, and high-cardinality grouping previews<br>
    - Industrial data source switching now refreshes stored credentials for the selected source and rejects invalid column-list config values<br>
    - Industrial data filters and cache refreshes now handle missing or removed production fields more predictably<br>
    - CSV Summary and Export dashboards now use clearer run notes, image snapshot wording, and group comparison takeaways<br>
    - CSV Summary now uses Edit groups for selected-reference comparisons and keeps dashboard rendering controls in Dashboard interactivity<br>
    - Grouped Export runs now add standard group analysis to the HTML dashboard instead of adding extra workbook sheets<br>

    <br><b>Version 2026.05rc4 (build 260609):</b><br>
    - Parser profiles can now be prepared from Tools > Parser profiles... for new supplier report templates without writing Python code<br>
    - CSV Summary can auto-create one group per selected CSV file name without adding a POPULATION group<br>
    - CSV Summary dashboards can render dense POPULATION background layers as static images while keeping smaller groups interactive<br>
    - CSV Summary and Export dashboards now use clearer run notes, image snapshot wording, and group comparison takeaways<br>
    - Grouped Export runs now add standard group analysis to the HTML dashboard instead of adding extra workbook sheets<br>

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
