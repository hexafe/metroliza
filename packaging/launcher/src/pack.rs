//! Packer: turns an onedir directory plus a launcher stub into one self-contained EXE.
//!
//! Output layout is described in [`crate::trailer`]. The packer runs on the build machine
//! (Windows CI and Linux tests) and is deliberately single-threaded and deterministic: files are
//! sorted by path and nothing time-dependent enters the output, so identical inputs give
//! identical bytes.

use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Cursor, Write};
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

use crate::archive::encode_file;
use crate::error::{LauncherError, Result};
use crate::fsutil::is_link_or_reparse;
use crate::manifest::{
    validate_git_sha, validate_relative_path, validate_version, FileEntry, Manifest, CHUNK_SIZE,
    FORMAT,
};
use crate::trailer::{has_certificate_table, read_trailer, Trailer, END_ALIGNMENT, TRAILER_LEN};

pub struct PackOptions {
    /// Directory to pack (the PyInstaller onedir output).
    pub input_dir: PathBuf,
    /// Relative path inside `input_dir` of the executable to start (e.g. `metroliza.exe`).
    pub entry: String,
    /// Version label, `[A-Za-z0-9._-]` only.
    pub version: String,
    /// Append the first [`CONTENT_KEY_LEN`] hex digits of the onedir content hash to the stored
    /// version label (`<version>-<hash>`). The cache directory and the single-instance name are
    /// derived from the stored label, so they then change whenever any packed file changes,
    /// not only when the label or the commit changes.
    pub content_key: bool,
    /// Lowercase hex commit id, 8-40 characters.
    pub git_sha: String,
    /// Unsigned launcher executable to prepend.
    pub stub: PathBuf,
    /// Destination EXE.
    pub output: PathBuf,
}

/// Length of the content hash prefix appended to the version by [`PackOptions::content_key`].
pub const CONTENT_KEY_LEN: usize = 12;

#[derive(Debug)]
pub struct PackSummary {
    /// Version label as stored in the manifest (with the content key when requested).
    pub version: String,
    /// Content hash of the packed files, see [`Manifest::content_sha256`].
    pub content_sha256: String,
    pub manifest_sha256: String,
    pub dir_name: String,
    pub file_count: usize,
    pub total_size: u64,
    pub packed_size: u64,
}

fn io_err(what: &str, path: &Path, e: std::io::Error) -> LauncherError {
    LauncherError::payload(format!("{what} {}: {e}", path.display()))
}

/// Collect `(relative path, absolute path)` for every file below `root`, rejecting anything that
/// is not a plain file or directory.
fn collect_files(root: &Path) -> Result<Vec<(String, PathBuf)>> {
    let mut found = Vec::new();
    let mut stack = vec![(root.to_path_buf(), String::new())];
    while let Some((dir, prefix)) = stack.pop() {
        for item in fs::read_dir(&dir).map_err(|e| io_err("read dir", &dir, e))? {
            let item = item.map_err(|e| io_err("read dir", &dir, e))?;
            let path = item.path();
            let name = item.file_name().into_string().map_err(|_| {
                LauncherError::payload(format!("non-UTF-8 name in {}", dir.display()))
            })?;
            let relative = if prefix.is_empty() {
                name
            } else {
                format!("{prefix}/{name}")
            };
            let meta = fs::symlink_metadata(&path).map_err(|e| io_err("stat", &path, e))?;
            if is_link_or_reparse(&meta) {
                return Err(LauncherError::payload(format!(
                    "symlink or reparse point is not allowed: {relative}"
                )));
            }
            if meta.is_dir() {
                stack.push((path, relative));
            } else if meta.is_file() {
                validate_relative_path(&relative)?;
                found.push((relative, path));
            } else {
                return Err(LauncherError::payload(format!(
                    "unsupported file type: {relative}"
                )));
            }
        }
    }
    found.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(found)
}

pub fn pack(options: &PackOptions) -> Result<PackSummary> {
    validate_version(&options.version)?;
    validate_git_sha(&options.git_sha)?;
    validate_relative_path(&options.entry)?;

    let input = fs::canonicalize(&options.input_dir)
        .map_err(|e| io_err("input dir", &options.input_dir, e))?;
    if let Some(parent) = options
        .output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|e| io_err("create output dir", parent, e))?;
    }
    let output_dir = fs::canonicalize(
        options
            .output
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new(".")),
    )
    .map_err(|e| io_err("output dir", &options.output, e))?;
    if output_dir.starts_with(&input) {
        return Err(LauncherError::payload(
            "output must not be inside the input directory",
        ));
    }

    // The stub must be a plain, unsigned launcher: appending to a signed file would invalidate
    // its signature, and a second payload would be ambiguous.
    let stub = fs::read(&options.stub).map_err(|e| io_err("read stub", &options.stub, e))?;
    if has_certificate_table(&mut Cursor::new(&stub)) {
        return Err(LauncherError::payload(
            "stub is already signed; sign the final EXE instead",
        ));
    }
    if read_trailer(&mut Cursor::new(&stub)).is_ok() {
        return Err(LauncherError::payload("stub already contains a payload"));
    }

    let files = collect_files(&input)?;
    if !files.iter().any(|(rel, _)| *rel == options.entry) {
        return Err(LauncherError::payload(
            "entry executable not found in input directory",
        ));
    }

    let staging = options
        .output
        .with_extension(format!("tmp-{}", std::process::id()));
    let result = write_packed(options, &stub, &files, &staging).and_then(|summary| {
        // Keep the stub's permissions so the packed file stays executable on Unix.
        let permissions = fs::metadata(&options.stub)
            .map_err(|e| io_err("stat stub", &options.stub, e))?
            .permissions();
        fs::set_permissions(&staging, permissions).map_err(|e| io_err("chmod", &staging, e))?;
        Ok(summary)
    });
    match result {
        Ok(summary) => {
            fs::rename(&staging, &options.output)
                .map_err(|e| io_err("rename output", &options.output, e))?;
            Ok(summary)
        }
        Err(e) => {
            let _ = fs::remove_file(&staging);
            Err(e)
        }
    }
}

