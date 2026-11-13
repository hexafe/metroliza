//! Host tool: pack an onedir directory and a launcher stub into one EXE.
//!
//! Usage: metroliza-packer --input DIR --entry REL --version V --git-sha SHA --stub EXE --output EXE
//!                         [--content-key]
//! `--content-key` appends the first 12 hex digits of the onedir content hash to the stored
//! version label, so the runtime cache key follows the packed files.
//! Prints a one-line JSON summary on success.

use std::path::PathBuf;
use std::process::ExitCode;

use metroliza_launcher::pack::{pack, PackOptions};

fn parse(args: impl Iterator<Item = String>) -> Result<PackOptions, String> {
    let (mut input, mut entry, mut version, mut git_sha, mut stub, mut output) =
        (None, None, None, None, None, None);
    let mut content_key = false;
    let mut args = args;
    while let Some(flag) = args.next() {
        let slot = match flag.as_str() {
            "--content-key" => {
                content_key = true;
                continue;
            }
            "--input" => &mut input,
            "--entry" => &mut entry,
            "--version" => &mut version,
            "--git-sha" => &mut git_sha,
            "--stub" => &mut stub,
            "--output" => &mut output,
            other => return Err(format!("unknown argument: {other}")),
        };
        *slot = Some(args.next().ok_or_else(|| format!("{flag} needs a value"))?);
    }
    let need = |value: Option<String>, name: &str| value.ok_or_else(|| format!("missing {name}"));
    Ok(PackOptions {
        input_dir: PathBuf::from(need(input, "--input")?),
        entry: need(entry, "--entry")?,
        version: need(version, "--version")?,
        content_key,
        git_sha: need(git_sha, "--git-sha")?,
        stub: PathBuf::from(need(stub, "--stub")?),
        output: PathBuf::from(need(output, "--output")?),
    })
}

fn main() -> ExitCode {
    let options = match parse(std::env::args().skip(1)) {
        Ok(options) => options,
        Err(message) => {
            eprintln!("{message}");
            eprintln!(
                "usage: metroliza-packer --input DIR --entry REL --version V --git-sha SHA \
                 --stub EXE --output EXE [--content-key]"
            );
            return ExitCode::from(2);
        }
    };
    match pack(&options) {
        Ok(summary) => {
            println!(
                "{{\"manifest_sha256\":\"{}\",\"version\":\"{}\",\"content_sha256\":\"{}\",\
                 \"dir_name\":\"{}\",\"file_count\":{},\"total_size\":{},\"packed_size\":{}}}",
                summary.manifest_sha256,
                summary.version,
                summary.content_sha256,
                summary.dir_name,
                summary.file_count,
                summary.total_size,
                summary.packed_size
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("pack failed: {error}");
            ExitCode::FAILURE
        }
    }
}
