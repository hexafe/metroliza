# Documentation Index

This directory contains active operational and maintenance documentation.

## Active docs

- Group Comparison worksheet interpretation and statistical caveats: see root `README.md` section "Group Comparison export sheet".
- `documentation_policy.md` — policy for permanent vs temporary docs, archival, and ownership.
- `google_conversion_smoke_runbook.md` — local Google Sheets conversion smoke guidance.
- `native_build_distribution.md` — native build/distribution workflow and packaging references.
- Grouping dialog color policy uses shared semantic tokens from `modules/ui_theme_tokens.py` (base row background, selected-row colors, default group color, and generated group palette) so dialogs stay visually consistent across light/dark themes.
- `roadmaps/2026_03_rc1_test_ci_execution_tracker.md` — active RC1 test/CI audit and incremental execution tracker.

### Active release-check docs (`docs/release_checks/`)

Canonical release operations docs (release gate/source-of-truth set):

- `release_checks/release_status.md` — current release operational status and entry-point links.
- `release_checks/release_candidate_checklist.md` — primary RC gate checklist and required sign-offs.
- `release_checks/open_testing_runbook.md` — open-testing execution runbook and evidence expectations.
- `release_checks/branching_strategy.md` — authoritative branch naming/rules used during release work.
- `release_checks/google_conversion_smoke.md` — required release smoke evidence log for Google conversion checks.

Supplemental tutorial/playbook docs (how-to guidance that supports, but does not override, canonical docs):

- `release_checks/release_branching_playbook.md` — practical branch workflow examples.
- `release_checks/release_playbook_beginner.md` — beginner-friendly end-to-end RC walkthrough.

## Archive

Retired planning/temporary docs are under `archive/`.

- Archive entry point: `archive/README.md`
- UI revamp historical planning set: `archive/2026/ui-revamp/README.md`
- Year buckets: `archive/YYYY/`
