//! Windows implementation of the platform layer (Win32 via `windows-sys`).
//!
//! Everything here is plain Win32 with fixed English texts. It has been compile-checked only on
//! Linux (`cargo check --target x86_64-pc-windows-gnu`); runtime behaviour is covered by the
//! Windows qualification job.

use std::ffi::{c_void, OsString};
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicIsize, AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::Mutex;
use std::thread::JoinHandle;

use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, FALSE, HANDLE, HWND, INVALID_HANDLE_VALUE,
    LPARAM, LRESULT, RECT, TRUE, WAIT_OBJECT_0, WPARAM,
};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, CreateSolidBrush, DeleteObject, DrawTextW, EndPaint, FillRect, FrameRect,
    GetStockObject, GetSysColorBrush, InvalidateRect, SelectObject, SetBkMode, UpdateWindow,
    COLOR_WINDOW, DEFAULT_GUI_FONT, DT_LEFT, DT_SINGLELINE, DT_VCENTER, HBRUSH, HGDIOBJ,
    PAINTSTRUCT, TRANSPARENT,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Memory::{
    CreateFileMappingW, MapViewOfFile, OpenFileMappingW, UnmapViewOfFile, FILE_MAP_READ,
    FILE_MAP_WRITE, PAGE_READWRITE,
};
use windows_sys::Win32::System::Threading::{
    CreateMutexW, CreateProcessW, GetExitCodeProcess, WaitForSingleObject, INFINITE,
    PROCESS_INFORMATION, STARTUPINFOW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, EnumWindows, GetMessageW,
    GetSystemMetrics, GetWindow, GetWindowThreadProcessId, IsIconic, IsWindowVisible, KillTimer,
    LoadCursorW, MessageBoxW, PostMessageW, PostQuitMessage, RegisterClassW, SetForegroundWindow,
    SetTimer, ShowWindow, TranslateMessage, GW_OWNER, IDC_ARROW, MB_ICONERROR, MB_ICONINFORMATION,
    MB_OK, MSG, SM_CXSCREEN, SM_CYSCREEN, SW_RESTORE, SW_SHOWNORMAL, WM_APP, WM_CLOSE, WM_CREATE,
    WM_DESTROY, WM_PAINT, WM_TIMER, WNDCLASSW, WS_CAPTION, WS_OVERLAPPED,
};

use super::Instance;
use crate::cache::Progress;
use crate::cmdline::build_command_line;
use crate::error::{ErrorKind, LauncherError, Result};

const TITLE: &str = "Metroliza";
const ALREADY_RUNNING: &str =
    "Metroliza is already running or still starting. Please wait a moment.";
const PREPARING: &str = "Preparing Metroliza for first use...";
const PREPARING_NOTE: &str = "This only happens once for each new version.";

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

// ---------------------------------------------------------------- progress window

static DONE: AtomicU64 = AtomicU64::new(0);
static TOTAL: AtomicU64 = AtomicU64::new(0);
/// Window handle as an integer so it can be shared across threads.
static WINDOW: AtomicIsize = AtomicIsize::new(0);

const TIMER_ID: usize = 1;
const WINDOW_WIDTH: i32 = 460;
const WINDOW_HEIGHT: i32 = 150;
const BAR_LEFT: i32 = 20;
const BAR_TOP: i32 = 76;
const BAR_HEIGHT: i32 = 20;

const fn rgb(r: u8, g: u8, b: u8) -> u32 {
    (r as u32) | ((g as u32) << 8) | ((b as u32) << 16)
}

fn draw_text(hdc: *mut c_void, text: &str, mut rect: RECT) {
    let text = wide(text);
    // SAFETY: `hdc` is the live paint DC of the window being painted.
    unsafe {
        DrawTextW(
            hdc,
            text.as_ptr(),
            -1,
            &mut rect,
            DT_LEFT | DT_SINGLELINE | DT_VCENTER,
        );
    }
}

