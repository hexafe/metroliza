//! Trailer: the fixed-size record that lets the launcher find its payload inside its own EXE.
//!
//! File layout of a packed launcher:
//!
//! ```text
//! [launcher PE][payload: blobs, manifest][zero padding][trailer, 64 bytes][certificate table?]
//! ```
//!
//! Authenticode signs the final file and appends the certificate table after everything else, so
//! the trailer sits immediately before the table when the PE header announces one
//! (`IMAGE_DIRECTORY_ENTRY_SECURITY`), and at the end of the file otherwise. The packer pads so
//! that the trailer ends on an 8-byte boundary, which is where signtool places the table; the
//! launcher therefore never has to guess at padding.

use std::io::{Read, Seek, SeekFrom};

use crate::error::{LauncherError, Result};

pub const MAGIC: [u8; 8] = *b"MTRLZPL1";
pub const TRAILER_LEN: u64 = 64;
/// Alignment of the end of the trailer (matches Authenticode certificate table alignment).
pub const END_ALIGNMENT: u64 = 8;

/// Index of the certificate table in the PE data directory array.
const DIRECTORY_ENTRY_SECURITY: u64 = 4;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Trailer {
    /// File offset of the first payload byte (also: size of the launcher stub).
    pub payload_offset: u64,
    /// Payload length: blobs followed by the manifest.
    pub payload_len: u64,
    /// Length of the manifest at the end of the payload.
    pub manifest_len: u64,
    /// SHA-256 of the manifest bytes.
    pub manifest_sha256: [u8; 32],
}

impl Trailer {
    pub fn encode(&self) -> [u8; TRAILER_LEN as usize] {
        let mut out = [0u8; TRAILER_LEN as usize];
        out[0..8].copy_from_slice(&MAGIC);
        out[8..16].copy_from_slice(&self.payload_offset.to_le_bytes());
        out[16..24].copy_from_slice(&self.payload_len.to_le_bytes());
        out[24..32].copy_from_slice(&self.manifest_len.to_le_bytes());
        out[32..64].copy_from_slice(&self.manifest_sha256);
        out
    }

    pub fn decode(bytes: &[u8; TRAILER_LEN as usize]) -> Result<Self> {
        if bytes[0..8] != MAGIC {
            return Err(LauncherError::payload("trailer magic not found"));
        }
        let le = |range: std::ops::Range<usize>| {
            u64::from_le_bytes(bytes[range].try_into().expect("8-byte slice"))
        };
        let mut manifest_sha256 = [0u8; 32];
        manifest_sha256.copy_from_slice(&bytes[32..64]);
        Ok(Self {
            payload_offset: le(8..16),
            payload_len: le(16..24),
            manifest_len: le(24..32),
            manifest_sha256,
        })
    }

    /// Length of the part of the payload that holds file blobs.
    pub fn blob_region_len(&self) -> u64 {
        self.payload_len - self.manifest_len
    }

    /// File offset of the manifest.
    pub fn manifest_offset(&self) -> u64 {
        self.payload_offset + self.blob_region_len()
    }
}

fn read_exact_at<R: Read + Seek>(file: &mut R, offset: u64, buf: &mut [u8]) -> Option<()> {
    file.seek(SeekFrom::Start(offset)).ok()?;
    file.read_exact(buf).ok()
}

fn u16_at<R: Read + Seek>(file: &mut R, offset: u64) -> Option<u16> {
    let mut b = [0u8; 2];
    read_exact_at(file, offset, &mut b)?;
    Some(u16::from_le_bytes(b))
}

fn u32_at<R: Read + Seek>(file: &mut R, offset: u64) -> Option<u32> {
    let mut b = [0u8; 4];
    read_exact_at(file, offset, &mut b)?;
    Some(u32::from_le_bytes(b))
}

