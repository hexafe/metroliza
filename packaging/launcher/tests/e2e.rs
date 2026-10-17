//! End-to-end tests: pack a directory, then drive the cache and the real launcher binary.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, SystemTime};

use metroliza_launcher::archive::Payload;
use metroliza_launcher::cache::{
    cleanup_old_versions, ensure_runtime, is_warm, NoProgress, Options, Outcome, MARKER,
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
