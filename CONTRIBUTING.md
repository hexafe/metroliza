# Contributing to Metroliza

## Before starting work

- Read [`docs/project/README.md`](docs/project/README.md) for the current source-of-truth hierarchy and repository/branch state.
- Start from a GitHub Issue and follow [`docs/project/development_workflow.md`](docs/project/development_workflow.md).
- Use [`docs/project/roadmap.md`](docs/project/roadmap.md) for current priorities; old roadmap checklists do not schedule work by themselves.
- Branch normal development from `develop` and target pull requests at `develop`.
- Branch only approved release fixes/evidence from `release/2026.06-rc2` and target that release branch; reconcile accepted release changes into `develop`.
- Do not start new routine work from `rc2` or the current production `master`; neither is the
  development base.
- GitHub currently presents `master` as the default branch, so select the pull-request base explicitly.
- Keep one primary Issue per pull request and separate behavior changes from structural refactors.

The exact branch decision and automated evidence are recorded in
[`docs/release_checks/rc2_branch_transition_decision_2026-08-22.md`](docs/release_checks/rc2_branch_transition_decision_2026-08-22.md).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements-dev.txt
```

Dependency files are split by purpose:

- `requirements.txt` for runtime.
- `requirements-dev.txt` for local development/tests.
- `requirements-build.txt` for packaging executables.

## Pre-commit hooks

Install and activate local hooks once per clone:

```bash
pre-commit install
```

Run all hooks on demand before opening a PR:

```bash
pre-commit run --all-files
```

The hook set includes whitespace/end-of-file normalization, Ruff linting, and secret-pattern checks. The committed allowlist keeps `config/google/credentials.example.json` as a permitted example template while still blocking real secret files such as `credentials.json`, `token.json`, `*.credentials.json`, and `*.token.json`.

## Baseline checks

Before opening a PR, run the validation tier required by the Issue. The baseline source checks are:

```bash
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
PYTHONPATH=src:. python -m ruff check .
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q
```

Do not claim packaged, clean-machine, Google, or other manual behavior from baseline tests alone. See the validation tiers in `docs/project/development_workflow.md`.

## Architecture notes

Metroliza's core flow is:

1. **Preflight/parse** (`src/metroliza/parsing/`) inspects inputs, resolves a parser, and normalizes reports/rows.
2. **Persist** (`src/metroliza/reports/`, `src/metroliza/storage/`, and domain repositories) stores and queries SQLite data.
3. **Group/filter/analyze** (`src/metroliza/tabular/`, `src/metroliza/industrial/`, `src/metroliza/analytics/`) prepares and evaluates selected data.
4. **Export/publish** (`src/metroliza/exporting/`, `src/metroliza/charts/`) creates Excel outputs and offline dashboards with optional Google conversion.

The full current package map and dependency rules are in [`docs/project/architecture.md`](docs/project/architecture.md).

## Contracts usage

Request/option contracts live with their owning packages:
`src/metroliza/shared/parse_contracts.py`, `src/metroliza/exporting/contracts.py`,
`src/metroliza/industrial/contracts.py`, and `src/metroliza/tabular/contracts.py`.
`src/metroliza/shared/contracts.py` is compatibility-only.

- Parse flows should build and validate `ParseRequest`.
- Export flows should build and validate `ExportRequest` and nested dataclasses (`AppPaths`, `ExportOptions`, `GroupingAssignment`).
- Prefer adding validation to contract constructors/helpers instead of duplicating checks in UI/dialog code.

## Module naming policy (`src/metroliza/`)

- Use **`snake_case.py`** for all new Python modules under `src/metroliza/`.
- Prefer canonical `metroliza.*` imports in new and touched implementation code.
- CamelCase module filenames are no longer supported; use snake_case paths exclusively.
- The root `modules/` tree is compatibility shim space only; do not add new implementation code there.
- The completed migration closeout is archived at [`docs/archive/2026/module_naming_migration.md`](docs/archive/2026/module_naming_migration.md).
- Behavior tests should migrate toward canonical imports; keep only explicit compatibility tests on `modules.*` as tracked by Issue #905.

## Coding guidance

- Keep changes incremental and aligned with the linked Issue and active project/release docs.
- Prefer shared helpers in `src/metroliza/reports/db.py` over direct `sqlite3.connect` in feature modules.
- **Transaction granularity:** each logical write unit (for example inserting one parsed report and all related measurements, or applying all edits from one Modify DB submission) must execute inside a single `run_transaction_with_retry` call so retries are atomic and rollback-safe.
- Use `run_transaction_with_retry` for multi-statement write workflows; keep retries centralized in `src/metroliza/reports/db.py` rather than implementing ad-hoc retry loops in feature modules.
- Add or update tests in `tests/` for each behavior change.
- Naming and boundary guardrail: `tests/test_directory_reorganization_architecture.py` enforces canonical source packages and legacy-shim boundaries.
- Do not hide follow-up work in TODO comments or stale Markdown checklists; create a GitHub Issue.
- Do not commit credentials, OAuth tokens, proprietary reports, production extracts, private keys, or unredacted sensitive diagnostics.

## Documentation source-of-truth hierarchy

Follow the canonical hierarchy in `docs/project/README.md` and `docs/documentation_policy.md`:

1. **GitHub Issues** define accepted in-flight work and its acceptance criteria.
2. **`docs/project/`** defines current product scope, architecture intent, roadmap, and development workflow.
3. **`docs/release_checks/`** defines release state, evidence, blockers, and promotion decisions.
4. **`docs/user_manual/`** defines current end-user behavior.
5. **`docs/archive/YYYY/`** and explicitly historical/reference-only plans preserve context but do not assign new work.

Key release entry points remain:

- [`docs/release_checks/release_candidate_checklist.md`](docs/release_checks/release_candidate_checklist.md)
- [`docs/release_checks/release_branching_playbook.md`](docs/release_checks/release_branching_playbook.md)
- [`docs/release_checks/branching_strategy.md`](docs/release_checks/branching_strategy.md)
- [`docs/release_checks/rc2_branch_transition_decision_2026-08-22.md`](docs/release_checks/rc2_branch_transition_decision_2026-08-22.md)

## Documentation sync policy

- Keep documentation-only synchronization separate from implementation when practical.
- When adding/renaming an active document under `docs/`, update `docs/README.md` in the same change.
- Use `docs/project/roadmap.md` as the single current planning overview and GitHub Issues as executable work.
- Treat archived implementation plans as historical context only.
- For release-candidate documentation, use `docs/release_checks/release_candidate_checklist.md` as the RC gate source of truth and update all linked evidence files in the same closeout slice.
- For Google export docs, explicitly describe required local secret files and the guaranteed local `.xlsx` fallback.
- For branch/release guidance, follow `docs/release_checks/branching_strategy.md` and keep release scope frozen after `release/<version>-rcN` is cut.
- For a beginner-friendly release walkthrough, see `docs/release_checks/release_playbook_beginner.md`.

## Google export contributor checklist

When touching Google conversion/auth flows, validate and document:

1. **Prerequisites:** local OAuth setup, required environment variables for optional smoke checks, and sandbox-account usage.
2. **Secrets posture:** `credentials.json`/`token.json` are local-only, never committed, and covered by `.gitignore` patterns.
3. **Fallback behavior:** conversion degradation/failure messaging still reports the preserved `.xlsx` output path.
4. **Testing strategy:** baseline automated tests remain passing; live smoke remains release-gated and non-default.
5. **Troubleshooting notes:** conversion warning guidance stays current in `README.md` and user docs.
6. **PR evidence:** any PR touching `src/metroliza/exporting/google_drive_export.py`, `src/metroliza/exporting/export_backends.py`, `src/metroliza/exporting/export_data_thread.py`, or Google export UI/contract/transport paths must include the standard Google conversion smoke evidence or explicit omission justification.

## Pull request expectations

Use `.github/pull_request_template.md` completely. In particular:

- select the correct base branch explicitly;
- link the primary Issue;
- state scope and non-goals;
- identify contracts, risk, failure, cancellation, and rollback behavior;
- select a validation tier and record exact commands/results;
- for release-line changes, document reconciliation into `develop`;
- update project, user, or release documentation when applicable;
- ensure evidence refers to the exact PR head/content tree.
