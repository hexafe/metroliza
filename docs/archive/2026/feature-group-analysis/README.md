# Group Analysis Feature Workspace (Archived)

## Metadata
- **Owner:** Data Export & Analysis Team
- **Status:** Archived / historical completed workspace
- **Scope:** Preserved implementation-cycle planning and validation docs from the completed Group Analysis export workstream.
- **Exit criteria:** Retained only as historical context after implementation and closeout.

## Purpose
This folder preserves the temporary planning and execution documentation that was used during the canonical Group Analysis workstream.

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
This directory is **archived**. It is not an active planning workspace.

For active end-user guidance, use [`../../../user_manual/group_analysis/README.md`](../../../user_manual/group_analysis/README.md).
For historical Group Analysis indexing and retained design notes, use [`../../../group_analysis/README.md`](../../../group_analysis/README.md).
The archived pre-consolidation Group Comparison XLSX workspace lives at `docs/archive/2026/feature-group-comparison-xlsx/`.

## Documents
- `implementation_plan.md` — archived implementation approach and sequencing snapshot.
- `todo.md` — archived task snapshot.
- `checklist.md` — archived completion-gate snapshot.
