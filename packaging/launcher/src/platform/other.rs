//! Non-Windows stand-in for the platform layer (development and tests only).

use std::ffi::OsString;
use std::path::Path;
use std::process::Command;

use super::Instance;
use crate::cache::Progress;
use crate::error::{ErrorKind, LauncherError, Result};
use crate::log::Log;

/// Environment variable carrying the splash window handle to the entry (Windows only).
pub const SPLASH_HWND_ENV: &str = "METROLIZA_LAUNCHER_SPLASH_HWND";
/// Window class of the Windows splash.
pub const SPLASH_CLASS: &str = "MetrolizaLauncherSplash";

/// Placeholder guard; there is no single-instance enforcement off Windows.
pub struct InstanceGuard;

pub fn acquire_instance(_version: &str) -> Instance {
    Instance::First(InstanceGuard)
}

pub fn activate_existing(_version: &str) {}

pub fn publish_entry_pid(_guard: &InstanceGuard, _pid: u32) {}

/// Writes the fixed text to stderr instead of showing a dialog.
pub fn show_error(kind: ErrorKind) {
    eprintln!("{}", kind.user_message());
}

/// No window off Windows; keeps the launcher flow identical for the development stand-in.
pub struct Splash;

impl Splash {
    pub fn show(log: &Log) -> Self {
        log.mark("splash_unavailable");
        Self
    }

    pub fn handle_for_entry(&self) -> Option<String> {
        None
    }

    pub fn status(&self, _main: &str) {}

    pub fn close(&self) {}
}

impl Progress for Splash {
    fn begin(&self, _total_bytes: u64) {}
    fn advance(&self, _bytes: u64) {}
    fn finish(&self) {}
}

pub struct Child(std::process::Child);

impl Child {
    pub fn id(&self) -> u32 {
        self.0.id()
    }

    /// Wait for exit; a process killed by a signal reports as 1.
    pub fn wait(mut self) -> Result<u32> {
        let status = self
            .0
            .wait()
            .map_err(|e| LauncherError::launch(format!("wait: {e}")))?;
        Ok(status.code().map_or(1, |c| c as u32))
    }
}

pub fn spawn_entry(exe: &Path, args: &[OsString], cwd: Option<&Path>) -> Result<Child> {
    // The payload does not record POSIX modes (the product is Windows-only); make the entry
    // runnable so the stand-in can be exercised on Linux.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(exe, std::fs::Permissions::from_mode(0o755));
    }
    let mut command = Command::new(exe);
    command.args(args);
    if let Some(dir) = cwd {
        command.current_dir(dir);
    }
    command
        .spawn()
        .map(Child)
        .map_err(|e| LauncherError::spawn(format!("spawn: {e}"), e.raw_os_error()))
}

/// Linux qualification stand-in: executable mappings survive their launcher and supervisor.
#[cfg(target_os = "linux")]
pub fn runtime_in_use(dir: &Path) -> std::io::Result<bool> {
    let dir = std::fs::canonicalize(dir)?;
    for process in std::fs::read_dir("/proc")? {
        let process = process?;
        if !process
            .file_name()
            .as_encoded_bytes()
            .iter()
            .all(u8::is_ascii_digit)
        {
            continue;
        }
        if std::fs::read_link(process.path().join("exe")).is_ok_and(|p| p.starts_with(&dir)) {
            return Ok(true);
        }
    }
    Ok(false)
}

/// No reliable resource-use probe is implemented on other development platforms.
#[cfg(not(target_os = "linux"))]
pub fn runtime_in_use(_dir: &Path) -> std::io::Result<bool> {
    Ok(true)
}
