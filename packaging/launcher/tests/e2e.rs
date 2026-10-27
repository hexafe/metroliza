//! End-to-end tests: pack a directory, then drive the cache and the real launcher binary.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, SystemTime};

use metroliza_launcher::archive::Payload;
use metroliza_launcher::cache::{
    cleanup_old_versions, ensure_runtime, is_warm, repair_runtime, NoProgress, Options, Outcome,
    MARKER, PENDING_MARKER,
};
use metroliza_launcher::pack::{pack, PackOptions};

const LAUNCHER: &str = env!("CARGO_BIN_EXE_metroliza-launcher");
const TEST_ENTRY: &str = env!("CARGO_BIN_EXE_launcher-test-entry");

/// Run `command`, retrying while the freshly packed executable is still "busy".
///
/// On Linux, a parallel test thread that forks between this test writing the EXE and executing
/// it briefly holds the write descriptor (until its child execs), so `execve` fails with
/// ETXTBSY ("Text file busy"). That is a test-harness race, not launcher behaviour.
fn status_retrying_busy(command: &mut Command) -> std::process::ExitStatus {
    for _ in 0..100 {
        match command.status() {
            Err(error) if error.kind() == std::io::ErrorKind::ExecutableFileBusy => {
                std::thread::sleep(Duration::from_millis(20));
            }
            result => return result.unwrap(),
        }
    }
    command.status().unwrap()
}

fn quick() -> Options {
    Options {
        threads: 4,
        sync_files: false,
    }
}

/// Create an onedir tree under `tmp` and pack it with `stub` into `<tmp>/<name>.exe`.
fn build(
    tmp: &Path,
    name: &str,
    version: &str,
    sha: &str,
    stub: &Path,
    entry_src: &Path,
) -> PathBuf {
    let input = tmp.join(format!("onedir-{name}"));
    fs::create_dir_all(input.join("lib/nested")).unwrap();
    fs::copy(entry_src, input.join("entry.exe")).unwrap();
    fs::write(
        input.join("lib/data.bin"),
        vec![version.len() as u8; 300_000],
    )
    .unwrap();
    fs::write(
        input.join("lib/nested/notes.txt"),
        format!("payload {version}"),
    )
    .unwrap();
    fs::write(input.join("lib/zero"), b"").unwrap();
    let output = tmp.join(format!("{name}.exe"));
    pack(&PackOptions {
        input_dir: input,
        entry: "entry.exe".into(),
        version: version.into(),
        content_key: false,
        git_sha: sha.into(),
        stub: stub.to_path_buf(),
        output: output.clone(),
    })
    .unwrap();
    output
}

fn set_completed(root: &Path, dir_name: &str, age_secs: u64) {
    let marker = fs::OpenOptions::new()
        .write(true)
        .open(
            root.join(dir_name)
                .join(if root.join(dir_name).join(MARKER).exists() {
                    MARKER
                } else {
                    PENDING_MARKER
                }),
        )
        .unwrap();
    marker
        .set_modified(SystemTime::now() - Duration::from_secs(age_secs))
        .unwrap();
}

#[test]
fn library_lifecycle_cold_warm_corrupt_repair_upgrade() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    fs::create_dir(&root).unwrap();
    let stub = tmp.path().join("stub.bin");
    fs::write(&stub, b"launcher stub").unwrap();

    let v1 = Payload::open(&build(tmp.path(), "v1", "1.0", "11111111", &stub, &stub)).unwrap();
    let r = ensure_runtime(&root, &v1, &NoProgress, &quick()).unwrap();
    assert_eq!(r.outcome, Outcome::Cold);
    let dir1 = r.dir.clone();
    drop(r);
    assert_eq!(
        ensure_runtime(&root, &v1, &NoProgress, &quick())
            .unwrap()
            .outcome,
        Outcome::Verified
    );
    set_completed(&root, "1.0_11111111", 300);
    assert_eq!(
        fs::read(dir1.join("lib/nested/notes.txt")).unwrap(),
        b"payload 1.0"
    );

    // Warm: marker mtime untouched.
    let mtime = fs::metadata(dir1.join(MARKER)).unwrap().modified().unwrap();
    let r = ensure_runtime(&root, &v1, &NoProgress, &quick()).unwrap();
    assert_eq!(r.outcome, Outcome::Warm);
    drop(r);
    assert_eq!(
        fs::metadata(dir1.join(MARKER)).unwrap().modified().unwrap(),
        mtime
    );

    // Corrupt: truncate one file, delete another; repair restores both.
    fs::write(dir1.join("lib/data.bin"), b"x").unwrap();
    fs::remove_file(dir1.join("lib/nested/notes.txt")).unwrap();
    assert!(!is_warm(&dir1, &v1));
    let r = ensure_runtime(&root, &v1, &NoProgress, &quick()).unwrap();
    assert_eq!(r.outcome, Outcome::Repaired);
    drop(r);
    assert_eq!(
        ensure_runtime(&root, &v1, &NoProgress, &quick())
            .unwrap()
            .outcome,
        Outcome::Verified
    );
    assert!(is_warm(&dir1, &v1));
    set_completed(&root, "1.0_11111111", 300);

    // Upgrade twice: only current and previous remain.
    for (name, version, sha, age) in [
        ("v2", "2.0", "22222222", 200),
        ("v3", "3.0", "33333333", 100),
    ] {
        let p = Payload::open(&build(tmp.path(), name, version, sha, &stub, &stub)).unwrap();
        let r = ensure_runtime(&root, &p, &NoProgress, &quick()).unwrap();
        assert_eq!(r.outcome, Outcome::Cold);
        let current = r.dir_name.clone();
        drop(r);
        set_completed(&root, &current, age);
        cleanup_old_versions(&root, &current);
    }
    assert!(
        !root.join("1.0_11111111").exists(),
        "oldest version removed"
    );
    assert!(root.join("2.0_22222222").exists(), "previous version kept");
    assert!(root.join("3.0_33333333").exists(), "current version kept");
}

