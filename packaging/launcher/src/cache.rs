//! Persistent, versioned runtime cache: root resolution, state machine, extraction, cleanup.
//!
//! Layout below the cache root:
//!
//! ```text
//! <root>/
//!   <version>_<sha8>/              unpacked onedir; valid only with a matching `.complete`
//!     .complete                    marker: hex manifest hash, written last
//!   <version>_<sha8>.staging-<pid> extraction in progress (never used, removed when stale)
//!   <version>_<sha8>.use           lock file: shared lock held while that version runs
//!   .extract.lock                  exclusive lock serialising cold extractions and cleanup
//! ```
//!
//! # State machine for one start
//!
//! 1. Take the shared `.use` lock of this version (a concurrent cleanup will skip it).
//! 2. **Warm**: marker equals the manifest hash and every manifest file exists with the expected
//!    size. No hashing, nothing is written. Done.
//! 3. Otherwise **cold** (no directory) or **repair** (directory present but invalid): show
//!    progress, take `.extract.lock` (waiting if another process extracts), re-check warm (the
//!    other process may have finished), remove stale staging directories (safe: they can only
//!    exist while someone holds the lock), remove the invalid directory, extract into
//!    `<dir>.staging-<pid>` with SHA-256 verification of every file, rename into place, and only
//!    then write the marker. A process killed at any point leaves either nothing usable (no
//!    marker) or a staging directory that the next run deletes.
//! 4. Cleanup (best effort, never fatal) keeps the current and the most recently completed other
//!    version and removes the rest, skipping any version whose `.use` lock is held.

use std::fs::{self, File, OpenOptions, TryLockError};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, SystemTime};

use crate::archive::{decode_file, Payload};
use crate::error::{LauncherError, Result};
use crate::fsutil::is_link_or_reparse;
use crate::manifest::{validate_version, FileEntry};

pub const MARKER: &str = ".complete";
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

/// Cheap validity check: marker matches the payload, every file exists with its expected size.
/// Deliberately size-only (no hashing); content was verified when the files were extracted.
pub fn is_warm(dir: &Path, payload: &Payload) -> bool {
    match fs::read_to_string(dir.join(MARKER)) {
        Ok(text) if text.trim() == payload.manifest_hash() => {}
        _ => return false,
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
    /// `fsync` every extracted file so a power loss cannot leave a marker next to unwritten data.
    pub sync_files: bool,
}

impl Default for Options {
    fn default() -> Self {
        let cpus = thread::available_parallelism().map_or(2, |n| n.get());
        Self {
            threads: cpus.clamp(2, 8),
            sync_files: true,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// Existing cache was valid; nothing was written.
    Warm,
    /// No cache for this version existed; extracted.
    Cold,
    /// A cache directory existed but was invalid (corrupt, partial, other payload); re-extracted.
    Repaired,
}

impl Outcome {
    pub fn as_str(self) -> &'static str {
        match self {
            Outcome::Warm => "warm",
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
                if let Err(e) =
                    extract_one(payload, staging, order[index], progress, options.sync_files)
                {
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
fn sync_dir(dir: &Path) {
    if let Ok(handle) = File::open(dir) {
        let _ = handle.sync_all();
    }
}

#[cfg(not(unix))]
fn sync_dir(_dir: &Path) {}

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

    remove_stale_staging(root);
    let existed = fs::symlink_metadata(dir).is_ok();
    if existed {
        // Remove the marker first so a half-deleted directory can never look valid.
        let _ = fs::remove_file(dir.join(MARKER));
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
    sync_dir(root);

    // The marker is the commit record: written (and flushed) only after everything else.
    let marker = dir.join(MARKER);
    // Flush through the writing handle: Windows refuses FlushFileBuffers on a read-only handle.
    OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(&marker)
        .and_then(|mut file| {
            io::Write::write_all(&mut file, format!("{}\n", payload.manifest_hash()).as_bytes())?;
            file.sync_all()
        })
        .map_err(|e| LauncherError::extraction(format!("marker: {e}")))?;
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
            fs::read_to_string(first.dir.join(MARKER)).unwrap().trim(),
            payload.manifest_hash()
        );
        drop(first);

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
            assert!(is_warm(&dir, &payload), "{label}: repaired");
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
            3,
            "{outcomes:?}"
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
