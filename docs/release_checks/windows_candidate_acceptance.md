# Windows candidate core acceptance

This is the bounded executable core of the #1047 acceptance packet. It exercises
the actual report workspace, parser worker, SQLite services, tabular filters and
Excel exporter. A successful result covers only the facets in its receipt. The
complete #1047 Windows candidate additionally requires the accepted UI,
diagnostics, privacy and geometry composition and its remaining runtime checks.

The package entry enables this scenario only when both
`METROLIZA_STARTUP_SMOKE=1` and `METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION=1` are
present. The existing diagnostics scenario takes priority. The normal application
does not run this synthetic scenario. The host driver sets the gates in an owned
private job; users do not need to configure them for ordinary work.

## Exact-source execution

Use the accepted final merged source and a clean checkout. Keep source-only
engineering results and earlier feature-package receipts with their own source
identities. They do not qualify a later composition.

Build on approved Windows CPython 3.11 x64 with the existing wrapper:

```powershell
.\build_windows_exe.ps1 -Clean -WithNative -Mode onedir
```

Then run the driver from that same clean source checkout. Replace the artifact
path with the actual release-derived onedir directory produced by the wrapper;
the output must be a new directory outside the source, fixture and package trees.

```powershell
$candidateSource = (Get-Location).Path
$candidateHead = (git rev-parse HEAD).Trim()
python scripts/qualify_windows_candidate_core.py `
  --source-checkout $candidateSource `
  --expected-source-sha $candidateHead `
  --artifact-dir 'C:\Metroliza acceptance\actual onedir' `
  --fixture-dir "$candidateSource\tests\fixtures\windows_candidate" `
  --oracle "$candidateSource\scripts\synthetic-report-oracle.json" `
  --output-dir 'C:\Metroliza acceptance\new core receipt'
```

The driver verifies embedded and sidecar provenance, notices and both executable
identities, relocates the complete package, and uses the existing restricted-user
Windows Job launcher. It requires native Windows QPA, ordinary-user execution,
completed supervised process topology and an unchanged package tree. Its outer
deadline is 900 seconds; it does not change product or per-test deadlines.

The receiving process uses the packaged runtime. Python used to run the host
driver is build-host tooling, so this is not a clean-machine claim.

## Inputs and observations

`tests/fixtures/windows_candidate` contains seven fixed public synthetic inputs,
copied byte-for-byte from the accepted #1047 preparation. The driver verifies all
seven hashes before staging private copies. Do not resave the integer CSV in a
spreadsheet program. Its distinct large integer lexemes are intentional.

The five PDFs each contain one `SMOKE FEATURE` measurement: nominal 10, tolerance
+0.1/-0.1, measured 10.02, deviation 0.02, bonus 0. No unit is supplied. Private
aliases supply reference REF001, date 2024-01-01 and samples 0 through 4 without
changing PDF bytes. The GUI selects samples 1 and 3 and verifies two imported and
three excluded reports. Independent comparisons require exact persisted keys,
measurements, grouping membership, exported cells and finite/precision filter IDs.

The literal-label export additionally checks formula-looking text, non-ASCII
labels, series caches, local references, values and limit order. A corrupted local
cell with unchanged chart cache must fail comparison. Pre-cancel and oversized
label rejection must preserve the prior completed workbook.

After all application processes exit, the driver verifies five artifact hashes
and rejects SQLite sidecars. It compares the actual database, workbook, grouping
and tabular results against the reviewed oracle and checks literal OOXML. It
repeats comparison on retained copies. The receipt binds source/tree, package,
notices, driver, oracle and comparator hashes.

## Remaining acceptance boundaries

This core receipt does not establish active-work cancellation/close, every
reopening or drift path, inferential statistics, offline dashboard rendering,
packaged OCR inference, optional-native fallback parity, incident-menu behavior,
privacy negative paths, supported desktop geometry, clean-machine launch or
desktop Excel rendering. A one-group `insufficient_groups` result proves the
specified grouping outcome; it does not prove inferential analysis.

Those applicable checks remain in the full W01–W16 matrix and their existing
owners' executable scenarios. Run them against the same final package identity.
PO acceptance on controlled copies follows delivery of the full candidate.
Release, live-data and legal/service approvals are separate. Historical SIGSEGV
cause remains UNKNOWN.