/// Turn a packed, unsigned file into a "signed" one by announcing and appending a fake
/// certificate table, the way signtool lays out an Authenticode signature.
fn fake_sign(packed: &Path) {
    let mut bytes = fs::read(packed).unwrap();
    let cert_offset = bytes.len() as u32;
    let cert = vec![0xCE; 2048];
    // The stub is a synthetic PE32+ header: security directory entry lives at a known offset.
    let security_entry = 0x80 + 24 + 112 + 4 * 8;
    bytes[security_entry..security_entry + 4].copy_from_slice(&cert_offset.to_le_bytes());
    bytes[security_entry + 4..security_entry + 8]
        .copy_from_slice(&(cert.len() as u32).to_le_bytes());
    bytes.extend(cert);
    fs::write(packed, bytes).unwrap();
}

#[test]
fn signed_layout_still_extracts() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    fs::create_dir(&root).unwrap();

    // Synthetic PE32+ header without a certificate table, used as the stub.
    let pe_at = 0x80usize;
    let mut stub = vec![0u8; pe_at + 24 + 112 + 16 * 8];
    stub[0..2].copy_from_slice(b"MZ");
    stub[0x3C..0x40].copy_from_slice(&(pe_at as u32).to_le_bytes());
    stub[pe_at..pe_at + 4].copy_from_slice(b"PE\0\0");
    stub[pe_at + 24..pe_at + 26].copy_from_slice(&0x20Bu16.to_le_bytes());
    stub[pe_at + 24 + 108..pe_at + 24 + 112].copy_from_slice(&16u32.to_le_bytes());
    let stub_path = tmp.path().join("stub.exe");
    fs::write(&stub_path, &stub).unwrap();

    let packed = build(tmp.path(), "s", "1.0", "aaaaaaaa", &stub_path, &stub_path);
    fake_sign(&packed);
    let payload = Payload::open(&packed).unwrap();
    let r = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
    assert_eq!(r.outcome, Outcome::Cold);
    assert_eq!(
        fs::read(r.dir.join("lib/nested/notes.txt")).unwrap(),
        b"payload 1.0"
    );
}

struct Run {
    code: Option<i32>,
    log: String,
}

fn run_launcher(exe: &Path, root: &Path, log: &Path, args: &[&str]) -> Run {
    run_launcher_with(exe, root, log, args, &[])
}

fn run_launcher_with(
    exe: &Path,
    root: &Path,
    log: &Path,
    args: &[&str],
    env: &[(&str, &str)],
) -> Run {
    let _ = fs::remove_file(log);
    // The launcher runs in the directory that holds the EXE; the entry must inherit that
    // directory (see the cwd assertion in the first binary test), not the runtime cache.
    let status = status_retrying_busy(
        Command::new(exe)
            .args(args)
            .current_dir(exe.parent().unwrap())
            .env("METROLIZA_RUNTIME_ROOT", root)
            .env("METROLIZA_LAUNCHER_LOG", log)
            .env("METROLIZA_LAUNCHER_NO_UI", "1")
            .envs(env.iter().copied()),
    );
    Run {
        code: status.code(),
        log: fs::read_to_string(log).unwrap_or_default(),
    }
}

#[test]
fn launcher_binary_runs_entry_passes_args_and_exit_code_and_reuses_cache() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    let log = tmp.path().join("launcher.log");
    let record = tmp.path().join("record.txt");
    let exe = build(
        tmp.path(),
        "bin",
        "1.0-bin",
        "abcdef01",
        Path::new(LAUNCHER),
        Path::new(TEST_ENTRY),
    );
    let record_arg = record.to_str().unwrap();
    let args = ["--record", record_arg, "--print-cwd", "--exit-code", "7"];

    let cold = run_launcher(&exe, &root, &log, &args);
    assert_eq!(cold.code, Some(7), "entry exit code is passed through");
    assert!(cold.log.contains("cache=cold"), "{}", cold.log);
    assert!(
        cold.log.contains("entry=started") && cold.log.contains("exit=7"),
        "{}",
        cold.log
    );
    let recorded = fs::read_to_string(&record).unwrap();
    assert!(recorded.contains("started pid="), "{recorded}");
    let runtime_dir = root.join("1.0-bin_abcdef01");
    // The entry inherits the launcher's working directory. The runtime directory is a disposable
    // cache: a relative export name or a file dialog must never default into it.
    let cwd = recorded
        .lines()
        .find_map(|line| line.strip_prefix("cwd="))
        .expect("entry recorded its working directory");
    assert_eq!(
        fs::canonicalize(cwd).unwrap(),
        fs::canonicalize(exe.parent().unwrap()).unwrap(),
        "{recorded}"
    );
    assert_ne!(
        fs::canonicalize(cwd).unwrap(),
        fs::canonicalize(&runtime_dir).unwrap()
    );

    assert!(runtime_dir.join(PENDING_MARKER).is_file());
    let verified = run_launcher(&exe, &root, &log, &args);
    assert_eq!(verified.code, Some(7));
    assert!(verified.log.contains("cache=verified"), "{}", verified.log);
    assert!(!runtime_dir.join(PENDING_MARKER).exists());
    let marker_time = fs::metadata(runtime_dir.join(MARKER))
        .unwrap()
        .modified()
        .unwrap();
    let warm = run_launcher(&exe, &root, &log, &args);
    assert_eq!(warm.code, Some(7));
    assert!(warm.log.contains("cache=warm"), "{}", warm.log);
    assert_eq!(
        fs::metadata(runtime_dir.join(MARKER))
            .unwrap()
            .modified()
            .unwrap(),
        marker_time
    );

    fs::remove_file(runtime_dir.join("lib/data.bin")).unwrap();
    let repaired = run_launcher(&exe, &root, &log, &["--exit-code", "0"]);
    assert_eq!(repaired.code, Some(0));
    assert!(repaired.log.contains("cache=repair"), "{}", repaired.log);
    assert!(runtime_dir.join("lib/data.bin").exists());
}

