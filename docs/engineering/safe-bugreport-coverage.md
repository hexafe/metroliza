# Local bug-report coverage

The copyable report is available from the main Help menu and records a bounded,
local sequence of source-controlled action codes and selected boolean states.
The detailed report adds validated build facts, session-relative event timing,
explicit workflow correlation, closed error categories, retained option snapshots,
closed source locations for covered exception handlers, output-publication checks,
temporary analytics output lifecycle,
and closed user choices describing the symptom and expected/observed behaviour.
It never includes input documents, worksheets, names, paths, SQL, measurements,
exception messages or screenshots. It is not uploaded automatically.

| Application workflow | Examples of recorded boundaries | Main implementation |
| --- | --- | --- |
| Startup and general errors | Start, caught startup/runtime failure, closed exception or log-error family | `app/bootstrap.py`, `shared/custom_logger.py`, `shared/safe_bugreport.py` |
| Report import and metadata review | Preflight, review, OCR selection, import outcome, used CMM backend, explicit planner edit/copy/undo/reset/selection | `ui/parser_preflight_worker.py`, `ui/report_planner_model.py`, `ui/metadata_review_worker.py`, `parsing/parse_reports_thread.py`, `shared/workflow_diagnostics.py` |
| Database and name matching | Edit lifecycle, mapping add/edit/delete and import/export | `ui/modify_db.py`, `ui/characteristic_mapping_dialog.py` |
| Export, filters, grouping and dashboards | Export lifecycle and selected options, filter/group actions and fixed visual presets | `ui/export_dialog.py`, `ui/filter_dialog.py`, `ui/data_grouping.py`, `ui/dashboard_visual_options_dialog.py` |
| CSV Summary | Load, filter, grouping, accepted request options including chart types and separate parameter sheets, analysis, staging file lifecycle and selected request/result checks | `ui/industrial_analytics_dialog.py`, `industrial/industrial_analytics_workflow.py` |
| Industrial data | Source profiles, sync, SQL preview/recipe operations, linking, analytics and export | `ui/industrial_*_dialog.py` |
| Real-time monitoring | Source configuration, session and polling state transitions, event review and dashboard | `ui/realtime_industrial_monitoring_dialog.py` |
| Parser profiles | Validation, installation and enabled state | `ui/parser_plugin_wizard.py` |

This is a map of instrumented operation boundaries, not a claim that every click,
field or error is captured. A closed error-log observer records only the static
module family for application ERROR records; it does not read or format their
content and may coalesce repeated errors. Handled failures that neither emit a
covered workflow result nor log an error can still be absent. Silent wrong output
needs a workflow-specific check and is not inferred from operation completion.

Report XLSX and analytics XLSX/HTML publication boundaries check that the final
target is a regular, non-empty file. Analytics temporary outputs are also checked
before replacement, preserving a prior complete output when a new temporary
output is missing or empty. These checks use file metadata once per publication;
they do not reopen workbooks or inspect measurements. The report retains only a
closed check kind, pass/fail and an explicitly supplied operation token, if any.
A passing check proves publication at that instant, not numerical correctness,
chart completeness, or that the file remained available afterwards.
Rejected temporary outputs emit a separate failed staging check, so they cannot
be confused with failures after publication.

The detailed timeline observes owned analytics HTML and XLSX staging files at
transfer or cleanup. The `created` event timestamp marks that observation, after
rendering. An interruption before transfer or cleanup can leave an incomplete
staging history. Each observed file gets an independent runtime token and shares
the current analysis request token when one is available. Successful removal and
transfer include a size bucket of empty, under 1 MiB, 1 to under 16 MiB, at least
16 MiB, or unknown. The recorder reads metadata only from the owned staging path
and retains no file names, paths or exact sizes. An observed file is reported as
removed only after successful cleanup. If both observation and cleanup fail, the
file leaves no lifecycle event. A transfer records the staging file leaving its
temporary path. The final output checks and CSV Summary publication provide the
evidence about completed output.

Export failures additionally retain the validated stage, failure code, backend,
cause category and bounded operating-system error numbers from the existing
structured diagnostic. Exception locations are fixed module-family codes selected
from exact source-owned logger names; arbitrary logger names and caller context
remain excluded. Unknown locations stay unknown; these codes are not stack traces
or exact source-line evidence. Failure and verification records use the same
bounded detailed event ring and are subject to its loss indication.

Detailed context has its own explicit bounded retention and loss status. Option
snapshots are retained independently from the recent-action ring; they describe an
observed request or observation, never an inferred global configuration. Workflow
IDs are generated operation identifiers, not user identities or hashes of input.
Only explicit correlations are reported. Unknown, missing and truncated context is
disclosed rather than presented as a complete session recording. Build facts use
closed platform/runtime codes and validated versions/hashes of product builds;
no machine name, account, installed-package path or environment contents are read.

Detailed history uses the owned asynchronous writer and private store protections.
Both legacy and detailed history reject duplicate JSON keys. Clearing history
invalidates frozen previews as well as resetting retained context. Copying a report
is an explicit operation and does not upload anything. Existing clipboard copies,
logs and separately exported incidents are outside this clear action.

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
