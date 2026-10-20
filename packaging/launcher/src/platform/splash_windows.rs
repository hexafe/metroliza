//! Launcher splash: the first window a user sees, shown before any cache work.
//!
//! The splash runs on its own thread with its own message loop, so the loading animation keeps
//! moving while the launcher extracts or verifies the runtime and while the application starts
//! (Python, Qt and the main window construct on the application's GUI thread). It also shows the
//! extraction/verification progress.
//!
//! Fallback: when the splash is disabled ([`SPLASH_ENV`]`=0`) or cannot be shown (thread start,
//! frame decoding, class or window creation failed, or the window thread did not create its window
//! within [`SHOW_WAIT`]), extraction and verification show the launcher's plain progress window
//! (`ProgressWindow`, unchanged from the launcher before the splash). Once the splash failed in a
//! process it is not tried again; the progress window is used for the rest of that launch.
//!
//! Hand-off protocol with the application (`metroliza.app.launcher_splash`): the launcher passes
//! the splash window handle in [`SPLASH_HWND_ENV`]. The application may update the status text
//! with `WM_COPYDATA` (UTF-16, [`STATUS_MAGIC`], at most [`MAX_STATUS_BYTES`]), closes it with
//! [`MSG_CLOSE`] before showing its own dialogs, and after the first paint of its main window
//! posts [`MSG_HANDOFF`] with that window's handle in `wParam`. The launcher, which owns the
//! foreground because the user just started it, then brings the main window to the front and
//! destroys the splash, so the focus moves exactly once and no two splashes overlap. If the entry
//! exits or never hands off, the launcher closes the splash itself. Before the exit-75 repair the
//! launcher shows the splash again (see [`Splash::reopen`]), so the repair and the restarted
//! application are covered as well.

use std::ffi::c_void;
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicBool, AtomicIsize, AtomicU64, AtomicU8, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};
use std::thread::JoinHandle;
use std::time::Duration;

use windows_sys::Win32::Foundation::{
    GetLastError, ERROR_CLASS_ALREADY_EXISTS, FALSE, HINSTANCE, HWND, LPARAM, LRESULT, POINT, RECT,
    WPARAM,
};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, CreateFontW,
    CreateSolidBrush, DeleteDC, DeleteObject, DrawTextW, EndPaint, FillRect, FrameRect,
    GetDC, GetDeviceCaps, InvalidateRect, ReleaseDC, SelectObject, SetBkMode, SetBrushOrgEx,
    SetStretchBltMode, SetTextColor, StretchDIBits, UpdateWindow, BITMAPINFO, BITMAPINFOHEADER,
    BI_RGB, CLEARTYPE_QUALITY, DEFAULT_CHARSET, DIB_RGB_COLORS, DT_END_ELLIPSIS, DT_LEFT,
    DT_NOPREFIX, DT_SINGLELINE, DT_VCENTER, DT_WORDBREAK, FW_BOLD, FW_NORMAL, HALFTONE, HDC,
    HGDIOBJ, LOGPIXELSX, PAINTSTRUCT, SRCCOPY, TRANSPARENT,
};
use windows_sys::Win32::System::DataExchange::COPYDATASTRUCT;
use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, GetClientRect, GetMessageW,
    GetSystemMetrics, IsWindow, KillTimer, LoadCursorW, PeekMessageW, PostMessageW,
    PostQuitMessage, RegisterClassW, SetForegroundWindow, SetTimer, ShowWindow, TranslateMessage,
    HTCAPTION, IDC_APPSTARTING, MSG, PM_REMOVE, SM_CXSCREEN, SM_CYSCREEN, SW_SHOWNORMAL, WM_APP,
    WM_CLOSE, WM_COPYDATA, WM_CREATE, WM_DESTROY, WM_ERASEBKGND, WM_NCHITTEST, WM_PAINT,
    WM_TIMER, WNDCLASSW, WS_EX_TOOLWINDOW, WS_POPUP,
};

use super::windows::ProgressWindow;
use crate::cache::{Progress, Stage};
use crate::log::Log;
use crate::splash_frames::{self, pixel, Frames};

