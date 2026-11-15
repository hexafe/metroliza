# Recipe flow delivery #1232

PO authorized the full seven-issue package on 2026-11-15, with two helpers,
token-conscious routing and all test execution grouped after implementation.

Base: `dev@c899c7c0618a923174d8053ad8a0d9783208e757`,
tree `7a156fbe91a5670428685c88c0272220463cf22a`.
Work branch: `feature/1232-flow-recipes`. PR #1231 is an unmerged diagnostic
candidate and is not part of this base.

## Scope and ownership

Primary issue: #1232. Requirements and acceptance remain in #1233–#1239.
The coherent package exceeds 600 lines/eight files by design: model, real
service ports, runner, UI, editor and source adapters share one immutable plan.
Keep it in one integration checkout with disjoint ownership rather than branches
per helper. This exception does not waive acceptance or review.

The source guard rejected consumer adapters inside Reports/exporting/tabular
packages because those imports created reverse dependencies on orchestration.
Their final home is `recipes/{report_ports,export_service,
report_configuration_adapter,tabular_adapter,industrial_adapter}.py`.
Domain engines remain unchanged; the existing Qt workers are reused through
`ui/recipe_execution_adapter.py`, with the core ports independent of widgets.

- `model_runner`: model/storage/bindings, built-ins and runner (#1233/#1235),
  followed by editor/capture (#1237).
- `ports_ui`: headless Reports ports (#1234), new UI components (#1236),
  followed by tabular/industrial adapters (#1238).
- Coordinator: existing window composition and hooks, diagnostics schemas,
  documentation, shared integration, validation and package evidence (#1239).

Implementers resolve from development-routing policy 1.1/map 1.0 to
`gpt-6.1-sol/high`; Standard requested. Backend-observed identity/effort is
not visible. OpenAI execution is available; Claude capacity initially UNKNOWN.
No recursive delegation, concurrent CI or worker test execution.

## Gates

Risk is CRITICAL at private configuration, SQLite ownership and output
publication boundaries. One full independent review and at most one fresh
changed-source delta are admitted. Mandatory project CI/GitHub review, real
Windows package and separate PO acceptance remain distinct gates.

The first delta closed all four required corrections with no new P0–P2, but its
receipt did not confirm loading the trusted policy files. The coordinator admits
one additional bounded policy/source rebind for this named gate defect. Supply
the full trusted policy inline in a fresh read-only reviewer context, inspect only
the final narrow delta, and preserve both earlier reports. This is a finite
extension to repair policy provenance, not another full audit or verdict retry.

Hosted validation then identified a concrete P1: the optional tabular analytics
workbook was absent from the resolved output family, permitting a source alias.
The coordinator admits one further bounded independent delta for that data-safety
fix and the CI-discovered stale documentation pin. Preserve previous findings;
do not repeat the full audit or reset the CI/package evidence.

The next hosted gate identified unsafe XML parsing in the qualification oracle
and a service-review P2 for a favorite retaining an old saved revision. Admit one
bounded delta for these named blockers together. Use the already pinned safe XML
parser, verify entity rejection, and resolve favorites from the current catalog.
No security baseline or required check is relaxed.

The next service review identified two further P2 blockers in unchanged paths:
analytics replacement asset publication and ambiguous composite grouping labels.
Admit one bounded independent delta for their grouped corrections. Require real
rerun/failure preservation controls and independent distinct-population statistics;
keep all prior reports, source bindings and exact-head CI/package gates.

Write meaningful tests alongside implementation; run them only after all
implementation slices and integration are complete. Use synthetic fixtures,
the verified dev virtual environment and one retained QApplication offscreen.
Preserve exact source bindings, actual statuses and adverse evidence.

PO subsequently requested a version increment, merge into `dev` and repository
cleanup at completion. This explicitly authorizes the coordinator to perform the
final merge after the required exact-source review, CI and package checks, and
to retire this task's execution ref using verified recovery and guarded deletion.
Separate user acceptance and issue closure remain distinct. Release, tag,
deployment and live-data migration are not authorized.
Rollback removes the new entry points while preserving user files and private
bindings. This document records execution authority, not acceptance.
