//! Windows implementation of the platform layer (Win32 via `windows-sys`).
//!
//! Everything here is plain Win32 with fixed English texts. It has been compile-checked only on
//! Linux (`cargo check --target x86_64-pc-windows-gnu`); runtime behaviour is covered by the
//! Windows qualification job.

use std::ffi::OsString;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::ptr::{null, null_mut};
use std::sync::Mutex;

use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, FALSE, HANDLE, HWND, INVALID_HANDLE_VALUE,
    LPARAM, TRUE, WAIT_OBJECT_0,
};
use windows_sys::Win32::System::Memory::{
    CreateFileMappingW, MapViewOfFile, OpenFileMappingW, UnmapViewOfFile, FILE_MAP_READ,
    FILE_MAP_WRITE, PAGE_READWRITE,
};
use windows_sys::Win32::System::Threading::{
    CreateMutexW, CreateProcessW, GetExitCodeProcess, WaitForSingleObject, INFINITE,
    PROCESS_INFORMATION, STARTUPINFOW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindow, GetWindowThreadProcessId, IsIconic, IsWindowVisible, MessageBoxW,
    SetForegroundWindow, ShowWindow, GW_OWNER, MB_ICONERROR, MB_ICONINFORMATION, MB_OK,
    SW_RESTORE,
};

use super::Instance;
use crate::cmdline::build_command_line;
use crate::error::{ErrorKind, LauncherError, Result};

const TITLE: &str = "Metroliza";
const ALREADY_RUNNING: &str =
    "Metroliza is already running or still starting. Please wait a moment.";

/// NUL-terminated UTF-16 for Win32 string parameters.
fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

/// Qualification and CI run without a person to dismiss dialogs: with this variable set,
/// message boxes are skipped (the outcome is still in the log and the exit code).
const NO_UI_ENV: &str = "METROLIZA_LAUNCHER_NO_UI";

fn message_box(text: &str, icon: u32) {
    if std::env::var_os(NO_UI_ENV).is_some_and(|v| !v.is_empty()) {
        return;
    }
    let (text, title) = (wide(text), wide(TITLE));
    // SAFETY: both buffers are NUL-terminated and outlive the call.
    unsafe {
        MessageBoxW(null_mut(), text.as_ptr(), title.as_ptr(), MB_OK | icon);
    }
}

/// Fixed-text error dialog; the detail is only in the log.
pub fn show_error(kind: ErrorKind) {
    message_box(kind.user_message(), MB_ICONERROR);
}

// ---------------------------------------------------------------- single instance

fn mutex_name(version: &str) -> Vec<u16> {
    wide(&format!("Local\\Metroliza-{version}"))
}

fn pid_mapping_name(version: &str) -> Vec<u16> {
    wide(&format!("Local\\Metroliza-{version}-entry-pid"))
}

/// Owns the named mutex (and the shared entry-pid cell) for the lifetime of the launcher.
pub struct InstanceGuard {
    mutex: HANDLE,
    version: String,
    pid_mapping: Mutex<HANDLE>,
}

impl Drop for InstanceGuard {
    fn drop(&mut self) {
        // SAFETY: handles were created by this guard and are closed exactly once.
        unsafe {
            CloseHandle(self.mutex);
            let mapping = *self.pid_mapping.lock().unwrap_or_else(|p| p.into_inner());
            if !mapping.is_null() {
                CloseHandle(mapping);
            }
        }
    }
}

/// Take `Local\Metroliza-<version>`. If creating the mutex fails for any other reason the launch
/// proceeds unguarded: refusing to start would be worse than a rare duplicate instance.
pub fn acquire_instance(version: &str) -> Instance {
    let name = mutex_name(version);
    // SAFETY: `name` is NUL-terminated; a null security descriptor means defaults.
    let (mutex, already) = unsafe {
        let mutex = CreateMutexW(null(), FALSE, name.as_ptr());
        (mutex, GetLastError() == ERROR_ALREADY_EXISTS)
    };
    if already {
        // SAFETY: handle returned by CreateMutexW above.
        unsafe { CloseHandle(mutex) };
        return Instance::Existing;
    }
    Instance::First(InstanceGuard {
        mutex,
        version: version.to_owned(),
        pid_mapping: Mutex::new(null_mut()),
    })
}

