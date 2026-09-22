# Supervised diagnostics V1

[Issue #1046](https://github.com/hexafe/metroliza/issues/1046) owns this implementation.
It consumes the separate [S1a startup contract](https://github.com/hexafe/metroliza/issues/1039).
The feature branch's local dependency composition is development evidence until S1a is integrated
into current `develop`; it does not itself grant Ready, merge or release acceptance.

## Execution and identity

The Windows Python 3.11 PyInstaller onedir contains `metroliza.exe`, a minimal launcher with its
own bundled standard-library runtime, and `metroliza_application.exe`, the real application.
The launcher's onefile bootloader extracts its own runtime before its Python supervisor starts.
This extra bootloader process is part of the observed topology and startup cost. Qt, OCR and
application bootstrap are excluded from that launcher. It validates fixed child/runtime component
hashes and equality with the embedded build SHA before launching the exact adjacent child.
The manifest is build provenance and consistency evidence, not a cryptographic signature.
Frozen entrypoints preserve the bundled loader's import paths. Adding the repository source
directory is confined to direct source execution.

The Windows onedir replaces PyInstaller's eager setuptools runtime hook with the same
distutils-shim policy using bundled distribution metadata. The original 6.22.3 hook imports
the compiler integrations to obtain a version; setuptools 65.5.0's import queries
`platform.system()`, whose Python 3.11 Windows implementation invokes a `cmd /c ver`
probe. The replacement preserves the version-dependent default, environment override and
optional-failure behavior without that import. The build checks module/metadata identity
and rejects a missing, duplicate or surviving upstream hook. Native positive and negative
controls compare the original hook and the replacement; packaged process acceptance stays
strict and does not admit shell helpers on their names alone.

The supervisor retains the `Popen` identity of its launched child. Two anonymous inherited pipes
carry a fresh session ID and challenge/response token; Windows uses an explicit handle inheritance
list. There is no listener, service, executable search through PATH or automatic restart.
Windows spawning temporarily clears the launcher's DLL search directory and restores it in a
serialized `finally` path, so the adjacent application bootloader initializes its own runtime.
Only approved canonical event bytes enter the queue and recorder. Raw stdout and stderr go to
the OS null sink, including no-console execution. No global Qt exception hook is installed.

## Limits and failure states

| Resource | Hard maximum/default |
| --- | --- |
| Encoded event | 4096 bytes |
| Framed payload | 4608 bytes, decoder allocated only within the cap |
| Child queue | 256 events / 256 KiB, including 16 events / 16 KiB terminal reserve |
| Ring | 2000 events / 2 MiB encoded accounting / 300 seconds, first limit wins |
| Ring terminal/control reserve | 32 events / 64 KiB inside ring totals; loss accounting also inside totals |
| Operation state | 128 tracked operations; bounded sequence and saturating loss counters |
| Store worker | One daemon; two lifecycle controls, one pending live snapshot and one reserved final snapshot |
| Local reports | 20 reports / 32 MiB including staging / 14 days; report envelope at most 3 MiB |
| Directory scan / markers | 256 entries / 32 markers |
| Store lock / shutdown | 0.25-second lock attempt; caller waits at most 0.75 seconds on worker close |

Encoded caps are not actual RSS. Snapshots share immutable event bytes, but retaining a writing
and pending snapshot can keep up to two additional ring-sized histories alive. Final admission
supersedes pending live history, preserving this bound. RSS, startup,
idle writes, flood/drop behavior and publication intervals are measured separately by the Windows driver.

Queue admission never waits for disk, UI or pipe writes. A full queue records bounded drops.
Contention that cannot be counted exactly leaves terminal loss evidence unknown instead of
claiming an exact zero. Partial, wrong-session, malformed, flooded and broken channels cannot
produce a complete-history claim. A receiver may outlive its bounded drain as a daemon when an
inherited handle is retained; its stop flag prevents later frames from changing the returned snapshot.

One bounded worker owns all marker, incident and resolution filesystem calls. The application
process is created before marker admission; handshake callbacks only enqueue lifecycle controls.
An actual failed workflow admits live publication while the app continues. Transient
store-lock failures are retried only on the worker. Publication backlog is not relabeled as
channel/event loss. Retained failed workflow history has a reserved final publication path.
A final incident that completed publication and readback is `saved` even when marker resolution
is still outstanding; that status does not claim the marker was resolved. Without verified durable
publication, a filesystem call still outstanding after the close budget returns
`publish_incomplete`. The normal process outcome remains independent of storage.

Healthy sessions write minimal markers rather than event files. Incidents distinguish observed
process return, POSIX signal where actually observed, missing handshake, caught workflow failure
and incomplete history. Numeric exit 139 alone never means SIGSEGV; no status establishes OOM,
rollback or native root cause. Domain validation remains `not_performed` unless an actual approved
validator supplied a result. V1 native stacks are unavailable.

V1 timing values reserve `86400000` milliseconds as a lower bound; source queue losses reserve
`4294967295` as a lower bound. The viewer displays these ceilings as "At least", including a
measurement exactly at the ceiling. Lower values remain exact bounded observations. This is also
the interpretation of `elapsed_ms`, workflow `duration_ms` and `source_dropped` in exported V1
`incident.json`; the schema does not imply exactness at the ceiling. Ring loss has its separate
`counters_saturated` flag. Unquantified source loss remains explicitly unknown.

The store uses private application state, bounded nonrecursive retention, exclusive staging,
validated atomic publication and identity checks. Missing user-state configuration is unavailable;
it never selects CWD as a fallback. PID/start identity checks keep stale/unclean markers conservative.
An absent clean marker is not proof of an application crash. Quota/publication failures preserve
previous complete reports; no automatic repair, re-import, replay or process-kill policy exists.
Validated inactive clean markers expire after 14 days; active or unknown identities are retained.
Windows publication uses an atomic no-replace rename. POSIX store recovery removes only an exact
generated staging alias paired with its unchanged complete final inode under the store lock.
An uncatchable POSIX export interruption can leave such a same-content hidden alias beside the
chosen export outside managed retention; no scan or deletion of user directories is attempted.

## Logging migration, preview and rollback

The qualified supervised entry suppresses the ordinary duplicate home/CWD managed files. Approved
incident events retain their INFO contract independently of retired file/global log thresholds.
Explicit safe console logging remains controlled by its own threshold. A failed supervised channel
does not silently recreate persistent file sinks; its unavailable state remains visible.

The UI hook is `metroliza.ui.incident_dialog.open_incident_viewer(parent)`. The shell owner installs
the Help/Tools action during composition. The dialog revalidates listed/selected content and exports
one selected incident with its bounded manifest and summary. It does not zip a directory or upload
anything. See the [operator guide](../user_manual/diagnostic_incidents.md).

Explicit rollback/direct launch uses `metroliza_application.exe` in the same complete onedir,
without an inherited diagnostic channel. Source and other packager entrypoints retain their direct
safe-log route. This has no crash-surviving recorder and is a documented mode change, not a data
migration. Raw opt-in startup profiling remains separate and is not a share-safe incident export.

## Qualification boundaries

Source tests use actual startup, selected import into scratch SQLite, local workbook export,
controlled child exit, surviving storage and a subsequent Qt preview/export. The package test seam
requires both existing startup-smoke mode and a closed explicit qualification scenario. It accepts
only a hash-pinned public PDF and an explicit scratch directory; it cannot select a business database.
The controlled hard exit belongs only to that synthetic test scenario.

The bounded owner-only Windows lane builds with normal `build_windows_exe.ps1 -Mode onedir` tooling,
checks artifact/provenance/notices, launches restricted ordinary-user processes without development
Python on their PATH, and exercises the complete package from a path with spaces/non-ASCII text.
The driver records the complete bounded package tree and binds its canonical manifest and exact
development ZIP by SHA-256. CI uploads that validated ZIP. Startup readiness is measured before
workflows, with matched direct/supervised startup and process-tree RSS samples and idle write
controls. Flood loss, incident latency, process roles, concurrent sessions and actual main-window
startup are separate checks. Exact Windows/build/tool versions accompany the measurements;
operational cost is explicitly `within_budget` or `unresolved` against recorded thresholds.
Its receipts are necessary package evidence. Source mocks or native source pytest alone do not
establish that result. Current full CI, Qt19, independent exact-head audit, configured review and
the Ready-triggered review remain separate gates. Final operational composition and release/real-data
acceptance belong to their respective delivery tracks; this feature does not authorize self-merge.

### Same-run Windows version-query evidence

EXE20 and EXE21 observed the exact contained app/cmd/conhost chain, all exited;
no leak was demonstrated. Replacing the eager setuptools hook had a positive
native counterfactual but did not remove the chain in the frozen package.
Dependency ownership in that package remains unproved until its own earliest
audit hook records a fixed callsite category. The qualifier therefore pairs
command-purpose proof with owned native file and ancestry proof in every run.

Permitted physical creation sequences are app alone or app/version-command/
version-console; supervised runs prepend the same two launcher processes. The
helper suffix requires exactly one `platform_ver` event, exact system cmd.exe
with the fixed ver command and both `_syscmd_ver`/`win32_ver` frames, a verified
parent chain and no observations missing. Zero events require zero helpers.
The outer dependency category `other` does not authorize an unknown command,
image or parent and does not establish a dependency-removal cause. Helpers
remain visible in assigned/max-active counts and must exit with their Job.

The explicit app hook precedes all implied runtime hooks; Analysis verifies
its exact source and order. The hook is inert outside synthetic qualification.
It closes an exclusive bounded receipt before each attempted Popen, avoiding
any atexit dependency for the deliberate hard-exit test. Failed writes,
installation, overflow and reentrancy exit the synthetic app with97; no
optional dependency catch can turn missing evidence into success. After Job
drain the host validates nonce, schema, regular single-link files, all records
and observation agreement, emits only fixed enums and removes the private
journal. The host binds its created directory identity and removes only the
capped regular single-link journal files followed by rmdir; replaced roots,
reparse points, nested content and unknown entries are rejected. Incidents and exported ZIPs never include these private journals.
Concurrent starts retain separate per-process owners and journals.

Native controls cover no call, the real version call, other commands, durable
prelaunch evidence after hard exit, failed exclusive write, two launcher-like
parents and two simultaneous Jobs. Their source proof cannot establish that
a packaged candidate passed; the exact packaged head still needs qualification.
