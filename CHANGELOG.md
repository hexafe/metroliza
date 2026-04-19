# Changelog (for end users)

## 2026.04 (build 260418) — current version
- HTML dashboard histograms now use the same bin range as the workbook/native histogram snapshots.
- Plotly scatter and trend views show points only, without connecting lines between samples.
- Metric sections include return buttons back to the dashboard jump list, and grouped metrics return to Group Analysis.
- Dashboard documentation now describes the richer report metadata panel shown beside summary charts.
- Filtering now uses tabs and grouped sections for Measurement, Report metadata, and Source so the dialog stays compact and fits laptop screens.
- Filter choices refresh report metadata views before loading, preventing stale-view measurement ID errors.
- Report-scoped filters are translated safely back to measurement export rows when export data is loaded.
- Filter layout and metadata-query regressions now have focused test coverage.

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
