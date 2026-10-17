//! Launcher orchestration: the sequence a double-click goes through.
//!
//! 1. Read and validate the payload appended to this EXE.
//! 2. Take the per-version single-instance guard; a second instance only activates the first.
//! 3. Resolve the cache root and make sure a valid runtime exists (extracting if needed).
//! 4. Start the entry executable from the runtime, clean up old versions in the background,
//!    wait for the entry process and return its exit code.

use std::ffi::OsString;
use std::path::PathBuf;
use std::thread;

use crate::archive::Payload;
use crate::cache::{cleanup_old_versions, ensure_runtime, resolve_root, Options, RootInputs};
use crate::error::{LauncherError, Result};
use crate::log::Log;
use crate::platform::{self, Instance};

/// Environment variable overriding the cache root (qualification and tests).
pub const ROOT_ENV: &str = "METROLIZA_RUNTIME_ROOT";

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
    let runtime = ensure_runtime(&root, &payload, &progress, &Options::default())?;
    log.line(&format!("cache={}", runtime.outcome.as_str()));

    let entry = runtime.dir.join(&payload.manifest.entry);
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let child = platform::spawn_entry(&entry, &args, &runtime.dir)?;
    platform::publish_entry_pid(&instance, child.id());
    log.line("entry=started");

    // Housekeeping runs beside the application; it never affects the exit code.
    let current = runtime.dir_name.clone();
    let cleanup = thread::spawn(move || cleanup_old_versions(&root, &current));

    let code = child.wait()?;
    if let Ok(report) = cleanup.join() {
        log.line(&format!(
            "cleanup removed={} in_use={} failed={} busy={}",
            report.removed.len(),
            report.skipped_in_use.len(),
            report.failed.len(),
            report.busy
        ));
    }
    log.line(&format!("exit={code}"));
    // Windows exit codes are unsigned 32-bit; the process exit API takes the same bits as i32.
    Ok(code as i32)
}
