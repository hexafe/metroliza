# User Manual

This folder is the main home for active end-user manuals for the Metroliza desktop app.

Use these guides when you want to understand what to click, what each dialog does, and what files or results you should expect. These pages are written for app users rather than developers.

## What this documentation set is for

Metroliza has several separate workflows. You do not need every tool every time.

In the app itself, the main database workflow starts from the main window buttons, utility actions live under **Tools**, and manuals/support items live under **Help**.

This manual set helps you:

- learn the normal app workflow in a simple order,
- open the right tool for the job,
- understand what each button and field does,
- avoid common mistakes,
- understand grouped dashboard analysis safely, and
- find the right reference page when you need details later.

## Recommended reading order

If you are new to the app, start here:

1. [Main window](main_window.md) — learn what each launcher button opens.
2. [Parsing](parsing.md) — create or update a database file from reports.
3. [Modify Database](modify_database.md) — optional cleanup for stored names and labels.
4. [Characteristic Name Matching](characteristic_name_matching.md) — optional normalization when the same characteristic appears under different names.
5. [Industrial Data](industrial_data.md) — optional production-line cache workflow for Oznak-supported databases.
6. [Realtime Industrial Monitoring](realtime_industrial_monitoring.md) — optional live monitoring guide for watched production signals.
7. [Export overview](export_overview.md) — create the main Excel report or dashboard.
8. [Export filtering](export_filtering.md) — narrow the export to the data you want.
9. [Export grouping](export_grouping.md) — create groups for grouped reporting and dashboard analysis.
10. [Group Analysis guide](group_analysis/README.md) — learn how to read grouped statistical output.

If you are using CSV Summary instead of the database workflow, jump to [CSV Summary](csv_summary.md).

If a supplier sends a report layout Metroliza does not recognize, use
[Parser Profiles](parser_profiles.md).

## Current documentation focus

The current 2026.06 RC1 tester documentation focus is realtime industrial
monitoring, Industrial Data source safety, replay evidence, and false-positive
handling. If you work with production-line data, read these pages first:

- [Industrial Data](industrial_data.md) — fetch production rows into a local cache before filtering, grouping, dashboards, or optional workbooks.
- [Realtime Industrial Monitoring](realtime_industrial_monitoring.md) — understand watched signals, anomaly events, source lag, and false-positive review.
- [Dashboard Visuals](dashboard_visuals.md) — tune dashboard appearance without changing the underlying results.

## Workflow manuals

These pages follow the main app workflows.

- [Main window](main_window.md)
- [Parsing](parsing.md)
- [Modify Database](modify_database.md)
- [Export overview](export_overview.md)
- [Export filtering](export_filtering.md)
- [Export grouping](export_grouping.md)
- [CSV Summary](csv_summary.md)
- [Industrial Data](industrial_data.md)
- [Realtime Industrial Monitoring](realtime_industrial_monitoring.md)
- [Parser Profiles](parser_profiles.md)

## Reference/help manuals

These pages support the main workflows.

- [Characteristic Name Matching](characteristic_name_matching.md)
- [Dashboard Visuals](dashboard_visuals.md)
- [Help, startup, and license](help_startup_and_license.md)

## Exported report interpretation manuals

These pages explain exported output rather than the Export dialog itself.

- [Group Analysis guide](group_analysis/README.md)
  - [HTML/Markdown version](group_analysis/user_manual.md)
  - [Printable PDF](group_analysis/user_manual.pdf)

The Group Analysis manual explains how to read grouped statistical output. It does **not** explain how to use the Export dialog itself. For export setup, start with [Export overview](export_overview.md).
