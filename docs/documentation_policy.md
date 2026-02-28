# Documentation Policy

This policy defines how Metroliza documentation is created, maintained, and archived.

## 1. Permanent documentation

Permanent documentation is expected to stay current and live in stable, discoverable locations.

Core permanent documents:
- `README.md`
- `CHANGELOG.md`
- Runbooks and operational checklists under `docs/` (for example `docs/release_checks/` and `docs/*_runbook.md`)
- `CONTRIBUTING.md`

## 2. Temporary documentation

Temporary documentation supports in-flight work and should be archived when the work closes.

Typical temporary documents:
- implementation plans
- migration notes
- one-off cleanup plans
- ad-hoc task trackers

Temporary docs should be placed in `docs/` while active, and moved to the archive once stale or complete.

## 3. Archival location

Archive stale temporary docs under year-based folders:

- `docs/archive/YYYY/`

Use the year of archival (not creation) for `YYYY`.

## 4. Review cadence and ownership

- **Cadence:** review documentation quality and freshness at least once per release cycle (or monthly, whichever is more frequent).
- **Owner requirement:** every temporary doc must list an owner (person or role) at creation time; owner is responsible for either keeping it current or archiving it.

## 5. Top-level Markdown rule

Avoid adding new top-level (`/`) `.md` files unless the file is a core repository document (for example `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, or similarly foundational repo-wide docs).

Project/task-specific docs should live under `docs/` and follow this policy.
