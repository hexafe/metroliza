# Metroliza native launcher

Rust launcher for the Windows single-EXE delivery (issue #1099, tracking #1101). The PyInstaller
onefile extracts every file to `%TEMP%` on every start; this launcher carries the onedir as an
appended payload, unpacks it **once per version** into a persistent per-user cache, and afterwards
only validates that cache and starts the entry executable.

It is a standalone binary crate, not a Python extension: it has no Python fallback. The fallback
delivery is the existing PyInstaller onefile/onedir.

## Crates and binaries

| Binary | Purpose |
| --- | --- |
| `metroliza-launcher` | The stub that becomes the user-facing EXE (`windows_subsystem = "windows"`). |
| `metroliza-packer` | Host tool: onedir + stub -> one EXE. Runs on Windows CI and Linux. |
| `launcher-test-entry` | Tiny stand-in for `metroliza.exe` used by tests and `scripts/qualify_windows_launcher.py`. |

All logic except the Win32 layer (`src/platform/windows.rs`) is platform independent and tested on
Linux. Dependencies are pure Rust (`lz4_flex`, `sha2`, `serde`, `serde_json`, `windows-sys` on
Windows); `Cargo.lock` is committed and every build uses `--locked`.

```
cargo test  --locked --manifest-path packaging/launcher/Cargo.toml
cargo check --locked --manifest-path packaging/launcher/Cargo.toml --target x86_64-pc-windows-gnu
.\build_windows_launcher_exe.ps1 -BuildOnedir      # full Windows build
```

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
<root>/<version>_<sha8>/.complete     marker: hex manifest hash, written last
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
4. **Warm**: marker equals the manifest hash and every manifest file exists with its expected size.
   No hashing, nothing written. The entry is started.
5. **Cold** (no directory) or **repair** (directory present but invalid): show the progress window,
   take `.extract.lock` (waiting if another process extracts, then re-check warm), delete stale
   staging directories, delete the invalid directory, extract with a bounded thread pool into
   `<dir>.staging-<pid>`, verify the SHA-256 of every file while writing, `fsync` each file,
   rename into place, then write and flush the marker.
6. Start the entry executable with `CreateProcessW`: no inherited handles, working directory = the
   runtime directory, arguments passed through. Wait for it and return its exit code.
7. Alongside the app, a best-effort cleanup keeps the current version and the most recently
   completed other version and removes the rest. It only touches directories named
   `<version>_<sha8>`, skips versions whose `.use` lock is held, and yields to a running
   extraction. It never fails the launch.

A process killed at any point leaves either no marker (so the directory is never used) or a staging
directory that the next extraction deletes. Corruption or a partial cache is repaired by
re-extracting; it never fails silently.

## User-visible errors

Only fixed English texts (`src/error.rs`): no exception text, paths or codes. Details go to the log
file named by `METROLIZA_LAUNCHER_LOG` if set. The launcher's own failures use exit codes
101-104; otherwise the exit code of the entry process is returned. Log lines: `cache=cold|warm|repair`,
`instance=second`, `entry=started`, `exit=<code>`, `cleanup ...`, `error=...`. Setting
`METROLIZA_LAUNCHER_NO_UI=1` suppresses message boxes (CI).

## Security notes

* The cache is per user and user-writable, like any per-user install. Anyone who can write to
  `%LOCALAPPDATA%` as that user can alter it; the launcher does not defend against that.
* Integrity is verified at **extraction**: every file's SHA-256 is checked while it is written, and
  the manifest is bound to the trailer by hash. A tampered payload fails extraction.
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
  process**; with a supervisor as entry the window may belong to its child, in which case the
  fixed "already running" message is shown instead.
* Empty directories in the onedir are not preserved.
