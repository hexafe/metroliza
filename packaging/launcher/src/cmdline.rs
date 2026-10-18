//! Windows command-line construction for `CreateProcessW`.
//!
//! Works on UTF-16 code units so it can be unit-tested on any platform. Implements the quoting
//! rules that `CommandLineToArgvW` / the MSVC runtime use to split a command line again, so the
//! entry process receives exactly the arguments the launcher received.

const BACKSLASH: u16 = b'\\' as u16;
const QUOTE: u16 = b'"' as u16;
const SPACE: u16 = b' ' as u16;
const TAB: u16 = b'\t' as u16;

/// Append `arg` to `out`, quoted if needed.
fn push_quoted(out: &mut Vec<u16>, arg: &[u16]) {
    let needs_quotes = arg.is_empty() || arg.iter().any(|&c| c == SPACE || c == TAB || c == QUOTE);
    if !needs_quotes {
        out.extend_from_slice(arg);
        return;
    }
    out.push(QUOTE);
    let mut backslashes = 0usize;
    for &c in arg {
        match c {
            BACKSLASH => backslashes += 1,
            QUOTE => {
                // Backslashes before a quote must be doubled, and the quote itself escaped.
                out.extend(std::iter::repeat_n(BACKSLASH, backslashes * 2 + 1));
                out.push(QUOTE);
                backslashes = 0;
            }
            _ => {
                out.extend(std::iter::repeat_n(BACKSLASH, backslashes));
                out.push(c);
                backslashes = 0;
            }
        }
    }
    // Backslashes before the closing quote must be doubled too.
    out.extend(std::iter::repeat_n(BACKSLASH, backslashes * 2));
    out.push(QUOTE);
}

/// Build a command line (without terminating NUL) from a program path and its arguments.
pub fn build_command_line(program: &[u16], args: &[Vec<u16>]) -> Vec<u16> {
    let mut line = Vec::new();
    // The program is always quoted so paths with spaces are unambiguous. Path names cannot
    // contain quotes on Windows, so plain quoting is exact here.
    line.push(QUOTE);
    line.extend_from_slice(program);
    line.push(QUOTE);
    for arg in args {
        line.push(SPACE);
        push_quoted(&mut line, arg);
    }
    line
}

#[cfg(test)]
mod tests {
    use super::*;

    fn w(s: &str) -> Vec<u16> {
        s.encode_utf16().collect()
    }

    fn line(program: &str, args: &[&str]) -> String {
        let args: Vec<Vec<u16>> = args.iter().map(|a| w(a)).collect();
        String::from_utf16(&build_command_line(&w(program), &args)).unwrap()
    }

    #[test]
    fn plain_arguments_are_unquoted() {
        assert_eq!(
            line(r"C:\App Dir\m.exe", &["--a", "b"]),
            r#""C:\App Dir\m.exe" --a b"#
        );
        assert_eq!(line(r"C:\m.exe", &[]), r#""C:\m.exe""#);
    }

    #[test]
    fn spaces_empty_and_quotes_are_escaped() {
        assert_eq!(line("m", &["a b"]), r#""m" "a b""#);
        assert_eq!(line("m", &[""]), r#""m" """#);
        assert_eq!(line("m", &[r#"say "hi""#]), r#""m" "say \"hi\"""#);
    }

    #[test]
    fn backslashes_are_doubled_only_before_quotes() {
        assert_eq!(line("m", &[r"C:\dir\file"]), r#""m" C:\dir\file"#);
        assert_eq!(line("m", &[r"C:\my dir\"]), r#""m" "C:\my dir\\""#);
        assert_eq!(line("m", &[r#"a\"b"#]), r#""m" "a\\\"b""#);
    }

    #[test]
    fn non_ascii_is_preserved() {
        assert_eq!(line("m", &["zażółć gęślą"]), "\"m\" \"zażółć gęślą\"");
    }
}
