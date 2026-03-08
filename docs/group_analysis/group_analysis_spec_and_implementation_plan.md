# Group Analysis Rebuild — Specification and Implementation Plan

**Suggested repo path:** `docs/group_analysis_spec_and_implementation_plan.md`

## 1. Purpose

This document defines the rebuild of the current `Group Comparison` export into a new workbook-level **Group Analysis** feature.

The current implementation should be treated as legacy. The new implementation must be designed for end users who need readable, trustworthy, decision-oriented analysis rather than a single overloaded worksheet.

The rebuild must preserve the existing grouping workflow in the app while replacing the export-side comparison logic and worksheet design.

---

## 2. Current context in the repository

Relevant current-state facts:

- The app is a Python desktop tool for metrology workflows, with grouping and Excel export already in place.
- The grouping workflow already uses `POPULATION` as the default group for all rows.
- Export already has a workbook-level hook for group comparison, but the current output is too dense and should be rebuilt.
- The current report profile already has independent export preset logic, including `Extended plots` for the main report.
- Group Analysis must remain independent from the main report preset system.

Relevant files to inspect during implementation:

- `modules/DataGrouping.py`
- `modules/ExportDialog.py`
- `modules/export_dialog_service.py`
- `modules/contracts.py`
- `modules/export_grouping_utils.py`
- `modules/ExportDataThread.py`
- legacy: `modules/export_group_comparison_writer.py`

---

## 3. Goals

### 3.1 Functional goals

Build a new **Group Analysis** export that:

- supports both **single-reference** and **multi-reference** group analysis,
- works as a **workbook-level** report,
- uses the existing group assignments,
- always generates a **Diagnostics** sheet,
- clearly explains what was analyzed, skipped, or limited,
- supports `POPULATION` as a normal group,
- preserves the current grouping UX,
- stays independent from existing `Extended plots` for the main export.

### 3.2 UX goals

The report must be:

- readable,
- compact,
- deterministic,
- explicit about limitations,
- useful for real production problem-solving and supplier comparison.

### 3.3 Technical goals

The rebuild must:

- avoid patching the legacy all-in-one writer,
- separate payload building from worksheet rendering,
- keep normal export behavior unchanged when Group Analysis is off,
- be testable at the helper/service level.

---

## 4. Non-goals

The following are intentionally out of scope for this iteration:

- alias mapping or canonical standardization of metric names across references,
- user-facing `Full` mode,
- optional Diagnostics,
- heuristic matching of “similar” metric names,
- forced enterprise-wide reporting standardization.

Metric-name standardization is explicitly deferred to a later phase after the app is adopted and real reporting inconsistencies are observed in production use.

---

## 5. Group semantics

### 5.1 POPULATION

`POPULATION` must be treated exactly like any other group.

Rules:

- no special display logic,
- no hidden exclusion from analysis,
- counts toward the minimum group count,
- counts toward scope resolution,
- if only one final group remains, even if it is `POPULATION`, there is no comparison.

### 5.2 Missing group labels

Any blank or missing group value in export-side merged data must be normalized to `POPULATION`.

The new implementation must not introduce or rely on `UNGROUPED` semantics for Group Analysis.

---

## 6. User-facing export options

Add the following options to export settings:

### 6.1 Group analysis level

Allowed values:

- `Off`
- `Light`
- `Standard`

Behavior:

- `Off` disables Group Analysis entirely.
- `Light` generates the compact statistical report plus Diagnostics.
- `Standard` generates everything from `Light`, plus supported plots, plus Diagnostics.

### 6.2 Group analysis scope

Allowed values:

- `Auto`
- `Single-reference`
- `Multi-reference`

Behavior:

- Scope is only relevant when Group Analysis is enabled.
- The scope control should be disabled when `Group analysis level = Off`.

### 6.3 Diagnostics

Diagnostics are **always generated** when `Group analysis level != Off`.

Diagnostics are not optional because they contain critical information about:

- resolved scope,
- analyzed vs skipped metrics,
- skip reasons,
- spec mismatches,
- histogram omissions,
- potential unmatched metrics across references.

### 6.4 Independence from main export preset

`Extended plots` and the existing report preset system remain independent from Group Analysis.

Examples that must be supported:

- main export with `Extended plots`, Group Analysis off,
- main export without `Extended plots`, Group Analysis `Light`,
- main export with `Extended plots`, Group Analysis `Standard`.

---

## 7. Scope resolution rules

Scope must be resolved using **grouped rows after export filtering and after applying grouping assignments**.

### 7.1 Auto

- grouped rows span exactly **1** reference → resolved scope = `local`
- grouped rows span **2+** references → resolved scope = `multi-reference`

### 7.2 Single-reference

- grouped rows span exactly **1** reference → run analysis
- grouped rows span **2+** references → skip main analysis and create a short Group Analysis message sheet:

> Single-reference group analysis skipped: grouped rows span multiple references.

### 7.3 Multi-reference

- grouped rows span **2+** references → run analysis
- grouped rows span exactly **1** reference → skip main analysis and create a short Group Analysis message sheet:

> Multi-reference group analysis skipped: grouped rows span only one reference.

---

## 8. Minimum conditions to run analysis

Full Group Analysis should run only if all of the following are true:

- at least **2 non-empty groups** remain after filtering and group assignment,
- numeric measurement data are available,
- at least **1 metric** is eligible for the selected analysis level.

If these conditions are not met:

- create a short `Group Analysis` sheet with a clear reason,
- create `Diagnostics` with the same reason and supporting context.

Example skip reasons:

- fewer than two groups,
- no numeric data,
- no comparable metrics for the selected level,
- forced scope incompatible with filtered grouped rows.

---

## 9. Metric identity and comparability

### 9.1 Current metric identity

For this iteration, metric identity is defined as:

- preferred: `HEADER - AX`
- fallback: `HEADER`

No alias mapping or fuzzy matching should be introduced.

### 9.2 Normalized spec comparison

The following values must be compared numerically, not as strings:

- `NOM`
- `LSL`
- `USL`

Normalization rules:

- convert to numeric where possible,
- round to **3 decimal places**,
- compare on the basis of `0.000` formatting.

This avoids false mismatches such as:

- `0`
- `0.0`
- `0.000`

### 9.3 Spec status categories

Each metric must be classified into one of the following:

- `EXACT_MATCH`
- `LIMIT_MISMATCH`
- `NOM_MISMATCH`
- `INVALID_SPEC`

#### EXACT_MATCH

Metric identity matches, nominal matches, and limits match.

- `Light`: full descriptive stats + pairwise A/B table
- `Standard`: full descriptive stats + plots + capability

#### LIMIT_MISMATCH

Metric identity and nominal match, but limits differ.

- `Light`: descriptive stats + A/B allowed, but with a strong warning
- `Standard`: skip metric

#### NOM_MISMATCH

Metric identity matches, but nominal differs.

- `Light`: descriptive only
- no A/B on raw `MEAS`
- `Standard`: skip metric

This is a deliberate business decision: when nominal differs, raw `MEAS` is no longer safely comparable for decision-oriented group comparison.

#### INVALID_SPEC

Missing values, parser noise, non-resolvable spec conflicts, or otherwise unusable spec metadata.

- `Light`: descriptive only, no A/B, no capability
- `Standard`: skip metric

---

## 10. Capability rules

### 10.1 Bilateral specs

When the specification is bilateral:

- `Cp = (USL - LSL) / (6 * std)`
- `Cpk = min((USL - mean)/(3*std), (mean - LSL)/(3*std))`

### 10.2 Upper-only GD&T

If:

- `NOM = 0`
- `LSL = 0`
- `USL > 0`

then treat the metric as upper-only GD&T:

- `Cp = N/A`
- `Capability = Cpk+ = (USL - mean) / (3 * std)`
- `Capability type = Cpk+`

### 10.3 Lower-only

Prepare the implementation so lower-only capability can be represented analogously:

- `Cp = N/A`
- `Capability = Cpk-`
- `Capability type = Cpk-`

### 10.4 Invalid capability

If any of the following are true:

- `std <= 0`,
- limits unavailable,
- unusable or mixed capability mode,
- invalid spec,

then capability values must be `N/A`.

---

## 11. Flags

### 11.1 Per-group flag

- `LOW N` when `n < 5`

### 11.2 Cross-group interpretation flags

