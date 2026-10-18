//! Optional diagnostic log for qualification and support.
//!
//! The launcher has no console and must not write to `%TEMP%`, so logging is off unless
//! `METROLIZA_LAUNCHER_LOG` names a file. Lines are `key=value` facts such as `cache=warm`;
//! the qualification script relies on them. Detailed error text goes here, never to the UI.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;

pub const LOG_ENV: &str = "METROLIZA_LAUNCHER_LOG";

pub struct Log {
    path: Option<PathBuf>,
}

impl Log {
    pub fn from_env() -> Self {
        Self {
            path: std::env::var_os(LOG_ENV)
                .filter(|v| !v.is_empty())
                .map(PathBuf::from),
        }
    }

    pub fn to_file(path: PathBuf) -> Self {
        Self { path: Some(path) }
    }

    /// Append one line; failures are ignored (logging must never affect launching).
    pub fn line(&self, text: &str) {
        let Some(path) = &self.path else { return };
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(file, "{text}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn appends_lines_and_is_silent_without_a_path() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("l.log");
        let log = Log::to_file(path.clone());
        log.line("cache=cold");
        log.line("cache=warm");
        assert_eq!(
            std::fs::read_to_string(path).unwrap(),
            "cache=cold\ncache=warm\n"
        );
        Log { path: None }.line("ignored");
    }
}
