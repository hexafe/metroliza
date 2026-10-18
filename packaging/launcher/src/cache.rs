//! Persistent, versioned runtime cache: root resolution, state machine, extraction, cleanup.
//!
//! Extraction commits a flushed `.pending` marker and runs immediately. The next launch hashes
//! and flushes every manifest file with bounded workers, then writes a durable `.complete` and
//! removes `.pending`. Completed warm caches keep the cheap existence/size check. Both markers
//! contain the manifest hash; if both survive an interrupted promotion, pending takes precedence.
//! A mismatch repairs from the payload before starting the entry, even if its EXE is damaged.
//!
//! Shared `<version>_<sha8>.use` leases protect active launchers. `.extract.lock` serializes
//! extraction, promotion and cleanup. Cleanup keeps current and previous versions and probes OS
//! resource users before any deletion, protecting applications orphaned by their supervisor.

use std::fs::{self, File, OpenOptions, TryLockError};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, SystemTime};

use sha2::{Digest, Sha256};

use crate::archive::{decode_file, Payload};
use crate::error::{LauncherError, Result};
use crate::fsutil::is_link_or_reparse;
use crate::manifest::{validate_version, FileEntry};

pub const MARKER: &str = ".complete";
pub const PENDING_MARKER: &str = ".pending";
pub const EXTRACT_LOCK: &str = ".extract.lock";
const STAGING_INFIX: &str = ".staging-";
const USE_SUFFIX: &str = ".use";

/// Receives extraction progress. Only used on the cold/repair path; must be callable from
/// several worker threads.
pub trait Progress: Sync {
    /// Called once when an extraction is needed, before waiting for the extraction lock.
    fn begin(&self, total_bytes: u64);
    /// Uncompressed bytes written since the last call.
    fn advance(&self, bytes: u64);
    /// Called once when extraction is over or turned out to be unnecessary.
    fn finish(&self);
}

/// Progress sink that ignores everything.
pub struct NoProgress;

impl Progress for NoProgress {
    fn begin(&self, _total_bytes: u64) {}
    fn advance(&self, _bytes: u64) {}
    fn finish(&self) {}
}

// ---------------------------------------------------------------- root resolution

/// Inputs for [`resolve_root`], injected so tests need no process environment.
pub struct RootInputs {
    /// `METROLIZA_RUNTIME_ROOT`: explicit root for tests and qualification. When set it is the
    /// only candidate, so a misconfigured qualification fails loudly instead of falling back.
    pub override_root: Option<PathBuf>,
    /// `%LOCALAPPDATA%`.
    pub local_app_data: Option<PathBuf>,
    /// Directory containing the launcher EXE.
    pub exe_dir: PathBuf,
}

struct Candidate {
    root: PathBuf,
    /// Also reject a link/reparse point at the parent (directories this launcher creates).
    check_parent: bool,
}

fn root_candidates(inputs: &RootInputs) -> Vec<Candidate> {
    if let Some(root) = &inputs.override_root {
        return vec![Candidate {
            root: root.clone(),
            check_parent: false,
        }];
    }
    let mut out = Vec::new();
    if let Some(base) = &inputs.local_app_data {
        out.push(Candidate {
            root: base.join("Metroliza").join("runtime"),
            check_parent: true,
        });
    }
    out.push(Candidate {
        root: inputs.exe_dir.join("MetrolizaRuntime"),
        check_parent: false,
    });
    out
}

fn is_plain_directory(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|m| m.is_dir() && !is_link_or_reparse(&m))
}

/// Create the root if needed and prove it is a writable, non-redirected directory.
fn prepare_root(candidate: &Candidate) -> io::Result<()> {
    let redirected = || io::Error::other("runtime root is not a plain directory");
    // Vet the parent before creating anything below it, so nothing is written through a link.
    if candidate.check_parent {
        if let Some(parent) = candidate.root.parent() {
            fs::create_dir_all(parent)?;
            if !is_plain_directory(parent) {
                return Err(redirected());
            }
        }
    }
    fs::create_dir_all(&candidate.root)?;
    if !is_plain_directory(&candidate.root) {
        return Err(redirected());
    }
    let probe = candidate
        .root
        .join(format!(".probe-{}", std::process::id()));
    fs::write(&probe, b"probe")?;
    fs::remove_file(&probe)
}

/// First usable cache root: override, else `%LOCALAPPDATA%\Metroliza\runtime`, else
/// `MetrolizaRuntime` next to the EXE. Nothing here touches `%TEMP%`.
pub fn resolve_root(inputs: &RootInputs) -> Result<PathBuf> {
    let mut last = String::from("no candidate");
    for candidate in root_candidates(inputs) {
        match prepare_root(&candidate) {
            Ok(()) => return Ok(candidate.root),
            Err(e) => last = format!("{}: {e}", candidate.root.display()),
        }
    }
    Err(LauncherError::cache(format!(
        "no usable runtime root ({last})"
    )))
}

// ---------------------------------------------------------------- locks

fn open_lock_file(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
}

/// Exclusive lock serialising cold extractions and cleanup. Released when dropped or when the
/// process dies, so a killed extractor never leaves a stuck lock.
struct ExtractLock {
    _file: File,
}

impl ExtractLock {
    fn acquire(root: &Path) -> io::Result<Self> {
        let file = open_lock_file(&root.join(EXTRACT_LOCK))?;
        file.lock()?;
        Ok(Self { _file: file })
    }

