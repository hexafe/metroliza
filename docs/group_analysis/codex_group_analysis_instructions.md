# Codex Instructions — Implement Group Analysis Rebuild Step by Step

**Suggested repo path:** `docs/codex_group_analysis_instructions.md`

This document tells Codex how to implement the Group Analysis rebuild using the repository plan in:

- `docs/group_analysis_spec_and_implementation_plan.md`

The goal is to let Codex work in small, reviewable steps while staying aligned with the approved specification.

---

## 1. Core instructions for Codex

Use `docs/group_analysis_spec_and_implementation_plan.md` as the source of truth.

Before changing code:

1. Read the specification document.
2. Inspect the current implementation in the relevant files.
3. Summarize the implementation plan in repo-specific terms.
4. Produce a TODO checklist linked to the phases in the spec.
5. Only then begin implementation.

Do not invent behavior that conflicts with the approved specification.

---

## 2. Non-negotiable rules

Codex must follow these rules exactly:

- Do **not** patch the legacy all-in-one Group Comparison sheet into another large all-in-one design.
- Do **not** introduce a user-facing `Full` mode.
- Do **not** make Diagnostics optional.
- Do **not** couple Group Analysis to the existing `Extended plots` export preset.
- Do **not** invent alias mapping or fuzzy matching for metric names.
- Do **not** treat `POPULATION` as a hidden technical group; treat it like any other group.
- Do **not** use `UNGROUPED` semantics in Group Analysis.
- Do **not** silently compare raw `MEAS` across metrics with nominal mismatch.

---

## 3. Recommended working order

Codex should implement the feature in the following order.

### Step 1 — Planning and repository audit

Read and inspect:

- `docs/group_analysis_spec_and_implementation_plan.md`
- `modules/DataGrouping.py`
- `modules/ExportDialog.py`
- `modules/export_dialog_service.py`
- `modules/contracts.py`
- `modules/export_grouping_utils.py`
- `modules/ExportDataThread.py`
- legacy `modules/export_group_comparison_writer.py`

Then produce:

- a short implementation plan,
- a TODO checklist,
- any repository-specific edge cases discovered.

### Step 2 — Contracts and export request plumbing

Implement:

- `group_analysis_level`
- `group_analysis_scope`

Update:

- `modules/contracts.py`
- `modules/export_dialog_service.py`

Preserve backward compatibility.

### Step 3 — Export dialog UI

Update:

- `modules/ExportDialog.py`

Requirements:

- add a separate Group Analysis subsection,
- add `Group analysis level`,
- add `Group analysis scope`,
- disable scope when level is off,
- keep existing report preset behavior unchanged,
- do not add a Diagnostics checkbox.

### Step 4 — Group normalization and scope helpers

Update:

- `modules/export_grouping_utils.py`

Implement:

- normalization of missing group values to `POPULATION`,
- helper(s) for safe group-label normalization if useful.

### Step 5 — New Group Analysis service layer

Create a new module, preferably:

- `modules/group_analysis_service.py`

Implement pure or mostly pure helpers for:

- metric identity building,
- spec normalization to 3 decimals,
- spec-status classification,
- scope resolution,
- descriptive stats,
- capability calculations,
- pairwise comparison payloads,
- diagnostics payloads,
- main Group Analysis payload assembly.

### Step 6 — New worksheet writer

Create a new module, preferably:

- `modules/group_analysis_writer.py`

Implement:

- `write_group_analysis_sheet(...)`
- `write_group_analysis_diagnostics_sheet(...)`

Keep the worksheet layout user-readable and compact.

### Step 7 — Export integration

Update:

- `modules/ExportDataThread.py`

Integrate the new Group Analysis pipeline:

- skip when level is off,
- prepare filtered grouped rows,
- resolve scope,
- build payload,
- write Group Analysis,
- write Diagnostics.

Keep normal export unchanged when Group Analysis is off.

### Step 8 — Tests

Add or update tests for:

- contracts,
- scope resolution,
- spec normalization and classification,
- capability,
- flags,
- POPULATION fallback,
- Light and Standard export generation,
- Diagnostics generation,
- independence from `Extended plots`.

### Step 9 — Final review pass

After implementation:

- review touched docstrings and concise comments,
- review any README or docs references if needed,
- summarize the final behavior,
- list trade-offs and follow-up opportunities.

### Step 10 — Final PR closeout status update (mandatory)

In the last PR for the roadmap cycle, update Group Analysis docs with a compact status block that clearly states:

- what has been implemented in this cycle,
- what is explicitly deferred/not implemented,
- what the next implementation step is (single concrete target).

Preferred location:

- `docs/group_analysis/group_analysis_spec_and_implementation_plan.md` under a dedicated status subsection.

