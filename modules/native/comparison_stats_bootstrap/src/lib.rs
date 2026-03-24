use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

fn cohen_d(sample_a: &[f64], sample_b: &[f64]) -> Option<f64> {
    if sample_a.len() < 2 || sample_b.len() < 2 {
        return None;
    }
    let n_a = sample_a.len() as f64;
    let n_b = sample_b.len() as f64;
    let mean_a = sample_a.iter().sum::<f64>() / n_a;
    let mean_b = sample_b.iter().sum::<f64>() / n_b;

    let var_a = sample_a
        .iter()
        .map(|v| (v - mean_a).powi(2))
        .sum::<f64>()
        / (n_a - 1.0);
    let var_b = sample_b
        .iter()
        .map(|v| (v - mean_b).powi(2))
        .sum::<f64>()
        / (n_b - 1.0);

    let pooled_den = n_a + n_b - 2.0;
    if pooled_den <= 0.0 {
        return None;
    }
    let pooled = ((n_a - 1.0) * var_a + (n_b - 1.0) * var_b) / pooled_den;
    if !(pooled > 0.0) {
        return None;
    }
    Some((mean_a - mean_b) / pooled.sqrt())
}

fn cliffs_delta(sample_a: &[f64], sample_b: &[f64]) -> Option<f64> {
    if sample_a.is_empty() || sample_b.is_empty() {
        return None;
    }
    let n_a = sample_a.len() as f64;
    let n_b = sample_b.len() as f64;

    let mut pooled: Vec<(f64, bool)> = Vec::with_capacity(sample_a.len() + sample_b.len());
    pooled.extend(sample_a.iter().copied().map(|v| (v, true)));
    pooled.extend(sample_b.iter().copied().map(|v| (v, false)));
    pooled.sort_by(|left, right| left.0.partial_cmp(&right.0).unwrap_or(std::cmp::Ordering::Equal));

    let mut idx = 0usize;
    let mut rank_sum_a = 0.0f64;
    while idx < pooled.len() {
        let start = idx;
        let value = pooled[idx].0;
        while idx < pooled.len() && pooled[idx].0 == value {
            idx += 1;
        }
        let end = idx;
        let avg_rank = (start as f64 + 1.0 + end as f64) / 2.0;
        let count_a = pooled[start..end].iter().filter(|(_, is_a)| *is_a).count() as f64;
        rank_sum_a += avg_rank * count_a;
    }

    let u_statistic = rank_sum_a - (n_a * (n_a + 1.0) / 2.0);
    Some((2.0 * u_statistic) / (n_a * n_b) - 1.0)
}

fn eta_or_omega_squared(groups: &[Vec<f64>], use_omega: bool) -> Option<f64> {
    if groups.len() < 2 {
        return None;
    }
    if groups.iter().any(|g| g.len() < 2) {
        return None;
    }

    let total_count: usize = groups.iter().map(|g| g.len()).sum();
    let values: Vec<f64> = groups.iter().flat_map(|g| g.iter().copied()).collect();
    let grand_mean = values.iter().sum::<f64>() / values.len() as f64;

    let mut ss_between = 0.0;
    let mut ss_within = 0.0;
    for group in groups {
        let n = group.len() as f64;
        let mean = group.iter().sum::<f64>() / n;
        ss_between += n * (mean - grand_mean).powi(2);
        ss_within += group.iter().map(|v| (v - mean).powi(2)).sum::<f64>();
    }
    let ss_total = ss_between + ss_within;
    if ss_total.abs() <= f64::EPSILON {
        return None;
    }
    if !use_omega {
        return Some(ss_between / ss_total);
    }

    let df_between = (groups.len() - 1) as f64;
    let df_within = (total_count - groups.len()) as f64;
    if df_within <= 0.0 {
        return None;
    }
    let ms_within = ss_within / df_within;
    let denom = ss_total + ms_within;
    if denom.abs() <= f64::EPSILON {
        return None;
    }
    Some(((ss_between - (df_between * ms_within)) / denom).max(0.0))
}

fn percentile_linear(sorted: &[f64], q: f64) -> f64 {
    if sorted.len() == 1 {
        return sorted[0];
    }
    let rank = (q / 100.0) * (sorted.len() - 1) as f64;
    let low = rank.floor() as usize;
    let high = rank.ceil() as usize;
    if low == high {
        return sorted[low];
    }
    let weight = rank - low as f64;
    sorted[low] * (1.0 - weight) + sorted[high] * weight
}

fn evaluate_kernel(effect_kernel: &str, groups: &[Vec<f64>]) -> Option<f64> {
    match effect_kernel {
        "cohen_d" => {
            if groups.len() != 2 {
                return None;
            }
            cohen_d(&groups[0], &groups[1])
        }
        "cliffs_delta" => {
            if groups.len() != 2 {
                return None;
            }
            cliffs_delta(&groups[0], &groups[1])
        }
        "eta_squared" => eta_or_omega_squared(groups, false),
        "omega_squared" => eta_or_omega_squared(groups, true),
        _ => None,
    }
}

#[pyfunction]
#[pyo3(signature = (effect_kernel, groups, level, iterations, seed))]
fn bootstrap_percentile_ci(
    effect_kernel: &str,
    groups: Vec<Vec<f64>>,
    level: f64,
    iterations: usize,
    seed: u64,
) -> PyResult<Option<(f64, f64)>> {
    if !(0.0 < level && level < 1.0) {
        return Err(PyValueError::new_err("level must be between 0 and 1"));
    }
    if iterations == 0 || groups.is_empty() || groups.iter().any(|g| g.is_empty()) {
        return Ok(None);
    }

    let mut rng = StdRng::seed_from_u64(seed);
    let mut estimates: Vec<f64> = Vec::with_capacity(iterations);
    for _ in 0..iterations.max(1) {
        let sampled_groups: Vec<Vec<f64>> = groups
            .iter()
            .map(|group| {
                (0..group.len())
                    .map(|_| {
                        let idx = rng.gen_range(0..group.len());
                        group[idx]
                    })
                    .collect::<Vec<f64>>()
            })
            .collect();

        if let Some(estimate) = evaluate_kernel(effect_kernel, &sampled_groups) {
            if estimate.is_finite() {
                estimates.push(estimate);
            }
        }
    }

    if estimates.is_empty() {
        return Ok(None);
    }
    estimates.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let lower_q = ((1.0 - level) / 2.0) * 100.0;
    let upper_q = (1.0 - (1.0 - level) / 2.0) * 100.0;
    Ok(Some((
        percentile_linear(&estimates, lower_q),
        percentile_linear(&estimates, upper_q),
    )))
}

#[pymodule]
fn _metroliza_comparison_stats_native(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(bootstrap_percentile_ci, m)?)?;
    Ok(())
}
