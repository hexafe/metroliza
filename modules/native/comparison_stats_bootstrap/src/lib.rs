use numpy::PyReadonlyArray1;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use statrs::distribution::{ContinuousCDF, Normal, StudentsT};

fn cohen_d(sample_a: &[f64], sample_b: &[f64]) -> Option<f64> {
    if sample_a.len() < 2 || sample_b.len() < 2 {
        return None;
    }
    let n_a = sample_a.len() as f64;
    let n_b = sample_b.len() as f64;
    let mean_a = sample_a.iter().sum::<f64>() / n_a;
    let mean_b = sample_b.iter().sum::<f64>() / n_b;

    let var_a = sample_a.iter().map(|v| (v - mean_a).powi(2)).sum::<f64>() / (n_a - 1.0);
    let var_b = sample_b.iter().map(|v| (v - mean_b).powi(2)).sum::<f64>() / (n_b - 1.0);

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

fn eta_or_omega_squared(groups: &[&[f64]], use_omega: bool) -> Option<f64> {
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

fn evaluate_kernel(effect_kernel: &str, groups: &[&[f64]]) -> Option<f64> {
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

fn normalize_correction_method(method: &str) -> String {
    match method.trim().to_lowercase().replace('-', "_").as_str() {
        "holm_bonferroni" => "holm".to_string(),
        "benjamini_hochberg" => "bh".to_string(),
        "fdr_bh" => "bh".to_string(),
        value => value.to_string(),
    }
}

fn adjust_pvalues(p_values: &[Option<f64>], method: &str) -> PyResult<Vec<Option<f64>>> {
    let mut indexed: Vec<(usize, f64)> = p_values
        .iter()
        .enumerate()
        .filter_map(|(idx, p)| p.and_then(|value| if value.is_finite() { Some((idx, value)) } else { None }))
        .collect();
    let mut adjusted = vec![None; p_values.len()];
    if indexed.is_empty() {
        return Ok(adjusted);
    }
    indexed.sort_by(|left, right| left.1.partial_cmp(&right.1).unwrap_or(std::cmp::Ordering::Equal));

    let m = indexed.len() as f64;
    match normalize_correction_method(method).as_str() {
        "holm" => {
            let mut running_max = 0.0f64;
            for (rank, (original_idx, p_value)) in indexed.iter().enumerate() {
                let factor = m - rank as f64;
                let corrected = (p_value * factor).min(1.0);
                running_max = running_max.max(corrected);
                adjusted[*original_idx] = Some(running_max);
            }
        }
        "bh" => {
            let mut running_min = 1.0f64;
            for (reverse_rank, (original_idx, p_value)) in indexed.iter().rev().enumerate() {
                let rank = indexed.len() - reverse_rank;
                let corrected = (p_value * m / rank as f64).min(1.0);
                running_min = running_min.min(corrected);
                adjusted[*original_idx] = Some(running_min);
            }
        }
        _ => return Err(PyValueError::new_err("Unsupported correction method")),
    }
    Ok(adjusted)
}

fn t_test_pvalue(sample_a: &[f64], sample_b: &[f64], equal_var: bool) -> Option<f64> {
    if sample_a.len() < 2 || sample_b.len() < 2 {
        return None;
    }
    let n_a = sample_a.len() as f64;
    let n_b = sample_b.len() as f64;
    let mean_a = sample_a.iter().sum::<f64>() / n_a;
    let mean_b = sample_b.iter().sum::<f64>() / n_b;
    let var_a = sample_a.iter().map(|v| (v - mean_a).powi(2)).sum::<f64>() / (n_a - 1.0);
    let var_b = sample_b.iter().map(|v| (v - mean_b).powi(2)).sum::<f64>() / (n_b - 1.0);

    let (t_stat, df) = if equal_var {
        let pooled_den = n_a + n_b - 2.0;
        if pooled_den <= 0.0 {
            return None;
        }
        let pooled = ((n_a - 1.0) * var_a + (n_b - 1.0) * var_b) / pooled_den;
        if !(pooled > 0.0) {
            return None;
        }
        let se = (pooled * (1.0 / n_a + 1.0 / n_b)).sqrt();
        if !(se > 0.0) {
            return None;
        }
        ((mean_a - mean_b) / se, pooled_den)
    } else {
        let term_a = var_a / n_a;
        let term_b = var_b / n_b;
        let se = (term_a + term_b).sqrt();
        if !(se > 0.0) {
            return None;
        }
        let numerator = (term_a + term_b).powi(2);
        let denominator = (term_a.powi(2) / (n_a - 1.0)) + (term_b.powi(2) / (n_b - 1.0));
        if !(denominator > 0.0) {
            return None;
        }
        ((mean_a - mean_b) / se, numerator / denominator)
    };

    let dist = StudentsT::new(0.0, 1.0, df).ok()?;
    Some(2.0 * (1.0 - dist.cdf(t_stat.abs())))
}

fn mann_whitney_pvalue(sample_a: &[f64], sample_b: &[f64]) -> Option<f64> {
    if sample_a.len() < 2 || sample_b.len() < 2 {
        return None;
    }
    let n1 = sample_a.len() as f64;
    let n2 = sample_b.len() as f64;

    let mut pooled: Vec<(f64, bool)> = Vec::with_capacity(sample_a.len() + sample_b.len());
    pooled.extend(sample_a.iter().copied().map(|v| (v, true)));
    pooled.extend(sample_b.iter().copied().map(|v| (v, false)));
    pooled.sort_by(|left, right| left.0.partial_cmp(&right.0).unwrap_or(std::cmp::Ordering::Equal));

    let mut idx = 0usize;
    let mut rank_sum_a = 0.0f64;
    let mut tie_correction_numer = 0.0f64;
    while idx < pooled.len() {
        let start = idx;
        let value = pooled[idx].0;
        while idx < pooled.len() && pooled[idx].0 == value {
            idx += 1;
        }
        let end = idx;
        let tie_count = (end - start) as f64;
        tie_correction_numer += tie_count.powi(3) - tie_count;
        let avg_rank = (start as f64 + 1.0 + end as f64) / 2.0;
        let count_a = pooled[start..end].iter().filter(|(_, is_a)| *is_a).count() as f64;
        rank_sum_a += avg_rank * count_a;
    }

    let u1 = rank_sum_a - (n1 * (n1 + 1.0) / 2.0);
    let mu = n1 * n2 / 2.0;
    let n = n1 + n2;
    if n <= 1.0 {
        return None;
    }
    let tie_term = tie_correction_numer / (n * (n - 1.0));
    let sigma_sq = n1 * n2 / 12.0 * ((n + 1.0) - tie_term);
    if !(sigma_sq > 0.0) {
        return None;
    }
    let sigma = sigma_sq.sqrt();
    let z = ((u1 - mu).abs() - 0.5) / sigma;
    let normal = Normal::new(0.0, 1.0).ok()?;
    Some(2.0 * (1.0 - normal.cdf(z.abs())))
}

#[pyfunction]
#[pyo3(signature = (effect_kernel, groups, level, iterations, seed))]
fn bootstrap_percentile_ci(
    effect_kernel: &str,
    groups: Vec<PyReadonlyArray1<'_, f64>>,
    level: f64,
    iterations: usize,
    seed: u64,
) -> PyResult<Option<(f64, f64)>> {
    if !(0.0 < level && level < 1.0) {
        return Err(PyValueError::new_err("level must be between 0 and 1"));
    }
    let groups: Vec<Vec<f64>> = groups
        .into_iter()
        .map(|group| {
            group
                .as_slice()
                .map_err(|_| PyValueError::new_err("groups must be contiguous float64 arrays"))
                .map(|values| values.to_vec())
        })
        .collect::<PyResult<Vec<Vec<f64>>>>()?;

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
        let sampled_group_refs: Vec<&[f64]> = sampled_groups.iter().map(Vec::as_slice).collect();

        if let Some(estimate) = evaluate_kernel(effect_kernel, &sampled_group_refs) {
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

#[pyfunction]
#[pyo3(signature = (effect_kernel, groups, pairs, level, iterations, seed))]
fn bootstrap_percentile_ci_batch(
    effect_kernel: &str,
    groups: Vec<PyReadonlyArray1<'_, f64>>,
    pairs: Vec<(usize, usize)>,
    level: f64,
    iterations: usize,
    seed: u64,
) -> PyResult<Vec<Option<(f64, f64)>>> {
    if !(0.0 < level && level < 1.0) {
        return Err(PyValueError::new_err("level must be between 0 and 1"));
    }
    let groups: Vec<Vec<f64>> = groups
        .into_iter()
        .map(|group| {
            group
                .as_slice()
                .map_err(|_| PyValueError::new_err("groups must be contiguous float64 arrays"))
                .map(|values| values.to_vec())
        })
        .collect::<PyResult<Vec<Vec<f64>>>>()?;

    if groups.is_empty() {
        return Ok(vec![None; pairs.len()]);
    }

    for &(left, right) in &pairs {
        if left >= groups.len() || right >= groups.len() {
            return Err(PyValueError::new_err("pair index out of range"));
        }
        if left == right {
            return Err(PyValueError::new_err("pair indices must be different"));
        }
    }

    if iterations == 0 || groups.iter().any(|g| g.is_empty()) {
        return Ok(vec![None; pairs.len()]);
    }

    let mut out: Vec<Option<(f64, f64)>> = Vec::with_capacity(pairs.len());
    for &(left, right) in &pairs {
        let pair_groups: [&[f64]; 2] = [groups[left].as_slice(), groups[right].as_slice()];
        let mut rng = StdRng::seed_from_u64(seed);
        let mut estimates: Vec<f64> = Vec::with_capacity(iterations);

        for _ in 0..iterations.max(1) {
            let sampled_groups: Vec<Vec<f64>> = pair_groups
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
            let sampled_group_refs: Vec<&[f64]> = sampled_groups.iter().map(Vec::as_slice).collect();

            if let Some(estimate) = evaluate_kernel(effect_kernel, &sampled_group_refs) {
                if estimate.is_finite() {
                    estimates.push(estimate);
                }
            }
        }

        if estimates.is_empty() {
            out.push(None);
            continue;
        }
        estimates.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let lower_q = ((1.0 - level) / 2.0) * 100.0;
        let upper_q = (1.0 - (1.0 - level) / 2.0) * 100.0;
        out.push(Some((
            percentile_linear(&estimates, lower_q),
            percentile_linear(&estimates, upper_q),
        )));
    }

    Ok(out)
}

#[pyfunction]
#[pyo3(signature = (labels, groups, alpha, correction_method, non_parametric, equal_var))]
fn pairwise_stats(
    py: Python<'_>,
    labels: Vec<String>,
    groups: Vec<PyReadonlyArray1<'_, f64>>,
    alpha: f64,
    correction_method: &str,
    non_parametric: bool,
    equal_var: bool,
) -> PyResult<Vec<PyObject>> {
    let groups: Vec<Vec<f64>> = groups
        .into_iter()
        .map(|group| {
            group
                .as_slice()
                .map_err(|_| PyValueError::new_err("groups must be contiguous float64 arrays"))
                .map(|values| values.to_vec())
        })
        .collect::<PyResult<Vec<Vec<f64>>>>()?;

    if labels.len() != groups.len() {
        return Err(PyValueError::new_err("labels and groups must have equal length"));
    }

    let mut rows: Vec<(String, String, String, Option<f64>, Option<f64>)> = Vec::new();
    let mut raw_p_values: Vec<Option<f64>> = Vec::new();
    for left in 0..labels.len() {
        for right in (left + 1)..labels.len() {
            let sample_a = groups[left].as_slice();
            let sample_b = groups[right].as_slice();
            let (test_used, p_value) = if non_parametric {
                ("Mann-Whitney U".to_string(), mann_whitney_pvalue(sample_a, sample_b))
            } else if equal_var {
                ("Student t-test".to_string(), t_test_pvalue(sample_a, sample_b, true))
            } else {
                ("Welch t-test".to_string(), t_test_pvalue(sample_a, sample_b, false))
            };
            let effect_size = if non_parametric {
                cliffs_delta(sample_a, sample_b)
            } else {
                cohen_d(sample_a, sample_b)
            };
            rows.push((
                labels[left].clone(),
                labels[right].clone(),
                test_used,
                p_value,
                effect_size,
            ));
            raw_p_values.push(p_value);
        }
    }

    let adjusted = adjust_pvalues(&raw_p_values, correction_method)?;
    let mut out: Vec<PyObject> = Vec::with_capacity(rows.len());
    for (idx, row) in rows.iter().enumerate() {
        let dict = PyDict::new_bound(py);
        dict.set_item("group_a", &row.0)?;
        dict.set_item("group_b", &row.1)?;
        dict.set_item("test_used", &row.2)?;
        dict.set_item("p_value", row.3)?;
        dict.set_item("effect_size", row.4)?;
        dict.set_item("adjusted_p_value", adjusted[idx])?;
        let significant = adjusted[idx].is_some_and(|p| p < alpha);
        dict.set_item("significant", significant)?;
        out.push(dict.into_any().unbind());
    }
    Ok(out)
}

#[pymodule]
fn _metroliza_comparison_stats_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(bootstrap_percentile_ci, m)?)?;
    m.add_function(wrap_pyfunction!(bootstrap_percentile_ci_batch, m)?)?;
    m.add_function(wrap_pyfunction!(pairwise_stats, m)?)?;
    Ok(())
}
