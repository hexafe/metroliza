# Changelog (for end users)

## 2026.06 RC2 (build 260709) — current version
- Excel and industrial workbook exports now keep imported formula-like and URL-like text literal, preventing source data from becoming active workbook formulas or links.
- Google OAuth tokens now use an atomic private application file, exclude client secrets, reject symlink targets, and migrate legacy local tokens only after a secure write succeeds.
- HTML and realtime dashboards now publish atomically, use private session output where appropriate, and preserve the last complete generation when publication fails.
- Parser resolution now reuses one bounded source inspection, rechecks source content before persistence, preserves approved multiline report fields while capping declarative regex work, and stores bounded provenance instead of duplicate parse trees.
- Report paths, typed membership filters, report identifiers, tabular numeric shadows, and measurement summaries now preserve stricter ownership and data-integrity invariants.
- CMM import now processes a valid final line without requiring a trailing newline and rejects empty parses without recording a successful fingerprint.
- Realtime industrial sync now stages streamed rows until atomic promotion, reclaims only stale heartbeat-leased staging at startup, quarantines permanent poison events, and keeps source health current even when no rows arrive.
- Realtime timestamps now use fixed-width UTC storage with explicit source timezones, detector inputs and identifiers are validated strictly, and legacy pickle model loading is disabled without deserialization.
- Realtime polling now atomically commits samples, stream events, and monotonic compare-and-swap offsets without stale failures overwriting newer progress; supports bounded multi-chunk catch-up and allowed lateness; and validates replay order before writing bounded batches.
- Realtime shutdown now waits for database workers before removing session files, and test isolation guards prevent module-scope Qt stubs from contaminating later tests.
- Packaging now distinguishes required and optional runtime assets, while CI scans short and cross-format credential assignments and uses an expiring Bandit baseline to turn new security findings into blocking failures.
- CSV Summary and Excel inputs now use one consistent local row store, keeping large files responsive while avoiding extra data copies.
- CSV Summary filters, grouping, and dashboard preparation can stream selected rows in smaller batches, reducing memory pressure on large tables.
- Grouped metric summaries now calculate directly from stored rows, so large CSV Summary analysis spends less time preparing intermediate tables.
- Export and industrial analytics paths now share lighter table helpers, improving stability when optional spreadsheet packages are unavailable.
- Parser and report data paths now use clearer reusable row-query contracts for filtering, counting, and streaming report-backed results.
- Magic filter expressions now accept field names and AND, OR, IN, and NOT IN wording in any letter case, including shorthand ranges.
- Industrial Data now opens cached rows in CSV Summary from indexed local metadata, so filter lists and simple grouping previews respond faster on large production caches.
- Industrial Data workbook export can now include raw cached data directly without first loading the full cache into the interactive table.
- Industrial export filters now apply consistently to cached and live exports, including additional production-field filters entered in the filter dialog.
- Industrial cache updates now refresh same-session filter lists more reliably, even when rows and production field values change within the same second.
- Industrial Data now clears abandoned temporary tabular views before preparing a new cache handoff, keeping long sessions lighter.
- Large SQL fetches now report saved rows clearly when rows were already streamed before a later read or save warning occurs.
- Realtime monitoring now reloads only newly inserted sample rows for anomaly review, keeping polling cycles quicker as monitoring history grows.
- Realtime diagnostics now keep source status messages more specific when a polling or dashboard refresh step fails.
- Realtime Industrial Monitoring now has a separate foundation for append-only samples, signal definitions, stream offsets, explainable anomaly events, replay, and dashboard review.
- Deterministic anomaly detectors now cover specification limits, warning limits, IQR fences, MAD robust z-score, rolling z-score, and stale-source checks with operator-readable explanations.
- Realtime polling now uses generated bounded queries, cursor offsets, chunk limits, safe diagnostics, and offset advancement only after local persistence succeeds.
- Industrial Data fetches can now save rows into the local cache while large guided or SQL reads are still running, with clearer progress for saving rows, refreshing links, and updating summaries.
- Industrial Data can now run the same guided filters or SQL query across checked production sources, then report one batch result for all successful and failed sources.
- Industrial source setup now accepts copied CSV headers or an approved all-columns marker when a reviewed table or view is allowed to expose simple columns.
- SQL query work now has a larger editor with a preview table for reviewed production queries before fetching rows.
- Realtime Industrial Monitoring now opens a configurable monitor dialog with source checkboxes, polling interval and timeout settings, bounded row limits, raw or aggregated dashboard mode, status, diagnostics, and dashboard output controls.
- Realtime source selection now keeps disabled production sources out of polling and separates saving one source from intentionally applying settings to all checked sources.
- Realtime Industrial Monitoring can now import the shared production source YAML file, reload source changes, and open the shared source editor from the monitor.
- Realtime dashboard snapshots now refresh in the background after polling, and Open Dashboard queues safely when a refresh is already running.
- Interactive HTML dashboards can now find points by TraceCode, record key, series, axis value, or point details, then save browser-local point marks without changing source data.
- Realtime dashboard review still works without selecting a Metroliza report database first; the app uses a temporary session SQLite store unless a persistent database is selected.
- Synthetic realtime fixtures and replay validation are available for pre-live testing without a production database.
- Optional advanced anomaly tooling stays separate from normal app startup, so standard users do not need extra ML packages.
- Industrial diagnostics now redact nested credentials, URI passwords, token-like fields, and raw SQL text from operator-facing status and persisted diagnostics.
- CMM parser probing now uses marker-based confidence so generic PDFs no longer look like perfect CMM report matches.
- CMM report import now rechecks encoded PDF page text before rejecting valid reports whose markers are hidden in compressed PDF bytes.
- Parser plugin handoff packages now have stronger tests that require local API contract content and small step-by-step prompts for LLM-assisted plugin work.
- Realtime rollout docs now include operator concepts, production safety checks, synthetic replay evidence, source lag review, and rollback steps.
- The About dialog now stays focused on the duck animation, version, author, and GitHub project link.

