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

Write meaningful tests alongside implementation; run them only after all
implementation slices and integration are complete. Use synthetic fixtures,
the verified dev virtual environment and one retained QApplication offscreen.
Preserve exact source bindings, actual statuses and adverse evidence.

No author merge, release, tag, deployment or live-data migration is authorized.
Rollback removes the new entry points while preserving user files and private
bindings. This document records execution authority, not acceptance.