/// Environment variable carrying the splash window handle (decimal) to the entry process.
pub const SPLASH_HWND_ENV: &str = "METROLIZA_LAUNCHER_SPLASH_HWND";
/// `METROLIZA_LAUNCHER_SPLASH=0` disables the splash; extraction and verification then show the
/// plain progress window, as the launcher did before the splash existed.
pub const SPLASH_ENV: &str = "METROLIZA_LAUNCHER_SPLASH";
/// Window class the application checks before it talks to a handle from the environment.
pub const SPLASH_CLASS: &str = "MetrolizaLauncherSplash";
/// Close the splash (posted by the application before its own dialogs, or by the launcher).
pub const MSG_CLOSE: u32 = WM_APP + 1;
/// The application's main window is painted: activate `wParam` and close the splash.
pub const MSG_HANDOFF: u32 = WM_APP + 2;
/// Launcher-internal: the runtime work ended, restart the deadline from now.
const MSG_REARM: u32 = WM_APP + 3;
/// `COPYDATASTRUCT::dwData` of a status-text update ("MLST").
pub const STATUS_MAGIC: usize = 0x4D4C_5354;
/// Largest accepted status text, in bytes of UTF-16.
pub const MAX_STATUS_BYTES: u32 = 512;

/// How long `show` waits for the window. A window thread that is later than this is told to
/// stop (it checks before it creates and before it shows its window) and the progress window is
/// used instead, so a slow start never leaves the launcher waiting or shows two windows.
const SHOW_WAIT: Duration = Duration::from_secs(2);

const TIMER_TICK: usize = 1;
const TIMER_DEADLINE: usize = 2;
/// One tick per animation frame (the GIF uses 100 ms); the indeterminate bar moves with it.
const TICK_MS: u32 = 100;
/// Safety net: a splash nobody hands off disappears this long after the launcher's runtime work
/// ended (it never fires during extraction or verification).
const DEADLINE_MS: u32 = 120_000;

// Logical (96 DPI) geometry, matching the application's Qt splash.
const WIDTH: i32 = 500;
const HEIGHT: i32 = 190;
const GIF_LEFT: i32 = 18;
const GIF_BOX: i32 = 128;
const TEXT_LEFT: i32 = 162;
const MARGIN: i32 = 18;
const BAR_HEIGHT: i32 = 6;

const BACKGROUND: u32 = pixel(0x15, 0x20, 0x2b);
const fn colorref(r: u8, g: u8, b: u8) -> u32 {
    (r as u32) | ((g as u32) << 8) | ((b as u32) << 16)
}
const BACKGROUND_REF: u32 = colorref(0x15, 0x20, 0x2b);
const BORDER_REF: u32 = colorref(0x2f, 0x48, 0x58);
const TITLE_REF: u32 = colorref(0xf8, 0xfa, 0xfc);
const STATUS_REF: u32 = colorref(0xcb, 0xd5, 0xe1);
const BAR_REF: u32 = colorref(0x3b, 0x82, 0xf6);

const STARTING: &str = "Starting Metroliza...";
const EXTRACTING: &str = "Preparing Metroliza for first use...";
const EXTRACTING_NOTE: &str = "This only happens once for each new version.";
const VERIFYING: &str = "Checking Metroliza files...";

// Window-thread claim states (one cell per `show` attempt).
const PENDING: u8 = 0;
const CLAIMED: u8 = 1;
const ABANDONED: u8 = 2;

// Which window receives the current `Progress::begin`..`finish` span.
const TARGET_NONE: u8 = 0;
const TARGET_SPLASH: u8 = 1;
const TARGET_FALLBACK: u8 = 2;

// Shared state between the launcher thread, the window thread and the window procedure. At most
// one splash window exists at a time: a new one is only created after the previous thread was
// joined, and never after a failed or abandoned attempt.
static WINDOW: AtomicIsize = AtomicIsize::new(0);
static DONE: AtomicU64 = AtomicU64::new(0);
static TOTAL: AtomicU64 = AtomicU64::new(0);
/// 0: indeterminate bar, 1: determinate (DONE/TOTAL).
static BAR_MODE: AtomicU8 = AtomicU8::new(0);
/// Extraction or verification is running: the deadline must not close the splash.
static RUNTIME_WORK: AtomicBool = AtomicBool::new(false);
static PAINTED: AtomicBool = AtomicBool::new(false);
static STATUS: Mutex<(String, String)> = Mutex::new((String::new(), String::new()));
/// State of the live (claimed) window; installed only after the claim, cleared on destroy.
static STATE: Mutex<Option<WindowState>> = Mutex::new(None);
/// Frames are decoded once per process (a repair re-shows the splash without decoding again).
static FRAMES: OnceLock<Option<Arc<Frames>>> = OnceLock::new();

