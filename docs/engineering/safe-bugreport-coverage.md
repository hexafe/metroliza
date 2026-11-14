# Local bug-report coverage

The copyable report is available from the main Help menu and records a bounded,
local sequence of source-controlled action codes and selected boolean states.
It never includes input documents, worksheets, names, paths, SQL, measurements,
exception messages or screenshots. It is not uploaded automatically.

| Application workflow | Examples of recorded boundaries | Main implementation |
| --- | --- | --- |
| Startup and general errors | Start, caught startup/runtime failure, closed exception or log-error family | `app/bootstrap.py`, `shared/custom_logger.py`, `shared/safe_bugreport.py` |
| Report import and metadata review | Preflight, review, OCR selection, import outcome, used CMM backend | `ui/parser_preflight_worker.py`, `ui/metadata_review_worker.py`, `parsing/parse_reports_thread.py`, `shared/workflow_diagnostics.py` |
| Database and name matching | Edit lifecycle, mapping add/edit/delete and import/export | `ui/modify_db.py`, `ui/characteristic_mapping_dialog.py` |
| Export, filters, grouping and dashboards | Export lifecycle and selected options, filter/group actions and fixed visual presets | `ui/export_dialog.py`, `ui/filter_dialog.py`, `ui/data_grouping.py`, `ui/dashboard_visual_options_dialog.py` |
| CSV Summary | Load, filter, grouping, selected outputs, analysis and selected checks | `ui/industrial_analytics_dialog.py` |
| Industrial data | Source profiles, sync, SQL preview/recipe operations, linking, analytics and export | `ui/industrial_*_dialog.py` |
| Real-time monitoring | Source configuration, session and polling state transitions, event review and dashboard | `ui/realtime_industrial_monitoring_dialog.py` |
| Parser profiles | Validation, installation and enabled state | `ui/parser_plugin_wizard.py` |

This is a map of instrumented operation boundaries, not a claim that every click,
field or error is captured. A closed error-log observer records only the static
module family for application ERROR records; it does not read or format their
content and may coalesce repeated errors. Handled failures that neither emit a
covered workflow result nor log an error can still be absent. Silent wrong output
needs a workflow-specific check and is not inferred from operation completion.

History starts asynchronously before interactive window construction, after
logging and startup configuration. Failures before that point, forced process
termination, native crashes and power loss may leave missing events; an existing
supervised incident is a separate diagnostic mechanism. A restart or retained
history alone does not establish that a crash occurred. The report explicitly
marks known event loss and warns that queued events may not survive an abrupt exit.

The report includes fixed instructions for a coding agent to examine the listed
events and attempt a relevant reproduction using synthetic inputs. The bundled
automatic matcher currently has one synthetic CSV/grouping reference scenario;
other workflows require source investigation and separately constructed synthetic
cases. A passing reference scenario is not reproduction of a user's incident.
