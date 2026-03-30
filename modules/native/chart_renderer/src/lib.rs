use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyModule};

fn call_python_renderer(
    py: Python<'_>,
    function_name: &str,
    payload: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let module = PyModule::import_bound(py, "modules.native_chart_compositor").map_err(|err| {
        PyRuntimeError::new_err(format!(
            "failed to import modules.native_chart_compositor for native chart rendering: {err}"
        ))
    })?;
    let function = module.getattr(function_name).map_err(|err| {
        PyRuntimeError::new_err(format!(
            "native chart compositor is missing `{function_name}`: {err}"
        ))
    })?;
    let result = function.call1((payload,)).map_err(|err| {
        PyRuntimeError::new_err(format!(
            "native chart compositor `{function_name}` failed: {err}"
        ))
    })?;
    Ok(result.into_py(py))
}

#[pyfunction]
fn render_histogram_png(py: Python<'_>, payload: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    call_python_renderer(py, "render_histogram_png", payload)
}

#[pyfunction]
fn render_distribution_png(py: Python<'_>, payload: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    call_python_renderer(py, "render_distribution_png", payload)
}

#[pyfunction]
fn render_iqr_png(py: Python<'_>, payload: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    call_python_renderer(py, "render_iqr_png", payload)
}

#[pyfunction]
fn render_trend_png(py: Python<'_>, payload: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    call_python_renderer(py, "render_trend_png", payload)
}

#[pymodule]
fn _metroliza_chart_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(render_histogram_png, m)?)?;
    m.add_function(wrap_pyfunction!(render_distribution_png, m)?)?;
    m.add_function(wrap_pyfunction!(render_iqr_png, m)?)?;
    m.add_function(wrap_pyfunction!(render_trend_png, m)?)?;
    Ok(())
}