struct WindowState {
    frames: Arc<Frames>,
    /// Title, status and note fonts, created once for the window's DPI (raw HFONT values).
    fonts: [isize; 3],
    frame: usize,
    frame_elapsed_ms: u32,
    tick: u64,
    scale_percent: i32,
    log: Log,
    close_reason: &'static str,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|p| p.into_inner())
}

fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

fn set_status(main: &str, note: &str) {
    let mut status = lock(&STATUS);
    status.0 = main.to_owned();
    status.1 = note.to_owned();
    drop(status);
    invalidate();
}

fn invalidate() {
    let hwnd = WINDOW.load(Ordering::Acquire);
    if hwnd != 0 {
        // SAFETY: InvalidateRect only queues a paint; a stale handle is rejected by Windows.
        unsafe { InvalidateRect(hwnd as HWND, null(), FALSE) };
    }
}

fn scaled(value: i32, scale_percent: i32) -> i32 {
    value * scale_percent / 100
}

type DpiAwarenessFn = unsafe extern "system" fn(isize) -> i32;
type DpiForSystemFn = unsafe extern "system" fn() -> u32;

fn user32_proc(name: &[u8]) -> Option<unsafe extern "system" fn() -> isize> {
    let module = wide("user32.dll");
    // SAFETY: user32 is loaded in every GUI-capable process; `name` is NUL-terminated.
    unsafe {
        let handle = GetModuleHandleW(module.as_ptr());
        if handle.is_null() {
            return None;
        }
        GetProcAddress(handle, name.as_ptr())
    }
}

/// System DPI awareness when the system supports it (Windows 10 1607+), matching the sizing,
/// which uses the system DPI; looked up at run time so older systems still start. Only set when
/// the splash is tried; with the splash disabled the process keeps the old DPI behaviour.
///
/// Deferred (STEP2 A1): per-monitor DPI awareness. It needs `WM_DPICHANGED` handling (new fonts
/// and geometry when the splash is on, or is moved to, a monitor with another scale); until then
/// the splash is sized once for the system DPI.
fn enable_dpi_awareness() {
    if let Some(function) = user32_proc(b"SetProcessDpiAwarenessContext\0") {
        // SAFETY: the symbol has this signature; -2 is DPI_AWARENESS_CONTEXT_SYSTEM_AWARE.
        unsafe {
            let set: DpiAwarenessFn = std::mem::transmute(function);
            set(-2);
        }
    }
}

fn system_scale_percent() -> i32 {
    let dpi = if let Some(function) = user32_proc(b"GetDpiForSystem\0") {
        // SAFETY: the symbol has this signature.
        unsafe {
            let get: DpiForSystemFn = std::mem::transmute(function);
            get() as i32
        }
    } else {
        // SAFETY: a screen DC is obtained and released in the same block.
        unsafe {
            let dc = GetDC(null_mut());
            let dpi = GetDeviceCaps(dc, LOGPIXELSX as i32);
            ReleaseDC(null_mut(), dc);
            dpi
        }
    };
    if dpi <= 0 {
        100
    } else {
        (dpi * 100 / 96).clamp(100, 400)
    }
}

unsafe fn fill(hdc: HDC, rect: &RECT, color: u32) {
    let brush = CreateSolidBrush(color);
    FillRect(hdc, rect, brush);
    DeleteObject(brush as HGDIOBJ);
}

unsafe fn create_font(height: i32, weight: u32) -> isize {
    let face = wide("Segoe UI");
    CreateFontW(
        -height,
        0,
        0,
        0,
        weight as i32,
        0,
        0,
        0,
        u32::from(DEFAULT_CHARSET),
        0,
        0,
        u32::from(CLEARTYPE_QUALITY),
        0,
        face.as_ptr(),
    ) as isize
}

unsafe fn delete_fonts(fonts: [isize; 3]) {
    for font in fonts {
        if font != 0 {
            DeleteObject(font as HGDIOBJ);
        }
    }
}

unsafe fn text(hdc: HDC, value: &str, rect: RECT, font: isize, color: u32, flags: u32) {
    let previous = SelectObject(hdc, font as HGDIOBJ);
    SetTextColor(hdc, color);
    let mut rect = rect;
    let value = wide(value);
    DrawTextW(hdc, value.as_ptr(), -1, &mut rect, flags | DT_NOPREFIX);
    SelectObject(hdc, previous);
}