#[test]
fn launcher_binary_reports_damaged_payload_with_distinct_exit_code() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    let log = tmp.path().join("launcher.log");
    let exe = build(
        tmp.path(),
        "bad",
        "1.0-bad",
        "abcdef01",
        Path::new(LAUNCHER),
        Path::new(TEST_ENTRY),
    );
    let mut bytes = fs::read(&exe).unwrap();
    let last = bytes.len() - 1;
    bytes[last] ^= 0xFF; // damage the trailer
    fs::write(&exe, bytes).unwrap();

    let run = run_launcher(&exe, &root, &log, &[]);
    assert_eq!(run.code, Some(101));
    assert!(run.log.contains("error=PayloadInvalid"), "{}", run.log);
    assert!(
        !root.exists(),
        "nothing created when the payload is invalid"
    );
}

#[test]
fn launcher_binary_does_not_use_temp_dir() {
    let tmp = tempfile::tempdir().unwrap();
    let scratch = tmp.path().join("scratch-temp");
    fs::create_dir(&scratch).unwrap();
    let root = tmp.path().join("root");
    let exe = build(
        tmp.path(),
        "t",
        "1.0-t",
        "abcdef01",
        Path::new(LAUNCHER),
        Path::new(TEST_ENTRY),
    );
    let status = status_retrying_busy(
        Command::new(&exe)
            .env("METROLIZA_RUNTIME_ROOT", &root)
            .env("METROLIZA_LAUNCHER_NO_UI", "1")
            .env("TMPDIR", &scratch)
            .env("TEMP", &scratch)
            .env("TMP", &scratch),
    );
    assert!(status.success());
    assert_eq!(
        fs::read_dir(&scratch).unwrap().count(),
        0,
        "launcher must not write to TEMP"
    );
}

/// Number of times the test entry started, and the repair variable it saw at each start.
fn starts(record: &Path) -> Vec<String> {
    fs::read_to_string(record)
        .unwrap_or_default()
        .lines()
        .filter(|line| line.starts_with("started "))
        .map(|line| line.rsplit("repair_available=").next().unwrap().to_string())
        .collect()
}

/// Fixture for the tests that run the real launcher binary.
///
/// Every such test packs its own version label (`1.0-<name>`): the single-instance guard is a
/// machine-wide named mutex per version on Windows, and cargo runs tests in parallel. With a
/// shared label the launchers of different tests see each other as "second instance" and exit 0
/// without starting the entry.
fn repair_fixture(name: &str) -> (tempfile::TempDir, PathBuf, PathBuf, PathBuf, PathBuf) {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    let log = tmp.path().join("launcher.log");
    let record = tmp.path().join("record.txt");
    let exe = build(
        tmp.path(),
        "repair",
        &format!("1.0-{name}"),
        "abcdef01",
        Path::new(LAUNCHER),
        Path::new(TEST_ENTRY),
    );
    (tmp, exe, root, log, record)
}

#[test]
fn exit_75_repairs_the_runtime_and_restarts_once_without_the_repair_variable() {
    let (_tmp, exe, root, log, record) = repair_fixture("repair");
    let record_arg = record.to_str().unwrap();
    let runtime_dir = root.join("1.0-repair_abcdef01");
    let data = runtime_dir.join("lib/data.bin");
    let args = [
        "--record",
        record_arg,
        "--record-file",
        data.to_str().unwrap(),
        "--request-repair",
        "--exit-code",
        "0",
    ];

    // Cold start: the entry sees the repair variable and asks for a repair on a runtime that
    // was just extracted, so the restart is the second and final start.
    let first = run_launcher(&exe, &root, &log, &args);
    assert_eq!(first.code, Some(0), "exit code of the restarted entry");
    assert_eq!(starts(&record), ["1", "unset"], "{}", first.log);
    assert!(first.log.contains("repair=requested"), "{}", first.log);
    assert!(first.log.contains("cache=cold"), "{}", first.log);
    assert!(first.log.contains("cache=repair"), "{}", first.log);
    assert!(first.log.contains("exit=0"), "{}", first.log);
    let original = fs::read(&data).unwrap();
    let verified = run_launcher(&exe, &root, &log, &["--exit-code", "0"]);
    assert!(verified.log.contains("cache=verified"));

    // Warm cache with a same-size modification the size-only warm check cannot see: the entry
    // sees the damaged file on the first start and the restored file on the second.
    let mut damaged = original.clone();
    damaged[0] ^= 0xFF;
    fs::write(&data, &damaged).unwrap();
    let _ = fs::remove_file(&record);
    let second = run_launcher(&exe, &root, &log, &args);
    assert_eq!(second.code, Some(0));
    assert!(second.log.contains("cache=warm"), "{}", second.log);
    assert!(second.log.contains("cache=repair"), "{}", second.log);
    assert_eq!(starts(&record), ["1", "unset"], "{}", second.log);
    let seen: Vec<String> = fs::read_to_string(&record)
        .unwrap()
        .lines()
        .filter(|l| l.starts_with("file "))
        .map(String::from)
        .collect();
    assert_eq!(seen.len(), 2, "{seen:?}");
    assert_ne!(
        seen[0], seen[1],
        "first start saw the damage, second did not"
    );
    assert_eq!(
        fs::read(&data).unwrap(),
        original,
        "runtime was re-extracted"
    );
    assert!(runtime_dir.join(PENDING_MARKER).is_file());
}

