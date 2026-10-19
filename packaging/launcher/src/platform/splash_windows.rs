//! Launcher splash: the first window a user sees, shown before any cache work.
//!
//! The splash runs on its own thread with its own message loop, so the loading animation keeps
//! moving while the launcher extracts or verifies the runtime and while the application starts
//! (Python, Qt and the main window construct on the application's GUI thread). It also shows the
//! extraction/verification progress the old progress window showed.
//!
//! Hand-off protocol with the application (`metroliza.app.launcher_splash`): the launcher passes
//! the splash window handle in [`SPLASH_HWND_ENV`]. The application may update the status text
//! with `WM_COPYDATA` (UTF-16, [`STATUS_MAGIC`], at most [`MAX_STATUS_BYTES`]), closes it with
//! [`MSG_CLOSE`] before showing its own dialogs, and after the first paint of its main window
//! posts [`MSG_HANDOFF`] with that window's handle in `wParam`. The launcher, which owns the
//! foreground because the user just started it, then brings the main window to the front and
//! destroys the splash, so the focus moves exactly once and no two splashes overlap. If the entry
//! exits or never hands off, the launcher closes the splash itself.

use std::ffi::c_void;
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicBool, AtomicIsize, AtomicU64, AtomicU8, Ordering};
use std::sync::{mpsc, Mutex, OnceLock};
use std::thread::JoinHandle;
use std::time::Duration;

use windows_sys::Win32::Foundation::{FALSE, HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
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
    GetSystemMetrics, IsWindow, KillTimer, LoadCursorW, PostMessageW, PostQuitMessage,
    RegisterClassW, SetForegroundWindow, SetTimer, ShowWindow, TranslateMessage, HTCAPTION,
    IDC_APPSTARTING, MSG, SM_CXSCREEN, SM_CYSCREEN, SW_SHOWNORMAL, WM_APP, WM_CLOSE,
    WM_COPYDATA, WM_CREATE, WM_DESTROY, WM_ERASEBKGND, WM_NCHITTEST, WM_PAINT, WM_TIMER,
    WNDCLASSW, WS_EX_TOOLWINDOW, WS_POPUP,
};

use crate::cache::{Progress, Stage};
use crate::log::Log;
use crate::splash_frames::{self, pixel, Frames};

/// Environment variable carrying the splash window handle (decimal) to the entry process.
pub const SPLASH_HWND_ENV: &str = "METROLIZA_LAUNCHER_SPLASH_HWND";
/// `METROLIZA_LAUNCHER_SPLASH=0` disables the splash (qualification of the old behaviour).
pub const SPLASH_ENV: &str = "METROLIZA_LAUNCHER_SPLASH";
/// Window class the application checks before it talks to a handle from the environment.
pub const SPLASH_CLASS: &str = "MetrolizaLauncherSplash";
/// Close the splash (posted by the application before its own dialogs, or by the launcher).
pub const MSG_CLOSE: u32 = WM_APP + 1;
/// The application's main window is painted: activate `wParam` and close the splash.
pub const MSG_HANDOFF: u32 = WM_APP + 2;
/// `COPYDATASTRUCT::dwData` of a status-text update ("MLST").
pub const STATUS_MAGIC: usize = 0x4D4C_5354;
/// Largest accepted status text, in bytes of UTF-16.
pub const MAX_STATUS_BYTES: u32 = 512;

const TIMER_TICK: usize = 1;
const TIMER_DEADLINE: usize = 2;
/// One tick per animation frame (the GIF uses 100 ms); the indeterminate bar moves with it.
const TICK_MS: u32 = 100;
/// Safety net: a splash nobody hands off disappears after this long.
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

// Shared state between the launcher thread, the window thread and the window procedure.
static WINDOW: AtomicIsize = AtomicIsize::new(0);
static DONE: AtomicU64 = AtomicU64::new(0);
static TOTAL: AtomicU64 = AtomicU64::new(0);
/// 0: indeterminate bar, 1: determinate (DONE/TOTAL).
static BAR_MODE: AtomicU8 = AtomicU8::new(0);
static PAINTED: AtomicBool = AtomicBool::new(false);
static STATUS: Mutex<(String, String)> = Mutex::new((String::new(), String::new()));
static STATE: OnceLock<Mutex<WindowState>> = OnceLock::new();

struct WindowState {
    frames: Option<Frames>,
    /// Title, status and note fonts, created once for the window's DPI (raw HFONT values).
    fonts: [isize; 3],
    frame: usize,
    frame_elapsed_ms: u32,
    tick: u64,
    scale_percent: i32,
    log: Log,
    close_reason: &'static str,
}

fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

fn set_status(main: &str, note: &str) {
    let mut status = STATUS.lock().unwrap_or_else(|p| p.into_inner());
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

/// Per-monitor-v2 DPI awareness when the system supports it (Windows 10 1703+), so the splash is
/// drawn sharp at 125–200 %; looked up at run time so older systems still start.
fn enable_dpi_awareness() {
    if let Some(function) = user32_proc(b"SetProcessDpiAwarenessContext\0") {
        // SAFETY: the symbol has this signature; -4 is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
        unsafe {
            let set: DpiAwarenessFn = std::mem::transmute(function);
            set(-4);
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

    let state = STATE.get().map(|s| s.lock().unwrap_or_else(|p| p.into_inner()));
    let scale = state.as_ref().map_or(100, |s| s.scale_percent);
    let tick = state.as_ref().map_or(0, |s| s.tick);
    let fonts = state.as_ref().map_or([0; 3], |s| s.fonts);
    if let Some(state) = &state {
        if let Some(frames) = &state.frames {
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
    }
    drop(state);

    let left = scaled(TEXT_LEFT, scale);
    let right = width - scaled(MARGIN, scale);
    let (main, note) = STATUS
        .lock()
        .map(|s| s.clone())
        .unwrap_or_else(|p| p.into_inner().clone());
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
        if let Some(state) = STATE.get() {
            state.lock().unwrap_or_else(|p| p.into_inner()).log.mark("splash_painted");
        }
    }
}

fn on_tick() {
    if let Some(state) = STATE.get() {
        let mut state = state.lock().unwrap_or_else(|p| p.into_inner());
        state.tick += 1;
        state.frame_elapsed_ms += TICK_MS;
        let delay = state
            .frames
            .as_ref()
            .and_then(|f| f.delays_ms.get(state.frame % f.delays_ms.len()).copied())
            .unwrap_or(100);
        if state.frame_elapsed_ms >= delay {
            state.frame_elapsed_ms = 0;
            state.frame = state.frame.wrapping_add(1);
        }
    }
    invalidate();
}

fn close_reason(reason: &'static str) {
    if let Some(state) = STATE.get() {
        state.lock().unwrap_or_else(|p| p.into_inner()).close_reason = reason;
    }
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
            close_reason("deadline");
            DestroyWindow(hwnd);
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
            close_reason("close");
            DestroyWindow(hwnd);
            0
        }
        MSG_HANDOFF => {
            let target = wparam as HWND;
            if !target.is_null() && IsWindow(target) != 0 {
                // The launcher still owns the foreground: give it to the main window, once.
                SetForegroundWindow(target);
            }
            close_reason("handoff");
            DestroyWindow(hwnd);
            0
        }
        WM_DESTROY => {
            KillTimer(hwnd, TIMER_TICK);
            KillTimer(hwnd, TIMER_DEADLINE);
            WINDOW.store(0, Ordering::Release);
            if let Some(state) = STATE.get() {
                let mut state = state.lock().unwrap_or_else(|p| p.into_inner());
                state.log.mark(&format!("splash_closed_{}", state.close_reason));
                for font in std::mem::take(&mut state.fonts) {
                    if font != 0 {
                        DeleteObject(font as HGDIOBJ);
                    }
                }
            }
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

fn window_thread(ready: mpsc::Sender<isize>, log: Log) {
    let scale_percent = system_scale_percent();
    let frames = splash_frames::decode(splash_frames::LOADING_GIF, BACKGROUND).ok();
    log.mark(if frames.is_some() { "splash_frames_decoded" } else { "splash_frames_failed" });
    let state = STATE.get_or_init(|| {
        Mutex::new(WindowState {
            frames: None,
            fonts: [0; 3],
            frame: 0,
            frame_elapsed_ms: 0,
            tick: 0,
            scale_percent,
            log: log.clone(),
            close_reason: "exit",
        })
    });
    {
        let mut state = state.lock().unwrap_or_else(|p| p.into_inner());
        state.frames = frames;
        state.scale_percent = scale_percent;
        state.log = log.clone();
        // SAFETY: plain GDI font creation; the handles are deleted when the window is destroyed.
        state.fonts = unsafe {
            [
                create_font(scaled(22, scale_percent), FW_BOLD),
                create_font(scaled(13, scale_percent), FW_NORMAL),
                create_font(scaled(12, scale_percent), FW_NORMAL),
            ]
        };
    }
    // SAFETY: plain Win32 window creation and message loop on a thread dedicated to the window.
    unsafe {
        let instance = GetModuleHandleW(null());
        let class_name = wide(SPLASH_CLASS);
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
        RegisterClassW(&class);

        let (width, height) = (scaled(WIDTH, scale_percent), scaled(HEIGHT, scale_percent));
        let x = (GetSystemMetrics(SM_CXSCREEN) - width) / 2;
        let y = (GetSystemMetrics(SM_CYSCREEN) - height) / 2;
        let title = wide("Metroliza");
        let hwnd = CreateWindowExW(
            WS_EX_TOOLWINDOW,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_POPUP,
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
            let _ = ready.send(0);
            return;
        }
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

/// The launcher splash. Closing (explicitly or by drop) is idempotent and joins its thread.
pub struct Splash {
    thread: Mutex<Option<JoinHandle<()>>>,
    hwnd: isize,
}

impl Splash {
    /// Show the splash now; returns once its window exists (or failed), normally within a few
    /// milliseconds. `METROLIZA_LAUNCHER_SPLASH=0` returns an inert splash.
    pub fn show(log: &Log) -> Self {
        if std::env::var_os(SPLASH_ENV).is_some_and(|v| v == "0") {
            log.mark("splash_disabled");
            return Self { thread: Mutex::new(None), hwnd: 0 };
        }
        enable_dpi_awareness();
        set_status(STARTING, "");
        let (sender, receiver) = mpsc::channel();
        let thread_log = log.clone();
        let handle = std::thread::spawn(move || window_thread(sender, thread_log));
        let hwnd = receiver.recv_timeout(Duration::from_secs(2)).unwrap_or(0);
        log.mark(if hwnd != 0 { "splash_shown" } else { "splash_failed" });
        Self { thread: Mutex::new(Some(handle)), hwnd }
    }

    /// Value for [`SPLASH_HWND_ENV`] while the window is still open.
    pub fn handle_for_entry(&self) -> Option<String> {
        let current = WINDOW.load(Ordering::Acquire);
        (self.hwnd != 0 && current == self.hwnd).then(|| current.to_string())
    }

    /// Replace the status text (launcher-side phases such as a repair).
    pub fn status(&self, main: &str) {
        set_status(main, "");
    }

    /// Close the window if it is still open and wait for its thread.
    pub fn close(&self) {
        let hwnd = WINDOW.load(Ordering::Acquire);
        if hwnd != 0 && hwnd == self.hwnd {
            // SAFETY: posting to a window owned by another thread is allowed from any thread.
            unsafe { PostMessageW(hwnd as HWND, MSG_CLOSE, 0, 0) };
        }
        if let Some(handle) = self.thread.lock().unwrap_or_else(|p| p.into_inner()).take() {
            let _ = handle.join();
        }
    }
}

impl Drop for Splash {
    fn drop(&mut self) {
        self.close();
    }
}

impl Progress for Splash {
    fn begin(&self, total_bytes: u64) {
        DONE.store(0, Ordering::Relaxed);
        TOTAL.store(total_bytes, Ordering::Relaxed);
        BAR_MODE.store(1, Ordering::Relaxed);
        if let Some(state) = STATE.get() {
            state.lock().unwrap_or_else(|p| p.into_inner()).log.mark("runtime_work_begin");
        }
    }

    fn advance(&self, bytes: u64) {
        DONE.fetch_add(bytes, Ordering::Relaxed);
    }

    fn finish(&self) {
        BAR_MODE.store(0, Ordering::Relaxed);
        set_status(STARTING, "");
        if let Some(state) = STATE.get() {
            state.lock().unwrap_or_else(|p| p.into_inner()).log.mark("runtime_work_done");
        }
    }

    fn stage(&self, stage: Stage) {
        DONE.store(0, Ordering::Relaxed);
        BAR_MODE.store(1, Ordering::Relaxed);
        let (main, note, mark) = match stage {
            Stage::Verifying => (VERIFYING, "", "verify_begin"),
            Stage::Extracting => (EXTRACTING, EXTRACTING_NOTE, "extract_begin"),
        };
        set_status(main, note);
        if let Some(state) = STATE.get() {
            state.lock().unwrap_or_else(|p| p.into_inner()).log.mark(mark);
        }
    }

    fn verified(&self, bytes: u64) {
        DONE.fetch_add(bytes, Ordering::Relaxed);
    }
}