unsafe fn paint(hwnd: HWND) {
    let mut ps: PAINTSTRUCT = std::mem::zeroed();
    let window_dc = BeginPaint(hwnd, &mut ps);
    let mut client: RECT = std::mem::zeroed();
    GetClientRect(hwnd, &mut client);
    let (width, height) = (client.right - client.left, client.bottom - client.top);

    // Double buffer: compose off screen, then one blit, so the animation never flickers.
    let dc = CreateCompatibleDC(window_dc);
    let bitmap = CreateCompatibleBitmap(window_dc, width, height);
    let previous_bitmap = SelectObject(dc, bitmap as HGDIOBJ);
    fill(dc, &client, BACKGROUND_REF);
    let border = CreateSolidBrush(BORDER_REF);
    FrameRect(dc, &client, border);
    DeleteObject(border as HGDIOBJ);
    SetBkMode(dc, TRANSPARENT as i32);

    let state = lock(&STATE);
    let scale = state.as_ref().map_or(100, |s| s.scale_percent);
    let tick = state.as_ref().map_or(0, |s| s.tick);
    let fonts = state.as_ref().map_or([0; 3], |s| s.fonts);
    if let Some(state) = state.as_ref() {
        let frames = &state.frames;
        let (fw, fh) = (frames.width as i32, frames.height as i32);
        let box_size = scaled(GIF_BOX, scale);
        let (dw, dh) = if fw >= fh {
            (box_size, (box_size * fh / fw).max(1))
        } else {
            ((box_size * fw / fh).max(1), box_size)
        };
        let x = scaled(GIF_LEFT, scale) + (box_size - dw) / 2;
        let y = (height - dh) / 2;
        let mut info: BITMAPINFO = std::mem::zeroed();
        info.bmiHeader = BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: fw,
            biHeight: -fh, // top-down rows
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB,
            biSizeImage: 0,
            biXPelsPerMeter: 0,
            biYPelsPerMeter: 0,
            biClrUsed: 0,
            biClrImportant: 0,
        };
        SetStretchBltMode(dc, HALFTONE);
        SetBrushOrgEx(dc, 0, 0, null_mut::<POINT>());
        // `decode` never returns an empty frame list.
        let pixels = &frames.pixels[state.frame % frames.pixels.len()];
        StretchDIBits(
            dc,
            x,
            y,
            dw,
            dh,
            0,
            0,
            fw,
            fh,
            pixels.as_ptr() as *const c_void,
            &info,
            DIB_RGB_COLORS,
            SRCCOPY,
        );
    }
    drop(state);

    let left = scaled(TEXT_LEFT, scale);
    let right = width - scaled(MARGIN, scale);
    let (main, note) = lock(&STATUS).clone();
    let title_top = scaled(46, scale);
    text(
        dc,
        "Metroliza",
        RECT { left, top: title_top, right, bottom: title_top + scaled(34, scale) },
        fonts[0],
        TITLE_REF,
        DT_LEFT | DT_SINGLELINE | DT_VCENTER,
    );
    let status_top = title_top + scaled(40, scale);
    text(
        dc,
        if main.is_empty() { STARTING } else { &main },
        RECT { left, top: status_top, right, bottom: status_top + scaled(36, scale) },
        fonts[1],
        STATUS_REF,
        DT_LEFT | DT_WORDBREAK | DT_END_ELLIPSIS,
    );
    if !note.is_empty() {
        let note_top = status_top + scaled(36, scale);
        text(
            dc,
            &note,
            RECT { left, top: note_top, right, bottom: note_top + scaled(18, scale) },
            fonts[2],
            STATUS_REF,
            DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS,
        );
    }

    // Progress bar: determinate while bytes are counted, otherwise a moving block.
    let bar_top = height - scaled(MARGIN + BAR_HEIGHT + 8, scale);
    let track = RECT { left, top: bar_top, right, bottom: bar_top + scaled(BAR_HEIGHT, scale) };
    fill(dc, &track, BORDER_REF);
    let span = (track.right - track.left).max(1);
    let filled = if BAR_MODE.load(Ordering::Relaxed) == 1 {
        let (done, total) = (DONE.load(Ordering::Relaxed), TOTAL.load(Ordering::Relaxed));
        let width = (done.min(total) * span as u64).checked_div(total).unwrap_or(0) as i32;
        RECT { right: track.left + width, ..track }
    } else {
        let block = span / 4;
        let period = 15u64; // ticks per sweep (1.5 s at 100 ms)
        let offset = ((tick % period) as i32 * (span + block) / period as i32) - block;
        RECT {
            left: (track.left + offset).max(track.left),
            right: (track.left + offset + block).min(track.right),
            ..track
        }
    };
    if filled.right > filled.left {
        fill(dc, &filled, BAR_REF);
    }

    BitBlt(window_dc, 0, 0, width, height, dc, 0, 0, SRCCOPY);
    SelectObject(dc, previous_bitmap);
    DeleteObject(bitmap as HGDIOBJ);
    DeleteDC(dc);
    EndPaint(hwnd, &ps);

    if !PAINTED.swap(true, Ordering::AcqRel) {
        if let Some(state) = lock(&STATE).as_ref() {
            state.log.mark("splash_painted");
        }
    }
}