/// Launcher log lines: facts as written, timing marks as their event name
/// (`timing event=splash_show epoch_ms=...` becomes `splash_show`).
fn log_events(log: &str) -> Vec<String> {
    log.lines()
        .map(|line| match line.strip_prefix("timing event=") {
            Some(rest) => rest.split_whitespace().next().unwrap_or("").to_string(),
            None => line.to_string(),
        })
        .collect()
}

/// [`log_events`] after the first line equal to `from`.
fn log_after(log: &str, from: &str) -> Vec<String> {
    log_events(log)
        .into_iter()
        .skip_while(|line| line != from)
        .skip(1)
        .collect()
}

/// Whether `items` contains every entry of `wanted`, in this order.
fn in_order(items: &[String], wanted: &[&str]) -> bool {
    let mut rest = items.iter();
    wanted
        .iter()
        .all(|item| rest.by_ref().any(|seen| seen == item))
}

#[test]
fn exit_75_repair_shows_the_splash_or_progress_window_again_before_the_restart() {
    let (_tmp, exe, root, log, record) = repair_fixture("repair-feedback");
    let record_arg = record.to_str().unwrap();
    let args = ["--record", record_arg, "--request-repair", "--exit-code", "0"];

    // Cold, then warm: in both, the feedback hooks run again after the entry asked for the
    // repair, around the re-extraction and before the restarted entry starts.
    let cold = run_launcher(&exe, &root, &log, &args);
    let verified = run_launcher(&exe, &root, &log, &["--exit-code", "0"]);
    assert!(verified.log.contains("cache=verified"), "{}", verified.log);
    let _ = fs::remove_file(&record);
    let warm = run_launcher(&exe, &root, &log, &args);
    assert!(warm.log.contains("cache=warm"), "{}", warm.log);
    for run in [&cold, &warm] {
        assert_eq!(run.code, Some(0), "{}", run.log);
        let events = log_events(&run.log);
        let first_show = events.iter().position(|e| e == "splash_show");
        let instance = events.iter().position(|e| e == "instance_acquired");
        assert!(
            instance.is_some() && first_show > instance,
            "the splash is requested only after the instance check: {}",
            run.log
        );
        let after = log_after(&run.log, "repair=requested");
        assert!(
            in_order(
                &after,
                &[
                    "splash_reopen",
                    "splash_repairing",
                    "runtime_work_begin",
                    "runtime_work_done",
                    "cache=repair",
                    "entry=started",
                    "exit=0",
                ],
            ),
            "{}",
            run.log
        );
    }
    assert_eq!(starts(&record), ["1", "unset"]);
}

/// A second launcher of a running version only activates the first one: no splash, no progress
/// window, no cache work. Windows only: the stand-in has no single-instance guard.
#[cfg(windows)]
#[test]
fn a_second_instance_shows_no_splash_and_touches_no_cache() {
    let (tmp, exe, root, log, record) = repair_fixture("second-instance");
    let stop = tmp.path().join("stop-first");
    let first_log = tmp.path().join("first.log");
    let record_arg = record.to_str().unwrap();
    let stop_arg = stop.to_str().unwrap();
    let mut first = Command::new(&exe)
        .args(["--record", record_arg, "--stop-file", stop_arg, "--sleep-ms", "60000"])
        .current_dir(exe.parent().unwrap())
        .env("METROLIZA_RUNTIME_ROOT", &root)
        .env("METROLIZA_LAUNCHER_LOG", &first_log)
        .env("METROLIZA_LAUNCHER_NO_UI", "1")
        .spawn()
        .unwrap();
    let _stop = StopOrphan(stop.clone());
    wait_for_record(&record, "started");
    let second = run_launcher(&exe, &root, &log, &["--record", record_arg, "--sleep-ms", "0"]);
    fs::write(&stop, b"stop").unwrap();
    let first_status = first.wait().unwrap();

    assert_eq!(second.code, Some(0), "{}", second.log);
    assert!(second.log.contains("instance=second"), "{}", second.log);
    for forbidden in ["splash_", "runtime_work_", "progress_window_", "cache="] {
        assert!(!second.log.contains(forbidden), "{forbidden}: {}", second.log);
    }
    assert_eq!(starts(&record).len(), 1, "the second instance started no entry");
    let first_text = fs::read_to_string(&first_log).unwrap_or_default();
    assert!(first_text.contains("splash_show"), "{first_text}");
    assert_eq!(first_status.code(), Some(0), "{first_text}");
}

/// Every span of runtime work in `log` is covered by a window: the splash was open at its start
/// (then no progress window), or the progress window was shown and closed inside it.
#[cfg(windows)]
fn assert_runtime_work_had_a_window(log: &str) {
    let events = log_events(log);
    let mut splash_open = false;
    let mut in_work = false;
    let mut covered = false;
    let mut spans = 0;
    for event in &events {
        match event.as_str() {
            "splash_shown" => splash_open = true,
            e if e.starts_with("splash_closed_") => splash_open = false,
            // The window thread may log its close slightly after the launcher's next mark.
            "splash_reopen" => splash_open = false,
            "runtime_work_begin" => {
                assert!(!in_work, "nested runtime work: {log}");
                in_work = true;
                covered = splash_open;
            }
            "progress_window_shown" => {
                assert!(in_work && !covered, "progress window beside the splash: {log}");
                covered = true;
            }
            "runtime_work_done" => {
                assert!(in_work && covered, "runtime work without a window: {log}");
                in_work = false;
                spans += 1;
            }
            _ => {}
        }
    }
    assert!(!in_work && spans > 0, "{log}");
}

