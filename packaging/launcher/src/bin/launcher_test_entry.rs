//! Stand-in for `metroliza.exe` in synthetic payloads (qualification and tests).
//!
//! Options (all optional):
//!   --record FILE      append one line (this process id) when started
//!   --sleep-ms N       keep running for up to N milliseconds
//!   --stop-file FILE   end the sleep early once FILE exists
//!   --exit-code N      exit with code N (default 0)
//!   --print-cwd        write the working directory to FILE given by --record as a second line
#![windows_subsystem = "windows"]

use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::{Duration, Instant};

fn main() {
    let mut args = std::env::args().skip(1);
    let (mut record, mut stop_file) = (None::<PathBuf>, None::<PathBuf>);
    let (mut sleep_ms, mut exit_code, mut print_cwd) = (0u64, 0i32, false);
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--record" => record = args.next().map(PathBuf::from),
            "--stop-file" => stop_file = args.next().map(PathBuf::from),
            "--sleep-ms" => sleep_ms = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            "--exit-code" => exit_code = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            "--print-cwd" => print_cwd = true,
            _ => {}
        }
    }
    if let Some(path) = &record {
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(file, "started pid={}", std::process::id());
            if print_cwd {
                let cwd = std::env::current_dir().unwrap_or_default();
                let _ = writeln!(file, "cwd={}", cwd.display());
            }
        }
    }
    let deadline = Instant::now() + Duration::from_millis(sleep_ms);
    while Instant::now() < deadline && !stop_file.as_ref().is_some_and(|p| p.exists()) {
        std::thread::sleep(Duration::from_millis(20));
    }
    std::process::exit(exit_code);
}
