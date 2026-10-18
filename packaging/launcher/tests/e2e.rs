//! End-to-end tests: pack a directory, then drive the cache and the real launcher binary.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, SystemTime};

use metroliza_launcher::archive::Payload;
use metroliza_launcher::cache::{
    cleanup_old_versions, ensure_runtime, is_warm, repair_runtime, NoProgress, Options, Outcome,
    MARKER,
};
use metroliza_launcher::pack::{pack, PackOptions};

const LAUNCHER: &str = env!("CARGO_BIN_EXE_metroliza-launcher");
const TEST_ENTRY: &str = env!("CARGO_BIN_EXE_launcher-test-entry");

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
        .open(root.join(dir_name).join(MARKER))
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
    let _ = fs::remove_file(log);
    let status = Command::new(exe)
        .args(args)
        .env("METROLIZA_RUNTIME_ROOT", root)
        .env("METROLIZA_LAUNCHER_LOG", log)
        .env("METROLIZA_LAUNCHER_NO_UI", "1")
        .status()
        .unwrap();
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
        "1.0",
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
    let runtime_dir = root.join("1.0_abcdef01");
    assert!(
        recorded.contains(&format!("cwd={}", runtime_dir.display())),
        "{recorded}"
    );

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
        "1.0",
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
        "1.0",
        "abcdef01",
        Path::new(LAUNCHER),
        Path::new(TEST_ENTRY),
    );
    let status = Command::new(&exe)
        .env("METROLIZA_RUNTIME_ROOT", &root)
        .env("METROLIZA_LAUNCHER_NO_UI", "1")
        .env("TMPDIR", &scratch)
        .env("TEMP", &scratch)
        .env("TMP", &scratch)
        .status()
        .unwrap();
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

fn repair_fixture() -> (tempfile::TempDir, PathBuf, PathBuf, PathBuf, PathBuf) {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("root");
    let log = tmp.path().join("launcher.log");
    let record = tmp.path().join("record.txt");
    let exe = build(
        tmp.path(),
        "repair",
        "1.0",
        "abcdef01",
        Path::new(LAUNCHER),
        Path::new(TEST_ENTRY),
    );
    (tmp, exe, root, log, record)
}

#[test]
fn exit_75_repairs_the_runtime_and_restarts_once_without_the_repair_variable() {
    let (_tmp, exe, root, log, record) = repair_fixture();
    let record_arg = record.to_str().unwrap();
    let runtime_dir = root.join("1.0_abcdef01");
    let data = runtime_dir.join("lib/data.bin");
    let args = [
        "--record",
        record_arg,
        "--record-file",
        "lib/data.bin",
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
    assert!(runtime_dir.join(MARKER).is_file());
}

#[test]
fn a_second_exit_75_is_final_and_does_not_loop() {
    let (_tmp, exe, root, log, record) = repair_fixture();
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
    let (_tmp, exe, root, log, record) = repair_fixture();
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
    let (_tmp, exe, root, log, record) = repair_fixture();
    let record_arg = record.to_str().unwrap();
    let _ = fs::remove_file(&log);
    let status = Command::new(&exe)
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
        .env("METROLIZA_RUNTIME_REPAIR_AVAILABLE", "0")
        .status()
        .unwrap();
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
    let mut bytes = fs::read(dir.join("lib/data.bin")).unwrap();
    bytes[10] ^= 0xFF; // same size: the warm check cannot see it
    fs::write(dir.join("lib/data.bin"), &bytes).unwrap();
    assert!(is_warm(&dir, &payload));

    let repaired = repair_runtime(&root, &payload, runtime, &NoProgress, &quick()).unwrap();
    assert_eq!(repaired.outcome, Outcome::Repaired);
    assert_eq!(repaired.dir, dir);
    assert_ne!(fs::read(dir.join("lib/data.bin")).unwrap(), bytes);
    assert!(is_warm(&dir, &payload));
}
