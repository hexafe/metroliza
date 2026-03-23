use pyo3::prelude::*;
use pyo3::types::PyList;

const TP_QUALIFIERS: &[&str] = &["RFS", "MMC", "LMC", "MMB", "LMB", "TANGENT", "PROJECTED"];
const TP_SEMANTIC_LABELS: &[&str] = &[
    "NOM", "+TOL", "TOL", "BONUS", "MEAS", "DEV", "OUTTOL", "ACT", "OUT",
];

#[derive(Clone, Debug, PartialEq)]
enum HeaderEntry {
    Text(String),
    NoHeader,
}

#[derive(Clone, Debug, PartialEq)]
enum Field {
    Text(String),
    Float(f64),
    Empty,
}

#[derive(Clone, Debug, PartialEq)]
struct Block {
    header_comment: Vec<HeaderEntry>,
    dimensions: Vec<Vec<Field>>,
}

fn measurement_line_map(code: &str) -> usize {
    match code {
        "X" | "Y" | "Z" | "TP" | "D" | "RN" | "PR" | "A" => 7,
        "M" | "DF" => 8,
        "PA" => 4,
        "D1" | "D2" | "D3" | "D4" => 5,
        _ => 0,
    }
}

fn is_comment_or_header(line: &str) -> bool {
    line.starts_with('#') || line.starts_with('*')
}

fn is_dim_line(line: &str) -> bool {
    line.starts_with("DIM")
}

fn is_number(value: &str) -> bool {
    value.trim().parse::<f64>().is_ok()
}

fn strip_comment_prefix(line: &str) -> String {
    line.trim_start_matches(|c| c == '#' || c == '*' || c == '/')
        .trim()
        .to_string()
}

fn extract_header_comment(lines: &[String]) -> (String, usize) {
    let mut header: Vec<String> = Vec::new();
    let mut counter = 0usize;
    for (index, line) in lines.iter().enumerate() {
        if !is_dim_line(line) {
            if index > 0 {
                header.push(line.replace('#', "").replace('*', ""));
            } else {
                header.push(line.clone());
            }
        } else {
            counter = index.saturating_sub(1);
            break;
        }
    }
    (header.join(" "), counter)
}

fn extract_measurement_tokens_and_raw_lines_consumed(
    lines: &[String],
    preserve_non_numeric_tokens: bool,
) -> (Vec<String>, usize) {
    if lines.is_empty() {
        return (Vec::new(), 0);
    }

    let code_tokens: Vec<String> = lines[0]
        .split_whitespace()
        .map(ToString::to_string)
        .collect();
    if code_tokens.is_empty() {
        return (Vec::new(), 0);
    }

    let code = code_tokens[0].clone();
    let mut parsed_tokens = vec![code.clone()];
    let mut raw_lines_consumed = 1usize;
    let max_token_count = measurement_line_map(&code);
    let max_numeric_count = if max_token_count > 0 {
        max_token_count - 1
    } else {
        0
    };

    let numeric_tokens_consumed = |tokens: &[String]| {
        tokens
            .iter()
            .skip(1)
            .filter(|token| is_number(token))
            .count()
    };

    let append_tokens = |parsed_tokens: &mut Vec<String>, tokens: &[String]| {
        for token in tokens {
            if is_number(token) {
                parsed_tokens.push(token.clone());
                if max_numeric_count > 0
                    && numeric_tokens_consumed(parsed_tokens) >= max_numeric_count
                {
                    break;
                }
            } else if preserve_non_numeric_tokens {
                parsed_tokens.push(token.clone());
                if max_numeric_count > 0
                    && numeric_tokens_consumed(parsed_tokens) >= max_numeric_count
                {
                    break;
                }
            }
        }
    };

    append_tokens(&mut parsed_tokens, &code_tokens[1..]);

    for raw_line in lines.iter().skip(1) {
        if max_numeric_count > 0 && numeric_tokens_consumed(&parsed_tokens) >= max_numeric_count {
            break;
        }

        let raw_line_tokens: Vec<String> = raw_line
            .split_whitespace()
            .map(ToString::to_string)
            .collect();
        if raw_line_tokens.is_empty() {
            raw_lines_consumed += 1;
            continue;
        }

        if is_comment_or_header(raw_line)
            || is_dim_line(raw_line)
            || measurement_line_map(&raw_line_tokens[0]) > 0
        {
            break;
        }

        raw_lines_consumed += 1;
        append_tokens(&mut parsed_tokens, &raw_line_tokens);
    }

    (parsed_tokens, raw_lines_consumed)
}

