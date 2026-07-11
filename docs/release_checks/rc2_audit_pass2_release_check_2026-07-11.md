# RC2 detailed repository audit pass 2 release check

Date: 2026-07-11
Release metadata: `2026.06rc2(260711)`
Branch: `rc2`
Commit: the integration commit containing this evidence; the exact pushed SHA and
GitHub Actions run are recorded in the final publish handoff.
Scope: release/security policy, parser concurrency, Google export, industrial and
tabular storage, realtime consistency, package boundaries, native reproducibility,
packaging notices, and CI parity.

## Outcome

The automatic local release gate is green. The pass-two audit also found and fixed
two integration defects before publication: a parser registry reload race that
could select one class and construct another, and a CSV Summary snapshot check that
compared a user-facing source column with its normalized internal name.

This evidence does not declare the RC ready for promotion. Clean-machine packaged
application evidence, Windows executable launch evidence, secure Google conversion
smoke, and release-owner/legal notice review remain manual blockers.

## Implemented hardening

### Parser and report correctness

- Parser registration, manifest, and detector updates are protected as one coherent
  generation. Resolvers probe an immutable snapshot and construct the exact class
  selected from that snapshot; re-registration cannot invalidate the decision
  between resolution and construction.
- Probe caching is bounded, single-flight, registration-aware, and invalidated by
  generation. Declarative profile generations publish atomically and invalidate
  changed, removed, disabled, enabled, or rolled-back profiles.
- Source inspection is shared and bounded, source mutation is rejected before
  persistence, and moved parser/report implementations keep exact compatibility
  module identity at their former public paths.
- Report edit SQL and transactions now live in a report service rather than the UI.
  Identifier quoting and fixed query maps close public-helper injection footguns.

### Google, security, and CI

- Google uploads use multipart transfer below 8 MiB and fixed-size resumable chunks
  above it, with bounded retry, offset validation, cancellation/timeout cleanup, and
  converted-file cleanup on fatal validation failure.
- Every Google HTTP request passes through a fail-closed HTTPS boundary restricted
  to approved Google API/OAuth hosts. Response-provided resumable locations are
  independently checked before transport.
- The repository secret scan covers tracked decodable files, extensionless files,
  private keys, shell/PowerShell assignments, and fails closed in CI when a relevant
  candidate cannot be inspected.
- Dynamic SQL findings were individually reviewed. External values stay bound,
  identifiers are quoted or allowlisted, eliminated findings were removed, and the
  remaining application-generated query shapes are expiry-bound in the reviewed
  Bandit baseline through 2026-10-31.
- GitHub Actions use immutable action SHAs, least-privilege permissions, disabled
  checkout credential persistence, job timeouts, and run concurrency cancellation.
  Windows core smoke is automatic and blocking; Google conversion remains local-only.

### Industrial, tabular, realtime, and export paths

- Realtime dashboard refresh reads one SQLite transaction snapshot, limits the
  timeline before joins, and batches related lookups. Older source-health evaluations
  cannot overwrite newer status. Operator-cleared context and segment field lists
  persist as empty without changing legacy default-row behavior.
- CSV Summary grouping assignments use a session-owned, connection-local temporary
  store with explicit cleanup and isolated concurrent dialogs. UI code no longer
  owns private store SQL.
- Internally owned tabular SQLite loads are cleaned on success and failure while
  caller-owned loads remain untouched. Snapshot validation maps source column labels
  to canonical fields before checking reuse.
- Export execution has a typed context and structured completion/warning/cancel
  outcome. Backend cleanup uses public callbacks rather than private attribute access.
- Dashboard manifests are validated before publication and rendered from typed,
  copied data. Workbook and plotting imports remain lazy on the dashboard-first path.

### Architecture, reproducibility, and notices

- Feature request contracts are package-owned under `exporting`, `industrial`, and
  `tabular`; `shared.contracts` is a lazy compatibility facade. App/UI, analytics/
  exporting, reports/parsing, native/CMM, and reports/industrial dependency seams
  were reduced without breaking compatibility imports.
- Canonical package-cycle tests now enforce the reduced four-package SCC budget.
  Exact legacy-reference and C901 ratchets prevent silent architecture regression.
- All five Rust crates carry versioned `Cargo.lock` files; build commands use
  `--locked`. The metadata-derived Python/Rust inventory regenerates byte-equivalent
  content after excluding its timestamp.
- PyInstaller/Nuitka helpers stage `THIRD_PARTY_NOTICES.md`, the dependency inventory,
  and a hashed notice manifest beside packaged artifacts. CI packaging smoke verifies
  and uploads those files with the binary.

## Local validation

Environment: CPython `3.11.15`, PyQt `6.6.1`, Qt `6.6.1`, PyMuPDF `1.28.0`,
cryptography `49.0.0`, Ruff `0.15.10`, and mypy `2.2.0`. `pip check` reported no
broken requirements.

| Check | Result |
|---|---|
| Exact CI coverage recipe | Passed: base suite `2800 passed, 21 skipped, 10 warnings, 97 subtests passed` in `400.99s`; all nine real-Qt append shards passed (`24`, `40`, `79`, `12`, `15`, `79`, `93`, `142`, and `39` tests; the eighth shard also passed `3` subtests). |
| Combined coverage | Passed at `83%`, above the blocking `80%` threshold; `coverage.xml` generated. |
| Parser concurrency/profile focused gate | Passed: `82 passed`, including deterministic concurrent registration and same-ID class-swap barriers. |
| CSV Summary benchmark/workflow regression gate | Passed: `26 passed`. |
| Ruff and compileall | Passed for the full repository. |
| Strict mypy boundaries | Passed for the three CI boundary modules and the three new package-owned contract modules. |
| Release metadata, hygiene, docs links, and whitespace | Passed. |
| CI-mode security audit | Passed with live dependency lookup: `No known vulnerabilities found`; `150` reviewed Metroliza and `4` reviewed sibling findings accepted, with no unbaselined medium/high finding. |
| Native Rust release tests | Passed offline with Python 3.11, `--locked`, and isolated targets for all five crates; comparison statistics passed `2` unit tests and the other crates completed their zero-test build smoke. |
| Third-party inventory regeneration | Passed: generated content matches `third_party_inventory_260711.json` after excluding `generated_at`. |
| Local packaged executable | Not produced: PyInstaller, Nuitka, and maturin are not installed in the Python 3.11 release venv. No local executable smoke is claimed. |
| Pushed GitHub Actions | Pending at evidence-authoring time; publication must record the exact final SHA and terminal run. |

## Remaining release-promotion blockers

- Build PyInstaller onefile/onedir and Nuitka release artifacts in the approved Python
  3.11 build environment, stage notices, and exercise representative parser, SQLite,
  dashboard, and opt-in workbook flows.
- Launch the Windows executable on a clean machine and record splash, first event-loop
  tick, feature warmup, core-flow, and artifact-hash evidence.
- Run the secure local Google conversion smoke against the exact build and record file
  ID, HTTPS URL, `MEASUREMENTS`/`REF_A` tab validation, warnings, and fallback status
  without credentials or tokens.
- Obtain release-owner/legal review for the generated inventory and PyQt/Qt and
  PyMuPDF distribution obligations.
- Record the exact pushed commit and terminal GitHub Actions run; automatic green CI
  does not waive any manual blocker above.