fn write_packed(
    options: &PackOptions,
    stub: &[u8],
    files: &[(String, PathBuf)],
    destination: &Path,
) -> Result<PackSummary> {
    let write_err = |e: std::io::Error| io_err("write", destination, e);
    let mut out = BufWriter::with_capacity(
        1 << 20,
        File::create(destination).map_err(|e| io_err("create", destination, e))?,
    );
    out.write_all(stub).map_err(write_err)?;

    let mut entries = Vec::with_capacity(files.len());
    let mut blob_len = 0u64;
    for (relative, path) in files {
        let source = File::open(path).map_err(|e| io_err("open", path, e))?;
        let encoded =
            encode_file(BufReader::new(source), &mut out).map_err(|e| io_err("encode", path, e))?;
        entries.push(FileEntry {
            path: relative.clone(),
            size: encoded.size,
            sha256: encoded.sha256,
            compressed_size: encoded.compressed_size,
            offset: blob_len,
        });
        blob_len += encoded.compressed_size;
    }

    let mut manifest = Manifest {
        format: FORMAT,
        version: options.version.clone(),
        git_sha: options.git_sha.clone(),
        entry: options.entry.clone(),
        chunk_size: CHUNK_SIZE,
        files: entries,
    };
    let content_sha256 = manifest.content_sha256();
    if options.content_key {
        manifest.version = format!("{}-{}", options.version, &content_sha256[..CONTENT_KEY_LEN]);
        validate_version(&manifest.version)?;
    }
    let manifest_bytes = manifest.to_bytes();
    out.write_all(&manifest_bytes).map_err(write_err)?;

    let payload_offset = stub.len() as u64;
    let payload_len = blob_len + manifest_bytes.len() as u64;
    // Pad so the trailer ends on the alignment Authenticode uses for the certificate table.
    let unpadded_end = payload_offset + payload_len + TRAILER_LEN;
    let padding = (END_ALIGNMENT - unpadded_end % END_ALIGNMENT) % END_ALIGNMENT;
    out.write_all(&vec![0u8; padding as usize])
        .map_err(write_err)?;

    let manifest_sha256: [u8; 32] = Sha256::digest(&manifest_bytes).into();
    let trailer = Trailer {
        payload_offset,
        payload_len,
        manifest_len: manifest_bytes.len() as u64,
        manifest_sha256,
    };
    out.write_all(&trailer.encode()).map_err(write_err)?;
    out.flush().map_err(write_err)?;
    out.into_inner()
        .map_err(|e| write_err(e.into_error()))?
        .sync_all()
        .map_err(write_err)?;

    Ok(PackSummary {
        version: manifest.version.clone(),
        content_sha256,
        manifest_sha256: crate::to_hex(&manifest_sha256),
        dir_name: manifest.dir_name(),
        file_count: manifest.files.len(),
        total_size: manifest.total_size(),
        packed_size: unpadded_end + padding,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::archive::Payload;

    fn write(dir: &Path, rel: &str, data: &[u8]) {
        let path = dir.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, data).unwrap();
    }

    fn options(tmp: &Path, input: &Path) -> PackOptions {
        write(tmp, "stub.exe", b"stub bytes");
        PackOptions {
            input_dir: input.to_path_buf(),
            entry: "app.exe".into(),
            version: "1.0".into(),
            content_key: false,
            git_sha: "abcdef0123456789".into(),
            stub: tmp.join("stub.exe"),
            output: tmp.join("out/final.exe"),
        }
    }

    #[test]
    fn packs_a_directory_and_the_payload_reads_back() {
        let tmp = tempfile::tempdir().unwrap();
        let input = tmp.path().join("in");
        write(&input, "app.exe", b"entry");
        write(&input, "lib/data.bin", &vec![3u8; 100_000]);
        write(&input, "lib/empty", b"");
        let opts = options(tmp.path(), &input);

        let summary = pack(&opts).unwrap();
        assert_eq!(summary.file_count, 3);
        assert_eq!(summary.dir_name, "1.0_abcdef01");
        let bytes = fs::read(&opts.output).unwrap();
        assert_eq!(bytes.len() as u64, summary.packed_size);
        assert_eq!(bytes.len() % 8, 0);
        assert!(bytes.starts_with(b"stub bytes"));

        let payload = Payload::open(&opts.output).unwrap();
        assert_eq!(payload.manifest_hash(), summary.manifest_sha256);
        let paths: Vec<_> = payload
            .manifest
            .files
            .iter()
            .map(|f| f.path.as_str())
            .collect();
        assert_eq!(paths, ["app.exe", "lib/data.bin", "lib/empty"]);
    }

    #[test]
    fn content_key_follows_the_packed_files_only() {
        let tmp = tempfile::tempdir().unwrap();
        let input = tmp.path().join("in");
        write(&input, "app.exe", b"entry");
        write(&input, "lib/data.bin", b"payload one");
        let mut opts = options(tmp.path(), &input);

        let plain = pack(&opts).unwrap();
        assert_eq!(plain.version, "1.0");
        assert_eq!(plain.dir_name, "1.0_abcdef01");

        opts.content_key = true;
        let first = pack(&opts).unwrap();
        assert_eq!(first.content_sha256, plain.content_sha256);
        assert_eq!(first.content_sha256.len(), 64);
        let key = &first.content_sha256[..CONTENT_KEY_LEN];
        assert_eq!(first.version, format!("1.0-{key}"));
        assert_eq!(first.dir_name, format!("1.0-{key}_abcdef01"));
        assert_eq!(
            Payload::open(&opts.output).unwrap().manifest.version,
            first.version
        );

        // Same files, other commit and other label: same content hash.
        opts.git_sha = "11111111".into();
        opts.version = "2.0".into();
        assert_eq!(pack(&opts).unwrap().content_sha256, first.content_sha256);

        // One changed byte: another key, therefore another cache directory.
        write(&input, "lib/data.bin", b"payload two");
        let changed = pack(&opts).unwrap();
        assert_ne!(changed.content_sha256, first.content_sha256);
        assert_ne!(changed.dir_name, first.dir_name);

        // A label that no longer fits the version limit is refused, not truncated.
        opts.version = "x".repeat(60);
        assert!(pack(&opts).is_err());
    }

    #[test]
    fn output_is_deterministic() {
        let tmp = tempfile::tempdir().unwrap();
        let input = tmp.path().join("in");
        write(&input, "app.exe", b"entry");
        write(&input, "a/b.txt", b"hello");
        let mut opts = options(tmp.path(), &input);
        pack(&opts).unwrap();
        let first = fs::read(&opts.output).unwrap();
        opts.output = tmp.path().join("out/second.exe");
        pack(&opts).unwrap();
        assert_eq!(first, fs::read(&opts.output).unwrap());
    }

    #[test]
    fn rejects_missing_entry_bad_metadata_and_output_inside_input() {
        let tmp = tempfile::tempdir().unwrap();
        let input = tmp.path().join("in");
        write(&input, "other.exe", b"x");
        let mut opts = options(tmp.path(), &input);
        assert!(pack(&opts).is_err(), "entry missing");

        write(&input, "app.exe", b"x");
        opts.version = "bad version".into();
        assert!(pack(&opts).is_err());
        opts.version = "1.0".into();
        opts.entry = "../app.exe".into();
        assert!(pack(&opts).is_err());
        opts.entry = "app.exe".into();
        opts.output = input.join("nested.exe");
        assert!(pack(&opts).is_err(), "output inside input");
        opts.output = tmp.path().join("ok.exe");
        assert!(pack(&opts).is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn rejects_symlinks_in_the_input() {
        let tmp = tempfile::tempdir().unwrap();
        let input = tmp.path().join("in");
        write(&input, "app.exe", b"x");
        std::os::unix::fs::symlink(input.join("app.exe"), input.join("link")).unwrap();
        let opts = options(tmp.path(), &input);
        let err = pack(&opts).unwrap_err();
        assert!(err.detail.contains("symlink"), "{err}");
        assert!(!opts.output.exists(), "no output on failure");
    }

    #[test]
    fn rejects_signed_or_already_packed_stub() {
        let tmp = tempfile::tempdir().unwrap();
        let input = tmp.path().join("in");
        write(&input, "app.exe", b"x");
        let mut opts = options(tmp.path(), &input);

        let mut signed = crate::trailer::test_support::synthetic_pe(true, (0x300, 16));
        signed.resize(0x300 + 16, 0);
        fs::write(&opts.stub, signed).unwrap();
        assert!(pack(&opts).is_err(), "signed stub");

        fs::write(&opts.stub, b"stub bytes").unwrap();
        pack(&opts).unwrap();
        opts.stub = opts.output.clone();
        opts.output = tmp.path().join("again.exe");
        assert!(pack(&opts).is_err(), "stub that already has a payload");
    }
}
