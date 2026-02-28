use pyo3::prelude::*;
use pyo3::types::{PyAny, PyList};

/// Prototype parser entrypoint.
///
/// For initial parity rollout, native path delegates to Python reference
/// implementation so tokenization orchestration remains byte-for-byte stable.
#[pyfunction]
fn parse_blocks(py: Python<'_>, raw_lines: &PyAny) -> PyResult<PyObject> {
    let modules = py.import("modules.cmm_parsing")?;
    let parser = modules.getattr("parse_raw_lines_to_blocks")?;

    let lines = raw_lines.downcast::<PyList>()?;
    let parsed = parser.call1((lines,))?;
    Ok(parsed.into_py(py))
}

#[pymodule]
fn _metroliza_cmm_native(py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_blocks, m)?)?;
    // Keep py referenced in signature for pyo3 compatibility and future extensions.
    let _ = py;
    Ok(())
}
