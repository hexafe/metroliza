//! Small filesystem helpers shared by the packer and the cache.

use std::fs::Metadata;

/// `FILE_ATTRIBUTE_REPARSE_POINT`: junctions, symlinks, OneDrive placeholders, mount points.
#[cfg(windows)]
const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;

/// True for symlinks and, on Windows, any reparse point (which includes junctions).
///
/// `meta` must come from `symlink_metadata`, otherwise links are already followed.
pub fn is_link_or_reparse(meta: &Metadata) -> bool {
    if meta.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if meta.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_directory_is_not_a_link() {
        let dir = tempfile::tempdir().unwrap();
        let meta = std::fs::symlink_metadata(dir.path()).unwrap();
        assert!(!is_link_or_reparse(&meta));
    }

    #[cfg(unix)]
    #[test]
    fn symlink_is_detected() {
        let dir = tempfile::tempdir().unwrap();
        let link = dir.path().join("link");
        std::os::unix::fs::symlink(dir.path(), &link).unwrap();
        let meta = std::fs::symlink_metadata(&link).unwrap();
        assert!(is_link_or_reparse(&meta));
    }
}
