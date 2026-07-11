# Release candidate checklist

This is the timeless, authoritative release-promotion gate. It intentionally does
not carry checked boxes from older builds. Exact commands, counts, commit SHAs,
workflow runs, artifacts, waivers, and sign-offs belong in a dated file under
`docs/release_checks/` and must identify the build being promoted.

Canonical release identity comes from `src/metroliza/app/version.py`. Run
`python scripts/sync_release_metadata.py --check` before recording evidence; do
not copy an older build identifier into this checklist.

## 1. Scope, ownership, and freeze

- [ ] Release owner, QA owner, release engineer, and backups are named.
- [ ] Scope is frozen; every late change has rationale, owner, test evidence, and rollback plan.
- [ ] Every open defect is classified as release-blocking or explicitly deferred with owner approval.
- [ ] The dated evidence file records branch, exact commit SHA, public version label, build ID, and artifact IDs.
- [ ] `README.md`, `CHANGELOG.md`, `docs/README.md`, and relevant runbooks describe the current behavior.
- [ ] Dependency pins and sibling checkout SHAs agree across requirements, CI, and hygiene tests.

## 2. Clean Python 3.11 local gate

Use a fresh environment resolved from `requirements-dev.txt`. Record Python,
Ruff, Qt, PyMuPDF, cryptography, and pinned sibling-package versions plus
`python -m pip check` output in the dated evidence file.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip check
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q \
  --cov=src/metroliza --cov=modules --cov=scripts --cov-report= --cov-fail-under=0
```

- [ ] Full tests pass without unexpected skips or first-party import failures.
- [ ] Coverage threshold from `unit-tests` passes.
- [ ] The `unit-test-coverage` artifact `coverage.xml` is reviewed for the exact commit.
- [ ] Ruff, compileall, metadata sync, release hygiene, and CI-mode security audit pass.
- [ ] Dependency audit reports no unapproved known vulnerabilities.
- [ ] Focused performance/query-plan guards pass for every changed hot path.

## 3. Automatic GitHub CI gate

All automatic jobs must reach terminal success for the exact pushed commit:

- [ ] `static-checks`
- [ ] `unit-tests`
- [ ] `windows-core-smoke`
- [ ] `native-artifacts`
- [ ] `cmm-parser-perf-gate`
- [ ] `perf-benchmarks` completes and any advisory regression is reviewed

Record the workflow run URL/ID and exact SHA. A green run for an older commit is
not evidence for the promoted build.

## 4. Packaging and clean-machine gate

- [ ] PyInstaller onefile artifact builds, is versioned correctly, and launches on clean Windows.
- [ ] PyInstaller onedir artifact builds and launches on clean Windows.
- [ ] Nuitka artifact builds and launches, or a dated release-owner waiver explains why it is excluded.
- [ ] Native wheels build for release targets and native plus pure-Python fallback smoke tests pass.
- [ ] Every native wheel resolves with the versioned `Cargo.lock`; lockfiles and the recorded Rust notice inventory match.
- [ ] Representative report parse, SQLite load, dashboard export, and optional workbook export pass from packaged artifacts.
- [ ] Startup evidence covers onefile extraction, Qt splash handoff, first event-loop tick, and feature warmup.
- [ ] `THIRD_PARTY_NOTICES.md` and a visible notices/licenses sidecar ship beside every executable/archive.
- [ ] The resolved Python and Rust dependency/license inventory is attached to the build evidence.
- [ ] Release-owner/legal confirmation is recorded for PyQt/Qt and PyMuPDF distribution obligations.

The hosted `packaging-smoke` and `windows-startup-benchmark` lanes may support
this evidence, but manual clean-machine launch and core-flow checks remain
release-blocking unless the release owner records a specific waiver.

## 5. Google conversion gate

Google conversion smoke is release-blocking for promoted RC artifacts; green CI does not satisfy that gate.
It runs only on a secure local workstation with
a sandbox account because OAuth client and token files are never materialized
on hosted runners.

- [ ] The command in `docs/google_conversion_smoke_runbook.md` runs against the exact build commit.
- [ ] Upload/conversion returns a matching file ID and HTTPS spreadsheet URL.
- [ ] Converted tab titles exactly match the generated workbook (`MEASUREMENTS`, `REF_A` for the smoke fixture).
- [ ] Warnings are empty and the local `.xlsx` fallback remains available.
- [ ] Evidence is recorded in `docs/release_checks/google_conversion_smoke.md` without secrets.

## 6. Product and data-integrity smoke

- [ ] CMM parser native/Python parity and mutation detection pass on representative fixtures.
- [ ] CSV Summary remains dashboard-first; workbook output is explicit opt-in.
- [ ] No eager/direct pandas startup coupling is introduced. Packaging may still include pandas through pinned runtime dependencies.
- [ ] Report edits, grouping assignments, exports, and industrial sync preserve SQLite transaction and rollback behavior.
- [ ] Realtime polling, anomaly events, dashboard snapshots, stale-writer protection, replay, cancellation, and shutdown pass.
- [ ] Google cancel/timeout/fatal-validation paths leave no orphaned converted file.
- [ ] Legacy `modules.*` compatibility imports and documented public paths still resolve.
- [ ] Deprecated Group Comparison and BOM entry points remain compatible for their announced window and emit the expected notice.

## 7. Security and privacy gate

- [ ] Secret scanning covers all tracked text/decodable files, private keys, extensionless files, shell, and PowerShell content.
- [ ] No real reports, databases, logs, exported workbooks, `credentials.json`, or `token.json` are tracked or bundled unintentionally.
- [ ] OAuth/token storage permissions, redaction, migration, and symlink protections pass.
- [ ] CI Actions use immutable reviewed SHAs, least-privilege permissions, disabled checkout credential persistence, bounded timeouts, and concurrency cancellation.
- [ ] Industrial credentials, connection strings, raw SQL, and source payloads remain redacted from diagnostics and logs.

## 8. Promotion decision and rollback

- [ ] No unresolved release-blocking defect remains.
- [ ] QA, release engineering, release owner, and required legal/compliance owners sign the dated evidence.
- [ ] Known issues and tester communication are ready.
- [ ] Previous stable tag/artifact is identified and verified runnable.
- [ ] Rollback owner and procedure are recorded.
- [ ] The RC is merged only after evidence review:

```bash
git checkout master
git pull --ff-only origin master
git merge --no-ff rc2
```

- [ ] The release tag is created from the reviewed merge commit and pushed.
- [ ] Final artifact hashes, publication location, announcement, and post-release monitoring owner are recorded.
