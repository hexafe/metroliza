//! Payload manifest: what is in the payload and how to verify it.
//!
//! The manifest is JSON, stored at the end of the payload. Its SHA-256 (the "manifest hash")
//! is recorded in the trailer and in the cache's `.complete` marker, so a marker is only valid
//! for the exact payload that produced it.

use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::error::{LauncherError, Result};
use crate::to_hex;

/// Manifest schema version. Bump on any incompatible change to manifest or blob layout.
pub const FORMAT: u32 = 1;

/// Uncompressed size of one independently coded block of a file.
pub const CHUNK_SIZE: u32 = 4 * 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileEntry {
    /// Relative path with `/` separators.
    pub path: String,
    /// Uncompressed size in bytes.
    pub size: u64,
    /// Lowercase hex SHA-256 of the uncompressed content.
    pub sha256: String,
    /// Size of the stored blob (block headers included).
    pub compressed_size: u64,
    /// Blob offset relative to the start of the payload.
    pub offset: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Manifest {
    pub format: u32,
    /// Version label safe for file names and the mutex name (`[A-Za-z0-9._-]`).
    pub version: String,
    /// Source commit (hex, 8-40 characters).
    pub git_sha: String,
    /// Relative path of the executable to start after unpacking.
    pub entry: String,
    /// Block size used by the packer (decoder checks it equals [`CHUNK_SIZE`]).
    pub chunk_size: u32,
    pub files: Vec<FileEntry>,
}

impl Manifest {
    /// Name of the cache directory for this payload: `<version>_<sha8>`.
    pub fn dir_name(&self) -> String {
        format!("{}_{}", self.version, &self.git_sha[..8])
    }

    /// Total uncompressed size of all files.
    pub fn total_size(&self) -> u64 {
        self.files.iter().map(|f| f.size).sum()
    }

    /// Serialise to the stored form. The manifest hash is the SHA-256 of these bytes.
    pub fn to_bytes(&self) -> Vec<u8> {
        // Plain structs of strings and integers always serialise.
        serde_json::to_vec(self).expect("manifest serialisation cannot fail")
    }

    /// Parse and fully validate stored manifest bytes.
    ///
    /// `blob_region_len` is the number of payload bytes holding file blobs; every entry must lie
    /// inside it. Validation is strict because the manifest drives file creation on disk.
    pub fn from_bytes(bytes: &[u8], blob_region_len: u64) -> Result<Self> {
        let manifest: Manifest = serde_json::from_slice(bytes)
            .map_err(|e| LauncherError::payload(format!("manifest parse: {e}")))?;
        manifest.validate(blob_region_len)?;
        Ok(manifest)
    }

    pub fn validate(&self, blob_region_len: u64) -> Result<()> {
        if self.format != FORMAT {
            return Err(LauncherError::payload(format!(
                "unsupported format {}",
                self.format
            )));
        }
        if self.chunk_size != CHUNK_SIZE {
            return Err(LauncherError::payload("unsupported chunk size"));
        }
        validate_version(&self.version)?;
        validate_git_sha(&self.git_sha)?;
        validate_relative_path(&self.entry)?;
        if !self.files.iter().any(|f| f.path == self.entry) {
            return Err(LauncherError::payload(
                "entry executable is not in the manifest",
            ));
        }
        let mut seen = HashSet::with_capacity(self.files.len());
        for file in &self.files {
            validate_relative_path(&file.path)?;
            // Windows file systems are case-insensitive: "A.dll" and "a.dll" would collide.
            if !seen.insert(file.path.to_ascii_lowercase()) {
                return Err(LauncherError::payload("duplicate path in manifest"));
            }
            if file.sha256.len() != 64
                || !file
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return Err(LauncherError::payload("malformed file hash"));
            }
            let end = file.offset.checked_add(file.compressed_size);
            if end.is_none_or(|end| end > blob_region_len) {
                return Err(LauncherError::payload("blob outside payload"));
            }
        }
        Ok(())
    }
}

/// SHA-256 of `bytes` as lowercase hex.
pub fn sha256_hex(bytes: &[u8]) -> String {
    to_hex(&Sha256::digest(bytes))
}

/// Version labels become directory names and a kernel object name; keep them boring.
pub fn validate_version(version: &str) -> Result<()> {
    let ok = !version.is_empty()
        && version.len() <= 64
        && !version.starts_with('.')
        && version
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'));
    if ok {
        Ok(())
    } else {
        Err(LauncherError::payload("invalid version label"))
    }
}

pub fn validate_git_sha(sha: &str) -> Result<()> {
    let ok = (8..=40).contains(&sha.len())
        && sha
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
    if ok {
        Ok(())
    } else {
        Err(LauncherError::payload(
            "git sha must be 8-40 lowercase hex characters",
        ))
    }
}