    /// `Ok(None)` if somebody else holds the lock.
    fn try_acquire(root: &Path) -> io::Result<Option<Self>> {
        let file = open_lock_file(&root.join(EXTRACT_LOCK))?;
        match file.try_lock() {
            Ok(()) => Ok(Some(Self { _file: file })),
            Err(TryLockError::WouldBlock) => Ok(None),
            Err(TryLockError::Error(e)) => Err(e),
        }
    }
}

/// Shared lock held for as long as a version is in use; cleanup removes only unlocked versions.
pub struct UseGuard {
    _file: File,
}

impl UseGuard {
    fn acquire(root: &Path, dir_name: &str) -> io::Result<Self> {
        let file = open_lock_file(&root.join(format!("{dir_name}{USE_SUFFIX}")))?;
        file.lock_shared()?;
        Ok(Self { _file: file })
    }
}

// ---------------------------------------------------------------- warm check

fn marker_matches(dir: &Path, marker: &str, payload: &Payload) -> bool {
    fs::read_to_string(dir.join(marker)).is_ok_and(|text| text.trim() == payload.manifest_hash())
}

/// Completed marker matches; no pending marker; every file has its expected size. No hashing.
pub fn is_warm(dir: &Path, payload: &Payload) -> bool {
    // A pending marker takes precedence, including an interrupted promotion with both markers.
    if !matches!(fs::symlink_metadata(dir.join(PENDING_MARKER)), Err(e) if e.kind() == io::ErrorKind::NotFound)
        || !marker_matches(dir, MARKER, payload)
    {
        return false;
    }
    payload.manifest.files.iter().all(|entry| {
        fs::symlink_metadata(dir.join(&entry.path))
            .is_ok_and(|m| m.is_file() && !is_link_or_reparse(&m) && m.len() == entry.size)
    })
}

// ---------------------------------------------------------------- extraction

/// Tuning knobs for extraction.
pub struct Options {
    /// Worker threads decoding and writing files (bounded).
    pub threads: usize,
    /// Flush each file during extraction (opt-in only). The default first launch writes a
    /// durable pending marker without per-file flushes. The next launch hashes AND flushes
    /// every file before completing the cache; verification alone could read dirty OS pages.
    /// `METROLIZA_LAUNCHER_SYNC_FILES=1` also flushes files during the first launch.
    pub sync_files: bool,
}

impl Default for Options {
    fn default() -> Self {
        let cpus = thread::available_parallelism().map_or(2, |n| n.get());
        Self {
            threads: cpus.clamp(2, 8),
            sync_files: std::env::var_os("METROLIZA_LAUNCHER_SYNC_FILES").is_some_and(|v| v == "1"),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// Existing cache was valid; nothing was written.
    Warm,
    /// A pending cache passed full SHA-256 verification and was made durable.
    Verified,
    /// No cache for this version existed; extracted.
    Cold,
    /// A cache directory existed but was invalid (corrupt, partial, other payload); re-extracted.
    Repaired,
}

impl Outcome {
    pub fn as_str(self) -> &'static str {
        match self {
            Outcome::Warm => "warm",
            Outcome::Verified => "verified",
            Outcome::Cold => "cold",
            Outcome::Repaired => "repair",
        }
    }
}

/// A validated runtime directory, kept "in use" while this value lives.
pub struct Runtime {
    pub dir: PathBuf,
    pub outcome: Outcome,
    pub dir_name: String,
    _use_guard: UseGuard,
}

fn extract_one(
    payload: &Payload,
    staging: &Path,
    entry: &FileEntry,
    progress: &dyn Progress,
    sync: bool,
) -> Result<()> {
    let fail = |e: io::Error| LauncherError::extraction(format!("{}: {e}", entry.path));
    let destination = staging.join(&entry.path);
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(fail)?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&destination)
        .map_err(fail)?;
    let blob = payload.blob_reader(entry).map_err(fail)?;
    decode_file(blob, &mut file, entry, &mut |bytes| progress.advance(bytes))?;
    if sync {
        file.sync_all().map_err(fail)?;
    }
    Ok(())
}

/// Decode and verify all files into `staging` (which must not exist yet).
fn extract_all(
    payload: &Payload,
    staging: &Path,
    progress: &dyn Progress,
    options: &Options,
) -> Result<()> {
    fs::create_dir(staging)
        .map_err(|e| LauncherError::extraction(format!("create staging: {e}")))?;

    process_files(payload, options, &|entry| {
        extract_one(payload, staging, entry, progress, options.sync_files)
    })
}

/// Bounded workers shared by extraction and second-launch verification. Largest files first.
fn process_files(
    payload: &Payload,
    options: &Options,
    process: &(dyn Fn(&FileEntry) -> Result<()> + Sync),
) -> Result<()> {
    // Largest files first so the long poles start early.
    let mut order: Vec<&FileEntry> = payload.manifest.files.iter().collect();
    order.sort_by(|a, b| b.size.cmp(&a.size).then_with(|| a.path.cmp(&b.path)));

    let next = AtomicUsize::new(0);
    let failed = AtomicBool::new(false);
    let first_error: Mutex<Option<LauncherError>> = Mutex::new(None);
    let workers = options.threads.clamp(1, order.len().max(1));

    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let index = next.fetch_add(1, Ordering::Relaxed);
                if index >= order.len() || failed.load(Ordering::Relaxed) {
                    return;
                }
                if let Err(e) = process(order[index]) {
                    failed.store(true, Ordering::Relaxed);
                    first_error
                        .lock()
                        .unwrap_or_else(|p| p.into_inner())
                        .get_or_insert(e);
                    return;
                }
            });
        }
    });

    match first_error.into_inner().unwrap_or_else(|p| p.into_inner()) {
        Some(e) => Err(e),
        None => Ok(()),
    }
}