fn on_tick() {
    if let Some(state) = lock(&STATE).as_mut() {
        state.tick += 1;
        state.frame_elapsed_ms += TICK_MS;
        let delay = state
            .frames
            .delays_ms
            .get(state.frame % state.frames.delays_ms.len())
            .copied()
            .unwrap_or(100);
        if state.frame_elapsed_ms >= delay {
            state.frame_elapsed_ms = 0;
            state.frame = state.frame.wrapping_add(1);
        }
    }
    invalidate();
}

fn close_reason(reason: &'static str) {
    if let Some(state) = lock(&STATE).as_mut() {
        state.close_reason = reason;
    }
}

/// Give the foreground to the application's main window (the launcher still owns it).
unsafe fn activate(target: WPARAM) {
    let target = target as HWND;
    if !target.is_null() && IsWindow(target) != 0 {
        SetForegroundWindow(target);
    }
}

/// Destroy the splash for `reason`. A hand-off already queued behind this close is honoured
/// first, so a close that races with the hand-off never loses the focus transfer.
unsafe fn close_window(hwnd: HWND, reason: &'static str) {
    let mut pending: MSG = std::mem::zeroed();
    let reason = if PeekMessageW(&mut pending, hwnd, MSG_HANDOFF, MSG_HANDOFF, PM_REMOVE) != 0 {
        activate(pending.wParam);
        "handoff"
    } else {
        reason
    };
    close_reason(reason);
    DestroyWindow(hwnd);
}

/// Accept a bounded UTF-16 status text; it is display-only and never interpreted.
unsafe fn on_copy_data(lparam: LPARAM) -> LRESULT {
    let data = lparam as *const COPYDATASTRUCT;
    if data.is_null() {
        return 0;
    }
    let data = &*data;
    if data.dwData != STATUS_MAGIC
        || data.cbData > MAX_STATUS_BYTES
        || data.cbData % 2 != 0
        || (data.cbData > 0 && data.lpData.is_null())
    {
        return 0;
    }
    let units = std::slice::from_raw_parts(data.lpData as *const u16, (data.cbData / 2) as usize);
    let text: String = String::from_utf16_lossy(units)
        .chars()
        .filter(|c| !c.is_control())
        .take(120)
        .collect();
    set_status(&text, "");
    1
}