fn process_tp_line(tokens: &[String]) -> Vec<Field> {
    let mut has_tp_qualifier = false;
    let mut has_explicit_nom_label = false;
    let mut numeric_values: Vec<f64> = Vec::new();

    for token in tokens.iter().skip(1) {
        let uppercase = token.to_uppercase();
        let normalized = uppercase.trim_end_matches(':');
        if let Ok(value) = token.parse::<f64>() {
            numeric_values.push(value);
        } else if TP_QUALIFIERS.contains(&normalized) {
            has_tp_qualifier = true;
        } else if TP_SEMANTIC_LABELS.contains(&normalized) && normalized == "NOM" {
            has_explicit_nom_label = true;
        }
    }

    if numeric_values.len() < 5 {
        return Vec::new();
    }

    let (nom, tol_plus, bonus, meas, dev, outtol) =
        if numeric_values.len() >= 6 && (has_explicit_nom_label || !has_tp_qualifier) {
            (
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                numeric_values[3],
                numeric_values[4],
                numeric_values[5],
            )
        } else {
            (
                0.0,
                numeric_values[0],
                numeric_values[1],
                numeric_values[2],
                numeric_values[3],
                numeric_values[4],
            )
        };

    vec![
        Field::Text("TP".to_string()),
        Field::Float(nom),
        Field::Float(tol_plus),
        Field::Empty,
        Field::Float(bonus),
        Field::Float(meas),
        Field::Float(dev),
        Field::Float(outtol),
    ]
}

fn normalize_numeric_tokens(line: &[String]) -> Vec<String> {
    let mut normalized = vec![line[0].clone()];
    normalized.extend(
        line.iter()
            .skip(1)
            .filter(|token| is_number(token))
            .cloned(),
    );
    normalized
}

fn process_line(line: &[String]) -> Vec<Field> {
    if line.is_empty() {
        return Vec::new();
    }

    let normalized_line = if !line[0].starts_with("TP") {
        normalize_numeric_tokens(line)
    } else {
        line.to_vec()
    };

    let code = normalized_line[0].as_str();
    match (code, normalized_line.len()) {
        ("X" | "Y" | "Z", 4) => vec![
            Field::Text(code.to_string()),
            Field::Float(normalized_line[1].parse().unwrap()),
            Field::Empty,
            Field::Empty,
            Field::Empty,
            Field::Float(normalized_line[2].parse().unwrap()),
            Field::Float(normalized_line[3].parse().unwrap()),
            Field::Empty,
        ],
        ("X" | "Y" | "Z", 7) => vec![
            Field::Text(code.to_string()),
            Field::Float(normalized_line[1].parse().unwrap()),
            Field::Float(normalized_line[2].parse().unwrap()),
            Field::Float(normalized_line[3].parse().unwrap()),
            Field::Empty,
            Field::Float(normalized_line[4].parse().unwrap()),
            Field::Float(normalized_line[5].parse().unwrap()),
            Field::Float(normalized_line[6].parse().unwrap()),
        ],
        (c, _) if c.starts_with("TP") => process_tp_line(&normalized_line),
        ("M", 7) | ("D", 7) | ("RN", 7) | ("PR", 7) => vec![
            Field::Text(code.to_string()),
            Field::Float(normalized_line[1].parse().unwrap()),
            Field::Float(normalized_line[2].parse().unwrap()),
            Field::Float(normalized_line[3].parse().unwrap()),
            Field::Empty,
            Field::Float(normalized_line[4].parse().unwrap()),
            Field::Float(normalized_line[5].parse().unwrap()),
            Field::Float(normalized_line[6].parse().unwrap()),
        ],
        ("M", 8) | ("DF", 8) => vec![
            Field::Text(code.to_string()),
            Field::Float(normalized_line[1].parse().unwrap()),
            Field::Float(normalized_line[2].parse().unwrap()),
            Field::Float(normalized_line[3].parse().unwrap()),
            Field::Float(normalized_line[4].parse().unwrap()),
            Field::Float(normalized_line[5].parse().unwrap()),
            Field::Float(normalized_line[6].parse().unwrap()),
            Field::Float(normalized_line[7].parse().unwrap()),
        ],
        ("DF", 7) | ("A", 7) => vec![
            Field::Text(code.to_string()),
            Field::Float(normalized_line[1].parse().unwrap()),
            Field::Float(normalized_line[2].parse().unwrap()),
            Field::Float(normalized_line[3].parse().unwrap()),
            Field::Float(0.0),
            Field::Float(normalized_line[4].parse().unwrap()),
            Field::Float(normalized_line[5].parse().unwrap()),
            Field::Float(normalized_line[6].parse().unwrap()),
        ],
        ("PR" | "PA", 4) => vec![
            Field::Text(code.to_string()),
            Field::Float(normalized_line[1].parse().unwrap()),
            Field::Empty,
            Field::Empty,
            Field::Empty,
            Field::Float(normalized_line[2].parse().unwrap()),
            Field::Float(normalized_line[3].parse().unwrap()),
            Field::Empty,
        ],
        ("D1" | "D2" | "D3" | "D4", 5) if is_number(&normalized_line[1]) => vec![
            Field::Text(code.to_string()),
            Field::Float(normalized_line[1].parse().unwrap()),
            Field::Float(normalized_line[2].parse().unwrap()),
            Field::Float(normalized_line[3].parse().unwrap()),
            Field::Empty,
            Field::Float(normalized_line[4].parse().unwrap()),
            Field::Empty,
            Field::Empty,
        ],
        _ => Vec::new(),
    }
}