/// Verify and flush a pending file before trusting it. Write access is needed for
/// FlushFileBuffers on Windows. Memory stays bounded to 1 MiB per worker.
fn verify_and_flush(dir: &Path, entry: &FileEntry) -> Result<()> {
    let fail = |e: io::Error| LauncherError::cache(format!("verify {}: {e}", entry.path));
    let path = dir.join(&entry.path);
    let meta = fs::symlink_metadata(&path).map_err(fail)?;
    if !meta.is_file() || is_link_or_reparse(&meta) || meta.len() != entry.size {
        return Err(LauncherError::cache("pending file metadata mismatch"));
    }
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .map_err(fail)?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0; 1024 * 1024];
    let mut remaining = entry.size;
    while remaining > 0 {
        let limit = remaining.min(buffer.len() as u64) as usize;
        let read = file.read(&mut buffer[..limit]).map_err(fail)?;
        if read == 0 {
            return Err(LauncherError::cache("pending file truncated"));
        }
        digest.update(&buffer[..read]);
        remaining -= read as u64;
    }
    if crate::to_hex(&digest.finalize()) != entry.sha256
        || file.metadata().map_err(fail)?.len() != entry.size
    {
        return Err(LauncherError::cache("pending file SHA-256 mismatch"));
    }
    file.sync_all().map_err(fail)
}

/// Persist directory entries too on Unix. Windows uses the flushed file handles above.
fn sync_payload_dirs(dir: &Path, payload: &Payload) -> io::Result<()> {
    let mut dirs = std::collections::BTreeSet::new();
    for entry in &payload.manifest.files {
        let path = dir.join(&entry.path);
        for parent in path.ancestors().skip(1) {
            dirs.insert(parent.to_path_buf());
            if parent == dir {
                break;
            }
        }
    }
    for path in dirs.iter().rev() {
        sync_dir(path)?;
    }
    sync_dir(dir.parent().unwrap_or(dir))
}

fn write_marker(dir: &Path, marker: &str, payload: &Payload) -> Result<()> {
    // Flush through the writing handle: Windows refuses FlushFileBuffers on read-only handles.
    OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(dir.join(marker))
        .and_then(|mut file| {
            io::Write::write_all(
                &mut file,
                format!("{}\n", payload.manifest_hash()).as_bytes(),
            )?;
            file.sync_all()?;
            sync_dir(dir)
        })
        .map_err(|e| LauncherError::extraction(format!("marker: {e}")))
}

fn promote_pending(dir: &Path, payload: &Payload, options: &Options) -> Result<bool> {
    if !marker_matches(dir, PENDING_MARKER, payload) {
        return Ok(false);
    }
    if process_files(payload, options, &|entry| verify_and_flush(dir, entry)).is_err() {
        return Ok(false);
    }
    sync_payload_dirs(dir, payload)
        .map_err(|e| LauncherError::cache(format!("persist pending directories: {e}")))?;
    // Keep pending until complete is durable. If interrupted with both markers, verify again.
    write_marker(dir, MARKER, payload)?;
    fs::remove_file(dir.join(PENDING_MARKER))
        .and_then(|()| sync_dir(dir))
        .map_err(|e| LauncherError::cache(format!("promote pending: {e}")))?;
    Ok(true)
}

/// Remove a directory tree, retrying briefly: on Windows a scanner may hold a file open for a
/// moment after it was written or deleted.
fn remove_tree(path: &Path) -> io::Result<()> {
    let mut last = Ok(());
    for attempt in 0..5 {
        match fs::remove_dir_all(path) {
            Ok(()) => return Ok(()),
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(()),
            Err(e) => last = Err(e),
        }
        thread::sleep(Duration::from_millis(100 * (attempt + 1)));
    }
    last
}

fn rename_with_retry(from: &Path, to: &Path) -> io::Result<()> {
    let mut last = Ok(());
    for attempt in 0..10 {
        match fs::rename(from, to) {
            Ok(()) => return Ok(()),
            Err(e) => last = Err(e),
        }
        thread::sleep(Duration::from_millis(100 * (attempt + 1)));
    }
    last
}

#[cfg(unix)]
fn sync_dir(dir: &Path) -> io::Result<()> {
    File::open(dir)?.sync_all()
}

#[cfg(not(unix))]
fn sync_dir(_dir: &Path) -> io::Result<()> {
    Ok(())
}

fn is_hex8(s: &str) -> bool {
    s.len() == 8
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// True for names of the form `<version>_<sha8>`: the only directories this module may delete.
fn is_version_dir_name(name: &str) -> bool {
    name.len() > 9
        && name.is_char_boundary(name.len() - 9)
        && name.as_bytes()[name.len() - 9] == b'_'
        && is_hex8(&name[name.len() - 8..])
        && validate_version(&name[..name.len() - 9]).is_ok()
}

fn is_staging_name(name: &str) -> bool {
    name.split_once(STAGING_INFIX).is_some_and(|(base, pid)| {
        is_version_dir_name(base) && !pid.is_empty() && pid.bytes().all(|b| b.is_ascii_digit())
    })
}

/// Delete staging directories of earlier, interrupted extractions. Callers hold the extraction
/// lock, which is the only way a staging directory can legitimately exist.
fn remove_stale_staging(root: &Path) {
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        if name.to_str().is_some_and(is_staging_name) {
            let _ = remove_tree(&entry.path());
        }
    }
}

