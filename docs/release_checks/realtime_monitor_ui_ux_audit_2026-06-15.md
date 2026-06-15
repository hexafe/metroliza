# Realtime Monitor UI/UX Audit - 2026-06-15

Scope: end-user workflow review for the realtime industrial monitoring launch
slice, plus the main-window About dialog cleanup requested for build `260615`.

## Research Basis

- Nielsen Norman Group's usability heuristics emphasize immediate system status,
  user control, error prevention, recognition over recall, and focused content:
  https://www.nngroup.com/articles/ten-usability-heuristics/
- NN/g's error-prevention guidance calls out poorly differentiated options,
  nearby similar choices, and missing safeguards as common causes of slips:
  https://www.nngroup.com/articles/error-prevention/
- W3C WAI form guidance requires clear labels for controls, including
  checkboxes and buttons, so users and assistive technology can identify each
  control's purpose:
  https://www.w3.org/WAI/tutorials/forms/labels/
- Qt's `QMessageBox::about` documentation describes About as a simple app
  metadata box with one acknowledgement action, supporting the decision to keep
  Metroliza's About dialog compact:
  https://doc.qt.io/qt-6/qmessagebox.html#about

## Findings And Implementation

| Finding | Risk | Resolution |
|---|---|---|
| Disabled production source profiles were visible and could be checked by the dialog. | Operators could accidentally attempt live polling against a source that an admin had disabled. | Disabled sources are now visible but uncheckable; the runtime also fails a disabled profile before source access. |
| Multi-source monitoring had no selected-count feedback or bulk selection controls. | Operators could start a monitor without a clear view of how many sources were active. | Added a checked-source summary plus Select All and Clear controls for enabled sources. |
| `Poll Once` could reuse stale saved configs after the operator changed checked sources. | A source that was unchecked after a previous save could still be polled. | Polling now rebuilds from the current checked enabled sources unless a timed run already has an active config set. |
| Saving settings for multiple checked sources used one visible form for every checked profile. | A source-specific configuration could be overwritten by another source's visible form. | The primary save action now saves the current source only. A separate Apply Current to Checked action makes intentional bulk copying explicit. |
| Empty/no-source launch looked too close to a usable monitor. | First-run users could interpret an empty dashboard as a successful live setup. | Open Dashboard is disabled until a selected source, saved config, or poll result exists; the source panel shows a no-source summary. |
| About dialog contained manual/support/license details beyond the requested project metadata. | The dialog competed with the Help menu and made a quick version check noisy. | About now keeps only the duck animation, version, author, and GitHub project link. |

## Deferred Follow-Up

The dialog still persists raw/aggregated dashboard preferences before a full
dashboard rendering contract exists for every choice. This should be handled as
a service-level follow-up: either pass display mode, bucket, methods, and group
fields into `RealtimeDashboardService.dashboard_snapshot()`, or remove/disable
the controls until the renderer can honor them end to end.

## Focused Validation

Focused tests added or updated in this slice:

- `tests/test_realtime_monitoring_dialog.py`
- `tests/test_realtime_source_runtime.py`
- `tests/test_about_window_gif_lifetime.py`
- `tests/test_release_metadata_sync.py`

Full release-gate validation is recorded separately in the current release
status/checklist after the local and pushed CI runs complete.
