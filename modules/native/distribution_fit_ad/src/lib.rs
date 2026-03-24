use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::SeedableRng;
use rand_distr::{Distribution, Gamma, Normal, Weibull};
use rayon::prelude::*;
use statrs::distribution::{ContinuousCDF, Normal as StatNormal};

const EPS: f64 = 1e-12;

#[derive(Clone, Debug)]
enum SupportedDistribution {
    Norm { loc: f64, scale: f64 },
    HalfNorm { loc: f64, scale: f64 },
    FoldNorm { c: f64, loc: f64, scale: f64 },
    Gamma { shape: f64, loc: f64, scale: f64 },
    WeibullMin { shape: f64, loc: f64, scale: f64 },
    LogNorm { sigma: f64, loc: f64, scale: f64 },
    JohnsonSu { gamma: f64, delta: f64, loc: f64, scale: f64 },
}

impl SupportedDistribution {
    fn from_name_and_params(name: &str, params: &[f64]) -> Option<Self> {
        match name {
            "norm" if params.len() == 2 => Some(Self::Norm {
                loc: params[0],
                scale: params[1],
            }),
            "halfnorm" if params.len() == 2 => Some(Self::HalfNorm {
                loc: params[0],
                scale: params[1],
            }),
            "foldnorm" if params.len() == 3 => Some(Self::FoldNorm {
                c: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "gamma" if params.len() == 3 => Some(Self::Gamma {
                shape: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "weibull_min" if params.len() == 3 => Some(Self::WeibullMin {
                shape: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "lognorm" if params.len() == 3 => Some(Self::LogNorm {
                sigma: params[0],
                loc: params[1],
                scale: params[2],
            }),
            "johnsonsu" if params.len() == 4 => Some(Self::JohnsonSu {
                gamma: params[0],
                delta: params[1],
                loc: params[2],
                scale: params[3],
            }),
            _ => None,
        }
    }

    fn params_valid(&self) -> bool {
        match self {
            Self::Norm { scale, .. } | Self::HalfNorm { scale, .. } => *scale > 0.0,
            Self::FoldNorm { c, scale, .. } => c.is_finite() && *scale > 0.0,
            Self::Gamma { shape, scale, .. } => *shape > 0.0 && *scale > 0.0,
            Self::WeibullMin { shape, scale, .. } => *shape > 0.0 && *scale > 0.0,
            Self::LogNorm { sigma, scale, .. } => *sigma > 0.0 && *scale > 0.0,
            Self::JohnsonSu { delta, scale, .. } => *delta > 0.0 && *scale > 0.0,
        }
    }

    fn sample_one(&self, rng: &mut rand::rngs::StdRng) -> Option<f64> {
        match self {
            Self::Norm { loc, scale } => {
                let d = Normal::new(*loc, *scale).ok()?;
                Some(d.sample(rng))
            }
            Self::HalfNorm { loc, scale } => {
                let d = Normal::new(0.0, *scale).ok()?;
                Some(loc + d.sample(rng).abs())
            }
            Self::FoldNorm { c, loc, scale } => {
                let d = Normal::new(c * scale, *scale).ok()?;
                Some(loc + d.sample(rng).abs())
            }
            Self::Gamma { shape, loc, scale } => {
                let d = Gamma::new(*shape, *scale).ok()?;
                Some(loc + d.sample(rng))
            }
            Self::WeibullMin { shape, loc, scale } => {
                let d = Weibull::new(*scale, *shape).ok()?;
                Some(loc + d.sample(rng))
            }
            Self::LogNorm { sigma, loc, scale } => {
                let mu = scale.ln();
                let d = Normal::new(mu, *sigma).ok()?;
                Some(loc + d.sample(rng).exp())
            }
            Self::JohnsonSu {
                gamma,
                delta,
                loc,
                scale,
            } => {
                let d = Normal::new(0.0, 1.0).ok()?;
                let z = d.sample(rng);
                let x = ((z - gamma) / delta).sinh();
                Some(loc + scale * x)
            }
        }
    }

    fn cdf(&self, x: f64) -> f64 {
        match self {
            Self::Norm { loc, scale } => {
                let d = StatNormal::new(*loc, *scale).unwrap();
                d.cdf(x)
            }
            Self::HalfNorm { loc, scale } => {
                if x <= *loc {
                    return 0.0;
                }
                let z = (x - loc) / scale;
                let standard = StatNormal::new(0.0, 1.0).unwrap();
                (2.0 * standard.cdf(z) - 1.0).clamp(0.0, 1.0)
            }
            Self::FoldNorm { c, loc, scale } => {
                if x <= *loc {
                    return 0.0;
                }
                let z = (x - loc) / scale;
                let standard = StatNormal::new(0.0, 1.0).unwrap();
                (standard.cdf(z - c) - standard.cdf(-z - c)).clamp(0.0, 1.0)
            }
            Self::Gamma { shape, loc, scale } => {
                if x <= *loc {
                    return 0.0;
                }
                let shifted = (x - loc) / scale;
                let d = statrs::distribution::Gamma::new(*shape, 1.0).unwrap();
                d.cdf(shifted)
            }
            Self::WeibullMin { shape, loc, scale } => {
                if x <= *loc {
                    return 0.0;
                }
                let shifted = (x - loc) / scale;
                let d = statrs::distribution::Weibull::new(*shape, 1.0).unwrap();
                d.cdf(shifted)
            }
            Self::LogNorm { sigma, loc, scale } => {
                if x <= *loc {
                    return 0.0;
                }
                let shifted = (x - loc) / scale;
                if shifted <= 0.0 {
                    return 0.0;
                }
                let d = statrs::distribution::LogNormal::new(0.0, *sigma).unwrap();
                d.cdf(shifted)
            }
            Self::JohnsonSu {
                gamma,
                delta,
                loc,
                scale,
            } => {
                let y = (x - loc) / scale;
                let transformed = gamma + delta * y.asinh();
                let standard = StatNormal::new(0.0, 1.0).unwrap();
                standard.cdf(transformed)
            }
        }
    }
}

fn ad_statistic(sample: &mut [f64], dist: &SupportedDistribution) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    sample.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = sample.len() as f64;
    let mut sum = 0.0;
    for (i, value) in sample.iter().enumerate() {
        let idx = (i + 1) as f64;
        let p = dist.cdf(*value).clamp(EPS, 1.0 - EPS);
        let rp = (1.0 - dist.cdf(sample[sample.len() - 1 - i])).clamp(EPS, 1.0);
        sum += (2.0 * idx - 1.0) * (p.ln() + rp.ln());
    }
    Some(-n - (sum / n))
}

fn ks_statistic(sample: &[f64], dist: &SupportedDistribution) -> Option<f64> {
    if sample.is_empty() {
        return None;
    }
    let mut sorted = sample.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = sorted.len() as f64;
    let mut d_plus = 0.0_f64;
    let mut d_minus = 0.0_f64;

    for (i, value) in sorted.iter().enumerate() {
        let rank = (i + 1) as f64;
        let cdf = dist.cdf(*value).clamp(0.0, 1.0);
        let plus = rank / n - cdf;
        let minus = cdf - (rank - 1.0) / n;
        if plus > d_plus {
            d_plus = plus;
        }
        if minus > d_minus {
            d_minus = minus;
        }
    }
    Some(d_plus.max(d_minus))
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9E37_79B9_7F4A_7C15);
    value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    value ^ (value >> 31)
}

fn iteration_seed(base_seed: u64, iteration_index: usize) -> u64 {
    splitmix64(base_seed ^ (iteration_index as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15))
}

fn run_ad_monte_carlo(
    dist: &SupportedDistribution,
    sample_size: usize,
    observed_stat: f64,
    iterations: usize,
    resolved_seed: u64,
) -> (Option<f64>, usize) {
    let (exceed_count, valid_trials) = (0..iterations)
        .into_par_iter()
        .map(|iteration_index| {
            let mut rng = rand::rngs::StdRng::seed_from_u64(iteration_seed(resolved_seed, iteration_index));
            let mut simulated = Vec::with_capacity(sample_size);

            for _ in 0..sample_size {
                match dist.sample_one(&mut rng) {
                    Some(value) if value.is_finite() => simulated.push(value),
                    _ => return (0usize, 0usize),
                }
            }

            let stat = match ad_statistic(&mut simulated, dist) {
                Some(value) if value.is_finite() => value,
                _ => return (0usize, 0usize),
            };

            if stat >= observed_stat {
                (1usize, 1usize)
            } else {
                (0usize, 1usize)
            }
        })
        .reduce(|| (0usize, 0usize), |left, right| (left.0 + right.0, left.1 + right.1));

    if valid_trials == 0 {
        return (None, 0);
    }
    let p_value = (exceed_count as f64 + 1.0) / (valid_trials as f64 + 1.0);
    (Some(p_value), valid_trials)
}

#[pyfunction]
#[pyo3(signature = (distribution, fitted_params, sample_values))]
fn compute_ad_ks_statistics(
    py: Python<'_>,
    distribution: &str,
    fitted_params: Vec<f64>,
    sample_values: Vec<f64>,
) -> PyResult<(f64, f64)> {
    let dist = SupportedDistribution::from_name_and_params(distribution, &fitted_params)
        .ok_or_else(|| PyValueError::new_err("Unsupported distribution identifier or invalid parameter count"))?;

    if !dist.params_valid() {
        return Err(PyValueError::new_err("Invalid distribution parameters"));
    }

    if sample_values.is_empty() {
        return Err(PyValueError::new_err("sample_values must not be empty"));
    }

    if sample_values.iter().any(|v| !v.is_finite()) {
        return Err(PyValueError::new_err("sample_values must be finite"));
    }

    py.allow_threads(|| {
        let mut ad_sample = sample_values.clone();
        let ad = ad_statistic(&mut ad_sample, &dist)
            .ok_or_else(|| PyValueError::new_err("Unable to compute Anderson-Darling statistic"))?;
        let ks = ks_statistic(&sample_values, &dist)
            .ok_or_else(|| PyValueError::new_err("Unable to compute Kolmogorov-Smirnov statistic"))?;
        Ok((ad, ks))
    })
}

#[pyfunction]
#[pyo3(signature = (distribution, fitted_params, sample_size, observed_stat, iterations, seed=None))]
fn estimate_ad_pvalue_monte_carlo(
    py: Python<'_>,
    distribution: &str,
    fitted_params: Vec<f64>,
    sample_size: usize,
    observed_stat: f64,
    iterations: usize,
    seed: Option<u64>,
) -> PyResult<(Option<f64>, usize)> {
    if iterations == 0 {
        return Ok((None, 0));
    }
    if sample_size == 0 {
        return Ok((None, 0));
    }

    let dist = SupportedDistribution::from_name_and_params(distribution, &fitted_params)
        .ok_or_else(|| PyValueError::new_err("Unsupported distribution identifier or invalid parameter count"))?;

    if !dist.params_valid() {
        return Ok((None, 0));
    }

    let resolved_seed = seed.unwrap_or_else(rand::random::<u64>);
    let result = py.allow_threads(|| {
        run_ad_monte_carlo(
            &dist,
            sample_size,
            observed_stat,
            iterations,
            resolved_seed,
        )
    });
    Ok(result)
}

#[pymodule]
fn _metroliza_distribution_fit_native(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_ad_ks_statistics, m)?)?;
    m.add_function(wrap_pyfunction!(estimate_ad_pvalue_monte_carlo, m)?)?;
    Ok(())
}
