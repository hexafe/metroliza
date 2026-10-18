# Metroliza native launcher

Rust launcher for the Windows single-EXE delivery (issue #1099, tracking #1101). The PyInstaller
onefile extracts every file to `%TEMP%` on every start; this launcher carries the onedir as an
appended payload, unpacks it **once per version** into a persistent per-user cache, and afterwards
only validates that cache and starts the entry executable.

It is a standalone binary crate, not a Python extension: it has no Python fallback. The fallback
delivery is the existing PyInstaller onefile/onedir.

For the 2026.09 RC1 line the payload is the **supervised onedir**
(`dist/metroliza_P_<label>_onedir`: the supervisor `metroliza.exe`, `metroliza_application.exe`,
`metroliza_ocr_worker.exe`, `metroliza_compute_worker.exe`, `supervision_manifest.json` and the rest of the onedir) and the entry is
`metroliza.exe`. The PyInstaller portable envelope (`metroliza_<label>.exe`, built by
`build_windows_portable_exe.ps1`) carries the same onedir but extracts all of it to `%TEMP%` on every
launch; it stays in the tree as the comparison and fallback delivery. See
[Packaging the supervised onedir](#packaging-the-supervised-onedir).

## Crates and binaries

| Binary | Purpose |
| --- | --- |
| `metroliza-launcher` | The stub that becomes the user-facing EXE (`windows_subsystem = "windows"`). |
| `metroliza-packer` | Host tool: onedir + stub -> one EXE. Runs on Windows CI and Linux. `--content-key` appends the onedir content hash to the version (below). |
| `launcher-test-entry` | Tiny stand-in for `metroliza.exe` used by tests and `scripts/qualify_windows_launcher.py`. `--request-repair` exits 75 while the repair variable is set. |

All logic except the Win32 layer (`src/platform/windows.rs`) is platform independent and tested on
Linux. Dependencies are pure Rust (`lz4_flex`, `sha2`, `serde`, `serde_json`, `windows-sys` on
Windows); `Cargo.lock` is committed and every build uses `--locked`.

```
cargo test  --locked --manifest-path packaging/launcher/Cargo.toml
cargo check --locked --manifest-path packaging/launcher/Cargo.toml --target x86_64-pc-windows-gnu
.\build_windows_launcher_exe.ps1 -Supervised      # pack the supervised onedir built by build_windows_portable_exe.ps1
```

## Packaging the supervised onedir

```powershell
.\build_windows_portable_exe.ps1                  # supervised onedir + portable envelope (unchanged)
.\build_windows_launcher_exe.ps1 -Supervised      # the same onedir -> dist\metroliza_<label>_launcher.exe
# or in one go, without the envelope:
.\build_windows_launcher_exe.ps1 -Supervised -BuildOnedir -Clean -WithNative
```

`-Supervised` refuses to pack anything but the RC1 supervised package: the entry must be
`metroliza.exe`, the supervisor, application, OCR worker and `supervision_manifest.json` must be
present, the build provenance must be the clean, exact `HEAD` with the same release label, and the
onedir must pass the identity check the portable envelope runs (`_verified_launcher`: complete
package identity plus the supervisor's provenance sidecar). The supplied onedir's verified
identity, embedded provenance and supervisor sidecar must all identify `HEAD`; a valid package
from another commit is rejected even when its release label matches. Without `-Supervised` the script packs
any onedir (the CI synthetic payload uses that).

* **Name:** `dist/metroliza_<label>_launcher.exe`, e.g. `metroliza_2026.09rc1_260927_launcher.exe`.
  The envelope is `metroliza_2026.09rc1_260927.exe`. The suffix keeps the two apart in `dist`,
  in artifact globs and in the qualification scripts, which check the name against the kind.
* **Runtime key:** the packer is called with `--content-key`, so the stored version is
  `<label>-<hash12>` and the cache directory is `<label>-<hash12>_<sha8>`, for example
  `2026.09rc1_260927-0123456789ab_89abcdef`. `hash12` is the first 12 hex digits of a SHA-256 over
  the entry path and, per file in path order, its path, size and content SHA-256. It does not
  depend on compression, offsets, the label or the commit, so two builds of the same files share
  it, and any changed, added or removed file gives a new directory. `sha8` is the source commit.
  The single-instance name (`Local\Metroliza-<version>`) uses the same stored version, so two
  builds with different contents can run side by side with separate caches.
* Provenance and notice sidecars are staged for the launcher EXE like for the envelope
  (`<exe>.provenance.json`, `<exe>.licenses`).
* The packer prints a JSON summary (`version`, `content_sha256`, `dir_name`, sizes); the script
  echoes the runtime directory name.

## Self-repair contract

After the second-launch integrity/durability pass, the completed warm check is size-only.
Later same-size modifications need the supervisor's package-identity check and this repair contract:

1. The launcher sets `METROLIZA_RUNTIME_REPAIR_AVAILABLE=1` in the environment of the **first**
   start of the entry (any inherited value is overwritten).
2. If the supervisor finds its package invalid and that variable is `1`, it shows **no notice** and
   exits with code **75** (`EX_TEMPFAIL`). Without the variable it keeps showing its precise notice.
3. On exit code 75 the launcher logs `repair=requested`, releases the runtime, deletes the
   pending and completion markers (so the directory can never look valid again; the whole tree is
   removed if a matching marker cannot be deleted), re-extracts and re-verifies every file through the normal repair path
   (`cache=repair`) and starts the entry **once more, with the variable removed**.
4. The exit code of that second run is returned unchanged, 75 included. There is never a second
   repair and never a loop; a second failure therefore reaches the user as the supervisor's precise
   notice.
5. Every other exit code, of the first start, passes through unchanged and nothing is restarted. If
   the re-extraction itself fails the user sees the fixed extraction error (exit code 101-104).

The single-instance mutex, the `.use` lock and the entry process id publication stay in place
across both starts. The supervisor side of the contract is specified in #1111 and is **not part of
this branch**; until it lands nothing exits with 75 and the launcher behaves exactly as before. The
launcher half is covered by the e2e tests with a fake entry (75 then success, 75 twice, other exit
codes unchanged, an inherited variable never reaches the restart) and by the `self_repair_exit_75`
scenario of `scripts/qualify_windows_launcher.py`.

## EXE format

```
[launcher PE][payload: file blobs..., manifest JSON][zero padding][trailer, 64 bytes][certificate table?]
```

* **Trailer** (little endian): magic `MTRLZPL1`, payload offset, payload length, manifest length,
  SHA-256 of the manifest. If the PE header announces an Authenticode certificate table
  (`IMAGE_DIRECTORY_ENTRY_SECURITY`) the trailer ends exactly where the table starts; otherwise at
  end of file. The packer pads so the trailer ends on an 8-byte boundary, the alignment signtool
  uses, so a signed EXE needs no scanning. The packer refuses a stub that is already signed: sign
  the **final** EXE.
* **Manifest** (JSON): format, version label, git sha, entry path (relative, recorded at pack time,
  so the same launcher starts `metroliza.exe` today or a supervisor later) and, per file, relative
  path, size, SHA-256, stored size and blob offset. The manifest hash is the identity of a payload.
* **Blobs**: each file is a sequence of independent blocks of up to 4 MiB uncompressed. A block is a
  `u32` header plus bytes; the top bit marks a block stored raw because LZ4 did not shrink it.
  Chunking bounds memory per worker thread.
* **Codec: LZ4** (`lz4_flex`, safe Rust). Chosen for decode speed: first-run time is dominated by
  disk and antivirus, not inflate (the RC1 envelope spends ~4.0 of 4.4 simulated seconds in
  single-threaded inflate). The cost is a larger EXE than zstd would give; zstd needs a C compiler
  and can replace LZ4 later by bumping the manifest `format`.
* Packing is deterministic (sorted paths, no timestamps). It rejects absolute paths, `..`, drive or
  stream syntax, reserved device names, case-insensitive duplicates, symlinks and reparse points.
  The same path rules are re-applied to the manifest before anything is created at run time.
  Empty directories are not recorded.

## Cache layout and states

```
<root>/<version>_<sha8>/              unpacked onedir; valid only with a matching marker
                                      (version = <label>-<hash12> for a --content-key payload)
<root>/<version>_<sha8>/.pending      flushed manifest hash; extraction finished, verification due
<root>/<version>_<sha8>/.complete     flushed manifest hash; verified files are durable
<root>/<version>_<sha8>.staging-<pid> extraction in progress
<root>/<version>_<sha8>.use           lock file, shared lock held while that version runs
<root>/.extract.lock                  exclusive lock: cold extractions and cleanup
```

**Root resolution:** `METROLIZA_RUNTIME_ROOT` (tests/qualification; authoritative, no fallback),
else `%LOCALAPPDATA%\Metroliza\runtime`, else `MetrolizaRuntime` next to the EXE. A candidate is
rejected if it cannot be created, is a symlink/reparse point (also its parent for the profile
location), or fails a write probe. If none works the user sees a fixed-text error. Nothing is ever
written to `%TEMP%`.

**Start sequence:**

1. Read and verify trailer and manifest (manifest hash).
2. Take the named mutex `Local\Metroliza-<version>`. If held, bring the running instance's window
   forward (the entry process id is published in a named section) or show a fixed message, then
   exit with code 0 without touching the cache.
3. Take the shared `.use` lock of this version.
4. **Warm**: `.complete` equals the manifest hash, `.pending` is absent and every manifest file
   exists with its expected size. No hashing, nothing written. The entry is started.
   **Pending**: under `.extract.lock`, verify every manifest file's SHA-256 using 2–8 bounded
   workers (1 MiB per worker), then flush each verified file. Verification alone can read dirty
   OS pages, so flushing is required before promotion. Persist directory entries on Unix, write
   and flush `.complete`, then remove `.pending`. Log `cache=verified` and start the entry.
   If either marker is wrong, a file differs, or verification cannot read/flush it, re-extract
   before starting the entry. If both markers survive an interrupted promotion, pending wins.
   A resource-use check prevents replacement while an orphaned application is still running.
5. **Cold** (no directory) or **repair** (directory present but invalid): show the progress window,
   take `.extract.lock` (waiting if another process extracts, then re-check warm), delete stale
   staging directories, delete the invalid directory, extract with a bounded thread pool into
   `<dir>.staging-<pid>`, verify each SHA-256 while writing, rename into place, then write and flush
   `.pending`. Run immediately without per-file flushing. This preserves fast first launch; the
   next launch must complete the pending pass even when the supervisor EXE cannot start.
   Set `METROLIZA_LAUNCHER_SYNC_FILES=1` to also flush files during extraction.
6. Start the entry executable with `CreateProcessW`: no inherited handles, the **launcher's own
   working directory** (where the user started it, as with the portable envelope; the runtime
   directory is a disposable cache and must never become the default folder of a file dialog or of
   a relative export name), arguments passed through, `METROLIZA_RUNTIME_REPAIR_AVAILABLE=1` set.
   Wait for it. If it exits with 75, repair the runtime and start it once more without the variable (see
   [Self-repair contract](#self-repair-contract)). Return the exit code of the last run.
7. Alongside the app, a best-effort cleanup keeps the current version and the most recently
   completed other version and removes the rest. It only touches directories named
   `<version>_<sha8>`, skips versions whose `.use` lock is held, and yields to a running
   extraction. Before deleting any file (including the marker), Windows Restart Manager checks
   every runtime resource for live users. This preserves a complete runtime when an application
   outlives its supervisor and launcher, even without a `.use` lock; query failures also preserve
   the directory. Only resource queries are used, never process shutdown or restart. Linux tests
   use `/proc` executable mappings as the stand-in. It never fails the launch.

Interrupted extraction leaves staging or an unmarked directory, which is re-extracted. A durable
pending marker always requires full verification on the next launch; a completed cache has already
passed verification and file flushing. A verification mismatch repairs without relying on exit 75.

## User-visible errors

Only fixed English texts (`src/error.rs`): no exception text, paths or codes. Details go to the log
file named by `METROLIZA_LAUNCHER_LOG` if set. The launcher's own failures use exit codes
101-104; otherwise the exit code of the entry process is returned. Log lines: `cache=cold|verified|warm|repair`,
`instance=second`, `entry=started` (twice after a repair), `repair=requested`, `exit=<code>`,
`cleanup ...`, `error=...`. Setting `METROLIZA_LAUNCHER_NO_UI=1` suppresses message boxes (CI).

## Measuring startup and qualifying the real payload

Both run on Windows only and are wired into the manual CI jobs; run them locally the same way.

```powershell
.\build_windows_portable_exe.ps1                  # onedir + envelope
.\build_windows_launcher_exe.ps1 -Supervised      # launcher EXE from the same onedir

# Qualification: first launch, reopen, hard exit, incident export, cleanup. For the launcher it
# also asserts cache=cold, then cache=verified, then cache=warm and one complete content-keyed runtime directory.
.\.venv-build\Scripts\python.exe scripts\qualify_windows_portable_onefile.py --artifact dist\metroliza_<label>_launcher.exe --kind launcher
.\.venv-build\Scripts\python.exe scripts\qualify_windows_portable_onefile.py --artifact dist\metroliza_<label>.exe

# Startup benchmark: the same smoke through envelope, launcher cold, verification and warm, 3 runs each.
.\.venv-build\Scripts\python.exe scripts\measure_windows_startup_routes.py `
  --portable dist\metroliza_<label>.exe --launcher dist\metroliza_<label>_launcher.exe --runs 3 --output-dir startup-artifacts
```

CI: `run_windows_startup_benchmark=1` (job `windows-startup-benchmark`) builds all three and uploads
`startup-benchmark.json`, `startup-benchmark.md`, the profiles and launcher logs as
`windows-startup-artifacts`; `run_windows_portable_onefile=1` (job `windows-portable-onefile`)
qualifies both EXEs and uploads the launcher as `windows-supervised-launcher-exe`;
`run_windows_launcher_qualification=1` runs the synthetic-payload scenarios (including the
self-repair on exit 75).

The benchmark uses the application's own startup smoke, `METROLIZA_STARTUP_UI_SMOKE=1`: the real
main window is built and shown and the process exits after the first Qt event-loop tick, with
`METROLIZA_LICENSE_VERIFICATION=0` so no dialog can appear. The supervisor forwards its environment
to the application, so the variable works through the supervised chain; this is verified by the
run itself (a run without the `first_event_loop_tick` profile event fails). The profile events carry
a wall-clock `epoch_ms`, which lets the script report the time from process creation to
`main_window_show_called` and to `first_event_loop_tick` ("first paint": the first event-loop tick
after `show()`), including launcher, extraction and supervisor time. Cold launches use a fresh
`METROLIZA_RUNTIME_ROOT` each; second-launch verification uses each of those three pending caches;
warm samples are launches 3 to 5 of one completed cache. Hosted
runner numbers are indicative, not clean-machine evidence.


The integrity/durability pass is a **one-time second-launch cost after each extraction or repair**.
The #1105 correction measured a synthetic payload of 128 MiB incompressible filler, 168 files
(134,982,097 bytes total), using 8 workers on Linux x86_64/tmpfs. Median of three launches:

| Phase | Before | Two-phase cache |
| --- | ---: | ---: |
| First launch (extract) | 318.0 ms | 318.6 ms |
| Second launch | 3.9 ms (size-only) | 215.3 ms (SHA-256 + flush + promote) |
| Completed warm launch | 4.0 ms | 3.9 ms |

The observed one-minute host load ranged from 8.90 to 10.46. These are memory-backed synthetic
measurements, not Windows disk or packaged-application timings; in particular tmpfs does not
measure physical flush latency. The real supervised payload has roughly 2,000 files, so its
one-time NTFS flush cost remains to be measured. The Windows startup benchmark now reports this
phase separately, once for each of three independently extracted caches, before measuring warm
launches. Completed warm launches still perform only marker, existence and size checks.

## Security notes

* The cache is per user and user-writable, like any per-user install. Anyone who can write to
  `%LOCALAPPDATA%` as that user can alter it; the launcher does not defend against that.
* Integrity is verified at **extraction** and again before pending-cache promotion: every file's
  SHA-256 is checked, and the manifest is bound to the trailer by hash. Files are flushed before
  committing `.complete`. Cache marker paths are reserved and cannot occur in the payload.
* The **warm check is size-based by design** (no hashing on the fast path). It detects deleted,
  truncated or replaced files but not same-size modification of an extracted file.
* Signing: no certificate exists today. `build_windows_launcher_exe.ps1` signs the final EXE when
  `METROLIZA_SIGNING_CERT_FILE` and `METROLIZA_SIGNING_CERT_PASSWORD` are set (optionally
  `METROLIZA_SIGNING_SIGNTOOL`, `METROLIZA_SIGNING_TIMESTAMP_URL`) and prints "signing skipped"
  otherwise.

## Known limits

* No application icon or version resource is embedded in the launcher EXE yet (needs the Windows
  resource compiler); the progress window and dialogs are plain Win32.
* POSIX permissions are not stored; the non-Windows stand-in marks the entry executable only so
  Linux tests can run it. The Linux build has no single-instance guard and no UI.
* Window activation for a second instance finds a visible top-level window of the **entry
  process**; with the supervisor as entry the window belongs to its child
  (`metroliza_application.exe`), so a second launch normally shows the fixed "already running"
  message instead of activating the window. Not yet proven on Windows with the real payload.
* The self-repair restart re-extracts the whole runtime (the same cost as a cold start, with the
  progress window). It is meant for the rare damaged cache, not for routine use.
* Empty directories in the onedir are not preserved.
