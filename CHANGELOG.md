# Changelog (for end users)

## 2026.03rc2(260322) — current version
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
