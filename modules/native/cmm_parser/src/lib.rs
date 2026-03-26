use pyo3::prelude::*;
use pyo3::types::PyList;
use pyo3::types::PyTuple;
use rusqlite::params;
use rusqlite::types::Value as SqlValue;
use rusqlite::Connection;

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

#[derive(Clone, Debug, PartialEq)]
struct FlatMeasurementRow {
    ax: String,
    nom: SqlValue,
    tol_plus: SqlValue,
    tol_minus: SqlValue,
    bonus: SqlValue,
    meas: SqlValue,
    dev: SqlValue,
    outtol: SqlValue,
    header: String,
    reference: String,
    fileloc: String,
    filename: String,
    date: String,
    sample_number: String,
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

#[derive(Clone, Copy, Debug, PartialEq)]
enum ParsedToken<'a> {
    Number(f64),
    Text(&'a str),
}

fn parse_token(token: &str) -> ParsedToken<'_> {
    match token.trim().parse::<f64>() {
        Ok(value) => ParsedToken::Number(value),
        Err(_) => ParsedToken::Text(token),
    }
}

fn parse_line_tokens(line: &str) -> Vec<ParsedToken<'_>> {
    line.split_whitespace().map(parse_token).collect()
}

fn is_number(value: &str) -> bool {
    matches!(parse_token(value), ParsedToken::Number(_))
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
) -> (Vec<ParsedToken<'_>>, usize) {
    if lines.is_empty() {
        return (Vec::new(), 0);
    }

    let code_tokens = parse_line_tokens(&lines[0]);
    if code_tokens.is_empty() {
        return (Vec::new(), 0);
    }

    let code = match code_tokens[0] {
        ParsedToken::Text(value) => value,
        ParsedToken::Number(_) => return (Vec::new(), 0),
    };
    let mut parsed_tokens = vec![ParsedToken::Text(code)];
    let mut raw_lines_consumed = 1usize;
    let max_token_count = measurement_line_map(code);
    let max_numeric_count = if max_token_count > 0 {
        max_token_count - 1
    } else {
        0
    };
    let mut numeric_count = 0usize;

    let append_tokens = |parsed_tokens: &mut Vec<ParsedToken<'_>>,
                         tokens: &[ParsedToken<'_>],
                         numeric_count: &mut usize| {
        for token in tokens {
            match token {
                ParsedToken::Number(value) => {
                    parsed_tokens.push(ParsedToken::Number(*value));
                    *numeric_count += 1;
                }
                ParsedToken::Text(value) if preserve_non_numeric_tokens => {
                    parsed_tokens.push(ParsedToken::Text(value));
                }
                ParsedToken::Text(_) => {}
            }
            if max_numeric_count > 0 && *numeric_count >= max_numeric_count {
                break;
            }
        }
    };

    append_tokens(&mut parsed_tokens, &code_tokens[1..], &mut numeric_count);

    for raw_line in lines.iter().skip(1) {
        if max_numeric_count > 0 && numeric_count >= max_numeric_count {
            break;
        }

        let raw_line_tokens = parse_line_tokens(raw_line);
        if raw_line_tokens.is_empty() {
            raw_lines_consumed += 1;
            continue;
        }

        let first_token = match raw_line_tokens[0] {
            ParsedToken::Text(value) => value,
            ParsedToken::Number(_) => "",
        };
        if is_comment_or_header(raw_line)
            || is_dim_line(raw_line)
            || measurement_line_map(first_token) > 0
        {
            break;
        }

        raw_lines_consumed += 1;
        append_tokens(&mut parsed_tokens, &raw_line_tokens, &mut numeric_count);
    }

    (parsed_tokens, raw_lines_consumed)
}

fn process_tp_line(tokens: &[ParsedToken<'_>]) -> Vec<Field> {
    let mut has_tp_qualifier = false;
    let mut has_explicit_nom_label = false;
    let mut numeric_values: Vec<f64> = Vec::new();

    for token in tokens.iter().skip(1) {
        match token {
            ParsedToken::Number(value) => numeric_values.push(*value),
            ParsedToken::Text(value) => {
                let uppercase = value.to_uppercase();
                let normalized = uppercase.trim_end_matches(':');
                if TP_QUALIFIERS.contains(&normalized) {
                    has_tp_qualifier = true;
                } else if TP_SEMANTIC_LABELS.contains(&normalized) && normalized == "NOM" {
                    has_explicit_nom_label = true;
                }
            }
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

fn process_line(line: &[ParsedToken<'_>]) -> Vec<Field> {
    if line.is_empty() {
        return Vec::new();
    }

    let code = match line[0] {
        ParsedToken::Text(value) => value,
        ParsedToken::Number(_) => return Vec::new(),
    };
    if code.starts_with("TP") {
        return process_tp_line(line);
    }

    let numeric_values: Vec<f64> = line
        .iter()
        .skip(1)
        .filter_map(|token| match token {
            ParsedToken::Number(value) => Some(*value),
            ParsedToken::Text(_) => None,
        })
        .collect();

    match (code, numeric_values.len()) {
        ("X" | "Y" | "Z", 4) => vec![
            Field::Text(code.to_string()),
            Field::Float(numeric_values[0]),
            Field::Empty,
            Field::Empty,
            Field::Empty,
            Field::Float(numeric_values[1]),
            Field::Float(numeric_values[2]),
            Field::Empty,
        ],
        ("X" | "Y" | "Z", 7) => vec![
            Field::Text(code.to_string()),
            Field::Float(numeric_values[0]),
            Field::Float(numeric_values[1]),
            Field::Float(numeric_values[2]),
            Field::Empty,
            Field::Float(numeric_values[3]),
            Field::Float(numeric_values[4]),
            Field::Float(numeric_values[5]),
        ],
        ("M", 7) | ("D", 7) | ("RN", 7) | ("PR", 7) => vec![
            Field::Text(code.to_string()),
            Field::Float(numeric_values[0]),
            Field::Float(numeric_values[1]),
            Field::Float(numeric_values[2]),
            Field::Empty,
            Field::Float(numeric_values[3]),
            Field::Float(numeric_values[4]),
            Field::Float(numeric_values[5]),
        ],
        ("M", 8) | ("DF", 8) => vec![
            Field::Text(code.to_string()),
            Field::Float(numeric_values[0]),
            Field::Float(numeric_values[1]),
            Field::Float(numeric_values[2]),
            Field::Float(numeric_values[3]),
            Field::Float(numeric_values[4]),
            Field::Float(numeric_values[5]),
            Field::Float(numeric_values[6]),
        ],
        ("DF", 7) | ("A", 7) => vec![
            Field::Text(code.to_string()),
            Field::Float(numeric_values[0]),
            Field::Float(numeric_values[1]),
            Field::Float(numeric_values[2]),
            Field::Float(0.0),
            Field::Float(numeric_values[3]),
            Field::Float(numeric_values[4]),
            Field::Float(numeric_values[5]),
        ],
        ("PR" | "PA", 4) => vec![
            Field::Text(code.to_string()),
            Field::Float(numeric_values[0]),
            Field::Empty,
            Field::Empty,
            Field::Empty,
            Field::Float(numeric_values[1]),
            Field::Float(numeric_values[2]),
            Field::Empty,
        ],
        ("D1" | "D2" | "D3" | "D4", 5) => vec![
            Field::Text(code.to_string()),
            Field::Float(numeric_values[0]),
            Field::Float(numeric_values[1]),
            Field::Float(numeric_values[2]),
            Field::Empty,
            Field::Float(numeric_values[3]),
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
                let mut tokens = line.split_whitespace();
                if let Some(code) = tokens.next() {
                    if measurement_line_map(code) == 0 {
                        continue;
                    }
                    let preserve_non_numeric_tokens = code.starts_with("TP");
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

fn header_to_string(entries: &[HeaderEntry]) -> String {
    let mut tokens: Vec<String> = Vec::new();
    for entry in entries {
        if let HeaderEntry::Text(value) = entry {
            if !value.is_empty() {
                tokens.push(value.clone());
            }
        }
    }
    tokens.join(", ").replace('\"', "")
}

fn field_to_sql_value(field: Option<&Field>) -> SqlValue {
    match field {
        Some(Field::Float(value)) => SqlValue::Real(*value),
        Some(Field::Text(value)) => SqlValue::Text(value.clone()),
        Some(Field::Empty) | None => SqlValue::Text(String::new()),
    }
}

fn flatten_blocks_to_rows(
    blocks: &[Block],
    reference: &str,
    fileloc: &str,
    filename: &str,
    date: &str,
    sample_number: &str,
) -> Vec<FlatMeasurementRow> {
    let mut rows: Vec<FlatMeasurementRow> = Vec::new();
    for block in blocks {
        let header = header_to_string(&block.header_comment);
        for measurement_line in &block.dimensions {
            let ax = match measurement_line.first() {
                Some(Field::Text(value)) => value.clone(),
                Some(Field::Float(value)) => value.to_string(),
                _ => String::new(),
            };
            rows.push(FlatMeasurementRow {
                ax,
                nom: field_to_sql_value(measurement_line.get(1)),
                tol_plus: field_to_sql_value(measurement_line.get(2)),
                tol_minus: field_to_sql_value(measurement_line.get(3)),
                bonus: field_to_sql_value(measurement_line.get(4)),
                meas: field_to_sql_value(measurement_line.get(5)),
                dev: field_to_sql_value(measurement_line.get(6)),
                outtol: field_to_sql_value(measurement_line.get(7)),
                header: header.clone(),
                reference: reference.to_string(),
                fileloc: fileloc.to_string(),
                filename: filename.to_string(),
                date: date.to_string(),
                sample_number: sample_number.to_string(),
            });
        }
    }
    rows
}

fn sql_value_to_py(py: Python<'_>, value: &SqlValue) -> PyObject {
    match value {
        SqlValue::Integer(v) => v.into_py(py),
        SqlValue::Real(v) => v.into_py(py),
        SqlValue::Text(v) => v.into_py(py),
        SqlValue::Null => "".into_py(py),
        SqlValue::Blob(v) => String::from_utf8_lossy(v).to_string().into_py(py),
    }
}

fn flat_rows_to_pyobject(py: Python<'_>, rows: &[FlatMeasurementRow]) -> PyResult<PyObject> {
    let py_rows = PyList::empty_bound(py);
    for row in rows {
        let tuple = PyTuple::new_bound(
            py,
            [
                row.ax.as_str().into_py(py),
                sql_value_to_py(py, &row.nom),
                sql_value_to_py(py, &row.tol_plus),
                sql_value_to_py(py, &row.tol_minus),
                sql_value_to_py(py, &row.bonus),
                sql_value_to_py(py, &row.meas),
                sql_value_to_py(py, &row.dev),
                sql_value_to_py(py, &row.outtol),
                row.header.as_str().into_py(py),
                row.reference.as_str().into_py(py),
                row.fileloc.as_str().into_py(py),
                row.filename.as_str().into_py(py),
                row.date.as_str().into_py(py),
                row.sample_number.as_str().into_py(py),
            ],
        );
        py_rows.append(tuple)?;
    }
    Ok(py_rows.into_py(py))
}

fn py_scalar_to_sql_value(value: &PyAny) -> PyResult<SqlValue> {
    if let Ok(v) = value.extract::<f64>() {
        return Ok(SqlValue::Real(v));
    }
    if let Ok(v) = value.extract::<i64>() {
        return Ok(SqlValue::Real(v as f64));
    }
    if let Ok(v) = value.extract::<String>() {
        return Ok(SqlValue::Text(v));
    }
    Ok(SqlValue::Text(String::new()))
}

fn py_rows_to_flat_rows(rows: &PyAny) -> PyResult<Vec<FlatMeasurementRow>> {
    let py_rows = rows.downcast::<PyList>()?;
    let mut normalized: Vec<FlatMeasurementRow> = Vec::with_capacity(py_rows.len());
    for item in py_rows.iter() {
        let tuple = item.downcast::<PyTuple>()?;
        if tuple.len() != 14 {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "measurement row must have 14 columns",
            ));
        }
        normalized.push(FlatMeasurementRow {
            ax: tuple.get_item(0)?.extract::<String>()?,
            nom: py_scalar_to_sql_value(tuple.get_item(1)?)?,
            tol_plus: py_scalar_to_sql_value(tuple.get_item(2)?)?,
            tol_minus: py_scalar_to_sql_value(tuple.get_item(3)?)?,
            bonus: py_scalar_to_sql_value(tuple.get_item(4)?)?,
            meas: py_scalar_to_sql_value(tuple.get_item(5)?)?,
            dev: py_scalar_to_sql_value(tuple.get_item(6)?)?,
            outtol: py_scalar_to_sql_value(tuple.get_item(7)?)?,
            header: tuple.get_item(8)?.extract::<String>()?,
            reference: tuple.get_item(9)?.extract::<String>()?,
            fileloc: tuple.get_item(10)?.extract::<String>()?,
            filename: tuple.get_item(11)?.extract::<String>()?,
            date: tuple.get_item(12)?.extract::<String>()?,
            sample_number: tuple.get_item(13)?.extract::<String>()?,
        });
    }
    Ok(normalized)
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

#[pyfunction]
fn normalize_measurement_rows(
    py: Python<'_>,
    blocks: &PyAny,
    reference: String,
    fileloc: String,
    filename: String,
    date: String,
    sample_number: String,
) -> PyResult<PyObject> {
    let lines = blocks.downcast::<PyList>()?;
    let mut rust_blocks: Vec<Block> = Vec::with_capacity(lines.len());
    for block_any in lines.iter() {
        let block = block_any.downcast::<PyList>()?;
        let header_py = block.get_item(0)?;
        let dims_py = block.get_item(1)?;

        let mut header_comment: Vec<HeaderEntry> = Vec::new();
        for header_entry in header_py.downcast::<PyList>()?.iter() {
            if let Ok(value) = header_entry.extract::<String>() {
                if value == "NO HEADER" {
                    header_comment.push(HeaderEntry::NoHeader);
                } else {
                    header_comment.push(HeaderEntry::Text(value));
                }
            } else if let Ok(nested) = header_entry.downcast::<PyList>() {
                for token in nested.iter() {
                    if let Ok(text) = token.extract::<String>() {
                        header_comment.push(HeaderEntry::Text(text));
                    }
                }
            }
        }

        let mut dimensions: Vec<Vec<Field>> = Vec::new();
        for row_any in dims_py.downcast::<PyList>()?.iter() {
            let row = row_any.downcast::<PyList>()?;
            let mut fields: Vec<Field> = Vec::new();
            for token in row.iter() {
                if let Ok(text) = token.extract::<String>() {
                    if text.is_empty() {
                        fields.push(Field::Empty);
                    } else {
                        fields.push(Field::Text(text));
                    }
                } else if let Ok(value) = token.extract::<f64>() {
                    fields.push(Field::Float(value));
                } else if let Ok(value) = token.extract::<i64>() {
                    fields.push(Field::Float(value as f64));
                } else {
                    fields.push(Field::Empty);
                }
            }
            dimensions.push(fields);
        }

        rust_blocks.push(Block {
            header_comment,
            dimensions,
        });
    }

    let rows = flatten_blocks_to_rows(
        &rust_blocks,
        &reference,
        &fileloc,
        &filename,
        &date,
        &sample_number,
    );
    flat_rows_to_pyobject(py, &rows)
}

#[pyfunction]
fn persist_measurement_rows(database: String, rows: &PyAny) -> PyResult<bool> {
    let normalized_rows = py_rows_to_flat_rows(rows)?;
    if normalized_rows.is_empty() {
        return Ok(false);
    }

    let first = &normalized_rows[0];
    let mut conn = Connection::open(database)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;
    let tx = conn
        .transaction()
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;

    tx.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS MEASUREMENTS (
            ID INTEGER PRIMARY KEY,
            AX TEXT,
            NOM REAL,
            "+TOL" REAL,
            "-TOL" REAL,
            BONUS REAL,
            MEAS REAL,
            DEV REAL,
            OUTTOL REAL,
            HEADER TEXT,
            REPORT_ID INTEGER,
            FOREIGN KEY (REPORT_ID) REFERENCES REPORTS(ID)
        );
        CREATE TABLE IF NOT EXISTS REPORTS (
            ID INTEGER PRIMARY KEY,
            REFERENCE TEXT,
            FILELOC TEXT,
            FILENAME TEXT,
            DATE TEXT,
            SAMPLE_NUMBER TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reports_reference ON REPORTS(REFERENCE);
        CREATE INDEX IF NOT EXISTS idx_reports_filename ON REPORTS(FILENAME);
        CREATE INDEX IF NOT EXISTS idx_reports_date ON REPORTS(DATE);
        CREATE INDEX IF NOT EXISTS idx_reports_sample_number ON REPORTS(SAMPLE_NUMBER);
        CREATE INDEX IF NOT EXISTS idx_reports_identity ON REPORTS(REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER);
        CREATE INDEX IF NOT EXISTS idx_measurements_report_id ON MEASUREMENTS(REPORT_ID);
        CREATE INDEX IF NOT EXISTS idx_measurements_report_header_ax ON MEASUREMENTS(REPORT_ID, HEADER, AX);
        CREATE INDEX IF NOT EXISTS idx_measurements_header ON MEASUREMENTS(HEADER);
        CREATE INDEX IF NOT EXISTS idx_measurements_ax ON MEASUREMENTS(AX);
        "#,
    )
    .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;

    let duplicate_count: i64 = tx
        .query_row(
            "SELECT COUNT(*) FROM REPORTS WHERE REFERENCE = ?1 AND FILELOC = ?2 AND FILENAME = ?3 AND DATE = ?4 AND SAMPLE_NUMBER = ?5",
            params![
                first.reference,
                first.fileloc,
                first.filename,
                first.date,
                first.sample_number
            ],
            |row| row.get(0),
        )
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;

    if duplicate_count > 0 {
        tx.commit()
            .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;
        return Ok(false);
    }

    tx.execute(
        "INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![
            first.reference,
            first.fileloc,
            first.filename,
            first.date,
            first.sample_number
        ],
    )
    .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;
    let report_id = tx.last_insert_rowid();

    let mut stmt = tx
        .prepare(
            "INSERT INTO MEASUREMENTS VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        )
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;
    for row in &normalized_rows {
        stmt.execute(params![
            Option::<i64>::None,
            row.ax,
            row.nom,
            row.tol_plus,
            row.tol_minus,
            row.bonus,
            row.meas,
            row.dev,
            row.outtol,
            row.header,
            report_id,
        ])
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;
    }
    drop(stmt);

    tx.commit()
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(err.to_string()))?;
    Ok(true)
}

#[pymodule]
fn _metroliza_cmm_native(py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_blocks, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_measurement_rows, m)?)?;
    m.add_function(wrap_pyfunction!(persist_measurement_rows, m)?)?;
    let _ = py;
    Ok(())
}