/// Make sure a valid runtime for `payload` exists below `root` and return it, extracting if
/// necessary. See the module documentation for the state machine.
pub fn ensure_runtime(
    root: &Path,
    payload: &Payload,
    progress: &dyn Progress,
    options: &Options,
) -> Result<Runtime> {
    let dir_name = payload.manifest.dir_name();
    let dir = root.join(&dir_name);
    let use_guard = UseGuard::acquire(root, &dir_name)
        .map_err(|e| LauncherError::cache(format!("use lock: {e}")))?;

    if is_warm(&dir, payload) {
        return Ok(Runtime {
            dir,
            outcome: Outcome::Warm,
            dir_name,
            _use_guard: use_guard,
        });
    }

    progress.begin(payload.manifest.total_size());
    let result = extract_locked(root, &dir, &dir_name, payload, progress, options);
    progress.finish();
    let outcome = result?;
    Ok(Runtime {
        dir,
        outcome,
        dir_name,
        _use_guard: use_guard,
    })
}

/// Declare `runtime` invalid and rebuild it: the entry reported that it cannot trust its own
/// files even though the cheap warm check passed (for example a same-size modification).
///
/// The marker is removed first, so from then on the directory can never look valid, and the
/// normal repair path re-extracts and re-verifies every file. The old handle is released before
/// the rebuild; the per-version single-instance guard held by the caller keeps other launchers
/// of this version out meanwhile.
pub fn repair_runtime(
    root: &Path,
    payload: &Payload,
    runtime: Runtime,
    progress: &dyn Progress,
    options: &Options,
) -> Result<Runtime> {
    let dir = runtime.dir.clone();
    if crate::platform::runtime_in_use(&dir)
        .map_err(|e| LauncherError::cache(format!("runtime resource query: {e}")))?
    {
        return Err(LauncherError::cache("cannot repair a runtime still in use"));
    }
    drop(runtime);
    for marker in [MARKER, PENDING_MARKER] {
        if fs::remove_file(dir.join(marker)).is_err() && marker_matches(&dir, marker, payload) {
            remove_tree(&dir)
                .map_err(|e| LauncherError::cache(format!("invalidate runtime: {e}")))?;
        }
    }
    ensure_runtime(root, payload, progress, options)
}

fn extract_locked(
    root: &Path,
    dir: &Path,
    dir_name: &str,
    payload: &Payload,
    progress: &dyn Progress,
    options: &Options,
) -> Result<Outcome> {
    let _lock = ExtractLock::acquire(root)
        .map_err(|e| LauncherError::cache(format!("extraction lock: {e}")))?;

    // Another process may have completed the extraction while we waited.
    if is_warm(dir, payload) {
        return Ok(Outcome::Warm);
    }

    if promote_pending(dir, payload, options)? {
        return Ok(Outcome::Verified);
    }

    remove_stale_staging(root);
    let existed = fs::symlink_metadata(dir).is_ok();
    if existed {
        if crate::platform::runtime_in_use(dir)
            .map_err(|e| LauncherError::cache(format!("runtime resource query: {e}")))?
        {
            return Err(LauncherError::cache(
                "cannot replace a runtime still in use",
            ));
        }
        // Remove the marker first so a half-deleted directory can never look valid.
        let _ = fs::remove_file(dir.join(MARKER));
        let _ = fs::remove_file(dir.join(PENDING_MARKER));
        remove_tree(dir).map_err(|e| LauncherError::cache(format!("remove invalid cache: {e}")))?;
    }

    let staging = root.join(format!("{dir_name}{STAGING_INFIX}{}", std::process::id()));
    if let Err(e) = extract_all(payload, &staging, progress, options) {
        let _ = remove_tree(&staging);
        return Err(e);
    }
    if let Err(e) = rename_with_retry(&staging, dir) {
        let _ = remove_tree(&staging);
        return Err(LauncherError::extraction(format!("commit: {e}")));
    }
    sync_dir(root).map_err(|e| LauncherError::extraction(format!("persist runtime: {e}")))?;

    // Only pending is committed on first launch. Its durable presence requires a full
    // integrity/durability pass on the next launch, even if the entry cannot start at all.
    write_marker(dir, PENDING_MARKER, payload)?;
    Ok(if existed {
        Outcome::Repaired
    } else {
        Outcome::Cold
    })
}

// ---------------------------------------------------------------- cleanup

/// What a cleanup pass did; informational only.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct CleanupReport {
    pub removed: Vec<String>,
    pub skipped_in_use: Vec<String>,
    pub failed: Vec<String>,
    /// Another process was extracting, so nothing was touched.
    pub busy: bool,
}

/// Remove one version directory if nobody uses it. Returns `Ok(true)` if removed.
fn remove_version_dir(root: &Path, name: &str) -> io::Result<bool> {
    let use_path = root.join(format!("{name}{USE_SUFFIX}"));
    let lock = open_lock_file(&use_path)?;
    match lock.try_lock() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => return Ok(false),
        Err(TryLockError::Error(e)) => return Err(e),
    }
    let dir = root.join(name);
    // The supervisor/launcher can die before the application. Consult the OS while holding
    // the exclusive lease, before removing even the marker. A failed query preserves the tree.
    if crate::platform::runtime_in_use(&dir)? {
        return Ok(false);
    }
    let _ = fs::remove_file(dir.join(MARKER));
    let removed = remove_tree(&dir);
    drop(lock);
    let _ = fs::remove_file(&use_path);
    removed.map(|()| true)
}