/// Splash disabled: extraction, verification and the exit-75 repair show the progress window.
#[cfg(windows)]
#[test]
fn a_disabled_splash_falls_back_to_the_progress_window() {
    let (_tmp, exe, root, log, record) = repair_fixture("progress-fallback");
    let disabled = [("METROLIZA_LAUNCHER_SPLASH", "0")];
    for expected in ["cache=cold", "cache=verified"] {
        let run = run_launcher_with(&exe, &root, &log, &["--exit-code", "0"], &disabled);
        assert_eq!(run.code, Some(0), "{}", run.log);
        assert!(run.log.contains(expected), "{}", run.log);
        assert!(
            in_order(
                &log_events(&run.log),
                &[
                    "splash_disabled",
                    "runtime_work_begin",
                    "progress_window_shown",
                    "progress_window_closed",
                    "runtime_work_done",
                    expected,
                ],
            ),
            "{}",
            run.log
        );
        assert!(!run.log.contains("splash_shown"), "{}", run.log);
        assert_runtime_work_had_a_window(&run.log);
    }
    let args = ["--record", record.to_str().unwrap(), "--request-repair", "--exit-code", "0"];
    let run = run_launcher_with(&exe, &root, &log, &args, &disabled);
    assert_eq!(run.code, Some(0), "{}", run.log);
    assert!(
        in_order(
            &log_after(&run.log, "repair=requested"),
            &["splash_reopen", "progress_window_shown", "progress_window_closed", "cache=repair"],
        ),
        "{}",
        run.log
    );
    assert_runtime_work_had_a_window(&run.log);
}

/// Each way the splash can fail (debug-build fault injection, see `splash_windows::fault`) ends
/// in the progress window covering the runtime work; a late window thread never shows its window.
/// Debug builds only: release builds compile the fault injection out.
#[cfg(all(windows, debug_assertions))]
#[test]
fn every_splash_failure_falls_back_to_the_progress_window() {
    let faults = [
        ("decode", "splash_frames_failed"),
        ("class", "splash_class_failed"),
        ("window", "splash_window_failed"),
        ("thread", "splash_thread_failed"),
        ("late", "splash_late_abandoned"),
    ];
    for (fault, failure_mark) in faults {
        let (_tmp, exe, root, log, _record) = repair_fixture(&format!("fault-{fault}"));
        // `late`: the window thread creates its window 3 s after `show`; the entry keeps the
        // launcher alive past that, so the thread's outcome is in the log.
        let args: &[&str] = if fault == "late" {
            &["--sleep-ms", "6000", "--exit-code", "0"]
        } else {
            &["--exit-code", "0"]
        };
        let env = [("METROLIZA_LAUNCHER_SPLASH_FAULT", fault)];
        let run = run_launcher_with(&exe, &root, &log, args, &env);
        assert_eq!(run.code, Some(0), "{fault}: {}", run.log);
        assert!(run.log.contains("cache=cold"), "{fault}: {}", run.log);
        let events = log_events(&run.log);
        assert!(
            in_order(
                &events,
                &[
                    "splash_show",
                    failure_mark,
                    "runtime_work_begin",
                    "progress_window_shown",
                    "progress_window_closed",
                    "runtime_work_done",
                    "cache=cold",
                ],
            ),
            "{fault}: {}",
            run.log
        );
        for never in ["splash_shown", "splash_painted"] {
            assert!(!run.log.contains(never), "{fault} {never}: {}", run.log);
        }
        assert_runtime_work_had_a_window(&run.log);
        if fault == "late" {
            assert!(
                in_order(&events, &["splash_late_abandoned", "splash_abandoned_window_destroyed"]),
                "the late thread's window is destroyed without being shown: {}",
                run.log
            );
        }
    }
}

/// Splash enabled: cold, verified and repair work is covered by the splash or, if the splash
/// could not be shown on this desktop, by the progress window; never by both, never by none.
#[cfg(windows)]
#[test]
fn runtime_work_always_has_a_window_with_the_splash_enabled() {
    let (_tmp, exe, root, log, record) = repair_fixture("splash-coverage");
    for expected in ["cache=cold", "cache=verified"] {
        let run = run_launcher(&exe, &root, &log, &["--exit-code", "0"]);
        assert_eq!(run.code, Some(0), "{}", run.log);
        assert!(run.log.contains(expected), "{}", run.log);
        assert_runtime_work_had_a_window(&run.log);
    }
    let args = ["--record", record.to_str().unwrap(), "--request-repair", "--exit-code", "0"];
    let run = run_launcher(&exe, &root, &log, &args);
    assert_eq!(run.code, Some(0), "{}", run.log);
    assert!(run.log.contains("cache=repair"), "{}", run.log);
    assert_runtime_work_had_a_window(&run.log);
}