- `IMBALANCED N` when `max(n) / min(n) >= 2`
- `SEVERELY IMBALANCED N` when `max(n) / min(n) >= 3`
- `SPEC?` when interpretation is limited due to spec mismatch or invalid spec

Flags should appear in:

- per-group stats rows,
- pairwise comparison rows where relevant,
- Diagnostics summary.

---

## 12. Report design

## 12.1 Light

`Light` is the main compact statistical report.

For each eligible metric, render:

1. metric header,
2. comparability/spec summary,
3. per-group descriptive stats table,
4. pairwise A/B table where allowed,
5. 1–3 short insights.

### Per-group stats columns

- `Group`
- `n`
- `mean`
- `std`
- `median`
- `IQR`
- `min`
- `max`
- `Cp`
- `Capability`
- `Capability type`
- `Flags`

### Pairwise A/B columns

- `Group A`
- `Group B`
- `Δmean`
- `adj p`
- `effect size`
- `verdict`
- `flags`

## 12.2 Standard

`Standard` includes everything from `Light` plus plots.

### Plot rules

Default:

- violin/distribution plots

Conditional:

- histograms

Histogram generation must be conservative. Add histograms only when they are meaningful and readable, for example:

- exact-match metric,
- small enough group count,
- sufficient sample size,
- reasonable readability.

If a histogram is skipped because it would be cluttered or low-value, record that in Diagnostics.

## 12.3 No user-facing Full mode

Do not expose any `Full` report level to end users.

The old “everything in one place” design is explicitly rejected.

---

## 13. Diagnostics sheet

Diagnostics are mandatory whenever Group Analysis is enabled.

Suggested worksheet name:

- `Diagnostics`

Diagnostics must include:

- requested Group Analysis level,
- requested scope,
- resolved scope,
- whether analysis executed or was skipped,
- skip reason if applicable,
- group count,
- reference count,
- analyzed metric count,
- skipped metric count,
- count by status:
  - `EXACT_MATCH`
  - `LIMIT_MISMATCH`
  - `NOM_MISMATCH`
  - `INVALID_SPEC`
- skipped metrics and reasons,
- warning summary,
- histogram skips,
- **Possible unmatched metrics across references**.

Diagnostics must be compact and readable, not a dump of raw internals.

---

## 14. UI changes

The export dialog should retain the current main report controls and add a clearly separate subsection for Group Analysis.

Suggested controls:

### Main report

- Export preset
- Google Sheets export
- Chart type
- Sort measurements by
- existing advanced options

### Group analysis

- Group analysis level
- Group analysis scope

UX rules:

- visually separate the Group Analysis subsection from the main report subsection,
- disable `Group analysis scope` when `level = Off`,
- do not add a Diagnostics checkbox.

---

## 15. Architecture and implementation approach

### 15.1 Recommended design

Use a service/writer split.

#### Service layer

Responsible for:

- scope resolution,
- metric identity building,
- spec normalization and classification,
- descriptive statistics,
- pairwise comparison payloads,
- capability computation,
- insight generation,
- Diagnostics payload.

#### Writer layer

Responsible for:

- creating the main `Group Analysis` worksheet,
- creating the `Diagnostics` worksheet,
- formatting sections and tables,
- inserting charts in `Standard` mode.

### 15.2 Legacy handling

The current `export_group_comparison_writer.py` should be treated as legacy.

Preferred implementation strategy:

- stop extending the old writer,
- build a new implementation in separate modules.

Suggested new modules:

- `modules/group_analysis_service.py`
- `modules/group_analysis_writer.py`

---

## 16. File-by-file change plan

## 16.1 `modules/contracts.py`

Add export options:

- `group_analysis_level`
- `group_analysis_scope`

Validation requirements:

- normalize to internal values,
- allow `off/light/standard`,
- allow `auto/single_reference/multi_reference`,
- preserve backward compatibility for all existing export flows.

## 16.2 `modules/export_dialog_service.py`

Update request construction so the two new Group Analysis options are carried into validated export requests.

## 16.3 `modules/ExportDialog.py`

Add UI controls for:

- Group analysis level
- Group analysis scope

Requirements:

- visually separated subsection,
- scope disabled when level is off,
- no Diagnostics checkbox,
- preserve current main report controls.

## 16.4 `modules/export_grouping_utils.py`

Normalize missing group values to `POPULATION`.

If helpful, add a small helper to centralize group-label normalization.

## 16.5 `modules/ExportDataThread.py`

Integrate the new Group Analysis pipeline:

1. skip when Group Analysis is off,
2. prepare filtered export dataframe,
3. apply grouping,
4. normalize missing groups to `POPULATION`,
5. resolve scope,
6. build analysis payload,
7. write `Group Analysis`,
8. write `Diagnostics`.

## 16.6 `modules/group_analysis_service.py` (new)

Implement helper/service logic such as:

- `resolve_group_analysis_scope(...)`
- `build_metric_identity(...)`
- `normalize_spec_value(...)`
- `classify_metric_spec_status(...)`
- `compute_group_descriptive_stats(...)`
- `compute_pairwise_comparisons(...)`
- `compute_capability_metrics(...)`
- `prepare_group_analysis_payload(...)`
- `prepare_group_analysis_diagnostics(...)`

## 16.7 `modules/group_analysis_writer.py` (new)

Implement worksheet rendering helpers such as:

- `write_group_analysis_sheet(...)`
- `write_group_analysis_diagnostics_sheet(...)`
- small formatting helpers for headers, tables, warnings, and charts.

## 16.8 Legacy writer

Do not keep adding features to the legacy all-in-one writer.

If practical, leave it in place temporarily but stop using it.

---

## 17. Suggested phased implementation order

### Phase 1 — Export options and UI

- Add new options to contracts.
- Update export dialog service.
- Add the new Group Analysis controls in `ExportDialog.py`.

### Phase 2 — Export-side grouping normalization and scope

- Normalize missing groups to `POPULATION`.
- Implement scope resolution helpers.
- Add minimum-condition checks.

### Phase 3 — Core service logic

- Metric identity helpers
- spec normalization and classification
- descriptive stats
- capability
- pairwise comparison payloads
- diagnostics payloads

### Phase 4 — Worksheet writer

- Implement `Light`
- Implement `Standard`
- Implement Diagnostics sheet
- Implement clean worksheet formatting

### Phase 5 — Export integration

- Plug the new pipeline into `ExportDataThread.py`
- Keep normal export unchanged when Group Analysis is off

### Phase 6 — Tests and cleanup

- unit tests,
- integration tests,
- docstrings and code comments,
- remove dead references to the legacy comparison sheet where safe.

## 17.1 Incremental PR roadmap for next-step implementation

Use the phases above as the execution order, but ship in small PRs with explicit scope.

### PR 1 — Contracts and request plumbing

- `modules/contracts.py`
- `modules/export_dialog_service.py`
- tests for option normalization and backward compatibility

Deliverable:

- validated request contains `group_analysis_level` and `group_analysis_scope`.

### PR 2 — Export dialog controls

- `modules/ExportDialog.py`
- UI behavior tests (where available)

Deliverable:

- Group Analysis section with level/scope controls,
- scope disabled when level is off,
- no Diagnostics checkbox.

### PR 3 — Group normalization and scope/minimum-condition helpers

- `modules/export_grouping_utils.py`
- scope helpers in `modules/group_analysis_service.py` (or equivalent helper module)
- unit tests for `POPULATION` fallback and scope resolution

Deliverable:

- missing groups normalized to `POPULATION`,
- deterministic scope resolution,
- skip reasons for non-runnable analysis.

### PR 4 — Core Group Analysis service payload

- `modules/group_analysis_service.py`
- unit tests for metric identity, spec status, capability, flags, diagnostics payload

Deliverable:

- pure/mostly-pure payload assembly for Light/Standard eligibility and Diagnostics.

### PR 5 — Worksheet writer

- `modules/group_analysis_writer.py`
- writer-focused tests/snapshots if present in repo style

Deliverable:

- `Group Analysis` (Light + Standard sections),
- mandatory `Diagnostics` rendering,
- compact readable layout.

### PR 6 — Export pipeline integration

- `modules/ExportDataThread.py`
- integration tests for off/light/standard, scope mismatch messages, independence from `Extended plots`

Deliverable:

- end-to-end wiring into export without changing normal export behavior when Group Analysis is off.

### PR 7 — Final stabilization and documentation closeout

- remaining tests/cleanup,
- remove safe dead paths to legacy writer,
- update Group Analysis documentation status.

Deliverable:

- implementation complete and documented,
- clear follow-up queue for deferred items.

### Required closeout update for the last PR

In the final PR of this roadmap, update documentation with a short release-status block that includes:

1. **Implemented in this cycle**
   - bullet list of completed roadmap PRs and shipped behavior.
2. **Not implemented (deferred)**
   - bullet list of explicitly deferred items (for example, metric alias/fuzzy matching).
3. **Next implementation step**
   - one concrete next step with target module(s) and test scope.

Suggested location:

- append a "Status after implementation cycle" subsection in this document,
- optionally mirror a short summary in `docs/group_analysis/codex_group_analysis_instructions.md`.

### 17.2 Status after implementation cycle

#### Implemented in this cycle

- Added roadmap and closeout requirements for incremental delivery via PRs, including a mandatory final documentation status update.
- Clarified the final-cycle closeout format so implementation completion can be tracked consistently across Codex runs.

#### Not implemented (deferred)

- Metric alias mapping across references remains out of scope for this cycle unless separately approved.
- Metric-name fuzzy matching / heuristic similarity matching remains out of scope for this cycle unless separately approved.
- Any enterprise-wide canonical metric-name standardization remains deferred to a later phase.

#### Next implementation step

- Execute **PR 1 — Contracts and request plumbing** by adding and validating `group_analysis_level` and `group_analysis_scope` in `modules/contracts.py` and `modules/export_dialog_service.py`, with backward-compatibility tests.

---

## 18. Test plan

### 18.1 Contracts and request building

Test:

- option parsing,
- normalization,
- backward compatibility.

### 18.2 Scope resolution

Test:

- auto + one reference,
- auto + multi-reference,
- forced single with multi-reference data,
- forced multi with single-reference data.

### 18.3 Spec normalization and classification

Test:

- exact match after numeric normalization to `0.000`,
- limit mismatch,
- nominal mismatch,
- invalid spec,
- parser-noise edge cases.

### 18.4 Capability

Test:

- bilateral capability,
- upper-only GD&T,
- invalid / zero-std cases,
- mixed mode behavior.

### 18.5 Flags

Test:

- `LOW N`,
- `IMBALANCED N`,
- `SEVERELY IMBALANCED N`.

### 18.6 Group normalization

Test:

- missing group → `POPULATION`,
- `POPULATION` behaves like a normal group,
- one-group result skips comparison.

### 18.7 Export integration

Test:

- Group Analysis off → no Group Analysis sheets,
- Light → `Group Analysis` + `Diagnostics`,
- Standard → charts added when eligible,
- scope mismatch → short message sheet + Diagnostics,
- independence from `Extended plots` preset.

---

## 19. Risks and accepted constraints

### 19.1 Metric-name inconsistency across references

This rebuild does not solve cross-reference metric naming inconsistency.

That limitation is accepted for now.

Mitigation for this iteration:

- include `Possible unmatched metrics across references` in Diagnostics.

### 19.2 Input-report quality

Reports may contain incorrect nominal values, missing limits, or inconsistent reporting practices.

Mitigation:

- `Light` remains permissive but explicit,
- `Standard` uses strict comparability rules,
- Diagnostics are mandatory.

---

## 20. Acceptance criteria

This feature is accepted when:

- the export dialog exposes Group Analysis controls,
- Group Analysis can be switched off independently of main export preset,
- `POPULATION` behaves like a normal group,
- `Light` and `Standard` behave according to this document,
- Diagnostics are always generated when Group Analysis is enabled,
- scope resolution behaves exactly as specified,
- mismatched specs are handled exactly as specified,
- normal export remains unaffected when Group Analysis is off,
- tests cover the new logic at service and integration level.

---

## 21. Final implementation note

This specification intentionally favors:

- clarity over exhaustiveness,
- deterministic behavior over heuristics,
- transparent limitations over silent assumptions.

The design should support real industrial troubleshooting, supplier comparison, and production issue triage without forcing full reporting standardization up front.