fn finalize_block(
    pdf_blocks_text: &mut Vec<Block>,
    header_comment: &[HeaderEntry],
    dim_block: &[Vec<Field>],
) {
    let candidate = Block {
        header_comment: header_comment.to_vec(),
        dimensions: dim_block.to_vec(),
    };
    pdf_blocks_text.push(candidate);
}

fn add_tolerances_to_blocks(pdf_blocks_text: &mut [Block]) {
    for block in pdf_blocks_text.iter_mut() {
        let mut tol_plus: Option<f64> = Some(0.0);
        let mut tol_minus: Option<f64> = None;
        let mut bonus: Option<f64> = None;

        if let Some(last_line) = block.dimensions.last() {
            if matches!(last_line.first(), Some(Field::Text(code)) if code == "TP") {
                let tp_tol = match last_line.get(2) {
                    Some(Field::Float(value)) => *value * 0.5,
                    _ => 0.0,
                };
                let tp_bonus = match last_line.get(4) {
                    Some(Field::Float(value)) => Some(*value),
                    _ => None,
                };
                tol_plus = Some(tp_tol);
                tol_minus = Some(-tp_tol);
                bonus = tp_bonus;

                for measurement_line in block.dimensions.iter_mut() {
                    if matches!(measurement_line.get(2), Some(Field::Empty)) {
                        measurement_line[2] = Field::Float(tp_tol);
                        measurement_line[3] = Field::Float(-tp_tol);
                        if let Some(tp_bonus_value) = tp_bonus {
                            measurement_line[4] = Field::Float(tp_bonus_value);
                        }
                    }
                }

                if let Some(tp_line) = block.dimensions.last_mut() {
                    tp_line[3] = Field::Float(0.0);
                }
            } else {
                let mut saw_explicit_tol_source = false;
                for measurement_line in &block.dimensions {
                    if let Some(Field::Float(value)) = measurement_line.get(2) {
                        tol_plus = Some(*value);
                        saw_explicit_tol_source = true;
                    }
                    if let Some(Field::Float(value)) = measurement_line.get(3) {
                        tol_minus = Some(*value);
                        saw_explicit_tol_source = true;
                    }
                    if let Some(Field::Float(value)) = measurement_line.get(4) {
                        bonus = Some(*value);
                    }
                }

                if bonus.is_none() && saw_explicit_tol_source {
                    bonus = Some(0.0);
                }

                for measurement_line in block.dimensions.iter_mut() {
                    if matches!(measurement_line.get(2), Some(Field::Empty)) {
                        if let Some(value) = tol_plus {
                            measurement_line[2] = Field::Float(value);
                        }
                    }
                    if matches!(measurement_line.get(3), Some(Field::Empty)) {
                        if let Some(value) = tol_minus {
                            measurement_line[3] = Field::Float(value);
                        }
                    }
                    if matches!(measurement_line.get(4), Some(Field::Empty)) {
                        if let Some(value) = bonus {
                            measurement_line[4] = Field::Float(value);
                        }
                    }
                }
            }
        }
    }
}