/// Device names Windows treats specially in any directory, with or without an extension.
const RESERVED_NAMES: [&str; 22] = [
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8",
    "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
];

/// Accept only plain relative paths: `/`-separated normal components, no `..`, no drive or
/// stream syntax, no names Windows would reinterpret. The same rule is applied when packing and
/// again before anything is created from a payload.
pub fn validate_relative_path(path: &str) -> Result<()> {
    let bad = || LauncherError::payload("unsafe path in payload");
    if path.is_empty() || path.len() > 240 {
        return Err(bad());
    }
    for component in path.split('/') {
        if component.is_empty() || component == "." || component == ".." {
            return Err(bad());
        }
        if component.ends_with('.') || component.ends_with(' ') {
            return Err(bad());
        }
        if component
            .chars()
            .any(|c| c.is_control() || "\\:*?\"<>|".contains(c))
        {
            return Err(bad());
        }
        let stem = component
            .split('.')
            .next()
            .unwrap_or("")
            .to_ascii_lowercase();
        if RESERVED_NAMES.contains(&stem.as_str()) {
            return Err(bad());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(path: &str, offset: u64, compressed: u64) -> FileEntry {
        FileEntry {
            path: path.into(),
            size: 10,
            sha256: sha256_hex(b"x"),
            compressed_size: compressed,
            offset,
        }
    }

    fn sample() -> Manifest {
        Manifest {
            format: FORMAT,
            version: "2026.09rc1_260927".into(),
            git_sha: "0123456789abcdef0123456789abcdef01234567".into(),
            entry: "metroliza.exe".into(),
            chunk_size: CHUNK_SIZE,
            files: vec![entry("metroliza.exe", 0, 10), entry("lib/a.dll", 10, 10)],
        }
    }

    #[test]
    fn round_trips_and_names_the_cache_directory() {
        let manifest = sample();
        let parsed = Manifest::from_bytes(&manifest.to_bytes(), 20).unwrap();
        assert_eq!(parsed, manifest);
        assert_eq!(parsed.dir_name(), "2026.09rc1_260927_01234567");
        assert_eq!(parsed.total_size(), 20);
    }

    #[test]
    fn rejects_unsafe_paths() {
        for path in [
            "",
            "/abs",
            "a//b",
            "a/../b",
            "..",
            ".",
            "C:/x",
            "a\\b",
            "a/b:stream",
            "nul",
            "NUL.txt",
            "dir/con.dll",
            "trail.",
            "trail ",
            "a/b/",
            "a\u{0}b",
            "x*y",
        ] {
            assert!(
                validate_relative_path(path).is_err(),
                "{path:?} must be rejected"
            );
        }
        for path in [
            "a",
            "a/b.dll",
            "lib/Python 3.11/x.pyd",
            "_internal/base_library.zip",
        ] {
            assert!(
                validate_relative_path(path).is_ok(),
                "{path:?} must be accepted"
            );
        }
    }

    #[test]
    fn rejects_bad_manifests() {
        let mut m = sample();
        m.files[1].path = "METROLIZA.EXE".into();
        assert!(
            Manifest::from_bytes(&m.to_bytes(), 20).is_err(),
            "case-insensitive duplicate"
        );

        let mut m = sample();
        m.entry = "missing.exe".into();
        assert!(
            Manifest::from_bytes(&m.to_bytes(), 20).is_err(),
            "entry not listed"
        );

        assert!(
            Manifest::from_bytes(&sample().to_bytes(), 19).is_err(),
            "blob past region"
        );

        let mut m = sample();
        m.files[0].offset = u64::MAX;
        assert!(
            Manifest::from_bytes(&m.to_bytes(), 20).is_err(),
            "offset overflow"
        );

        let mut m = sample();
        m.files[0].sha256 = "ABC".into();
        assert!(
            Manifest::from_bytes(&m.to_bytes(), 20).is_err(),
            "hash shape"
        );

        let mut m = sample();
        m.format = 99;
        assert!(Manifest::from_bytes(&m.to_bytes(), 20).is_err(), "format");

        assert!(Manifest::from_bytes(b"not json", 20).is_err());
    }

    #[test]
    fn rejects_bad_version_and_sha() {
        for v in ["", ".hidden", "a b", "a/b", "a(b)", &"x".repeat(65)] {
            assert!(validate_version(v).is_err(), "{v:?}");
        }
        assert!(validate_version("2026.09rc1_260927").is_ok());
        assert!(validate_git_sha("abc").is_err());
        assert!(validate_git_sha("ABCDEF0123").is_err());
        assert!(validate_git_sha("abcdef0123").is_ok());
    }
}
