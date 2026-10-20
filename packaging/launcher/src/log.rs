//! Optional diagnostic log for qualification and support.
//!
//! The launcher has no console and must not write to `%TEMP%`, so logging is off unless
//! `METROLIZA_LAUNCHER_LOG` names a file. Lines are `key=value` facts such as `cache=warm`;
//! the qualification script relies on them. Detailed error text goes here, never to the UI.
//! Timing lines (`timing event=<name> epoch_ms=<ms>`) mark launch phases for the startup
//! timeline; consumers that look for `cache=` or `instance=` lines are unaffected.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

pub const LOG_ENV: &str = "METROLIZA_LAUNCHER_LOG";

#[derive(Clone)]
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

    /// Append a timing line for `event` with the wall-clock time in milliseconds since the Unix
    /// epoch (comparable with the application's startup profile `epoch_ms`).
    pub fn mark(&self, event: &str) {
        if self.path.is_none() {
            return;
        }
        let epoch_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0.0, |d| d.as_secs_f64() * 1000.0);
        self.line(&format!("timing event={event} epoch_ms={epoch_ms:.3}"));
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
        Log { path: None }.mark("ignored");
    }

    #[test]
    fn timing_lines_do_not_look_like_facts() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("t.log");
        let log = Log::to_file(path.clone());
        log.mark("main");
        log.line("cache=warm");
        let text = std::fs::read_to_string(path).unwrap();
        let mut lines = text.lines();
        let timing = lines.next().unwrap();
        assert!(timing.starts_with("timing event=main epoch_ms="), "{timing}");
        assert!(!timing.starts_with("cache="));
        assert_eq!(lines.next(), Some("cache=warm"));
    }
}