fn parse_raw_lines_to_blocks_native(raw_lines: &[String]) -> Vec<Block> {
    let mut pdf_blocks_text: Vec<Block> = Vec::new();
    let mut text_block_active = false;
    let mut dim_block: Vec<Vec<Field>> = Vec::new();
    let mut header_comment: Vec<HeaderEntry> = Vec::new();
    let mut raw_lines_to_skip = 0usize;

    for (index, original_line) in raw_lines.iter().enumerate() {
        if raw_lines_to_skip > 0 {
            raw_lines_to_skip -= 1;
            continue;
        }

        let prev_line = if index > 0 {
            Some(raw_lines[index - 1].as_str())
        } else {
            None
        };
        let mut line = original_line.clone();

        if is_comment_or_header(&line) {
            let end = (index + 10).min(raw_lines.len());
            let (header, skip_count) = extract_header_comment(&raw_lines[index..end]);
            line = header;
            raw_lines_to_skip = skip_count;
        }

        if !is_comment_or_header(&line) && line.split_whitespace().count() == 3 {
            if index == raw_lines.len() - 1 && text_block_active {
                finalize_block(&mut pdf_blocks_text, &header_comment, &dim_block);
                text_block_active = false;
                header_comment.clear();
                dim_block.clear();
            }
            continue;
        }

        if text_block_active {
            if is_comment_or_header(&line) || is_dim_line(&line) {
                if is_comment_or_header(&line) && prev_line.is_some_and(is_comment_or_header) {
                    header_comment.push(HeaderEntry::Text(strip_comment_prefix(&line)));
                }

                if is_dim_line(&line) && prev_line.is_some_and(|value| !is_comment_or_header(value))
                {
                    finalize_block(&mut pdf_blocks_text, &header_comment, &dim_block);
                    text_block_active = true;
                    dim_block.clear();
                }

                if is_comment_or_header(&line)
                    && prev_line.is_some_and(|value| !is_comment_or_header(value))
                {
                    finalize_block(&mut pdf_blocks_text, &header_comment, &dim_block);
                    text_block_active = true;
                    header_comment.clear();
                    dim_block.clear();
                    header_comment.push(HeaderEntry::Text(strip_comment_prefix(&line)));
                }
            } else {
                let tokens: Vec<String> =
                    line.split_whitespace().map(ToString::to_string).collect();
                if !tokens.is_empty() && measurement_line_map(&tokens[0]) > 0 {
                    let preserve_non_numeric_tokens = tokens[0].starts_with("TP");
                    let (parsed_tokens, consumed) =
                        extract_measurement_tokens_and_raw_lines_consumed(
                            &raw_lines[index..],
                            preserve_non_numeric_tokens,
                        );
                    raw_lines_to_skip = consumed.saturating_sub(1);
                    let temp_line = process_line(&parsed_tokens);
                    if !temp_line.is_empty() {
                        dim_block.push(temp_line);
                    }
                }
            }
        } else if pdf_blocks_text.is_empty() {
            if is_comment_or_header(&line) {
                header_comment.push(HeaderEntry::Text(strip_comment_prefix(&line)));
                text_block_active = true;
            } else if is_dim_line(&line) {
                header_comment.push(HeaderEntry::NoHeader);
                text_block_active = true;
            }
        } else {
            if is_dim_line(&line) || is_comment_or_header(&line) {
                finalize_block(&mut pdf_blocks_text, &header_comment, &dim_block);
                text_block_active = false;
                dim_block.clear();
            }
            if is_comment_or_header(&line) {
                header_comment.clear();
                dim_block.clear();
                header_comment.push(HeaderEntry::Text(strip_comment_prefix(&line)));
                text_block_active = true;
            }
        }

        if index == raw_lines.len() - 1 && text_block_active {
            finalize_block(&mut pdf_blocks_text, &header_comment, &dim_block);
            text_block_active = false;
            header_comment.clear();
            dim_block.clear();
        }
    }

    if text_block_active {
        let candidate = Block {
            header_comment: header_comment.clone(),
            dimensions: dim_block.clone(),
        };
        if pdf_blocks_text.last() != Some(&candidate) {
            pdf_blocks_text.push(candidate);
        }
    }

    add_tolerances_to_blocks(&mut pdf_blocks_text);
    pdf_blocks_text
}

fn blocks_to_pyobject(py: Python<'_>, blocks: &[Block]) -> PyResult<PyObject> {
    let py_blocks = PyList::empty_bound(py);
    for block in blocks {
        let py_header = PyList::empty_bound(py);
        for entry in &block.header_comment {
            match entry {
                HeaderEntry::Text(value) => {
                    let nested = PyList::new_bound(py, [value.as_str()]);
                    py_header.append(nested)?;
                }
                HeaderEntry::NoHeader => py_header.append("NO HEADER")?,
            }
        }

        let py_dims = PyList::empty_bound(py);
        for measurement_line in &block.dimensions {
            let py_line = PyList::empty_bound(py);
            for field in measurement_line {
                match field {
                    Field::Text(value) => py_line.append(value.as_str())?,
                    Field::Float(value) => py_line.append(*value)?,
                    Field::Empty => py_line.append("")?,
                }
            }
            py_dims.append(py_line)?;
        }

        let py_block = PyList::empty_bound(py);
        py_block.append(py_header)?;
        py_block.append(py_dims)?;
        py_blocks.append(py_block)?;
    }
    Ok(py_blocks.into_py(py))
}

#[pyfunction]
fn parse_blocks(py: Python<'_>, raw_lines: &PyAny) -> PyResult<PyObject> {
    let lines = raw_lines.downcast::<PyList>()?;
    let mut rust_lines = Vec::with_capacity(lines.len());
    for item in lines.iter() {
        rust_lines.push(item.extract::<String>()?);
    }

    let blocks = parse_raw_lines_to_blocks_native(&rust_lines);
    blocks_to_pyobject(py, &blocks)
}

#[pymodule]
fn _metroliza_cmm_native(py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_blocks, m)?)?;
    let _ = py;
    Ok(())
}
