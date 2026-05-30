# Changelog (for end users)

## 2026.05 RC4 (build 260524) — current version
- Google Sheets export now checks converted workbook tabs and warns when a local Excel fallback should be used.
- Canceling long parsing, export, and metadata tasks is more reliable from progress windows.
- Dashboard plot visuals can now be customized.

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
