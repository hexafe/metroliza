use image::{DynamicImage, ImageFormat, Rgba, RgbaImage};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyModule};
use std::io::Cursor;

const WIDTH: u32 = 800;
const HEIGHT: u32 = 400;

fn set_pixel_safe(image: &mut RgbaImage, x: i32, y: i32, color: Rgba<u8>) {
    if x < 0 || y < 0 {
        return;
    }
    let ux = x as u32;
    let uy = y as u32;
    if ux < image.width() && uy < image.height() {
        image.put_pixel(ux, uy, color);
    }
}

fn draw_rect_fill(image: &mut RgbaImage, x0: i32, y0: i32, x1: i32, y1: i32, color: Rgba<u8>) {
    let xmin = x0.min(x1);
    let xmax = x0.max(x1);
    let ymin = y0.min(y1);
    let ymax = y0.max(y1);
    for y in ymin..=ymax {
        for x in xmin..=xmax {
            set_pixel_safe(image, x, y, color);
        }
    }
}

fn draw_vertical_line(image: &mut RgbaImage, x: i32, y0: i32, y1: i32, color: Rgba<u8>) {
    let ymin = y0.min(y1);
    let ymax = y0.max(y1);
    for y in ymin..=ymax {
        set_pixel_safe(image, x, y, color);
    }
}

fn draw_horizontal_line(image: &mut RgbaImage, x0: i32, x1: i32, y: i32, color: Rgba<u8>) {
    let xmin = x0.min(x1);
    let xmax = x0.max(x1);
    for x in xmin..=xmax {
        set_pixel_safe(image, x, y, color);
    }
}

fn get_payload_dict<'py>(payload: &'py Bound<'py, PyAny>) -> PyResult<&'py Bound<'py, PyDict>> {
    payload
        .downcast::<PyDict>()
        .map_err(|_| PyValueError::new_err("payload must be a dict"))
}

fn get_values(payload: &Bound<'_, PyDict>) -> PyResult<Vec<f64>> {
    let raw_values = payload
        .get_item("values")?
        .ok_or_else(|| PyValueError::new_err("payload.values is required"))?;

    let values: Vec<f64> = raw_values
        .extract()
        .map_err(|_| PyValueError::new_err("payload.values must be a list of numeric values"))?;

    let finite: Vec<f64> = values.into_iter().filter(|v| v.is_finite()).collect();
    if finite.is_empty() {
        return Err(PyValueError::new_err(
            "payload.values must contain at least one finite number",
        ));
    }
    Ok(finite)
}

fn get_optional_f64(payload: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<f64>> {
    match payload.get_item(key)? {
        None => Ok(None),
        Some(value) => {
            if value.is_none() {
                Ok(None)
            } else {
                let parsed: f64 = value.extract().map_err(|_| {
                    PyValueError::new_err(format!("payload.{key} must be numeric or None"))
                })?;
                if parsed.is_finite() {
                    Ok(Some(parsed))
                } else {
                    Ok(None)
                }
            }
        }
    }
}

fn get_bin_count(payload: &Bound<'_, PyDict>, sample_len: usize) -> PyResult<usize> {
    let default_bins = ((sample_len as f64).sqrt().round() as usize).clamp(5, 60);
    match payload.get_item("bin_count")? {
        None => Ok(default_bins),
        Some(value) => {
            if value.is_none() {
                return Ok(default_bins);
            }
            let count: usize = value.extract().map_err(|_| {
                PyValueError::new_err("payload.bin_count must be a positive integer or None")
            })?;
            if count == 0 {
                return Err(PyValueError::new_err(
                    "payload.bin_count must be >= 1 when provided",
                ));
            }
            Ok(count.clamp(1, 512))
        }
    }
}

#[pyfunction]
fn render_histogram_png(py: Python<'_>, payload: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let payload = get_payload_dict(payload)?;
    let values = get_values(payload)?;
    let lsl = get_optional_f64(payload, "lsl")?;
    let usl = get_optional_f64(payload, "usl")?;
    let bin_count = get_bin_count(payload, values.len())?;

    let mut min_value = values
        .iter()
        .copied()
        .fold(f64::INFINITY, |acc, value| acc.min(value));
    let mut max_value = values
        .iter()
        .copied()
        .fold(f64::NEG_INFINITY, |acc, value| acc.max(value));

    if !min_value.is_finite() || !max_value.is_finite() {
        return Err(PyValueError::new_err(
            "payload.values produced invalid range",
        ));
    }

    if (max_value - min_value).abs() < f64::EPSILON {
        min_value -= 0.5;
        max_value += 0.5;
    }

    let range = (max_value - min_value).max(f64::EPSILON);
    let mut bins = vec![0usize; bin_count];
    for value in &values {
        let ratio = ((*value - min_value) / range).clamp(0.0, 1.0);
        let mut idx = (ratio * bin_count as f64).floor() as usize;
        if idx >= bin_count {
            idx = bin_count - 1;
        }
        bins[idx] += 1;
    }

    let max_count = bins.iter().copied().max().unwrap_or(1).max(1);

    let mut image = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba([255, 255, 255, 255]));
    let margin_left: i32 = 56;
    let margin_right: i32 = 20;
    let margin_top: i32 = 24;
    let margin_bottom: i32 = 40;

    let plot_x0 = margin_left;
    let plot_x1 = WIDTH as i32 - margin_right;
    let plot_y0 = margin_top;
    let plot_y1 = HEIGHT as i32 - margin_bottom;

    let black = Rgba([30, 30, 30, 255]);
    let bar_fill = Rgba([79, 129, 189, 255]);
    let spec_red = Rgba([200, 55, 55, 255]);

    draw_horizontal_line(&mut image, plot_x0, plot_x1, plot_y1, black);
    draw_vertical_line(&mut image, plot_x0, plot_y0, plot_y1, black);

    let plot_width = (plot_x1 - plot_x0).max(1);
    let bin_width = (plot_width as f64 / bin_count as f64).max(1.0);
    let plot_height = (plot_y1 - plot_y0).max(1);

    for (idx, count) in bins.iter().enumerate() {
        let x_start = plot_x0 + (idx as f64 * bin_width).floor() as i32 + 1;
        let mut x_end = plot_x0 + (((idx + 1) as f64) * bin_width).floor() as i32 - 1;
        if x_end < x_start {
            x_end = x_start;
        }

        let height_ratio = *count as f64 / max_count as f64;
        let bar_height = (height_ratio * plot_height as f64).round() as i32;
        let y_start = (plot_y1 - bar_height).clamp(plot_y0, plot_y1);

        draw_rect_fill(&mut image, x_start, y_start, x_end, plot_y1 - 1, bar_fill);
    }

    let draw_spec = |image: &mut RgbaImage, spec_value: f64| {
        let ratio = ((spec_value - min_value) / range).clamp(0.0, 1.0);
        let x = plot_x0 + (ratio * plot_width as f64).round() as i32;
        draw_vertical_line(image, x, plot_y0, plot_y1, spec_red);
    };

    if let Some(value) = lsl {
        draw_spec(&mut image, value);
    }
    if let Some(value) = usl {
        draw_spec(&mut image, value);
    }

    let mut bytes = Vec::new();
    DynamicImage::ImageRgba8(image)
        .write_to(&mut Cursor::new(&mut bytes), ImageFormat::Png)
        .map_err(|err| PyValueError::new_err(format!("failed to encode png: {err}")))?;

    Ok(pyo3::types::PyBytes::new_bound(py, &bytes).into_py(py))
}

#[pymodule]
fn _metroliza_chart_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(render_histogram_png, m)?)?;
    Ok(())
}
