# Group Analysis Feature Docs

## Metadata
- **Owner:** Data Export & Analysis Team
- **Status:** Active (draft)
- **Scope:** Temporary working documentation for planning, implementing, validating, and documenting the Group Analysis export surface.
- **Exit criteria:** Feature implementation is merged, validation checklist is complete, and temporary docs in this folder are archived per `docs/documentation_policy.md`.

## Purpose
This folder contains the temporary planning and execution documentation for the canonical Group Analysis workstream.

Current default export contract: Light and Standard create the canonical user-facing `Group Analysis` worksheet without automatically adding a separate diagnostics worksheet. Internal/debug exports may still enable a separate internal diagnostics sheet explicitly.

## Canonical worksheet summary
Group Analysis is the single active grouped statistical export surface.

- The user-facing workbook contract is a **single canonical `Group Analysis` sheet** for both Light and Standard exports.
- Users should read the **title, compact summary, and metric index first**, then jump into the relevant metric block.
- Each metric block keeps descriptive statistics, pairwise comparisons, interpretation/action notes, and on-sheet visual support together.
- The sheet stays **single-tab and user-facing**: no parallel `Group Comparison` worksheet and no default diagnostics tab.
- Layout expectations are explicit: **no freeze panes**, **hidden gridlines**, **selective borders**, and **tuned widths/heights** instead of full-sheet wrapping or full-grid borders.
- Pairwise results should be interpreted with **adjusted p-values first**, then effect size and any shape/distance context.
- Cautions are written for end users and should explain uncertainty sources such as small samples, imbalanced groups, or distribution-shape differences in plain language.
- Standard adds more on-sheet support, especially plots; Light keeps the same reading order with less visual/detail density.

## Workspace status
This directory is the **only active feature-doc workspace** for grouped statistical export planning and validation.

The older `docs/feature/group-comparison-xlsx/` workspace is retained only as legacy reference material and should not be treated as an active source of requirements.

## Documents
- `implementation_plan.md` — implementation approach and sequencing.
- `todo.md` — actionable task list.
- `checklist.md` — completion and quality gates.