/// Certificate table of a PE file as `(file offset, size)`, or `None` for a PE without one and
/// for anything that is not a well-formed PE (such input is simply treated as unsigned).
fn pe_certificate_table<R: Read + Seek>(file: &mut R) -> Option<(u64, u64)> {
    if u16_at(file, 0)? != 0x5A4D {
        return None; // "MZ"
    }
    let pe = u64::from(u32_at(file, 0x3C)?);
    if u32_at(file, pe)? != 0x0000_4550 {
        return None; // "PE\0\0"
    }
    let optional = pe + 24;
    let (count_at, dirs_at) = match u16_at(file, optional)? {
        0x10B => (optional + 92, optional + 96),   // PE32
        0x20B => (optional + 108, optional + 112), // PE32+
        _ => return None,
    };
    if u64::from(u32_at(file, count_at)?) <= DIRECTORY_ENTRY_SECURITY {
        return None;
    }
    let entry = dirs_at + DIRECTORY_ENTRY_SECURITY * 8;
    let offset = u64::from(u32_at(file, entry)?);
    let size = u64::from(u32_at(file, entry + 4)?);
    (offset != 0 && size != 0).then_some((offset, size))
}

/// True if the PE header announces an Authenticode certificate table.
pub fn has_certificate_table<R: Read + Seek>(file: &mut R) -> bool {
    pe_certificate_table(file).is_some()
}

/// File offset one past the last byte the trailer may occupy: the start of the certificate
/// table for a signed EXE, the end of the file otherwise.
pub fn trailer_end<R: Read + Seek>(file: &mut R) -> Result<u64> {
    let len = file
        .seek(SeekFrom::End(0))
        .map_err(|e| LauncherError::payload(format!("seek: {e}")))?;
    match pe_certificate_table(file) {
        None => Ok(len),
        Some((offset, size)) => {
            if offset.checked_add(size).is_none_or(|end| end > len) {
                return Err(LauncherError::payload("certificate table outside file"));
            }
            Ok(offset)
        }
    }
}

/// Locate, read and sanity-check the trailer of a packed launcher.
pub fn read_trailer<R: Read + Seek>(file: &mut R) -> Result<Trailer> {
    let end = trailer_end(file)?;
    if end < TRAILER_LEN {
        return Err(LauncherError::payload("file too small for a trailer"));
    }
    let mut raw = [0u8; TRAILER_LEN as usize];
    read_exact_at(file, end - TRAILER_LEN, &mut raw)
        .ok_or_else(|| LauncherError::payload("cannot read trailer"))?;
    let trailer = Trailer::decode(&raw)?;

    let payload_end = trailer.payload_offset.checked_add(trailer.payload_len);
    if trailer.manifest_len == 0
        || trailer.manifest_len > trailer.payload_len
        || payload_end.is_none_or(|p| p > end - TRAILER_LEN)
    {
        return Err(LauncherError::payload("trailer fields are inconsistent"));
    }
    Ok(trailer)
}