## 2026.05 RC5 (build 260612)
- Saved report updates are safer if a database write fails partway through.
- HTML dashboard-only exports now report a failure instead of success when dashboard creation fails.
- CSV Summary filters and multi-file exports behave more consistently across regular and large-file paths.
- Packaging, startup timing, and performance checks now fail when required release evidence is missing.
- Parser profiles can now be prepared from **Tools > Parser profiles...** for new supplier report templates without writing Python code.
- Parser profile handoff folders now include self-contained LLM contracts, small step-by-step prompts, and a manifest so local or inexpensive models can complete profiles with less context.
- Parser profile workflows now include package integrity checks, profile validation evidence, diagnose output, repair-prompt generation, and install actions in the app and CLI.
- Parser handoff instructions now require expected results for every parsed approval row and include a privacy-redaction checklist for external LLM use.
- CSV and Excel parser profiles are now discovered by normal report import, and parser persistence failures are isolated to the failed file instead of stopping the batch.
- Advanced generated parser plugins now persist `ParseResultV2` output through Metroliza's existing SQLite repository path, so generated parsers feed CSV Summary, filtering, grouping, exports, and dashboards consistently.
- Google Sheets export now checks converted workbook tabs and warns when a local Excel fallback should be used.
- Canceling long parsing, export, and metadata tasks is more reliable from progress windows.
- Dashboard plot visuals can now be customized.
- CSV Summary dashboards can turn very large group point layers into static images automatically, with thresholds still adjustable in Dashboard interactivity.
- CSV Summary and Export dashboard visual settings now focus on per-element styling instead of one shared opacity control.
- CSV Summary can auto-create one group per selected CSV file name without adding a POPULATION group.
- CSV Summary dashboards can render dense POPULATION background layers as static images while keeping smaller groups interactive.
- CSV Summary static POPULATION layers now remain visible when all selected rows belong to POPULATION and no random sampling is needed.
- Oznak Check access no longer requests a reference column unless reference filtering is configured.
- Industrial data sync can fetch by filters, row limits, or explicit fetch-all confirmation, then analyze cached rows through the CSV Summary tools.
- Industrial data now presents Oznak access as fetch-to-cache first, then opens cached source rows in CSV Summary for filtering, grouping, dashboards, and optional workbooks.
- Industrial data dashboards can group and filter by fetched columns plus source, so rows from multiple production databases stay traceable.
- Industrial SQL recipes now reject read-lock/write-output `SELECT` forms, and fallback SQL fetches stream rows into the local cache in chunks for large fetch-all operations.
- Industrial-only temporary caches no longer create report-link schema unless an opened Metroliza report database is the active target.
- Guided Industrial source setup now uses simple table/view identifiers for pinned Oznak compatibility; schema-qualified access belongs in SQL recipes or IT-provided views.
- Industrial Data and grouping release checks now include advisory benchmark probes for cache ingest, cache-to-CSV Summary handoff, static multi-group rendering, and high-cardinality grouping previews.
- Industrial data source switching now refreshes stored credentials for the selected source and rejects invalid column-list config values.
- Industrial data filters and cache refreshes now handle missing or removed production fields more predictably.
- CSV Summary and Export dashboards now use clearer run notes, image snapshot wording, and group comparison takeaways.
- CSV Summary now uses Edit groups for selected-reference comparisons and keeps dashboard rendering controls in Dashboard interactivity.
- Grouped Export runs now add standard group analysis to the HTML dashboard instead of adding extra workbook sheets.

## 2026.05 RC4 (build 260609)
- Parser profiles can now be prepared from **Tools > Parser profiles...** for new supplier report templates without writing Python code.
- CSV Summary can auto-create one group per selected CSV file name without adding a POPULATION group.
- CSV Summary dashboards can render dense POPULATION background layers as static images while keeping smaller groups interactive.
- CSV Summary and Export dashboards now use clearer run notes, image snapshot wording, and group comparison takeaways.
- Grouped Export runs now add standard group analysis to the HTML dashboard instead of adding extra workbook sheets.