#[test]
fn warm_same_length_entry_damage_repairs_once_even_if_restarted_entry_exits_75() {
    let (_tmp, exe, root, log, record) = repair_fixture("spawn-damage");
    assert_eq!(run_launcher(&exe, &root, &log, &[]).code, Some(0));
    let verified = run_launcher(&exe, &root, &log, &[]);
    assert!(verified.log.contains("cache=verified"), "{}", verified.log);
    let payload = Payload::open(&exe).unwrap();
    let dir = root.join("1.0-spawn-damage_abcdef01");
    let entry = dir.join("entry.exe");
    let original = fs::read(&entry).unwrap();
    // All-zero bytes of the same length are neither ELF nor PE. The completed cache still
    // passes the size-only warm check, but the OS cannot spawn its entry executable.
    fs::write(&entry, vec![0; original.len()]).unwrap();
    assert!(is_warm(&dir, &payload));

    let run = run_launcher(
        &exe,
        &root,
        &log,
        &["--record", record.to_str().unwrap(), "--exit-code", "75"],
    );
    assert_eq!(run.code, Some(75), "{}", run.log);
    assert!(run.log.contains("cache=warm"), "{}", run.log);
    assert!(
        run.log.contains("repair=spawn_failed error=LaunchFailed"),
        "{}",
        run.log
    );
    assert_eq!(run.log.matches("repair=").count(), 1, "{}", run.log);
    assert_eq!(run.log.matches("cache=repair").count(), 1, "{}", run.log);
    assert_eq!(starts(&record), ["unset"], "{}", run.log);
    assert_eq!(run.log.matches("entry=started").count(), 1, "{}", run.log);
    assert_eq!(
        run.log.matches("cleanup removed=").count(),
        1,
        "{}",
        run.log
    );
    assert!(run.log.contains("exit=75"), "{}", run.log);
    assert_eq!(fs::read(&entry).unwrap(), original, "entry restored");
    assert!(dir.join(PENDING_MARKER).is_file());
    assert!(!dir.join(MARKER).exists());
}

#[test]
fn persistent_spawn_failure_after_repair_returns_error_without_another_repair() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    fs::create_dir(&root).unwrap();
    let log = tmp.path().join("launcher.log");
    let invalid = tmp.path().join("invalid.exe");
    // Even a successful re-extraction cannot make this payload's entry a valid executable.
    fs::write(&invalid, vec![0; 4096]).unwrap();
    let exe = build(
        tmp.path(),
        "invalid-entry",
        "1.0-spawn-persistent",
        "abcdef01",
        Path::new(LAUNCHER),
        &invalid,
    );
    let payload = Payload::open(&exe).unwrap();
    drop(ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap());
    let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
    assert_eq!(runtime.outcome, Outcome::Verified);
    let dir = runtime.dir.clone();
    drop(runtime);
    assert!(is_warm(&dir, &payload));

    let run = run_launcher(&exe, &root, &log, &[]);
    assert_eq!(run.code, Some(104), "{}", run.log);
    assert!(run.log.contains("cache=warm"), "{}", run.log);
    assert_eq!(
        run.log.matches("repair=spawn_failed").count(),
        1,
        "{}",
        run.log
    );
    assert_eq!(run.log.matches("repair=").count(), 1, "{}", run.log);
    assert_eq!(run.log.matches("cache=repair").count(), 1, "{}", run.log);
    // The spawn-failure repair is announced as a repair, around its runtime work.
    let after_failure: Vec<String> = log_events(&run.log)
        .into_iter()
        .skip_while(|line| !line.starts_with("repair=spawn_failed"))
        .collect();
    assert!(
        in_order(
            &after_failure,
            &["splash_repairing", "runtime_work_begin", "runtime_work_done", "cache=repair"],
        ),
        "{}",
        run.log
    );
    assert_eq!(
        run.log.matches("error=LaunchFailed").count(),
        2,
        "{}",
        run.log
    );
    assert!(!run.log.contains("entry=started"), "{}", run.log);
    assert!(!run.log.contains("cleanup removed="), "{}", run.log);
    assert!(dir.join(PENDING_MARKER).is_file());
    assert!(!dir.join(MARKER).exists());
}

// Build a payload that passes hash verification but cannot be spawned by the OS.
fn unspawnable_fixture(name: &str, bytes: &[u8]) -> (tempfile::TempDir, PathBuf, PathBuf, PathBuf) {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    fs::create_dir(&root).unwrap();
    let log = tmp.path().join("launcher.log");
    let invalid = tmp.path().join("invalid.exe");
    fs::write(&invalid, bytes).unwrap();
    let exe = build(
        tmp.path(),
        "invalid-entry",
        &format!("1.0-{name}"),
        "abcdef01",
        Path::new(LAUNCHER),
        &invalid,
    );
    (tmp, exe, root, log)
}

fn freshly_checked_spawn_failure_does_not_repair(outcome: &str) {
    let label = format!("spawn-checked-{outcome}");
    let (_tmp, exe, root, log) = unspawnable_fixture(&label, &[0; 4096]);
    let dir = root.join(format!("1.0-{label}_abcdef01"));
    if outcome != "cold" {
        let payload = Payload::open(&exe).unwrap();
        drop(ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap());
        assert!(dir.join(PENDING_MARKER).is_file());
        if outcome == "repair" {
            fs::remove_file(dir.join(PENDING_MARKER)).unwrap();
        }
    }
    // Hashes match the payload even though its entry is not a valid executable.
    let run = run_launcher(&exe, &root, &log, &[]);
    assert_eq!(run.code, Some(104), "{}", run.log);
    assert!(run.log.contains(&format!("cache={outcome}")), "{}", run.log);
    assert!(!run.log.contains("repair="), "{}", run.log);
    assert_eq!(
        run.log.matches("error=LaunchFailed").count(),
        1,
        "{}",
        run.log
    );
    assert!(!run.log.contains("entry=started"), "{}", run.log);
    assert!(!run.log.contains("cleanup removed="), "{}", run.log);
    assert_eq!(dir.join(PENDING_MARKER).exists(), outcome != "verified");
    assert_eq!(dir.join(MARKER).exists(), outcome == "verified");
}

#[test]
fn cold_spawn_failure_does_not_repair() {
    freshly_checked_spawn_failure_does_not_repair("cold");
}

#[test]
fn verified_pending_spawn_failure_does_not_repair() {
    freshly_checked_spawn_failure_does_not_repair("verified");
}

#[test]
fn repaired_spawn_failure_does_not_repair_again() {
    freshly_checked_spawn_failure_does_not_repair("repair");
}

