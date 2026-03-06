# Changelog (for end users)

## 2026.03 (build 260305) — current version
- **Group names can now be renamed via double-click**: in the group management flow, you can quickly update a group name by double-clicking it directly instead of using a separate rename action.
- **Group comparison matrices are cleaner and easier to read**: diagonal cells now stay intentionally blank, and exported values are sanitized more consistently so matrix outputs are clearer at a glance.
- **Export pipeline reliability is stricter by design**: when a fatal local workbook error is detected, the pipeline now stops immediately instead of continuing with partial or misleading output.
- **Grouped statistical test validation was hardened**: mismatched or invalid grouped test-selection inputs are now caught earlier, helping prevent silent issues in downstream statistical results.
- **Extended chart behavior has been refined**: scatter specification lines render more reliably, and legends are trimmed to reduce clutter in complex plots.
- **Python module naming was standardized**: canonical imports now follow snake_case naming, with compatibility shims in place to keep existing integrations working during migration.
- **Histogram and normality feedback presentation was polished**: normality status wording and table display were updated to make interpretation more straightforward for end users.

## 2026.02 (build 260223)
- Performance improvements during report generation.
- Additional stability improvements in export and grouping flows.

## 2026.02 (build 260216)
- Bug fixes and improved module interoperability.

## 2024.02 (build 240225)
- Added the first CSV Summary module version.

## 2024.02 (build 240218)
- First public release.