#[cfg(test)]
pub(crate) mod test_support {
    /// Minimal synthetic PE header (DOS stub pointer + PE signature + COFF + optional header
    /// with a full 16-entry data directory). `security` fills IMAGE_DIRECTORY_ENTRY_SECURITY.
    pub fn synthetic_pe(plus: bool, security: (u32, u32)) -> Vec<u8> {
        let pe_at = 0x80usize;
        let optional_len = if plus { 112 + 16 * 8 } else { 96 + 16 * 8 };
        let mut buf = vec![0u8; pe_at + 24 + optional_len];
        buf[0..2].copy_from_slice(b"MZ");
        buf[0x3C..0x40].copy_from_slice(&(pe_at as u32).to_le_bytes());
        buf[pe_at..pe_at + 4].copy_from_slice(b"PE\0\0");
        let opt = pe_at + 24;
        let magic: u16 = if plus { 0x20B } else { 0x10B };
        buf[opt..opt + 2].copy_from_slice(&magic.to_le_bytes());
        let (count_at, dirs_at) = if plus {
            (opt + 108, opt + 112)
        } else {
            (opt + 92, opt + 96)
        };
        buf[count_at..count_at + 4].copy_from_slice(&16u32.to_le_bytes());
        let sec = dirs_at + 4 * 8;
        buf[sec..sec + 4].copy_from_slice(&security.0.to_le_bytes());
        buf[sec + 4..sec + 8].copy_from_slice(&security.1.to_le_bytes());
        buf
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::synthetic_pe;
    use super::*;
    use std::io::Cursor;

    fn sample_trailer(payload_offset: u64, payload_len: u64) -> Trailer {
        Trailer {
            payload_offset,
            payload_len,
            manifest_len: 10,
            manifest_sha256: [7u8; 32],
        }
    }

    /// stub + payload + trailer, with the trailer ending on an 8-byte boundary.
    fn packed(stub: &[u8], payload_len: u64) -> (Vec<u8>, Trailer) {
        let mut file = stub.to_vec();
        let trailer = sample_trailer(stub.len() as u64, payload_len);
        file.extend(vec![0xAB; payload_len as usize]);
        while (file.len() as u64 + TRAILER_LEN) % END_ALIGNMENT != 0 {
            file.push(0);
        }
        file.extend(trailer.encode());
        (file, trailer)
    }

    #[test]
    fn encode_decode_round_trip() {
        let t = sample_trailer(123, 456);
        assert_eq!(Trailer::decode(&t.encode()).unwrap(), t);
        assert_eq!(t.blob_region_len(), 446);
        assert_eq!(t.manifest_offset(), 123 + 446);
    }

    #[test]
    fn rejects_wrong_magic() {
        let mut raw = sample_trailer(1, 20).encode();
        raw[0] ^= 0xFF;
        assert!(Trailer::decode(&raw).is_err());
    }

    #[test]
    fn unsigned_non_pe_trailer_is_at_end_of_file() {
        let (file, trailer) = packed(b"plain stub, not a PE", 100);
        let mut cursor = Cursor::new(file);
        assert_eq!(read_trailer(&mut cursor).unwrap(), trailer);
    }

    #[test]
    fn unsigned_pe_without_certificate_table_uses_end_of_file() {
        for plus in [false, true] {
            let (file, trailer) = packed(&synthetic_pe(plus, (0, 0)), 100);
            let mut cursor = Cursor::new(file);
            assert_eq!(read_trailer(&mut cursor).unwrap(), trailer);
        }
    }

    #[test]
    fn signed_pe_trailer_is_before_certificate_table() {
        for plus in [false, true] {
            let stub = synthetic_pe(plus, (0, 0));
            let (unsigned, trailer) = packed(&stub, 100);

            // Sign: patch the security directory to point at the appended certificate data.
            let cert = vec![0xCE; 1500];
            let cert_offset = unsigned.len() as u32;
            let mut signed = synthetic_pe(plus, (cert_offset, cert.len() as u32));
            signed.extend_from_slice(&unsigned[signed.len()..]);
            signed.extend_from_slice(&cert);

            let mut cursor = Cursor::new(signed);
            assert_eq!(trailer_end(&mut cursor).unwrap(), u64::from(cert_offset));
            assert_eq!(read_trailer(&mut cursor).unwrap(), trailer);
        }
    }

    #[test]
    fn certificate_table_outside_file_is_rejected() {
        let (mut file, _) = packed(&synthetic_pe(true, (0, 0)), 100);
        let bogus = synthetic_pe(true, (file.len() as u32 - 8, 4096));
        file[..bogus.len()].copy_from_slice(&bogus);
        assert!(read_trailer(&mut Cursor::new(file)).is_err());
    }

    #[test]
    fn truncated_or_garbage_files_are_rejected() {
        assert!(read_trailer(&mut Cursor::new(vec![0u8; 10])).is_err());
        assert!(read_trailer(&mut Cursor::new(vec![0u8; 4096])).is_err());
        let (file, _) = packed(b"stub", 100);
        let truncated = file[..file.len() - 1].to_vec();
        assert!(read_trailer(&mut Cursor::new(truncated)).is_err());
    }

    #[test]
    fn inconsistent_trailer_fields_are_rejected() {
        // payload claims to extend into the trailer itself
        let mut file = vec![0u8; 64];
        file.extend(sample_trailer(0, 100).encode());
        assert!(read_trailer(&mut Cursor::new(file)).is_err());
    }
}
