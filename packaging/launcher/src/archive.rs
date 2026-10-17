//! Blob codec and payload reader.
//!
//! # Codec choice: LZ4 (block format) via `lz4_flex`
//!
//! The payload is unpacked once per version, but that first run is the slowest thing a user
//! sees, and the payload is mostly DLLs/`.pyd`/ONNX models. LZ4 decodes at several GB/s per
//! core, so extraction is bound by disk and antivirus rather than by inflate (the RC1 PyInstaller
//! envelope spends 4.0 of 4.4 simulated seconds in single-threaded inflate). The price is a
//! larger EXE than with zstd or deflate; that is a download-size trade-off, not a launch-time
//! one. `lz4_flex` is pure Rust (no C toolchain in the Windows build) with safe encode/decode.
//! zstd would compress better but needs a C compiler; it can be swapped in later by bumping
//! [`crate::manifest::FORMAT`].
//!
//! # Blob layout
//!
//! A file is stored as consecutive blocks of up to [`CHUNK_SIZE`] uncompressed bytes. Each block
//! is a little-endian `u32` header followed by that many bytes. The top bit of the header marks a
//! block stored raw because compression did not help; otherwise the bytes are an LZ4 block.
//! Chunking bounds memory per worker thread regardless of file size. Empty files have no blocks.

use std::fs::File;
use std::io::{self, BufReader, Read, Seek, SeekFrom, Take, Write};
use std::path::{Path, PathBuf};

use lz4_flex::block::{compress_into, decompress_into, get_maximum_output_size};
use sha2::{Digest, Sha256};

use crate::error::{LauncherError, Result};
use crate::manifest::{sha256_hex, FileEntry, Manifest, CHUNK_SIZE};
use crate::to_hex;
use crate::trailer::{read_trailer, Trailer};

const RAW_FLAG: u32 = 1 << 31;
const CHUNK: usize = CHUNK_SIZE as usize;

/// Result of encoding one file; becomes a [`FileEntry`] once an offset is assigned.
pub struct Encoded {
    pub size: u64,
    pub sha256: String,
    pub compressed_size: u64,
}

fn read_full(src: &mut impl Read, buf: &mut [u8]) -> io::Result<usize> {
    let mut filled = 0;
    while filled < buf.len() {
        match src.read(&mut buf[filled..]) {
            Ok(0) => break,
            Ok(n) => filled += n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
            Err(e) => return Err(e),
        }
    }
    Ok(filled)
}

/// Encode `src` into blocks written to `dst`; returns size, hash and stored size.
pub fn encode_file(mut src: impl Read, mut dst: impl Write) -> io::Result<Encoded> {
    let mut input = vec![0u8; CHUNK];
    let mut output = vec![0u8; get_maximum_output_size(CHUNK)];
    let mut hasher = Sha256::new();
    let (mut size, mut stored) = (0u64, 0u64);
    loop {
        let n = read_full(&mut src, &mut input)?;
        if n == 0 {
            break;
        }
        hasher.update(&input[..n]);
        size += n as u64;
        let compressed =
            compress_into(&input[..n], &mut output).map_err(|e| io::Error::other(e.to_string()))?;
        let (header, body) = if compressed < n {
            (compressed as u32, &output[..compressed])
        } else {
            (n as u32 | RAW_FLAG, &input[..n])
        };
        dst.write_all(&header.to_le_bytes())?;
        dst.write_all(body)?;
        stored += 4 + body.len() as u64;
    }
    Ok(Encoded {
        size,
        sha256: to_hex(&hasher.finalize()),
        compressed_size: stored,
    })
}

/// Decode a blob of `entry` from `src` into `dst`, verifying size and SHA-256.
///
/// `advance` is called with the number of uncompressed bytes after each block.
pub fn decode_file(
    src: impl Read,
    mut dst: impl Write,
    entry: &FileEntry,
    advance: &mut dyn FnMut(u64),
) -> Result<()> {
    let fail = |what: &str| LauncherError::extraction(format!("{}: {what}", entry.path));
    let mut src = src.take(entry.compressed_size);
    let mut input = vec![0u8; get_maximum_output_size(CHUNK)];
    let mut output = vec![0u8; CHUNK];
    let mut hasher = Sha256::new();
    let mut remaining = entry.size;

    while remaining > 0 {
        let expected = remaining.min(u64::from(CHUNK_SIZE)) as usize;
        let mut header = [0u8; 4];
        src.read_exact(&mut header)
            .map_err(|_| fail("truncated block header"))?;
        let header = u32::from_le_bytes(header);
        let raw = header & RAW_FLAG != 0;
        let len = (header & !RAW_FLAG) as usize;
        if len > input.len() || (raw && len != expected) {
            return Err(fail("invalid block length"));
        }
        src.read_exact(&mut input[..len])
            .map_err(|_| fail("truncated block"))?;
        let block: &[u8] = if raw {
            &input[..len]
        } else {
            let produced = decompress_into(&input[..len], &mut output[..expected])
                .map_err(|_| fail("corrupt compressed block"))?;
            if produced != expected {
                return Err(fail("block size mismatch"));
            }
            &output[..expected]
        };
        hasher.update(block);
        dst.write_all(block)
            .map_err(|e| fail(&format!("write: {e}")))?;
        remaining -= expected as u64;
        advance(expected as u64);
    }
    // The blob must be consumed exactly; trailing bytes mean the manifest and blob disagree.
    let mut extra = [0u8; 1];
    if src
        .read(&mut extra)
        .map_err(|e| fail(&format!("read: {e}")))?
        != 0
    {
        return Err(fail("unexpected trailing blob data"));
    }
    if to_hex(&hasher.finalize()) != entry.sha256 {
        return Err(fail("SHA-256 mismatch"));
    }
    dst.flush().map_err(|e| fail(&format!("flush: {e}")))
}