/// Publish the entry process id in a named 4-byte section so a second launcher can find the
/// application window. Best effort.
pub fn publish_entry_pid(guard: &InstanceGuard, pid: u32) {
    let name = pid_mapping_name(&guard.version);
    // SAFETY: standard create-map-write-unmap sequence on a 4-byte pagefile-backed section; the
    // view is unmapped before returning and the section handle is kept for the guard's lifetime.
    unsafe {
        let mapping = CreateFileMappingW(
            INVALID_HANDLE_VALUE,
            null(),
            PAGE_READWRITE,
            0,
            4,
            name.as_ptr(),
        );
        if mapping.is_null() {
            return;
        }
        let view = MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, 4);
        if view.Value.is_null() {
            CloseHandle(mapping);
            return;
        }
        (view.Value as *mut u32).write_volatile(pid);
        UnmapViewOfFile(view);
        // A repair restart publishes a second pid under the same name: keep one handle only.
        let mut slot = guard.pid_mapping.lock().unwrap_or_else(|p| p.into_inner());
        if !slot.is_null() {
            CloseHandle(*slot);
        }
        *slot = mapping;
    }
}

fn read_entry_pid(version: &str) -> Option<u32> {
    let name = pid_mapping_name(version);
    // SAFETY: read-only open and map of the 4-byte section written by `publish_entry_pid`.
    unsafe {
        let mapping = OpenFileMappingW(FILE_MAP_READ, FALSE, name.as_ptr());
        if mapping.is_null() {
            return None;
        }
        let view = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 4);
        let pid = (!view.Value.is_null()).then(|| (view.Value as *const u32).read_volatile());
        if !view.Value.is_null() {
            UnmapViewOfFile(view);
        }
        CloseHandle(mapping);
        pid.filter(|&p| p != 0)
    }
}

struct WindowSearch {
    pid: u32,
    found: HWND,
}

unsafe extern "system" fn find_window(hwnd: HWND, lparam: LPARAM) -> i32 {
    let search = &mut *(lparam as *mut WindowSearch);
    let mut owner_pid = 0u32;
    GetWindowThreadProcessId(hwnd, &mut owner_pid);
    // Visible, unowned top-level window of the entry process.
    if owner_pid == search.pid && IsWindowVisible(hwnd) != 0 && GetWindow(hwnd, GW_OWNER).is_null()
    {
        search.found = hwnd;
        return FALSE;
    }
    TRUE
}

/// A second launcher of the same version: bring the running application forward if its window
/// can be found, otherwise tell the user with a fixed message. Never extracts or starts anything.
pub fn activate_existing(version: &str) {
    if let Some(pid) = read_entry_pid(version) {
        let mut search = WindowSearch {
            pid,
            found: null_mut(),
        };
        // SAFETY: `search` outlives the synchronous EnumWindows call; the callback only
        // dereferences the pointer passed here.
        unsafe {
            EnumWindows(
                Some(find_window),
                &mut search as *mut WindowSearch as LPARAM,
            );
            if !search.found.is_null() {
                if IsIconic(search.found) != 0 {
                    ShowWindow(search.found, SW_RESTORE);
                }
                SetForegroundWindow(search.found);
                return;
            }
        }
    }
    message_box(ALREADY_RUNNING, MB_ICONINFORMATION);
}

// ---------------------------------------------------------------- entry process

/// The running entry process.
pub struct Child {
    process: HANDLE,
    pid: u32,
}

impl Child {
    pub fn id(&self) -> u32 {
        self.pid
    }

    /// Wait for the process to end and return its exit code.
    pub fn wait(self) -> Result<u32> {
        // SAFETY: `process` is a valid process handle owned by `self`, closed exactly once.
        unsafe {
            let waited = WaitForSingleObject(self.process, INFINITE);
            let mut code = 0u32;
            let ok = waited == WAIT_OBJECT_0 && GetExitCodeProcess(self.process, &mut code) != 0;
            CloseHandle(self.process);
            if ok {
                Ok(code)
            } else {
                Err(LauncherError::launch("wait for entry process failed"))
            }
        }
    }
}