## 2026.05 RC3 (build 260519)
- CSV Summary and Export grouping filters now apply after pressing Enter, keeping large row sets responsive while typing.
- Export grouping filters now narrow Reference and Parts lists without hiding existing groups.
- CSV Summary can assign all rows matching the active filter, including rows outside the visible page.
- HTML dashboard annotations for limits and means stay visible on Plotly charts.
- Interactive histogram legends and overlays now use clearer names and percent-axis scaling.

## 2026.05 RC2 (build 260517)
- CSV Summary can load multiple CSV files and handles large CSV files more reliably.
- CSV Summary filters and grouping stay in sync with the loaded data, including date filters and numeric-looking group names.
- Grouped statistics now compare groups overall and pair-by-pair instead of showing only separate group summaries.
- HTML dashboards use clearer grouping labels and smaller datapoints for large datasets.
- Oznak integration can fetch and export industrial database data directly without selecting a Metroliza database first.
- Database credentials can be remembered locally after a successful Oznak export.
- Export, parsing, filtering, and grouping screens fit more cleanly in compact windows.

## 2026.05 RC1 (build 260512)
- CSV Summary revamp.
- Oznak integration: connect and fetch data from industrial databases.
- UI revamp.

## 2026.04 (build 260421)
- Re-running parsing on an existing database refreshes older CMM report rows so OCR header metadata can replace filename-only values.
- Packaged builds include OCR model files so the executable does not depend on runtime model downloads.
- HTML dashboard histograms now use the same bin range as the workbook/native histogram snapshots.
- Plotly scatter and trend views show points only, without connecting lines between samples.
- Metric sections include return buttons back to the dashboard jump list, and grouped metrics return to Group Analysis.
- Dashboard documentation now describes the richer report metadata panel shown beside summary charts.
- Filtering now uses tabs and grouped sections for Measurement, Report metadata, and Source so the dialog stays compact and fits laptop screens.
- Filter choices refresh report metadata views before loading, preventing stale-view measurement ID errors.
- Report-scoped filters are translated safely back to measurement export rows when export data is loaded.

## 2026.04rc2(260415)
- Export setup is more compact on smaller laptops and keeps the main choices visible in one window.
- Database, Excel, filter, and grouping rows fit more cleanly, even when file paths are long.
- Advanced export settings are collapsed by default, so routine exports need less scrolling.
- Filters and grouping use clearer in-dialog actions, and dependent options only appear when they apply.

## 2026.04rc1(260414)
- Group Analysis exports are easier to review during routine checks.
- Standard exports now place grouped-analysis plots on a separate `Group Analysis Plots` sheet so the main results sheet stays cleaner.
- Grouped comparison and capability summaries are shown more consistently across the workbook.
- When a capability confidence interval cannot be shown from a small sample, the worksheet now says so clearly.
- Group Analysis help text and in-app release notes were refreshed for faster non-technical reading.

## 2026.03rc3(260329)
- Faster export/report generation.
- Export setup usability improved, with fewer layout/clipping issues at common window sizes.
- Saved export presets load more reliably for repeat export workflows.
- Updated Group Analysis sheet presentation improves readability and metric-by-metric comparison flow.
- Added optional HTML dashboard output with extended plots and group analysis, when selected.

## 2026.03rc2(260322)
- Group Analysis is now the main release focus, with the grouped export presented as the primary worksheet for comparing groups metric-by-metric.
- Expanded user manuals now cover Group Analysis reading order, plain-English interpretation, and the surrounding export workflow more clearly for end users.
- The Group Analysis manual set now more explicitly supports non-technical readers who need to understand adjusted p-values, effect size, Delta mean, and caution notes.
- Existing grouped-analysis, chart-readability, and capability-safeguard improvements remain part of the current release-candidate baseline.

## 2026.03rc1(260319)
- Completed the parser module naming cleanup: parser imports now use canonical snake_case modules only, and legacy CamelCase parser shims were removed.
- Histogram table polishing improved readability and visual consistency in end-user reports/exports.
- Grouping analysis prototype v2 was added to extend grouped-data analysis workflows.
- Histogram dashboards and chart layouts were improved for readability (cleaner side tables, taller rows, clearer title/x-axis visibility).
- Capability reporting now includes confidence intervals in rendered analytics/exports for better statistical interpretation.
- Low-sample safeguards were added for capability and distribution-fit metrics to reduce overconfident conclusions.
- Capability labels are clearer by spec type (`Cp/Cpk`, `Cpu`, `Cpl`), and symbol-rendering issues in chart labels were fixed.
- Added observed-vs-estimated NOK discrepancy warnings to highlight practical quality gaps.
- Group names can be renamed instantly via double-click in the group list.

## 2026.02 (build 260223)
- Performance improvements during report generation.
- Additional stability improvements in export and grouping flows.

## 2026.02 (build 260216)
- Bug fixes and improved module interoperability.

## 2024.02 (build 240225)
- Added the first CSV Summary module version.

## 2024.02 (build 240218)
- First public release.
