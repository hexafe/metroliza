//! Launcher orchestration: the sequence a double-click goes through.
//!
//! 1. Read and validate the payload appended to this EXE.
//! 2. Take the per-version single-instance guard; a second instance only activates the first.
//! 3. Resolve the cache root and make sure a valid runtime exists (extracting if needed).
//! 4. Start the entry executable from the runtime (with the launcher's own working directory,
//!    not the cache), clean up old versions in the background, wait for the entry process and
//!    return its exit code.
//! 5. Self-repair: the first start carries [`REPAIR_AVAILABLE_ENV`]. If the entry exits with
//!    [`REPAIR_EXIT_CODE`] it found its own package invalid and showed no notice; the launcher
//!    then re-extracts the runtime and starts the entry exactly once more, without the variable,
//!    and returns that run's exit code whatever it is. There is never a second repair.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::thread;

use crate::archive::Payload;
use crate::cache::{
    cleanup_old_versions, ensure_runtime, repair_runtime, resolve_root, Options, RootInputs,
};
use crate::error::{LauncherError, Result};
use crate::log::Log;
use crate::platform::{self, Instance};

/// Environment variable overriding the cache root (qualification and tests).
pub const ROOT_ENV: &str = "METROLIZA_RUNTIME_ROOT";

/// Set to `1` on the first start of the entry to tell it that this launcher can rebuild the
/// runtime. An entry that finds its package invalid then exits silently with
/// [`REPAIR_EXIT_CODE`] instead of showing a notice. Never set on the second start.
pub const REPAIR_AVAILABLE_ENV: &str = "METROLIZA_RUNTIME_REPAIR_AVAILABLE";

/// Exit code (`EX_TEMPFAIL`) by which the entry asks for one runtime repair and restart.
pub const REPAIR_EXIT_CODE: u32 = 75;

/// Run the launcher; returns the process exit code.
pub fn run() -> i32 {
    let log = Log::from_env();
    match launch(&log) {
        Ok(code) => code,
        Err(error) => {
            // Detail goes to the log only; the user sees a fixed text.
            log.line(&format!("error={error}"));
            platform::show_error(error.kind);
            error.kind.exit_code()
        }
    }
}

fn env_path(name: &str) -> Option<PathBuf> {
    std::env::var_os(name)
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
}

fn launch(log: &Log) -> Result<i32> {
    let exe =
        std::env::current_exe().map_err(|e| LauncherError::payload(format!("current exe: {e}")))?;
    let payload = Payload::open(&exe)?;
    let version = payload.manifest.version.clone();

    // Before any cache work: a second instance must never extract or start anything.
    let instance = match platform::acquire_instance(&version) {
        Instance::Existing => {
            log.line("instance=second");
            platform::activate_existing(&version);
            return Ok(0);
        }
        Instance::First(guard) => guard,
    };

    let inputs = RootInputs {
        override_root: env_path(ROOT_ENV),
        local_app_data: env_path("LOCALAPPDATA"),
        exe_dir: exe.parent().map(PathBuf::from).unwrap_or_default(),
    };
    let root = resolve_root(&inputs)?;

    let progress = platform::ProgressWindow::new();
    let mut runtime = ensure_runtime(&root, &payload, &progress, &Options::default())?;
    log.line(&format!("cache={}", runtime.outcome.as_str()));

    let entry = runtime.dir.join(&payload.manifest.entry);
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let child = start_entry(&entry, &args, true, &instance, log)?;

    // Housekeeping runs beside the application; it never affects the exit code. It is joined
    // before anything below changes the environment or touches the cache again.
    let current = runtime.dir_name.clone();
    let cleanup_root = root.clone();
    let cleanup = thread::spawn(move || cleanup_old_versions(&cleanup_root, &current));

    let mut code = child.wait()?;
    if let Ok(report) = cleanup.join() {
        log.line(&format!(
            "cleanup removed={} in_use={} failed={} busy={}",
            report.removed.len(),
            report.skipped_in_use.len(),
            report.failed.len(),
            report.busy
        ));
    }

    if code == REPAIR_EXIT_CODE {
        // The entry rejected its own files without telling the user. Rebuild once and retry
        // once; the second run is final, even if it asks for a repair again.
        log.line("repair=requested");
        runtime = repair_runtime(&root, &payload, runtime, &progress, &Options::default())?;
        log.line(&format!("cache={}", runtime.outcome.as_str()));
        let entry = runtime.dir.join(&payload.manifest.entry);
        code = start_entry(&entry, &args, false, &instance, log)?.wait()?;
    }

    log.line(&format!("exit={code}"));
    // Windows exit codes are unsigned 32-bit; the process exit API takes the same bits as i32.
    Ok(code as i32)
}

/// Start the entry and publish its process id for second-instance activation.
///
/// `repair_available` sets or removes [`REPAIR_AVAILABLE_ENV`] in this process just before the
/// spawn (the entry inherits the environment), so the first and the second start differ only in
/// that variable. No other thread of the launcher is running while it changes.
fn start_entry(
    entry: &Path,
    args: &[OsString],
    repair_available: bool,
    instance: &platform::InstanceGuard,
    log: &Log,
) -> Result<platform::Child> {
    if repair_available {
        std::env::set_var(REPAIR_AVAILABLE_ENV, "1");
    } else {
        std::env::remove_var(REPAIR_AVAILABLE_ENV);
    }
    // No explicit working directory: the entry runs where the user started the launcher, as the
    // portable envelope does. The runtime directory is a disposable cache, so nothing (a
    // relative export name, a file dialog's start folder) may default into it.
    let child = platform::spawn_entry(entry, args, None)?;
    platform::publish_entry_pid(instance, child.id());
    log.line("entry=started");
    Ok(child)
}
