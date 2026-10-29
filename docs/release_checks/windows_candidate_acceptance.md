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

After freezing finishes, install the pinned acceptance-host dependencies into
the build interpreter. Keep them out of the frozen application. Use the installed
Windows Edge executable explicitly; do not download a browser during acceptance.

```powershell
$candidatePython = '.\.venv-build\Scripts\python.exe'
& $candidatePython -m pip install -r requirements-windows-candidate-host.txt
if ($LASTEXITCODE -ne 0) { throw 'Acceptance host dependency installation failed' }
$candidateBrowser = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
if (-not (Test-Path -LiteralPath $candidateBrowser -PathType Leaf)) {
  throw 'The approved installed Windows Edge executable is required'
}
```

Then run the driver from that same clean source checkout. Replace the artifact
path with the actual release-derived onedir directory produced by the wrapper;
the output must be a new directory outside the source, fixture and package trees.

```powershell
$candidateSource = (Get-Location).Path
$candidateHead = (git rev-parse HEAD).Trim()
& $candidatePython scripts/qualify_windows_candidate_core.py `
  --source-checkout $candidateSource `
  --expected-source-sha $candidateHead `
  --artifact-dir 'C:\Metroliza acceptance\actual onedir' `
  --fixture-dir "$candidateSource\tests\fixtures\windows_candidate" `
  --oracle "$candidateSource\scripts\synthetic-report-oracle.json" `
  --browser $candidateBrowser `
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

Every Reports producer clicks the real Import control before waiting for metadata
to become idle. It binds the newly accepted import operation, observes its queued
start and terminal result within the existing 45-second import deadline, then
confirms native worker completion. A cleared `parse_thread` alone is not evidence
of success: fast completion, worker error and cancellation retain the outcome of
that specific operation. Cancel and owner cleanup discard pending starts before
canceling and joining existing workers; closing must never launch a queued import.

Failed core receipts retain a bounded `cleanup_failure` alongside the primary
`failure` when both occur. Cleanup failure always fails qualification. W06 failures
also retain `inference_failure` and `inference_failure_stage` (fixtures, review,
import, cleanup, database, groups, public_service or artifact), so an import failure cannot be
mistaken for a statistical mismatch. Producer and host validate these closed
identifiers; raw exception messages and private paths are excluded.

A nonzero launcher exit always fails, including after a completed scenario. If
the full packaged core receipt validates against the requested source, native mode
and DPR, the host records `receipt_state=valid_success` and
`failure_category=post_success_nonzero_exit`. A `complete` stage marker alone
does not establish that the success receipt was written. Invalid, missing or
source-mismatched receipts retain their existing failure classification. There
are no host retries or increased deadlines.

### Post-success process exits

RC `6a604a1e`, Combined run `40937991935`, core DPR 1.0 reached a valid
success receipt but exited with `0xC0000005`. Its last atexit census still found
a live QApplication and 869 Qt wrappers (319 already deleted), with 10 Python
threads including 9 daemons. The fatal observation identifies the main thread,
one remaining Python thread state and no Python frame. These findings narrow
the failure to native interpreter-finalization work; the census alone cannot
identify the destructing object or the daemon thread names.