#[cfg(unix)]
#[test]
fn warm_permission_denied_spawn_does_not_repair() {
    // The Unix stand-in chmods the entry before spawning. A directory as the script's
    // interpreter reliably yields EACCES even after that chmod, without a privileged test.
    // Windows policy/access-denial codes are covered by the spawn policy unit test there.
    let (_tmp, exe, root, log) = unspawnable_fixture("spawn-denied", b"#!/\n");
    let payload = Payload::open(&exe).unwrap();
    drop(ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap());
    let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
    assert_eq!(runtime.outcome, Outcome::Verified);
    let dir = runtime.dir.clone();
    drop(runtime);
    let marker = fs::read(dir.join(MARKER)).unwrap();
    let error = metroliza_launcher::platform::spawn_entry(&dir.join("entry.exe"), &[], None)
        .err()
        .unwrap();
    assert!(error.detail.contains("os error 13"), "{error}");

    let run = run_launcher(&exe, &root, &log, &[]);
    assert_eq!(run.code, Some(104), "{}", run.log);
    assert!(run.log.contains("cache=warm"), "{}", run.log);
    assert!(!run.log.contains("repair="), "{}", run.log);
    assert_eq!(
        run.log.matches("error=LaunchFailed").count(),
        1,
        "{}",
        run.log
    );
    assert!(!run.log.contains("entry=started"), "{}", run.log);
    assert!(!run.log.contains("cleanup removed="), "{}", run.log);
    assert_eq!(fs::read(dir.join(MARKER)).unwrap(), marker);
    assert!(!dir.join(PENDING_MARKER).exists());
}

#[cfg(unix)]
#[test]
fn failed_spawn_repair_preserves_original_launch_error() {
    use std::os::unix::fs::PermissionsExt;
    let (_tmp, exe, root, log) = unspawnable_fixture("spawn-repair-fails", &[0; 4096]);
    let payload = Payload::open(&exe).unwrap();
    drop(ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap());
    let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
    let dir = runtime.dir.clone();
    drop(runtime);
    // Prevent marker invalidation/removal after a repairable ENOEXEC on a Warm cache.
    fs::set_permissions(&dir, fs::Permissions::from_mode(0o555)).unwrap();
    let run = run_launcher(&exe, &root, &log, &[]);
    fs::set_permissions(&dir, fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(run.code, Some(104), "{}", run.log);
    assert!(run.log.contains("cache=warm"), "{}", run.log);
    assert_eq!(
        run.log.matches("repair=spawn_failed").count(),
        1,
        "{}",
        run.log
    );
    assert!(
        run.log.contains("repair_error=CacheUnavailable"),
        "{}",
        run.log
    );
    assert_eq!(
        run.log.matches("error=LaunchFailed").count(),
        2,
        "{}",
        run.log
    );
    assert!(!run.log.contains("entry=started"), "{}", run.log);
}

#[test]
fn a_second_exit_75_is_final_and_does_not_loop() {
    let (_tmp, exe, root, log, record) = repair_fixture("twice");
    let record_arg = record.to_str().unwrap();
    // Without --request-repair the entry exits 75 on both starts, whatever the variable says.
    let run = run_launcher(
        &exe,
        &root,
        &log,
        &["--record", record_arg, "--exit-code", "75"],
    );
    assert_eq!(run.code, Some(75), "the second run's exit code is returned");
    assert_eq!(
        starts(&record),
        ["1", "unset"],
        "exactly two starts: {}",
        run.log
    );
    assert_eq!(
        run.log.matches("repair=requested").count(),
        1,
        "{}",
        run.log
    );
    assert_eq!(run.log.matches("entry=started").count(), 2, "{}", run.log);
    assert!(run.log.contains("exit=75"), "{}", run.log);
}

#[test]
fn other_exit_codes_pass_through_without_a_repair_or_restart() {
    let (_tmp, exe, root, log, record) = repair_fixture("passthrough");
    let record_arg = record.to_str().unwrap();
    for code in ["0", "1", "74", "76", "255"] {
        let _ = fs::remove_file(&record);
        let run = run_launcher(
            &exe,
            &root,
            &log,
            &["--record", record_arg, "--exit-code", code],
        );
        assert_eq!(run.code, Some(code.parse().unwrap()), "exit code {code}");
        assert_eq!(
            starts(&record),
            ["1"],
            "single start for {code}: {}",
            run.log
        );
        assert!(!run.log.contains("repair="), "{}", run.log);
        assert_eq!(run.log.matches("entry=started").count(), 1, "{}", run.log);
    }
}

#[test]
fn a_repair_variable_inherited_from_the_parent_never_reaches_the_restart() {
    let (_tmp, exe, root, log, record) = repair_fixture("inherited");
    let record_arg = record.to_str().unwrap();
    let _ = fs::remove_file(&log);
    let status = status_retrying_busy(
        Command::new(&exe)
            .args([
                "--record",
                record_arg,
                "--request-repair",
                "--exit-code",
                "3",
            ])
            .env("METROLIZA_RUNTIME_ROOT", &root)
            .env("METROLIZA_LAUNCHER_LOG", &log)
            .env("METROLIZA_LAUNCHER_NO_UI", "1")
            .env("METROLIZA_RUNTIME_REPAIR_AVAILABLE", "0"),
    );
    assert_eq!(status.code(), Some(3));
    assert_eq!(starts(&record), ["1", "unset"]);
}

#[test]
fn library_repair_runtime_rebuilds_a_warm_runtime() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    fs::create_dir(&root).unwrap();
    let stub = tmp.path().join("stub.bin");
    fs::write(&stub, b"launcher stub").unwrap();
    let payload = Payload::open(&build(tmp.path(), "v1", "1.0", "11111111", &stub, &stub)).unwrap();

    let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
    assert_eq!(runtime.outcome, Outcome::Cold);
    let dir = runtime.dir.clone();
    assert_eq!(
        ensure_runtime(&root, &payload, &NoProgress, &quick())
            .unwrap()
            .outcome,
        Outcome::Verified
    );
    let mut bytes = fs::read(dir.join("lib/data.bin")).unwrap();
    bytes[10] ^= 0xFF; // same size: the warm check cannot see it
    fs::write(dir.join("lib/data.bin"), &bytes).unwrap();
    assert!(is_warm(&dir, &payload));

    let repaired = repair_runtime(&root, &payload, runtime, &NoProgress, &quick()).unwrap();
    assert_eq!(repaired.outcome, Outcome::Repaired);
    assert_eq!(repaired.dir, dir);
    assert_ne!(fs::read(dir.join("lib/data.bin")).unwrap(), bytes);
    assert_eq!(
        ensure_runtime(&root, &payload, &NoProgress, &quick())
            .unwrap()
            .outcome,
        Outcome::Verified
    );
    assert!(is_warm(&dir, &payload));
}