unsafe fn paint(hwnd: HWND) {
    let mut ps: PAINTSTRUCT = std::mem::zeroed();
    let hdc = BeginPaint(hwnd, &mut ps);
    let mut client: RECT = std::mem::zeroed();
    windows_sys::Win32::UI::WindowsAndMessaging::GetClientRect(hwnd, &mut client);
    FillRect(hdc, &client, GetSysColorBrush(COLOR_WINDOW));

    let font = GetStockObject(DEFAULT_GUI_FONT) as HGDIOBJ;
    let previous = SelectObject(hdc, font);
    SetBkMode(hdc, TRANSPARENT as i32);
    draw_text(
        hdc,
        PREPARING,
        RECT {
            left: BAR_LEFT,
            top: 16,
            right: client.right - BAR_LEFT,
            bottom: 40,
        },
    );
    draw_text(
        hdc,
        PREPARING_NOTE,
        RECT {
            left: BAR_LEFT,
            top: 40,
            right: client.right - BAR_LEFT,
            bottom: 64,
        },
    );

    // Self-drawn bar: avoids comctl32 and the visual-styles manifest.
    let frame = RECT {
        left: BAR_LEFT,
        top: BAR_TOP,
        right: client.right - BAR_LEFT,
        bottom: BAR_TOP + BAR_HEIGHT,
    };
    let (done, total) = (DONE.load(Ordering::Relaxed), TOTAL.load(Ordering::Relaxed));
    let inner_width = u64::from((frame.right - frame.left - 2) as u32);
    let filled = (done.min(total) * inner_width)
        .checked_div(total)
        .unwrap_or(0) as i32;
    let fill_brush: HBRUSH = CreateSolidBrush(rgb(0, 120, 215));
    let border_brush: HBRUSH = CreateSolidBrush(rgb(120, 120, 120));
    let fill = RECT {
        left: frame.left + 1,
        top: frame.top + 1,
        right: frame.left + 1 + filled,
        bottom: frame.bottom - 1,
    };
    FillRect(hdc, &fill, fill_brush);
    FrameRect(hdc, &frame, border_brush);
    DeleteObject(fill_brush as HGDIOBJ);
    DeleteObject(border_brush as HGDIOBJ);

    SelectObject(hdc, previous);
    EndPaint(hwnd, &ps);
}

unsafe extern "system" fn window_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_CREATE => {
            SetTimer(hwnd, TIMER_ID, 50, None);
            0
        }
        WM_TIMER => {
            InvalidateRect(hwnd, null(), FALSE);
            0
        }
        WM_PAINT => {
            paint(hwnd);
            0
        }
        // The user cannot cancel: only the launcher itself ends this window (WM_APP).
        WM_CLOSE => 0,
        WM_APP => {
            DestroyWindow(hwnd);
            0
        }
        WM_DESTROY => {
            KillTimer(hwnd, TIMER_ID);
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// Create the window and pump messages until it is destroyed. Runs on its own thread; sends the
/// window handle (or 0 on failure) through `ready` once creation was attempted.
fn window_thread(ready: mpsc::Sender<isize>) {
    // SAFETY: plain Win32 window creation and message loop on a thread dedicated to the window.
    unsafe {
        let instance = GetModuleHandleW(null());
        let class_name = wide("MetrolizaLauncherProgress");
        let class = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(window_proc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: instance,
            hIcon: null_mut(),
            hCursor: LoadCursorW(null_mut(), IDC_ARROW),
            hbrBackground: null_mut(),
            lpszMenuName: null(),
            lpszClassName: class_name.as_ptr(),
        };
        RegisterClassW(&class);

        let x = (GetSystemMetrics(SM_CXSCREEN) - WINDOW_WIDTH) / 2;
        let y = (GetSystemMetrics(SM_CYSCREEN) - WINDOW_HEIGHT) / 2;
        let title = wide(TITLE);
        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION,
            x.max(0),
            y.max(0),
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            null_mut(),
            null_mut(),
            instance,
            null(),
        );
        if hwnd.is_null() {
            let _ = ready.send(0);
            return;
        }
        ShowWindow(hwnd, SW_SHOWNORMAL);
        UpdateWindow(hwnd);
        SetForegroundWindow(hwnd);
        let _ = ready.send(hwnd as isize);

        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

/// Progress window shown only when an extraction is needed. If the window cannot be created the
/// extraction simply runs without one.
pub struct ProgressWindow {
    thread: Mutex<Option<JoinHandle<()>>>,
}

impl ProgressWindow {
    pub fn new() -> Self {
        Self {
            thread: Mutex::new(None),
        }
    }
}

impl Default for ProgressWindow {
    fn default() -> Self {
        Self::new()
    }
}

impl Progress for ProgressWindow {
    fn begin(&self, total_bytes: u64) {
        DONE.store(0, Ordering::Relaxed);
        TOTAL.store(total_bytes, Ordering::Relaxed);
        let (sender, receiver) = mpsc::channel();
        let handle = std::thread::spawn(move || window_thread(sender));
        let hwnd = receiver.recv().unwrap_or(0);
        WINDOW.store(hwnd, Ordering::Release);
        *self.thread.lock().unwrap_or_else(|p| p.into_inner()) = Some(handle);
    }

    fn advance(&self, bytes: u64) {
        DONE.fetch_add(bytes, Ordering::Relaxed);
    }

    fn finish(&self) {
        let hwnd = WINDOW.swap(0, Ordering::AcqRel);
        if hwnd != 0 {
            // SAFETY: posting to a window owned by the UI thread is allowed from any thread.
            unsafe { PostMessageW(hwnd as HWND, WM_APP, 0, 0) };
        }
        if let Some(handle) = self.thread.lock().unwrap_or_else(|p| p.into_inner()).take() {
            let _ = handle.join();
        }
    }
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
            return Err(LauncherError::launch(format!(
                "CreateProcessW error {}",
                GetLastError()
            )));
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
