# Supervised diagnostics: research and proposed contract

Status: **PROPOSED — product acceptance required; no runtime implementation**

Owner: ORCH-METROLIZA / capability [#944](https://github.com/hexafe/metroliza/issues/944)

Research packet: [#1037](https://github.com/hexafe/metroliza/issues/1037)

Last reviewed: 2026-09-10

Audited source: `develop@b645164e83898df69335713f808189de6cc1fc31`

Audited tree: `46fd6819d23fbabe19fda7b90ba9ac24e5bd6110`

Canonical execution/review receipt: [Issue checkpoint](https://github.com/hexafe/metroliza/issues/1037#issuecomment-5621144480)

## Decision for the Product Owner

**Rekomendacja:** rozszerzyć istniejące bezpieczne zdarzenia #1011 i dodać mały, lokalny
nadzorca procesu z ograniczoną historią w RAM oraz atomowym zapisem incydentu. Preferowany
wariant pakowania to osobny launcher bez Qt/OCR, dostarczany razem z aplikacją. Pierwsza
wersja ma zachować historię operacji i rzeczywisty status zakończenia procesu także po jego
awarii. Nie będzie obiecywać natywnego stosu ani wyniku zapisu bazy po awarii.

Raport domyślny zawiera wyłącznie zatwierdzone kody, identyfikację kompilacji, losowe ID
operacji, etapy i bezpieczne lokalizacje kodu. Nie zawiera pomiarów, nazw dokumentów,
ścieżek użytkownika, SQL, komunikatów wyjątków ani sekretów. Stosy faulthandler wymagają
osobnego, sprawdzonego kanału; minidumpy pozostają oddzielną, wrażliwą funkcją wsparcia.

Do akceptacji są: osobny launcher i jego koszt dystrybucji, proponowane limity/retencja,
minimalne znaczniki na dysku oraz opisane granice V1. Implementację należy uruchomić dopiero
osobnym packetem. Ten dokument nie naprawia #998, nie odblokowuje #995 i nie zmienia
zatrzymanego audytu #981 ani jego Draft PR #1036.

## 1. Recommendation and corrections to the starting hypothesis

Adopt **existing closed events → bounded local transport → independent supervisor ring →
local incident**, using stdlib first. Keep capture, classification, persistence and export
as separate contracts. Make V1 useful through safe workflow stages and Python source locations;
ship native-termination detection in V1, while explicitly reporting `native_stack: unavailable`.
A later native collector must be armed before termination. Waiting for a dead process cannot
recover its address space.

Six adjustments to the initial orchestrator proposal follow from the source and research:

1. A role inside the full frozen application is not sufficiently independent for the strongest
   startup claim. Its bootloader, Python initialization and automatically selected runtime hooks
   precede application entry. Prefer a **separately frozen, stdlib-only, onedir/standalone launcher**
   with its own minimal collection and build identity. It supervises the existing application
   bundle, including its bootloader. This costs another runtime/artifact and needs qualification;
   it is not asserted to be small in measured RSS or download bytes.
2. Reuse the safe construction and publication principles in `scripts/ocr_diagnostic_contract.py`,
   but **do not copy its process-lifetime policy**. Its finite checks kill/reap children on timeout,
   output limit or parent loss. A GUI owning an SQLite write must not acquire that behavior.
3. `faulthandler` is not share-safe structured logging. Even Python-only traces contain filenames
   and function metadata. Keep its raw text out of default disk output. Qualify a separate bounded
   RAM-only normalization channel before enabling it; safe exception frames do not require it.
4. Do not flush on every ordinary warning/error log. Legacy suppression produces little meaning,
   and repeated handled errors can create a disk storm. Trigger on typed operation failure,
   abnormal exit, manual report, or qualified suspected-hang state, with deduplication and quotas.
5. Useful diagnostics require **explicit workflow adapters**, not merely more global hooks. Worker
   errors already become signals/results and may never reach `sys.excepthook`. Do not import all
   optional native/OCR components solely to populate a diagnostic inventory.
6. In PyQt6 6.6.1, installing `sys.excepthook` changes the binding's callback-error path. Leave the
   global hook unchanged in the V1 Qt application; section 5.2 explains the verified source behavior.

The rollout includes an explicit logging-policy migration (S2d): until accepted and implemented,
the new recorder coexists with the current managed home/CWD logs. S2a alone does not make the
whole application incident-only.

These are proposed decisions, not accepted ADRs or findings that the current logging foundation
is unsafe. All current behavior below is source-inspected unless an existing receipt is named.

## 2. Evidence and actual boundary inventory

Evidence labels: **IMPLEMENTED / SOURCE-ONLY** means code and relevant tests were read, not run
here; **TESTED (historical)** is limited to the linked existing receipt; **GAP** is absent coverage;
**OUT-OF-SCOPE** is deliberately excluded. Local research execution before this document freeze
included no runtime probe, native crash, Qt session, benchmark, package build, installation,
dependency resolution or dump collection. No hosted job was manually dispatched. Local executable
validation was limited to named documentation/scope/hygiene checks. Ordinary push/Draft-PR CI is
tracked separately by exact run/result in the canonical receipt; it does not qualify the proposed
supervisor, Qt hooks, native capture or packaged behavior.

### 2.1 Launch and sink map

In this table, `M` means the managed formatter boundary described in the first row. User-facing
workflow data and diagnostic data are different contracts: the recorder must not subscribe to
arbitrary UI labels/results. “No network sink” concerns the inspected diagnostic path, not every
optional product integration or host collector.

| Origin and exact boundary | Transport → validation | RAM/disk/network; retention | Operator outcome and evidence status |
| --- | --- | --- | --- |
| `logging_utils.ensure_application_logging`, `ManagedSafeFormatter`, `_safe_event` [R1] | LogRecord → closed `serialize_diagnostic_event`; legacy text/args/exception text suppressed; unmanaged handlers preserved | Two rotating files: home `.metroliza/metroliza.log` **and CWD** when writable; temp `metroliza/metroliza.log` only if both fail; 10 MiB + 7 backups per distinct target. Optional managed console. No network handler here | IMPLEMENTED / SOURCE-ONLY. Safe type/structure, not workflow history. `handleError` is non-rendering; total sink failure installs NullHandler, with no persistent success receipt |
| `diagnostic_events.ExceptionDiagnosticEvent`, `build_exception_diagnostic_event` [R2] | Exact approved types/identity-to-literal serialization; bounded exception graph | Primitive JSON at M; UUID correlation is generated for each exception event | IMPLEMENTED / SOURCE-ONLY. 32 exception nodes, depth 8, 64 counted traceback frames; no frame coordinates, operation lifecycle or shared session |
| `custom_logger.log_exception`, `handle_exception`, `notify_user` [R3] | Exception → closed generic `UNHANDLED_EXCEPTION`; caller `context` does not become operation identity; optional QMessageBox | M plus GUI dialog; no incident store | IMPLEMENTED / SOURCE-ONLY. UI and logging coupled in some callers; bootstrap error path may itself need Qt. Do not invoke GUI from new low-level hooks |
| Root `metroliza.py`; canonical `metroliza.app.bootstrap.run_application` [R4] | Root imports bootstrap before entry; `run_application` catches `Exception` around `bootstrap_application` | Same application process; M initialized inside bootstrap; returns 1 on caught startup failure | IMPLEMENTED / SOURCE-ONLY. Source GUI and `python -m metroliza.app.bootstrap` have no external supervisor. There is no `src/metroliza/__main__.py`; do not document `python -m metroliza` as canonical GUI entry |
| `bootstrap.log_runtime_provenance`; `build_provenance.load_build_provenance` [R4, R5] | Legacy interpolated provenance → M suppression; manifest has validation but several strings are not a diagnostic allowlist | Embedded manifest/read-only runtime object; log shows suppressed legacy record | SOURCE-ONLY usefulness gap. Exact source manifest can fall back to unknown SHA; never infer runtime source identity from research checkout |
| `startup_profile.record_event`, `get_profile_path` [R6] | Opt-in env → arbitrary `extra` merged into JSONL; no M validation | Explicit path or home `.metroliza/startup_profile_<pid>_<time>.jsonl`; executable, extraction path, PID; no rotation/age cap in writer; OSError silently ignored | IMPLEMENTED / SOURCE-ONLY separate support sink, not share-safe. `test_startup_profile_writes_jsonl_events` deliberately checks an extra `detail` field |
| `packaging/metroliza_package_entry.py`, both PyInstaller specs, `build_nuitka.ps1` [R7] | Package entry directly imports bootstrap; specs use it and `runtime_hooks=[]`; standard hook machinery still applies | PyInstaller onedir/onefile `console=False`, windowed traceback not disabled; Nuitka standalone/onefile, console normally disabled; onefile extraction owned by packager | IMPLEMENTED / SOURCE-ONLY. Import/loader failures can precede M; bootloader dialogs/native stderr/debug output are outside M. No native collector in specs |
| `ParseReportsThread.run/log_and_exit`, stage-1 `ThreadPoolExecutor` and `future.result()` [R8] | Caught per-file/main worker exceptions → legacy logging, custom safe exception event and `error_occurred` string; futures consumed explicitly on main path | M plus in-process result/UI signals with paths/text; no independent incident | IMPLEMENTED / SOURCE-ONLY. Existing catches are adapter seams. Cancelled/unconsumed futures need explicit lifecycle accounting, not assumptions about a global hook |
| `MetadataEnrichmentThread.run`, `ParsePreflightThread.run` [R9] | Caught exceptions → logging and/or `failed/error_occurred` string; progress contains filenames/report IDs | M where called, otherwise UI RAM; finished signals also occur in cleanup | IMPLEMENTED / SOURCE-ONLY. A finished signal alone does not prove operation success; recorder takes typed outcome, not arbitrary emitted strings |
| Industrial/realtime/tabular worker `run` methods [R10] | QThread catches → `redact_sensitive_text` and result/error/cancel signals | UI RAM and existing workflow stores; no shared incident transport | IMPLEMENTED / SOURCE-ONLY. Text redaction is not the #1011 closed schema; never promote these strings into incidents |
| `ExportDataThread.run/log_and_exit`, `_ensure_chart_executor`, `_ensure_summary_prep_executor` [R11] | QThread catches, typed completion, legacy stage logger; optional ProcessPoolExecutor; bounded thread-pool preparation; future results consumed on relevant path | M; completion metadata/UI/export artifacts may contain output paths, labels and exception messages | IMPLEMENTED / SOURCE-ONLY. Distinguish fallback, cancelled, failed and completed-after-cleanup. Process-pool failure is a worker outcome, not automatically application death |
| `exporting.backend_diagnostics.build_backend_diagnostic_summary`, `_build_backend_entry`; app alias [R12] | Imports/resolves several native bridges; free-form `error=str(exc)` and formatted lines | Returned RAM/UI/export metadata; not automatically M-safe; no own persistent diagnostic sink | IMPLEMENTED / SOURCE-ONLY. Reuse approved component/backend facts through a new projection, not raw dicts or an eager supervisor import |
| Native bridges and third-party OCR/Qt/runtime messages [R12, R13] | Python fallback/error helpers may reach M; native OS fd/debug/journal output bypasses it | External/unmanaged streams and OS facilities, with environment-specific retention | GAP in common capture. No installed `qInstallMessageHandler`, fatal handler, global Python/thread/unraisable hook or asyncio adapter found in canonical startup. No claim that managed logging covers native text |
| `windows_ocr_runtime_diagnostics.main`, `diagnose_header_ocr_metadata.main`, `ocr_diagnostic_contract.run_child/worker_main/publish` [R14] | Request JSON → child; protocol separated from bounded native noise; exact rows validated; parent publication guarded against input/sidecar aliases | Bounded RAM, 64 KiB output bound; final safe JSON to explicit output or stdout; atomic staging/fsync/replace; no report-store retention policy | IMPLEMENTED; TESTED (historical #1033 receipt). Required failure/nonzero and publication failure code 2; raw noise never published. OCR/DB inputs remain private and DB read-only |
| `diagnose_windows_ocr.ps1`, `setup_windows_runtime.ps1` [R14] | Script dispatch and native exit propagation; invoking context and setup messages are separate from JSON | Console and explicitly selected output; no common retention | SOURCE-ONLY here. Repository-relative wrapper semantics differ from caller-relative Python CLI. Setup is an installer, not an automatic incident action |
| Other developer CLIs: `explain_parser_resolution.main/_format_candidate`, `parser_plugin_self_service._cmd_evidence`, startup summary/measurement tools [R15] | Own argparse/output contracts; source/plugin paths, registry-load errors, candidate reasons and profile evidence printed directly, outside M | Explicit stdout/files, including parser/source/build data; caller controls retention | IMPLEMENTED / SOURCE-ONLY; OUT-OF-SCOPE for automatic attachment. Reviewed projection required before each becomes a #944 bundle input |
| Shared preview/export and fatal/native store | No common implementation located in the inspected app/packaging surfaces; #944 still owns planned bundle capability | No default shared incident/fatal store | GAP. Existing application/export/diagnostic outputs are not implicitly support bundles |

`tests/test_logging_utils.py` covers both destinations, rotation, fallback, adversarial suppression,
forged events, non-rendering sink failure and preservation of unmanaged handlers. `test_diagnostic_events.py`
checks exact-type/enum/UUID defenses and graph bounds. `test_bootstrap_startup.py` patches the bootstrap
failure seam; it does **not** demonstrate an import/native crash surviving in another process.
`test_packaging_spec_hiddenimports.py` reads build files; textual assertions are not a packaged launch
or handle-inheritance proof. The OCR tests include real subprocess/Windows-specific contracts, but
cannot qualify long-running GUI supervision or reuse kill-on-parent-loss as a safe GUI policy.

### 2.2 Existing evidence and ownership

[#1011 integration](https://github.com/hexafe/metroliza/issues/944#issuecomment-5528304544) establishes
the accepted safe foundation and the explicit executable-custom-LogRecord threat-model exclusion.
[#1033](https://github.com/hexafe/metroliza/pull/1033) supplies historical safe OCR/process/publication
work, now present in the audited develop tree. Neither is new execution in this research.

The later [owner continuation](https://github.com/hexafe/metroliza/issues/1037#issuecomment-5621182327)
was read during this same window; its semantic-success counterexample is included in section 7.
Local execution works in this new isolated research checkout. That does not repair or synchronize
the old audit checkout, whose local/remote discrepancy remains recorded in its own checkpoint.

The [#981 STOP checkpoint](https://github.com/hexafe/metroliza/issues/981#issuecomment-5620071004)
preserves Draft #1036 at `b451e7af3153da89c16d09f5b26a7f4799a82da3`. It records clean final review,
one successful CI run and another run failing in an unchanged Qt shard; no all-CI-green claim.
Its files and branches were not reused.

[#998 canonical evidence](https://github.com/hexafe/metroliza/issues/998#issuecomment-5592456371)
and Draft [#1034](https://github.com/hexafe/metroliza/pull/1034), observed at
`f7cffb88deae51a508dcce7a0ed040a2f61365c9`, are diagnostic experiments owned by LEWY. The packet's
older `df0f9b8` snapshot has moved. Existing bounded source-coordinate validation is a useful design
precedent, not proof of production reliability or root cause. No new Qt/native reproduction or
experimental allocation is activated here.

## 3. Alternative analysis with primary sources

Documentation was consulted on 2026-09-10. Python semantics below use **3.11**; both PyQt6 and
Qt are pinned to **6.6.1** in `requirements.txt`. Build requirements specify **PyInstaller >=6.11**
and **Nuitka >=1.9**, not an exact qualified version. Current web manuals therefore identify questions
for the chosen build, not permission to upgrade or assume the latest behavior is deployed.

| Option | What it adds / limits | Confidentiality, effort and decision |
| --- | --- | --- |
| Existing stdlib + reviewed safe events + separate supervisor | Operation history, independent exit observation and controlled incident publication; does not restore native memory | Recommended V1. Own small protocol/store adapters and package topology; reuse #1011 serializers, not a competing logger |
| `MemoryHandler` | Buffers LogRecords in its own process, flushing at capacity/severity/close; it is not an age/byte-bounded surviving ring | Reject as recorder. Child RAM dies with child; raw objects may retain sensitive data. [Python 3.11 handlers](https://docs.python.org/3.11/library/logging.handlers.html) |
| `QueueHandler` / `QueueListener` | Moves handler work to a listener; listener thread still shares process fate. Stock preparation formats/merges messages; bounded enqueue may drop | Possible internal implementation ingredient only after safe projection. Use finite queues of serialized primitives; never stock prepare on arbitrary records, default pickle receivers, or exposed listeners. [Python logging cookbook](https://docs.python.org/3.11/howto/logging-cookbook.html) |
| Python 3.11 `faulthandler` | C implementation emits bounded Python frame text for selected fatal signals and Windows exceptions; descriptor lifetime matters; no Python 3.14 C-stack feature | Candidate optional channel, not default raw file. It emits filenames/functions and may be incomplete. `register` is unavailable on Windows; `dump_traceback_later(exit=True)` violates the no-kill rule. [3.11 API](https://docs.python.org/3.11/library/faulthandler.html) |
| Crashpad directly | Client registration plus separate handler, local crash database/minidumps, platform-specific live-process access | Preferred candidate if sensitive native capture is later approved. Requires native bridge, handler distribution, symbol pipeline, licensing/build maintenance and offline policy. Memory in a minidump may contain secrets; it is not an allowlisted incident. [Crashpad design](https://chromium.googlesource.com/crashpad/crashpad/+/main/doc/overview_design.md) |
| Sentry Native with Crashpad backend | Native SDK supplies backend integration plus Sentry event/transport machinery; not achieved by installing a Python logger | More integration convenience but extra collection/transport surface. Local-only must disable upload in both SDK and handler paths and prove offline persistence/deletion. No DSN alone is not the acceptance test. Current upstream calls standalone SDK use experimental; qualify an exact tag. Dedicated handler/database and compiler/privacy constraints below reinforce rejection for V1. [Native SDK](https://github.com/getsentry/sentry-native) |
| Windows WER LocalDumps | OS collection configured before termination; per-executable registry options and local retention | Support-only alternative. Administrator required to enable documented HKLM configuration; custom crash reporting and automatic-debugger interaction limit coexistence. No registry changes here. [Microsoft LocalDumps](https://learn.microsoft.com/en-us/windows/win32/wer/collecting-user-mode-dumps) |
| `MiniDumpWriteDump` / explicit OS support collector | Live target handle/rights and exception context permit a helper to write a dump; Microsoft recommends another process and serializing DbgHelp calls | Native engineering, not a post-exit `Popen.wait()` callback. Same-user operation can be possible but access rights, protected targets and exact configuration decide. Manual support collector/ProcDump is separately approved, never silently installed or attached. [Microsoft API](https://learn.microsoft.com/en-us/windows/win32/api/minidumpapiset/nf-minidumpapiset-minidumpwritedump) |
| Linux post-mortem | Existing kernel/systemd collector can preserve separate evidence; debugger/symbol tools can inspect an already retained core | Optional support input only. Availability/access/retention depend on host policy; do not change `core_pattern`, core limits, service settings or install tools. Existing journal/core text is sensitive. [systemd design](https://systemd.io/COREDUMP/) |
| structlog / Loguru | Event ergonomics, processors, contextual binding and sinks | No process-survival guarantee and no confidentiality guarantee merely from JSON. Loguru `diagnose` may include variable values. Adds migration/dependency work without closing the central gap; reject for V1. [structlog](https://www.structlog.org/en/stable/getting-started.html), [Loguru API](https://loguru.readthedocs.io/en/stable/api/logger.html) |

Sentry Native adds concrete integration constraints: distribute `crashpad_handler`, set explicit
handler and private database paths (`sentry_options_set_handler_path` / `sentry_options_set_database_path`),
and never share that database directory with incident/measurement files because SDK maintenance may
delete entries. Its Windows MinGW configuration requires x64 LLVM/Clang for PDBs, whereas this repo's
`build_nuitka.ps1` prefers MinGW/GCC (lines 64–75, 205–212, 659–664). Windows fast-fail can bypass
`before_send`/`on_crash`; callback scrubbing is not a collection privacy boundary.
[SDK constraints](https://github.com/getsentry/sentry-native)

For a future local-only Sentry spike, inventory the exact tag's transport, consent/cache and native
handler upload settings separately; `sentry_options_set_transport` governs SDK event transport, not
proof about every native report path. Test denied-network operation plus later launches, queues,
consent transitions and deletion: no delayed upload is allowed by this proposal.
[SDK option declarations](https://github.com/getsentry/sentry-native/blob/master/include/sentry.h)
These requirements may force a compiler/symbol/artifact change, which remains separately gated.
Direct Crashpad still requires its own symbol/toolchain proof; choosing it does not remove that burden.

A native SDK must be registered **inside the actual application/native process**, not only in the
supervisor or onefile bootloader. Retain matching app/launcher/handler binaries, PDB/debug information,
Python/Qt/native extension identities and build maps. Missing symbols yields an explicit missing-map
state; a library name or top faulthandler frame does not establish the initiating defect. Crashpad
registration does not automatically cover every worker or pre-registration bootstrap failure.

## 4. Privacy and useful event contract

### 4.1 Threat model

Protect measurement content, report/customer identifiers, paths, credentials and user-controlled
metadata from accidental persistence/export. Treat exceptions, LogRecords, plugin metadata, stdout,
stderr, Qt text, JSON IPC and local report files as untrusted input. Defend against malformed frames,
unknown fields, huge/nested values, duplicate JSON keys, bad types, invalid Unicode, symlink/reparse
aliases, storage races and diagnostic floods.

Trust reviewed application/launcher code and its verified build metadata. An attacker executing
arbitrary code as the same user, a hostile kernel/admin, or malicious executable descriptors inside
LogRecord subclasses is not contained by this design. The IPC schema is not a sandbox for malicious
plugins, and a permitted enum/count can be abused as a covert channel by executable code. State this
limit instead of claiming protection against arbitrary code execution. Normal filesystem permissions
do not encrypt data against the account owner; no new host encryption/swap policy is proposed.

Default records forbid messages/locals, raw traceback objects, code text, raw source filenames,
function metadata, SQL, complete argv/env, filesystem/URL paths, host/user/hardware identity,
report IDs/hashes, measurements, row counts and per-measurement timing. A low-entropy identifier
hash is still an identifier. User-entered notes, screenshots and file attachments are not default
fields; no generic `details`, `extra`, arbitrary tags or arbitrary version string is accepted.

### 4.2 Extend the existing schema, do not replace it

Use new reviewed classes/enums in the canonical shared diagnostic module, preserving legacy safe
suppression and old event validity. An IPC envelope is a transport projection of these types, not a
second independently evolving error taxonomy. OCR retains its existing public CLI format; a #944
adapter maps reviewed reason/backend enums and excludes document-derived counts. Do not make the
GUI depend on `scripts.*` or import an OCR runtime in the supervisor.

| Field group | Proposed validation and diagnostic value |
| --- | --- |
| Session / incident / operation | Independently generated UUIDs; operation ID spans start, stage and one terminal outcome; incident ID assigned by supervisor; no input-derived IDs. Process role is enum; worker ID is session-local ordinal, never arbitrary thread name |
| Build | Release/build/source-map ID from trusted build catalog; source SHA allowed only when validated as code identity; unknown/dirty source explicitly qualified. Runtime manifest reused through a closed projection, not copied wholesale |
| Runtime/backend | Fixed component IDs; numeric versions validated and matched to supported manifest where available; OS family/version class, architecture enum; requested/effective backend and availability enums. Inventory records what was already observed, with `not_initialized` for unused optional components |
| Event | Versioned event code and operation/stage/outcome enums; bounded sequence and relative monotonic time; approved exception kind; code-location IDs. No arbitrary logger/context/category/function text |
| Outcome | `completed`, `failed`, `cancelled`, `fallback`, `unknown`; independent persistence state `not_applicable`, `confirmed_committed`, `confirmed_rolled_back`, `unknown`. Confirmation requires the existing owning workflow's authoritative result; event absence is never rollback evidence |
| Location | Source-controlled callsite/frame ID plus trusted map ID; at most 32 safe frames/event. Unknown external/plugin/dynamic/compiled frame becomes a fixed `unmapped` category and bounded count |
| Loss/status | Saturating counters for queue/ring/invalid/deduplicated loss; explicit saturation and incompleteness flags; earliest/latest retained relative time; IPC/fatal/store availability; no undocumented silent success |

Validate before IPC **and** reconstruct at supervisor ingestion and final publication. Exact built-in
primitive types only; bool is not an int; finite bounded integers; no floats/NaN/Infinity. A frame is
at most 4 KiB encoded UTF-8, with depth <=4 and bounded collections. Reject unknown schema versions,
extra/duplicate keys and oversized frames before expensive parsing. Reject rather than stringify
unexpected objects; serialization/hook failures emit at most one fixed diagnostic-status code.

### 4.3 Safe code locations

Prefer explicit callsite IDs for workflow transitions. For exception stacks, walk a bounded number
of frames without `traceback.format_exception`, source-line lookup or object repr. Map exact trusted
code objects to a build-generated ID registry populated only from reviewed modules. A matching
filename/function string is insufficient: `compile(..., filename=...)` can forge it. Do not accept
arbitrary metadata on functions as a trust anchor. Unknown source/dirty code keeps the safe callsite
and marks frame mapping unavailable, rather than guessing a release line.

The release job must bind the map to the exact artifact and retain it for offline maintainers.
Packaged .pyc and Nuitka compiled functions require their own verified mapping. Compiled Python
frames are not guaranteed to reconstruct source coordinates; explicit callsites remain useful.
A future native symbolizer projects only trusted module/build IDs and reviewed frame IDs. Raw
addresses, paths or unsupported third-party symbols remain in the separately sensitive workflow.
Textual faulthandler normalization can identify a known coordinate but cannot prove that coordinate
caused the crash; label it `reported_frame`, with incomplete/mapping confidence.

### 4.4 Synthetic examples and an actionable timeline

The following are **proposed** JSON projections, not payloads accepted by today's serializer.
Build/map IDs and UUIDs are synthetic; no production source/document identity is encoded.

```json
{
  "schema": 1,
  "session_id": "11111111111141118111111111111111",
  "operation_id": "22222222222242228222222222222222",
  "role": "application",
  "seq": 42,
  "elapsed_ms": 12500,
  "code": "operation_stage",
  "operation": "report_import",
  "stage": "persist_begin",
  "location_id": "import.persist.begin.v1",
  "map_id": "synthetic-map-1"
}
```

```json
{
  "schema": 1,
  "incident_id": "33333333333343338333333333333333",
  "session_id": "11111111111141118111111111111111",
  "build_id": "synthetic-build-1",
  "trigger": "abnormal_exit",
  "observation": {"role": "application", "kind": "posix_signal", "value": 11},
  "cause": "unknown",
  "operation_state": "unknown",
  "persistence_state": "unknown",
  "history": {"events_retained": 42, "events_dropped": 3, "incomplete": true},
  "python_stack": "unavailable",
  "native_stack": "unavailable",
  "store_state": "published",
  "attachments": []
}
```

A full incident contains the validated event array, bounded runtime/build facts and loss summary;
this second example shows its summary projection. `store_state: published` describes a successfully
read-back report, not an advance promise written before publication. The authoritative success
receipt belongs to the publisher; the on-disk content can omit that derived field.

Example timeline: `import.start → inspect.done → parser.selected (builtin family) → persist.begin →
application exited by SIGSEGV`. The maintainer learns the exact build, reviewed code region and
last **observed** operation. They do not learn report identity or conclude that the transaction
committed. Another example: `export.start → renderer.failed → fallback.completed → cleanup.done`;
the report should explain degraded success without describing the entire export as failed.

## 5. Supervisor, transport, hooks and fatal channel

### 5.1 Lifetime and IPC contract

The launcher initializes a private store/marker and tiny schema reader, then starts the application.
It owns process handles, bounded recording and publication, not SQLite, business cancellation or
recovery. It waits for both actual application termination and owned bootloader cleanup where needed.
It never opens the measurement DB. On supervisor loss the application continues its existing lifecycle
with `diagnostics_unavailable`; there is no kill-on-close Job Object, parent-death kill signal,
automatic restart, command replay or reparented recovery loop.

Source proof may use inherited anonymous pipes, explicit `pass_fds` on POSIX and a Windows handle
allowlist. **Packaged target proposal:** private local IPC established after application entry, avoiding
an unproved assumption that custom handles survive every bootloader. Use AF_UNIX in an owner-private
runtime directory on Linux, and an owner-restricted named pipe with remote clients rejected on Windows.
No TCP port, SocketHandler or pickle. A one-use random endpoint/nonce passed only to the launched
process is removed from descendant environment after handshake; it never enters reports. Limit to
one admitted application peer, one handshake, <=8 connection attempts and a 10-second
post-entry handshake budget. A 120-second pre-entry startup observation deadline produces
`startup_delayed` and a fixed notification, never a kill or second launch; this budget is a proposal
for cold/AV-delayed packaging tests, not a guarantee that slow startup is broken.

Cross-check OS peer identity against the launched tree before accepting diagnostic events. Windows
uses pipe-client PID plus a retained process handle/creation time and verified lineage; Linux uses
peer credentials plus live identity/ancestry and start time. PID alone is insufficient. A pre-handshake
crash is classified against the launched bootloader/direct child; actual app status stays unknown.
A malicious same-user process is outside the confidentiality trust boundary, but accidental/stale
peer mixing and cross-instance joins must still fail closed. Windows ACL/identity code is a narrow
platform adapter, not an added service or administrator requirement. Platform feasibility references:
[pipe client identity](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid),
[pipe access control](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights).

Use a bounded child queue of **already serialized bytes**, with a dedicated writer and separate
control/terminal capacity. Producers make a nonblocking try-enqueue; they never wait for transport,
disk, a listener lock, or GUI work. A Python allocation/lock attempt is still best effort, not a
hard real-time claim. Reserve terminal slots; if all slots fill, retain a fixed loss counter and the
latest bounded per-operation state, never an unbounded retry. Supervisor ingestion revalidates,
assigns receive order/time and accounts for gaps. Never equate enqueue success with durable capture.

Default native stdout/stderr go to a null destination; no unbounded `communicate()` capture and no
raw attachment. No-console Python `None` streams need early safe null objects separately: `Popen`
redirection does not recreate them. Support mode may drain native noise through a **separate**
fixed-buffer discard reader; it counts bytes/loss but never saves content or parses it as safe IPC.
Keep draining after the capture quota (proposed 64 KiB transient RAM, 16 KiB read chunks), so flood cannot hold application progress behind a full pipe.
No flood-triggered process termination. Rate-limited frame decoding and publication run separately
from process observation; a stalled reader must not conceal exit.

A partial frame/EOF yields `protocol_incomplete`; malformed length/version yields fixed rejection.
A broken event pipe marks capture unavailable and releases producer resources. After process exit,
drain already available safe events for at most a proposed 250 ms, then publish incomplete state.
Do not wait forever for EOF held open by grandchildren. Worker subprocesses close application-only
handles; distinct admitted worker streams require separate bounded IDs/adapters, not implicit trust.

### 5.2 Hook semantics

| Boundary | Proposed adapter and limit |
| --- | --- |
| Handled operation failures | Emit at the catch/result seam using approved operation/stage/error IDs. Preserve existing fallback/cancel/transaction results; never infer from warning severity |
| Main Python exception | Earliest safe top-level adapter in the owned entry/`run_application`; `SystemExit` classified separately. Leave global `sys.excepthook` unchanged in the V1 Qt app. A separate non-Qt CLI may qualify it without the binding interaction below; pre-adapter imports remain launcher-observed. [Python sys](https://docs.python.org/3.11/library/sys.html) |
| Python thread | `threading.excepthook` for uncaught `Thread.run` errors; release exception/thread references immediately; does not terminate or describe the main process. [Python threading](https://docs.python.org/3.11/library/threading.html) |
| Destructor/unraisable | `sys.unraisablehook` records approved kind/location only, never `object` repr or `err_msg`; no resurrection or kept exception references |
| Future/task | Observe result/exception at the existing owner seam and terminalize exactly once; executor-captured exceptions do not become thread-hook events. Cancelled, abandoned and failed are distinct. [Future.result](https://docs.python.org/3.11/library/concurrent.futures.html) |
| asyncio | Install an event-loop exception handler only where an actual asyncio loop is introduced/owned; project bounded context keys and explicitly observe tasks. No asyncio loop was found in the audited canonical startup. [3.11 loop API](https://docs.python.org/3.11/library/asyncio-eventloop.html) |
| PyQt callback/QThread | Existing handled-error seams get safe events; unhandled callback termination remains unchanged. `threading.excepthook` does not cover QThread. New catch/termination behavior needs explicit acceptance for slots, virtual overrides and QThread.run separately |
| Qt messages | Optional `qInstallMessageHandler` adapter maps only severity/approved callsites; arbitrary message/context/category is excluded. Qt has one global handler: detect ownership, preserve/restore the previous handler and qualify coexistence before installation. Raw forwarding to that handler is outside incident validation. Handler is reentrant/concurrent; fatal processing still terminates. Never log recursively, show GUI, throw or wait in it. [Qt 6.6.1 source](https://raw.githubusercontent.com/qt/qtbase/v6.6.1/src/corelib/global/qlogging.cpp) |

**Binding-specific source finding:** PyQt6 6.6.1 `qpycore_pyqtslotproxy.cpp:205–212` calls
`pyqt6_err_print()` for a failed Python slot. In `qpycore_public_api.cpp:84–113`, a custom
`sys.excepthook` selects `PyErr_Print()` and skips the default branch calling `qFatal` at
224–227. A hook that merely emits a record and returns can therefore allow callback continuation;
calling `sys.__excepthook__` alone does not restore the binding's fatal branch. V1 must not install
that global hook in the Qt app. Use existing top-level/handled seams and supervisor exit capture;
any later global hook requires a separately accepted fail-stop policy and actual binding tests.
The `QThread.run` virtual path also requires its own test; slot evidence is not universal coverage.
This is source inspection, not an executed Qt experiment. [Official 6.6.1 source distribution](https://files.pythonhosted.org/packages/source/P/PyQt6/PyQt6-6.6.1.tar.gz),
[PyPI release/hash](https://pypi.org/project/PyQt6/6.6.1/); verified source SHA256
`9f158aa29d205142c56f0f35d07784b8df0be28378d20a97bcda8bd64ffd0379`.

No Python-level signal callback can safely repair a synchronous memory fault. Do not replace fatal
termination with normal execution or swallow unsafe native exceptions. [Python 3.11 signal rules](https://docs.python.org/3.11/library/signal.html)

### 5.3 Fatal-channel decision

V1 default delivers safe events, safe Python exception frames where mapped, and OS exit observations.
**Raw faulthandler is not automatically enabled to a persistent file.** A proposed S2a qualification
may enable a dedicated nonblocking fatal pipe before Qt/OCR imports: 16 KiB read chunks with <=64 KiB transient raw
RAM/channel, <=64 projected frames and <=8 thread groups per incident, strict coordinate projection against the trusted map, then immediate discard. The report must
state `not_armed`, `unavailable`, `truncated`, `unmapped` or `available` accurately.

After the accepted fatal-input budget, continue draining/discarding without accumulating raw text;
mark truncation and never publish the unused tail. The receiving supervisor must be ready before arming. Keep the fd/handle valid until disable/exit;
close/reuse or rotating it can send fault bytes to the wrong destination. POSIX nonblocking writes
may lose frames; Windows named/anonymous-pipe semantics, conversion to a CRT fd, broken reader and
fatal-write backpressure must be qualified on the exact interpreter/build. No normal Python logger,
allocation-heavy serializer, Qt callback or JSON writer runs inside a fatal signal handler.

Compare the emergency-file alternative explicitly: a private preopened file avoids reader dependence
but contains raw metadata and stock faulthandler does not implement a product-wide byte quota/rotation
contract. Truncating after a dump does not prevent transient disclosure or overflow. It is therefore
support-only after separate privacy/storage approval, never the default fallback when the pipe fails.
No `dump_traceback_later(..., exit=True)`. A fatal pipe cannot guarantee native stack capture or evidence
if both processes die; inability to qualify it must not delay V1's bounded exit/history protection.

## 6. Storage modes, budgets and operator behavior

All numbers here are **proposed initial acceptance targets**, not measurements or approved defaults.
Do not change existing dual file logging during this research. S2d owns the later accepted migration,
including level/console compatibility, current logging tests and rollback. These new recorder quotas
do not retroactively cap existing managed logs; account for both stores during coexistence.

| Mode/resource | Proposed policy and reason |
| --- | --- |
| Default incident-triggered recorder | The new recorder writes no healthy-operation event file. Existing managed home/CWD logs remain during coexistence; the whole-app incident-only target requires the accepted S2d migration. Supervisor RAM ring: min of 2 MiB encoded event bytes, 2,000 events and 5 minutes age; 128 events/256 KiB reserved inside those totals for terminal/status facts. Child queue <=128 KiB and <=128 frames, including terminal reserve; per-frame <=4 KiB |
| Healthy-session disk writes | One atomic <=4 KiB started marker, one replacement after authenticated app handshake, one clean-ended replacement at normal exit. Fields: random session ID, trusted build ID, coarse start time, marker state and local process identity needed to avoid PID reuse. No measurement/operation rows; no periodic disk heartbeat |
| Marker retention | Local-only process PID/start identity never exported. At most 8 active supervised sessions and 20 inactive markers, <=112 KiB; inactive age <=14 days. Stale active marker without confirmed owner liveness becomes `previous_session_unclean_unknown`, not a proven crash. Indeterminate identity is not deleted as dead |
| Incident store | <=3 MiB/report, <=20 reports, <=32 MiB aggregate including staging, age <=14 days; whichever limit binds first. Enforce before writes under a bounded local store lock. Reserve staging headroom; no existing report replacement for a new incident |
| Storm control | Same session/build/operation/error/location deduplicated; one handled/hang snapshot per 60 seconds, <=3 automatic incidents/session/hour; terminal exit always attempted using reserved slot/headroom. Additional triggers increment bounded summary counters; no repeated process restarts |
| Explicit support mode | Same safe schema, opt-in <=30 minutes, earlier of monotonic duration and persisted expiry; expires on next launch as well. Optional sequential safe-event recording <=8 MiB within the same aggregate quota. No raw stdout/profile attachment and no per-measurement flush |
| Strict RAM-only option | No markers or support log. Child-only failure can preserve history if supervisor survives and destination works; loss of both processes/power loses the history. This limitation is visible before selection |
| Sensitive native mode | Separate explicit collection consent, exact collector/config/build, private store and separate export consent. Default disabled. Proposed one dump/session, <=24 hours retention, a separately approved byte budget and failed/partial cleanup policy. Never included in default bundle or public GitHub |

At 100 admitted events/second, 2,000 events cover at most 20 seconds, not five minutes; byte limits
may shorten that. Coalesce routine progress into coarse stage transitions and rate-limit redundant
legacy-suppression counts before the ring. Keep a bounded summary of <=32 active operations within
the same memory budget; overflow is counted. Never retain per-file or per-row progress by default.
Report first/last retained times, age eviction, byte/count eviction and child-side loss separately.
No measurement of actual Python heap/RSS follows from an encoded-byte cap. All counters saturate
at 2^31−1 with a saturation flag; sequence/time values are nonnegative integers <=2^63−1. Unknown
source fields and excess active operations are rejected/coalesced within the same fixed budgets.

Use a single user-private application-state location: Windows local app data; Linux XDG state home
with the usual home-state fallback. Prefer local storage; reject or report unsuitable/unwritable
locations rather than write into CWD, a shared temp directory or the measurement DB. Create with
owner-only POSIX modes / restrictive Windows DACL; verify ownership and reject symlinks/reparse-point
redirection and hardlink aliases. Use task-owned generated names and exclusive creation, validate
before writing, fsync the staged safe bytes, atomically publish and synchronize the directory where
supported. Atomic rename visibility and durable survival of power failure are separate claims.

Serialize publication/retention across instances with a bounded lock and preallocated/reserved quota;
if locking/quota/storage fails, keep the bounded RAM report and announce `incident_not_saved`. Do not
purge a previous complete report merely to attempt a write that can fail. Clean only validated owned
staging/expired reports and never live/unknown-owner sessions. Locked files consume quota; report
retention failure and stop further writes instead of falling back endlessly. Exported user copies
are outside managed retention and the preview explains that. Secure erasure on SSD is not promised.

The operator sees a short local notification/next-launch card with build, last stage, observed exit,
stack availability, lost-history flag and storage status. No Qt is imported into the supervisor just
to display it; on Windows a minimal fixed-text notification can be separately qualified, while the
next normal GUI launch provides rich preview. If neither display nor storage is available, classify
this as unavailable rather than claiming a notification was delivered. A CLI returns a distinct
launcher/storage failure code; it preserves native status in the report instead of squeezing Windows
DWORDs into a Unix shell exit code.

Capture is automatic within the accepted mode; **export is a separate deliberate action**. Preview
lists exactly the safe JSON/summary and byte sizes, with an explicit cancel. Validate again on reading
stored incidents; do not trust old files because of their names. Export only the selected bounded
incident and manifest through an atomic writer, never recursively zip logs, profiles, SQLite, dumps
or an application directory. No telemetry account or upload code is needed. The maintainer receives
safe facts and source-map IDs, and can request a separately approved reproduction if those are
insufficient. A saved incident never implies that retrying a write is safe.

## 7. Failure coverage and acceptance matrix

**Every test below is proposed, NOT RUN in this research.** Stage identifiers are defined in section 10; S2 below means S2a unless export is named.
Execute only in a separately authorized disposable environment with synthetic data; no new Qt/crash
campaign follows from this document.

| Scenario | Required V1/next-stage evidence and operator result | Acceptance discriminator / limitation |
| --- | --- | --- |
| Normal exit | Clean marker plus actual successful process exit; no automatic incident | S2: exit 0 + terminal handshake; history discarded. Exit 0 without clean handshake is `unclean_unknown`, not proven success |
| Undetected incorrect result: [#1035](https://github.com/hexafe/metroliza/issues/1035) | The exporter returned `completed` with structurally incorrect chart labels and no process crash. Supervisor/hooks cannot infer this semantic defect from a successful operation/exit; no incident is guaranteed | S1 domain seam: a separately owned artifact/domain validator can emit closed `validation_failed` plus source-controlled rule/stage/location IDs, without imported headers or workbook content. Until such a validator exists, preserve observed `completed` and separate validation `not_performed`; do not retroactively report failure. Validator implementation, repair and further #981 probes are outside this research |
| Handled operation failure | Typed failed outcome, stage and safe code location, even while app stays alive | S1/S2: catch and continue fixture emits exactly one operation terminal event; no global hook required |
| Unhandled main error | Safe owned top-level event and nonzero exit, if adapter armed | S1/S2: pre/post-adapter exceptions separated; existing caught bootstrap path covered explicitly; no global Qt hook installed |
| Python thread error | Thread-role failure; main process may still be alive | S1: synthetic Thread.run exception; no false application-terminated flag, no retained exception/thread objects |
| Qt callback/worker error | Explicit outcome or binding-specific hook event; preserve fatal behavior | S1 later PyQt6 6.6.1 gate: slot, overridden virtual and QThread.run separately; custom-hook negative control must expose changed termination; no generic threading-hook claim |
| Unobserved future/task | Owner records failure/cancel/abandoned terminal state; loop hook only supplements | S1: exception captured in a future cannot pass merely because thread hook is silent; never-result-consumed control fails coverage |
| Import/bootstrap failure | Before handshake: launched-role failure + missing application handshake; after: safe stage | S2: source import failure, packaging/runtime-hook failure and missing native DLL; no raw traceback attachment |
| Native abort/SIGSEGV/access violation | Actual observer status + pre-crash safe history; cause unknown; native stack unavailable in V1 | S2 later isolated faults: direct POSIX negative returncode/signal versus explicit exit 139; Windows observed uint32 status versus guessed cause. S4 validates armed native context |
| Process hung but alive | Liveness yes; responsiveness unknown/suspect; one bounded snapshot/notification | S3: blocked GUI versus alive worker; never kill/restart. IPC delay alone cannot prove GUI deadlock |
| Legitimate long operation | GUI/operation signals interpreted independently | S3: long async work with healthy GUI produces no hang alert; coarse progress is not deadline proof |
| Sleep/resume/debugger pause | Reset suspicion after detected discontinuity; unknown pause remains qualified | S3: suspend/resume and debugger fixtures, grace window and user pause setting; no immediate post-resume incident storm |
| Killed / OOM-like exit | Actual signal or Windows termination status with unknown cause unless corroborated | S2: SIGKILL, shell exit 137/139 and external termination distinguishable. Group `memory.events` counter alone does not attribute OOM to this PID |
| Broken IPC / partial frame | Capture loss marker and bounded producer behavior; app continues | S2: malformed length, EOF mid-frame, peer mismatch, full queue, inherited grandchild fd; no busy loop or indefinite wait |
| Supervisor failure | Child retains existing data lifecycle; next-launch marker may show unclean/unknown | S2: supervisor termination during synthetic write; no kill-on-close, no auto-restart; simultaneous loss loses RAM |
| Log flood | Bounded memory/CPU admission, reserved terminal capacity, explicit drops | S2: invalid/event/native-noise floods separately; no raw bytes in disk/export; null stdout default and support drain do not deadlock |
| Full/read-only/locked destination | Visible `incident_not_saved`, previous complete bytes preserved | S2: controlled fault seams first; actual Windows lock/read-only/space-quota gate later; never fill the user's disk |
| Concurrent instances | Separate sessions/peers/markers; shared quota/retention obeyed | S2: cross-connect, stale PID, lock contention, malformed stored incident and 9th supervised request; no cross-session history or silent eviction |
| Shutdown during SQLite write | Existing cooperative shutdown remains owner; persistence outcome unknown absent confirmed result | S2: synthetic transaction + normal shutdown and abrupt child/supervisor loss separately; no diagnostic DB connection or replay, no assertion that a saved report proves commit/rollback |
| Power loss / both processes lost | At most last durable safe marker/report; no RAM history guarantee | S2 specification review, later controlled host/VM gate if approved. File flush alone is not a universal storage/power-loss guarantee |
| Launcher itself fails before Python | No launcher-side guarantee; OS/direct-launch fallback guidance | S2: corrupt/missing launcher runtime distinct from application failure; no recursive attempt to supervise the supervisor |

A direct POSIX `Popen.returncode < 0` identifies a terminating signal of **that direct child**.
A shell-style 139 is an ordinary exit status unless independent evidence says otherwise. Windows
status is recorded as the observed DWORD, with a known-status label only as classification, not
proof of a native fault: application code can return the same value. For a onefile bootloader, keep
bootloader status separate from actual app status. [Python subprocess](https://docs.python.org/3.11/library/subprocess.html)

OOM attribution requires separately matched OS evidence and permissions. Linux cgroup memory-event
counters describe group activity and cannot alone identify which process failed. Do not enable OS
collectors just to replace `unknown` with a more confident label. [Kernel cgroup documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)

## 8. Packaging feasibility and qualification gates

### 8.1 Proposed process trees

`L` = separately packaged minimal launcher/supervisor; `A` = actual Metroliza app; `B` = onefile
bootloader/extractor; `H` = future separately gated native handler. Runtime initialization within a
process is shown with `→`, not invented as another PID. All trees are **design models**, not observed
process traces. Packager/OS versions can add re-exec or helper details that exact-artifact tests must record.

```text
Source:                    shell/shortcut → Python L
                                               └─ Python A → bootstrap → Qt/OCR
PyInstaller onedir/Win:    shortcut → lean onedir L (own bootloader → Python)
                                               └─ app onedir A (bootloader/hooks → Python → Qt)
PyInstaller onedir/Linux:  shortcut → launcher bootloader/re-exec → L
                                               └─ app bootloader/re-exec → A → Qt
                              (v6.11.1 Linux onedir re-execs in the same PID; no fork)
PyInstaller onefile:       shortcut → lean onedir L
                                               └─ app B (extracts, owns cleanup; splash thread)
                                                   └─ app A (hooks → Python → Qt)
Nuitka standalone:         shortcut → lean standalone L
                                               └─ compiled app A → bootstrap → Qt
Nuitka onefile:            shortcut → lean standalone L
                                               └─ app B (extracts, owns cleanup)
                                                   └─ compiled app A → bootstrap → Qt
Every app where enabled:   A ── native registration ── H (platform-specific handler ownership)
Optional existing workers: A ── process-pool worker(s), with explicit worker roles; never L again
Direct fallback:            existing source/app entry → A or B → A; supervision unavailable
```

Contrast under evaluation: a **single role-dispatched app bundle** gives
`B → full-runtime supervisor role → same-executable app role` in onefile, or
`full-runtime supervisor role → app role` in onedir. It reduces artifact pairing but retains heavy
collection/runtime-hook exposure and same-executable/bootloader recursion complexity. It does not
cover its own pre-entry failure. Accept it only if the PO explicitly selects that narrower startup
scope and measured packaging evidence supports it; it is not the recommended strong-boundary V1.

Qualify onedir/standalone first, then their onefile tracks. The generic
[6.11.1 bootstrap prose](https://pyinstaller.org/en/v6.11.1/advanced-topics.html) describes two processes
except Windows onedir, but exact [v6.11.1 bootloader source](https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.11.1/bootloader/src/pyi_main.c)
`_pyi_main_handle_posix_onedir` (1255–1305) resolves Linux onedir explicitly: adjust the library path
and `execvp` without `fork`, retaining the PID. The diagram follows source over that broad prose;
this applies to the lean onedir launcher as well. Runtime/build version remains unpinned here, so
exact-artifact qualification must still confirm the selected version's actual PID tree.

PyInstaller distinguishes parent, main and worker process levels; onefile extraction lifetime belongs
to the bootloader. Private `_PYI_*` state is not an application role API. Consult the **chosen version's**
public behavior and do not forge private flags. The current manual additionally describes changes
since 6.22.1; the repository's lower-bound requirement does not prove those protections exist in an
older artifact. [PyInstaller bootloader documentation](https://pyinstaller.org/en/stable/advanced-topics.html)

Nuitka's standalone and onefile choices require separate process/extraction receipts, and same-binary
execution must not be treated as a general Python `-c` interpreter. Do not assume compiled source
maps or subprocess dispatch work like .pyc. [Nuitka manual](https://nuitka.net/user-documentation/user-manual.html)

### 8.2 Dispatch, identity and lifetime requirements

The launcher manifest identifies the paired application by a trusted artifact identity and relative
installation entry, resolved against the launcher location, **never CWD/PATH**. Preserve the user's
original CWD and intentional arguments for product semantics but exclude them from diagnostics.
Reject missing/mismatched/tampered child before spawn; no automatic search for a similarly named exe.
Unverified source mode is visibly weaker than signed/retained release-artifact pairing. Parent-built
metadata cannot simply trust an app-supplied SHA. Ordinary same-account use requires no elevation.

For packaged applications, public entry must resolve direct/supervised/worker modes before heavyweight
imports or UI creation. Standard multiprocessing diversion/`freeze_support` must precede normal app
argument parsing where the frozen packager requires it. Avoid `sys.executable -c` recursion: source
Python and frozen app executables are different launch contracts. `runtime_hooks=[]` does not remove
automatic dependency hooks. No-console handling and loader hooks must be exercised before declaring
startup protected. [PyInstaller common pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)

The separate launcher runtime must not contaminate a separately bundled app's DLL/library search.
Treat the paired app as a separate executable environment and restore the launcher's own loader
modifications in its spawn context. The app's own bundled workers retain the app environment;
external system tools receive the separately sanitized environment. Do not globally mutate search
paths while other launcher threads spawn; serialize this narrow spawn boundary. No environment
values are retained or exported.

IPC handshake occurs at the earliest practical app hook/entry and identifies actual `A`; before it,
only `B`/launched-process evidence is available. On Windows retain a process handle and query exit
status before it disappears. On POSIX a supervisor can wait for its direct child; a onefile grandchild's
status may be only bootloader-propagated. Do not manufacture direct wait status for that grandchild:
record observation provenance or `unknown`, with a future armed collector as stronger evidence.

Keep the launcher outside app extraction directories. `B` owns extraction cleanup and may wait for `A`;
`L` neither deletes a running extraction directory nor assumes `A` exit completes cleanup. Closing
`L` must not kill `A`. On abnormal `B` loss while `A` lives, report packaging/lifetime uncertainty and
leave cleanup to separately qualified packager behavior; no unsafe global temp cleanup. Concurrent
onefile instances must prove isolation, including AV locks and delayed cleanup.

A missing launcher/diagnostic subsystem provides an explicit existing direct-launch path with a fixed
“diagnostics unavailable” indication. Never start a second app as fallback if the first launch's
identity/liveness is uncertain. “Direct launch” does not mean recover/replay interrupted work.

### 8.3 Real acceptance required per artifact

S2 must demonstrate source/Linux and source/Windows first, then **PyInstaller onedir, PyInstaller
onefile, Nuitka standalone and Nuitka onefile** individually, with exact Python/Qt/packager versions,
head/tree/artifact hash/provenance/notices and observed process/role map. A mode stays unqualified and
cannot be advertised as supervised until its own gates pass; no packager/dependency update is implied.

For each: shortcut and CLI/no-console; spaces/non-ASCII/relative invocation; portable/read-only install;
missing/tampered/mismatched child; pre-entry failure; IPC peer/handle ownership; future/process worker
dispatch without recursion; no-console `None`; early native output; normal exit; child/supervisor loss;
concurrent launches; AV/file locks; extraction cleanup; external-tool versus own-bundle library paths;
offline operation; direct fallback and no privilege prompt. Native fault/Qt cases require a separately
authorized isolated acceptance packet, not local user-session experiments. [#901](https://github.com/hexafe/metroliza/issues/901)
retains clean-machine exact-artifact release acceptance; ordinary Windows core smoke is insufficient.

## 9. Hang detection and measurement plan

Keep three independent observations: (1) an OS process exists; (2) a GUI-loop timer/ping was processed;
(3) an operation progressed. A worker heartbeat cannot certify the GUI. Proposed S3 heartbeat is a
2-second GUI-loop tick with no disk write; missing ticks for 15 seconds produce only `suspect` after
startup/operation context is considered. A separate launcher cadence-gap detector resets suspicion;
allow 30 seconds grace after known resume and a fresh responsiveness baseline. Wall-clock jumps,
suspend semantics and attached debugger uncertainty must be tested per OS. If pause cannot be
identified, label “responsiveness unknown/delayed”, not a proved deadlock. Allow explicit temporary
support pause/extension; do not infer it from arbitrary environment/debugger strings.

Request one bounded safe snapshot and notify at most once per suspicion interval. A nonresponsive
GUI may not answer; this fact belongs in the incident. Recovery of responsiveness ends the interval;
no kill/restart or write cancellation. Long blocking GUI work is a responsiveness issue even if
expected, but not proof that the process cannot finish. Operation-specific expected stages may
qualify the message; they do not suppress recording indefinitely.

Before performance approval, measure baseline versus candidate on the **same exact source/artifact**
with synthetic idle/startup/import/export workloads and agreed hardware. Separate cold/warm launches,
packager extraction time and launcher-to-GUI-ready time. Report distributions and sample count,
not invented improvements. Proposed initial measurement recipe is 20 paired launches per cold/warm
mode and 5 trials of each 60-second load profile, subject to an approved bounded execution packet.

| Metric | How to collect / proposed acceptance discussion target |
| --- | --- |
| Startup delta | External timestamps + safe GUI-ready milestone; report median/p95 and absolute delta. Candidate budget <=100 ms warm added p95, to be accepted or revised from real data |
| Resident memory | OS sampling of whole process tree; peak and idle RSS/private bytes versus baseline, including launcher/bootloaders/handler. Encoded 2 MiB ring is not an RSS bound; provisional incremental budget <=40 MiB requires measurement |
| Event cost / dropped rate | Synthetic 10/100/1,000 events/s plus 10,000/s flood; admitted/dropped/evicted/terminal counts. Demonstrate bounded plateau, preserved terminal evidence and no raw output |
| GUI responsiveness | Loop latency/jitter compared with recording disabled at equal work; proposed added p95 <=5 ms under ordinary load; no claim before actual binding/package tests |
| Idle disk writes | OS process-attributed write counters, excluding unrelated application/OS writes. New recorder has only the named lifecycle marker writes; existing managed-file writes are measured separately until S2d; no periodic recorder write |
| Incident publication | Trigger-to-valid-final-file and failure-notification latency with ring full; proposed healthy-local-store p95 <=1 second, storage-failure wait bounded to <=1 second before unavailable status; slow syscall/platform limits must be reconciled before accepting this bound |
| Degraded/flood behavior | CPU/RAM/queue/lock/EOF tests, parent death, no-console and disk denial; privacy/correctness must pass before speed tuning |

Do not enable a new benchmark campaign merely to deliver this document. Timing and memory targets
are negotiable; absence of measurements is explicit. A synchronous filesystem syscall can stall beyond
a Python timeout: publication must run independently of liveness/producer handling, and implementation
must qualify what its deadline actually bounds (notification/queue admission versus kernel I/O).

## 10. Staged implementation packets and rollback

No follow-on implementation Issue, assignment, dependency change or activation is created by this
research. External owner ORCH-METROLIZA and PO accept/refine these packets first. Each slice has one
writer, independent security/semantics review and exact-head evidence; no concurrent writers on the
shared event contract or LEWY's experimental helper. Keep the total class CRITICAL / MILESTONE.

| Proposed slice / owner / prerequisites | MUST | SHOULD | DEFERRED and rollback |
| --- | --- | --- | --- |
| **S1: useful safe events/hooks**; #944 foundation owner; accepted schema/privacy contract | Extend existing classes; session/operation/stage/outcome and safe code-map contracts; bootstrap/handled/thread/future seams; preserve default Qt global exception hook; tests that fail on raw text, dynamic filenames, extra fields, spoofed metadata and lost terminal outcomes. Preserve original exception/termination and UI/result behavior | Start with bootstrap plus one import and one export adapter; approved lazy build/backend facts. Narrow Qt hook semantics and single-message-handler ownership/coexistence qualification as their own authorized test gate | No mass log rewrite, supervisor, native dump or DB changes. Roll back new adapters/event variants while retaining current #1011 safe logging; unknown-new-event readers fail closed |
| **S2a: supervised V1**; #944 runtime + packaging owner; S1 and accepted budgets | Minimal launcher, authenticated bounded IPC/ring/store/marker, safe publication/failure display, direct fallback; actual exit provenance and native-stack-unavailable status; fail-first process/privacy tests; routing/coexistence tests proving new recorder delivery does not duplicate events into current home/CWD sinks; selected packaged targets and #901 mapping | Optional faulthandler RAM channel only after separate transport/mapping qualification; bootstrap-safe Python frame context | No kill/restart, raw dump or hang engine. Disable supervision through explicit direct entry; retain safe incidents/markers without replay; do not delete diagnostic evidence automatically |
| **S2b: operator preview/export**; #944 UX/service owner; S2a safe capture | Validate stored report, exact manifest/preview/cancel, atomic explicit export, alias guards, no arbitrary attachments. Core capture already works in S2a; export is not a prerequisite for saving an incident | Small readable timeline and instructions for missing symbols/history | No cloud/notes/samples/dumps by default. Disable export action independently while capture remains functional |
| **S2d: managed-log policy migration**; #944 logging/security owner; S2a plus explicit PO acceptance | Own the switch from current dual home/CWD files to the proposed incident-triggered default; preserve closed serialization and visible logging-unavailable behavior; update existing rotation/fallback/level tests for explicitly selected modes; prove default no duplicate CWD/home event writes and support expiry | Keep source-compatible safe event types, concise migration guidance and optional bounded support file | No silent policy change in S2a. Roll back routing/configuration to current safe managed logging while retaining incident evidence; do not revive arbitrary text. Until this gate, whole-app incident-only behavior remains unimplemented |
| **S3: responsiveness**; #944 + #945 UI owner; S2a and qualified Qt lifecycle seam | Separate OS/GUI/progress semantics; resume/debugger/legitimate-long-work tests; bounded suspicion snapshot and notification; no forced shutdown | Operation-specific stage expectations, diagnostic pause and recovered state | No causal deadlock claims or automatic remediation. Disable heartbeat interpretation; leave exit/history capture working |
| **S4: sensitive native capability**; native/platform security owner + #901; explicit separate approval | Compare exact Crashpad versus Sentry Native builds and OS-only support path; native registration before failure, symbol retention including GCC/Clang/PDB decision, dedicated handler/private database, collection-time privacy (not before_send/on_crash), consent/retention/offline proof, handler coexistence and crash-time privacy review; verify actual app PID for every package | Prefer direct Crashpad if local capture still outweighs SDK maintenance; use already available OS evidence for narrowly approved support cases | Default raw/minidump collection and upload remain disabled. Removing/denying collector must leave V1 diagnostics operational; unregister safely, preserve OS settings and separately consented retained artifacts |

S2a can be delivered in separate small PRs: core/source transport and store first, Windows onedir
qualification next, then onefile and Nuitka qualification tracks. Early capture remains useful while
unqualified modes keep the explicit direct path; do not advertise those modes as protected. S2b
export and S2d logging-policy migration are independently reviewed behavior changes.

Every implementation packet must include tests with a deliberately missing hook, lossy/full transport,
wrong peer, invalid event, denied publication and unqualified native stack so that false success fails.
Report outcomes separately for software protocol, actual PyQt behavior, packaged Windows, native
symbolization and physical/power-loss testing. None can be substituted by an aggregate green suite.

Dependency/owner map: #1011 accepted schema is the foundation; #1002/#1000 provide reusable patterns
and retain OCR/release ownership; #917/#920 supply build/provenance policy; #927/#929/#936/#940/#941
consume safe workflow adapters; #945 supplies preview/UI seams; #901 owns exact-artifact/clean-machine
gates. #998 is evidence input only and continues independently; neither #998 closure nor a speculative
Qt repair is a prerequisite for designing this diagnostic foundation. Shared-ledger/roadmap maturity
updates wait for accepted product behavior.

## 11. Acceptance decisions and research validation

The PO can accept the schema/coverage direction independently of sensitive native capture. Concrete
open decisions are: separate launcher delivery/size budget versus narrower same-bundle supervision;
healthy marker writes versus explicit RAM-only mode; S2d migration away from current dual logs;
retention/instance/flood limits; which packaged
modes are enabled after individual qualification; and whether/when to authorize the fatal RAM channel
and S4. Recommended defaults are those in sections 1 and 6. No unresolved choice silently enables
raw output, automatic restart, system configuration or cloud transport.

Research acceptance requires this single document to cover packet A–H, consistent source/status
claims, primary references, parseable synthetic JSON, existing docs/ownership/hygiene checks,
`git diff --check` and independent exact-document review. Runtime falsification is not applicable to
this documentation-only diff; explicit broken-case acceptance oracles are supplied for implementation.
The canonical checkpoint records the actual final document blob/commit/tree, checks, reviews, CI,
START/END and later source movement; do not embed a self-referential final commit in this document.

MUST mapping: A → section 2/source catalog; B → section 3; C → sections 5/7; D → section 4;
E → section 6; F → section 8; G → sections 5/9; H → sections 10/11. No feature-catalog promotion,
accepted ADR, Ready, merge, Issue closure, experiment renewal or production wrapper is delivered.

## Source catalog at the audited commit

These links bind observations to the audited source, not moving `develop`. Tests named above are
read for their assertions; only checks explicitly reported in the canonical receipt were run here.

- **R1:** [logging_utils.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/shared/logging_utils.py), [logging tests](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/tests/test_logging_utils.py).
- **R2:** [diagnostic_events.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/shared/diagnostic_events.py), [event tests](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/tests/test_diagnostic_events.py).
- **R3:** [custom_logger.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/shared/custom_logger.py).
- **R4:** [root launcher](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/metroliza.py), [bootstrap](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/app/bootstrap.py), [startup tests](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/tests/test_bootstrap_startup.py).
- **R5:** [build_provenance.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/app/build_provenance.py).
- **R6:** [startup_profile.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/app/startup_profile.py), [profile/guard tests](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/tests/test_startup_performance_guards.py).
- **R7:** [package entry](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/packaging/metroliza_package_entry.py), [onedir spec](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/packaging/metroliza_onedir.spec), [onefile spec](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/packaging/metroliza_onefile.spec), [Nuitka build](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/packaging/build_nuitka.ps1), [packaging tests](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/tests/test_packaging_spec_hiddenimports.py).
- **R8:** [parse_reports_thread.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/parsing/parse_reports_thread.py).
- **R9:** [metadata_enrichment_thread.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/parsing/metadata_enrichment_thread.py), [parser_preflight_worker.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/ui/parser_preflight_worker.py).
- **R10:** [industrial_workers.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/industrial/industrial_workers.py).
- **R11:** [export_data_thread.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/exporting/export_data_thread.py), [export_logging_service.py](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/exporting/export_logging_service.py).
- **R12:** [canonical backend diagnostics](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/exporting/backend_diagnostics.py), [app alias](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/app/backend_diagnostics.py).
- **R13:** [native bridge package](https://github.com/hexafe/metroliza/tree/b645164e83898df69335713f808189de6cc1fc31/src/metroliza/native_bridges), [runtime requirements](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/requirements.txt), [build requirements](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/requirements-build.txt).
- **R14:** [OCR process/publication contract](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/scripts/ocr_diagnostic_contract.py), [runtime CLI](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/scripts/windows_ocr_runtime_diagnostics.py), [header CLI](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/scripts/diagnose_header_ocr_metadata.py), [PowerShell wrapper](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/diagnose_windows_ocr.ps1), [setup](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/setup_windows_runtime.ps1), [process tests](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/tests/test_windows_ocr_runtime_diagnostics.py).
- **R15:** [developer scripts inventory](https://github.com/hexafe/metroliza/tree/b645164e83898df69335713f808189de6cc1fc31/scripts), [startup measurement](https://github.com/hexafe/metroliza/blob/b645164e83898df69335713f808189de6cc1fc31/scripts/measure_windows_startup.ps1).