fn wait_for_record(record: &Path, text: &str) {
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    while !fs::read_to_string(record)
        .unwrap_or_default()
        .contains(text)
    {
        assert!(std::time::Instant::now() < deadline, "missing {text}");
        std::thread::sleep(Duration::from_millis(20));
    }
}

struct StopOrphan(PathBuf);
impl Drop for StopOrphan {
    fn drop(&mut self) {
        let _ = fs::write(&self.0, b"stop");
    }
}

#[test]
fn cleanup_preserves_orphan_after_supervisor_and_launcher_exit() {
    let (tmp, exe, root, log, record) = repair_fixture("orphan");
    let stop = tmp.path().join("stop-orphan");
    let _stop_on_failure = StopOrphan(stop.clone());
    let run = run_launcher(
        &exe,
        &root,
        &log,
        &[
            "--spawn-orphan",
            "--record",
            record.to_str().unwrap(),
            "--stop-file",
            stop.to_str().unwrap(),
            // The test ends the orphan through --stop-file; this bound only caps a failed
            // run. 15 s was shorter than packing two payloads on a slow CI runner, so the orphan
            // could exit before cleanup and the in-use assertion failed (run 39164218530).
            "--sleep-ms",
            "120000",
        ],
    );
    assert_eq!(run.code, Some(0)); // both supervisor and launcher are gone
    wait_for_record(&record, "started");
    let orphan_name = "1.0-orphan_abcdef01";
    let orphan_dir = root.join(orphan_name);
    let original_marker = fs::read(orphan_dir.join(PENDING_MARKER)).unwrap();
    let original_data = fs::read(orphan_dir.join("lib/data.bin")).unwrap();
    set_completed(&root, orphan_name, 300);
    let mut current = String::new();
    for (name, version, sha, age) in [
        ("new2", "2.0", "22222222", 200),
        ("new3", "3.0", "33333333", 100),
    ] {
        let payload = Payload::open(&build(
            tmp.path(),
            name,
            version,
            sha,
            Path::new(LAUNCHER),
            Path::new(TEST_ENTRY),
        ))
        .unwrap();
        let runtime = ensure_runtime(&root, &payload, &NoProgress, &quick()).unwrap();
        current = runtime.dir_name.clone();
        drop(runtime);
        set_completed(&root, &current, age);
    }
    let report = cleanup_old_versions(&root, &current);
    assert_eq!(report.skipped_in_use, vec![orphan_name]);
    assert_eq!(
        fs::read(orphan_dir.join(PENDING_MARKER)).unwrap(),
        original_marker
    );
    assert_eq!(
        fs::read(orphan_dir.join("lib/data.bin")).unwrap(),
        original_data
    );
    assert!(!fs::read_to_string(&record).unwrap().contains("stopped"));
    // A second launch of an orphan's pending cache must also avoid destructive repair if
    // verification cannot trust it. This exercises the shared pre-deletion protection.
    let payload = Payload::open(&exe).unwrap();
    fs::write(orphan_dir.join("lib/data.bin"), b"damaged").unwrap();
    assert!(ensure_runtime(&root, &payload, &NoProgress, &quick()).is_err());
    assert_eq!(
        fs::read(orphan_dir.join(PENDING_MARKER)).unwrap(),
        original_marker
    );
    fs::write(&stop, b"stop").unwrap();
    wait_for_record(&record, "stopped");
    // The process may still be returning from main after writing the record.
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    while orphan_dir.exists() {
        cleanup_old_versions(&root, &current);
        assert!(
            std::time::Instant::now() < deadline,
            "orphan not reclaimed after exit"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
}

#[test]
fn pending_corrupt_entry_is_repaired_before_it_can_start() {
    for victim in ["entry.exe", "lib/nested/notes.txt"] {
        let (_tmp, exe, root, log, _record) = repair_fixture(if victim == "entry.exe" {
            "pending-entry"
        } else {
            "pending-resource"
        });
        assert_eq!(run_launcher(&exe, &root, &log, &[]).code, Some(0));
        let dir = fs::read_dir(&root)
            .unwrap()
            .flatten()
            .find(|e| e.path().is_dir())
            .unwrap()
            .path();
        let original = fs::read(dir.join(victim)).unwrap();
        fs::write(dir.join(victim), vec![0; original.len()]).unwrap();
        let run = run_launcher(&exe, &root, &log, &[]);
        assert_eq!(run.code, Some(0), "{}", run.log);
        assert!(run.log.contains("cache=repair"), "{}", run.log);
        assert!(!run.log.contains("repair=requested")); // damaged EXE cannot request anything
        assert_eq!(fs::read(dir.join(victim)).unwrap(), original);
        assert!(dir.join(PENDING_MARKER).exists());
        assert!(!dir.join(MARKER).exists());
    }
}
