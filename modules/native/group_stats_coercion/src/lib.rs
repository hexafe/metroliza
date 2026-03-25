use numpy::{IntoPyArray, PyArray1};
use pyo3::prelude::*;
use pyo3::types::PySequence;

#[pyfunction]
fn coerce_sequence_to_float64<'py>(
    py: Python<'py>,
    values: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let sequence = values.downcast::<PySequence>()?;
    let len = sequence.len()?;
    let mut out = Vec::with_capacity(len);
    let builtins = py.import_bound("builtins")?;
    let float_fn = builtins.getattr("float")?;

    for idx in 0..len {
        let item = sequence.get_item(idx)?;
        let value = float_fn
            .call1((item,))
            .and_then(|as_float| as_float.extract::<f64>())
            .unwrap_or(f64::NAN);
        out.push(value);
    }

    Ok(out.into_pyarray_bound(py))
}

#[pymodule]
fn _metroliza_group_stats_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(coerce_sequence_to_float64, m)?)?;
    Ok(())
}