/// Start `exe` with `args` and no inherited handles. `cwd` is the working directory; `None`
/// inherits the launcher's own, which is what the user's double-click or shortcut set.
pub fn spawn_entry(exe: &Path, args: &[OsString], cwd: Option<&Path>) -> Result<Child> {
    let program: Vec<u16> = exe.as_os_str().encode_wide().collect();
    let args: Vec<Vec<u16>> = args.iter().map(|a| a.encode_wide().collect()).collect();
    let mut command_line = build_command_line(&program, &args);
    command_line.push(0);
    let application: Vec<u16> = program.iter().copied().chain(std::iter::once(0)).collect();
    let directory: Option<Vec<u16>> = cwd.map(|dir| {
        dir.as_os_str()
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    });

    // SAFETY: zeroed STARTUPINFOW/PROCESS_INFORMATION are valid initial values; all string
    // buffers are NUL-terminated and outlive the call; the command line buffer is mutable as
    // CreateProcessW requires.
    unsafe {
        let mut startup: STARTUPINFOW = std::mem::zeroed();
        startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
        let mut info: PROCESS_INFORMATION = std::mem::zeroed();
        let created = CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            null(),
            null(),
            FALSE, // bInheritHandles: the entry process inherits nothing from the launcher
            0,
            null(),
            directory.as_ref().map_or(null(), |dir| dir.as_ptr()),
            &startup,
            &mut info,
        );
        if created == 0 {
            let code = GetLastError();
            return Err(LauncherError::spawn(
                format!("CreateProcessW error {code}"),
                Some(code as i32),
            ));
        }
        CloseHandle(info.hThread);
        Ok(Child {
            process: info.hProcess,
            pid: info.dwProcessId,
        })
    }
}

/// Ask Windows about processes using any runtime file, including orphaned application images.
/// Restart Manager observes kernel resource use without requiring application cooperation or
/// trusting a stale PID. No shutdown/restart API is called. Errors fail closed in cleanup.
pub fn runtime_in_use(dir: &Path) -> std::io::Result<bool> {
    use windows_sys::Win32::Foundation::ERROR_MORE_DATA;
    use windows_sys::Win32::System::RestartManager::{
        RmEndSession, RmGetList, RmRegisterResources, RmStartSession, CCH_RM_SESSION_KEY,
    };

    let mut directories = vec![dir.to_path_buf()];
    let mut names = Vec::new();
    while let Some(directory) = directories.pop() {
        for entry in std::fs::read_dir(directory)? {
            let entry = entry?;
            let meta = std::fs::symlink_metadata(entry.path())?;
            if crate::fsutil::is_link_or_reparse(&meta) {
                return Err(std::io::Error::other("redirected runtime resource"));
            }
            if meta.is_dir() {
                directories.push(entry.path());
            } else if meta.is_file() {
                let path = std::fs::canonicalize(entry.path())?;
                names.push(
                    path.as_os_str()
                        .encode_wide()
                        .chain(Some(0))
                        .collect::<Vec<_>>(),
                );
            }
        }
    }
    let pointers: Vec<_> = names.iter().map(|name| name.as_ptr()).collect();
    let mut session = 0;
    let mut key = [0; CCH_RM_SESSION_KEY as usize + 1];
    // SAFETY: all output pointers refer to live initialized storage.
    let status = unsafe { RmStartSession(&mut session, 0, key.as_mut_ptr()) };
    if status != 0 {
        return Err(std::io::Error::from_raw_os_error(status as i32));
    }
    let result = (|| {
        // SAFETY: paths and pointer array live through registration; there are no apps/services.
        let status = unsafe {
            RmRegisterResources(
                session,
                pointers.len() as u32,
                pointers.as_ptr(),
                0,
                null(),
                0,
                null(),
            )
        };
        if status != 0 {
            return Err(std::io::Error::from_raw_os_error(status as i32));
        }
        let (mut needed, mut count, mut reasons) = (0, 0, 0);
        // SAFETY: a zero-capacity query uses a null buffer and reports the required count.
        let status =
            unsafe { RmGetList(session, &mut needed, &mut count, null_mut(), &mut reasons) };
        match status {
            0 => Ok(needed != 0 || reasons != 0),
            ERROR_MORE_DATA => Ok(true),
            _ => Err(std::io::Error::from_raw_os_error(status as i32)),
        }
    })();
    // SAFETY: this function owns the session and always ends it, even on a failed query.
    unsafe { RmEndSession(session) };
    result
}