/// A validated payload inside a packed launcher EXE.
#[derive(Debug)]
pub struct Payload {
    /// The packed EXE the payload lives in (workers open their own handles).
    pub path: PathBuf,
    pub trailer: Trailer,
    pub manifest: Manifest,
}

impl Payload {
    /// Open `exe`, locate the trailer (before an Authenticode table if present) and load the
    /// manifest, verifying it against the trailer's manifest hash.
    pub fn open(exe: &Path) -> Result<Self> {
        let mut file = File::open(exe).map_err(|e| LauncherError::payload(format!("open: {e}")))?;
        let trailer = read_trailer(&mut file)?;

        let mut bytes = vec![0u8; trailer.manifest_len as usize];
        file.seek(SeekFrom::Start(trailer.manifest_offset()))
            .and_then(|_| file.read_exact(&mut bytes))
            .map_err(|e| LauncherError::payload(format!("manifest read: {e}")))?;
        if sha256_hex(&bytes) != to_hex(&trailer.manifest_sha256) {
            return Err(LauncherError::payload("manifest hash mismatch"));
        }
        let manifest = Manifest::from_bytes(&bytes, trailer.blob_region_len())?;
        Ok(Self {
            path: exe.to_path_buf(),
            trailer,
            manifest,
        })
    }

    /// Hex manifest hash; the content of the cache's `.complete` marker.
    pub fn manifest_hash(&self) -> String {
        to_hex(&self.trailer.manifest_sha256)
    }

    /// Buffered reader over the stored blob of `entry` (own file handle, safe across threads).
    pub fn blob_reader(&self, entry: &FileEntry) -> io::Result<BufReader<Take<File>>> {
        let mut file = File::open(&self.path)?;
        file.seek(SeekFrom::Start(self.trailer.payload_offset + entry.offset))?;
        Ok(BufReader::with_capacity(
            256 * 1024,
            file.take(entry.compressed_size),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pseudo_random(len: usize) -> Vec<u8> {
        let mut state = 0x9E37_79B9_7F4A_7C15u64;
        (0..len)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                (state >> 32) as u8
            })
            .collect()
    }

    fn round_trip(data: &[u8]) -> (Encoded, Vec<u8>) {
        let mut blob = Vec::new();
        let enc = encode_file(data, &mut blob).unwrap();
        assert_eq!(enc.size, data.len() as u64);
        assert_eq!(enc.compressed_size, blob.len() as u64);
        let entry = FileEntry {
            path: "f".into(),
            size: enc.size,
            sha256: enc.sha256.clone(),
            compressed_size: enc.compressed_size,
            offset: 0,
        };
        let mut out = Vec::new();
        let mut seen = 0;
        decode_file(blob.as_slice(), &mut out, &entry, &mut |n| seen += n).unwrap();
        assert_eq!(seen, enc.size);
        (enc, out)
    }

    #[test]
    fn round_trips_empty_small_chunk_boundary_and_multi_chunk() {
        for len in [0, 1, 1000, CHUNK - 1, CHUNK, CHUNK + 1, 2 * CHUNK + 17] {
            let data: Vec<u8> = (0..len).map(|i| (i % 251) as u8).collect();
            assert_eq!(round_trip(&data).1, data, "len {len}");
        }
    }

    #[test]
    fn incompressible_data_is_stored_raw_with_bounded_overhead() {
        let data = pseudo_random(300_000);
        let (enc, out) = round_trip(&data);
        assert_eq!(out, data);
        assert_eq!(enc.compressed_size, data.len() as u64 + 4);
    }

    #[test]
    fn compressible_data_shrinks() {
        let (enc, _) = round_trip(&vec![b'a'; 1_000_000]);
        assert!(enc.compressed_size < 10_000);
    }

    fn encoded(data: &[u8]) -> (Vec<u8>, FileEntry) {
        let mut blob = Vec::new();
        let enc = encode_file(data, &mut blob).unwrap();
        let entry = FileEntry {
            path: "f".into(),
            size: enc.size,
            sha256: enc.sha256,
            compressed_size: enc.compressed_size,
            offset: 0,
        };
        (blob, entry)
    }

    #[test]
    fn detects_corruption_truncation_and_hash_mismatch() {
        let data: Vec<u8> = (0..50_000).map(|i| (i % 7) as u8).collect();
        let (blob, entry) = encoded(&data);
        let run =
            |blob: &[u8], entry: &FileEntry| decode_file(blob, Vec::new(), entry, &mut |_| {});
        assert!(run(&blob, &entry).is_ok());

        let mut flipped = blob.clone();
        let last = flipped.len() - 1;
        flipped[last] ^= 0x55;
        assert!(run(&flipped, &entry).is_err(), "flipped byte");

        assert!(
            run(&blob[..blob.len() - 3], &entry).is_err(),
            "truncated blob"
        );

        let mut bad_hash = entry.clone();
        bad_hash.sha256 = "0".repeat(64);
        assert!(run(&blob, &bad_hash).is_err(), "hash mismatch");

        let mut short = entry.clone();
        short.size -= 1;
        assert!(
            run(&blob, &short).is_err(),
            "size smaller than the blob decodes to"
        );

        let mut long = entry.clone();
        long.size += 1;
        assert!(
            run(&blob, &long).is_err(),
            "size larger than the blob holds"
        );
    }

    #[test]
    fn rejects_absurd_block_length() {
        let (_, mut entry) = encoded(b"hello");
        let blob = u32::MAX.to_le_bytes().to_vec();
        entry.compressed_size = 4;
        assert!(decode_file(blob.as_slice(), Vec::new(), &entry, &mut |_| {}).is_err());
    }
}
