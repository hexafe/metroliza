//! Operating-system layer: single-instance guard, splash (with the progress window as its
//! fallback), error dialog, entry process.
//!
//! Windows has the real implementation (`windows.rs`, Win32 through `windows-sys`). Other
//! platforms get a minimal stand-in (`other.rs`) so the library and the launcher binary build
//! and can be exercised end to end on Linux; it provides no single-instance guard and no UI.

#[cfg(windows)]
mod splash_windows;
#[cfg(windows)]
mod windows;
#[cfg(windows)]
pub use self::splash_windows::{Splash, SPLASH_CLASS, SPLASH_HWND_ENV};
#[cfg(windows)]
pub use self::windows::*;

#[cfg(not(windows))]
mod other;
#[cfg(not(windows))]
pub use self::other::*;

/// Result of trying to become the one running instance of a version.
pub enum Instance {
    /// This process is the first; keep the guard alive for the whole run.
    First(InstanceGuard),
    /// Another launcher of the same version is already running.
    Existing,
}
