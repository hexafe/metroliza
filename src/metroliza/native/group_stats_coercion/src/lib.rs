use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::prelude::*;
use pyo3::types::PyString;
use pyo3::types::PySequence;

#[pyfunction]
fn coerce_sequence_to_float64<'py>(
    py: Python<'py>,
    values: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    if let Ok(array) = values.extract::<PyReadonlyArray1<'_, f64>>() {
        let out = array
            .as_slice()
            .map(|slice| slice.to_vec())
            .unwrap_or_else(|_| array.as_array().iter().copied().collect::<Vec<f64>>());
        return Ok(out.into_pyarray_bound(py));
    }

    let sequence = values.downcast::<PySequence>()?;
    let len = sequence.len()?;
    let mut out = Vec::with_capacity(len);

    for idx in 0..len {
        let item = sequence.get_item(idx)?;
        let value = if let Ok(v) = item.extract::<f64>() {
            v
        } else if let Ok(v) = item.extract::<i64>() {
            v as f64
        } else if let Ok(v) = item.downcast::<PyString>() {
            v.to_str()
                .ok()
                .and_then(|s| s.parse::<f64>().ok())
                .unwrap_or(f64::NAN)
        } else {
            f64::NAN
        };
        out.push(value);
    }

    Ok(out.into_pyarray_bound(py))
}

#[pymodule]
fn _metroliza_group_stats_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(coerce_sequence_to_float64, m)?)?;
    Ok(())
}
