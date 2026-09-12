# Capability and integration contract

Design snapshot: `develop@dd0f964cbcf8cd3382fd68dd528b22c1a3b5d7be`,
tree `5241c49c8b1dc7ae8e95079ae41eb3e35722569a`.
Sources: #1023, #945, #1013 audit comment 5529006626, current source/state/tests.
The supplied HTML/PNG concept informed the restrained colors, persistent context,
table/details split and scope footer. The runtime is native PyQt6 only.

## Capability matrix

| Prototype control / responsibility | Existing backend or UI seam on snapshot | Required adapter / deferred feature |
| --- | --- | --- |
| Workspace/source/destination context | `ui/workspace_context.py`: immutable `WorkspaceSnapshot`, `WorkspaceContext` version/signals | #1016 binds one shared context owner; approval records the context version. Prototype adds synthetic workspace name only. |
| Review reports, pending/cancelled review | `parsing/preflight.py`: `ParseFilePreflight`, `ParsePreflightResult`; existing preflight worker | #1015 adapts immutable evidence into table rows. Preserve no-write inspection, fingerprints, parser identity/generation and final source verification. |
| Recognition and parser evidence | `ParseFilePreflight` exposes parser, confidence, diagnostic reason and fingerprint | Existing evidence adapter; no new OCR or metadata extraction. Demo scores/fingerprints are visibly synthetic. |
| Destination match/completeness | Snapshot exposes destination duplicate status, not this independent completeness dimension | #1019 must supply authoritative accepted-complete/incomplete/unknown evidence and atomic outcomes. UI must never infer completeness from table presence/schema version or duplicate status. |
| Verify matches / explicit repair | Atomic no-clobber work is a dependency in #1019 / PR #1021; not integrated on this snapshot | Production adapter gated on that work and its review. Unknown matches verify first; selected incomplete graphs need explicit repair permission. Accepted complete reports never use replacement. |
| Checkbox selection / hidden count / scope dialog | Current `shared/parse_contracts.py:ParseRequest` has no selected identity set | Consume the canonical #1014 selected-plan contract after integration. Prototype `Plan` is a disposable simulation DTO, not a competing production ImportPlan. |
| Search/status/parser filters and sorting | `QAbstractTableModel`, `QSortFilterProxyModel` | UI-only #1015 adapter. Visibility never changes selected identities. Reference/date/part filters deferred until bounded, provenance-bearing extraction exists. |
| Persistent task/cancel/close guard | `ui/ui_tasks.py:UiTaskController`, `UiTaskState`, close policies | #1016 owns tasks outside pages. Real cancellation acknowledgement and thread lifecycle stay with existing controller/worker, not the demo QTimer. |
| Outcome/review/changed evidence | `ui/parsing_dialog.py`: `_primary_outcome_lines`, `_review_snapshot_group`, `_changed_since_review_group` (#1020) | One adapter preserves three domains. Demo “Repaired” is presentation evidence for an imported incomplete graph, not a proposal for another production persistence enum. |
| Overview next action | Existing MainWindow context and next-step state | #1016 offers one contextual continuation. It must respond to context invalidation rather than always linking an old task. |
| Tabular analysis destination | `tabular/contracts.py`, `tabular_analytics_service.py`; existing CSV dialog | Honest navigation placeholder. Source scope/units/table/chart handoff adapter deferred; no fake computed statistics. |
| Industrial data destination | `industrial/industrial_workflow_state.py`; existing Industrial dialog | Connection/cache/task ownership adapter deferred. No credentials, queries or synchronization enabled. |
| Realtime monitor destination | `industrial/realtime/realtime_service.py`; current session/rebind handling | Retention/stop/rebind adapter deferred. No live data or polling in this prototype. |
| Parser profiles destination | `parsing/declarative_parser_profiles.py`, `parser_profile_handoff.py` | Profile editor/validation handoff deferred; real registry changes must invalidate parser approval. |
| Light/dark and focus | Existing `ui/ui_theme_tokens.py` has semantic tokens; native Qt controls | Local `theme.py` provides extractable tokens. #1016 consolidates into canonical tokens; #946 validates screen readers, OS high-contrast and packaged scaling. |

All source paths in this table are under `src/metroliza/`. They are inspected or
identified integration seams, not runtime imports of the prototype.

## State contract

Recognition, destination completeness, eligibility, selected identity and execution
outcome are distinct fields. Source-copy exclusion and changed-source evidence are
also independent. Review records historical evidence; task results never rewrite it.

Source, destination, workspace and metadata changes invalidate approval. A running
plan is frozen and input controls are locked, while navigation/search remain usable.
Cancellation marks only pending selected identities cancelled; completed imported,
preserved, failed or changed outcomes remain intact. Execute-time change rejects that
identity and requires a fresh review before another task. The demo does not model
SQLite writes or real worker races.

## Integration plan and rollback

1. **#1015 — planner adapter.** After #1014 and #1019 contracts are accepted and
   integrated, map source evidence and destination completeness into a native model.
   Feed the exact confirmed identities into the canonical immutable plan. Port the
   hidden-selection, destination-only, explicit-repair and cancellation regressions.
   Keep production parser selection, final digest checks, transactions and owner-thread
   persistence in their current owners. Do not copy `Session.step()` into production.
2. **#1016 — shell adapter.** Bind canonical workspace and task controllers to persistent
   Overview/Reports pages. Reuse existing domain dialogs through one coordinator until
   their domain adapters are ready. Consolidate tokens, keyboard/focus and outcome
   rendering. Update active user manuals with the same vocabulary.
3. **#946 / #955 — validation and guidance.** Validate assistive technology, high contrast,
   packaged Windows DPI and novice tasks. Add contextual help after Product Owner
   workflow approval. No production readiness is implied by this prototype.

Rollback at this stage is simply not launching this standalone directory; production
startup has no reference to it. Future #1015/#1016 rollout should retain the existing
Parsing dialog and shell routing behind the approved UI switch. Revert routing/UI
adapters if needed while keeping the canonical import safety contracts intact. No
schema or data rollback should be necessary for the UI switch.

## Explicit first-pass gaps

- Session context, selection and task ledger persist across navigation, not process restarts.
- Earlier task ledgers remain in memory; a history browser and persisted resumable queue are deferred.
- Industrial, realtime, tabular and profile destinations are honest placeholders.
- No export artifact, real metadata extraction, production service adapter, OCR, statistics,
  migration or real persistence is enabled.
- Screen-reader/high-contrast, packaged Windows and OS compositor DPI validation are deferred.
- Large-table filter expansion and sorting have measurable pauses; timings are in VALIDATION.md.
- The supplied HTML is a reference, not bundled executable runtime or a replacement toolkit.

These deferrals retain #1015/#1016/#946 and the domain owners; Product Owner approval
of this native workflow precedes canonical UI implementation.
