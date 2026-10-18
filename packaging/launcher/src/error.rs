//! Launcher errors and the fixed texts shown to users.
//!
//! Detailed errors (with paths and OS codes) are only ever written to the optional log file.
//! The user interface shows only the fixed strings from [`ErrorKind::user_message`].

use std::fmt;

/// Coarse failure class; decides the fixed user-facing text.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorKind {
    /// The appended payload is missing, truncated or fails validation.
    PayloadInvalid,
    /// No usable runtime directory could be prepared (permissions, redirected profile, ...).
    CacheUnavailable,
    /// Unpacking failed (disk full, security software, tampered payload, ...).
    ExtractionFailed,
    /// The entry executable could not be started.
    LaunchFailed,
}

impl ErrorKind {
    /// Fixed English text for the error dialog. Never contains paths, codes or raw errors.
    pub fn user_message(self) -> &'static str {
        match self {
            ErrorKind::PayloadInvalid => {
                "Metroliza could not read its own package. The file may be damaged. \
                 Please download Metroliza again."
            }
            ErrorKind::CacheUnavailable => {
                "Metroliza could not prepare its program folder. Please check that your user \
                 profile is writable and has free disk space, then try again."
            }
            ErrorKind::ExtractionFailed => {
                "Metroliza could not unpack its files. Please check free disk space and \
                 security software settings, then try again."
            }
            ErrorKind::LaunchFailed => {
                "Metroliza could not be started. Please try again, or download Metroliza again."
            }
        }
    }

    /// Process exit code used when the launcher itself fails (distinct from any app exit code
    /// the qualification expects, which are small non-negative numbers).
    pub fn exit_code(self) -> i32 {
        match self {
            ErrorKind::PayloadInvalid => 101,
            ErrorKind::CacheUnavailable => 102,
            ErrorKind::ExtractionFailed => 103,
            ErrorKind::LaunchFailed => 104,
        }
    }
}

/// Error with a class (for the UI) and a detail string (for the log only).
#[derive(Debug)]
pub struct LauncherError {
    pub kind: ErrorKind,
    pub detail: String,
}

impl LauncherError {
    pub fn new(kind: ErrorKind, detail: impl Into<String>) -> Self {
        Self {
            kind,
            detail: detail.into(),
        }
    }

    pub fn payload(detail: impl Into<String>) -> Self {
        Self::new(ErrorKind::PayloadInvalid, detail)
    }

    pub fn cache(detail: impl Into<String>) -> Self {
        Self::new(ErrorKind::CacheUnavailable, detail)
    }

    pub fn extraction(detail: impl Into<String>) -> Self {
        Self::new(ErrorKind::ExtractionFailed, detail)
    }

    pub fn launch(detail: impl Into<String>) -> Self {
        Self::new(ErrorKind::LaunchFailed, detail)
    }
}

impl fmt::Display for LauncherError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}: {}", self.kind, self.detail)
    }
}

impl std::error::Error for LauncherError {}

pub type Result<T> = std::result::Result<T, LauncherError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn user_messages_are_fixed_text_without_placeholders() {
        for kind in [
            ErrorKind::PayloadInvalid,
            ErrorKind::CacheUnavailable,
            ErrorKind::ExtractionFailed,
            ErrorKind::LaunchFailed,
        ] {
            let text = kind.user_message();
            assert!(!text.is_empty());
            assert!(!text.contains('{') && !text.contains('\\') && !text.contains(':'));
        }
    }

    #[test]
    fn exit_codes_are_distinct() {
        let codes = [
            ErrorKind::PayloadInvalid.exit_code(),
            ErrorKind::CacheUnavailable.exit_code(),
            ErrorKind::ExtractionFailed.exit_code(),
            ErrorKind::LaunchFailed.exit_code(),
        ];
        for (i, a) in codes.iter().enumerate() {
            for b in &codes[i + 1..] {
                assert_ne!(a, b);
            }
        }
    }
}