Product event-loop return and every returning package qualification flow now
use GUI-thread teardown before interpreter finalization: request chart-pool
shutdown for every pool, then join chart workers and use the existing bounded
detached-thread shutdown within one shared monotonic 5-second deadline,
delete already-hidden top-level widgets without calling close or delivering a
close event, then drain deferred deletes. Any visible top-level retains Qt
untouched; teardown cannot prompt or repeat product close handlers. The GC timer
stops while automatic GC remains disabled, followed by collection on GUI and a
scan for live widgets, running QThreads and foreign-thread QObjects. Only after
successful QApplication destruction is the previous GC state restored. Retention
keeps automatic GC disabled for main-thread finalization. Failed/incomplete cleanup retains the
application safely and never changes the scenario exit code.
The chart joins use the remaining deadline even if the normal Quit hook has
already spent its detached-thread wait; that detached wait is never granted again.
Thus the chart join shares the teardown's 5-second budget after aboutToQuit's
existing wait (up to 5 seconds). Close-handler waits add no teardown latency
because teardown never calls close. Event callbacks and Python finalizers are
not preempted by this deadline. A later application-factory call after release
raises rather than creating an unsafe second QApplication (#1119).
Closed startup profile events report completion/counts without object or exception text.
Linux offscreen regression evidence proves the teardown contract only. The
proposed root cause is confirmed only once Windows Combined passes with the
exit census showing a released application; nonzero exits still fail.

The Python supervisor and portable envelope convert Windows child DWORDs in
`0x80000000..0xffffffff` to signed int32 before `SystemExit`, preserving the
bits through CPython's signed C exit argument, including Python 3.11. POSIX and
integers outside the DWORD range retain their existing platform behavior.
This fixes launcher exit-code masking; it does not suppress termination or
qualify a nonzero exit as success.

Failed diagnostics retain the exact `observed_exit_code` and, for every nonzero
code, a consistent `observed_exit_class` from this closed table:

| DWORD | Class |
| --- | --- |
| `0xC0000005` | `access_violation` |
| `0xC0000409` | `stack_buffer_overrun` |
| `0xC0000374` | `heap_corruption` |
| `0xC00000FD` | `stack_overflow` |
| `0xC000001D` | `illegal_instruction` |
| `0xC0000008` | `invalid_handle` |
| `0xC0000142` | `dll_init_failed` |
| `0xC000013A` | `control_c_exit` |
| `0xE06D7363` | `cpp_exception` |
| `3` | `abort_3` |
| `0xFFFFFFFF` | `all_ones` |
| Other `0xC0000000..0xFFFFFFFE` | `other_ntstatus_error` |
| Any remaining nonzero DWORD | `other_nonzero` |

`child_wait_ntstatus_error` and `child_wait_high_bit_other` distinguish
`0xC0000000..0xFFFFFFFE` and `0x80000000..0xBFFFFFFF` at the child handle.
The all-ones bucket remains separate. Host validators reject unknown or
code-inconsistent classes.

Only the existing startup-probe gate plus the qualification-root environment
and `METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION=1` enable early all-thread
faulthandler capture in the application entry. Diagnostic `normal` and
`concurrent` modes alone do not enable it. The sink is a private, non-inheritable
raw OS descriptor, held open until exit and removed with the existing private-root
cleanup. The host reads at most the last 64 KiB only after owned-process cleanup completes.
It retains only `child_fatal_observation`: `present`, a closed `kind`
(`access_violation`, `stack_overflow`, `code_0x` plus eight lowercase hex digits,
`fatal_python_error` or `other`), up to 12 `stem:function` frames from the
Current thread stack, `truncated`, and the boolean `multiple_blocks` (more than
one complete exception header observed in the retained tail). Windows can log
handled first-chance exceptions; only the last header-led block supplies the
kind and frames. A partial leading block is discarded. A block without a
Current thread header has no frames; `<no Python frame>` is a complete empty
stack. A tail cut sets `truncated`; `multiple_blocks: false` does not exclude
earlier exceptions outside that tail. Stem and function lengths are at most 64;
only `[A-Za-z0-9_.]` and `[A-Za-z0-9_<>]`, respectively, are accepted.
Frames are shortened further, with `truncated: true`, if needed to preserve
the existing failure and phase fields within the byte limit.
The last block also supplies `current_thread_marked` (a Current thread header
exists), `python_threads` (thread-header count, capped at 32), and
`faulting_is_main` (`true`, `false`, or `"unknown"`). The child records the main
Python thread ident at sink enable in an exclusively created fixed-format private
sidecar. The host compares numeric ids, accepting zero padding differences, and
never publishes them. A missing/invalid sidecar or an unmarked fault gives
`"unknown"`. When the current thread is unmarked or differs from main,
`main_frames` retains at most six frames from the matching main-thread stack,
using the same stem/function restrictions. No main stack is inferred when its
header is absent. A native fault without a Python thread state may leave every
Python stack labelled Thread, with no Current thread; an empty `frames` array
alone therefore cannot identify the faulting thread.

Paths, line numbers, raw text and unrelated thread stacks are excluded from public
evidence, which remains bounded to 4096 bytes. Faults after
`_PyFaulthandler_Fini`, including late finalization or DLL unload, cannot be
captured: `present: false` is valid and is recorded explicitly. Because a
handled first-chance exception is also logged, `present: true` with a matching
`observed_exit_class` does not prove that the retained block is the terminating
fault: a late fault, or a fail-fast that bypasses the vectored handler
(for example `0xC0000409`/`0xC0000374`), leaves only the earlier handled block.
These observations discriminate exits without establishing their root cause.

Under exactly the fatal-sink gate, the package entry registers an exit inventory
callback before its other callbacks and before `child_atexit_reached`. Atexit's
LIFO order makes the inventory run last among the entry's own callbacks. PyQt's
QtCore atexit cleanup (`cleanup_on_exit` / `pyqt6_cleanup_qobjects`) runs before
this census, as does Python's threading shutdown. Thus `qapp_alive` and the
wrapper counts describe the state after PyQt cleanup, before subsequent
interpreter GC/module teardown; they do not prove that teardown completed.
The census never imports Qt, explicitly collects garbage, deletes objects,
changes SIP exit policy, or retains wrappers after returning. Automatic GC is
disabled for the census and its previous state is restored in `finally`,
including on Python errors. Python callback exceptions, including
`BaseException`, are caught and do not escape; native faults cannot be caught by
this handler. The census adds work before finalization and perturbs timing, so
occurrence rates are not directly comparable with earlier runs. It does not
guarantee an unchanged process exit code.

The private inventory JSON has only `qapp_alive`, `qt_wrappers`, `qt_classes`,
`cpp_created_wrappers`, `py_owned_wrappers`, `threads_alive`, `daemon_threads`, `daemon_thread_names`,
and `deleted_wrappers`. Only already-loaded PyQt6 modules are consulted.
GC-tracked SIP wrappers, including wrappers for deleted C++ objects, are counted
up to 1000000 using type names and wrapper-only SIP flag queries:
`sip.isdeleted`, `not sip.ispycreated` for `cpp_created_wrappers`, and
`sip.ispyowned` for `py_owned_wrappers`. These are intended to read wrapper
state; that they never touch the C++ object on every PyQt6-sip build is not
independently verified. These independent counts can overlap.
They do not establish native object liveness: `isdeleted` may miss C++-side
deletion of C++-created objects. No Qt method is called (including
`parent()` and `QCoreApplication.instance()`, which could build a wrapper and
run sub-class conversion on the C++ object), and the census does not construct
Qt wrappers. `qapp_alive` means an existing application wrapper is in the
census and is not flagged deleted.
The SIP query signatures are documented in the installed `PyQt6/sip.pyi` API
stub; their ownership/origin meanings are described in the
[SIP ABI 13 API](https://python-sip.readthedocs.io/en/stable/abi_13.html).
The top 12 `[ClassName, count]` pairs sort by descending
count then name. Names must match `^[A-Za-z_][A-Za-z0-9_]{0,48}$`; all others
count as `other`. Thread counts come from `threading.enumerate()` and share the
1000000 cap. This is a census of GC-tracked wrappers and enumerated Python
threads, not every native object or thread.
`daemon_thread_names` contains up to 8 `[name, count]` pairs, sorted by descending
count then name. Runs of digits are replaced with `N` before checking
`^[A-Za-z][A-Za-z0-9_.-]{0,40}$`; rejected names count as `other`.
Only daemon entries in the capped census contribute. This can include Python
DummyThread entries for completed native threads; names do not prove that those
native threads are still running. Historical inventories without names cannot
identify the nine daemon entries retroactively.
The host requires the new field; an older private inventory without it is invalid
and reads as `null`, rather than implying there were no daemon names.

After owned cleanup, the host reads at most 4096 bytes with the same no-follow,
regular-file, single-link, non-reparse and fstat identity checks as the fatal sink.
Missing, unsafe or invalid inventory becomes `null`, never a zero-object claim.
Both passing and failing core runs print `core_exit_inventory=<json>`; fresh
reopen runs print `reopen_exit_inventory=<json>` from their separate private root.
Failed diagnostics retain `exit_inventory` inside the existing 4096-byte bound,
trimming `daemon_thread_names` first, then `qt_classes`, then stack frames while preserving failure, exit and
phase fields. Counts, booleans, normalized thread names, safe class names and sanitized frame names are
the entire public contract: no object representations, addresses, thread ids,
paths, raw text or exception messages. Private sidecars are removed with the
owned root. Probes perturb timing; surviving Qt wrappers without an application
are a diagnostic lead, not proof that SIP or Qt caused the access violation.

Core runs enable the opt-in startup probe in a separate owned private directory,
leaving the scenario's initially empty root intact. The host retains only fixed
phase names from empty, regular, single-link, non-reparse marker files. Phases
cover the child's application/scenario return, requested exit and recorder close,
the supervisor's observed child exit and receiver drain, and publisher/storage
completion. `child_atexit_reached` and `launcher_atexit_reached` are registered
only under the probe gate and record entry into Python's atexit callbacks; they
do not prove completion of interpreter or native teardown.
`child_wait_zero`/`child_wait_nonzero` describe the supervisor's child handle;
`child_wait_all_ones` and `launcher_exit_all_ones` additionally distinguish -1 or
4294967295 at their respective boundaries. The numeric `observed_exit_code` belongs to the named
`requested_launcher_handle` (or `fresh_reopen_launcher_handle`). They must not be
treated as the same process. Failure receipts retain an allowlisted
`startup_phases` array within a 4096-byte envelope. Successful core runs retain
separate `core` and `reopen` process-phase records inside the hash-bound
`fresh-reopen-observation.json`, using separate probe roots. Marker presence proves only that the
boundary was reached, absence is inconclusive, and array order is the allowlist
order rather than an event timeline. Probes perturb timing and cannot establish
the cause of an earlier uninstrumented exit. No raw text, paths or exception
messages are retained in this phase evidence.

### Faulting module evidence

The combined Windows job always attempts a bounded Application log query after
the core/fallback steps, from its recorded UTC job start. Event 1000 from
`Application Error` supplies the faulting module; Event 1001 is not queried
because it adds no required closed field. `fault-events/fault-events.json`
(schema version 1) retains at most eight events, newest first, for exact packaged
application, launcher, OCR worker and compute worker basenames. The query reads
at most 64 events; `truncated` also signals that this query cap was reached.

Only the allowlisted application basename, validated module basename and numeric
version, normalized hexadecimal exception/offset, and whole seconds since job
start survive reduction. Invalid module names become `other`; invalid versions
and hex values become `unavailable`. No paths, users, SIDs, report IDs, raw event
text or dumps are retained. Query/parse failures produce `status: unavailable`
with a closed reason token. This optional evidence never changes qualification
outcomes: every nonzero process exit still fails. Events are associated by name
and time window, not by a retained PID; a matching module is a diagnostic lead,
not proof of the root cause or of which scenario faulted. Missing/delayed Windows
events do not prove absence of a fault.

### Further core observations

The literal-label export additionally checks formula-looking text, non-ASCII
labels, series caches, local references, values and limit order. A corrupted local
cell with unchanged chart cache must fail comparison. Pre-cancel and oversized
label rejection must preserve the prior completed workbook. The W07 source
operation also starts the actual `ExportDataThread`, waits for its measurement
stage progress above its entry value, after a completed header unit, while it is still running, then calls its cooperative cancel
seam. That canceled run must retain the previous complete workbook bytes and
leave no temporary workbook publication file.

The additional W06 case imports ten real synthetic PDFs into a separate SQLite
database through the same Reports workspace. It reuses two original 10.02 PDFs
and generates eight reports in private scratch space. Filename-resolved groups
A (9.90, 9.92, 9.94, 9.96, 10.02) and B (10.02, 10.04, 10.06, 10.08, 10.10)
each contain five observations. The public analysis must be runnable, with one
matching metric, Student t-test, adjusted p-value 0.0020 and Cohen's d -2.836.
An independent standard-library comparator checks the actual persisted rows,
group membership and public result against separately specified expected values.
It checks both the original and retained inference database and JSON artifact.
This fixed case supplements the preserved one-group negative boundary.
The core reports W03, the named W04 guards, W05, W06 and the bounded W07 export contract as executed.
A second real MainWindow reopens the completed import's Reports source and DB
context. Exact schema and complete logical SQLite dump, public measurements,
counts and source hashes must remain unchanged, with no sidecars. Normal startup
recovery can rewrite the physical database without changing that content; both
physical hashes are retained and the final artifact digest is bound only after
semantic comparison succeeds. Each read-only observation itself must preserve
bytes and leave no sidecars. This reopen check is context rebind only. An additional real Reports workspace
then imports the same two approved reports while a filter hides them, retains
selection across Home/Tools/Reports navigation, rejects both duplicates on a
fresh review, rejects a source changed after review and restores a valid plan
with re-review. A barrier at the real parser batch entry lets an active worker
receive the ordinary MainWindow close/cancel request before parsing/commit.
The window must defer close, the real worker must cancel, and the prior logical
SQLite contents and all source hashes must remain unchanged. This proves that
named cancellation boundary, not every later transaction boundary.

The W04 driver waits for the complete owned Job to exit, then accepts either no
SQLite sidecars or only a regular, single-link, non-reparse, zero-byte WAL plus
exactly 32 KiB SHM. It rejects journals, nonempty WALs and other SHM sizes,
checks the entire logical dump with an immutable read against the pre-cancel
digest, and verifies that database and sidecar hashes stay unchanged through
observation. It independently verifies the persisted measurements on an exact
sidecar-free copy using the existing public oracle, rechecks all five source
hashes, and retains that verified copy. A real duplicate review may leave an
inert WAL/SHM pair while the GUI runs; that child observation is recorded
separately and never treated as proof of final cleanup. The child
physical database hashes describe in-process observations; the host calculates
and verifies the retained artifact hash after the complete Job exits. W07 covers exact literal output plus failed,
pre-cancelled and in-flight cancelled publication preservation; it does not
establish arbitrary close paths or desktop Excel rendering. Cleanup always joins
the export thread before returning, including after an operation failure; the
existing external Job/watchdog bounds a worker that cannot stop cooperatively.
The host rejects inconsistent check statuses, and separately requires a native
ordinary-user packaged runtime before accepting any Windows observation.

After all application processes exit, the driver verifies the seven original artifact hashes and the additional W04 database
and rejects SQLite sidecars except the strictly inert W04 pair above. It compares the actual database, workbook, grouping
and tabular results against the reviewed oracle and checks literal OOXML. It
repeats comparison on retained copies. The receipt binds source/tree, package,
notices, driver, both oracles and comparator hashes. Both databases must remain
closed and byte-identical through comparison, with no journal sidecars created.

## Dashboard and native geometry slice

The same application scenario seeds two public synthetic industrial samples,
opens realtime monitoring from the actual MainWindow, and uses its real debounced
worker and private output owner to generate offline dashboard HTML. It checks
source content, retains a byte-identical copy, and requires owned private output
cleanup on close. The host independently checks the retained HTML and its hash,
then renders those exact bytes in the explicitly selected Windows browser through
the pinned Playwright host tooling. The disposable browser profile runs offline,
with its sandbox enabled and only the pinned local document allowed. Real DOM/JS
and layout observations cover 1280x720 and 390x844 viewports, required sections,
signal chart and sample points, containment and table scrolling. External resources,
unexpected scripts, overflow, changed input bytes or incomplete browser/profile
cleanup fail the gate. The host retains the separate `browser-observation.json`
and its hash. The application receipt still records browser rendering as
`not_assessed`: rendering belongs to this subsequent host observation.

On Windows the slice also requires Windows QPA, a 1920x1080 physical display,
and the requested DPR. It checks the main frame and actual industrial data,
source profile, and synchronization dialogs for containment, resizing, scrolling,
focus access and overlapping bulk controls. Use `--dpi-scale 1.0`, `1.25`, and
`1.5` in separate owned runs of the same immutable package. The driver rejects
partial/source geometry observations as Windows evidence. A close refusal or a
still-visible owner fails cleanup and retains the object instead of deleting it.
Source execution records Windows geometry as `not_assessed`. A Linux browser
receipt is source engineering evidence only and is rejected by the Windows host
gate. The browser checks above still require execution on the final package.

## OCR slice

The application scenario also passes the pinned image-only-header PDF through the
public parser and actual RapidOCR CPU inference. It binds the declared model
assets and verifies extracted metadata provenance and measurements against an
independent host oracle. The host retains `ocr-observation.json` and its hash.
Existing source observations do not establish packaged Windows inference; run
this check with the same final package used for the other core facets.

## Optional native fallback slice

Run the same complete driver once with `--native-mode default` and once with
`--native-mode unavailable`, using separate new output directories and the same
immutable `-WithNative` package, source SHA and independent oracles. The latter
is a qualification-only control: it verifies all sixteen native callables are
present, temporarily makes those exact bridge bindings unavailable, and runs the
real import/SQLite/filter/analysis/export journey. The normal frozen-backend
policy remains unchanged. No package files, Python modules or product services
are removed or replaced. Owners cancel and join their workers before bindings
are restored, including on an ordinary operation failure. If a bounded join
itself fails, the synthetic child exits unsuccessfully into its owned Job teardown
with native bindings still unavailable; no successful native observation is
written and no live fallback worker is switched back to a native implementation.
Both runs must independently match the same expected data and outputs; success
of one mode cannot substitute for the other. The host binds the requested mode,
exact binding list, initial availability, disabled count and restoration in
`native-observation.json` and its artifact hash. This proves behavior with native
callables forced unavailable; it does not claim a physically missing-module
installation or native-versus-Python numerical equivalence for other inputs.
The final Windows package execution of both modes remains required.

## Remaining acceptance boundaries

This core receipt does not establish every active-work cancellation/close,
reopening or drift path, inference beyond the fixed W06 case,
incident-menu behavior,
privacy negative paths beyond the observed owned-dashboard path, supported desktop geometry beyond the three named industrial dialogs, clean-machine launch or
desktop Excel rendering. A one-group `insufficient_groups` result proves the
specified grouping outcome; it does not prove inferential analysis.

Those applicable checks remain in the full W01–W16 matrix and their existing
owners' executable scenarios. Run them against the same final package identity.
PO acceptance on controlled copies follows delivery of the full candidate.
Release, live-data and legal/service approvals are separate. Historical SIGSEGV
cause remains UNKNOWN.

## Diagnostic flood observations

A diagnostic flood failure retains an optional bounded
`qualification_failure.flood_observation`: channel and handshake state,
clean-terminal and source-loss-known flags, the source drop counter, ring
counters and the retained event count. A zero source counter with unknown source
loss does not establish zero drops. `receiver_drain_incomplete: true` records a
receiver unfinished at the bounded post-exit snapshot; it remains
INCOMPLETE/FAIL even when ring counters are positive. Its absence on an older
receipt does not establish completed draining. The source drop ceiling
4294967295 means at least that many drops.

The child recorder counts every rejected event exactly, including admissions
that meet the writer's queue lock, and a drained recorder always sends
`ended(dropped=N)`. On close it waits in 1-second windows while the writer still
completes frames, with a 4.094-second total allowance derived from the bounded
queue bytes at a minimum of 64 KiB/s; before handshake completion it does not
wait. Source tests establish these policies, not frozen Windows Quit/relaunch,
anonymous-pipe, inherited-handle, owned Job or process-exit behavior: those
require the same final package on Windows. The historical RC attempt-2
`flood_channel_incomplete` failure remains causally UNKNOWN.

Older builds may reject an incident that carries the new optional drain flag.
Their store reader reports the whole listing INVALID if any incident fails
validation, so one newer incident can hide older valid history in an older
build. Keep the store and read it with a compatible build; this change does not
migrate older readers or delete history.

## Combined workflow and immutable receipt gate

The owner-only `run_windows_candidate_acceptance=1` input in the existing CI
workflow builds one clean `-WithNative` onedir, then executes the diagnostic
qualifier and core at DPR1.0/1.25/1.5 plus forced-unavailable at DPR1.0. Its
60-minute job budget is the separate whole-program ledger. The installed Windows
browser and host automation are prepared only after freezing.

The core child publishes a closed startup receipt and, only with the runtime
audit gate enabled, waits for the same bounded host acknowledgement as the V1
qualifier before importing workflow/native services. The host advances its
process-observation phase before allowing work to proceed. This explicit probe
effect prevents lazy work from being classified as startup because of host
polling order; normal program execution has no such wait.

Each core run retains its complete bounded owned-process topology. The final
`finalize_windows_candidate_receipts.py` gate rechecks the diagnostic archive,
all four core receipt identities, retained artifact hashes, native/OCR/browser
observations and owned-job completion. Different source/tree/package hashes,
missing modes or scales, incomplete facets and unresolved operational cost fail.
The resulting `combined-candidate-receipt.json` covers precisely the diagnostic
and four core runs. Remaining W01–W16 facets still require their separate
execution evidence; the gate is not a release or clean-machine claim. Only a
successful job retains the engineering package for the external orchestrator.

The combined core child additionally executes W04 active preflight/export close,
dirty source editor refusal and deferred dashboard context rebind; W12 actual
private-directory creation refusal and Windows sharing-denial cleanup/retry; and
W13 shell/planner layout with Qt keyboard events. These use real workers, services
and SQLite. Scheduling barriers enter the real operation and every owner is joined
before restoring unavailable-native bindings. A failed join exits the owned child
without a PASS or restoration under a live worker.

The independent closeout receipt validator requires packaged context, Windows QPA,
complete native facets and the requested DPR. Source offscreen evidence stays
partial. `windows_qt_planner_keyboard` means QTest-delivered Qt events, not native
Win32 input injection. Shell import is checked against pinned readonly SQLite rows,
not only the worker summary. Synthetic denial handles never target user data.