Optional mirror:

- add a short summary note in this instructions file for future Codex runs.

#### Current cycle status note

- **Implemented in this cycle:** contracts/UI/request plumbing, service/writer baseline, export integration for Off/Light/Standard with diagnostics and scope-mismatch handling, spec-aligned flag semantics (`LOW N`, `IMBALANCED N`, `SEVERELY IMBALANCED N`, `SPEC?`) with tests, and Standard-mode chart insertion for eligible metrics.
- **Deferred (not implemented):** long-term alias/fuzzy/canonical metric matching across references.
- **Next implementation step:** design and implement a deterministic alias/canonical metric mapping strategy in `modules/group_analysis_service.py` (plus diagnostics/writer test coverage) for multi-reference datasets.


---

## 4. How Codex should structure its output in each step

For each step, Codex should provide:

1. what it inspected,
2. what it plans to change,
3. the exact files to touch,
4. why those changes align with the spec,
5. a short summary of what remains.

This keeps the work reviewable and makes it easy to continue with prompts like:

- “Proceed with Step 2 only.”
- “Implement Step 5 only.”
- “Review Step 7 before touching tests.”

---

## 5. Short step-by-step prompts for the user

The user can drive Codex in small increments with prompts like these.

### Prompt A — Planning only

```text
Read docs/group_analysis_spec_and_implementation_plan.md and inspect the current repository files relevant to Group Analysis.
Summarize the implementation plan in repo-specific terms and create a TODO checklist aligned with the phases in the spec.
Do not change code yet.
```

### Prompt B — Contracts and UI only

```text
Implement only Step 2 and Step 3 from docs/codex_group_analysis_instructions.md.
Update contracts, export request plumbing, and ExportDialog UI for Group Analysis.
Do not implement service, writer, or ExportDataThread integration yet.
At the end, summarize what changed and what remains.
```

### Prompt C — Service layer only

```text
Implement only Step 5 from docs/codex_group_analysis_instructions.md.
Create the new Group Analysis service layer based strictly on docs/group_analysis_spec_and_implementation_plan.md.
Do not integrate it into ExportDataThread yet.
Add or update tests for the new helper logic if practical.
```

### Prompt D — Writer only

```text
Implement only Step 6 from docs/codex_group_analysis_instructions.md.
Create the new worksheet writer for Group Analysis and Diagnostics.
Keep it independent from the legacy all-in-one writer.
Do not wire it into export flow yet.
```

### Prompt E — Export integration only

```text
Implement only Step 7 from docs/codex_group_analysis_instructions.md.
Wire the new Group Analysis service and writer into ExportDataThread.
Preserve normal export behavior when Group Analysis is off.
At the end, summarize the integration points and remaining test gaps.
```

### Prompt F — Tests and final review

```text
Implement only Step 8 and Step 9 from docs/codex_group_analysis_instructions.md.
Add or update tests, review touched docs/comments/docstrings, and provide a final implementation summary with trade-offs and follow-up suggestions.
```

---

## 6. Single bootstrap prompt for Codex

If the user prefers a single starting prompt that first creates the planning artifacts before implementation, use this:

```text
Start by reading docs/group_analysis_spec_and_implementation_plan.md.
Inspect the current repository state for all files relevant to Group Analysis.
As your first action, produce or update repository documentation as needed so there is a clear implementation plan and TODO checklist aligned with that spec.
Do not start coding until that planning step is complete and summarized.
After that, proceed step by step according to docs/codex_group_analysis_instructions.md, beginning with contracts and export request plumbing.
At each step, summarize what changed, what remains, and any deviations or risks.
Do not patch the legacy all-in-one Group Comparison sheet into another bloated design.
```

---

## 7. Review checklist Codex should use before finishing

Before claiming the feature is complete, Codex should verify:

- Group Analysis can be turned off independently.
- `Extended plots` still behaves independently.
- `POPULATION` is treated like a normal group.
- missing groups are normalized to `POPULATION`.
- scope resolution follows the approved rules.
- Diagnostics are always generated when Group Analysis is enabled.
- `Light` and `Standard` behave differently in the intended way.
- `NOM_MISMATCH` disables raw A/B comparison.
- upper-only GD&T produces `Cpk+`.
- invalid or mixed specs are handled conservatively.
- normal export still works when Group Analysis is off.

---

## 8. Final note for Codex

Prefer clean, small, explicit helpers and a readable worksheet structure.

This feature is intended for real industrial use:

- supplier comparison,
- root-cause analysis,
- production issue triage,
- trustworthy communication of what was and was not analyzed.

Keep the implementation honest, deterministic, and easy to review.