/// Keep `current` and the most recently completed other version; remove everything else this
/// module created. Best effort: errors are reported, never raised, and versions that are in use
/// (or locked by a process we cannot see) are left alone.
pub fn cleanup_old_versions(root: &Path, current: &str) -> CleanupReport {
    let mut report = CleanupReport::default();
    let Ok(Some(_lock)) = ExtractLock::try_acquire(root) else {
        report.busy = true;
        return report;
    };
    remove_stale_staging(root);
    let Ok(entries) = fs::read_dir(root) else {
        return report;
    };

    let mut other_versions: Vec<(Option<SystemTime>, String)> = Vec::new();
    let mut use_files: Vec<String> = Vec::new();
    for entry in entries.flatten() {
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if let Some(stem) = name.strip_suffix(USE_SUFFIX) {
            if is_version_dir_name(stem) {
                use_files.push(stem.to_owned());
            }
        } else if name != current && is_version_dir_name(&name) && is_plain_directory(&entry.path())
        {
            let completed = fs::metadata(entry.path().join(MARKER))
                .or_else(|_| fs::metadata(entry.path().join(PENDING_MARKER)))
                .and_then(|m| m.modified())
                .ok();
            other_versions.push((completed, name));
        }
    }

    // Newest completion first; directories without a marker (never completed) sort last.
    other_versions.sort_by(|a, b| b.cmp(a));
    let mut keep_previous = true;
    for (completed, name) in &other_versions {
        if completed.is_some() && keep_previous {
            keep_previous = false;
            continue;
        }
        match remove_version_dir(root, name) {
            Ok(true) => report.removed.push(name.clone()),
            Ok(false) => report.skipped_in_use.push(name.clone()),
            Err(_) => report.failed.push(name.clone()),
        }
    }

    // Lock files whose directory is gone (and whose version is not running) are litter.
    for stem in use_files {
        if stem != current && !root.join(&stem).exists() {
            if let Ok(lock) = open_lock_file(&root.join(format!("{stem}{USE_SUFFIX}"))) {
                if lock.try_lock().is_ok() {
                    drop(lock);
                    let _ = fs::remove_file(root.join(format!("{stem}{USE_SUFFIX}")));
                }
            }
        }
    }
    report
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pack::{pack, PackOptions};
    use std::sync::atomic::AtomicU64;

    /// Build a packed payload from `(path, content)` files and open it.
    pub(crate) fn make_payload(
        tmp: &Path,
        version: &str,
        sha: &str,
        files: &[(&str, Vec<u8>)],
    ) -> Payload {
        let input = tmp.join(format!("in-{version}-{sha}"));
        for (rel, data) in files {
            let path = input.join(rel);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, data).unwrap();
        }
        fs::write(tmp.join("stub.bin"), b"stub").unwrap();
        let output = tmp.join(format!("{version}-{sha}.exe"));
        pack(&PackOptions {
            input_dir: input,
            entry: files[0].0.into(),
            version: version.into(),
            content_key: false,
            git_sha: sha.into(),
            stub: tmp.join("stub.bin"),
            output: output.clone(),
        })
        .unwrap();
        Payload::open(&output).unwrap()
    }

    fn sample_files() -> Vec<(&'static str, Vec<u8>)> {
        vec![
            ("app.exe", b"entry binary".to_vec()),
            ("lib/a.dll", vec![1u8; 70_000]),
            (
                "lib/deep/b.bin",
                (0..200_000u32).map(|i| (i * 31 % 253) as u8).collect(),
            ),
            ("empty.txt", Vec::new()),
        ]
    }

    fn quick() -> Options {
        Options {
            threads: 3,
            sync_files: false,
        }
    }

    #[derive(Default)]
    struct Counting {
        begins: AtomicU64,
        bytes: AtomicU64,
    }

    impl Progress for Counting {
        fn begin(&self, _total: u64) {
            self.begins.fetch_add(1, Ordering::SeqCst);
        }
        fn advance(&self, bytes: u64) {
            self.bytes.fetch_add(bytes, Ordering::SeqCst);
        }
        fn finish(&self) {}
    }

    #[test]
    fn first_launch_leaves_pending_and_second_checks_same_size_corruption() {
        for victim in ["app.exe", "lib/deep/b.bin"] {
            let tmp = tempfile::tempdir().unwrap();
            let root = tmp.path().join("root");
            fs::create_dir(&root).unwrap();
            let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());
            let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
            let dir = runtime.dir.clone();
            drop(runtime);
            let expected = fs::read(dir.join(victim)).unwrap();
            fs::write(dir.join(victim), vec![0; expected.len()]).unwrap();
            let repaired = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
            assert_eq!(repaired.outcome, Outcome::Repaired, "same-size {victim}");
            assert_eq!(fs::read(dir.join(victim)).unwrap(), expected);
        }
    }

    #[test]
    fn cold_cache_is_pending_until_the_next_launch() {
        let tmp = tempfile::tempdir().unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());
        let runtime = ensure_runtime(tmp.path(), &payload, &NoProgress, &quick()).unwrap();
        assert!(runtime.dir.join(".pending").is_file());
        assert!(!runtime.dir.join(MARKER).exists());
        assert!(!is_warm(&runtime.dir, &payload));
    }

    #[test]
    fn interrupted_promotion_cannot_hide_pending_corruption() {
        let tmp = tempfile::tempdir().unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());
        let runtime = ensure_runtime(tmp.path(), &payload, &NoProgress, &quick()).unwrap();
        let dir = runtime.dir.clone();
        drop(runtime);
        write_marker(&dir, MARKER, &payload).unwrap(); // complete written, pending not removed
        fs::write(dir.join("empty.txt"), b"corrupt").unwrap();
        assert!(!is_warm(&dir, &payload));
        assert_eq!(
            ensure_runtime(tmp.path(), &payload, &NoProgress, &quick())
                .unwrap()
                .outcome,
            Outcome::Repaired
        );
        assert!(!dir.join(MARKER).exists());
        assert!(dir.join(PENDING_MARKER).exists());
        assert!(fs::read(dir.join("empty.txt")).unwrap().is_empty());
    }

    #[test]
    fn foreign_pending_marker_requires_reextraction() {
        let tmp = tempfile::tempdir().unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());
        let runtime = ensure_runtime(tmp.path(), &payload, &NoProgress, &quick()).unwrap();
        fs::write(runtime.dir.join(PENDING_MARKER), b"wrong payload").unwrap();
        drop(runtime);
        assert_eq!(
            ensure_runtime(tmp.path(), &payload, &NoProgress, &quick())
                .unwrap()
                .outcome,
            Outcome::Repaired
        );
    }

    #[test]
    fn cold_then_warm_does_not_extract_again() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());

        let progress = Counting::default();
        let first = ensure_runtime(&root, &payload, &progress, &quick()).unwrap();
        assert_eq!(first.outcome, Outcome::Cold);
        assert_eq!(first.dir, root.join("1.0_aaaaaaaa"));
        assert_eq!(
            progress.bytes.load(Ordering::SeqCst),
            payload.manifest.total_size()
        );
        assert_eq!(
            fs::read(first.dir.join("lib/a.dll")).unwrap(),
            vec![1u8; 70_000]
        );
        assert_eq!(
            fs::read_to_string(first.dir.join(PENDING_MARKER))
                .unwrap()
                .trim(),
            payload.manifest_hash()
        );
        let original = fs::metadata(first.dir.join("lib/a.dll"))
            .unwrap()
            .modified()
            .unwrap();
        drop(first);
        let verified = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
        assert_eq!(verified.outcome, Outcome::Verified);
        assert!(!verified.dir.join(PENDING_MARKER).exists());
        assert_eq!(
            fs::metadata(verified.dir.join("lib/a.dll"))
                .unwrap()
                .modified()
                .unwrap(),
            original
        );
        drop(verified);

        let marker = root.join("1.0_aaaaaaaa").join(MARKER);
        let before = fs::metadata(&marker).unwrap().modified().unwrap();
        let progress = Counting::default();
        let second = ensure_runtime(&root, &payload, &progress, &quick()).unwrap();
        assert_eq!(second.outcome, Outcome::Warm);
        assert_eq!(
            progress.begins.load(Ordering::SeqCst),
            0,
            "warm start must not show progress"
        );
        assert_eq!(progress.bytes.load(Ordering::SeqCst), 0);
        assert_eq!(fs::metadata(&marker).unwrap().modified().unwrap(), before);
    }

    #[test]
    fn corrupt_partial_or_foreign_caches_are_repaired() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());
        let dir = root.join("1.0_aaaaaaaa");
        drop(ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap());
        drop(ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap());

        type Damage = Box<dyn Fn(&Path)>;
        let damages: Vec<(&str, Damage)> = vec![
            (
                "deleted file",
                Box::new(|d| fs::remove_file(d.join("lib/a.dll")).unwrap()),
            ),
            (
                "truncated file",
                Box::new(|d| fs::write(d.join("lib/a.dll"), b"short").unwrap()),
            ),
            (
                "missing marker",
                Box::new(|d| fs::remove_file(d.join(MARKER)).unwrap()),
            ),
            (
                "foreign marker",
                Box::new(|d| fs::write(d.join(MARKER), "deadbeef\n").unwrap()),
            ),
            (
                "file replaced by dir",
                Box::new(|d| {
                    fs::remove_file(d.join("app.exe")).unwrap();
                    fs::create_dir(d.join("app.exe")).unwrap();
                }),
            ),
        ];
        for (label, damage) in damages {
            damage(&dir);
            assert!(!is_warm(&dir, &payload), "{label}: must not look warm");
            let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
            assert_eq!(runtime.outcome, Outcome::Repaired, "{label}");
            assert!(!is_warm(&dir, &payload), "{label}: repair remains pending");
            assert_eq!(
                ensure_runtime(&root, &payload, &NoProgress, &quick())
                    .unwrap()
                    .outcome,
                Outcome::Verified
            );
            assert!(is_warm(&dir, &payload), "{label}: repaired and verified");
            assert_eq!(
                fs::read(dir.join("lib/a.dll")).unwrap(),
                vec![1u8; 70_000],
                "{label}"
            );
        }
    }

    #[test]
    fn interrupted_extraction_leaves_nothing_usable_and_is_cleaned_up() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());

        // What a killed extractor leaves behind: a staging dir and (worst case) a renamed dir
        // without marker.
        let stale = root.join("1.0_aaaaaaaa.staging-4242");
        fs::create_dir_all(stale.join("lib")).unwrap();
        fs::write(stale.join("lib/a.dll"), b"partial").unwrap();
        let dir = root.join("1.0_aaaaaaaa");
        fs::create_dir_all(dir.join("lib")).unwrap();
        fs::write(dir.join("app.exe"), b"entry binary").unwrap();
        assert!(!is_warm(&dir, &payload));

        let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
        assert_eq!(runtime.outcome, Outcome::Repaired);
        assert!(!stale.exists(), "stale staging removed");
        assert!(dir.join(PENDING_MARKER).is_file());
        assert_eq!(
            ensure_runtime(&root, &payload, &NoProgress, &quick())
                .unwrap()
                .outcome,
            Outcome::Verified
        );
        assert!(is_warm(&dir, &payload));
    }

    #[test]
    fn tampered_blob_fails_extraction_and_leaves_no_runtime() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());

        let mut bytes = fs::read(&payload.path).unwrap();
        let entry = payload
            .manifest
            .files
            .iter()
            .find(|f| f.path == "lib/deep/b.bin")
            .unwrap();
        let at =
            (payload.trailer.payload_offset + entry.offset + entry.compressed_size / 2) as usize;
        bytes[at] ^= 0xFF;
        fs::write(&payload.path, bytes).unwrap();

        let err = ensure_runtime(&root, &payload, &NoProgress, &quick())
            .err()
            .expect("must fail");
        assert_eq!(err.kind, crate::error::ErrorKind::ExtractionFailed);
        assert!(!root.join("1.0_aaaaaaaa").exists());
        let leftovers: Vec<_> = fs::read_dir(&root)
            .unwrap()
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.contains("staging"))
            .collect();
        assert!(leftovers.is_empty(), "{leftovers:?}");
    }

    #[test]
    fn concurrent_cold_starts_extract_exactly_once() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let payload = make_payload(tmp.path(), "1.0", "aaaaaaaa", &sample_files());
        let progress = Counting::default();

        let outcomes: Vec<Outcome> = thread::scope(|scope| {
            let handles: Vec<_> = (0..4)
                .map(|_| {
                    scope.spawn(|| {
                        ensure_runtime(&root, &payload, &progress, &quick())
                            .unwrap()
                            .outcome
                    })
                })
                .collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });
        assert_eq!(
            outcomes.iter().filter(|o| **o == Outcome::Cold).count(),
            1,
            "{outcomes:?}"
        );
        assert_eq!(
            outcomes.iter().filter(|o| **o == Outcome::Warm).count(),
            2,
            "{outcomes:?}"
        );
        assert_eq!(
            outcomes.iter().filter(|o| **o == Outcome::Verified).count(),
            1
        );
        assert_eq!(
            progress.bytes.load(Ordering::SeqCst),
            payload.manifest.total_size()
        );
    }

    #[test]
    fn extraction_lock_excludes_second_holder() {
        let tmp = tempfile::tempdir().unwrap();
        let held = ExtractLock::acquire(tmp.path()).unwrap();
        assert!(ExtractLock::try_acquire(tmp.path()).unwrap().is_none());
        drop(held);
        assert!(ExtractLock::try_acquire(tmp.path()).unwrap().is_some());
    }

    fn install(tmp: &Path, root: &Path, version: &str, sha: &str, age_secs: u64) -> String {
        let payload = make_payload(tmp, version, sha, &sample_files());
        drop(ensure_runtime(root, &payload, &NoProgress, &quick()).unwrap());
        let runtime = ensure_runtime(root, &payload, &NoProgress, &quick()).unwrap();
        // Make completion order independent of filesystem timestamp resolution.
        let marker = OpenOptions::new()
            .write(true)
            .open(runtime.dir.join(MARKER))
            .unwrap();
        marker
            .set_modified(SystemTime::now() - Duration::from_secs(age_secs))
            .unwrap();
        runtime.dir_name.clone()
    }

    #[test]
    fn cleanup_keeps_current_and_previous_only() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let v1 = install(tmp.path(), &root, "1.0", "11111111", 300);
        let v2 = install(tmp.path(), &root, "2.0", "22222222", 200);
        let v3 = install(tmp.path(), &root, "3.0", "33333333", 100);
        // Unrelated content in the root must never be touched.
        fs::create_dir(root.join("not-a-version")).unwrap();
        fs::write(root.join("notes.txt"), b"keep").unwrap();

        let report = cleanup_old_versions(&root, &v3);
        assert_eq!(report.removed, vec![v1.clone()]);
        assert!(root.join(&v3).exists() && root.join(&v2).exists() && !root.join(&v1).exists());
        assert!(!root.join(format!("{v1}.use")).exists());
        assert!(root.join("not-a-version").exists() && root.join("notes.txt").exists());

        // Idempotent.
        assert_eq!(cleanup_old_versions(&root, &v3), CleanupReport::default());
    }

    #[test]
    fn cleanup_keeps_previous_even_when_current_is_an_older_version() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let v1 = install(tmp.path(), &root, "1.0", "11111111", 300);
        let v2 = install(tmp.path(), &root, "2.0", "22222222", 200);
        let v3 = install(tmp.path(), &root, "3.0", "33333333", 100);
        // Downgrade run of v1: v3 is the most recently completed other version.
        let report = cleanup_old_versions(&root, &v1);
        assert_eq!(report.removed, vec![v2.clone()]);
        assert!(root.join(&v1).exists() && root.join(&v3).exists());
    }

    #[test]
    fn cleanup_skips_versions_in_use_and_removes_incomplete_dirs() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir(&root).unwrap();
        let v1 = install(tmp.path(), &root, "1.0", "11111111", 300);
        let v2 = install(tmp.path(), &root, "2.0", "22222222", 200);
        let v3 = install(tmp.path(), &root, "3.0", "33333333", 100);
        let broken = "0.5_44444444";
        fs::create_dir_all(root.join(broken).join("x")).unwrap();

        // v1 is "running": hold its use lock the way a launcher would.
        let running = UseGuard::acquire(&root, &v1).unwrap();
        let report = cleanup_old_versions(&root, &v3);
        assert_eq!(report.skipped_in_use, vec![v1.clone()]);
        assert_eq!(report.removed, vec![broken.to_string()]);
        assert!(
            root.join(&v1).join("lib/a.dll").exists(),
            "in-use version stays intact"
        );
        assert!(root.join(&v2).exists());

        drop(running);
        let report = cleanup_old_versions(&root, &v3);
        assert_eq!(report.removed, vec![v1.clone()]);
    }

    #[test]
    fn cleanup_yields_to_a_running_extraction() {
        let tmp = tempfile::tempdir().unwrap();
        let v1 = install(tmp.path(), tmp.path(), "1.0", "11111111", 300);
        let _held = ExtractLock::acquire(tmp.path()).unwrap();
        let report = cleanup_old_versions(tmp.path(), "9.0_99999999");
        assert!(report.busy);
        assert!(tmp.path().join(v1).exists());
    }

    #[test]
    fn name_patterns_are_strict() {
        assert!(is_version_dir_name("2026.09rc1_260927_0123abcd"));
        assert!(!is_version_dir_name("1.0_0123ABCD"));
        assert!(!is_version_dir_name("1.0_0123abc"));
        assert!(!is_version_dir_name("_0123abcd"));
        assert!(!is_version_dir_name("a b_0123abcd"));
        assert!(is_staging_name("1.0_0123abcd.staging-77"));
        assert!(!is_staging_name("1.0_0123abcd.staging-"));
        assert!(!is_staging_name("1.0_0123abcd.staging-7x"));
        assert!(!is_staging_name("random.staging-7"));
    }

    fn inputs(tmp: &Path) -> RootInputs {
        RootInputs {
            override_root: None,
            local_app_data: Some(tmp.join("LocalAppData")),
            exe_dir: tmp.join("exe"),
        }
    }

    #[test]
    fn root_prefers_local_app_data_and_creates_it() {
        let tmp = tempfile::tempdir().unwrap();
        fs::create_dir_all(tmp.path().join("LocalAppData")).unwrap();
        let root = resolve_root(&inputs(tmp.path())).unwrap();
        assert_eq!(root, tmp.path().join("LocalAppData/Metroliza/runtime"));
        assert!(root.is_dir());
    }

    #[test]
    fn root_override_is_authoritative() {
        let tmp = tempfile::tempdir().unwrap();
        let mut input = inputs(tmp.path());
        input.override_root = Some(tmp.path().join("qual"));
        assert_eq!(resolve_root(&input).unwrap(), tmp.path().join("qual"));

        // An unusable override must not silently fall back to another location.
        fs::write(tmp.path().join("file"), b"x").unwrap();
        input.override_root = Some(tmp.path().join("file/sub"));
        assert!(resolve_root(&input).is_err());
        assert!(!tmp.path().join("exe").exists());
    }

    #[test]
    fn root_falls_back_next_to_the_exe_when_local_app_data_is_unusable() {
        let tmp = tempfile::tempdir().unwrap();
        fs::create_dir_all(tmp.path().join("exe")).unwrap();
        // LOCALAPPDATA points below a regular file: cannot be created.
        fs::write(tmp.path().join("blocked"), b"x").unwrap();
        let mut input = inputs(tmp.path());
        input.local_app_data = Some(tmp.path().join("blocked"));
        assert_eq!(
            resolve_root(&input).unwrap(),
            tmp.path().join("exe/MetrolizaRuntime")
        );

        input.local_app_data = None;
        assert_eq!(
            resolve_root(&input).unwrap(),
            tmp.path().join("exe/MetrolizaRuntime")
        );
    }

    #[cfg(unix)]
    #[test]
    fn root_rejects_redirected_directories_and_falls_back() {
        let tmp = tempfile::tempdir().unwrap();
        let lad = tmp.path().join("LocalAppData");
        let elsewhere = tmp.path().join("elsewhere");
        fs::create_dir_all(&lad).unwrap();
        fs::create_dir_all(&elsewhere).unwrap();
        std::os::unix::fs::symlink(&elsewhere, lad.join("Metroliza")).unwrap();
        fs::create_dir_all(tmp.path().join("exe")).unwrap();

        let root = resolve_root(&inputs(tmp.path())).unwrap();
        assert_eq!(root, tmp.path().join("exe/MetrolizaRuntime"));
        assert!(
            fs::read_dir(&elsewhere).unwrap().next().is_none(),
            "nothing written through the link"
        );
    }

    #[test]
    fn root_error_when_nothing_is_usable() {
        let tmp = tempfile::tempdir().unwrap();
        fs::write(tmp.path().join("blocked"), b"x").unwrap();
        let input = RootInputs {
            override_root: None,
            local_app_data: Some(tmp.path().join("blocked")),
            exe_dir: tmp.path().join("blocked/exe"),
        };
        let err = resolve_root(&input).unwrap_err();
        assert_eq!(err.kind, crate::error::ErrorKind::CacheUnavailable);
    }
}
