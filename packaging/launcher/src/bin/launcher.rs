//! Metroliza launcher entry point (no console window on Windows).
#![windows_subsystem = "windows"]

fn main() {
    std::process::exit(metroliza_launcher::app::run());
}
