//! Stand-in for `metroliza.exe` in synthetic payloads (qualification and tests).
//!
//! Options (all optional):
//!   --record FILE      append one line (this process id and the repair variable) when started
//!   --sleep-ms N       keep running for up to N milliseconds
//!   --stop-file FILE   end the sleep early once FILE exists
//!   --exit-code N      exit with code N (default 0)
//!   --print-cwd        write the working directory to FILE given by --record as a second line
//!   --record-file REL  also record the length and first byte of REL (relative to the working
//!                      directory) so a test can see which version of a file this start saw
//!   --request-repair   exit with 75 (the self-repair request) while
//!                      METROLIZA_RUNTIME_REPAIR_AVAILABLE is "1"; otherwise exit with
//!                      --exit-code. Behaves like a supervisor that rejected its package and
//!                      was told that the launcher can repair it.
#![windows_subsystem = "windows"]

use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::{Duration, Instant};

const REPAIR_AVAILABLE_ENV: &str = "METROLIZA_RUNTIME_REPAIR_AVAILABLE";

fn main() {
    let mut args = std::env::args().skip(1);
    let (mut record, mut stop_file) = (None::<PathBuf>, None::<PathBuf>);
    let (mut sleep_ms, mut exit_code, mut print_cwd) = (0u64, 0i32, false);
    let (mut record_file, mut request_repair) = (None::<PathBuf>, false);
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--record" => record = args.next().map(PathBuf::from),
            "--stop-file" => stop_file = args.next().map(PathBuf::from),
            "--sleep-ms" => sleep_ms = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            "--exit-code" => exit_code = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            "--print-cwd" => print_cwd = true,
            "--record-file" => record_file = args.next().map(PathBuf::from),
            "--request-repair" => request_repair = true,
            _ => {}
        }
    }
    let repair_variable = std::env::var(REPAIR_AVAILABLE_ENV).ok();
    if let Some(path) = &record {
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(
                file,
                "started pid={} repair_available={}",
                std::process::id(),
                repair_variable.as_deref().unwrap_or("unset")
            );
            if print_cwd {
                let cwd = std::env::current_dir().unwrap_or_default();
                let _ = writeln!(file, "cwd={}", cwd.display());
            }
            if let Some(relative) = &record_file {
                match std::fs::read(relative) {
                    Ok(bytes) => {
                        let _ = writeln!(
                            file,
                            "file len={} first={}",
                            bytes.len(),
                            bytes.first().copied().unwrap_or(0)
                        );
                    }
                    Err(_) => {
                        let _ = writeln!(file, "file missing");
                    }
                }
            }
        }
    }
    if request_repair && repair_variable.as_deref() == Some("1") {
        std::process::exit(75);
    }
    let deadline = Instant::now() + Duration::from_millis(sleep_ms);
    while Instant::now() < deadline && !stop_file.as_ref().is_some_and(|p| p.exists()) {
        std::thread::sleep(Duration::from_millis(20));
    }
    std::process::exit(exit_code);
}
