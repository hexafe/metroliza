//! Metroliza native launcher: library half.
//!
//! The launcher is a small executable with a compressed onedir payload appended to it. At first
//! start of a version it unpacks the payload once into a persistent, versioned per-user cache;
//! every later start only validates that cache and runs the entry executable from it.
//!
//! Everything except the thin Win32 layer in [`platform`] is platform independent and unit-tested
//! on Linux. See `packaging/launcher/README.md` for the format and the cache state machine.

pub mod app;
pub mod archive;
pub mod cache;
pub mod cmdline;
pub mod error;
pub mod fsutil;
pub mod log;
pub mod manifest;
pub mod pack;
pub mod platform;
pub mod splash_frames;
pub mod trailer;

/// Lowercase hexadecimal encoding of `bytes`.
pub fn to_hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        // Writing to a String cannot fail.
        let _ = write!(out, "{byte:02x}");
    }
    out
}