unsafe extern "system" fn window_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_CREATE => {
            SetTimer(hwnd, TIMER_TICK, TICK_MS, None);
            SetTimer(hwnd, TIMER_DEADLINE, DEADLINE_MS, None);
            0
        }
        WM_TIMER if wparam == TIMER_DEADLINE => {
            // The timer repeats; while the launcher still extracts or verifies it is ignored.
            if !RUNTIME_WORK.load(Ordering::Acquire) {
                close_window(hwnd, "deadline");
            }
            0
        }
        WM_TIMER => {
            on_tick();
            0
        }
        WM_ERASEBKGND => 1,
        WM_PAINT => {
            paint(hwnd);
            0
        }
        // Dragging anywhere moves the splash; it has no frame or buttons.
        WM_NCHITTEST => HTCAPTION as LRESULT,
        WM_COPYDATA => on_copy_data(lparam),
        // Only the launcher or the application ends the splash.
        WM_CLOSE => 0,
        MSG_CLOSE => {
            close_window(hwnd, "close");
            0
        }
        MSG_HANDOFF => {
            activate(wparam);
            close_reason("handoff");
            DestroyWindow(hwnd);
            0
        }
        MSG_REARM => {
            // Same id: replaces the running deadline timer.
            SetTimer(hwnd, TIMER_DEADLINE, DEADLINE_MS, None);
            0
        }
        WM_DESTROY => {
            KillTimer(hwnd, TIMER_TICK);
            KillTimer(hwnd, TIMER_DEADLINE);
            // Only the claimed window owns the shared state; a window destroyed because its
            // thread was abandoned leaves it alone.
            if WINDOW
                .compare_exchange(hwnd as isize, 0, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                if let Some(state) = lock(&STATE).take() {
                    state.log.mark(&format!("splash_closed_{}", state.close_reason));
                    delete_fonts(state.fonts);
                }
            }
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// The class is registered once per process; a repeated registration reports "already exists".
unsafe fn register_class(instance: HINSTANCE, class_name: &[u16]) -> bool {
    let class = WNDCLASSW {
        style: 0,
        lpfnWndProc: Some(window_proc),
        cbClsExtra: 0,
        cbWndExtra: 0,
        hInstance: instance,
        hIcon: null_mut(),
        hCursor: LoadCursorW(null_mut(), IDC_APPSTARTING),
        hbrBackground: null_mut(),
        lpszMenuName: null(),
        lpszClassName: class_name.as_ptr(),
    };
    RegisterClassW(&class) != 0 || GetLastError() == ERROR_CLASS_ALREADY_EXISTS
}

fn abandoned(claim: &AtomicU8) -> bool {
    claim.load(Ordering::Acquire) == ABANDONED
}

/// Create the splash and pump its messages until it is destroyed. Sends the window handle once
/// the window is shown, or 0 when any step failed. Does nothing visible once `claim` says the
/// launcher stopped waiting; the window is created hidden and claimed before it is shown.
fn window_thread(ready: mpsc::Sender<isize>, claim: Arc<AtomicU8>, log: Log) {
    if abandoned(&claim) {
        return;
    }
    let decoded = FRAMES.get_or_init(|| {
        splash_frames::decode(splash_frames::LOADING_GIF, BACKGROUND)
            .ok()
            .map(Arc::new)
    });
    let Some(frames) = decoded.clone() else {
        log.mark("splash_frames_failed");
        let _ = ready.send(0);
        return;
    };
    log.mark("splash_frames_decoded");
    let scale_percent = system_scale_percent();
    // SAFETY: plain Win32 window creation and message loop on a thread dedicated to the window;
    // every GDI font created here is deleted exactly once (here on failure, in WM_DESTROY after
    // it was handed to STATE).
    unsafe {
        let instance = GetModuleHandleW(null());
        let class_name = wide(SPLASH_CLASS);
        if !register_class(instance, &class_name) {
            log.mark("splash_class_failed");
            let _ = ready.send(0);
            return;
        }
        if abandoned(&claim) {
            return;
        }
        let fonts = [
            create_font(scaled(22, scale_percent), FW_BOLD),
            create_font(scaled(13, scale_percent), FW_NORMAL),
            create_font(scaled(12, scale_percent), FW_NORMAL),
        ];
        let (width, height) = (scaled(WIDTH, scale_percent), scaled(HEIGHT, scale_percent));
        let x = (GetSystemMetrics(SM_CXSCREEN) - width) / 2;
        let y = (GetSystemMetrics(SM_CYSCREEN) - height) / 2;
        let title = wide("Metroliza");
        let hwnd = CreateWindowExW(
            WS_EX_TOOLWINDOW,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_POPUP, // hidden until claimed
            x.max(0),
            y.max(0),
            width,
            height,
            null_mut(),
            null_mut(),
            instance,
            null(),
        );
        if hwnd.is_null() {
            delete_fonts(fonts);
            log.mark("splash_window_failed");
            let _ = ready.send(0);
            return;
        }
        if claim
            .compare_exchange(PENDING, CLAIMED, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            // The launcher stopped waiting and shows the progress window: never appear.
            DestroyWindow(hwnd);
            delete_fonts(fonts);
            log.mark("splash_abandoned_window_destroyed");
            return;
        }
        *lock(&STATE) = Some(WindowState {
            frames,
            fonts,
            frame: 0,
            frame_elapsed_ms: 0,
            tick: 0,
            scale_percent,
            log: log.clone(),
            close_reason: "exit",
        });
        PAINTED.store(false, Ordering::Release);
        WINDOW.store(hwnd as isize, Ordering::Release);
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

#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    /// `METROLIZA_LAUNCHER_SPLASH=0`.
    Disabled,
    /// The splash could not be shown; the progress window is used for this launch.
    Failed,
    /// The splash thread was started and showed its window.
    Shown,
}

struct Inner {
    mode: Mode,
    thread: Option<JoinHandle<()>>,
}

/// Start a window thread and wait (at most [`SHOW_WAIT`]) for its window.
fn start_splash(inner: &mut Inner, log: &Log) {
    log.mark("splash_show");
    enable_dpi_awareness();
    set_status(STARTING, "");
    BAR_MODE.store(0, Ordering::Relaxed);
    DONE.store(0, Ordering::Relaxed);
    TOTAL.store(0, Ordering::Relaxed);
    let claim = Arc::new(AtomicU8::new(PENDING));
    let (sender, receiver) = mpsc::channel();
    let (thread_claim, thread_log) = (Arc::clone(&claim), log.clone());
    let spawned = std::thread::Builder::new()
        .name("launcher-splash".into())
        .spawn(move || window_thread(sender, thread_claim, thread_log));
    let handle = match spawned {
        Ok(handle) => handle,
        Err(_) => {
            log.mark("splash_thread_failed");
            inner.mode = Mode::Failed;
            return;
        }
    };
    let hwnd = match receiver.recv_timeout(SHOW_WAIT) {
        Ok(hwnd) => hwnd,
        Err(RecvTimeoutError::Timeout) => {
            if claim
                .compare_exchange(PENDING, ABANDONED, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                // The late thread sees the flag and exits without a window; it is detached
                // (dropping the handle closes it), so nothing ever waits for it.
                log.mark("splash_late_abandoned");
                inner.mode = Mode::Failed;
                return;
            }
            // The thread claimed its window just now: the handle follows immediately (or the
            // channel closes if the thread ended).
            receiver.recv().unwrap_or(0)
        }
        Err(RecvTimeoutError::Disconnected) => 0,
    };
    if hwnd == 0 {
        // The thread reported a failure (or ended) and returns without a window.
        let _ = handle.join();
        WINDOW.store(0, Ordering::Release);
        log.mark("splash_failed");
        inner.mode = Mode::Failed;
        return;
    }
    log.mark("splash_shown");
    inner.mode = Mode::Shown;
    inner.thread = Some(handle);
}

/// Close the splash window if it is open and wait for its thread (which then ends promptly).
/// Returns false only when the thread had to be detached with its window possibly still open.
fn close_splash(inner: &mut Inner) -> bool {
    let Some(handle) = inner.thread.take() else {
        return true;
    };
    let hwnd = WINDOW.load(Ordering::Acquire);
    // SAFETY: posting to a window owned by another thread is allowed from any thread.
    let ending = hwnd == 0
        || unsafe { PostMessageW(hwnd as HWND, MSG_CLOSE, 0, 0) } != 0
        // The post failed because the window was destroyed meanwhile (hand-off, deadline).
        || WINDOW.load(Ordering::Acquire) == 0;
    if ending {
        // The window is gone or MSG_CLOSE destroys it; either way its message loop ends now.
        let _ = handle.join();
    }
    // Otherwise (a full message queue) the thread is detached rather than waited for.
    ending
}

/// The launcher's visible feedback: the splash, or the plain progress window as its fallback.
/// Closing (explicitly or by drop) is idempotent and joins the splash thread.
pub struct Splash {
    log: Log,
    inner: Mutex<Inner>,
    fallback: ProgressWindow,
    /// [`TARGET_NONE`], [`TARGET_SPLASH`] or [`TARGET_FALLBACK`] for the current runtime work.
    target: AtomicU8,
}

impl Splash {
    /// Show the splash now; returns once its window exists or the attempt failed (normally
    /// within a few milliseconds, at most [`SHOW_WAIT`]). Disabled or failed: no window yet; the
    /// progress window appears if extraction or verification is needed.
    pub fn show(log: &Log) -> Self {
        let splash = Self {
            log: log.clone(),
            inner: Mutex::new(Inner {
                mode: Mode::Disabled,
                thread: None,
            }),
            fallback: ProgressWindow::new(),
            target: AtomicU8::new(TARGET_NONE),
        };
        if std::env::var_os(SPLASH_ENV).is_some_and(|v| v == "0") {
            log.mark("splash_show");
            log.mark("splash_disabled");
        } else {
            start_splash(&mut lock(&splash.inner), log);
        }
        splash
    }

    /// Show the splash again before the exit-75 repair. The application normally closed or
    /// handed off the splash before it asked for the repair, and a close it posted may still be
    /// queued, so the old window is always closed first and a fresh one is shown; it covers the
    /// repair and is handed to the restarted application. Without a working splash the progress
    /// window appears for the repair (from `Progress::begin`).
    pub fn reopen(&self) {
        self.log.mark("splash_reopen");
        let mut inner = lock(&self.inner);
        if inner.mode != Mode::Shown {
            return;
        }
        if !close_splash(&mut inner) {
            // Never a second splash beside one that may still be open: use the progress window.
            self.log.mark("splash_close_detached");
            inner.mode = Mode::Failed;
            return;
        }
        start_splash(&mut inner, &self.log);
    }

    /// Value for [`SPLASH_HWND_ENV`] while the splash window is open.
    pub fn handle_for_entry(&self) -> Option<String> {
        let inner = lock(&self.inner);
        let current = WINDOW.load(Ordering::Acquire);
        (inner.mode == Mode::Shown && inner.thread.is_some() && current != 0)
            .then(|| current.to_string())
    }

    /// Replace the status text (launcher-side phases such as a repair).
    pub fn status(&self, main: &str) {
        set_status(main, "");
    }

    /// Close the splash window if it is still open and wait for its thread. Idempotent; never
    /// waits for a thread that could not be told to stop.
    pub fn close(&self) {
        close_splash(&mut lock(&self.inner));
    }

    fn splash_open(&self) -> bool {
        let inner = lock(&self.inner);
        inner.mode == Mode::Shown && inner.thread.is_some() && WINDOW.load(Ordering::Acquire) != 0
    }
}

impl Drop for Splash {
    fn drop(&mut self) {
        self.close();
    }
}

impl Progress for Splash {
    fn begin(&self, total_bytes: u64) {
        self.log.mark("runtime_work_begin");
        // Set first, so the deadline cannot close the splash between the check and the work.
        RUNTIME_WORK.store(true, Ordering::Release);
        if self.splash_open() {
            DONE.store(0, Ordering::Relaxed);
            TOTAL.store(total_bytes, Ordering::Relaxed);
            BAR_MODE.store(1, Ordering::Relaxed);
            self.target.store(TARGET_SPLASH, Ordering::Release);
        } else {
            RUNTIME_WORK.store(false, Ordering::Release);
            self.target.store(TARGET_FALLBACK, Ordering::Release);
            self.fallback.begin(total_bytes);
            self.log.mark("progress_window_shown");
        }
    }

    fn advance(&self, bytes: u64) {
        match self.target.load(Ordering::Acquire) {
            TARGET_SPLASH => {
                DONE.fetch_add(bytes, Ordering::Relaxed);
            }
            TARGET_FALLBACK => self.fallback.advance(bytes),
            _ => {}
        }
    }

    fn finish(&self) {
        match self.target.swap(TARGET_NONE, Ordering::AcqRel) {
            TARGET_SPLASH => {
                BAR_MODE.store(0, Ordering::Relaxed);
                set_status(STARTING, "");
                RUNTIME_WORK.store(false, Ordering::Release);
                let hwnd = WINDOW.load(Ordering::Acquire);
                if hwnd != 0 {
                    // SAFETY: posting to a window owned by another thread is allowed.
                    unsafe { PostMessageW(hwnd as HWND, MSG_REARM, 0, 0) };
                }
            }
            TARGET_FALLBACK => {
                self.fallback.finish();
                self.log.mark("progress_window_closed");
            }
            _ => {}
        }
        self.log.mark("runtime_work_done");
    }

    fn stage(&self, stage: Stage) {
        let (main, note, mark) = match stage {
            Stage::Verifying => (VERIFYING, "", "verify_begin"),
            Stage::Extracting => (EXTRACTING, EXTRACTING_NOTE, "extract_begin"),
        };
        self.log.mark(mark);
        // The progress window keeps its fixed text and bar, as before the splash.
        if self.target.load(Ordering::Acquire) == TARGET_SPLASH {
            DONE.store(0, Ordering::Relaxed);
            BAR_MODE.store(1, Ordering::Relaxed);
            set_status(main, note);
        }
    }

    fn verified(&self, bytes: u64) {
        if self.target.load(Ordering::Acquire) == TARGET_SPLASH {
            DONE.fetch_add(bytes, Ordering::Relaxed);
        }
    }
}
